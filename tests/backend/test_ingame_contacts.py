import json
import struct
import pytest
from tools.ingame.contacts import (capture_hurtboxes, decode_hitboxes, decode_hurtboxes,
                             HITBOX_STRIDE, HURTBOX_OFFSET, HURTBOX_STRIDE,
                             HURTBOX_CAPACITY, HURTBOX_COUNT_OFFSET)
from shared.ingame.pose import CaptureError
from tools.ingame.contacts import native_hitbox_geometry


def test_native_command_literal_and_axis_order_match_captured_backair():
    geometry = native_hitbox_geometry({'size':1331,'z_offset':1188,'y_offset':-255,'x_offset':184})
    assert geometry == {'radius':5.198885917663574,
                        'local_xyz':[4.6403279304504395,-0.9960299730300903,0.7187039852142334]}
    assert abs(geometry['radius']-1331/256) > .0003


@pytest.mark.parametrize('key,value', [('size',-1),('size',65536),('x_offset',32768),('y_offset',-32769),('z_offset',True),('size',1.0)])
def test_native_command_geometry_refuses_unencoded_values(key,value):
    fields={'size':1331,'z_offset':1188,'y_offset':-255,'x_offset':184}
    fields[key]=value
    with pytest.raises(CaptureError): native_hitbox_geometry(fields)


def fixture():
    raw = bytearray(4*HITBOX_STRIDE)
    struct.pack_into('>III', raw, 0, 2, 0xDEADBEEF, 3)
    struct.pack_into('>5f', raw, 12, 2.76, 1, 2, 3, 6.5)
    struct.pack_into('>I', raw, 0x48, 0x81234560)
    raw[0x44] = 1
    raw[0x134] = 0x80
    return raw


def test_live_two_attachment_and_big_endian_fields():
    hit, = decode_hitboxes(bytes(fixture()))
    assert hit['live'] == 2
    assert hit['bone_pointer'] == 0x81234560
    assert hit['integer_damage'] == 3 and hit['damage'] == pytest.approx(2.76)
    assert hit['local_xyz'] == [1,2,3] and hit['radius'] == 6.5
    assert hit['grabbed_only'] and hit['victim_count'] == 1


def test_short_or_nonfinite_live_data_refused():
    with pytest.raises(CaptureError):
        decode_hitboxes(bytes(3*HITBOX_STRIDE))
    raw = fixture()
    struct.pack_into('>f', raw, 0x4c, float('nan'))
    with pytest.raises(CaptureError):
        decode_hitboxes(bytes(raw))


def test_inactive_stale_data_not_interpreted_as_live():
    raw = fixture()
    struct.pack_into('>I', raw, 0, 0)
    struct.pack_into('>f', raw, 0x4c, float('nan'))
    assert decode_hitboxes(bytes(raw)) == []


def hurt_fixture():
    raw = bytearray(HURTBOX_CAPACITY * HURTBOX_STRIDE)
    for slot, state in enumerate((0, 1, 2)):
        base = slot * HURTBOX_STRIDE
        struct.pack_into('>I7fI', raw, base, state,
                         1 + slot, 2 + slot, 3 + slot,
                         4 + slot, 5 + slot, 6 + slot, 1.5 + slot,
                         0x81234000 + slot * 0x20)
        raw[base + 0x24] = 0x80 if slot == 2 else 0x40
        struct.pack_into('>6fIII', raw, base + 0x28,
                         10 + slot, 11 + slot, 12 + slot,
                         13 + slot, 14 + slot, 15 + slot,
                         0x20 + slot, slot, slot != 1)
    return raw


def test_hurtboxes_preserve_states_attachment_flags_and_big_endian_fields():
    raw = hurt_fixture()
    struct.pack_into('>I', raw, 2 * HURTBOX_STRIDE + 0x48, 0x10203040)
    boxes = decode_hurtboxes(bytes(raw), 3)
    assert [box['state'] for box in boxes] == [0, 1, 2]
    assert boxes[2]['local_a'] == [3, 4, 5]
    assert boxes[2]['scale'] == 3.5
    assert boxes[2]['bone_pointer'] == 0x81234040
    assert boxes[2]['bone_index'] == 0x22
    assert boxes[2]['height'] == 2 and boxes[2]['grabbable']
    assert boxes[2]['grabbable_word'] == 0x10203040
    assert boxes[2]['flags_byte'] == 0x80 and boxes[2]['skip_update_pos']
    assert boxes[1]['grabbable'] is False


@pytest.mark.parametrize('count', [-1, 16, 1.0, True])
def test_hurtbox_count_is_bounded_integer(count):
    with pytest.raises(CaptureError):
        decode_hurtboxes(bytes(hurt_fixture()), count)


def test_hurtbox_full_native_array_required_and_active_locals_are_finite():
    with pytest.raises(CaptureError):
        decode_hurtboxes(bytes(hurt_fixture()[:-1]), 1)
    raw = hurt_fixture()
    struct.pack_into('>f', raw, 4, float('nan'))
    with pytest.raises(CaptureError):
        decode_hurtboxes(bytes(raw), 1)
    raw = hurt_fixture()
    struct.pack_into('>I', raw, 0, 3)
    with pytest.raises(CaptureError):
        decode_hurtboxes(bytes(raw), 1)


def test_hurtbox_cached_stale_nonfinite_is_preserved_without_reading_past_count():
    raw = hurt_fixture()
    struct.pack_into('>f', raw, 0x28, float('nan'))
    struct.pack_into('>f', raw, 0x34, float('inf'))
    struct.pack_into('>f', raw, HURTBOX_STRIDE + 4, float('nan'))
    expected_raw = bytes(raw[:HURTBOX_STRIDE])
    box, = decode_hurtboxes(bytes(raw), 1)
    assert box['cached_a'][0] is None and box['cached_b'][0] is None
    assert box['cached_positions_finite'] is False
    assert bytes.fromhex(box['raw']) == expected_raw
    json.dumps(box, allow_nan=False)


def test_capture_hurtboxes_reads_count_and_complete_array():
    fighter = 0x80400000
    raw = bytes(hurt_fixture())

    class Memory:
        def __init__(self):
            self.calls = []

        def bytes(self, address, size):
            self.calls.append((address, size))
            return b'\x00\x00\x03\x00' if size == 4 else raw

    d = Memory()
    capture = capture_hurtboxes(d, fighter)
    assert d.calls == [(fighter + HURTBOX_COUNT_OFFSET - 2, 4),
                       (fighter + HURTBOX_OFFSET, HURTBOX_CAPACITY * HURTBOX_STRIDE)]
    assert capture['raw_count'] == '03' and capture['count'] == 3
    assert capture['raw'] == raw.hex() and len(capture['hurtboxes']) == 3
