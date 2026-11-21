"""Held weapons that appear per move: an Ultimate fighter's lance, axe or bow on a
Melee donor that only has a sword.

In Ultimate these are separate models, shown while a move runs. Melee has a
data-only switch for which of a fighter's parts are drawn (script command 31,
"change model state": slot, variant), and Nucleus builds make costume add-on
models follow that switch. So:

  * each weapon becomes an add-on model in every costume, hung on the donor's
    weapon joint, its meshes listed under its own variant of the donor's sword
    slot;
  * a move that uses a weapon starts with "sword slot -> that variant": the
    weapon shows, and the sword (drawn and sheathed are variants 0 and 1) hides;
  * the game puts the slot back when the action changes.

Which weapon a move uses is read from the game: the script names an article
by an id, and hitboxes on the hold bone say how far the weapon reaches. A
model is matched to a move as the smallest one that contains those hitboxes.
Only rigid weapons that hang from a hold bone are handled here; one with its
own animations (Byleth's whip) is `chain_weapon.py`.
"""
from __future__ import annotations

import json
import struct
import subprocess
from collections import Counter
from pathlib import Path

import numpy as np

HOLD_ROOTS = ('haver', 'have', 'havel')
SLOT = 1                      # the donor's sword slot (Marth: variant 0 drawn, 1 sheathed)
FIRST_VARIANT = 2             # weapons take the variants after the donor's own


# --------------------------------------------------------------- game models
def hold_models(ssbh, dump_root, fighter, bending=None):
    """{name: model} for every article model that hangs from a hold bone and does not
    bend. `bending`: the names that do (`chain_weapon.chains`); when it is not given,
    any article with an animation folder is left out, as before the archive's clips
    for every article were fetched. Geometry is given in the hold bone's own axes."""
    base = Path(dump_root) / 'gamedata' / 'fighter' / fighter
    out = {}
    for folder in sorted((base / 'model').iterdir()):
        d = folder / 'c00'
        if folder.name == 'body' or not (d / 'model.numshb').exists() or not (d / 'model.nusktb').exists():
            continue
        if folder.name in bending if bending is not None else (base / 'motion' / folder.name).exists():
            continue                                    # a weapon that bends: not a rigid add-on
        skel = ssbh.skel_data.read_skel(str(d / 'model.nusktb'))
        roots = [b for b in skel.bones if b.parent_index is None]
        hold = next((b for b in roots if b.name.lower() in HOLD_ROOTS), None)
        if hold is None or not (d / 'model.numdlb').exists() or not (d / 'model.numatb').exists():
            continue
        world = {b.name: np.array(skel.calculate_world_transform(b), float) for b in skel.bones}   # row vectors
        to_hold = np.linalg.inv(world[hold.name])
        material = {(e.mesh_object_name, e.mesh_object_subindex): e.material_label
                    for e in ssbh.modl_data.read_modl(str(d / 'model.numdlb')).entries}
        texture = {}
        for e in ssbh.matl_data.read_matl(str(d / 'model.numatb')).entries:
            texture[e.material_label] = next((t.data for t in e.textures
                                              if getattr(t.param_id, 'name', '') == 'Texture0'), None)
        parts = []
        for o in ssbh.mesh_data.read_mesh(str(d / 'model.numshb')).objects:
            P = np.array(o.positions[0].data, float)[:, :3]
            N = np.array(o.normals[0].data, float)[:, :3] if o.normals else np.zeros_like(P)
            UV = np.array(o.texture_coordinates[0].data, float)[:, :2] if o.texture_coordinates else np.zeros((len(P), 2))
            M = np.eye(4)
            if o.parent_bone_name and not o.bone_influences:
                M = world[o.parent_bone_name]           # a part bound to one bone is stored in that bone's axes
            M = M @ to_hold
            P = np.c_[P, np.ones(len(P))] @ M
            N = N @ M[:3, :3]
            parts.append({'texture': texture.get(material.get((o.name, o.subindex))), 'positions': P[:, :3],
                          'normals': N, 'uvs': UV, 'triangles': np.array(o.vertex_indices, int).reshape(-1, 3)})
        allp = np.vstack([p['positions'] for p in parts])
        out[folder.name] = {'parts': parts, 'min': allp.min(0), 'max': allp.max(0), 'root': hold.name,
                            'triangles': int(sum(len(p['triangles']) for p in parts))}
    return out


