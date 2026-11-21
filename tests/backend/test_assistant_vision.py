"""Provider payload bounds, lossless duplicate detection and encoding reuse."""
import io

import pytest
from PIL import Image

from randall.assistant import vision
from shared import mod_files
from core import config


@pytest.fixture
def images(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'STORAGE_PATH', tmp_path)
    vision._encoded_preview.cache_clear()
    def register(index):
        image = Image.new('RGB', (128, 128), (index, 80, 100))
        output = io.BytesIO()
        image.save(output, format='PNG')
        return mod_files.register(output.getvalue(), f'preview-{index}.png')
    yield register
    vision._encoded_preview.cache_clear()


def receipt(files, name='hsdraw', **result):
    return {'name': name, 'result': {'files': files, **result}}


def count(content):
    return sum(block['type'] == 'image_url' for block in content)


def labels(content):
    return '\n'.join(block.get('text', '') for block in content)


def test_recent_history_shrinks_from_sixteen_to_six(images):
    files = [images(i) for i in range(20)]
    content = vision.context_images([receipt([file]) for file in files])
    assert count(content) == 6
    assert '14 older images omitted' in labels(content)
    for file in files[-6:]:
        assert file['file_id'] in labels(content)
    assert files[0]['file_id'] not in labels(content)


def test_entire_new_batch_survives_small_history_limit(images):
    old = [receipt([images(i)]) for i in range(5)]
    fresh = [receipt([images(i)]) for i in range(5, 13)]
    content = vision.context_images(old + fresh, fresh_receipts=fresh)
    assert count(content) == 8
    for entry in fresh:
        assert entry['result']['files'][0]['file_id'] in labels(content)


def test_duplicate_bytes_share_image_but_keep_both_identities(images):
    first, second = images(20), images(20)
    content = vision.context_images([receipt([first]), receipt([second])])
    assert first['file_id'] != second['file_id']
    assert count(content) == 1
    assert first['file_id'] in labels(content) and second['file_id'] in labels(content)
    assert 'PNG bytes identical' in labels(content)
    assert 'does not establish model or gameplay equivalence' in labels(content)


def test_one_pixel_change_is_not_suppressed(images):
    first = images(20)
    path, _ = mod_files.resolve(first['file_id'])
    with Image.open(path) as source:
        source.putpixel((64, 64), (21, 80, 100))
        output = io.BytesIO()
        source.save(output, format='PNG')
    changed = mod_files.register(output.getvalue(), 'tiny-change.png')
    content = vision.context_images([receipt([first, changed])])
    assert count(content) == 2
    assert 'PNG bytes identical' not in labels(content)


def test_encoding_is_reused_but_changed_file_still_rejected(images):
    file = images(20)
    result = {'files': [file]}
    assert count(vision.tool_images('hsdraw', result)) == 1
    assert count(vision.tool_images('hsdraw', result)) == 1
    cache = vision._encoded_preview.cache_info()
    assert cache.misses == 1 and cache.hits == 1
    path, _ = mod_files.resolve(file['file_id'])
    path.write_bytes(b'changed')
    rejected = vision.tool_images('hsdraw', result)
    assert count(rejected) == 0 and 'could not be attached' in labels(rejected)


def test_latest_swatch_and_render_are_kept(images):
    swatch, render = images(1), images(2)
    history = [receipt([swatch], 'generate_material'), receipt([render], 'skin_lab_open')]
    history.extend(receipt([images(i)], 'skin_lab', action='texture') for i in range(10, 30))
    content = vision.context_images(history)
    assert count(content) == 6
    assert swatch['file_id'] in labels(content) and render['file_id'] in labels(content)


def test_error_receipts_cannot_displace_comparison(images):
    comparison = [images(i) for i in range(8)]
    failed = receipt([images(30)], error='Failed')
    content = vision.context_images([receipt(comparison), failed])
    assert count(content) == 8
    assert failed['result']['files'][0]['file_id'] not in labels(content)


def test_pictures_attached_to_the_message_are_shown_not_only_named(images):
    """A render dragged from the workbench onto the message bar is the user pointing at it."""
    first, second = images(1), images(2)
    zipped = mod_files.register(b'PK\x05\x06' + b'\0' * 18, 'model.zip')
    content = vision.attachment_images([mod_files.describe(mod_files.resolve(f['file_id'])[1])
                                        for f in (first, zipped, second)])
    assert count(content) == 2, 'the ZIP is not a picture'
    assert 'preview-1.png' in labels(content) and 'pointing at it' in labels(content)
    many = [mod_files.describe(mod_files.resolve(images(i)['file_id'])[1]) for i in range(3, 9)]
    content = vision.attachment_images(many)
    assert count(content) == 4 and '2 more attached picture(s) not shown' in labels(content)
    assert vision.attachment_images([{'file_id': 'f' * 32, 'name': 'gone.png', 'extension': '.png'}]) == [
        {'type': 'text', 'text': 'The user attached gone.png, but it could not be shown to you. Do not claim to have seen it.'}]
