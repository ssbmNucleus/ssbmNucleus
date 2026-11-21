"""Source-space mesh handoff onto an explicitly compatible named skeleton.

SMD does not carry bone scale. Import must preserve the supplied DAT's binds,
then verify actual joint order, rest transforms, inverse binds and mesh output.
Materials are named geometry groups; textures and source material semantics
are intentionally unmeasured by this adapter.
"""
import numpy as np
import argparse
import sys
from pathlib import Path
from .compat import smd
from .rig_dependencies import validate_rig
from .rig_archive import world_matrices
from .rig_benchmark import Skin
from .rig_archive import read_skeleton
from .evidence_catalog import read_json
from .workbench import write_new,fingerprint
from .experiment_inputs import freeze,finish
from .envelope_contract import prepare_links,RIGID_THRESHOLD


def prepare(mesh,source_rig,target_rig,selection,*,envelope_policy='preserve_entries',uv_convention='source',fold=None):
    # `fold`: {source joint: the target joint it was folded into} (own_skeleton.fold_plan): its weights go there
    fold=dict(fold or {})
    if uv_convention not in ('source','hsd_smd'):raise ValueError('Explicit source or hsd_smd UV convention required')
    if envelope_policy not in ('preserve_entries','preserve_weighted_transform'):raise ValueError('Explicit known envelope policy required')
    source_order,_,_=validate_rig(source_rig);order,parent,rest=validate_rig(target_rig)
    if set(source_order)-set(order)-set(fold):raise ValueError('Target omits named source joints')
    if set(fold.values())-set(order):raise ValueError('A joint is folded into one the target does not have')
    source_world=world_matrices(source_rig);target_world=world_matrices(target_rig)
    drift=max(float(np.max(np.abs(source_world[j]-target_world[j]))) for j in source_order if j not in fold)
    if drift>1e-4:raise ValueError('Identity mesh handoff requires compatible source bind worlds')
    names=[(r['name'],r['subindex']) for r in selection['meshes']]
    if not names or len(set(names))!=len(names):raise ValueError('Explicit unique mesh selection required')
    actual=[(o.name,o.subindex) for o in mesh.objects]
    if len(set(actual))!=len(actual) or set(names)-set(actual):raise ValueError('Source mesh identity missing or ambiguous')
    model=smd.SMD();index={j:i for i,j in enumerate(order)}
    for j in order:model.bones.append(smd.Bone(index[j],j,-1 if parent[j] is None else index[parent[j]],tuple(rest[j]['t']),tuple(rest[j]['r'])))
    rows=[];all_positions=[];all_weights={};vertex_offset=0;split_vertices=0;unsafe_vertices=0
    for obj in mesh.objects:
        if (obj.name,obj.subindex) not in names:continue
        points=np.asarray(obj.positions[0].data,dtype=float)[:,:3].copy()
        normals=np.asarray(obj.normals[0].data,dtype=float)[:,:3].copy()
        tex=[x for x in obj.texture_coordinates if x.name=='map1']
        if len(tex)!=1:raise ValueError('Explicit source map1 UV channel required')
        uv=np.asarray(tex[0].data,dtype=float)[:,:2].copy();count=len(points)
        # Ultimate decoded textures use a top-left origin. SMD uses bottom-left;
        # HSDRaw's importer flips V again. Its exporter also flips V, so an SMD
        # roundtrip alone cannot detect this error (Charizard's teal head).
        if uv_convention=='hsd_smd':uv[:,1]=1-uv[:,1]
        if points.shape!=(count,3) or normals.shape!=(count,3) or uv.shape!=(count,2) or not count or not all(np.isfinite(x).all() for x in (points,normals,uv)):
            raise ValueError('Nonempty finite vertex attributes with matching domains required')
        weights=[[] for _ in range(count)]
        if obj.parent_bone_name:
            joint=obj.parent_bone_name
            if joint not in source_world or obj.bone_influences:raise ValueError('Rigid source binding ambiguous or unknown')
            world=source_world[joint];points=(np.c_[points,np.ones(count)]@world.T)[:,:3]
            normals=normals@np.linalg.inv(world[:3,:3])
            weights=[[(index[fold.get(joint,joint)],1.)] for _ in range(count)]
        else:
            for influence in obj.bone_influences:
                joint=influence.bone_name
                if joint not in source_world:raise ValueError('Unknown weighted source joint')
                for weight in influence.vertex_weights:
                    i=weight.vertex_index;amount=float(weight.vertex_weight)
                    if type(i) is not int or not 0<=i<count or not np.isfinite(amount) or amount<0:raise ValueError('Invalid source influence')
                    k=index[fold.get(joint,joint)];same=[n for n,(b,_) in enumerate(weights[i]) if b==k]
                    if same:weights[i][same[0]]=(k,weights[i][same[0]][1]+amount)
                    else:weights[i].append((k,amount))
        lengths=np.linalg.norm(normals,axis=1)
        if np.any(lengths<1e-12):raise ValueError('Zero source normal')
        normals/=lengths[:,None]
        totals=np.array([sum(w for _,w in links) for links in weights])
        if any(not links for links in weights) or np.max(np.abs(totals-1))>.0002:raise ValueError('Complete source weights must sum to one within measured source rounding')
        for i,links in enumerate(weights):
            mismatch=(len(links)==1 and links[0][1]!=1.) or (len(links)>1 and links[0][1]>=RIGID_THRESHOLD)
            if envelope_policy=='preserve_weighted_transform':
                weights[i],change=prepare_links(links);split_vertices+=change['split']
            else:unsafe_vertices+=mismatch
        for i,links in enumerate(weights):
            for bone,amount in links:
                ids,values=all_weights.setdefault(order[bone],([],[]));ids.append(vertex_offset+i);values.append(amount)
        triangles=np.asarray(obj.vertex_indices)
        if triangles.ndim!=1 or triangles.dtype.kind not in 'ui' or len(triangles)%3 or not len(triangles) or np.any(triangles<0) or np.any(triangles>=count):raise ValueError('Bounded explicit triangle indices required')
        group=len(rows);placeholder=len(order)+group;material=f'mesh_{group:03d}'
        model.bones.append(smd.Bone(placeholder,f'Joint_0_Object_{group}',-1))
        vertices=[smd.Vertex(tuple(points[i]),tuple(normals[i]),tuple(uv[i]),weights[i],parent=placeholder) for i in range(count)]
        for face in triangles.reshape(-1,3):model.triangles.append(smd.Triangle(material,tuple(vertices[int(i)] for i in face)))
        rows.append(dict(name=obj.name,subindex=obj.subindex,material=material,placeholder=placeholder,
            vertices=count,triangles=len(triangles)//3,unused_vertices=count-len(set(map(int,triangles))),
            max_influences=max(map(len,weights)),weight_sum_error=float(np.max(np.abs(totals-1)))))
        all_positions.extend(points);vertex_offset+=count
    Skin(all_positions,all_weights,source_world,weight_sum_tolerance=.0002)
    return model,dict(status='SOURCE_MESH_HANDOFF_IMPORT_UNVERIFIED' if not unsafe_vertices else 'SOURCE_ENVELOPE_MATRIX_MODE_CONFLICT',joints=len(order),mesh_groups=rows,
        source_vertices=vertex_offset,triangle_corners=len(model.triangles)*3,weighted_joints=len(all_weights),
        bind_world_drift=drift,requires_original_dat_binds=True,
        nonunit_scale_joints=[j for j in order if rest[j]['s']!=[1.,1.,1.]],native_accepted=False,
        envelope_policy=envelope_policy,uv_convention=uv_convention,split_vertices=split_vertices,unsafe_vertices=unsafe_vertices,
        scope='Source-space positions and full supplied weights; no grip/fitting transforms, weight truncation or weight normalization. Normals are normalized. SMD omits scale: preserve template DAT binds. Mesh/material/game readback remains required.')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('mesh','source-rig','target-rig','template','selection','out'):p.add_argument('--'+arg,type=Path,required=True)
    p.add_argument('--reader-dir',type=Path)
    p.add_argument('--envelope-policy',choices=['preserve_entries','preserve_weighted_transform'],default='preserve_entries')
    p.add_argument('--uv-convention',choices=['source','hsd_smd'],default='source')
    a=p.parse_args(argv)
    if a.reader_dir:sys.path.insert(0,str(a.reader_dir.resolve()))
    import ssbh_data_py as ssbh
    metadata=read_json(a.target_rig.read_bytes());target,_=read_skeleton(a.template.read_bytes(),metadata['order'])
    for key in ('order','parent','rest'):
        if target[key]!=metadata[key]:raise ValueError('Target metadata differs from actual template DAT')
    paths={k:getattr(a,k) for k in ('mesh','source_rig','target_rig','template','selection')}
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    pins=freeze(out/'frozen-inputs',paths,project_root=Path(__file__).resolve().parents[2])
    model,receipt=prepare(ssbh.mesh_data.read_mesh(str(a.mesh)),read_json(a.source_rig.read_bytes()),target,read_json(a.selection.read_bytes()),envelope_policy=a.envelope_policy,uv_convention=a.uv_convention)
    smd.save(model,out/'source.smd');receipt['smd']=fingerprint(out/'source.smd')
    finish(out/'final-inputs',pins,project_root=Path(__file__).resolve().parents[2]);write_new(out/'receipt.json',receipt)
    print(receipt['status'],receipt['source_vertices'],'vertices',len(receipt['mesh_groups']),'mesh groups')


if __name__=='__main__':main()
