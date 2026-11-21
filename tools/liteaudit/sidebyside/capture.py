"""Capture the REAL game picture for each target frame: play the .slp in Slippi's
playback Dolphin, freeze on exactly that frame and grab the render window.

    app/venv/Scripts/python.exe -B tools/liteaudit/sidebyside/capture.py --targets <run>/targets-ext.json --out <run>/shots [--only id,id] [--wait S] [--iso PATH]

Per target (targets-ext.json, from prep.mjs) it writes <out>/<id>.png and
<out>/<id>.json with:
  - the frame check: the match frame Dolphin is frozen on, and which replay frame
    the live fighters (x, y, action state, action frame) match best; both must be
    the target frame;
  - the game camera (CObj view matrix, perspective fov/aspect, viewport), so the
    compositor can project world points into the shot and frame Watch Lite the same;
  - live items and stage collision at that frame;
  - for Fox/Falco: the HipN joint's world position and every live effect the
    fighter owns (root JObj world position, child scale, animation frame), and for
    shine targets the same frame by frame around the shot (seq.mjs prints it).
  - for Link, Marth, Young Link and Roy, and any fighter holding a Beam Sword: the sword
    trail as the game holds it (sample count, the ring of 3 joint positions and axes, the
    blade), the sword joint now, and the Beam Sword's own bones and blade length.
Built on tools/liteaudit/replay_dump.py (same launch, live-MEM1 location).
One Dolphin at a time: the harness lock is held for the whole run.
"""
import argparse
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / 'app' / 'backend'))
sys.path.insert(0, str(REPO / 'tools' / 'liteaudit'))
from shared.ingame import dolphin_lock, framestep                    # noqa: E402
from shared.ingame import screenshot as shot                         # noqa: E402
from shared.ingame.melee_mem import Dolphin                          # noqa: E402
from tracker.replays.dolphin_config import playback_dolphin_path     # noqa: E402
from replay_dump import _locate_live, MATCH_FRAME                    # noqa: E402
from shared.vanilla_extract.vanilla_refs import known_vanilla_iso    # noqa: E402

STATIC_PLAYER, STRIDE = 0x80453080, 0xE90
CAMERA = 0x80452C68
GOBJ_ENTITIES = 0x804D782C
EFFECT_PLINKS = (11, 12)
ITEM_PLINK = 9
COLL_DATA, COLL_VTX, COLL_LINE = 0x804D64B4, 0x804D64B8, 0x804D64BC


def vanilla_iso(override=None):
    iso = Path(override) if override else known_vanilla_iso()
    if not iso or not iso.is_file():
        raise SystemExit('no vanilla ISO: record one in the app (Settings) or pass --iso')
    return str(iso)


def fighter_ptr(d, port):
    slot = STATIC_PLAYER + STRIDE * port
    gobj = d.u32(slot + 0xB0)
    if not gobj or not 0x80000000 <= gobj < 0x81800000:
        return None, None
    ft = d.u32(gobj + 0x2C)
    return (gobj, ft) if ft and 0x80000000 <= ft < 0x81800000 else (None, None)


def floats(d, addr, n):
    raw = d.bytes(addr, 4 * n)
    return list(struct.unpack('>' + 'f' * n, raw)) if raw and len(raw) == 4 * n else None


def jobj_world(d, j):
    m = floats(d, j + 0x44, 12)
    return [m[3], m[7], m[11]] if m else None


def read_camera(d):
    gobj = d.u32(CAMERA)
    cobj = d.u32(gobj + 0x28) if gobj else None
    if not cobj:
        return None
    return {
        'viewport': floats(d, cobj + 0x0C, 4),
        'near_far': floats(d, cobj + 0x38, 2),
        'fov_aspect': floats(d, cobj + 0x40, 2),
        'projection_type': d.u8(cobj + 0x50),
        'view_mtx': floats(d, cobj + 0x54, 12),
        'eye': floats(d, 0x80452C94, 3), 'interest': floats(d, 0x80452C7C, 3),
    }


