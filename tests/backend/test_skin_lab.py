from tests.paths import BACKEND
import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

from shared.rendering import palette


def _solid(w, h, rgba):
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    arr[:, :] = rgba
    return arr


def test_hsl_round_trip():
    rgb = np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255],
                    [200, 150, 60], [17, 230, 190]], dtype=np.float64)
    h, s, l = palette.rgb_to_hsl(rgb)
    back = palette.hsl_to_rgb(h, s, l)
    assert np.abs(back.astype(int) - rgb.astype(int)).max() <= 1


def test_analyze_finds_distinct_hue_groups():
    # one red texture, one green texture (both > MIN_GROUP_PIXELS)
    red = _solid(32, 32, (200, 40, 40, 255))
    green = _solid(32, 32, (40, 200, 40, 255))
    groups, pixel_maps = palette.analyze({0: red, 1: green}, max_groups=2)
    assert len(groups) == 2
    hues = sorted(g['centerHue'] for g in groups)
    assert hues[0] < 30 or hues[0] > 330      # red-ish
    assert 90 < hues[1] < 150                 # green-ish
    # every opaque pixel assigned to some group
    assert set(np.unique(pixel_maps[0])) <= {0, 1}
    assert set(np.unique(pixel_maps[1])) <= {0, 1}


def test_analyze_skips_grays_and_extremes():
    gray = _solid(32, 32, (128, 128, 128, 255))     # s < 15
    black = _solid(32, 32, (5, 5, 5, 255))          # l < 10
    clear = _solid(32, 32, (200, 40, 40, 0))        # transparent
    groups, pixel_maps = palette.analyze({0: gray, 1: black, 2: clear}, max_groups=4)
    assert groups == []
    for m in pixel_maps.values():
        assert (m == 255).all()


def test_apply_hue_shift_recolors_only_the_group():
    # red square with a gray border: shift red +120 degrees -> green, gray untouched
    arr = _solid(32, 32, (128, 128, 128, 255))
    arr[8:24, 8:24] = (200, 40, 40, 255)   # 256 px, above the 100-px group floor
    groups, pixel_maps = palette.analyze({0: arr}, max_groups=1)
    assert len(groups) == 1
    out = palette.apply_adjustments(arr, pixel_maps[0], {0: (120.0, 0.0)})
    assert out is not None
    center = out[16, 16]
    assert center[1] > center[0] and center[1] > center[2]   # now green-dominant
    assert tuple(out[0, 0][:3]) == (128, 128, 128)           # gray border untouched
    assert (out[..., 3] == 255).all()                        # alpha preserved


def test_tint_colorizes_whites_keeping_lightness():
    from shared.rendering import compose
    arr = _solid(8, 8, (220, 220, 220, 255))   # near-white (no hue)
    arr[0, 0] = (40, 40, 40, 255)              # dark pixel outside mask (lum_min)
    mask = compose.build_mask(arr, sat_max=18, lum_min=30)
    out = compose.tint(arr, mask, hue=120.0, saturation=50.0)
    px = out[4, 4]
    assert px[1] > px[0] and px[1] > px[2]     # white became green
    assert px.max() > 180                      # stayed light
    assert tuple(out[0, 0][:3]) == (40, 40, 40)  # unmasked untouched
    assert compose.tint(arr, np.zeros((8, 8), dtype=bool), 120) is None


def test_apply_no_adjustments_returns_none():
    arr = _solid(8, 8, (200, 40, 40, 255))
    groups, pixel_maps = palette.analyze({0: arr}, max_groups=1)
    assert palette.apply_adjustments(arr, pixel_maps[0], {0: (0.0, 0.0)}) is None


def test_saturation_shift_clamps():
    arr = _solid(16, 16, (200, 40, 40, 255))
    groups, pixel_maps = palette.analyze({0: arr}, max_groups=1)
    out = palette.apply_adjustments(arr, pixel_maps[0], {0: (0.0, -200.0)})
    # fully desaturated -> r == g == b
    px = out[4, 4]
    assert abs(int(px[0]) - int(px[1])) <= 1 and abs(int(px[1]) - int(px[2])) <= 1


