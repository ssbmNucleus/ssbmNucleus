"""
harness_mcp.py -- MCP (Model Context Protocol) server for the in-game test
harness, so AI agents get the CORRECT path (backend/shared/ingame solo engine) as
first-class, schema-described tools instead of rediscovering -- and misusing --
the raw scripts (the recurring tools/ingame/dolphin/ + cpustep + CPU mistake).

Zero dependencies beyond the backend's own: speaks line-delimited JSON-RPC 2.0
over stdio (the MCP stdio transport) with plain stdlib. No `mcp` package.

Register in Claude Code (project .mcp.json):

    {
      "mcpServers": {
        "melee-harness": {
          "command": "python",
          "args": ["C:/path/to/ssbmNucleus/tools/harness/harness_mcp.py"]
        }
      }
    }

Two tool families:

- ONE-SHOT wrappers around the proven CLIs, run as subprocesses:
  `frameshot` (frame-exact move screenshots), `effect_probe` (spec-driven live
  DAT pokes), `run_ingame_test` (full PASS/CRASH/HUNG verdict on a built ISO).

- a persistent LIVE SESSION (the big win: boot Dolphin ONCE, then interact
  across many tool calls): `boot_match` -> `do_move` / `step` / `send_input` /
  `screenshot` / `game_state` / `read_ram` / `write_ram` / `poke_dat` /
  `set_player` / `freeze` -> `end_session`. The session is the solo no-CPU
  no-cursor engine, frozen via the retail debug-pause bits, exactly like
  frameshot.py (whose helpers it reuses).

Long calls (boot ~60-90 s) stream MCP progress notifications, which Claude
Code uses to reset its tool timeout. If calls still time out, set
MCP_TOOL_TIMEOUT=600000 in the client environment.

stdout is the JSON-RPC channel: this file dups fd 1 for the protocol and
points sys.stdout at stderr, so stray print()s inside harness modules can
never corrupt a message.
"""
import atexit
import base64
import bisect
import io
import json
import os
import re
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

# This file lives in <repo>/tools/harness/; the backend it drives is <repo>/app/backend.
REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "app" / "backend"
INGAME_TOOLS = REPO_ROOT / "tools" / "ingame"     # the Dolphin driver and smoke runners
DEV_TOOLS = REPO_ROOT / "tools" / "dev"
sys.path.insert(0, str(BACKEND))

# ---------------------------------------------------------------------------
# JSON-RPC over stdio (MCP stdio transport: one JSON object per line)
# ---------------------------------------------------------------------------
_RPC = None                            # initialized only by the stdio entry point

def _send(obj):
    if _RPC is None:
        raise RuntimeError("MCP stdio is not initialized")
    _RPC.write((json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8"))

def _reply(req_id, result):
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})

def _reply_err(req_id, code, message):
    _send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})

def _notify(method, params):
    _send({"jsonrpc": "2.0", "method": method, "params": params})


class Progress:
    """Forwards harness log lines as MCP progress notifications (and to
    stderr) so long tool calls stay alive and visible."""

    def __init__(self, token):
        self.token = token
        self.n = 0

    def __call__(self, message):
        message = str(message).strip()
        if not message:
            return
        print(f"[harness] {message}", file=sys.stderr, flush=True)
        if self.token is not None:
            self.n += 1
            _notify("notifications/progress",
                    {"progressToken": self.token, "progress": self.n,
                     "message": message})


# ---------------------------------------------------------------------------
# Harness imports (after sys.path setup)
# ---------------------------------------------------------------------------
from devtools import frameshot as fs                                        # noqa: E402
from core.config import PROJECT_ROOT, RESOURCES_DIR, MEXCLI_PATH, HSDRAW_EXE   # noqa: E402
from core.child_procs import own   # noqa: E402
from shared.ingame.boot import DolphinBoot, _write_ini                 # noqa: E402
from shared.ingame.melee_mem import Dolphin                            # noqa: E402
from shared.ingame.melee_css import Cursor                             # noqa: E402
from shared.ingame.melee_sss import StageCursor, INTERNAL_STAGE_ID     # noqa: E402
from shared.ingame.observe import wait_in_game, wait_game_frames       # noqa: E402
from shared.ingame import nav, match_setup, framestep                  # noqa: E402
from shared.ingame import screenshot as shot                           # noqa: E402
from shared.ingame.char_select import CKIND                            # noqa: E402
from shared.ingame.moves import MoveRunner, MoveError, MOVES, park_bag # noqa: E402
from shared.ingame.gamestate import Bag, Player, state_name            # noqa: E402
from shared.ingame.datram import DatRam                                # noqa: E402
from shared.ingame import dolphin_lock                                 # noqa: E402
from shared.ingame.boot import dolphin_running                         # noqa: E402

FRAME_COUNTER = 0x80479D60             # global logic-frame counter (u32)
MCP_OUT = fs.DEFAULT_OUT.parent / "mcp"
_stamp = time.strftime("%Y%m%d-%H%M%S")


def _resolve_iso(iso):
    """Explicit path > frameshot's default > the vanilla 1.02 in the repo."""
    if iso:
        p = Path(iso).resolve()
        if not p.exists():
            raise ValueError(f"ISO missing: {p}")
        return p
    if fs.DEFAULT_ISO.exists():
        return fs.DEFAULT_ISO
    from shared.vanilla_extract.vanilla_refs import known_vanilla_iso
    recorded = known_vanilla_iso()
    if recorded and Path(recorded).is_file():
        return Path(recorded)
    vanilla = sorted(PROJECT_ROOT.glob("Super Smash Bros*.iso"))
    if vanilla:
        return vanilla[0]
    raise ValueError(f"no ISO: pass one (default {fs.DEFAULT_ISO} missing, "
                     f"no vanilla ISO in {PROJECT_ROOT})")


def _parse_addr(v):
    return v if isinstance(v, int) else int(str(v), 0)


# ---------------------------------------------------------------------------
# The live session
# ---------------------------------------------------------------------------
class Session:
    """One booted solo match, frozen, driven across many tool calls."""

    def __init__(self):
        self.boot = None
        self.d = None
        self.pipe = None
        self.runner = None
        self.bag = None
        self.bag_dx, self.bag_dy = 8.0, 0.0
        self.plain_bg = None
        self.stage = None
        self.char_label = None
        self.move = None
        self.move_frame = 0
        self.dats = {}
        self.out_dir = MCP_OUT / _stamp
        self.shots = 0

    @property
    def active(self):
        return self.boot is not None

    def require(self):
        if not self.active:
            raise ValueError("no live session -- call boot_match first")
        if not self.d.alive():
            raise ValueError("Dolphin died (crash?) -- call end_session, then "
                             "boot_match again")

    def start(self, args, log):
        if self.active:
            raise ValueError("a session is already live -- end_session first "
                             "(one Dolphin at a time)")
        iso = _resolve_iso(args.get("iso"))
        stage = args.get("stage", "finaldestination")
        if stage not in INTERNAL_STAGE_ID:
            raise ValueError(f"unknown stage '{stage}' "
                             f"(known: {', '.join(sorted(INTERNAL_STAGE_ID))})")
        char_kind = fs.parse_char(str(args.get("char", "marth")))
        color = int(args.get("color", 0))
        bag_kind = fs.parse_char(str(args["bag"])) if args.get("bag") else None
        bag_color = int(args.get("bag_color", 0))
        bp = args.get("bag_pos", [8, 0])
        self.bag_dx, self.bag_dy = (fs.parse_bag_pos(bp) if isinstance(bp, str)
                                    else (float(bp[0]), float(bp[1])))
        kirby_copy = args.get("kirby_copy")
        if kirby_copy:
            if kirby_copy not in match_setup.KIRBY_COPY_FTKIND:
                raise ValueError(f"unknown kirby_copy donor '{kirby_copy}' (known: "
                                 f"{', '.join(sorted(match_setup.KIRBY_COPY_FTKIND))})")
            if bag_kind is None:
                raise ValueError("kirby_copy requires bag=<donor> -- the donor "
                                 "must be in the match or the install hangs")
        pb = args.get("plain_bg")
        self.plain_bg = ("404040" if pb is True else str(pb)) if pb else None
        self.stage = stage
        self.char_label = (str(args.get("char", "marth")).lower()
                           if not str(args.get("char", "")).startswith("0x")
                           else str(args["char"]))

        dolphin_lock.acquire(
            f"mcp live session {self.char_label} @ {stage}",
            wait=float(args.get("wait_for_dolphin", 0) or 0))
        fs.RUNS_ROOT.mkdir(parents=True, exist_ok=True)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        boot = DolphinBoot(str(iso), None, str(fs.RUNS_ROOT), clean_osd=True,
                           log=log)
        self.boot = boot               # so cleanup() runs even on a failed boot
        try:
            boot.prepare()
            _write_ini(str(boot.user_dir / "Config" / "Dolphin.ini"),
                       lambda upsert, _r: upsert("Core", "SlippiOnlineDelay", "0"))
            boot.launch()
            if not boot.wait_for_pipe(timeout=45):
                raise RuntimeError("input pipe never appeared")
            d = Dolphin(boot.pid)
            t0 = time.time()
            while not d.locate() and time.time() - t0 < 20:
                if not d.alive():
                    raise RuntimeError("Dolphin died during boot")
                time.sleep(0.4)
            if d.base is None:
                raise RuntimeError("could not locate MEM1")
            self.d = d

            match_setup.patch_one_player(d, log=log)
            if kirby_copy:
                # JIT gotcha: arm before Kirby's first spawn compiles the func
                if not match_setup.arm_kirby_copy_ondeath(d, log=log):
                    raise RuntimeError("could not arm the Kirby copy patch")
            p = self.pipe = boot.open_pipe()
            if not nav.nav_to_css(d, p, log=log):
                raise RuntimeError("never reached the offline CSS")
            nav.wait_css_ready(d, Cursor(d, p), log=log)
            match_setup.force_time_infinite(d, log=log)

            def write_players():
                if bag_kind is None:
                    match_setup.write_solo_player(d, char_kind, color)
                else:
                    match_setup.write_bag_player(d, char_kind, color,
                                                 bag_ckind=bag_kind,
                                                 bag_color=bag_color)

            log(f"memory-select ckind=0x{char_kind:02X}"
                + (f" + bag 0x{bag_kind:02X}" if bag_kind is not None else " solo"))
            write_players()
            match_setup.warp_to_stage_select(d)
            sc = StageCursor(d, p)
            if not sc.wait_for_stage_select(timeout=8.0):
                raise RuntimeError("CSS->SSS warp did not land")
            write_players()
            if not sc.force_select(INTERNAL_STAGE_ID[stage]):
                raise RuntimeError("match never started")
            if not wait_in_game(d, timeout=25.0, log=log):
                raise RuntimeError("never reached in-game")
            if not wait_game_frames(d, 200):   # past READY / GO!
                # Scene flags become "in-game" before allocation/READY. Keep
                # preload evidence before cleaning our own failed Dolphin child.
                diagnostic={"global_frame":d.u32(FRAME_COUNTER),"regions":{}}
                for address,size in ((0x80431FA0,0xD8),(0x80432078,0x978),(0x80015BD0,0xD8)):
                    raw=d.bytes(address,size)
                    diagnostic['regions'][hex(address)]=raw.hex() if raw else None
                evidence=self.out_dir/'boot-failure-memory.json'
                evidence.write_text(json.dumps(diagnostic,indent=2))
                raise RuntimeError(f"Match scene entered but startup frames stalled; evidence: {evidence}")
            active_ports = [0] if bag_kind is None else [0, 1]
            match_setup.fix_player_pad_indices(d, active_ports, log=log)
            if self.plain_bg:
                fs.assert_plain_bg(d, self.plain_bg)
                if stage == "finaldestination":
                    fs.kill_stage_particles(d)
            if kirby_copy:
                hat = match_setup.install_kirby_copy_via_rebirth(
                    d, match_setup.KIRBY_COPY_FTKIND[kirby_copy], port=0, log=log)
                if hat != match_setup.KIRBY_COPY_FTKIND[kirby_copy]:
                    raise RuntimeError(f"kirby copy install failed (hat={hat})")

            framestep.freeze(d)
            runner = self.runner = MoveRunner(d, p, log=log)
            if not runner.player.resolve():
                raise RuntimeError("Match startup completed without an active fighter")
            if kirby_copy and runner.player.state() in (12, 13):
                # ride out the copy-install rebirth halo (as frameshot does)
                runner.p.frame(["SET MAIN 0.500 0.000", "FLUSH"])
                runner._step(3)
                runner.p.neutral()
                runner.player.set_pos(0.0, 25.0)
                for _ in range(180):
                    runner._step(1)
                    if runner.player.state() == 14:
                        break
            if bag_kind is not None:
                self.bag = Bag(d, port=1)
                if not self.bag.resolve():
                    raise RuntimeError("bag never spawned (port 1 ft is null)")
            log("session ready: match loaded, game FROZEN")
        except BaseException:
            self.stop()
            raise

    def stop(self):
        try:
            if self.pipe:
                self.pipe.close()
        except Exception:
            pass
        try:
            if self.boot:
                self.boot.cleanup()
        except Exception:
            pass
        dolphin_lock.release()         # no-op unless this process holds it
        self.__init__()                # reset all fields, keep out_dir fresh

    # --- helpers ------------------------------------------------------------
    def reassert_visuals(self):
        if self.plain_bg:
            fs.assert_plain_bg(self.d, self.plain_bg)
            if self.stage == "finaldestination":
                fs.kill_stage_particles(self.d)
            time.sleep(0.1)            # let the renderer composite the pokes

    def status(self):
        self.runner.player.resolve()
        s = self.runner.player.snapshot()
        s['kind'] = self.runner.player.kind()
        s['fighter_pointer'] = self.runner.player.ft
        out = {"player": s, "frozen": framestep.is_frozen(self.d),
               "global_frame": self.d.u32(FRAME_COUNTER),
               "move": self.move, "move_frame": self.move_frame or None}
        if self.bag:
            b = self.bag.snapshot()
            b["in_damage"] = self.bag.in_damage()
            out["bag"] = b
        return out

    def stepn(self, n, bag_pin=False):
        got = 0
        for _ in range(int(n)):
            got += self.runner._step(1)
            if self.bag and bag_pin:
                self.bag.pin()
        if self.move:
            self.move_frame += got
        return got


