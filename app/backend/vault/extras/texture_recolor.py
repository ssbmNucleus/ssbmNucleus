"""
texture_recolor extras -- color-picker-driven raw-texel hue recolors.

Distinct from `type: "texture"` (textures.py): that format shifts a texture
via the HSDRawViewer CLI export/shift-hue/import round-trip, needs a JOBJ
node path, and its hue slider lives nested inside a sibling color editor.
This format is for textures that do NOT sit on a JOBJ->DObj->MObj material
tree reachable by the CLI (e.g. Samus's charge-ball, an effect/particle
texture-graphics block embedded in the fighter file) -- it patches the raw
GX texel bytes directly, in place, at a fixed file offset. It also presents
as a plain single ColorPicker in the UI (its own extras card), not a hue
slider: apply = per-texel hue ROTATE by (target_hue - vanilla_dominant_hue),
preserving each texel's saturation/value/alpha (HSV, matching
shared/rendering/stock_gen.py's precedent), then re-encode in the texture's original
GX format. Grays/whites stay neutral; gradients/shading survive.

Two texture-block shapes, both under the config's "texture" key:

Direct formats (RGB5A3/RGB565) -- single image, recolor the texel bytes
themselves (Samus charge_ball, task #12):
    "texture": {"offset": 0x36840, "width": 64, "height": 64,
                 "gx_format": 5}   # 5 = RGB5A3

CI4/CI8 palette formats (task #14, EfCoData common_fire/common_flash) --
recolor is a PALETTE hue-rotate: each image's pixel INDICES are untouched,
only its TLUT (color lookup table) entries are rotated. One texGroup can
carry several images/poses each with its own palette (grp9 has 10), so the
config's "texture" key becomes a LIST of {offset, palette} pairs under
"images", plus a shared width/height/gx_format/palette_format:
    "texture": {
        "gx_format": 9, "width": 64, "height": 64,   # 9 = CI8 (8 = CI4)
        "images": [
            {"offset": "0x8CB40", "palette": "0x96B40"},
            {"offset": "0x8DB40", "palette": "0x96D40"},
            ...
        ],
        "palette_format": 2   # RGB5A3 TLUT (see ptcl_texbank.py tlutfmt)
    }
Offsets in "images" may be given as hex strings (JSON-friendly, matches
effect-texbank.md) or ints; both are normalized at load.

Config shape (extra_types.py entry, direct-format example):
    {
        "id": "charge_ball",
        "format": "texture_recolor",
        "target_file": "PlSs.dat",
        "texture": {"offset": 0x36840, "width": 64, "height": 64,
                     "gx_format": 5},   # 5 = RGB5A3
        "vanilla_dominant_hue": 239,   # recorded reference; apply always
                                        # LIVE-measures the vanilla texture's
                                        # actual hue unless a caller pins it
                                        # (see apply_texture_recolor)
        "vanilla": {"color1": "0004FF"},   # a representative vanilla swatch
        "properties": [{"id": "color1", "name": "...", "format": "RGB"}]
    }

Restore-to-vanilla does NOT keep a copy of the texel/palette bytes in the
JSON config (too big for a hand-maintained offsets dict) -- it re-reads the
untouched bytes straight from the vanilla reference DAT in
storage/test-base/files/<target_file>, the same "vanilla bytes live on disk,
not in config" pattern the texture.py CLI path uses for its vanilla PNG
cache. This means restore requires the test-base vanilla DAT to be present
(mirrors the CLI path's requirement that a vanilla texture be exportable).

No routes: the /api/mex/storage/extras/texture-recolor/* endpoints live in
texture_routes.py.
"""

import colorsys
import logging
import struct

import file_retry
from shared.rendering.gx_texels import (decode_palette, dominant_hue, enc_rgb565, enc_rgb5a3,
                               encode_palette, recolor_texels, rgb565, rgb5a3, tile_iter)

logger = logging.getLogger(__name__)

# NOTE on offsets: plss_ball_probe.py / shared.rendering.datprobe address images by
# DATA-SECTION-relative offset (add the 0x20 DAT header to get a raw file
# offset). The MAP spec's cited offsets (e.g. 0x36840) are RAW FILE offsets
# (as seen with a hex editor / HSDRawViewer), so texture_recolor configs
# store the RAW file offset directly and this module's _region() uses it
# as-is (no header adjustment) -- it seeks/reads dat_path directly, it does
# not go through DatFile's data-section-relative addressing.


