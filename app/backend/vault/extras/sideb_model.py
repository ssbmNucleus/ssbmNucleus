"""Falco's static Phantasm afterimage, isolated from the rest of PlFc.dat.

Spooky Phantasm replaces article 3's one-joint, untextured mesh. It is not
an image shine and cannot be represented by three color operands. Copy only
that validated model graph; leave the target article's attributes, states,
animations, blaster and every other fighter field alone.

The supported subset is intentionally small: one static joint, one DObj and
one unskinned PObj, indexed POS/NRM and optional texture coordinates (no
textures). Unknown structures are refused. Display-list indices determine
the exact array bytes to copy, including a relocated pointer to offset zero.
"""
import hashlib
import math
import struct
from pathlib import Path

import file_retry

from .effect_model import EffectDat, EffectModelError


MAGIC = b'NUCSIDEB'
HEADER_SIZE = 64
MAX_DATA = 16 * 1024 * 1024
# Retail PlFc's supported model, ignoring its three editable RGBA colors.
# A rebuilt archive keeps the same signature; geometry/alpha/flags do not.
COLOR_MODEL_SIGNATURE = '9fdcf560a7d7373fcff67c24435e3222b6bf32fa9c082fbe9a89a50f3bb87ea0'


class SideBModelError(ValueError):
    pass


def supports(config):
    return bool(config.get('afterimage_model'))


def is_model_mod(mod):
    return bool((mod.get('modifications') or {}).get('sideb_model'))


