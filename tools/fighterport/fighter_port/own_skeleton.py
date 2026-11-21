"""A port on the fighter's OWN skeleton: the stages of ULTIMATE_PORT_PIPELINE.md as functions of a fighter and a work
folder, where the Pokemon Trainer campaign had them as scripts for three species.

A fighter whose body fits no Melee fighter's (a dog with a duck on its back) cannot borrow a skeleton. Its own goes into
the game instead: Melee holds 140 joints a fighter and 32,768 bytes a clip, and a custom fighter brings its own table of
which joint is which (the package's `boneDefinitions`). The donor then gives only what a fighter's code and tables need
(states, actions, the engine's numbers); every table of the donor's that names a joint is written again for this rig.

Stages (each a function, each leaving a file and a receipt in the work folder):
  freeze    the rig the game will hold: the source bones, helpers where a source clip scales or turns a joint in a way
            Melee's joints cannot follow, and the four joints the engine itself drives. Every later number is an index
            into this order.
  body      the costume: that rig as Melee joints, and the game's own model on it with the weights its artists gave
            it (nothing is rigged again). What is drawn is what the game's own resting clip shows.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from . import fighters
from . import native_port as core
from . import rig_wrappers as wrap
from . import rotation_charts, scale_helpers, skin_cost
from echo_ultimate.gamedata import swing

ROOT_CHAIN = ['__engine_Top', 'Trans', '__engine_XRot', '__engine_YRot', 'Rot']
WEIGHTS = (3, 10)                    # a vertex keeps its three heaviest joints, shares in tenths (see skin_cost)
# The longest side a picture of the body may have. A newer game's body brings a picture of 1024 a side (half a
# megabyte in the costume file); a fighter's files share one heap of 6.6 MB with the stage and the other fighters,
# and with every switched part carried the costume is already several times the size of the game's largest.
# At 512 Duck Hunt's is 1.8 MB (2.2 at full size): beside Peach on Pokemon Stadium 0.34 MB is left. None: as it comes.
# This is the side of a PLAIN picture (no see-through, or a cutout), which the game holds at 4 bits a pixel. A
# picture with soft edges is held at 16, so its side is `soft_side` of this: the same bytes, whichever fighter.
PICTURE_SIDE = 512
FORM_PICTURE_SIDE = PICTURE_SIDE // 2   # a form of a fighter of forms: every form's costume is loaded for each player


def picture_side_for(fighter, work=None):
    """The longest side of a plain picture of this fighter's body (`PICTURE_SIDE`), half of it for a form of a fighter
    of forms (`fighters.FORMS`): a player brings every form's costume into the one heap (PORT_CHECKLIST 13.7), so each
    form's pictures take a quarter of the bytes. A form the group's room still has no place for is given a smaller
    side by the port command (`<work>/forms-side.json`, `forms.shrink_side`)."""
    import json as _json
    from . import fighters
    group, _ = fighters.group(fighter)
    if group is None or group == fighter:
        return PICTURE_SIDE
    told = Path(work) / 'forms-side.json' if work else None
    if told is not None and told.exists():
        return int(_json.loads(told.read_text('utf-8'))['side'])
    return FORM_PICTURE_SIDE
REST_CLIP = 'a00defaulteyelid'       # the clip that says what a fighter shows when nothing else says otherwise
DONOR = {'Marth': dict(joint='PlyMars5K_Share_joint', costume='PlMsNr.dat', data='PlMs.dat', clips='PlMsAJ.dat',
                       root='ftDataMars', prefix='PlyMars5K_Share')}


# A weapon of the fighter's that the game keeps as a second model (an article) and puts in a hand in its code: its
# meshes are added to the body as parts on the hold joint, under one node name, and `own_faces.CODE_SHOWN` says when
# they are drawn. 'folder': the article's model folder; 'node': the name its parts go by; 'joint': the body's joint
# it is held at; 'held_at': the article's own joint that sits on it. (Its own clips, a cover that opens, are not
# carried: it is as it rests. Every costume takes the first costume's article.) Written in `fighters.py`
# (`article_parts`), the one place a fighter is written into; Wolf's gun was the first.
ARTICLE_PARTS = fighters.column('article_parts')


def with_articles(fighter, root, work, costume, model_dir):
    """The folder the body's model is read from: the game's own, or, for a fighter with `ARTICLE_PARTS`, a copy of it
    under <work>/merged/<costume> whose model also holds each article's meshes: moved into the space of the body's
    hold joint (the article's own `held_at` joint laid on it), named `<node>_VIS_O_OBJShape`, with the article's
    own material and pictures under names of their own."""
    import shutil
    import ssbh_data_py as ssbh
    parts = fighters.get(fighter, 'article_parts')
    if not parts:
        return Path(model_dir)
    model_dir = Path(model_dir)
    out = Path(work) / 'merged' / costume
    out.mkdir(parents=True, exist_ok=True)
    for f in model_dir.iterdir():
        if f.is_file() and f.name not in ('model.numshb', 'model.numdlb', 'model.numatb'):
            shutil.copyfile(f, out / f.name)
    mesh = ssbh.mesh_data.read_mesh(str(model_dir / 'model.numshb'))
    modl = ssbh.modl_data.read_modl(str(model_dir / 'model.numdlb'))
    matl = ssbh.matl_data.read_matl(str(model_dir / 'model.numatb'))
    for part in parts:
        art = source_dir(root, fighter) / 'model' / part['folder'] / 'c00'
        if not (art / 'model.numshb').exists():
            from echo_ultimate.gamedata import arc
            arc.extract(root, Path(root) / 'gamedata', arc.listed(root, [f"fighter/{fighter}/model/{part['folder']}/c00/"]))
        skel = ssbh.skel_data.read_skel(str(art / 'model.nusktb'))
        names = [b.name for b in skel.bones]

        def world(i):
            m = np.array(skel.bones[i].transform, dtype=float).T
            up = skel.bones[i].parent_index
            return world(up) @ m if up is not None else m
        held = np.linalg.inv(world(names.index(part['held_at'])))
        a_mesh = ssbh.mesh_data.read_mesh(str(art / 'model.numshb'))
        a_modl = ssbh.modl_data.read_modl(str(art / 'model.numdlb'))
        a_matl = ssbh.matl_data.read_matl(str(art / 'model.numatb'))
        label = {(e.mesh_object_name, e.mesh_object_subindex): e.material_label for e in a_modl.entries}
        prefix = part['node'] + '_'
        used = set()
        for i, o in enumerate(a_mesh.objects):
            if o.bone_influences:
                raise ValueError(f"{part['folder']}: {o.name} is skinned; only parts that ride one joint are carried")
            to = held @ (world(names.index(o.parent_bone_name)) if o.parent_bone_name in names else np.eye(4))

            def moved(data, w, to=to):
                v = np.asarray(data, dtype=float)
                v3 = v[:, :3] @ to[:3, :3].T + (to[:3, 3] if w else 0.0)
                return np.hstack([v3, v[:, 3:]]).astype(np.asarray(data).dtype)
            for attr, w in ((o.positions, True), (o.normals, False), (o.tangents, False), (o.binormals, False)):
                for a in attr:
                    a.data = moved(a.data, w)
            was = (o.name, o.subindex)
            o.name, o.subindex, o.parent_bone_name = f"{part['node']}_VIS_O_OBJShape", i, part['joint']
            mesh.objects.append(o)
            modl.entries.append(ssbh.modl_data.ModlEntryData(o.name, o.subindex, prefix + label[was]))
            used.add(label[was])
        for e in a_matl.entries:
            if e.material_label not in used:
                continue
            e.material_label = prefix + e.material_label
            for tex in e.textures:
                if (art / f'{tex.data}.nutexb').is_file():
                    shutil.copyfile(art / f'{tex.data}.nutexb', out / f'{prefix}{tex.data}.nutexb')
                    tex.data = prefix + tex.data
            matl.entries.append(e)
    mesh.save(str(out / 'model.numshb'))
    modl.save(str(out / 'model.numdlb'))
    matl.save(str(out / 'model.numatb'))
    return out


def source_dir(root, fighter):
    return Path(root) / 'gamedata' / 'fighter' / fighter


# ---- a skeleton over the engine's joint limit ------------------------------------------------------------------------
# The engine holds own_data.MAX_PARTS joints: the game's bones, the engine's own four and every helper. A source whose
# bones leave less than HELPER_ROOM for helpers (Incineroar, 2026-11-13: 143 bones, and 40 helpers asked for: 187)
# is made to fit by two rules that cost no pose, applied only to such a source (the fighters ported before them are
# built as they were):
#   - FOLDED: a bone the skin does not use, or one no clip ever moves off its rest (its skin is then its parent's in
#     every pose), and that the engine binds to none of its places, is folded into the bone above it: its children
#     hang from that bone with its rest laid into theirs, its skin weights go to that bone, and a script that names
#     it is given that bone. Every clip is laid on the rig from the source's own world poses, so a child's own track
#     takes in what the folded bone did. (Incineroar: the 14 `_offset` bones between a face bone and its group, the
#     face's groups and `Face`, the six `H_` bones the game turns from `model.nuhlpb` by rule, which the port does not
#     apply either way and which stood at rest on their parents, `ClavicleC`, `LegC`, the toes' unskinned tips.)
#   - EXACT SCALE: a bone that makes up for its parent's scale (`compensate_scale`) needs a helper above it only where
#     that scale is uneven (x, y and z apart). An even scale is undone by the bone's own size track (the world pose is
#     the same matrix); only an uneven one leaves a lean a joint cannot hold. (`scale_exact` in the rig's provenance.)
# What is folded is in the rig's provenance (`folded`: bone -> the bone it went into); a stage that reads the
# source's skeleton (`source_rig`) gets it without them.
#   - BUDGET: still over, the rig gives up what shows least, and says each in its provenance (`over_limit`): first the
#     turn helpers of bones the skin does not use (a held item or a held victim may turn the long way between two
#     frames: on whole frames it is where the game puts it), then it folds LEAVES that carry the least skin (their
#     weights summed; the bones under the head last: the face is looked at), one at a time, until it fits. A folded
#     leaf that moves is a STAND-IN: its part rides the bone above it as it rests there. (Incineroar: the belt's
#     flame tongues, which the clips flicker by scaling them, stand still; a tuft of the tail; finger tips.)
HELPER_ROOM = 15          # helpers a source is given room for before the rules above are used (preflight's "CLOSE")
FOLD_STILL = 1e-4         # a bone whose every track is its rest within this (place, quaternion, size) never moves
UNEVEN = 1e-4             # a parent's size whose x, y and z differ by more than this is uneven
# the engine's limit and its own joints, as own_data.MAX_PARTS and preflight.ENGINE_JOINTS say (a test holds them
# together): not imported, so that the rig's kept-or-made key does not take in the later steps' code
MAX_PARTS = 140           # ftparts.c:28
ENGINE_JOINTS = 4         # __engine_Top, __engine_XRot, __engine_YRot, __engine_ExtraMotion


def tight(source_joints):
    """Whether a source of this many bones gets the two rules above."""
    return source_joints + ENGINE_JOINTS + HELPER_ROOM > MAX_PARTS


def _skin_share(fighter, root):
    """{bone: how much of the first costume's skin it carries (its weights summed over the vertices; a part rigidly on
    a bone counts each vertex whole)}. A bone not in it carries none."""
    import ssbh_data_py as ssbh
    mesh = ssbh.mesh_data.read_mesh(str(source_dir(root, fighter) / 'model' / 'body' / 'c00' / 'model.numshb'))
    out = {}
    for o in mesh.objects:
        if o.parent_bone_name:
            out[o.parent_bone_name] = out.get(o.parent_bone_name, 0.0) + len(o.positions[0].data)
        for inf in o.bone_influences:
            got = sum(float(w.vertex_weight) for w in inf.vertex_weights)
            if got > 0:
                out[inf.bone_name] = out.get(inf.bone_name, 0.0) + got
    return out


def _skinned(fighter, root):
    """The bones the first costume's skin hangs any vertex on (a weight, or a part rigidly on a bone)."""
    return set(_skin_share(fighter, root))


