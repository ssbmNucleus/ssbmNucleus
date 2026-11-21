"""Explicit bind-space capsule conversion with measured float32 error bounds.

Endpoint-only conversion is insufficient when the old/new joint basis changes
scale. Only near-similarity transforms are admitted; arbitrary affine sphere
images would require ellipsoids. No runtime pose equivalence is implied.
"""
import numpy as np


def affine(value):
    m=np.asarray(value,dtype=float)
    if (m.shape!=(4,4) or not np.isfinite(m).all() or
            not np.array_equal(m[3],[0.,0.,0.,1.]) or np.linalg.cond(m[:3,:3])>1e8):
        raise ValueError('Finite nonsingular affine matrix required')
    return m


def rebase_capsule(old_bind,new_bind,a,b,radius,*,model_transform,relative_anisotropy=1e-5,max_world_error=1e-4):
    old=affine(old_bind);new=affine(new_bind);model=affine(model_transform)
    for value in (radius,relative_anisotropy,max_world_error):
        if type(value) not in (float,int) or not np.isfinite(value) or value<0:raise ValueError('Finite nonnegative radius and tolerances required')
    points=np.asarray([a,b],dtype=float)
    if points.shape!=(2,3) or not np.isfinite(points).all():raise ValueError('Two finite capsule endpoints required')
    mapping=np.linalg.solve(new,model@old);singular=np.linalg.svd(mapping[:3,:3],compute_uv=False)
    scale=float(np.mean(singular))
    anisotropy=float((singular.max()-singular.min())/scale)
    if anisotropy>relative_anisotropy:raise ValueError('Bone change would turn the capsule radius into an ellipsoid')
    local=(np.c_[points,np.ones(2)]@mapping.T)[:,:3]
    packed=local.astype(np.float32).astype(float);packed_radius=float(np.float32(radius*scale))
    if not np.isfinite(packed).all() or not np.isfinite(packed_radius):raise ValueError('Float32 geometry overflow')
    original_world=(np.c_[points,np.ones(2)]@(model@old).T)[:,:3]
    target_world=(np.c_[packed,np.ones(2)]@new.T)[:,:3]
    endpoint_error=float(np.max(np.linalg.norm(original_world-target_world,axis=1)))
    # Singular values bound the difference between the mapped sphere and the
    # rounded target sphere. Multiply by the new basis norm for model units.
    radial_bound=float(np.linalg.norm(new[:3,:3],2)*np.max(np.abs(radius*singular-packed_radius)))
    if endpoint_error+radial_bound>max_world_error:raise ValueError('Rebased capsule exceeds world-space error budget')
    return dict(status='BIND_GEOMETRY_REBASED_RUNTIME_PENDING',a=packed[0].tolist(),b=packed[1].tolist(),
        radius=packed_radius,endpoint_error=endpoint_error,radial_error_bound=radial_bound,
        world_error_bound=endpoint_error+radial_bound,relative_anisotropy=anisotropy,
        local_mapping=mapping.tolist(),native_accepted=False,
        scope='Bind-model-space capsule bound after float32 storage; animation, runtime scale and collision phases are unvalidated.')