class Model:
    def __init__(self, raw):
        try:
            self.dat = d = EffectDat(raw)
        except (EffectModelError, struct.error) as error:
            raise SideBModelError(f'Invalid Phantasm DAT: {error}') from error
        if (len(d.data) > MAX_DATA or len(d.roots) != 1 or d.refs
                or d.root_name() != 'ftDataFalco'):
            raise SideBModelError('Side-B model import requires an ftDataFalco DAT')
        if any(r % 4 or r + 4 > len(d.data) or d.u32(r) >= len(d.data)
               for r in d.relocs):
            raise SideBModelError('Invalid Phantasm DAT relocation')
        self.nodes = {}
        self.links = {}
        self.material = None
        root = d.roots[0][0]
        self.bound(root, 0x60)
        articles = self.pointer(root + 0x48)
        self.bound(articles, 16)
        article = self.pointer(articles + 12)  # ftFc_Init_OnLoad: items[3]
        self.bound(article, 0x18)
        self.model_slot = self.pointer(article + 0x10)
        self.bound(self.model_slot, 16)
        if d.data[self.model_slot + 4:self.model_slot + 16] != bytes(12):
            raise SideBModelError('Unsupported Phantasm model attachment')
        self.joint = self.pointer(self.model_slot)
        self.node(self.joint, 0x40, (16,))
        j = self.joint
        # No child, sibling, envelope, IK or render-object dependencies.
        if any(d.u32(j + off) for off in (0, 8, 12, 0x38, 0x3c)):
            raise SideBModelError('Phantasm must have one static model joint')
        if d.u32(j + 4) & ~0x701C01C8:
            raise SideBModelError('Unsupported Phantasm joint flags')
        if any(not math.isfinite(d.f32(j + off)) or abs(d.f32(j + off)) > 1e6
               for off in range(0x14, 0x38, 4)):
            raise SideBModelError('Invalid Phantasm model transform')
        obj = self.pointer(j + 16)
        self.node(obj, 16, (8, 12))
        if d.u32(obj) or d.u32(obj + 4):
            raise SideBModelError('Phantasm must have one unnamed mesh')
        material = self.pointer(obj + 8)
        self.node(material, 24, (12, 20))
        if any(d.u32(material + off) for off in (0, 8, 16)):
            raise SideBModelError('Textured or custom-shader Phantasm models are unsupported')
        if d.u32(material + 4) != 0x60000004:
            raise SideBModelError('Unsupported Phantasm material render mode')
        self.material = self.pointer(material + 12)
        self.node(self.material, 20)
        alpha, shininess = d.f32(self.material + 12), d.f32(self.material + 16)
        if not 0 <= alpha <= 1 or not math.isfinite(shininess):
            raise SideBModelError('Invalid Phantasm material')
        pe = self.pointer(material + 20, optional=True)
        if pe is not None:
            self.node(pe, 12)
        pobj = self.pointer(obj + 12)
        self.pobj = pobj
        self.node(pobj, 24, (8, 16))
        if d.u32(pobj) or d.u32(pobj + 4) or d.u32(pobj + 20):
            raise SideBModelError('Linked or skinned Phantasm meshes are unsupported')
        if d.u16(pobj + 12) & ~0xC000:  # only cull-front / cull-back
            raise SideBModelError('Animated Phantasm mesh bindings are unsupported')
        attributes = self.pointer(pobj + 8)
        attrs = []
        for index in range(16):
            at = attributes + index * 24
            self.bound(at, 24)
            attr, kind, count, scalar = struct.unpack_from('>4I', d.data, at)
            if attr == 255:
                self.node(attributes, (index + 1) * 24,
                          tuple(i * 24 + 20 for i in range(index)))
                break
            if (attr not in (9, 10, 13, 14, 15, 16, 17, 18, 19, 20)
                    or kind not in (2, 3) or scalar not in range(5)):
                raise SideBModelError('Unsupported Phantasm vertex attribute')
            if (attr == 9 and count not in (0, 1)
                    or attr == 10 and (count != 0 or scalar not in (1, 3, 4))
                    or attr >= 13 and count not in (0, 1)):
                raise SideBModelError('Unsupported Phantasm vertex components')
            components = (2 + count) if attr == 9 else (3 if attr == 10 else 1 + count)
            stride = d.u16(at + 18)
            minimum = components * (1, 1, 2, 2, 4)[scalar]
            if stride < minimum or stride > 256:
                raise SideBModelError('Invalid Phantasm vertex stride')
            attrs.append((at, attr, kind - 1, stride))
        else:
            raise SideBModelError('Unterminated Phantasm vertex attributes')
        names = [a[1] for a in attrs]
        if names[:2] != [9, 10] or names != sorted(set(names)):
            raise SideBModelError('Phantasm requires indexed position and normal arrays')
        display = self.pointer(pobj + 16)
        display_size = d.u16(pobj + 14) * 32
        if not display_size:
            raise SideBModelError('Empty Phantasm mesh')
        self.node(display, display_size, align=32)
        cursor, end = display, display + display_size
        maxima = [-1] * len(attrs)
        while cursor < end:
            opcode = d.data[cursor]
            if opcode == 0:
                if any(d.data[cursor:end]):
                    raise SideBModelError('Unexpected Phantasm display-list padding')
                break
            if opcode not in (0x80, 0x90, 0x98, 0xA0, 0xA8, 0xB0, 0xB8) or cursor + 3 > end:
                raise SideBModelError('Unsupported Phantasm display-list command')
            count = d.u16(cursor + 1)
            cursor += 3
            if cursor + count * sum(a[2] for a in attrs) > end:
                raise SideBModelError('Truncated Phantasm display list')
            for _ in range(count):
                for i, (_, _, width, _) in enumerate(attrs):
                    value = d.data[cursor] if width == 1 else d.u16(cursor)
                    maxima[i] = max(maxima[i], value)
                    cursor += width
        if any(value < 0 for value in maxima):
            raise SideBModelError('Empty Phantasm geometry')
        for (at, _, _, stride), maximum in zip(attrs, maxima):
            self.node(self.pointer(at + 20), (maximum + 1) * stride, align=32)
        ordered = sorted((off, off + size) for off, (size, _) in self.nodes.items())
        if any(left[1] > right[0] for left, right in zip(ordered, ordered[1:])):
            raise SideBModelError('Overlapping Phantasm model blocks are unsupported')
        # Every reference in the accepted graph must be explicitly described.
        for off, (size, _) in self.nodes.items():
            for r in d.relocs:
                if off <= r < off + size and r not in self.links:
                    raise SideBModelError('Unsupported pointer in Phantasm model data')

    def bound(self, offset, size):
        if offset is None or offset < 0 or size <= 0 or offset + size > len(self.dat.data):
            raise SideBModelError('Phantasm model points outside its DAT')

    def pointer(self, offset, optional=False):
        self.bound(offset, 4)
        if offset not in self.dat.relocs:
            if optional and self.dat.u32(offset) == 0:
                return None
            raise SideBModelError('Missing Phantasm model pointer')
        return self.dat.u32(offset)

    def node(self, offset, size, fields=(), align=4):
        self.bound(offset, size)
        if offset in self.nodes:
            old_size, old_align = self.nodes[offset]
            size, align = max(size, old_size), max(align, old_align)
        self.nodes[offset] = (size, align)
        for relative in fields:
            r = offset + relative
            target = self.pointer(r, optional=True)
            if target is not None:
                self.links[r] = target

    def append_to(self, target):
        mapping = {}
        # Preserve source alignment for display lists and indexed arrays.
        for offset, (size, align) in self.nodes.items():
            mapping[offset] = target.append(self.dat.data[offset:offset + size], align)
        for field, value in self.links.items():
            owner = next((o for o, (size, _) in self.nodes.items() if o <= field < o + size), None)
            if owner is None or value not in mapping:
                raise SideBModelError('Unresolved Phantasm model reference')
            target.set_ptr(mapping[owner] + field - owner, mapping[value])
        return mapping[self.joint]

    def signature(self):
        # Offset-independent, useful for source fidelity and native round trips.
        empty = bytearray(32)
        struct.pack_into('>I', empty, 0, 32)
        result = EffectDat(empty)
        joint = self.append_to(result)
        return hashlib.sha256(bytes(result.data) + struct.pack('>I', joint)).hexdigest()

    def color_layout_signature(self):
        colors = self.dat.data[self.material:self.material + 12]
        self.dat.data[self.material:self.material + 12] = bytes(12)
        try:
            return self.signature()
        finally:
            self.dat.data[self.material:self.material + 12] = colors


