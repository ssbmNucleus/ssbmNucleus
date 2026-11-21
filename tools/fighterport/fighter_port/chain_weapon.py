"""A held weapon that bends: Byleth's whip sword on a donor that only has a rigid sword.

In Ultimate the whip is a model of its own with a chain of bones, and one clip
per move that uses it (same name and length as the fighter's clip for that
move). Melee can do the same with data alone:

  * a clip is applied joint by joint and stops where its joint list ends, so
    joints added AFTER the donor's own are free: old clips never touch them,
    and a clip that lists them moves them;
  * the whip's joints are hung as the last joint under the costume's root (so
    no donor joint changes its number), with the whip mesh skinned to them;
  * the first of them is keyed, every frame, to where the donor's weapon joint
    is, so the whip sits in the hand; the rest take the whip clip's own motion;
  * the whip's meshes are listed in the fighter's part tables as one more
    variant of the sword slot, so script command 31 shows them and hides the
    sword, like the rigid weapons in `weapons.py`.

What limits it is the game's own numbers, each met on the way (2026-11-10):

  * 140 joints per fighter (ftparts.c);
  * a joint at most 29 parents deep ("fighter joint depth num over", ftanim.c):
    a longer chain is cut into runs that each hang on the weapon's first joint;
  * 0x8000 bytes per clip. The model tool stores every key it is given, so the
    weapon's curves are thinned here, as tightly as the room beside the body's
    part of the clip allows (`PRECISION`); `drift` says how far that moves it;
  * the whole bank of clips is loaded as one block: 2.42 MB loaded, 2.54 MB did
    not ("memp_kouho", lbmemory.c). The game's own largest is 2.18 MB.

`weapons.build_addon` makes the joints and skinned mesh (the model tool's add-on
import, on an empty file); `graft` moves them into a costume; `finish` writes
the port's data files that go with such a costume.
"""
from __future__ import annotations

import json
import math
import struct
import subprocess
from pathlib import Path

import numpy as np

from .weapons import HOLD_ROOTS, _dobj_count

MAX_JOINTS = 140              # ftparts.c MAX_FT_PARTS
RUN = 20                      # ftanim.c walks a joint's parents on a stack of 30 ("fighter joint depth num
                              # over"): a longer chain is cut into runs of this many, each hung on the hold bone
CLIP_BYTES = 0x8000           # the buffer the game reads one clip into
ROOT_DRAW_FLAGS = (1 << 28) | (1 << 29) | (1 << 30)     # a joint's "something below me draws in this pass" bits


# ----------------------------------------------------------------- the model
BENDS = 8        # how many skin-carrying bones a weapon's own clips must move within it for it to count as bending
MOVED = 0.5      # how far (units) such a bone must go from its rest place within the weapon


