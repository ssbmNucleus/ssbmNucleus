"""Standalone skeleton descriptor roundtrip before importing any mesh or fighter.

Writes classical SRT HSD_Joint descriptors with inverse binds. The archive has
no drawables, materials, game callbacks or fighter lookup table; it is not a
playable costume. Its purpose is to prove numeric traversal and stored binds.
"""
import hashlib
import re
import struct
import numpy as np
from vault.echo.datroot import build
from .compat.rig_inventory import costume_inventory,Archive
from .rig_wrappers import canonical_jobj_order
from .rigmap import euler_xyz


def world_matrices(rig):
    result={}
    for j in rig['order']:
        r=rig['rest'][j];local=np.eye(4)
        local[:3,:3]=euler_xyz(r['r'])*np.asarray(r['s']);local[:3,3]=r['t']
        parent=rig['parent'][j];result[j]=result[parent]@local if parent is not None else local
    return result


def read_skeleton(blob, order):
    inventory=costume_inventory(blob);archive=Archive(blob)
    if (len(order)!=inventory['joint_count'] or len(set(order))!=len(order) or
            any(not isinstance(j,str) or not j for j in order)):raise ValueError('Explicit unique joint names must match archive traversal')
    rig=dict(order=list(order),parent={},rest={});inverse={}
    for j,row in zip(order,inventory['joints']):
        rig['parent'][j]=None if row['parent'] is None else order[row['parent']]
        rig['rest'][j]=dict(r=row['rotation'],t=row['translation'],s=row['scale'])
        offset=archive.ptr(row['offset']+0x38)
        if offset is None:raise ValueError('Stored inverse bind required')
        archive.require(offset,48);m=np.eye(4)
        m[:3]=np.array(struct.unpack_from('>12f',blob,32+offset)).reshape(3,4)
        if not np.isfinite(m).all():raise ValueError('Nonfinite inverse bind')
        inverse[j]=m
    worlds=world_matrices(rig)
    for j in order:
        if np.max(np.abs(worlds[j]@inverse[j]-np.eye(4)))>1e-4:raise ValueError('Inverse bind does not match stored SRT')
    return rig,inverse


def build_skeleton(rig, *, root_name='PlyPipeline_Share_joint',max_world_error=1e-4):
    canonical=canonical_jobj_order(rig)
    if canonical['order']!=rig['order']:raise ValueError('Canonical depth-first joint order required before serialization')
    count=len(rig['order'])
    if count>255 or not re.fullmatch(r'Ply[A-Za-z0-9_]+_joint',root_name):raise ValueError('Bounded skeleton and plain joint root name required')
    if type(max_world_error) not in (int,float) or not np.isfinite(max_world_error) or max_world_error<0:
        raise ValueError('Finite nonnegative error budget required')
    order=rig['order'];index={j:i for i,j in enumerate(order)};children={j:[] for j in order}
    for j in order:
        parent=rig['parent'][j]
        if parent is not None:children[parent].append(j)
    stored=dict(order=order,parent=rig['parent'],rest={})
    for j in order:
        stored['rest'][j]={key:np.asarray(rig['rest'][j][key],dtype=np.float32).astype(float).tolist() for key in ('r','t','s')}
    worlds=world_matrices(stored);reference=world_matrices(rig)
    if any(not np.isfinite(w).all() or np.linalg.cond(w[:3,:3])>1e8 for w in worlds.values()):raise ValueError('Singular or nonfinite stored bind')
    data=bytearray(count*(0x40+0x30));relocations=[]
    def pointer(slot,value):
        struct.pack_into('>I',data,slot,value);relocations.append(slot)
    for j in order:
        i=index[j];offset=i*0x40;rest=stored['rest'][j]
        struct.pack_into('>I',data,offset+4,9) # SKELETON | CLASSICAL_SCALE
        if children[j]:pointer(offset+8,index[children[j][0]]*0x40)
        parent=rig['parent'][j]
        if parent is not None:
            siblings=children[parent];position=siblings.index(j)
            if position+1<len(siblings):pointer(offset+12,index[siblings[position+1]]*0x40)
        struct.pack_into('>9f',data,offset+0x14,*(rest['r']+rest['s']+rest['t']))
        inverse_offset=count*0x40+i*0x30;pointer(offset+0x38,inverse_offset)
        inverse=np.linalg.inv(worlds[j])[:3].astype(np.float32)
        if not np.isfinite(inverse).all():raise ValueError('Inverse bind overflow')
        struct.pack_into('>12f',data,inverse_offset,*inverse.ravel())
    blob=build(data,relocations,[(0,root_name)],[])
    inventory=costume_inventory(blob);archive=Archive(blob)
    if inventory['joint_count']!=count or inventory['dobj_descriptor_count']!=0:raise ValueError('Stored skeleton domain differs')
    for i,row in enumerate(inventory['joints']):
        expected=None if rig['parent'][order[i]] is None else index[rig['parent'][order[i]]]
        if row['offset']!=i*0x40 or row['parent']!=expected:raise ValueError('Actual DAT traversal differs from curve order')
        inv=archive.ptr(row['offset']+0x38);archive.require(inv,48)
        matrix=np.eye(4);matrix[:3]=np.array(struct.unpack_from('>12f',blob,32+inv)).reshape(3,4)
        if np.max(np.abs(worlds[order[i]]@matrix-np.eye(4)))>1e-4:raise ValueError('Stored inverse bind differs')
    error=max(float(np.max(np.abs(worlds[j]-reference[j]))) for j in order)
    if error>max_world_error:raise ValueError('Float32 bind drift exceeds budget')
    return blob,dict(status='SKELETON_ARCHIVE_ROUNDTRIP_NOT_COSTUME',joints=count,drawables=0,
        root=root_name,sha256=hashlib.sha256(blob).hexdigest(),bytes=len(blob),bind_world_error=error,
        depth_first_indices_verified=True,native_accepted=False)


