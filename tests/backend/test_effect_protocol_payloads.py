from tests.paths import APP
import io
import zipfile

import pytest
from PIL import Image

from vault.importing.unified import effects
from vault.routes.import_unified import routes, import_bp
import vault.importing.unified.archive as unified_archive
from vault.extras import helpers, effect_model
from core.extra_lookup import get_extra_type


def archive(tmp_path, files):
    path = tmp_path / 'effect.zip'
    with zipfile.ZipFile(path, 'w') as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return path


def png():
    output = io.BytesIO()
    Image.new('RGBA', (16, 16), (0, 255, 100, 128)).save(output, 'PNG')
    return output.getvalue()


def test_image_protocol_import_and_duplicate_skip(vault, monkeypatch, tmp_path):
    monkeypatch.setattr(helpers, 'STORAGE_PATH', vault.storage)
    monkeypatch.setattr(effects, 'STORAGE_PATH', vault.storage)
    path = archive(tmp_path, {'nested/shine.png': png(), 'preview.png': b'not the payload'})
    first, status = unified_archive._import_single_archive(path, 'Falco_Default.zip',
        mod_type='effect', effect_type='Shine Color', custom_title='My shine')
    assert status == 200 and first['imported_count'] == 1
    cfg = get_extra_type('Falco', 'shine')
    mod = vault.read()['characters'][first['character']]['extras']['shine'][0]
    assert mod['name'] == 'My shine' and mod['format'] == 'effect_model'
    assert (vault.storage / first['character'] / mod['image_file']).exists()
    assert effect_model.png_from_mod(vault.storage / first['character'], mod, cfg).startswith(b'\x89PNG')
    second, status = unified_archive._import_single_archive(path, 'Falco_Default.zip',
        mod_type='effect', effect_type='Shine Color', duplicate_action='skip')
    assert status == 200 and second['skipped_count'] == 1
    assert len(vault.read()['characters'][first['character']]['extras']['shine']) == 1


def test_duplicate_uses_selected_dat_and_normalized_type(tmp_path):
    path = archive(tmp_path, {'PlFx.dat': b'fighter', 'EfFxData custom.dat': b'effect'})
    with zipfile.ZipFile(path) as zf:
        character, key, _, member, digest = effects.select_effect_payload(zf, 'Fox_Default.zip', 'Shine Color')
    assert (character, key, member) == ('Fox', 'shine', 'EfFxData custom.dat')
    assert digest == effects.compute_dat_hash(b'effect')


@pytest.mark.parametrize('files,type_id', [
    ({'one.png': b'a', 'two.png': b'b'}, 'shine'),
    ({'shine.png': b'a'}, 'laser'),
    ({'preview.png': b'a'}, 'shine'),
    ({'PlFx.dat': b'a', 'PlFc.dat': b'b'}, 'shine'),
])
def test_ambiguous_or_unsupported_payload_rejected(tmp_path, files, type_id):
    with zipfile.ZipFile(archive(tmp_path, files)) as zf:
        with pytest.raises(ValueError):
            effects.select_effect_payload(zf, 'Fox_Default.zip', type_id)


def test_wrong_bank_shine_never_creates_vault_entry(vault, monkeypatch, tmp_path):
    monkeypatch.setattr(effects, 'STORAGE_PATH', vault.storage)
    result = effects._import_effect_mod(archive(tmp_path, {'EfFxData.dat': b'bad DAT'}),
                                        'Fox_Default.zip', 'shine')
    assert not result['success']
    assert not list(vault.storage.rglob('*.dat'))


def test_local_gradient_dat_import_uses_shared_pipeline(vault, monkeypatch):
    from vault.routes.extras import extras_bp
    from flask import Flask
    from pathlib import Path
    source = APP / 'storage/test-base/files/EfFxData.dat'
    if not source.exists():
        pytest.skip('vanilla effect fixture unavailable')
    monkeypatch.setattr(effects, 'STORAGE_PATH', vault.storage)
    monkeypatch.setattr(helpers, 'STORAGE_PATH', vault.storage)
    app = Flask(__name__)
    app.register_blueprint(extras_bp)
    response = app.test_client().post('/api/mex/storage/extras/import', data={
        'file': (io.BytesIO(source.read_bytes()), 'EfFxData.dat'),
        'character': 'Fox', 'extraType': 'shine', 'name': 'Gradient',
    })
    assert response.status_code == 200, response.get_json()
    assert 'primary' in response.get_json()['mod']['modifications']
