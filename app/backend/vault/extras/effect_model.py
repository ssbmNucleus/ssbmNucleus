"""effect_model extras -- image/PNG-based effect models (Fox/Falco image shines).

The third extras format, alongside color operands (`shine_gradient`,
`apply_hex_patches`) and whole-texture byte replacement (`texture_region`).

WHY A THIRD FORMAT
------------------
Fox/Falco's shine is `effFoxDataTable` model 0 of `EfFxData.dat`: a 43-vertex
triangle FAN whose per-vertex RGBA6 colors ARE the two-color gradient the
`shine_gradient` extra patches in place (that extra's `hex` region
0x1C2A0-0x1C350 is literally this display list). An "image shine" -- the
community mods with a picture inside the hexagon (NERV, Honeycomb, Trollface,
Pokeball, ...) -- is a structurally DIFFERENT thing: the hexagon's DObj is
replaced by a two-triangle textured quad, so there are no color operands to
read or write and every offset-based read returns garbage.

Measured 2026-09-09 against the vanilla file and the real website mods
(research/docs-research/effect-maps/fox-falco-image-shine.md): every one of those mods
is the SAME edit. Model 0's

    JObj(root, scale 1) -> JObj(child, BILLBOARD) -> DObj -> MObj + POBJ

keeps its root JObj, its child JObj, and its AnimJoint / MatAnimJoint /
ShapeAnimJoint byte-identical to vanilla (the shine's expanding pop is
AnimJoint scale tracks 8/9/10, which override the child JObj's static scale --
that is why the mods can leave it at 1.0). ONLY the child JObj's `dobj`
pointer moves, to a new DObj carrying a textured quad:

    MObj  rendermode 0x40000010 (TEX0), Mat 7F7F7FFF/FFFFFFFF/FFFFFFFF
    TObj  texgensrc 4 (TEX0), wrap REPEAT/REPEAT, flags 0x00340010 -> ImageDesc
    POBJ  3 attributes (POS s16 scale 11 / NRM / TEX0) plus a 32-byte display
          list: two GX_DRAW_TRIANGLES over a +-8.0 quad, u = (x+8)/16,
          v = (8-y)/16

So this module does exactly that edit and nothing else: it APPENDS the new
blocks and repoints one pointer. Every other effect in the file (lasers,
firefox, blaster flash, the sparkle particles, the startup flash, and the
hexagon's own gradient bytes) is left byte-for-byte alone -- an image shine
and a custom sparkle color can coexist, and reverting brings the gradient
back untouched.

REVERSIBILITY (why the file does not grow without bound)
--------------------------------------------------------
An HSD archive is pointer-walked, so appending is easy but removing is not.
Every append this module makes starts with a 0x40-byte `NUCSHINE` header
recording what was overwritten. `revert()` finds that header, truncates the
data section back to it, drops the relocation entries inside it, and restores
the child JObj's `dobj` / `flags`. Install therefore always reverts first: the
file after installing image shine A, then B, then A again is byte-identical to
the file after installing A once. The header itself is referenced by no
pointer, which an HSD loader ignores.

CONFIG SHAPE (extra_types.py)
-----------------------------
    "image_model": {
        "root_index": 0,       # which archive root holds the model table
        "model_index": 0,      # SBM_EffectModel index (shine = 0)
        "width": 256, "height": 256,
        "gx_format": 5,        # RGB5A3 -- 15-bit color + 3-bit alpha
        "half_extent": 8.0     # quad corner in model units (vanilla hex ~8.27)
    }
"""

import io
import logging
import struct
import file_retry
import hashlib
import uuid
from pathlib import Path
from datetime import datetime
from core.metadata import load_metadata, save_metadata
from core.extra_lookup import get_storage_character
from vault.extras import helpers

logger = logging.getLogger(__name__)


DAT_HEADER = 0x20          # data-section offset + 0x20 == raw file offset
ALIGN_TEX = 0x20           # GX texture data and display lists: 32-byte aligned
MAGIC = b'NUCSHINE'
HEADER_SIZE = 0x40
HEADER_VERSION = 1

# JObj flag bits, from the decomp (sysdolphin/baselib/displayfunc.h and
# jobj.h). The textured child draws in the TEXEDGE pass, the vanilla
# vertex-colored hexagon in OPA -- and the ROOT_* bits on the model's ROOT
# JObj say which passes HSD_JObjDisp descends at all. Setting TEXEDGE on the
# child WITHOUT flipping the root's ROOT_OPA to ROOT_TEXEDGE renders nothing
# whatsoever (verified in-game 2026-09-09: shine simply vanished), which is
# exactly why every community image shine carries root flags 0x40000008 where
# vanilla has 0x10000008. The rest of each word is preserved.
JOBJ_OPA = 0x00040000
JOBJ_XLU = 0x00080000
JOBJ_TEXEDGE = 0x00100000
JOBJ_TRSP_MASK = JOBJ_OPA | JOBJ_XLU | JOBJ_TEXEDGE
JOBJ_ROOT_OPA = 1 << 28
JOBJ_ROOT_XLU = 1 << 29
JOBJ_ROOT_TEXEDGE = 1 << 30
JOBJ_ROOT_MASK = JOBJ_ROOT_OPA | JOBJ_ROOT_XLU | JOBJ_ROOT_TEXEDGE

