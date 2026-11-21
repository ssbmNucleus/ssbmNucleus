import base64
import io
import json
import re

import numpy as np
import pytest
from PIL import Image

from shared.aiengine import image_api
from randall.assistant import engine, live_runs, store, tools
from shared import mod_files
from randall.recolor import skin_lab as lab, texture_material as material
from randall.assistant.vision import tool_images
from tests.backend.test_assistant_skin_lab import session, png


def array(raw):
    return np.array(Image.open(io.BytesIO(raw)).convert('RGBA'))


def swatch():
    return mod_files.register(png('green'), 'Leather.png')['file_id']


def preview(**kwargs):
    kwargs.setdefault('minimum_size', 1)
    return material.skin_material('test', 'preview', texture_indices=[0],
                                  material_file_id=swatch(), mode='tile', **kwargs)


def test_mask_preview_apply_refine_reset_and_original_preservation(session):
    viewer, source = session
    original = dict(viewer.pixels)
    result = preview(mask={'hue_min': 350, 'hue_max': 20}, strength=1, shading=0)
    assert not viewer.updates and not lab._sessions['test']['edited']
    assert result['reading'] and result['selected_pixels'] == {'0': 256}
    assert tool_images('skin_material', result)[1]['type'] == 'image_url'
    assert len(array(mod_files.resolve(result['files'][0]['file_id'])[0].read_bytes())) > 0
    applied = material.skin_material('test', 'apply', preview_id=result['preview_id'])
    assert not applied.get('reading') and applied['files']
    assert viewer.pixels[1] == original[1]
    assert viewer.pixels[2] == original[2]
    assert np.array_equal(array(viewer.pixels[0])[..., 3], array(original[0])[..., 3])
    assert array(viewer.pixels[0])[0, 0, :3].tolist() == [0, 128, 0]
    again = material.skin_material('test', 'preview', preview_id=result['preview_id'], strength=0.5)
    material.skin_material('test', 'apply', preview_id=again['preview_id'])
    assert array(viewer.pixels[0])[0, 0, :3].tolist() == [110, 79, 15]
    # Applying twice must not accumulate the overlay.
    edited = viewer.pixels[0]
    material.skin_material('test', 'apply', preview_id=again['preview_id'])
    assert viewer.pixels[0] == edited
    exported = lab.skin_lab('test', 'export')['files'][0]
    assert exported['file_id'] != source['file_id']
    material.skin_material('test', 'reset', preview_id=again['preview_id'])
    assert viewer.pixels == original
    assert not mod_files.resolve(source['file_id'])[1]['edited']


def test_spatial_mask_protects_pixels_and_preserves_alpha(session):
    viewer, _ = session
    before = array(viewer.pixels[0])
    mask = np.full((16, 16, 4), 255, dtype=np.uint8)
    mask[:8, :, :3] = 0
    mask[8:12, :, 3] = 0
    mask[12:, :8, :3] = 128
    mask_id = mod_files.register(lab._png(mask), 'Mask.png')['file_id']
    result = preview(strength=1, shading=0, mask_files=[{'texture_index': 0, 'file_id': mask_id}])
    material.skin_material('test', 'apply', preview_id=result['preview_id'])
    after = array(viewer.pixels[0])
    assert np.array_equal(before[:12], after[:12])
    assert np.array_equal(before[..., 3], after[..., 3])
    assert after[15, 15, :3].tolist() == [0, 128, 0]
    assert after[15, 0, 0] in (109, 110)


@pytest.mark.parametrize('change', [{'mask': {'unknown': 1}}, {'mask': {'sat_min': 90, 'sat_max': 10}},
    {'mask': {'hue_min': float('nan')}}, {'strength': float('inf')}, {'tile_size': True},
    {'mode': 'other'}, {'mask_files': [{'texture_index': 0, 'file_id': '../secret'}]},
    {'mask': {'hue_min': 120, 'hue_max': 160}}])
def test_bad_or_empty_mask_never_writes(session, change):
    viewer, _ = session
    args = dict(session_id='test', action='preview', texture_indices=[0], material_file_id=swatch(), mode='tile')
    args.update(change)
    with pytest.raises(ValueError): material.skin_material(**args)
    assert not viewer.updates


def test_stale_preview_and_palette_snapshot_cannot_erase_later_edits(session):
    viewer, _ = session
    plan = preview()
    lab.skin_lab('test', 'analyze_palette', texture_indices=[0])
    lab.skin_lab('test', 'recolor', adjustments=[{'index': 0, 'hue_shift': 100}])
    changed = viewer.pixels[0]
    with pytest.raises(ValueError, match='changed'):
        material.skin_material('test', 'apply', preview_id=plan['preview_id'])
    assert viewer.pixels[0] == changed
    plan = preview()
    material.skin_material('test', 'apply', preview_id=plan['preview_id'])
    with pytest.raises(ValueError, match='Analyze'):
        lab.skin_lab('test', 'reset_palette')


