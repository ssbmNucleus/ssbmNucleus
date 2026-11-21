"""Flatten an explicitly selected secondary UV color layer for static costumes.

UVs use decoded texture coordinates (v=0 at the top); the model exporter can
flip them afterward. This is a static diffuse approximation, not a shader port.
"""
import numpy as np
from PIL import Image


def one_tile(uv):
    """Whether a mesh's first coordinates lie within one repeat of its picture (on 0..1, or whole repeats off it:
    Squirtle's eye white sits two down, -1.85..-1.15). A picture that repeats draws such a mesh where the same
    coordinates moved onto 0..1 fall, so the layer bake may move them there (`layer_coordinates(base_repeat=True)`);
    not moved, every triangle is off the picture and the second layer (an iris) is drawn nowhere."""
    uv = np.asarray(uv, float)
    return bool(len(uv)) and bool(np.all(np.floor(uv.min(axis=0)) == np.floor(uv.max(axis=0) - 1e-6)))


def layer_coordinates(base_uv, overlay_uv, *, base_repeat=False, transform=(1,1,0,0)):
    """Translate complete repeat islands and apply Ultimate's secondary UV transform.

    CustomVector31 convention checked against ssbh_wgpu's TransformUv:
    https://github.com/ScanMountGoat/ssbh_wgpu/blob/main/ssbh_wgpu/src/shader/model.wgsl
    """
    base,second=np.asarray(base_uv,float).copy(),np.asarray(overlay_uv,float).copy()
    scale_u,scale_v,offset_u,offset_v=transform
    second[:,0]=scale_u*(second[:,0]-offset_u)
    second[:,1]=1-scale_v*(1-second[:,1]-offset_v)
    tile=np.zeros(2)
    if base_repeat:
        tile=np.floor(base.min(axis=0));base-=tile
        if np.any(base>1):raise ValueError('UV island spans tiles; split triangles before baking')
    return base,second,tile


def _sample(pixels, uv):
    h, w = pixels.shape[:2]
    xy = np.clip(uv * [w, h] - .5, [0, 0], [w-1, h-1])
    lo = np.floor(xy).astype(int)
    hi = np.minimum(lo+1, [w-1, h-1])
    f = xy-lo
    a = pixels[lo[..., 1], lo[..., 0]]
    b = pixels[lo[..., 1], hi[..., 0]]
    c = pixels[hi[..., 1], lo[..., 0]]
    d = pixels[hi[..., 1], hi[..., 0]]
    return ((a*(1-f[..., 0, None])+b*f[..., 0, None])*(1-f[..., 1, None])
            +(c*(1-f[..., 0, None])+d*f[..., 0, None])*f[..., 1, None])


def alpha_layer(base, overlay, base_uv, overlay_uv, indices, size=512):
    """Rasterize the UV correspondence and alpha-blend RGB; preserve base alpha.

    Both samplers clamp to edge. Overlapping destination UV triangles must
    describe the same mapping; different surfaces need separate materials.
    """
    base_uv, overlay_uv = np.asarray(base_uv), np.asarray(overlay_uv)
    if (base_uv.shape != overlay_uv.shape or base_uv.ndim != 2
            or base_uv.shape[1] != 2 or not np.isfinite(base_uv).all()
            or not np.isfinite(overlay_uv).all() or size < 2):
        raise ValueError('finite matching UV pairs and a positive texture size required')
    yy, xx = np.mgrid[:size, :size]
    result = _sample(np.asarray(base.convert('RGBA'), float),
                     np.stack([xx+.5, yy+.5], -1)/size)
    layer = np.asarray(overlay.convert('RGBA'), float)
    for tri in np.asarray(indices).reshape(-1, 3):
        points = base_uv[tri]*size
        a, b, c = points
        matrix = np.stack([b-a, c-a], axis=1)
        if abs(np.linalg.det(matrix)) < 1e-8:
            continue
        low = np.maximum(np.floor(points.min(axis=0)).astype(int), 0)
        high = np.minimum(np.ceil(points.max(axis=0)).astype(int), size-1)
        if np.any(low > high):
            continue
        y, x = np.mgrid[low[1]:high[1]+1, low[0]:high[0]+1]
        bc = (np.stack([x+.5, y+.5], -1)-a)@np.linalg.inv(matrix).T
        weights = np.concatenate([1-bc.sum(axis=-1, keepdims=True), bc], -1)
        inside = np.all(weights >= -1e-7, axis=-1)
        color = _sample(layer, weights@overlay_uv[tri])
        target = result[y, x]
        alpha = color[..., 3:4]/255
        target[..., :3] = target[..., :3]*(1-alpha)+color[..., :3]*alpha
        result[y[inside], x[inside]] = target[inside]
    return Image.fromarray(np.clip(np.rint(result), 0, 255).astype('uint8'))
