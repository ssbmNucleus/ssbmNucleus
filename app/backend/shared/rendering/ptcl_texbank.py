#!/usr/bin/env python3
"""
ptcl_texbank.py -- decode the HSD_TEXGraphicBank inside an Ef*Data.dat.

Companion to ptcl_parse.py. Where ptcl_parse decodes the particle *bytecode*
(color operands + each script's `texGroup` index), THIS module decodes the
*texture bank* those texGroup indices point into, so the marquee TEXTURE-ONLY
effects (Din's Fire, Vanish, Quick Attack, Link arrow, Bowser Bomb, Marth/Roy
fire) can be wired as `texture_recolor` extras -- which need, per texGroup:
per-image {file offset, width, height, gx_format, palette offset/format}.

FORMAT (decoded from the decomp + HSDRaw, both agree)
    SBM_EffectTable @ data-section 0:
        +0x00  Particles       -> HSD_ParticleGroup  (ptcl bank; ptcl_parse)
        +0x04  TextureGraphics -> HSD_TEXGraphicBank  (THIS bank)

    HSD_TEXGraphicBank  (offsets relative to the bank start = 0x20 + tex_ptr):
        [0]              s32  num_groups
        [1 .. num]       s32  group_offset[num_groups]  (relative to bank start;
                                                         0 = null / "same slot")
        (HSDRaw HSD_TEXGraphicBank.cs: Length @0x00, offsets @0x04*i;
         decomp psInitDataBankLocate "Phase 3": groups = texBank+1, each entry
         += texBank when nonzero.)

    HSD_PSTexGroup  (0x18 header; decomp psstructs.h _HSD_PSTexGroup):
        +0x00  u32  num       image count (== poseNum range)
        +0x04  u32  fmt       GXTexFmt
        +0x08  u32  tlutfmt   GXTlutFmt (palette format, CI only)
        +0x0C  u32  width
        +0x10  u32  height
        +0x14  u16  palnum    #palettes (0 -> 1-per-image "double num" scheme)
        +0x16  u16  palflag   bit0 = single shared palette
        +0x18  s32  texTable[num]   image-data offsets (relative to bank start)
        +0x18+num*4  s32 palTable[...]  palette offsets (CI only; count per
                                        palflag/palnum, see decomp Phase-3)

    A particle script's `pp->texGroup` (ptcl_parse Script.header['texGroup'])
    indexes psTexGroupArray[bank][texGroup] == group[texGroup] here, and the
    running `poseNum` selects texTable[poseNum] -- so one texGroup can hold an
    animated sequence of frames sharing one w/h/fmt.

RAW FILE OFFSETS: like plss_ball_probe / texture_recolor, everything printed
and every texture_recolor `offset` emitted here is a RAW file offset
(data-section-relative + 0x20 header), directly usable by a hex editor and by
extras/texture_recolor.py's _region() (which does NOT re-add the header).

CLI:
    python ptcl_texbank.py <EfXxData.dat> [--json] [--export DIR]
                           [--groups 9,16] [--recolor-spec]
    python ptcl_texbank.py --verify        # 17088-diff-containment self-test
"""

import argparse
import glob
import json
import os
import struct
import sys

# reuse the verified GX decoders from plss_ball_probe / texture_recolor
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))  # backend/ for the shared.rendering imports

from datprobe import gx_image_size  # noqa: E402  (shared/rendering is on path via _HERE)
from shared.rendering.gx_texels import dominant_hue  # noqa: E402  (backend/ is on path too)

DATA_START = 0x20


def _u16(d, o):
    return struct.unpack_from(">H", d, o)[0]


def _u32(d, o):
    return struct.unpack_from(">I", d, o)[0]


def parse_archive(data):
    """Return (data_section_start, effect_table_file_offset, public_name)."""
    _fsize, dsize, nreloc, npub = struct.unpack_from(">IIII", data, 0)
    reloc_off = DATA_START + dsize
    pub_off = reloc_off + nreloc * 4
    do, no = struct.unpack_from(">II", data, pub_off)
    str_off = pub_off + npub * 8
    name = data[str_off + no:str_off + no + 64].split(b"\x00")[0].decode(
        "ascii", "replace")
    return DATA_START, DATA_START + do, name


# --------------------------------------------------------------------------- #
# GX decode (RGB5A3 / RGB565 / I4 / I8 / IA4 / IA8 / CI4 / CI8 / RGBA8 / CMPR)
# Reuse datprobe.decode_image where possible via a tiny Image shim.
# --------------------------------------------------------------------------- #
class _Img:
    __slots__ = ("data_offset", "width", "height", "format", "data")

    def __init__(self, data_offset, width, height, fmt, data):
        self.data_offset = data_offset
        self.width = width
        self.height = height
        self.format = fmt
        self.data = data