def fold_plan(fighter, root, source, raws, bound, swung=()):
    """{bone: the kept bone it is folded into} for a source over the limit (the FOLDED rule above). `source`: the
    source rig; `raws`: every clip as read ({stem: RawSource}); `bound`: the bones the engine binds a place to;
    `swung`: bones of the swing chains."""
    skinned = _skinned(fighter, root)
    moves, uneven = set(), set()
    for raw in raws.values():
        for j, tr in raw.tracks.items():
            b = raw.bind[j]
            sc = np.linalg.norm(b[:3, :3], axis=0)
            from scipy.spatial.transform import Rotation
            q0 = Rotation.from_matrix(b[:3, :3] / sc).as_quat()
            q = np.asarray(tr.q, dtype=float)
            turned = np.minimum(np.abs(q - q0).max(axis=-1), np.abs(q + q0).max(axis=-1)).max()
            if (np.abs(np.asarray(tr.t) - b[:3, 3]).max() > FOLD_STILL or turned > FOLD_STILL
                    or np.abs(np.asarray(tr.s) - sc).max() > FOLD_STILL):
                moves.add(j)
            s = np.asarray(tr.s, dtype=float)
            if (s.max(axis=1) - s.min(axis=1)).max() > UNEVEN:
                uneven.add(j)
    kids = {}
    for j in source.order:
        kids.setdefault(source.parent[j], []).append(j)
    keep = set(ROOT_CHAIN) | set(bound) | set(swung)
    folded = {}
    for j in source.order:
        if j in keep or source.parent[j] is None:
            continue
        if j in skinned and j in moves:
            continue
        if kids.get(j) and j in uneven:
            continue                                    # (its children would lean under it)
        folded[j] = None
    for j in folded:                                    # into the nearest bone above that is kept
        up = source.parent[j]
        while up in folded:
            up = source.parent[up]
        folded[j] = up
    return folded


