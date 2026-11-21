"""The portrait renderer's per-process debug logs do not pile up in the data scratch.

0.9.0 smoke test: 195 csp_debug_<pid>.log (one-shot renders) and 211 csp_server_<pid>.log
(pool workers) had collected since 09-10; nothing removed them. A clean render now deletes
its log, a failed one keeps it, and the backend's start sweeps old ones (processor/csp_logs.py).

The renderer is stood in for by a small Python child that writes its log the way HSDRawViewer
does: <temp>/csp_<kind>_<own pid>.log, held open while it runs.
"""
import os
import subprocess
import sys
import time
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

import csp_logs
import generate_csp
from shared.rendering import csp_pool

# The venv's python.exe on Windows is a launcher that runs the base interpreter as a CHILD,
# so its pid is not the one Popen reports. HSDRawViewer.exe is no launcher; the base
# interpreter stands in for it faithfully.
PYTHON = getattr(sys, '_base_executable', None) or sys.executable

_TEMP = "os.environ['TMP'] if os.name == 'nt' else os.environ['TMPDIR']"

ONE_SHOT = f'''
import os, sys
log = open(os.path.join({_TEMP}, 'csp_debug_%d.log' % os.getpid()), 'w')
log.write('Main called\\n'); log.flush()
output, write, code = sys.argv[1], sys.argv[2] == 'write', int(sys.argv[3])
if write:
    open(output, 'wb').write(b'portrait')
print('rendered')
sys.exit(code)
'''

SERVER = f'''
import os, sys
log = open(os.path.join({_TEMP}, 'csp_server_%d.log' % os.getpid()), 'w')
print('READY', flush=True)
while True:
    line = sys.stdin.readline()
    if not line or line.strip() == 'QUIT':
        break
    args = line.rstrip('\\n').split('\\t')
    log.write(line); log.flush()
    if 'bad' in args[1]:
        print('ERR\\t' + args[2], flush=True)
    else:
        open(args[2], 'wb').write(b'portrait')
        print('DONE\\t' + args[2], flush=True)
'''


@pytest.fixture
def temp(tmp_path, monkeypatch):
    """The renderer's temp folder (in the app: the data scratch), private to the test."""
    folder = tmp_path / 'scratch'
    folder.mkdir()
    for key in ('TMP', 'TEMP', 'TMPDIR'):
        monkeypatch.setenv(key, str(folder))
    return folder


def _logs(folder, prefix):
    return sorted(p.name for p in folder.glob(prefix + '*.log'))


# --- one-shot --csp renders (generate_csp) -------------------------------------------------

def _one_shot(tmp_path, write, code):
    output = tmp_path / 'out.png'
    cmd = [PYTHON, '-c', ONE_SHOT, str(output), 'write' if write else 'skip', str(code)]
    return generate_csp._run_render_process(cmd, str(tmp_path), str(output)), output


def test_clean_one_shot_render_deletes_its_log(temp, tmp_path):
    result, output = _one_shot(tmp_path, write=True, code=0)
    assert result.returncode == 0 and 'rendered' in result.stdout
    assert output.is_file()
    assert _logs(temp, csp_logs.DEBUG) == []


@pytest.mark.parametrize('write, code', [(False, 4), (False, 0), (True, 3)],
                         ids=['crashed', 'exit-0-without-png', 'nonzero-with-png'])
def test_failed_one_shot_render_keeps_its_log_and_says_where(temp, tmp_path, monkeypatch, write, code):
    said = []
    monkeypatch.setattr(generate_csp, 'logger', SimpleNamespace(warning=said.append))
    result, _ = _one_shot(tmp_path, write=write, code=code)
    assert result.returncode == code
    kept = _logs(temp, csp_logs.DEBUG)
    assert len(kept) == 1
    assert said and kept[0] in said[0]


def test_head_shot_and_portrait_both_render_through_the_log_handling():
    """Both one-shot --csp launchers in generate_csp go through _run_render_process."""
    import inspect
    source = inspect.getsource(generate_csp)
    assert source.count('_run_render_process(') == 3   # the definition and two callers
    assert 'subprocess.run(cmd' not in source


# --- --csp-server pool workers (csp_pool) --------------------------------------------------

@pytest.fixture
def fake_server(monkeypatch):
    real_popen = subprocess.Popen

    def popen(argv, **kwargs):
        assert argv[1:] == ['--csp-server']
        return real_popen([PYTHON, '-c', SERVER], **kwargs)

    monkeypatch.setattr(csp_pool.subprocess, 'Popen', popen)
    monkeypatch.setattr(csp_pool, 'own', lambda child: child)
    monkeypatch.setattr(csp_pool, 'staggered_launch', lambda **_: nullcontext())
    monkeypatch.setattr(csp_pool, '_output_looks_blank', lambda _: False)


def _job(tmp_path, name):
    return ['--csp', str(tmp_path / f'{name}.dat'), str(tmp_path / f'{name}.png')]