def _is_palette_cfg(tex_cfg):
    """True for the CI4/CI8 multi-image {"images": [...]} shape (task #14);
    False for the original single-image direct-format shape (charge_ball)."""
    return 'images' in tex_cfg


def _as_int(v):
    """Normalize a config offset that may be a hex string ("0x8CB40") or an
    int (0x8CB40) -- effect-texbank.md's tables are written as hex strings,
    the original charge_ball config uses raw Python ints; both must work."""
    return int(v, 16) if isinstance(v, str) else v


def _region(tex_cfg):
    """(start, end) raw file-byte range of the texture's pixel data.
    Direct-format (single image) only -- palette-format configs have no
    single region and are handled by the _images()/_palette_region() paths
    below instead."""
    from shared.rendering.datprobe import gx_image_size
    start = tex_cfg['offset']
    size = gx_image_size(tex_cfg['gx_format'], tex_cfg['width'], tex_cfg['height'])
    return start, start + size


def _images(tex_cfg):
    """Normalize a palette-format config's "images" list to
    [(image_offset, palette_offset), ...] with int offsets."""
    return [(_as_int(im['offset']), _as_int(im['palette']))
            for im in tex_cfg['images']]


def _palette_region(tex_cfg, pal_offset):
    """(start, end) raw file-byte range of one image's TLUT. HSDRaw stores a
    fixed 0x200-byte (256-entry) palette block regardless of the image's
    actual format bit-depth (matches ptcl_texbank.py's TexGroup.extent()),
    so CI4 (16 live entries) and CI8 (256 live entries) both use the same
    0x200 stride -- only the live entry COUNT decoded/encoded differs."""
    return pal_offset, pal_offset + 0x200


# --------------------------------------------------------------------------- #
# GX decode/encode -- the texel codecs live in shared/rendering/gx_texels.py (promoted
# from shared/rendering/plss_ball_probe.py, the working, in-game-verified prototype).
# The block codecs below handle the direct (non-palette) formats the
# charge_ball texture uses.
# --------------------------------------------------------------------------- #
_DECODERS = {5: rgb5a3, 4: rgb565}
_ENCODERS = {5: enc_rgb5a3, 4: enc_rgb565}
_TILE = {5: (4, 4), 4: (4, 4)}


def decode_texel_block(raw, w, h, fmt):
    """raw: the exact GX pixel byte block (no DAT header). -> [RGBA...]."""
    if fmt not in _DECODERS:
        raise ValueError(f'texture_recolor: unsupported GX format {fmt}')
    decode = _DECODERS[fmt]
    bw, bh = _TILE[fmt]
    px = [(0, 0, 0, 0)] * (w * h)
    for x, y, i in tile_iter(w, h, bw, bh):
        if x >= w or y >= h:
            continue
        v = struct.unpack_from('>H', raw, i * 2)[0]
        px[y * w + x] = decode(v)
    return px


def encode_texel_block(px, w, h, fmt):
    """[RGBA...] -> the exact GX pixel byte block (no DAT header)."""
    if fmt not in _ENCODERS:
        raise ValueError(f'texture_recolor: unsupported GX format {fmt}')
    encode = _ENCODERS[fmt]
    bw, bh = _TILE[fmt]
    from shared.rendering.datprobe import gx_image_size
    buf = bytearray(gx_image_size(fmt, w, h))
    for x, y, i in tile_iter(w, h, bw, bh):
        r, g, b, a = px[y * w + x] if (x < w and y < h) else (0, 0, 0, 0)
        struct.pack_into('>H', buf, i * 2, encode(r, g, b, a))
    return bytes(buf)


# --------------------------------------------------------------------------- #
# CI4/CI8 palette (TLUT) recolor -- decode_palette/encode_palette (shared/rendering/
# gx_texels.py, promoted from plss_ball_probe's in-game-verified prototype).
# CI recolor rotates the PALETTE entries, not the image's pixel indices -- the
# indices select which palette slot a texel uses and are untouched by a
# color-only recolor.
# --------------------------------------------------------------------------- #
_PALETTE_ENTRY_COUNT = {8: 0x10, 9: 0x100}  # CI4 -> 16 live entries, CI8 -> 256