def fold_rig(source, folded):
    """The source rig less the folded bones: each kept bone hangs from the nearest kept bone above it, at the same
    rest place in the world."""
    from .rig_benchmark import rotation_angles
    if not folded:
        return source
    order = [j for j in source.order if j not in folded]
    parent, rest = {}, {}
    for j in order:
        up = source.parent[j]
        while up in folded:
            up = folded[up]
        parent[j] = up
        local = source.world[j] if up is None else np.linalg.solve(source.world[up], source.world[j])
        size = np.linalg.norm(local[:3, :3], axis=0)
        rest[j] = dict(r=[float(v) for v in rotation_angles(local[:3, :3] / size)],
                       t=[float(v) for v in local[:3, 3]], s=[float(v) for v in size])
    rig = core.rig_from_meta(dict(order=order, parent=parent, rest=rest))
    for j in order:
        if not np.allclose(rig.world[j], source.world[j], atol=1e-6, rtol=0):
            raise ValueError(f'folding moved the rest place of {j}')
    return rig


def source_rig(skel_path, frozen=None):
    """The source's skeleton as the frozen rig keeps it: less the bones the rig folded (`frozen`'s provenance)."""
    import ssbh_data_py as ssbh
    from .ultimate import skeleton_metadata
    source = core.rig_from_meta(skeleton_metadata(ssbh.skel_data.read_skel(str(skel_path))))
    return fold_rig(source, ((frozen or {}).get('provenance') or {}).get('folded') or {})


def even_scale(raws, compensated):
    """Of the bones that make up for their parent's scale, those whose parent's scale is even in every clip where
    they do (the EXACT SCALE rule above): they need no helper."""
    out = set(compensated)
    for raw in raws.values():
        for j, tr in raw.tracks.items():
            if j in out and tr.compensate_scale:
                up = raw.tracks.get(raw.parent[j])
                if up is not None:
                    s = np.asarray(up.s, dtype=float)
                    if (s.max(axis=1) - s.min(axis=1)).max() > UNEVEN:
                        out.discard(j)
    return out


def freeze(fighter, root, work, stems=None, threshold=0.2, grid=4, directions=128, log=print):
    """Stage 1. -> (the frozen rig, where it was written). `stems`: the clips the rig must be able to play (all of the
    fighter's body clips when not given); their poses decide which joints need a helper."""
    import ssbh_data_py as ssbh
    from . import batch_evaluation as batch
    from . import rig_benchmark as bench
    from .source_preflight import ANY_BONE, RawSource
    from .ultimate import skeleton_metadata
    src = source_dir(root, fighter)
    skel_path = src / 'model' / 'body' / 'c00' / 'model.nusktb'
    motion = src / 'motion' / 'body' / 'c00'
    stems = sorted(stems or (p.stem for p in motion.glob('*.nuanmb')))
    source = core.rig_from_meta(skeleton_metadata(ssbh.skel_data.read_skel(str(skel_path))))

    # which joints make up for their parent's scale: the helper rig has to exist before a clip can be laid on it
    compensated, sanitized, raws, unread = set(), {}, {}, {}
    for stem in stems:
        try:
            # (a track for a bone the skeleton lacks is passed over, not a reason to refuse: source_preflight.ANY_BONE)
            raw = RawSource.from_files(skel_path, motion / f'{stem}.nuanmb', allow_unbound=ANY_BONE)
            fixed = core.sanitize_scale(raw)
        except Exception as exc:                        # a clip the reader refuses is named, not passed over
            unread[stem] = str(exc)[:200]
            continue
        if fixed:
            sanitized[stem] = fixed
        comp = sorted(j for j, tr in raw.tracks.items() if tr.compensate_scale)
        compensated.update(comp)
        raws[stem] = raw
    log(f'    {len(raws)} clips read, {len(unread)} refused; joints that make up for a parent\'s scale: '
        f'{sorted(compensated) or "none"}')
    # a source over the engine's limit: fold the bones that cost no pose, and give a helper only for an uneven scale
    folded, exact, keep, over_limit = {}, set(), set(), []
    if tight(len(source.order)):
        bound = {b for b in fighters.bindings(fighter, source.order, source.parent, source.world)[0].values() if b}
        swung_bones = set()
        for c in (swing.read(motion, source.order) or {}).get('chains', []):
            j = c.get('end')
            while j is not None:
                swung_bones.add(j)
                j = None if j == c.get('start') else source.parent.get(j)
        keep = set(ROOT_CHAIN) | bound | swung_bones
        folded = fold_plan(fighter, root, source, raws, bound, swung_bones)
        source = fold_rig(source, folded)
        compensated = {j for j in compensated if j not in folded}
        exact = even_scale(raws, compensated)
        compensated -= exact
        log(f'    over the limit ({len(source.order) + len(folded)} bones): {len(folded)} folded into the bone above '
            f'them ({sorted(folded)}); {len(exact)} make up for an even scale by their own size, no helper '
            f'({sorted(exact)})')
    scaled = scale_helpers.extend_rig(source, sorted(compensated))

    # every clip's poses, on the helper rig, between frames as well as on them
    domains = []
    for i, (stem, raw) in enumerate(raws.items(), 1):
        times = bench.frame_grid(raw.end, grid) if raw.end else np.zeros(1)
        reference = {j: w for j, w in batch.raw_worlds(raw, times).items() if j in scaled.original_order}
        parent_scales = {j: np.array([raw.parts(raw.parent[j], float(f))[2] if raw.parent[j] in raw.tracks
                                      else np.ones(3) for f in times]) for j in compensated}
        domains.append(scale_helpers.expand_worlds(scaled, reference, parent_scales, set(compensated)))
        if i % 60 == 0 or i == len(raws):
            log(f'    sampled {i}/{len(raws)} clips')
    raws.clear()
    # a joint whose local transform is sheared cannot be given a chart (see the campaign's freeze.py)
    sheared = {}
    for worlds in domains:
        for j in scaled.order:
            par = scaled.parent[j]
            loc = np.linalg.solve(worlds[par], worlds[j]) if par is not None else worlds[j]
            sc = np.linalg.norm(loc[:, :3, :3], axis=1)
            if np.any(sc < 1e-10):
                sheared[j] = 'SINGULAR_SCALE'
                continue
            r = loc[:, :3, :3] / sc[:, None, :]
            dev = float(np.abs(np.swapaxes(r, 1, 2) @ r - np.eye(3)).max())
            if dev > 1e-7 or float(np.linalg.det(r).min()) < 0:
                sheared[j] = max(sheared[j] if isinstance(sheared.get(j), float) else 0.0, dev)
    # the parts the game swings by physics keep clear of helpers: a helper inside a chain would break it
    swung = swing_plan(scaled, swing.read(motion, source.order))
    in_chain = {j for c in swung['chains'] for j in c['joints']}
    candidates = SimpleNamespace(order=[j for j in scaled.order if j not in sheared and j not in in_chain],
                                 parent=scaled.parent)
    proposed = rotation_charts.choose(candidates, domains, threshold=threshold, directions=directions)
    charts, rejected = {}, []
    for j, row in proposed.items():
        if j in set(core.ENGINE_PARENTS):
            rejected.append(dict(joint=j, reason='ENGINE_ROOT', before=row['before'], after=row['after']))
        elif row['after'] < threshold:
            rejected.append(dict(joint=j, reason='NO_CLEARANCE', before=row['before'], after=row['after']))
        else:
            charts[j] = row
    for c in swung['chains']:                           # ... and a chain's first joint stands straight on a helper
        if c['on_helper']:
            charts[c['joints'][0]] = dict(rotation=rotation_charts.euler_xyz(scaled.rest[c['joints'][0]]['r']),
                                          reason='SWING_ROOT')
    if keep:
        # the BUDGET rule (above): the rig is the bones, a helper for each uneven scale and each chart, and the engine's
        # own four joints (three over the root chain, one for extra motion)
        over = lambda: len(source.order) + len(compensated) + len(charts) + ENGINE_JOINTS - MAX_PARTS
        share = _skin_share(fighter, root)
        # (the face is looked at: the bones under the head go last, whatever little skin each carries; Incineroar's
        # upper lip went first without this)
        head = fighters.bindings(fighter, source.order, source.parent, source.world)[0].get('headN')
        face = set()
        for k in source.order:
            up = source.parent[k]
            while up is not None and up != head:
                up = source.parent[up]
            if up is not None:
                face.add(k)
        for j in sorted(charts):
            if over() > 0 and j not in share and charts[j].get('reason') != 'SWING_ROOT':
                rejected.append(dict(joint=j, reason='OVER_LIMIT', before=charts[j].get('before'),
                                     after=charts[j].get('after')))
                over_limit.append(f'{j}: its turn helper (the skin does not use it)')
                del charts[j]
        while over() > 0:
            parents = set(source.parent.values())
            leaves = [j for j in source.order if j not in parents and j not in keep and j in share]
            if not leaves:
                break
            j = min(leaves, key=lambda k: (k in face, share[k], source.order.index(k)))
            over_limit.append(f'{j}: folded into {source.parent[j]} (a leaf carrying {share[j]:.1f} of the skin; it moves '
                              'in the clips, so it is a STAND-IN: it rides that bone as it rests there)')
            folded[j] = source.parent[j]
            source = fold_rig(source, {j: source.parent[j]})
            charts.pop(j, None)
            compensated.discard(j)
        for j in folded:                                # (a bone folded into one folded after it: the bone above)
            while folded[j] in folded:
                folded[j] = folded[folded[j]]
        if over_limit:
            log(f'    still over the limit: gave up {len(over_limit)}: ' + '; '.join(over_limit))
        scaled = scale_helpers.extend_rig(source, sorted(compensated))
    charted = rotation_charts.extend_rig(scaled, charts)
    helper_meta = dict(order=list(charted.order), parent=dict(charted.parent),
                       rest={j: dict(r=list(v['r']), t=list(v['t']), s=list(v['s'])) for j, v in charted.rest.items()})
    wrapped = wrap.insert_identity_parents(helper_meta, core.ENGINE_PARENTS)
    wrapped['order'].append(core.EXTRA_MOTION)
    wrapped['parent'][core.EXTRA_MOTION] = '__engine_Top'
    wrapped['rest'][core.EXTRA_MOTION] = dict(r=[0., 0., 0.], t=[0., 0., 0.], s=[1., 1., 1.])
    frozen = wrap.canonical_jobj_order(wrapped)
    rig = core.rig_from_meta(frozen)
    for j in source.order:
        if not np.allclose(rig.world[j], source.world[j], atol=1e-9, rtol=0):
            raise ValueError(f'{fighter}: a helper moved the rest place of {j}')
    if rig.order[:5] != ROOT_CHAIN:
        raise ValueError(f'{fighter}: the root chain is {rig.order[:5]}, not {ROOT_CHAIN}')
    depth = max(len(_ancestors(frozen, j)) for j in frozen['order'])
    frozen['provenance'] = dict(
        fighter=fighter, source_skeleton=str(skel_path), source_joints=len(source.order), clips_sampled=len(domains),
        clips_refused=unread, chart_sample_grid=f'1/{grid}', scale_helpers=sorted(compensated),
        chart_helpers=sorted(charts),                   # (the swing chains' helpers are among them: one mechanism)
        swing_helpers=sorted(j for j in charts if charts[j].get('reason') == 'SWING_ROOT'),
        scale_sanitized=sanitized, chart_rejected=rejected, chart_threshold=threshold,
        chart_directions=directions, depth=depth,
        shear_excluded={k: (round(v, 5) if isinstance(v, float) else v) for k, v in sheared.items()},
        folded=folded, scale_exact=sorted(exact), over_limit=over_limit)
    for c in swung['chains']:                           # a chain is a line of first children, numbered in a row
        at = [frozen['order'].index(j) for j in c['joints']]
        if at != list(range(at[0], at[0] + len(at))):
            raise ValueError(f"{fighter}: the swing chain {c['joints']} is not a line of first children "
                             f"(joints {at}); the game could not swing it")
    frozen['swing'] = swung
    out = Path(work) / 'rig' / f'rig-{fighter}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(frozen, indent=2), 'utf-8')
    return frozen, out


