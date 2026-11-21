"""Reader for Smash Ultimate .prc parameter files (magic 'paracobn').

Names in these files are 40-bit hashes: (length << 32) | crc32(lowercase name).
A name can only be shown when it is known, so labels are built from whatever
word lists are passed in; unknown ones print as 0x... hashes.
"""
import struct
import zlib


def hash40(s: str) -> int:
    b = s.lower().encode('utf-8')
    return (len(b) << 32) | (zlib.crc32(b) & 0xFFFFFFFF)


class Prc:
    def __init__(self, data: bytes, labels=()):
        if data[:8] != b'paracobn':
            raise ValueError('not a prc file')
        hsize, rsize = struct.unpack_from('<II', data, 8)
        self.hashes = list(struct.unpack_from(f'<{hsize // 8}Q', data, 16))
        self.ref = data[16 + hsize:16 + hsize + rsize]
        self.data = data
        self.start = 16 + hsize + rsize
        self.labels = {hash40(n): n for n in labels}
        self.root = self._read(self.start)

    def name(self, h: int) -> str:
        return self.labels.get(h, f'0x{h:010x}')

    def _read(self, o):
        d = self.data
        t = d[o]
        p = o + 1
        if t == 1:
            return bool(d[p])
        if t == 2:
            return struct.unpack_from('<b', d, p)[0]
        if t == 3:
            return d[p]
        if t == 4:
            return struct.unpack_from('<h', d, p)[0]
        if t == 5:
            return struct.unpack_from('<H', d, p)[0]
        if t == 6:
            return struct.unpack_from('<i', d, p)[0]
        if t == 7:
            return struct.unpack_from('<I', d, p)[0]
        if t == 8:
            return struct.unpack_from('<f', d, p)[0]
        if t == 9:
            return Hash(self.hashes[struct.unpack_from('<I', d, p)[0]], self)
        if t == 10:
            s = struct.unpack_from('<I', d, p)[0]
            return self.ref[s:self.ref.index(b'\0', s)].decode('utf-8', 'replace')
        if t == 11:
            n = struct.unpack_from('<I', d, p)[0]
            offs = struct.unpack_from(f'<{n}I', d, p + 4)
            return [self._read(o + x) for x in offs]
        if t == 12:
            n, r = struct.unpack_from('<II', d, p)
            out = {}
            for i in range(n):
                hi, off = struct.unpack_from('<II', self.ref, r + i * 8)
                out[self.name(self.hashes[hi])] = self._read(o + off)
            return out
        raise ValueError(f'unknown param type {t} at {o:#x}')


class Hash:
    def __init__(self, value, prc):
        self.value = value
        self.text = prc.name(value)

    def __repr__(self):
        return self.text

    def __eq__(self, other):
        return isinstance(other, Hash) and other.value == self.value or other == self.text

    def __hash__(self):
        return hash(self.value)
