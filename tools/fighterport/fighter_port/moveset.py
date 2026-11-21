"""Compile an explicit Ultimate-to-donor motion coverage manifest.

Each result is checkpointed and hash-verified. Missing donor states stay visible
as blocked rows; compilation never silently substitutes an unrelated move.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from .author import bake
from .evaluation import Animation
from .provenance import fingerprint, verify_bundle
from .retarget import transfer
from echo_ultimate.decode import decode


def target_action(actions, motion):
    matches = [(i,a) for i,a in enumerate(actions) if a.motion == motion and a.symbol]
    symbols = {a.symbol for _,a in matches}
    if not matches:
        raise ValueError(f'donor has no animation slot for {motion}')
    if len(symbols) != 1:
        raise ValueError(f'ambiguous donor motion {motion}: {sorted(symbols)}')
    return matches[0][0],matches[0][1].symbol


def guard_animation_loops(data, action_indices):
    """Yield at a script's self-loop until the animation wraps.

    Donor scripts can jump back after their old final absolute timer. A longer
    imported clip leaves every timer in the past and the interpreter spins
    forever in one frame. Retail Command_08 waits for animation wrap. Preserve
    existing waits and retarget the copied script's self-pointer to its new root.
    """
    from vault.echo.subactions import FighterDat
    fighter = FighterDat(data); changes = []
    for index in action_indices:
        old = fighter.actions[index].script_offset
        items = fighter.script_items(index)
        if any(code == 8 for code, _, _ in items):
            continue
        jumps = [i for i, (code, _, ptr) in enumerate(items) if code == 7 and ptr == old]
        if not jumps:
            continue
        for i in reversed(jumps):
            items.insert(i, (8, {'unknown': 0}, None))
        change = fighter.replace_script(index, items)
        for cmd in fighter.script(index).commands:
            if cmd.code == 7 and cmd.fields.get('pointer') == old:
                fighter.dat.set_u32(cmd.offset + 4, change['new_offset'])
        fighter._scripts.clear()
        changes.append(change)
    return fighter.to_bytes(), changes


def enable_engine_root(data, action_indices):
    """Let Melee extract TransN translation instead of drawing it.

    The action flag is independent of having translation curves in the AJ.
    Preserve all other donor flags; only explicitly authored engine roots opt in.
    The state's physics callback must separately consume the extracted delta.
    For example, ordinary AttackS3 uses friction-only ft_80084F3C: setting this
    flag alone discards its visible translation without moving the fighter.
    Validate the callback and live movement before treating this as root motion.
    """
    from vault.echo.subactions import FighterDat, ACTION_SIZE
    fighter = FighterDat(data); table, count = fighter.action_table; changes = []
    for index in sorted(set(action_indices)):
        if not 0 <= index < count:
            raise ValueError(f'invalid engine-root action {index}')
        before = fighter.actions[index].flags
        after = before | 0x80000000
        if before != after:
            fighter.dat.set_u32(table + index * ACTION_SIZE + 0x10, after)
            changes.append({'action':index,'before':before,'after':after})
    return fighter.to_bytes(), changes


def verify_result(result, target_rig):
    """A resumed output must still match its frozen clip and target skeleton."""
    _, files = verify_bundle(Path(result['manifest']))
    for actual, frozen, label in ((Path(result['animation']),files['animation'],'animation'),
                                  (Path(target_rig),files['rig'],'target rig')):
        if fingerprint(actual)['sha256'] != fingerprint(frozen)['sha256']:
            raise ValueError(f'compiled {label} differs from its frozen bundle')


def _at(keys, frame):
    """Source time shown on clip frame `frame` (time keys are piecewise linear)."""
    for (f0, t0), (f1, t1) in zip(keys, keys[1:]):
        if frame <= f1:
            return t0 + (t1 - t0) * (frame - f0) / (f1 - f0) if f1 > f0 else t1
    return float(keys[-1][1])


def join_parts(parts, source_root, skeleton, landmarks, allow_unbound, target_rig, folder, carry):
    """Carry each part across on its own (folder/part<i>), then write both the source and
    the carried animation again on one timeline: folder/decoded/source.anim and
    folder/full.anim, a key on every frame. A part's `time_keys` ([[clip frame, source
    time], ...], default the whole clip frame for frame) say which stretch of it plays;
    the next part takes over on the frame after. -> the first part's transfer report,
    with where each part starts."""
    import shutil
    from .bvh_to_anim import write_anim
    from .evaluation import sample
    from .rigmap import Rig
    from .smpl_to_anim import unwrap
    pieces, timeline, starts = [], [], []
    for i, part in enumerate(parts):
        sub = folder/f'part{i}'
        decoded = sub/'decoded'
        if not (decoded/'decode.json').exists():
            decode(skeleton, source_root/part['source'], decoded, allow_unbound=allow_unbound, landmarks=landmarks)
        record = sub/'transfer.json'
        if not record.exists():
            record.write_text(json.dumps(transfer(decoded/'source.anim', decoded/'source.joints.json', target_rig,
                                                  sub/'full.anim', **carry), indent=2))
        native = json.loads(record.read_text())
        verify_bundle(Path(native['manifest']))
        carried, source = Animation(sub/'full.anim'), Animation(decoded/'source.anim')
        keys = part.get('time_keys') or [[0, 0.0], [int(round(carried.end)), float(carried.end)]]
        last = keys[-1][0] if i == len(parts)-1 else keys[-1][0]-1
        starts.append(len(timeline))
        timeline += [(i, min(_at(keys, f), carried.end)) for f in range(last+1)]
        pieces.append((carried, source, native))
    for which, rig, out in ((0, Rig(target_rig), folder/'full.anim'),
                            (1, Rig(folder/'part0'/'decoded'/'source.joints.json'), folder/'decoded'/'source.anim')):
        out.parent.mkdir(parents=True, exist_ok=True)
        anims = [p[which] for p in pieces]
        channels = {}
        for joint in rig.order:
            names = sorted({c for a in anims for c in a.channels.get(joint, {})})
            for name in names:
                rest = rig.rest[joint][name[0]]['XYZ'.index(name[-1])]       # translateX -> rest['t'][0]
                values, prev = {}, None
                for frame, (i, time) in enumerate(timeline):
                    keys = anims[i].channels.get(joint, {}).get(name)
                    v = sample(keys, time) if keys else rest
                    if name.startswith('rotate'):
                        v = prev = unwrap(prev, v)
                    values[frame] = float(v)
                channels.setdefault(joint, {})[name] = values
        write_anim(out, len(timeline)-1, channels, rig.order)
    for name in ('source.joints.json', 'decode.json'):
        shutil.copy(folder/'part0'/'decoded'/name, folder/'decoded'/name)
    return {**pieces[0][2], 'joined': [{'source': part['source'], 'first_frame': start} for part, start in zip(parts, starts)]}


def compile_set(spec_path, source_root, target_rig, target_pl, out):
    from vault.echo.subactions import FighterDat
    spec_path,source_root,target_rig,target_pl,out = map(Path,(spec_path,source_root,target_rig,target_pl,out))
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    entries = spec['clips']
    ids = [e['id'] for e in entries]
    if spec.get('schema') != 1 or not ids or len(ids) != len(set(ids)):
        raise ValueError('coverage manifest requires schema 1 and unique nonempty clip ids')
    if any(not name or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_-' for c in name) for name in ids):
        raise ValueError('clip ids must be lowercase path-safe identifiers')
    actions = FighterDat(target_pl.read_bytes()).actions
    landmarks = json.loads((spec_path.parent/spec['landmarks']).read_text())
    skeleton = source_root/spec['skeleton']
    identity = {'spec':fingerprint(spec_path),'rig':fingerprint(target_rig),'pl':fingerprint(target_pl),
                'skeleton':fingerprint(skeleton),'landmarks':landmarks,
                'code':{n:fingerprint(Path(__file__).with_name(n+'.py')) for n in ('moveset','ultimate','retarget','author')}}
    out.mkdir(parents=True,exist_ok=True)
    identity_path = out/'identity.json'
    if identity_path.exists():
        if json.loads(identity_path.read_text()) != identity:
            raise ValueError('moveset inputs changed; use a new output directory')
    else:
        identity_path.write_text(json.dumps(identity,indent=2))
    rows, install, symbols = [], [], set()
    for entry in entries:
        row = {'id':entry['id'],'target_motion':entry.get('target_motion'),
               'category':entry['category'],'gameplay_status':'unverified'}
        try:
            if entry.get('blocked'):
                row.update(status='blocked',reason=entry['blocked'])
                rows.append(row)
                continue
            index,symbol = target_action(actions,entry['target_motion'])
            if symbol in symbols:
                raise ValueError(f'duplicate target animation: {symbol}')
            symbols.add(symbol)
            folder = out/entry['id']; record = folder/'result.json'
            if record.exists():
                result = json.loads(record.read_text())
                verify_result(result, target_rig)
                if result.get('source') and result['source'] != fingerprint(source_root/entry['source']):
                    raise ValueError('source animation changed after compilation')
            else:
                folder.mkdir(parents=True,exist_ok=True)
                if entry.get('animation'):
                    animation = (spec_path.parent/entry['animation']).resolve()
                    manifest = (spec_path.parent/entry['manifest']).resolve()
                    _,files = verify_bundle(manifest)
                    if fingerprint(animation)['sha256'] != fingerprint(files['animation'])['sha256']:
                        raise ValueError('provided animation differs from its frozen bundle')
                    if fingerprint(target_rig)['sha256'] != fingerprint(files['rig'])['sha256']:
                        raise ValueError('provided animation uses a different target rig')
                    result = {'animation':str(animation),'manifest':str(manifest),'timing':'existing reviewed candidate'}
                else:
                    source = source_root/entry['source']
                    full = folder/'full.anim'
                    native_record = folder/'transfer.json'
                    carry = dict(attachments=entry.get('attachments', spec.get('attachments',())),   # a clip may name its own
                                 body_scale=entry.get('body_scale','reject'),
                                 root_motion_joint=entry.get('root_motion_joint'),
                                 engine_root=entry.get('engine_root'))
                    if entry.get('parts'):
                        # several source clips played one after another as one clip
                        if not native_record.exists():
                            native = join_parts(entry['parts'], source_root, skeleton, landmarks, spec.get('allow_unbound',()),
                                                target_rig, folder, carry)
                            native_record.write_text(json.dumps(native,indent=2))
                    else:
                        decoded = folder/'decoded'
                        if not (decoded/'decode.json').exists():
                            decode(skeleton,source,decoded,allow_unbound=spec.get('allow_unbound',()),landmarks=landmarks)
                        if not native_record.exists():
                            native = transfer(decoded/'source.anim',decoded/'source.joints.json',target_rig,full,**carry)
                            native_record.write_text(json.dumps(native,indent=2))
                    native = json.loads(native_record.read_text())
                    verify_bundle(Path(native['manifest']))
                    animation,manifest = full,Path(native['manifest'])
                    end = entry.get('last_frame')
                    explicit = entry.get('time_keys')
                    if entry.get('parts'):               # already on its own timeline, frame for frame
                        last = int(round(Animation(full).end))
                        explicit = [[0, 0.0], [last, float(last)]]
                    if entry.get('hold_end'):
                        # The engine leaves most actions one frame before their clip's count runs out (a clip of 28
                        # is 27 frames of dodge). A clip that must last as long as its keys say goes on one frame
                        # more: at the speed it was going, or holding its last pose where the source has no more.
                        if explicit is None and end is None:
                            last = int(round(Animation(full).end))
                            explicit = [[0, 0.0], [last, float(last)]]
                        if explicit is not None:
                            explicit = [list(k) for k in explicit]
                            (f0, t0), (f1, t1) = explicit[-2], explicit[-1]
                            explicit.append([f1 + 1, float(t1) + (float(t1) - float(t0)) / (f1 - f0)])
                        else:
                            end += 1
                    timing = 'complete raw source animation; donor scripts unchanged'
                    if explicit is not None:
                        # [[clip frame, source time], ...]: the source's own playback speed, e.g. the
                        # game's motion-rate changes. Source times past the clip's end hold its last pose.
                        source_end = Animation(full).end
                        keys = []
                        for frame, time in explicit:
                            if type(frame) is not int or (keys and frame <= keys[-1][0]):
                                raise ValueError('time_keys need increasing integer clip frames')
                            keys.append([frame, min(float(time), source_end)])
                        if len(keys) < 2 or keys[0][0] != 0 or any(b[1] < a[1] for a, b in zip(keys, keys[1:])):
                            raise ValueError('time_keys start at clip frame 0 and never run backwards')
                        end = keys[-1][0]
                        recipe = folder/'timing.recipe.json'
                        recipe.write_text(json.dumps({'schema':1,'name':entry['id'],'frames':end+1,
                            'base':'full.anim','time_keys':keys},indent=2))
                        authored = bake(recipe,target_rig,folder/'final.anim')
                        animation,manifest = folder/'final.anim',Path(authored['manifest'])
                        timing = 'source frames resampled through explicit time keys'
                    elif end is not None:
                        if type(end) is not int or end < 1:
                            raise ValueError('last_frame must be a positive integer')
                        source_end = Animation(full).end
                        keys = [[0,0],[end,end]] if end <= source_end else [[0,0],[source_end,source_end],[end,source_end]]
                        recipe = folder/'timing.recipe.json'
                        recipe.write_text(json.dumps({'schema':1,'name':entry['id'],'frames':end+1,
                            'base':'full.anim','time_keys':keys},indent=2))
                        authored = bake(recipe,target_rig,folder/'final.anim')
                        animation,manifest = folder/'final.anim',Path(authored['manifest'])
                        timing = 'raw source frames, trimmed or held at end; no script-rate inference'
                    result = {'animation':str(animation.resolve()),'manifest':str(manifest.resolve()),
                              'source':fingerprint(source),'timing':timing}
                record.write_text(json.dumps(result,indent=2))
            row.update(status='compiled',action=index,symbol=symbol,**result)
            item = {'move':f'action{index}','file':result['animation'],'manifest':result['manifest']}
            if entry.get('engine_root'):
                item['engine_root'] = entry['engine_root']
            install.append(item)
        except (ValueError,OSError,KeyError,RuntimeError) as exc:
            row.update(status='error',reason=str(exc))
        rows.append(row)
        print(entry['id'],row['status'],flush=True)
        (out/'coverage.json').write_text(json.dumps({'schema':1,'clips':rows},indent=2))
    report = {'schema':1,'clips':rows,'counts':{s:sum(r['status']==s for r in rows) for s in ('compiled','blocked','error')},
        'limits':'Motion coverage only. Scripts, hitboxes, physics and visual acceptance are separate checks.'}
    (out/'coverage.json').write_text(json.dumps(report,indent=2))
    (out/'install.json').write_text(json.dumps(install,indent=2))
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('spec'); p.add_argument('--source-root',required=True)
    p.add_argument('--rig',required=True); p.add_argument('--pl',required=True); p.add_argument('--out',required=True)
    a = p.parse_args()
    result = compile_set(a.spec,a.source_root,a.rig,a.pl,a.out)
    print(json.dumps(result['counts']))
    return 1 if result['counts']['error'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
