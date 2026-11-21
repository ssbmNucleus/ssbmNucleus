"""The pristine test base: built once per (vanilla ISO, MexCLI), copied for every
test, never reused half-built. A fake stands in for `mexcli create`; no ISO,
no MexCLI and no game files are involved."""
import io
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

import projects.install.pristine_base as pristine
import projects.install.test_build as builds
from mexcli.project import MexExportCancelled

WAIT = 10.0


class FakeCreate:
    """`mexcli create <iso> <out> <name>` on a thread: writes files/ first, then
    (once its gate opens) project.mexproj, like the real one finishing last.
    fail='exit' exits 1 with an error; fail='json' writes everything and exits
    0 but its final JSON says success false."""

    def __init__(self, argv, *, gate=None, fail=False):
        self.argv = argv
        self.out = Path(argv[3])
        self.gate = gate
        self.fail = fail
        self.returncode = None
        self.terminated = False
        self.started = threading.Event()
        self._killed = threading.Event()
        self.stdout = io.StringIO('{\n  "success": false,\n  "error": "synthetic failure"\n}\n'
                                  if fail else '{\n  "status": "complete"\n}\n')
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        (self.out / 'files' / 'audio').mkdir(parents=True)
        (self.out / 'files' / 'PlFxNr.dat').write_bytes(b'vanilla fox ' * 100)
        (self.out / 'files' / 'audio' / 'main.ssm').write_bytes(b'vanilla audio')
        (self.out / 'sys').mkdir()
        (self.out / 'sys' / 'main.dol').write_bytes(b'vanilla dol')
        self.started.set()
        while self.gate is not None and not self.gate.is_set():
            if self._killed.wait(0.01):
                self.returncode = 1
                return
        if self._killed.is_set() or self.fail == 'exit':
            self.returncode = 1
            return
        (self.out / 'project.mexproj').write_text('{"build": {"name": "NucleusTest"}}')
        self.returncode = 0

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise subprocess.TimeoutExpired(self.argv, timeout)
        return self.returncode

    def terminate(self):
        self.terminated = True
        self._killed.set()

    kill = terminate


@pytest.fixture
def lab(tmp_path, monkeypatch):
    builds_dir = tmp_path / 'test-builds'
    root = builds_dir / 'pristine-base'
    mex = tmp_path / 'mex'
    mex.mkdir()
    (mex / 'mexcli.exe').write_bytes(b'synthetic mexcli v1')
    (mex / 'codes.gct').write_bytes(b'synthetic codes v1')
    iso = tmp_path / 'vanilla.iso'
    iso.write_bytes(b'GALE01' + b'\0' * 4096)
    monkeypatch.setattr(builds, 'TEST_BUILD_DIR', builds_dir)
    monkeypatch.setattr(builds, 'PRISTINE_BASE_DIR', root)
    monkeypatch.setattr(builds, 'MEXCLI_PATH', mex / 'mexcli.exe')
    lab = type('Lab', (), {})()
    lab.root, lab.builds, lab.iso, lab.mex = root, builds_dir, iso, mex
    lab.creates, lab.gate, lab.fail = [], None, None

    def spawn(argv, cwd):
        proc = FakeCreate(argv, gate=lab.gate, fail=lab.fail)
        lab.creates.append(proc)
        return proc

    monkeypatch.setattr(pristine, '_spawn', spawn)
    return lab


def bases(lab):
    return sorted(p.name for p in lab.root.iterdir() if p.name.startswith('base-'))


def leftovers(lab):
    return sorted(p.name for p in lab.root.iterdir() if not p.name.startswith('base-'))


def projects(lab):
    return sorted(p.name for p in lab.builds.iterdir() if p.name.startswith('proj_'))


def wait_for(predicate, what):
    deadline = time.monotonic() + WAIT
    while not predicate():
        assert time.monotonic() < deadline, f'timed out waiting for {what}'
        time.sleep(0.01)