# Measured constants of the community image-shine quad (module docstring).
MOBJ_RENDERMODE = 0x40000010
MAT_AMBIENT = 0x7F7F7FFF
MAT_DIFFUSE = 0xFFFFFFFF
MAT_SPECULAR = 0xFFFFFFFF
MAT_ALPHA = 1.0
MAT_SHININESS = 50.0
TOBJ_TEXGENSRC = 4            # GX_TG_TEX0
TOBJ_WRAP = 1                 # GX_REPEAT
TOBJ_FLAGS = 0x00340010
TOBJ_BLENDING = 1.0
TOBJ_MAGFILTER = 1            # GX_LINEAR
POS_SCALE_EXP = 11            # s16 / 2**11 == /2048
# The normal attribute's comp_type and its single normal byte, matching the
# shipped mods. Tested both ways in-game (2026-09-09): GX_S8/0x7F renders
# identically, so this is fidelity to the proven files, not a requirement.
NRM_COMP_TYPE = 0
# Static child-JObj scale. This one IS load-bearing: leaving vanilla's 0.422
# in place made the game assert in psdisp.c (psDispParticles, invalid texture
# format) and freeze the frame the shine drew, in-game 2026-09-09. Rebuilding
# with 1.0 -- the value every shipped image shine uses -- renders correctly.
# The AnimJoint's scale tracks drive the shine's pop over this value at
# runtime, so the size on screen is unchanged either way.
CHILD_JOBJ_SCALE = 1.0


class EffectModelError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

def parse_cfg(type_config):
    """Normalize the config's image_model dict (hex-string tolerant)."""
    raw = (type_config or {}).get('image_model')
    if not raw:
        raise EffectModelError("config has no 'image_model' dict")

    def _i(v):
        return v if isinstance(v, int) else int(str(v), 0)

    return {
        'root_index': _i(raw.get('root_index', 0)),
        'model_index': _i(raw.get('model_index', 0)),
        'width': _i(raw.get('width', 256)),
        'height': _i(raw.get('height', 256)),
        'gx_format': _i(raw.get('gx_format', 5)),
        'half_extent': float(raw.get('half_extent', 8.0)),
        'root_symbol': raw.get('root_symbol') or '',
    }


def supports(type_config):
    """True when this extra type declares an image_model capability."""
    return bool((type_config or {}).get('image_model'))


# ---------------------------------------------------------------------------
# HSD archive
# ---------------------------------------------------------------------------

class EffectDat:
    """A read/modify/write view of an HSD archive (Ef*Data.dat and friends).

    Only what this module needs: the data section, the relocation offsets,
    and the root/reference/string tables, carried through verbatim.
    """

    def __init__(self, raw):
        raw = bytes(raw)
        if len(raw) < DAT_HEADER:
            raise EffectModelError('not a DAT file (too short)')
        (self.file_size, self.data_size, self.reloc_count,
         self.root_count, self.ref_count) = struct.unpack_from('>IIIII', raw, 0)
        reloc_start = DAT_HEADER + self.data_size
        table_end = (reloc_start + self.reloc_count * 4
                     + (self.root_count + self.ref_count) * 8)
        if (self.data_size > len(raw) or table_end > len(raw)
                or self.file_size != len(raw)):
            raise EffectModelError(
                f'not a valid DAT archive (file is {len(raw)} bytes, header '
                f'says {self.file_size}, data 0x{self.data_size:X})')
        self.data = bytearray(raw[DAT_HEADER:DAT_HEADER + self.data_size])
        self.relocs = set(struct.unpack_from(
            f'>{self.reloc_count}I', raw, reloc_start))
        tbl = reloc_start + self.reloc_count * 4
        self.roots = [struct.unpack_from('>II', raw, tbl + i * 8)
                      for i in range(self.root_count)]
        self.refs = [struct.unpack_from('>II', raw, tbl + (self.root_count + i) * 8)
                     for i in range(self.ref_count)]
        self.strings = raw[tbl + (self.root_count + self.ref_count) * 8:]

    @classmethod
    def load(cls, path):
        return cls(Path(path).read_bytes())

    def root_name(self, index=0):
        """The root's symbol name, or '' when it cannot be read."""
        if index >= len(self.roots):
            return ''
        start = self.roots[index][1]
        end = self.strings.find(b'\0', start)
        if start < 0 or start >= len(self.strings) or end < 0:
            return ''
        return self.strings[start:end].decode('ascii', 'replace')

    # -- reads ---------------------------------------------------------------
    def u16(self, off):
        return struct.unpack_from('>H', self.data, off)[0]

    def u32(self, off):
        return struct.unpack_from('>I', self.data, off)[0]

    def f32(self, off):
        return struct.unpack_from('>f', self.data, off)[0]

    def ptr(self, off):
        """A pointer field: None when null, else the data-section offset.

        A RELOCATED field holding 0 is a real pointer to data offset 0 (real
        mods do this -- NERV's display list lives at offset 0), so the
        relocation set, not the value, decides nullness.
        """
        if off < 0 or off + 4 > len(self.data):
            return None
        v = self.u32(off)
        if v == 0 and off not in self.relocs:
            return None
        return v

    def set_ptr(self, off, value):
        struct.pack_into('>I', self.data, off, value)
        self.relocs.add(off)

    def clear_ptr(self, off):
        struct.pack_into('>I', self.data, off, 0)
        self.relocs.discard(off)

    # -- model table ---------------------------------------------------------
    def model_entries(self, root_index=0):
        """Data offsets of the SBM_EffectModel entries in a root's table.

        SBM_EffectTable: +0x00 Particles*, +0x04 TexGraphicBank*, then an
        inline array of 0x14-byte {f32 scale, JObj*, AnimJoint*,
        MatAnimJoint*, ShapeAnimJoint*} entries. The array length is implicit
        -- it ends where the JObj slot stops being a relocated pointer.
        """
        if root_index >= len(self.roots):
            raise EffectModelError(f'no root {root_index} in this archive')
        base = self.roots[root_index][0]
        out = []
        i = 0
        while True:
            entry = base + 8 + i * 0x14
            if entry + 0x14 > self.data_size or (entry + 4) not in self.relocs:
                break
            out.append(entry)
            i += 1
        return out

    def model_entry(self, cfg):
        entries = self.model_entries(cfg['root_index'])
        idx = cfg['model_index']
        if idx >= len(entries):
            raise EffectModelError(
                f'model {idx} not in this archive (found {len(entries)})')
        return entries[idx]

    # -- serialize -----------------------------------------------------------
    def to_bytes(self):
        data = bytearray(self.data)
        if len(data) % 4:
            data += b'\0' * (4 - len(data) % 4)
        relocs = sorted(r for r in self.relocs if r + 4 <= len(data))
        out = bytearray(b'\0' * DAT_HEADER)
        out += data
        for r in relocs:
            out += struct.pack('>I', r)
        for off, so in self.roots:
            out += struct.pack('>II', off, so)
        for off, so in self.refs:
            out += struct.pack('>II', off, so)
        out += self.strings
        struct.pack_into('>IIIII', out, 0, len(out), len(data), len(relocs),
                         len(self.roots), len(self.refs))
        return bytes(out)

    # -- append --------------------------------------------------------------
    def append(self, blob, align=4):
        """Append bytes at `align`; returns their data offset."""
        self.align_to(align)
        off = len(self.data)
        self.data += blob
        self.data_size = len(self.data)
        return off

    def align_to(self, align):
        self.data += b'\0' * ((-len(self.data)) % align)
        self.data_size = len(self.data)


