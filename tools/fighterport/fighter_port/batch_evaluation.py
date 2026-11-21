"""Batched equivalents of the scalar animation/source evaluators.

No sampling-domain reduction. Pose arrays are joint -> (frames, 4, 4). Skin
uses bounded frame chunks and all supplied vertices/weights. Scalar parity is
required by callers before substituting this evaluator in an acceptance run.
"""
import numpy as np
from scipy.spatial.transform import Rotation, Slerp


def times_array(times, end):
    if isinstance(end,(bool,np.bool_)) or not np.isscalar(end) or not np.isfinite(end) or end<0:raise ValueError('Finite nonnegative animation end required')
    ts=np.asarray(times,dtype=float)
    if ts.ndim!=1 or not len(ts) or not np.isfinite(ts).all() or np.any(ts<0) or np.any(ts>end) or np.any(np.diff(ts)<=0):
        raise ValueError('Distinct increasing finite frames within the animation required')
    return ts


def curve_values(keys, times):
    if not keys:raise ValueError('Empty curve')
    if any(k.outgoing not in ('step','linear','auto','fixed','spline') or not np.isfinite([k.in_slope,k.out_slope]).all() for k in keys):raise ValueError('Invalid curve interpolation or slope')
    kt=np.array([k.time for k in keys]);v=np.array([k.value for k in keys],dtype=float)
    if np.any(np.diff(kt)<=0) or not np.isfinite(np.r_[kt,v]).all():raise ValueError('Invalid curve keys')
    ts=np.asarray(times,dtype=float)
    if ts.ndim!=1 or not np.isfinite(ts).all():raise ValueError('Finite one-dimensional curve samples required')
    index=np.clip(np.searchsorted(kt,ts,side='right')-1,0,len(keys)-1)
    out=v[index].copy()
    for i,key in enumerate(keys[:-1]):
        mask=(index==i)&(ts>=kt[0])
        if not mask.any():continue
        h=kt[i+1]-kt[i];u=(ts[mask]-kt[i])/h
        if key.outgoing=='step':continue
        if key.outgoing in ('linear','auto'):out[mask]=v[i]+u*(v[i+1]-v[i])
        elif key.outgoing in ('fixed','spline'):
            out[mask]=(2*u**3-3*u*u+1)*v[i]+(u**3-2*u*u+u)*h*key.out_slope+(-2*u**3+3*u*u)*v[i+1]+(u**3-u*u)*h*keys[i+1].in_slope
        else:raise ValueError('Unsupported curve interpolation')
    if not np.isfinite(out).all():raise ValueError('Nonfinite curve evaluation')
    return out


def euler_matrices(angles):
    x,y,z=np.asarray(angles,dtype=float).T
    sx,cx,sy,cy,sz,cz=np.sin(x),np.cos(x),np.sin(y),np.cos(y),np.sin(z),np.cos(z)
    out=np.empty((len(x),3,3))
    out[:,0,:]=np.c_[cz*cy,cz*sx*sy-cx*sz,cz*cx*sy+sx*sz]
    out[:,1,:]=np.c_[sz*cy,sz*sx*sy+cx*cz,sz*cx*sy-sx*cz]
    out[:,2,:]=np.c_[-sy,sx*cy,cx*cy]
    return out


def animation_worlds(animation, rig, times):
    ts=times_array(times,animation.end);n=len(ts);out={}
    if not rig.order or len(set(rig.order))!=len(rig.order) or set(rig.parent)!=set(rig.order) or set(rig.rest)!=set(rig.order):raise ValueError('Exact unique rig domains required')
    if set(animation.channels)-set(rig.order):raise ValueError('Animation contains unknown joints')
    for j in rig.order:
        ch=animation.channels.get(j,{});rest=rig.rest[j]
        if set(ch)-{kind+axis for kind in ('rotate','translate','scale') for axis in 'XYZ'}:raise ValueError('Unknown animation channel')
        if any(np.asarray(rest[k]).shape!=(3,) or not np.isfinite(rest[k]).all() for k in ('r','t','s')):raise ValueError('Invalid rest transform')
        def values(kind,default):
            return np.column_stack([curve_values(ch[kind+axis],ts) if kind+axis in ch else np.full(n,rest[default][i]) for i,axis in enumerate('XYZ')])
        local=np.broadcast_to(np.eye(4),(n,4,4)).copy()
        local[:,:3,:3]=euler_matrices(values('rotate','r'))*values('scale','s')[:,None,:]
        local[:,:3,3]=values('translate','t')
        parent=rig.parent[j]
        if parent is not None and parent not in out:raise ValueError('Rig order must place parents before children')
        out[j]=out[parent]@local if parent is not None else local
    return out


