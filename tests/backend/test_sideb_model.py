"""Static Phantasm model import is bounded, lossless and reversible."""
import io
import os
import struct
import subprocess
import zipfile
from pathlib import Path

import pytest

from core.extra_lookup import get_extra_type
from vault.extras import sideb_model as sm, helpers
from vault.extras.effect_model import EffectDat
from vault.extras.derive import derive_modifications_from_dat
from vault.importing.unified import effects, effect_detect
from vault.routes.extras import colors
from projects.routes import extras
from shared.vanilla_extract import vanilla_refs


def model_dat(vertex=100):
    """An authored static triangle: no proprietary asset needed for fast tests."""
    raw = bytearray(32)
    struct.pack_into('>I', raw, 0, 32)
    d = EffectDat(raw)
    root = d.append(bytes(96))
    articles = d.append(bytes(16))
    article = d.append(bytes(24))
    desc = d.append(bytes(16))
    joint = d.append(bytes(64))
    obj = d.append(bytes(16))
    mat = d.append(bytes(24))
    material = d.append(bytes.fromhex('0099ffffcce6ffffffffffff3e99999a42480000'))
    pobj = d.append(bytes(24))
    attrs = d.append(bytes(72))
    display = d.append(b'\x90\0\x03' + struct.pack('>6H', 0, 0, 1, 1, 2, 2) + bytes(17), 32)
    positions = d.append(struct.pack('>9h', 0, 0, 0, vertex, 0, 0, 0, vertex, 0), 32)
    normals = d.append(bytes([0, 0, 127] * 3), 32)
    d.align_to(4)
    struct.pack_into('>I', d.data, joint + 4, 0x20080088)
    struct.pack_into('>3f', d.data, joint + 32, 1, 1, 1)
    struct.pack_into('>I', d.data, mat + 4, 0x60000004)
    struct.pack_into('>HH', d.data, pobj + 12, 0x8000, 1)
    struct.pack_into('>4IBBHI', d.data, attrs, 9, 3, 1, 3, 11, 0, 6, 0)
    struct.pack_into('>4IBBHI', d.data, attrs + 24, 10, 3, 0, 1, 6, 0, 3, 0)
    struct.pack_into('>I', d.data, attrs + 48, 255)
    for source, target in [(root + 0x48, articles), (articles + 12, article),
                           (article + 16, desc), (desc, joint), (joint + 16, obj),
                           (obj + 8, mat), (obj + 12, pobj), (mat + 12, material),
                           (pobj + 8, attrs), (pobj + 16, display),
                           (attrs + 20, positions), (attrs + 44, normals)]:
        d.set_ptr(source, target)
    d.roots = [(root, 0)]
    d.strings = b'ftDataFalco\0'
    out = bytearray(d.to_bytes())
    out[20:24] = b'001B'
    return bytes(out)


def test_transplant_changes_only_model_pointer_and_append():
    target, donor = model_dat(), model_dat(200)
    before = sm.read_model(target)
    output = sm.install(target, donor)
    after = sm.read_model(output)
    assert after.signature() == sm.read_model(donor).signature()
    preserved = bytearray(after.dat.data[:len(before.dat.data)])
    preserved[before.model_slot:before.model_slot + 4] = before.dat.data[before.model_slot:before.model_slot + 4]
    assert preserved == before.dat.data
    assert output[20:32] == target[20:32]
    assert sm.install(output, donor) == output
    assert sm.install(output, model_dat(300)) == sm.install(target, model_dat(300))
    assert sm.revert(output) == target


def test_revert_keeps_other_edits_made_after_install():
    target = model_dat()
    installed = bytearray(sm.install(target, model_dat(200)))
    installed[32:36] = b'kept'  # an unrelated fighter attribute
    expected = bytearray(target)
    expected[32:36] = b'kept'
    assert sm.revert(installed) == expected


