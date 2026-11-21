"""Conservative leaf-pruning plans and explicit index remapping for offline rigs.

Ancestors are retained without composing transforms. An empty consumer list
means only a geometry estimate; it never certifies a usable fighter rig.
"""
import math


def validate_rig(rig):
    order, parent, rest = (rig[k] for k in ('order', 'parent', 'rest'))
    if not order or any(not isinstance(j, str) or not j for j in order) or len(set(order)) != len(order):
        raise ValueError('Nonempty unique joint names required')
    if set(parent) != set(order) or set(rest) != set(order):
        raise ValueError('Rig domains differ')
    seen = set()
    for joint in order:
        if parent[joint] is not None and parent[joint] not in seen:
            raise ValueError('Parent must precede child; cycles and missing parents refused')
        for kind in ('r', 't', 's'):
            values = rest[joint][kind]
            if len(values) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
                raise ValueError('Finite three-component rest values required')
        seen.add(joint)
    return order, parent, rest


def rig_fingerprint(rig):
    """Bind clip evidence to topology AND rest transforms, not just node count."""
    import hashlib
    import json
    order,parent,rest=validate_rig(rig)
    canonical=dict(order=order,parent=parent,rest={j:{k:list(map(float,rest[j][k])) for k in ('r','t','s')} for j in order})
    return hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def closure_plan(rig, weighted_joints, *, consumers):
    order, parent, _ = validate_rig(rig)
    weighted = set(weighted_joints)
    if not weighted or weighted - set(order):
        raise ValueError('Nonempty known weighted joint domain required')
    if not isinstance(consumers, dict) or any(not isinstance(k, str) or not k for k in consumers):
        raise ValueError('Named consumer-to-joint lists required')
    required = set(weighted)
    reasons = {j: ['skin'] for j in weighted}
    for name, joints in consumers.items():
        if not isinstance(joints, list) or not joints or any(j not in parent for j in joints):
            raise ValueError('Each declared consumer must name known joints')
        for joint in joints:
            required.add(joint)
            reasons.setdefault(joint, []).append(name)
    retained = set(required)
    for joint in required:
        while parent[joint] is not None:
            joint = parent[joint]
            retained.add(joint)
    kept = [j for j in order if j in retained]
    indices = {j: i for i, j in enumerate(kept)}
    return dict(status='OFFLINE_DEPENDENCY_PLAN_NOT_ENGINE_ACCEPTED', native_ready=False,
                original_count=len(order), retained_count=len(kept),
                required={j: sorted(reasons[j]) for j in order if j in reasons},
                retained=kept, removed=[j for j in order if j not in retained],
                old_to_new={str(i): indices.get(j) for i, j in enumerate(order)},
                scope='Only named consumers are protected; unlisted consumers remain unresolved.')


def mesh_closure_plan(rig, mesh, selection, *, consumers, animated_joints=(), unresolved_consumers=()):
    """Derive live dependencies from raw selected meshes, never animation alone.

    Selection uses the same name/subindex identities as source_mesh_handoff.
    Excluded mesh users are retained as invalidation evidence. This is a plan,
    not permission to discard undeclared engine consumers or runtime variants.
    """
    order, _, _ = validate_rig(rig)
    known = set(order)
    chosen = [(r['name'], r['subindex']) for r in selection['meshes']]
    actual = [(o.name, o.subindex) for o in mesh.objects]
    if not chosen or len(set(chosen)) != len(chosen) or len(set(actual)) != len(actual) or set(chosen)-set(actual):
        raise ValueError('Explicit unique known mesh selection required')
    animated = set(animated_joints)
    if animated-known:
        raise ValueError('Animated joint outside source rig')
    if not isinstance(unresolved_consumers, (list, tuple)) or any(not isinstance(x, str) or not x for x in unresolved_consumers):
        raise ValueError('Explicit unresolved consumer names required')
    if not isinstance(consumers, dict) or any(k.startswith('mesh:') for k in consumers):
        raise ValueError('Named consumers required; mesh: is reserved')
    weighted, rigid, excluded = set(), {}, []
    for obj in mesh.objects:
        joints = set()
        count = len(obj.positions[0].data)
        if not count:
            raise ValueError('Empty source mesh')
        if obj.parent_bone_name:
            if obj.bone_influences:
                raise ValueError('Ambiguous rigid and weighted mesh')
            joints.add(obj.parent_bone_name)
        for influence in obj.bone_influences:
            for w in influence.vertex_weights:
                if type(w.vertex_index) is not int or not 0 <= w.vertex_index < count or not math.isfinite(w.vertex_weight) or w.vertex_weight < 0:
                    raise ValueError('Invalid source influence')
                if w.vertex_weight > 0:
                    joints.add(influence.bone_name)
        if not joints or joints-known:
            raise ValueError('Mesh requires known positive skin influences or a rigid parent')
        if (obj.name, obj.subindex) in chosen:
            # Rigid bindings also seed the closure for all-rigid accessories.
            weighted.update(joints)
            if obj.parent_bone_name:
                rigid[f'mesh:{obj.name}:{obj.subindex}'] = [obj.parent_bone_name]
        else:
            excluded.append(dict(name=obj.name, subindex=obj.subindex, joints=sorted(joints)))
    result = closure_plan(rig, weighted, consumers=dict(consumers, **rigid))
    removed = set(result['removed'])
    result.update(schema='mesh-joint-plan-v1',source_rig_sha256=rig_fingerprint(rig), selected_meshes=[dict(name=n, subindex=i) for n,i in chosen],
                  animation_only_removed=[j for j in order if j in animated & removed],
                  excluded_mesh_dependencies=[dict(row, removed_users=sorted(set(row['joints']) & removed)) for row in excluded],
                  unresolved_consumers=list(unresolved_consumers),
                  next_step='Resolve consumers, then freeze helpers and count the serialized costume before admission.')
    return result


