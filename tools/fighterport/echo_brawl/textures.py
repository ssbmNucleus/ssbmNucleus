"""A Brawl costume's textures (TEX0, with a palette in PLT0 where it has one) as pictures.

A fighter's costumes are files of the same model with other textures under the same names (FitIke00.pac,
FitIke01.pac, ...), so a costume's pictures by name are what a recolour is made from.

The pixel formats are the GameCube's own, which the app already decodes (`shared.rendering.datprobe`).
"""
from __future__ import annotations

import re
import struct
from pathlib import Path
from types import SimpleNamespace

from . import arc, brres

TEXTURES, PALETTES = 'Textures(NW4R)', 'Palettes(NW4R)'


def _texture(data, at):
    """A TEX0's header -> (width, height, format, where its pixels start, whether it has a palette)."""
    start, _name, palette, width, height, fmt = struct.unpack_from('>iiIHHI', data, at + 0x10)
    return width, height, fmt, at + start, bool(palette)


def _palette(data, at):
    """A PLT0 -> what the decoder takes for one (its format: 0 grey and alpha, 1 RGB565, 2 RGB5A3)."""
    start, _name, fmt, count = struct.unpack_from('>iiIH', data, at + 0x10)
    return SimpleNamespace(format=fmt, count=count, data=data[at + start:at + start + count * 2])


def pictures(data: bytes):
    """{texture name: RGBA picture} of a BRRES."""
    from PIL import Image
    from shared.rendering import datprobe
    found = brres.folders(data)
    palettes = found.get(PALETTES, {})
    out = {}
    for name, at in found.get(TEXTURES, {}).items():
        width, height, fmt, start, has_palette = _texture(data, at)
        size = struct.unpack_from('>I', data, at + 4)[0]
        image = SimpleNamespace(width=width, height=height, format=fmt, data=data[start:at + size])
        table = _palette(data, palettes[name]) if has_palette and name in palettes else None
        rows = datprobe.decode_image(image, table)
        picture = Image.new('RGBA', (width, height))
        picture.putdata([px for row in rows for px in row])
        out[name] = picture
    return out


def costume_files(root, fighter):
    """{costume number: file} of the fighter's costumes on the extracted disc (FitIke00.pac is 0)."""
    from .gamedata import find
    folder, stem = find(root, fighter)
    out = {}
    for path in sorted(Path(folder).glob(f'{stem}[0-9][0-9].pac')):
        out[int(re.search(r'(\d\d)\.pac$', path.name)[1])] = path
    return out


def costumes(root, fighter):
    """{costume number: {texture name: picture}} for every costume of the fighter."""
    out = {}
    for number, path in costume_files(root, fighter).items():
        _name, files = arc.read(path.read_bytes())
        found = {}
        for f in files:                                 # the model and its textures are files of their own in it
            if f['data'][:4] == b'bres' and TEXTURES in brres.folders(f['data']):
                found.update(pictures(f['data']))
        if found:
            out[number] = found
    return out


def wraps(root, fighter):
    """{texture name: (across, down)} as the materials of the fighter's first costume draw each (0 clamp, 1 repeat,
    2 mirror). A texture drawn more than one way keeps the first."""
    import struct
    files = costume_files(root, fighter)
    if not files:
        return {}
    out = {}
    for f in arc.read(files[min(files)].read_bytes())[1]:
        data = f['data']
        if data[:4] != b'bres':
            continue
        for mdl in brres.folders(data).get('3DModels(NW4R)', {}).values():
            sections = struct.unpack_from('>11i', data, mdl + 0x10)
            if not sections[6]:
                continue
            for _name, at in brres._group(data, mdl + sections[6]):       # the materials
                count, first = struct.unpack_from('>ii', data, at + 0x2C)
                for i in range(count):
                    ref = at + first + i * 0x34
                    name = brres._text(data, ref + struct.unpack_from('>i', data, ref)[0])
                    out.setdefault(name, tuple(struct.unpack_from('>II', data, ref + 0x18)))
    return out


def trail_picture(root, fighter):
    """The picture the fighter's own sword trail is drawn with (TexIkeSwordTrace in effect/fighter/ef_ike.pac), or
    None: no such file on the extracted disc, or no picture of that kind in it."""
    path = next(iter(sorted(Path(root).rglob(f'ef_{fighter}.pac'))), None)
    if path is None:
        return None
    for f in arc.read(path.read_bytes())[1]:
        if f['data'][:4] == b'bres' and TEXTURES in brres.folders(f['data']):
            found = pictures(f['data'])
            name = next((n for n in sorted(found) if n.lower().endswith('trace')), None)
            if name:
                return found[name]
    return None