def moving_bones(ssbh, dump_root, fighter, name):
    """How many of an article's skin-carrying bones its own clips move within the article (measured from
    its root, so being carried about does not count). Byleth: the whip sword 37, the axe 2 (its head
    slides out), the bow 2 (the string), the lance 1."""
    base = Path(dump_root) / 'gamedata' / 'fighter' / fighter
    d = base / 'model' / name / 'c00'
    clips = sorted((base / 'motion' / name / 'c00').glob('*.nuanmb'))
    if not clips or not (d / 'model.nusktb').exists() or not (d / 'model.numshb').exists():
        return 0
    skel = ssbh.skel_data.read_skel(str(d / 'model.nusktb'))
    names = [b.name for b in skel.bones]
    parent = {b.name: (names[b.parent_index] if b.parent_index is not None else None) for b in skel.bones}
    rest_local = {b.name: np.array(b.transform, float).T for b in skel.bones}
    skinned = set()
    for o in ssbh.mesh_data.read_mesh(str(d / 'model.numshb')).objects:
        skinned |= {i.bone_name for i in o.bone_influences} if o.bone_influences else {o.parent_bone_name}
    skinned = [n for n in skinned if n in parent]
    root = next(n for n in names if parent[n] is None)

    def place(local, n):
        m = local[n]
        while parent[n] is not None:
            n = parent[n]
            m = local[n] @ m
        return m

    rest = {n: (np.linalg.inv(place(rest_local, root)) @ place(rest_local, n))[:3, 3] for n in skinned}
    moved = set()
    for clip in clips:
        tracks = {n.name: n.tracks[0].values for g in ssbh.anim_data.read_anim(str(clip)).groups
                  if 'Transform' in str(g.group_type) for n in g.nodes if n.name in parent}
        frames = max((len(v) for v in tracks.values()), default=0)
        for f in range(0, frames, max(1, frames // 12)):
            local = dict(rest_local)
            for n, v in tracks.items():
                local[n] = _matrix(v[min(f, len(v) - 1)])
            inv = np.linalg.inv(place(local, root))
            moved |= {n for n in skinned if np.linalg.norm((inv @ place(local, n))[:3, 3] - rest[n]) > MOVED}
    return len(moved)


def chains(dump_root, fighter, ssbh=None):
    """Names of the fighter's article models that bend: they have clips of their own that move at least
    BENDS of their skin-carrying bones within the model. (A weapon whose clips only slide a part or
    two, an axe head or a bow string, is a rigid one: `weapons.hold_models`.) Without `ssbh` nothing
    is measured and every article with clips is named."""
    base = Path(dump_root) / 'gamedata' / 'fighter' / fighter
    found = sorted(f.name for f in (base / 'model').iterdir()
                   if f.name != 'body' and (f / 'c00' / 'model.numshb').exists()
                   and any((base / 'motion' / f.name / 'c00').glob('*.nuanmb')))
    if ssbh is None:
        return found
    return [name for name in found if moving_bones(ssbh, dump_root, fighter, name) >= BENDS]


def read(ssbh, dump_root, fighter, name, stems=None):
    """One bending weapon: the bones worth keeping (root, any bone that carries
    skin, and what joins them), the skinned mesh, and its clips by name.
    Everything is in the hold bone's own axes, with the hold bone at the origin.
    A mesh part that none of the clips `stems` (default: all) ever shows is left
    out, so pass the clips the port uses when building the model."""
    base = Path(dump_root) / 'gamedata' / 'fighter' / fighter
    d = base / 'model' / name / 'c00'
    skel = ssbh.skel_data.read_skel(str(d / 'model.nusktb'))
    names = [b.name for b in skel.bones]
    parent = {b.name: (names[b.parent_index] if b.parent_index is not None else None) for b in skel.bones}
    hold = next((b.name for b in skel.bones if b.parent_index is None and b.name.lower() in HOLD_ROOTS), None)
    if hold is None:
        return None
    world = {b.name: np.array(skel.calculate_world_transform(b), float) for b in skel.bones}   # row vectors
    to_hold = np.linalg.inv(world[hold])
    material = {(e.mesh_object_name, e.mesh_object_subindex): e.material_label
                for e in ssbh.modl_data.read_modl(str(d / 'model.numdlb')).entries}
    texture = {e.material_label: next((t.data for t in e.textures if getattr(t.param_id, 'name', '') == 'Texture0'), None)
               for e in ssbh.matl_data.read_matl(str(d / 'model.numatb')).entries}
    parts, skinned = [], set()
    for o in ssbh.mesh_data.read_mesh(str(d / 'model.numshb')).objects:
        P = np.array(o.positions[0].data, float)[:, :3]
        N = np.array(o.normals[0].data, float)[:, :3] if o.normals else np.zeros_like(P)
        UV = np.array(o.texture_coordinates[0].data, float)[:, :2] if o.texture_coordinates else np.zeros((len(P), 2))
        links = [dict() for _ in P]
        M = np.eye(4)
        if o.bone_influences:
            for bi in o.bone_influences:
                for vw in bi.vertex_weights:
                    links[vw.vertex_index][bi.bone_name] = links[vw.vertex_index].get(bi.bone_name, 0) + vw.vertex_weight
        elif o.parent_bone_name:
            M = world[o.parent_bone_name]               # a part bound to one bone is stored in that bone's axes
            links = [{o.parent_bone_name: 1.0} for _ in P]
        else:
            links = [{hold: 1.0} for _ in P]
        M = M @ to_hold
        skinned |= {b for l in links for b in l}
        parts.append({'name': o.name.split('_VIS')[0], 'texture': texture.get(material.get((o.name, o.subindex))),
                      'positions': (np.c_[P, np.ones(len(P))] @ M)[:, :3], 'normals': N @ M[:3, :3], 'uvs': UV,
                      'triangles': np.array(o.vertex_indices, int).reshape(-1, 3), 'links': links})
    clips = {p.stem: p for p in sorted((base / 'motion' / name / 'c00').glob('*.nuanmb'))}
    shown = {}
    for stem, path in clips.items():                    # a part no clip ever shows (a spare gem) is left out
        if stems is not None and stem not in stems:
            continue
        for g in ssbh.anim_data.read_anim(str(path)).groups:
            if 'Visibility' in str(g.group_type):
                for n in g.nodes:
                    shown[n.name] = shown.get(n.name, False) or any(n.tracks[0].values)
    parts = [p for p in parts if shown.get(p['name'], True)]
    skinned = {b for p in parts for l in p['links'] for b in l}
    keep = {hold}
    for b in skinned:
        while b is not None and b not in keep:
            keep.add(b)
            b = parent[b]
    def kept_parent(n):
        p = parent[n]
        while p is not None and p not in keep:
            p = parent[p]
        return p

    hangs, depth = {}, {}
    for n in names:                                     # skeleton order: a parent comes before its children
        if n not in keep:
            continue
        hangs[n] = kept_parent(n)
        depth[n] = 0 if hangs[n] is None else depth[hangs[n]] + 1
        if depth[n] > RUN:                              # too deep for the game: start a new run on the hold bone
            hangs[n], depth[n] = hold, 1
    bones, stack = [], [hold]                           # in the order the game numbers joints
    while stack:
        n = stack.pop()
        bones.append(n)
        stack += [k for k in reversed(names) if hangs.get(k) == n]

    for part in parts:                                  # at most four bones a vertex, by index into `bones`
        out = []
        for l in part['links']:
            top = sorted(l.items(), key=lambda kv: -kv[1])[:4]
            total = sum(w for _, w in top) or 1.0
            out.append([(bones.index(b), w / total) for b, w in top])
        part['links'] = out
    return {'name': name, 'hold': hold, 'bones': bones, 'parent': hangs,
            'all': names, 'all_parent': parent,
            'local': {b.name: np.array(b.transform, float).T for b in skel.bones},      # column vectors from here on
            'rest': {n: (world[n] @ to_hold).T for n in bones}, 'parts': parts, 'clips': clips,
            'triangles': int(sum(len(p['triangles']) for p in parts))}


def _matrix(t):
    x, y, z, w = t.rotation
    R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    M = np.eye(4)
    M[:3, :3] = R * np.array(t.scale, float)
    M[:3, 3] = t.translation
    return M


class Clip:
    """One of the weapon's clips: poses of the kept bones (relative to the hold
    bone) and whether its meshes are shown, at any time."""

    def __init__(self, ssbh, chain, stem):
        self.chain = chain
        anim = ssbh.anim_data.read_anim(str(chain['clips'][stem]))
        self.end = float(anim.final_frame_index)
        self.tracks, self.shown = {}, {}
        for g in anim.groups:
            for n in g.nodes:
                if 'Transform' in str(g.group_type):
                    self.tracks[n.name] = [_matrix(v) for v in n.tracks[0].values]
                elif 'Visibility' in str(g.group_type):
                    self.shown[n.name] = [bool(v) for v in n.tracks[0].values]

    def _local(self, bone, time):
        keys = self.tracks.get(bone)
        if not keys:
            return self.chain['local'][bone]
        time = min(max(time, 0.0), len(keys) - 1)
        a = int(math.floor(time))
        b = min(a + 1, len(keys) - 1)
        u = time - a
        return keys[a] if u < 1e-6 else keys[a] * (1 - u) + keys[b] * u     # a frame apart: close enough to blend

    def pose(self, time):
        """{kept bone: 4x4 relative to the hold bone}. The hold bone's own track
        (a path in the fighter's space) is dropped: the port's hand carries it."""
        c = self.chain
        world = {}
        for n in c['all']:
            p = c['all_parent'][n]
            world[n] = np.eye(4) if n == c['hold'] else world[p] @ self._local(n, time)
        return {n: world[n] for n in c['bones']}

    def visible(self, part):
        """[(first frame, last frame)] spans in which the mesh part is drawn (all, when it has no track)."""
        v = self.shown.get(part)
        if v is None:
            return [(0, int(self.end))]
        v = v + [v[-1]] * (int(self.end) + 1 - len(v))
        spans, start = [], None
        for i, on in enumerate(v):
            if on and start is None:
                start = i
            if not on and start is not None:
                spans.append((start, i - 1))
                start = None
        if start is not None:
            spans.append((start, len(v) - 1))
        return spans


def hold_path(ssbh, skel, anim_path, hold, root='Trans'):
    """Where the body's hold bone is on each frame of a body clip, relative to the bone
    that carries the fighter's travel: (frames, 3)."""
    names = [b.name for b in skel.bones]
    by_name = {b.name: b for b in skel.bones}
    tracks = {n.name: n.tracks[0].values for g in ssbh.anim_data.read_anim(str(anim_path)).groups
              if 'Transform' in str(g.group_type) for n in g.nodes}
    line = []
    b = by_name.get(hold)
    while b is not None and b.name != root:
        line.append(b)
        b = by_name[names[b.parent_index]] if b.parent_index is not None else None
    if b is None:
        return np.zeros((0, 3))
    frames = max((len(tracks[x.name]) for x in line if x.name in tracks), default=1)
    out = []
    for f in range(frames):
        M = np.eye(4)
        for x in reversed(line):
            v = tracks.get(x.name)
            M = M @ (_matrix(v[min(f, len(v) - 1)]) if v else np.array(x.transform, float).T)
        out.append(M[:3, 3])
    return np.array(out)


def align(ssbh, chain, path, used=(), tolerance=0.05):
    """Which of the weapon's clips play during a body clip, and from which of its frames.

    The weapon's own root track is the path of the hand that holds it, so a clip of the
    weapon belongs where that path lies on the body's (`path`, from `hold_path`).
    -> [(weapon clip, first body frame)] in order, clips in `used` left out."""
    found = []
    for stem, clip_path in chain['clips'].items():
        if stem in used:
            continue
        anim = ssbh.anim_data.read_anim(str(clip_path))
        track = next((n.tracks[0].values for g in anim.groups if 'Transform' in str(g.group_type)
                      for n in g.nodes if n.name == chain['hold']), None)
        if not track or len(track) < 3 or len(track) > len(path):
            continue
        own = np.array([np.array(v.translation, float) for v in track])
        if np.abs(own - own[0]).max() < tolerance:
            continue                                    # a still root says nothing about where it belongs
        best = None
        for first in range(len(path) - len(own) + 1):
            worst = float(np.abs(own - path[first:first + len(own)]).max())
            if worst < tolerance and (best is None or worst < best[0]):
                best = (worst, first)
        if best:
            found.append((stem, best[1]))
    return sorted(found, key=lambda x: x[1])


def reach(ssbh, chain, run):
    """How far the weapon's end gets from the fighter during a body clip, from the weapon's
    own clips (`run`: [(clip, first body frame)], as `align` gives). The weapon's root track
    is the hand's place in the fighter's space, so root track x pose puts its last bone there.
    -> {forward, up (the game's units, at the furthest), first, last (body frames it is at
    least two thirds out)} or None."""
    tip = chain['bones'][-1]
    far = []
    for stem, first in run:
        clip = Clip(ssbh, chain, stem)
        root = clip.tracks.get(chain['hold']) or []
        for f in range(min(len(root), int(clip.end) + 1)):
            at = (root[f] @ clip.pose(float(f))[tip])[:3, 3]
            far.append((first + f, float(at[2]), float(at[1])))       # fighter space: z ahead, y up
    if not far:
        return None
    length = max(math.hypot(z, y) for _, z, y in far)
    out = [f for f, z, y in far if math.hypot(z, y) >= length * 2 / 3]
    best = max(far, key=lambda r: math.hypot(r[1], r[2]))
    return {'forward': abs(best[1]), 'up': best[2], 'first': min(out), 'last': max(out)}


class Sequence:
    """Several of the weapon's clips one after another, each from the time it starts at
    (in whatever time `pose` is asked in: the body clip's own frames)."""

    def __init__(self, parts):
        self.parts = sorted(parts, key=lambda p: p[1])          # [(Clip, first clip frame)]

    def pose(self, frame):
        clip, first = next((p for p in reversed(self.parts) if frame >= p[1]), self.parts[0])
        return clip.pose(min(max(frame - first, 0.0), clip.end))


def stems_of(clips):
    """Every clip of the weapon that a list of port clips uses."""
    return [q['stem'] for c in clips for q in (c.get('parts') or [c])]


def _to_axes(M, to_joint):
    """A transform given in hold-bone axes, in the donor weapon joint's axes (to_joint includes the scale)."""
    R = to_joint / np.cbrt(abs(np.linalg.det(to_joint)))
    out = np.eye(4)
    out[:3, :3] = R @ M[:3, :3] @ R.T
    out[:3, 3] = to_joint @ M[:3, 3]
    return out


def _locals(chain, pose, to_joint):
    """{bone: its transform relative to its kept parent}, in the weapon joint's axes."""
    there = {n: _to_axes(M, to_joint) for n, M in pose.items()}
    return {n: (np.linalg.inv(there[chain['parent'][n]]) @ there[n]) if chain['parent'][n] else there[n]
            for n in chain['bones']}


def _euler(R):
    from .smpl_to_anim import orthonormalize, to_hsd_euler
    return to_hsd_euler(orthonormalize(R))


def write_smd(chain, to_joint, out_dir, texture_dirs, max_texture=256):
    """The weapon as a skinned SMD in the donor weapon joint's axes. -> (smd, joint names in file order, textures not found)"""
    from PIL import Image
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name, bones = chain['name'], chain['bones']
    smd = out_dir / f'{name}.smd'
    rest = _locals(chain, chain['rest'], to_joint)
    lines = ['version 1', 'nodes']
    lines += [f'{i} "{n}" {bones.index(chain["parent"][n]) if chain["parent"][n] else -1}' for i, n in enumerate(bones)]
    lines += ['end', 'skeleton', 'time 0']
    for i, n in enumerate(bones):
        t, r = rest[n][:3, 3], _euler(rest[n][:3, :3])
        lines.append(f'{i} {t[0]:.6f} {t[1]:.6f} {t[2]:.6f} {r[0]:.6f} {r[1]:.6f} {r[2]:.6f}')
    lines += ['end', 'triangles']
    tex_map, missing = {}, []
    rot = to_joint / np.cbrt(abs(np.linalg.det(to_joint)))
    for part in chain['parts']:
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
                q, n, uv, links = P[v], N[v], part['uvs'][v], part['links'][v]
                lines.append(f'0 {q[0]:.5f} {q[1]:.5f} {q[2]:.5f} {n[0]:.5f} {n[1]:.5f} {n[2]:.5f} '
                             f'{uv[0]:.5f} {1 - uv[1]:.5f} {len(links)} ' + ' '.join(f'{b} {w:.4f}' for b, w in links))
    lines.append('end')
    smd.write_text(chr(10).join(lines) + chr(10), 'ascii')
    Path(str(smd) + '.textures.json').write_text(json.dumps(tex_map, indent=1), 'utf-8')
    return smd, missing


# ------------------------------------------------------------- into the costume
def _tree(d, root):
    """Joint offsets under `root`, in the order the game numbers them (a joint, its children, then its next)."""
    out, stack = [], [root]
    while stack:
        j = stack.pop()
        out.append(j)
        for o in (0xC, 8):                              # next goes on first so the child is taken first
            if d.ptr(j + o) is not None:
                stack.append(d.ptr(j + o))
    return out


def graft(costume: bytes, addon: bytes, datroot, Dat):
    """Hang an add-on file's joints (built by `weapons.build_addon`) as the last
    joint under the costume's root, so they are the fighter's own joints, numbered
    after every joint the costume had. -> (bytes, report)"""
    original = [name for _, name in datroot.parse(costume)[2]]
    d = Dat(datroot.merge_bytes(costume, addon))
    body = next(off for name, off in d.roots if name.endswith('_joint') and 'matanim' not in name)
    symbol = [off for name, off in d.roots if name == 'mexCostume'][-1]         # the add-on file's, merged in last
    new = d.ptr(d.u32(d.ptr(symbol + 0xC)))
    before, added = _tree(d, body), _tree(d, new)
    meshes_before, meshes = _dobj_count(d, body), _dobj_count(d, new)
    if len(before) + len(added) > MAX_JOINTS:
        raise ValueError(f'{len(before)} + {len(added)} joints is over the game limit of {MAX_JOINTS}')
    last = d.ptr(body + 8)
    while d.ptr(last + 0xC) is not None:
        last = d.ptr(last + 0xC)
    d.set_u32(last + 0xC, new)
    d.add_reloc(last + 0xC)
    # the walk that draws a model only goes below a joint flagged for that pass: flag the root for the weapon's
    passes = (d.u32(new + 4) >> 18 & 7) << 28 | d.u32(new + 4) & ROOT_DRAW_FLAGS
    d.set_u32(body + 4, d.u32(body + 4) | passes)
    now = _tree(d, body)
    if now[:len(before)] != before or now[len(before):] != added:
        raise ValueError('the graft would renumber the costume joints')
    data, relocs, roots, xrefs = datroot.parse(d.to_bytes())
    kept, seen = [], set()
    for off, name in roots:
        if name in original and name not in seen:
            kept.append((off, name))
            seen.add(name)
    return datroot.build(data, relocs, kept, xrefs), {
        'first_joint': len(before), 'joints': len(added), 'meshes': list(range(meshes_before, meshes_before + meshes)),
        'rest': [[d.f32(j + 0x14 + 4 * k) for k in range(9)] for j in added]}      # rotation, scale, translation


def list_meshes(pl: bytes, slot: int, variant: int, meshes, Dat, tables=None):
    """In the fighter's own part tables (every costume's, every detail level), give
    `slot` a `variant` that draws `meshes`; variants in between draw nothing."""
    d = Dat(pl)
    ft = next(off for name, off in d.roots if name.startswith('ftData'))
    look = d.ptr(ft + 8)
    array, done = d.ptr(look + 4), {}
    if d.u32(look) <= slot:
        raise ValueError(f'the fighter has {d.u32(look)} part slots; no slot {slot}')
    listed = None
    for t in range(tables if tables is not None else _table_count(d, look)):
        for which in (0, 4, 8, 12):
            slots = d.ptr(array + 0x10 * t + which)
            if slots is None:
                continue
            rec = slots + 8 * slot
            if rec in done:
                continue
            count, entries = d.u32(rec), d.ptr(rec + 4)
            if count > variant:
                raise ValueError(f'slot {slot} already has a variant {variant}')
            blob, pointers = b'', []
            for i in range(count):
                n, p = d.u32(entries + 8 * i), d.ptr(entries + 8 * i + 4)
                if p is not None:
                    pointers.append(8 * i + 4)
                blob += struct.pack('>II', n, p or 0)
            blob += struct.pack('>II', 0, 0) * (variant - count)
            if listed is None:
                listed = d.append_struct(bytes(meshes) + bytes(-len(meshes) % 4), align=4)
            pointers.append(8 * variant + 4)
            blob += struct.pack('>II', len(meshes), listed)
            new = d.append_struct(blob, pointers, align=4)
            d.set_u32(rec, variant + 1)
            d.set_u32(rec + 4, new)
            if entries is None:
                d.add_reloc(rec + 4)
            done[rec] = new
    return d.to_bytes(), len(done)


def _table_count(d, look):
    """How many costume tables the fighter has: they sit in one array that ends where the next struct begins."""
    array = d.ptr(look + 4)
    return max(1, (d.struct_end(array) - array) // 0x10)


# ------------------------------------------------------------------- the clips
CHANNELS = ('translateX', 'translateY', 'translateZ', 'rotateX', 'rotateY', 'rotateZ')
# how far a kept key may sit from the true curve (units, radians), tightest first. The model tool
# stores every key it is given and a clip holds 0x8000 bytes, of which the body needs about half.
PRECISION = ((0.02, 0.004), (0.03, 0.008), (0.05, 0.015), (0.08, 0.025), (0.12, 0.04), (0.2, 0.07))
HAND_PRECISION = (0.01, 0.002)


def curves(chain, clip, body_anim, rig, weapon_joint, to_joint, keys):
    """Per clip frame, each weapon joint's translation and rotation (the costume's
    local values): -> ({bone: {channel: [values]}}, frames). The first joint is put
    where `weapon_joint` is on that frame of the body's clip; the rest take the
    weapon clip's pose at that frame's source time (`keys`: [[clip frame, source time], ...])."""
    from .evaluation import Animation
    from .oneshot import source_time
    from .smpl_to_anim import unwrap
    body = Animation(body_anim)
    end = int(round(body.end))
    top = rig.order[0]
    values = {n: {c: [] for c in CHANNELS} for n in chain['bones']}
    for frame in range(end + 1):
        world = body.world(rig, float(frame))
        local = _locals(chain, clip.pose(source_time(keys, frame)), to_joint)
        local[chain['bones'][0]] = np.linalg.inv(world[top]) @ world[weapon_joint]
        for n in chain['bones']:
            t, r = local[n][:3, 3], _euler(local[n][:3, :3])
            for axis, a in enumerate('XYZ'):
                values[n]['translate' + a].append(float(t[axis]))
                prev = values[n]['rotate' + a][-1] if values[n]['rotate' + a] else None
                values[n]['rotate' + a].append(unwrap(prev, float(r[axis])))
    return values, end + 1


def keyed(chain, values, rest, precision):
    """Thin the curves: -> {bone: {channel: {frame: value}}}, leaving out a channel
    that never leaves the costume's rest value (`rest`: per joint, rotation, scale,
    translation as the costume file has them)."""
    out = {}
    for i, n in enumerate(chain['bones']):
        r0 = dict(zip(('rotateX', 'rotateY', 'rotateZ', 'translateX', 'translateY', 'translateZ'),
                      list(rest[i][0:3]) + list(rest[i][6:9])))
        out[n] = {}
        for ch, vals in values[n].items():
            turn = ch.startswith('rotate')
            if turn:                                    # the rest angle a whole turn away is still the rest pose
                shift = 2 * math.pi * round((vals[0] - r0[ch]) / (2 * math.pi))
                vals = [v - shift for v in vals]
            tol = (precision if i else HAND_PRECISION)[1 if turn else 0]
            if max(abs(v - r0[ch]) for v in vals) < tol:
                continue
            frames = [0] if max(vals) - min(vals) < tol else _thin(vals, tol)
            out[n][ch] = {f: vals[f] for f in frames}
    return out


def drift(chain, values, kept):
    """Largest distance (costume units) any weapon joint ends up from where the full curves put it."""
    from .rigmap import euler_xyz

    def sample(n, ch, frame):
        k = kept[n].get(ch)
        if k is None:
            return None
        fs = sorted(k)
        if len(fs) == 1 or frame <= fs[0]:
            return k[fs[0]]
        for a, b in zip(fs, fs[1:]):
            if frame <= b:
                return k[a] + (k[b] - k[a]) * (frame - a) / (b - a)
        return k[fs[-1]]

    worst = 0.0
    frames = len(next(iter(values[chain['bones'][0]].values())))
    for frame in range(frames):
        true, thin = {}, {}
        for n in chain['bones'][1:]:
            p = chain['parent'][n]
            for world, pick in ((true, lambda c: values[n][c][frame]),
                                (thin, lambda c: sample(n, c, frame) if sample(n, c, frame) is not None else values[n][c][0])):
                L = np.eye(4)
                L[:3, :3] = euler_xyz([pick('rotateX'), pick('rotateY'), pick('rotateZ')])
                L[:3, 3] = [pick('translateX'), pick('translateY'), pick('translateZ')]
                world[n] = world[p] @ L if p in world else L
            worst = max(worst, float(np.linalg.norm(true[n][:3, 3] - thin[n][:3, 3])))
    return worst


def clip_text(body_anim, rig, kept, bones, first_joint):
    """The body's clip text (Maya .anim) with the weapon's joints added after the donor's."""
    text = Path(body_anim).read_text('utf-8-sig')
    listed = []
    for line in text.splitlines():
        w = line.strip().rstrip(';').split()
        if w and w[0] == 'anim':
            n = w[3] if len(w) >= 7 else w[1]
            if n not in listed:
                listed.append(n)
    if listed != rig.order:
        raise ValueError(f'{body_anim}: the clip does not list the donor joints in order')
    lines, row = [], 100000
    for i, n in enumerate(bones):
        name = f'JOBJ_{first_joint + i}'
        for ch, k in kept[n].items():
            attr = 'translate' if ch.startswith('translate') else 'rotate'
            lines += [f'anim {attr}.{ch} {ch} {name} 0 {row} 0;', 'animData {', ' input time;',
                      ' output ' + ('angular' if attr == 'rotate' else 'linear') + ';', ' weighted 0;',
                      ' preInfinity constant;', ' postInfinity constant;', ' keys {']
            lines += [f' {f} {k[f]:.6f} linear linear 1 1 0;' for f in sorted(k)]
            lines += [' }', '}']
            row += 1
        if not kept[n]:
            lines.append(f'anim {name} 0 {row} 0;')
            row += 1
    return text.rstrip(chr(10)) + chr(10) + chr(10).join(lines) + chr(10)


def _thin(values, tolerance):
    """Frames to keep so straight lines between them stay within `tolerance` of every value."""
    keep, stack = {0, len(values) - 1}, [(0, len(values) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        worst, at = 0.0, None
        for i in range(a + 1, b):
            err = abs(values[i] - (values[a] + (values[b] - values[a]) * (i - a) / (b - a)))
            if err > worst:
                worst, at = err, i
        if worst > tolerance:
            keep.add(at)
            stack += [(a, at), (at, b)]
    return sorted(keep)


def _clips(aj: bytes):
    """[(offset, bytes)] of the clips in an animation bank (each a small file, padded to 0x20)."""
    out, o = [], 0
    while o + 0x20 <= len(aj):
        size = struct.unpack_from('>I', aj, o)[0]
        if size < 0x20 or o + size > len(aj):
            raise ValueError(f'animation bank: bad clip size at {o:#x}')
        out.append((o, aj[o:o + size]))
        o += size + (-size % 0x20)
    return out


def widen_clip(aj: bytes, symbol: str, joints: int, datroot):
    """Replace `symbol`'s clip with an empty one that lists `joints` joints, so the
    model tool accepts a clip of that many joints for it. -> bytes"""
    out, found = b'', False
    for _, blob in _clips(aj):
        data, relocs, roots, xrefs = datroot.parse(blob)
        if roots and roots[0][1] == symbol:
            tree = roots[0][0]
            head = bytearray(data[tree:tree + 0x14])
            table = bytes(joints) + b'\xff'
            table += bytes(-len(table) % 4)
            struct.pack_into('>II', head, 0xC, 0x14, 0x14 + len(table))
            blob = datroot.build(bytes(head) + table + bytes(12), [0xC, 0x10], [(0, symbol)], [])
            found = True
        out += blob + b'\xff' * (-len(blob) % 0x20)
    if not found:
        raise ValueError(f'no clip {symbol} in the animation bank')
    return out


def install_clip(hsdraw_exe, aj: Path, pl: Path, symbol, anim: Path, joints, datroot, work: Path, error=0.0001):
    """Put a clip with added joints into the bank (aj and pl are rewritten in place). -> the tool's last line"""
    work.mkdir(parents=True, exist_ok=True)
    wide = work / 'wide.dat'
    wide.write_bytes(widen_clip(aj.read_bytes(), symbol, joints, datroot))
    out_aj, out_pl = work / 'out_aj.dat', work / 'out_pl.dat'
    for f in (out_aj, out_pl):
        f.unlink(missing_ok=True)
    r = subprocess.run([str(hsdraw_exe), '--anim', 'import', str(wide), symbol, str(anim), str(out_aj),
                        '--pl', str(pl), str(out_pl), '--error', str(error)], capture_output=True, text=True, timeout=900)
    text = (r.stdout + r.stderr).strip()
    if not out_aj.exists() or not out_pl.exists() or 'SUCCESS' not in text:
        raise RuntimeError(f'{symbol}: clip import failed: {text[-600:]}')
    aj.write_bytes(out_aj.read_bytes())
    pl.write_bytes(out_pl.read_bytes())
    return text.splitlines()[-1]


def finish(ssbh, dump_root, fighter, port: Path, out: Path, grafted: dict, hsdraw_exe, datroot, Dat, log=print):
    """The port's data files for a costume that carries the bending weapon:
    its meshes in the part tables, and the clips of the moves that use it with
    the added joints. Reads <port>/final and weapons.json, writes `out`."""
    from . import weapons
    from .rigmap import Rig
    port, out = Path(port), Path(out)
    info = json.loads((port / 'weapons.json').read_text('utf-8'))
    rig_json = next(port.glob('*.joints.json'))
    rig = Rig(rig_json)
    files = sorted((port / 'final').glob('*.dat'))
    aj_src = next(f for f in files if f.stem.endswith('AJ'))
    pl_src = next(f for f in files if f != aj_src)
    out.mkdir(parents=True, exist_ok=True)
    aj, pl = out / aj_src.name, out / pl_src.name
    aj.write_bytes(aj_src.read_bytes())
    data = pl_src.read_bytes()
    report = {}
    if len(info.get('chains', {})) > 1:
        raise ValueError('one bending weapon per fighter for now: their joints would have to be stacked')
    for name, c in info.get('chains', {}).items():
        g = grafted[name]
        if g['first_joint'] != len(rig.order):
            raise ValueError(f"the costume has {g['first_joint']} joints, the donor rig {len(rig.order)}")
        data, tables = list_meshes(data, info['slot'], c['variant'], g['meshes'], Dat)
        pl.write_bytes(data)
        chain = read(ssbh, dump_root, fighter, name, stems_of(c['clips']))
        if len(chain['bones']) != g['joints']:
            raise ValueError(f"the costume carries {g['joints']} joints for {name}, the model now has {len(chain['bones'])}")
        tj = weapons.to_joint(port / 'clips', rig_json, info['attach']['target'], chain['hold'])
        for i, (n, L) in enumerate(_locals(chain, chain['rest'], tj).items()):
            if i and float(np.abs(L[:3, 3] - np.array(g['rest'][i][6:9])).max()) > 1e-3:
                raise ValueError(f'{name}: costume joint {g["first_joint"] + i} is not {n}; rebuild the costumes')
        rows = []
        bank = {datroot.parse(blob)[2][0][1]: len(blob) for _, blob in _clips(aj.read_bytes())}
        for clip in c['clips']:
            motion = (Sequence([(Clip(ssbh, chain, q['stem']), q['first']) for q in clip['parts']]) if clip.get('parts')
                      else Clip(ssbh, chain, clip['stem']))
            values, frames = curves(chain, motion, clip['anim'], rig, info['attach']['target'],
                                    tj, clip.get('time_keys'))
            anim = out / 'clips' / f"{clip['motion']}.anim"
            anim.parent.mkdir(exist_ok=True)
            room = CLIP_BYTES - bank[clip['symbol']]
            for step, precision in enumerate(PRECISION):
                kept = keyed(chain, values, g['rest'], precision)
                tracks, keys = sum(len(k) for k in kept.values()), sum(len(v) for k in kept.values() for v in k.values())
                if tracks * 12 + keys * 3.2 + 200 > room and step < len(PRECISION) - 1:
                    continue                            # would not fit beside the body: next coarser
                anim.write_text(clip_text(clip['anim'], rig, kept, chain['bones'], g['first_joint']), 'utf-8')
                line = install_clip(hsdraw_exe, aj, pl, clip['symbol'], anim, g['first_joint'] + g['joints'], datroot,
                                    out / 'work', info.get('clip_error', 0.0001))
                if 'tolerance raised' not in line or step == len(PRECISION) - 1:
                    break                               # the tool kept the body's own precision
            note = line[line.index('('):line.index('; refreshed')].rsplit(' -> ', 1)[0]
            row = {'motion': clip['motion'], 'frames': frames, 'tracks': tracks, 'keys': keys, 'precision': list(precision),
                   'off_by_at_most': round(drift(chain, values, kept), 2), 'tool': note}
            rows.append(row)
            log(' ', {k: v for k, v in row.items() if k != 'tool'}, note)
        report[name] = {'part_tables': tables, 'clips': rows, 'joints': g['first_joint'] + g['joints'],
                        'bank_bytes': aj.stat().st_size}
    (out / 'chain-report.json').write_text(json.dumps(report, indent=1), 'utf-8')
    return report
