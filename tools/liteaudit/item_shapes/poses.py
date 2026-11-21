"""Shapes that ride a posed fighter (fighterbones.py): the Fire Fox / Fire Bird travel anchor (HipN) and
Bowser's Whirling Fortress shell. Fighter-local world units, x along facing, y up, model scale applied."""
import math

import cv2
import numpy as np

import fighterbones as fb
import hsdgeom
import stage_bake as sb
from isofiles import dat

PART_XROTN, PART_HIPN = 2, 4


def _mats(nodes, values):
    out = []
    for i, (parent, _) in enumerate(nodes):
        rx, ry, rz, sx, sy, sz, x, y, z = values[i]
        cx, cy, cz = math.cos(rx), math.cos(ry), math.cos(rz)
        ax, ay, az = math.sin(rx), math.sin(ry), math.sin(rz)
        m = np.array([[cz * cy, cz * ay * ax - az * cx, cz * ay * cx + az * ax, x], [az * cy, az * ay * ax + cz * cx, az * ay * cx - cz * ax, y],
                      [-ay, cy * ax, cy * cx, z], [0, 0, 0, 1.]])
        m[:3, :3] *= np.array([sx, sy, sz])[None, :]
        out.append(m if parent < 0 else out[parent] @ m)
    return out


def _part_world(code, state, frame, part, rotate_model=0.0):
    """world position of `part` at the action frame, facing +1 at the origin, with XRotN rotation X =
    2 pi - rotate_model (ftFox_SpecialHi_RotateModel)."""
    f = fb.fighter(code)
    end, trs, name = fb.tracks(code, state)
    a = fb.action(code, state)
    trans = f['joints'][1] if a.flags & 0x80000000 else None
    _, values = sb.pose(f['nodes'], trs, frame, remove_trans=trans)
    values[f['joints'][PART_XROTN]][0] = 2 * math.pi - rotate_model
    mats = _mats(f['nodes'], values)
    R = np.array([[math.cos(math.pi / 2), 0, math.sin(math.pi / 2), 0], [0, 1, 0, 0], [-math.sin(math.pi / 2), 0, math.cos(math.pi / 2), 0],
                  [0, 0, 0, 1.0]])
    S = np.diag([f['scale']] * 3 + [1.0])
    return (np.eye(4) @ R @ S @ mats[f['joints'][part]])[:3, 3]


def travel_hips():
    """Fox (1) / Falco (22) in SpecialHi (355) and SpecialAirHi (356), which share the table: per action frame,
    the XRotN pivot height and HipN minus the pivot (up), with the travel angle 0 (rotX = 2 pi). The plume
    sits on HipN = pivot + (fwd, up) turned by the travel angle about the pivot."""
    out = {}
    for code, cid in (('Fx', 1), ('Fc', 22)):
        tables = []
        for st in (355, 356):
            rows = []
            for fr in range(0, int(fb.tracks(code, st)[0]) + 1):
                h = _part_world(code, st, fr, PART_HIPN)
                pv = _part_world(code, st, fr, PART_XROTN)
                rows.append([round(pv[0], 3), round(pv[1], 3), round(h[0] - pv[0], 3), round(h[1] - pv[1], 3)])
            tables.append(rows)
        assert tables[0] == tables[1], code
        rows = tables[0]
        assert all(abs(r[0]) < 1e-6 and abs(r[1] - rows[0][1]) < 1e-6 for r in rows), code   # one pivot for all frames
        out[cid] = dict(pivot_up=rows[0][1], hip_up=[r[3] for r in rows])
    return out


# ---------------------------------------------------------------- Bowser's Whirling Fortress
# ftKp_SpecialN_80135780: on the ground (SpecialHi 359) the shell-only model shows while cmd_vars[2] & 1, in the
# air (SpecialAirHi 360) while cmd_vars[1] & 1; cmd_vars[2] == 2 ends both (air: ftKp_SpecialAirHi_Anim -> Fall).
KOOPA_FLAG = {359: 2, 360: 1}
SET_FLAG = 0x13
SHELL_BOX, SHELL_PPU = (-26, 26, -10, 34), 12


def koopa_windows():
    """{state: [first, end)} action frames with the shell-only model, from the PlKp.dat subaction scripts."""
    fd = fb.fighter('Kp')['fd']
    out = {}
    for st, flag in KOOPA_FLAG.items():
        cmds = [c for c in fd.script(fb.action('Kp', st).index).commands if not c.after_end and c.code == SET_FLAG]
        first = min(c.frame for c in cmds if c.fields['flag'] == flag and c.fields['value'] & 1)
        end = min(c.frame for c in cmds if c.fields['flag'] == 2 and c.fields['value'] == 2)
        out[st] = [int(first), int(end)]
    return out


def koopa_shell_dobjs():
    """PlKp.dat ftData->x8->x0 (FtPartsDesc): costume 0, model part 0, variant 1 = the shell-only DObjs."""
    d = dat('PlKp.dat')
    x8 = d.p(next(v for k, v in d.roots if k.startswith('ftData')) + 8)
    lookup = d.p(d.p(x8 + 4))                         # vis_table[costume 0][0]
    variant = d.p(lookup + 4) + 8 * 1                   # model 0's variants, variant 1
    arr = d.p(variant + 4)
    return {d.b(arr + k) for k in range(d.u(variant))}


def koopa_shell():
    """Per state, per action frame inside the window: the outline of the shell-only DObjs of PlKpNr.dat posed
    with the state's own figatree, front view (orthographic, 12 px/unit, coverage closed by 0.25 units,
    simplified 0.12). {state: {first, frames: [polygon]}}."""
    m = dat('PlKpNr.dat')
    root = next(v for k, v in m.roots if k.endswith('_joint') and 'matanim' not in k)
    shell = koopa_shell_dobjs()
    f = fb.fighter('Kp')
    c, s = math.cos(math.pi / 2), math.sin(math.pi / 2)        # fighter root: facing +1, model scale
    world = np.eye(4) @ np.array([[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1.0]]) @ np.diag([f['scale']] * 3 + [1.0])
    x0, x1, y0, y1 = SHELL_BOX
    out = {}
    for st, (lo, hi) in koopa_windows().items():
        end, trs, _ = fb.tracks('Kp', st)
        a = fb.action('Kp', st)
        trans = f['joints'][1] if a.flags & 0x80000000 else None
        frames = []
        for fr in range(lo, hi):
            _, values = sb.pose(f['nodes'], trs, float(fr), remove_trans=trans)
            ov = {i: dict(r=list(v[0:3]), s=list(v[3:6]), t=list(v[6:9])) for i, v in enumerate(values)}
            parts, _ = hsdgeom.model(m, root, override=ov, with_hidden=True)
            parts = hsdgeom.transform_parts([p for i, p in enumerate(parts) if i in shell], world)
            fo, W, H = hsdgeom.ortho(x0, x1, y0, y1, SHELL_PPU)
            img, cov = hsdgeom.raster(m, parts, fo, W, H, ss=2)
            r = max(1, int(round(0.25 * SHELL_PPU)))
            k = cv2.morphologyEx(cov.astype(np.uint8), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
            ps = hsdgeom.silhouette(k > 0, x0, y1, SHELL_PPU, eps_units=0.12, min_area_units=0.5)
            frames.append(ps[0] if ps else [])
        out[st] = dict(first=lo, frames=frames)
    return out
