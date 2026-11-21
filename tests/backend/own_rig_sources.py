"""Real sources for the own-rig tests: a fighter's rig kit written out as the files a user uploads.

`gltf_from_kit` writes the glTF an HSDRawViewer DAE becomes after the app's
Collada conversion (joints named JOBJ_<n> in their hierarchy, one skinned mesh
node per drawable named Joint_<j>_Object_<n>), so the tests go through the real
loader (`repose.load_source`) and the real own-rig construction
(`pipeline.own_rig_for`) instead of hand-built source dicts.

The kits are the ones the app exports on first use (`fighter_catalog._rig_kit`);
tests that need them skip where none are cached. NUCLEUS_TEST_NUCLEUS_ROOT
points at an app folder whose storage/ and utility/assets/ have them.
"""
from tests.paths import APP
import base64
import json
import math
import os
import shutil
from pathlib import Path

import numpy as np


def _roots():
    """Nucleus roots to find kits and vanilla costumes in: NUCLEUS_TEST_NUCLEUS_ROOT, the checkout's own."""
    roots = []
    if os.environ.get('NUCLEUS_TEST_NUCLEUS_ROOT'):
        roots.append(Path(os.environ['NUCLEUS_TEST_NUCLEUS_ROOT']))
    roots.append(APP)
    return roots


def kit_path(fighter):
    """The fighter's cached rig kit SMD, or None."""
    for root in _roots():
        path = root / 'storage' / 'modellab' / 'rigkits' / fighter.replace(' ', '_') / 'rigkit.smd'
        if path.is_file():
            return path
    return None


def vanilla_dat(fighter, code):
    """The fighter's vanilla Nr costume DAT (first-run assets), or None."""
    for root in _roots():
        path = root / 'utility' / 'assets' / 'vanilla' / fighter / (code + 'Nr') / (code + 'Nr.dat')
        if path.is_file():
            return path
    return None


def _quaternion(rx, ry, rz):
    """xyzw of Rz @ Ry @ Rx (the SMD's euler order)."""
    cx, sx = math.cos(rx / 2), math.sin(rx / 2)
    cy, sy = math.cos(ry / 2), math.sin(ry / 2)
    cz, sz = math.cos(rz / 2), math.sin(rz / 2)
    return [sx * cy * cz - cx * sy * sz, cx * sy * cz + sx * cy * sz,
            cx * cy * sz - sx * sy * cz, cx * cy * cz + sx * sy * sz]