def test_base_is_built_once_and_every_test_gets_its_own_copy(lab):
    seen = []
    first, first_proj = builds.create_temp_project(str(lab.iso), progress_cb=lambda p, m: seen.append((p, m)))
    second, second_proj = builds.create_temp_project(str(lab.iso))

    assert len(lab.creates) == 1
    assert first != second and first_proj.is_file() and second_proj.is_file()
    [base] = bases(lab)
    base = lab.root / base
    copied = sorted(str(p.relative_to(first)) for p in first.rglob('*') if p.is_file())
    original = sorted(str(p.relative_to(base)) for p in base.rglob('*') if p.is_file()
                      if p.name != pristine.RECORD)
    assert copied == original and pristine.RECORD not in copied

    # A test writes into its copy (an import, the DAS loader, main.dol): the base
    # and the next test's copy must not see it. A hard link would leak it.
    (first / 'sys' / 'main.dol').write_bytes(b'patched by a test')
    (first / 'files' / 'PlFxNr.dat').write_bytes(b'imported costume')
    assert (base / 'sys' / 'main.dol').read_bytes() == b'vanilla dol'
    assert (second / 'files' / 'PlFxNr.dat').read_bytes() == b'vanilla fox ' * 100

    # The first build showed the one-time message, then the copy, on a rising bar.
    messages = [m for _p, m in seen]
    assert any(m.startswith(pristine.BUILD_MESSAGE) and m.endswith('s') for m in messages)
    assert messages[-1] == 'Copying the test base… 100%'
    percentages = [p for p, _m in seen]
    assert percentages == sorted(percentages)
    low, high = builds.BAR_BASE
    assert all(low <= p <= high for p, m in seen if m.startswith(pristine.BUILD_MESSAGE))
    low, high = builds.BAR_COPY
    assert all(low <= p <= high for p, m in seen if m.startswith('Copying'))


def test_a_new_iso_or_mexcli_rebuilds_and_drops_the_old_base(lab):
    builds.create_temp_project(str(lab.iso))
    [old] = bases(lab)

    lab.iso.write_bytes(b'GALE01' + b'\1' * 4096)        # another ISO at the same path
    builds.create_temp_project(str(lab.iso))
    assert len(lab.creates) == 2
    [new] = bases(lab)
    assert new != old and not leftovers(lab)
    record = json.loads((lab.root / new / pristine.RECORD).read_text())
    assert record['iso'] == pristine.iso_identity(lab.iso)

    (lab.mex / 'codes.gct').write_bytes(b'synthetic codes v2')   # a MexCLI update
    builds.create_temp_project(str(lab.iso))
    assert len(lab.creates) == 3
    assert bases(lab) != [new] and len(bases(lab)) == 1

    (lab.mex / 'seed_codes.ini').write_bytes(b'[codes] shipped beside mexcli')
    builds.create_temp_project(str(lab.iso))
    assert len(lab.creates) == 4

    builds.create_temp_project(str(lab.iso))                  # and then it is reused
    assert len(lab.creates) == 4


def test_interrupted_and_unrecorded_bases_are_never_used(lab):
    key, _identity = pristine.base_key(lab.iso, lab.mex / 'mexcli.exe')
    # A build that died after create wrote everything but before the rename...
    crashed = lab.root / '.building-0123456789ab'
    (crashed / 'files').mkdir(parents=True)
    (crashed / 'project.mexproj').write_text('{}')
    # ...and a base folder at the right name with no record (or a wrong one).
    unrecorded = lab.root / f'base-{key}'
    (unrecorded / 'files').mkdir(parents=True)
    (unrecorded / 'project.mexproj').write_text('{}')
    (unrecorded / 'files' / 'half.dat').write_bytes(b'half-written')

    proj_dir, _proj = builds.create_temp_project(str(lab.iso))
    assert len(lab.creates) == 1, 'nothing half-built may stand in for a base'
    assert not (proj_dir / 'files' / 'half.dat').exists()
    assert bases(lab) == [f'base-{key}'] and not leftovers(lab)

    (lab.root / f'base-{key}' / pristine.RECORD).write_text(json.dumps({'key': 'someone-else'}))
    builds.create_temp_project(str(lab.iso))
    assert len(lab.creates) == 2

    # Leftovers beside a good base (an app exit mid-build) go on its next use.
    (lab.root / '.building-feedfacecafe' / 'files').mkdir(parents=True)
    (lab.root / '.trash-feedfacecafe').mkdir()
    builds.create_temp_project(str(lab.iso))
    assert len(lab.creates) == 2 and bases(lab) == [f'base-{key}'] and not leftovers(lab)


