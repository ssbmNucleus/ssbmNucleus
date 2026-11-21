"""Transfer explicit skeletal motion between landmark-mapped rigs.

Both imported and authored clips can use this path. Source times are explicit;
there is no video solver, root locking, hidden temporal fit, or foot planting.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .bvh_to_anim import write_anim
from .evaluation import Animation
from .provenance import capture_bundle, fingerprint
from .rigmap import Rig
from .smpl_to_anim import BONE_CHILD, min_rot, orthonormalize, to_hsd_euler, unwrap


def body_basis(rig):
    def p(name):
        return rig.pos[rig.landmarks[name]]
    lateral = p('l_hip') - p('r_hip')
    lateral /= np.linalg.norm(lateral)
    up = p('chest') - p('pelvis')
    up -= lateral * np.dot(up, lateral)
    up /= np.linalg.norm(up)
    basis = np.column_stack((lateral, up, np.cross(lateral, up)))
    if not np.isfinite(basis).all():
        raise ValueError('degenerate rest body basis')
    return basis


def leg_length(rig):
    lengths = []
    for side in ('l', 'r'):
        hip, knee, ankle = [rig.pos[rig.landmarks[side+'_'+n]] for n in ('hip','knee','ankle')]
        lengths.append(np.linalg.norm(knee-hip) + np.linalg.norm(ankle-knee))
    value = float(np.mean(lengths))
    if value < 1e-8:
        raise ValueError('degenerate rest leg length')
    return value


def transfer(source_anim, source_rig, target_rig, out, source_times=None,
             attachments=(), basis=None, scale=None, align_bones=True,
             body_scale='reject', root_motion_joint=None, engine_root=None):
    """Attachment entries name source/target joints and their hand anchors.

    Body joint rotations transfer in world space with a rest-pose correction.
    Target bone lengths remain fixed. Pelvis displacement and animated offsets
    of attachments transfer with the leg-length scale. Attachment rest grips
    remain those of the target model.
    """
    source, target, animation = Rig(source_rig), Rig(target_rig), Animation(source_anim)
    if body_scale not in ('reject', 'rigid'):
        raise ValueError('body_scale must be reject or rigid')
    attachments = list(attachments)
    out = Path(out)
    if out.exists():
        raise ValueError('choose a new output animation to preserve previous transfers')
    times = [float(t) for t in source_times] if source_times is not None else animation.times()
    if not times or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        raise ValueError('source times must be finite and strictly increasing')
    if any(t < animation.start or t > animation.end for t in times):
        raise ValueError('source time outside the animation interval')
    B = body_basis(target) @ body_basis(source).T if basis is None else np.asarray(basis, float)
    if B.shape != (3,3) or not np.allclose(B.T@B, np.eye(3), atol=1e-5) or not np.isclose(np.linalg.det(B),1):
        raise ValueError('basis must be a proper rotation')
    unit_scale = leg_length(target)/leg_length(source) if scale is None else float(scale)
    if not np.isfinite(unit_scale) or unit_scale <= 0:
        raise ValueError('scale must be positive and finite')
    common = sorted(set(source.landmarks) & set(target.landmarks))
    if 'pelvis' not in common:
        raise ValueError('both rigs require a pelvis landmark')
    mapping = {target.landmarks[lm]: source.landmarks[lm] for lm in common}
    if len(mapping) != len(common):
        raise ValueError('target landmarks must map to distinct joints')
    for j in mapping:
        m = target.world[j][:3,:3]
        if not np.allclose(m.T@m,np.eye(3),atol=1e-5) or np.linalg.det(m) < 0:
            raise ValueError(f'target body scale requires an explicit policy: {j}')
    attachment_map = {}
    for a in attachments:
        for key, rig in (('source',source),('source_anchor',source),('target',target),('target_anchor',target)):
            if a.get(key) not in rig.order:
                raise ValueError(f'invalid attachment {key}')
        j = a['target']
        if a.get('carry'):
            # the weapon is in another hand than the one its joint hangs from: any anchor solved before it will do
            if a['carry'] not in source.order or target.order.index(a['target_anchor']) >= target.order.index(j):
                raise ValueError('a carried attachment needs a known source bone and an anchor that comes before its target')
        elif a['target_anchor'] not in target._ancestors(j):
            raise ValueError('attachment target must be a descendant of its target anchor')
        if j in mapping or j in attachment_map or a['target_anchor'] == j:
            raise ValueError('attachment target must be a unique descendant of its target anchor')
        attachment_map[j] = a
    source_rest = {j: orthonormalize(w[:3,:3]) for j,w in source.world.items()}
    target_rest = {j: orthonormalize(w[:3,:3]) for j,w in target.world.items()}
    corrections = {j: np.eye(3) for j in mapping}
    if align_bones:
        for lm, child in BONE_CHILD.items():
            if lm in common and child in common:
                sj,sc,tj,tc = source.landmarks[lm],source.landmarks[child],target.landmarks[lm],target.landmarks[child]
                a,b = target.pos[tc]-target.pos[tj], B@(source.pos[sc]-source.pos[sj])
                if min(np.linalg.norm(a),np.linalg.norm(b)) > 1e-8:
                    corrections[tj] = min_rot(a,b)
    pelvis_s, pelvis_t = source.landmarks['pelvis'], target.landmarks['pelvis']
    if root_motion_joint is not None and (root_motion_joint == pelvis_s or
            root_motion_joint not in source._ancestors(pelvis_s)):
        raise ValueError('root motion joint must be a strict ancestor of pelvis')
    if engine_root is not None:
        j=engine_root.get('target')
        engine_basis=np.asarray(engine_root.get('basis'),float)
        if (root_motion_joint is None or j not in target._ancestors(pelvis_t)
                or j in mapping or j in attachment_map):
            raise ValueError('engine root needs removed source motion and an unmapped target ancestor')
        if (engine_basis.shape!=(3,3) or not np.allclose(engine_basis.T@engine_basis,np.eye(3),atol=1e-5)
                or not np.isclose(np.linalg.det(engine_basis),1)):
            raise ValueError('engine root basis must be a proper rotation')
    channels, previous, discarded_scale = {}, {}, {}
    for frame, time in enumerate(times):
        sw, tw = animation.world(source,time), {}
        trajectory = (sw[root_motion_joint][:3,3]-source.pos[root_motion_joint]
                      if root_motion_joint is not None else np.zeros(3))
        sr = {j: orthonormalize(w[:3,:3]) for j,w in sw.items()}
        for j in target.order:
            parent = tw[target.parent[j]] if target.parent[j] else np.eye(4)
            world = parent @ target.local[j]
            if j in mapping:
                sj = mapping[j]
                matrix = sw[sj][:3,:3]
                singular = np.linalg.svd(matrix, compute_uv=False)
                if np.linalg.det(matrix) <= 0 or singular.min() < 1e-6:
                    raise ValueError(f'animated body reflection or singular transform: {sj}')
                if not np.allclose(matrix.T@matrix, np.eye(3), atol=1e-4):
                    if body_scale == 'reject':
                        raise ValueError(f'animated body scale requires an explicit policy: {sj}')
                    bounds = discarded_scale.setdefault(sj, [1.0, 1.0])
                    bounds[0] = min(bounds[0], float(singular.min()))
                    bounds[1] = max(bounds[1], float(singular.max()))
                world[:3,:3] = B @ sr[sj] @ source_rest[sj].T @ B.T @ corrections[j] @ target_rest[j]
            if j == pelvis_t:
                world[:3,3] = target.pos[j] + unit_scale * B @ (sw[pelvis_s][:3,3]-source.pos[pelvis_s]-trajectory)
            if j in attachment_map:
                a = attachment_map[j]
                sj,sa,ta = a['source'],a['source_anchor'],a['target_anchor']
                delta = sr[sa] @ source_rest[sa].T
                residual = sw[sj][:3,3]-sw[sa][:3,3] - delta@(source.pos[sj]-source.pos[sa])
                world[:3,3] = tw[ta][:3,3] + B@delta@B.T@(target.pos[j]-target.pos[ta]) + unit_scale*B@residual
                world[:3,:3] = B@sr[sj]@source_rest[sj].T@B.T@target_rest[j]
                if a.get('carry'):
                    # placed from the hand that holds it, and turned as the weapon's model was built (against `carry`)
                    world[:3,3] = tw[ta][:3,3] + unit_scale*B@(sw[sj][:3,3]-sw[sa][:3,3])
                    world[:3,:3] = B@sr[sj]@source_rest[a['carry']].T@B.T@target_rest[j]
            tw[j] = world
            if j not in mapping and j not in attachment_map:
                continue
            local = np.linalg.solve(parent,world)
            angles = to_hsd_euler(orthonormalize(local[:3,:3]))
            if j in previous:
                angles = tuple(unwrap(p,v) for p,v in zip(previous[j],angles))
            previous[j] = angles
            ch = channels.setdefault(j,{})
            for axis,value in zip('XYZ',angles):
                ch.setdefault('rotate'+axis,{})[frame] = value
            if j == pelvis_t or j in attachment_map:
                for axis,value in zip('XYZ',local[:3,3]):
                    ch.setdefault('translate'+axis,{})[frame] = float(value)
        if engine_root is not None:
            # Melee consumes TransN translation into fighter physics and clears
            # the joint before drawing. Keep it outside the body FK solve, so
            # the trajectory is neither canceled in the hips nor applied twice.
            ch=channels.setdefault(engine_root['target'],{})
            # Source-to-engine axes are explicit. Anatomical alignment B may
            # pitch the chest several degrees; applying that to floor travel
            # would turn a horizontal step into vertical motion.
            values=engine_basis@(unit_scale*trajectory)
            for axis,value in zip('XYZ',values):
                ch.setdefault('translate'+axis,{})[frame]=float(value)
    out.parent.mkdir(parents=True,exist_ok=True)
    write_anim(out,len(times)-1,channels,target.order)
    report = {'schema':1,'source':fingerprint(Path(source_anim)), 'source_rig':fingerprint(Path(source_rig)),
              'target_rig':fingerprint(Path(target_rig)), 'output':fingerprint(out),
              'source_times':times,'basis':B.tolist(),'scale':unit_scale,'align_bones':align_bones,
              'body_scale_policy':body_scale,'discarded_world_scale_ranges':discarded_scale,
              'landmarks':common,'attachments':list(attachments),
              'root_motion_removed_from':root_motion_joint,
              'engine_root':engine_root,
              'policy':'world rotations; target rest bone lengths and grips; pelvis and attachment displacement; no planting',
              'limits':'Mapped body and attachment joints only; no weapon articulation, visibility, physics, scripts or quality grade.',
              'code':fingerprint(Path(__file__))}
    report_path = out.with_suffix('.retarget.json')
    report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    files = {'source_animation':Path(source_anim), 'source_rig':Path(source_rig),
             'animation':out, 'rig':Path(target_rig), 'retarget':report_path}
    for name in ('retarget','evaluation','rigmap','smpl_to_anim','bvh_to_anim'):
        files['code_'+name] = Path(__file__).with_name(name+'.py')
    manifest = capture_bundle(out, files, {'solver':'skeletal-transfer',
        'rig_name':Path(target_rig).stem,'clip':out.stem,'source_times':times,
        'timing_note':'Explicit source samples; game script motion rates and cancellation are separate.'})
    return {**report, 'manifest':str(manifest)}


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source_anim')
    ap.add_argument('source_rig')
    ap.add_argument('target_rig')
    ap.add_argument('--out', required=True)
    ap.add_argument('--source-times', help='JSON array of source sample times; output frames are 0..N-1')
    ap.add_argument('--attachments', help='JSON list of source/target joints and hand anchors')
    ap.add_argument('--basis', help='JSON 3x3 source-to-target rotation; default: rest body axes')
    ap.add_argument('--scale', type=float, help='displacement scale; default: rest leg length ratio')
    ap.add_argument('--no-align-bones', action='store_true')
    ap.add_argument('--body-scale', choices=('reject','rigid'), default='reject',
                    help='rigid explicitly discards positive source stretch and keeps target bone lengths')
    args = ap.parse_args()
    def read(path, default):
        return json.loads(Path(path).read_text(encoding='utf-8')) if path else default
    result = transfer(args.source_anim,args.source_rig,args.target_rig,args.out,
        source_times=read(args.source_times,None),attachments=read(args.attachments,()),
        basis=read(args.basis,None),scale=args.scale,align_bones=not args.no_align_bones,
        body_scale=args.body_scale)
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
