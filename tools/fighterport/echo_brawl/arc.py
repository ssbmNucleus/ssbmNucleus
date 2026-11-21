"""Brawl's archive (.pac; .pcs is the same, compressed): a list of files, each with a kind and an index.

Kinds: 1 misc data (a fighter's moveset), 2 model data (a BRRES), 3 texture data, 4 animation data, 6 effects.
"""
from __future__ import annotations

import struct

KINDS = {1: 'misc', 2: 'model', 3: 'texture', 4: 'animation', 5: 'scene', 6: 'effect', 7: 'group', 8: 'effect2'}


def lz77(data: bytes) -> bytes:
    """Nintendo's LZ77 (type 0x10), with or without the 'LZ77' tag in front."""
    at = 4 if data[:4] == b'LZ77' else 0
    if data[at] & 0xF0 != 0x10:
        raise ValueError('not LZ77 type 0x10 data')
    size = int.from_bytes(data[at + 1:at + 4], 'little')
    at += 4
    if size == 0:
        size = int.from_bytes(data[at:at + 4], 'little')
        at += 4
    out = bytearray()
    while len(out) < size:
        flags = data[at]
        at += 1
        for bit in range(8):
            if len(out) >= size:
                break
            if flags & (0x80 >> bit):
                a, b = data[at], data[at + 1]
                at += 2
                count, back = (a >> 4) + 3, ((a & 0xF) << 8 | b) + 1
                for _ in range(count):
                    out.append(out[-back])
            else:
                out.append(data[at])
                at += 1
    return bytes(out)


def read(data: bytes):
    """-> (the archive's name, [{'kind', 'index', 'group', 'redirect', 'data'}])"""
    if data[:4] != b'ARC\x00':
        data = lz77(data)
    if data[:4] != b'ARC\x00':
        raise ValueError('not a Brawl archive')
    count = struct.unpack_from('>H', data, 6)[0]
    name = data[0x10:0x40].split(b'\x00')[0].decode('ascii', 'replace')
    at, files = 0x40, []
    for _ in range(count):
        kind, index, size, group, _pad, redirect = struct.unpack_from('>HHIBBh', data, at)
        body = data[at + 0x20:at + 0x20 + size]
        files.append({'kind': KINDS.get(kind, kind), 'index': index, 'group': group, 'redirect': redirect, 'data': body})
        at = (at + 0x20 + size + 0x1F) & ~0x1F
    return name, files
