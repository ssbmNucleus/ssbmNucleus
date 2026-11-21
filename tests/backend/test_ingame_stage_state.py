import struct

import pytest

from shared.ingame.pose import CaptureError
from shared.ingame.stage_state import capture_stage_state


@pytest.mark.parametrize('kind', [37, 36, -1, 511])
def test_exact_engine_ground_kind_and_raw_word_preserved(kind):
    class Memory:
        def bytes(self, address, size):
            assert (address, size) == (0x8049E750, 4)
            return struct.pack('>i', kind)
    result = capture_stage_state(Memory())
    assert result['ground_kind'] == kind
    assert result['raw'] == struct.pack('>i', kind).hex()
    assert 'stage_name' not in result and 'stage_id' not in result


@pytest.mark.parametrize('raw', [None, b'', b'\x00\x00\x25'])
def test_short_memory_is_not_unknown_or_default_stage(raw):
    class Memory:
        def bytes(self, address, size): return raw
    with pytest.raises(CaptureError, match='Short MEM1'):
        capture_stage_state(Memory())
