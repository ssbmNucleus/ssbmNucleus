"""verify_costume.py -- the metered in-game verification of ONE costume.

This is the last computational gate before a costume may be released: it runs
the candidate in the actual game under a declared capture profile and returns
measured evidence, not an opinion.

What it is NOT
--------------
It is not a pass. Neither a completed capture run nor a missing measurement
ever becomes `verified` here:

* a required measurement that could not be taken is ``unknown``;
* a capture whose actor could not be isolated is ``unknown``;
* an unsupported profile entry makes the profile INCOMPLETE and is recorded,
  never silently dropped;
* ``outcome == 'verified'`` requires complete execution evidence AND a passing
  appearance check on every frame the profile asked for.

The two kinds of evidence (ASTRA-CONSULT-2 section 1)
-----------------------------------------------------
**Execution evidence** -- the intended candidate was inserted, selected, booted
and captured at the requested states. Read back from RAM (`Fighter.x619
costume_id`, `Fighter.kind`, `StageInfo.grkind`, action state and animation
frame), never echoed from the player block the harness wrote. This is what
eliminates "built slot 4, captured slot 0".

**Appearance evidence** -- the actual game frames, measured with a CONTROLLED
camera. The profile's camera is fixed in advance and the harness runs with
`--fixed-camera` (frameshot ``fit_mode='measure'``): a clipped or absent model
is measured against a paired capture of the same frozen frame with the fighter
taken out of every render pass, and recorded. It is never re-framed. A wider
shot chosen after seeing a result must not be able to make an extent check
pass.

Ownership and the machine
-------------------------
The coordinator takes the machine-wide Dolphin lock (`shared.ingame.dolphin_lock`) for
the whole run, in ONE pid, and runs the capture in-process so the emulator boot
re-acquires that same lock as a no-op. If the lock is held by a live process
the run stops with outcome ``incomplete`` and reason ``dolphin_busy``: a busy
Dolphin is left alone, never taken. Cancellation closes only the `Session` this
run opened, through its retained child handle; nothing is ever matched by image
name or by port owner.

Timing is recorded per phase -- lock wait, ISO build, ISO identity, boot,
captures, teardown, checks -- so "where did the four minutes go" is answerable
from the manifest.

Caching
-------
Keyed on candidate bytes + profile version + engine version (a content hash of
the harness sources that decide what the pictures look like) + character and
stage. Identical inputs return the stored manifest instead of spending another
boot; the manifest says ``cache.hit``.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]          # backend/shared/ingame -> backend
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import file_retry  # noqa: E402  (after the path setup: this also runs as a script)
from core.hashing import sha256_file  # noqa: E402
# The verification's parts (profile, cache, appearance and execution evidence,
# outcome) live beside this module; this one is the engine identity and the
# coordinator that owns the machine.
from shared.ingame.verify_profile import (  # noqa: E402
    MANIFEST_SCHEMA, PROFILE_VERSION, resolve_profile, shot_specs)
from shared.ingame.verify_cache import cache_spec, cache_key, validate_cached  # noqa: E402
from shared.ingame.verify_appearance import measure_capture, contact_sheet  # noqa: E402
from shared.ingame.verify_evidence import _check, execution_evidence, insertion_evidence  # noqa: E402
from shared.ingame.verify_outcome import decide_outcome, deterministic_unknown  # noqa: E402


# The harness sources that decide what a capture looks like and what it means.
# A change to any of them is a different engine version, so cached results from
# before it are not served.
# Named here so a build-time generator and a reader can both see what the
# engine identity is SUPPOSED to cover. Everything in `shared/ingame/` is included by
# the glob below; these are the ones outside it, plus the ones whose absence
# would be the most expensive to miss.
_ENGINE_SOURCES = ("frameshot.py", "verify_costume.py", "moves.py",
                   "gamestate.py", "framestep.py", "boot.py",
                   "match_setup.py")


def engine_source_paths():
    """Every module that decides what a capture looks like and what it means.

    The whole of `shared/ingame/` plus the capture engine. A hand-kept list of six
    files left `nav.py`, `screenshot.py` and `melee_css.py` outside the engine
    identity although each of them can change a picture.
    """
    paths = sorted(HERE.glob("*.py"), key=lambda p: p.name)
    paths.append(BACKEND / "devtools" / "frameshot.py")
    return tuple(paths)


class Cancelled(RuntimeError):
    """The run was cancelled. Only the owned emulator instance was stopped."""


# --- identity, versions, cache keys ------------------------------------------- #

ENGINE_DIGEST_NAME = "engine_digest.json"


def _engine_digest_file():
    """The build-generated engine digest, when this is a packaged app.

    A frozen build has no source tree: hashing `_ENGINE_SOURCES` there produced
    `None` for every entry and collapsed to one constant id, so every packaged
    install would have shared a cache namespace and every code change would
    have been invisible to it. `scripts/build/engine_digest.py` writes this file
    at build time and the spec bundles it.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    candidates = [HERE / ENGINE_DIGEST_NAME, BACKEND / ENGINE_DIGEST_NAME]
    if meipass:
        candidates[:0] = [Path(meipass) / "shared" / "ingame" / ENGINE_DIGEST_NAME,
                          Path(meipass) / ENGINE_DIGEST_NAME]
    for path in candidates:
        if path.is_file():
            return path
    return None


