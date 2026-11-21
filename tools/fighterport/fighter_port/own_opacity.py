"""Numeric material opacity on the same clock as the port's native animation.

Game readers supply validated bindings and clip samples. This adapter does not infer shader semantics from
material/curve names. It keeps partial values, maps split/re-timed jobs, and restores defaults on interruption.
Native material alpha is an explicit adaptation when a source uses screen-door dithering.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np


def read(root, fighter):
    path = Path(root) / 'gamedata' / 'fighter' / fighter / 'game.json'
    data = json.loads(path.read_text('utf-8')).get('material_opacity') if path.exists() else None
    if not data:
        return None
    if data.get('version') != 1:
        raise ValueError('unsupported material opacity schema')
    names = [b['mesh'] for b in data['bindings']]
    if len(names) != len(set(names)):
        raise ValueError('duplicate material opacity binding')
    def valid(values):
        return all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in values)
    if not valid([b['default'] for b in data['bindings']]):
        raise ValueError('invalid default opacity')
    for stem, clip in data['clips'].items():
        end = clip['end']
        if type(end) is not int or end < 0:
            raise ValueError(f'{stem}: invalid opacity duration')
        for mesh, values in clip['tracks'].items():
            if mesh not in names or len(values) not in (1, end + 1) or not valid(values):
                raise ValueError(f'{stem}/{mesh}: invalid opacity samples')
    return data


def pieces(data, receipt):
    """Source mesh -> body DOBJ and its resting low-detail copy, in the importer's checked order."""
    groups, layout = receipt['mesh_groups'], receipt['pieces']
    from .own_faces import drawn_at_rest
    rest = drawn_at_rest(layout)
    if len(rest) != len(layout['low']):
        raise ValueError('opacity: low-detail copies do not match the resting pieces')
    copies = dict(zip(rest, layout['low']))
    out = []
    for b in data['bindings']:
        indices = [i for i, g in enumerate(groups) if g['name'] == b['mesh']]
        if not indices:
            raise ValueError(f"opacity mesh {b['mesh']} is absent from the costume")
        group = receipt.get('faces', {}).get('opacity', {}).get(b['mesh'])
        if group is None or layout['groups'][group - 1] != [indices]:
            raise ValueError('opacity requires its own model group; prepare the costume again')
        indices += [copies[i] for i in indices if i in copies]
        out.append(dict(b, pieces=indices, group=group))
    return out


def reserve_faces(faces, data):
    """Reserve independent native groups so zero opacity also removes material-free shadow draws.

The current reader supplies opacity-only meshes. A mesh also controlled by discrete visibility needs a
combined source predicate; refuse that collision instead of overriding the discrete track.
"""
    if not data or not data['bindings']:
        return faces
    from copy import deepcopy
    from .own_faces import MOST_GROUPS
    faces = deepcopy(faces)
    nodes = set(faces['always'] + faces['never']) | {n for g in faces['groups'] for c in g['choices'] for n in c}
    faces['opacity'] = {}
    for b in data['bindings']:
        node = b['mesh'][:-5] if b['mesh'].endswith('Shape') else b['mesh']
        if node in nodes:
            raise ValueError(f'{node}: combining discrete visibility and opacity is unsupported')
        if len(faces['groups']) + 2 > MOST_GROUPS:
            raise ValueError('opacity would exceed the native model-group limit')
        nodes.add(node)
        faces['groups'].append(dict(choices=[[node]], seen=[1], rest=0, moving=[], clock=[]))
        faces['shown_at_rest'].append(node)
        faces['opacity'][b['mesh']] = len(faces['groups'])
    faces['shown_at_rest'].sort()
    return faces


def low_lists(layout, faces):
    """Move the controlled low-detail copies out of the always-drawn shadow group."""
    if not faces.get('opacity'):
        return layout
    from .own_faces import drawn_at_rest
    copied = dict(zip(drawn_at_rest(layout), layout['low']))
    switched = [[] for _ in layout['groups']]
    moved = set()
    for group in faces['opacity'].values():
        switched[group - 1] = [[copied[i] for i in choice if i in copied]
                               for choice in layout['groups'][group - 1]]
        moved.update(i for choice in switched[group - 1] for i in choice)
    return dict(layout, low_body=[i for i in layout['low'] if i not in moved], low_groups=switched)


