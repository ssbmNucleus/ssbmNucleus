"""Play a REAL .slp back in Slippi's playback Dolphin and dump the stage's live
collision every frame: ground truth for what a stage really did in a real
match (two fighters, items, effects all drawing from the same HSD_Rand
stream). stage_dump.py can only show a solo match; this shows the replay.

    app\\venv\\Scripts\\python.exe tools/liteaudit/replay_dump.py <game.slp> [...] [--frames N]

Same tables and calibration as stage_dump.py (slippi_frame = match_frame:
the row is AFTER that replay frame), plus the RAM seed at each frame boundary.
The seed pairs with replay pre-frame n+1; countdown rows are indexed backwards
from the first match_frame 1, with the last zero row at Slippi 0 (C16).
One Dolphin at a time: the harness
lock is held for the whole run. Output: app/scratch/liteaudit/replaydump/
<replay-stem>.npz + .json.
"""
import argparse
import json
import struct
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "app" / "backend"))
import numpy as np                                                   # noqa: E402
from shared.ingame import dolphin_lock, framestep                    # noqa: E402
from shared.ingame.melee_mem import Dolphin                          # noqa: E402
from tracker.replays.dolphin_config import playback_dolphin_path     # noqa: E402

OUT = REPO / "app" / "scratch" / "liteaudit" / "replaydump"
COLL_DATA, COLL_VTX, COLL_LINE, COLL_JOINT = 0x804D64B4, 0x804D64B8, 0x804D64BC, 0x804D64C0
MATCH_FRAME = 0x8046B6A0 + 0x24
RAND_SEED = 0x804D5F90


def _iso():
    from core.config import PROJECT_ROOT
    for p in sorted(Path(PROJECT_ROOT).glob("*.iso")):
        return str(p)
    raise SystemExit("no vanilla ISO in the app root")


