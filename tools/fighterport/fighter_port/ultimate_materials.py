"""Bake explicitly selected Ultimate Texture0/Texture1 color layers for HSD.

Decoded nutexb PNGs and source UVs both use top-left V. Keep this convention
while baking; source_mesh_handoff's hsd_smd mode handles the file boundary.
"""
import hashlib
import subprocess
from pathlib import Path
import numpy as np
from PIL import Image
from .material_bake import alpha_layer,layer_coordinates
from .source_material_handoff import plan

def bake(model_dir, mesh, selection, out, texture_tool, *, color_layers=None, max_texture_dimension=None, preserve_materials=()):
    import ssbh_data_py as ssbh
    model_dir,out=map(Path,(model_dir,out))
    texture_tool=Path(texture_tool) if texture_tool else None    # none: the repo's own texture reader
    out.mkdir(parents=True,exist_ok=True)
    decoded=out/'decoded-textures'; decoded.mkdir(exist_ok=True)
    modl=ssbh.modl_data.read_modl(str(model_dir/'model.numdlb'))
    matl=ssbh.matl_data.read_matl(str(model_dir/'model.numatb'))
    chosen={(r['name'],r['subindex']) for r in selection['meshes']}
    if len(chosen)!=len(selection['meshes']):raise ValueError('Duplicate selected mesh')
    color_layers=color_layers or selection.get('color_layers',{})
    texture_ids={t.param_id.name:int(t.param_id.value) for e in matl.entries for t in e.textures}
    groups=[dict(name=o.name,subindex=o.subindex,material=f'mesh_{i:03d}')
            for i,o in enumerate(o for o in mesh.objects if (o.name,o.subindex) in chosen)]
    # Reuse the existing handoff's strict identity/basename validation. Do not
    # silently overwrite ambiguous mesh, binding or material dictionary rows.
    plan(mesh,modl,matl,groups,dict(selection,color_layers={label:dict(layer,texture_param=texture_ids[layer['texture']])
                                                        for label,layer in color_layers.items()}))
    labels={(e.mesh_object_name,e.mesh_object_subindex):e.material_label for e in modl.entries}
    if set(preserve_materials)-set(labels.values()):raise ValueError('Unknown preserved material')
    if max_texture_dimension is not None and (type(max_texture_dimension) is not int or max_texture_dimension<=0):raise ValueError('Positive integer texture dimension required')
    materials={e.material_label:{t.param_id.name:t.data for t in e.textures} for e in matl.entries}
    vectors={e.material_label:{t.param_id.name:t.data for t in e.vectors} for e in matl.entries}
    rows=[]
    def decode(name):
        src=model_dir/(name+'.nutexb')
        if src.parent.resolve()!=model_dir.resolve() or not src.is_file():
            raise ValueError(f'Missing or nonlocal texture: {name}')
        digest=hashlib.sha256(src.read_bytes()).hexdigest()
        png=decoded/(digest+'.png')
        if not png.exists():
            if texture_tool is None:
                from echo_ultimate import nutexb
                nutexb.read(src)[0].save(png)
            else:
                r=subprocess.run([str(texture_tool),str(src),str(png)],capture_output=True,text=True,timeout=180)
                if r.returncode or not png.is_file():raise RuntimeError(r.stdout+r.stderr)
        with Image.open(png) as im:return im.convert('RGBA').copy(),digest
    for obj in mesh.objects:
        if (obj.name,obj.subindex) not in chosen:continue
        group=len(rows);label=labels[obj.name,obj.subindex];tex=materials[label]
        image,sha=decode(tex['Texture0'])
        row=dict(group=group,mesh=obj.name,subindex=obj.subindex,material=label,
                 texture=tex['Texture0'],source_sha256=sha,png=f'mesh_{group:03d}.png',status='OK',uv_origin='top_left')
        layer=color_layers.get(label)
        if 'Texture1' in tex and layer is None:
            raise ValueError(f'{label} has Texture1: specify the secondary UV/color-layer policy')
        if layer:
            overlay,overlay_sha=decode(tex[layer['texture']])
            coords={t.name:np.asarray(t.data)[:,:2] for t in obj.texture_coordinates}
            transform=vectors[label].get('CustomVector31',[1,1,0,0])
            base_uv,second_uv,tile=layer_coordinates(coords['map1'],coords[layer['uv_set']],
                                        base_repeat=layer.get('base_repeat',False),transform=transform)
            row['base_uv_tile']=tile.tolist();row['secondary_uv_transform']=list(transform)
            image=alpha_layer(image,overlay,base_uv,second_uv,obj.vertex_indices,
                              size=max(image.size))
            row['color_layer']=dict(texture=tex[layer['texture']],sha256=overlay_sha,
                                    uv_set=layer['uv_set'],mode='static_alpha_over_rgb')
        if max_texture_dimension is not None:
            from .costume_budget import resize_texture
            image,row['dimension_policy']=resize_texture(image,max_texture_dimension,preserve=label in preserve_materials)
        image.save(out/row['png'])
        row['png_sha256']=hashlib.sha256((out/row['png']).read_bytes()).hexdigest()
        rows.append(row)
    return rows