def test_six_disjoint_previews_survive_until_applied(session):
    viewer, _ = session
    viewer.textures = [{'index': i, 'width': 16, 'height': 16} for i in range(6)]
    viewer.pixels = {i: png('red') for i in range(6)}
    fid = swatch()
    previews = [material.skin_material('test', 'preview', texture_indices=[i], material_file_id=fid,
                mode='tile', minimum_size=1) for i in range(6)]
    for result in previews:
        material.skin_material('test', 'apply', preview_id=result['preview_id'])
    assert viewer.updates == list(range(6))


def test_preview_limit_is_explicit_and_overlap_is_reported(session, monkeypatch):
    first = preview()
    second = preview()
    assert second['overlapping_previews'] == [{'preview_id': first['preview_id'], 'texture_indices': [0]}]
    monkeypatch.setattr(material, 'MAX_PLANS', 2)
    with pytest.raises(ValueError, match='storage is full'):
        preview()
    material.skin_material('test', 'apply', preview_id=first['preview_id'])
    with pytest.raises(ValueError, match='changed'):
        material.skin_material('test', 'apply', preview_id=second['preview_id'])


def test_encoding_roundtrip_is_used_for_stale_checks(session, monkeypatch):
    viewer, _ = session
    update = viewer.update_texture
    def quantized(index, raw):
        pixels = array(raw)
        pixels[..., :3] = pixels[..., :3] // 8 * 8
        update(index, lab._png(pixels))
    monkeypatch.setattr(viewer, 'update_texture', quantized)
    result = preview()
    material.skin_material('test', 'apply', preview_id=result['preview_id'])
    # Real encoders may change the submitted pixels, so revisions compare readback.
    material.skin_material('test', 'preview', preview_id=result['preview_id'], strength=0.2)


def test_partial_native_failure_rolls_back(session, monkeypatch):
    viewer, _ = session
    before = dict(viewer.pixels)
    update = viewer.update_texture
    failed = False
    def fail_once(index, raw):
        nonlocal failed
        update(index, raw)
        if index == 1 and not failed:
            failed = True
            raise RuntimeError('native reply lost')
    monkeypatch.setattr(viewer, 'update_texture', fail_once)
    result = material.skin_material('test', 'preview', texture_indices=[0, 1], material_file_id=swatch(), mode='tile')
    with pytest.raises(ValueError, match='restored'):
        material.skin_material('test', 'apply', preview_id=result['preview_id'])
    assert viewer.pixels == before


def test_projection_requires_geometry_and_upscales_small_canvases(session, monkeypatch):
    viewer, _ = session
    monkeypatch.setattr(viewer, 'get_uv_layout', lambda: [], raising=False)
    # No layout to project onto: that texture is tiled, and the reply says so,
    # instead of refusing the whole preview and costing the model a round.
    tiled = material.skin_material('test', 'preview', texture_indices=[0], material_file_id=swatch())
    assert tiled['tiled_without_uv_layout'] == [0]
    tris = [[0, 0, 1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0],
            [1, 0, 1, 1, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 0]]
    monkeypatch.setattr(viewer, 'get_uv_layout', lambda: [{'index': 0, 'triangles': tris}])
    viewer.textures[2].update(matAnim=True, animates=0)
    result = material.skin_material('test', 'preview', texture_indices=[0, 2], material_file_id=swatch())
    assert result['world_scale'] > 0
    material.skin_material('test', 'apply', preview_id=result['preview_id'])
    # At least minimum_size; any growth past it must be reported as detail sizing.
    size = array(viewer.pixels[0]).shape
    assert size[0] >= 128
    if size[0] > 128:
        assert result['enlarged_for_detail']['0'] == [size[1], size[0]]
    assert not any(i == 1 for i in viewer.updates)


