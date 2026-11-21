"""Randall adapters for reusable preparation and failure diagnosis.

All character choices are explicit data. The animation adapter reuses the
source reader, chart expansion, codec audit and full geometry evaluator.
"""
import hashlib
import json
from pathlib import Path


OPERATIONS = ('plan_rig', 'source_visibility', 'costume_budget', 'animation_diagnose')


def pin(path):
    path = Path(path)
    payload = path.read_bytes()
    return dict(path=str(path.resolve()), sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload))


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def handle(args, log):
    op = args['op']
    if op == 'plan_rig':
        import ssbh_data_py as ssbh
        from .rig_dependencies import mesh_closure_plan
        paths = {key:args[key] for key in ('source_rig','source_mesh','selection')}
        result = mesh_closure_plan(read(paths['source_rig']), ssbh.mesh_data.read_mesh(str(paths['source_mesh'])),
                                  read(paths['selection']), consumers=args['consumers'],
                                  animated_joints=args.get('animated_joints',[]),
                                  unresolved_consumers=args.get('unresolved_consumers',[]))
        result['inputs'] = {key:pin(path) for key,path in paths.items()}
        return result
    if op == 'source_visibility':
        from .source_visibility import read_tracks, resolve
        tracks, primary = read_tracks(args['source_motion'],args['frame'])
        fallback, fallback_pin = None, None
        if args.get('fallback_motion'):
            if 'fallback_frame' not in args:raise ValueError('Explicit fallback_frame required with fallback_motion')
            fallback, fallback_pin = read_tracks(args['fallback_motion'],args['fallback_frame'])
        result = resolve(read(args['selection']),tracks,args['frame'],fallback_tracks=fallback,
                         fallback_frame=args.get('fallback_frame',0),defaults=args.get('visibility_defaults'))
        result['inputs'] = dict(primary=primary, fallback=fallback_pin, selection=pin(args['selection']),
                                defaults=args.get('visibility_defaults',{}))
        if args.get('costume'):
            from .compat.rig_inventory import costume_inventory
            topology=costume_inventory(Path(args['costume']).read_bytes(),args.get('joint_symbol'))
            mapping=args.get('dobj_map')
            if (not isinstance(mapping,list) or len(mapping)!=len(result['rows']) or len(set(mapping))!=len(mapping) or
                    any(type(i) is not int or not 0<=i<topology['dobj_descriptor_count'] for i in mapping)):
                raise ValueError('Explicit reviewed selection-row to serialized DObj mapping required')
            if result['unresolved_nodes']:raise ValueError('Cannot bind unresolved visibility')
            for row,dobj in zip(result['rows'],mapping):row['dobj']=dobj
            result.update(costume_sha256=topology['sha256'],hidden_dobjs=[r['dobj'] for r in result['rows'] if r['visible'] is False],
                          binding_scope='Caller-declared DObj correspondence on hash-bound costume; topology bounded, mesh correspondence requires separate readback evidence.')
        return result
    if op == 'costume_budget':
        from .costume_budget import measure
        result = measure(Path(args['costume']).read_bytes(),args.get('joint_symbol'))
        result['input'] = pin(args['costume'])
        return result
    if op == 'animation_diagnose':
        return diagnose(Path(args['recipe']),Path(args['out']),log)
    raise ValueError(f'Unknown preparation operation: {op}')


def source_target_worlds(raw, times, source_rig, scaled, charted, target_rig, wrappers):
    """Expand existing source charts and explicit identity engine wrappers."""
    import numpy as np
    from . import batch_evaluation as batch, rotation_charts, scale_helpers
    if set(source_rig.order)-set(raw.order):
        raise ValueError('Source subset includes unknown raw joints')
    if set(target_rig.order)-set(charted.order) != set(wrappers) or set(wrappers)&set(charted.order) or len(set(wrappers)) != len(wrappers):
        raise ValueError('Exact explicitly declared wrapper domain required')
    if set(charted.order)-set(target_rig.order):
        raise ValueError('Target omits source/chart joints')
    # Readback names alone do not prove the same parent or bind domain.
    for j in charted.order:
        p = target_rig.parent[j]
        while p in wrappers:
            p = target_rig.parent[p]
        if p != charted.parent[j] or not np.allclose(target_rig.world[j],charted.world[j],rtol=0,atol=1e-4):
            raise ValueError('Target parent or bind differs from declared source/chart recipe')
    for j in wrappers:
        if not np.allclose(target_rig.local[j],np.eye(4),rtol=0,atol=1e-7):
            raise ValueError('Only identity engine wrappers supported by source pose adapter')
    full = batch.raw_worlds(raw,times)
    compensated = {j for j in source_rig.order if j in raw.tracks and raw.tracks[j].compensate_scale and raw.parent[j] is not None}
    compensated &= set(scaled.helpers)
    parent_scales = {j:np.array([raw.parts(raw.parent[j],float(f))[2] if raw.parent[j] in raw.tracks else np.ones(3) for f in times]) for j in compensated}
    world = rotation_charts.expand_worlds(charted,scale_helpers.expand_worlds(
        scaled,{j:full[j] for j in source_rig.order},parent_scales,compensated))
    identity = np.broadcast_to(np.eye(4),(len(times),4,4)).copy()
    result = {}
    for j in target_rig.order:
        if j in world:
            result[j] = world[j]
        else:
            p = target_rig.parent[j]
            result[j] = identity.copy() if p is None else result[p].copy()
    return result