def effects_of(d, owner_gobj):
    """Every live effect GObj whose EF_Effect.parent_gobj is this fighter."""
    out = []
    table = d.u32(GOBJ_ENTITIES)
    if not table:
        return out
    for link in EFFECT_PLINKS:
        g = d.u32(table + 4 * link)
        seen = 0
        while g and 0x80000000 <= g < 0x81800000 and seen < 512:
            seen += 1
            eff = d.u32(g + 0x2C)
            if eff and 0x80000000 <= eff < 0x81800000 and d.u32(eff + 0x08) == owner_gobj:
                root = d.u32(g + 0x28)
                entry = {'gobj': hex(g), 'p_link': link}
                if root:
                    entry['root_world'] = jobj_world(d, root)
                    entry['root_scale'] = floats(d, root + 0x2C, 3)
                    kids = []
                    c = d.u32(root + 0x10)
                    while c and 0x80000000 <= c < 0x81800000 and len(kids) < 8:
                        aobj = d.u32(c + 0x7C)
                        kids.append({'flags': hex(d.u32(c + 0x14)), 'scale': floats(d, c + 0x2C, 3),
                                     'rot_z': floats(d, c + 0x24, 1), 'world': jobj_world(d, c),
                                     'anim_frame': floats(d, aobj + 4, 1)[0] if aobj else None})
                        c = d.u32(c + 0x08)
                    entry['children'] = kids
                out.append(entry)
            g = d.u32(g + 0x08)
    return out


def read_items(d):
    out = []
    table = d.u32(GOBJ_ENTITIES)
    g = d.u32(table + 4 * ITEM_PLINK) if table else 0
    seen = 0
    while g and 0x80000000 <= g < 0x81800000 and seen < 256:
        seen += 1
        it = d.u32(g + 0x2C)
        root = d.u32(g + 0x28)
        if it and 0x80000000 <= it < 0x81800000:
            e = {'kind': d.u32(it + 0x10), 'facing': floats(d, it + 0x2C, 1)[0], 'vel': floats(d, it + 0x40, 3),
                 'pos': floats(d, it + 0x4C, 3), 'msid': d.u32(it + 0x24)}
            if root and 0x80000000 <= root < 0x81800000:
                e['root'] = {'world': floats(d, root + 0x44, 12), 'scale': floats(d, root + 0x2C, 3),
                             'rot': floats(d, root + 0x1C, 4), 'flags': hex(d.u32(root + 0x14))}
            out.append(e)
        g = d.u32(g + 0x08)
    return out


def read_collision(d):
    """The engine's live collision (tools/liteaudit/stage_dump.py layout): every
    line's two vertex world positions and its runtime flags."""
    cd = d.u32(COLL_DATA)
    if not cd:
        return None
    n_vtx, lines_p, n_line = d.u32(cd + 4), d.u32(cd + 8), d.u32(cd + 0xC)
    lraw = d.bytes(lines_p, n_line * 0x10)
    vraw = d.bytes(d.u32(COLL_VTX), n_vtx * 0x18)
    fraw = d.bytes(d.u32(COLL_LINE), n_line * 8)
    out = []
    for i in range(n_line):
        v0, v1 = struct.unpack_from('>HH', lraw, i * 0x10)
        x0, y0 = struct.unpack_from('>ff', vraw, v0 * 0x18 + 8)
        x1, y1 = struct.unpack_from('>ff', vraw, v1 * 0x18 + 8)
        flags = struct.unpack_from('>I', fraw, i * 8 + 4)[0]
        out.append([i, flags, round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)])
    return out


# Link, Marth, Young Link, Roy: struct SwordAttrs in the special attributes (Fighter +0x2D4)
SWORD_ATTRS = {6: 0x64, 18: 0x78, 20: 0x64, 26: 0x78}


def sword_trail(d, ft, parts, attrs_at):
    """The sword trail as the game holds it (ftafterimage.c): the sample count (+0x2100, -1 off), the
    ring's next slot and item bit (+0x2101), the blade (+0x20F8 inner, +0x20FC outer), the ring of 3
    samples [joint position, X axis] (+0x20B0), newest first, and the sword joint now."""
    count = d.u8(ft + 0x2100)
    count = count - 256 if count >= 128 else count
    bits = d.u8(ft + 0x2101)
    slot = (bits >> 1) & 0x7F
    ring = [floats(d, ft + 0x20B0 + 0x18 * k, 6) for k in range(3)]
    order = [(slot - 1 - k) % 3 for k in range(3)]
    out = {'count': count, 'item': bits & 1, 'blade': floats(d, ft + 0x20F8, 2),
           'ring': [ring[k] for k in order[:max(0, count)]]}
    if attrs_at is not None:
        part = d.u32(d.u32(ft + 0x2D4) + attrs_at + 0x14)
        joint = d.u32(parts + 0x10 * part) if parts and part < 200 else None
        if joint:
            m = floats(d, joint + 0x44, 12)
            out['sword'] = [m[3], m[7], m[11], m[0], m[4], m[8]]
    beam = beam_sword(d, ft, parts)
    if beam:
        out['beam'] = beam
    return out