SESSION = Session()
atexit.register(SESSION.stop)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
def t_harness_info(args, log):
    return {
        "read_first": "docs/dev/INGAME_TESTING.md + app/backend/shared/ingame/README.md; "
                      "REST routes: docs/dev/API_REFERENCE.md",
        "families": {
            "in-game (live Dolphin)": "boot_match -> do_move/step/screenshot/"
                "poke_dat -> end_session; one-shots frameshot/effect_probe/"
                "run_ingame_test",
            "app backend (REST)": "backend_start -> vault_import/vault_list/"
                "retake_csp/api(any of ~230 routes) -> backend_stop; "
                "build_modded_iso for full builds",
            "direct engines": "render_csp (portrait from any DAT), dat_probe "
                "(texture+matanim inventory), detect_content (classify a mod "
                "file), hsdraw (model export/import, DObj surgery, stage "
                "render), mexcli (raw project ops -- prefer REST)",
            "decomp reference": "decomp (op=symbol/addr/grep/source/info): "
                "the local Melee decompilation = ground truth for engine "
                "behavior; symbol addresses ARE live MEM1 addresses, so "
                "chain decomp -> read_ram/write_ram to work by name",
            "iso + memory forensics": "iso_file (list/extract any file from "
                "a GC ISO, ensure_ref for vanilla references), ram_search "
                "(live MEM1 pattern find + snapshot/diff -- snapshot, act, "
                "diff to map bytes to behavior)",
            "asset derivation": "render_stock (stock icon for a modded DAT "
                "-- the companion to render_csp), stage_shot (stage-alone / "
                "pause-overlay / DAS-variant-batch screenshots)",
            "stage authoring": "stage_workbench (guide/inspect/mesh/graft/"
                "cameras/package): freeform stage construction using the "
                "Colosseum and CS2 primitives; start with op=guide",
            "fighter creation": "native_port (Nucleus's native port engine, "
                "source readers, build receipts and advanced adapters); "
                "rigswap (model-to-costume import and fixes through Randall). "
                "Start with op=info; long work returns a job id for op=status. "
                "Developer calibration is optional.",
            "perf verdicts": "fps_batch (CSS memory/FPS "
                "HEALTHY/DEGRADED/HUNG verdict per ISO)",
            "maintenance / diagnosis": "extras_doctor (no-boot extras "
                "triage), fsm_patch (bake/revert Crazy Hand FSMs in a DOL), "
                "csp_regression (golden-image suite -- run after renderer "
                "changes), mex_codes (bundled m-ex codes status/update)",
        },
        "rules": [
            "GAMEPLAY tests (crashes, moves, effects, screenshots) use THIS "
            "server's solo engine: no CPU, no CSS cursor. Do NOT wire up "
            "tools/ingame/dolphin/ + cpustep for gameplay -- the CPU "
            "attacks you and moves the camera, ruining repros. The cursor-"
            "driven CSS/SSS orchestrator (run-modded-match.js) was removed "
            "2026-07-17; there is no CSS/SSS cursor tool.",
            "One Dolphin at a time: end_session before frameshot/effect_probe/"
            "run_ingame_test, and vice versa. This is enforced MACHINE-WIDE "
            "via an advisory lock shared by all agents/sessions -- check "
            "dolphin_status to see who owns the emulator, and pass "
            "wait_for_dolphin=<seconds> on booting tools to queue for it.",
            "Never poke the debug-pause step byte by hand (wedge gotcha) -- "
            "the step tool uses framestep.step()'s handshake.",
            "Frame numbering: frame 1 = first frame of the move's action state "
            "(community frame-data convention).",
            "Custom pose probes use shared.ingame.gamestate.Player.pose and .visibility "
            "while frozen, with counts from the tested costume; do not duplicate "
            "JObj/visibility offsets. Keep raw fractional animation time and "
            "rotation flags. See shared/ingame/README.md for the capture schema.",
            "A source author and verifier sharing one sampler can agree on the "
            "same bug. Check raw source against an independent reference at "
            "fractional as well as integer frames before authoring; packed "
            "playback, transitions, and rendered visibility are separate gates.",
            "ckind: vanilla chars have names; m-ex added fighters are external "
            "ids from 0x1A up (pass char='0x1A' with the built ISO).",
        ],
        "moves": list(MOVES),
        "stages": sorted(INTERNAL_STAGE_ID),
        "chars": sorted(CKIND),
        "kirby_copy_donors": sorted(match_setup.KIRBY_COPY_FTKIND),
        "default_iso": str(fs.DEFAULT_ISO),
        "artifacts": {"frameshot": str(fs.DEFAULT_OUT), "session": str(MCP_OUT)},
    }


def t_boot_match(args, log):
    SESSION.start(args, log)
    if args.get("debug_draw", "off") != "off":
        from shared.ingame.debug_draw import set_debug_draw
        set_debug_draw(SESSION.d, args["debug_draw"])
    return {"ok": True, "iso": str(_resolve_iso(args.get("iso"))),
            "out_dir": str(SESSION.out_dir), **SESSION.status()}


def t_debug_draw(args, log):
    SESSION.require()
    from shared.ingame.debug_draw import set_debug_draw
    return {"fighters": set_debug_draw(SESSION.d, args.get("mode", "overlay"),
                                      args.get("ports", list(range(6))))}


def t_game_state(args, log):
    SESSION.require()
    out = SESSION.status()
    watch = float(args.get("watch_seconds", 0) or 0)
    if watch > 0:
        f0 = SESSION.d.u32(FRAME_COUNTER)
        time.sleep(watch)
        if not SESSION.d.alive():
            out["health"] = "crashed"
        else:
            f1 = SESSION.d.u32(FRAME_COUNTER)
            frozen = framestep.is_frozen(SESSION.d)
            out["health"] = ("frozen-by-harness" if frozen and f1 == f0
                             else "hung" if f1 == f0 else "running")
            out["frames_advanced"] = f1 - f0
    return out


def t_do_move(args, log):
    SESSION.require()
    move = args["move"]
    if move not in MOVES:
        raise ValueError(f"unknown move '{move}' (known: {', '.join(MOVES)})")
    SESSION.runner.reset()
    if SESSION.bag:
        park_bag(SESSION.runner, SESSION.bag,
                 dx=SESSION.bag_dx, dy=SESSION.bag_dy)
    state = SESSION.runner.execute(move, rise=int(args.get("rise", 10)))
    SESSION.move, SESSION.move_frame = move, 1
    return {"entry_state": state, "entry_state_name": state_name(state),
            "note": "frozen on the move's FRAME 1 -- use step/screenshot",
            **SESSION.status()}


def t_step(args, log):
    SESSION.require()
    got = SESSION.stepn(args.get("frames", 1), bool(args.get("bag_pin")))
    return {"stepped": got, **SESSION.status()}


def t_send_input(args, log):
    SESSION.require()
    lines = list(args["lines"])
    SESSION.pipe.frame(lines + ["FLUSH"])
    out = {"sent": lines}
    n = int(args.get("then_step", 0) or 0)
    if n:
        out["stepped"] = SESSION.stepn(n)
    if args.get("then_neutral"):
        SESSION.pipe.neutral()
    out.update(SESSION.status())
    return out


def t_screenshot(args, log):
    SESSION.require()
    SESSION.reassert_visuals()
    png = shot.capture_via_printwindow(SESSION.boot.pid, max_width=1280)
    if not png:
        png = shot.capture_png(SESSION.boot.pid, max_width=1280)
    if not png:
        raise RuntimeError("capture failed (window gone?)")
    SESSION.shots += 1
    label = args.get("label") or (
        f"{SESSION.char_label}-{SESSION.move or 'live'}"
        f"-f{SESSION.move_frame:02d}" if SESSION.move
        else f"{SESSION.char_label}-live-{SESSION.shots:03d}")
    path = SESSION.out_dir / f"{re.sub(r'[^A-Za-z0-9._-]', '_', label)}.png"
    path.write_bytes(png)

    from PIL import Image
    img = Image.open(io.BytesIO(png))
    w = int(args.get("max_width", 640))
    if img.width > w:
        img = img.resize((w, round(img.height * w / img.width)))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return {"_image": base64.b64encode(buf.getvalue()).decode(),
            "file": str(path), **SESSION.status()}


def t_read_ram(args, log):
    SESSION.require()
    addr = _parse_addr(args["addr"])
    size = int(args.get("size", 4))
    if not 1 <= size <= 4096:
        raise ValueError("size must be 1..4096")
    data = SESSION.d.bytes(addr, size)
    if data is None:
        raise RuntimeError(f"read failed @0x{addr:08X}")
    out = {"addr": f"0x{addr:08X}", "hex": data.hex()}
    if size == 4:
        out["u32"] = int.from_bytes(data, "big")
        out["f32"] = SESSION.d.f32(addr)
    return out


def t_write_ram(args, log):
    SESSION.require()
    addr = _parse_addr(args["addr"])
    data = bytes.fromhex(args["hex"])
    SESSION.d.write_bytes(addr, data)
    back = SESSION.d.bytes(addr, len(data))
    return {"addr": f"0x{addr:08X}", "wrote": data.hex(),
            "readback": back.hex() if back else None,
            "verified": back == data}


def t_poke_dat(args, log):
    SESSION.require()
    path = str(Path(args["file"]).resolve())
    dat = SESSION.dats.get(path)
    if dat is None:
        dat = DatRam(SESSION.d, path)
        if not dat.locate():
            raise RuntimeError(f"DAT image not found in MEM1 (is it loaded in "
                               f"this match/scene?): {path}")
        SESSION.dats[path] = dat
        log(f"located {Path(path).name} at "
            + ", ".join(f"0x{b:08X}" for b in dat.bases))
    off = _parse_addr(args["offset"])
    if args.get("restore"):
        n = int(args["restore"])
        dat.restore(off, n)
        return {"restored": n, "offset": f"0x{off:X}",
                "bases": [f"0x{b:08X}" for b in dat.bases]}
    data = bytes.fromhex(args["hex"])
    dat.poke(off, data)
    return {"poked": data.hex(), "offset": f"0x{off:X}",
            "bases": [f"0x{b:08X}" for b in dat.bases],
            "note": "pokes do not survive a scene re-load; redo the move to "
                    "see the effect"}


def t_set_player(args, log):
    SESSION.require()
    port = int(args.get("port", 0))
    pl = (SESSION.runner.player if port == 0 else
          SESSION.bag if (SESSION.bag and port == 1) else Player(SESSION.d, port))
    if port not in (0, 1) or (port == 1 and not SESSION.bag):
        if not pl.resolve():
            raise ValueError(f"no fighter on port {port}")
    if args.get("x") is not None or args.get("y") is not None:
        cur = pl.pos() or (0.0, 0.0)
        pl.set_pos(float(args.get("x", cur[0])), float(args.get("y", cur[1])))
    if args.get("percent") is not None:
        pl.set_percent(float(args["percent"]))
    s = pl.snapshot()
    s["percent"] = pl.percent()
    return {"port": port, "player": s}


def t_freeze(args, log):
    SESSION.require()
    if bool(args.get("frozen", True)):
        framestep.freeze(SESSION.d)
    else:
        framestep.unfreeze(SESSION.d)
    return {"frozen": framestep.is_frozen(SESSION.d)}


def t_end_session(args, log):
    if not SESSION.active:
        return {"ok": True, "note": "no session was live"}
    SESSION.stop()
    return {"ok": True, "note": "Dolphin closed, temp User dir removed"}


def t_dolphin_status(args, log):
    st = dolphin_lock.status()
    st["lock_path"] = str(dolphin_lock.LOCK_PATH)
    st["dolphin_process_running"] = bool(dolphin_running())
    st["this_session"] = {
        "owns_lock": bool(st["owner"]) and st["owner"].get("pid") == os.getpid(),
        "live_session_active": SESSION.active,
    }
    st["note"] = ("all lock-aware entry points (boot_match, frameshot, "
                  "effect_probe, run_ingame_test) accept wait_for_dolphin="
                  "<seconds> to queue instead of failing while it's held")
    return st


def _no_session(what):
    if SESSION.active:
        raise ValueError(f"{what} boots its own Dolphin -- end_session first")


def _lock_env(args):
    """Env for SUBPROCESS one-shots: the child's own DolphinBoot.launch()
    enforces the machine-wide lock (do NOT hold it in this parent process --
    the child has a different pid and would queue against us forever).
    wait_for_dolphin just sets the child's queue budget."""
    env = dict(os.environ)
    wait = args.get("wait_for_dolphin")
    if wait is not None:
        env["MELEE_DOLPHIN_LOCK_WAIT"] = str(float(wait))
    return env


def _run_cli(cmd, log, tail=120, cwd=None, stdin_text=None, env=None):
    from core.config import get_subprocess_args
    from collections import deque
    log("$ " + subprocess.list2cmdline(cmd))
    proc = subprocess.Popen(cmd, cwd=str(cwd or BACKEND), stdout=subprocess.PIPE,
                            stdin=subprocess.PIPE if stdin_text is not None else None,
                            stderr=subprocess.STDOUT, text=True, env=env,
                            encoding="utf-8", errors="replace", bufsize=1,
                            **get_subprocess_args())
    if stdin_text is not None:
        proc.stdin.write(stdin_text)
        proc.stdin.close()
    lines = deque(maxlen=tail)
    for line in proc.stdout:
        line = line.rstrip()
        lines.append(line)
        log(line)
    code = proc.wait()
    return code, list(lines)


