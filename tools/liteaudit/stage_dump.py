"""Dump a stage's LIVE collision geometry from Melee, frame by frame.

Ground truth for Watch Lite's stage drawing (meleeStages.js / meleeMovers.json):
boot a solo match on any vanilla stage through the melee-harness session code,
freeze it, and on every logic frame read the engine's own collision tables
(decomp mp/mplib.c + mp/types.h):

    0x804D64B4  MapCollData*  verts/lines/joints counts, static line table
    0x804D64B8  CollVtx*      per-vertex state, current world pos at +0x08
    0x804D64BC  CollLine*     per-line runtime flags at +0x04
    0x804D64C0  CollJoint*    per-joint runtime flags at +0x08 (hidden/off)
    0x8046B6C4  u32           VsSceneController.state.frame_count
    0x804D5F90  u32           HSD_Rand seed (sysdolphin random.c), read at the
                              frame boundary, to pair with the replay's per-frame
                              recorded seed when porting "random" stage logic

Each dumped match is also saved by Slippi as a replay; its path is recorded in
the summary (`replay`) so the live collision and the .slp can be compared.
Rows with match_frame n hold state AFTER Slippi frame n: slippi_frame =
match_frame, not match_frame - 1. RAM boundary seeds match the replay's pre
seed at n+1 (FoD seedA and Yoshi's Story ride, C16). During countdown the
counter stays zero; recover frames by row index so the last zero row is
Slippi 0 and the first counter value 1 is Slippi 1. All five early captures
confirm every countdown row against the paired replay's raw pre-frame seeds.

Positions are world coordinates after the stage's joint animation, so moving
platforms, scrolling stages and transformations come out exactly as the game
collides with them. One Dolphin at a time (the harness lock is honoured).

    app\\venv\\Scripts\\python.exe tools/liteaudit/stage_dump.py --stage 8 --frames 1300
    app\\venv\\Scripts\\python.exe tools/liteaudit/stage_dump.py --stage all --frames 3600

Output: app/scratch/liteaudit/stagedump/stage-<id>[-<tag>].npz (+ .json summary).
"""
import argparse
import json
import struct
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "harness"))
import harness_mcp as hm                                       # noqa: E402
import numpy as np                                             # noqa: E402

OUT = REPO / "app" / "scratch" / "liteaudit" / "stagedump"

COLL_DATA, COLL_VTX, COLL_LINE, COLL_JOINT = 0x804D64B4, 0x804D64B8, 0x804D64BC, 0x804D64C0
MATCH_FRAME = 0x8046B6A0 + 0x24
RAND_SEED = 0x804D5F90
REPLAY_ROOT = Path.home() / "OneDrive" / "Documents" / "Slippi"

# Vanilla VS stages by internal id (== the .slp GameStart stage id). 21 is the
# unused Akaneia slot; 26 (Icetop) is adventure-only and may refuse to load.
VANILLA = {2: "Fountain of Dreams", 3: "Pokemon Stadium", 4: "Peach's Castle",
           5: "Kongo Jungle", 6: "Brinstar", 7: "Corneria", 8: "Yoshi's Story",
           9: "Onett", 10: "Mute City", 11: "Rainbow Cruise", 12: "Jungle Japes",
           13: "Great Bay", 14: "Hyrule Temple", 15: "Brinstar Depths",
           16: "Yoshi's Island", 17: "Green Greens", 18: "Fourside",
           19: "Mushroom Kingdom I", 20: "Mushroom Kingdom II", 22: "Venom",
           23: "Poke Floats", 24: "Big Blue", 25: "Icicle Mountain", 26: "Icetop",
           27: "Flat Zone", 28: "Dream Land N64", 29: "Yoshi's Island N64",
           30: "Kongo Jungle N64", 31: "Battlefield", 32: "Final Destination"}