def patch_costume(payload, root_name, bindings):
    """Enable blending before MOBJ shader creation, preserving the other pieces' material descriptors."""
    from .compat.rig_inventory import Archive, costume_inventory
    inv = costume_inventory(payload, root_name)
    dat = Archive(payload)
    dobjs = [d for j in inv['joints'] for d in j['dobj_offsets']]
    owners = {}
    for binding in bindings:
        for i in binding['pieces']:
            if i < 0 or i >= len(dobjs) or i in owners:
                raise ValueError('invalid or multiply bound opacity DOBJ')
            owners[i] = binding
    materials, changed = {}, []
    for i, dobj in enumerate(dobjs):
        m = dat.ptr(dobj + 8)
        if m is None:
            if i in owners:
                raise ValueError('opacity piece has no material')
            continue
        dat.require(m, 24)
        mat = dat.ptr(m + 12)
        if mat is not None:
            materials.setdefault(mat, []).append(i)
    for mat, indices in materials.items():
        selected = [i for i in indices if i in owners]
        if not selected:
            continue
        if len(selected) != len(indices) or len({owners[i]['mesh'] for i in indices}) != 1:
            raise ValueError('opacity material is shared by differently controlled pieces')
        dat.require(mat, 20)
        dat.set_f32(mat + 12, owners[indices[0]]['default'])
        for i in indices:
            m = dat.ptr(dobjs[i] + 8)
            flags = dat.u32(m + 4)
            # Keep vertex alpha when used; multiply it by the animated material alpha.
            alpha = 3 if flags & (2 << 13) else 1
            dat.set_u32(m + 4, (flags & ~(3 << 13)) | (alpha << 13) | (1 << 29) | (1 << 30))
            pe = dat.ptr(m + 20)
            if pe is not None:
                dat.require(pe, 12)
                # HSD_SetupPEMode uses this descriptor instead of rendermode when present.
                raw = bytearray(dat.buf[32 + pe:32 + pe + 12])
                raw[0] = (raw[0] | 8) & ~32  # depth test kept, depth write off
                raw[4:7] = bytes((1, 4, 5))  # BLEND, SRCALPHA, INVSRCALPHA
                raw[9:12] = bytes((7, 0, 7)) # both alpha compares ALWAYS
                dat.buf[32 + pe:32 + pe + 12] = raw
            changed.append(i)
    for j in inv['joints']:
        if any(d in {dobjs[i] for i in changed} for d in j['dobj_offsets']):
            dat.set_u32(j['offset'] + 4, dat.u32(j['offset'] + 4) | (1 << 19) | (1 << 29))
    if set(changed) != set(owners):
        raise ValueError('opacity piece has no material color descriptor')
    return dat.to_bytes(), sorted(changed)


def costume(path, root, fighter, receipt, root_name):
    data = read(root, fighter)
    if not data or not data['bindings']:
        return []
    path = Path(path)
    payload, changed = patch_costume(path.read_bytes(), root_name, pieces(data, receipt))
    path.write_bytes(payload)
    return changed


def job_tracks(data, job, clip_ends):
    """Use the animation bank's exact part maps; defaults cover a part with no calibrated curve."""
    from . import own_bank
    maps = [own_bank.part_keys(p, clip_ends[p['stem']]) for p in job['parts']]
    frames, parts, at, end = own_bank.timeline(maps, 1)
    tracks = {}
    for b in data['bindings']:
        values = np.full(len(frames), b['default'], dtype=float)
        for i, part in enumerate(job['parts']):
            clip = data['clips'].get(part['stem'])
            if clip is None or b['mesh'] not in clip['tracks']:
                continue
            if clip['end'] != clip_ends[part['stem']]:
                raise ValueError(f"{part['stem']}: opacity and animation clocks disagree; export the reader again")
            samples = clip['tracks'][b['mesh']]
            mask = parts == i
            values[mask] = np.interp(at[mask], np.arange(len(samples)), samples)
        # Remove only collinear keys (within float roundoff), retaining the exact boundary of a hidden interval.
        keys = []
        for frame, value in zip(frames, values):
            keys.append((float(frame), float(value)))
            while len(keys) >= 3:
                a, b0, c = keys[-3:]
                predicted = a[1] + (c[1] - a[1]) * (b0[0] - a[0]) / (c[0] - a[0])
                if abs(predicted - b0[1]) > 1e-7 or (b0[1] == 0) != (predicted == 0):
                    break
                keys.pop(-2)
        if any(value != b['default'] for _, value in keys):
            tracks[b['mesh']] = keys
    return tracks


