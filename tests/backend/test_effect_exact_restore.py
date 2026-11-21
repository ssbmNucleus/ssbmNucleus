"""Grouped effects restore original per-record variation instead of flattening it."""
from tests.paths import APP
from pathlib import Path
import struct

import pytest

from projects.routes import extras as project_extras
from vault.extras import helpers, effect_model
from vault.extras import color_patch
from core.extra_lookup import get_extra_type
from shared.vanilla_extract import vanilla_refs


CASES = [('C. Falcon', 'falcon_punch'), ('C. Falcon', 'falcon_kick'),
         ('C. Falcon', 'raptor_boost'), ('Fox', 'upb'), ('Fox', 'shine'),
         ('Samus', 'missile'), ('Luigi', 'luigi_fireball_smoke'),
         ('Zelda', 'zelda_farore'), ('Zelda', 'zelda_transform'),
         ('Kirby', 'kirby_stone'), ('Kirby', 'kirby_copy_luigi')]


def _fixture(vault, monkeypatch, character, extra):
    cfg = get_extra_type(character, extra)
    source = APP / 'storage/test-base/files' / cfg['target_file']
    if not source.exists():
        source = APP.parents[1] / '.tmp/effects-roster-static-20260909/vault/test-base/files' / cfg['target_file']
    if not source.exists():
        pytest.skip(f"Vanilla {cfg['target_file']} unavailable")
    raw = source.read_bytes()
    vault.touch('test-base', 'files', cfg['target_file'], data=raw)
    target = vault.path('project/files', cfg['target_file'])
    target.write_bytes(raw)
    monkeypatch.setattr(helpers, 'STORAGE_PATH', vault.storage)
    monkeypatch.setattr(helpers, 'get_project_files_dir', lambda: target.parent)
    monkeypatch.setattr(vanilla_refs, 'ensure_vanilla_ref', lambda name, **kwargs: source)
    monkeypatch.setattr(project_extras, 'restore_texture_extra', lambda *args: None)
    return cfg, raw, target


