"""Repeated shine edits retain per-vertex channel identity after colors become equal."""
from tests.paths import APP
from pathlib import Path

import pytest

from vault.extras import helpers
from core.extra_lookup import get_extra_type
from shared.vanilla_extract import vanilla_refs


VANILLA = APP / 'storage/test-base/files/EfFxData.dat'
pytestmark = pytest.mark.skipif(not VANILLA.exists(), reason='vanilla EfFxData.dat unavailable')
CHANNELS = ('primary', 'secondary', 'flash1', 'flash2')


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(vanilla_refs, 'ensure_vanilla_ref', lambda filename: VANILLA)
    path = tmp_path / 'EfFxData.dat'
    original = VANILLA.read_bytes()
    path.write_bytes(original)
    return path, original, get_extra_type('Fox', 'shine')


def _recipe(*colors):
    return {key: {'color': color} for key, color in zip(CHANNELS, colors)}


def _expected(original, config, modifications, shift=0):
    """Independent oracle: replace channel bytes at their original vertex slots."""
    expected = bytearray(b'\0' * shift + original)
    groups = [([config['offsets']['hex']], ('primary', 'secondary')),
              (config['flash_offsets']['ranges'], ('flash1', 'flash2'))]
    for ranges, channels in groups:
        for region in ranges:
            start = region['start']
            count = int.from_bytes(original[start + 1:start + 3], 'big')
            for vertex in range(count):
                offset = start + 4 + 4 * vertex
                vanilla = original[offset:offset + 2].hex().upper()
                for channel in channels:
                    if vanilla == config['vanilla'][channel] and channel in modifications:
                        expected[offset + shift:offset + shift + 2] = bytes.fromhex(modifications[channel]['color'])
    return bytes(expected)


@pytest.mark.parametrize('first', [
    ('FC00', '03FF', '0FF0', 'AB9F'),
    ('FC00', 'FC00', 'FC00', 'FC00'),
])
def test_repeated_edits_split_channels_and_restore_vanilla(fixture, first):
    path, original, config = fixture
    helpers.patch_shine_color_slots(path, config, _recipe(*first))
    assert path.read_bytes() == _expected(original, config, _recipe(*first))
    second = _recipe('FC1F', '03FF', '0FF0', 'FE60')
    helpers.patch_shine_color_slots(path, config, second)
    assert path.read_bytes() == _expected(original, config, second)
    helpers.patch_shine_color_slots(path, config, second)
    assert path.read_bytes() == _expected(original, config, second)
    helpers.patch_shine_color_slots(path, config,
        {key: {'color': config['vanilla'][key]} for key in CHANNELS})
    assert path.read_bytes() == original


def test_relocated_equalized_display_lists_use_structural_identity(fixture):
    path, original, config = fixture
    path.write_bytes(b'\0' * 96 + original)
    helpers.patch_shine_color_slots(path, config, _recipe(*(['FC00'] * 4)))
    second = _recipe('621F', 'AB9F', '63FF', 'FFFF')
    helpers.patch_shine_color_slots(path, config, second)
    assert path.read_bytes() == _expected(original, config, second, shift=96)


@pytest.mark.parametrize('damage', ['ambiguous', 'invalid_layout'])
def test_unsafe_layout_leaves_all_color_groups_unchanged(fixture, damage):
    path, original, config = fixture
    altered = bytearray(original)
    if damage == 'ambiguous':
        start = config['offsets']['hex']['start']
        altered.extend(original[start:start + 3 + 43 * 4])
    else:
        # A flash vertex index changed: RGBY bytes alone are insufficient
        # evidence to write, and the earlier hex group must remain untouched.
        altered[config['flash_offsets']['ranges'][0]['start'] + 3] ^= 1
    path.write_bytes(altered)
    with pytest.raises(ValueError, match='layout matches'):
        helpers.patch_shine_color_slots(path, config, _recipe(*(['FC00'] * 4)))
    assert path.read_bytes() == altered
