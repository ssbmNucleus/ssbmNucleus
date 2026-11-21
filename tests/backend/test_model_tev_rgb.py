"""Independent TEV RGB edits prove their model owner instead of using ptcl IDs."""
from tests.paths import APP
from copy import deepcopy
from pathlib import Path
import struct

import pytest

from vault.extras import helpers
from vault.extras import color_patch
from vault.routes.extras import colors
from core.extra_lookup import get_extra_type
from tests.backend.test_effect_exact_restore import _relocate


ANCHOR = 0x114C4


@pytest.fixture
def model(vault, monkeypatch):
    source = APP / 'storage/test-base/files/EfSsData.dat'
    if not source.exists():
        source = APP.parents[1] / '.tmp/effects-roster-static-20260909/vault/test-base/files/EfSsData.dat'
    if not source.exists():
        pytest.skip('Vanilla Samus DAT unavailable')
    raw = source.read_bytes()
    reference = vault.touch('test-base', 'files', 'EfSsData.dat', data=raw)
    target = vault.touch('project', 'files', 'EfSsData.dat', data=raw)
    monkeypatch.setattr(helpers, 'STORAGE_PATH', vault.storage)
    config = {'id': 'warm_proposal', 'target_file': 'EfSsData.dat',
              'offsets': {key: {'start': ANCHOR + delta, 'size': 3, 'format': 'RGB',
                                'model_tev_anchor': ANCHOR}
                          for key, delta in [('warm_c1', 4), ('warm_c2', 8)]},
              'vanilla': {'warm_c1': 'FFFF8A', 'warm_c2': 'FF4C00'}}
    return config, raw, reference, target


def _apply(config, reference, target, first, second):
    safety = {'dat_path': str(target), 'vanilla_path': str(reference),
              'extra_id': config['id'], 'vanilla_map': config['vanilla'], 'skipped': []}
    return color_patch.apply_hex_patches(target, config['offsets'],
        {'warm_c1': {'color': first}, 'warm_c2': {'color': second}}, safety=safety)


@pytest.mark.parametrize('array_offsets', [False, True])
def test_real_model_relocation_reapply_split_and_exact_restore_preserve_alpha_and_siblings(model, array_offsets):
    config, raw, reference, target = model
    if array_offsets:
        for info in config['offsets'].values():
            info['offsets'] = [info.pop('start')]
            info.pop('size')
    assert _apply(config, reference, target, '00FF00', '00FF00') == []
    current = bytearray(target.read_bytes())
    current[ANCHOR + 7] = 0x40
    current[ANCHOR + 11] = 0x91
    current[0x11588:0x1158B] = bytes.fromhex('123456')
    target.write_bytes(_relocate(current))
    assert _apply(config, reference, target, 'AA33CC', '3355FF') == []
    changed = target.read_bytes()
    assert changed[ANCHOR + 36:ANCHOR + 40] == bytes.fromhex('AA33CC40')
    assert changed[ANCHOR + 40:ANCHOR + 44] == bytes.fromhex('3355FF91')
    assert _apply(config, reference, target, 'AA33CC', '3355FF') == []
    assert target.read_bytes() == changed
    report = {}
    assert helpers.restore_extra_color_bytes(target, config, report=report) == []
    assert report == {'restored_spans': 2}
    expected = bytearray(raw)
    expected[ANCHOR + 7] = 0x40
    expected[ANCHOR + 11] = 0x91
    expected[0x11588:0x1158B] = bytes.fromhex('123456')
    assert target.read_bytes() == _relocate(expected)


@pytest.mark.parametrize('failure', ['missing_marker', 'ambiguous_owner', 'missing_reference'])
def test_model_guard_rejects_missing_or_ambiguous_identity_without_writing(model, failure):
    config, raw, reference, target = model
    modified = bytearray(raw)
    if failure == 'missing_marker':
        modified[ANCHOR] = 0x06
    elif failure == 'ambiguous_owner':
        # Give an existing arc texture the warm texture's complete owner
        # signature, retaining its own valid TEV pointer. Both then match.
        modified[0x11598:0x11598 + 0x5C] = modified[0x114D8:0x114D8 + 0x5C]
        struct.pack_into('>I', modified, 0x11598 + 0x58, 0x11578 - 32)
    else:
        reference = reference.with_name('unavailable.dat')
    target.write_bytes(modified)
    skips = _apply(config, reference, target, '00FF00', 'FF00FF')
    assert len(skips) == 2
    assert target.read_bytes() == modified
    if failure != 'missing_reference':
        assert len(helpers.restore_extra_color_bytes(target, config)) == 2
        assert target.read_bytes() == modified


def test_model_guard_does_not_trust_equal_color_at_stale_offset(model):
    config, raw, reference, target = model
    shifted = bytearray(_relocate(raw))
    shifted[ANCHOR + 4:ANCHOR + 7] = bytes.fromhex('FFFF8A')
    target.write_bytes(shifted)
    # The stale offset overlaps the relocated owner's ImageDesc, so this
    # also invalidates its structure. Matching vanilla RGB there must not
    # bypass the complete model proof or mutate the unrelated stale bytes.
    assert len(_apply(config, reference, target, '00FF00', 'FF00FF')) == 2
    assert target.read_bytes() == shifted


def test_model_guard_rejects_alpha_or_other_non_rgb_write_shapes(model):
    config, raw, reference, target = model
    config = deepcopy(config)
    config['offsets']['warm_c1']['start'] += 3
    config['offsets']['warm_c2']['size'] = 4
    assert len(_apply(config, reference, target, '00FF00', 'FF00FF')) == 2
    assert target.read_bytes() == raw


def test_explicit_model_guard_cannot_be_bypassed_by_omitting_safety(model):
    config, raw, _, target = model
    with pytest.raises(ValueError, match='write-safety'):
        color_patch.apply_hex_patches(target, config['offsets'], {'warm_c1': {'color': '00FF00'}})
    assert target.read_bytes() == raw


def test_shipped_screw_attack_install_and_restore_reach_both_swirl_channels(model, vault, monkeypatch):
    _, raw, _, target = model
    config = get_extra_type('Samus', 'screw_attack')
    assert set(config['offsets']) == {'arc_c1', 'arc_c2', 'warm_swirl_c1', 'warm_swirl_c2'}
    modifications = {key: {'color': '00FF00' if key.endswith('_c1') else 'FF00FF'}
                     for key in config['offsets']}
    vault.write({'characters': {'Samus': {'extras': {'screw_attack': [
        {'id': 'screw_test', 'name': 'Screw Attack test', 'modifications': modifications}]}}}})
    monkeypatch.setattr(helpers, 'get_project_files_dir', lambda: target.parent)
    client = vault.client(colors, 'extras_bp')
    response = client.post('/api/mex/storage/extras/install',
        json={'character': 'Samus', 'extraType': 'screw_attack', 'modId': 'screw_test'})
    assert response.status_code == 200, response.get_json()
    assert target.read_bytes()[ANCHOR + 4:ANCHOR + 11] == bytes.fromhex('00FF0000FF00FF')
    assert target.read_bytes()[0x11588:0x1158F] == bytes.fromhex('00FF0000FF00FF')
    response = client.post('/api/mex/storage/extras/restore-vanilla',
        json={'character': 'Samus', 'extraType': 'screw_attack'})
    assert response.status_code == 200, response.get_json()
    assert target.read_bytes() == raw