def read_model(raw):
    return Model(raw)


def recipe(raw):
    model = read_model(raw)
    return {'sideb_model': {'version': 1, 'sha256': model.signature()}}


def replacement_recipe(raw):
    model = read_model(raw)
    if model.color_layout_signature() == COLOR_MODEL_SIGNATURE:
        return {}
    return {'sideb_model': {'version': 1, 'sha256': model.signature()}}


def colors(raw):
    model = read_model(raw)
    if model.color_layout_signature() != COLOR_MODEL_SIGNATURE:
        raise SideBModelError('This Phantasm contains a replacement model, not a color recipe')
    return {key: bytes(model.dat.data[model.material + i * 4:model.material + i * 4 + 4]).hex().upper()
            for i, key in enumerate(('primary', 'secondary', 'tertiary'))}


def _serialize(dat, original):
    raw = bytearray(dat.to_bytes())
    raw[20:32] = original[20:32]  # retain the DAT version/reserved header bytes
    return bytes(raw)


def _revert(dat, model_slot):
    offset = bytes(dat.data).rfind(MAGIC)
    if offset < 0:
        return False
    if offset + HEADER_SIZE > len(dat.data):
        raise SideBModelError('Damaged Phantasm restore record')
    version, original_size, end, slot, original, installed = struct.unpack_from('>6I', dat.data, offset + 8)
    if (version != 1 or slot != model_slot or original_size != offset
            or end != len(dat.data) or original >= offset or slot + 4 > offset
            or dat.ptr(slot) != installed):
        raise SideBModelError('Phantasm was changed after installation; cannot safely undo its append')
    for r in dat.relocs:
        if r < offset and r != slot and dat.u32(r) >= offset:
            raise SideBModelError('Another model references the installed Phantasm')
    if any(p >= offset for p, _ in dat.roots + dat.refs):
        raise SideBModelError('Another archive root references the installed Phantasm')
    del dat.data[offset:]
    dat.data_size = len(dat.data)
    dat.relocs = {r for r in dat.relocs if r < offset}
    dat.set_ptr(slot, original)
    return True


