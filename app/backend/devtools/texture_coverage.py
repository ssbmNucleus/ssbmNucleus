"""
texture_coverage.py -- sweep every Ef*Data texture bank for COLORED texture
groups and cross-ref against shipped extras. Finds Bowser-breath_texture-style
coverage gaps: colored flame/glow textures whose extras only tint particles,
so a recolored mod still reads mostly-vanilla in game (the 2026-07-03 blue
fire report). Grayscale groups are fine -- ptcl colors tint those.

    python devtools/texture_coverage.py

Output: one row per colored (>=10% saturated pixels, usage-weighted) or
already-covered texture group, with ** GAP ** markers when the file has color
extras but nothing recolors that group. Rows are candidates for new
`texture_recolor` extras (offsets = the group's images/palettes, see
breath_texture / upb_charge_fire precedent); attribute the group to a move
via the scripts' texGroup header (ptcl_parse Script.header['texGroup']) plus
a MAP-mission live poke before shipping.

Decode gotcha handled here: ptcl_texbank stores the RAW packed tlutfmt word
(e.g. 0x01000002); the GX palette format is its low bits -- decoding CI
groups with the raw value silently produces grayscale garbage.
"""
import sys
import glob
import os
import colorsys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "shared", "rendering"))

import ptcl_texbank as tb  # noqa: E402
from core.extra_types import EXTRA_TYPES  # noqa: E402

FILES = sorted(glob.glob(os.path.join(
    os.path.dirname(BACKEND), "storage", "test-base", "files", "Ef*Data.dat")))

# which target files have shipped extras, and which texture extras cover
# which byte extents
color_extras = {}      # target_file -> [extra ids with color offsets]
texture_extents = {}   # target_file -> [(extra_id, start, end)]
for char, lst in EXTRA_TYPES.items():
    for t in lst:
        tf = t.get("target_file")
        if not tf:
            continue
        if t.get("format") == "texture_recolor":
            tex = t["texture"]
            offs = []
            if "images" in tex:
                for im in tex["images"]:
                    o = im["offset"]
                    p = im["palette"]
                    offs.append(int(o, 16) if isinstance(o, str) else o)
                    offs.append(int(p, 16) if isinstance(p, str) else p)
            else:
                s = tex.get("offset") or tex.get("start")
                if s is not None:
                    offs.append(int(s, 16) if isinstance(s, str) else s)
            if offs:
                texture_extents.setdefault(tf, []).append(
                    (t["id"], min(offs), max(offs) + 0x200))
        elif t.get("offsets"):
            color_extras.setdefault(tf, []).append(t["id"])

from shared.rendering.gx_texels import decode_palette, dominant_hue  # noqa: E402


def group_pixels(data, g):
    """Usage-weighted pixels for hue measurement. ptcl_texbank stores the RAW
    packed tlutfmt word (e.g. 0x01000002); decode_texgroup_image needs the GX
    format in the low bits, so mask before building the TLUT -- without this,
    CI decodes silently produce garbage for most banks."""
    if g.fmt in (8, 9):  # CI4 / CI8
        cnt = 0x100 if g.fmt == 9 else 0x10
        pal_offs = [o for o in (g.pal_offs or []) if o]
        px = []
        for k, off in enumerate(g.image_offs):
            if not off:
                continue
            img = tb._Img(off - tb.DATA_START, g.width, g.height, g.fmt,
                          data[off:off + g.image_size])
            po = None
            if pal_offs:
                po = pal_offs[0] if len(pal_offs) == 1 else (
                    pal_offs[k] if k < len(pal_offs) else pal_offs[0])
            if po is None:
                continue
            tlut = tb._Tlut(po - tb.DATA_START, g.tlutfmt & 0x3, cnt,
                            data[po:po + cnt * 2])
            try:
                px += tb._rows_to_flat(tb.decode_texgroup_image(data, img, tlut))
            except Exception:
                pass
        return px
    _hue, flat = tb.group_dominant_hue(data, g)
    return flat


def colored_fraction(px):
    opaque = colored = 0
    for r, g, b, a in px:
        if a < 32:
            continue
        opaque += 1
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        if s >= 0.15 and 0.08 < l < 0.95:
            colored += 1
    return (colored / opaque) if opaque else 0.0, opaque

print(f"{'file':<14} {'grp':>3} {'fmt':<7} {'imgs':>4} {'size':<9} "
      f"{'hue':>6} {'col%':>5}  coverage")
print("-" * 100)
for path in FILES:
    name = os.path.basename(path)
    try:
        report, data, groups = tb.build_report(path)
    except Exception as e:
        print(f"{name:<14} !! parse failed: {e}")
        continue
    has_color_extra = name in color_extras
    for g in groups:
        if g.group_file_off is None:
            continue
        flat = group_pixels(data, g)
        hue = dominant_hue(flat)
        frac, opaque = colored_fraction(flat)
        ext = g.extent()
        covered = ""
        for (eid, s, e) in texture_extents.get(name, []):
            if ext and not (ext[1] <= s or ext[0] >= e):
                covered = f"covered by {eid}"
        colored = hue is not None and frac >= 0.10
        flag = ""
        if colored and not covered:
            flag = ("** GAP (file has color extras: "
                    f"{','.join(color_extras[name])}) **" if has_color_extra
                    else "(colored, file has NO extras)")
        if colored or covered:
            print(f"{name:<14} {g.index:>3} {tb.FMT_NAMES.get(g.fmt, g.fmt):<7} "
                  f"{g.num:>4} {g.width}x{g.height:<6} "
                  f"{(round(hue) if hue is not None else '-'):>6} "
                  f"{frac*100:4.0f}%  {covered}{flag}")