def engine_version():
    """Identity of the code and binaries that decide what a capture looks like.

    In a dev checkout this is hashed from the sources. In a packaged build the
    sources are gone, so a build-generated digest is read instead; if neither is
    available the identity is explicitly `unavailable` and nothing is cached
    under it -- an unknown engine must not share a namespace with a known one.
    """
    digest = _engine_digest_file()
    if digest is not None:
        try:
            stored = json.loads(digest.read_text(encoding="utf-8"))
            if stored.get("id"):
                stored["source"] = str(digest)
                return stored
        except (OSError, ValueError):
            pass
    parts, missing = {}, []
    for path in engine_source_paths():
        try:
            parts[path.name] = sha256_file(path)[:16]
        except OSError:
            parts[path.name] = None
            missing.append(path.name)
    if missing:
        return {"schema": "harness-engine-version-v1", "sources": parts,
                "id": None, "unavailable": missing,
                "reason": ("these harness sources could not be hashed, so the "
                           "engine identity is unknown and no result may be "
                           "cached under it")}
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    return {"schema": "harness-engine-version-v1", "sources": parts,
            "id": hashlib.sha256(canonical.encode()).hexdigest()[:16],
            "source": "checkout"}


def _content_identity(path, memo=None):
    """Identity of a binary we RUN: its content, not its metadata.

    Path, size and an integer mtime are not identity. A rebuilt MexCLI, a
    Dolphin swapped in place or a patched DLL keeps all three and changes every
    capture. Hashing is memoised against size+mtime so a 60 MB emulator is read
    once per machine, not once per run.
    """
    try:
        path = Path(path)
        stat = path.stat()
    except (OSError, TypeError):
        return None
    key = f"{path}|{stat.st_size}|{stat.st_mtime_ns}"
    store = _binary_memo() if memo is None else memo
    digest = store.get(key)
    if not digest:
        try:
            digest = sha256_file(path)
        except OSError:
            return None
        store[key] = digest
        if memo is None:
            _save_binary_memo(store)
    return {"path": str(path), "bytes": stat.st_size, "sha256": digest}


def _binary_memo_path():
    return cache_root() / "binary-identities.json"


