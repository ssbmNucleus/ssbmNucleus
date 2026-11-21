"""
fps_batch.py -- boot a LIST of ISOs in sequence, measure CSS health, and print
a HEALTHY / DEGRADED / HUNG verdict + summary table.

Modes:
  offline  -> offline VS character select, matching console / local-play usage
  online   -> Slippi Online / unranked CSS, matching Dolphin netplay usage
  both     -> boot each ISO twice and score both modes independently

The online CSS loads more memory than the offline VS CSS. Use --mode online when
pinning the Dolphin/Slippi costume limit; use --mode offline for the console
limit. Every nav step has an internal timeout so a hung build scores HUNG and the
batch moves to the next ISO.

Run from backend/:
  python devtools/fps_batch.py --mode offline ../output/count-450.iso ...
  python devtools/fps_batch.py --mode online  ../output/count-450.iso ...
  python devtools/fps_batch.py --mode both    ../output/count-450.iso ...
  python devtools/fps_batch.py                # no args -> all output/count-*.iso, offline
"""
import argparse
import glob
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/
from core.config import STORAGE_PATH  # noqa: E402
from shared.ingame.boot import DolphinBoot, dolphin_running  # noqa: E402
from shared.ingame.melee_mem import Dolphin  # noqa: E402
from shared.ingame.melee_pipe import Pipe  # noqa: E402
from shared.ingame.melee_css import Cursor  # noqa: E402
from shared.ingame import nav, match_setup  # noqa: E402

RUNS = STORAGE_PATH / "test-runs"
FRAME_COUNTER = 0x80479D60
ONLINE_CSS = 0x08
RESULTS = (STORAGE_PATH.parent / "output" / "count-fps-results.txt").resolve()


def log(m):
    print(m, flush=True)


def measure(d, secs):
    """(fps, (f0, f1)) over `secs` wall-clock; fps None if counter unreadable."""
    f0 = d.u32(FRAME_COUNTER)
    t0 = time.time()
    time.sleep(secs)
    f1 = d.u32(FRAME_COUNTER)
    t1 = time.time()
    if f0 is None or f1 is None:
        return None, (f0, f1)
    df = (f1 - f0) & 0xFFFFFFFF
    return df / (t1 - t0), (f0, f1)


def classify(css_fps):
    if css_fps is None:
        return "HUNG"
    if css_fps < 5:
        return "HUNG"
    if css_fps < 40:
        return "DEGRADED"
    return "HEALTHY"


def fps_from_samples(samples):
    if len(samples) < 2:
        return None
    t0, f0 = samples[0]
    t1, f1 = samples[-1]
    if t1 <= t0:
        return None
    return ((f1 - f0) & 0xFFFFFFFF) / (t1 - t0)


def exit_online_css(p):
    """Hold B to leave the online CSS before matchmaking can complete."""
    try:
        p.press("B")
        time.sleep(1.3)
        p.release("B")
        time.sleep(0.8)
    except Exception:
        pass


def probe_online_css(d, p, watch_secs=8.0):
    """Enter the Slippi online CSS, watch frame health, then back out.

    Returns (verdict, css_fps, note). This intentionally does not try to select
    anyone or enter a match; reaching the online CSS is enough to load the CSPs
    whose memory budget we are measuring.
    """
    reached = False
    try:
        p.neutral()
        if not nav.wait_menu_ready(d, log=log):
            return "NO-MENU", None, "boot menu never became input-ready"
        if d.u8(nav.SCENE_MAJOR) != ONLINE_CSS:
            log("entering Slippi online CSS (A from Online Play)")
            p.tap("A", 0.08)

        start = time.time()
        samples = []
        last_frame = None
        frozen = 0.0
        while time.time() - start < watch_secs:
            time.sleep(0.3)
            if not d.alive() or not d.locate():
                return "CRASH", fps_from_samples(samples), "process/RAM gone"
            scene = d.u8(nav.SCENE_MAJOR)
            frame = d.u32(FRAME_COUNTER)
            now = time.time()
            if scene == ONLINE_CSS:
                reached = True
                if frame is not None:
                    samples.append((now, frame))
            if frame is None or frame == last_frame:
                frozen += 0.3
                if frozen > 2.5:
                    fps = fps_from_samples(samples)
                    return "HUNG", fps, f"frame frozen >2.5s in scene 0x{scene:02x}"
            else:
                frozen = 0.0
                last_frame = frame

        if not reached:
            scene = d.u8(nav.SCENE_MAJOR)
            return "NO-ENTRY", None, f"never reached online CSS (scene 0x{scene:02x})"
        fps = fps_from_samples(samples)
        return classify(fps), fps, f"online CSS loaded, watched {watch_secs:.1f}s"
    finally:
        if reached:
            exit_online_css(p)


