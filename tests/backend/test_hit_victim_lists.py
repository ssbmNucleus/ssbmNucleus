import struct
import pytest
from tools.ingame.contacts import decode_hit_victims,HITBOX_STRIDE


def test_zero_cursor_does_not_mean_empty():
    raw=bytearray(HITBOX_STRIDE);struct.pack_into('>II',raw,0x74,0x81234560,0)
    row=decode_hit_victims(bytes(raw))
    assert row['primary']['replacement_cursor']==0
    assert row['primary']['occupied']==1 and row['primary']['entries'][0]['pointer']==0x81234560
    assert row['secondary']['occupied']==0


def test_all_twelve_slots_retained():
    raw=bytearray(HITBOX_STRIDE);raw[0x45]=11
    for i in range(12):struct.pack_into('>II',raw,0xd4+i*8,0x81200000+i*4,i)
    row=decode_hit_victims(bytes(raw))['secondary']
    assert row['occupied']==12 and row['entries'][11]['timer']==11


@pytest.mark.parametrize('offset,value',[(0x44,12),(0x45,255)])
def test_bad_cursor_refused(offset,value):
    raw=bytearray(HITBOX_STRIDE);raw[offset]=value
    with pytest.raises(ValueError):decode_hit_victims(bytes(raw))