def t_frameshot(args, log):
    _no_session("frameshot")
    out_dir = fs.DEFAULT_OUT / "mcp" / time.strftime("%Y%m%d-%H%M%S")
    cmd = [sys.executable, "devtools/frameshot.py",
           "--char", str(args.get("char", "marth")),
           "--stage", str(args.get("stage", "finaldestination")),
           "--iso", str(_resolve_iso(args.get("iso"))),
           "--out", str(out_dir),
           "--color", str(args.get("color", 0))]
    for s in args.get("shots") or []:
        cmd += ["--shot", str(s)]
    # BATCH: many (char, color, shots) targets in ONE boot -- between targets
    # frameshot quits to the CSS and memory-selects the next fighter instead of
    # rebooting Dolphin (~15s/target vs ~90s/boot). Read batch.json, not a glob:
    # only status == "ok" means the shots are real.
    targets = args.get("targets")
    if targets:
        out_dir.mkdir(parents=True, exist_ok=True)
        tfile = out_dir / "targets.json"
        payload = {"targets": targets}
        if args.get("shots"):
            payload["shots"] = [str(s) for s in args["shots"]]
        tfile.write_text(json.dumps(payload, indent=2))
        cmd += ["--batch", str(tfile)]
    if args.get("move"):
        cmd += ["--move", str(args["move"]),
                "--frames", str(args.get("frames", "1"))]
    if args.get("plain_bg"):
        pb = args["plain_bg"]
        cmd += ["--plain-bg"] + ([] if pb is True else [str(pb)])
    if args.get("bag"):
        cmd += ["--bag", str(args["bag"]),
                "--bag-pos", str(args.get("bag_pos", "8,0"))]
    if args.get("bag_pin"):
        cmd += ["--bag-pin"]
    if args.get("kirby_copy"):
        cmd += ["--kirby-copy", str(args["kirby_copy"])]
    for spec in args.get("input_at") or []:
        cmd += ["--input-at", str(spec)]
    if args.get("rise") is not None:
        cmd += ["--rise", str(args["rise"])]

    code, tail = _run_cli(cmd, log, env=_lock_env(args))
    glob_root = "**/" if targets else ""
    # key by RELATIVE path in batch mode: two targets on the same fighter write
    # the same sidecar filename into different per-target dirs.
    sidecars = {(str(p.relative_to(out_dir)) if targets else p.name):
                json.loads(p.read_text())
                for p in sorted(out_dir.glob(f"{glob_root}*.json"))
                if p.name not in ("batch.json", "targets.json")} \
        if out_dir.exists() else {}
    res = {"exit_code": code, "ok": code == 0, "out_dir": str(out_dir),
           "pngs": [str(p) for p in sorted(out_dir.glob(f"{glob_root}*.png"))]
                   if out_dir.exists() else [],
           "sidecars": sidecars, "log_tail": tail}
    manifest = out_dir / "batch.json"
    if targets and manifest.is_file():
        res["batch"] = json.loads(manifest.read_text())
    return res


def t_effect_probe(args, log):
    _no_session("effect_probe")
    spec = args["spec"]
    if isinstance(spec, str):
        spec_path = Path(spec).resolve()
        if not spec_path.exists():
            raise ValueError(f"spec file missing: {spec_path}")
    else:
        MCP_OUT.mkdir(parents=True, exist_ok=True)
        spec_path = MCP_OUT / f"probe-{time.strftime('%Y%m%d-%H%M%S')}.json"
        spec_path.write_text(json.dumps(spec, indent=2))
    cmd = [sys.executable, "devtools/effect_probe.py", str(spec_path)]
    if args.get("dry_run"):
        cmd.append("--dry-run")
    code, tail = _run_cli(cmd, log, tail=200, env=_lock_env(args))
    return {"exit_code": code, "ok": code == 0, "spec": str(spec_path),
            "log_tail": tail}


def t_run_ingame_test(args, log):
    _no_session("run_ingame_test")
    from shared.ingame.runner import run_test
    iso = _resolve_iso(args.get("iso"))
    fs.RUNS_ROOT.mkdir(parents=True, exist_ok=True)

    def emit(stage, pct, message):
        log(f"[{pct}%] {stage}: {message}")

    # in-process: DolphinBoot.launch() enforces the lock (re-entrant per pid);
    # honor wait_for_dolphin via the env knob it reads.
    if args.get("wait_for_dolphin") is not None:
        os.environ["MELEE_DOLPHIN_LOCK_WAIT"] = str(float(args["wait_for_dolphin"]))
    result = run_test(str(iso), None, str(fs.RUNS_ROOT),
                      manifest=args.get("manifest"), emit=emit, log=log,
                      observe_seconds=int(args.get("observe_seconds", 9)))
    return result


# ---------------------------------------------------------------------------
# Wave 2: app backend (REST), vault, CSP/model engines, CLI passthroughs
# ---------------------------------------------------------------------------
BACKEND_STATE = {"proc": None, "url": None, "log": None, "spawned": False}


def _stop_backend():
    if BACKEND_STATE["url"] and BACKEND_STATE["spawned"]:
        try:
            _http("POST", BACKEND_STATE["url"] + "/api/mex/shutdown",
                  body={}, timeout=5)
        except Exception:
            pass
    p = BACKEND_STATE["proc"]
    if p and p.poll() is None:
        try:
            p.kill()
            p.wait(timeout=10)
        except Exception:
            pass
    BACKEND_STATE.update({"proc": None, "url": None, "spawned": False})


atexit.register(_stop_backend)


def _http(method, url, body=None, timeout=300):
    data, headers = None, {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if BACKEND_STATE.get("token"):
        headers["X-Nucleus-Token"] = BACKEND_STATE["token"]
    if BACKEND_STATE.get("agent_session"):
        headers["X-Nucleus-Agent-Session"] = BACKEND_STATE["agent_session"]
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw, ct, status = r.read(), r.headers.get("Content-Type", ""), r.status
    except urllib.error.HTTPError as e:
        raw, ct, status = e.read(), e.headers.get("Content-Type", ""), e.code
    if "json" in ct:
        try:
            return status, json.loads(raw)
        except Exception:
            pass
    return status, {"_non_json": True, "content_type": ct, "bytes": len(raw),
                    "text_head": raw[:400].decode("utf-8", "replace")}


def _http_multipart(url, fields, file_field, file_path, timeout=1800):
    fp = Path(file_path)
    if not fp.exists():
        raise ValueError(f"file missing: {fp}")
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in (fields or {}).items():
        if v is None:
            continue
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; '
                      f'name="{k}"\r\n\r\n{v}\r\n').encode())
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; '
                  f'name="{file_field}"; filename="{fp.name}"\r\n'
                  f'Content-Type: application/octet-stream\r\n\r\n').encode())
    parts.append(fp.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        url, data=b"".join(parts), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 **({"X-Nucleus-Token": BACKEND_STATE["token"]} if BACKEND_STATE.get("token") else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    try:
        return status, json.loads(raw)
    except Exception:
        return status, {"_non_json": True, "bytes": len(raw),
                        "text_head": raw[:400].decode("utf-8", "replace")}


def _backend_require():
    if not BACKEND_STATE["url"]:
        raise ValueError("app backend not running -- call backend_start first")
    return BACKEND_STATE["url"]


def _capped(obj, limit=28000):
    """Serialize a JSON response, truncating huge payloads (vault metadata
    can be megabytes) instead of flooding the agent's context."""
    text = json.dumps(obj, indent=2, default=str)
    if len(text) <= limit:
        return obj
    return {"_truncated": True, "note": f"response was {len(text)} chars; "
            "narrow the query (e.g. ?character=) for the full body",
            "preview": text[:limit]}


def t_backend_start(args, log):
    if BACKEND_STATE["url"]:
        try:
            st, j = _http("GET", BACKEND_STATE["url"] + "/api/mex/status",
                          timeout=5)
            return {"url": BACKEND_STATE["url"], "already_running": True,
                    "status": j}
        except Exception:
            _stop_backend()             # stale -- restart below
    if args.get("url"):                 # attach to an external instance
        url = str(args["url"]).rstrip("/")
        st, j = _http("GET", url + "/api/mex/status", timeout=10)
        BACKEND_STATE.update({"proc": None, "url": url, "spawned": False})
        return {"url": url, "attached": True, "status": j}

    py = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
    cmd = [str(py) if py.exists() else sys.executable,
           str(INGAME_TOOLS / "nucleus" / "_run_backend.py")]
    MCP_OUT.mkdir(parents=True, exist_ok=True)
    logf = MCP_OUT / f"backend-{time.strftime('%Y%m%d-%H%M%S')}.log"
    # stdout goes to a FILE, not a pipe: this single-threaded server can't
    # drain a pipe during long tool calls and a full 64KB buffer deadlocks
    # the backend mid-log-write (documented in run-texture-harvest.js)
    fh = open(logf, "ab")
    log(f"spawning backend: {subprocess.list2cmdline(cmd)}")
    proc = own(subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), stdout=fh,
                                stderr=subprocess.STDOUT))
    port, t0 = None, time.time()
    while time.time() - t0 < 45:
        if proc.poll() is not None:
            raise RuntimeError(f"backend exited rc={proc.returncode}; "
                               f"log: {logf}")
        raw = logf.read_bytes()
        m = re.search(rb"BACKEND_PORT:(\d+)", raw)
        if m:
            port = int(m.group(1))
            # the backend authenticates every /api call with the token it
            # prints at startup (X-Nucleus-Token); capture it for _http
            t = re.search(rb"BACKEND_TOKEN:([0-9a-f]+)", raw)
            BACKEND_STATE["token"] = t.group(1).decode() if t else None
            break
        time.sleep(0.4)
    if not port:
        proc.kill()
        raise RuntimeError(f"no BACKEND_PORT within 45s; log: {logf}")
    url = f"http://127.0.0.1:{port}"
    log(f"backend on {url}; waiting for connected...")
    status = None
    t0 = time.time()
    while time.time() - t0 < 60:
        try:
            _, status = _http("GET", url + "/api/mex/status", timeout=5)
            if status.get("connected"):
                break
        except Exception:
            pass
        time.sleep(1.0)
    BACKEND_STATE.update({"proc": proc, "url": url, "spawned": True,
                          "log": str(logf)})
    try:
        _, setup = _http("GET", url + "/api/mex/setup/status", timeout=10)
    except Exception:
        setup = None
    return {"url": url, "port": port, "log": str(logf), "status": status,
            "setup": setup,
            "note": "dev instance: repo storage/, projects/, output/; the "
                    "installed desktop app (LOCALAPPDATA, port 5000) is "
                    "untouched"}


def t_backend_stop(args, log):
    if not BACKEND_STATE["url"]:
        return {"ok": True, "note": "no backend was running"}
    spawned = BACKEND_STATE["spawned"]
    _stop_backend()
    return {"ok": True, "stopped": "spawned instance" if spawned
            else "detached from external instance"}


def t_api(args, log):
    url = _backend_require()
    route = str(args["route"])
    if not route.startswith("/"):
        raise ValueError("route must start with / (e.g. /api/mex/status)")
    method = str(args.get("method", "GET")).upper()
    timeout = int(args.get("timeout", 300))
    if args.get("file"):
        st, j = _http_multipart(url + route, args.get("fields") or {},
                                args.get("file_field", "file"), args["file"],
                                timeout=timeout)
    else:
        st, j = _http(method, url + route, body=args.get("body"),
                      timeout=timeout)
    return {"status": st, "response": _capped(j)}


def t_vault_import(args, log):
    url = _backend_require()
    fields = {"slippi_action": args.get("slippi_action"),
              "duplicate_action": args.get("duplicate_action"),
              "custom_title": args.get("custom_title")}
    log(f"uploading {args['file']} to /api/mex/import/file ...")
    st, j = _http_multipart(url + "/api/mex/import/file", fields, "file",
                            args["file"], timeout=1800)
    return {"status": st, "result": _capped(j)}


_VAULT_ROUTES = {
    "costumes": "/api/mex/storage/costumes",
    "das_variants": "/api/mex/das/storage/variants",
    "custom_characters": "/api/mex/custom-characters/list",
    "custom_stages": "/api/mex/custom-stages/list",
    "project_fighters": "/api/mex/fighters",
    "metadata": "/api/mex/storage/metadata",
}


def t_vault_list(args, log):
    url = _backend_require()
    kind = args.get("kind", "costumes")
    route = _VAULT_ROUTES.get(kind)
    if not route:
        raise ValueError(f"unknown kind '{kind}' "
                         f"(known: {', '.join(_VAULT_ROUTES)})")
    q = ""
    if args.get("character"):
        q = ("?character=" if kind == "costumes" else "?stage=") \
            + urllib.parse.quote(str(args["character"]))
    st, j = _http("GET", url + route + q, timeout=120)
    return {"status": st, "result": _capped(j)}


def t_retake_csp(args, log):
    url = _backend_require()
    character = args["character"]
    skin_ids = args.get("skin_ids") or [args["skin_id"]]
    apply = bool(args.get("apply", True))
    results, first_img = [], None
    for i, sid in enumerate(skin_ids):
        st, prev = _http("POST", url + "/api/mex/storage/costumes/generate-csp",
                         body={"character": character, "skinId": sid},
                         timeout=300)
        if st != 200 or not prev.get("dataUri"):
            results.append({"skinId": sid, "ok": False, "error": prev})
            log(f"[{i+1}/{len(skin_ids)}] {sid}: preview FAILED")
            continue
        entry = {"skinId": sid, "ok": True, "poseName": prev.get("poseName")}
        if first_img is None:
            first_img = prev["dataUri"].split(",", 1)[-1]
        if apply:
            st2, res = _http("POST",
                             url + "/api/mex/storage/costumes/generate-csp",
                             body={"character": character, "skinId": sid,
                                   "apply": True,
                                   "imageData": prev["dataUri"]},
                             timeout=300)
            entry["applied"] = st2 == 200 and bool(res.get("success", True))
        results.append(entry)
        log(f"[{i+1}/{len(skin_ids)}] {sid}: pose={entry.get('poseName')} "
            f"applied={entry.get('applied', '(preview only)')}")
    out = {"character": character, "results": results}
    if first_img:
        out["_image"] = first_img
    return out