def beam_sword(d, ft, parts):
    """A held Beam Sword (item kind 12, Fighter +0x1974): its bone 5 (the trail's joint, it_80285314) and the
    fighter's hold part (ft_data +0x8 -> +0x10) as world 3x4 matrices, the blade's Y scale (bone 6) and the
    sword's length variables x10 / x28 / x4C (Item +0xDE4 / +0xDFC / +0xE20)."""
    gobj = d.u32(ft + 0x1974)
    if not gobj or not 0x80000000 <= gobj < 0x81800000:
        return None
    it = d.u32(gobj + 0x2C)
    if not it or d.u32(it + 0x10) != 12:
        return None
    bones = d.u32(it + 0xBBC)
    out = {'x10': floats(d, it + 0xDE4, 1)[0], 'x28': floats(d, it + 0xDFC, 1)[0], 'x4C': floats(d, it + 0xE20, 1)[0]}
    for k in (1, 5, 6):
        j = d.u32(bones + 4 * k) if bones else None
        if j:
            out[f'bone{k}'] = floats(d, j + 0x44, 12)
    hold = d.u8(d.u32(d.u32(ft + 0x10C) + 0x8) + 0x10)
    j = d.u32(parts + 0x10 * hold) if parts else None
    if j:
        out['hold'] = [hold, floats(d, j + 0x44, 12)]
    return out


def read_live(d):
    live = []
    for port in range(4):
        gobj, ft = fighter_ptr(d, port)
        if not ft:
            continue
        entry = {'port': port, 'kind': d.u32(ft + 0x04), 'pos': floats(d, ft + 0xB0, 2), 'state': d.u32(ft + 0x10),
                 'facing': floats(d, ft + 0x2C, 1)[0], 'anim_frame': floats(d, ft + 0x894, 1)[0]}
        parts = d.u32(ft + 0x5E8)
        hip = d.u32(parts + 0x10 * 4) if parts else None
        if hip:
            entry['hip'] = jobj_world(d, hip)
            aobj = d.u32(hip + 0x7C)
            if aobj and 0x80000000 <= aobj < 0x81800000:
                entry['hip_aobj_frame'] = floats(d, aobj + 4, 1)[0]
        tn = d.u32(parts + 0x10 * 1) if parts else None
        if tn:
            aobj = d.u32(tn + 0x7C)
            if aobj and 0x80000000 <= aobj < 0x81800000:
                entry['transn_aobj_frame'] = floats(d, aobj + 4, 1)[0]
        if entry['kind'] in (1, 22):              # Fox / Falco: the reflector's own effect objects
            entry['effects'] = effects_of(d, gobj)
        trail = sword_trail(d, ft, parts, SWORD_ATTRS.get(entry['kind']))
        if entry['kind'] in SWORD_ATTRS or 'beam' in trail:
            entry['trail'] = trail
        live.append(entry)
    return live


def align(t, live):
    """Which replay frame the frozen game shows: the truth frame whose every
    port (x, y, state, action frame counter) best matches the live fighters."""
    best = None
    for fr, rows in t['truth'].items():
        cost = 0.0
        for x, y, st, age in rows:
            if x is None:
                continue
            cost += min(abs(q['pos'][0] - x) + abs(q['pos'][1] - y) + (0 if q['state'] == st else 50)
                        + abs(q['anim_frame'] - age) for q in live) if live else 1e9
        if best is None or cost < best[1] - 1e-9 or (abs(cost - best[1]) <= 1e-9 and int(fr) == t['frame']):
            best = (int(fr), cost)
    return {'frame': best[0], 'cost': round(best[1], 5)} if best else None