def code(mine, bindings, main, other):
    """Stateless per-fighter evaluation: action/table changes and hitlag cannot leak another fighter's alpha."""
    mine = dict(mine) if mine else dict(source=[], frame=[], provides=[], load=[], table=[], rows=[])
    f = lambda v: repr(float(v)) + 'f'
    lines = ['typedef struct { float frame, alpha; } OpacityKey;',
             'static float OpacityAt(const OpacityKey *keys, int count, float at)', '{',
             '    int i;', '    if (!(at > keys[0].frame)) return keys[0].alpha;',
             '    for (i = 1; i < count; ++i)', '        if (at < keys[i].frame)',
             '            return keys[i-1].alpha + (keys[i].alpha - keys[i-1].alpha) *',
             '                (at - keys[i-1].frame) / (keys[i].frame - keys[i-1].frame);',
             '    return keys[count-1].alpha;', '}']
    arrays, names = {}, {}
    for table in (main, other):
        for tracks in table.values():
            for keys in tracks.values():
                key = tuple(map(tuple, keys))
                if key not in arrays:
                    name = 'opacity_keys_' + str(len(arrays))
                    arrays[key] = name
                    lines += [f'static const OpacityKey {name}[] = {{' + ', '.join(
                        '{' + f(at) + ', ' + f(value) + '}' for at, value in keys) + '};']
    lines += ['static void OpacityFrame(FighterData *fd, GOBJ *gobj)', '{', '    int a = fd->action_id;',
              '    float at = fd->state.frame;', '    if (!fd->dobj_lookup) return;']
    for i, b in enumerate(bindings):
        names[b['mesh']] = i
        lines += [f'    float opacity_{i} = {f(b["default"])};']
    for table, cond in ((main, 'fd->ftaction == fd->ftData->ftaction'),
                        (other, 'fd->ftaction == (FtAction *)(fd->ftData->x14)')):
        lines += [f'    if ({cond})', '        switch (a)', '        {']
        for action, tracks in sorted(table.items()):
            if not tracks:
                continue
            lines += [f'        case {int(action)}:']
            for mesh, keys in tracks.items():
                name = arrays[tuple(map(tuple, keys))]
                lines += [f'            opacity_{names[mesh]} = OpacityAt({name}, {len(keys)}, at);']
            lines += ['            break;']
        lines += ['        }']
    for b in bindings:
        lines += [f'    Fighter_SetVisGroupCurrent(gobj, {b["group"]}, opacity_{names[b["mesh"]]} > 0.0f ? 0 : -1);']
        for index in b['pieces']:
            lines += [f'    if (fd->dobj_lookup[{index}] && fd->dobj_lookup[{index}]->mobj && fd->dobj_lookup[{index}]->mobj->mat)',
                      f'        fd->dobj_lookup[{index}]->mobj->mat->alpha = opacity_{names[b["mesh"]]};']
    lines += ['}', 'static void OpacityProc(GOBJ *gobj)', '{',
              '    OpacityFrame(gobj->userdata, gobj);', '}']
    mine['source'] = list(mine.get('source') or []) + lines
    # OnFrame is before animation/input/collision. A late owned process reads the pose actually rendered,
    # including same-update interrupts and hitlag. The fighter GOBJ owns its lifetime, also outside matches.
    mine['load'] = list(mine.get('load') or []) + ['GObj_AddProc(gobj, OpacityProc, 23);']
    mine['provides'] = list(mine.get('provides') or []) + ['numeric source material opacity on the native animation clock']
    return mine


def carry(pl, own, root, fighter, jobs, rows, mine=None, kit=True, demo_jobs=None):
    from . import own_demo, own_bank
    data = read(root, fighter)
    if not data or not data['bindings']:
        return mine, data
    if not kit:
        raise ValueError('source material opacity requires MexTK')
    receipt = json.loads((Path(own) / 'body' / 'receipt.json').read_text('utf-8'))
    bindings = pieces(data, receipt)
    import ssbh_data_py as ssbh
    motion = Path(root) / 'gamedata' / 'fighter' / fighter / 'motion' / 'body' / 'c00'
    ends = {p.stem: int(ssbh.anim_data.read_anim(str(p)).final_frame_index) for p in motion.glob('*.nuanmb')}
    by_motion = {j['motion']: j for j in jobs}
    main = {}
    for row in rows.values():
        job = by_motion.get(row.get('motion')) if row.get('kind') == 'SOURCE' else None
        if row.get('kind') == 'HELD':
            job = dict(parts=[dict(stem=own_bank.HOLD_STEM, keys=[[0, 0]])])
        if job:
            tracks = job_tracks(data, job, ends)
            main.update({int(a): tracks for a in row.get('actions', [])})
    demo_rows = own_demo.demo_rows(pl)
    if demo_jobs is None:
        demo_jobs, _without = own_demo.jobs_for(fighter, demo_rows, sorted(ends))
    other = {r['index']: job_tracks(data, demo_jobs[r['symbol']], ends)
             for r in demo_rows if r['symbol'] in demo_jobs}
    report = dict(bindings=bindings, main_actions=sorted(a for a, t in main.items() if t),
                  demo_actions=sorted(a for a, t in other.items() if t), unresolved=data.get('unresolved', []),
                  adaptation=data.get('adaptation'), evidence=data.get('evidence'))
    return code(mine, bindings, main, other), report
