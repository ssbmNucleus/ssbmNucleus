import struct
import pytest
from core.iso_reads import ensure_padding, inspect


def disc(tmp_path, offset=0x60C, length=44):
    # File ends at ...38; whole-image 32-byte padding leaves only eight bytes,
    # but the game's 64-byte read needs twenty: the real 12-byte EOF failure.
    names = b'\0costume.dat\0'
    fst = struct.pack('>III', 0x01000000, 0, 2) + struct.pack('>III', 1, offset, length) + names
    size = (offset + length + 31) & ~31
    data = bytearray(size)
    data[0x1C:0x20] = bytes.fromhex('c2339f3d')
    struct.pack_into('>II', data, 0x424, 0x440, len(fst))
    data[0x440:0x440+len(fst)] = fst
    data[offset:offset+length] = bytes(range(length))
    path = tmp_path / 'candidate.iso'
    path.write_bytes(data)
    return path


def test_unaligned_last_file_needs_more_than_whole_iso_alignment(tmp_path):
    path = disc(tmp_path)
    original = path.read_bytes()
    assert inspect(path)['issues'][0]['missing_padding'] == 12
    receipt = ensure_padding(path)
    assert receipt['added_bytes'] > 0
    assert path.read_bytes()[:len(original)] == original
    assert not any(path.read_bytes()[len(original):])
    assert path.stat().st_size % 2048 == 0
    assert not inspect(path)['issues']
    assert ensure_padding(path)['added_bytes'] == 0


def test_aligned_payload_is_already_safe(tmp_path):
    path = disc(tmp_path, offset=0x600)
    original = path.read_bytes()
    assert ensure_padding(path)['added_bytes'] == 0
    assert path.read_bytes() == original


def test_missing_payload_is_never_synthesized(tmp_path):
    path = disc(tmp_path)
    path.write_bytes(path.read_bytes()[:-9])
    original = path.read_bytes()
    with pytest.raises(ValueError, match='Truncated ISO payload'):
        ensure_padding(path)
    assert path.read_bytes() == original


def test_bad_fst_is_refused_before_mutation(tmp_path):
    path = disc(tmp_path)
    data = bytearray(path.read_bytes())
    struct.pack_into('>I', data, 0x448, 0xFFFFFFFF)
    path.write_bytes(data)
    with pytest.raises(ValueError, match='FST root/count'):
        ensure_padding(path)
    assert path.read_bytes() == data