# ---------------------------------------------------------------------------
# model walk
# ---------------------------------------------------------------------------

def jobj_nodes(dat, root):
    """Depth-first (child before next) JObj offsets under `root`."""
    out = []
    seen = set()
    stack = [root]
    while stack:
        j = stack.pop()
        if j is None or j in seen:
            continue
        seen.add(j)
        out.append(j)
        nxt = dat.ptr(j + 0x0C)
        child = dat.ptr(j + 0x08)
        if nxt is not None:
            stack.append(nxt)
        if child is not None:
            stack.append(child)
    return out


def find_display_jobj(dat, cfg):
    """The JObj in the model that carries the drawn DObj.

    Vanilla shine model 0 is root -> child with only the child holding a
    DObj, and the community image shines keep that shape. Ambiguity (more
    than one DObj-carrying node) is refused rather than guessed at.
    """
    entry = dat.model_entry(cfg)
    root = dat.ptr(entry + 4)
    if root is None:
        raise EffectModelError('model has no JObj')
    holders = [j for j in jobj_nodes(dat, root)
               if dat.ptr(j + 0x10) is not None]
    if len(holders) != 1:
        raise EffectModelError(
            f'expected exactly one DObj-carrying JObj in model '
            f'{cfg["model_index"]}, found {len(holders)}')
    return holders[0]


def read_texture(dat, cfg):
    """Info about the model's first material texture, or None if untextured.

    None is the VANILLA answer (the hexagon is vertex-colored and has no
    TObj), and is how a gradient shine is told apart from an image shine.
    """
    try:
        jobj = find_display_jobj(dat, cfg)
    except EffectModelError as e:
        logger.debug(f'[effect_model] no display JObj: {e}')
        return None
    dobj = dat.ptr(jobj + 0x10)
    while dobj is not None:
        mobj = dat.ptr(dobj + 0x08)
        if mobj is not None:
            tobj = dat.ptr(mobj + 0x08)
            while tobj is not None:
                img = dat.ptr(tobj + 0x4C)
                if img is not None:
                    tlut = dat.ptr(tobj + 0x50)
                    info = {
                        'tobj': tobj,
                        'image_desc': img,
                        'data_offset': dat.ptr(img + 0x00),
                        'width': dat.u16(img + 0x04),
                        'height': dat.u16(img + 0x06),
                        'gx_format': dat.u32(img + 0x08),
                        'tlut': tlut,
                    }
                    if tlut is not None:
                        info['tlut_data_offset'] = dat.ptr(tlut + 0x00)
                        info['tlut_format'] = dat.u32(tlut + 0x04)
                        info['tlut_count'] = dat.u16(tlut + 0x0C)
                    return info
                tobj = dat.ptr(tobj + 0x04)
        dobj = dat.ptr(dobj + 0x04)
    return None


def is_image_model(dat_bytes, type_config):
    """True when this DAT's configured model is a textured (image) model."""
    cfg = parse_cfg(type_config)
    try:
        return read_texture(EffectDat(dat_bytes), cfg) is not None
    except EffectModelError as e:
        logger.debug(f'[effect_model] not an image model: {e}')
        return False


# What kind of shine a DAT's model 0 actually is. Community "shine mods" come
# in three shapes and only one of them is an image:
#   'gradient' -- vanilla shape (one untextured DObj): the two-color hexagon,
#                 handled by shine_gradient's color offsets
#   'image'    -- one textured DObj: THIS module's format
#   'model'    -- replacement geometry (Honeycomb, Stop Sign) or a real 3D
#                 model with several textured nodes (Triforce). Not an image;
#                 installing it would need whole-model surgery, which Nucleus
#                 does not do -- say so instead of guessing.
CLASSIFY_GRADIENT = 'gradient'
CLASSIFY_IMAGE = 'image'
CLASSIFY_MODEL = 'model'