def t_build_modded_iso(args, log):
    cmd = ["node", str(INGAME_TOOLS / "nucleus" /
                       "build-modded-iso.js")]
    for flag, key in [("--type", "type"), ("--mod", "mod"),
                      ("--fighter", "fighter"), ("--iso", "iso"),
                      ("--name", "name"), ("--compression", "compression"),
                      ("--stage", "stage"), ("--extra", "extra"),
                      ("--menu", "menu"), ("--count", "count")]:
        if args.get(key) is not None:
            cmd += [flag, str(args[key])]
    if args.get("export_only"):
        cmd += ["--export-only"]
    for extra in args.get("extra_args") or []:
        cmd.append(str(extra))
    if BACKEND_STATE["url"]:
        cmd += ["--backend", BACKEND_STATE["url"]]
    code, tail = _run_cli(cmd, log, tail=80, cwd=PROJECT_ROOT)
    manifest = None
    for line in reversed(tail):
        if line.startswith("MANIFEST "):
            try:
                manifest = json.loads(line[len("MANIFEST "):])
            except Exception:
                pass
            break
    return {"exit_code": code, "ok": code == 0, "manifest": manifest,
            "log_tail": tail if code != 0 else tail[-25:]}


def t_render_csp(args, log):
    from generate_csp import generate_csp as _gen   # PROCESSOR_DIR on path
    import shutil
    src = Path(args["dat"]).resolve()
    if not src.exists():
        raise ValueError(f"DAT missing: {src}")
    # render in a temp dir: generate_csp writes <stem>_csp.png NEXT TO the
    # input, and we must not litter vault/vanilla folders
    work = MCP_OUT / f"csp-{time.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"
    work.mkdir(parents=True, exist_ok=True)
    dat = work / src.name
    shutil.copy2(src, dat)
    paired = None
    if args.get("paired_dat"):
        paired = work / Path(args["paired_dat"]).name
        shutil.copy2(Path(args["paired_dat"]).resolve(), paired)
    log(f"rendering CSP for {src.name} (scale {args.get('scale', 1)})...")
    out = _gen(str(dat), scale=int(args.get("scale", 1)),
               paired_dat_filepath=str(paired) if paired else None,
               color_index=args.get("color_index"))
    if not out:
        raise RuntimeError("generate_csp returned None (see logs/ and "
                           "%TEMP%/csp_debug_<pid>.log)")
    png = Path(out).read_bytes()
    from PIL import Image
    img = Image.open(io.BytesIO(png))
    if img.width > 544:
        img = img.resize((544, round(img.height * 544 / img.width)))
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        png = buf.getvalue()
    return {"_image": base64.b64encode(png).decode(), "file": str(out),
            "size": f"{img.width}x{img.height}"}


def t_dat_probe(args, log):
    cmd = [sys.executable, "-m", "shared.rendering.datprobe",
           str(Path(args["dat"]).resolve())]
    if args.get("dump_dir"):
        cmd += ["--dump-dir", str(args["dump_dir"])]
    code, tail = _run_cli(cmd, log, tail=250)
    return {"exit_code": code, "inventory": tail}


def t_detect_content(args, log):
    from vault.importing.unified.detection import detect_content_type
    from core.rar_tools import rar_to_temp_zip
    p = Path(args["file"]).resolve()
    if not p.exists():
        raise ValueError(f"file missing: {p}")
    # The classifier only reads zips; /import/file repacks .rar before it gets
    # there, so do the same here or the tool disagrees with the real import.
    converted = rar_to_temp_zip(str(p)) if p.suffix.lower() == ".rar" else None
    try:
        return detect_content_type(str(converted or p), filename=p.name,
                                   deep=bool(args.get("deep", True)))
    finally:
        if converted:
            Path(converted).unlink(missing_ok=True)


def t_hsdraw(args, log):
    argv = [str(a) for a in args["args"]]
    if not argv or not argv[0].startswith("--"):
        raise ValueError("first arg must be a --mode flag (e.g. --csp, "
                         "--model, --dobj-info); a bare path would open the "
                         "GUI and hang this server")
    exe = Path(HSDRAW_EXE)
    if not exe.exists():
        raise RuntimeError(f"HSDRawViewer.exe missing: {exe} (run "
                           "python tools/build/fetch_native.py hsdlib)")
    code, tail = _run_cli([str(exe)] + argv, log, tail=120,
                          cwd=PROJECT_ROOT)
    return {"exit_code": code, "ok": code == 0, "log_tail": tail}


def t_mexcli(args, log):
    argv = [str(a) for a in args["args"]]
    exe = Path(MEXCLI_PATH).resolve()
    if not exe.exists():
        raise RuntimeError(f"mexcli.exe missing: {exe}")
    stdin_text = None
    if args.get("stdin_json") is not None:
        stdin_text = json.dumps(args["stdin_json"])
    code, tail = _run_cli([str(exe)] + argv, log, tail=120,
                          cwd=PROJECT_ROOT, stdin_text=stdin_text)
    parsed = None
    for line in reversed(tail):        # mexcli prints noise then JSON last
        s = line.strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                parsed = json.loads(s)
            except Exception:
                pass
            break
    result = {"exit_code": code, "json": parsed, "log_tail": tail[-40:]}
    if code == 0 and argv and argv[0].lower() == "export":
        output = parsed.get("outputPath") if isinstance(parsed, dict) else None
        if not output:
            raise RuntimeError("Successful ISO export omitted its outputPath; cannot admit DVD reads")
        output = Path(output)
        if not output.is_absolute():
            output = Path(PROJECT_ROOT) / output
        from core.iso_reads import ensure_padding
        result["dvd_read_admission"] = ensure_padding(output)
    return result


def t_wait_for_file(args, log):
    p = Path(args["path"])
    min_bytes = int(args.get("min_bytes", 1))
    stable = float(args.get("stable_seconds", 3))
    timeout = float(args.get("timeout", 900))
    t0, last_size, last_change = time.time(), -1, time.time()
    while time.time() - t0 < timeout:
        size = p.stat().st_size if p.exists() else -1
        if size != last_size:
            last_size, last_change = size, time.time()
            log(f"{p.name}: {max(size, 0) // (1024*1024)} MB")
        elif size >= min_bytes and time.time() - last_change >= stable:
            return {"ok": True, "path": str(p), "bytes": size,
                    "waited_seconds": round(time.time() - t0, 1)}
        time.sleep(1.0)
    return {"ok": False, "path": str(p),
            "bytes": max(last_size, 0),
            "note": f"not stable/present within {timeout}s"}


# ---------------------------------------------------------------------------
# Decomp reference -- read-only lookups into the local Melee decompilation
# (github.com/doldecomp/melee checkout). The DOL is statically loaded, so a
# symbol's 0x80xxxxxx address in symbols.txt IS its live MEM1 address: chain
# decomp -> read_ram/write_ram to inspect or poke engine state by name.
# ---------------------------------------------------------------------------
_DECOMP = {"root": None, "symbols": None}
_SYM_RE = re.compile(r"^(\S+)\s*=\s*([.\w]+):0x([0-9A-Fa-f]+);\s*//\s*(.*)$")


def _decomp_root():
    if _DECOMP["root"] is not None:
        return _DECOMP["root"]
    cands = [Path(p) for p in (os.environ.get("MELEE_DECOMP", ""),) if p]
    cands += [p / "melee" for p in Path(PROJECT_ROOT).resolve().parents]
    cands.append(Path.home() / "projects" / "melee")
    for c in cands:
        if (c / "config" / "GALE01" / "symbols.txt").is_file():
            _DECOMP["root"] = c.resolve()
            return _DECOMP["root"]
    raise RuntimeError(
        "melee decomp not found -- set MELEE_DECOMP to the repo root "
        "(must contain config/GALE01/symbols.txt)")


def _decomp_symbols():
    if _DECOMP["symbols"] is None:
        syms = []
        txt = (_decomp_root() / "config" / "GALE01" / "symbols.txt").read_text(
            encoding="utf-8", errors="replace")
        for line in txt.splitlines():
            m = _SYM_RE.match(line.strip())
            if not m:
                continue
            attrs = dict(kv.split(":", 1) for kv in m.group(4).split()
                         if ":" in kv)
            try:
                size = int(attrs.get("size", "0"), 16)
            except ValueError:
                size = 0
            syms.append({"name": m.group(1), "section": m.group(2),
                         "addr": int(m.group(3), 16), "size": size,
                         "type": attrs.get("type"),
                         "scope": attrs.get("scope")})
        syms.sort(key=lambda s: s["addr"])
        _DECOMP["symbols"] = syms
    return _DECOMP["symbols"]


def _sym_out(s):
    return {"name": s["name"], "addr": f"0x{s['addr']:08X}",
            "section": s["section"], "type": s["type"],
            "size": hex(s["size"]) if s["size"] else None,
            "scope": s["scope"]}


def _decomp_src_files(root, path_filter=""):
    for base in ("src", "include"):
        top = root / base
        if not top.is_dir():
            continue
        for dirpath, _dirs, files in os.walk(top):
            for fn in files:
                if not fn.endswith((".c", ".h")):
                    continue
                p = Path(dirpath) / fn
                rel = p.relative_to(root).as_posix()
                if path_filter and path_filter not in rel:
                    continue
                yield p, rel


def t_decomp(args, log):
    op = args.get("op") or ("symbol" if args.get("query") else
                            "addr" if args.get("addr") else "info")
    root = _decomp_root()
    limit = max(1, min(int(args.get("limit", 0) or 0) or 40, 200))

    if op == "info":
        syms = _decomp_symbols()
        return {
            "root": str(root), "symbols": len(syms),
            "ops": {"symbol": "{query} name search (regex or substring)",
                    "addr": "{addr} -> containing symbol + offset",
                    "grep": "{pattern, path?} regex over decomp src/+include/",
                    "source": "{symbol} -> the function's C source"},
            "notes": [
                "The DOL is statically loaded: symbols.txt addresses ARE "
                "live MEM1 addresses -- feed them to read_ram/write_ram.",
                "m-ex builds hook/relocate a few functions and add content "
                "(MxDt, added fighters) the decomp doesn't know; vanilla "
                "symbols still resolve for the vast majority of the engine.",
                "Fighter code is under src/melee/ft/, menus src/melee/mn/, "
                "scenes src/melee/gm/, sysdolphin src/sysdolphin/.",
            ]}

    if op == "symbol":
        query = (args.get("query") or "").strip()
        if not query:
            raise ValueError("op=symbol needs query")
        try:
            rx = re.compile(query, re.IGNORECASE)
        except re.error:
            rx = re.compile(re.escape(query), re.IGNORECASE)
        hits = [s for s in _decomp_symbols() if rx.search(s["name"])]
        return {"query": query, "total": len(hits),
                "truncated": len(hits) > limit,
                "symbols": [_sym_out(s) for s in hits[:limit]]}

    if op == "addr":
        target = int(str(args.get("addr", "")).strip(), 16)
        syms = _decomp_symbols()
        i = bisect.bisect_right([s["addr"] for s in syms], target) - 1
        if i < 0:
            return {"addr": f"0x{target:08X}", "symbol": None,
                    "note": "below the first known symbol"}
        s = syms[i]
        out = {"addr": f"0x{target:08X}", "symbol": _sym_out(s),
               "offset": hex(target - s["addr"])}
        if s["size"] and target >= s["addr"] + s["size"]:
            out["note"] = ("past the end of this symbol -- gap or unnamed "
                           "data; next symbol follows")
        if i + 1 < len(syms):
            out["next_symbol"] = _sym_out(syms[i + 1])
        return out

    if op == "grep":
        pattern = args.get("pattern") or ""
        if not pattern:
            raise ValueError("op=grep needs pattern")
        rx = re.compile(pattern)
        path_filter = (args.get("path") or "").replace("\\", "/")
        matches, files_hit, truncated = [], 0, False
        for p, rel in _decomp_src_files(root, path_filter):
            try:
                lines = p.read_text(encoding="utf-8",
                                    errors="replace").splitlines()
            except OSError:
                continue
            hit = False
            for n, line in enumerate(lines, 1):
                if rx.search(line):
                    hit = True
                    if len(matches) < limit:
                        matches.append(f"{rel}:{n}: {line.strip()[:200]}")
                    else:
                        truncated = True
            files_hit += hit
        return {"pattern": pattern, "path_filter": path_filter or None,
                "files_with_matches": files_hit, "truncated": truncated,
                "matches": matches}

    if op == "source":
        name = (args.get("symbol") or "").strip()
        if not name:
            raise ValueError("op=source needs symbol")
        sym = next((s for s in _decomp_symbols() if s["name"] == name), None)
        # a definition line references the symbol, isn't a call/prototype
        def_rx = re.compile(
            r"^[A-Za-z_][\w \t*]*\b" + re.escape(name) + r"\s*\(")
        max_lines = max(20, min(int(args.get("max_lines", 0) or 0) or 400,
                                2000))
        for p, rel in _decomp_src_files(root):
            if not p.name.endswith(".c"):
                continue
            try:
                lines = p.read_text(encoding="utf-8",
                                    errors="replace").splitlines()
            except OSError:
                continue
            for n, line in enumerate(lines):
                if not def_rx.match(line) or line.rstrip().endswith(";"):
                    continue
                end = n
                for j in range(n, min(n + max_lines, len(lines))):
                    end = j
                    if lines[j].startswith("}"):
                        break
                body = "\n".join(lines[n:end + 1])
                return {"symbol": name, "file": rel, "line": n + 1,
                        "addr": _sym_out(sym) if sym else None,
                        "truncated": not lines[end].startswith("}"),
                        "source": body}
        return {"symbol": name, "source": None,
                "addr": _sym_out(sym) if sym else None,
                "note": "no definition found in decomp .c files (asm-only or "
                        "data symbol?) -- try op=grep"}

    raise ValueError(f"unknown op '{op}' (symbol|addr|grep|source|info)")