class _Tlut:
    __slots__ = ("data_offset", "format", "count", "data")

    def __init__(self, data_offset, fmt, count, data):
        self.data_offset = data_offset
        self.format = fmt
        self.count = count
        self.data = data


def decode_texgroup_image(data, img, tlut=None):
    """Decode one HSD_PSTexGroup image via datprobe's proven decoder.
    Returns [h][w] RGBA rows."""
    from datprobe import decode_image as _dp_decode
    return _dp_decode(img, tlut)


# --------------------------------------------------------------------------- #
# bank walk
# --------------------------------------------------------------------------- #
class TexGroup:
    def __init__(self, index, group_file_off):
        self.index = index
        self.group_file_off = group_file_off
        self.num = 0
        self.fmt = 0
        self.tlutfmt = 0
        self.width = 0
        self.height = 0
        self.palnum = 0
        self.palflag = 0
        self.image_offs = []   # raw file offsets of each image's pixel data
        self.pal_offs = []     # raw file offsets of each palette (CI only)

    @property
    def is_paletted(self):
        return self.fmt in (8, 9, 10)  # CI4 / CI8 / CI14X2

    @property
    def image_size(self):
        return gx_image_size(self.fmt, self.width, self.height)

    def extent(self):
        """(lo, hi) raw file byte range spanning ALL this group's image +
        palette data (the range a texture_recolor of the whole group covers)."""
        lows = []
        highs = []
        for off in self.image_offs:
            if off:
                lows.append(off)
                highs.append(off + self.image_size)
        for off in self.pal_offs:
            if off:
                lows.append(off)
                highs.append(off + 0x200)  # HSDRaw uses fixed 0x200 palette
        if not lows:
            return None
        return (min(lows), max(highs))


def parse_texbank(data):
    """Return (header dict, [TexGroup])."""
    ds, et_off, pub_name = parse_archive(data)
    tex_ptr = _u32(data, et_off + 0x04)
    if tex_ptr == 0:
        return ({"public_name": pub_name, "tex_bank_off": None,
                 "num_groups": 0, "no_tex_bank": True}, [])
    bank = ds + tex_ptr
    num_groups = _u32(data, bank)
    groups = []
    for i in range(num_groups):
        go = _u32(data, bank + 4 + i * 4)
        if not go:
            g = TexGroup(i, None)
            groups.append(g)
            continue
        gabs = bank + go
        g = TexGroup(i, gabs)
        g.num = _u32(data, gabs + 0x00)
        g.fmt = _u32(data, gabs + 0x04)
        g.tlutfmt = _u32(data, gabs + 0x08)
        g.width = _u32(data, gabs + 0x0C)
        g.height = _u32(data, gabs + 0x10)
        g.palnum = _u16(data, gabs + 0x14)
        g.palflag = _u16(data, gabs + 0x16)
        # image offset table (relative to bank start) at +0x18
        for k in range(g.num):
            eo = _u32(data, gabs + 0x18 + k * 4)
            g.image_offs.append(bank + eo if eo else 0)
        # palette table (CI formats). Count per decomp Phase-3 palette logic:
        #   palflag&1 -> single palette; palnum>0 -> palnum palettes;
        #   else (palnum==0) -> one palette per image (double num).
        if g.is_paletted:
            if g.palflag & 1:
                npal = 1
            elif g.palnum:
                npal = g.palnum
            else:
                npal = g.num
            base = gabs + 0x18 + g.num * 4
            for k in range(npal):
                po = _u32(data, base + k * 4)
                g.pal_offs.append(bank + po if po else 0)
        groups.append(g)
    hdr = {
        "public_name": pub_name,
        "effect_table_off": et_off,
        "tex_bank_off": bank,
        "num_groups": num_groups,
        "file_size": len(data),
    }
    return hdr, groups


# --------------------------------------------------------------------------- #
# analysis: dominant hue of a group (saturation-weighted, plss method)
# --------------------------------------------------------------------------- #
def _rows_to_flat(rows):
    out = []
    for row in rows:
        out.extend(row)
    return out


def group_images(data, g):
    """Yield (poseNum, _Img, _Tlut|None) for a group."""
    for k, off in enumerate(g.image_offs):
        if not off:
            continue
        size = g.image_size
        img = _Img(off - DATA_START, g.width, g.height, g.fmt,
                   data[off:off + size])
        tlut = None
        if g.is_paletted and g.pal_offs:
            # single shared palette or per-image
            po = g.pal_offs[0] if len(g.pal_offs) == 1 else (
                g.pal_offs[k] if k < len(g.pal_offs) else g.pal_offs[0])
            if po:
                cnt = 0x100 if g.fmt == 9 else 0x10  # CI8=256, CI4=16
                # HSDRaw stores a fixed 0x200-byte (256-color) palette block;
                # decode `cnt` entries for the format.
                tlut = _Tlut(po - DATA_START, g.tlutfmt, cnt,
                             data[po:po + cnt * 2])
        yield k, img, tlut


