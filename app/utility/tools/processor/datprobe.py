"""
datprobe.py -- a tiny pure-Python HSD/DAT reader used to inspect costume
files OUTSIDE the viewer: list the material (JOBJ-tree) textures and the
MatAnim texture-swap frames (blink/half-closed eyes etc.) that material
animations carry in `*_matanim_joint` roots.

Why it exists: the skin lab's texture list comes from HSDRawViewer's
RenderJObj.GetTextureList(), which only walks DOBJ materials -- MatAnim
swap frames are invisible there, so AI recolors used to miss them and the
character flashed STOCK eyes on every blink. This module is the ground
truth for "what textures does this DAT really contain", and the verifier
for "did an exported skin actually recolor the swap frames".

Only reading is supported. Pointer values in a DAT are offsets into the
data section (file offset = value + 0x20); 0 is treated as null, which
matches how HSDRaw materializes references for these node types.

CLI: python -m skinlab.datprobe <file.dat> [--dump-dir DIR]
"""

import struct
import sys
from collections import namedtuple
from pathlib import Path

HEADER_SIZE = 0x20

# GXTexFmt numeric values (matches HSDRaw.GX.GXTexFmt)
TEX_FMT = {0: 'I4', 1: 'I8', 2: 'IA4', 3: 'IA8', 4: 'RGB565',
           5: 'RGB5A3', 6: 'RGBA8', 8: 'CI4', 9: 'CI8', 10: 'CI14X2',
           14: 'CMPR'}
TLUT_FMT = {0: 'IA8', 1: 'RGB565', 2: 'RGB5A3'}

Image = namedtuple('Image', 'offset data_offset width height format data')
Tlut = namedtuple('Tlut', 'offset data_offset format count data')
TexAnimInfo = namedtuple(
    'TexAnimInfo', 'joint_index matanim_index texmap_id images tluts')
TobjInfo = namedtuple('TobjInfo', 'jobj_index dobj_index image tlut')


