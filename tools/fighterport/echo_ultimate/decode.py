"""Decode Ultimate skeleton/animation files into the existing FK inspection format.

Requires the optional ssbh_data_py package. This preserves source bone tracks;
it does not retarget to a donor or reproduce game-script timing/materials.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from fighter_port.bvh_to_anim import write_anim
from fighter_port.provenance import fingerprint
from fighter_port.smpl_to_anim import orthonormalize, quat_to_mat, to_hsd_euler, unwrap


def skeleton_metadata(skeleton):
    names = [b.name for b in skeleton.bones]
    if not names or len(names) != len(set(names)):
        raise ValueError('skeleton must have unique, nonempty bone names')
    parent, rest = {}, {}
    for i, b in enumerate(skeleton.bones):
        if b.parent_index is not None and not 0 <= b.parent_index < len(names):
            raise ValueError('skeleton parent index is out of range')
        # ssbh_data_py exposes row-vector matrices; our FK uses column vectors.
        local = np.asarray(b.transform, dtype=float).T
        if local.shape != (4, 4) or not np.isfinite(local).all() or not np.allclose(local[3], [0, 0, 0, 1]):
            raise ValueError(f'invalid rest matrix for {b.name}')
        scale = np.linalg.norm(local[:3, :3], axis=0)
        if np.any(scale < 1e-8):
            raise ValueError(f'singular rest matrix for {b.name}')
        rotation = orthonormalize(local[:3, :3])
        if not np.allclose(rotation * scale, local[:3, :3], atol=1e-5):
            raise ValueError(f'sheared/reflected rest matrix for {b.name}')
        parent[b.name] = names[b.parent_index] if b.parent_index is not None else None
        rest[b.name] = {'t': local[:3, 3].tolist(), 'r': list(to_hsd_euler(rotation)), 's': scale.tolist()}
    order, active = [], set()
    def visit(name):
        if name in active:
            raise ValueError('cyclic skeleton hierarchy')
        if name in order:
            return
        active.add(name)
        if parent[name] is not None:
            visit(parent[name])
        active.remove(name)
        order.append(name)
    for name in names:
        visit(name)
    return {'order': order, 'parent': parent, 'rename': {n: n for n in names}, 'rest': rest}


def animation_channels(animation, names, allow_unbound=(), needed=None):
    """`needed`: bones whose motion the caller will use. A track with inheritance
    flags this decoder cannot evaluate stops the decode only when it is on one of
    them; on any other bone (cloth, hair) the track is left out and listed, so
    that bone keeps its rest pose. None keeps the strict behaviour: every flagged
    track is an error."""
    end = float(animation.final_frame_index)
    if not np.isfinite(end) or end < 0 or not end.is_integer():
        raise ValueError('expected a finite integer final frame index')
    end = int(end)
    channels, ignored = {}, []
    for group in animation.groups:
        if group.group_type.name != 'Transform':
            ignored.append({'group': group.group_type.name, 'nodes': len(group.nodes)})
            continue
        for node in group.nodes:
            if node.name not in names:
                if node.name in allow_unbound:
                    ignored.append({'group': 'Transform', 'node': node.name, 'reason': 'explicitly allowed unbound track'})
                    continue
                raise ValueError(f'animation bone absent from skeleton: {node.name}')
            for track in node.tracks:
                if track.name != 'Transform' or node.name in channels:
                    raise ValueError(f'unsupported/duplicate transform track: {node.name}/{track.name}')
                flags = track.transform_flags
                if track.compensate_scale or any(getattr(flags, f) for f in (
                    'override_translation', 'override_rotation', 'override_scale', 'override_compensate_scale')):
                    if needed is not None and node.name not in needed:
                        ignored.append({'group': 'Transform', 'node': node.name,
                                        'reason': 'inheritance flags on a bone the transfer does not use; left at rest'})
                        continue
                    raise ValueError(f'unsupported transform inheritance flags: {node.name}')
                if len(track.values) not in (1, end + 1):
                    raise ValueError(f'track must be constant or cover all frames: {node.name}')
                ch, previous = {}, None
                for frame, value in enumerate(track.values):
                    q = np.asarray(value.rotation, dtype=float)
                    t, s = np.asarray(value.translation, dtype=float), np.asarray(value.scale, dtype=float)
                    if (q.shape != (4,) or t.shape != (3,) or s.shape != (3,)
                            or not np.isfinite(np.r_[q, t, s]).all() or np.linalg.norm(q) < 1e-8):
                        raise ValueError(f'invalid transform values: {node.name}, frame {frame}')
                    # SSBH is XYZW, the shared quaternion helper is WXYZ.
                    angles = to_hsd_euler(quat_to_mat(q[[3, 0, 1, 2]]))
                    if previous is not None:
                        angles = tuple(unwrap(p, a) for p, a in zip(previous, angles))
                    previous = angles
                    for kind, vector in (('translate', t), ('rotate', angles), ('scale', s)):
                        for axis, number in zip('XYZ', vector):
                            ch.setdefault(kind + axis, {})[frame] = float(number)
                channels[node.name] = ch
    if not channels:
        raise ValueError('animation contains no skeletal transform tracks')
    return end, channels, ignored


def decode(skeleton_path: Path, animation_path: Path, out: Path, allow_unbound=(), landmarks=None):
    try:
        import ssbh_data_py as ssbh
    except ImportError as exc:
        raise RuntimeError('Ultimate decoding requires the optional ssbh_data_py package') from exc
    skeleton_path, animation_path, out = Path(skeleton_path), Path(animation_path), Path(out)
    if out.exists() and any(out.iterdir()):
        raise ValueError('choose an empty output directory to preserve previous decodes')
    skeleton = ssbh.skel_data.read_skel(str(skeleton_path))
    animation = ssbh.anim_data.read_anim(str(animation_path))
    meta = skeleton_metadata(skeleton)
    needed = None
    if landmarks is not None:
        from fighter_port.rigmap import Rig
        meta['landmarks'] = landmarks
        Rig(meta)  # validate explicit bindings before writing anything
        # with explicit landmarks only those bones and what they hang from carry the pose across
        needed = set()
        for bone in landmarks.values():
            while bone is not None and bone not in needed:
                needed.add(bone)
                bone = meta['parent'][bone]
    end, channels, ignored = animation_channels(animation, meta['order'], allow_unbound, needed)
    out.mkdir(parents=True, exist_ok=True)
    rig_path, anim_path = out / 'source.joints.json', out / 'source.anim'
    rig_path.write_text(json.dumps(meta, indent=2), encoding='utf-8')
    write_anim(anim_path, end, channels, meta['order'])
    from importlib.metadata import version
    result = {'schema': 1, 'source': {'skeleton': fingerprint(skeleton_path), 'animation': fingerprint(animation_path)},
              'reader': {'package': 'ssbh_data_py', 'version': version('ssbh_data_py')},
              'output': {'rig': fingerprint(rig_path), 'animation': fingerprint(anim_path)},
              'bones': len(meta['order']), 'animated_bones': len(channels), 'final_frame_index': end,
              'ignored_groups': ignored,
              'limitations': ['raw animation times; game-script motion rates and cancellation are not applied',
                              'material/visibility tracks, helper constraints and physics are not evaluated',
                              'Euler baking preserves sampled frames; fractional-frame interpolation may differ']}
    result['code'] = fingerprint(Path(__file__))
    (out / 'decode.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('skeleton', type=Path)
    parser.add_argument('animation', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--allow-unbound', default='', help='explicit comma-separated animation nodes absent from the skeleton')
    parser.add_argument('--landmarks', type=Path, help='JSON mapping of semantic body landmarks to source bone names')
    args = parser.parse_args()
    print(json.dumps(decode(args.skeleton, args.animation, args.out,
                           tuple(n for n in args.allow_unbound.split(',') if n),
                           json.loads(args.landmarks.read_text()) if args.landmarks else None), indent=2))


if __name__ == '__main__':
    main()