@pytest.mark.parametrize('fault', ['root', 'relocation', 'joint', 'skin', 'display', 'stride', 'index'])
def test_malformed_or_unsupported_models_fail_without_mutation(tmp_path, fault):
    raw = model_dat(200)
    model = sm.read_model(raw)
    d = model.dat
    if fault == 'root':
        d.strings = b'ftDataFox\0'
    elif fault == 'relocation':
        d.set_ptr(model.model_slot, len(d.data) + 32)
    elif fault == 'joint':
        d.set_ptr(model.joint + 8, model.joint)
    elif fault == 'skin':
        struct.pack_into('>H', d.data, model.pobj + 12, 0x2000)
    elif fault == 'display':
        d.data[d.ptr(model.pobj + 16)] = 0x61
    elif fault == 'stride':
        struct.pack_into('>H', d.data, d.ptr(model.pobj + 8) + 18, 1)
    else:
        struct.pack_into('>H', d.data, d.ptr(model.pobj + 16) + 3, 65535)
    donor = tmp_path / 'bad.dat'
    donor.write_bytes(d.to_bytes())
    target = tmp_path / 'target.dat'
    original = model_dat()
    target.write_bytes(original)
    with pytest.raises(sm.SideBModelError):
        sm.install_mod(target, tmp_path, {'model_file': 'bad.dat'})
    assert target.read_bytes() == original


def test_revert_refuses_to_discard_later_appends():
    installed = sm.read_model(sm.install(model_dat(), model_dat(200))).dat
    installed.append(b'other data')
    with pytest.raises(sm.SideBModelError, match='changed after'):
        sm.revert(installed.to_bytes())


def test_stored_source_cannot_escape_storage(tmp_path):
    target = tmp_path / 'target.dat'
    target.write_bytes(model_dat())
    with pytest.raises(sm.SideBModelError, match='path'):
        sm.install_mod(target, tmp_path / 'storage', {'model_file': '../target.dat'})


@pytest.fixture
def api(vault, monkeypatch):
    original = model_dat()
    monkeypatch.setattr(sm, 'COLOR_MODEL_SIGNATURE', sm.read_model(original).color_layout_signature())
    reference = vault.touch('test-base', 'files', 'PlFc.dat', data=original)
    target = vault.touch('project', 'files', 'PlFc.dat', data=original)
    monkeypatch.setattr(helpers, 'STORAGE_PATH', vault.storage)
    monkeypatch.setattr(effects, 'STORAGE_PATH', vault.storage)
    monkeypatch.setattr(helpers, 'get_project_files_dir', lambda: target.parent)
    monkeypatch.setattr(vanilla_refs, 'ensure_vanilla_ref', lambda name, **kw: reference)
    # The authored fixture's material is compact; point the restore color
    # contract at its actual operands instead of the retail DAT's offsets.
    config = dict(get_extra_type('Falco', 'sideb'))
    material = sm.read_model(original).material + 32
    config['offsets'] = {key: {'start': material + index * 4, 'size': 4, 'format': 'RGBA'}
                         for index, key in enumerate(('primary', 'secondary', 'tertiary'))}
    monkeypatch.setattr(extras, 'get_extra_type', lambda *args: config)
    vault.write({'characters': {}})
    return vault.client(colors, 'extras_bp'), target, original


def upload(client, raw=None):
    response = client.post('/api/mex/storage/extras/import', data={
        'file': (io.BytesIO(raw or model_dat(200)), 'PlFc-spooky.dat'),
        'character': 'Falco', 'extraType': 'sideb', 'name': 'Spooky'})
    assert response.status_code == 200, response.get_json()
    return response.get_json()['mod']


