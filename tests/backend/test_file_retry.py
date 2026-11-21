"""
file_retry: bounded retries for transient Windows file locks.

Defender / the search indexer briefly hold a file the app just wrote, and the
next replace/open/unlink on it fails with winerror 5/32/33 (or a bare
PermissionError errno 13 from the CRT). These tests drive the Windows path on
any OS through `file_retry.IS_WINDOWS` and a fake clock, so they are fast and
deterministic: no real sleeps, no real scanner.
"""
from tests.paths import BACKEND
import errno
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import file_retry
import core.metadata as cm


class FakeClock:
    """Stands in for the `time` module inside file_retry: sleep advances it."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(file_retry, 'time', fake)
    return fake


@pytest.fixture
def windows(monkeypatch, clock):
    monkeypatch.setattr(file_retry, 'IS_WINDOWS', True)
    return clock


def lock_error(winerror):
    """The PermissionError a Win32 call raises for a scanner-held file."""
    exc = PermissionError(errno.EACCES, 'Access is denied', 'locked.json')
    exc.winerror = winerror
    return exc


def _inside(path, root):
    try:
        path = os.path.normcase(os.path.abspath(os.fspath(path)))
    except TypeError:
        return False
    return path.startswith(os.path.normcase(os.path.abspath(os.fspath(root))) + os.sep)


def flaky(real, failures, make_error, *, within=None):
    """Wrap `real` to raise `make_error()` `failures` times, then call through.

    `within`: when the fake replaces a process-wide function (os.replace,
    Path.write_text), only calls on a path under this folder are counted or
    failed, and every other caller goes straight to `real`. Threads an earlier
    test in this xdist worker left running (a menu-ref derivation publishing
    with os.replace, say) otherwise took one of the injected failures or added
    to the count while this test ran.
    """
    calls = {'n': 0, 'raised': []}

    def wrapper(*args, **kwargs):
        if within is not None and not (args and _inside(args[0], within)):
            return real(*args, **kwargs)
        calls['n'] += 1
        if calls['n'] <= failures:
            exc = make_error()
            calls['raised'].append(exc)
            raise exc
        return real(*args, **kwargs)
    return wrapper, calls


def test_windows_flag_defaults_to_the_real_platform():
    assert file_retry.IS_WINDOWS == (os.name == 'nt')


def test_importing_it_does_not_initialize_core():
    """`core` runs core.config on import (repoints TEMP, may take the data-root
    lease). Standalone tools that only want a retried write must not pay that."""
    backend = BACKEND
    subprocess.run([
        sys.executable, '-I', '-c',
        'import sys; sys.path.insert(0, sys.argv[1]); '
        'import file_retry, shared.ingame.dolphin_lock; '
        'assert not any(n == "core" or n.startswith("core.") for n in sys.modules), '
        'sorted(n for n in sys.modules if n.startswith("core"))',
        str(backend),
    ], cwd=backend, check=True, timeout=30)


# --------------------------------------------------------------------------
# replace
# --------------------------------------------------------------------------

@pytest.mark.parametrize('winerror', [5, 32, 33])
def test_replace_retries_each_transient_lock_then_publishes(windows, monkeypatch, tmp_path, winerror):
    src, dst = tmp_path / 'new.json.tmp', tmp_path / 'metadata.json'
    src.write_text('new', encoding='utf-8')
    dst.write_text('old', encoding='utf-8')
    fake, calls = flaky(os.replace, 3, lambda: lock_error(winerror), within=tmp_path)
    monkeypatch.setattr(os, 'replace', fake)

    assert file_retry.replace(src, dst) is None

    assert calls['n'] == 4
    assert dst.read_text(encoding='utf-8') == 'new'
    assert not src.exists()
    assert windows.sleeps == [0.01, 0.02, 0.04]


@pytest.mark.parametrize('error', [
    lambda: OSError('injected disk failure'),             # no errno at all
    lambda: FileNotFoundError(errno.ENOENT, 'gone'),       # not a lock
    lambda: lock_error(17),                                # ERROR_NOT_SAME_DEVICE
    lambda: lock_error(1224),                              # a lock code not in the set
])
def test_replace_raises_other_errors_at_once(windows, monkeypatch, tmp_path, error):
    raised = error()
    calls = []
    real_replace = os.replace

    def fake(src, dst):
        if not _inside(src, tmp_path):        # another thread's replace: not this test's
            return real_replace(src, dst)
        calls.append((src, dst))
        raise raised
    monkeypatch.setattr(os, 'replace', fake)

    with pytest.raises(OSError) as info:
        file_retry.replace(tmp_path / 'a', tmp_path / 'b')

    assert info.value is raised
    assert len(calls) == 1
    assert windows.sleeps == []


def test_replace_reraises_the_last_lock_error_after_the_deadline(windows, monkeypatch, tmp_path):
    fake, calls = flaky(os.replace, 10 ** 6, lambda: lock_error(32), within=tmp_path)
    monkeypatch.setattr(os, 'replace', fake)

    with pytest.raises(PermissionError) as info:
        file_retry.replace(tmp_path / 'a', tmp_path / 'b')

    # the original exception object, unchanged -- not a wrapper
    assert info.value is calls['raised'][-1]
    assert info.value.winerror == 32
    # bounded: the waits add up to exactly the default timeout, none over 100 ms
    assert sum(windows.sleeps) == pytest.approx(file_retry.DEFAULT_TIMEOUT)
    assert max(windows.sleeps) <= 0.1
    assert calls['n'] == len(windows.sleeps) + 1 < 30


def test_replace_honours_a_custom_timeout(windows, monkeypatch, tmp_path):
    fake, calls = flaky(os.replace, 10 ** 6, lambda: lock_error(5), within=tmp_path)
    monkeypatch.setattr(os, 'replace', fake)

    with pytest.raises(PermissionError):
        file_retry.replace(tmp_path / 'a', tmp_path / 'b', timeout=0.05)

    assert sum(windows.sleeps) == pytest.approx(0.05)
    assert calls['n'] == len(windows.sleeps) + 1


def test_replace_does_not_retry_off_windows(monkeypatch, clock, tmp_path):
    monkeypatch.setattr(file_retry, 'IS_WINDOWS', False)
    fake, calls = flaky(os.replace, 1, lambda: lock_error(32), within=tmp_path)
    monkeypatch.setattr(os, 'replace', fake)

    with pytest.raises(PermissionError):
        file_retry.replace(tmp_path / 'a', tmp_path / 'b')

    assert calls['n'] == 1
    assert clock.sleeps == []


# --------------------------------------------------------------------------
# retry_locked
# --------------------------------------------------------------------------

def test_retry_locked_retries_a_crt_sharing_violation_and_returns_the_result(windows, tmp_path):
    # open() reports a sharing violation as plain errno 13 with no winerror.
    target = tmp_path / 'IfAll.usd'
    fake, calls = flaky(lambda path, data: path.write_bytes(data), 2,
                        lambda: PermissionError(errno.EACCES, 'Permission denied', str(target)))

    assert file_retry.retry_locked(fake, target, b'hud') == 3

    assert calls['n'] == 3
    assert target.read_bytes() == b'hud'
    assert windows.sleeps == [0.01, 0.02]


def test_retry_locked_passes_kwargs_through_and_keeps_its_timeout(windows):
    seen = []

    def fn(*args, **kwargs):
        seen.append((args, kwargs))
        return 'ok'

    assert file_retry.retry_locked(fn, 1, 2, timeout=0.5, encoding='utf-8') == 'ok'
    assert seen == [((1, 2), {'encoding': 'utf-8'})]


def test_retry_locked_wraps_open_for_a_with_block(windows, monkeypatch, tmp_path):
    target = tmp_path / 'fighter.json'
    fake_open, calls = flaky(open, 1, lambda: lock_error(32))

    with file_retry.retry_locked(fake_open, target, 'w', encoding='utf-8') as f:
        json.dump({'name': 'Fox'}, f)

    assert calls['n'] == 2
    assert json.loads(target.read_text(encoding='utf-8')) == {'name': 'Fox'}


@pytest.mark.parametrize('error', [
    lambda: FileNotFoundError(errno.ENOENT, 'gone'),
    lambda: FileExistsError(errno.EEXIST, 'exists'),      # open(..., 'xb') on Windows too
    lambda: ValueError('not an OSError at all'),
])
def test_retry_locked_raises_other_errors_at_once(windows, error):
    raised = error()
    calls = []

    def fn():
        calls.append(1)
        raise raised

    with pytest.raises(Exception) as info:
        file_retry.retry_locked(fn)

    assert info.value is raised
    assert len(calls) == 1
    assert windows.sleeps == []


def test_retry_locked_reraises_the_last_lock_error_after_the_deadline(windows):
    fake, calls = flaky(lambda: None, 10 ** 6,
                        lambda: PermissionError(errno.EACCES, 'Permission denied'))

    with pytest.raises(PermissionError) as info:
        file_retry.retry_locked(fake, timeout=0.3)

    assert info.value is calls['raised'][-1]
    assert sum(windows.sleeps) == pytest.approx(0.3)
    assert calls['n'] == len(windows.sleeps) + 1


def test_retry_locked_does_not_retry_off_windows(monkeypatch, clock):
    monkeypatch.setattr(file_retry, 'IS_WINDOWS', False)
    fake, calls = flaky(lambda: None, 1, lambda: PermissionError(errno.EACCES, 'denied'))

    with pytest.raises(PermissionError):
        file_retry.retry_locked(fake)

    assert calls['n'] == 1
    assert clock.sleeps == []


# --------------------------------------------------------------------------
# real call sites
# --------------------------------------------------------------------------

def test_save_metadata_survives_a_scanner_holding_metadata_json(vault, windows, monkeypatch):
    """The storage_stages reorder failure: os.replace(metadata.json.tmp ->
    metadata.json) answered [WinError 5] while Defender held the old file."""
    vault.write({'characters': {}, 'stages': {'old': True}})
    fake, calls = flaky(os.replace, 2, lambda: lock_error(5), within=vault.storage)
    monkeypatch.setattr(cm.os, 'replace', fake)

    cm.save_metadata({'characters': {}, 'stages': {'reordered': True}})

    assert calls['n'] == 3
    assert vault.read() == {'characters': {}, 'stages': {'reordered': True}}
    assert [p.name for p in cm.METADATA_FILE.parent.iterdir()] == ['metadata.json']


def test_save_metadata_still_fails_cleanly_on_a_lock_that_never_clears(vault, windows, monkeypatch):
    vault.write({'characters': {}, 'version': 1})
    fake, calls = flaky(os.replace, 10 ** 6, lambda: lock_error(5), within=vault.storage)
    monkeypatch.setattr(cm.os, 'replace', fake)

    with pytest.raises(PermissionError) as info:
        cm.save_metadata({'characters': {}, 'version': 2})

    assert info.value is calls['raised'][-1]
    assert vault.read() == {'characters': {}, 'version': 1}
    # the temp file is still cleaned up after the bounded wait
    assert [p.name for p in cm.METADATA_FILE.parent.iterdir()] == ['metadata.json']


def test_menu_ref_publish_retries_a_locked_png(windows, monkeypatch, tmp_path):
    """HUD reference derivation: publishing a just-dumped glyph PNG over the
    previous one while a scanner holds it."""
    menu_refs = pytest.importorskip('shared.vanilla_extract.menu_refs')
    (tmp_path / 'glyph_0.png').write_bytes(b'old')
    fake, calls = flaky(os.replace, 2, lambda: lock_error(5), within=tmp_path)
    monkeypatch.setattr(os, 'replace', fake)

    menu_refs._publish(tmp_path, 'glyph_0.png', b'new')

    assert calls['n'] == 3
    assert (tmp_path / 'glyph_0.png').read_bytes() == b'new'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['glyph_0.png']


def test_door_catalog_write_retries_a_sharing_violation(windows, monkeypatch, tmp_path):
    """A plain (non-atomic) catalog write that open() refuses with errno 13."""
    doors = pytest.importorskip('vault.menus.doors')
    catalog = tmp_path / 'metadata.json'
    monkeypatch.setattr(doors, 'DOORS_METADATA', catalog)
    real_write_text = type(catalog).write_text
    fake, calls = flaky(real_write_text, 2,
                        lambda: PermissionError(errno.EACCES, 'Permission denied', str(catalog)),
                        within=tmp_path)
    monkeypatch.setattr(type(catalog), 'write_text', fake)

    doors._save_doors_metadata([{'id': 'abc', 'name': 'Door'}])

    assert calls['n'] == 3
    assert json.loads(catalog.read_bytes()) == [{'id': 'abc', 'name': 'Door'}]