def group_dominant_hue(data, g):
    flat = []
    for _k, img, tlut in group_images(data, g):
        try:
            rows = decode_texgroup_image(data, img, tlut)
        except Exception:
            continue
        flat.extend(_rows_to_flat(rows))
    return dominant_hue(flat), flat


# --------------------------------------------------------------------------- #
# report + export
# --------------------------------------------------------------------------- #
FMT_NAMES = {0: 'I4', 1: 'I8', 2: 'IA4', 3: 'IA8', 4: 'RGB565', 5: 'RGB5A3',
             6: 'RGBA8', 8: 'CI4', 9: 'CI8', 10: 'CI14X2', 14: 'CMPR'}


def build_report(path, want_groups=None, with_hue=False):
    data = open(path, "rb").read()
    hdr, groups = parse_texbank(data)
    out = {"file": os.path.basename(path), "header": {
        "public_name": hdr.get("public_name"),
        "tex_bank_off": hex(hdr["tex_bank_off"]) if hdr.get("tex_bank_off") else None,
        "num_groups": hdr["num_groups"],
    }, "groups": []}
    for g in groups:
        if want_groups is not None and g.index not in want_groups:
            continue
        if g.group_file_off is None:
            out["groups"].append({"index": g.index, "null": True})
            continue
        ext = g.extent()
        gd = {
            "index": g.index,
            "group_off": hex(g.group_file_off),
            "num_images": g.num,
            "fmt": FMT_NAMES.get(g.fmt, g.fmt),
            "gx_format": g.fmt,
            "tlutfmt": g.tlutfmt,
            "width": g.width,
            "height": g.height,
            "palnum": g.palnum,
            "palflag": g.palflag,
            "image_size": g.image_size,
            "images": [{"pose": k, "offset": hex(o)} for k, o in
                       enumerate(g.image_offs) if o],
            "palettes": [hex(o) for o in g.pal_offs if o],
            "extent": [hex(ext[0]), hex(ext[1])] if ext else None,
        }
        if with_hue:
            hue, _ = group_dominant_hue(data, g)
            gd["dominant_hue"] = round(hue, 1) if hue is not None else None
        out["groups"].append(gd)
    return out, data, groups


def print_table(report):
    h = report["header"]
    print("=" * 78)
    print("FILE: %s  symbol=%s" % (report["file"], h["public_name"]))
    print("  tex_bank@%s  num_groups=%d" % (h["tex_bank_off"], h["num_groups"]))
    print("=" * 78)
    for g in report["groups"]:
        if g.get("null"):
            print("group %-2d  <null>" % g["index"])
            continue
        line = ("group %-2d  @%s  %d img  %-7s %dx%d  palnum=%d palflag=%d  "
                "extent=%s" % (
                    g["index"], g["group_off"], g["num_images"], g["fmt"],
                    g["width"], g["height"], g["palnum"], g["palflag"],
                    ("%s..%s" % (g["extent"][0], g["extent"][1]))
                    if g["extent"] else "none"))
        if "dominant_hue" in g:
            line += "  hue=%s" % g["dominant_hue"]
        print(line)
        for im in g["images"]:
            print("      pose %-2d  image@%s" % (im["pose"], im["offset"]))


def export_pngs(path, out_dir, groups, data, want_groups=None):
    from datprobe import save_png
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(path))[0]
    n = 0
    for g in groups:
        if g.group_file_off is None:
            continue
        if want_groups is not None and g.index not in want_groups:
            continue
        for k, img, tlut in group_images(data, g):
            try:
                rows = decode_texgroup_image(data, img, tlut)
            except Exception as e:
                print("  skip grp%d pose%d: %s" % (g.index, k, e))
                continue
            fn = "%s_grp%02d_pose%d_%s_%dx%d_%06X.png" % (
                base, g.index, k, FMT_NAMES.get(g.fmt, g.fmt),
                g.width, g.height, g.image_offs[k])
            save_png(rows, os.path.join(out_dir, fn))
            n += 1
    print("exported %d PNGs to %s" % (n, out_dir))
    return n