def hex_to_hue(color_hex):
    r = int(color_hex[0:2], 16)
    g = int(color_hex[2:4], 16)
    b = int(color_hex[4:6], 16)
    h, _l, _s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return h * 360


# --------------------------------------------------------------------------- #
# high-level ops used by colors.py + extras_audit.py
# --------------------------------------------------------------------------- #
def _pal_entry_count(tex_cfg):
    return _PALETTE_ENTRY_COUNT.get(tex_cfg['gx_format'], 0x100)


def read_current_dominant_color(dat_path, tex_cfg):
    """Read the current texel block (direct formats) or the first image's
    palette (CI formats) and return the dominant hue re-expressed as an RGB
    hex swatch (full saturation/value) -- what the ColorPicker should show
    as "current color"."""
    raw = dat_path.read_bytes() if hasattr(dat_path, 'read_bytes') else open(dat_path, 'rb').read()
    if _is_palette_cfg(tex_cfg):
        images = _images(tex_cfg)
        count = _pal_entry_count(tex_cfg)
        px = []
        for _img_off, pal_off in images:
            pstart, pend = _palette_region(tex_cfg, pal_off)
            px += decode_palette(raw[pstart:pend], count, tex_cfg['palette_format'])
    else:
        start, end = _region(tex_cfg)
        block = raw[start:end]
        px = decode_texel_block(block, tex_cfg['width'], tex_cfg['height'], tex_cfg['gx_format'])
    hue = dominant_hue(px)
    if hue is None:
        return None
    r, g, b = colorsys.hls_to_rgb(hue / 360, 0.5, 1.0)
    return f'{round(r*255):02X}{round(g*255):02X}{round(b*255):02X}'


def recolor_spans(tex_cfg):
    """(start, length) of every byte span an install rewrites and restore
    puts back: the direct texel block, or each image's live palette entries
    (CI formats; the index bytes are never touched)."""
    if _is_palette_cfg(tex_cfg):
        live = _pal_entry_count(tex_cfg) * 2
        return [(pal_off, live) for _img_off, pal_off in _images(tex_cfg)]
    start, end = _region(tex_cfg)
    return [(start, end - start)]


def _vanilla_bytes(tex_cfg):
    """Read the raw vanilla DAT bytes from storage/test-base/files/ (never
    from dat_path, which may already carry a previous install's recolor --
    always shifting from a fresh vanilla read is what keeps repeated
    installs from compounding drift, matching textures.py's
    apply_texture_extra_hue pattern of re-deriving from a vanilla reference
    every time). User installs never had a test-base folder, so a missing
    reference is extracted from the recorded vanilla ISO on first use
    (vanilla_refs.py)."""
    from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
    target_file = tex_cfg['_target_file']
    vanilla_dat = ensure_vanilla_ref(target_file)
    if vanilla_dat is None:
        raise RuntimeError(
            f"no vanilla reference for {target_file} and no vanilla ISO "
            f"available to extract it from -- set your vanilla Melee ISO in "
            f"Settings (or re-run first-run setup), then try again")
    return vanilla_dat.read_bytes()


def _vanilla_texels(tex_cfg):
    """Decode the (direct-format) texel block from the vanilla reference DAT."""
    van = _vanilla_bytes(tex_cfg)
    start, end = _region(tex_cfg)
    return decode_texel_block(van[start:end], tex_cfg['width'], tex_cfg['height'], tex_cfg['gx_format'])


def _vanilla_palettes(tex_cfg):
    """Decode every image's palette from the vanilla reference DAT.
    Returns [[RGBA...], ...] in "images" order."""
    van = _vanilla_bytes(tex_cfg)
    count = _pal_entry_count(tex_cfg)
    out = []
    for _img_off, pal_off in _images(tex_cfg):
        pstart, pend = _palette_region(tex_cfg, pal_off)
        out.append(decode_palette(van[pstart:pend], count, tex_cfg['palette_format']))
    return out