@pytest.mark.parametrize('how', ['exit', 'json'])
def test_a_failed_create_leaves_no_base_and_no_project(lab, how):
    lab.fail = how
    with pytest.raises(RuntimeError, match='synthetic failure'):
        builds.create_temp_project(str(lab.iso))
    assert not bases(lab) and not leftovers(lab) and not projects(lab)

    lab.fail = None
    proj_dir, proj = builds.create_temp_project(str(lab.iso))
    assert proj.is_file() and len(lab.creates) == 2


@pytest.mark.parametrize('damage', ['delete', 'truncate', 'unlistable'])
def test_a_damaged_base_is_rebuilt_not_copied(lab, monkeypatch, damage):
    builds.create_temp_project(str(lab.iso))
    [base] = bases(lab)
    fox = lab.root / base / 'files' / 'PlFxNr.dat'
    if damage == 'delete':
        fox.unlink()
    elif damage == 'truncate':
        fox.write_bytes(b'vanilla')
    else:                               # a folder os.walk cannot list
        real_walk = os.walk

        def walk(top, onerror=None, **kwargs):
            if onerror is not None and Path(top).name == base:
                onerror(PermissionError('synthetic: access denied'))
            return real_walk(top, onerror=onerror, **kwargs)

        monkeypatch.setattr(pristine.os, 'walk', walk)
    seen = []
    proj_dir, _proj = builds.create_temp_project(str(lab.iso), progress_cb=lambda p, m: seen.append(m))
    assert len(lab.creates) == 2
    assert (proj_dir / 'files' / 'PlFxNr.dat').read_bytes() == b'vanilla fox ' * 100
    assert pristine.CLEAN_MESSAGE in seen, 'deleting the old base is announced, not silent'


def test_a_base_folder_that_cannot_be_removed_fails_before_create(lab, monkeypatch):
    key, _identity = pristine.base_key(lab.iso, lab.mex / 'mexcli.exe')
    (lab.root / f'base-{key}' / 'files').mkdir(parents=True)     # unrecorded, and stuck
    monkeypatch.setattr(pristine, '_clear', lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError, match='could not be removed'):
        builds.create_temp_project(str(lab.iso))
    assert not lab.creates, 'no three-minute create that could never be renamed into place'
    assert not projects(lab)


def test_two_tests_at_once_build_one_base_and_the_second_waits(lab):
    lab.gate = threading.Event()
    results, seen_b = {}, []

    def run(name, progress_cb=None):
        results[name] = builds.create_temp_project(str(lab.iso), progress_cb=progress_cb)

    a = threading.Thread(target=run, args=('a',))
    a.start()
    wait_for(lambda: lab.creates and lab.creates[0].started.is_set(), 'the first build')
    b = threading.Thread(target=run, args=('b', lambda p, m: seen_b.append((p, m))))
    b.start()
    wait_for(lambda: any(m.startswith('Waiting for another test build') for _p, m in seen_b),
             'the second test to wait')
    assert not results
    lab.gate.set()
    a.join(WAIT)
    b.join(WAIT)
    assert len(lab.creates) == 1
    assert results['a'][0] != results['b'][0]
    assert results['a'][1].is_file() and results['b'][1].is_file()


