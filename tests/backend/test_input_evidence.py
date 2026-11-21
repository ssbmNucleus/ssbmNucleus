import struct

import pytest

from tools.ingame.input_evidence import (
    COMMON_DATA_POINTER,
    PAD_GAME_STATUS,
    PAD_STATUS_SIZE,
    capture_input_evidence,
)
from shared.ingame.pose import CaptureError


FIGHTER = 0x80500000
COMMON = 0x80600000


class Memory:
    def __init__(self):
        self.blocks = {}
        self.truncate = None

    def put(self, address, raw):
        self.blocks[address] = bytes(raw)

    def bytes(self, address, size):
        for start, raw in self.blocks.items():
            offset = address - start
            if 0 <= offset and offset + size <= len(raw):
                result = raw[offset:offset + size]
                if self.truncate == (address, size):
                    return result[:-1]
                return result
        return None


def fixture(*, controller=2):
    d = Memory()
    d.put(FIGHTER + 0x618, bytes([controller, 1, 9, 0]))

    pad = bytearray(PAD_STATUS_SIZE)
    struct.pack_into('>bb', pad, 0x18, 16, -8)
    struct.pack_into('>2f', pad, 0x20, 0.2, -0.1)
    d.put(PAD_GAME_STATUS + controller * PAD_STATUS_SIZE, pad)

    fighter_input = bytearray(0x54)
    # The delivered 0.2 X is below the 0.28 common deadzone and the fighter's
    # filtered current X is therefore independently observable as zero.
    struct.pack_into('>4f', fighter_input, 0, 0.0, 0.0, 0.35, -0.1)
    fighter_input[0x50] = 0xFE
    d.put(FIGHTER + 0x620, fighter_input)

    d.put(COMMON_DATA_POINTER, struct.pack('>I', COMMON))
    common = bytearray(0x5C)
    values = {
        0x00: 0.28, 0x24: 0.18, 0x28: 0.4, 0x2C: 0.8,
        0x34: -0.3, 0x38: -0.625, 0x3C: 0.8, 0x58: 0.625,
    }
    for offset, value in values.items():
        struct.pack_into('>f', common, offset, value)
    struct.pack_into('>i', common, 0x40, 2)
    d.put(COMMON, common)
    return d


def test_valid_capture_distinguishes_pad_delivery_from_fighter_deadzone():
    d = fixture()
    result = capture_input_evidence(d, FIGHTER)
    assert result['controller_index'] == 2
    assert result['pad']['entry_address'] == PAD_GAME_STATUS + 2 * 0x44
    assert result['pad']['raw_left_stick_s8'] == [16, -8]
    assert result['pad']['raw_left_stick_bytes'] == '10f8'
    assert result['pad']['normalized_left_stick'] == pytest.approx([0.2, -0.1])
    assert result['fighter_input'] == {
        'left_stick': [0.0, 0.0],
        'previous_left_stick': pytest.approx([0.35, -0.1]),
        'tilt_timer_x': 0xFE,
    }
    assert result['common']['thresholds']['horizontal_deadzone'] == pytest.approx(0.28)
    assert result['common']['thresholds']['dash_window'] == 2
    assert 'verdict' not in result
    for block in result['raw_blocks']:
        assert bytes.fromhex(block['raw']) == d.bytes(block['address'], block['size'])


@pytest.mark.parametrize('controller', [4, 255])
def test_invalid_controller_index_is_refused_before_pad_read(controller):
    d = fixture(controller=controller)
    with pytest.raises(CaptureError, match='controller index'):
        capture_input_evidence(d, FIGHTER)


@pytest.mark.parametrize('fighter', [True, 0, 0x80400001, 0x817FFA00])
def test_invalid_fighter_pointer_is_refused(fighter):
    with pytest.raises(CaptureError, match='fighter pointer'):
        capture_input_evidence(fixture(), fighter)


@pytest.mark.parametrize('pointer', [0, 0x80600001, 0x817FFFC0])
def test_invalid_common_pointer_is_refused(pointer):
    d = fixture()
    d.put(COMMON_DATA_POINTER, struct.pack('>I', pointer))
    with pytest.raises(CaptureError, match='ftCommonData pointer'):
        capture_input_evidence(d, FIGHTER)


@pytest.mark.parametrize('target,offset', [
    ('pad', 0x20), ('fighter', 0), ('common', 0x24),
])
def test_nonfinite_decoded_float_is_refused(target, offset):
    d = fixture()
    bases = {
        'pad': PAD_GAME_STATUS + 2 * PAD_STATUS_SIZE,
        'fighter': FIGHTER + 0x620,
        'common': COMMON,
    }
    raw = bytearray(d.blocks[bases[target]])
    struct.pack_into('>I', raw, offset, 0x7FC00000)
    d.put(bases[target], raw)
    with pytest.raises(CaptureError, match='Nonfinite'):
        capture_input_evidence(d, FIGHTER)


@pytest.mark.parametrize('address,size', [
    (FIGHTER + 0x618, 4),
    (PAD_GAME_STATUS + 2 * PAD_STATUS_SIZE, PAD_STATUS_SIZE),
    (FIGHTER + 0x620, 0x54),
    (COMMON_DATA_POINTER, 4),
    (COMMON, 0x5C),
])
def test_every_memory_block_refuses_truncation(address, size):
    d = fixture()
    d.truncate = (address, size)
    with pytest.raises(CaptureError, match='Short'):
        capture_input_evidence(d, FIGHTER)