def gltf_from_kit(kit, destination, *, offsets=None, drop_joints=(), flat=False):
    """Write `kit` (a loaded rig-kit SMD) as a skinned glTF. -> path.

    `offsets` {drawable index: xyz} moves one drawable's corners: an edited
    costume mod. `drop_joints` leaves joints out of the file the way Blender's
    Collada importer drops leaf joints (their weights folded into the parent).
    `flat` writes every joint as a root at its world bind: the same positions,
    no hierarchy.
    """
    from shared.modellab import rig
    offsets = offsets or {}
    joints = [b for b in kit.bones if b.name.startswith('JOBJ_')]
    drawables = [b for b in kit.bones if not b.name.startswith('JOBJ_')]
    keep = [b for b in joints if int(b.name[5:]) not in set(drop_joints)]
    kept_ids = {b.id for b in keep}
    parent = {b.id: b.parent for b in joints}

    def surviving(joint):
        while joint is not None and joint not in kept_ids:
            joint = parent.get(joint)
        return joint

    worlds = rig.joint_world_matrices(kit)
    node_of = {b.id: i for i, b in enumerate(keep)}
    nodes = []
    for b in keep:
        above = None if flat else surviving(parent.get(b.id))
        local = np.linalg.inv(worlds[above]) @ worlds[b.id] if above is not None else worlds[b.id]
        rotation = local[:3, :3]
        rx = math.atan2(rotation[2, 1], rotation[2, 2])
        ry = math.asin(max(-1., min(1., -rotation[2, 0])))
        rz = math.atan2(rotation[1, 0], rotation[0, 0])
        nodes.append(dict(name=b.name, translation=[float(v) for v in local[:3, 3]],
                          rotation=_quaternion(rx, ry, rz)))
    for b in keep:
        above = None if flat else surviving(parent.get(b.id))
        if above is not None:
            nodes[node_of[above]].setdefault('children', []).append(node_of[b.id])
    blob, views, accessors, meshes = bytearray(), [], [], []

    def add(array, component, kind, target=None):
        data = np.ascontiguousarray(array)
        while len(blob) % 4:
            blob.append(0)
        views.append(dict(buffer=0, byteOffset=len(blob), byteLength=data.nbytes,
                          **({'target': target} if target else {})))
        blob.extend(data.tobytes())
        acc = dict(bufferView=len(views) - 1, componentType=component, count=int(len(data)), type=kind)
        if kind == 'VEC3' and component == 5126:
            acc.update(min=[float(v) for v in data.min(0)], max=[float(v) for v in data.max(0)])
        accessors.append(acc)
        return len(accessors) - 1

    skin_joints = [node_of[b.id] for b in keep]
    index_of = {b.id: k for k, b in enumerate(keep)}
    inverse = np.array([np.linalg.inv(worlds[b.id]).T.reshape(-1) for b in keep], np.float32)
    mesh_nodes = []
    for d_index, d in enumerate(drawables):
        tris = [t for t in kit.triangles if t.verts[0].parent == d.id]
        if not tris:
            continue
        pos = np.array([v.pos for t in tris for v in t.verts], np.float32) + np.asarray(offsets.get(d_index, (0, 0, 0)), np.float32)
        nrm = np.array([v.normal for t in tris for v in t.verts], np.float32)
        uv = np.array([v.uv for t in tris for v in t.verts], np.float32)
        js, ws = np.zeros((len(pos), 4), np.uint16), np.zeros((len(pos), 4), np.float32)
        for k, v in enumerate(v for t in tris for v in t.verts):
            merged = {}
            for joint, weight in v.weights:
                merged[index_of[surviving(joint)]] = merged.get(index_of[surviving(joint)], 0.) + weight
            pairs = sorted(merged.items(), key=lambda p: -p[1])[:4]
            total = sum(w for _, w in pairs) or 1.
            for c, (j, w) in enumerate(pairs):
                js[k, c], ws[k, c] = j, w / total
        attributes = dict(POSITION=add(pos, 5126, 'VEC3', 34962), NORMAL=add(nrm, 5126, 'VEC3', 34962),
                          TEXCOORD_0=add(uv, 5126, 'VEC2', 34962), JOINTS_0=add(js, 5123, 'VEC4', 34962),
                          WEIGHTS_0=add(ws, 5126, 'VEC4', 34962))
        meshes.append(dict(primitives=[dict(attributes=attributes, mode=4)]))
        mesh_nodes.append(dict(name=d.name, mesh=len(meshes) - 1, skin=0))
    first_mesh = len(nodes)
    nodes.extend(mesh_nodes)
    ibm = add(inverse, 5126, 'MAT4')
    roots = [node_of[b.id] for b in keep if flat or surviving(parent.get(b.id)) is None]
    doc = dict(asset=dict(version='2.0'), scene=0,
               scenes=[dict(nodes=roots + list(range(first_mesh, len(nodes))))],
               nodes=nodes, meshes=meshes, skins=[dict(joints=skin_joints, inverseBindMatrices=ibm)],
               accessors=accessors, bufferViews=views,
               buffers=[dict(byteLength=len(blob),
                             uri='data:application/octet-stream;base64,' + base64.b64encode(bytes(blob)).decode())])
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(doc), encoding='utf-8')
    return destination


def smd_copy(fighter, destination):
    """The kit's own SMD and textures copied to `destination` (an HSDRawViewer SMD upload). -> path"""
    source = kit_path(fighter)
    destination = Path(destination)
    shutil.copytree(source.parent, destination)
    return destination / 'rigkit.smd'
