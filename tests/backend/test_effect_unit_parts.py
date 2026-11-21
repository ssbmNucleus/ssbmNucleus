"""A move is ONE extra whose mod carries nested parts (core.extra_types.UNIT_PARTS).

Covers: the registry, folding pre-unit standalone part mods into unit mods
on list, applying/restoring parts through the guarded per-format writers,
and the website import grouping a DAT's differing sub-types under the move.
"""
import io
import zipfile

from flask import Flask
import pytest

from core.extra_types import UNIT_PARTS
from core.extra_lookup import part_owner, get_unit_parts, get_extra_type
import vault.importing.unified.detected_effects as detected_effects
import vault.importing.unified.menu_import as menu_import
import vault.routes.extras.colors as colors
import vault.extras.unit_parts as unit_parts
from vault.routes.extras import extras_bp
import vault.routes.import_unified.routes as routes
import vault.importing.unified.archive as unified_archive
import vault.importing.unified.effects as effects
import vault.importing.unified.effect_detect as effect_detect
import vault.importing.unified.detection as detection
from vault.routes.import_unified import import_bp


def test_registry_marks_every_part_and_scopes_them_per_character():
    for primary, parts in UNIT_PARTS.items():
        for part in parts:
            assert part_owner(part) == primary
    assert part_owner('upb') is None
    assert [p for p, _ in get_unit_parts('Fox', 'upb')] == ['upb_charge_fire', 'charge_flames']
    assert [p for p, _ in get_unit_parts('Falco', 'upb')] == ['upb_charge_fire']   # charge flames are Fox-only
    assert [p for p, _ in get_unit_parts('Mario', 'mario_fireball')] == ['mario_fireball_aura']
    for primary, parts in UNIT_PARTS.items():
        for part in parts:
            owner = next(c for c in ('Fox', 'Mario', 'Luigi', 'Bowser', 'Samus') if get_extra_type(c, part))
            assert get_extra_type(owner, part)['part_of'] == primary


def test_list_folds_standalone_part_mods_into_the_unit(vault):
    vault.write({'characters': {'Fox': {'skins': [], 'extras': {
        'charge_flames': [{'id': 'charge_flames_ab12', 'name': 'Blue Charge', 'active': True,
                           'modifications': {'flame_c1': {'color': '0000FF'}}}],
        'upb': [{'id': 'upb_1', 'name': 'Red Fire', 'modifications': {'tip': {'color': 'F800'}}}],
    }}}})
    client = vault.client(colors, 'extras_bp')
    body = client.get('/api/mex/storage/extras/list/Fox').get_json()
    assert 'charge_flames' not in body['extras']
    names = {m['name']: m for m in body['extras']['upb']}
    assert set(names) == {'Red Fire', 'Blue Charge'}
    folded = names['Blue Charge']
    assert folded['modifications'] == {'parts': {'charge_flames': {'flame_c1': {'color': '0000FF'}}}}
    assert folded['migrated_from'] == 'charge_flames' and folded['active'] is True
    # persisted, so the next list is free
    stored = vault.read()['characters']['Fox']['extras']
    assert 'charge_flames' not in stored and len(stored['upb']) == 2


