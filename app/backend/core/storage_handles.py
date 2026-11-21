"""Long-lived handles into the storage (Vault) folder, closed before the folder itself is swapped.

A Replace All restore (vault/routes/vault_backup.py) renames the live storage folder aside and the restored one into
its place. Windows refuses that rename while any file under the folder is open, and a few modules keep a SQLite
connection open for as long as their thread lives: the assistant's task journal and wish ledger, both on
``storage/assistant/tasks/tasks.db``. Each such module registers a closer here at import; the swap calls
:func:`close_all` first, and every module reopens its connection on its next use.

This lives in core so the Vault code needs no import of a gated package (the assistant may not ship in a build).
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

_closers = []
_lock = threading.Lock()


def register(closer):
    """Add ``closer`` (no arguments): it closes every handle its module holds under the storage folder, on every
    thread, and leaves the module able to reopen them."""
    with _lock:
        if closer not in _closers:
            _closers.append(closer)


def close_all():
    """Run every registered closer. One that fails is logged; the rest still run."""
    with _lock:
        closers = list(_closers)
    for closer in closers:
        try:
            closer()
        except Exception:  # noqa: BLE001 - a closer that fails must not stop the others
            logger.warning('Could not close storage handles with %r', closer, exc_info=True)
