"""Read an Ultimate texture file (.nutexb) into an image.

The file is the pixel data, then a 0xB0-byte footer (little endian) that ends
in " XET": sixteen mip sizes, " XNT", a 0x40-byte name, width, height, depth,
a format byte, then mip count, alignment, layer count and data size.

The data is laid out the Switch's way (Tegra "block linear": 64x8-byte tiles
stacked in blocks of up to sixteen), so it is put back in rows first. Block
compressed formats are then decoded by Pillow.

Checked against a known-good copy of Byleth's `alp_master_001_col` (see the test).
"""
from __future__ import annotations

import struct
from pathlib import Path

# format byte -> (kind, bytes per pixel or per 4x4 block)
FORMATS = {0x00: ('rgba', 4), 0x05: ('rgba', 4), 0x50: ('bgra', 4), 0x55: ('bgra', 4),
           0x80: ('bc1', 8), 0x85: ('bc1', 8), 0x90: ('bc2', 16), 0x95: ('bc2', 16),
           0xA0: ('bc3', 16), 0xA5: ('bc3', 16), 0xB0: ('bc4', 8), 0xB5: ('bc4', 8),
           0xC0: ('bc5', 16), 0xC5: ('bc5', 16), 0xE0: ('bc7', 16), 0xE5: ('bc7', 16)}


def header(data: bytes):
    if data[-8:-4] != b' XET':
        raise ValueError('not a nutexb file')
    f = data[-0xB0:]
    if f[0x40:0x44] != b' XNT':
        raise ValueError('nutexb footer not where expected')
    width, height, depth = struct.unpack_from('<III', f, 0x84)
    mips, _align, layers, size = struct.unpack_from('<IIII', f, 0x98)
    return {'name': f[0x44:0x84].split(b'\0')[0].decode('ascii', 'replace'), 'width': width, 'height': height,
            'depth': depth, 'format': f[0x90], 'mips': mips, 'layers': layers, 'size': size,
            'mip_sizes': list(struct.unpack_from('<16I', f, 0))}


def _stack(rows):
    """How many 8-row tiles are stacked in one block, for a surface `rows` high."""
    span = rows + rows // 2
    return 16 if span >= 128 else 8 if span >= 64 else 4 if span >= 32 else 2 if span >= 16 else 1


def unswizzle(data: bytes, columns: int, rows: int, unit: int) -> bytes:
    """Block-linear data -> rows of `columns` units of `unit` bytes."""
    stack = _stack(rows)
    wide = columns * unit
    tiles_across = -(-wide // 64)
    out = bytearray(wide * rows)
    for y in range(rows):
        base = (y // (8 * stack)) * 512 * stack * tiles_across + (y % (8 * stack) // 8) * 512
        row = (y % 8 // 2) * 64 + (y % 2) * 16
        for x in range(0, wide, unit):
            at = base + (x // 64) * 512 * stack + (x % 64 // 32) * 256 + (x % 32 // 16) * 32 + x % 16 + row
            out[y * wide + x:y * wide + x + unit] = data[at:at + unit]
    return bytes(out)


def read(path):
    """-> (PIL image, RGBA, top mip of the first layer; header)"""
    from PIL import Image
    data = Path(path).read_bytes()
    h = header(data)
    if h['format'] not in FORMATS:
        raise ValueError(f"{path}: texture format {h['format']:#x} is not handled")
    kind, unit = FORMATS[h['format']]
    w, ht = h['width'], h['height']
    if kind in ('rgba', 'bgra'):
        raw = unswizzle(data, w, ht, unit)
        return Image.frombytes('RGBA', (w, ht), raw, 'raw', 'RGBA' if kind == 'rgba' else 'BGRA'), h
    bw, bh = -(-w // 4), -(-ht // 4)
    raw = unswizzle(data, bw, bh, unit)
    n = int(kind[2])
    image = Image.frombytes('RGBA' if n != 4 else 'L', (bw * 4, bh * 4), raw, 'bcn', (n, kind.upper()))
    return image.convert('RGBA').crop((0, 0, w, ht)), h


def swizzle(rows_data: bytes, columns: int, rows: int, unit: int) -> bytes:
    """Rows of `columns` units of `unit` bytes -> block-linear data (the inverse of `unswizzle`), padded to whole
    blocks."""
    stack = _stack(rows)
    wide = columns * unit
    tiles = -(-wide // 64)
    out = bytearray(512 * stack * tiles * (-(-rows // (8 * stack))))
    for y in range(rows):
        base = (y // (8 * stack)) * 512 * stack * tiles + (y % (8 * stack) // 8) * 512
        row = (y % 8 // 2) * 64 + (y % 2) * 16
        for x in range(0, wide, unit):
            at = base + (x // 64) * 512 * stack + (x % 64 // 32) * 256 + (x % 32 // 16) * 32 + x % 16 + row
            out[at:at + unit] = rows_data[y * wide + x:y * wide + x + unit]
    return bytes(out)


def write(path, image, name=None):
    """An image saved as a nutexb the way `read` reads one: plain RGBA (format 0x00), one mip, one layer. (For a
    game that is not Ultimate, whose pictures the port is handed in Ultimate's shapes.)"""
    import struct
    image = image.convert('RGBA')
    w, h = image.size
    data = swizzle(image.tobytes(), w, h, 4)
    name = (name or Path(path).stem).encode('ascii', 'replace')[:0x3F]
    footer = bytearray(0xB0)
    struct.pack_into('<I', footer, 0, len(data))
    footer[0x40:0x44] = b' XNT'
    footer[0x44:0x44 + len(name)] = name
    struct.pack_into('<IIIBBHI', footer, 0x84, w, h, 1, 0x00, 4, 0, 0)
    struct.pack_into('<IIII', footer, 0x98, 1, 0x1000, 1, len(data))
    footer[0xA8:0xAC] = b' XET'
    struct.pack_into('<HH', footer, 0xAC, 1, 2)
    Path(path).write_bytes(data + bytes(footer))
