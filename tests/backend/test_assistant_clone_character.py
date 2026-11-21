"""A clone is a separate, complete vault package; failures never publish half one."""
import io
import json
import struct
import zipfile

import numpy as np
from PIL import Image
import pytest

from randall.assistant import clone_character as adapter, tools
from shared import mod_files
from vault.routes import custom_characters
import vault.importing.custom_character_zip as cc_zip
from vault.echo import clone, package
from vault.echo import donors as echo_donors
from vault.importing import custom_character_package
from tests.backend.test_echo_ops import build_synthetic_dat


def costume_dat(value=0, root='PlyCaptain5K_Share_joint'):
    body = bytes([value]) * 64
    strings = root.encode() + b'\0'
    return struct.pack('>8I', 32 + len(body) + 8 + len(strings), len(body), 0, 1, 0, 0, 0, 0) + body + struct.pack('>II', 0, 0) + strings


def donor_zip():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        z.writestr('fighter.json', json.dumps(dict(name='C. Falcon', seriesID=0,
            functions={'specialN': 12345}, files={'fighterDataPath': 'PlCa.dat', 'animFile': 'PlCaAJ.dat'},
            costumes=[dict(name='Normal', file={'fileName': 'PlCaNr.dat',
                'jointSymbol': 'PlyCaptain5K_Share_joint'}, icon='old', csp='old')],
            redCostumeIndex=2, blueCostumeIndex=5, greenCostumeIndex=4)))
        z.writestr('PlCa.dat', build_synthetic_dat())
        z.writestr('PlCaAJ.dat', b'original animations')
        z.writestr('sound.zip', b'original sound')
        z.writestr('PlCaNr.zip', b'original costume')
        z.writestr('icon.png', b'original artwork')
    return buffer.getvalue()


@pytest.fixture
def setup_clone(vault, monkeypatch):
    monkeypatch.setattr(custom_characters, 'CUSTOM_CHARACTERS_PATH', vault.storage / 'custom_characters')
    monkeypatch.setattr(cc_zip, 'CUSTOM_CHARACTERS_PATH', vault.storage / 'custom_characters')
    monkeypatch.setattr(custom_character_package, 'CUSTOM_CHARACTERS_PATH', vault.storage / 'custom_characters')
    original = donor_zip()
    monkeypatch.setattr(echo_donors, 'export_donor_zip', lambda donor: original)
    vault.write({'characters': {'C. Falcon': {'skins': [{'id': 'untouched'}]}}, 'custom_characters': []})
    image = clone.png_bytes(Image.new('RGBA', (136, 188), (220, 200, 180, 255)))
    stock = clone.png_bytes(Image.new('RGBA', (24, 24), (220, 200, 180, 255)))
    monkeypatch.setattr(clone, 'render_assets', lambda *a: dict(csp=image, stock=stock, hd=image))
    inputs = [mod_files.register(costume_dat(i), 'PlCaNr.dat',
        origin={'character': 'C. Falcon', 'costume_code': 'PlCaNr'}, edited=True)['file_id'] for i in range(5)]
    args = dict(file_id=inputs[0], recolor_file_ids=inputs[1:], name='Elemental HERO Neos', short_name='Neos')
    return vault, args, original


