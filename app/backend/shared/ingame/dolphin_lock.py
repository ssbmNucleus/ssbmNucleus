"""dolphin_lock.py -- machine-wide advisory lock for the ONE-Dolphin-at-a-time
harness rule, so concurrent agents/sessions QUEUE for the emulator instead of
fighting over it (window capture, controller pipes and the in-app embed all
assume a single Dolphin).

The lock is a JSON file created atomically (O_CREAT|O_EXCL) in a per-machine
location shared by every checkout and the installed app. Holders record pid +
purpose; a lock whose pid is dead is stale and silently reclaimed. Purely
advisory: nothing stops a rogue process from launching Dolphin directly, but
every harness entry point (MCP live session, frameshot, effect_probe,
run_ingame_test) acquires it, which covers the real contention.

Usage:
    from shared.ingame.dolphin_lock import acquire, release, status, hold, BusyError

    acquire("frameshot marth fair", wait=120)   # blocks up to 120 s
    ...
    release()

    with hold("live session fox @ FD"):         # context-managed
        ...

Slots: a machine with the memory for it runs N harness Dolphins at once
(default 1, at most MAX_SLOTS). Slot 0 is LOCK_PATH itself, so a default
machine behaves exactly as before; slot i > 0 is a sibling file
`harness-dolphin.<i>.lock`. DolphinBoot gives every run its own User dir, and
memory reads and window captures already target a pid.

ONE POOL PER MACHINE (`machine_config`): the size, and where the machine keeps
its per-slot copies of Dolphin, are read from `harness-dolphin.json` beside
the lock files, {"slots": 4, "slot_dir": "D:/.../dolphin-slots"}; a key the
file does not give comes from the environment (NUCLEUS_DOLPHIN_SLOTS,
NUCLEUS_DOLPHIN_SLOT_DIR). The file is the place to set it: every tool on the
machine takes the first free slot, which only works when they all count the
same slots. (Until 2026-11-10 each tool set its own size in its environment,
and one pinned its groups to fixed slots, so a tool could wait on a slot while
others stood free.)

What separates two slots is the slot's own COPY of Dolphin (`slot_kit`), not
its pipe number (`slot_pipe`): see slot_kit.
"""
import ctypes
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

import file_retry

if os.name == "nt":
    _root = Path(os.environ.get("LOCALAPPDATA",
                                str(Path.home() / "AppData" / "Local")))
    LOCK_PATH = _root / "SSBM Nucleus" / "harness-dolphin.lock"
else:
    LOCK_PATH = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) \
        / "ssbm-nucleus-dolphin.lock"

# One controller pipe per slot (slippibot1..8), so never more slots than pipes.
MAX_SLOTS = 8


KIT_EXE = "Slippi Dolphin.exe"