def test_four_pixel_body_retains_pattern_and_reset_restores_dimensions(session):
    viewer, _ = session
    original = np.full((4, 4, 4), [240, 160, 180, 255], dtype=np.uint8)
    original[:, :2, 3] = 170
    viewer.pixels[0] = lab._png(original)
    tile = np.full((32, 32, 4), [90, 40, 20, 255], dtype=np.uint8)
    tile[::4, :, :3] = [180, 100, 60]
    fid = mod_files.register(lab._png(tile), 'Pattern.png')['file_id']
    mask = np.full((4, 4, 4), 255, dtype=np.uint8)
    mask[:, :2, :3] = 0
    mid = mod_files.register(lab._png(mask), 'Mask.png')['file_id']
    args = dict(texture_indices=[0], material_file_id=fid, mode='tile', strength=1, shading=0,
                mask_files=[{'texture_index': 0, 'file_id': mid}])
    result = material.skin_material('test', 'preview', **args)
    assert result['dimensions']['0'] == {'original': [4, 4], 'proposed': [128, 128]}
    refined = material.skin_material('test', 'preview', preview_id=result['preview_id'], **args)
    material.skin_material('test', 'apply', preview_id=refined['preview_id'])
    pixels = array(viewer.pixels[0])
    assert pixels.shape == (128, 128, 4)
    expected = np.repeat(np.repeat(original, 32, axis=0), 32, axis=1)
    assert np.array_equal(pixels[:, :64], expected[:, :64])
    assert np.array_equal(pixels[..., 3], expected[..., 3])
    assert len(np.unique(pixels[:, 64:, :3].reshape(-1, 3), axis=0)) > 1
    material.skin_material('test', 'reset', preview_id=refined['preview_id'])
    assert np.array_equal(array(viewer.pixels[0]), original)


def test_refine_rejects_actually_changed_target_or_swatch(session):
    plan = preview()
    with pytest.raises(ValueError, match='new target'):
        material.skin_material('test', 'preview', preview_id=plan['preview_id'], texture_indices=[1])
    with pytest.raises(ValueError, match='new target'):
        material.skin_material('test', 'preview', preview_id=plan['preview_id'], material_file_id=swatch())


def test_stale_native_resize_readback_rolls_back_and_is_not_success(session, monkeypatch):
    viewer, _ = session
    before = dict(viewer.pixels)
    update = viewer.update_texture
    def stale(index, raw):
        with Image.open(io.BytesIO(raw)) as image:
            cropped = image.crop((0, 0, 16, 16))
            update(index, lab._png(np.array(cropped)))
    monkeypatch.setattr(viewer, 'update_texture', stale)
    plan = material.skin_material('test', 'preview', texture_indices=[0], material_file_id=swatch(), mode='tile')
    with pytest.raises(ValueError, match='Update HSDRawViewer'):
        material.skin_material('test', 'apply', preview_id=plan['preview_id'])
    assert viewer.pixels == before


def test_surface_coverage_includes_eye_background_and_all_blink_frames(session):
    viewer, _ = session
    # Body plus nine eye expressions exceeds the former eight-texture limit.
    pink = [255, 207, 222, 255]
    body = np.full((16, 16, 4), pink, dtype=np.uint8)
    eye = body.copy()
    eye[3:13, 3:13] = [255, 255, 255, 255]  # white rim
    eye[5:11, 5:11] = [30, 160, 150, 255]  # iris
    eye[7:9, 7:9] = [0, 0, 0, 255]  # pupil
    viewer.textures = [{'index': i, 'width': 16, 'height': 16, 'matAnim': i >= 2,
                        'animates': 1 if i >= 2 else -1} for i in range(10)]
    viewer.pixels = {i: lab._png(body if i == 0 else eye) for i in range(10)}
    originals = dict(viewer.pixels)
    mask = {'hue_min': 320, 'hue_max': 360, 'sat_min': 10, 'lum_min': 55}
    coverage = tools.execute(tools.prepare('skin_material', {'session_id': 'test', 'action': 'coverage', 'mask': mask}))
    assert not coverage.get('error'), coverage
    assert not viewer.updates and len(coverage['files']) == 2
    assert [row['texture_index'] for row in coverage['matches']] == list(range(10))
    assert coverage['matches'][1]['selected_pixels'] == 156
    fid = mod_files.register(png((100, 55, 25, 255)), 'Brown leather.png')['file_id']
    args = dict(material_file_id=fid, mask=mask, mode='tile', minimum_size=1, strength=1, shading=0)
    partial = material.skin_material('test', 'preview', texture_indices=[0, 1], **args)
    assert partial['unselected_animation_variants'] == list(range(2, 10))
    assert len(partial['unselected_mask_matches']) == 8
    result = tools.execute(tools.prepare('skin_material', {'session_id': 'test', 'action': 'preview',
                           'texture_indices': list(range(10)), **args}))
    assert not result.get('error'), result
    assert not result['unselected_mask_matches'] and not result['unselected_animation_variants']
    assert len(result['files']) == 2
    material.skin_material('test', 'apply', preview_id=result['preview_id'])
    for index in range(1, 10):
        pixels = array(viewer.pixels[index])
        assert pixels[0, 0].tolist() == [100, 55, 25, 255]
        assert np.array_equal(pixels[3:13, 3:13], eye[3:13, 3:13])
    material.skin_material('test', 'reset', preview_id=result['preview_id'])
    assert viewer.pixels == originals


