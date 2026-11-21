"""
texture_region extras -- whole-texture replacement for effects whose editable
data is one raw GX image region inside a DAT, not color operands.

First consumer: `common_shield` (research/docs-research/effect-maps/common-shield.md).
The shield bubble is a 128x128 IA8 texture at EfCoData.dat 0x104320 -- IA8 is
intensity+alpha with NO hue (the per-port red/blue/yellow/green tint is
engine-side), so a color-picker recolor is meaningless; community shield mods
are byte replacements of exactly this region. A texture_region mod therefore
stores a SOURCE (a full modded DAT from the website effect import path, or a
PNG encoded here) and install copies the region bytes into the target DAT.

Config shape (extra_types.py / extraTypes.js):
    "format": "texture_region",
    "texture_region": {
        "offset": "0x104320",   # vanilla file offset of the image data
        "size":   "0x8000",     # region byte length
        "width": 128, "height": 128,
        "gx_format": 3          # IA8 (the only decoder/encoder wired so far)
    }

Offset safety (docs/dev/EXTRAS_AUDIT.md "Offset safety: guard + relocation"):
a re-saved DAT can shift the image. Every read/write here locates the region
via the HSD_ImageDesc structs {u32 ptr, u16 w, u16 h, u32 fmt} that reference
it: scan for descs matching w/h/fmt, group by ptr, take the most-referenced
pointer (the shield image is referenced by 10 TObjs in vanilla; the only
other 128x128 IA8 image in EfCoData has 2 -- a >=3-referencer majority is
decisive). If no confident match is found the operation SKIPS LOUDLY rather
than writing at an unverified offset.
"""

import io
import logging
import struct
from collections import Counter
from pathlib import Path

import file_retry
from shared.rendering.gx_texels import tile_iter

logger = logging.getLogger(__name__)

DAT_HEADER = 0x20   # data-section pointers are file offset - 0x20
MIN_REFS = 3        # confident-majority threshold for the ImageDesc scan


class TextureRegionError(RuntimeError):
    pass


def parse_cfg(type_config):
    """Normalize the config's texture_region dict (hex-string tolerant)."""
    raw = type_config.get('texture_region')
    if not raw:
        raise TextureRegionError("config has no 'texture_region' dict")

    def _i(v):
        return v if isinstance(v, int) else int(str(v), 0)

    return {
        'offset': _i(raw['offset']),
        'size': _i(raw['size']),
        'width': _i(raw['width']),
        'height': _i(raw['height']),
        'gx_format': _i(raw.get('gx_format', 3)),
    }


def locate_region(data, cfg):
    """Find the region's file offset in `data` (bytes of a whole DAT).

    Fast path: the vanilla-shaped check -- an ImageDesc referencing the
    config offset exists. Otherwise scan for {w,h,fmt} ImageDescs and take
    the most-referenced pointer (>= MIN_REFS). Returns the file offset.
    """
    sig = struct.pack('>HHI', cfg['width'], cfg['height'], cfg['gx_format'])
    ptrs = Counter()
    i = 0
    while True:
        i = data.find(sig, i)
        if i < 0:
            break
        if i >= 4 and (i % 4) == 0:
            ptr, = struct.unpack('>I', data[i - 4:i])
            if 0 < ptr <= len(data) - DAT_HEADER - cfg['size']:
                ptrs[ptr] += 1
        i += 1

    vanilla_ptr = cfg['offset'] - DAT_HEADER
    if ptrs.get(vanilla_ptr, 0) >= MIN_REFS:
        return cfg['offset']
    if ptrs:
        ptr, refs = ptrs.most_common(1)[0]
        if refs >= MIN_REFS:
            off = ptr + DAT_HEADER
            if off != cfg['offset']:
                logger.info(f"[texture_region] relocated region: config "
                            f"0x{cfg['offset']:X} -> 0x{off:X} ({refs} refs)")
            return off
    raise TextureRegionError(
        f"no confident ImageDesc match for {cfg['width']}x{cfg['height']} "
        f"fmt {cfg['gx_format']} (candidates: "
        + (", ".join(f"0x{p + DAT_HEADER:X} x{n}" for p, n in ptrs.most_common(4)) or "none")
        + ") -- refusing to write at an unverified offset")


def read_region(dat_path, type_config):
    """Region bytes out of any DAT containing the texture (target project
    file, a stored mod DAT, or the vanilla reference)."""
    cfg = parse_cfg(type_config)
    data = Path(dat_path).read_bytes()
    off = locate_region(data, cfg)
    return data[off:off + cfg['size']]


def write_region(dat_path, type_config, region):
    """Write region bytes into the DAT at its located offset."""
    cfg = parse_cfg(type_config)
    if len(region) != cfg['size']:
        raise TextureRegionError(
            f"region is {len(region)} bytes, expected 0x{cfg['size']:X}")
    dat_path = Path(dat_path)
    data = dat_path.read_bytes()
    off = locate_region(data, cfg)
    with file_retry.retry_locked(open, dat_path, 'r+b') as f:
        f.seek(off)
        f.write(region)
    return off


def vanilla_region(type_config, target_file):
    """The vanilla region bytes, via the vanilla reference DAT (lazily
    extracted from the recorded vanilla ISO). None when unavailable."""
    from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
    ref = ensure_vanilla_ref(target_file)
    if not ref:
        return None
    try:
        return read_region(ref, type_config)
    except TextureRegionError as e:
        logger.warning(f"[texture_region] vanilla ref unusable: {e}")
        return None


# ---------------------------------------------------------------------------
# IA8 <-> PNG (GX 4x4-texel tiles, 2 bytes per texel: [alpha][intensity])
# ---------------------------------------------------------------------------