def apply_texture_recolor(dat_path, tex_cfg, target_hex, vanilla_hue=None):
    """Patch the texture in dat_path IN PLACE, rotating every VANILLA
    texel's (direct format) or palette entry's (CI format) hue by
    (target_hue - vanilla_dominant_hue) and writing the result. Byte-size is
    unchanged; for CI formats the image's pixel INDEX bytes are never
    touched -- only the palette (TLUT) entries move.

    The shift always starts from the vanilla reference (see
    _vanilla_texels/_vanilla_palettes), NOT from dat_path's current bytes --
    dat_path may already carry a previous mod's recolor, and shifting from
    an already-shifted state would compound rounding error across repeated
    installs. `vanilla_hue`, if given, overrides the LIVE-measured vanilla
    dominant hue (the config's recorded constant is a documented reference
    value; the live measurement is what the verified plss_ball_probe.py
    prototype actually uses and is what keeps byte-for-byte parity with it --
    prefer leaving vanilla_hue=None unless a caller has a specific reason to
    pin the shift to the recorded constant).
    """
    target_hue = hex_to_hue(target_hex)

    if _is_palette_cfg(tex_cfg):
        pals = _vanilla_palettes(tex_cfg)
        all_px = [px for pal in pals for px in pal]
        van_hue = vanilla_hue if vanilla_hue is not None else dominant_hue(all_px)
        if van_hue is None:
            van_hue = tex_cfg.get('vanilla_dominant_hue', 0)
        shift = target_hue - van_hue

        images = _images(tex_cfg)
        with file_retry.retry_locked(open, dat_path, 'r+b') as f:
            for (_img_off, pal_off), pal in zip(images, pals):
                new_pal = recolor_texels(pal, shift)
                pbytes = encode_palette(new_pal, tex_cfg['palette_format'])
                f.seek(pal_off)
                f.write(pbytes)
        logger.info(f"[OK] texture_recolor patched {len(images)} palette(s) in {dat_path} "
                    f"(target={target_hex} vanilla_hue={van_hue:.1f} shift={shift:.1f})")
        return

    start, end = _region(tex_cfg)
    px = _vanilla_texels(tex_cfg)
    van_hue = vanilla_hue if vanilla_hue is not None else dominant_hue(px)
    if van_hue is None:
        van_hue = tex_cfg.get('vanilla_dominant_hue', 0)
    shift = target_hue - van_hue

    new_px = recolor_texels(px, shift)
    new_block = encode_texel_block(new_px, tex_cfg['width'], tex_cfg['height'], tex_cfg['gx_format'])
    with file_retry.retry_locked(open, dat_path, 'r+b') as f:
        f.seek(start)
        f.write(new_block)
    logger.info(f"[OK] texture_recolor patched 0x{start:X}-0x{end:X} in {dat_path} "
                f"(target={target_hex} vanilla_hue={van_hue:.1f} shift={shift:.1f})")


def restore_texture_recolor(dat_path, tex_cfg):
    """Restore the texture (or, for CI formats, every image's palette) to
    vanilla bytes, read fresh from the vanilla reference DAT in
    storage/test-base/files/. This mirrors how other extras' vanilla
    reference data lives on disk, not in the JSON config -- the texel/
    palette bytes are too big to hand-maintain as a config literal, and
    re-deriving them by "rotating back" would compound rounding error across
    repeated installs (this module's HLS round-trip is lossy at RGB5A3's
    4/5-bit precision). Reading the untouched vanilla bytes is the robust,
    exact option.
    """
    van = _vanilla_bytes(tex_cfg)

    if _is_palette_cfg(tex_cfg):
        count = _pal_entry_count(tex_cfg)
        images = _images(tex_cfg)
        with file_retry.retry_locked(open, dat_path, 'r+b') as f:
            for _img_off, pal_off in images:
                pstart, pend = _palette_region(tex_cfg, pal_off)
                # only re-write the live entry span (count*2 bytes), not the
                # full fixed 0x200 block -- matches what apply/encode_palette
                # writes and avoids touching any trailing bytes other data
                # might share the block with.
                nbytes = count * 2
                f.seek(pstart)
                f.write(van[pstart:pstart + nbytes])
        logger.info(f"[OK] texture_recolor restored {len(images)} vanilla palette(s) in {dat_path}")
        return

    start, end = _region(tex_cfg)
    vanilla_block = van[start:end]
    with file_retry.retry_locked(open, dat_path, 'r+b') as f:
        f.seek(start)
        f.write(vanilla_block)
    logger.info(f"[OK] texture_recolor restored vanilla bytes 0x{start:X}-0x{end:X} in {dat_path}")