STIFF = 100.0        # a swing joint pulled this hard to its clip's pose is left to the clip (a reading of 'goalstrength')
TWIST = 1e-3         # radians a swung joint may be turned about its own length at rest


def swing_plan(rig, swung):
    """The source's swing chains, as Melee can hold them. -> {'chains': [...], 'spheres', 'ellipsoids', 'capsules'}.

    Melee swings a line of joints, each the first child of the one before; the last joint of the line is only
    carried. A joint that is being swung takes nothing from its clip. And at rest a swung joint must not be turned
    about its own length: the game takes a tenth of that turn away every frame. So here:
      - a joint the source holds stiffly to its clip (`STIFF`) at the head of a chain stays with the clip;
      - the chain ends on the first child of its last joint (a chain whose last joint has no child gives that
        joint up to be the end);
      - a joint that is turned about its length at rest starts a chain of its own, standing straight on a helper
        that holds its rest turn ('on_helper'); the chain before it ends on that helper.
    Each chain: 'joints' (names, swung ones then the end), 'numbers' (the source's numbers for each swung joint),
    'on_helper'."""
    out = dict(chains=[], spheres=[], ellipsoids=[], capsules=[])
    if not swung:
        return out
    for key in ('spheres', 'ellipsoids', 'capsules'):
        out[key] = swung[key]
    kids = {}
    for j in rig.order:
        kids.setdefault(rig.parent[j], []).append(j)

    def twisted(joint, child):
        axis = int(np.argmax(np.abs(np.asarray(rig.rest[child]['t'], dtype=float))))
        return abs(float(rig.rest[joint]['r'][axis])) > TWIST
    for chain in swung['chains']:
        path = [chain['end']]
        while path[-1] != chain['start']:
            up = rig.parent.get(path[-1])
            if up is None:
                raise ValueError(f"swing chain {chain['start']}: its end {chain['end']} is not below its start")
            path.append(up)
        path.reverse()
        numbers = dict(zip(path, chain['joints']))
        while path and numbers.get(path[0], {}).get('goalstrength', 0.0) >= STIFF:
            path.pop(0)
        if not path:
            continue
        tip = (kids.get(path[-1]) or [None])[0]
        if tip is None:                                 # nothing below to end on: the last joint is the end
            tip = path.pop()
            if not path:
                continue
        line = path + [tip]
        start = 0
        for i in range(1, len(path) + 1):               # cut where a swung joint is twisted at rest
            if i == len(path) or twisted(path[i], line[i + 1]):
                part = line[start:i + 1]
                out['chains'].append(dict(joints=part, numbers=[numbers.get(j, {}) for j in part[:-1]],
                                          on_helper=twisted(part[0], part[1])))
                start = i
    for a, b in zip(out['chains'], out['chains'][1:]):  # a chain cut for a twist ends on the next one's helper
        if a['joints'][-1] == b['joints'][0] and b['on_helper']:
            a['joints'][-1] = '__chart_before_' + b['joints'][0]
    return out