def test_coverage_requires_mask_and_reports_unscanned_textures(session):
    viewer, _ = session
    with pytest.raises(ValueError, match='explicit'):
        material.skin_material('test', 'coverage', mask={})
    with pytest.raises(ValueError, match='texture_indices'):
        material.skin_material('test', 'coverage')
    viewer.textures[2].update(width=4096, height=4096)
    result = material.skin_material('test', 'coverage', mask={'hue_min': 320, 'hue_max': 360})
    assert result['unscanned_texture_indices'] == [2]
    assert result['scanned_texture_indices'] == [0, 1]
    assert not viewer.updates


class Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def iter_content(self, size): yield json.dumps(self.body).encode()


def test_provider_fresh_images_metadata_and_private_credentials(session, monkeypatch):
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response({'data': [{'b64_json': base64.b64encode(png('brown')).decode()}], 'usage': {'cost': 0.014}})
    monkeypatch.setattr(image_api.requests, 'post', post)
    monkeypatch.delenv('NUCLEUS_MATERIAL_MODEL', raising=False)
    call = tools.prepare('generate_material', {'prompt': 'weathered leather'})
    first = tools.execute(call, image_key='secret-test-key')
    second = tools.execute(call, image_key='secret-test-key')
    assert first['files'][0]['file_id'] != second['files'][0]['file_id']
    assert first['cost_usd'] == 0.014 and first['reading']
    # The card's Developer details show the cost; Randall is never handed a dollar figure to repeat.
    from randall.assistant import compaction
    seen = compaction.model_view(first)
    assert 'cost_usd' not in seen and 'cost_per_material_usd' not in seen and seen['files'] == first['files']
    assert first['provider'] == 'openrouter' and 'provider' not in seen, "nor the provider's name"
    assert tool_images('generate_material', first)[1]['type'] == 'image_url'
    assert len(calls) == 2 and calls[0][0].endswith('/api/v1/images')
    assert calls[0][1]['json']['n'] == 1
    assert calls[0][1]['headers']['Authorization'] == 'Bearer secret-test-key'
    assert 'secret-test-key' not in json.dumps(first)
    with pytest.raises(ValueError): tools.prepare('generate_material', {'prompt': 'x', '_key': 'override'})


@pytest.mark.parametrize('status,attempts', [(401, 1), (402, 1), (403, 1), (429, 1),
                                             (400, 2), (500, 2), (503, 2)])
def test_provider_errors_do_not_leak_and_retry_only_transient_ones_once(monkeypatch, status, attempts):
    calls = []
    def post(*args, **kwargs):
        calls.append(1)
        return Response({'error': 'secret-test-key'}, status=status)
    monkeypatch.setattr(image_api.requests, 'post', post)
    with pytest.raises(ValueError) as error:
        image_api.generate_material_sheet(['denim'], key='secret-test-key')
    assert 'secret-test-key' not in str(error.value) and 'secret-test-key' not in error.value.diagnostic
    assert len(calls) == attempts
    # The card and Randall read a plain sentence (402: this month's usage ran out); the status is the developer's.
    assert str(error.value) == (image_api.USED_UP if status == 402 else image_api.UNAVAILABLE)
    assert f'HTTP {status}' in error.value.diagnostic


def test_a_failed_generation_reads_plainly_on_the_card_and_keeps_its_detail_for_the_report(monkeypatch):
    """Owner's rule (2026-10-07): users never see the provider's name, credits or money. The old card read
    "OpenRouter credits are exhausted. No automatic retry was made (HTTP 402)."."""
    monkeypatch.setattr(image_api.requests, 'post', lambda *a, **kw: Response({'error': 'x'}, status=402))
    result = tools.execute(tools.prepare('generate_material', {'prompt': 'denim'}), image_key='k')
    assert result['error'] == image_api.USED_UP
    assert result['diagnostic'] == 'image provider HTTP 402 (no credit left on the key); no automatic retry'
    for sentence in (image_api.USED_UP, image_api.UNAVAILABLE, image_api.NOT_SET_UP):
        assert not re.search(r'openrouter|credit|\$|key|HTTP', sentence, re.IGNORECASE), sentence
    from randall.assistant import compaction
    assert compaction.model_view(result) == {'error': image_api.USED_UP}, 'the detail never reaches the model'


def test_no_key_says_randalls_access_is_not_set_up():
    with pytest.raises(ValueError) as error:
        image_api.generate_material_sheet(['denim'], key=None)
    assert str(error.value) == image_api.NOT_SET_UP and 'no provider key' in error.value.diagnostic


