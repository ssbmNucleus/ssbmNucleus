"""Shield bubble geometry from vanilla game data (read-only ISO access), for build.py.

Reuses the liteaudit helpers: FighterDisc + FighterNumericDat + skeleton() (tools/liteaudit/stage_bake.py),
FighterDat (vault/echo/subactions.py), read_figatree (tools/native_rig/fobj_reader.py)
and stage_bake.fighter_value (fighter FOBJ evaluation). build.py puts tools/liteaudit and app/backend
on sys.path before importing this module.

Decomp references (src/melee/ft/chara/ftCommon/ftCo_Guard.c):
  ftCo_80091E78  per-frame guard pose: ShieldPose (ft_data->x20->x8, an
                 HSD_Joint tree from TransN down) blended with the rest pose +
                 the Guard figatree (submotion 38) sampled at frame x8 (angle+10)
                 by weight x4 (lb_8000C868: lerp T/S, slerp R).
  ftCo_80091D58  shield bone (parts[ft_data->x8->x11]) scale = inlineB0().
"""
import math
import re

import numpy as np

from stage_bake import FighterNumericDat, skeleton, skeleton_at, fighter_value
from vault.echo.subactions import FighterDat
from tools.native_rig.fobj_reader import read_figatree

CODES = 'Mr Fx Ca Dk Kb Kp Lk Sk Ns Pe Pp Nn Pk Ss Ys Pr Mt Lg Ms Zd Cl Dr Fc Pc Gw Gn Fe'.split()
SM_GUARDON, SM_GUARD, SM_GUARDDAMAGE = 37, 38, 40
CH_IX = {1: 0, 2: 1, 3: 2, 8: 3, 9: 4, 10: 5, 5: 6, 6: 7, 7: 8}   # FOBJ type -> [rx ry rz sx sy sz tx ty tz]


# ---------------------------------------------------------------- math
def euler_to_quat(r):
    """HSD EulerToQuat for R = Rz*Ry*Rx (HSD_MkRotationMtx order). Returns (x, y, z, w)."""
    cx, cy, cz = (math.cos(a / 2) for a in r)
    sx, sy, sz = (math.sin(a / 2) for a in r)
    return np.array([sx * cy * cz - cx * sy * sz,
                     cx * sy * cz + sx * cy * sz,
                     cx * cy * sz - sx * sy * cz,
                     cx * cy * cz + sx * sy * sz])