def plain_model(ssbh, dump_root, fighter, name, texture_dir=None):
    """One article model as the game has it, in its own axes (a projectile), in the
    shape `hold_models` gives. With `texture_dir`, its colour textures are decoded
    from the game there as <texture>.png for `write_smd`."""
    d = Path(dump_root) / 'gamedata' / 'fighter' / fighter / 'model' / name / 'c00'
    skel = ssbh.skel_data.read_skel(str(d / 'model.nusktb'))
    world = {b.name: np.array(skel.calculate_world_transform(b), float) for b in skel.bones}   # row vectors
    material = {(e.mesh_object_name, e.mesh_object_subindex): e.material_label
                for e in ssbh.modl_data.read_modl(str(d / 'model.numdlb')).entries}
    texture = {e.material_label: next((t.data for t in e.textures if getattr(t.param_id, 'name', '') == 'Texture0'), None)
               for e in ssbh.matl_data.read_matl(str(d / 'model.numatb')).entries}
    parts = []
    for o in ssbh.mesh_data.read_mesh(str(d / 'model.numshb')).objects:
        P = np.array(o.positions[0].data, float)[:, :3]
        N = np.array(o.normals[0].data, float)[:, :3] if o.normals else np.zeros_like(P)
        UV = np.array(o.texture_coordinates[0].data, float)[:, :2] if o.texture_coordinates else np.zeros((len(P), 2))
        M = world[o.parent_bone_name] if o.parent_bone_name and not o.bone_influences else np.eye(4)
        parts.append({'texture': texture.get(material.get((o.name, o.subindex))), 'positions': (np.c_[P, np.ones(len(P))] @ M)[:, :3],
                      'normals': N @ M[:3, :3], 'uvs': UV, 'triangles': np.array(o.vertex_indices, int).reshape(-1, 3)})
    if texture_dir is not None:
        from echo_ultimate import nutexb
        Path(texture_dir).mkdir(parents=True, exist_ok=True)
        for t in {p['texture'] for p in parts if p['texture']}:
            if (d / f'{t}.nutexb').exists():
                nutexb.read(d / f'{t}.nutexb')[0].save(Path(texture_dir) / f'{t}.png')
    allp = np.vstack([p['positions'] for p in parts])
    return {'parts': parts, 'min': allp.min(0), 'max': allp.max(0), 'root': None,
            'triangles': int(sum(len(p['triangles']) for p in parts))}


def blade_model(height, texture, steps=12):
    """A flat crescent `height` tall, centred on the origin and bulging toward +x, in the shape
    `hold_models` gives: what stands in for a shot the game draws with particles and has no model
    for. `texture` names its one picture (u along the blade, v from the outer edge in)."""
    t = np.linspace(-1.0, 1.0, steps + 1)
    half, bulge, thick = height / 2, 0.30 * height, 0.14 * height
    outer = np.c_[bulge * (1 - t ** 2), half * t, np.zeros_like(t)]
    inner = np.c_[(bulge - thick) * (1 - t ** 2), half * t, np.zeros_like(t)]
    front = np.vstack([outer, inner])
    uv = np.vstack([np.c_[(t + 1) / 2, np.zeros_like(t)], np.c_[(t + 1) / 2, np.ones_like(t)]])
    n, tris = steps + 1, []
    for i in range(steps):
        tris += [[i, i + 1, n + i + 1], [i, n + i + 1, n + i]]
    tris = np.array(tris, int)
    P = np.vstack([front, front])                       # seen from both sides: the same faces again, turned over
    N = np.vstack([np.tile([0.0, 0.0, 1.0], (2 * n, 1)), np.tile([0.0, 0.0, -1.0], (2 * n, 1))])
    T = np.vstack([tris, tris[:, ::-1] + 2 * n])
    return {'parts': [{'texture': texture, 'positions': P, 'normals': N, 'uvs': np.vstack([uv, uv]), 'triangles': T}],
            'min': P.min(0), 'max': P.max(0), 'root': None, 'triangles': len(T)}