def test_import_install_current_restore_and_rename(api):
    client, target, original = api
    mod = upload(client)
    assert mod['format'] == 'sideb_model'
    body = {'character': 'Falco', 'extraType': 'sideb', 'modId': mod['id']}
    for _ in range(2):
        response = client.post('/api/mex/storage/extras/install', json=body)
        assert response.status_code == 200, response.get_json()
        assert sm.read_model(target.read_bytes()).signature() == sm.read_model(model_dat(200)).signature()
    current = client.get('/api/mex/storage/extras/current/Falco/sideb').get_json()
    assert current['sidebModel'] == mod['modifications']['sideb_model']
    assert current['status'] == 'custom' and current['colors'] == {}
    response = client.post('/api/mex/storage/extras/create', json=dict(body, name='Renamed', modifications=mod['modifications']))
    assert response.status_code == 200
    response = client.post('/api/mex/storage/extras/create', json=dict(body, name='Oops', modifications={'primary': {'color': 'FF0000FF'}}))
    assert response.status_code == 400
    result = client.post('/api/mex/storage/extras/restore-vanilla', json=body)
    assert result.status_code == 200, result.get_json()
    assert target.read_bytes() == original


def test_color_selection_replaces_model_and_retains_color_only_import(api, vault):
    client, target, original = api
    mod = upload(client)
    client.post('/api/mex/storage/extras/install', json={'character': 'Falco', 'extraType': 'sideb', 'modId': mod['id']})
    color_raw = bytearray(original)
    material = sm.read_model(original).material + 32
    color_raw[material:material + 4] = bytes.fromhex('123456FF')
    color = upload(client, color_raw)
    assert color['modifications']['primary']['color'] == '123456FF'
    assert not sm.is_model_mod(color)
    response = client.post('/api/mex/storage/extras/install', json={'character': 'Falco', 'extraType': 'sideb', 'modId': color['id']})
    assert response.status_code == 200, response.get_json()
    assert target.read_bytes() == color_raw


def test_automatic_detection_works_without_reference(monkeypatch):
    monkeypatch.setattr(effect_detect, '_vanilla_ref', lambda _: None)
    candidates = effect_detect.candidate_effects(model_dat(200), 'PlFc-spooky.dat')
    assert any(c['character'] == 'Falco' and c['extra_type'] == 'sideb' and c['differs'] for c in candidates)


@pytest.mark.parametrize('website_tag', [False, True])
def test_full_archive_import_and_duplicate_skip(api, vault, tmp_path, website_tag):
    from vault.importing.unified.archive import _import_single_archive
    path = tmp_path / 'spooky.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('PlFc-spooky.dat', model_dat(200))
    hints = {'mod_type': 'effect', 'effect_type': 'Side-B Color'} if website_tag else {}
    payload, status = _import_single_archive(str(path), 'Falco_Spooky.zip', **hints)
    assert status == 200 and payload['success'], payload
    mods = vault.read()['characters']['Falco']['extras']['sideb']
    assert len(mods) == 1 and sm.is_model_mod(mods[0])
    payload, status = _import_single_archive(str(path), 'Falco_Spooky.zip', duplicate_action='skip', **hints)
    assert status == 200 and payload['skipped_count'] == 1, payload
    assert len(vault.read()['characters']['Falco']['extras']['sideb']) == 1


def test_missing_restore_reference_is_atomic(tmp_path, monkeypatch):
    target = tmp_path / 'whole-file-custom.dat'
    custom = model_dat(200)
    target.write_bytes(custom)
    monkeypatch.setattr(vanilla_refs, 'ensure_vanilla_ref', lambda _: None)
    with pytest.raises(sm.SideBModelError, match='reference'):
        sm.apply_colors(target, {'primary': {'color': '123456FF'}})
    assert target.read_bytes() == custom


def test_manual_wrong_character_import_is_rejected_without_saved_files(api, vault):
    client, _, _ = api
    raw = model_dat().replace(b'ftDataFalco', b'ftDataFoxxx')
    response = client.post('/api/mex/storage/extras/import', data={
        'file': (io.BytesIO(raw), 'PlFc.dat'), 'character': 'Falco', 'extraType': 'sideb'})
    assert response.status_code == 400
    assert vault.read() == {'characters': {}}


@pytest.mark.slow
@pytest.mark.parametrize('filename', [
    'PlFc-PHANTOM-PHANTASM-BLUE.dat', 'PlFc-PHANTOM-PHANTASM-GREEN.dat',
    'PlFc-ANIMELEE-SPOOKY-PHANTASM-BLUE.dat', 'PlFc-ANIMELEE-SPOOKY-PHANTASM-GREEN.dat'])