def _u32s(raw, stride, off):
    return [struct.unpack_from(">I", raw, i * stride + off)[0] for i in range(len(raw) // stride)]


def _locate_live(d, timeout=90.0):
    """The playback build maps more than one MEM1-sized region that starts
    with the game id (it keeps snapshots for seeking), and Dolphin.locate()
    takes the first, which can be a frozen copy. Find every candidate and keep
    the one whose RNG seed / match frame actually move."""
    import ctypes
    from shared.ingame import melee_mem as mm
    deadline = time.time() + timeout
    while time.time() < deadline:
        cands, addr, mbi = [], 0, mm.MEMORY_BASIC_INFORMATION()
        while addr < 0x7FFFFFFFFFFF and mm._k32.VirtualQueryEx(
                d.h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            # Any committed region at least MEM1-sized: the playback build can
            # hold MEM1 in private memory, and its MAPPED game-id views may be
            # the disc image (which also starts with "GALE01").
            if (mbi.State == 0x1000 and mbi.RegionSize >= mm.MEM1_REGION_SIZE
                    and d._raw(mbi.BaseAddress, len(mm.GAME_ID)) == mm.GAME_ID):
                cands.append(mbi.BaseAddress)
            nxt = mbi.BaseAddress + mbi.RegionSize
            if nxt <= addr:
                break
            addr = nxt
        def probe(base):
            d.base = base
            return (d.u32(RAND_SEED), d.u32(MATCH_FRAME), d.u32(0x80479D60))
        before = {b: probe(b) for b in cands}
        time.sleep(0.5)
        for b in cands:
            if probe(b) != before[b]:
                d.base = b
                return b
        time.sleep(0.5)
    d.base = None
    return None


def dump_replay(slp, frames, log):
    slp = Path(slp).resolve()
    comm = Path(tempfile.mkstemp(suffix=".json", prefix="liteaudit_comm_")[1])
    comm.write_text(json.dumps({"mode": "normal", "replay": str(slp), "isRealTimeMode": False,
                                "commandId": uuid.uuid4().hex}))
    proc = subprocess.Popen([playback_dolphin_path(), "-i", str(comm), "-b", "-e", _iso()],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log(f"playback pid {proc.pid} for {slp.name}")
    try:
        d = Dolphin(proc.pid)
        if _locate_live(d) is None:
            raise RuntimeError("playback Dolphin never exposed a live MEM1")
        log(f"live MEM1 at {hex(d.base)}")
        # Freeze as soon as the match logic runs (match frame counter moving
        # and the collision tables allocated), to keep the countdown frames.
        t0 = time.time()
        while True:
            mf, cd = d.u32(MATCH_FRAME), d.u32(COLL_DATA)
            if mf and cd and 0x80000000 <= cd < 0x81800000 and d.u32(cd + 4):
                break
            if proc.poll() is not None or time.time() - t0 > 120:
                raise RuntimeError("replay never reached the match")
            time.sleep(0.002)
        framestep.freeze(d)
        cd = d.u32(COLL_DATA)
        n_vtx, lines_p, n_line = d.u32(cd + 4), d.u32(cd + 8), d.u32(cd + 0xC)
        joints_p, n_joint = d.u32(cd + 0x24), d.u32(cd + 0x28)
        lraw = d.bytes(lines_p, n_line * 0x10)
        lines = np.array([struct.unpack_from(">HHhhhhHH", lraw, i * 0x10) for i in range(n_line)],
                         dtype=np.int32)
        jraw = d.bytes(joints_p, n_joint * 0x28)
        joints = np.array([struct.unpack_from(">10h4f2h", jraw, i * 0x28) for i in range(n_joint)],
                          dtype=np.float64)
        mf = np.zeros(frames, dtype=np.int64)
        seeds = np.zeros(frames, dtype=np.uint32)
        verts = np.zeros((frames, n_vtx, 2), dtype=np.float32)
        lflags = np.zeros((frames, n_line), dtype=np.uint32)
        jflags = np.zeros((frames, n_joint), dtype=np.uint32)
        n = 0
        for f in range(frames):
            cur = d.u32(MATCH_FRAME)
            if cur is None or (f and cur <= mf[f - 1]):
                break                                   # match over / scene left
            mf[f], seeds[f] = cur, d.u32(RAND_SEED) or 0
            v = np.frombuffer(d.bytes(d.u32(COLL_VTX), n_vtx * 0x18), dtype=">f4").reshape(n_vtx, 6)
            verts[f] = v[:, 2:4]
            lflags[f] = _u32s(d.bytes(d.u32(COLL_LINE), n_line * 8), 8, 4)
            jflags[f] = _u32s(d.bytes(d.u32(COLL_JOINT), n_joint * 0x34), 0x34, 8)
            n = f + 1
            if framestep.step(d, 1) != 1:
                break
    finally:
        if proc.poll() is None:
            proc.kill()                                 # the exact PID we started
        try:
            comm.unlink()
        except OSError:
            pass
    OUT.mkdir(parents=True, exist_ok=True)
    stem = slp.stem
    np.savez_compressed(OUT / f"{stem}.npz", match_frame=mf[:n], seed=seeds[:n], verts=verts[:n],
                        line_flags=lflags[:n], joint_flags=jflags[:n], lines=lines, joints=joints)
    summary = {"replay": str(slp), "frames": n,
               "match_frame": [int(mf[0]), int(mf[n - 1])] if n else None,
               "verts": n_vtx, "lines": n_line, "joints": n_joint}
    (OUT / f"{stem}.json").write_text(json.dumps(summary, indent=1))
    log(json.dumps(summary))
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("replays", nargs="+")
    ap.add_argument("--frames", type=int, default=30000)
    ap.add_argument("--wait", type=float, default=7200, help="seconds to queue for the Dolphin lock")
    a = ap.parse_args()

    def log(m):
        print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

    dolphin_lock.acquire("liteaudit replay_dump", wait=a.wait)
    try:
        for r in a.replays:
            try:
                dump_replay(r, a.frames, log)
            except Exception as e:                   # one bad replay must not stop the batch
                log(f"{r} FAILED: {e!r}")
    finally:
        dolphin_lock.release()


if __name__ == "__main__":
    main()