def test_build_mask_hue_wraparound_and_bounds():
    from shared.rendering import compose
    arr = np.zeros((1, 4, 4), dtype=np.uint8)
    arr[0, 0] = (200, 40, 40, 255)    # red, hue ~0
    arr[0, 1] = (40, 40, 200, 255)    # blue, hue ~240
    arr[0, 2] = (128, 128, 128, 255)  # gray
    arr[0, 3] = (200, 40, 40, 0)      # transparent red
    # wrap range 330..30 selects red only
    m = compose.build_mask(arr, hue_min=330, hue_max=30, sat_min=15)
    assert m.tolist() == [[True, False, False, False]]
    # plain range selects blue
    m = compose.build_mask(arr, hue_min=200, hue_max=260)
    assert m.tolist() == [[False, True, False, False]]
    # low-sat bright = gray
    m = compose.build_mask(arr, sat_max=10, lum_min=30)
    assert m.tolist() == [[False, False, True, False]]


def test_composite_modulates_by_original_lightness():
    from shared.rendering import compose
    arr = np.zeros((2, 2, 4), dtype=np.uint8)
    arr[0, 0] = (60, 60, 220, 255)    # dark blue
    arr[0, 1] = (170, 170, 250, 255)  # light blue
    arr[1, 0] = (128, 128, 128, 255)  # gray (unmasked)
    arr[1, 1] = (60, 60, 220, 0)      # transparent
    material = np.full((1, 1, 3), 128, dtype=np.uint8)  # flat gray fabric
    mask = compose.build_mask(arr, hue_min=200, hue_max=260, sat_min=15)
    out = compose.composite(arr, material, mask)
    # light pixel ends up brighter than dark pixel (shading survived)
    assert out[0, 1, :3].mean() > out[0, 0, :3].mean()
    assert tuple(out[1, 0][:3]) == (128, 128, 128)   # unmasked untouched
    assert out[1, 1, 3] == 0                          # alpha preserved
    # empty mask -> None
    assert compose.composite(arr, material, np.zeros((2, 2), dtype=bool)) is None


def test_hue_shift_only_masked_pixels():
    from shared.rendering import compose
    arr = np.zeros((1, 2, 4), dtype=np.uint8)
    arr[0, 0] = (40, 40, 200, 255)   # blue
    arr[0, 1] = (200, 40, 40, 255)   # red
    mask = compose.build_mask(arr, hue_min=200, hue_max=260)
    out = compose.hue_shift(arr, mask, hue_delta=-120.0)
    assert out[0, 0, 1] > out[0, 0, 2]               # blue (240) - 120 -> green (120)
    assert tuple(out[0, 1][:3]) == (200, 40, 40)     # red untouched
    assert compose.hue_shift(arr, mask) is None      # no deltas -> None


def _tri(uv0, uv1, uv2, p0, p1, p2):
    return list(uv0) + list(uv1) + list(uv2) + list(p0) + list(p1) + list(p2)


def test_rasterize_uv_layout_interpolates_positions():
    from shared.rendering import compose
    # one triangle covering the lower-left half of an 8x8 texture, mapped to
    # a world quad in the XY plane (z=0): pos should interpolate linearly
    tris = [_tri((0, 0), (1, 0), (0, 1),
                 (0, 0, 0), (8, 0, 0), (0, 8, 0))]
    pos, nrm, covered = compose.rasterize_uv_layout(tris, 8, 8)
    assert covered[0, 0] and not covered[7, 7]
    # texel centers map 1:1 onto world units here
    assert np.allclose(pos[0, 0], (0.5, 0.5, 0), atol=0.6)
    assert np.allclose(pos[0, 6], (6.5, 0.5, 0), atol=0.6)
    # face normal is +/-Z
    assert abs(nrm[0, 0][2]) > 0.99


def test_rasterize_uv_layout_wrap_modes():
    from shared.rendering import compose
    # UVs spanning two repeats: with REPEAT both halves of the texture get
    # painted; with CLAMP out-of-range texels fold onto the border
    tris = [_tri((0, 0), (2, 0), (0, 1),
                 (0, 0, 0), (16, 0, 0), (0, 8, 0))]
    _, _, cov_rep = compose.rasterize_uv_layout(tris, 8, 8,
                                                wrap_s=compose.WRAP_REPEAT)
    assert cov_rep[0].all()
    m = compose._fold_indices(np.array([8, 9, 15]), 8, compose.WRAP_MIRROR)
    assert m.tolist() == [7, 6, 0]
    c = compose._fold_indices(np.array([-3, 9]), 8, compose.WRAP_CLAMP)
    assert c.tolist() == [0, 7]