def blade_picture(colour, size=16):
    """The picture for `blade_model`: the colour, lightest along the outer edge."""
    from PIL import Image
    c = np.array(colour[:3], float)
    rows = [np.clip(c + (255 - c) * (0.75 * (1 - v / (size - 1)) ** 2), 0, 255) for v in range(size)]
    a = np.repeat(np.array(rows)[:, None, :], size, axis=1).astype(np.uint8)
    return Image.fromarray(a, 'RGB').convert('RGBA')


# ------------------------------------------------------- which move, which weapon
def assign(game, models, clips=None, own_bone=None):
    """-> ({script: model name}, notes). A script with hitboxes on the hold bone
    takes the smallest model that contains them; a script that names an article
    takes the model that article's scripts settled on. `clips` ({model name: the
    names of that article's own clips}) settles an article too: the game keeps a
    clip for a weapon under the name of each move that animates it (a bow's own
    specialnstart), so a script that makes an article and plays such a clip names it.
    `own_bone`: the bone the fighter's own weapon hangs from. When that is the hold
    bone itself (Cloud's sword is in his hand, not on a sword bone), hitboxes on it
    are the own weapon's and say nothing about another model."""
    notes, fitted, article_of, unfitted = [], {}, {}, set()
    size = {n: float(np.linalg.norm(m['max'] - m['min'])) for n, m in models.items()}
    for script, m in game['moves'].items():
        ids = [a for a in m.get('articles', []) if a]
        if ids:
            article_of[script] = ids[0]
        pts = [np.array([h['x'], h['y'], h['z']], float) for h in m['hitboxes']
               if str(h.get('bone')).lower() == 'haver' and all(isinstance(h.get(k), (int, float)) for k in 'xyz')]
        if str(own_bone).lower() == 'haver':
            pts = []
        if not pts:
            continue
        fits = [n for n, mod in models.items()
                if all(np.all(p >= mod['min'] - 0.5) and np.all(p <= mod['max'] + 0.5) for p in pts)]
        if fits:
            fitted[script] = min(fits, key=size.get)
        else:
            unfitted.add(script)
    # an article is the model its scripts' hitboxes fit, by majority
    votes = {}
    for script, model in fitted.items():
        if script in article_of:
            votes.setdefault(article_of[script], Counter())[model] += 1
    for script, article in article_of.items():
        played = (game['moves'][script].get('animation') or '')[:-len('.nuanmb')]
        for model in models:
            if played and played in (clips or {}).get(model, ()):
                votes.setdefault(article, Counter())[model] += 1
    article_model = {a: c.most_common(1)[0][0] for a, c in votes.items()}
    # one held article and one model left over: they are each other's (a spun bow's hitboxes sit off the bow)
    open_articles = sorted({article_of[s] for s in unfitted if s in article_of} - set(article_model))
    open_models = sorted(set(models) - set(article_model.values()))
    if len(open_articles) == 1 and len(open_models) == 1:
        article_model[open_articles[0]] = open_models[0]
        notes.append(f'{open_articles[0]} = {open_models[0]} by elimination (its hitboxes fit no model)')
    by_script = {}
    for script in sorted(set(fitted) | set(article_of) | unfitted, key=len):
        if article_of.get(script) in article_model:
            by_script[script] = article_model[article_of[script]]          # the script names its weapon
            continue
        if script not in fitted and script not in unfitted:
            continue                                                       # names an article that is no held weapon
        base = max((s for s in by_script if script.startswith(s) and s != script), key=len, default=None)
        if base is not None:
            by_script[script] = by_script[base]                            # a move's later part keeps its weapon
        elif script in fitted:
            by_script[script] = fitted[script]
        else:
            notes.append(f'{script}: hold-bone hitboxes fit none of {sorted(models)}')
    notes.append('articles: ' + ', '.join(f'{a} = {m}' for a, m in sorted(article_model.items())))
    return by_script, notes


