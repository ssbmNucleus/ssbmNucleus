import io

import numpy as np
import pytest
from PIL import Image

from randall.recolor import skin_lab as lab, texture_inspection
from shared import mod_files
from tests.backend.test_assistant_skin_lab import session, png


def test_live_usage_and_animation_links_use_renderer_indices(session):
    viewer, _ = session
    viewer.textures[2].update(matAnim=True, animates=0)
    viewer.get_uv_layout = lambda: [{'index': 0, 'triangles': [[0, 0, 1, 0, 0, 1, -2, 0, 0, 3, 0, 0, 0, 4, 0]]}]
    result = lab.skin_lab('test', 'texture_usage')
    rows = result['textures']
    assert rows[0]['animation_variants'] == [2]
    assert rows[0]['bounds'] == {'min': [-2, 0, 0], 'max': [3, 4, 0]}
    assert rows[2]['geometry_texture_index'] == 0 and rows[2]['mapped_triangles'] == 1
    assert rows[1]['mapped_triangles'] == 0 and 'bounds' not in rows[1]


def test_highlight_includes_animation_and_restores_without_editing(session):
    viewer, _ = session
    viewer.textures[2].update(matAnim=True, animates=0)
    before = dict(viewer.pixels)
    result = lab.skin_lab('test', 'highlight', texture_indices=[0])
    assert result['texture_indices'] == [0, 2]
    assert viewer.pixels == before and not lab._sessions['test']['edited']
    file, _ = mod_files.resolve(result['files'][0]['file_id'])
    pixels = np.array(Image.open(file))
    assert pixels[0, 0].tolist() == [255, 0, 255, 200]


def test_highlight_restores_if_capture_fails(session):
    viewer, _ = session
    before = dict(viewer.pixels)
    def fail(): raise RuntimeError('capture failed')
    viewer.grab_frame = fail
    with pytest.raises(RuntimeError): lab.skin_lab('test', 'highlight', texture_indices=[0, 1])
    assert viewer.pixels == before


def test_texture_sheet_pages_are_complete_and_no_edit(session):
    viewer, _ = session
    viewer.textures = [{'index': i, 'width': 16, 'height': 16} for i in range(35)]
    viewer.pixels = {i: png('pink') for i in range(35)}
    before = dict(viewer.pixels)
    first = lab.skin_lab('test', 'texture_sheet')
    second = lab.skin_lab('test', 'texture_sheet', page=1)
    assert first['texture_indices'] + second['texture_indices'] == list(range(35))
    # The on-screen census paints textures temporarily; every one is restored.
    assert first['pages'] == 2 and viewer.pixels == before and not lab._sessions['test']['edited']
    with pytest.raises(ValueError): lab.skin_lab('test', 'texture_sheet', page=2)


def test_dark_brown_palette_scoped_absolute_and_resettable(session):
    viewer, _ = session
    viewer.pixels[0] = png((250, 192, 210, 180))
    before = dict(viewer.pixels)
    lab.skin_lab('test', 'analyze_palette', texture_indices=[0], max_groups=1)
    args = [{'index': 0, 'set_hue': 25, 'set_saturation': 50, 'lightness_scale': 0.4}]
    lab.skin_lab('test', 'recolor', adjustments=args)
    after = viewer.pixels[0]
    pixel = np.array(Image.open(io.BytesIO(after)))[0, 0]
    assert pixel[0] > pixel[1] > pixel[2] and pixel[:3].max() < 160 and pixel[3] == 180
    assert viewer.pixels[1] == before[1] and viewer.pixels[2] == before[2]
    lab.skin_lab('test', 'recolor', adjustments=args)
    assert viewer.pixels[0] == after
    lab.skin_lab('test', 'reset_palette')
    assert viewer.pixels == before




def test_hidden_textures_are_labelled_and_an_edit_aimed_only_at_them_is_refused(session):
    viewer, _ = session
    viewer.get_uv_layout = lambda: []
    lab._sessions['test']['hidden_textures'] = {'lowpoly': [2], 'alternate': [1]}
    rows = {r['index']: r for r in lab.skin_lab('test', 'texture_usage')['textures']}
    assert rows[2]['hidden'] == 'lowpoly' and rows[1]['hidden'] == 'alternate' and 'hidden' not in rows[0]
    with pytest.raises(ValueError, match='never drawn on the fighter'):
        lab.skin_lab('test', 'analyze_palette', texture_indices=[1, 2])
    with pytest.raises(ValueError, match='never drawn on the fighter'):
        lab.skin_lab('test', 'analyze_palette', parts={'face': [2]})
    # A visible texture alongside keeps the low-poly copy in step with it.
    assert lab.skin_lab('test', 'analyze_palette', texture_indices=[0, 2])['groups'] is not None