def _paint(cfg, target):
    if cfg.get('format') == 'shine_gradient':
        helpers.patch_shine_color_slots(target, cfg,
            {key: {'color': 'FC00'} for key in ('primary', 'secondary', 'flash1', 'flash2')})
        color_patch.patch_shine_sparkle_color(target, cfg['offsets']['sparkles'], 'AA33CC')
    else:
        mods = {key: {'color': 'AA' * (len(value) // 2)} for key, value in cfg['vanilla'].items()
                if key in cfg['offsets']}
        color_patch.apply_hex_patches(target, cfg['offsets'], mods)


@pytest.mark.parametrize('character,extra', CASES)
def test_restore_route_is_byte_exact_for_previously_residual_effects(vault, monkeypatch, character, extra):
    cfg, raw, target = _fixture(vault, monkeypatch, character, extra)
    _paint(cfg, target)
    assert target.read_bytes() != raw
    client = vault.client(project_extras, 'extras_bp')
    response = client.post('/api/mex/storage/extras/restore-vanilla',
                           json={'character': character, 'extraType': extra})
    assert response.status_code == 200, response.get_json()
    assert target.read_bytes() == raw


def test_restoring_punch_preserves_raptor_material(vault, monkeypatch):
    cfg, raw, target = _fixture(vault, monkeypatch, 'C. Falcon', 'falcon_punch')
    _paint(cfg, target)
    sibling = get_extra_type('C. Falcon', 'raptor_boost')['offsets']['hit_mat_c1']['offsets'][0]
    modified = bytearray(target.read_bytes())
    modified[sibling:sibling + 3] = bytes.fromhex('123456')
    target.write_bytes(modified)
    assert helpers.restore_extra_color_bytes(target, cfg) == []
    expected = bytearray(raw)
    expected[sibling:sibling + 3] = bytes.fromhex('123456')
    assert target.read_bytes() == expected


def _relocate(raw):
    archive = effect_model.EffectDat(raw)
    data = bytes(archive.data)
    relocs = archive.relocs.copy()
    archive.data = bytearray(32) + archive.data
    for offset in relocs:
        pointer, = struct.unpack_from('>I', data, offset)
        struct.pack_into('>I', archive.data, offset + 32, pointer + 32)
    archive.relocs = {offset + 32 for offset in relocs}
    archive.roots = [(offset + 32, name) for offset, name in archive.roots]
    archive.refs = [(offset + 32, name) for offset, name in archive.refs]
    archive.data_size = len(archive.data)
    return archive.to_bytes()


@pytest.mark.parametrize('character,extra', [('Samus', 'missile'), ('Zelda', 'zelda_farore')])
def test_particle_restoration_retains_each_relocated_primary_and_secondary(vault, monkeypatch, character, extra):
    cfg, raw, target = _fixture(vault, monkeypatch, character, extra)
    _paint(cfg, target)
    target.write_bytes(_relocate(target.read_bytes()))
    assert helpers.restore_extra_color_bytes(target, cfg) == []
    assert target.read_bytes() == _relocate(raw)


def test_unidentified_restore_location_is_skipped_without_mutation(vault, monkeypatch):
    cfg, _, target = _fixture(vault, monkeypatch, 'Samus', 'missile')
    invalid = bytes(1024)
    target.write_bytes(invalid)
    assert helpers.restore_extra_color_bytes(target, cfg)
    assert target.read_bytes() == invalid


def test_restore_route_reports_rejected_spans_without_claiming_success(vault, monkeypatch):
    _, _, target = _fixture(vault, monkeypatch, 'Samus', 'missile')
    invalid = bytes(1024)
    target.write_bytes(invalid)
    response = vault.client(project_extras, 'extras_bp').post('/api/mex/storage/extras/restore-vanilla',
        json={'character': 'Samus', 'extraType': 'missile'})
    assert response.status_code == 409
    detail = response.get_json()
    assert detail['success'] is False
    assert detail['restored_spans'] == 0
    assert detail['failed_spans']
    assert target.read_bytes() == invalid


def test_partial_restore_reports_committed_spans_and_preserves_unidentified_bytes(vault, monkeypatch):
    cfg = {'id': 'partial', 'target_file': 'Partial.dat', 'vanilla': {'good': '102030', 'bad': '405060'},
           'offsets': {'good': {'start': 64, 'size': 3, 'format': 'RGB'},
                       'bad': {'start': 128, 'size': 3, 'format': 'RGB'}}}
    raw = bytes((index * 37) % 251 for index in range(256))
    vault.touch('test-base', 'files', 'Partial.dat', data=raw)
    modified = bytearray(raw)
    modified[64:67] = bytes.fromhex('AA33CC')
    modified[104:155] = bytes(51)  # destroy the second slot's location proof
    target = vault.touch('project', 'files', 'Partial.dat', data=modified)
    monkeypatch.setattr(helpers, 'STORAGE_PATH', vault.storage)
    monkeypatch.setattr(helpers, 'get_project_files_dir', lambda: target.parent)
    monkeypatch.setattr(project_extras, 'get_extra_type', lambda *args: cfg)
    response = vault.client(project_extras, 'extras_bp').post('/api/mex/storage/extras/restore-vanilla',
        json={'character': 'Test', 'extraType': 'partial'})
    detail = response.get_json()
    assert response.status_code == 409, detail
    assert detail['restored_spans'] == 1
    assert len(detail['failed_spans']) == 1
    assert detail['failed_spans'][0]['layer_id'] == '0x80'
    modified[64:67] = raw[64:67]
    assert target.read_bytes() == modified


def test_nested_texture_failure_reports_colors_already_restored(vault, monkeypatch):
    cfg, raw, target = _fixture(vault, monkeypatch, 'C. Falcon', 'falcon_punch')
    _paint(cfg, target)
    def fail_texture(*args):
        raise RuntimeError('Texture import failed')
    monkeypatch.setattr(project_extras, 'restore_texture_extra', fail_texture)
    response = vault.client(project_extras, 'extras_bp').post('/api/mex/storage/extras/restore-vanilla',
        json={'character': 'C. Falcon', 'extraType': 'falcon_punch'})
    detail = response.get_json()
    assert response.status_code == 409
    assert detail['restored_spans'] > 0
    assert detail['failed_spans'] == [{'layer_id': 'punch_texture', 'reason': 'Texture import failed'}]
    assert target.read_bytes() == raw