def _ancestors(meta, joint):
    out = []
    while meta['parent'].get(joint) is not None:
        joint = meta['parent'][joint]
        out.append(joint)
    return out


def shown_at_rest(root, fighter, mesh):
    """The parts of the game's model that are drawn at rest: [{'name', 'subindex'}], in the model's own order. The
    game hides and shows whole parts by name, clip by clip (a blinking face, open wings); the resting clip's first
    frame says which are up when nothing else has spoken. A part no clip ever names is always drawn."""
    import ssbh_data_py as ssbh
    motion = source_dir(root, fighter) / 'motion' / 'body' / 'c00'
    named = {}
    for path in [motion / f'{REST_CLIP}.nuanmb'] + sorted(motion.glob('*.nuanmb')):
        if not path.exists():
            continue
        for g in ssbh.anim_data.read_anim(str(path)).groups:
            if 'Visib' in str(g.group_type):
                for n in g.nodes:
                    named.setdefault(n.name, bool(n.tracks[0].values[0]))     # the resting clip is read first
    for n, drawn in ((fighters.get(fighter, 'code_shown') or {}).get('rest') or {}).items():
        named.setdefault(n, bool(drawn))                # (and what the game's code shows and hides at rest)

    def node(name):
        return next((n for n in sorted(named, key=len, reverse=True)
                     if name == n + 'Shape' or name.startswith(n + '_VIS')), None)
    rows = []
    for o in mesh.objects:
        n = node(o.name)
        if n is None or named[n]:
            rows.append(dict(name=o.name, subindex=o.subindex))
    return dict(meshes=rows, rule=f"what {REST_CLIP} shows on its first frame, and every part no clip names")


def mend_normals(mesh, carried):
    """A vertex the game's own model gives no normal (a few in the corners of mouths and eyes that rest hides)
    takes one from the triangles it is a corner of: their normals added up, each by its area; where those have
    no area, from the other corners of the same triangles; failing that, straight up. In place, on the mesh
    objects named in `carried`. -> {object: how many vertices} (what was mended; lighting only, no shape)."""
    done = {}
    for obj in mesh.objects:
        if (obj.name, obj.subindex) not in carried:
            continue
        given = np.asarray(obj.normals[0].data)
        normals = given.astype(float)
        bare = np.where(np.linalg.norm(normals[:, :3], axis=1) < 1e-12)[0]
        if not len(bare):
            continue
        points = np.asarray(obj.positions[0].data, dtype=float)[:, :3]
        faces = np.asarray(obj.vertex_indices).reshape(-1, 3)
        for v in bare:
            mine = faces[(faces == v).any(axis=1)]
            total = sum((np.cross(points[b] - points[a], points[c] - points[a]) for a, b, c in mine), np.zeros(3))
            if np.linalg.norm(total) < 1e-12:
                total = sum((normals[i, :3] for i in set(mine.ravel()) - {v}), np.zeros(3))
            if np.linalg.norm(total) < 1e-12:
                total = np.array([0.0, 1.0, 0.0])
            normals[v, :3] = total / np.linalg.norm(total)
        obj.normals[0].data = normals.astype(given.dtype)
        done[f'{obj.name}/{obj.subindex}'] = int(len(bare))
    return done


def render_flags(dat_path, root_name, donor_costume):
    """The donor costume's own drawing flags, put on the new joints (a bare skeleton file's joints say only that they
    are joints, and the game then draws nothing). The joint that carries the model's pieces is told to draw both solid
    and see-through pieces: the importer hangs every piece on one joint. (See the campaign's stage2.py.)"""
    from vault.echo.subactions import Dat
    from .compat.rig_inventory import costume_inventory
    donor = costume_inventory(Path(donor_costume).read_bytes(), root_name)
    donor_root = donor['joints'][0]['flags']
    others = [j['flags'] for j in donor['joints'][1:] if not j['dobj_offsets']]
    donor_other = max(set(others), key=others.count) if others else donor_root
    blob = Path(dat_path).read_bytes()
    inv, dat = costume_inventory(blob, root_name), Dat(blob)
    XLU, ROOT_XLU = 1 << 19, 1 << 29
    for j in inv['joints']:
        want = donor_root if j['parent'] is None else donor_other
        if j['dobj_offsets']:
            want |= XLU | ROOT_XLU
        dat.set_u32(j['offset'] + 4, j['flags'] | want)
    Path(dat_path).write_bytes(dat.to_bytes())
    after = costume_inventory(Path(dat_path).read_bytes(), root_name)['joints']
    return dict(donor_root=hex(donor_root), donor_other=hex(donor_other), root_after=hex(after[0]['flags']),
                pieces=sum(len(j['dobj_offsets']) for j in after))


