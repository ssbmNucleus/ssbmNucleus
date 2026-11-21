"""Represent T*C*R*S with two ordinary SRT nodes, without projecting shear.

A helper carries T*C and the original joint carries R*S. Original bind worlds
and skin weights are preserved. This constructs an OFFLINE rig; reordered
indices require explicit engine-consumer mapping before native integration.
"""
import copy
from types import SimpleNamespace
import numpy as np
from .rigmap import euler_xyz


def extend_rig(original, helper_bones):
    bones=list(helper_bones)
    if len(set(bones))!=len(bones) or set(bones)-set(original.order):raise ValueError('Unique known helper bones required')
    helpers={j:'__scale_before_'+j for j in bones}
    if set(helpers.values())&set(original.order):raise ValueError('Helper name collision')
    rest=copy.deepcopy(original.rest);parent=dict(original.parent);order=[]
    for j in original.order:
        if j in helpers:
            helper=helpers[j];parent[helper]=parent[j];parent[j]=helper
            rest[helper]=dict(r=[0.,0.,0.],t=rest[j]['t'][:],s=[1.,1.,1.])
            rest[j]['t']=[0.,0.,0.];order.append(helper)
        order.append(j)
    rig=SimpleNamespace(order=order,parent=parent,rest=rest,local={},world={},helpers=helpers,
                        original_order=list(original.order),original_parent=dict(original.parent))
    for j in order:
        r=rest[j];local=np.eye(4);local[:3,:3]=euler_xyz(r['r'])*np.array(r['s']);local[:3,3]=r['t']
        rig.local[j]=local;rig.world[j]=rig.world[parent[j]]@local if parent[j] is not None else local
    for j in original.order:
        if not np.allclose(rig.world[j],original.world[j],rtol=0,atol=1e-9):raise ValueError('Helper insertion changed original bind world')
    return rig


def expand_worlds(rig, original_worlds, parent_scales, compensated):
    """Batched source world poses -> extended world poses for scalar authoring.

    parent_scales[j] is the IMMEDIATE source parent's interpolated track scale,
    one when unanimated. It is not accumulated world scale or the helper scale.
    The caller must obtain it from the same authoring sampler as original_worlds.
    """
    if set(original_worlds)!=set(rig.original_order) or set(compensated)-set(rig.helpers):
        raise ValueError('Source or compensation domain differs from helper rig')
    n=next(iter(original_worlds.values())).shape[0]
    if not n:raise ValueError('Nonempty pose arrays required')
    out={}
    for j in rig.original_order:
        world=original_worlds[j]
        if world.shape!=(n,4,4) or not np.isfinite(world).all():raise ValueError('Invalid source pose')
        parent=rig.original_parent[j]
        if j in rig.helpers:
            pw=original_worlds[parent] if parent is not None else np.broadcast_to(np.eye(4),(n,4,4))
            local=np.linalg.solve(pw,world)
            helper_local=np.broadcast_to(np.eye(4),(n,4,4)).copy();helper_local[:,:3,3]=local[:,:3,3]
            if j in compensated and parent is not None:
                scales=np.asarray(parent_scales[j],dtype=float)
                if scales.shape!=(n,3) or not np.isfinite(scales).all() or np.any(np.abs(scales)<1e-12):raise ValueError('Invalid immediate parent scale')
                helper_local[:,range(3),range(3)]=1./scales
            out[rig.helpers[j]]=pw@helper_local
        out[j]=world.copy()
    return out


def original_worlds(rig, expanded):
    return {j:expanded[j] for j in rig.original_order}