def _tiles(w, h):
    for x, y, _index in tile_iter(w, h, 4, 4):
        yield x, y


def region_to_png_bytes(region, type_config):
    """Decode the IA8 region to PNG bytes (grayscale + alpha)."""
    from PIL import Image
    cfg = parse_cfg(type_config)
    if cfg['gx_format'] != 3:
        raise TextureRegionError(f"unsupported gx_format {cfg['gx_format']}")
    img = Image.new('LA', (cfg['width'], cfg['height']))
    px = img.load()
    it = iter(_tiles(cfg['width'], cfg['height']))
    for i in range(0, cfg['size'], 2):
        x, y = next(it)
        px[x, y] = (region[i + 1], region[i])
    buf = io.BytesIO()
    img.convert('RGBA').save(buf, 'PNG')
    return buf.getvalue()


def png_to_region(png_bytes, type_config):
    """Encode an image to the IA8 region (resized to the config dimensions;
    color inputs are luminance-converted -- IA8 cannot carry hue)."""
    from PIL import Image
    cfg = parse_cfg(type_config)
    if cfg['gx_format'] != 3:
        raise TextureRegionError(f"unsupported gx_format {cfg['gx_format']}")
    img = Image.open(io.BytesIO(png_bytes)).convert('RGBA')
    if img.size != (cfg['width'], cfg['height']):
        img = img.resize((cfg['width'], cfg['height']), Image.LANCZOS)
    la = img.convert('LA')
    px = la.load()
    out = bytearray(cfg['size'])
    it = iter(_tiles(cfg['width'], cfg['height']))
    for i in range(0, cfg['size'], 2):
        x, y = next(it)
        inten, alpha = px[x, y]
        out[i] = alpha
        out[i + 1] = inten
    return bytes(out)


# ---------------------------------------------------------------------------
# mod-source resolution
# ---------------------------------------------------------------------------

def region_from_mod(storage_dir, found_mod, type_config):
    """Resolve a mod's stored source into region bytes.

    Sources (newest first):
    - `texture_file` (models/<id>.texreg): raw region bytes (PNG import path)
    - `model_file` ending .dat: a full modded DAT (website effect import path)
      -- the region is located inside it (relocation-aware, so re-saved
      community files still extract).
    """
    cfg = parse_cfg(type_config)
    tex_file = found_mod.get('texture_file')
    if tex_file:
        p = Path(storage_dir) / tex_file
        region = p.read_bytes()
        if len(region) != cfg['size']:
            raise TextureRegionError(
                f"stored region {p.name} is {len(region)} bytes, "
                f"expected 0x{cfg['size']:X}")
        return region
    model_file = found_mod.get('model_file')
    if model_file and str(model_file).lower().endswith('.dat'):
        return read_region(Path(storage_dir) / model_file, type_config)
    raise TextureRegionError(
        "mod has no texture_file or .dat model_file to read the region from")


# ---------------------------------------------------------------------------
# vault import (the extras import route and the unified /import/file
# dispatcher). The routes live in texture_routes.py.
# ---------------------------------------------------------------------------

import hashlib  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime  # noqa: E402

from core.metadata import load_metadata, save_metadata  # noqa: E402
from core.extra_lookup import get_storage_character  # noqa: E402

from . import helpers  # noqa: E402

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}


def import_texture_region_bytes(raw, suffix, character, extra_type, type_config, name=''):
    """Store an image (encoded into the region) or a full modded DAT as a
    texture_region mod. Returns the metadata entry. Raises TextureRegionError
    when a DAT's region cannot be located. Shared by the extras page route and
    the unified /import/file dispatcher."""
    storage_char = get_storage_character(character, extra_type)
    mod_id = f"{extra_type}_{uuid.uuid4().hex[:8]}"
    models_dir = helpers.STORAGE_PATH / storage_char / 'models'
    models_dir.mkdir(parents=True, exist_ok=True)

    stored = {}
    if suffix in IMAGE_EXTS:
        region = png_to_region(raw, type_config)
        (models_dir / f"{mod_id}.texreg").write_bytes(region)
        stored['texture_file'] = f"models/{mod_id}.texreg"
    else:
        # validate the region locates before storing (a wrong-file DAT
        # fails here instead of at install time)
        cfg = parse_cfg(type_config)
        off = locate_region(raw, cfg)
        region = raw[off:off + cfg['size']]
        (models_dir / f"{mod_id}.dat").write_bytes(raw)
        stored['model_file'] = f"models/{mod_id}.dat"

    # decoded-region preview so the mod card shows the actual texture
    try:
        preview = region_to_png_bytes(region, type_config)
        (models_dir / f"{mod_id}_preview.png").write_bytes(preview)
        stored['screenshot'] = f"models/{mod_id}_preview.png"
    except Exception as e:
        logger.warning(f"[texture_region] preview render failed: {e}")

    metadata = load_metadata(default={'characters': {}})
    chars = metadata.setdefault('characters', {})
    char_data = chars.setdefault(storage_char, {'skins': [], 'extras': {}})
    extras = char_data.setdefault('extras', {})
    mods = extras.setdefault(extra_type, [])
    mod = {
        'id': mod_id,
        'name': name or 'texture',
        'type': 'texture_region',
        'date_added': datetime.now().isoformat(),
        'source': 'uploaded',
        'file_hash': hashlib.md5(region).hexdigest(),
        **stored,
    }
    mods.append(mod)
    save_metadata(metadata)
    logger.info(f"[OK] Imported texture_region mod '{mod['name']}' "
                f"({extra_type}) for {storage_char}")
    return mod