def body(fighter, root, work, frozen, donor, donor_dir, log=print, weights=WEIGHTS, costume='c00',
         picture_side='rule'):
    """Stage 2. -> (the costume file, its receipt). `donor_dir` holds the donor's own files (its costume gives the
    joints' drawing flags and the root's name). `weights`: (the most joints a vertex keeps, the parts its shares are
    rounded to), or None to keep the source's own (see `skin_cost`). `costume`: which of the game's costume folders
    the model and its pictures are taken from (the first goes to <work>/body, another to <work>/body-<costume>; its
    files are taken out of the game's archive when they are not on disk yet). `picture_side`: the longest side any
    of the body's pictures may have (None: as the game has them). A costume shares one heap of 6.6 MB with the
    stage and the other fighters' files, and its pictures are the largest thing in it: Duck Hunt's, with every
    part his face switches, is 2.2 MB, of which the dog's one picture of 1024 a side is 0.5 MB (0.13 MB at 512).
    'rule' (not given): `picture_side_for` the fighter."""
    if picture_side == 'rule':
        picture_side = picture_side_for(fighter, work)
    import subprocess
    import ssbh_data_py as ssbh
    from . import compat
    compat.install()
    from core.config import HSDRAW_EXE
    from .compat import smd
    from .rig_archive import build_skeleton, read_skeleton
    from .source_mesh_handoff import prepare
    from .ultimate import skeleton_metadata
    from .ultimate_materials import bake
    names = DONOR[donor]
    out = Path(work) / ('body' if costume == 'c00' else f'body-{costume}')
    out.mkdir(parents=True, exist_ok=True)
    model_dir = source_dir(root, fighter) / 'model' / 'body' / costume
    if not (model_dir / 'model.numshb').exists():
        from echo_ultimate.gamedata import arc
        arc.extract(root, Path(root) / 'gamedata', arc.listed(root, [f'fighter/{fighter}/model/body/{costume}/']))
    model_dir = with_articles(fighter, root, work, costume, model_dir)
    blob, receipt = build_skeleton(frozen, root_name=names['joint'])
    skeleton = out / 'skeleton.dat'
    skeleton.write_bytes(blob)
    stored, _inverse = read_skeleton(blob, frozen['order'])
    if stored['order'] != frozen['order']:
        raise ValueError('the skeleton file does not hold the frozen order')
    mesh = ssbh.mesh_data.read_mesh(str(model_dir / 'model.numshb'))
    # every part the clips ever draw is carried, as pieces of its own: the ones a clip shows and hides are the
    # choices of the fighter's model groups (`own_faces`), and what is drawn at rest is what `shown_at_rest` says
    from . import own_faces
    faces = own_faces.of_fighter(root, fighter)
    carried = own_faces.selection([(o.name, o.subindex) for o in mesh.objects], faces)
    named = own_faces.pieces(carried, faces)
    resting = own_faces.drawn_at_rest(named)
    rest = shown_at_rest(root, fighter, mesh)
    if [carried[i] for i in resting] != [(r['name'], r['subindex']) for r in rest['meshes']]:
        raise ValueError(f"{fighter}: the groups' resting choices are not the parts the resting clip shows")
    selection = dict(meshes=[dict(name=n, subindex=i) for n, i in carried], at_rest=rest['meshes'],
                     rule=f"every part some clip draws; at rest, {rest['rule']}")
    (out / 'selection.json').write_text(json.dumps(selection, indent=1), 'utf-8')
    source_meta = skeleton_metadata(ssbh.skel_data.read_skel(str(model_dir / 'model.nusktb')))
    mended = mend_normals(mesh, set(carried))
    model, handoff = prepare(mesh, source_meta, frozen, selection, uv_convention='hsd_smd',
                             fold=frozen.get('provenance', {}).get('folded'))
    handoff['normals_mended'] = mended
    if weights:
        handoff['weights'] = skin_cost.lighten(model, *weights)
        log(f"  skin weights: {handoff['weights']}")
    body_materials = len(model.materials)
    if body_materials != len(carried):
        raise ValueError(f'{body_materials} materials for {len(carried)} parts: a piece is a part')
    # the low-detail copy is of what is drawn at rest: the shadow's outline does not change with the face
    material = [row['material'] for row in handoff['mesh_groups']]
    # (STAND-IN, for room: the parts rest hides keep half their triangles; said in the receipt)
    handoff['fewer_triangles'] = skin_cost.fewer_hidden(model, {m for i, m in enumerate(material) if i not in set(resting)})
    if handoff['fewer_triangles']:
        before, after = (sum(v[k] for v in handoff['fewer_triangles'].values()) for k in (0, 1))
        log(f"  parts hidden at rest: {before:,} triangles made {after:,} in {len(handoff['fewer_triangles'])} parts")
    low = skin_cost.low_detail(model, {material[i] for i in resting})
    if body_materials + len(low) > own_faces.MOST_PIECES:
        raise ValueError(f'{body_materials + len(low)} pieces: a fighter holds {own_faces.MOST_PIECES}')
    smd_path = out / f'{fighter}.smd'
    smd.save(model, smd_path)
    # a material with a second picture (an iris over a white) is laid over the first, by its own second coordinates
    matl = ssbh.matl_data.read_matl(str(model_dir / 'model.numatb'))
    modl = ssbh.modl_data.read_modl(str(model_dir / 'model.numdlb'))
    chosen = {(r['name'], r['subindex']) for r in selection['meshes']}
    label = {(e.mesh_object_name, e.mesh_object_subindex): e.material_label for e in modl.entries}
    second = {e.material_label for e in matl.entries if any(t.param_id.name == 'Texture1' for t in e.textures)}
    layers = {}
    from .material_bake import one_tile
    for o in mesh.objects:
        if (o.name, o.subindex) in chosen and label.get((o.name, o.subindex)) in second:
            sets = [t.name for t in o.texture_coordinates]
            first = next((t.data for t in o.texture_coordinates if t.name == 'map1'), o.texture_coordinates[0].data)
            # (a white whose coordinates are whole repeats off the picture is moved onto it for the bake, if every
            # mesh of the material lies in one repeat: else the iris is laid nowhere)
            fits = one_tile(np.asarray(first, float)[:, :2]) and layers.get(label[o.name, o.subindex], {}).get('base_repeat', True)
            layers[label[o.name, o.subindex]] = dict(texture='Texture1', uv_set='uvSet' if 'uvSet' in sets else sets[-1],
                                                     base_repeat=fits)
    handoff['textures'] = bake(model_dir, mesh, selection, out, None, color_layers=layers,
                               max_texture_dimension=picture_side)
    handoff['small_pictures'] = skin_cost.small_pictures(
        out, [m for i, m in enumerate(material) if i not in set(resting)], [material[i] for i in resting])
    if picture_side:
        # (by the picture's stored format, for every fighter: Wolf's fur was the first to need it)
        soft_side = skin_cost.soft_side(picture_side)
        handoff['soft_pictures'] = skin_cost.soft_pictures(out, material, soft_side)
        if handoff['soft_pictures']:
            log(f"  pictures with soft edges (held at {skin_cost.SOFT_BITS} bits a pixel, a plain one at "
                f"{skin_cost.PLAIN_BITS}), made {soft_side} a side at most: {handoff['soft_pictures']}")
    skin_cost.low_pictures(out, low)
    imported = out / f'{fighter}.dat'
    r = subprocess.run([str(HSDRAW_EXE), '--model', 'import', str(skeleton), names['joint'], str(smd_path), str(imported)],
                       capture_output=True, text=True, timeout=3600)
    (out / 'import.log').write_text(r.stdout + r.stderr, 'utf-8')
    if r.returncode or not imported.exists():
        raise RuntimeError(f'the model import failed ({r.returncode}): see {out / "import.log"}')
    handoff['render_flags'] = render_flags(imported, names['joint'], Path(donor_dir) / names['costume'])
    regrouped, groups = skin_cost.regroup(imported.read_bytes())
    imported.write_bytes(regrouped)
    handoff['groups'] = dict(before=groups['before'], after=groups['after'],
                             left=[r for r in groups['pieces'] if 'left' in r])
    handoff['bytes'] = imported.stat().st_size
    split = skin_cost.pieces(imported.read_bytes(), body_materials, resting)
    # 'high': the pieces that are always drawn; 'groups': the choices of each group of switched parts, 'rest' the
    # choice each starts on; 'low': the low-detail copy of what is drawn at rest
    handoff['pieces'] = dict(high=named['high'], low=split['low'], groups=named['groups'], rest=named['rest'])
    from . import own_opacity
    handoff['pieces'] = own_opacity.low_lists(handoff['pieces'], faces)
    handoff['faces'] = faces
    handoff['skin'] = dict(body=skin_cost.cost(imported.read_bytes(), resting),
                           low_detail=skin_cost.cost(imported.read_bytes(), split['low']),
                           every_part=skin_cost.cost(imported.read_bytes(), split['high']))
    log(f"  the skin each frame: {handoff['skin']}")
    handoff['parts'] = len(selection['meshes'])
    (out / 'receipt.json').write_text(json.dumps(handoff, indent=1, default=str), 'utf-8')
    return imported, handoff