class DatFile:
    def __init__(self, path):
        self.path = Path(path)
        self.raw = self.path.read_bytes()
        (self.file_size, self.data_size, self.reloc_count,
         self.root_count, self.ref_count) = struct.unpack_from(
            '>IIIII', self.raw, 0)
        reloc_start = HEADER_SIZE + self.data_size
        self.relocs = set(struct.unpack_from(
            f'>{self.reloc_count}I', self.raw, reloc_start))
        roots_start = reloc_start + self.reloc_count * 4
        strings_start = roots_start + (self.root_count + self.ref_count) * 8
        self.roots = []
        for i in range(self.root_count):
            data_off, str_off = struct.unpack_from(
                '>II', self.raw, roots_start + i * 8)
            end = self.raw.index(b'\0', strings_start + str_off)
            name = self.raw[strings_start + str_off:end].decode(
                'ascii', 'replace')
            self.roots.append((name, data_off))

    # -- primitive readers (offsets are data-section relative) ------------- #
    def u32(self, off):
        return struct.unpack_from('>I', self.raw, HEADER_SIZE + off)[0]

    def u16(self, off):
        return struct.unpack_from('>H', self.raw, HEADER_SIZE + off)[0]

    def ptr(self, off):
        # a 0 word is a NULL pointer only when the field is absent from the
        # reloc table; relocated 0 is a real pointer to data offset 0 (vanilla
        # Pl*.dat stores the model lookup tables there, as the first struct)
        v = self.u32(off)
        if v == 0 and off not in self.relocs:
            return None
        return v

    # -- structs ------------------------------------------------------------ #
    def image_at(self, off, data_size=None):
        data_off = self.ptr(off + 0x00)
        w, h = self.u16(off + 0x04), self.u16(off + 0x06)
        fmt = self.u32(off + 0x08)
        data = None
        if data_off is not None and data_size is None:
            data_size = gx_image_size(fmt, w, h)
        if data_off is not None:
            start = HEADER_SIZE + data_off
            data = self.raw[start:start + data_size]
        return Image(off, data_off, w, h, fmt, data)

    def tlut_at(self, off):
        data_off = self.ptr(off + 0x00)
        fmt = self.u32(off + 0x04)
        # HSD_Tlut: 0x00 data, 0x04 format, 0x08 gx tlut name, 0x0C u16 color
        # count (decomp tobj.h n_entries; HSDRaw HSD_Tlut.ColorCount). 0x0E is
        # struct padding - always 0 - so reading it gave empty palettes.
        count = self.u16(off + 0x0C)
        data = None
        if data_off is not None:
            start = HEADER_SIZE + data_off
            data = self.raw[start:start + count * 2]
        return Tlut(off, data_off, fmt, count, data)

    # -- tree walks ----------------------------------------------------------- #
    def _iter_tree(self, off, child_off, next_off):
        """Depth-first (child before next) node offsets of a Child/Next tree."""
        seen = set()
        stack = [off]
        order = []
        while stack:
            node = stack.pop()
            if node is None or node in seen:
                continue
            seen.add(node)
            order.append(node)
            # push next first so child is processed first (LIFO)
            stack.append(self.ptr(node + next_off))
            stack.append(self.ptr(node + child_off))
        return order

    def jobj_textures(self, root_off):
        """All material TOBJ images in the JOBJ tree, in RenderDobjs order
        (the order RenderJObj.GetTextureList walks)."""
        result = []
        jobjs = self._iter_tree(root_off, 0x08, 0x0C)
        for j_idx, j in enumerate(jobjs):
            flags = self.u32(j + 0x04)
            if flags & (1 << 14) or flags & (1 << 5):   # SPLINE / PTCL
                continue
            dobj = self.ptr(j + 0x10)
            d_idx = 0
            while dobj is not None:
                mobj = self.ptr(dobj + 0x08)
                if mobj is not None:
                    tobj = self.ptr(mobj + 0x08)
                    while tobj is not None:
                        img_off = self.ptr(tobj + 0x4C)
                        tlut_off = self.ptr(tobj + 0x50)
                        if img_off is not None:
                            result.append(TobjInfo(
                                j_idx, d_idx,
                                self.image_at(img_off),
                                self.tlut_at(tlut_off) if tlut_off else None))
                        tobj = self.ptr(tobj + 0x04)
                dobj = self.ptr(dobj + 0x04)
                d_idx += 1
        return result

    def matanim_texanims(self, root_off):
        """Every TexAnim in a matanim_joint tree with its swap-frame images."""
        result = []
        joints = self._iter_tree(root_off, 0x00, 0x04)
        for j_idx, joint in enumerate(joints):
            matanim = self.ptr(joint + 0x08)
            m_idx = 0
            while matanim is not None:
                texanim = self.ptr(matanim + 0x08)
                while texanim is not None:
                    texmap = self.u32(texanim + 0x04)
                    img_count = self.u16(texanim + 0x14)
                    tlut_count = self.u16(texanim + 0x16)
                    img_arr = self.ptr(texanim + 0x0C)
                    tlut_arr = self.ptr(texanim + 0x10)
                    images, tluts = [], []
                    for i in range(img_count):
                        img_off = self.ptr(img_arr + i * 4) if img_arr else None
                        if img_off is not None:
                            images.append(self.image_at(img_off))
                    for i in range(tlut_count):
                        tlut_off = self.ptr(tlut_arr + i * 4) if tlut_arr else None
                        if tlut_off is not None:
                            tluts.append(self.tlut_at(tlut_off))
                    if images:
                        result.append(TexAnimInfo(j_idx, m_idx, texmap,
                                                  images, tluts))
                    texanim = self.ptr(texanim + 0x00)
                matanim = self.ptr(matanim + 0x00)
                m_idx += 1
        return result

    def find_roots(self, suffix):
        return [(n, o) for n, o in self.roots if n.endswith(suffix)]


def samples_textures(path):
    """Whether any model joint tree of the DAT draws an image. Vanilla Mr. Game &
    Watch draws none (the game paints him one flat colour by slot); a model
    imported onto him draws its own. False when the file cannot be read."""
    try:
        dat = DatFile(path)
        return any(dat.jobj_textures(off) for name, off in dat.roots
                   if name.endswith('_joint') and 'matanim' not in name
                   and 'shapeanim' not in name)
    except Exception:  # noqa: BLE001 - a probe, never a gate
        return False


