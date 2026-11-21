"""Explicit static source diffuse materials for an identity mesh handoff.

Retains mesh groups, positions and full weights. Source map1 coordinates use
top-origin V; the HSD importer flips SMD V, so this handoff flips V once before
import. Secondary eye UV layers are baked per mesh, never shared by label alone.
This is a static diffuse approximation, not an Ultimate shader implementation.
"""
import argparse
import copy
from pathlib import Path
import subprocess
import sys
import numpy as np
from PIL import Image
from .compat import smd
from .material_bake import alpha_layer
from .evidence_catalog import read_json
from .workbench import write_new, fingerprint
from .experiment_inputs import freeze, finish


def plan(mesh, modl, matl, groups, selection):
    def unique(rows, key):
        result = {}
        for row in rows:
            identity = key(row)
            if identity in result:
                raise ValueError('Ambiguous material or mesh identity')
            result[identity] = row
        return result
    objects = unique(mesh.objects, lambda o: (o.name, o.subindex))
    bindings = unique(modl.entries, lambda e: (e.mesh_object_name, e.mesh_object_subindex))
    materials = unique(matl.entries, lambda e: e.material_label)
    if not groups or len({g['material'] for g in groups}) != len(groups):
        raise ValueError('Explicit unique handoff material groups required')
    if {(g['name'], g['subindex']) for g in groups} != {(g['name'], g['subindex']) for g in selection['meshes']}:
        raise ValueError('Selection differs from geometry handoff')
    rows = []
    for group in groups:
        identity = group['name'], group['subindex']
        obj = objects[identity]
        label = bindings[identity].material_label
        material = materials[label]
        tex = unique(material.textures, lambda t: int(t.param_id.value))
        diffuse = selection.get('texture_overrides', {}).get(label) or tex[92].data
        names = [diffuse]
        layer = selection.get('color_layers', {}).get(label)
        if layer:
            names.append(tex[layer['texture_param']].data)
            channels = [t for t in obj.texture_coordinates if t.name == layer['uv_set']]
            if len(channels) != 1:
                raise ValueError('Unique configured layer UV channel required')
        for name in names:
            if not isinstance(name, str) or not name or Path(name).name != name or '/' in name or '\\' in name or ':' in name:
                raise ValueError('Texture must be a local source basename')
        rows.append(dict(**group, source_material=label, diffuse=diffuse,
                         layer=layer, overlay=names[1] if layer else None))
    return rows


def flip_smd_v(model):
    result = copy.deepcopy(model)
    # Vertices may be shared by several faces; flip each object exactly once.
    seen = set()
    for triangle in result.triangles:
        for vertex in triangle.verts:
            if id(vertex) not in seen:
                seen.add(id(vertex)); vertex.uv = (vertex.uv[0], 1. - vertex.uv[1])
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('model-dir', 'handoff', 'selection', 'texture-tool', 'reader-dir', 'out'):
        p.add_argument('--'+key, type=Path, required=True)
    a = p.parse_args(argv)
    sys.path.insert(0, str(a.reader_dir.resolve()))
    import ssbh_data_py as ssbh
    mesh = ssbh.mesh_data.read_mesh(str(a.model_dir/'model.numshb'))
    selection = read_json(a.selection.read_bytes())
    receipt = read_json((a.handoff/'receipt.json').read_bytes())
    rows = plan(mesh, ssbh.modl_data.read_modl(str(a.model_dir/'model.numdlb')),
                ssbh.matl_data.read_matl(str(a.model_dir/'model.numatb')),
                receipt['mesh_groups'], selection)
    model = smd.load(a.handoff/'source.smd', strict=True)
    if {t.material for t in model.triangles} != {r['material'] for r in rows}:
        raise ValueError('Geometry material domain differs from handoff receipt')
    size = selection.get('max_texture', 512)
    if type(size) is not int or not 2 <= size <= 1024:
        raise ValueError('Explicit bounded texture size required')
    paths = {name: a.model_dir/name for name in ('model.numshb', 'model.numdlb', 'model.numatb')}
    paths.update(source_smd=a.handoff/'source.smd', handoff=a.handoff/'receipt.json',
                 selection=a.selection, texture_tool=a.texture_tool)
    for row in rows:
        for name in (row['diffuse'], row['overlay']):
            if name: paths[name+'.nutexb'] = a.model_dir/(name+'.nutexb')
    out = a.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    pins = freeze(out/'frozen-inputs', paths, project_root=Path(__file__).resolve().parents[2])
    decoded = out/'decoded'; decoded.mkdir()
    for key, path in paths.items():
        if path.suffix != '.nutexb': continue
        with (decoded/(path.stem+'.log')).open('x') as log:
            subprocess.run([str(a.texture_tool.resolve()), str(path.resolve()), str(decoded/(path.stem+'.png'))],
                           stdout=log, stderr=subprocess.STDOUT, check=True,
                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
    objects = {(o.name, o.subindex): o for o in mesh.objects}; sidecar = {}
    for row in rows:
        with Image.open(decoded/(row['diffuse']+'.png')) as image: image = image.convert('RGBA')
        row['decoded_size'] = list(image.size)
        if row['layer']:
            obj = objects[row['name'], row['subindex']]
            channels = {t.name: np.asarray(t.data)[:, :2] for t in obj.texture_coordinates}
            with Image.open(decoded/(row['overlay']+'.png')) as overlay:
                image = alpha_layer(image, overlay, channels['map1'], channels[row['layer']['uv_set']], obj.vertex_indices, size=size)
        elif max(image.size) > size:
            image = image.resize((max(1, size*image.width//max(image.size)), max(1, size*image.height//max(image.size))), Image.Resampling.LANCZOS)
        name = row['material']+'.png'; image.save(out/name)
        row['png'] = fingerprint(out/name); row['encoded_input_size'] = list(image.size)
        row['alpha_extrema'] = list(image.getchannel('A').getextrema())
        sidecar[row['material']] = name
    smd.save(flip_smd_v(model), out/'materialized.smd')
    write_new(out/'materialized.smd.textures.json', sidecar)
    finish(out/'final-inputs', pins, project_root=Path(__file__).resolve().parents[2])
    write_new(out/'receipt.json', dict(status='STATIC_DIFFUSE_HANDOFF_IMPORT_PENDING', groups=rows,
        smd=fingerprint(out/'materialized.smd'), uv_transform='u, 1-v; importer flips V back to source map1',
        limitations=['Static selected visibility', 'Diffuse and configured eye layers only; source shaders not reproduced'], native_accepted=False))
    print('Static material handoff:', len(rows), 'groups')


if __name__ == '__main__': main()