def _binary_memo():
    try:
        return json.loads(_binary_memo_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_binary_memo(store):
    try:
        _atomic_write_json(_binary_memo_path(), store)
    except OSError:
        pass


def _mexcli_libraries():
    """The libraries MexCLI actually links, not just the exe beside them.

    The prebuilt MexCLI (utility/mex/<rid>/, from tools/build/fetch_native.py) is
    a self-contained build whose HSDRaw.dll and mexLib.dll decide how a costume
    is written to the disc -- HSDRaw.dll is the one that rebuilt bone tables
    wrongly until 2026-09-21. An identity naming HSDRawViewer.exe and not these
    DLLs can serve a verdict produced by different code.
    """
    try:
        from core.config import MEXCLI_PATH
    except Exception:
        return []
    folder = Path(MEXCLI_PATH).parent
    return [folder / "HSDRaw.dll", folder / "mexLib.dll", folder / "mexcli.dll"]


def toolchain_identity(vanilla_iso=None):
    """Everything OUTSIDE this repo that decides what the game does.

    The engine digest covers our Python. It does not cover the emulator, the
    build tools that put the costume on the disc, the libraries those tools
    link, or the base disc itself -- and a cache keyed without them will serve
    a verdict produced by a different Dolphin, a different MexCLI or a
    different Melee. Everything here is identified by CONTENT.
    """
    out = {"schema": "verification-toolchain-v2"}
    memo = _binary_memo()
    try:
        from core.config import MEXCLI_PATH, HSDRAW_EXE
        out["mexcli"] = _content_identity(MEXCLI_PATH, memo)
        out["hsdraw"] = _content_identity(HSDRAW_EXE, memo)
    except Exception:
        out["mexcli"] = out["hsdraw"] = None
    libraries = {}
    for path in _mexcli_libraries():
        identity = _content_identity(path, memo)
        if identity:
            libraries[Path(path).name] = identity["sha256"]
    out["mexcli_libraries"] = libraries or None
    try:
        from shared.ingame.boot import resolve_dolphin
        out["dolphin"] = _content_identity(resolve_dolphin(None)[0], memo)
    except Exception:
        out["dolphin"] = None
    out["vanilla_iso"] = _content_identity(vanilla_iso, memo) if vanilla_iso else None
    _save_binary_memo(memo)
    required = (out.get("mexcli"), out.get("hsdraw"), out.get("dolphin"),
                out.get("vanilla_iso"), out.get("mexcli_libraries"))
    out["complete"] = all(item is not None for item in required)
    canonical = json.dumps({k: v for k, v in out.items() if k != "schema"},
                           sort_keys=True, separators=(",", ":"), default=str)
    out["id"] = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    return out


def cache_root():
    root = os.environ.get("NUCLEUS_VERIFY_CACHE")
    if root:
        return Path(root)
    try:
        from core.config import STORAGE_PATH
        return Path(STORAGE_PATH) / "verify-cache"
    except Exception:
        return BACKEND.parent / "scratch" / "ingame" / "verify-cache"


# --- timing -------------------------------------------------------------------- #

class Timing:
    """Per-phase wall clock, so a run can say where its minutes went."""

    ORDER = ("lock_wait", "iso_build", "iso_identity", "boot", "captures",
             "teardown", "checks")

    def __init__(self):
        self.started = time.time()
        self.phases = {}

    def add(self, name, seconds):
        self.phases[name] = round(self.phases.get(name, 0.0) + float(seconds), 3)

    @contextmanager
    def phase(self, name):
        t0 = time.time()
        try:
            yield
        finally:
            self.add(name, time.time() - t0)

    def result(self):
        out = {name: self.phases.get(name, 0.0) for name in self.ORDER}
        for name, value in self.phases.items():
            out.setdefault(name, value)
        out["total"] = round(time.time() - self.started, 3)
        out["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%S",
                                          time.localtime(self.started))
        return out


# --- the coordinator ------------------------------------------------------------ #

WATCHDOG_SECONDS = 360.0   # whole-run emergency ceiling, not the only deadline
ABANDON_GRACE = 60.0       # how long a stopped capture thread gets to unwind
# Per-phase monotonic deadlines. The emergency ceiling above cannot tell a
# 90-second boot apart from a 300-second one, and the 2026-09-22 incident spent
# ten minutes inside a phase that normally takes fifteen seconds.
PHASE_DEADLINES = {"iso_build": 300.0, "boot": 90.0, "captures": 180.0}

# Only ONE verification at a time in this process. The machine-wide file lock
# is PID-keyed, so two threads here would both "already hold" it and the first
# teardown would hand it back underneath the second.
_RUN_LOCK = threading.Lock()

# Capture threads this process stopped watching after a watchdog or a cancel.
# They own nothing any more -- their emulator was closed before they were let
# go -- but they will still release the machine-wide lock when they unwind, so
# a new run in this process waits for them rather than racing them.
_ABANDONED = []


def abandoned_capture_threads():
    """Still-running capture threads from earlier stopped runs in this process."""
    _ABANDONED[:] = [t for t in _ABANDONED if t.is_alive()]
    return list(_ABANDONED)


def seal_candidate(source, folder):
    """Copy the candidate into a read-only verification package and describe it.

    Not a security boundary -- this process could undo the permission bits it
    just set -- but it makes the ordinary accident (something rewrites the file
    the build is about to read, or the archive is edited between hashing and
    importing) fail loudly instead of silently verifying other bytes. The
    package hash AND every archive member's hash are recorded, so the DAT that
    ships can be checked against the DAT that was captured rather than against
    a zip container that could be repacked byte-differently around identical
    contents.
    """
    import zipfile
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    sealed = folder / Path(source).name
    if sealed.resolve() != Path(source).resolve():
        if sealed.exists():
            sealed.chmod(0o600)
            sealed.unlink()
        shutil.copy2(source, sealed)
    members = {}
    try:
        with zipfile.ZipFile(sealed) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                members[info.filename] = hashlib.sha256(
                    archive.read(info.filename)).hexdigest()
    except (OSError, zipfile.BadZipFile):
        members = {}
    try:
        sealed.chmod(0o444)
    except OSError:
        pass
    return {"path": sealed, "sha256": sha256_file(sealed),
            "bytes": sealed.stat().st_size, "members": members,
            "sealed_read_only": True,
            "note": "a private verification package, not an export"}


def verify(candidate_file, character, *, destination, profile=PROFILE_VERSION,
           vanilla_iso=None, nana_file=None, lock_wait=0.0, stop_event=None,
           timeout=WATCHDOG_SECONDS, use_cache=True, log=print, keep_iso=False,
           label=None):
    """Run ONE costume candidate in the game under a declared capture profile.

    Args:
        candidate_file: the costume archive to verify. Its bytes are SEALED
            into ``<destination>/candidate/`` read-only, every archive member is
            hashed, and the test ISO is built from that copy -- a private
            verification package, not an export.
        character: the fighter the costume belongs to, e.g. 'Mewtwo'.
        destination: folder for the captures, the manifest and the sheet.
        profile: capture-profile version.
        vanilla_iso: clean Melee ISO; defaults to the configured one.
        lock_wait: seconds to QUEUE for the machine-wide Dolphin lock. 0 means
            do not wait: a busy Dolphin is reported and left alone.
        stop_event: a ``threading.Event``; setting it closes only the emulator
            instance this run owns.
        timeout: whole-run emergency ceiling. Each phase also has its own
            deadline (:data:`PHASE_DEADLINES`).
        use_cache: reuse a stored result whose canonical specification -- the
            candidate bytes, the profile, the engine and the toolchain --
            matches this run's, and whose evidence still hashes correctly.

    Returns:
        dict: the manifest (also written to ``<destination>/verification.json``).
    """
    timing = Timing()
    # ABSOLUTE from here on: MexCLI, Dolphin and the capture engine all run
    # from other working directories, and a relative path silently becomes a
    # different (or missing) file over there.
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    resolved = resolve_profile(profile)
    engine = engine_version()
    lines = []

    def say(message):
        lines.append(str(message))
        try:
            log(message)
        except Exception:
            pass

    source = Path(candidate_file).resolve()
    if not source.is_file():
        raise ValueError(f"Candidate archive not found: {source}")
    package = seal_candidate(source, destination / "candidate")
    sealed, candidate_hash = package["path"], package["sha256"]
    say(f"candidate {sealed.name} sha256:{candidate_hash[:16]}… "
        f"({package['bytes']} bytes, {len(package['members'])} member(s)), "
        f"sealed read-only for verification only")

    clean_iso = vanilla_iso or _configured_vanilla_iso()
    toolchain = toolchain_identity(clean_iso)
    spec = cache_spec(candidate_hash=candidate_hash,
                      member_hashes=package["members"],
                      profile_version=resolved["profile_version"],
                      engine=engine, toolchain=toolchain, character=character,
                      stage=resolved["stage"],
                      nana_hash=sha256_file(nana_file) if nana_file and
                      Path(nana_file).is_file() else None)
    key = cache_key(spec)
    cacheable = bool(engine.get("id")) and toolchain.get("complete")
    cache_file = cache_root() / f"{key}.json"
    if use_cache and cacheable and cache_file.is_file():
        try:
            stored = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            stored, refusal = None, f"the stored entry is unreadable: {exc}"
        else:
            refusal = validate_cached(stored, spec, key)
        if stored is not None and refusal is None:
            stored["cache"] = {"hit": True, "key": key, "spec": spec,
                               "stored": str(cache_file),
                               "note": "the canonical specification and every "
                                       "evidence hash matched; no boot was spent"}
            # A hit must still leave the manifest where the caller was told to
            # look for it, or the facade's advertised path is a lie.
            (destination / "verification.json").write_text(
                json.dumps(stored, indent=2, default=str), encoding="utf-8")
            say(f"cache hit {key[:16]}… -- the stored result is about these "
                f"exact bytes and its evidence still hashes")
            return stored
        if stored is not None:
            say(f"cache entry {key[:16]}… REFUSED: {refusal}")
    elif use_cache and not cacheable:
        say("caching is off for this run: "
            + ("the engine identity is unavailable"
               if not engine.get("id") else
               "part of the toolchain identity could not be established"))

    _raise_if_cancelled(stop_event)

    if not _RUN_LOCK.acquire(blocking=False):
        say("another verification is already running in this process")
        return _busy_manifest(
            destination, resolved, engine, candidate_hash, sealed, character,
            {"pid": os.getpid(), "purpose": "another verification in this process"},
            timing, key, spec, lines)
    try:
        lingering = abandoned_capture_threads()
        if lingering:
            say(f"{len(lingering)} capture thread(s) from an earlier stopped run "
                f"are still unwinding in this process; not starting another")
            return _busy_manifest(
                destination, resolved, engine, candidate_hash, sealed, character,
                {"pid": os.getpid(),
                 "purpose": "an earlier stopped verification run in this process"},
                timing, key, spec, lines)

        # --- 1. the machine-wide Dolphin lock, taken by THIS pid for the whole run
        from . import dolphin_lock
        purpose = f"verify_costume {label or sealed.name} ({character})"
        current = dolphin_lock.status()
        if current.get("stale"):
            owner = current.get("owner") or {}
            say(f"reclaiming a stale Dolphin lock from dead pid {owner.get('pid')} "
                f"({owner.get('purpose')})")
        elif current.get("locked"):
            owner = current.get("owner") or {}
            say(f"the Dolphin lock is held by live pid {owner.get('pid')} "
                f"({owner.get('purpose')})")
        t_lock = time.time()
        try:
            lock = dolphin_lock.acquire(purpose, wait=float(lock_wait or 0))
        except dolphin_lock.BusyError as exc:
            timing.add("lock_wait", time.time() - t_lock)
            owner = getattr(exc, "owner", {}) or {}
            say(f"Dolphin is busy (pid {owner.get('pid')}, "
                f"{owner.get('purpose')}) -- leaving it alone")
            return _busy_manifest(destination, resolved, engine, candidate_hash,
                                  sealed, character, owner, timing, key, spec,
                                  lines)
        timing.add("lock_wait", time.time() - t_lock)
        lease = lock.get("token")
        say(f"Dolphin lock held by pid {lock['pid']} under lease {lease}")

        return _run(destination=destination, resolved=resolved, engine=engine,
                    toolchain=toolchain, spec=spec, key=key, package=package,
                    character=character, clean_iso=clean_iso,
                    nana_file=nana_file, stop_event=stop_event, timeout=timeout,
                    keep_iso=keep_iso, use_cache=use_cache and cacheable,
                    cache_file=cache_file, timing=timing, say=say, lines=lines,
                    lease=lease)
    finally:
        _RUN_LOCK.release()


def _run(*, destination, resolved, engine, toolchain, spec, key, package,
         character, clean_iso, nana_file, stop_event, timeout, keep_iso,
         use_cache, cache_file, timing, say, lines, lease):
    """The part of `verify` that owns the machine. The lock is already held."""
    from . import dolphin_lock
    sealed = package["path"]
    candidate_hash = package["sha256"]
    run_error = None
    cancelled = False
    execution_failure = None
    batch = {}
    batch_row = {}
    sidecars = []
    iso_identity = {}
    color_index = None
    owned = {"session": None, "pid": None, "booted": False}
    deadline_at = time.monotonic() + float(timeout) if timeout else None
    shots_dir = destination / "captures"
    iso_target = destination / "verification.iso"
    try:
        _raise_if_cancelled(stop_event)
        # --- 2. build the test ISO from the sealed bytes
        with timing.phase("iso_build"):
            color_index = _deadline("iso_build", stop_event, say, _build_iso,
                                    sealed, character, iso_target, clean_iso,
                                    nana_file, say)
        say(f"test ISO built; the candidate landed in costume slot {color_index}")
        with timing.phase("iso_identity"):
            iso_identity = _iso_identity(iso_target, character, color_index,
                                         package, clean_iso, say)

        _raise_if_cancelled(stop_event)
        # --- 3. boot + capture, IN-PROCESS so the lock stays with this pid
        batch = _run_captures(iso_target, character, int(color_index), resolved,
                              shots_dir, timing, stop_event, timeout, say,
                              owned=owned, deadline_at=deadline_at)
        rows = batch.get("targets") or []
        batch_row = rows[0] if rows else {}
        sidecars = _read_sidecars(Path(batch_row.get("dir") or shots_dir))
        # The disc the captures were taken from must still be the disc that was
        # hashed: replacing it mid-run would otherwise go unremarked.
        iso_identity["sha256_after_capture"] = sha256_file(iso_target)
        iso_identity["unchanged_during_capture"] = (
            iso_identity["sha256_after_capture"] == iso_identity["sha256"])
    except Cancelled:
        cancelled = True
        run_error = "cancelled: only the emulator instance this run owned was stopped"
        say(run_error)
    except TimeoutError as exc:
        execution_failure = "timeout"
        run_error = f"timeout: {exc}"
        say(f"verification stopped: {run_error}")
    except Exception as exc:
        run_error = f"{type(exc).__name__}: {exc}"
        say(f"verification run failed: {run_error}")
    finally:
        # TEARDOWN ALWAYS RUNS, including on an exception and on the watchdog.
        # A boot that hangs (Slippi menu navigation spun for 626 s on
        # 2026-09-22) otherwise keeps an emulator on screen and the machine-wide
        # lock held for as long as the harness's own internal timeouts allow.
        t_down = time.time()
        _close_owned(owned, say, wait=10.0)
        if owned.get("session") is not None or owned.get("awaiting_launch"):
            # The worker had not launched yet when we stopped; give it a
            # bounded moment to reach (and fail) its launch, then close again.
            time.sleep(1.0)
            _close_owned(owned, say, wait=10.0)
        if owned.get("pid") and not owned.get("exited"):
            # Do NOT report a clean teardown over a child that is still there.
            execution_failure = execution_failure or "owned_child_not_confirmed_exited"
            run_error = run_error or (
                f"the emulator this run started (pid {owned['pid']}) could not "
                f"be confirmed exited; the machine-wide lock is kept")
            say(run_error)
        else:
            dolphin_lock.release(token=lease)
        timing.add("teardown", time.time() - t_down)
        if not keep_iso:
            try:
                iso_target.unlink()
                iso_identity["path"] = None
                iso_identity["note"] = ("the test ISO was deleted after the run; "
                                        "its sha256 remains the identity")
            except OSError:
                pass

    # --- 4. measure
    with timing.phase("checks"):
        evidence = execution_evidence(
            resolved=resolved,
            requested={"character": character,
                       "ckind": batch_row.get("ckind", _ckind(character)),
                       "costume_slot": color_index,
                       "iso_identity": iso_identity},
            batch_row=batch_row, sidecars=sidecars)
        appearance, captures = _appearance(resolved, evidence, batch_row,
                                           shots_dir)
        outcome, reasons = decide_outcome(
            evidence, appearance, run_error=run_error, cancelled=cancelled,
            profile_complete=resolved["complete"],
            execution_failure=execution_failure)
        sheet = contact_sheet([c["path"] for c in captures if c["path"]],
                              destination / "contact-sheet.png")

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "game_verification": {
            "profile_version": resolved["profile_version"],
            "candidate_hash": f"sha256:{candidate_hash}",
            "iso_identity": iso_identity,
            "costume_slot": None if color_index is None else int(color_index),
            "captures": captures,
            "ram_observations": {
                "schema": "gale01-verification-observations-v1",
                "live_identity": batch_row.get("live_identity"),
                "live_stage_state": batch_row.get("live_stage_state"),
                "per_capture": evidence["observations"],
            },
            "outcome": outcome,
            "timing": timing.result(),
        },
        "candidate": {"path": str(sealed), "sha256": candidate_hash,
                      "bytes": package["bytes"], "members": package["members"],
                      "sealed_read_only": package["sealed_read_only"],
                      "note": package["note"]},
        "execution_evidence": evidence,
        "appearance_checks": appearance,
        "outcome_reasons": reasons,
        "execution_failure": execution_failure,
        "profile": resolved,
        "engine_version": engine,
        "toolchain": toolchain,
        "cache": {"hit": False, "key": key, "spec": spec, "stored": None,
                  "deterministic": deterministic_unknown(outcome, reasons)},
        "contact_sheet": sheet,
        "limitations": _limitations(resolved, evidence, appearance),
        "run": {"character": character, "candidate": str(sealed),
                "destination": str(destination), "error": run_error,
                "execution_failure": execution_failure,
                "timed_out": execution_failure == "timeout",
                "cancelled": cancelled,
                "watchdog_seconds": float(timeout) if timeout else None,
                "phase_deadlines": dict(PHASE_DEADLINES),
                # the ONE emulator this run started, by pid, so a leftover is
                # attributable without matching a process by image name
                "owned_emulator_pid": owned["pid"],
                "coordinator_pid": os.getpid(),
                "lock_lease": lease,
                "capture_manifest": batch.get("_path"),
                "log_tail": "\n".join(lines[-200:])},
    }
    worth_remembering = (
        outcome in {"verified", "failed"}
        or deterministic_unknown(outcome, reasons))
    if use_cache and worth_remembering and run_error is None:
        # A measured verdict always says the same thing again. So does an
        # inconclusive one whose every reason is a bounded limitation of this
        # profile -- an actor that reaches the rendered boundary at a fixed
        # camera will reach it again, and re-booting for that on every
        # identical managed export buys nothing. A timeout or a busy emulator
        # is a fact about one moment and is never stored.
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            manifest["cache"]["stored"] = str(cache_file)
            _atomic_write_json(cache_file, manifest)
        except OSError:
            manifest["cache"]["stored"] = None
    _atomic_write_json(destination / "verification.json", manifest)
    say(f"outcome: {outcome}")
    return manifest