def test_stop_during_the_base_build_kills_it_and_leaves_nothing(lab):
    lab.gate = threading.Event()        # never opens: only a Stop ends this build
    stop = threading.Event()
    outcome = {}

    def run():
        token = builds.STOP_CHECK.set(stop.is_set)
        try:
            builds.create_temp_project(str(lab.iso))
        except BaseException as exc:    # noqa: BLE001 -- the test inspects it
            outcome['error'] = exc
        finally:
            builds.STOP_CHECK.reset(token)

    worker = threading.Thread(target=run)
    worker.start()
    wait_for(lambda: lab.creates and lab.creates[0].started.is_set(), 'the build to start')
    assert any(lab.root.glob('.building-*/files/PlFxNr.dat'))
    stop.set()
    worker.join(WAIT)

    assert isinstance(outcome.get('error'), pristine.BuildStopped)
    assert isinstance(outcome['error'], MexExportCancelled), 'the job reports it as a Stop'
    assert lab.creates[0].terminated
    assert not bases(lab) and not projects(lab)
    # One rename to .trash-* (never read), so the Stop frees the slot at once.
    assert [name.split('-')[0] for name in leftovers(lab)] == ['.trash']

    lab.gate = None                      # the next test builds a whole new base
    proj_dir, proj = builds.create_temp_project(str(lab.iso))
    assert proj.is_file() and len(lab.creates) == 2 and len(bases(lab)) == 1
    assert not leftovers(lab)


def test_stop_while_waiting_for_another_build_gives_up_the_wait(lab):
    lab.gate = threading.Event()
    builder = threading.Thread(target=lambda: builds.create_temp_project(str(lab.iso)))
    builder.start()
    wait_for(lambda: lab.creates and lab.creates[0].started.is_set(), 'the first build')
    stop = threading.Event()

    def progress(_pct, message):        # Stop lands while this test is waiting
        if message.startswith('Waiting for another test build'):
            stop.set()

    token = builds.STOP_CHECK.set(stop.is_set)
    try:
        with pytest.raises(pristine.BuildStopped):
            builds.create_temp_project(str(lab.iso), progress_cb=progress)
    finally:
        builds.STOP_CHECK.reset(token)
    assert stop.is_set()
    lab.gate.set()
    builder.join(WAIT)
    assert len(lab.creates) == 1 and len(bases(lab)) == 1 and len(projects(lab)) == 1


def test_abandoned_test_projects_are_swept(lab):
    lab.builds.mkdir(parents=True)
    old, recent, other = (lab.builds / 'proj_0123456789ab', lab.builds / 'proj_ba9876543210',
                          lab.builds / 'extras_fox_proj')
    for folder in (old, recent, other):
        (folder / 'files').mkdir(parents=True)
    long_ago = time.time() - builds.STALE_PROJECT_SECONDS - 60
    os.utime(old, (long_ago, long_ago))
    os.utime(other, (long_ago, long_ago))
    builds.create_temp_project(str(lab.iso))
    assert not old.exists() and recent.exists() and other.exists()


def test_export_progress_lands_on_the_export_band(tmp_path):
    seen = []

    def export_iso(out, progress, *rest, should_stop=None):
        for pct in (0, 50, 100):
            progress(pct, f'export {pct}')
        Path(out).write_bytes(b'iso')

    fake_mex = type('Mex', (), {'project_path': str(tmp_path), 'export_iso': staticmethod(export_iso)})()
    builds._export(fake_mex, str(tmp_path / 'out.iso'), lambda p, m: seen.append((p, m)), lambda m: None)
    low, high = builds.BAR_EXPORT
    assert seen == [(low, 'Exporting the test ISO…'), (low, 'export 0'),
                    ((low + high) / 2, 'export 50'), (high, 'export 100')]