def capture_target(t, out, iso, log):
    F = t['frame']
    start = max(-123, F - 150)
    out.mkdir(parents=True, exist_ok=True)
    fd, comm = tempfile.mkstemp(suffix='.json', prefix='comm_', dir=str(out))
    os.close(fd)
    comm = Path(comm)
    comm.write_text(json.dumps({'mode': 'normal', 'replay': str(Path(t['slp']).resolve()), 'startFrame': start,
                                'isRealTimeMode': False, 'commandId': uuid.uuid4().hex}))
    t0 = time.time()
    proc = subprocess.Popen([playback_dolphin_path(), '-i', str(comm), '-b', '-e', iso],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    meta = {'id': t['id'], 'slp': t['slp'], 'frame': F, 'pid': proc.pid}
    log(f"{t['id']}: playback pid {proc.pid}, start {start}, target {F}")
    try:
        d = Dolphin(proc.pid)
        if _locate_live(d) is None:
            raise RuntimeError('playback Dolphin never exposed a live MEM1')
        pre = int(t.get('seq_pre', 0))
        # run (fast-forwarded seek, then real time) until just short of the frame
        while True:
            mf = d.u32(MATCH_FRAME)
            if mf is not None and mf < 0x80000000 and F - pre - 45 <= mf <= F - pre - 5:
                break
            if mf is not None and mf < 0x80000000 and F - pre - 5 < mf < F + 100000:
                raise RuntimeError(f'overshot: match frame {mf} vs {F}')
            if proc.poll() is not None or time.time() - t0 > 240:
                raise RuntimeError(f'never reached frame {F} (last match frame {mf})')
            time.sleep(0.001)
        framestep.freeze(d)
        time.sleep(0.1)
        seq = []

        def step_to(target):
            for _ in range(400):
                cur = d.u32(MATCH_FRAME)
                if cur >= target:
                    return cur
                if framestep.step(d, 1) != 1:
                    raise RuntimeError('stepping failed')
                if pre and cur + 1 >= F - pre:
                    seq.append({'match_frame': d.u32(MATCH_FRAME), 'live': read_live(d), 'items': read_items(d)})
            raise RuntimeError('could not reach the frame')
        if step_to(F) != F:
            raise RuntimeError(f'landed on {d.u32(MATCH_FRAME)}, not {F}')
        meta['match_frame'] = d.u32(MATCH_FRAME)
        meta['seconds_to_frame'] = round(time.time() - t0, 1)
        live = read_live(d)
        meta['live'] = live
        meta['items'] = read_items(d)
        meta['alignment'] = align(t, live)
        meta['camera'] = read_camera(d)
        meta['collision'] = read_collision(d)
        framestep.wait_render_frames(d, 4)
        png = shot.capture_via_printwindow(proc.pid, max_width=1600)
        if not png:
            raise RuntimeError('screenshot returned nothing')
        (out / f"{t['id']}.png").write_bytes(png)
        for _ in range(int(t.get('seq_post', 0))):
            if framestep.step(d, 1) != 1:
                break
            seq.append({'match_frame': d.u32(MATCH_FRAME), 'live': read_live(d), 'items': read_items(d)})
        if seq:
            meta['seq'] = seq
        meta['seconds_total'] = round(time.time() - t0, 1)
        meta['ok'] = True
        log(f"{t['id']}: frozen on {meta['match_frame']}, aligned to {meta['alignment']}, {meta['seconds_total']} s")
    except Exception as e:                       # noqa: BLE001 -- record and go on
        meta['ok'] = False
        meta['error'] = repr(e)
        log(f"{t['id']}: FAILED {e!r}")
    finally:
        if proc.poll() is None:
            proc.kill()                          # the exact PID we started
            try:
                proc.wait(10)
            except Exception:                    # noqa: BLE001
                pass
        try:
            shot.close_capture(proc.pid)
        except Exception:                        # noqa: BLE001
            pass
        try:
            comm.unlink()
        except OSError:
            pass
    (out / f"{t['id']}.json").write_text(json.dumps(meta, indent=1))
    return meta


def capture_all(targets, out, iso=None, wait=1800, log=print):
    """Capture every target under one hold of the Dolphin lock; returns the metas."""
    iso = vanilla_iso(iso)
    dolphin_lock.acquire('liteaudit side-by-side capture', wait=wait)
    try:
        return [capture_target(t, Path(out), iso, log) for t in targets]
    finally:
        dolphin_lock.release()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--targets', required=True, help='targets-ext.json from prep.mjs')
    ap.add_argument('--out', required=True, help='folder for <id>.png / <id>.json')
    ap.add_argument('--only', default='')
    ap.add_argument('--wait', type=float, default=1800, help='seconds to queue for the Dolphin lock')
    ap.add_argument('--iso', help='vanilla NTSC 1.02 ISO (default: the one the app recorded)')
    a = ap.parse_args()
    targets = json.loads(Path(a.targets).read_text())
    if a.only:
        keep = set(a.only.split(','))
        targets = [t for t in targets if t['id'] in keep]

    def log(m):
        print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)
    capture_all(targets, Path(a.out), a.iso, a.wait, log)


if __name__ == '__main__':
    main()
