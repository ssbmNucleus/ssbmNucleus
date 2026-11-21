"""Bake editable pose/timing recipes and two-bone contacts to ordinary .anim.

Recipes can start from rig rest or an existing animation. No video, solver or
original-game file is required. Angles in recipes are degrees; positions are
rig units. Outputs retain the usual frozen provenance and install interface.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .bvh_to_anim import write_anim
from .evaluation import Animation
from .provenance import capture_bundle, fingerprint
from .rigmap import Rig, euler_xyz
from .smpl_to_anim import min_rot, orthonormalize, quats, quat_to_mat, to_hsd_euler, unwrap


def _world(rig, local):
    result = {}
    for j in rig.order:
        p = rig.parent[j]
        result[j] = result[p] @ local[j] if p else local[j].copy()
    return result


def _keys(values, frames, dimensions):
    a = np.asarray(values, dtype=float)
    if (a.ndim != 2 or a.shape[1] != dimensions+1 or len(a) == 0
            or not np.isfinite(a).all() or np.any(np.diff(a[:,0]) <= 0)
            or a[0,0] < 0 or a[-1,0] > frames-1):
        raise ValueError('keys require ordered, finite [frame, values...] within the output interval')
    if len(a) > 1 and (a[0,0] != 0 or a[-1,0] != frames-1):
        raise ValueError('animated keys must include output endpoints; a single key is constant')
    return a


def _sample(keys, frame, smooth=False, rotation=False):
    i = max(0, min(int(np.searchsorted(keys[:,0],frame,side='right'))-1,len(keys)-1))
    a, b = keys[i], keys[min(i+1,len(keys)-1)]
    u = (frame-a[0])/(b[0]-a[0]) if b[0] != a[0] else 0.0
    u = float(np.clip(u,0,1))
    if smooth:
        u = u*u*(3-2*u)
    if not rotation:
        return a[1:] + u*(b[1:]-a[1:])
    q0,q1 = quats(np.array([euler_xyz(np.deg2rad(a[1:])),euler_xyz(np.deg2rad(b[1:]))]))
    dot = float(np.clip(np.dot(q0,q1),-1,1))
    if dot > .9995:
        q = (1-u)*q0 + u*q1
    else:
        angle = np.arccos(dot)
        q = (np.sin((1-u)*angle)*q0 + np.sin(u*angle)*q1)/np.sin(angle)
    return quat_to_mat(q/np.linalg.norm(q))


def _joint(rig, name):
    j = name[6:] if name.startswith('joint:') else rig.landmarks.get(name,name)
    if j not in rig.order:
        raise ValueError(f'unknown joint or landmark: {name}')
    return j


def _set_world_rotation(rig, local, j, rotation):
    w = _world(rig,local)
    p = rig.parent[j]
    parent_r = orthonormalize(w[p][:3,:3]) if p else np.eye(3)
    local[j][:3,:3] = parent_r.T @ rotation


def two_bone(rig, local, chain, goal, pole=None):
    """Preserve segment lengths and end orientation; return reach residual.

    Intermediate helper joints are permitted. The pole is a point in rig world
    coordinates. Without a pole, retain the posed knee/elbow bend plane.
    """
    a,b,c = chain
    w = _world(rig,local)
    if any(not np.allclose(m[:3,:3].T@m[:3,:3],np.eye(3),atol=1e-5) for m in w.values()):
        raise ValueError('two-bone constraints require an unscaled, rigid hierarchy')
    pa,pb,pc = [w[j][:3,3].copy() for j in chain]
    end_rotation = w[c][:3,:3].copy()
    l1,l2 = np.linalg.norm(pb-pa),np.linalg.norm(pc-pb)
    if min(l1,l2) < 1e-7:
        raise ValueError('two-bone chain has a zero-length segment')
    vector = np.asarray(goal)-pa
    distance = float(np.linalg.norm(vector))
    if distance < 1e-7:
        raise ValueError('two-bone goal coincides with the chain root')
    axis = vector/distance
    d = float(np.clip(distance,abs(l1-l2)+1e-7,l1+l2-1e-7))
    bend = (np.asarray(pole)-pa) if pole is not None else pb-pa
    bend -= axis*np.dot(bend,axis)
    if np.linalg.norm(bend) < 1e-7:
        seed = np.eye(3)[np.argmin(np.abs(axis))]
        bend = seed-axis*np.dot(seed,axis)
    bend /= np.linalg.norm(bend)
    along = (l1*l1-l2*l2+d*d)/(2*d)
    middle = pa + along*axis + np.sqrt(max(0,l1*l1-along*along))*bend
    _set_world_rotation(rig,local,a,min_rot(pb-pa,middle-pa)@w[a][:3,:3])
    w = _world(rig,local)
    _set_world_rotation(rig,local,b,min_rot(w[c][:3,3]-w[b][:3,3],pa+d*axis-w[b][:3,3])@w[b][:3,:3])
    _set_world_rotation(rig,local,c,end_rotation)
    return float(np.linalg.norm(_world(rig,local)[c][:3,3]-goal))


def bake(recipe_path, rig_path, out):
    recipe_path, out = Path(recipe_path), Path(out)
    spec = json.loads(recipe_path.read_text(encoding='utf-8'))
    allowed = {'schema','name','frames','base','time_keys','controls','contacts'}
    if set(spec)-allowed or spec.get('schema') != 1:
        raise ValueError('unknown recipe fields or unsupported schema')
    frames = spec.get('frames')
    if isinstance(frames,bool) or not isinstance(frames,int) or not 1 <= frames <= 10000:
        raise ValueError('frames must be an integer from 1 to 10000')
    if out.exists():
        raise ValueError('choose a new output animation to preserve previous recipes')
    rig = Rig(rig_path)
    base_path = (recipe_path.parent/spec['base']).resolve() if spec.get('base') else None
    base = Animation(base_path) if base_path else None
    times = np.arange(frames,dtype=float)
    if spec.get('time_keys') is not None:
        if base is None:
            raise ValueError('time_keys require a base animation')
        keys = _keys(spec['time_keys'],frames,1)
        if np.any(np.diff(keys[:,1]) < 0):
            raise ValueError('base time must not run backwards; holds are allowed')
        times = np.array([_sample(keys,f)[0] for f in range(frames)])
    if base and (times.min() < base.start or times.max() > base.end):
        raise ValueError('base sample outside animation; provide explicit time_keys')
    controls, seen = [], set()
    for control in spec.get('controls',[]):
        if set(control)-{'joint','rotation_delta_deg','translation_delta','interpolation'}:
            raise ValueError('unknown control fields')
        j = _joint(rig,control['joint'])
        if j in seen:
            raise ValueError('combine controls for the same joint into one entry')
        seen.add(j)
        interpolation = control.get('interpolation','smooth')
        if interpolation not in ('linear','smooth'):
            raise ValueError('interpolation must be linear or smooth')
        curves = {k:_keys(control[k],frames,3) for k in ('rotation_delta_deg','translation_delta') if k in control}
        if not curves:
            raise ValueError('control needs rotation_delta_deg or translation_delta')
        controls.append((j,interpolation == 'smooth',curves))
    poses = []
    for f,t in enumerate(times):
        w = base.world(rig,float(t)) if base else rig.world
        local = {j:np.linalg.solve(w[rig.parent[j]],w[j]) if rig.parent[j] else w[j].copy() for j in rig.order}
        for j,m in local.items():
            scales = np.linalg.norm(m[:3,:3],axis=0)
            if np.any(scales < 1e-8):
                raise ValueError(f'zero scale requires an explicit policy: {j}')
            rotation = m[:3,:3]/scales
            if not np.allclose(rotation.T@rotation,np.eye(3),atol=1e-5) or np.linalg.det(rotation) < 0:
                raise ValueError(f'shear or reflected scale requires an explicit policy: {j}')
        for j,smooth,curves in controls:
            if 'rotation_delta_deg' in curves:
                scales = np.linalg.norm(local[j][:3,:3],axis=0)
                rotation = orthonormalize(local[j][:3,:3])
                local[j][:3,:3] = (rotation@_sample(curves['rotation_delta_deg'],f,smooth,True))*scales
            if 'translation_delta' in curves:
                local[j][:3,3] += _sample(curves['translation_delta'],f,smooth)
        poses.append(local)
    contacts, touched = [], set()
    for contact in spec.get('contacts',[]):
        if set(contact)-{'chain','frames','anchor_frame','target','pole','allow_unreachable'}:
            raise ValueError('unknown contact fields')
        chain = [_joint(rig,n) for n in contact['chain']]
        if (len(chain) != 3 or len(set(chain)) != 3 or chain[0] not in rig._ancestors(chain[1])
                or chain[1] not in rig._ancestors(chain[2])):
            raise ValueError('contact chain must be ordered root, middle, end descendants')
        interval = contact.get('frames',[0,frames-1])
        if (len(interval) != 2 or any(type(f) is not int for f in interval)
                or not 0 <= interval[0] <= interval[1] < frames):
            raise ValueError('contact frames require an inclusive integer interval')
        # Reject interacting chains: solving one could silently undo another.
        if any(a in rig._ancestors(b) or b in rig._ancestors(a) for a in chain for b in touched):
            raise ValueError('contact chains must have independent branches')
        touched.update(chain)
        if ('anchor_frame' in contact) == ('target' in contact):
            raise ValueError('contact needs exactly one anchor_frame or target')
        if 'anchor_frame' in contact:
            anchor = contact['anchor_frame']
            if type(anchor) is not int or not 0 <= anchor < frames:
                raise ValueError('invalid contact anchor_frame')
            goal = _world(rig,poses[anchor])[chain[2]][:3,3].copy()
        else:
            goal = np.asarray(contact['target'],float)
        pole = np.asarray(contact['pole'],float) if 'pole' in contact else None
        if goal.shape != (3,) or not np.isfinite(goal).all() or (pole is not None and (pole.shape != (3,) or not np.isfinite(pole).all())):
            raise ValueError('contact target/pole must be finite world-space points')
        residuals = [two_bone(rig,poses[f],chain,goal,pole) for f in range(interval[0],interval[1]+1)]
        if max(residuals) > .001 and not contact.get('allow_unreachable',False):
            raise ValueError(f'unreachable contact {chain}: maximum residual {max(residuals):.6f} rig units')
        contacts.append({'chain':chain,'frames':interval,'target':goal.tolist(),'residuals':residuals})
    # Preserve sparsity: unkeyed engine roots keep their runtime facing and
    # unkeyed rest translations avoid needless game-bank quantization.
    keyed = {j:set(ch) for j,ch in base.channels.items()} if base else {}
    for j,_,curves in controls:
        for field,kind in (('rotation_delta_deg','rotate'),('translation_delta','translate')):
            if field in curves:
                keyed.setdefault(j,set()).update(kind+axis for axis in 'XYZ')
    for contact in contacts:
        for j in contact['chain']:
            keyed.setdefault(j,set()).update('rotate'+axis for axis in 'XYZ')
    for names in keyed.values():
        if any(k.startswith('rotate') for k in names):
            names.update('rotate'+axis for axis in 'XYZ')
    channels, previous = {}, {}
    for f,local in enumerate(poses):
        for j,m in local.items():
            if j not in keyed:
                continue
            angles = to_hsd_euler(orthonormalize(m[:3,:3]))
            if j in previous:
                angles = tuple(unwrap(p,v) for p,v in zip(previous[j],angles))
            previous[j] = angles
            ch = channels.setdefault(j,{})
            for kind,values in (('rotate',angles),('translate',m[:3,3]),('scale',np.linalg.norm(m[:3,:3],axis=0))):
                for axis,value in zip('XYZ',values):
                    if kind+axis in keyed[j]:
                        ch.setdefault(kind+axis,{})[f] = float(value)
    out.parent.mkdir(parents=True,exist_ok=True)
    write_anim(out,frames-1,channels,rig.order)
    report = {'schema':1,'recipe':fingerprint(recipe_path),'rig':fingerprint(rig_path),
        'animation':fingerprint(out),'base':fingerprint(base_path) if base_path else None,
        'base_times':times.tolist() if base else None,'contacts':contacts,
        'limits':'Pose/timing authoring only; no hitboxes, physics, collision avoidance or automatic quality grade.'}
    report_path = out.with_suffix('.author.json')
    report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    files = {'recipe':recipe_path,'rig':Path(rig_path),'animation':out,'author_report':report_path}
    # A base-free clip uses its authored result as the review source, clearly
    # labelled below; this is a preview, not an independent reference.
    files.update(source_animation=base_path or out,source_rig=Path(rig_path))
    for name in ('author','evaluation','rigmap','smpl_to_anim','bvh_to_anim'):
        files['code_'+name] = Path(__file__).with_name(name+'.py')
    manifest = capture_bundle(out,files,{'solver':'recipe','rig_name':Path(rig_path).stem,
        'clip':spec.get('name',out.stem),'source_times':times.tolist(),
        'source_label':'Base skeleton' if base else 'Authored skeleton (self-preview)',
        'allow_source_holds':True})
    return {**report,'manifest':str(manifest)}


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('recipe'); ap.add_argument('rig'); ap.add_argument('--out',required=True)
    a = ap.parse_args()
    print(json.dumps(bake(a.recipe,a.rig,a.out),indent=2))


if __name__ == '__main__':
    main()
