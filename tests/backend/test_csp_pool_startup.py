"""Pool startup must not hold completed previews behind unrelated GL starts."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from shared.rendering import csp_pool, csp_concurrency


@pytest.fixture
def fake_native(monkeypatch):
    starts = []
    monkeypatch.setattr(csp_pool, 'staggered_launch', lambda **_: nullcontext())
    monkeypatch.setattr(csp_pool, '_output_looks_blank', lambda _: False)

    def spawn(worker):
        starts.append(worker.idx)
        worker.ready = True

    def render(worker, args, timeout):
        if not worker.alive():
            worker._spawn()
        worker.jobs += 1
        return True

    monkeypatch.setattr(csp_pool._Worker, '_spawn', spawn)
    monkeypatch.setattr(csp_pool._Worker, 'alive', lambda w: getattr(w, 'ready', False))
    monkeypatch.setattr(csp_pool._Worker, 'close', lambda w, asked=False: setattr(w, 'ready', False))
    monkeypatch.setattr(csp_pool._Worker, 'render', render)
    return starts


def test_unused_pool_never_launches_native_processes(fake_native):
    with csp_pool.CspRenderPool('fake', workers=12):
        assert fake_native == []
    assert fake_native == []


def test_sequential_jobs_reuse_one_warm_worker(fake_native):
    with csp_pool.CspRenderPool('fake', workers=12) as pool:
        for _ in range(8):
            assert pool.render(['--csp', 'in.dat', 'out.png'])
    assert len(fake_native) == 1


def test_ready_worker_finishes_while_other_worker_is_still_starting(fake_native, monkeypatch):
    starting = threading.Event()
    release = threading.Event()
    original_spawn = csp_pool._Worker._spawn

    def spawn(worker):
        if not starting.is_set():
            starting.set()
            assert release.wait(3)
        original_spawn(worker)

    monkeypatch.setattr(csp_pool._Worker, '_spawn', spawn)
    with csp_pool.CspRenderPool('fake', workers=2) as pool:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(pool.render, ['--csp', 'slow.dat', 'slow.png'])
            try:
                assert starting.wait(1)
                second = executor.submit(pool.render, ['--csp', 'fast.dat', 'fast.png'])
                assert second.result(timeout=1) is True
                assert not first.done()
            finally:
                release.set()
            assert first.result(timeout=1) is True


def test_recycling_does_not_start_an_unused_replacement(fake_native):
    with csp_pool.CspRenderPool('fake', workers=1, recycle_after=1) as pool:
        assert pool.render(['--csp', 'in.dat', 'out.png'])
        assert len(fake_native) == 1
        assert pool.render(['--csp', 'in2.dat', 'out2.png'])
        assert len(fake_native) == 2


def test_failed_start_returns_fallback_without_retrying_in_same_job(monkeypatch):
    starts = []

    def fail(worker):
        starts.append(worker.idx)
        raise RuntimeError('driver failed')

    monkeypatch.setattr(csp_pool._Worker, '_spawn', fail)
    with csp_pool.CspRenderPool('fake', workers=2) as pool:
        assert pool.render(['--csp', 'in.dat', 'out.png']) is False
    assert len(starts) == 1


def test_actual_worker_launches_keep_the_stagger_with_pool_installed(monkeypatch):
    sleeps = []
    monkeypatch.setattr(csp_concurrency, '_csp_pool_active', lambda: True)
    monkeypatch.setattr(csp_concurrency.time, 'sleep', sleeps.append)
    monkeypatch.setattr(csp_concurrency, 'CSP_LAUNCH_STAGGER_S', 1.5)
    with csp_concurrency.staggered_launch():
        pass
    assert sleeps == []
    with csp_concurrency.staggered_launch(force=True):
        pass
    assert sleeps == [1.5]


@pytest.mark.parametrize('cpus, expected', [(1, 1), (2, 2), (12, 4)])
def test_preview_worker_limit_respects_cpu_count(monkeypatch, cpus, expected):
    monkeypatch.delenv('MEX_CSP_PARALLELISM', raising=False)
    monkeypatch.setattr(csp_concurrency.os, 'cpu_count', lambda: cpus)
    assert csp_concurrency.csp_workers(default_limit=4) == expected
    assert csp_concurrency.csp_workers() == cpus


def test_explicit_parallelism_override_is_preserved(monkeypatch):
    monkeypatch.setenv('MEX_CSP_PARALLELISM', '8')
    assert csp_concurrency.csp_workers(default_limit=4) == 8


@pytest.mark.parametrize('character, pooled_attempts', [('Marth', 1), ('Fox', 0)])
def test_oneshot_fallback_and_fox_bypass_observe_startup_spacing(monkeypatch, tmp_path, character, pooled_attempts):
    import generate_csp

    dat = tmp_path / 'costume.dat'
    dat.write_bytes(b'test costume')
    attempts = []
    pool = SimpleNamespace(render=lambda args: attempts.append(args) or False)
    monkeypatch.setattr(generate_csp, '_active_pool', pool)
    monkeypatch.setattr(generate_csp, 'normalized_render_dat', lambda path, _: (path, None))
    monkeypatch.setattr(generate_csp, 'model_is_replacement', lambda *_: False)
    monkeypatch.setattr(generate_csp, 'low_poly_dobjs', lambda *_: None)
    monkeypatch.setattr(generate_csp, 'skeleton_is_deformed', lambda *_: False)
    monkeypatch.setattr(generate_csp, '_fox_gun_args', lambda: ['--gun', 'PlFx.dat'])
    guarded = []

    @contextmanager
    def launch(*, force=False):
        assert force is True
        guarded.append(True)
        try:
            yield
        finally:
            guarded.pop()

    def run(cmd, cwd):
        assert guarded == [True]
        Path(cmd[cmd.index('--csp') + 2]).write_bytes(b'rendered portrait')
        return SimpleNamespace(returncode=0), 4242

    for key in ('TMP', 'TEMP', 'TMPDIR'):   # the renderer-log cleanup stays in tmp_path
        monkeypatch.setenv(key, str(tmp_path))
    monkeypatch.setattr(csp_concurrency, 'staggered_launch', launch)
    monkeypatch.setattr(generate_csp, '_spawn_renderer', run)
    output = generate_csp.generate_single_csp_internal(str(dat), character, costume_slot=0)
    assert output and Path(output).read_bytes() == b'rendered portrait'
    assert len(attempts) == pooled_attempts


def test_close_asks_every_worker_to_quit_before_waiting_on_any(monkeypatch):
    """The workers shut down together: each QUIT is sent before the first wait (a wait is up to 3 s each)."""
    events = []
    monkeypatch.setattr(csp_pool._Worker, 'quit', lambda w: events.append(('quit', w.idx)) or True)
    monkeypatch.setattr(csp_pool._Worker, 'close', lambda w, asked=False: events.append(('wait', w.idx, asked)))
    csp_pool.CspRenderPool('HSDRawViewer.exe', workers=3).close()
    assert events == [('quit', 0), ('quit', 1), ('quit', 2), ('wait', 0, True), ('wait', 1, True), ('wait', 2, True)]