def check_archive(dat_bytes, type_config):
    """Confirm a file is the right archive for this extra, else raise.

    Community effect zips carry unrelated DATs next to the one that matters
    (NERV ships optional `PlFx`/`PlFc` fighter files alongside its two
    `EfFxData` variants, and HSDRawViewer users ship exported
    `Models_0_(SBM_EffectModel...)` fragments). Those parse as archives and
    would walk into nonsense, so the configured root symbol gates them out.
    """
    cfg = parse_cfg(type_config)
    dat = EffectDat(dat_bytes)
    want = cfg['root_symbol']
    if want:
        got = dat.root_name(cfg['root_index'])
        if got != want:
            raise EffectModelError(
                f"this is not a {type_config.get('target_file', want)} effect "
                f"file (its first root is '{got or 'unnamed'}', expected "
                f"'{want}')")
    return dat


def classify_model(dat_bytes, type_config):
    """('gradient' | 'image' | 'model', detail) for a DAT's configured model."""
    cfg = parse_cfg(type_config)
    dat = check_archive(dat_bytes, type_config)
    entry = dat.model_entry(cfg)
    root = dat.ptr(entry + 4)
    if root is None:
        raise EffectModelError('model has no JObj')
    dobjs = tobjs = 0
    holders = 0
    for j in jobj_nodes(dat, root):
        dobj = dat.ptr(j + 0x10)
        if dobj is not None:
            holders += 1
        while dobj is not None:
            dobjs += 1
            mobj = dat.ptr(dobj + 0x08)
            if mobj is not None:
                tobj = dat.ptr(mobj + 0x08)
                while tobj is not None:
                    tobjs += 1
                    tobj = dat.ptr(tobj + 0x04)
            dobj = dat.ptr(dobj + 0x04)
    detail = {'dobjs': dobjs, 'tobjs': tobjs, 'jobjs_with_dobj': holders}
    if holders == 1 and dobjs == 1 and tobjs == 0:
        return CLASSIFY_GRADIENT, detail
    if holders == 1 and dobjs == 1 and tobjs >= 1:
        info = read_texture(dat, cfg)
        if info is not None:
            detail.update({k: info[k] for k in ('width', 'height', 'gx_format')})
            return CLASSIFY_IMAGE, detail
    return CLASSIFY_MODEL, detail


# ---------------------------------------------------------------------------
# pixels
# ---------------------------------------------------------------------------

def read_rgba(dat, cfg):
    """(width, height, [(r, g, b, a), ...] row-major) of the model texture."""
    info = read_texture(dat, cfg)
    if info is None:
        raise EffectModelError(
            'this model has no texture -- it is a color/gradient effect, '
            'not an image effect')
    if info['data_offset'] is None:
        raise EffectModelError('texture has no image data')

    from shared.rendering.datprobe import Image, Tlut, decode_image, gx_image_size

    w, h, fmt = info['width'], info['height'], info['gx_format']
    if not (0 < w <= 1024 and 0 < h <= 1024):
        raise EffectModelError(f'implausible texture size {w}x{h}')
    size = gx_image_size(fmt, w, h)
    start = info['data_offset']
    if start + size > len(dat.data):
        raise EffectModelError(
            f'texture data (0x{start:X}+0x{size:X}) runs past the data section')
    img = Image(info['image_desc'], start, w, h, fmt,
                bytes(dat.data[start:start + size]))
    tlut = None
    if info.get('tlut') is not None and info.get('tlut_data_offset') is not None:
        count = info['tlut_count'] or 256
        ts = info['tlut_data_offset']
        tlut = Tlut(info['tlut'], ts, info['tlut_format'], count,
                    bytes(dat.data[ts:ts + count * 2]))
    rows = decode_image(img, tlut)
    return w, h, [px for row in rows for px in row]


def _to_pil(px, w, h):
    from PIL import Image as PILImage
    im = PILImage.new('RGBA', (w, h))
    im.putdata(px)
    return im


def _png_bytes(px, w, h):
    buf = io.BytesIO()
    _to_pil(px, w, h).save(buf, 'PNG')
    return buf.getvalue()


def png_from_dat(dat_bytes, type_config):
    """The model texture of a DAT, as PNG bytes."""
    cfg = parse_cfg(type_config)
    w, h, px = read_rgba(EffectDat(dat_bytes), cfg)
    return _png_bytes(px, w, h)


def rgba_from_image_bytes(raw, cfg):
    """Any image file -> the [RGBA] texel list the configured texture wants."""
    from PIL import Image as PILImage
    try:
        im = PILImage.open(io.BytesIO(raw))
    except Exception as e:
        raise EffectModelError(f'could not read that image: {e}')
    im = im.convert('RGBA')
    if im.size != (cfg['width'], cfg['height']):
        im = im.resize((cfg['width'], cfg['height']), PILImage.LANCZOS)
    return list(im.getdata())


def _encode_texels(px, cfg):
    from .texture_recolor import encode_texel_block
    return encode_texel_block(px, cfg['width'], cfg['height'], cfg['gx_format'])