# ------------------------------------------------------------------ the add-on
def to_joint(clips_dir, rig_json, attach, hold):
    """3x3 that takes the hold bone's axes to the donor weapon joint's, scale
    included: the way every clip carries that joint (see retarget attachments)."""
    from .rigmap import Rig
    from .smpl_to_anim import orthonormalize
    clip = next(p for p in sorted(Path(clips_dir).iterdir()) if (p / 'transfer.json').exists())
    report = json.loads((clip / 'transfer.json').read_text('utf-8'))
    B, scale = np.array(report['basis'], float), float(report['scale'])
    source, target = Rig(clip / 'decoded' / 'source.joints.json'), Rig(rig_json)
    return scale * orthonormalize(target.world[attach][:3, :3]).T @ B @ orthonormalize(source.world[hold][:3, :3])


def write_smd(models, name, to_joint, out_dir, texture_dirs, max_texture=256):
    """One weapon as an SMD in the donor weapon joint's axes (to_joint: 3x3 that
    takes hold-bone axes there, scale included). Textures are copied small beside
    it and named in the importer's sidecar map. -> (smd path, textures not found)"""
    from PIL import Image
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    smd = out_dir / f'{name}.smd'
    lines = ['version 1', 'nodes', '0 "root" -1', 'end', 'skeleton', 'time 0', '0 0 0 0 0 0 0', 'end', 'triangles']
    tex_map, missing = {}, []
    rot = to_joint / np.cbrt(abs(np.linalg.det(to_joint)))
    for part in models[name]['parts']:
        mat = f'{name}_{part["texture"] or "plain"}'
        if mat not in tex_map and part['texture'] and part['texture'] not in missing:
            found = [Path(d) / sub / f'{part["texture"]}.png' for d in texture_dirs for sub in (name, '')]
            src = next((f for f in found if f.exists()), None)
            if src is None:
                missing.append(part['texture'])
            else:
                im = Image.open(src).convert('RGBA')
                im.thumbnail((max_texture, max_texture))
                im.save(out_dir / f'{mat}.png')
                tex_map[mat] = f'{mat}.png'
        P = part['positions'] @ to_joint.T
        N = part['normals'] @ rot.T
        for tri in part['triangles']:
            lines.append(mat)
            for v in tri:
                q, n, uv = P[v], N[v], part['uvs'][v]
                lines.append(f'0 {q[0]:.5f} {q[1]:.5f} {q[2]:.5f} {n[0]:.5f} {n[1]:.5f} {n[2]:.5f} '
                             f'{uv[0]:.5f} {1 - uv[1]:.5f}')
    lines.append('end')
    smd.write_text(chr(10).join(lines) + chr(10), 'ascii')
    Path(str(smd) + '.textures.json').write_text(json.dumps(tex_map, indent=1), 'utf-8')
    return smd, missing


def _empty_dat(path):
    """A DAT with one four-byte root, for the model tool to add an add-on to."""
    names = b'stub' + bytes(1)
    body = bytes(4) + struct.pack('>II', 0, 0) + names
    body += bytes(-len(body) % 4)
    Path(path).write_bytes(struct.pack('>IIIIIIII', 0x20 + len(body), 4, 0, 1, 0, 0, 0, 0) + body)


