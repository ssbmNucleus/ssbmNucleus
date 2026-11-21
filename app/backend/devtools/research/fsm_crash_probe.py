"""
fsm_crash_probe.py -- pin down the FSM-engine hang with Deoxys (GodMewtwo FSM).

Uses the in-app ingame engine (backend/shared/ingame): solo memory-select (no CPU,
no CSS cursor), force-load Final Destination, then:
  phase 1: idle ~20s   (repro: fidget anims Wait2/Wait3 = FSM subactions 18/19
                        fire after ~10s idle; prior run hung at frame 685)
  phase 2: taunt D_UP  (user-reported crash; appeal subactions are FSM entries)
Samples (global frame, p1 action state, anim frame) the whole time and prints
the exact state at the freeze.

Run from backend/:  python devtools/research/fsm_crash_probe.py [--iso <path>]
The default ISO is the harness-test build (FSM-patched Deoxys at ckind 0x1A).
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/

from core.config import STORAGE_PATH, PROJECT_ROOT  # noqa: E402

from shared.ingame.boot import DolphinBoot  # noqa: E402
from shared.ingame.melee_mem import Dolphin  # noqa: E402
from shared.ingame.melee_pipe import Pipe  # noqa: E402
from shared.ingame.melee_css import Cursor  # noqa: E402
from shared.ingame.melee_sss import StageCursor, INTERNAL_STAGE_ID  # noqa: E402
from shared.ingame.observe import wait_in_game, wait_game_frames  # noqa: E402
from shared.ingame import nav, match_setup  # noqa: E402
from shared.ingame import screenshot as shot  # noqa: E402

ART = PROJECT_ROOT.parent / "tests" / "artifacts" / "fsm-probe"
RUNS_ROOT = STORAGE_PATH / "test-runs"
DEFAULT_ISO = PROJECT_ROOT / "output" / "harness-test.iso"

DEOXYS_CKIND = 0x1A  # first added m-ex fighter = external/CSS id 0x1A

FRAME_COUNTER = 0x80479D60
STATIC_PLAYER = 0x80453080
STATIC_STRIDE = 0xE90


def log(m):
    print(m, flush=True)


def snap(boot, name):
    png = None
    try:
        png = shot.capture_via_printwindow(boot.pid, max_width=960)
    except Exception:
        png = None
    if not png:
        try:
            png = shot.capture_png(boot.pid, max_width=960)
        except Exception:
            png = None
    if png:
        (ART / f"{name}.png").write_bytes(png)
        log(f"  shot -> {name}.png")


def ft_data(d, port=0):
    gobj = d.u32(STATIC_PLAYER + STATIC_STRIDE * port + 0xB0)
    return d.u32(gobj + 0x2C) if gobj else None


def sample_until_hang(d, ft, seconds, label):
    """Sample frame/state/subaction/anim continuously; return ('hung'|'ok', trail).
    Logs every change of (action state, +0x70, +0x74) -- the engine compares FSM
    entries against the +0x70/+0x74 fields, so these identify the exact match."""
    trail = []          # (gf, state, a70, a74, anim) change events
    t_end = time.time() + seconds
    last_gf = None
    frozen_at = None
    last_key = None
    while time.time() < t_end:
        gf = d.u32(FRAME_COUNTER)
        st = d.u32(ft + 0x10)
        a70 = d.u32(ft + 0x70)
        a74 = d.u32(ft + 0x74)
        af = d.f32(ft + 0x894)
        if gf != last_gf:
            last_gf = gf
            frozen_at = None
            key = (st, a70, a74)
            if key != last_key:
                last_key = key
                trail.append((gf, st, a70, a74, af))
                log(f"  [{label}] frame {gf}: state=0x{st:X} +70=0x{a70:X} "
                    f"+74=0x{a74:X} anim={None if af is None else round(af, 1)}")
        else:
            if frozen_at is None:
                frozen_at = time.time()
            elif time.time() - frozen_at > 2.0:
                log(f"  [{label}] HUNG at frame {gf}: state=0x{st:X} +70=0x{a70:X} "
                    f"+74=0x{a74:X} anim={None if af is None else round(af, 2)}")
                trail.append((gf, st, a70, a74, af))
                return "hung", trail
        time.sleep(0.004)
    return "ok", trail


def main():
    iso = DEFAULT_ISO
    if "--iso" in sys.argv:
        iso = Path(sys.argv[sys.argv.index("--iso") + 1])
    if not iso.exists():
        raise SystemExit(f"ISO missing: {iso}")
    ART.mkdir(parents=True, exist_ok=True)
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)

    boot = DolphinBoot(str(iso), None, str(RUNS_ROOT), log=log)
    p = None
    try:
        boot.prepare()
        boot.launch()
        if not boot.wait_for_pipe(timeout=45):
            raise SystemExit("input pipe never appeared")
        d = Dolphin(boot.pid)
        t0 = time.time()
        while not d.locate() and time.time() - t0 < 20:
            if not d.alive():
                raise SystemExit("Dolphin died during boot")
            time.sleep(0.4)
        if d.base is None:
            raise SystemExit("could not locate MEM1")

        solo = match_setup.patch_one_player(d, log=log)
        p = Pipe(boot.pipe_index)
        if not nav.nav_to_css(d, p, log=log):
            raise SystemExit("never reached the offline CSS")
        cur = Cursor(d, p)
        nav.wait_css_ready(d, cur, log=log)
        match_setup.force_time_infinite(d, log=log)

        log(f"memory-select Deoxys (ckind=0x{DEOXYS_CKIND:02X}) solo...")
        match_setup.write_solo_player(d, DEOXYS_CKIND, 0)
        match_setup.warp_to_stage_select(d)
        sc = StageCursor(d, p)
        if not sc.wait_for_stage_select(timeout=8.0):
            raise SystemExit("CSS->SSS warp did not land")
        match_setup.write_solo_player(d, DEOXYS_CKIND, 0)
        if not sc.force_select(INTERNAL_STAGE_ID["finaldestination"]):
            raise SystemExit("match never started")
        log("match started on FD")

        wait_in_game(d, timeout=20.0)
        wait_game_frames(d, 200)  # past READY/GO
        ft = ft_data(d)
        log(f"p1 ftData=0x{ft:08X}")
        snap(boot, "1-spawn")

        log("phase 1: idle 20s (fidget anims = FSM subactions 18/19)...")
        v, trail = sample_until_hang(d, ft, 20.0, "idle")
        if v == "hung":
            snap(boot, "2-idle-hang")
            log(f"IDLE HANG. trail: {[(g, hex(s), a) for g, s, a in trail[-8:]]}")
            return 1

        log("phase 2: taunt (D_UP)...")
        p.tap("D_UP", 0.1)
        v, trail = sample_until_hang(d, ft, 10.0, "taunt")
        snap(boot, "3-after-taunt")
        if v == "hung":
            log(f"TAUNT HANG. trail: {[(g, hex(s), a) for g, s, a in trail[-8:]]}")
            return 1

        log("NO HANG observed in either phase")
        return 0
    finally:
        try:
            if p:
                p.close()
        except Exception:
            pass
        boot.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