def materials(costume_path, fighter_dat, donor, out):
    """Stage 2b. The donor's code animates textures by number (a blink, a hurt face); a costume built from another
    game has no texture animations at all, and the game stops when one is asked for. So the costume gets an empty
    animation tree over its joints, and still animations on the texture numbers the fighter's data names (the data
    stage has already pointed those at textures this costume has). `fighter_dat` is the fighter file as rewritten for
    this rig. -> (the costume file, its receipt)."""
    from . import compat
    compat.install()
    from core.config import HSDRAW_EXE
    from . import costume as cos
    costume_path, out = Path(costume_path), Path(out)
    payload, tree = cos.add_empty_material_tree(costume_path.read_bytes())
    with_tree = out.with_name(out.stem + '_tree.dat')
    with_tree.write_bytes(payload)
    if out.exists():
        out.unlink()
    receipt = cos.static_materials(with_tree, fighter_dat, DONOR[donor]['joint'], out, HSDRAW_EXE)
    return out, dict(tree=tree, static=receipt)


def lookup(fighter, frozen, work):
    """Stage 3. Which joint is which, for the engine: its 54 named places (hip, head, the hands, the feet, ...)
    bound to this rig's joints (`fighters.bindings`: by the game's own bone names, the thumb measured on the rest
    pose; a fighter needs no table of its own). -> (the table, where it was written)"""
    from . import compat
    compat.install()
    from .compat.bone_lookup import SLOTS, compile_lookup
    bound, source, notes = fighters.bindings(fighter, frozen['order'], frozen['parent'], core.rig_from_meta(frozen).world)
    missing = [slot for slot in fighters.NEEDED if not bound.get(slot)]
    if missing:
        raise ValueError(f"{fighter}: the rig has no joint for {missing}, which the engine turns or reads on every "
                         f"fighter (bound {source}). Name the joint that stands for each in the fighter's `bindings` "
                         'in fighter_port/fighters.py')
    table = compile_lookup(frozen['order'], [bound.get(slot) for slot in SLOTS])
    table['bound_by'] = dict(source=source, notes=notes)
    out = Path(work) / 'rig' / 'lookup.json'
    out.write_text(json.dumps(table, indent=1), 'utf-8')
    return table, out


# The rig and the body are most of `prepare` (Wolf's rig is half a minute, the stage a minute and a half to three),
# and every failure after them (the joint table, the fighter data, the texture animations) cost both again: four
# runs of Wolf's trial. So each leaves a note of what it was made from (`made_from`), and `prepare` keeps what is on
# disk while all of that is the same: the game's files it reads, the donor's costume, this fighter's values in
# fighters.py that it reads, the libraries' versions, and its code (this file less the steps after it, each of this
# repo's modules that imports in turn, at any depth, the app's modules among them, the HSDRaw program). Any
# difference makes it again. Delete <work>/rig/made-from.json or <work>/body/made-from.json to make one again anyway.
AFTER_THE_BODY = ('lookup', 'materials', 'prepare')                     # this file's functions that neither step runs
THE_BODYS_OWN = ('body', 'with_articles', 'shown_at_rest', 'mend_normals', 'render_flags', '_opacity_bindings')   # ... nor the rig
NOT_READ_BY_THE_BODY = ('bindings', 'item_hold', 'taunt', 'code_timed_hits', 'code_timed_effects', 'lopsided')
APP_PACKAGES = ('shared', 'randall', 'vault', 'core')
LIBRARIES = ('ssbh_data_py', 'numpy', 'scipy', 'pillow', 'pyfqmr')
REPO = Path(__file__).resolve().parents[1]


def _hash_files(*paths):
    """One hash of these files' names and bytes (a folder: every file under it), in a fixed order."""
    import hashlib
    h = hashlib.sha1()
    for p in map(Path, paths):
        if not p.exists():
            h.update(f'(no {p.name})'.encode())
            continue
        for f in sorted(f for f in p.rglob('*') if f.is_file()) if p.is_dir() else [p]:
            h.update((f.relative_to(p).as_posix() if p.is_dir() else p.name).encode() + b'\0')
            h.update(f.read_bytes())
    return h.hexdigest()


def _imports(tree, package):
    """Every module name an AST imports, anywhere in it; relative ones read against `package`. A name imported from a
    package may be a module of it (`from . import x`), so it is given both ways."""
    import ast
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ''
            if node.level:
                parts = package.split('.')
                base = '.'.join(parts[:len(parts) - node.level + 1] + ([node.module] if node.module else []))
            names += [base] + [f'{base}.{a.name}' for a in node.names]
    return names


def _code(leave_out):
    """The code a step runs, as {module: hash}: this file without the functions in `leave_out`, then each of this
    repo's modules it imports, in turn, at any depth, and the files of the app's modules among them (not followed
    further). fighters.py is left to `made_from`, which takes the values the step reads, so a value written there for
    a later step (a binding, a lopsided pair) does not make the rig and the body again."""
    import ast
    import hashlib
    import importlib
    from . import compat
    compat.install()
    tree = ast.parse(Path(__file__).read_text('utf-8'))
    tree.body = [n for n in tree.body if not (isinstance(n, ast.FunctionDef) and n.name in leave_out)]
    got = {__name__: hashlib.sha1(ast.dump(tree).encode()).hexdigest()}
    todo, seen = _imports(tree, __package__), {__name__, fighters.__name__}
    while todo:
        name = todo.pop()
        if name in seen or not name:
            continue
        seen.add(name)
        path = REPO.joinpath(*name.split('.'))
        path = path / '__init__.py' if (path / '__init__.py').is_file() else path.with_suffix('.py')
        if path.is_file():
            text = path.read_text('utf-8')
            got[name] = hashlib.sha1(text.encode()).hexdigest()
            todo += _imports(ast.parse(text), name if path.name == '__init__.py' else name.rpartition('.')[0])
        elif name.split('.')[0] in APP_PACKAGES:
            try:
                file = getattr(importlib.import_module(name), '__file__', None)
            except Exception:                       # a name in a module (`from core.config import X`), not a module
                continue
            if file:
                got[name] = _hash_files(file)
    return got


def _opacity_bindings(root, fighter):
    from . import own_opacity
    return (own_opacity.read(root, fighter) or {}).get('bindings', [])