# --------------------------------------------------------------------------- #
# GX image helpers (sizes + decode for the common Melee formats)              #
# --------------------------------------------------------------------------- #
def gx_image_size(fmt, w, h):
    def blocks(x, b):
        return (x + b - 1) // b
    if fmt in (0, 8):            # I4 / CI4: 8x8 tiles, 4bpp
        return blocks(w, 8) * blocks(h, 8) * 32
    if fmt in (1, 2, 9):         # I8 / IA4 / CI8: 8x4 tiles, 8bpp
        return blocks(w, 8) * blocks(h, 4) * 32
    if fmt in (3, 4, 5, 10):     # IA8 / RGB565 / RGB5A3 / CI14X2: 4x4, 16bpp
        return blocks(w, 4) * blocks(h, 4) * 32
    if fmt == 6:                 # RGBA8: 4x4 tiles, two cache lines
        return blocks(w, 4) * blocks(h, 4) * 64
    if fmt == 14:                # CMPR: 8x8 tiles of 4 DXT1 blocks
        return blocks(w, 8) * blocks(h, 8) * 32
    raise ValueError(f'unknown GX format {fmt}')


def _rgb565(v):
    return (((v >> 11) & 0x1F) * 255 // 31,
            ((v >> 5) & 0x3F) * 255 // 63,
            (v & 0x1F) * 255 // 31, 255)


def _rgb5a3(v):
    if v & 0x8000:
        return (((v >> 10) & 0x1F) * 255 // 31,
                ((v >> 5) & 0x1F) * 255 // 31,
                (v & 0x1F) * 255 // 31, 255)
    return (((v >> 8) & 0xF) * 17, ((v >> 4) & 0xF) * 17,
            (v & 0xF) * 17, ((v >> 12) & 0x7) * 255 // 7)


def _decode_palette(tlut):
    pal = []
    for i in range(tlut.count):
        v = struct.unpack_from('>H', tlut.data, i * 2)[0]
        if tlut.format == 1:
            pal.append(_rgb565(v))
        elif tlut.format == 2:
            pal.append(_rgb5a3(v))
        else:                                  # IA8
            a, i_ = v >> 8, v & 0xFF
            pal.append((i_, i_, i_, a))
    return pal


def decode_image(img, tlut=None):
    """Image -> [h][w] RGBA tuples for the common Melee formats."""
    w, h, fmt, data = img.width, img.height, img.format, img.data
    out = [[(0, 0, 0, 0)] * w for _ in range(h)]
    pal = _decode_palette(tlut) if tlut is not None else None
    if pal is not None and len(pal) < 256:
        # a palette shorter than the index range: out-of-range indices read
        # as transparent instead of raising (count comes from the file)
        pal += [(0, 0, 0, 0)] * (256 - len(pal))

    def put(x, y, px):
        if x < w and y < h:
            out[y][x] = px

    pos = 0
    if fmt in (0, 8):       # I4 / CI4
        for by in range(0, h, 8):
            for bx in range(0, w, 8):
                for y in range(8):
                    for x in range(0, 8, 2):
                        b = data[pos]; pos += 1
                        for k, nib in enumerate(((b >> 4) & 0xF, b & 0xF)):
                            px = pal[nib][:4] if fmt == 8 else (nib * 17,) * 3 + (255,)
                            put(bx + x + k, by + y, tuple(px))
    elif fmt in (1, 2, 9):  # I8 / IA4 / CI8
        for by in range(0, h, 4):
            for bx in range(0, w, 8):
                for y in range(4):
                    for x in range(8):
                        b = data[pos]; pos += 1
                        if fmt == 9:
                            px = tuple(pal[b][:4])
                        elif fmt == 1:
                            px = (b, b, b, 255)
                        else:
                            i_ = (b & 0xF) * 17
                            px = (i_, i_, i_, ((b >> 4) & 0xF) * 17)
                        put(bx + x, by + y, px)
    elif fmt in (3, 4, 5):  # IA8 / RGB565 / RGB5A3
        for by in range(0, h, 4):
            for bx in range(0, w, 4):
                for y in range(4):
                    for x in range(4):
                        v = struct.unpack_from('>H', data, pos)[0]; pos += 2
                        if fmt == 4:
                            px = _rgb565(v)
                        elif fmt == 5:
                            px = _rgb5a3(v)
                        else:
                            px = (v & 0xFF,) * 3 + (v >> 8,)
                        put(bx + x, by + y, px)
    elif fmt == 6:          # RGBA8
        for by in range(0, h, 4):
            for bx in range(0, w, 4):
                ar = data[pos:pos + 32]; gb = data[pos + 32:pos + 64]
                pos += 64
                for y in range(4):
                    for x in range(4):
                        i2 = (y * 4 + x) * 2
                        put(bx + x, by + y, (ar[i2 + 1], gb[i2], gb[i2 + 1],
                                             ar[i2]))
    elif fmt == 14:         # CMPR: 8x8 tiles of four DXT1 4x4 sub-blocks
        for by in range(0, h, 8):
            for bx in range(0, w, 8):
                for sub in range(4):
                    sx, sy = bx + (sub & 1) * 4, by + (sub >> 1) * 4
                    c0, c1 = struct.unpack_from('>HH', data, pos)
                    bits = data[pos + 4:pos + 8]
                    pos += 8
                    p0, p1 = _rgb565(c0), _rgb565(c1)
                    if c0 > c1:
                        pal4 = [p0, p1,
                                tuple((2 * a + b) // 3 for a, b in zip(p0, p1)),
                                tuple((a + 2 * b) // 3 for a, b in zip(p0, p1))]
                    else:
                        pal4 = [p0, p1,
                                tuple((a + b) // 2 for a, b in zip(p0, p1)),
                                (0, 0, 0, 0)]
                    for y in range(4):
                        row = bits[y]
                        for x in range(4):
                            idx = (row >> (6 - 2 * x)) & 3
                            put(sx + x, sy + y, pal4[idx])
    else:
        raise ValueError(f'decode not implemented for format {fmt}')
    return out


def save_png(rows, path):
    from PIL import Image as PILImage
    h, w = len(rows), len(rows[0])
    im = PILImage.new('RGBA', (w, h))
    im.putdata([px for row in rows for px in row])
    im.save(path)


# --------------------------------------------------------------------------- #
# report                                                                       #
# --------------------------------------------------------------------------- #
def probe(path, dump_dir=None):
    dat = DatFile(path)
    print(f'{dat.path.name}: {dat.file_size} bytes, roots:')
    for name, off in dat.roots:
        print(f'  {name} @ 0x{off:X}')

    jobj_roots = [(n, o) for n, o in dat.roots
                  if n.endswith('_joint') and 'matanim' not in n
                  and 'shapeanim' not in n]
    mat_roots = dat.find_roots('_matanim_joint')

    listed = []
    for name, off in jobj_roots:
        listed = dat.jobj_textures(off)
        print(f'\nJOBJ tree ({name}): {len(listed)} material TOBJ images')
        for i, t in enumerate(listed):
            print(f'  [{i}] jobj {t.jobj_index} dobj {t.dobj_index} '
                  f'{t.image.width}x{t.image.height} '
                  f'{TEX_FMT.get(t.image.format, t.image.format)} '
                  f'data@0x{t.image.data_offset:X}')

    listed_keys = {t.image.data for t in listed}
    total_hidden = 0
    for name, off in mat_roots:
        texanims = dat.matanim_texanims(off)
        n_imgs = sum(len(t.images) for t in texanims)
        print(f'\nMatAnim tree ({name}): {len(texanims)} TexAnims, '
              f'{n_imgs} swap-frame images')
        for t in texanims:
            print(f'  joint {t.joint_index} matanim {t.matanim_index} '
                  f'texmap {t.texmap_id}: {len(t.images)} images, '
                  f'{len(t.tluts)} palettes')
            for i, img in enumerate(t.images):
                dup = 'SAME-AS-MATERIAL' if img.data in listed_keys else 'HIDDEN'
                if dup == 'HIDDEN':
                    total_hidden += 1
                print(f'    img[{i}] {img.width}x{img.height} '
                      f'{TEX_FMT.get(img.format, img.format)} '
                      f'data@0x{img.data_offset:X} {dup}')
                if dump_dir:
                    tlut = t.tluts[i] if i < len(t.tluts) else (
                        t.tluts[0] if t.tluts else None)
                    out = (Path(dump_dir) /
                           f'matanim_j{t.joint_index}m{t.matanim_index}'
                           f't{t.texmap_id}_f{i}.png')
                    out.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        save_png(decode_image(img, tlut), out)
                        print(f'      -> {out}')
                    except Exception as e:
                        print(f'      decode failed: {e}')
    print(f'\nTOTAL hidden MatAnim swap-frame images: {total_hidden}')
    return total_hidden


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    dump = None
    if '--dump-dir' in sys.argv:
        dump = sys.argv[sys.argv.index('--dump-dir') + 1]
    probe(sys.argv[1], dump)