# ---------------------------------------------------------------------------
# the NUCSHINE append header
# ---------------------------------------------------------------------------
#   0x00 magic 'NUCSHINE'
#   0x08 u16 version           0x0A u16 flags (reserved)
#   0x0C u16 root_index        0x0E u16 model_index
#   0x10 u32 jobj_off          -- the JObj whose dobj/flags were changed
#   0x14 u32 orig_dobj         -- its previous DObj pointer value
#   0x18 u32 orig_dobj_present -- 1 when that field was a real pointer
#   0x1C u32 orig_jobj_flags
#   0x20 u32 root_jobj_off     -- the model's ROOT JObj (pass gating)
#   0x24 u32 orig_root_flags
#   0x28 3xf32 orig_child_scale
#   0x34.. reserved zeros
_HDR = '>8sHHHHIIIIII3f'


def _make_header(cfg, jobj_off, orig_dobj, orig_flags, root_off,
                 orig_root_flags, orig_scale):
    blob = bytearray(HEADER_SIZE)
    struct.pack_into(_HDR, blob, 0, MAGIC, HEADER_VERSION, 0,
                     cfg['root_index'], cfg['model_index'], jobj_off,
                     orig_dobj if orig_dobj is not None else 0,
                     1 if orig_dobj is not None else 0, orig_flags,
                     root_off, orig_root_flags, *orig_scale)
    return bytes(blob)


def find_header(dat):
    """(offset, fields) of our append header, or (None, None).

    Scanned from the end backwards: the header is the first block of the
    newest append, so the LAST magic in the file is the live one. (Older ones
    cannot normally exist -- install reverts first -- but a hand-edited file
    should still revert to its newest state.)
    """
    data = bytes(dat.data)
    pos = data.rfind(MAGIC)
    while pos >= 0:
        if pos % 4 == 0 and pos + HEADER_SIZE <= len(data):
            (_magic, ver, _flags, root_index, model_index, jobj_off,
             orig_dobj, present, orig_flags, root_off, orig_root_flags,
             sx, sy, sz) = struct.unpack_from(_HDR, data, pos)
            if (ver == HEADER_VERSION and jobj_off + 0x40 <= pos
                    and root_off + 0x40 <= pos):
                return pos, {
                    'version': ver,
                    'root_index': root_index,
                    'model_index': model_index,
                    'jobj_off': jobj_off,
                    'orig_dobj': orig_dobj if present else None,
                    'orig_jobj_flags': orig_flags,
                    'root_jobj_off': root_off,
                    'orig_root_flags': orig_root_flags,
                    'orig_child_scale': (sx, sy, sz),
                }
        pos = data.rfind(MAGIC, 0, pos)
    return None, None


def revert(dat):
    """Undo a previous install: truncate our append, restore the JObj.

    Returns True when something was reverted. A no-op on a vanilla file, or
    on one whose image shine arrived as a whole-file swap rather than through
    this module.
    """
    off, hdr = find_header(dat)
    if off is None:
        return False
    jobj = hdr['jobj_off']
    del dat.data[off:]
    dat.data_size = len(dat.data)
    dat.relocs = {r for r in dat.relocs if r + 4 <= off}
    struct.pack_into('>I', dat.data, jobj + 0x04, hdr['orig_jobj_flags'])
    struct.pack_into('>I', dat.data, hdr['root_jobj_off'] + 0x04,
                     hdr['orig_root_flags'])
    struct.pack_into('>3f', dat.data, jobj + 0x20, *hdr['orig_child_scale'])
    if hdr['orig_dobj'] is not None:
        dat.set_ptr(jobj + 0x10, hdr['orig_dobj'])
    else:
        dat.clear_ptr(jobj + 0x10)
    logger.info(f'[effect_model] reverted append at 0x{off:X} '
                f'(JObj 0x{jobj:X} -> DObj '
                f'0x{(hdr["orig_dobj"] or 0):X})')
    return True


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def _quad_buffers(cfg):
    """POS / NRM / TEX0 attribute buffers and the display list.

    Two GX_DRAW_TRIANGLES primitives over a +-half_extent quad in the XY
    plane, with u = (x + e) / 2e and v = (e - y) / 2e -- the mapping every
    measured community mod uses, so an imported image and an authored PNG
    come out the same way up.
    """
    e = cfg['half_extent']
    unit = 1 << POS_SCALE_EXP
    corners = [(e, -e), (-e, -e), (-e, e), (e, e)]
    pos = b''.join(struct.pack('>hhh', int(round(x * unit)),
                               int(round(y * unit)), 0) for x, y in corners)
    # Only index 0 is ever referenced by the display list (the quad is flat).
    # The byte is 0x80 with comp_type GX_U8 and frac 7, exactly as the proven
    # community mods write it -- see NRM_COMP_TYPE.
    nrm = struct.pack('>BBB', 0, 0, 0x80) + b'\0' * 9
    tex = b''.join(struct.pack('>BB', 128 if x > 0 else 0, 128 if y < 0 else 0)
                   for x, y in corners)
    disp = b''
    for tri in ((0, 1, 2), (0, 2, 3)):
        disp += struct.pack('>BH', 0x90, 3)         # GX_DRAW_TRIANGLES, 3 verts
        for v in tri:
            disp += struct.pack('>BBB', v, 0, v)    # POS, NRM(0), TEX0 indices
    disp += b'\0' * ((-len(disp)) % ALIGN_TEX)
    return pos, nrm, tex, disp


def _attr(name, atype, compcnt, comptype, scale, stride):
    """HSD_Attribute: name, type, compcnt, comptype, scale, pad, stride, buf."""
    return struct.pack('>IIIIBBHI', name, atype, compcnt, comptype,
                       scale, 0, stride, 0)