def made_from(step, fighter, root, work, donor=None, donor_dir=None):
    """What a step of `prepare` is made from, as {part: hash}: 'rig' (the skeleton and every clip of the fighter's
    body) or 'body' (its model and the parts it carries, the clips that say what is drawn, the rig, the donor's
    costume, the HSDRaw program). Two notes that are equal mean the step would make the same files."""
    import importlib.metadata
    src = source_dir(root, fighter)
    motion = src / 'motion' / 'body' / 'c00'
    note = {}
    for lib in LIBRARIES:
        try:
            note[f'library {lib}'] = importlib.metadata.version(lib)
        except Exception:
            note[f'library {lib}'] = None
    if step == 'rig':
        note['game files'] = _hash_files(src / 'model' / 'body' / 'c00' / 'model.nusktb', motion)
        note['code'] = _code(AFTER_THE_BODY + THE_BODYS_OWN)
        return note
    from . import compat
    compat.install()
    from core.config import HSDRAW_EXE
    note['opacity bindings'] = _opacity_bindings(root, fighter)
    articles = [src / 'model' / p['folder'] / 'c00' for p in fighters.get(fighter, 'article_parts') or ()]
    note['game files'] = _hash_files(src / 'model' / 'body' / 'c00', motion, *articles)
    note['rig'] = _hash_files(Path(work) / 'rig' / f'rig-{fighter}.json')
    note['donor'] = [donor, _hash_files(Path(donor_dir) / DONOR[donor]['costume'])]
    exe = Path(HSDRAW_EXE)
    note['HSDRaw'] = [str(exe), exe.stat().st_size, exe.stat().st_mtime_ns] if exe.exists() else None
    note['values'] = {k: repr(v) for k, v in sorted(fighters.FIGHTERS.get(fighter, {}).items())
                      if k not in NOT_READ_BY_THE_BODY}
    note['settings'] = repr((WEIGHTS, picture_side_for(fighter, work)))
    note['code'] = _code(AFTER_THE_BODY)
    return note


def _kept(step, folder, wanted, now, log):
    """Whether the step's files in `folder` can be kept: they are all there and their note is `now`. Says which."""
    import json as _json
    saved = Path(folder) / 'made-from.json'
    was = _json.loads(saved.read_text('utf-8')) if saved.exists() else None
    if was == now and all(Path(f).exists() for f in wanted):
        log(f'    kept: made from the same files, code and settings ({saved})')
        return True
    if was is None:
        log(f'    made: no note of what the {step} on disk was made from')
    else:
        changed = sorted(k for k in set(was) | set(now) if was.get(k) != now.get(k))
        if 'code' in changed:
            changed.remove('code')
            changed.append('code: ' + ', '.join(sorted(k for k in set(was.get('code') or {}) | set(now['code'])
                                                       if (was.get('code') or {}).get(k) != now['code'].get(k))))
        log(f'    made again: {"; ".join(changed) or "a file of it is gone"}')
    return False


def _note(folder, note):
    Path(folder).mkdir(parents=True, exist_ok=True)
    (Path(folder) / 'made-from.json').write_text(json.dumps(note, indent=1), 'utf-8')


def put_costume(made, dest):
    """Copy the first costume into the package only when its bytes are new. -> whether it was written.
    The art stage refuses pictures older than the costume files (they would show a body the disc no longer
    holds); a rerun of `prepare` that makes the same bytes must not make the round's pictures stale (Slap City's
    Ittle: prepare run again for a receipt rewrote the same costume, and the art stage asked for another round)."""
    made, dest = Path(made), Path(dest)
    if dest.exists() and dest.read_bytes() == made.read_bytes():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copyfile(made, dest)
    return True


def prepare(fighter, root, work, donor, donor_dir, log=print):
    """Stages 1 to 4, in the order they lean on each other: the rig, the body on it, the engine's joint table, the
    donor's fighter data rewritten for the rig, and the costume's texture animations (which need that data).
    The rig and the body are kept while what they are made from is the same (`made_from`).
    -> {'rig', 'costume', 'data', 'lookup'}: the files a clip stage and a packaging stage start from."""
    from . import own_data
    from echo_ultimate.gamedata import arc
    work = Path(work)
    # the game's files first: this stage reads them straight off the disk, and a fighter nobody has ported yet has
    # none there (Wolf's first run died here in seven seconds)
    have, listed = arc.fetch_fighter(root, fighter)
    log(f'  game files: {have} of {listed} for {fighter}')
    if not have:
        raise RuntimeError(f"the game's archive lists no files for a fighter named {fighter!r} (the name is the "
                           f"folder's under fighter/ in {Path(root) / 'Hashes_FullPath'})")
    log('  rig')
    rig_path = work / 'rig' / f'rig-{fighter}.json'
    note = made_from('rig', fighter, root, work)
    if _kept('rig', work / 'rig', [rig_path], note, log):
        frozen = json.loads(rig_path.read_text('utf-8'))
    else:
        (work / 'rig' / 'made-from.json').unlink(missing_ok=True)       # (a run stopped half way keeps no note)
        frozen, rig_path = freeze(fighter, root, work, log=log)
        _note(work / 'rig', note)
    log(f"    {len(frozen['order'])} joints (the engine holds {own_data.MAX_PARTS}), {frozen['provenance']['depth']} "
        f"deep (it walks {own_data.MAX_DEPTH - 1}); swing chains: {[c['joints'][0] for c in frozen['swing']['chains']]}")
    # the joint table next: it is seconds, and the body after it is minutes
    table, lookup_path = lookup(fighter, frozen, work)
    log(f"  joint table: bound {table['bound_by']['source']}" + ''.join(f'; {n}' for n in table['bound_by']['notes']))
    log('  body')
    plain = work / 'body' / f'{fighter}.dat'
    note = made_from('body', fighter, root, work, donor, donor_dir)
    if _kept('body', work / 'body', [plain, work / 'body' / 'receipt.json'], note, log):
        receipt = json.loads((work / 'body' / 'receipt.json').read_text('utf-8'))
    else:
        (work / 'body' / 'made-from.json').unlink(missing_ok=True)
        plain, receipt = body(fighter, root, work, frozen, donor, donor_dir, log=log)
        _note(work / 'body', note)
    log(f"    {receipt['parts']} parts, {receipt['bytes']:,} bytes")
    log('  fighter data')
    if own_data.main(['--fighter', fighter, '--root', str(root), '--work', str(work), '--donor', donor,
                      '--donor-dir', str(donor_dir)]):
        raise RuntimeError('the fighter data did not come out right: see its report')
    data = work / 'data' / DONOR[donor]['data']
    log('  texture animations')
    costume, _ = materials(plain, data, donor, work / 'body' / f'{fighter}_static.dat')
    from . import own_opacity
    own_opacity.costume(costume, root, fighter, receipt, DONOR[donor]['joint'])
    # where the first costume's bytes are: the costumes stage stops on one that is too large for a match's heap, and
    # here it is known minutes sooner
    kinds = skin_cost.bytes_by_kind(costume.read_bytes())
    for line in skin_cost.kind_lines('  the first costume', kinds):
        log(line)
    stop = skin_cost.too_large('the first costume', kinds)
    if stop:
        log('  THE COSTUMES STAGE WILL STOP ON THIS: ' + stop)
    return dict(rig=rig_path, costume=costume, data=data, lookup=lookup_path)