# ---------------------------------------------------------------------------
# Wave 3 (gap audit): ISO file access, RAM search/diff, stock icons, stage
# capture, extras triage, FSM patching, regression suite, m-ex codes.
# ---------------------------------------------------------------------------
def t_iso_file(args, log):
    from shared.vanilla_extract import vanilla_refs
    op = args.get("op", "list")
    if op == "ensure_ref":
        p = vanilla_refs.ensure_vanilla_ref(args["filename"])
        if p is None:
            raise RuntimeError(
                "could not resolve a vanilla reference (no recorded vanilla "
                "ISO in storage/vanilla_iso.json, or the file is not on the "
                "disc) -- pass op=extract with an explicit iso instead")
        return {"path": str(p), "bytes": p.stat().st_size,
                "note": "cached under storage/test-base/files/"}
    iso = args.get("iso")
    iso = Path(iso).resolve() if iso else vanilla_refs.known_vanilla_iso()
    if not iso or not Path(iso).is_file():
        raise ValueError("pass iso=<path> -- no recorded vanilla ISO to "
                         "default to")
    if op == "list":
        files = vanilla_refs.list_files_in_iso(iso, contains=args.get("contains"))
        cap = 400
        return {"iso": str(iso), "total": len(files),
                "truncated": len(files) > cap,
                "files": files[:cap]}
    if op == "extract":
        filename = str(args["filename"])
        dest = Path(args.get("dest") or (MCP_OUT / "iso" / Path(filename).name))
        if not vanilla_refs.extract_file_from_iso(iso, filename, dest):
            raise RuntimeError(f"'{filename}' not found on {iso} "
                               "(op=list with contains= to browse names)")
        return {"path": str(dest), "bytes": dest.stat().st_size,
                "iso": str(iso)}
    raise ValueError(f"unknown op '{op}' (list|extract|ensure_ref)")


_RAM_SNAPSHOTS = {}                     # name -> bytes(MEM1); ~24 MB each
_RAM_SNAPSHOTS_MAX = 4


def t_ram_search(args, log):
    SESSION.require()
    from shared.ingame.melee_mem import GC_BASE, MEM1_VALID
    mode = args.get("mode", "find")

    def _bound(key, default):
        v = args.get(key)
        return (int(str(v), 0) - GC_BASE) if v is not None else default
    lo = max(0, _bound("start", 0))
    hi = min(MEM1_VALID, _bound("end", MEM1_VALID))
    if lo >= hi:
        raise ValueError("start must be below end (GC addresses, MEM1)")

    if mode == "snapshot":
        mem = SESSION.d.snapshot()
        if not mem:
            raise RuntimeError("MEM1 snapshot failed")
        name = str(args.get("name", "base"))
        if name not in _RAM_SNAPSHOTS and \
                len(_RAM_SNAPSHOTS) >= _RAM_SNAPSHOTS_MAX:
            _RAM_SNAPSHOTS.pop(next(iter(_RAM_SNAPSHOTS)))
        _RAM_SNAPSHOTS[name] = bytes(mem)
        return {"snapshot": name, "bytes": len(mem),
                "held": list(_RAM_SNAPSHOTS)}

    if mode == "find":
        if args.get("hex"):
            needle = bytes.fromhex(args["hex"])
            align = 1
        elif args.get("value") is not None:
            import struct as _s
            t = str(args.get("type", "u32"))
            if t == "f32":
                needle = _s.pack(">f", float(args["value"]))
            elif t in ("u32", "s32"):
                needle = int(str(args["value"]), 0).to_bytes(4, "big",
                             signed=(t == "s32"))
            elif t == "u16":
                needle = int(str(args["value"]), 0).to_bytes(2, "big")
            elif t == "u8":
                needle = int(str(args["value"]), 0).to_bytes(1, "big")
            else:
                raise ValueError(f"unknown type '{t}' (u8|u16|u32|s32|f32)")
            align = len(needle)
        else:
            raise ValueError("mode=find needs hex=<bytes> or value=+type=")
        mem = SESSION.d.snapshot()
        if not mem:
            raise RuntimeError("MEM1 snapshot failed")
        cap = max(1, min(int(args.get("limit", 0) or 0) or 200, 1000))
        hits, i = [], lo
        while len(hits) < cap:
            i = mem.find(needle, i, hi)
            if i < 0:
                break
            if i % align == 0 or bool(args.get("unaligned")):
                hits.append(f"0x{GC_BASE + i:08X}")
            i += 1
        return {"needle": needle.hex(), "count": len(hits),
                "truncated": len(hits) >= cap, "addrs": hits,
                "note": "chain hits through decomp op=addr to name them"}

    if mode == "diff":
        name = str(args.get("name", "base"))
        base = _RAM_SNAPSHOTS.get(name)
        if base is None:
            raise ValueError(f"no snapshot '{name}' -- run mode=snapshot first "
                             f"(held: {list(_RAM_SNAPSHOTS) or 'none'})")
        cur = SESSION.d.snapshot()
        if not cur:
            raise RuntimeError("MEM1 snapshot failed")
        cap = max(1, min(int(args.get("limit", 0) or 0) or 200, 1000))
        gap = 8                          # merge changed runs this close
        regions, i, truncated = [], lo, False
        n = min(hi, len(base), len(cur))
        while i < n:
            if base[i] == cur[i]:
                i += 1
                continue
            j = i + 1
            last_diff = i
            while j < n and j - last_diff <= gap:
                if base[j] != cur[j]:
                    last_diff = j
                j += 1
            if len(regions) >= cap:
                truncated = True
                break
            size = last_diff - i + 1
            regions.append({
                "addr": f"0x{GC_BASE + i:08X}", "size": size,
                "old": base[i:i + min(size, 32)].hex(),
                "new": cur[i:i + min(size, 32)].hex(),
            })
            i = last_diff + 1
        return {"vs_snapshot": name, "regions": len(regions),
                "truncated": truncated, "changes": regions}

    raise ValueError(f"unknown mode '{mode}' (find|snapshot|diff)")


def t_render_stock(args, log):
    from shared.rendering.costume_assets import build_stock
    src = Path(args["dat"]).resolve()
    if not src.exists():
        raise ValueError(f"DAT missing: {src}")
    code = args.get("costume_code") or src.stem
    csp = None
    if args.get("csp"):
        csp = Path(args["csp"]).read_bytes()
    log(f"deriving stock icon for {src.name} ({args['character']}/{code})...")
    png, source, method = build_stock(
        args["character"], code, src.read_bytes(), dat_path=str(src),
        aligned_csp=csp, vanilla_fallback=bool(args.get("vanilla_fallback", True)),
        color_index=args.get("color_index"))
    if png is None:
        raise RuntimeError(f"no stock icon derivable (source={source}) -- for "
                           "model imports pass csp=<our own render_csp output>")
    MCP_OUT.mkdir(parents=True, exist_ok=True)
    out = MCP_OUT / f"stock-{code}-{time.strftime('%H%M%S')}.png"
    out.write_bytes(png)
    return {"_image": base64.b64encode(png).decode(), "file": str(out),
            "source": source, "method": method}


def t_stage_workbench(args, log):
    tools_dir = str(REPO_ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    from stages.workbench import handle
    return handle(args, log)


def t_stage_shot(args, log):
    sweep = args.get("framing_sweep")
    if sweep is not None:
        import math
        if args.get("pause") or args.get("variants"):
            raise ValueError("framing_sweep is for a single stage, not pause/variant mode")
        if not isinstance(sweep, list) or not 1 <= len(sweep) <= 32:
            raise ValueError("framing_sweep needs 1..32 camera views")
        for view in sweep:
            for key in ("eye", "interest"):
                xyz = view.get(key)
                if not isinstance(xyz, (list, tuple)) or len(xyz) != 3 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in xyz):
                    raise ValueError(f"Each sweep {key} must have 3 finite world coordinates")
            fov = view.get("fov", 30)
            if not isinstance(fov, (int, float)) or not 1 <= fov < 179 or view["eye"] == view["interest"]:
                raise ValueError("Sweep needs a valid fov and distinct eye/interest")
        sweep = [dict(v, fov=v.get("fov", 30)) for v in sweep]
    _no_session("stage_shot")
    from shared.ingame import capture
    iso = _resolve_iso(args.get("iso"))
    if args.get("wait_for_dolphin") is not None:
        os.environ["MELEE_DOLPHIN_LOCK_WAIT"] = str(float(args["wait_for_dolphin"]))
    fs.RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    MCP_OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%H%M%S")

    def emit(stage, pct, message):
        log(f"[{pct}%] {stage}: {message}")

    def _save(tag, png):
        tag = re.sub(r"[^A-Za-z0-9._-]", "_", str(tag))
        p = MCP_OUT / f"stage-{tag}-{stamp}.png"
        p.write_bytes(png)
        return p

    def _inline(png, out):
        from PIL import Image
        img = Image.open(io.BytesIO(png))
        w = int(args.get("max_width", 640))
        if img.width > w:
            img = img.resize((w, round(img.height * w / img.width)))
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        out["_image"] = base64.b64encode(buf.getvalue()).decode()

    if args.get("pause"):
        r = capture.capture_pause(str(iso), None, str(fs.RUNS_ROOT),
                                  emit=emit, log=log)
        out = {"ok": r["ok"], "reason": r.get("reason") or None}
        if r.get("png"):
            out["file"] = str(_save("pause", r["png"]))
            _inline(r["png"], out)
        return out

    if args.get("variants"):
        r = capture.capture_stage_batch(str(iso), None, str(fs.RUNS_ROOT),
                                        list(args["variants"]),
                                        emit=emit, log=log)
        shots, first = [], None
        for s in r.get("shots", []):
            entry = {"id": s.get("id"), "button": s.get("button")}
            if s.get("png"):
                entry["file"] = str(_save(str(s.get("id")), s["png"]))
                if first is None:
                    first = s["png"]
            shots.append(entry)
        out = {"ok": r.get("ok", False), "shots": shots,
               "failures": r.get("failures") or [],
               "crashed_id": r.get("crashed_id"),
               "reason": r.get("reason") or None}
        if first:
            _inline(first, out)
        return out

    stage = str(args.get("stage", "finaldestination"))
    if args.get("internal_id") is not None:
        internal = int(str(args["internal_id"]), 0)
    elif stage in INTERNAL_STAGE_ID:
        internal = INTERNAL_STAGE_ID[stage]
    else:
        raise ValueError(f"unknown stage '{stage}' -- pass internal_id for "
                         f"non-legal stages (known: "
                         f"{', '.join(sorted(INTERNAL_STAGE_ID))})")
    framing = args.get("framing_key") or (
        stage if args.get("internal_id") is None else None)
    r = capture.capture_stage(str(iso), None, str(fs.RUNS_ROOT), internal,
                              hold=args.get("hold"),
                              framing_key=framing,
                              emit=emit, log=log,
                              hires_textures=bool(args.get("hires_textures")),
                              framing_sweep=sweep,
                              stadium_form=args.get("stadium_form"))
    out = {"ok": r["ok"], "reason": r.get("reason") or None,
           "internal_id": internal}
    if r.get("stadium"):
        out["stadium"] = r["stadium"]
    if sweep is not None:
        out["shots"] = []
        first = None
        captured = r.get("shots", [])
        for i, view in enumerate(sweep):
            result = captured[i] if i < len(captured) else {}
            entry = {"index": i, "framing": view,
                     "ok": bool(result.get("png")), "reason": result.get("reason") or r.get("reason")}
            if result.get("png"):
                entry["file"] = str(_save(f"{stage}-{i}", result["png"]))
                first = first or result["png"]
            out["shots"].append(entry)
        out["ok"] = all(s["ok"] for s in out["shots"])
        out["framing_source"] = "Posed debug cameras; not captured match-camera motion"
        if first:
            _inline(first, out)
        return out
    if r.get("png"):
        out["file"] = str(_save(stage, r["png"]))
        _inline(r["png"], out)
    return out


def t_extras_doctor(args, log):
    cmd = [sys.executable, "devtools/extras_doctor.py",
           "--project", str(args["project"]), "--char", str(args["char"])]
    if args.get("extra"):
        cmd += ["--extra", str(args["extra"])]
    if args.get("verbose"):
        cmd += ["-v"]
    code, tail = _run_cli(cmd, log, tail=250)
    return {"exit_code": code, "ok": code == 0, "report": tail}


def t_fsm_patch(args, log):
    from projects.install import fsm_patcher
    op = args.get("op", "state")
    dol = Path(args["dol"]).resolve()
    if not dol.exists():
        raise ValueError(f"DOL missing: {dol}")
    try:
        if op == "state":
            return {"dol": str(dol), "state": fsm_patcher.get_patch_state(dol)}
        if op == "apply":
            text = (Path(args["fsm_txt"]).read_text(encoding="utf-8",
                                                    errors="replace")
                    if args.get("fsm_txt") else str(args.get("text", "")))
            if not text.strip():
                raise ValueError("op=apply needs fsm_txt=<path> or text=")
            entries = fsm_patcher.parse_fsm_txt(text)
            if args.get("external_id") is not None:
                entries = fsm_patcher.retarget_entries(
                    entries, int(str(args["external_id"]), 0))
            fsm_patcher.apply_fsm_patch(dol, entries)
            return {"dol": str(dol), "applied_entries": len(entries),
                    "state": fsm_patcher.get_patch_state(dol),
                    "note": "revertible via op=remove (sidecar backup)"}
        if op == "remove":
            fsm_patcher.remove_fsm_patch(dol)
            return {"dol": str(dol), "state": fsm_patcher.get_patch_state(dol)}
    except fsm_patcher.FsmError as e:
        raise RuntimeError(str(e))
    raise ValueError(f"unknown op '{op}' (state|apply|remove)")


def t_csp_regression(args, log):
    suite = (RESOURCES_DIR / "utility" / "tools" / "processor" /
             "csp_regression")
    cmd = [sys.executable, "run_regression.py"]
    if args.get("update_goldens"):
        cmd += ["--update-goldens"]
    if args.get("exe"):
        cmd += ["--exe", str(args["exe"])]
    if args.get("pool"):
        cmd += ["--pool", str(int(args["pool"]))]
    for extra in args.get("extra_args") or []:
        cmd.append(str(extra))
    code, tail = _run_cli(cmd, log, tail=250, cwd=suite)
    return {"exit_code": code, "ok": code == 0, "log_tail": tail}