def install(raw, source):
    donor = read_model(source)
    target = read_model(raw)
    if donor.signature() == target.signature():
        return raw
    dat, slot = target.dat, target.model_slot
    try:
        _revert(dat, slot)
    except SideBModelError:
        # A native rebuild may relocate a retained, unreferenced record.
        # Never truncate on stale offsets. A new isolated model append is
        # safe: only the currently validated model pointer is changed.
        pass
    original = dat.ptr(slot)
    offset = dat.append(bytes(HEADER_SIZE))
    joint = donor.append_to(dat)
    dat.align_to(4)
    struct.pack_into('>8s6I', dat.data, offset, MAGIC, 1, offset,
                     len(dat.data), slot, original, joint)
    dat.set_ptr(slot, joint)
    return _serialize(dat, raw)


def revert(raw):
    target = read_model(raw)
    if not _revert(target.dat, target.model_slot):
        return raw
    return _serialize(target.dat, raw)


def _write(path, raw):
    patch = path.with_name(path.name + '.patching')
    patch.write_bytes(raw)
    file_retry.replace(patch, path)


def install_mod(path, storage, mod):
    relative = mod.get('model_file', '')
    source = (Path(storage) / relative).resolve()
    if (not relative or source.suffix.lower() != '.dat'
            or not source.is_relative_to(Path(storage).resolve())):
        raise SideBModelError('Invalid stored Phantasm model path')
    _write(path, install(path.read_bytes(), source.read_bytes()))


def _restored(raw):
    try:
        restored = revert(raw)
    except SideBModelError:
        restored = raw
    if replacement_recipe(restored):
        # A native DAT rebuild can discard the unreferenced append record.
        # Restore only the vanilla afterimage, never overwrite the fighter DAT.
        from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
        reference = ensure_vanilla_ref('PlFc.dat')
        if not reference:
            raise SideBModelError('A vanilla PlFc.dat reference is required to restore this afterimage')
        vanilla = Path(reference).read_bytes()
        if replacement_recipe(vanilla):
            raise SideBModelError('The Phantasm restore reference is not vanilla')
        restored = install(restored, vanilla)
    return restored


def revert_installed(path):
    raw = path.read_bytes()
    restored = _restored(raw)
    if restored != raw:
        _write(path, restored)
        return True
    return False


def apply_colors(path, modifications):
    """Restore the original mesh and edit its live material atomically.

    An append/native rebuild can leave unreachable old material bytes in the
    DAT. Scanning for the old marker would recolor those instead of the model
    the game draws; follow the article's active joint pointer instead.
    """
    selected = {}
    for index, key in enumerate(('primary', 'secondary', 'tertiary')):
        value = modifications.get(key, {}).get('color')
        if value:
            try:
                encoded = bytes.fromhex(value)
            except (TypeError, ValueError) as error:
                raise SideBModelError('Phantasm colors must be RGBA hex values') from error
            if len(encoded) != 4:
                raise SideBModelError('Phantasm colors must contain four RGBA bytes')
            selected[index] = encoded
    if not selected:
        raise SideBModelError('No Phantasm colors were provided')
    original = path.read_bytes()
    restored = _restored(original)
    model = read_model(restored)
    colors(restored)  # prove the active layout is the supported color model
    for index, value in selected.items():
        start = model.material + index * 4
        model.dat.data[start:start + 4] = value
    output = _serialize(model.dat, original)
    if output != original:
        _write(path, output)
    return len(selected)
