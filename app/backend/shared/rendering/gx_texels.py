"""GX texel codecs and hue maths shared by the raw-texel recolors.

One definition for what extras/texture_recolor.py (the shipped recolor, promoted
from the in-game-verified plss_ball_probe prototype) and
shared/rendering/ptcl_texbank.py (the effect texture-bank reader) both need: the tiled
texel order, RGB5A3/RGB565 decode and encode, TLUT (palette) decode and encode,
the saturation-weighted dominant hue, and the per-texel hue rotation.

The two pixel decoders are shared.rendering.datprobe's: that reader is vendored as-is
into the standalone processor build (utility/tools/processor/datprobe.py, kept
byte-equal by a test), so it cannot import from here, and this module reuses
its decoders instead of keeping a second copy.
"""

import colorsys
import struct
from math import atan2, cos, degrees, pi, sin

from shared.rendering.datprobe import _rgb565 as rgb565, _rgb5a3 as rgb5a3


def tile_iter(w, h, bw, bh):
    """Yield (x, y, linear_index) in GX tiled order for a bw x bh tile grid."""
    idx = 0
    for ty in range(0, h, bh):
        for tx in range(0, w, bw):
            for py in range(bh):
                for px in range(bw):
                    yield tx + px, ty + py, idx
                    idx += 1


def enc_rgb5a3(r, g, b, a):
    if a >= 0xE0:  # treat near-opaque as opaque bit set
        return 0x8000 | ((r * 31 // 255) << 10) | ((g * 31 // 255) << 5) | (b * 31 // 255)
    return (((a * 7 // 255) & 0x7) << 12) | ((r * 15 // 255) << 8) \
        | ((g * 15 // 255) << 4) | (b * 15 // 255)


def enc_rgb565(r, g, b, a):
    return ((r * 31 // 255) << 11) | ((g * 63 // 255) << 5) | (b * 31 // 255)


def decode_palette(raw, count, tlut_fmt):
    """raw: the TLUT byte block (may be the full fixed 0x200-byte HSDRaw
    block; only the first `count` entries are decoded). -> [RGBA...]."""
    out = []
    for i in range(count):
        v = struct.unpack_from('>H', raw, i * 2)[0]
        if tlut_fmt == 2:        # RGB5A3
            out.append(rgb5a3(v))
        elif tlut_fmt == 1:      # RGB565
            out.append(rgb565(v))
        else:                     # IA8
            inten = v & 0xFF
            alpha = (v >> 8) & 0xFF
            out.append((inten, inten, inten, alpha))
    return out


def encode_palette(pal, tlut_fmt, block_size=0x200):
    """[RGBA...] -> TLUT bytes, len(pal) * 2 of them. `block_size` names
    HSDRaw's fixed palette block and does not change the output: the caller
    re-writes only `len(pal) * 2` bytes, so the vanilla block's trailing bytes
    are preserved."""
    buf = bytearray(len(pal) * 2)
    for i, (r, g, b, a) in enumerate(pal):
        if tlut_fmt == 2:
            v = enc_rgb5a3(r, g, b, a)
        elif tlut_fmt == 1:
            v = enc_rgb565(r, g, b, a)
        else:  # IA8
            v = ((a & 0xFF) << 8) | (((r + g + b) // 3) & 0xFF)
        struct.pack_into('>H', buf, i * 2, v)
    return bytes(buf)


def dominant_hue(px):
    """Saturation-weighted dominant hue (degrees) of an RGBA texel list, or
    None if nothing qualifies."""
    sx = sy = 0.0
    for r, g, b, a in px:
        if a < 32:
            continue
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        if s < 0.15 or l < 0.08 or l > 0.95:
            continue
        ang = h * 2 * pi
        sx += s * cos(ang)
        sy += s * sin(ang)
    if sx == 0 and sy == 0:
        return None
    return degrees(atan2(sy, sx)) % 360


def recolor_texels(px, hue_shift_deg):
    """Rotate each texel's hue by hue_shift_deg, preserving S/V(L)/alpha.
    Grays (low S) barely move; whites/blacks stay neutral."""
    shift = (hue_shift_deg % 360) / 360.0
    out = []
    for r, g, b, a in px:
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        h = (h + shift) % 1.0
        nr, ng, nb = colorsys.hls_to_rgb(h, l, s)
        out.append((round(nr * 255), round(ng * 255), round(nb * 255), a))
    return out