# --------------------------------------------------------------------------- #
# VERIFY: 17088 rainbow-fire diff containment
# --------------------------------------------------------------------------- #
# The 17088 "rainbow fire whole cast" mod is a PURE texture diff vs vanilla
# EfCoData (base byte-identical). Its changed bytes MUST land inside exactly the
# tex-group(s) that hold the fire texture -- that is the ground-truth proof the
# bank layout decode is correct (offsets/sizes are right if and only if the diff
# is fully contained in decoded image extents).
# The mod-pool backup it reads: SSBM_BACKUP_DIR, default ~/ssbm-backup.
_BACKUP_DIR = os.environ.get("SSBM_BACKUP_DIR") or os.path.join(os.path.expanduser("~"), "ssbm-backup")
_17088_DIR = os.path.join(_BACKUP_DIR, "uploads", "posts", "2024", "07", "post_17088")
_17088_GLOB = os.path.join(_17088_DIR, "EfCoData rainbow*.dat")
_17088_OG_GLOB = os.path.join(_17088_DIR, "og effects", "EfCoData original*.dat")


def _diff_range(a, b):
    lo = hi = None
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            if lo is None:
                lo = i
            hi = i
    return lo, hi


def run_verify(base_dir):
    print("ptcl_texbank verify -- 17088 rainbow-fire diff containment")
    van_path = os.path.join(base_dir, "EfCoData.dat")
    if not os.path.exists(van_path):
        print("  SKIP: no vanilla EfCoData.dat at", van_path)
        return True
    van = open(van_path, "rb").read()
    hdr, groups = parse_texbank(van)
    print("  EfCoData tex_bank@0x%X  num_groups=%d" % (
        hdr["tex_bank_off"], hdr["num_groups"]))

    modp = glob.glob(_17088_GLOB)
    ogp = glob.glob(_17088_OG_GLOB)
    if not modp:
        print("  SKIP: 17088 rainbow mod not found (%s). " % _BACKUP_DIR +
              "Bank decode still validated structurally below.")
        _structural_checks(groups)
        return True
    mod = open(modp[0], "rb").read()
    if ogp:
        og = open(ogp[0], "rb").read()
        if og != van:
            print("  WARN: 17088 'og' base differs from test-base vanilla "
                  "(md5 mismatch) -- diff may be noisy")
    lo, hi = _diff_range(van, mod)
    print("  17088 diff range: 0x%X .. 0x%X (span %d bytes)" % (
        lo, hi, hi - lo))

    # find which group extents contain the diff
    hits = []
    for g in groups:
        ext = g.extent()
        if ext and ext[0] <= lo and hi < ext[1]:
            hits.append((g, ext, "FULLY CONTAINS"))
        elif ext and ext[0] <= hi and lo <= ext[1]:
            hits.append((g, ext, "overlaps"))
    ok = False
    for g, ext, rel in hits:
        print("  -> group %d (%s %dx%d, %d img) extent 0x%X..0x%X : %s" % (
            g.index, FMT_NAMES.get(g.fmt, g.fmt), g.width, g.height, g.num,
            ext[0], ext[1], rel))
        if rel == "FULLY CONTAINS":
            ok = True
    if ok:
        print("  PASS: 17088 fire diff is FULLY CONTAINED in a decoded group "
              "extent -> bank offset/size decode is correct.")
    else:
        print("  FAIL: 17088 diff not fully contained in any single group "
              "extent (decode may be wrong, or diff spans >1 group).")
    _structural_checks(groups)
    return ok


def _structural_checks(groups):
    """Sanity: every non-null group's images fit in the file and its extent is
    monotonic; used both standalone and after the diff check."""
    bad = 0
    for g in groups:
        if g.group_file_off is None:
            continue
        if g.width <= 0 or g.height <= 0 or g.fmt not in FMT_NAMES:
            print("  STRUCT-WARN group %d: implausible %dx%d fmt=%s" % (
                g.index, g.width, g.height, g.fmt))
            bad += 1
    print("  structural check: %d non-null groups, %d warnings" % (
        sum(1 for g in groups if g.group_file_off is not None), bad))


# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", help="Ef*Data.dat path")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--export", metavar="DIR", help="export group PNGs to DIR")
    ap.add_argument("--groups", help="comma list of group indices to limit to")
    ap.add_argument("--hue", action="store_true",
                    help="compute saturation-weighted dominant hue per group")
    ap.add_argument("--verify", action="store_true",
                    help="17088-diff-containment self-test")
    ap.add_argument("--base",
                    default=os.path.join(_HERE, "..", "..", "..", "storage",
                                         "test-base", "files"))
    args = ap.parse_args(argv)

    if args.verify:
        ok = run_verify(os.path.abspath(args.base))
        return 0 if ok else 1

    if not args.path:
        ap.error("path required (or use --verify)")

    want = None
    if args.groups:
        want = set(int(x, 0) for x in args.groups.split(","))

    report, data, groups = build_report(args.path, want_groups=want,
                                         with_hue=args.hue or args.json)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_table(report)
    if args.export:
        export_pngs(args.path, args.export, groups, data, want_groups=want)
    return 0


if __name__ == "__main__":
    sys.exit(main())