def _atomic_write_json(path, payload):
    """Write a record whole or not at all: a half-written one is a lie."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, default=str),
                         encoding="utf-8")
    file_retry.replace(temporary, path)
    return path


def _deadline(phase, stop_event, say, function, *args, **kwargs):
    """Run a blocking phase under its own monotonic deadline.

    The whole-run ceiling cannot tell a 15-second build from a stuck one. The
    worker is a daemon thread: an external tool it is blocked in (mexcli has no
    timeout of its own) cannot be interrupted from here, so the deadline
    reports an execution failure and the run stops waiting -- it does not claim
    to have killed anything it did not start.
    """
    limit = PHASE_DEADLINES.get(phase)
    if not limit:
        return function(*args, **kwargs)
    box = {}

    def work():
        try:
            box["value"] = function(*args, **kwargs)
        except BaseException as exc:                     # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=work, name=f"verify-{phase}", daemon=True)
    thread.start()
    started = time.monotonic()
    while thread.is_alive():
        if stop_event is not None and stop_event.is_set():
            raise Cancelled(f"cancelled during {phase}")
        if time.monotonic() - started > limit:
            _ABANDONED.append(thread)
            say(f"{phase} exceeded its {limit:.0f}s deadline; abandoning the "
                f"external tool it is blocked in")
            raise TimeoutError(f"the {phase} phase exceeded {limit:.0f}s")
        thread.join(0.25)
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _iso_identity(iso_target, character, color_index, package, clean_iso, say):
    """What was built, and whether the candidate's own bytes are on that disc.

    `totalCostumes - 1` is the builder's opinion of where the costume landed.
    Reading the slot back out of RAM proves which slot the engine LOADED, not
    which bytes that slot holds. So look for the candidate's DAT on the disc by
    CONTENT: if a file on the built ISO hashes to one of the sealed archive's
    members, the exact bytes that were verified are the exact bytes that were
    inserted, whatever the builder chose to call them.
    """
    identity = {
        "path": str(iso_target),
        "bytes": iso_target.stat().st_size,
        "sha256": sha256_file(iso_target),
        "builder": "projects.install.test_build.build_single_costume_iso",
        "character": character,
        "costume_slot": int(color_index),
        "base_iso": _content_identity(clean_iso),
        "candidate_members": package["members"],
    }
    identity.update(insertion_evidence(iso_target, clean_iso, package,
                                       character, say))
    return identity


# --- internals ------------------------------------------------------------------ #

def _raise_if_cancelled(stop_event):
    if stop_event is not None and stop_event.is_set():
        raise Cancelled("cancelled before the emulator was started")


def _ckind(character):
    from .char_select import ckind
    try:
        return int(ckind(character))
    except Exception:
        return None


def _build_iso(sealed, character, target, vanilla_iso, nana_file, say):
    from projects.install.test_build import build_single_costume_iso
    clean = vanilla_iso or _configured_vanilla_iso()
    if not clean:
        raise ValueError("No clean Melee ISO is configured, so a verification "
                         "package cannot be built.")
    say(f"building the verification package from {Path(clean).name}…")
    index = build_single_costume_iso(
        str(clean), character, str(sealed), str(target),
        nana_zip=str(nana_file) if nana_file else None, log=say)
    if not target.is_file() or not target.stat().st_size:
        raise ValueError("The verification build produced no ISO.")
    return int(index)


def _configured_vanilla_iso():
    try:
        from core import config
    except Exception:
        return None
    record = Path(config.STORAGE_PATH).resolve() / "vanilla_iso.json"
    if not record.is_file():
        return None
    try:
        path = json.loads(record.read_text(encoding="utf-8")).get("path")
    except (OSError, ValueError):
        return None
    return path if path and Path(path).is_file() else None


def _capture_args(iso, character, color, resolved, out_dir):
    """A frameshot Namespace straight from the CLI's own parser.

    Built from `build_parser()` so the profile can never drift from the flags:
    every default a capture depends on comes from the command line definition,
    and only the profile's own fields are overridden.
    """
    from devtools.frameshot import build_parser
    camera = resolved["camera"]
    argv = ["--iso", str(iso),
            "--char", str(character).lower().replace(" ", "").replace(".", ""),
            "--color", str(int(color)),
            "--stage", resolved["stage"],
            "--out", str(out_dir),
            "--closeup", "--plain-bg", camera["plain_bg"],
            "--fixed-camera",
            "--cam-dist", str(camera["cam_dist"]),
            "--cam-fov", str(camera["cam_fov"]),
            "--cam-height", str(camera["cam_height"]),
            "--cam-side", str(camera["cam_side"]),
            "--cam-pitch", str(camera["cam_pitch"]),
            "--on-hang", "abort"]
    for spec in shot_specs(resolved):
        argv += ["--shot", spec]
    return build_parser().parse_args(argv), argv


def _close_owned(owned, say, wait=10.0):
    """Close the ONE emulator instance this run started, if it is still open.

    Identity first: the retained `Session` object holds the `Popen` the harness
    itself created, and `close()` goes through that handle. Nothing here
    enumerates processes, matches an image name, or looks up a port owner --
    this machine hosts the app these agents run inside, and an image-wide kill
    would take the session down with the emulator.
    """
    session = owned.get("session")
    if session is None:
        return None
    boot = getattr(session, "boot", None)
    launched = boot is not None and getattr(boot, "proc", None) is not None
    if not launched:
        # NOTHING HAS BEEN LAUNCHED YET. Closing here and dropping the session
        # used to set `exited=True` -- "no process, so it is gone" -- and let
        # go of the reference, after which a child the worker launched a
        # moment later escaped the repeated-stop condition entirely. Keep
        # owning it and come back.
        owned["exited"] = False
        owned["awaiting_launch"] = True
        try:
            session.close(keep=True)
        except Exception as exc:
            say(f"pre-launch close raised: {exc}")
        return None
    owned["awaiting_launch"] = False
    owned["session"] = None
    owned["closed_session"] = session
    try:
        if getattr(boot, "pid", None):
            owned["pid"] = boot.pid
        say(f"teardown: closing the owned emulator instance "
            f"(pid {owned.get('pid')})")
        kept = session.close(keep=True)
    except Exception as exc:
        say(f"owned-session close raised: {exc}")
        kept = None
    # VERIFY THE CHILD IS GONE before this run stops claiming ownership of the
    # machine. Only the retained handle is consulted; nothing is enumerated.
    owned["exited"] = _await_owned_exit(session, wait, say)
    return kept


def _await_owned_exit(session, wait, say):
    """Poll the retained child handle until it exits, up to `wait` seconds."""
    boot = getattr(session, "boot", None)
    proc = getattr(boot, "proc", None) if boot is not None else None
    if proc is None:
        return True
    deadline = time.monotonic() + max(0.0, float(wait or 0))
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return True
        try:
            boot.terminate()
        except Exception:
            pass
        time.sleep(0.2)
    exited = proc.poll() is not None
    if not exited:
        say(f"the owned emulator (pid {getattr(proc, 'pid', '?')}) has not "
            f"exited after {wait:.0f}s; ownership is NOT being released quietly")
    return exited


def _run_captures(iso, character, color, resolved, out_dir, timing, stop_event,
                  timeout, say, owned=None, deadline_at=None):
    """Boot the isolated emulator and capture the profile. Owns exactly one
    Dolphin, closes exactly that one, and never matches a process by name.

    `owned` is the caller's record of what this run started: it is filled in as
    soon as the session object exists -- BEFORE the boot completes -- so the
    watchdog and the caller's `finally` can stop a boot that hangs, which is
    the case that otherwise holds the machine-wide lock for minutes.
    """
    from devtools import frameshot as fs

    out_dir.mkdir(parents=True, exist_ok=True)
    args, argv = _capture_args(iso, character, color, resolved, out_dir)
    say("capture argv: " + " ".join(argv))
    targets = [fs.make_target(args.char, args.color, fs.parse_shots(args),
                              tid=f"{args.char}-slot{args.color}")]

    owned = {"session": None, "pid": None} if owned is None else owned
    phases = {}
    result = {}

    def on_session(session):
        if session is None:
            owned["booted"] = True      # the engine let go of it
            return
        owned["session"] = session
        boot = getattr(session, "boot", None)
        if boot is not None and getattr(boot, "pid", None):
            # The second notification carries a launched child: that is the end
            # of the boot phase as far as the deadline is concerned.
            owned["pid"] = boot.pid
            owned["booted"] = True

    def work():
        try:
            rows, boots, kept = fs.run_targets(
                args, Path(iso).resolve(), targets, out_dir, False, None,
                timing=phases, on_session=on_session, stop_event=stop_event)
            result["targets"] = rows
            result["boots"] = boots
            result["kept_run_dirs"] = kept
        except BaseException as exc:            # noqa: BLE001 - reported below
            result["error"] = f"{type(exc).__name__}: {exc}"

    t0 = time.monotonic()
    boot_limit = PHASE_DEADLINES.get("boot")
    capture_limit = PHASE_DEADLINES.get("captures")
    thread = threading.Thread(target=work, name="verify-captures", daemon=True)
    thread.start()
    stopped, stopped_at, why = None, None, ""
    while thread.is_alive():
        elapsed = time.monotonic() - t0
        # The ceiling is ABSOLUTE, measured from the start of the whole run:
        # counting it from the first capture gave a slow build its minutes back
        # and made the advertised bound a fiction.
        expired = bool(deadline_at is not None and time.monotonic() > deadline_at)
        why = "the whole-run ceiling" if expired else ""
        if not expired and deadline_at is None and timeout and elapsed > float(timeout):
            expired, why = True, f"the {timeout:.0f}s ceiling"
        # PHASE deadlines, not only the ceiling. A boot that hangs in the
        # Slippi menus used to have ten minutes; it now has ninety seconds.
        if not expired and boot_limit and not owned.get("booted")                 and elapsed > boot_limit:
            expired, why = True, f"the {boot_limit:.0f}s boot deadline"
        if not expired and capture_limit and owned.get("booted")                 and elapsed > boot_limit + capture_limit:
            expired, why = True, f"the {capture_limit:.0f}s capture deadline"
        cancelled = stop_event is not None and stop_event.is_set()
        if stopped is None and (expired or cancelled):
            stopped, stopped_at = ("timeout" if expired else "cancelled"), time.monotonic()
            say(f"{stopped} after {elapsed:.0f}s ({why or 'cancelled'}): stopping "
                f"the emulator instance this run owns"
                + ("" if owned.get("session") is not None else " (none is open)"))
        if stopped is not None and (not owned.get("exited")
                                    or owned.get("awaiting_launch")
                                    or owned.get("session") is not None):
            # Keep stopping until the retained child is actually gone: the
            # worker may only now be reaching the launch it was preparing.
            # close() goes through DolphinBoot's RETAINED child handle. No name
            # sweep, no port owner lookup, nothing else on this machine is
            # touched -- and it happens even when the hang is in the BOOT, which
            # is when the session exists but has never finished opening.
            _close_owned(owned, say, wait=2.0)
        if stopped_at is not None and time.monotonic() - stopped_at > ABANDON_GRACE:
            # The emulator is already gone, so the machine is free; the capture
            # thread just has not noticed yet. Stop waiting on it, but REMEMBER
            # it: when it finally unwinds it will call DolphinBoot.terminate(),
            # which releases the machine-wide lock -- and a later run in this
            # same process must not have its lock pulled out from under it.
            say(f"the capture thread has not unwound {ABANDON_GRACE:.0f}s after "
                f"its emulator was stopped; abandoning it")
            _ABANDONED.append(thread)
            break
        thread.join(0.25)

    timing.add("boot", round(phases.get("boot_seconds", 0.0), 3))
    timing.add("teardown", round(phases.get("teardown_seconds", 0.0), 3))
    total = time.monotonic() - t0
    timing.add("captures", round(max(0.0, total
                                     - phases.get("boot_seconds", 0.0)
                                     - phases.get("teardown_seconds", 0.0)), 3))
    if stopped == "cancelled":
        raise Cancelled("cancelled: only the owned emulator instance was stopped")
    if stopped == "timeout":
        raise TimeoutError(f"boot/capture exceeded {why}")
    if result.get("error"):
        raise RuntimeError(result["error"])
    manifest_path = out_dir / "capture-manifest.json"
    payload = {"iso": str(iso), "stage": resolved["stage"],
               "seconds": round(total, 1), "boots": result.get("boots"),
               "boot_seconds": round(phases.get("boot_seconds", 0.0), 1),
               "teardown_seconds": round(phases.get("teardown_seconds", 0.0), 1),
               "capture": {"fit_mode": fs.fit_mode(args), **resolved["camera"]},
               "kept_run_dirs": result.get("kept_run_dirs") or [],
               "targets": result.get("targets") or []}
    manifest_path.write_text(json.dumps(payload, indent=2, default=str),
                             encoding="utf-8")
    payload["_path"] = str(manifest_path)
    return payload


def _read_sidecars(folder):
    rows = []
    for path in sorted(Path(folder).glob("*.json")):
        if path.name in {"capture-manifest.json", "verification.json"}:
            continue
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return [r for r in rows if isinstance(r, dict) and r.get("move")]


def _appearance(resolved, evidence, batch_row, shots_dir):
    """Per-frame appearance checks + the manifest's `captures` list."""
    folder = Path(batch_row.get("dir") or shots_dir)
    fits = {}
    for name, info in (batch_row.get("autofit") or {}).items():
        fits[name] = info
    checks, captures = [], []
    for row in evidence["observations"]:
        name = row.get("file")
        path = folder / name if name else None
        recorded = row.get("autofit") or (fits.get(name) if name else None)
        if path is None or not path.is_file():
            checks.append({"move": row["move"], "frame": row["frame"],
                           "path": str(path) if path else "",
                           "status": "unknown", "source": None,
                           "measurement": None,
                           "reason": "the profile asked for this frame and no "
                                     "capture exists for it"})
            captures.append({"move": row["move"], "frame": row["frame"],
                             "path": None, "hash": None})
            continue
        measured = measure_capture(path, resolved["appearance"], recorded,
                                   folder=folder)
        checks.append({"move": row["move"], "frame": row["frame"], **measured})
        capture = {"move": row["move"], "frame": row["frame"],
                   "path": str(path), "hash": f"sha256:{sha256_file(path)}"}
        # The measurement pair travels with the frame it explains, hashed, so
        # the check can be re-derived by anyone holding the manifest.
        evidence_pair = (measured.get("measurement") or {})
        for key in ("actor_file", "background_file"):
            name = evidence_pair.get(key)
            if name and (folder / name).is_file():
                capture.setdefault("measurement_pair", {})[key.split("_")[0]] = {
                    "path": str(folder / name),
                    "hash": f"sha256:{sha256_file(folder / name)}"}
        captures.append(capture)
    return checks, captures


