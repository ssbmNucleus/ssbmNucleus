"""Particle textures of an effect DAT (HSD particle texture bank, particle.c psInitDataBankLocate).

The effect table (efasync.c efAsync_DatEntries, e.g. EfCoData.dat `effCommonDataTable`) starts with
the command bank and the texture bank. The texture bank is {u32 groups; u32 group offset[groups]},
offsets relative to the bank; a group (HSD_PSTexGroup) is {num, fmt, tlutfmt, width, height,
u16 palnum, u16 palflag, u32 image offset[num], palette offset(s)}: `num` poses of one size and
format. Colour-indexed groups (fmt 8/9/10) carry one palette (palflag & 1) or one per pose.
"""
import struct

import numpy as np

from shared.rendering import datprobe


def banks(d, table_root):
    """(command bank, texture bank) offsets of an effect table root."""
    tab = d.root[table_root]
    return d.u(tab), d.u(tab + 4)


def group(d, tex_bank, g):
    """Texture group `g`: {'fmt', 'w', 'h', 'poses': [H x W x 4 float32 RGBA 0..255]} or None."""
    if g < 0 or g >= d.u(tex_bank):
        return None
    go = d.u(tex_bank + 4 + 4 * g)
    if not go:
        return None
    tg = tex_bank + go
    num, fmt, tfmt, w, h = (d.u(tg + 4 * i) for i in range(5))
    palnum, palflag = struct.unpack_from('>HH', d.raw, 0x20 + tg + 0x14)
    poses = []
    for k in range(num):
        off = tex_bank + d.u(tg + 0x18 + 4 * k)
        data = d.raw[0x20 + off:0x20 + off + datprobe.gx_image_size(fmt, w, h)]
        tl = None
        if fmt in (8, 9, 10):
            po = tex_bank + d.u(tg + 0x18 + 4 * (num if palflag & 1 else num + k))
            n = 16 if fmt == 8 else 256
            tl = datprobe.Tlut(0, po, tfmt, n, d.raw[0x20 + po:0x20 + po + 2 * n])
        rows = np.array(datprobe.decode_image(datprobe.Image(0, off, w, h, fmt, data), tl), dtype=np.float32)
        if fmt in (0, 1):
            rows[:, :, 3] = rows[:, :, 0]      # GX I4 / I8: the intensity is the alpha too
        poses.append(rows)
    return {'fmt': fmt, 'w': w, 'h': h, 'poses': poses}
