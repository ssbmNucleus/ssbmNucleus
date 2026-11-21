"""Atomic, per-archive coordination for ZIP rewrites."""

import os
import tempfile
import threading
import zipfile
from pathlib import Path

import file_retry


_locks_guard = threading.Lock()
_archive_locks = {}


def _lock_for(path: Path):
    key = str(path.resolve())
    with _locks_guard:
        return _archive_locks.setdefault(key, threading.RLock())


def rewrite_zip_atomic(archive_path, rewrite):
    """Build and validate a unique sibling ZIP, then atomically publish it.

    ``rewrite(source, destination)`` owns the content policy. The destination
    archive is never exposed until it closes and passes a full CRC read. Calls
    targeting the same archive serialize from source read through replacement,
    so independent edits do not start from the same stale ZIP generation.
    """
    archive_path = Path(archive_path)
    with _lock_for(archive_path):
        fd, staged_name = tempfile.mkstemp(
            prefix=archive_path.name + '.', suffix='.tmp', dir=archive_path.parent)
        os.close(fd)
        staged = Path(staged_name)
        try:
            with zipfile.ZipFile(archive_path, 'r') as source:
                with zipfile.ZipFile(staged, 'w', zipfile.ZIP_DEFLATED) as destination:
                    rewrite(source, destination)
            with zipfile.ZipFile(staged, 'r') as candidate:
                bad_member = candidate.testzip()
                if bad_member is not None:
                    raise zipfile.BadZipFile(
                        f"Staged archive has a corrupt member: {bad_member}")
            file_retry.replace(staged, archive_path)
        finally:
            try:
                staged.unlink()
            except FileNotFoundError:
                pass