def machine_config():
    """{"slots": N, "slot_dir": folder or None} for THIS machine: the file
    `harness-dolphin.json` beside the lock files, each key falling back to the
    environment (NUCLEUS_DOLPHIN_SLOTS, NUCLEUS_DOLPHIN_SLOT_DIR), then to one
    slot and no copies. Read at every call: LOCK_PATH can be redirected."""
    try:
        file = json.loads(LOCK_PATH.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        file = {}
    if not isinstance(file, dict):
        file = {}
    try:
        wanted = int(file.get("slots") or os.environ.get("NUCLEUS_DOLPHIN_SLOTS") or 1)
    except (TypeError, ValueError):
        wanted = 1
    slot_dir = file.get("slot_dir") or os.environ.get("NUCLEUS_DOLPHIN_SLOT_DIR") or None
    return {"slots": max(1, min(MAX_SLOTS, wanted)), "slot_dir": slot_dir}


def slot_count():
    """How many harness Dolphins this machine may run at once (1..8)."""
    return machine_config()["slots"]


def slot_kit(index):
    r"""Slot `index`'s own copy of Slippi Dolphin, {"exe", "prefix",
    "stock_exe"}, or None when this machine keeps none for it. `stock_exe` is
    the Dolphin the copy was made from: the copy stands in for that one only.

    Stock Slippi Dolphin creates its controller pipes \\.\pipe\slippibot1..4
    for itself whatever its config says, and the names are machine-wide. So two
    stock Dolphins cannot both be driven through pipes: the second gets none
    (2026-11-10, two captures started together: one shot, one "pipe not
    available"). A machine that runs several keeps one folder per slot under
    `slot_dir`: `<index>/Slippi Dolphin.exe`, a copy whose pipes carry a prefix
    of its own, and `<index>/slot.json` naming it ({"slot": 1, "prefix":
    "slipslotB", "stock_exe": "<the exe it was copied from>"}). The copies are
    made by a dev tool outside the app; this only reads them. Windows only:
    elsewhere a run's pipes live in its User dir."""
    folder = machine_config()["slot_dir"]
    if os.name != "nt" or not folder or index is None:
        return None
    kit = Path(folder) / str(index)
    try:
        meta = json.loads((kit / "slot.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(meta, dict):
        return None
    prefix, stock, exe = meta.get("prefix"), meta.get("stock_exe"), kit / KIT_EXE
    if (meta.get("slot") != index or not isinstance(prefix, str) or not prefix
            or not isinstance(stock, str) or not stock or not exe.is_file()):
        return None
    return {"exe": str(exe), "prefix": prefix, "stock_exe": stock}


def slot_path(index):
    """Lock file of slot `index`; slot 0 is LOCK_PATH itself."""
    if index == 0:
        return LOCK_PATH
    return LOCK_PATH.with_name(f"{LOCK_PATH.stem}.{index}{LOCK_PATH.suffix}")


def slot_pipe(index):
    """The slippibot<N> pipe a slot's Dolphin is driven through."""
    return index + 1


class BusyError(RuntimeError):
    """Dolphin is owned by another live process. .owner has the details."""

    def __init__(self, owner):
        self.owner = owner
        super().__init__(
            f"Dolphin is in use by pid {owner.get('pid')} "
            f"({owner.get('purpose', '?')}) since {owner.get('started_str')} "
            "-- pass a wait timeout to queue for it, or retry later")


def _pid_alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _read_owner(path=None):
    try:
        return json.loads((path or LOCK_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _slot_status(index):
    owner = _read_owner(slot_path(index))
    if owner is None:
        return {"slot": index, "locked": False, "owner": None, "stale": False}
    alive = _pid_alive(owner.get("pid"))
    owner["alive"] = alive
    return {"slot": index, "locked": alive, "owner": owner, "stale": not alive}


def status():
    """{locked, owner{pid,purpose,started,started_str,alive}, stale} for slot 0,
    plus `slot_count`, `free_slots` and per-slot `slots` entries."""
    slots = [_slot_status(i) for i in range(slot_count())]
    result = {key: slots[0][key] for key in ("locked", "owner", "stale")}
    result.update(slot_count=len(slots), slots=slots,
                  free_slots=sum(1 for s in slots if not s["locked"]))
    return result


# Nesting depth and lease of the lock THIS process holds. Re-acquiring from the
# same pid is legitimate -- every boot path funnels through DolphinBoot.launch,
# inside a coordinator that already took the lock -- but the inner acquire must
# not let the inner release hand the machine back while the outer holder is
# still using it. The depth counts that nesting; the lease identifies WHICH
# holder, so a release from a stale nested caller cannot drop a later one.
_state = {"depth": 0, "token": None, "slot": None}
_local = threading.Lock()
# How long an unparsable lock file is assumed to be mid-write rather than
# debris. Writing is atomic, so this only covers a crash between create and
# fill, which the single-step create below has already closed.
UNREADABLE_GRACE = 10.0


def _write_payload(payload, path=None):
    """Write the lock file WHOLE. A reader that catches it half-written sees
    unreadable JSON, and unreadable JSON is treated as stale and unlinked --
    which is another process deleting a live lock."""
    path = path or LOCK_PATH
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    file_retry.replace(temporary, path)


def current_slot():
    """The slot this process holds, or None."""
    return _state["slot"] if _state["depth"] > 0 else None


def _try_slot(path, payload):
    """One claim on one slot's file. -> (True, None) or (False, owner).

    Stale files (dead owner) and unreadable debris past its grace period are
    reclaimed and the claim retried; a live owner, or a file too young to call
    debris, is reported busy."""
    for _ in range(4):
        try:
            # Create and FILL in one step. Creating an empty file and
            # writing it afterwards leaves a window in which another
            # process reads unreadable JSON, calls it stale, unlinks it and
            # acquires -- and then the first writer overwrites the second's
            # payload. Two owners, both successful.
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
                handle.flush()
                os.fsync(handle.fileno())
            return True, None
        except FileExistsError:
            owner = _read_owner(path)
            if owner is not None and owner.get("pid") == os.getpid():
                # Our pid, but this process has no depth: a previous run in
                # this process died without releasing. Take it over.
                _write_payload(payload, path)
                return True, None
            if owner is None:
                # UNREADABLE IS NOT STALE. A lock whose json cannot be
                # parsed may be one that is mid-write, and unlinking it is
                # how two owners happen. Give it a grace period and only
                # then treat an unreadable file as debris.
                try:
                    age = time.time() - path.stat().st_mtime
                except OSError:
                    continue
                if age < UNREADABLE_GRACE:
                    return False, {"pid": None, "purpose": "an unreadable lock file"}
                try:
                    path.unlink()
                except OSError:
                    pass
                continue
            if not _pid_alive(owner.get("pid")):
                try:                   # the owner is dead -- reclaim
                    path.unlink()
                except OSError:
                    pass
                continue
            return False, owner
    return False, {"pid": None, "purpose": "a contended lock file"}


def acquire(purpose, wait=0.0, poll=2.0):
    """Take the lock, waiting up to `wait` seconds if it's held. Stale locks
    (dead owner pid) are reclaimed immediately. Raises BusyError on timeout.

    Re-acquiring from the pid that already holds it updates the purpose and
    increments a nesting depth: the lock is handed back only when the outermost
    holder releases it. The returned payload carries a `token`; pass it to
    `release(token=...)` so an inner or stale caller cannot drop a lease it
    does not own."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + max(0.0, float(wait or 0))
    while True:
        with _local:
            payload = {"pid": os.getpid(), "purpose": str(purpose)[:200],
                       "argv0": sys.argv[0], "started": time.time(),
                       "started_str": time.strftime("%Y-%m-%d %H:%M:%S")}
            if _state["depth"] > 0:
                # Already ours. Nest under the existing lease.
                _state["depth"] += 1
                payload["token"] = _state["token"]
                payload["depth"] = _state["depth"]
                payload["slot"] = _state["slot"]
                _write_payload(payload, slot_path(_state["slot"]))
                return dict(payload)
            payload["token"] = uuid.uuid4().hex
            payload["depth"] = 1
            busy = None
            for index in range(slot_count()):
                payload["slot"] = index
                claimed, owner = _try_slot(slot_path(index), payload)
                if claimed:
                    _state.update(depth=1, token=payload["token"], slot=index)
                    return dict(payload)
                busy = busy or owner
            if time.time() >= deadline:
                raise BusyError(busy)
        time.sleep(poll)


def release(token=None):
    """Drop the lock if THIS process holds it (no-op otherwise).

    With `token`, only the holder of that lease may release, and only when the
    nesting it opened is the outermost one. Without a token the historical
    behaviour is kept -- one level is dropped -- so existing callers still
    unwind correctly."""
    with _local:
        if _state["depth"] <= 0:
            # This process holds no lease, so any slot file naming its pid is
            # debris: a pre-lease file, or one a failed unlink left behind.
            for index in range(slot_count()):
                path = slot_path(index)
                owner = _read_owner(path)
                if owner and owner.get("pid") == os.getpid():
                    try:
                        file_retry.retry_locked(path.unlink, missing_ok=True)
                    except OSError:
                        pass
            return False
        if token is not None and token != _state["token"]:
            return False                   # not this lease's to give away
        _state["depth"] -= 1
        if _state["depth"] > 0:
            return False                   # an outer holder is still using it
        path = slot_path(_state["slot"])
        try:
            # Retried: a scanner holding the file must not leave a lease that
            # names this live pid. If it still fails, the next release() of
            # this process removes it (the depth <= 0 sweep above).
            file_retry.retry_locked(path.unlink, missing_ok=True)
        except OSError:
            pass
        _state.update(token=None, slot=None)
        return True


class hold:
    """Context manager: acquire on enter, release on exit."""

    def __init__(self, purpose, wait=0.0):
        self.purpose, self.wait = purpose, wait

    def __enter__(self):
        return acquire(self.purpose, wait=self.wait)

    def __exit__(self, *exc):
        release()
        return False