def test_a_transient_failure_then_success_returns_the_image(monkeypatch):
    replies = [Response({'error': 'busy'}, status=400)]
    def post(*args, **kwargs):
        return replies.pop(0) if replies else Response({'data': [{'b64_json': base64.b64encode(png('red')).decode()}],
                                                        'usage': {'cost': 0.01}})
    monkeypatch.setattr(image_api.requests, 'post', post)
    pngs, metadata = image_api.generate_material_sheet(['denim'], key='k')
    assert pngs and metadata['cost_usd'] == 0.01


def test_a_timeout_is_never_retried_because_it_may_have_been_billed(monkeypatch):
    calls = []
    def post(*args, **kwargs):
        calls.append(1)
        raise image_api.requests.Timeout('slow')
    monkeypatch.setattr(image_api.requests, 'post', post)
    with pytest.raises(ValueError) as error:
        image_api.generate_material_sheet(['denim'], key='k')
    assert str(error.value) == image_api.UNAVAILABLE and 'no automatic retry' in error.value.diagnostic
    assert len(calls) == 1


@pytest.mark.parametrize('body', [{}, {'data': []}, {'data': [{'b64_json': 'not base64'}]},
    {'data': [{'b64_json': base64.b64encode(b'not an image').decode()}]}])
def test_provider_rejects_invalid_images(monkeypatch, body):
    monkeypatch.setattr(image_api.requests, 'post', lambda *a, **kw: Response(body))
    with pytest.raises(ValueError) as error:
        image_api.generate_material_sheet(['denim'], key='test')
    assert str(error.value) == image_api.UNAVAILABLE and 'raster image' in error.value.diagnostic


def test_engine_forwards_request_key_without_persisting_it(vault, monkeypatch):
    count = 0
    keys = []
    def provider(messages, *args):
        nonlocal count
        count += 1
        if count == 1:
            yield {'type': 'completion', 'message': {'role': 'assistant', 'content': None, 'tool_calls': [
                {'id': 'gen', 'function': {'name': 'generate_material', 'arguments': '{"prompt":"denim"}'}}]}}
        else:
            yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Swatch ready.'}}
    def generate(prompts, *, key=None, style='swatch'):
        keys.append(key)
        return [png('blue')] * len(prompts), {'provider': 'openrouter', 'model': 'test'}
    monkeypatch.setattr(engine, '_provider', provider)
    monkeypatch.setattr(material, 'generate_material_sheet', generate)
    run = engine.start(None, 'Generate denim', {}, request_key='private-request-key')
    list(live_runs.stream(run))
    assert keys == ['private-request-key'] and run.answer['status'] == 'done'
    assert 'private-request-key' not in json.dumps(store.get(run.chat_id))


# ---- several materials, one image ------------------------------------------

def sheet(colors, gutter=12, split=(200, 200)):
    """A 2x2 sheet like the provider draws: four colours split by black gutters
    that cross at `split` (the model does not always centre them)."""
    from PIL import Image, ImageDraw
    image = Image.new('RGBA', (400, 400), (0, 0, 0, 255))
    draw = ImageDraw.Draw(image)
    half, (sx, sy) = gutter // 2, split
    cells = ((0, 0, sx, sy), (sx, 0, 400, sy), (0, sy, sx, 400), (sx, sy, 400, 400))
    for (x0, y0, x1, y1), color in zip(cells, colors):
        draw.rectangle([x0 + half, y0 + half, x1 - 1 - half, y1 - 1 - half], fill=color)
    return image


def test_a_sheet_is_cut_on_its_gutters_into_the_requested_order():
    colors = [(200, 40, 40, 255), (40, 60, 200, 255), (220, 180, 40, 255), (40, 200, 190, 255)]
    crops = image_api.split_sheet(sheet(colors))
    assert len(crops) == 4
    for crop, color in zip(crops, colors):
        pixels = np.asarray(crop)
        assert (pixels == color).all(), 'no gutter black may survive in a swatch'


def test_an_off_centre_gutter_is_found_rather_than_assumed():
    colors = [(200, 40, 40, 255), (40, 60, 200, 255), (220, 180, 40, 255), (40, 200, 190, 255)]
    crops = image_api.split_sheet(sheet(colors, split=(230, 175)))
    for crop, color in zip(crops, colors):
        assert (np.asarray(crop) == color).all(), 'a half split would cut into the neighbour'