def test_apply_parts_dispatches_each_part_to_its_own_file(monkeypatch, tmp_path):
    files = {}
    for name in ('EfFxData.dat', 'EfCoData.dat'):
        p = tmp_path / name
        p.write_bytes(b'x' * 32)
        files[name] = p
    monkeypatch.setattr(unit_parts, 'find_dat_file', lambda files_dir, target: files.get(target))
    calls = []
    monkeypatch.setattr(unit_parts, 'apply_texture_recolor',
                        lambda path, cfg, color, vanilla_hue=None: calls.append(('texture', cfg['_target_file'], color)))
    monkeypatch.setattr(unit_parts, 'get_dynamic_offsets', lambda path, tid, fallback: fallback)
    monkeypatch.setattr(unit_parts, 'make_write_safety', lambda *a, **k: {'skipped': []})
    monkeypatch.setattr(unit_parts, 'apply_hex_patches',
                        lambda path, offsets, mods, safety=None: calls.append(('hex', sorted(mods))) or [])

    result = unit_parts.apply_parts('Fox', {'tip': {'color': 'F800'}, 'parts': {
        'upb_charge_fire': {'color1': {'color': '00FF00'}},
        'charge_flames': {'flame_c1': {'color': '0000FF'}, 'wisp_c1': {'color': '0000AA'}},
    }}, tmp_path)
    assert result['applied'] == ['upb_charge_fire', 'charge_flames']
    assert result['errors'] == [] and result['skipped'] == []
    assert calls == [('texture', 'EfFxData.dat', '00FF00'), ('hex', ['flame_c1', 'wisp_c1'])]
    # the target files were swapped in atomically (no .patching leftovers)
    assert not list(tmp_path.glob('*.patching'))


def test_apply_parts_reports_a_missing_target_without_aborting_the_rest(monkeypatch, tmp_path):
    fx = tmp_path / 'EfFxData.dat'
    fx.write_bytes(b'x' * 32)
    monkeypatch.setattr(unit_parts, 'find_dat_file',
                        lambda files_dir, target: fx if target == 'EfFxData.dat' else None)
    monkeypatch.setattr(unit_parts, 'apply_texture_recolor', lambda *a, **k: None)
    result = unit_parts.apply_parts('Fox', {'parts': {
        'charge_flames': {'flame_c1': {'color': '0000FF'}},
        'upb_charge_fire': {'color1': {'color': '00FF00'}},
    }}, tmp_path)
    assert result['applied'] == ['upb_charge_fire']
    assert result['skipped'] == ['charge_flames: EfCoData.dat not in project']


def test_restore_parts_restores_every_part_of_the_unit(monkeypatch, tmp_path):
    for name in ('EfFxData.dat', 'EfCoData.dat'):
        (tmp_path / name).write_bytes(b'x')
    monkeypatch.setattr(unit_parts, 'find_dat_file', lambda files_dir, target: tmp_path / target)
    restored = []
    monkeypatch.setattr(unit_parts, 'restore_texture_recolor', lambda path, cfg: restored.append(cfg['_target_file']))
    monkeypatch.setattr(unit_parts, 'restore_extra_color_bytes',
                        lambda path, cfg, report=None: restored.append(cfg['id']) or [])
    report = {'restored_spans': 0, 'failed_spans': [], 'restored_components': []}
    unit_parts.restore_parts('Fox', 'upb', tmp_path, report)
    assert report['restored_components'] == ['upb_charge_fire', 'charge_flames']
    assert restored == ['EfFxData.dat', 'charge_flames']
    assert report['failed_spans'] == []


# ── website import: parts fold under the move ────────────────────────────────

def _client():
    app = Flask(__name__)
    app.register_blueprint(import_bp)
    return app.test_client()


def _post(client, files, **form):
    data = {'file': [(io.BytesIO(payload), name) for name, payload in files]}
    data.update(form)
    return client.post('/api/mex/import/file', data=data, content_type='multipart/form-data')


def _quiet(monkeypatch):
    monkeypatch.setattr(unified_archive, 'detect_character_from_zip', lambda _p: [])
    monkeypatch.setattr(unified_archive, 'detect_stage_from_zip', lambda _p: [])
    monkeypatch.setattr(unified_archive, 'import_vanilla_stage_dats', lambda *_a, **_k: [])
    monkeypatch.setattr(unified_archive, 'looks_like_pause_zip', lambda _p: False)
    monkeypatch.setattr(menu_import, 'looks_like_pause_zip', lambda _p: False)
    monkeypatch.setattr(unified_archive, 'looks_like_percent_zip', lambda _p: False)
    monkeypatch.setattr(detection, 'detect_character_from_zip', lambda _p: [])
    monkeypatch.setattr(detection, 'detect_stage_from_zip', lambda _p: [])
    monkeypatch.setattr(unified_archive, '_effect_duplicate_response', lambda *_a, **_k: None)
    monkeypatch.setattr(detected_effects, '_effect_duplicate_response', lambda *_a, **_k: None)


