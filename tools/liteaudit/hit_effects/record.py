"""Record what the game spawns when a hit lands: play the .slp in Slippi's playback Dolphin, freeze
just before the hit frame and step through it, reading RAM every frame.

    app/venv/Scripts/python.exe -B tools/liteaudit/hit_effects/record.py --targets <targets.json> --out <dir>
        [--only id,id] [--pre 2] [--post 24] [--shots 14] [--iso PATH] [--wait S] [--root DIR]

targets.json is samples.json (the hits build.py bakes; .slp paths relative to --root), pick.mjs's
output, or the side-by-side tool's prep.mjs (id, slp, frame).
Per target, <out>/<id>.json holds per frame (F - pre .. F + post):
  - every fighter: position, state, action frame, facing, percent, hitlag, and the damage record
    the game keeps for its last hit (Fighter +0x1850 kb, +0x1854 contact point, +0x1860 element,
    +0x184C hurtbox, ftcoll.c ftColl_8007A06C), its hurtbox capsules (+0x11A0, world a/b and
    radius) and its live hitboxes (+0x914, x4: state, damage, radius, element, previous and
    current centre, contact point) and its colour overlays (+0x408, +0x488: colour animation,
    wait, colour, light, flags);
  - every live particle (HSD_Particle, the lists at hsd_804D0908 by link): bank, texture group and
    pose, colours, size, rotation, life, position, velocity, its command list and generator, and its
    app SRT (translate, scale, matrix) when it has one;
  - every live effect GObj (p_links 11, 12): root and child JObj world matrices, scales and flags;
  - the game camera.
and <out>/<id>_<k>.png the game picture for k = 0 .. shots-1 frames after the hit (F + k).
The bank tables (command lists, texture groups: psCmdListArray / psTexGroupArray) are saved once
per target so particles can be traced back to EfCoData.dat offline (build.py).
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

STATIC_PLAYER, STRIDE = 0x80453080, 0xE90
CAMERA = 0x80452C68
GOBJ_ENTITIES = 0x804D782C
EFFECT_PLINKS = (11, 12)
VANILLA_STAGE_MAX = 32        # m-ex stages are numbered past the vanilla ones
FIRST_FRAME_S = 25            # a replay that plays shows a match frame by now (a capture takes ~10 s)
REACH_S = 90                  # and reaches the hit by now
PTCL_HEADS, PTCL_LINKS = 0x804D0908, 146
TEXG_TABLE, TEXG_COUNT = 0x804D0B50, 0x804D0A4C
CMD_TABLE, CMD_COUNT = 0x804D0E5C, 0x804D0D58


def ok(p):
    return p and 0x80000000 <= p < 0x81800000


def floats(d, addr, n):
    raw = d.bytes(addr, 4 * n)
    return [round(v, 5) for v in struct.unpack('>' + 'f' * n, raw)] if raw and len(raw) == 4 * n else None


def fighter_ptr(d, port):
    gobj = d.u32(STATIC_PLAYER + STRIDE * port + 0xB0)
    if not ok(gobj):
        return None, None
    ft = d.u32(gobj + 0x2C)
    return (gobj, ft) if ok(ft) else (None, None)


def read_fighter(d, port, gobj, ft):
    e = {'port': port, 'gobj': hex(gobj), 'kind': d.u32(ft + 0x04), 'pos': floats(d, ft + 0xB0, 3), 'state': d.u32(ft + 0x10),
         'facing': floats(d, ft + 0x2C, 1)[0], 'anim_frame': floats(d, ft + 0x894, 1)[0], 'scale': floats(d, ft + 0x34, 3),
         'percent': floats(d, ft + 0x1830, 1)[0],
         'dmg': {'facing': floats(d, ft + 0x1844, 1)[0], 'angle': d.s32(ft + 0x1848), 'hurtbox': d.s32(ft + 0x184C),
                 'kb': floats(d, ft + 0x1850, 1)[0], 'pos': floats(d, ft + 0x1854, 3), 'element': d.u32(ft + 0x1860),
                 'source': hex(d.u32(ft + 0x1868) or 0), 'x187c': floats(d, ft + 0x187C, 1)[0], 'x1880': floats(d, ft + 0x1880, 3),
                 'x188c': d.s32(ft + 0x188C), 'x1890': d.s32(ft + 0x1890), 'x1898': floats(d, ft + 0x1898, 1)[0]},
         # hitlag shake (ftCo_DamageFall.c ftCo_80090594 / ftCo_80090690): pattern type, frames left, step
         'shake': {'type': d.u8(ft + 0x18F8), 'frames': d.u16(ft + 0x18FA), 'step': d.u8(ft + 0x18FC), 'count': d.u8(ft + 0x18FD)}}
    n = d.u8(ft + 0x119E) or 0
    hurt = []
    for i in range(min(n, 15)):
        c = ft + 0x11A0 + 0x4C * i
        hurt.append({'state': d.u32(c), 'r': floats(d, c + 0x1C, 1)[0], 'a': floats(d, c + 0x28, 3), 'b': floats(d, c + 0x34, 3),
                     'bone': d.s32(c + 0x40), 'height': d.s32(c + 0x44)})
    e['hurt'] = hurt
    hits = []
    for i in range(4):
        h = ft + 0x914 + 0x138 * i
        st = d.u32(h)
        if not st:
            continue
        hits.append({'i': i, 'state': st, 'dmg': floats(d, h + 0xC, 1)[0], 'r': floats(d, h + 0x1C, 1)[0], 'element': d.u32(h + 0x30),
                     'sfx': d.s32(h + 0x38), 'cur': floats(d, h + 0x4C, 3), 'prev': floats(d, h + 0x58, 3),
                     'contact': floats(d, h + 0x64, 3)})
    e['hits'] = hits
    # the colour overlays (lb/types.h ColorOverlay, ftcolanim.c): the model's material blends to
    # `rgba` by its alpha while flags 0x80 is set (ftmaterial.c); +0x408 is drawn while its colour
    # animation `i` is not 0, +0x488 otherwise (ftdevice.c ftCo_800C0658)
    e['overlay'] = [{'at': hex(o), 'i': d.s32(ft + o + 0x28), 'timer': d.s32(ft + o), 'rgba': list(d.bytes(ft + o + 0x2C, 4) or b''),
                     'light': list(d.bytes(ft + o + 0x50, 4) or b''), 'flags': d.u8(ft + o + 0x7C)} for o in (0x408, 0x488)]
    return e


def read_particles(d):
    out = []
    for link in range(PTCL_LINKS):
        p = d.u32(PTCL_HEADS + 4 * link)
        seen = 0
        while ok(p) and seen < 2000:
            seen += 1
            raw = d.bytes(p, 0x98)
            if not raw or len(raw) < 0x98:
                break
            nxt, kind = struct.unpack_from('>II', raw, 0)
            bank, texg, pose, pal = raw[8], raw[9], raw[10], raw[11]
            prim = list(raw[0x12:0x16])
            env = list(raw[0x16:0x1A])
            cmdlist, = struct.unpack_from('>I', raw, 0x20)
            cmdptr, = struct.unpack_from('>H', raw, 0x24)
            life, = struct.unpack_from('>H', raw, 0x2A)
            vel = struct.unpack_from('>fff', raw, 0x2C)
            grav, fric = struct.unpack_from('>ff', raw, 0x38)
            pos = struct.unpack_from('>fff', raw, 0x40)
            size, rot = struct.unpack_from('>ff', raw, 0x4C)
            mat = list(raw[0x7C:0x80])
            trail, = struct.unpack_from('>f', raw, 0x84)
            gen, appsrt = struct.unpack_from('>II', raw, 0x88)
            # the colour the display uses: primCol eased toward its target by remain / count
            # (psdisp.c getColorPrimEnv)
            pcount, ecount = struct.unpack_from('>HH', raw, 0x0E)
            premain, eremain = struct.unpack_from('>HH', raw, 0x68)
            ptarget, etarget = list(raw[0x6C:0x70]), list(raw[0x70:0x74])

            def eased(col, target, remain, count):
                if not count:
                    return col
                s = 65536 * remain // count
                return [((t << 16) + (c - t) * s) >> 16 for c, t in zip(col, target)]
            acmp = {'count': struct.unpack_from('>H', raw, 0x54)[0], 'mode': raw[0x56], 'p1': raw[0x57], 'p2': raw[0x58],
                    'remain': struct.unpack_from('>H', raw, 0x78)[0], 't1': raw[0x7A], 't2': raw[0x7B]}
            e = {'addr': hex(p), 'link': link, 'kind': hex(kind), 'bank': bank, 'texg': texg, 'pose': pose, 'pal': pal,
                 'prim': prim, 'env': env, 'prim_shown': eased(prim, ptarget, premain, pcount),
                 'env_shown': eased(env, etarget, eremain, ecount), 'acmp': acmp,
                 'cmdlist': hex(cmdlist), 'cmdptr': cmdptr, 'life': life,
                 'vel': [round(v, 4) for v in vel], 'grav': round(grav, 4), 'fric': round(fric, 4),
                 'pos': [round(v, 4) for v in pos], 'size': round(size, 4), 'rot': round(rot, 4), 'mat_amb': mat,
                 'trail': round(trail, 4), 'gen': hex(gen), 'appsrt': hex(appsrt)}
            if ok(appsrt):
                e['srt'] = {'translate': floats(d, appsrt + 0x8, 3), 'rot': floats(d, appsrt + 0x14, 4),
                            'scale': floats(d, appsrt + 0x24, 3), 'mmtx': floats(d, appsrt + 0x34, 12)}
            if ok(gen):
                e['gen_pos'] = floats(d, gen + 0x24, 3)
            out.append(e)
            p = nxt
    return out


def read_effects(d):
    out = []
    table = d.u32(GOBJ_ENTITIES)
    if not ok(table):
        return out
    for link in EFFECT_PLINKS:
        g = d.u32(table + 4 * link)
        seen = 0
        while ok(g) and seen < 512:
            seen += 1
            eff = d.u32(g + 0x2C)
            root = d.u32(g + 0x28)
            entry = {'gobj': hex(g), 'p_link': link, 'parent': hex(d.u32(eff + 0x08) or 0) if ok(eff) else None}
            if ok(root):
                js = []

                def walk(j, depth):
                    while ok(j) and len(js) < 32:
                        aobj = d.u32(j + 0x7C)
                        js.append({'depth': depth, 'flags': hex(d.u32(j + 0x14)), 'scale': floats(d, j + 0x2C, 3),
                                   'rot': floats(d, j + 0x1C, 4), 'translate': floats(d, j + 0x38, 3),
                                   'world': floats(d, j + 0x44, 12), 'dobj': hex(d.u32(j + 0x18) or 0),
                                   'anim_frame': floats(d, aobj + 4, 1)[0] if ok(aobj) else None})
                        walk(d.u32(j + 0x10), depth + 1)
                        j = d.u32(j + 0x08)
                walk(root, 0)
                entry['joints'] = js
            out.append(entry)
            g = d.u32(g + 0x08)
    return out


def read_camera(d):
    gobj = d.u32(CAMERA)
    cobj = d.u32(gobj + 0x28) if ok(gobj) else None
    if not ok(cobj):
        return None
    return {'viewport': floats(d, cobj + 0x0C, 4), 'near_far': floats(d, cobj + 0x38, 2), 'fov_aspect': floats(d, cobj + 0x40, 2),
            'projection_type': d.u8(cobj + 0x50), 'view_mtx': floats(d, cobj + 0x54, 12),
            'eye': floats(d, 0x80452C94, 3), 'interest': floats(d, 0x80452C7C, 3)}


def read_banks(d):
    banks = []
    for bank in range(4):
        cmd_n, cmd_t = d.u32(CMD_COUNT + 4 * bank), d.u32(CMD_TABLE + 4 * bank)
        tex_n, tex_t = d.u32(TEXG_COUNT + 4 * bank), d.u32(TEXG_TABLE + 4 * bank)
        if not ok(cmd_t):
            continue
        cmds = [hex(d.u32(cmd_t + 4 * i) or 0) for i in range(min(cmd_n, 4096))] if cmd_n < 4096 else []
        texs = []
        if ok(tex_t) and tex_n < 4096:
            for i in range(tex_n):
                g = d.u32(tex_t + 4 * i)
                if ok(g):
                    num, fmt, tfmt, w, h = struct.unpack('>IIIII', d.bytes(g, 20))
                    texs.append({'i': i, 'addr': hex(g), 'num': num, 'fmt': fmt, 'tlutfmt': tfmt, 'w': w, 'h': h,
                                 'pal': d.u16(g + 0x14), 'images': [hex(d.u32(g + 0x18 + 4 * k) or 0) for k in range(min(num, 64))]})
                else:
                    texs.append(None)
        banks.append({'bank': bank, 'cmd_n': cmd_n, 'cmds': cmds, 'tex_n': tex_n, 'texs': texs})
    return banks


def frame_record(d):
    fighters = []
    for port in range(4):
        gobj, ft = fighter_ptr(d, port)
        if ft:
            fighters.append(read_fighter(d, port, gobj, ft))
    return {'match_frame': d.u32(MATCH_FRAME), 'fighters': fighters, 'particles': read_particles(d),
            'effects': read_effects(d), 'camera': read_camera(d)}


def record_target(t, out, iso, pre, post, shots, log):
    F = t['frame']
    if t.get('stage') is not None and t['stage'] > VANILLA_STAGE_MAX:
        # an m-ex stage: the vanilla ISO cannot play it (playback stays black)
        meta = {'id': t['id'], 'slp': t['slp'], 'frame': F, 'ok': False, 'error': f"custom stage {t['stage']}"}
        log(f"{t['id']}: skipped, custom stage {t['stage']}")
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{t['id']}.json").write_text(json.dumps(meta))
        return meta
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
    meta = {'id': t['id'], 'slp': t['slp'], 'frame': F, 'kind': t.get('kind'), 'why': t.get('why'),
            'subject': t.get('subject'), 'attacker': t.get('attacker'), 'pid': proc.pid}
    log(f"{t['id']}: playback pid {proc.pid}, start {start}, target {F}")
    try:
        d = Dolphin(proc.pid)
        if _locate_live(d) is None:
            raise RuntimeError('playback Dolphin never exposed a live MEM1')
        playing = False
        while True:
            mf = d.u32(MATCH_FRAME)
            if mf is not None and mf < 0x80000000 and F - pre - 45 <= mf <= F - pre - 5:
                break
            if mf is not None and mf < 0x80000000 and F - pre - 5 < mf < F + 100000:
                raise RuntimeError(f'overshot: match frame {mf} vs {F}')
            playing = playing or (mf is not None and 0 < mf < 0x80000000)
            if proc.poll() is not None:
                raise RuntimeError(f'playback Dolphin exited before frame {F}')
            if not playing and time.time() - t0 > FIRST_FRAME_S:
                raise RuntimeError(f'no match frame after {FIRST_FRAME_S} s: the replay does not play on this ISO '
                                   '(a custom stage or character?)')
            if time.time() - t0 > REACH_S:
                raise RuntimeError(f'never reached frame {F} (last match frame {mf})')
            time.sleep(0.001)
        framestep.freeze(d)
        time.sleep(0.1)
        for _ in range(400):
            if d.u32(MATCH_FRAME) >= F - pre:
                break
            if framestep.step(d, 1) != 1:
                raise RuntimeError('stepping failed')
        meta['banks'] = read_banks(d)
        frames = []
        while True:
            mf = d.u32(MATCH_FRAME)
            rec = frame_record(d)
            k = mf - F
            if 0 <= k < shots:
                framestep.wait_render_frames(d, 4)
                png = shot.capture_via_printwindow(proc.pid, max_width=1600)
                if png:
                    (out / f"{t['id']}_{k:02d}.png").write_bytes(png)
                    rec['shot'] = f"{t['id']}_{k:02d}.png"
            frames.append(rec)
            if mf >= F + post:
                break
            if framestep.step(d, 1) != 1:
                raise RuntimeError('stepping failed')
        meta['frames'] = frames
        meta['seconds_total'] = round(time.time() - t0, 1)
        meta['ok'] = True
        log(f"{t['id']}: {len(frames)} frames {frames[0]['match_frame']}..{frames[-1]['match_frame']}, {meta['seconds_total']} s")
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
    (out / f"{t['id']}.json").write_text(json.dumps(meta))
    return meta


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--targets', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--only', default='')
    ap.add_argument('--pre', type=int, default=2)
    ap.add_argument('--post', type=int, default=24)
    ap.add_argument('--shots', type=int, default=14)
    ap.add_argument('--wait', type=float, default=1800, help='seconds to queue for the Dolphin lock')
    ap.add_argument('--iso', help='vanilla NTSC 1.02 ISO (default: the one the app recorded)')
    ap.add_argument('--root', default=os.environ.get('SLIPPI_REPLAYS') or str(Path.home() / 'Documents' / 'Slippi'), help='folder that relative .slp paths (samples.json) start from')
    a = ap.parse_args()
    targets = json.loads(Path(a.targets).read_text())
    for t in targets:
        if not Path(t['slp']).is_absolute():
            t['slp'] = str(Path(a.root) / t['slp'])
    if a.only:
        keep = set(a.only.split(','))
        targets = [t for t in targets if t['id'] in keep]
    iso = a.iso
    if not iso:
        from shared.vanilla_extract.vanilla_refs import known_vanilla_iso
        iso = known_vanilla_iso()
    if not iso or not Path(iso).is_file():
        raise SystemExit('no vanilla ISO: pass --iso')

    def log(m):
        print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)
    dolphin_lock.acquire('liteaudit hit-effect recording', wait=a.wait)
    try:
        for t in targets:
            record_target(t, Path(a.out), str(iso), a.pre, a.post, a.shots, log)
    finally:
        dolphin_lock.release()


if __name__ == '__main__':
    main()
