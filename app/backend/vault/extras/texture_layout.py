"""Copy one re-encoded texture into an archive without moving anything else.

HSDRawViewer's `--texture import` re-serializes the whole archive: unreferenced
data is dropped and every surviving block can move. The colour extras address
their bytes by vanilla offset (core/extra_types.py, vault/extras/color_patch.py),
so after a Falcon Punch fire hue the next colour write found nine of its ten
flare lines ambiguous and restore left 13 groups unresolved (bug 11-19,
app/scratch/bugs-2026-11-19/DIAGNOSIS.md section 1).

So the native import only ever runs on a temporary copy, and this module takes
just the target texture's encoded pixels (and palette) out of that copy and
writes them over the same bytes in the original archive:

  * the texture is found the way HSDRawViewer finds it: the named root, an
    effect table's `Models_<n>_/RootJoint`, then the JOBJ tree's material
    textures in its order (Program.cs NavigateToTexture /
    CollectTexturesFromJOBJ, the same order as datprobe.jobj_textures);
  * width, height, GX format, mipmap flag, palette format and colour count,
    and the payload length must all match; anything else is refused and
    nothing is written;
  * pixel and palette buffers are shared in vanilla files (seven of Falcon's
    image headers point at one buffer). HSDRaw edits a shared buffer in place
    (HSDStruct.SetBuffer), so every image using it changes, and writing the
    buffer once in place does the same. The result is then checked texture by
    texture against the native import for the whole model.
"""

import struct

from shared.rendering.datprobe import gx_image_size

HEADER = 0x20
JOBJ_SPLINE = 1 << 14
JOBJ_PTCL = 1 << 5
PALETTED = {8, 9, 10}           # CI4, CI8, CI14X2

# SBM_EffectTable: Models is an embedded array of 0x14-byte SBM_EffectModel
# entries at 0x08; SBM_EffectModel.RootJoint is the pointer at 0x04
# (HSDRaw/Melee/Ef/SBM_EffectTable.cs).
EFFECT_MODELS = 0x08
EFFECT_MODEL_SIZE = 0x14
EFFECT_ROOT_JOINT = 0x04


class TextureLayoutError(RuntimeError):
    """The texture cannot be replaced in place; nothing was written."""


class _Archive:
    """Just enough of an HSD archive to follow pointers: data offsets are
    relative to the data section, 0 is NULL unless the field is relocated."""

    def __init__(self, raw):
        if len(raw) < HEADER:
            raise TextureLayoutError('not an HSD archive')
        self.raw = bytes(raw)
        (_size, self.data_size, reloc_count, root_count, _refs) = struct.unpack_from('>5I', raw, 0)
        reloc_start = HEADER + self.data_size
        roots_start = reloc_start + reloc_count * 4
        if roots_start + root_count * 8 > len(raw):
            raise TextureLayoutError('truncated HSD archive')
        self.relocs = set(struct.unpack_from(f'>{reloc_count}I', raw, reloc_start))
        strings = roots_start + (root_count + _refs) * 8
        self.roots = {}
        for i in range(root_count):
            offset, name_off = struct.unpack_from('>II', raw, roots_start + i * 8)
            end = raw.index(b'\0', strings + name_off)
            self.roots[raw[strings + name_off:end].decode('ascii', 'replace')] = offset

    def u32(self, off):
        if off < 0 or off + 4 > self.data_size:
            raise TextureLayoutError(f'read outside the data section at 0x{off:X}')
        return struct.unpack_from('>I', self.raw, HEADER + off)[0]

    def u16(self, off):
        if off < 0 or off + 2 > self.data_size:
            raise TextureLayoutError(f'read outside the data section at 0x{off:X}')
        return struct.unpack_from('>H', self.raw, HEADER + off)[0]

    def ptr(self, off):
        value = self.u32(off)
        if value == 0 and off not in self.relocs:
            return None
        return value

    def bytes_at(self, off, length):
        if off < 0 or off + length > self.data_size:
            raise TextureLayoutError(f'buffer outside the data section at 0x{off:X}')
        return self.raw[HEADER + off:HEADER + off + length]


def _root_joint(archive, node_path):
    """The JOBJ a node path like effCaptainDataTable/Models_0_/RootJoint names."""
    parts = node_path.split('/')
    if len(parts) != 3 or parts[2] != 'RootJoint' or not parts[1].startswith('Models_') \
            or not parts[1].endswith('_'):
        raise TextureLayoutError(f'unsupported texture path {node_path!r}')
    try:
        model = int(parts[1][len('Models_'):-1])
    except ValueError:
        raise TextureLayoutError(f'unsupported texture path {node_path!r}') from None
    root = archive.roots.get(parts[0])
    if root is None:
        raise TextureLayoutError(f'no root {parts[0]!r}')
    field = root + EFFECT_MODELS + model * EFFECT_MODEL_SIZE + EFFECT_ROOT_JOINT
    if field not in archive.relocs:
        raise TextureLayoutError(f'{node_path} has no joint')
    return archive.ptr(field)


