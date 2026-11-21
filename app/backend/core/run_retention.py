"""Retention for Test-in-Game scratch output (storage/test-runs, storage/test-builds).

Every run leaves a ``test-<YYYYMMDD_HHMMSS>[-n]`` directory plus a sibling
``test-<...>-dolphin.log`` in test-runs (~50 MB each) and the ISO it booted in
test-builds. Nothing ever deleted them, so call these right after creating the
folders. Deletion is best-effort: a locked or already-gone path is skipped.
"""
import shutil
from pathlib import Path

_LOG_SUFFIX = '-dolphin.log'


def _remove(path):
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink()
    except OSError:
        pass


def prune_runs(runs_root, keep=5, protect=()):
    """Keep only the newest ``keep`` run stamps under ``runs_root``.

    A stamp is the run dir ``test-<stamp>`` and its ``test-<stamp>-dolphin.log``;
    they are kept or deleted together. Newest is by name (the stamp sorts
    chronologically). Names in ``protect`` (the current run) are never deleted
    and do not count against ``keep``. Returns the names that were removed.
    """
    root = Path(runs_root)
    if not root.is_dir():
        return []
    protected = {Path(p).name for p in protect}
    stamps = {}
    for entry in root.iterdir():
        name = entry.name
        if not name.startswith('test-'):
            continue
        if entry.is_file() and name.endswith(_LOG_SUFFIX):
            stamps.setdefault(name[:-len(_LOG_SUFFIX)], []).append(entry)
        elif entry.is_dir():
            stamps.setdefault(name, []).append(entry)
    candidates = sorted((s for s in stamps if s not in protected), reverse=True)
    removed = []
    for stamp in candidates[max(keep, 0):]:
        for path in stamps[stamp]:
            _remove(path)
            removed.append(path.name)
    return removed


def prune_test_builds(builds_dir, keep=2, protect=()):
    """Keep only the newest ``keep`` ISOs (by mtime) directly in ``builds_dir``.

    Only ``*.iso`` files are touched; throwaway project folders are left alone.
    """
    root = Path(builds_dir)
    if not root.is_dir():
        return []
    protected = {Path(p).name for p in protect}
    isos = []
    for entry in root.glob('*.iso'):
        if entry.name in protected or not entry.is_file():
            continue
        try:
            isos.append((entry.stat().st_mtime, entry.name, entry))
        except OSError:
            continue
    isos.sort(reverse=True)
    removed = []
    for _, name, path in isos[max(keep, 0):]:
        _remove(path)
        removed.append(name)
    return removed


def prune_test_scratch(storage_path, protect_iso=None):
    """Convenience wrapper used by the Test-in-Game routes."""
    storage = Path(storage_path)
    prune_runs(storage / 'test-runs', keep=5)
    prune_test_builds(storage / 'test-builds', keep=2,
                      protect=(protect_iso,) if protect_iso else ())