def _limitations(resolved, evidence, appearance):
    out = []
    for entry in resolved["entries"]:
        if entry["status"] != "supported":
            out.append(f"profile entry {entry['id']!r} ({entry['label']}) is "
                       f"unsupported: {entry['reason']}")
    for check in evidence["checks"]:
        if check["status"] == "unknown":
            out.append(f"{check['check_id']}: {check['reason']}")
    for row in appearance:
        if row["status"] == "unknown":
            out.append(f"{row['move']}:{row['frame']}: {row['reason']}")
    return out


def _busy_manifest(destination, resolved, engine, candidate_hash, sealed,
                   character, owner, timing, key, spec, lines):
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "game_verification": {
            "profile_version": resolved["profile_version"],
            "candidate_hash": f"sha256:{candidate_hash}",
            "iso_identity": {},
            "costume_slot": None,
            "captures": [],
            "ram_observations": {
                "schema": "gale01-verification-observations-v1",
                "live_identity": None, "live_stage_state": None,
                "per_capture": []},
            "outcome": "incomplete",
            "timing": timing.result(),
        },
        "execution_evidence": {"status": "incomplete", "checks": [
            _check("dolphin_available", "unknown", expected="the machine's "
                   "single Dolphin slot", observed=owner,
                   reason="another live process holds the machine-wide Dolphin "
                          "lock; it was left alone and nothing was built or "
                          "booted", critical=True)],
            "missing_captures": [], "observations": []},
        "appearance_checks": [],
        "outcome_reasons": ["dolphin_busy"],
        "profile": resolved,
        "engine_version": engine,
        "cache": {"hit": False, "key": key, "spec": spec, "stored": None},
        "contact_sheet": None,
        "execution_failure": "dolphin_busy",
        "limitations": ["no measurement was taken: the emulator was busy"],
        "run": {"character": character, "candidate": str(sealed),
                "destination": str(destination), "error": "dolphin_busy",
                "capture_manifest": None, "log_tail": "\n".join(lines[-200:])},
    }
    _atomic_write_json(Path(destination) / "verification.json", manifest)
    return manifest


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        description="verify one costume candidate in the actual game")
    ap.add_argument("candidate", help="costume .zip to verify")
    ap.add_argument("character", help="the fighter it belongs to, e.g. Mewtwo")
    ap.add_argument("--out", required=True, help="artifacts folder")
    ap.add_argument("--profile", default=PROFILE_VERSION)
    ap.add_argument("--iso", default=None, help="clean Melee ISO override")
    ap.add_argument("--lock-wait", type=float, default=0.0)
    ap.add_argument("--timeout", type=float, default=WATCHDOG_SECONDS)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--keep-iso", action="store_true")
    ap.add_argument("--label", default=None)
    args = ap.parse_args(argv)
    manifest = verify(args.candidate, args.character, destination=args.out,
                      profile=args.profile, vanilla_iso=args.iso,
                      lock_wait=args.lock_wait, timeout=args.timeout,
                      use_cache=not args.no_cache, keep_iso=args.keep_iso,
                      label=args.label)
    print(json.dumps(manifest["game_verification"]["timing"], indent=2))
    print("outcome:", manifest["game_verification"]["outcome"])
    for reason in manifest["outcome_reasons"]:
        print(f"  - [{reason['code']}] {reason['check']}: {reason['detail']}")
    return 0 if manifest["game_verification"]["outcome"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