def test_triplanar_is_consistent_across_textures():
    from shared.rendering import compose
    # two different textures whose UV islands land on the SAME world surface
    # must bake the SAME pattern -- that's the seamlessness guarantee
    mat = (np.random.RandomState(7).rand(16, 16, 3) * 255).astype(np.uint8)
    quad = ((0, 0, 0), (8, 0, 0), (0, 8, 0))
    tris = [_tri((0, 0), (1, 0), (0, 1), *quad)]
    pos_a, nrm_a, cov_a = compose.rasterize_uv_layout(tris, 8, 8)
    pos_b, nrm_b, cov_b = compose.rasterize_uv_layout(tris, 8, 8)
    sample_a = compose.triplanar_sample(mat, pos_a, nrm_a, 4.0)
    sample_b = compose.triplanar_sample(mat, pos_b, nrm_b, 4.0)
    both = cov_a & cov_b
    assert np.allclose(sample_a[both], sample_b[both])


def test_composite_project_paints_and_respects_mask():
    from shared.rendering import compose
    arr = np.zeros((8, 8, 4), dtype=np.uint8)
    arr[..., :3] = 200
    arr[..., 3] = 255
    layout = {'triangles': [
        _tri((0, 0), (1, 0), (0, 1), (0, 0, 0), (8, 0, 0), (0, 8, 0)),
        _tri((1, 1), (1, 0), (0, 1), (8, 8, 0), (8, 0, 0), (0, 8, 0)),
    ], 'wrapS': 1, 'wrapT': 1}
    mat = np.zeros((4, 4, 3), dtype=np.uint8)
    mat[..., 0] = 255   # pure red material
    mask = np.zeros((8, 8), dtype=bool)
    mask[:, :4] = True
    out = compose.composite_project(arr, mat, mask, layout, world_scale=8.0)
    assert out is not None
    assert out[2, 2, 0] > 150 and out[2, 2, 1] < 100   # masked: red
    assert tuple(out[2, 6][:3]) == (200, 200, 200)     # unmasked untouched
    # empty mask -> None
    assert compose.composite_project(
        arr, mat, np.zeros((8, 8), bool), layout, 8.0) is None


def test_composite_project_shared_shade_ref():
    from shared.rendering import compose
    layout = {'triangles': [
        _tri((0, 0), (1, 0), (0, 1), (0, 0, 0), (8, 0, 0), (0, 8, 0)),
        _tri((1, 1), (1, 0), (0, 1), (8, 8, 0), (8, 0, 0), (0, 8, 0)),
    ], 'wrapS': 1, 'wrapT': 1}
    mat = np.full((4, 4, 3), 128, dtype=np.uint8)
    mask = np.ones((8, 8), dtype=bool)
    dark = np.zeros((8, 8, 4), dtype=np.uint8)
    dark[..., :3] = 40
    dark[..., 3] = 255
    light = np.zeros((8, 8, 4), dtype=np.uint8)
    light[..., :3] = 220
    light[..., 3] = 255
    # per-texture refs: both expose the material identically (seam step)
    a = compose.composite_project(dark, mat, mask, layout, 8.0)
    b = compose.composite_project(light, mat, mask, layout, 8.0)
    assert abs(int(a[4, 4, 0]) - int(b[4, 4, 0])) <= 2
    # shared ref: the dark texture renders the material darker
    ref = (compose.masked_lightness(dark, mask)
           + compose.masked_lightness(light, mask)) / 2
    a = compose.composite_project(dark, mat, mask, layout, 8.0, shade_ref=ref)
    b = compose.composite_project(light, mat, mask, layout, 8.0, shade_ref=ref)
    assert int(b[4, 4, 0]) - int(a[4, 4, 0]) > 40


def test_layout_world_scale_from_bbox():
    from shared.rendering import compose
    layouts = [{'triangles': [
        _tri((0, 0), (1, 0), (0, 1), (0, 0, 0), (10, 0, 0), (0, 10, 0))]}]
    ws = compose.layout_world_scale(layouts, fraction=0.5)
    assert abs(ws - np.sqrt(200) * 0.5) < 1e-6
    assert compose.layout_world_scale([{'triangles': []}]) == 1.0


def test_fox_region_map_is_valid():
    import json as _json
    path = BACKEND_DIR / 'assets' / 'texture_regions' / 'Fox.json'
    region_map = _json.loads(path.read_text(encoding='utf-8'))
    regions = region_map['regions']
    assert set(region_map['protected']) <= set(
        regions['eyes'] + regions['face_detail'])
    for name, idxs in regions.items():
        assert idxs == sorted(set(idxs)), name
        assert all(0 <= i < region_map['basis']['textureCount'] for i in idxs), name