def test_several_materials_cost_one_request_and_come_back_in_order(session, monkeypatch):
    calls = []
    colors = [(200, 40, 40, 255), (40, 60, 200, 255), (220, 180, 40, 255), (40, 200, 190, 255)]
    buffer = io.BytesIO()
    sheet(colors).save(buffer, format='PNG')
    def post(url, **kwargs):
        calls.append(kwargs['json'])
        return Response({'data': [{'b64_json': base64.b64encode(buffer.getvalue()).decode()}],
                         'usage': {'cost': 0.01}})
    monkeypatch.setattr(image_api.requests, 'post', post)
    call = tools.prepare('generate_material', {'prompts': ['aztec fret', 'serape', 'gold']})
    result = tools.execute(call, image_key='k')
    assert len(calls) == 1, 'three materials, ONE billed image'
    assert [m['prompt'] for m in result['materials']] == ['aztec fret', 'serape', 'gold']
    assert len(result['files']) == 3 and result['cost_usd'] == 0.01
    assert result['cost_per_material_usd'] == round(0.01 / 3, 6)
    prompt = calls[0]['prompt']
    assert 'Top-left: aztec fret.' in prompt and 'Bottom-left: gold.' in prompt
    assert 'Bottom-right: plain flat neutral grey.' in prompt, 'the unused quadrant is kept inert'
    first = mod_files.resolve(result['files'][0]['file_id'])[0].read_bytes()
    assert (np.asarray(Image.open(io.BytesIO(first)).convert('RGBA')) == colors[0]).all()


def test_one_material_is_still_a_plain_swatch(session, monkeypatch):
    calls = []
    def post(url, **kwargs):
        calls.append(kwargs['json'])
        return Response({'data': [{'b64_json': base64.b64encode(png('brown')).decode()}]})
    monkeypatch.setattr(image_api.requests, 'post', post)
    result = tools.execute(tools.prepare('generate_material', {'prompts': ['leather']}), image_key='k')
    assert len(result['files']) == 1 and 'grid' not in calls[0]['prompt'].lower()


@pytest.mark.parametrize('args', [{'prompts': []}, {'prompts': ['a'] * 5}, {'prompts': ['']},
                                  {'prompt': 'a', 'prompts': ['b']}, {}])
def test_malformed_material_requests_never_reach_the_provider(session, monkeypatch, args):
    monkeypatch.setattr(image_api.requests, 'post', lambda *a, **k: pytest.fail('billed a bad request'))
    try:
        result = tools.execute(tools.prepare('generate_material', args), image_key='k')
    except ValueError:
        return                                  # refused at prepare: never billed
    assert result.get('error'), 'a malformed request must come back as an error'


def test_continuity_remembers_each_swatch_s_own_prompt():
    from randall.assistant.continuity import working_context
    receipts = [{'name': 'generate_material', 'arguments': {'prompts': ['aztec', 'serape']},
                 'result': {'files': [{'file_id': 'a', 'extension': '.png'}, {'file_id': 'b', 'extension': '.png'}],
                            'materials': [{'prompt': 'aztec', 'file_id': 'a'}, {'prompt': 'serape', 'file_id': 'b'}],
                            'cost_usd': 0.01}}]
    swatches = working_context(receipts)['material_swatches']
    assert {s['file_id']: s['prompt'] for s in swatches} == {'a': 'aztec', 'b': 'serape'}
    # This state is in the model's context: no dollar figure for Randall to repeat.
    assert not any('cost_usd' in s for s in swatches)


def test_coverage_of_named_textures_needs_no_colour_mask(session):
    """A known part IS its textures, so naming them selects them whole -- the
    same thing an omitted mask means for preview."""
    viewer, _ = session
    result = material.skin_material('test', 'coverage', texture_indices=[0, 1])
    assert {m['texture_index'] for m in result['matches']} == {0, 1}
    assert all(m['fraction'] == 1.0 for m in result['matches'])
    assert not viewer.updates, 'coverage never edits'


def test_a_texture_is_enlarged_until_a_tile_spans_enough_texels():
    """Mario's 8x8 cap panel spread six texels over 2.9 square units of cap, so
    a projected motif smeared. texels_per_tile measures that budget."""
    from shared.rendering import compose
    # One triangle covering a quarter of the UV square over a 10x10 world patch.
    tri = [0, 0, 0.5, 0, 0, 0.5,   0, 0, 0, 10, 0, 0, 0, 10, 0]
    sparse = compose.texels_per_tile([tri], 8, 8, world_scale=10)
    dense = compose.texels_per_tile([tri], 512, 512, world_scale=10)
    assert sparse < material.DETAIL_TEXELS < dense
    assert abs(dense / sparse - 64) < 1e-6, 'doubling the side doubles the budget'
    assert compose.texels_per_tile([], 8, 8, 10) is None
    assert compose.texels_per_tile([[0, 0, 0, 0, 0, 0] + [0] * 9], 8, 8, 10) is None