def build_addon(hsdraw_exe, smd, attach_joint, work):
    """Run the model tool's add-on import on an empty file -> a DAT holding just the add-on."""
    work = Path(work)
    stub, dyn, out = work / 'stub.dat', work / 'dynamics.json', Path(smd).with_suffix('.addon.dat')
    _empty_dat(stub)
    dyn.write_text('[]')
    out.unlink(missing_ok=True)
    r = subprocess.run([str(hsdraw_exe), '--accessory', str(stub), str(smd), str(attach_joint), str(dyn), str(out)],
                       capture_output=True, text=True, timeout=600)
    if not out.exists():
        raise RuntimeError('add-on import failed: ' + (r.stdout + r.stderr)[-800:])
    return out, r.stdout


def _dobj_count(d, root):
    """How many DObjs hang under joint `root`."""
    n, stack = 0, [root]
    while stack:
        j = stack.pop()
        flags = d.u32(j + 4)
        dobj = d.ptr(j + 0x10) if not flags & ((1 << 14) | (1 << 5)) else None
        while dobj is not None:
            n += 1
            dobj = d.ptr(dobj + 4)
        for o in (0xC, 8):
            if d.ptr(j + o) is not None:
                stack.append(d.ptr(j + o))
    return n


def add_to_costume(costume: bytes, addon: bytes, variant: int, datroot, Dat):
    """Append one weapon's add-on to a costume that may already carry add-ons, and
    list its meshes under `variant` of the sword slot only. -> (bytes, report)"""
    original = [name for _, name in datroot.parse(costume)[2]]
    d = Dat(datroot.merge_bytes(costume, addon))
    syms = [off for name, off in d.roots if name == 'mexCostume']
    keep_symbol, new_symbol = syms[0], syms[-1]
    had = d.u32(keep_symbol + 8) if keep_symbol != new_symbol else 0
    acc = d.u32(d.ptr(new_symbol + 0xC))
    count = _dobj_count(d, d.ptr(acc))
    if not 0 < count < 256:
        raise ValueError(f'add-on has {count} meshes')
    mine = bytes(range(count))

    def lookup():
        # variants before this weapon's own show nothing; any variant after it is past the list, so hidden too
        blob = b''.join(struct.pack('>II', 0, 0) for _ in range(variant))
        listed = d.append_struct(mine + bytes(-len(mine) % 4), align=4)
        blob += struct.pack('>II', count, listed)
        entries = d.append_struct(blob, [variant * 8 + 4], align=4)
        return d.append_struct(struct.pack('>IIII', 0, 0, variant + 1, entries), [12], align=4)   # slot 0 empty, slot 1

    table = d.append_struct(struct.pack('>IIII', lookup(), lookup(), lookup(), 0), [0, 4, 8], align=4)
    d.set_u32(acc + 0x10, SLOT + 1)
    d.set_u32(acc + 0x14, table)
    d.add_reloc(acc + 0x14)
    if keep_symbol != new_symbol:
        old_array = d.ptr(keep_symbol + 0xC)
        pointers = [d.u32(old_array + 4 * i) for i in range(had)] + [acc]
        array = d.append_struct(struct.pack(f'>{len(pointers)}I', *pointers), range(0, 4 * len(pointers), 4), align=4)
        d.set_u32(keep_symbol + 8, len(pointers))
        d.set_u32(keep_symbol + 0xC, array)
        d.add_reloc(keep_symbol + 0xC)
    data, relocs, roots, xrefs = datroot.parse(d.to_bytes())
    kept, seen = [], set()
    for off, name in roots:                              # the costume's own roots, each once (the first mexCostume)
        if name in original and name not in seen:
            kept.append((off, name))
            seen.add(name)
    if 'mexCostume' not in seen:
        kept.append((new_symbol, 'mexCostume'))
    return datroot.build(data, relocs, kept, xrefs), {'meshes': count, 'addons_before': had, 'variant': variant}