def raw_worlds(raw, times):
    """RawSource POLICY evaluated in batches; raw validation still runs first."""
    ts=times_array(times,raw.end);n=len(ts);parts={};out={}
    left=np.minimum(np.floor(ts).astype(int),raw.end);right=np.minimum(left+1,raw.end);u=(ts-left)[:,None]
    for j,tr in raw.tracks.items():
        trans=(1-u)*tr.t[left]+u*tr.t[right];scale=(1-u)*tr.s[left]+u*tr.s[right]
        if raw.end==0 or np.array_equal(tr.q,np.broadcast_to(tr.q[0],tr.q.shape)):
            rot=np.broadcast_to(Rotation.from_quat(tr.q[0]).as_matrix(),(n,3,3)).copy()
        else:rot=Slerp(np.arange(raw.end+1),Rotation.from_quat(tr.q))(ts).as_matrix()
        parts[j]=(trans,rot,scale)
    for j in raw.order:
        parent=raw.parent[j]
        if j not in parts:local=np.broadcast_to(raw.bind[j],(n,4,4)).copy()
        else:
            trans,rot,scale=parts[j];local=np.broadcast_to(np.eye(4),(n,4,4)).copy()
            basis=rot*scale[:,None,:]
            if raw.tracks[j].compensate_scale and parent is not None:
                parent_scale=parts[parent][2] if parent in parts else np.ones((n,3))
                if np.any(np.abs(parent_scale)<1e-12):raise ValueError('Zero parent scale cannot be compensated')
                basis=basis/parent_scale[:,:,None]
            local[:,:3,:3]=basis;local[:,:3,3]=trans
        out[j]=out[parent]@local if parent is not None else local
    return out


def frame(worlds, index):
    return {j:w[index] for j,w in worlds.items()}


def deform(skin, worlds, start, stop):
    result=np.zeros((stop-start,skin.count,3))
    for j,ids,weights,local,unique in skin.parts:
        values=np.einsum('vi,fji->fvj',local,worlds[j][start:stop,:3,:],optimize=True)*weights[None,:,None]
        if unique:result[:,ids,:]+=values
        else:
            for i in range(stop-start):np.add.at(result[i],ids,values[i])
    return result


def measure_worlds(times, candidate, reference, skin=None, *, chunk_frames=32, reference_skin=None):
    ts=np.asarray(times,dtype=float);n=len(ts)
    if not n or ts.ndim!=1 or not np.isfinite(ts).all() or np.any(np.diff(ts)<=0) or set(candidate)!=set(reference) or not candidate:
        raise ValueError('Matching nonempty pose domains and increasing finite frames required')
    if type(chunk_frames) is not int or chunk_frames<=0:raise ValueError('Positive integer chunk size required')
    if reference_skin is not None:
        if skin is None or not np.array_equal(skin.positions,reference_skin.positions):
            raise ValueError('Separate binds require identical source vertex correspondence')
        a={j:(ids,weights) for j,ids,weights,_,_ in skin.parts}
        b={j:(ids,weights) for j,ids,weights,_,_ in reference_skin.parts}
        if set(a)!=set(b) or any(not all(np.array_equal(x,y) for x,y in zip(a[j],b[j])) for j in a):
            raise ValueError('Separate binds require identical source skin weights')
    else:reference_skin=skin
    worst={k:dict(value=0.,frame=None,joint=None) for k in ('pivot','basis','skin')}
    for j in candidate:
        a,b=candidate[j],reference[j]
        if a.shape!=(n,4,4) or b.shape!=(n,4,4) or not np.isfinite(a).all() or not np.isfinite(b).all():raise ValueError('Invalid pose array')
        if not np.allclose(a[:,3,:],[0,0,0,1],rtol=0,atol=1e-9) or not np.allclose(b[:,3,:],[0,0,0,1],rtol=0,atol=1e-9):raise ValueError('Affine pose arrays required')
        for key,values in (('pivot',np.linalg.norm(a[:,:3,3]-b[:,:3,3],axis=1)),('basis',np.max(abs(a[:,:3,:3]-b[:,:3,:3]),axis=(1,2)))):
            i=int(np.argmax(values))
            if values[i]>worst[key]['value']:worst[key]=dict(value=float(values[i]),frame=float(ts[i]),joint=j)
    if skin:
        for start in range(0,n,chunk_frames):
            stop=min(n,start+chunk_frames)
            distances=np.linalg.norm(deform(skin,candidate,start,stop)-deform(reference_skin,reference,start,stop),axis=2)
            i,v=np.unravel_index(int(np.argmax(distances)),distances.shape)
            if distances[i,v]>worst['skin']['value']:worst['skin']=dict(value=float(distances[i,v]),frame=float(ts[start+i]),vertex=int(v))
    return dict(samples=n,joints=len(candidate),vertices=skin.count if skin else 0,metrics=worst,
                skin_status='MEASURED' if skin else 'UNMEASURED',chunk_frames=chunk_frames)
