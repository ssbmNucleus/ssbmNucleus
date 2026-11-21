"""Native pipe/memory input comparison worker; one locked Dolphin per process.

Run once per backend with different --out directories, then compare captures.
--backend memory explicitly permits QA with the default ONE lock slot. Never
increase slots on a small laptop. Six desktop workers each run this same flow.
Uses frameshot's real solo navigation, character switching and move captures.
"""
import argparse
import ctypes
import ctypes.wintypes as wt
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / 'app' / 'backend'), str(REPO)]
from devtools import frameshot as fs
from shared.ingame import dolphin_lock, framestep
from shared.ingame.boot import DolphinBoot
from shared.ingame.gamestate import Player
from tools.ingame.input_evidence import capture_input_evidence
from tools.ingame.owned_session import close_owned_session


def foreground_pid():
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetForegroundWindow.restype = wt.HWND
    user.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    pid = wt.DWORD()
    user.GetWindowThreadProcessId(user.GetForegroundWindow(), ctypes.byref(pid))
    return pid.value


def verify_owned(boot, protected):
    """Verify command line as well as the shared retained-handle/ancestry guard."""
    import psutil
    proc = boot.proc
    if proc is None or proc.poll() is not None:
        return None
    process = psutil.Process(proc.pid)
    forbidden = set(protected) | {os.getpid()} | {p.pid for p in psutil.Process().parents()}
    command = process.cmdline()
    if (proc.pid in forbidden or process.ppid() != os.getpid()
            or Path(process.exe()).resolve() != Path(boot.exe).resolve()
            or command != list(proc.args)):
        raise RuntimeError("Refusing cleanup: retained Dolphin child identity changed")
    return {"pid": proc.pid, "parent": process.ppid(), "command": command}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--backend", choices=("pipe", "memory"), required=True)
    parser.add_argument("--wait-for-dolphin", type=float, default=120)
    parser.add_argument("--background", action="store_true",
                        help="return focus to the pre-boot window before every input; require unfocused delivery")
    parser.add_argument("--protected-pid", type=int, action="append", default=[])
    parser.add_argument("--deterministic-visuals", action="store_true",
                        help="hide native HUD and seed HSD RNG before each move for pixel comparisons")
    options = parser.parse_args()
    out = Path(options.out).resolve()
    out.mkdir(parents=True, exist_ok=False)  # immutable evidence, no old PNG reuse
    log_file = (out / "run.log").open("w", encoding="utf-8")

    def log(message):
        print(message, flush=True)
        print(message, file=log_file, flush=True)

    import harness_mcp
    status = harness_mcp.t_dolphin_status({}, log)
    log("dolphin_status: " + json.dumps(status))
    # Pass queue budget to the same chokepoint used by MCP wait_for_dolphin.
    os.environ["MELEE_DOLPHIN_LOCK_WAIT"] = str(options.wait_for_dolphin)
    if os.environ.get("MELEE_DOLPHIN_LOCK") == "0":
        raise RuntimeError("Verification requires the machine-wide Dolphin lock")
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetForegroundWindow.restype = wt.HWND
    user.SetForegroundWindow.argtypes = [wt.HWND]
    previous_window = user.GetForegroundWindow()
    receipt = {"backend": options.backend, "status_before": status,
               "iso": str(Path(options.iso).resolve()), "targets": [],
               "deterministic_visuals": options.deterministic_visuals,
               "started_utc": datetime.now(timezone.utc).isoformat(),
               "input_samples": [], "focus_samples": [], "success": False}

    class ProbeBoot(DolphinBoot):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs, input_backend=options.backend)

        def terminate(self):
            identity = verify_owned(self, options.protected_pid)
            if identity:
                receipt["owned_process"] = identity
                log("owned cleanup identity: " + json.dumps(identity))
            return super().terminate()

        def open_pipe(self, *args, **kwargs):
            controller = super().open_pipe(*args, **kwargs)
            original_frame = controller.frame

            def frame(lines):
                if options.background and foreground_pid() == self.pid:
                    user.SetForegroundWindow(previous_window)
                    time.sleep(0.05)
                foreground = foreground_pid()
                receipt["focus_samples"].append({"dolphin": self.pid, "foreground": foreground})
                if options.background and foreground == self.pid:
                    raise RuntimeError("Could not establish background input: Dolphin still has focus")
                return original_frame(lines)
            controller.frame = frame
            return controller

    fs.DolphinBoot = ProbeBoot
    if options.deterministic_visuals:
        class SeededMoves(fs.MoveRunner):
            def execute(self, *args, **kwargs):
                # GALE01 random.c seed_ptr, and capture.py's existing HUD flag.
                # This profile changes only the comparison fixture, not input.
                seed_pointer = self.d.u32(0x804D5F94)
                if (seed_pointer is None or seed_pointer % 4
                        or not 0x80003000 <= seed_pointer <= 0x817FFFFC):
                    raise RuntimeError("Invalid HSD RNG pointer")
                if not self.d.write_u32(seed_pointer, 0x12345678):
                    raise RuntimeError("Could not seed visual comparison")
                from shared.ingame.capture import HUD_FLAG_ADDR
                if not self.d.write_u8(HUD_FLAG_ADDR, 1):
                    raise RuntimeError("Could not hide HUD for visual comparison")
                return super().execute(*args, **kwargs)
        fs.MoveRunner = SeededMoves
    args = fs.build_parser().parse_args([
        "--iso", options.iso, "--closeup", "--plain-bg", "404040", "--no-autofit",
        "--no-control-cache", "--keep-run"])
    session = fs.Session(args, Path(options.iso).resolve(), log=log)
    try:
        with dolphin_lock.hold("verify " + options.backend + " input", wait=options.wait_for_dolphin):
            try:
                session.open()
                receipt["lock_slot"] = dolphin_lock.current_slot()
                receipt["ready_utc"] = datetime.now(timezone.utc).isoformat()
                receipt["dolphin_pid"] = session.boot.pid
                receipt["run_directory"] = str(session.boot.run_dir)
                with open(session.boot.exe, "rb") as executable:
                    receipt["executable_sha256"] = hashlib.file_digest(executable, "sha256").hexdigest()
                for char in ("marth", "mario", "fox"):
                    if receipt["targets"] and not fs.recover_to_css(session, log=log):
                        raise RuntimeError("Could not recover to offline CSS")
                    target = fs.make_target(char, 0, [
                        ("jab", [3]), ("ftilt", [4]), ("fair", [4]), ("upb", [5])])
                    ok, reason = fs.start_match(session, args, target, None, log=log)
                    if not ok:
                        raise RuntimeError(reason)
                    # First establish raw input parity, bracketed by game frames.
                    # Capture every button plus sticks/triggers; stay frozen until
                    # each native game snapshot has consumed the held stimulus.
                    player = Player(session.d)
                    player.resolve()
                    for commands in (["SET MAIN .689 .311", "SET C .25 .75", "SET L .5"],
                                     ["PRESS A", "PRESS B", "PRESS X", "PRESS Y", "PRESS Z", "PRESS L", "PRESS R"]):
                        session.p.neutral()
                        session.p.frame(list(commands) + ["FLUSH"])
                        time.sleep(0.05)   # same pipe settle used by MoveRunner
                        if framestep.step(session.d, 1) != 1:
                            raise RuntimeError("Input sample frame step was not exact")
                        before = session.d.u32(0x80479D60)
                        evidence = capture_input_evidence(session.d, player.ft)
                        after = session.d.u32(0x80479D60)
                        if before != after:
                            raise RuntimeError("Input evidence was not frozen")
                        receipt["input_samples"].append({"char": char, "commands": commands,
                            "game_frame": before, "evidence": evidence})
                    session.p.neutral()
                    result = fs.run_shots(session, args, target, None, out / char, log=log)
                    receipt["targets"].append({"char": char, **result})
                    if (result["failures"] or result["broken"] or result["unproven"]
                            or len(result["images"]) != 4):
                        raise RuntimeError("Native frameshot failed: " + char)
                receipt["success"] = True
            except Exception as exc:
                receipt["error"] = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                # Persist evidence even when a capture or cleanup fails.
                try:
                    receipt["cleanup"] = close_owned_session(
                        session, protected_pids=tuple(options.protected_pid))
                except Exception as exc:
                    receipt["success"] = False
                    receipt["cleanup_error"] = f"{type(exc).__name__}: {exc}"
                    raise
                finally:
                    receipt["finished_utc"] = datetime.now(timezone.utc).isoformat()
                    (out / "verification.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    finally:
        log_file.close()
    print(str(out / "verification.json"), flush=True)


if __name__ == "__main__":
    main()