def t_fps_batch(args, log):
    _no_session("fps_batch")
    cmd = [sys.executable, "devtools/fps_batch.py",
           "--mode", str(args.get("mode", "offline"))]
    for iso in args.get("isos") or []:
        cmd.append(str(iso))
    code, tail = _run_cli(cmd, log, tail=200, env=_lock_env(args))
    return {"exit_code": code, "ok": code == 0, "log_tail": tail}


# --- netplay desync test (backend/devtools/netrig.py + slpdiff.py) ----------
NETRIG = BACKEND / "devtools" / "netrig.py"
SLPDIFF = BACKEND / "devtools" / "slpdiff.py"


def _netrig_root():
    return Path(os.environ.get("NETRIG_ROOT") or Path.home() / "slippi-desync-rig")


def _slippi_code(user_dir):
    try:
        return json.loads((Path(user_dir) / "Slippi" / "user.json").read_text(
            encoding="utf-8")).get("connectCode") or None
    except (OSError, ValueError):
        return None


def _rig_python():
    """The Python the rig runs in: the creation settings' "python" (the one with
    vgamepad), else this one."""
    from creation.workflows import settings as creation_settings
    return str((creation_settings() or {}).get("python") or sys.executable)


def _has_module(python, name):
    try:
        ran = subprocess.run([python, "-c", f"import importlib.util as u, sys; "
                              f"sys.exit(0 if u.find_spec({name!r}) else 1)"],
                             capture_output=True, timeout=60)
        return ran.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _netrig_check():
    """What the two-client rig needs on this computer: {ready, problems, ...}."""
    python = _rig_python()
    root = _netrig_root()
    live = Path(os.environ.get("APPDATA", "")) / "Slippi Launcher" / "netplay"
    code_a = _slippi_code(root / "instance-a" / "User")
    code_b = _slippi_code(live / "User")
    problems = []
    if not (root / "instance-a" / "Slippi Dolphin.exe").is_file():
        problems.append(
            f"No rig at {root}: copy Slippi Launcher's netplay folder ({live}) to "
            f"{root / 'instance-a'} (or set NETRIG_ROOT), run that copy's Slippi "
            "Dolphin.exe once and log in there with a SECOND Slippi account. "
            "It keeps that login; the launcher stays on your main account.")
    elif not code_a:
        problems.append(f"{root / 'instance-a'} has no Slippi login: run its "
                        "Slippi Dolphin.exe once and log in with a second account.")
    if not code_b:
        problems.append("Slippi Launcher is not installed or not logged in "
                        f"(no user.json under {live}).")
    if code_a and code_b and code_a == code_b:
        problems.append(f"Both clients are the same account ({code_a}): the rig "
                        f"copy at {root / 'instance-a'} keeps its login, so sign "
                        "Slippi Launcher into a different Slippi account than the "
                        "rig's (usually your main one).")
    if not _has_module(python, "vgamepad"):
        problems.append(f"The two virtual controllers need vgamepad in {python} "
                        "(pip install vgamepad, which also installs the ViGEmBus "
                        "driver), or name a Python that has it as \"python\" in "
                        "app/scratch/creation/settings.json.")
    return {"ready": not problems, "problems": problems, "rig": str(root),
            "python": python, "client_a": code_a, "client_b": code_b}


def t_netplay_desync(args, log):
    op = str(args.get("op", "check"))
    if op == "check":
        return _netrig_check()
    if op in ("status", "kill"):
        code, tail = _run_cli([_rig_python(), str(NETRIG), op], log, tail=40)
        return {"exit_code": code, "output": tail}
    if op != "play":
        raise ValueError("op must be check|play|status|kill")
    ready = _netrig_check()
    if not ready["ready"]:
        return dict(ready, ok=False, verdict=None,
                    note="Set the rig up first (problems), then run op=play.")
    _no_session("netplay_desync")
    iso_a = _resolve_iso(args.get("iso"))
    iso_b = _resolve_iso(args.get("iso_b")) if args.get("iso_b") else iso_a
    cmd = [ready["python"], str(NETRIG), "play", "--iso-a", str(iso_a),
           "--iso-b", str(iso_b),
           "--char-a", str(args.get("char_a", "falcon")),
           "--char-b", str(args.get("char_b", "falcon")),
           "--costume-a", str(int(args.get("costume_a", 0))),
           "--costume-b", str(int(args.get("costume_b", 0))),
           "--throws", str(int(args.get("throws", 10))),
           "--moves", str(args.get("moves", "dthrow"))]
    for key, flag in (("stage", "--require-stage"), ("css_a", "--css-a"),
                      ("css_b", "--css-b"), ("min_seconds", "--min-seconds")):
        if args.get(key) not in (None, ""):
            cmd += [flag, str(args[key])]
    if args.get("inject_desync"):
        cmd.append("--inject-desync")
    code, tail = _run_cli(cmd, log, tail=200)
    verdict = next((ln.split("VERDICT:", 1)[1].strip(" =") for ln in reversed(tail)
                    if "=== VERDICT:" in ln), None)
    replays = [ln.split(":", 1)[1].strip() for ln in tail
               if ln.strip().startswith(("replay a:", "replay b:"))]
    out = {"exit_code": code, "verdict": verdict, "ok": verdict == "CLEAN",
           "clients": [ready["client_a"], ready["client_b"]], "replays": replays,
           "log_tail": tail[-60:]}
    if len(replays) == 2 and all(r and r != "None" and Path(r).is_file() for r in replays):
        dcode, dtail = _run_cli([ready["python"], str(SLPDIFF), *replays], log, tail=40)
        out["replay_diff"] = {"identical": dcode == 0, "diverged": dcode == 2,
                              "output": dtail}
    return out


def t_mex_codes(args, log):
    action = str(args.get("action", "status"))
    if action not in ("status", "backup", "update", "restore", "list"):
        raise ValueError("action must be status|backup|update|restore|list")
    cmd = [sys.executable, str(DEV_TOOLS / "mex_codes.py"),
           action]
    if action == "update" and args.get("include_ini"):
        cmd.append("--include-ini")
    if action == "restore":
        if not args.get("backup_dir"):
            raise ValueError("action=restore needs backup_dir (see "
                             "action=list)")
        cmd.append(str(args["backup_dir"]))
    code, tail = _run_cli(cmd, log, tail=120, cwd=PROJECT_ROOT)
    return {"exit_code": code, "ok": code == 0, "output": tail}


# ---------------------------------------------------------------------------
# Tool registry (name -> schema + handler). Descriptions carry the guidance
# that keeps agents off the wrong path -- that is half the point of this file.
# ---------------------------------------------------------------------------
def _obj(props, required=None):
    return {"type": "object", "properties": props, "required": required or []}

_CHAR = {"type": "string", "description":
         "character name (marth, fox, sheik, ...) or external id like '0x1A' "
         "(= FIRST m-ex added fighter; needs the built ISO)"}
_ISO = {"type": "string", "description":
        "ISO path; default output/harness-test.iso, falling back to the "
        "vanilla 1.02 in the repo root"}
_STAGE = {"type": "string", "description":
          "battlefield|dreamland|finaldestination|fountainofdreams|"
          "pokemonstadium|yoshisstory (default finaldestination)"}
_BAG = {"type": "string", "description":
        "add a punching-bag 2nd player (HUMAN port, no controller: stands "
        "still, never attacks, never moves the camera -- NEVER a CPU) so "
        "on-hit-only effects are capturable; char name, e.g. 'dk'"}
_WAIT_DOLPHIN = {"type": "number", "description":
                 "seconds to QUEUE for the machine-wide Dolphin lock if "
                 "another agent/process holds it (default 0 = fail fast "
                 "with the owner's identity; see dolphin_status)"}