def diagnose(recipe_path, out, log):
    import numpy as np
    from . import native_port, rig_benchmark as bench, batch_evaluation as batch, rotation_charts
    from .animation_compression import _skin, _run
    from .animation_diagnostics import _limits
    from .workbench import stage_errors
    from .evaluation import Key
    from .rig_archive import read_skeleton
    from .rig_dependencies import validate_rig
    from .source_preflight import RawSource
    recipe_pin = pin(recipe_path)
    recipe = read(recipe_path)
    if recipe['schema'] != 'animation-diagnosis-input-v1':
        raise ValueError('Explicit animation-diagnosis-input-v1 recipe required')
    limits=dict(recipe['limits'])
    capacity=limits.pop('bytes',None)
    if capacity is not None and (type(capacity) is not int or capacity not in (32768,65504,131040)):
        raise ValueError('Unsupported clip capacity')
    _limits(limits)
    keys = ('source_rig','target_rig','source_skeleton','source_motion','costume','skin_smd','authored','packed','codec')
    paths = {k:(recipe_path.resolve().parent/recipe[k]).resolve() for k in keys}
    inputs = {k:pin(p) for k,p in paths.items()}
    if recipe.get('input_sha256') != {k:v['sha256'] for k,v in inputs.items()}:
        raise ValueError('Recipe input SHA-256 pins missing or changed')
    source_meta, target_meta = read(paths['source_rig']), read(paths['target_rig'])
    validate_rig(source_meta); validate_rig(target_meta)
    source_rig = native_port.rig_from_meta(source_meta)
    actual, inverse = read_skeleton(paths['costume'].read_bytes(),target_meta['order'])
    target = native_port.rig_from_meta(actual)
    expected = native_port.rig_from_meta(target_meta)
    if target.parent != expected.parent or any(not np.allclose(target.local[j],expected.local[j],rtol=0,atol=1e-4) for j in target.order):
        raise ValueError('Costume readback differs from frozen target rig')
    scaled, charted = native_port.rebuild_helpers(target_meta,source_rig)
    raw = RawSource.from_files(paths['source_skeleton'],paths['source_motion'])
    for j in source_rig.order:
        if j not in raw.parent or source_rig.parent[j] != raw.parent[j] or not np.allclose(source_rig.local[j],raw.bind[j],rtol=0,atol=1e-4):
            raise ValueError('Source subset differs from raw skeleton')
    authored_spec = read(paths['authored'])
    if isinstance(authored_spec,list):
        if len(authored_spec) != 1:
            raise ValueError('One authored clip per diagnosis required')
        authored_spec = authored_spec[0]
    if authored_spec['nodes'] != len(target.order) or authored_spec['end'] != raw.end:
        raise ValueError('Authored source clock/node domain differs')
    channels = {}
    for ch in authored_spec['channels']:
        i, typ = ch['joint'], ch['type']
        if type(i) is not int or not 0 <= i < len(target.order) or typ not in bench.TYPES:
            raise ValueError('Invalid authored channel')
        key = target.order[i], typ
        if key in channels:
            raise ValueError('Duplicate authored channel')
        channels[key] = [Key(**k) for k in ch['keys']]
    authored = bench.animation(channels,authored_spec['end'])
    points = _skin(paths['skin_smd'],target)
    skin = bench.Skin(points.positions,{j:(ids,weights) for j,ids,weights,_,_ in points.parts},target.world,inverse_bind=inverse)
    times = bench.frame_grid(raw.end,16)
    source = source_target_worlds(raw,times,source_rig,scaled,charted,target,recipe['wrappers'])
    out = out.resolve(); out.mkdir(parents=True,exist_ok=False)
    audit = out/'packed-audit.json'
    log('Auditing encoded clip, then measuring source / authored / packed poses on the same full grid.')
    _run([paths['codec'],'audit',paths['packed'],audit],out/'codec-audit.log')
    packed = bench.packed_animation(read(audit),target.order)
    if packed.end != raw.end:
        raise ValueError('Packed source clock differs')
    result = stage_errors(times,source,batch.animation_worlds(authored,target,times),
                          batch.animation_worlds(packed,target,times),skin,limits=limits,parent=target.parent,
                          authored_stage=recipe.get('authored_stage','exact'),predecessors=recipe.get('predecessors'))
    if pin(recipe_path)!=recipe_pin or any(pin(paths[k]) != v for k,v in inputs.items()):
        raise ValueError('Input changed during diagnosis')
    from .rig_dependencies import rig_fingerprint
    from .compat.animation_archive import track_fingerprint
    result.update(inputs=inputs, recipe=recipe_pin, encoded_bytes=paths['packed'].stat().st_size,
                  rig_sha256=rig_fingerprint(target_meta),nodes=len(target.order),
                  track_sha256=track_fingerprint(paths['packed'].read_bytes()),
                  capacity=capacity,capacity_passed=paths['packed'].stat().st_size<=capacity if capacity else None,
                  scope='Source-clock pose diagnosis on declared subset/charts/identity wrappers and supplied costume readback. Movement ownership and live gameplay remain separate.')
    (out/'receipt.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return dict(result,output=str(out))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request',type=Path,help='JSON native_port preparation request')
    args = parser.parse_args()
    print(json.dumps(handle(read(args.request),lambda _:None),indent=2))