def test_tool_creates_complete_independent_clone_and_is_idempotent(setup_clone):
    vault, args, donor = setup_clone
    progress = []
    result = tools.execute(tools.prepare('create_clone_character', args), progress=progress.append)
    assert 'error' not in result
    assert result['vault_changed'] and result['gameplay_tested'] is False
    assert result['character']['costume_count'] == 5 and len(progress) == 7
    root = vault.storage / 'custom_characters' / result['character']['slug']
    assert (root / 'donor.zip').read_bytes() == donor
    with zipfile.ZipFile(root / 'fighter.zip') as z, zipfile.ZipFile(io.BytesIO(donor)) as original:
        for name in ['PlCa.dat', 'PlCaAJ.dat', 'sound.zip']:
            assert z.read(name) == original.read(name)
        fighter = json.loads(z.read('fighter.json'))
        assert fighter['functions'] == {'specialN': 12345}
        assert [fighter[k] for k in ['redCostumeIndex', 'blueCostumeIndex', 'greenCostumeIndex']] == [1, 2, 3]
        assert fighter['name'] == args['name']
        for i, (code, name, _) in enumerate(clone.COSTUMES):
            stem = 'PlCa' + code
            with zipfile.ZipFile(io.BytesIO(z.read(stem + '.zip'))) as costume:
                assert costume.read(stem + '.dat') == costume_dat(i)
                for asset in ['csp.png', 'stc.png']:
                    assert Image.open(io.BytesIO(costume.read(asset))).format == 'PNG'
            assert (root / 'costumes' / (stem + '_csp.png')).exists()
            assert (root / 'costumes' / (stem + '_stc.png')).exists()
            assert (root / 'costumes' / (stem + '_csp_hd.png')).exists()
            assert fighter['costumes'][i]['name'] == name
        for asset, size in [('icon.png', (64, 56)), ('big_banner.png', (256, 28)), ('small_banner.png', (120, 24))]:
            assert Image.open(io.BytesIO(z.read(asset))).size == size
    from core.metadata import load_metadata
    before = load_metadata()
    assert before['characters']['C. Falcon']['skins'] == [{'id': 'untouched'}]
    again = adapter.create_clone_character(**args)
    assert not again['vault_changed'] and again['character'] == result['character']
    assert load_metadata() == before


@pytest.mark.parametrize('failure', ['art', 'metadata', 'cancel'])
def test_failure_does_not_publish_partial_character(setup_clone, monkeypatch, failure):
    from core import metadata
    vault, args, _ = setup_clone
    before = metadata.load_metadata()
    def fail(*a, **kw):
        raise ValueError('deliberate failure')
    if failure == 'art':
        monkeypatch.setattr(clone, 'render_assets', fail)
    elif failure == 'metadata':
        monkeypatch.setattr(metadata, 'save_metadata', fail)
    else:
        args['_cancelled'] = lambda: True
    with pytest.raises(ValueError):
        adapter.create_clone_character(**args)
    assert metadata.load_metadata() == before
    assert not list((vault.storage / 'custom_characters').glob('elemental*'))


@pytest.mark.parametrize('bad', ['wrong_root', 'different_donor', 'duplicate', 'missing_file', 'path'])
def test_invalid_inputs_rejected_before_rendering(setup_clone, monkeypatch, bad):
    _, args, _ = setup_clone
    calls = []
    monkeypatch.setattr(clone, 'render_assets', lambda *a: calls.append(a))
    if bad == 'wrong_root':
        args['file_id'] = mod_files.register(costume_dat(9, 'PlyFox5K_Share_joint'), 'model.dat',
            origin={'character': 'C. Falcon', 'costume_code': 'PlCaNr'})['file_id']
    elif bad == 'different_donor':
        args['file_id'] = mod_files.register(costume_dat(9, 'PlyFox5K_Share_joint'), 'model.dat',
            origin={'character': 'Fox', 'costume_code': 'PlFxNr'})['file_id']
    elif bad == 'duplicate':
        args['recolor_file_ids'][0] = args['file_id']
    elif bad == 'missing_file':
        path, _ = mod_files.resolve(args['file_id'])
        path.write_bytes(b'changed')
    else:
        args['file_id'] = '../../somewhere.dat'
    with pytest.raises(ValueError):
        adapter.create_clone_character(**args)
    assert not calls


def test_tints_preserve_alpha_shading_and_neutral_mode_accents():
    pixels = np.array([[[70, 70, 70, 255], [160, 160, 160, 255], [220, 20, 20, 255],
                        [100, 100, 100, 0], [255, 255, 255, 255]]], dtype=np.uint8)
    original = pixels.copy()
    out = clone.tint_texture(pixels, 220, 'neutral')
    assert np.array_equal(pixels, original)
    assert np.array_equal(out[..., 3], pixels[..., 3])
    assert np.array_equal(out[0, 2:4], pixels[0, 2:4])
    assert out[0, 4, 2] > out[0, 4, 0]  # white highlights are tinted too, without speckling
    assert out[0, 0, 2] > out[0, 0, 0] and out[0, 1, 2] > out[0, 0, 2]


def test_empty_artwork_is_an_error():
    with pytest.raises(ValueError, match='empty'):
        clone.checked_image(clone.png_bytes(Image.new('RGBA', (24, 24))))