def probe_offline_css(d, p, res):
    """Navigate to offline VS CSS and measure a clean fps window there."""
    match_setup.patch_one_player(d, log=log)
    reached = nav.nav_to_css(d, p, log=log)
    if not reached:
        # The menu->CSS hop advances the frame counter; a hang before/at the
        # transition shows up as a frozen counter here too.
        cfps, ctr = measure(d, 4.0)
        res["css_fps"] = round(cfps, 1) if cfps is not None else None
        res["verdict"] = "HUNG" if (cfps is not None and cfps < 5) else "NAV-FAIL"
        res["note"] = f"nav_to_css failed; counter {ctr}"
        return res

    nav.wait_css_ready(d, Cursor(d, p), log=log)
    # The costume preload is what hangs; give the CSS a moment to either reach
    # steady 60 fps or freeze, then measure a clean 5 s window.
    time.sleep(2.0)
    cfps, ctr = measure(d, 5.0)
    res["css_fps"] = round(cfps, 1) if cfps is not None else None
    res["verdict"] = classify(cfps)
    if cfps is None:
        res["note"] = f"counter unreadable {ctr}"
    return res


def probe(iso, mode):
    """Boot one ISO, navigate to the requested CSS, measure health."""
    res = {"iso": Path(iso).name, "mode": mode, "menu_fps": None, "css_fps": None,
           "verdict": "ERROR", "note": ""}
    # Absolute: Dolphin launches with cwd=<exe dir>, so a relative ISO path would
    # resolve against the Slippi folder and "die during boot" (file not found).
    p_iso = Path(iso).resolve()
    if not p_iso.exists():
        # Don't hand Dolphin a missing file (it exits ~4s with code 3, which looks
        # exactly like a crash). output/ is auto-cleaned, so ISOs can vanish.
        res["verdict"] = "MISSING"
        res["note"] = "ISO file not found (output/ is auto-cleaned?)"
        return res
    boot = DolphinBoot(str(p_iso), None, str(RUNS), log=log)
    p = None
    try:
        boot.prepare()
        boot.launch()
        if not boot.wait_for_pipe(timeout=60):
            res["verdict"] = "NO-BOOT"
            res["note"] = "pipe never appeared (crash/abort during disc load)"
            return res
        d = Dolphin(boot.pid)
        t0 = time.time()
        while not d.locate() and time.time() - t0 < 30:
            if not d.alive():
                res["verdict"] = "CRASH"
                res["note"] = "process died during boot"
                return res
            time.sleep(0.4)
        if d.base is None:
            res["verdict"] = "NO-MEM1"
            res["note"] = "MEM1 base never resolved"
            return res

        mfps, _ = measure(d, 3.0)
        res["menu_fps"] = round(mfps, 1) if mfps is not None else None

        p = Pipe(boot.pipe_index)
        if mode == "online":
            verdict, cfps, note = probe_online_css(d, p)
            res["verdict"] = verdict
            res["css_fps"] = round(cfps, 1) if cfps is not None else None
            res["note"] = note
            return res
        return probe_offline_css(d, p, res)
    except Exception as e:  # noqa: BLE001 - want the batch to survive any single ISO
        res["verdict"] = "EXC"
        res["note"] = f"{type(e).__name__}: {e}"
        return res
    finally:
        try:
            if p:
                p.close()
        except Exception:
            pass
        boot.cleanup()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("offline", "online", "both"),
        default="offline",
        help="CSS mode to score: offline VS, Slippi online, or both",
    )
    parser.add_argument("isos", nargs="*")
    return parser.parse_args()


def main():
    args = parse_args()
    isos = args.isos
    if not isos:
        out = STORAGE_PATH.parent / "output"
        isos = sorted(glob.glob(str(out / "count-*.iso")))
    if not isos:
        raise SystemExit("no ISOs given and no output/count-*.iso found")

    open_dolphins = dolphin_running()
    if open_dolphins:
        log(f"WARNING: a Dolphin EMULATOR is already open (pids {open_dolphins}). "
            f"It steals input focus -- close it or results are unreliable.")

    modes = ["offline", "online"] if args.mode == "both" else [args.mode]
    log(f"probing {len(isos)} ISO(s), mode={args.mode}:")
    for i in isos:
        log(f"  - {Path(i).name}")

    results = []
    for iso in isos:
        for mode in modes:
            log("")
            log(f"################ {Path(iso).name} [{mode}] ################")
            r = probe(iso, mode)
            results.append(r)
            log(f"  -> {r['verdict']}  "
                f"(mode={r['mode']} menu={r['menu_fps']} css={r['css_fps']})  "
                f"{r['note']}")
            time.sleep(4)

    log("")
    log("==================== SUMMARY ====================")
    lines = [f"  {'ISO':<22} {'MODE':<7} {'VERDICT':<9} {'CSS fps':>8} {'MENU fps':>9}  note"]
    for r in results:
        lines.append(f"  {r['iso']:<22} {r['mode']:<7} {r['verdict']:<9} "
                     f"{str(r['css_fps']):>8} {str(r['menu_fps']):>9}  {r['note']}")
    table = "\n".join(lines)
    log(table)

    try:
        RESULTS.parent.mkdir(parents=True, exist_ok=True)
        with open(RESULTS, "w", encoding="utf-8") as f:
            f.write(f"count-limit CSS fps probe (mode={args.mode})\n")
            f.write(table + "\n")
        log(f"\nwrote {RESULTS}")
    except Exception as e:  # noqa: BLE001
        log(f"(could not write results file: {e})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