def model_textures(archive, node_path):
    """The TOBJ offsets under the node, in HSDRawViewer's texture-index order:
    a joint's materials (DObj list, then each MObj's TObj list, those with an
    image), then its child subtree, then its next sibling."""
    order, stack, seen = [], [_root_joint(archive, node_path)], set()
    while stack:
        jobj = stack.pop()
        if jobj is None or jobj in seen:
            continue
        seen.add(jobj)
        if not archive.u32(jobj + 0x04) & (JOBJ_SPLINE | JOBJ_PTCL):
            dobj = archive.ptr(jobj + 0x10)
            while dobj is not None:
                mobj = archive.ptr(dobj + 0x08)
                tobj = archive.ptr(mobj + 0x08) if mobj is not None else None
                while tobj is not None:
                    if archive.ptr(tobj + 0x4C) is not None:
                        order.append(tobj)
                    tobj = archive.ptr(tobj + 0x04)
                dobj = archive.ptr(dobj + 0x04)
        stack.append(archive.ptr(jobj + 0x0C))   # next, after the child subtree
        stack.append(archive.ptr(jobj + 0x08))   # child first
    return order


def _texture(archive, tobj):
    """(image header, pixel span, palette header or None, palette span or None);
    a span is (data offset, bytes)."""
    image = archive.ptr(tobj + 0x4C)
    width, height = archive.u16(image + 0x04), archive.u16(image + 0x06)
    gx_format, mipmap = archive.u32(image + 0x08), archive.u32(image + 0x0C)
    data = archive.ptr(image)
    if data is None:
        raise TextureLayoutError(f'texture at 0x{tobj:X} has no pixels')
    head = {'width': width, 'height': height, 'format': gx_format, 'mipmap': mipmap,
            'lod': archive.bytes_at(image + 0x10, 8)}
    pixels = (data, archive.bytes_at(data, gx_image_size(gx_format, width, height)))
    tlut = archive.ptr(tobj + 0x50)
    palette_head = palette = None
    if tlut is not None:
        palette_data = archive.ptr(tlut)
        count = archive.u16(tlut + 0x0C)
        palette_head = {'format': archive.u32(tlut + 0x04), 'count': count}
        if palette_data is not None:
            palette = (palette_data, archive.bytes_at(palette_data, count * 2))
    return head, pixels, palette_head, palette


def transplant_texture(original, imported, node_path, tex_index):
    """`original` with texture `tex_index` under `node_path` taken from
    `imported` (the same archive after HSDRaw's import). Only the texture's
    pixel and palette bytes change. Raises TextureLayoutError when it does not
    fit in place."""
    before, after = _Archive(original), _Archive(imported)
    old_list, new_list = model_textures(before, node_path), model_textures(after, node_path)
    if len(old_list) != len(new_list):
        raise TextureLayoutError('the import changed the model\'s texture list')
    if not 0 <= tex_index < len(old_list):
        raise TextureLayoutError(f'texture {tex_index} is out of range (0-{len(old_list) - 1})')
    old = _texture(before, old_list[tex_index])
    new = _texture(after, new_list[tex_index])
    if old[0] != new[0]:
        raise TextureLayoutError(
            f'the new texture is {new[0]["width"]}x{new[0]["height"]} format {new[0]["format"]}, '
            f'the archive holds {old[0]["width"]}x{old[0]["height"]} format {old[0]["format"]}')
    if old[0]['mipmap']:
        raise TextureLayoutError('mipmapped textures cannot be replaced in place')
    if old[2] != new[2] or (old[3] is None) != (new[3] is None):
        raise TextureLayoutError('the new texture\'s palette differs in format or size')
    if old[0]['format'] in PALETTED and old[3] is None:
        raise TextureLayoutError('a paletted texture without a palette')

    spans = [(old[1][0], new[1][1])]
    if old[3] is not None:
        spans.append((old[3][0], new[3][1]))
    result = bytearray(original)
    for offset, data in spans:
        result[HEADER + offset:HEADER + offset + len(data)] = data
    result = bytes(result)

    # Every texture of the model must now read exactly as the native import's:
    # a buffer shared with a texture that HSDRaw did not change shows up here.
    patched = _Archive(result)
    for tobj_old, tobj_new in zip(model_textures(patched, node_path), new_list):
        mine, theirs = _texture(patched, tobj_old), _texture(after, tobj_new)
        if (mine[0], mine[1][1], mine[2], mine[3] and mine[3][1]) != \
                (theirs[0], theirs[1][1], theirs[2], theirs[3] and theirs[3][1]):
            raise TextureLayoutError('a texture sharing these pixels would change differently '
                                     'from the native import')
    return result