def test_apply_with_preview_arguments_previews_and_applies_in_one_call(session):
    viewer, _ = session
    applied = material.skin_material('test', 'apply', texture_indices=[0], material_file_id=swatch(),
                                     mode='tile', mask={'hue_min': 350, 'hue_max': 20},
                                     strength=1, shading=0, minimum_size=1)
    assert applied['action'] == 'apply' and applied['updated_textures'] == [0]
    assert applied['selected_pixels'] == {'0': 256} and applied['files']
    assert array(viewer.pixels[0])[0, 0, :3].tolist() == [0, 128, 0]
    # It left a real plan behind, so reset undoes it like any other apply.
    material.skin_material('test', 'reset', preview_id=applied['preview_id'])
    assert array(viewer.pixels[0])[0, 0, :3].tolist() != [0, 128, 0]
    # Apply by id with changed controls refines that preview, then applies it.
    refined = material.skin_material('test', 'apply', preview_id=applied['preview_id'], strength=0.5)
    assert refined['action'] == 'apply'
    assert array(viewer.pixels[0])[0, 0, :3].tolist() == [110, 79, 15]
    # A new swatch cannot refine the old plan, so it becomes a fresh one-shot.
    fresh = material.skin_material('test', 'apply', preview_id=applied['preview_id'], texture_indices=[0],
                                   material_file_id=swatch(), mode='tile', strength=1, shading=0,
                                   minimum_size=1)
    assert fresh['preview_id'] != applied['preview_id']
    # Reset stays strict: it only ever undoes a named plan.
    with pytest.raises(ValueError, match='takes only session_id, action and preview_id'):
        material.skin_material('test', 'reset', preview_id=applied['preview_id'], strength=0.5)


def test_a_material_edit_keeps_the_rest_of_the_palette_analysis(session):
    viewer, _ = session
    groups = lab.skin_lab('test', 'analyze_palette', texture_indices=[0, 1, 2])['groups']
    before = dict(viewer.pixels)
    material.skin_material('test', 'apply', texture_indices=[0], material_file_id=swatch(),
                           mode='tile', strength=1, shading=0, minimum_size=1)
    painted = viewer.pixels[0]
    analysis = lab._sessions['test']['palette']
    assert analysis is not None and 0 not in analysis['originals'], 'only the painted texture leaves'
    # The same group numbers still recolour, without a new analysis, and never
    # restore the painted texture from its old snapshot.
    result = lab.skin_lab('test', 'recolor', adjustments=[
        {'index': i, 'hue_shift': 90} for i in range(len(groups))])
    assert 0 not in result['updated_textures'] and viewer.pixels[0] == painted
    assert any(viewer.pixels[i] != before[i] for i in result['updated_textures'])


def test_painting_every_analysed_texture_ends_the_analysis(session):
    lab.skin_lab('test', 'analyze_palette', texture_indices=[0])
    material.skin_material('test', 'apply', texture_indices=[0], material_file_id=swatch(),
                           mode='tile', strength=1, shading=0, minimum_size=1)
    with pytest.raises(ValueError, match='Analyze the palette first'):
        lab.skin_lab('test', 'recolor', adjustments=[{'index': 0, 'hue_shift': 90}])


def test_coverage_ignores_preview_settings_sent_by_habit(session):
    result = material.skin_material('test', 'coverage', texture_indices=[0], mask={'hue_min': 350, 'hue_max': 20},
                                    material_file_id=swatch(), mode='project', strength=0.8)
    assert result['matches'][0]['texture_index'] == 0


def test_a_numeric_string_camera_angle_is_read_as_a_number(session, monkeypatch):
    viewer, _ = session
    seen = {}
    monkeypatch.setattr(viewer, 'set_camera', lambda **kw: seen.update(kw), raising=False)
    monkeypatch.setattr(viewer, 'camera', seen, raising=False)
    lab.skin_lab('test', 'camera', camera={'rot_y': '180'})
    assert seen == {'rot_y': 180.0}
    with pytest.raises(ValueError, match='must be a number'):
        lab.skin_lab('test', 'camera', camera={'rot_y': 'around'})


def test_texel_density_is_measured_per_axis():
    """Samus's armour strips: fine along u, starved along v. Averaging hid it."""
    from shared.rendering import compose
    # UV spans the full texture both ways; the world triangle is 1 unit wide
    # along u but 16 units long along v.
    tri = [0, 0, 1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 16, 0]
    along_u, along_v = compose.texels_per_tile_axes([tri], 64, 64, world_scale=1)
    assert along_u == pytest.approx(64) and along_v == pytest.approx(4)
    assert compose.texels_per_tile_axes([], 64, 64, 1) is None