def _u32s(raw, stride, off):
    return [struct.unpack_from(">I", raw, i * stride + off)[0]
            for i in range(len(raw) // stride)]


SPECIALS = [
    (["SET MAIN 0.500 0.500", "PRESS B", "FLUSH"], 30, 60),                     # neutral-B (lasers, turnips...)
    (["SET MAIN 0.000 0.500", "PRESS B", "FLUSH"], 30, 60),                     # side-B left
    (["SET MAIN 1.000 0.500", "PRESS B", "FLUSH"], 30, 60),                     # side-B right
    (["SET MAIN 0.500 0.000", "PRESS B", "FLUSH"], 30, 60),                     # down-B
]


def _wander_plan(frames, stage_id, specials=False):
    """Scripted inputs that make a solo fighter USE the stage: walk both ways,
    jump onto and drop through platforms, attack (blocks, switches), stand on
    things long enough to tip them. Player-triggered stage mechanics (tilting
    platforms, flip blocks, collapsing clouds, Peach's switch) never fire for a
    fighter standing still at spawn. Fixed per stage so runs are repeatable."""
    import random
    rng = random.Random(0x57A6E + stage_id)
    plan = [None] * frames
    f = 0
    moves = [
        (["RELEASE A", "RELEASE X", "SET MAIN 0.000 0.500", "FLUSH"], 40, 110),   # walk/run left
        (["RELEASE A", "RELEASE X", "SET MAIN 1.000 0.500", "FLUSH"], 40, 110),   # walk/run right
        (["SET MAIN 0.500 0.500", "PRESS X", "FLUSH"], 6, 6),                     # jump
        (["RELEASE X", "SET MAIN 0.500 0.000", "FLUSH"], 8, 20),                  # crouch / drop through
        (["SET MAIN 0.500 0.500", "PRESS A", "FLUSH"], 4, 4),                     # jab (blocks, switches)
        (["RELEASE A", "SET MAIN 0.500 1.000", "PRESS A", "FLUSH"], 4, 4),        # up-tilt / up-air
        (["RELEASE A", "RELEASE X", "SET MAIN 0.500 0.500", "FLUSH"], 60, 240),   # stand still
    ]
    if specials:
        moves += SPECIALS
    while f < frames:
        cmd, lo, hi = moves[rng.randrange(len(moves))]
        plan[f] = cmd
        f += rng.randint(lo, hi)
        if f < frames:
            plan[f] = ["RELEASE A", "RELEASE B", "RELEASE X", "SET MAIN 0.500 0.500", "FLUSH"]
            f += 2
    return plan


NEUTRAL = ["RELEASE A", "RELEASE B", "RELEASE X", "RELEASE L", "RELEASE R", "RELEASE Z", "SET MAIN 0.500 0.500", "SET C 0.500 0.500", "FLUSH"]
# Script actions: list of (frame offset, pipe lines | "PLACE") inside one step.
_ACTIONS = {
    "wait": [],
    "left": [(0, ["SET MAIN 0.000 0.500", "FLUSH"])],
    "right": [(0, ["SET MAIN 1.000 0.500", "FLUSH"])],
    "jump": [(0, ["PRESS X", "FLUSH"]), (2, ["RELEASE X", "FLUSH"])],
    "jab": [(0, ["PRESS A", "FLUSH"]), (3, ["RELEASE A", "FLUSH"])],
    "nb": [(0, ["PRESS B", "FLUSH"]), (3, ["RELEASE B", "FLUSH"])],
    "sb_l": [(0, ["SET MAIN 0.000 0.500", "PRESS B", "FLUSH"]), (3, ["RELEASE B", "SET MAIN 0.500 0.500", "FLUSH"])],
    "sb_r": [(0, ["SET MAIN 1.000 0.500", "PRESS B", "FLUSH"]), (3, ["RELEASE B", "SET MAIN 0.500 0.500", "FLUSH"])],
    "db": [(0, ["SET MAIN 0.500 0.000", "PRESS B", "FLUSH"]), (3, ["RELEASE B", "SET MAIN 0.500 0.500", "FLUSH"])],
    "fsmash_l": [(0, ["SET C 0.000 0.500", "FLUSH"]), (3, ["SET C 0.500 0.500", "FLUSH"])],
    "fsmash_r": [(0, ["SET C 1.000 0.500", "FLUSH"]), (3, ["SET C 0.500 0.500", "FLUSH"])],
    "dsmash": [(0, ["SET C 0.500 0.000", "FLUSH"]), (3, ["SET C 0.500 0.500", "FLUSH"])],
    "usmash": [(0, ["SET C 0.500 1.000", "FLUSH"]), (3, ["SET C 0.500 0.500", "FLUSH"])],
    # Jump, then C-stick toward the target: forward or back air, both hit that side.
    "aerial_l": [(0, ["PRESS X", "FLUSH"]), (2, ["RELEASE X", "FLUSH"]),
                 (7, ["SET C 0.000 0.500", "FLUSH"]), (10, ["SET C 0.500 0.500", "FLUSH"])],
    "aerial_r": [(0, ["PRESS X", "FLUSH"]), (2, ["RELEASE X", "FLUSH"]),
                 (7, ["SET C 1.000 0.500", "FLUSH"]), (10, ["SET C 0.500 0.500", "FLUSH"])],
    # Tether/grab-air. Fighter_procInput skips the Z -> L+A conversion while the
    # debug pause flag is set, and this dumper TAS-steps under it: press L+A.
    "zair": [(0, ["PRESS X", "FLUSH"]), (2, ["RELEASE X", "FLUSH"]),
             (9, ["PRESS L", "PRESS A", "FLUSH"]), (12, ["RELEASE L", "RELEASE A", "FLUSH"])],
    # Smash input, then hold A for ~60 frames of charge.
    "charged_fsmash_l": [(0, ["SET MAIN 0.000 0.500", "PRESS A", "FLUSH"]),
                         (1, ["SET MAIN 0.500 0.500", "FLUSH"]), (63, ["RELEASE A", "FLUSH"])],
    "charged_fsmash_r": [(0, ["SET MAIN 1.000 0.500", "PRESS A", "FLUSH"]),
                         (1, ["SET MAIN 0.500 0.500", "FLUSH"]), (63, ["RELEASE A", "FLUSH"])],
    "up_b": [(0, ["SET MAIN 0.500 1.000", "PRESS B", "FLUSH"]),
             (3, ["RELEASE B", "SET MAIN 0.500 0.500", "FLUSH"])],
    # Sheik chain: side-B held, swung up then down, released.
    "chain_hold": [(0, ["SET MAIN 1.000 0.500", "PRESS B", "FLUSH"]), (4, ["SET MAIN 0.500 0.500", "FLUSH"]),
                   (55, ["SET MAIN 0.500 1.000", "FLUSH"]), (75, ["SET MAIN 0.500 0.000", "FLUSH"]),
                   (95, ["RELEASE B", "SET MAIN 0.500 0.500", "FLUSH"])],
    "place": [(0, "PLACE")],     # re-teleport to --place (precede with jump: airborne)
}


def _script_plan(frames, script):
    """--script "jump@3,place@40,aerial_r@35x30,wait@3000": comma-separated
    action[@frames][xRepeat]; a step lasts @frames (default 30) and starts from
    neutral inputs. Runs once; the remaining frames are neutral."""
    plan = [None] * frames
    f = 0
    for step in script.split(","):
        step = step.strip()
        rep = 1
        if "x" in step.split("@")[-1]:
            step, r = step.rsplit("x", 1)
            rep = int(r)
        name, _, dur = step.partition("@")
        if name not in _ACTIONS:
            raise ValueError(f"unknown script action {name!r}; known: {sorted(_ACTIONS)}")
        dur = int(dur or 30)
        for _ in range(rep):
            if f < frames:
                plan[f] = NEUTRAL
            for off, cmd in _ACTIONS[name]:
                if f + 1 + off < frames:
                    plan[f + 1 + off] = cmd
            f += 1 + dur
    if f < frames:
        plan[f] = NEUTRAL
    return plan


def _parse_watch(spec):
    """--watch "cam=0x80452C68:0x39C,gv=0x804D7848>0x2C>0:0x200": name=ADDR[>OFF...]:LEN.
    Each '>OFF' dereferences the current address as a pointer, then adds OFF.
    LEN bytes are recorded every frame into the npz as watch_<name> (uint8)."""
    out = []
    for item in filter(None, (s.strip() for s in spec.split(","))):
        name, _, rest = item.partition("=")
        expr, _, length = rest.rpartition(":")
        parts = expr.split(">")
        out.append((name, int(parts[0], 0), [int(o, 0) for o in parts[1:]], int(length, 0)))
    return out


def _watch_addr(d, base, derefs):
    addr = base
    for off in derefs:
        ptr = d.u32(addr)
        if not ptr or not (0x80000000 <= ptr < 0x81800000):
            return None
        addr = ptr + off
    return addr


def _write_pos(d, ft, xy):
    # Player.set_pos writes only cur_pos; the collision step sweeps from
    # prev_pos and CollData's copies (decomp lb/types.h CollData at fp+0x6F0)
    # and snaps a long teleport back. Write them all.
    for off in (0xB0, 0xBC, 0x6F4, 0x700, 0x70C):
        d.write_f32(ft + off, float(xy[0]))
        d.write_f32(ft + off + 4, float(xy[1]))


def dump(stage_id, frames, char, tag, log, seed=None, wander=False, place=None,
         air_place=False, script=None, specials=False, watch=None):
    name = f"id{stage_id}"
    hm.INTERNAL_STAGE_ID[name] = stage_id      # the session validates by name
    s = hm.Session()
    t0 = time.time()
    s.start({"stage": name, "char": char, "wait_for_dolphin": 600}, log)
    d = s.d
    try:
        if place is not None:
            # Put the fighter on a known surface (e.g. Yoshi's Story's cloud)
            # so the replay's fighter positions pin down which slippi frame a
            # dump row shows: a rider is carried exactly by its platform.
            # Wait out the entry animation first: a position written during
            # it is overwritten when the fighter lands in Wait (state 14).
            for _ in range(400):
                if s.runner.player.state() == 14:
                    break
                hm.framestep.step(d, 1)
            if air_place:
                # A grounded fighter keeps its old ground line and snaps back
                # to it; teleport from a jump so it lands on the target instead.
                s.pipe.frame(["PRESS X", "FLUSH"])
                hm.framestep.step(d, 2)
                s.pipe.frame(["RELEASE X", "FLUSH"])
                for _ in range(20):
                    hm.framestep.step(d, 1)
                    if s.runner.player.state() not in (14, 24):    # Wait, KneeBend
                        break
            ft = s.runner.player._ft()
            _write_pos(d, ft, place)
            hm.framestep.step(d, 2)
            log(f"placed at {place}; now state {s.runner.player.state()} pos {s.runner.player.pos()}")
        if seed is not None:
            # A different RNG seed per run is what proves a stage model is
            # driven by the seed and not by this one recording.
            d.write_u32(RAND_SEED, seed & 0xFFFFFFFF)
        cd = d.u32(COLL_DATA)
        n_vtx, lines_p, n_line = d.u32(cd + 4), d.u32(cd + 8), d.u32(cd + 0xC)
        joints_p, n_joint = d.u32(cd + 0x24), d.u32(cd + 0x28)
        # static tables: MapLine {v0 u16, v1 u16, prev0, next0, prev1, next1, hi u16, lo u16}
        lraw = d.bytes(lines_p, n_line * 0x10)
        lines = np.array([struct.unpack_from(">HHhhhhHH", lraw, i * 0x10)
                          for i in range(n_line)], dtype=np.int32)
        # MapJoint {5 x (start s16, count s16), bounds 4f, vtx_start s16, vtx_count s16}
        jraw = d.bytes(joints_p, n_joint * 0x28)
        joints = np.array([struct.unpack_from(">10h4f2h", jraw, i * 0x28)
                           for i in range(n_joint)], dtype=np.float64)
        boot_s = time.time() - t0
        mf = np.zeros(frames, dtype=np.int64)
        seeds = np.zeros(frames, dtype=np.uint32)
        verts = np.zeros((frames, n_vtx, 2), dtype=np.float32)
        lflags = np.zeros((frames, n_line), dtype=np.uint32)
        jflags = np.zeros((frames, n_joint), dtype=np.uint32)
        watches = _parse_watch(watch) if watch else []
        wdata = {name: np.zeros((frames, ln), dtype=np.uint8) for name, _, _, ln in watches}
        t1 = time.time()
        plan = (_script_plan(frames, script) if script else
                _wander_plan(frames, stage_id, specials) if wander else None)
        for f in range(frames):
            if plan is not None and plan[f] == "PLACE":
                if place is None:
                    raise ValueError("script action 'place' needs --place")
                _write_pos(d, s.runner.player._ft(), place)
            elif plan is not None and plan[f] is not None:
                s.pipe.frame(plan[f])
            mf[f] = d.u32(MATCH_FRAME) or 0
            seeds[f] = d.u32(RAND_SEED) or 0
            vraw = d.bytes(d.u32(COLL_VTX), n_vtx * 0x18)
            v = np.frombuffer(vraw, dtype=">f4").reshape(n_vtx, 6)
            verts[f] = v[:, 2:4]
            lflags[f] = _u32s(d.bytes(d.u32(COLL_LINE), n_line * 8), 8, 4)
            jflags[f] = _u32s(d.bytes(d.u32(COLL_JOINT), n_joint * 0x34), 0x34, 8)
            for name, base, derefs, ln in watches:
                addr = _watch_addr(d, base, derefs)
                if addr is not None:
                    wdata[name][f] = np.frombuffer(d.bytes(addr, ln), dtype=np.uint8)
            if hm.framestep.step(d, 1) != 1:
                log(f"step failed at {f}; keeping {f} frames")
                mf, verts, lflags, jflags = mf[:f], verts[:f], lflags[:f], jflags[:f]
                seeds = seeds[:f]
                wdata = {k: v[:f] for k, v in wdata.items()}
                break
        dump_s = time.time() - t1
    finally:
        s.stop()
    # Slippi finishes writing the replay when the match ends (Dolphin closes):
    # the newest .slp modified after boot is this match's.
    replay = None
    newest = sorted((p for p in REPLAY_ROOT.glob("*/*.slp") if p.stat().st_mtime >= t0),
                    key=lambda p: p.stat().st_mtime)
    if newest:
        replay = str(newest[-1])
    OUT.mkdir(parents=True, exist_ok=True)
    stem = f"stage-{stage_id}" + (f"-{tag}" if tag else "")
    np.savez_compressed(OUT / f"{stem}.npz", match_frame=mf, seed=seeds, verts=verts,
                        line_flags=lflags, joint_flags=jflags, lines=lines,
                        joints=joints, **{f"watch_{k}": v for k, v in wdata.items()})
    moving = int((np.abs(verts - verts[:1]).max(axis=(0, 2)) > 0.01).sum()) if len(verts) else 0
    summary = {"stage": stage_id, "name": VANILLA.get(stage_id), "frames": int(len(mf)),
               "match_frame": [int(mf[0]), int(mf[-1])] if len(mf) else None,
               "verts": n_vtx, "lines": n_line, "joints": n_joint,
               "moving_verts": moving,
               "line_flag_changes": int((lflags != lflags[:1]).any(axis=1).sum()) if len(mf) else 0,
               "joint_flag_changes": int((jflags != jflags[:1]).any(axis=1).sum()) if len(mf) else 0,
               "boot_s": round(boot_s, 1), "dump_s": round(dump_s, 1),
               "replay": replay}
    (OUT / f"{stem}.json").write_text(json.dumps(summary, indent=1))
    log(json.dumps(summary))
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="8", help="internal stage id, comma list, or 'all'")
    ap.add_argument("--frames", type=int, default=1300)
    ap.add_argument("--char", default="marth")
    ap.add_argument("--tag", default="")
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--place", default=None,
                    help="'x,y' to put the fighter at once the match is frozen")
    ap.add_argument("--early", action="store_true",
                    help="freeze as soon as the match scene runs (capture from ~slippi -123, not ~75)")
    ap.add_argument("--wander", action="store_true",
                    help="drive scripted inputs so player-triggered mechanics fire")
    ap.add_argument("--watch", default=None,
                    help="extra RAM per frame: name=ADDR[>OFF...]:LEN,... (see _parse_watch)")
    ap.add_argument("--specials", action="store_true",
                    help="with --wander: also use B moves (projectiles, items)")
    ap.add_argument("--air-place", action="store_true",
                    help="with --place: jump first so the fighter lands on the target")
    ap.add_argument("--script", default=None,
                    help="scripted inputs, e.g. 'fsmash_l@60x4,wait@2400'; see _script_plan")
    ap.add_argument("--seed", type=lambda v: int(v, 0), default=None,
                    help="overwrite the RNG seed once the match is frozen")
    a = ap.parse_args()
    ids = sorted(VANILLA) if a.stage == "all" else [int(x) for x in a.stage.split(",")]
    if a.early:
        # The harness waits 200 game frames (past READY/GO) before freezing;
        # scripted stages need the countdown frames too.
        _orig_wait = hm.wait_game_frames
        hm.wait_game_frames = lambda d, n, *k, **kw: _orig_wait(d, 1, *k, **kw)

    def log(m):
        print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

    for sid in ids:
        stem = f"stage-{sid}" + (f"-{a.tag}" if a.tag else "")
        if a.skip_existing and (OUT / f"{stem}.npz").exists():
            continue
        try:
            dump(sid, a.frames, a.char, a.tag, log, seed=a.seed, wander=a.wander,
                 air_place=a.air_place, script=a.script, specials=a.specials, watch=a.watch,
                 place=tuple(float(v) for v in a.place.split(",")) if a.place else None)
        except Exception as e:               # one bad stage must not stop the sweep
            log(f"stage {sid} FAILED: {e!r}")


if __name__ == "__main__":
    main()