def quat_mat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def euler_mat(r):
    rx, ry, rz = r
    cx, cy, cz = math.cos(rx), math.cos(ry), math.cos(rz)
    sx, sy, sz = math.sin(rx), math.sin(ry), math.sin(rz)
    return np.array([[cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
                     [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
                     [-sy, cy * sx, cy * cx]])


def slerp(q1, q2, t):
    """HSD_QuatLib_8037EF28 (after lb_8000C868's hemisphere flip)."""
    if np.sum((q1 - q2) ** 2) > np.sum((q1 + q2) ** 2):
        q2 = -q2
    d = float(np.clip(q1 @ q2, -1, 1))
    ang = math.acos(d)
    if ang < 1e-6:
        return q1 * (1 - t) + q2 * t
    return (q1 * math.sin((1 - t) * ang) + q2 * math.sin(t * ang)) / math.sin(ang)


class SRT:
    """One joint's local transform: euler (or quaternion) rotation, scale, translation."""
    __slots__ = ('r', 'q', 's', 't')

    def __init__(self, v=None, q=None):
        if v is not None:
            self.r = list(v[0:3]); self.s = list(v[3:6]); self.t = list(v[6:9])
        self.q = q

    def copy(self):
        o = SRT(); o.r = self.r[:]; o.s = self.s[:]; o.t = self.t[:]; o.q = None if self.q is None else self.q.copy()
        return o

    def quat(self):
        return self.q if self.q is not None else euler_to_quat(self.r)

    def matrix(self):
        m = np.eye(4)
        m[:3, :3] = (quat_mat(self.q) if self.q is not None else euler_mat(self.r)) * np.array(self.s)[None, :]
        m[:3, 3] = self.t
        return m


def blend(a, b, w_a, w_b):
    """lb_8000C868 / lb_8000C490: out.T/S = a*w_a + b*w_b; rotation = slerp(a, b, w_b)."""
    o = SRT()
    o.t = [x * w_a + y * w_b for x, y in zip(a.t, b.t)]
    o.s = [x * w_a + y * w_b for x, y in zip(a.s, b.s)]
    if a.q is None and b.q is None and all(abs(x - y) <= 1e-4 for x, y in zip(a.r, b.r)):
        o.r = a.r[:]; o.q = None
        return o
    o.r = None
    o.q = slerp(a.quat(), b.quat(), w_b)
    return o


def fk(parents, srts):
    mats = []
    for i, p in enumerate(parents):
        m = srts[i].matrix()
        mats.append(m if p < 0 else mats[p] @ m)
    return mats


# ---------------------------------------------------------------- data
class CommonData:
    """PlCo.dat ftLoadCommonData pData[0] = ftCommonData (p_ftCommonData)."""

    def __init__(self, d):
        plco = FighterNumericDat(d.file('PlCo.dat'))
        self.base = plco.u(plco.roots['ftLoadCommonData'])
        self.plco = plco

    def f(self, off):
        return self.plco.f(self.base + off)


class Fighter:
    def __init__(self, d, cid, plco=None):
        self.cid = cid
        code = CODES[cid]
        self.code = code
        raw = d.file(f'Pl{code}.dat')
        self.fd = FighterDat(raw)
        self.raw = FighterNumericDat(raw)
        r = self.fd.ft_root
        attrs = self.raw.u(r)
        self.model_scale = self.raw.f(attrs + 0x8C)
        self.shield_size = self.raw.f(attrs + 0x90)
        x8 = self.raw.u(r + 8)
        self.shield_part = self.raw.d[x8 + 0x11]
        # asm 80091F38..44: lwz r5,0x20(ft_data); lwz r5,0(r5); lwz r5,8(r5)
        # -> (*ft_data->x20)->child: the ShieldPose HSD_Joint tree from TransN down.
        x20 = self.raw.u(r + 0x20)
        self.pose_top = self.raw.u(x20) if x20 else 0        # Yoshi: x20 struct is zeroed (egg, no tilt)
        if self.pose_top:
            self.pose_root = self.raw.u(self.pose_top + 8)
            self.pose_nodes = skeleton_at(self.raw, self.pose_root)
        else:
            self.pose_root, self.pose_nodes = 0, []
        model = f'Pl{code}Nr.dat'
        if model not in d.entries:
            model = next(n for n in sorted(d.entries) if re.fullmatch(f'Pl{code}[A-Z][a-z].dat', n))
        self.nodes = skeleton(d.file(model))
        self.parents = [p for p, _ in self.nodes]
        # part index -> costume node (holes from PlCo pData[5], as stage_bake)
        if plco is None:
            plco = FighterNumericDat(d.file('PlCo.dat'))
        missing_table = plco.u(plco.roots['ftLoadCommonData'] + 20)
        missing = plco.u(missing_table + cid * 4)
        holes = {plco.d[plco.u(missing) + 4 * i] for i in range(plco.u(missing + 4))} if missing else set()
        self.holes = holes
        self.part_node = {}
        node = part = 0
        while node < len(self.nodes):
            if part not in holes:
                self.part_node[part] = node
                node += 1
            part += 1
        self.node_part = {n: p for p, n in self.part_node.items()}
        self.aj = d.file(f'Pl{code}AJ.dat') if f'Pl{code}AJ.dat' in d.entries else b''
        # Nana: actions without animation bytes borrow Popo's (ftData_80085FD4 / 80086060)
        self.other = (FighterDat(d.file('PlPp.dat')), d.file('PlPpAJ.dat')) if cid == 11 else None
        self.flags_b4 = {1} if cid == 16 else set()       # ftMt_Init_OnLoad: TransN flags_b4
        self._anims = {}

    def anim(self, sm):
        if sm not in self._anims:
            a, aj = self.fd.actions[sm], self.aj
            if not a.anim_size and self.other:
                a, aj = self.other[0].actions[sm], self.other[1]
            if not a.anim_size:
                self._anims[sm] = None
            else:
                clip = FighterNumericDat(aj[a.anim_offset:a.anim_offset + a.anim_size])
                end, counts, tracks, *_ = read_figatree(clip.d, next(iter(clip.roots.values())))
                self._anims[sm] = (end, counts, tracks)
        return self._anims[sm]

    # --- poses (lists of SRT indexed by costume node) ---
    def rest(self):
        return [SRT(v) for _, v in self.nodes]

    def shield_pose_srts(self):
        """ft_data->x20->x8 HSD_Joint tree mapped onto costume nodes from TransN (part 1) on.
        Walk = ftAnim_8006FA58: parts in order, skipping holes."""
        out = {}
        part = 1
        for k, (_, v) in enumerate(self.pose_nodes):
            while part in self.holes:
                part += 1
            out[self.part_node[part]] = SRT(v)
            part += 1
        return out

    def anim_srts(self, sm, frame, base=None):
        """rest (or `base`) with the figatree channels at `frame` overriding."""
        end, counts, tracks = self.anim(sm)
        vals = [list(v) for _, v in self.nodes] if base is None else None
        srts = [SRT(v) for v in vals] if base is None else [b.copy() for b in base]
        for tr in tracks:
            if tr.type in CH_IX and tr.node < len(srts):
                ix = CH_IX[tr.type]
                val = fighter_value(tr.events, frame - tr.start)
                s = srts[tr.node]
                if ix < 3:
                    if s.q is not None:
                        raise ValueError('quat base')
                    s.r[ix] = val
                elif ix < 6:
                    s.s[ix - 3] = val
                else:
                    s.t[ix - 6] = val
        return srts

    def guard_pose(self, x8, x4):
        """ftCo_80091E78 with arg1 >= 1 (Guard): final local SRTs from TransN on.

        x4 == 0: joints = ShieldPose (8006FA58).
        x4 > 0 : jobj2 = rest pose (8006FB88) + Guard anim at frame x8 (AnimAll);
                 if x4 < 1: jobj2 = blend(ShieldPose, jobj2, 1-x4, x4) (80070108);
                 joints = jobj2 (8006FF74).
        The hold bone (x10) gets scale 1/model_scale in both paths (8007F6A4);
        it is never an ancestor of the shield bone (checked).
        """
        sp = self.shield_pose_srts()
        srts = self.rest()
        if x4 == 0:
            for n, s in sp.items():
                srts[n] = s.copy()
            return srts
        anim = self.anim_srts(SM_GUARD, x8)
        for n in range(1, len(srts)):
            srts[n] = anim[n]
        if x4 < 1:
            for n, s in sp.items():
                if self.node_part.get(n) in self.flags_b4:
                    srts[n] = s.copy()
                else:
                    srts[n] = blend(s, srts[n], 1 - x4, x4)
        return srts

    def shield_local(self, srts):
        """Shield bone centre in the TopN frame (TopN = identity), model units."""
        mats = fk(self.parents, srts)
        return mats[self.part_node[self.shield_part]], mats


def to_world(local_pos, model_scale, facing):
    """TopN: T(pos) * RotY(facing*pi/2) * S(model_scale) (ftPartSetRotY(fp,0,...),
    Fighter_UpdateModelScale). Returns (dx, dy, dz) relative to the fighter position."""
    x, y, z = local_pos
    return (facing * model_scale * z, model_scale * y, -facing * model_scale * x)