def test_artwork_style_asks_for_the_subject_itself(monkeypatch):
    """The swatch wrapper forbids objects and lettering, so "money themed"
    could only ever come back as green noise."""
    from shared.aiengine import image_api
    seen = []
    monkeypatch.setattr(image_api, '_request', lambda prompt, key: (seen.append(prompt) or (Image.new('RGBA', (8, 8)), {})))
    image_api.generate_material_sheet(['a wall of US hundred dollar bills'], key='k', style='artwork')
    assert seen[0].startswith(image_api.ARTWORK) and 'no objects' not in seen[0]
    image_api.generate_material_sheet(['worn denim'], key='k')
    assert seen[1].startswith(image_api.SWATCH)
    with pytest.raises(ValueError, match='style must be'):
        image_api.generate_material_sheet(['x'], key='k', style='photo')


def test_artwork_prompts_are_generated_one_per_request(monkeypatch):
    """A 2x2 grid would halve the resolution of art that must read as itself."""
    from shared.aiengine import image_api
    calls = []
    monkeypatch.setattr(image_api, '_request',
                        lambda prompt, key: (calls.append(prompt) or (Image.new('RGBA', (8, 8)), {'cost_usd': .01})))
    pngs, metadata = image_api.generate_material_sheet(['bills', 'coins'], key='k', style='artwork')
    assert len(calls) == 2 and len(pngs) == 2 and metadata['cost_usd'] == pytest.approx(.02)


def test_fit_lays_the_artwork_across_the_texture_without_repeating(vault, monkeypatch):
    """A banknote must stay one banknote: fit keeps the image whole and its
    aspect, where tile and project square it into a repeating swatch."""
    import numpy as np
    from shared.rendering import compose
    original = np.zeros((16, 32, 4), np.uint8)
    original[..., 3] = 255
    art = np.zeros((8, 8, 3), np.uint8)
    art[:4] = (200, 30, 30)          # top half red, bottom half blue
    art[4:] = (30, 30, 200)
    mask = np.ones((16, 32), bool)
    fitted = compose.composite(original, art, mask, mode='fit')
    tiled = compose.composite(original, art, mask, mode='tile')
    assert fitted[0, 0, 0] > fitted[0, 0, 2] and fitted[-1, 0, 2] > fitted[-1, 0, 0], 'stretched once, top to bottom'
    assert (fitted[:, 0] == fitted[:, -1]).all(), 'no horizontal repeat across the texture'
    assert (tiled[:8, 0] == tiled[8:, 0]).all(), 'tile repeats the swatch down the texture'
    assert not (fitted[:8, 0] == fitted[8:, 0]).all(), 'fit does not repeat it'


def _quad(world_units, size=128):
    """One UV-filling triangle pair over `world_units` of model surface."""
    import numpy as np
    s = float(world_units)
    return np.array([
        [0, 0, 1, 0, 0, 1,  0, 0, 0,  s, 0, 0,  0, s, 0],
        [1, 0, 1, 1, 0, 1,  s, 0, 0,  s, s, 0,  0, s, 0],
    ], dtype=float), size


def test_a_projected_material_is_filtered_to_what_the_texels_can_carry():
    """Point-sampling a fine swatch per texel keeps whichever pixel it lands
    on: an ice Falcon's frost became camo splotches on his 128px suit."""
    import numpy as np
    from shared.rendering import compose
    triangles, size = _quad(8)          # one tile spans 16 texels here
    material = np.random.default_rng(0).integers(0, 255, (256, 256, 3), dtype=np.uint8)
    filtered = compose.prefilter_material(material, triangles, size, size, world_scale=1.0)
    assert filtered.shape[0] < material.shape[0], 'averaged down to the sampling density'
    assert filtered.shape[0] >= 4
    # High-frequency energy (neighbour differences) drops: that IS the aliasing.
    rough = np.abs(np.diff(material[..., 0].astype(float), axis=1)).mean()
    smooth = np.abs(np.diff(filtered[..., 0].astype(float), axis=1)).mean()
    assert smooth < rough


def test_a_material_the_texels_can_carry_is_left_alone():
    """Coarse enough to sample honestly: no filtering, no lost detail."""
    import numpy as np
    from shared.rendering import compose
    triangles, size = _quad(0.25)       # one tile spans ~512 texels
    material = np.random.default_rng(1).integers(0, 255, (64, 64, 3), dtype=np.uint8)
    assert compose.prefilter_material(material, triangles, size, size, world_scale=1.0) is material
