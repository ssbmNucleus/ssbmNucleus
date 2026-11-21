"""Posed fighter bones from the vanilla ISO (stage_bake.bake_fighters' path): skeleton of Pl<XX>Nr.dat,
the action's FigaTree from Pl<XX>AJ.dat, part index -> node mapping (PlCo holes), pose at a frame.

world(code, state, frame, pos, facing) -> {part: 4x4 world matrix}; the fighter root takes the position,
rotation Y = pi/2 x facing and the model scale (common attributes +0x8C); TopN's translation is cleared
(Slippi records the moved root). Action state -> action index comes from the DOL's motion state tables,
located by the decomp's symbols.txt (DECOMP, set by build.py)."""
import math
import os
import re
import struct
from functools import lru_cache
from pathlib import Path

import numpy as np

import stage_bake as sb
from isofiles import disc
from vault.echo.subactions import FighterDat
from tools.native_rig.fobj_reader import read_figatree

CODES = 'Mr Fx Ca Dk Kb Kp Lk Sk Ns Pe Pp Nn Pk Ss Ys Pr Mt Lg Ms Zd Cl Dr Fc Pc Gw Gn Fe'.split()
DECOMP = Path(os.environ.get('MELEE_DECOMP') or Path.home() / 'projects' / 'melee')


@lru_cache(None)
def symbols():
    p = DECOMP / 'config/GALE01/symbols.txt'
    return {m[0]: (int(m[1], 16), int(m[2], 16)) for m in re.findall(
        r'(\w+) = \.[^:]+:0x([0-9A-Fa-f]+); // type:object size:0x([0-9A-Fa-f]+)', p.read_text())}


@lru_cache(None)
def fighter(code):
    D = disc()
    cid = CODES.index(code)
    fd = FighterDat(D.file(f'Pl{code}.dat'))
    raw = sb.FighterNumericDat(D.file(f'Pl{code}.dat'))
    attrs = fd.dat.ptr(fd.ft_root)
    scale = fd.dat.f32(attrs + 0x8c)
    model = f'Pl{code}Nr.dat'
    if model not in D.entries:
        model = next(n for n in D.entries if re.fullmatch(f'Pl{code}[A-Z][a-z].dat', n))
    nodes = sb.skeleton(D.file(model))
    aj = D.file(f'Pl{code}AJ.dat')
    plco = sb.FighterNumericDat(D.file('PlCo.dat'))
    missing_table = plco.u(plco.roots['ftLoadCommonData'] + 20)
    missing = plco.u(missing_table + cid * 4)
    holes = {plco.d[plco.u(missing) + 4 * i] for i in range(plco.u(missing + 4))} if missing else set()
    joint_indices = {}
    node = part = 0
    while node < len(nodes):
        if part not in holes:
            joint_indices[part] = node
            node += 1
        part += 1
    sy = symbols()
    common = D.ram(sy['ftData_MotionStateList'][0], 341 * 32)
    special = struct.unpack('>33I', D.ram(sy['ftData_CharacterStateTables'][0], 33 * 4))
    address = special[cid]
    size = next(n for a, n in sy.values() if a == address)
    table = common + D.ram(address, size)
    indices = [struct.unpack_from('>i', table, i)[0] for i in range(0, len(table), 32)]
    return dict(fd=fd, raw=raw, scale=scale, nodes=nodes, aj=aj, joints=joint_indices, indices=indices, cid=cid)


def action(code, state):
    f = fighter(code)
    return f['fd'].actions[f['indices'][state]]


@lru_cache(None)
def tracks(code, state):
    f = fighter(code)
    a = action(code, state)
    clip = sb.FighterNumericDat(f['aj'][a.anim_offset:a.anim_offset + a.anim_size])
    end, counts, trs, *_ = read_figatree(clip.d, next(iter(clip.roots.values())))
    return end, trs, a.motion


def local(code, state, frame):
    """{node: model-space 4x4 (fighter root at origin, facing +z, unscaled)} for the action at frame."""
    f = fighter(code)
    end, trs, name = tracks(code, state)
    # bake_fighters: TransN's translation is moved into the fighter's position (and cleared) only for
    # actions whose flags have bit 31 (ftAnim_8006E054); otherwise it stays in the pose
    a = action(code, state)
    trans = f['joints'][1] if a.flags & 0x80000000 else None
    mats, _ = sb.pose(f['nodes'], trs, frame, remove_trans=trans)
    return mats


def world(code, state, frame, pos=(0.0, 0.0), facing=1.0):
    f = fighter(code)
    mats = local(code, state, frame)
    c, s = math.cos(math.pi / 2 * facing), math.sin(math.pi / 2 * facing)
    R = np.array([[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1.0]])
    S = np.diag([f['scale']] * 3 + [1.0])
    T = np.eye(4)
    T[:3, 3] = [pos[0], pos[1], 0.0]
    root = T @ R @ S
    out = {}
    for part, node in f['joints'].items():
        out[part] = root @ mats[node]
    return out


def hold_part(code):
    """ft_data->x8->x10: the item-hold part (setupVeg / Item_8026AB54)."""
    f = fighter(code)
    raw = f['raw']
    root = f['fd'].ft_root
    return raw.d[raw.u(root + 8) + 0x10]
