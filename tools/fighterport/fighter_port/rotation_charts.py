"""Fixed orientation helpers move Euler singularities without changing bone worlds.

Choose among the 24 proper axis permutations on an explicit sampled domain.
The helper carries T*Q and the original joint Q^-1*R*S. This is an offline rig
representation choice, not a time-varying branch switch or an engine mapping.
"""
import copy
import itertools
from types import SimpleNamespace
import numpy as np
from .rigmap import euler_xyz
from .smpl_to_anim import to_hsd_euler


def orientations(directions=0):
    if type(directions) is not int or not 0<=directions<=256:raise ValueError('At most 256 additional sphere directions required')
    out=[np.eye(3)]
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((-1,1),repeat=3):
            q=np.eye(3)[:,perm]*signs
            if np.linalg.det(q)>.5 and not any(np.array_equal(q,x) for x in out):out.append(q)
    for i in range(directions):
        z=1-2*(i+.5)/directions;angle=i*np.pi*(3-np.sqrt(5));radius=np.sqrt(1-z*z)
        normal=np.array([radius*np.cos(angle),radius*np.sin(angle),z])
        axis=np.eye(3)[int(np.argmin(np.abs(normal)))];x=axis-normal*np.dot(axis,normal);x/=np.linalg.norm(x)
        out.append(np.column_stack((x,np.cross(normal,x),normal)))
    return out


def choose(rig,domains,*,threshold=.2,directions=0):
    if not domains or not 0<threshold<1:raise ValueError('Explicit domains and singularity threshold required')
    result={};choices=orientations(directions)
    for j in rig.order:
        rotations=[]
        for worlds in domains:
            p=rig.parent[j];local=np.linalg.solve(worlds[p],worlds[j]) if p is not None else worlds[j]
            s=np.linalg.norm(local[:,:3,:3],axis=1)
            if np.any(s<1e-10):raise ValueError('Singular scale')
            r=local[:,:3,:3]/s[:,None,:]
            if not np.allclose(np.swapaxes(r,1,2)@r,np.eye(3),rtol=0,atol=1e-7) or np.any(np.linalg.det(r)<0):raise ValueError('Chart selection requires shear-free local rotations')
            rotations.append(r)
        r=np.concatenate(rotations)
        def clearance(q):return float(np.sqrt(np.maximum(0.,1.-np.clip(r[:,:,0]@q[:,2],-1.,1.)**2)).min())
        before=clearance(np.eye(3))
        if before>=threshold:continue
        q=max(choices,key=clearance);after=clearance(q)
        if after>before+1e-9:result[j]=dict(rotation=q.tolist(),before=before,after=after)
    return result


def extend_rig(original,charts):
    if set(charts)-set(original.order):raise ValueError('Unknown chart bones')
    helpers={j:'__chart_before_'+j for j in charts}
    if set(helpers.values())&set(original.order):raise ValueError('Chart helper collision')
    rest=copy.deepcopy(original.rest);parent=dict(original.parent);order=[]
    for j in original.order:
        if j in charts:
            q=np.asarray(charts[j]['rotation'],dtype=float)
            if q.shape!=(3,3) or not np.allclose(q.T@q,np.eye(3),atol=1e-12,rtol=0) or np.linalg.det(q)<0:raise ValueError('Proper orthogonal chart required')
            helper=helpers[j];parent[helper]=parent[j];parent[j]=helper
            rest[helper]=dict(r=to_hsd_euler(q),t=rest[j]['t'][:],s=[1.,1.,1.])
            rest[j]['r']=to_hsd_euler(q.T@euler_xyz(rest[j]['r']));rest[j]['t']=[0.,0.,0.];order.append(helper)
        order.append(j)
    rig=SimpleNamespace(order=order,parent=parent,rest=rest,world={},local={},charts=charts,chart_helpers=helpers,
        original_order=original.order,original_parent=original.parent)
    for j in order:
        v=rest[j];m=np.eye(4);m[:3,:3]=euler_xyz(v['r'])*np.asarray(v['s']);m[:3,3]=v['t'];rig.local[j]=m
        rig.world[j]=rig.world[parent[j]]@m if parent[j] is not None else m
    for j in original.order:
        if not np.allclose(rig.world[j],original.world[j],atol=1e-9,rtol=0):raise ValueError('Chart changed bind world')
    return rig


def expand_worlds(rig,worlds):
    if set(worlds)!=set(rig.original_order):raise ValueError('Exact original world domain required')
    n=len(next(iter(worlds.values())));out={}
    for j in rig.original_order:
        p=rig.original_parent[j]
        if j in rig.charts:
            pw=worlds[p] if p is not None else np.broadcast_to(np.eye(4),(n,4,4))
            local=np.linalg.solve(pw,worlds[j]);h=np.broadcast_to(np.eye(4),(n,4,4)).copy()
            h[:,:3,:3]=rig.charts[j]['rotation'];h[:,:3,3]=local[:,:3,3]
            out[rig.chart_helpers[j]]=pw@h
        out[j]=worlds[j].copy()
    return out
