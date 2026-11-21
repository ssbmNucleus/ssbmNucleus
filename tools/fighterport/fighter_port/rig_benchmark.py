"""Reusable source-hierarchy SRT authoring and full-domain geometry measurement.

The caller supplies independent reference worlds, a strict encoder/readback and
explicit skin/bind data. No donor indices, anatomy guesses, or pilot imports.
"""
from __future__ import annotations

import numpy as np

from .evaluation import Animation, Key
from .rigmap import euler_xyz
from .scalar_curves import reduce_track
from .smpl_to_anim import unwrap, orthonormalize

TYPES = {1:'rotateX', 2:'rotateY', 3:'rotateZ', 5:'translateX', 6:'translateY', 7:'translateZ',
         8:'scaleX', 9:'scaleY', 10:'scaleZ'}


def frame_grid(end, subdivisions=32):
    if type(end) is not int or end <= 0 or type(subdivisions) is not int or subdivisions <= 0:
        raise ValueError('Positive integer end and subdivisions required')
    return np.arange(end * subdivisions + 1, dtype=float) / subdivisions


def rotation_angles(rotation):
    """Extract XYZ angles without snapping a near-pole rotation onto the pole.

    atan2 retains the small cosine that asin loses near +/-pi/2. Only an
    effectively exact pole uses the combined X rotation with Z set to zero.
    """
    cosine = np.hypot(rotation[0, 0], rotation[1, 0])
    y = np.arctan2(-rotation[2, 0], cosine)
    if cosine > 1e-12:
        return np.array([np.arctan2(rotation[2, 1], rotation[2, 2]), y,
                         np.arctan2(rotation[1, 0], rotation[0, 0])])
    return np.array([np.arctan2(-rotation[1, 2], rotation[1, 1]), y, 0.])


def local_vectors(rig, worlds, *, project_shear=False):
    """Keep every source parent; refuse shear/reflection instead of discarding it."""
    result = {j: [] for j in rig.order}
    previous = {}
    for world in worlds:
        if set(world) != set(rig.order):
            raise ValueError('World joint domain mismatch')
        for j in rig.order:
            p = rig.parent[j]
            local = np.linalg.solve(world[p], world[j]) if p is not None else world[j]
            if local.shape != (4,4) or not np.isfinite(local).all() or not np.allclose(local[3], [0,0,0,1], rtol=0, atol=1e-9):
                raise ValueError('Invalid local transform')
            scale = np.linalg.norm(local[:3,:3], axis=0)
            if np.any(scale < 1e-10):
                raise ValueError('Singular local scale')
            rotation = local[:3,:3] / scale
            if not np.allclose(rotation.T @ rotation, np.eye(3), rtol=0, atol=1e-7) or np.linalg.det(rotation) < 0:
                if not project_shear:
                    raise ValueError(f'Local SRT cannot represent shear/reflection at {j}')
                rotation = orthonormalize(local[:3,:3])
            base = rotation_angles(rotation)
            choices = (base, np.array([base[0]+np.pi, np.pi-base[1], base[2]+np.pi]))
            if j in previous:
                choices = [np.array([unwrap(p,v) for p,v in zip(previous[j], c)]) for c in choices]
                angles = min(choices, key=lambda c: np.max(np.abs(c-previous[j])))
            else:
                angles = base
            if not np.allclose(euler_xyz(angles), rotation, rtol=0, atol=1e-7):
                raise ValueError('Euler branch lost matrix equivalence')
            previous[j] = angles
            result[j].append(np.r_[angles, local[:3,3], scale])
    return {j: np.asarray(v) for j,v in result.items()}


def author(rig, times, worlds, tau, *, project_shear=False):
    if tau <= 0 or not np.isfinite(tau):
        raise ValueError('Positive finite scalar tolerance required')
    vectors = local_vectors(rig, worlds, project_shear=project_shear)
    ints = [i for i,t in enumerate(times) if float(t).is_integer()]
    if len(worlds) != len(times) or len(ints) < 2 or not np.array_equal(np.asarray(times)[ints], np.arange(int(times[-1])+1)):
        raise ValueError('Complete integer frame domain required')
    channels = {}
    for j in rig.order:
        rest = np.r_[rig.rest[j]['r'], rig.rest[j]['t'], rig.rest[j]['s']]
        for col, typ in enumerate(TYPES):
            values = vectors[j][:,col]
            # Only omit exact bind constants; no scalar threshold can certify
            # the accumulated world error of omitted tracks.
            if np.max(np.abs(values-rest[col])) <= 1e-10:
                continue
            tolerance = tau if typ in (1,2,3) else (tau*2 if typ in (5,6,7) else 5e-5)
            channels[(j,typ)] = reduce_track(np.asarray(times), values, ints, tolerance)
    return channels


def animation(channels, end):
    value = object.__new__(Animation)
    value.start, value.end, value.path, value.channels = 0., float(end), None, {}
    for (j,typ), keys in channels.items():
        value.channels.setdefault(j,{})[TYPES[typ]] = keys
    return value


def codec_spec(rig, channels, end, symbol):
    indices = {j:i for i,j in enumerate(rig.order)}
    return dict(symbol=symbol, end=end, nodes=len(rig.order), channels=[
        dict(joint=indices[j], type=typ, keys=[vars(k) for k in keys]) for (j,typ),keys in channels.items()])