TOOLS = [
    ("harness_info", "START HERE before any in-game work. Returns the "
     "harness ground rules (why gameplay tests must use this solo engine and "
     "never the tools/ingame/dolphin CPU/cursor path), valid moves/stages/chars, "
     "kirby-copy donors, and artifact locations.", _obj({}), t_harness_info),

    ("boot_match", "Boot an ISO into a solo offline match (no CPU, no CSS "
     "cursor -- player block written straight to RAM) and FREEZE it, ready "
     "for do_move/step/screenshot/poke tools. Takes ~60-90 s. One session at "
     "a time; end_session when done.", _obj({
         "iso": _ISO, "char": _CHAR,
         "debug_draw": {"type": "string", "enum": ["off", "overlay", "collision"],
                        "description": "retail attack/hurt collision graphics (default off)"},
         "color": {"type": "integer", "description": "costume slot (default 0)"},
         "stage": _STAGE, "bag": _BAG,
         "bag_color": {"type": "integer"},
         "bag_pos": {"type": "string", "description": "'dx,dy' park offset in "
                     "front of the attacker (default '8,0')"},
         "kirby_copy": {"type": "string", "description": "give a Kirby "
                        "attacker this donor's copy ability (KO->rebirth "
                        "primitive); REQUIRES bag=<same donor>"},
         "plain_bg": {"type": ["boolean", "string"], "description": "flat "
                      "stage background + no stage textures so effect colors "
                      "read unambiguously; true = gray 404040, or 'RRGGBB'"},
         "wait_for_dolphin": _WAIT_DOLPHIN,
     }), t_boot_match),

    ("debug_draw", "Toggle retail attack spheres and hurt capsules in the live match. "
     "Overlay keeps the model; collision hides it; off restores normal rendering.", _obj({
         "mode": {"type": "string", "enum": ["off", "overlay", "collision"]},
         "ports": {"type": "array", "items": {"type": "integer"}},
     }), t_debug_draw),

    ("game_state", "Snapshot the live session: action state id/name, anim "
     "frame, position, facing, airborne (+ bag), frozen flag, global frame "
     "counter. watch_seconds>0 also reports health: running|hung|crashed "
     "(use after risky inputs to detect a hang -- the frame counter stalls).",
     _obj({"watch_seconds": {"type": "number", "description":
           "unfreeze-style health watch window (game must be unfrozen to "
           "expect 'running')"}}), t_game_state),

    ("do_move", "Execute a move recipe from idle (auto-settles + recenters "
     "first, parks the bag if present) and leave the game FROZEN on the "
     "move's frame 1. Then use step + screenshot for frames 2..N.", _obj({
         "move": {"type": "string", "description": "one of: " + ", ".join(MOVES)},
         "rise": {"type": "integer", "description":
                  "frames to rise before an aerial (default 10)"},
     }, ["move"]), t_do_move),

    ("step", "Advance N logic frames via the debug-pause single-step "
     "handshake (TAS-exact; NEVER poke the step bytes yourself -- they "
     "wedge). Increments move_frame when a move is active.", _obj({
         "frames": {"type": "integer", "description": "default 1"},
         "bag_pin": {"type": "boolean", "description": "re-pin the bag every "
                     "frame so knockback can't push it out of range "
                     "(rapid-jab / command-grab finishers)"},
     }), t_step),

    ("send_input", "Send raw controller-pipe lines as ONE atomic frame, e.g. "
     "['SET MAIN 1.000 0.500','PRESS B'] = side-B. Stick range 0..1, 0.5 "
     "center, y=1 UP. Buttons: A B X Y Z L R START D_UP... Use then_step to "
     "advance frames after, then_neutral to release everything.", _obj({
         "lines": {"type": "array", "items": {"type": "string"}},
         "then_step": {"type": "integer"},
         "then_neutral": {"type": "boolean"},
     }, ["lines"]), t_send_input),

    ("screenshot", "Capture the live Dolphin frame (PrintWindow -- works "
     "occluded/background). Saves full-res PNG to the session out_dir and "
     "returns an inline image (default 640 px wide). Re-asserts plain_bg "
     "pokes before grabbing.", _obj({
         "label": {"type": "string", "description":
                   "filename stem; default <char>-<move>-f<NN>"},
         "max_width": {"type": "integer", "description":
                       "inline image width (default 640)"},
     }), t_screenshot),

    ("read_ram", "Read live GameCube RAM (MEM1, big-endian). addr accepts "
     "'0x80453080'. Returns hex (+u32/f32 when size=4).", _obj({
         "addr": {"type": "string"},
         "size": {"type": "integer", "description": "bytes, default 4, max 4096"},
     }, ["addr"]), t_read_ram),

    ("write_ram", "Write bytes to live RAM and verify by readback. Use for "
     "one-off pokes; for DAT-file experiments prefer poke_dat (it finds all "
     "resident copies and can restore vanilla bytes).", _obj({
         "addr": {"type": "string"}, "hex": {"type": "string"},
     }, ["addr", "hex"]), t_write_ram),

    ("poke_dat", "Locate a DAT file's loaded image in MEM1 (datram.py "
     "majority-vote match) and poke FILE offsets live -- no rebuild, no "
     "reboot. Pass hex to poke, or restore=<n bytes> to undo. Locate only "
     "works once the match has the file resident; pokes don't survive a "
     "scene reload.", _obj({
         "file": {"type": "string", "description":
                  "path to the DAT on disk, e.g. storage/test-base/files/EfFxData.dat"},
         "offset": {"type": "string", "description": "file offset, e.g. '0x1A884'"},
         "hex": {"type": "string"},
         "restore": {"type": "integer", "description":
                     "restore this many vanilla bytes at offset instead"},
     }, ["file", "offset"]), t_poke_dat),

    ("set_player", "Teleport a fighter (set_pos) and/or set percent. port 0 "
     "= attacker, 1 = bag.", _obj({
         "port": {"type": "integer"}, "x": {"type": "number"},
         "y": {"type": "number"}, "percent": {"type": "number"},
     }), t_set_player),

    ("freeze", "Freeze (frozen=true) or unfreeze the game logic via the "
     "retail debug-pause bit. Unfreeze to observe real-time behavior (crash "
     "watches); rendering runs either way.", _obj({
         "frozen": {"type": "boolean"},
     }), t_freeze),

    ("end_session", "Close the session's Dolphin and delete its throwaway "
     "User dir. ALWAYS call when done (also required before frameshot/"
     "effect_probe/run_ingame_test).", _obj({}), t_end_session),

    ("frameshot", "One-shot frame-exact move screenshots ('marth fair frame "
     "4') via frameshot.py in a subprocess: boots, captures, cleans up. Use "
     "shots=['fair:1-8','fsmash:10'] for many moves in ONE boot, and "
     "targets=[{id,char,color,shots?},...] for many CHARACTERS/COSTUMES in one "
     "boot (~15s each vs ~90s per boot) -- the way to sweep a costume roster. "
     "Returns PNG paths + JSON sidecars (state/anim/pos per capture, bag.hit), "
     "plus a `batch` manifest for targets runs: trust its per-target status "
     "('ok'), NOT the file list -- a hung target is reported, never faked. "
     "Prefer the live session tools when you'll iterate interactively.",
     _obj({
         "char": _CHAR, "iso": _ISO, "stage": _STAGE,
         "color": {"type": "integer"},
         "targets": {"type": "array", "items": {"type": "object"},
                     "description": "batch mode: [{'id','char','color',"
                     "'shots'?}] captured in ONE boot (quit-to-CSS between "
                     "targets); `shots` here is the per-target default"},
         "shots": {"type": "array", "items": {"type": "string"},
                   "description": "repeatable 'move:frames' specs, frames = "
                   "'4' | '1-8' | '1,4,7'"},
         "move": {"type": "string", "description": "single-move form"},
         "frames": {"type": "string"},
         "plain_bg": {"type": ["boolean", "string"]},
         "bag": _BAG, "bag_pos": {"type": "string"},
         "bag_pin": {"type": "boolean"},
         "kirby_copy": {"type": "string"},
         "input_at": {"type": "array", "items": {"type": "string"},
                      "description": "'N:LINE[|LINE]' raw pipe lines on move "
                      "frame N (charged specials)"},
         "rise": {"type": "integer"},
         "wait_for_dolphin": _WAIT_DOLPHIN,
     }), t_frameshot),

    ("effect_probe", "Run a spec-driven live-poke probe (effect_probe.py): "
     "one boot, locate DATs, apply/verify/restore pokes per experiment, "
     "capture per-move frames. Pass the spec as an inline object or a file "
     "path; dry_run parses + prints the plan without booting. Spec format: "
     "backend/probes/effect_probe.example.json.", _obj({
         "spec": {"type": ["object", "string"]},
         "dry_run": {"type": "boolean"},
         "wait_for_dolphin": _WAIT_DOLPHIN,
     }, ["spec"]), t_effect_probe),

    ("run_ingame_test", "Full automated verdict on a built ISO (the in-app "
     "'Test in game' engine): boot -> offline match -> optional manifest-"
     "driven checks -> PASS/CRASH/HUNG + screenshot. Use for crash-testing "
     "builds; takes a few minutes.", _obj({
         "iso": _ISO,
         "manifest": {"type": "object", "description":
                      "optional build manifest (costume/character/customStage/"
                      "das/effect keys -- see docs/dev/INGAME_TESTING.md)"},
         "observe_seconds": {"type": "integer"},
         "wait_for_dolphin": _WAIT_DOLPHIN,
     }), t_run_ingame_test),

    ("dolphin_status", "Machine-wide Dolphin ownership check: who (which "
     "process/agent) holds the emulator lock, for what purpose, since when, "
     "whether a Dolphin process is actually running, and whether THIS "
     "session owns it. Call before booting anything if another agent might "
     "be testing; to queue instead of failing, pass wait_for_dolphin=<sec> "
     "on boot_match/frameshot/effect_probe/run_ingame_test.", _obj({}),
     t_dolphin_status),

    # --- app backend (REST) ------------------------------------------------
    ("backend_start", "Start (or attach to) a headless Nucleus app backend "
     "for vault/project/build operations. Spawns the dev Flask instance "
     "(repo storage/, auto-picks a free port -- never fights the installed "
     "desktop app). Required before api/vault_import/vault_list/retake_csp. "
     "Prefer REST over raw mexcli for anything touching the vault or a "
     "shared project: the blueprints hold the workspace locks and encode "
     "Slippi auto-fix, Gecko injection on export, DAS healing.", _obj({
         "url": {"type": "string", "description": "attach to an already-"
                 "running backend instead of spawning (e.g. "
                 "http://127.0.0.1:5000 = the desktop app)"},
     }), t_backend_start),

    ("backend_stop", "Shut down the spawned backend (POST /shutdown + kill). "
     "Also runs automatically on server exit.", _obj({}), t_backend_stop),

    ("api", "Call ANY backend REST endpoint (~230 routes; the authoritative "
     "list is docs/dev/API_REFERENCE.md). JSON body via `body`, multipart upload "
     "via `file`+`fields`. NOTE: export/start returns immediately and "
     "finishes via Socket.IO -- poll its output artifact with wait_for_file "
     "instead; setup/start and test-in-game starts return a jobId to poll "
     "at /api/jobs/<jobId>. Do NOT call "
     "test-in-game routes while a live boot_match session is running (both "
     "want Dolphin).", _obj({
         "route": {"type": "string", "description": "e.g. /api/mex/status"},
         "method": {"type": "string", "description": "GET|POST|DELETE (default GET)"},
         "body": {"type": "object"},
         "file": {"type": "string", "description": "path to upload as "
                  "multipart (forces POST)"},
         "fields": {"type": "object", "description": "extra multipart form fields"},
         "file_field": {"type": "string", "description": "multipart field name (default 'file')"},
         "timeout": {"type": "integer", "description": "seconds (default 300)"},
     }, ["route"]), t_api),

    ("vault_import", "Add a mod to the vault: uploads any zip/7z to the "
     "universal auto-detect importer (/api/mex/import/file). Handles "
     "costumes, stages, custom characters/stages, patches, bundles, menu "
     "mods, sound banks, nested container zips (2 levels), Slippi auto-fix, "
     "duplicate skip.", _obj({
         "file": {"type": "string", "description": "path to the mod archive"},
         "slippi_action": {"type": "string", "description": "optional: fix|keep"},
         "duplicate_action": {"type": "string", "description": "optional: skip|import"},
         "custom_title": {"type": "string"},
     }, ["file"]), t_vault_import),

    ("vault_list", "List vault/project content (trimmed to fit context). "
     "kinds: costumes (per-character skins; pass character=), das_variants "
     "(pass character=stage name), custom_characters, custom_stages, "
     "project_fighters, metadata (FULL metadata.json -- huge, avoid).",
     _obj({
         "kind": {"type": "string", "description": "default costumes"},
         "character": {"type": "string"},
     }), t_vault_list),

    ("retake_csp", "Re-render vault CSP portrait(s) headlessly with the "
     "character's active pose ('Retake CSP'): preview render, then apply "
     "back to the vault (apply=false for preview only). Returns the first "
     "portrait inline.", _obj({
         "character": {"type": "string"},
         "skin_id": {"type": "string", "description": "single vault skin id"},
         "skin_ids": {"type": "array", "items": {"type": "string"},
                      "description": "batch form"},
         "apply": {"type": "boolean", "description": "default true"},
     }, ["character"]), t_retake_csp),

    ("build_modded_iso", "Build a modded ISO end-to-end via the proven Node "
     "harness (project create -> install -> icon placement -> export -> "
     "poll): type=costume|character|stage|das|effect|menu|modpack|stress. "
     "Uses the running backend_start instance if any, else spawns its own. "
     "Takes minutes; returns the build manifest (consumed by "
     "run_ingame_test-style checks). Writes projects/<name> + output/"
     "<name>.iso.", _obj({
         "type": {"type": "string", "description": "default costume"},
         "mod": {"type": "string", "description": "vault item id/slug/name"},
         "fighter": {"type": "string"},
         "iso": {"type": "string", "description": "vanilla ISO path"},
         "name": {"type": "string", "description": "project name (default harness-test)"},
         "compression": {"type": "number"},
         "stage": {"type": "string"}, "extra": {"type": "string"},
         "menu": {"type": "string"}, "count": {"type": "integer"},
         "export_only": {"type": "boolean", "description":
                         "re-export existing project"},
         "extra_args": {"type": "array", "items": {"type": "string"},
                        "description": "raw extra flags (see script header)"},
     }), t_build_modded_iso),

    # --- direct engines (no backend needed) ---------------------------------
    ("render_csp", "Render a character-select portrait from ANY costume DAT "
     "via the canonical engine (generate_csp + HSDRawViewer --csp: auto "
     "char/color detect, pose+camera, low-poly hiding, IC pairing, Fox gun). "
     "Renders on a temp copy (never litters the source dir). Returns the "
     "portrait inline. scale: 1=136x188, 2=2x, 4=HD.", _obj({
         "dat": {"type": "string"},
         "scale": {"type": "integer", "description": "1|2|4 (default 1)"},
         "color_index": {"type": "integer", "description":
                         "only needed for Game & Watch"},
         "paired_dat": {"type": "string", "description": "Nana partner DAT "
                        "for Ice Climbers"},
     }, ["dat"]), t_render_csp),

    ("dat_probe", "Ground-truth texture inventory of a DAT outside the "
     "viewer (shared.rendering.datprobe): roots, JOBJ-tree material textures, AND "
     "MatAnim swap frames (eye-blink textures the viewer's list misses). "
     "dump_dir writes decoded PNGs.", _obj({
         "dat": {"type": "string"},
         "dump_dir": {"type": "string"},
     }, ["dat"]), t_dat_probe),

    ("detect_content", "Classify a mod archive offline (the same "
     "detect_content_type behind /import/file, no writes): costume, stage, "
     "custom_character, xdelta, bundle, sound_bank, css_background, "
     "nested_archive, ... with confidence + details. Use before "
     "vault_import to know what you're holding.", _obj({
         "file": {"type": "string"},
         "deep": {"type": "boolean", "description": "default true"},
     }, ["file"]), t_detect_content),

    ("hsdraw", "Run HSDRawViewer headless (arg[0] MUST be a --mode flag; a "
     "bare path opens the GUI). Key modes: --csp <dat> <out.png> [--scale N]"
     " | --model export <dat> <jointSym> <out.smd|dae> | --model import "
     "<dat> <jointSym> <model> <out.dat> [--strip-matanim] | --texture "
     "export|import <dat> <root> <index> <png> | --dobj-info <dat> | "
     "--remove-dobjs | --inject-lowpoly | --accessory | --stage-render "
     "<Gr.dat> <out.png> [--eye x,y,z ...] | --stock-icons export | "
     "--convert-tex. Prefer render_csp for portraits (it adds pose/camera/"
     "hiding logic).", _obj({
         "args": {"type": "array", "items": {"type": "string"}},
     }, ["args"]), t_hsdraw),

    ("mexcli", "Run MexCLI directly (~50 verbs: create/open/info/"
     "list-fighters/get-costumes/import-costume(s)/remove-costume(s)/"
     "export/add-fighter/add-stage/get|set-css-layout/get|set-sss-layout/"
     "import-ssm/ssm-*/hps-to-wav/set-menu-playlist/...). ALL paths must be "
     "ABSOLUTE. stdin_json feeds set-* verbs. WARNING: only use on "
     "throwaway/test projects -- for the shared vault or a project the app "
     "may have open, go through backend_start + api (the backend holds "
     "mexcli_lock; two mexcli processes on one workspace corrupt it).",
     _obj({
         "args": {"type": "array", "items": {"type": "string"}},
         "stdin_json": {"description": "JSON piped to stdin for set-* verbs"},
     }, ["args"]), t_mexcli),

    ("wait_for_file", "Poll a file until it exists, exceeds min_bytes, and "
     "its size is stable -- the completion signal for async REST jobs like "
     "export/start (watch output/<name>.iso, min_bytes ~800MB).", _obj({
         "path": {"type": "string"},
         "min_bytes": {"type": "integer"},
         "stable_seconds": {"type": "number", "description": "default 3"},
         "timeout": {"type": "number", "description": "default 900"},
     }, ["path"]), t_wait_for_file),

    ("decomp", "Read-only reference into the local Melee decompilation "
     "(doldecomp/melee checkout, auto-located; override with MELEE_DECOMP "
     "env var) -- ground truth for engine behavior. ops: symbol {query} "
     "name search -> addresses | addr {addr} -> containing symbol + offset "
     "| grep {pattern, path?} regex over decomp src/ | source {symbol} -> "
     "the function's C source | info. The DOL is statically loaded, so "
     "symbol addresses ARE live MEM1 addresses: chain with read_ram/"
     "write_ram to inspect or poke engine state by NAME instead of magic "
     "numbers. Caveat: m-ex builds hook a few functions and add content "
     "the decomp doesn't know.", _obj({
         "op": {"type": "string", "description":
                "symbol|addr|grep|source|info (inferred from args if "
                "omitted)"},
         "query": {"type": "string", "description":
                   "op=symbol: regex or substring, case-insensitive"},
         "addr": {"type": "string", "description":
                  "op=addr: hex address, e.g. '0x80479D60'"},
         "pattern": {"type": "string", "description": "op=grep: regex"},
         "path": {"type": "string", "description":
                  "op=grep: only files whose repo-relative path contains "
                  "this, e.g. 'melee/mn'"},
         "symbol": {"type": "string", "description":
                    "op=source: exact function symbol name"},
         "limit": {"type": "integer", "description":
                   "max results (default 40, cap 200)"},
         "max_lines": {"type": "integer", "description":
                       "op=source: max lines returned (default 400)"},
     }), t_decomp),

    # --- wave 3 (gap audit) --------------------------------------------------
    ("iso_file", "Read files straight out of a GameCube ISO (pure-Python FST "
     "reader -- no wit/extraction step). ops: list {iso?, contains?} -> "
     "[{name,offset,size}] | extract {iso?, filename, dest?} -> pulls ONE "
     "file (e.g. GrIz.dat, PlFxGr.dat, TyEievui.dat) | ensure_ref {filename} "
     "-> cached vanilla reference DAT via the app's recorded vanilla ISO "
     "(storage/test-base/files/). iso defaults to that recorded vanilla ISO.",
     _obj({
         "op": {"type": "string", "description": "list|extract|ensure_ref "
                "(default list)"},
         "iso": {"type": "string"},
         "contains": {"type": "string", "description":
                      "op=list: case-insensitive name filter"},
         "filename": {"type": "string", "description":
                      "FST entry name, case-insensitive (bare filename)"},
         "dest": {"type": "string", "description":
                  "op=extract output path (default session out dir)"},
     }), t_iso_file),

    ("ram_search", "Search / diff live MEM1 (needs a boot_match session) -- "
     "the interactive alternative to hand-rolled probe scripts for byte->"
     "visual mapping. mode=find {hex | value+type(u8|u16|u32|s32|f32)} -> "
     "addresses (value search is width-aligned; unaligned=true to disable) | "
     "mode=snapshot {name?} -> stash a full-MEM1 baseline | mode=diff "
     "{name?} -> changed regions vs that baseline (do: snapshot -> step/act "
     "-> diff). start/end bound any mode to a GC address range. Chain hits "
     "through decomp op=addr to name them.", _obj({
         "mode": {"type": "string", "description": "find|snapshot|diff "
                  "(default find)"},
         "hex": {"type": "string", "description": "mode=find: byte pattern"},
         "value": {"type": ["number", "string"],
                   "description": "mode=find: numeric value"},
         "type": {"type": "string", "description": "value width (default u32)"},
         "unaligned": {"type": "boolean"},
         "name": {"type": "string", "description":
                  "snapshot slot (default 'base', max 4 held)"},
         "start": {"type": "string"}, "end": {"type": "string"},
         "limit": {"type": "integer", "description": "max results (default 200)"},
     }), t_ram_search),

    ("render_stock", "Derive the 24x24 stock icon for a MODDED costume DAT "
     "via the canonical engine (costume_assets.build_stock: texture-diff "
     "recolor -> head-shot crop -> csp-diff; G&W slot recolor). The "
     "companion to render_csp -- hsdraw --stock-icons only rips vanilla "
     "icons. Pass csp=<our own render_csp output> to enable the csp-diff "
     "fallback for model imports.", _obj({
         "dat": {"type": "string"},
         "character": {"type": "string", "description":
                       "vanilla assets character folder name, e.g. 'Fox'"},
         "costume_code": {"type": "string", "description":
                          "e.g. PlFxGr (default: DAT filename stem)"},
         "csp": {"type": "string", "description": "pixel-aligned OWN CSP "
                 "render (never a community image)"},
         "color_index": {"type": "integer", "description": "G&W slot 0-3"},
         "vanilla_fallback": {"type": "boolean", "description":
                              "default true; false = fail instead of "
                              "returning the vanilla icon"},
     }, ["dat", "character"]), t_render_stock),

    ("stage_workbench", "Freeform custom stage authoring. Start with op=guide. "
     "Promoted Colosseum/CS2 primitives, not a fixed design recipe: inspect "
     "DAT/scene_data groups and animations; mesh converts triangle JSON + PNG; "
     "graft builds a new DAT from a flexible spec (3D animated donors and/or "
     "custom meshes); cameras returns real-match framing estimates; package "
     "writes a verified ZIP. Paths must be absolute; relative spec assets "
     "resolve beside the spec. Outputs must be new revisions. No automatic "
     "vault install, ISO build or gameplay test. Native inspect/graft needs "
     ".NET SDK and configured HSDRaw. See tools/stages/README.md.", _obj({
         "op": {"type": "string", "enum": ["guide", "inspect", "mesh", "graft", "cameras", "package"]},
         "file": {"type": "string", "description": "DAT/USD/RDAT for inspect"},
         "spec": {"type": "string", "description": "JSON file for graft or mesh; guide documents formats"},
         "out": {"type": "string", "description": "New output DAT/ZIP/sweep JSON, or mesh filename prefix"},
         "stage": {"type": "string", "description": "Optional camera/budget preset: battlefield|final|fountain|dreamland|stadium|yoshis (long names also accepted)"},
         "camera": {"type": "object", "description": "Optional custom StageCameraInfo constants; see guide"},
         "views": {"type": "array", "items": {"type": "object"}, "description": "Optional camera views [{name,box:[xmin,ymin,xmax,ymax]}] in world units"},
         "files": {"type": "object", "additionalProperties": {"type": "string"}, "description": "package: ZIP filename -> absolute source path"},
     }), t_stage_workbench),

    ("stage_shot", "Headless STAGE screenshot (the DAS-capture engine): boot "
     "an ISO, load the stage ALONE (invisible fighter, no HUD/timer), pose a "
     "deterministic DEBUG_FREE camera, capture, clean up. Boots its own "
     "Dolphin (end_session first). Forms: single {stage|internal_id, hold?} "
     "| pause=true -> pause-overlay preview (GmPause mods) | variants=[{id,"
     "button,internal_id,framing_key}] -> one boot, many DAS variants.",
     _obj({
         "iso": _ISO, "stage": _STAGE,
         "internal_id": {"type": ["integer", "string"], "description":
                         "raw internal stage id for non-legal stages"},
         "hold": {"type": "string", "description":
                  "button held while loading (DAS variant select), e.g. 'A'"},
         "framing_key": {"type": "string", "description":
                         "camera preset key (default: the stage name)"},
         "stadium_form": {"type": "string", "description":
                          "Pokemon Stadium form: fire|grass|water|rock"},
         "framing_sweep": {"type": "array", "items": {"type": "object"}, "description":
                           "Optional 1..32 views [{eye:[x,y,z],interest:[x,y,z],fov,name?}], world units; chain stage_workbench cameras views. Returns per-view success/files; no pause/variants."},
         "pause": {"type": "boolean"},
         "variants": {"type": "array", "items": {"type": "object"}},
         "hires_textures": {"type": "boolean"},
         "max_width": {"type": "integer", "description":
                       "inline image width (default 640)"},
         "wait_for_dolphin": _WAIT_DOLPHIN,
     }), t_stage_shot),

    ("extras_doctor", "Read-only extras triage for a built project, NO boot: "
     "reads the project's DAT bytes per extra layer and reports VANILLA/"
     "MODDED + offset resolution (in-place / RELOCATED / UNRESOLVED-skipped)."
     " The first thing to run when an installed extra 'does nothing'.", _obj({
         "project": {"type": "string", "description": "project name or path"},
         "char": {"type": "string", "description":
                  "extra_types character key, e.g. 'Bowser'"},
         "extra": {"type": "string", "description": "one extra id (default all)"},
         "verbose": {"type": "boolean"},
     }, ["project", "char"]), t_extras_doctor),

    ("fsm_patch", "Standalone Crazy-Hand FSM engine ops on a main.dol (NTSC "
     "1.02 / m-ex layout; the same engine the export pipeline bakes in). "
     "ops: state {dol} -> vanilla|patched|unknown | apply {dol, fsm_txt|"
     "text, external_id?} -> parse Crazy Hand FSM lines + bake (idempotent, "
     "sidecar backup) | remove {dol} -> revert.", _obj({
         "op": {"type": "string", "description": "state|apply|remove"},
         "dol": {"type": "string"},
         "fsm_txt": {"type": "string", "description": "path to FSM .txt"},
         "text": {"type": "string", "description": "inline FSM lines"},
         "external_id": {"type": ["integer", "string"], "description":
                         "retarget entries to this external fighter id"},
     }, ["dol"]), t_fsm_patch),

    ("csp_regression", "Run the CSP-renderer golden-image regression suite "
     "(utility/tools/processor/csp_regression): renders every guarded case "
     "through the real generate_csp pipeline and compares to goldens. Run "
     "after ANY change to HSDRawViewer --csp / generate_csp / render pose "
     "logic. update_goldens=true regenerates goldens (only after a reviewed, "
     "intentional change).", _obj({
         "update_goldens": {"type": "boolean"},
         "exe": {"type": "string", "description":
                 "HSDRawViewer build dir override"},
         "pool": {"type": "integer", "description": "parallel workers"},
         "extra_args": {"type": "array", "items": {"type": "string"}},
     }), t_csp_regression),

    ("fps_batch", "Batch CSS health/perf verdict over one or more ISOs "
     "(backend/devtools/fps_batch.py): boots each, sits on the character-select "
     "screen, scores memory + FPS -> HEALTHY/DEGRADED/HUNG per ISO. The "
     "stress check for compression levels and heavy modpacks. mode: offline "
     "(VS CSS, default) | online (Slippi netplay CSS) | both.", _obj({
         "isos": {"type": "array", "items": {"type": "string"},
                  "description": "default: output/count-*.iso"},
         "mode": {"type": "string"},
         "wait_for_dolphin": _WAIT_DOLPHIN,
     }), t_fps_batch),

    ("netplay_desync", "Two-client Slippi NETPLAY desync test "
     "(backend/devtools/netrig.py): two real Slippi Dolphins on this computer, "
     "each logged into a DIFFERENT Slippi account, direct-connect over real "
     "Slippi, play a scripted match (default: Falcon dthrow spam), and the "
     "verdict is CLEAN or DESYNC from live monitoring plus a frame diff of the "
     "two clients' own replays (slpdiff). The check for 'does this mod desync "
     "online'. ops: check (what the rig needs and whether it is ready; "
     "DEFAULT, run it first) | play {iso, iso_b?, char_a, char_b, costume_a, "
     "costume_b, moves, throws, stage?, css_a?, css_b?, min_seconds?} (several "
     "minutes; both clients play iso unless iso_b is given) | status | kill. "
     "Needs: a copy of Slippi Launcher's netplay folder logged into a second "
     "account (NETRIG_ROOT/instance-a), the launcher logged into the first, "
     "and vgamepad + ViGEmBus for two virtual controllers. It connects to "
     "Slippi's servers with both accounts.", _obj({
         "op": {"type": "string", "enum": ["check", "play", "status", "kill"]},
         "iso": _ISO,
         "iso_b": {"type": "string", "description": "client B's ISO (default: iso)"},
         "char_a": {"type": "string", "description": "netrig character name (default falcon)"},
         "char_b": {"type": "string"},
         "costume_a": {"type": "integer", "minimum": 0},
         "costume_b": {"type": "integer", "minimum": 0},
         "moves": {"type": "string", "description": "comma list cycled per rep: dthrow,uthrow,upb,swap"},
         "throws": {"type": "integer", "minimum": 1, "maximum": 100},
         "stage": {"type": "string", "description": "requeue until the random stage is this one"},
         "css_a": {"type": "string", "description": "'x,y,iconIndex' CSS target for a modded layout (client A)"},
         "css_b": {"type": "string"},
         "min_seconds": {"type": "integer", "minimum": 0},
         "inject_desync": {"type": "boolean", "description": "positive control: force a one-sided edit to prove the detector fires"},
     }), t_netplay_desync),

    ("mex_codes", "SAFE m-ex Gecko codes maintenance (tools/dev/mex_codes.py): "
     "action=status (read-only compare of bundled codes.gct/codes.ini vs "
     "upstream akaneia/m-ex; DEFAULT) | backup | update {include_ini?} "
     "(always backs up first; codes.ini is a local fork -- do not overwrite "
     "blindly) | restore {backup_dir} | list. Network access on "
     "status/update.", _obj({
         "action": {"type": "string"},
         "include_ini": {"type": "boolean"},
         "backup_dir": {"type": "string"},
     }), t_mex_codes),
]