def test_import_groups_a_units_parts_under_one_mod(vault, monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setattr(effect_detect, 'candidate_effects', lambda data, basename: [
        {'character': 'Fox', 'extra_type': 'shine', 'name': 'Shine Color', 'differs': True},
        {'character': 'Fox', 'extra_type': 'upb', 'name': 'Up-B Color', 'differs': True},
        {'character': 'Fox', 'extra_type': 'upb_charge_fire', 'name': 'Flight Fire Texture', 'differs': True},
        {'character': 'Fox', 'extra_type': 'laser_ring', 'name': 'Blaster Flash', 'differs': False},
    ])
    imports = []

    def fake_effect_import(zip_path, zip_name, effect_type, custom_title=None):
        imports.append((effect_type, custom_title))
        return {'success': True, 'type': 'effect', 'imported_count': 1, 'character': 'Fox',
                'effect_type': effect_type, 'id': f'{effect_type}_1', 'message': f'{effect_type} ok'}
    monkeypatch.setattr(unified_archive, '_import_effect_mod', fake_effect_import)
    monkeypatch.setattr(detected_effects, '_import_effect_mod', fake_effect_import)
    import vault.extras.derive as extras_derive
    monkeypatch.setattr(extras_derive, 'derive_modifications_from_dat',
                        lambda path, tid, cfg: {'color1': {'color': '00FF00'}})
    attached = []
    monkeypatch.setattr(effects, 'attach_effect_part',
                        lambda char, primary, mod_id, part, mods: attached.append((char, primary, mod_id, part, mods)) or True)

    body = _post(_client(), [('EfFxData.dat', b'x' * 64)]).get_json()
    assert body['success'] is True
    assert body['imported_count'] == 2                     # shine + Up-B, not three
    assert imports == [('shine', 'EfFxData (Shine Color)'), ('upb', 'EfFxData (Up-B Color)')]
    assert attached == [('Fox', 'upb', 'upb_1', 'upb_charge_fire', {'color1': {'color': '00FF00'}})]
    assert 'with Flight Fire Texture' in body['message']


def test_import_of_parts_only_creates_a_vanilla_primary_carrying_them(vault, monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setattr(effect_detect, 'candidate_effects', lambda data, basename: [
        {'character': 'Fox', 'extra_type': 'charge_flames', 'name': 'Charge Flames', 'differs': True},
    ])
    monkeypatch.setattr(unified_archive, '_import_effect_mod',
                        lambda *_a, **_k: pytest.fail('the primary must not be imported from a parts-only file'))
    monkeypatch.setattr(detected_effects, '_import_effect_mod',
                        lambda *_a, **_k: pytest.fail('the primary must not be imported from a parts-only file'))
    import vault.extras.derive as extras_derive
    monkeypatch.setattr(extras_derive, 'derive_modifications_from_dat',
                        lambda path, tid, cfg: {'flame_c1': {'color': '0000FF'}})
    monkeypatch.setattr(effects, 'STORAGE_PATH', vault.storage)

    body = _post(_client(), [('EfCoData original fire.dat', b'x' * 64)]).get_json()
    assert body['success'] is True and body['imported_count'] == 1
    mods = vault.read()['characters']['Fox']['extras']['upb']
    assert len(mods) == 1
    assert mods[0]['modifications'] == {'parts': {'charge_flames': {'flame_c1': {'color': '0000FF'}}}}
    assert mods[0]['name'] == 'EfCoData original fire'
    assert (vault.storage / 'Fox' / 'models' / f"{mods[0]['id']}.dat").exists()