def packed_animation(raw, order):
    """Bind audited FOBJ indices to an explicit ordered rig; no JOBJ name guess.

    Adjacent slope-only opcodes advance slope state, never the animation clock.
    Unlike the old pilot exporter, unknown names cannot silently drop channels.
    """
    if raw['nodes'] != len(order) or len(set(order)) != len(order):
        raise ValueError('Packed node domain differs from rig')
    channels = {}
    for ch in raw['channels']:
        index, typ = ch['joint'], ch['type']
        if type(index) is not int or not 0 <= index < len(order) or typ not in TYPES:
            raise ValueError('Invalid packed channel identity')
        identity = (order[index],typ)
        if identity in channels:
            raise ValueError('Duplicate packed channel')
        keys=[]; d0=d1=0.; last=0
        for x in ch['keys']:
            op=x['op']
            if op not in (1,2,3,4,5,6) or not all(np.isfinite(x[k]) for k in ('frame','value','tan')):
                raise ValueError('Invalid packed opcode or number')
            if op==5:
                d0,d1=d1,x['tan'];last=op;continue
            if op in (3,4): d0,d1=d1,x['tan']
            elif last!=5: d0,d1=d1,0.
            if keys:
                old=keys[-1]
                if x['frame'] <= old.time:
                    raise ValueError('Packed value frames must increase')
                mode='step' if last in (1,6) else ('fixed' if last in (3,4,5) else 'linear')
                keys[-1]=Key(old.time,old.value,mode,old.in_slope,d0)
            keys.append(Key(x['frame'],x['value'],'linear',d1,0.));last=op
        if not keys:
            raise ValueError('Packed channel has no value keys')
        channels[identity]=keys
    return animation(channels,raw['end'])


class Skin:
    """Precompute bind-space weighted vertices once; retain every supplied weight."""
    def __init__(self, positions, weights, bind, *, weight_sum_tolerance=1e-4, inverse_bind=None):
        points = np.asarray(positions, dtype=float)
        if points.ndim != 2 or points.shape[1] != 3 or not len(points) or not np.isfinite(points).all():
            raise ValueError('Nonempty finite Nx3 positions required')
        self.count = len(points)
        self.positions = points.copy()
        self.parts = []
        totals = np.zeros(self.count)
        if inverse_bind is not None:
            if set(inverse_bind)!=set(bind):raise ValueError('Explicit inverse bind domain differs')
            for joint,matrix in inverse_bind.items():
                inv=np.asarray(matrix,dtype=float)
                world=np.asarray(bind[joint],dtype=float)
                if world.shape!=(4,4) or not np.isfinite(world).all() or not np.array_equal(world[3],[0.,0.,0.,1.]):
                    raise ValueError('Finite affine bind world required')
                if (inv.shape!=(4,4) or not np.isfinite(inv).all() or not np.array_equal(inv[3],[0.,0.,0.,1.]) or
                        np.max(np.abs(world@inv-np.eye(4)))>1e-4):
                    raise ValueError('Explicit stored inverse bind differs from bind world')
        for joint, (ids, amounts) in weights.items():
            ids = np.asarray(ids)
            amounts = np.asarray(amounts, dtype=float)
            if ids.dtype.kind not in 'iu' or len(ids) != len(amounts) or np.any(ids < 0) or np.any(ids >= self.count) or not np.isfinite(amounts).all() or np.any(amounts < 0):
                raise ValueError('Invalid skin weights')
            np.add.at(totals, ids, amounts)
            inv=np.linalg.inv(bind[joint]) if inverse_bind is None else np.asarray(inverse_bind[joint],dtype=float)
            local = np.c_[points[ids], np.ones(len(ids))] @ inv.T
            self.parts.append((joint, ids, amounts, local, len(np.unique(ids)) == len(ids)))
        if not 0 <= weight_sum_tolerance <= .001:
            raise ValueError('Weight sum tolerance must be explicit and at most .001')
        self.weight_sum_error = float(np.max(np.abs(totals-1.)))
        if not np.allclose(totals, 1., rtol=0, atol=weight_sum_tolerance):
            raise ValueError('Full skin weights must sum to one')

    def deform(self, world):
        result = np.zeros((self.count,3))
        for j,ids,weights,local,unique in self.parts:
            values = (local @ world[j].T)[:,:3] * weights[:,None]
            if unique:
                result[ids] += values
            else:
                np.add.at(result, ids, values)
        return result


def measure(rig, times, candidate, reference, skin=None):
    """Same frames and explicit domains, with worst witnesses retained."""
    worst = {k:dict(value=0., frame=None, joint=None) for k in ('pivot','basis','skin')}
    if not len(times):
        raise ValueError('Empty measurement domain')
    for f in times:
        a, b = candidate(float(f)), reference(float(f))
        if set(a) != set(rig.order) or set(b) != set(rig.order):
            raise ValueError('Measurement joint domain differs')
        for j in rig.order:
            if not np.isfinite(a[j]).all() or not np.isfinite(b[j]).all():
                raise ValueError('Nonfinite measured pose')
            for key, v in (('pivot',np.linalg.norm(a[j][:3,3]-b[j][:3,3])),
                           ('basis',np.max(np.abs(a[j][:3,:3]-b[j][:3,:3])))):
                if v > worst[key]['value']:
                    worst[key] = dict(value=float(v), frame=float(f), joint=j)
        if skin:
            distances = np.linalg.norm(skin.deform(a)-skin.deform(b),axis=1)
            i = int(np.argmax(distances))
            if distances[i] > worst['skin']['value']:
                worst['skin'] = dict(value=float(distances[i]),frame=float(f),vertex=i)
    return dict(samples=len(times), joints=len(rig.order), vertices=skin.count if skin else 0,
                metrics=worst, skin_status='MEASURED' if skin else 'UNMEASURED')