def test_published_spooky_variants(tmp_path, filename):
    assets = Path(os.environ.get('NUCLEUS_SPOOKY_ASSET_DIR', 'missing-spooky-assets'))
    reference = Path(os.environ.get('NUCLEUS_SPOOKY_VANILLA_DAT', 'missing-vanilla-dat'))
    if not (assets / filename).is_file() or not reference.is_file():
        pytest.skip('Set NUCLEUS_SPOOKY_ASSET_DIR and NUCLEUS_SPOOKY_VANILLA_DAT to lawful local fixtures')
    source = assets / filename
    raw = source.read_bytes()
    config = get_extra_type('Falco', 'sideb')
    assert derive_modifications_from_dat(source, 'sideb', config) == sm.recipe(raw)
    original = bytearray(reference.read_bytes())
    original[32:36] = b'kept'  # deliberately customized target outside the afterimage
    installed = sm.install(original, raw)
    before, after = sm.read_model(original), sm.read_model(installed)
    preserved = bytearray(after.dat.data[:len(before.dat.data)])
    preserved[before.model_slot:before.model_slot + 4] = before.dat.data[before.model_slot:before.model_slot + 4]
    assert preserved == before.dat.data
    assert sm.read_model(installed).signature() == sm.read_model(raw).signature()
    assert sm.install(installed, raw) == installed
    assert sm.revert(installed) == original


@pytest.mark.slow
def test_native_save_reopen_color_switch_and_reinstall(tmp_path, monkeypatch):
    from core.config import MEXCLI_PATH, get_subprocess_args
    assets = Path(os.environ.get('NUCLEUS_SPOOKY_ASSET_DIR', 'missing-spooky-assets'))
    reference = Path(os.environ.get('NUCLEUS_SPOOKY_VANILLA_DAT', 'missing-vanilla-dat'))
    source = assets / 'PlFc-PHANTOM-PHANTASM-BLUE.dat'
    if not source.is_file() or not reference.is_file() or not MEXCLI_PATH.is_file():
        pytest.skip('Requires pinned MexCLI and local Spooky/vanilla fixtures')
    monkeypatch.setattr(vanilla_refs, 'ensure_vanilla_ref', lambda name: reference)
    original = reference.read_bytes()
    assert not sm.replacement_recipe(original)
    installed = tmp_path / 'installed.dat'
    installed.write_bytes(sm.install(original, source.read_bytes()))
    empty = bytearray(32)
    struct.pack_into('>I', empty, 0, 32)
    (tmp_path / 'empty.dat').write_bytes(empty)
    rebuilt = tmp_path / 'rebuilt.dat'
    result = subprocess.run([str(MEXCLI_PATH), 'copy-root', str(installed), 'ftDataFalco',
                             str(tmp_path / 'empty.dat'), str(rebuilt)],
                            capture_output=True, text=True, timeout=60, **get_subprocess_args())
    assert result.returncode == 0, result.stderr
    reopened = rebuilt.read_bytes()
    assert sm.read_model(reopened).signature() == sm.read_model(source.read_bytes()).signature()
    assert sm.install(reopened, source.read_bytes()) == reopened
    # Native relocation may leave old, unreachable vanilla color markers.
    # Applying colors must follow the live article model, not those markers.
    sm.apply_colors(rebuilt, {'primary': {'color': '123456FF'}})
    assert sm.colors(rebuilt.read_bytes())['primary'] == '123456FF'
    after = rebuilt.read_bytes()
    sm.apply_colors(rebuilt, {'primary': {'color': '123456FF'}})
    assert rebuilt.read_bytes() == after
    sm.apply_colors(rebuilt, {key: {'color': value} for key, value in sm.colors(original).items()})
    assert sm.colors(rebuilt.read_bytes()) == sm.colors(original)
    rebuilt.write_bytes(sm.install(rebuilt.read_bytes(), source.read_bytes()))
    assert sm.read_model(rebuilt.read_bytes()).signature() == sm.read_model(source.read_bytes()).signature()