def test_worker_whose_jobs_all_rendered_deletes_its_log_when_it_quits(temp, tmp_path, fake_server):
    with csp_pool.CspRenderPool('HSDRawViewer.exe', workers=1) as pool:
        assert pool.render(_job(tmp_path, 'one'))
        assert pool.render(_job(tmp_path, 'two'))
        assert len(_logs(temp, csp_logs.SERVER)) == 1   # held while the worker runs
    assert _logs(temp, csp_logs.SERVER) == []


def test_worker_with_a_failed_job_keeps_its_log(temp, tmp_path, fake_server):
    with csp_pool.CspRenderPool('HSDRawViewer.exe', workers=1) as pool:
        assert pool.render(_job(tmp_path, 'good'))
        assert not pool.render(_job(tmp_path, 'bad'))
        assert pool.render(_job(tmp_path, 'good-again'))
    kept = _logs(temp, csp_logs.SERVER)
    assert len(kept) == 1
    assert 'bad.dat' in (temp / kept[0]).read_text()


def test_recycled_worker_drops_the_clean_log_and_starts_a_new_one(temp, tmp_path, fake_server):
    with csp_pool.CspRenderPool('HSDRawViewer.exe', workers=1, recycle_after=1) as pool:
        assert pool.render(_job(tmp_path, 'one'))   # recycled after this job
        assert _logs(temp, csp_logs.SERVER) == []
        assert pool.render(_job(tmp_path, 'two'))
    assert _logs(temp, csp_logs.SERVER) == []


def test_blank_output_counts_as_a_failed_job(temp, tmp_path, fake_server, monkeypatch):
    monkeypatch.setattr(csp_pool, '_output_looks_blank', lambda _: True)
    with csp_pool.CspRenderPool('HSDRawViewer.exe', workers=1) as pool:
        assert not pool.render(_job(tmp_path, 'blank'))   # recycles the worker
    assert len(_logs(temp, csp_logs.SERVER)) == 1


def test_log_of_a_worker_still_running_is_left_for_the_sweep(tmp_path):
    log = tmp_path / 'csp_server_77.log'
    log.write_text('x')
    worker = csp_pool._Worker('HSDRawViewer.exe', 0, lazy=True)
    worker.proc = SimpleNamespace(pid=77, poll=lambda: None)
    worker.log_dir = tmp_path
    worker._drop_log()
    assert log.exists() and worker.log_dir == tmp_path


# --- the start sweep (csp_logs.sweep) -------------------------------------------------------

def _age(path, days, now):
    stamp = now - days * 86400
    os.utime(path, (stamp, stamp))


def test_sweep_removes_logs_past_the_age_limit_and_nothing_else(tmp_path):
    now = time.time()
    old = [tmp_path / 'csp_debug_101.log', tmp_path / 'csp_server_102.log']
    recent = [tmp_path / 'csp_debug_201.log', tmp_path / 'csp_server_202.log']
    others = [tmp_path / name for name in ('csp_debug_abc.log', 'csp_server_9.txt', 'other.log',
                                           'csp_lookup_index', 'viewer_checkpoint_1')]
    for path in old + recent + others:
        path.write_text('x')
        _age(path, 30 if path in old or path in others else 1, now)
    assert csp_logs.sweep(tmp_path, now=now) == 2
    assert not any(p.exists() for p in old)
    assert all(p.exists() for p in recent + others)


def test_sweep_keeps_only_the_newest_beyond_the_count_cap(tmp_path):
    now = time.time()
    for n in range(6):
        path = tmp_path / f'csp_debug_{300 + n}.log'
        path.write_text('x')
        _age(path, n / 24, now)   # 300 newest ... 305 oldest, all within the age limit
    assert csp_logs.sweep(tmp_path, keep=2, now=now) == 4
    assert _logs(tmp_path, csp_logs.DEBUG) == ['csp_debug_300.log', 'csp_debug_301.log']


def test_sweep_never_deletes_a_log_a_running_renderer_holds(tmp_path):
    # Named for a live pid (POSIX skips it) and held open (Windows refuses the delete).
    now = time.time()
    held = tmp_path / f'csp_server_{os.getpid()}.log'
    held.write_text('x')
    _age(held, 30, now)   # before opening: Windows will not touch a held file's times either
    with open(held, 'a'):
        assert csp_logs.sweep(tmp_path, now=now) == 0
        assert held.exists()


def test_sweep_of_a_missing_folder_is_a_no_op(tmp_path):
    assert csp_logs.sweep(tmp_path / 'missing') == 0


@pytest.mark.skipif(os.name != 'nt', reason='Windows temp-path rule')
def test_temp_dir_follows_the_windows_rule():
    assert str(csp_logs.temp_dir({'TMP': r'E:\a', 'TEMP': r'E:\b'})) == r'E:\a'
    assert str(csp_logs.temp_dir({'TEMP': r'E:\b', 'USERPROFILE': r'C:\u'})) == r'E:\b'
    assert str(csp_logs.temp_dir({'USERPROFILE': r'C:\u'})) == r'C:\u'


@pytest.mark.skipif(os.name == 'nt', reason='POSIX temp-path rule')
def test_temp_dir_follows_the_posix_rule():
    assert str(csp_logs.temp_dir({'TMPDIR': '/x', 'TMP': '/y'})) == '/x'
    assert str(csp_logs.temp_dir({})) == '/tmp'