def build_image_model(dat, cfg, px):
    """Append a textured quad DObj and point the model's JObj at it.

    `px` is a [(r, g, b, a), ...] list of exactly width*height texels. Any
    previous append is reverted first, so repeated installs neither stack nor
    grow the file.
    """
    if len(px) != cfg['width'] * cfg['height']:
        raise EffectModelError(
            f'expected {cfg["width"] * cfg["height"]} texels, got {len(px)}')

    revert(dat)
    jobj = find_display_jobj(dat, cfg)
    root_jobj = dat.ptr(dat.model_entry(cfg) + 4)
    orig_dobj = dat.ptr(jobj + 0x10)
    orig_flags = dat.u32(jobj + 0x04)
    orig_root_flags = dat.u32(root_jobj + 0x04)
    orig_scale = struct.unpack_from('>3f', dat.data, jobj + 0x20)

    dat.append(_make_header(cfg, jobj, orig_dobj, orig_flags, root_jobj,
                            orig_root_flags, orig_scale), align=ALIGN_TEX)

    texels_off = dat.append(_encode_texels(px, cfg), align=ALIGN_TEX)

    # HSD_Image: data*, u16 width, u16 height, u32 format, u32 mipmap, f32 lod
    img_off = dat.append(struct.pack('>IHHIIf', 0, cfg['width'], cfg['height'],
                                     cfg['gx_format'], 0, 0.0))
    dat.set_ptr(img_off + 0x00, texels_off)

    tobj = bytearray(0x5C)
    struct.pack_into('>II', tobj, 0x08, 0, TOBJ_TEXGENSRC)   # GX_TEXMAP0, TEX0
    struct.pack_into('>9f', tobj, 0x10, 0.0, 0.0, 0.0,       # rotation
                     1.0, 1.0, 1.0,                          # scale
                     0.0, 0.0, 0.0)                          # translation
    struct.pack_into('>II', tobj, 0x34, TOBJ_WRAP, TOBJ_WRAP)
    struct.pack_into('>BB', tobj, 0x3C, 1, 1)                # repeat S / T
    struct.pack_into('>I', tobj, 0x40, TOBJ_FLAGS)
    struct.pack_into('>f', tobj, 0x44, TOBJ_BLENDING)
    struct.pack_into('>I', tobj, 0x48, TOBJ_MAGFILTER)
    tobj_off = dat.append(bytes(tobj))
    dat.set_ptr(tobj_off + 0x4C, img_off)

    mat_off = dat.append(struct.pack('>IIIff', MAT_AMBIENT, MAT_DIFFUSE,
                                     MAT_SPECULAR, MAT_ALPHA, MAT_SHININESS))

    mobj_off = dat.append(struct.pack('>IIIIII', 0, MOBJ_RENDERMODE,
                                      0, 0, 0, 0))
    dat.set_ptr(mobj_off + 0x08, tobj_off)
    dat.set_ptr(mobj_off + 0x0C, mat_off)

    pos, nrm, tex, disp = _quad_buffers(cfg)
    # GX_SetArray demands 32-BYTE-ALIGNED array bases, and HSD hands these
    # buffers straight to it. At 4-byte alignment the GP hangs the frame the
    # model first draws (verified in-game 2026-09-09: the match froze on shine
    # frame 1) -- which is why every community mod's POS/NRM/TEX0 buffers sit
    # on 0x20 boundaries. The DAT's data section is itself 32-byte aligned
    # when loaded, so a 32-aligned data offset is a 32-aligned address.
    buf_offs = [dat.append(pos, align=ALIGN_TEX),
                dat.append(nrm, align=ALIGN_TEX),
                dat.append(tex, align=ALIGN_TEX)]
    attrs_off = dat.append(
        _attr(9, 2, 1, 3, POS_SCALE_EXP, 6)     # POS,  GX_INDEX8, XYZ, s16
        + _attr(10, 2, 0, NRM_COMP_TYPE, 7, 3)  # NRM,  GX_INDEX8, XYZ
        + _attr(13, 2, 1, 0, 7, 2)              # TEX0, GX_INDEX8, ST,  u8
        + _attr(255, 0, 0, 0, 0, 0))            # GX_VA_NULL terminator
    for i, buf in enumerate(buf_offs):
        dat.set_ptr(attrs_off + i * 0x18 + 0x14, buf)

    disp_off = dat.append(disp, align=ALIGN_TEX)
    # HSD_POBJ: name, next, attrs, u16 flags, u16 displist_size(32B units),
    #           displist, tail
    pobj_off = dat.append(struct.pack('>IIIHHII', 0, 0, 0, 0,
                                      len(disp) // ALIGN_TEX, 0, 0))
    dat.set_ptr(pobj_off + 0x08, attrs_off)
    dat.set_ptr(pobj_off + 0x10, disp_off)

    dobj_off = dat.append(struct.pack('>IIII', 0, 0, 0, 0))
    dat.set_ptr(dobj_off + 0x08, mobj_off)
    dat.set_ptr(dobj_off + 0x0C, pobj_off)

    dat.set_ptr(jobj + 0x10, dobj_off)
    struct.pack_into('>3f', dat.data, jobj + 0x20, CHILD_JOBJ_SCALE,
                     CHILD_JOBJ_SCALE, CHILD_JOBJ_SCALE)
    # The child draws in the TEXEDGE pass; the root must ASK for that pass or
    # HSD_JObjDisp never descends into it (see the JOBJ_ROOT_* comment above).
    struct.pack_into('>I', dat.data, jobj + 0x04,
                     (orig_flags & ~JOBJ_TRSP_MASK) | JOBJ_TEXEDGE)
    struct.pack_into('>I', dat.data, root_jobj + 0x04,
                     (orig_root_flags & ~JOBJ_ROOT_MASK) | JOBJ_ROOT_TEXEDGE)
    dat.align_to(ALIGN_TEX)
    logger.info(f'[effect_model] built image model {cfg["model_index"]}: '
                f'{cfg["width"]}x{cfg["height"]} fmt {cfg["gx_format"]} '
                f'-> DObj 0x{dobj_off:X}')
    return dat


def install_image(dat_bytes, px, type_config):
    """Install a texel list into a DAT's configured model. -> new DAT bytes."""
    cfg = parse_cfg(type_config)
    dat = EffectDat(dat_bytes)
    build_image_model(dat, cfg, px)
    return dat.to_bytes()


def revert_from_reference(dat, cfg, reference_bytes):
    """Fallback revert for a file that lost its NUCSHINE header.

    Another extra can re-save the whole archive through the HSDRawViewer CLI
    (Fox's `upb_texture` fire hue targets this very file), and a re-save drops
    unreferenced blocks -- including our header. The image model itself
    survives, so without this the image could never be taken back out and a
    colour install would quietly patch bytes nothing draws.

    Restores the display JObj's dobj / flags / scale from the vanilla
    reference, but ONLY when that JObj still sits at the vanilla offset and
    the vanilla DObj it pointed at still parses in this file. Anything else
    (a genuinely re-laid-out archive) is refused rather than guessed at: the
    appended blocks stay as orphans, which costs bytes and nothing else.
    """
    ref = EffectDat(reference_bytes)
    ref_jobj = find_display_jobj(ref, cfg)
    ref_dobj = ref.ptr(ref_jobj + 0x10)
    if ref_dobj is None:
        return False
    try:
        jobj = find_display_jobj(dat, cfg)
    except EffectModelError:
        return False
    if jobj != ref_jobj or ref_dobj + 0x10 > len(dat.data):
        logger.warning('[effect_model] cannot revert from the vanilla '
                       'reference: this file has been re-laid-out '
                       f'(JObj 0x{jobj:X} vs vanilla 0x{ref_jobj:X})')
        return False
    # the vanilla DObj must still BE there: same bytes as the reference
    if dat.data[ref_dobj:ref_dobj + 0x10] != ref.data[ref_dobj:ref_dobj + 0x10]:
        logger.warning('[effect_model] cannot revert from the vanilla '
                       f'reference: DObj 0x{ref_dobj:X} no longer matches')
        return False
    dat.set_ptr(jobj + 0x10, ref_dobj)
    struct.pack_into('>I', dat.data, jobj + 0x04, ref.u32(ref_jobj + 0x04))
    struct.pack_into('>3f', dat.data, jobj + 0x20,
                     *struct.unpack_from('>3f', ref.data, ref_jobj + 0x20))
    root = dat.ptr(dat.model_entry(cfg) + 4)
    ref_root = ref.ptr(ref.model_entry(cfg) + 4)
    if root is not None and root == ref_root:
        struct.pack_into('>I', dat.data, root + 0x04, ref.u32(ref_root + 0x04))
    logger.info('[effect_model] reverted from the vanilla reference '
                '(append header was gone)')
    return True


def revert_dat(dat_bytes, type_config):
    """Undo an installed image model. -> (new bytes, reverted?)."""
    cfg = parse_cfg(type_config)
    dat = EffectDat(dat_bytes)
    if revert(dat):
        return dat.to_bytes(), True
    if read_texture(dat, cfg) is None:
        return dat_bytes, False     # nothing installed: a clean no-op
    # An image IS installed but our header is gone -- try the reference.
    from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
    ref = ensure_vanilla_ref(type_config.get('target_file'))
    if ref and revert_from_reference(dat, cfg, Path(ref).read_bytes()):
        return dat.to_bytes(), True
    raise EffectModelError(
        'an image effect is installed but Nucleus cannot take it back out of '
        'this file (its revert marker is gone and the vanilla reference does '
        'not line up) -- rebuild the project from your ISO to clear it')


# ---------------------------------------------------------------------------
# mod-source resolution
# ---------------------------------------------------------------------------

def is_image_mod(mod):
    """True when a stored extras mod is an image-model mod.

    `format` is written by this module's import path; the `modifications`
    probe also catches mods healed by
    helpers.derive_modifications_from_dat, which marks a rebuilt image DAT
    with an 'image' key instead of colors it cannot read.
    """
    if not mod:
        return False
    if mod.get('format') == 'effect_model' or mod.get('type') == 'effect_model':
        return True
    return 'image' in (mod.get('modifications') or {})


def texels_from_mod(storage_dir, mod, type_config):
    """A stored mod's texels.

    Sources (newest first):
    - `image_file` (models/<id>.png): the authored / normalized image
    - `model_file` ending .dat: a full modded DAT from the website effect
      import path -- its own model texture is decoded out of it
    """
    cfg = parse_cfg(type_config)
    storage_dir = Path(storage_dir)
    image_file = mod.get('image_file')
    if image_file:
        return rgba_from_image_bytes((storage_dir / image_file).read_bytes(), cfg)
    model_file = mod.get('model_file')
    if model_file and str(model_file).lower().endswith('.dat'):
        raw = (storage_dir / model_file).read_bytes()
        w, h, px = read_rgba(EffectDat(raw), cfg)
        if (w, h) != (cfg['width'], cfg['height']):
            from PIL import Image as PILImage
            im = _to_pil(px, w, h).resize(
                (cfg['width'], cfg['height']), PILImage.LANCZOS)
            px = list(im.getdata())
        return px
    raise EffectModelError(
        'mod has no image_file or .dat model_file to read an image from')


def png_from_mod(storage_dir, mod, type_config):
    """A stored mod's image as PNG bytes (previews and re-editing)."""
    cfg = parse_cfg(type_config)
    px = texels_from_mod(storage_dir, mod, type_config)
    return _png_bytes(px, cfg['width'], cfg['height'])


def install_mod(dat_path, storage_dir, mod, type_config):
    """Install a stored image mod into a project DAT (atomic swap)."""
    dat_path = Path(dat_path)
    px = texels_from_mod(storage_dir, mod, type_config)
    patched = install_image(dat_path.read_bytes(), px, type_config)
    tmp = dat_path.with_name(dat_path.name + '.patching')
    tmp.write_bytes(patched)
    file_retry.replace(tmp, dat_path)
    return dat_path


def revert_installed(dat_path, type_config):
    """Take an installed image model back out of a project DAT."""
    dat_path = Path(dat_path)
    out, changed = revert_dat(dat_path.read_bytes(), type_config)
    if not changed:
        return False
    tmp = dat_path.with_name(dat_path.name + '.patching')
    tmp.write_bytes(out)
    file_retry.replace(tmp, dat_path)
    return True


def vanilla_png(type_config, target_file):
    """The vanilla model's image, or None -- vanilla shine has no texture, so
    this is None for the shine and exists for symmetry with texture_region."""
    from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
    ref = ensure_vanilla_ref(target_file)
    if not ref:
        return None
    try:
        return png_from_dat(Path(ref).read_bytes(), type_config)
    except EffectModelError:
        return None


IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}


def texels_from_upload(raw, suffix, type_config):
    """(texels, source_kind) for an uploaded image or modded DAT.

    A DAT is classified first so the three community shine shapes get three
    different answers: an image shine is decoded, a gradient mod is sent to
    the color editor, and replacement geometry is refused by name rather than
    installed as something it is not.
    """
    cfg = parse_cfg(type_config)
    if suffix in IMAGE_EXTS:
        return rgba_from_image_bytes(raw, cfg), 'image'
    if suffix != '.dat':
        raise EffectModelError(
            f'unsupported file type "{suffix}" (use .dat or an image)')

    kind, detail = classify_model(raw, type_config)
    if kind == CLASSIFY_GRADIENT:
        raise EffectModelError(
            'this file is a color/gradient effect, not an image effect -- '
            'import it as a color mod (or use the color editor)')
    if kind == CLASSIFY_MODEL:
        raise EffectModelError(
            'this file replaces the effect GEOMETRY rather than putting an '
            f'image on it ({detail["dobjs"]} meshes, {detail["tobjs"]} '
            'textures). Nucleus can install image effects, not replacement '
            '3D models, so this one is not supported yet')
    w, h, px = read_rgba(EffectDat(raw), cfg)
    if (w, h) != (cfg['width'], cfg['height']):
        from PIL import Image as PILImage
        px = list(_to_pil(px, w, h).resize(
            (cfg['width'], cfg['height']), PILImage.LANCZOS).getdata())
    return px, 'dat'


def import_image_mod(file_storage, character, extra_type, type_config, name=''):
    """Create an image-model mod from an uploaded image or modded DAT.

    Shares the extras page's `/storage/extras/import` surface with
    texture_region (texture_region.py routes to here). The mod stores a
    NORMALIZED PNG, not the uploaded DAT: the install path only ever needs
    the texels, and a PNG is what the editor re-opens for further editing.
    """
    cfg = parse_cfg(type_config)
    raw = file_storage.read()
    suffix = Path(file_storage.filename or '').suffix.lower()
    px, source_kind = texels_from_upload(raw, suffix, type_config)

    storage_char = get_storage_character(character, extra_type)
    mod_id = f'{extra_type}_{uuid.uuid4().hex[:8]}'
    models_dir = helpers.STORAGE_PATH / storage_char / 'models'
    models_dir.mkdir(parents=True, exist_ok=True)

    png = _png_bytes(px, cfg['width'], cfg['height'])
    (models_dir / f'{mod_id}.png').write_bytes(png)
    (models_dir / f'{mod_id}_preview.png').write_bytes(png)

    metadata = load_metadata(default={'characters': {}})
    chars = metadata.setdefault('characters', {})
    char_data = chars.setdefault(storage_char, {'skins': [], 'extras': {}})
    mods = char_data.setdefault('extras', {}).setdefault(extra_type, [])
    mod = {
        'id': mod_id,
        'name': name or Path(file_storage.filename or 'image').stem,
        'type': 'effect_model',
        'format': 'effect_model',
        'date_added': datetime.now().isoformat(),
        'source': 'uploaded',
        'image_file': f'models/{mod_id}.png',
        'screenshot': f'models/{mod_id}_preview.png',
        'file_hash': hashlib.md5(png).hexdigest(),
        # so install/apply and the derive heal path recognize it without
        # having to re-read the image (see is_image_mod)
        'modifications': {'image': {
            'width': cfg['width'], 'height': cfg['height'],
            'gx_format': cfg['gx_format'], 'imported_from': source_kind,
        }},
    }
    mods.append(mod)
    save_metadata(metadata)
    logger.info(f"[OK] Imported image {extra_type} mod '{mod['name']}' "
                f'for {storage_char} (from {source_kind})')
    return mod