# Creation engines stay in developer tools; importing the MCP never starts a job.
sys.path.insert(0, str(REPO_ROOT / "tools"))
from creation.workflows import TOOLS as CREATION_TOOLS
TOOLS.extend(CREATION_TOOLS)

TOOL_DEFS = [{"name": n, "description": d, "inputSchema": s}
             for n, d, s, _ in TOOLS]
HANDLERS = {n: h for n, d, s, h in TOOLS}


# ---------------------------------------------------------------------------
# Request loop
# ---------------------------------------------------------------------------
def handle_call(req_id, params):
    name = params.get("name")
    args = params.get("arguments") or {}
    fn = HANDLERS.get(name)
    if fn is None:
        _reply_err(req_id, -32602, f"unknown tool: {name}")
        return
    token = (params.get("_meta") or {}).get("progressToken")
    log = Progress(token)
    try:
        result = fn(args, log)
    except (ValueError, MoveError, RuntimeError, SystemExit) as e:
        # SystemExit: frameshot's parse helpers exit on bad args -- that must
        # become a tool error, not kill the server. RuntimeError: expected
        # environment/backend failures read better as one line than a trace
        _reply(req_id, {"content": [{"type": "text", "text": f"ERROR: {e}"}],
                        "isError": True})
        return
    except Exception:
        _reply(req_id, {"content": [{"type": "text",
                                     "text": "ERROR:\n" + traceback.format_exc()}],
                        "isError": True})
        return
    content = []
    if isinstance(result, dict) and "_image" in result:
        img = result.pop("_image")
        mime = result.pop("_image_mime", "image/png")
        content.append({"type": "image", "data": img, "mimeType": mime})
    content.insert(0, {"type": "text",
                       "text": json.dumps(result, indent=2, default=str)})
    _reply(req_id, {"content": content, "isError": False})


def main():
    global _RPC
    os.chdir(BACKEND)
    _RPC = os.fdopen(os.dup(1), "wb", buffering=0)
    sys.stdout = sys.stderr            # library imports never redirect the app
    print(f"[harness_mcp] ready ({len(TOOLS)} tools), backend={BACKEND}",
          file=sys.stderr, flush=True)
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            break                      # client gone -> cleanup via atexit
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        req_id, method = msg.get("id"), msg.get("method")
        params = msg.get("params") or {}
        if method == "initialize":
            _reply(req_id, {
                "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "melee-harness", "version": "1.0.0"},
            })
        elif method == "tools/list":
            _reply(req_id, {"tools": TOOL_DEFS})
        elif method == "tools/call":
            handle_call(req_id, params)
        elif method == "ping":
            _reply(req_id, {})
        elif req_id is not None:       # unknown *request* needs an error
            _reply_err(req_id, -32601, f"method not found: {method}")
        # notifications (initialized, cancelled, ...) are ignored


if __name__ == "__main__":
    main()
