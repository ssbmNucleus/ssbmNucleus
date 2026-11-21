"""A Rivals 2 costume's pictures. The game draws a fighter's colours in its shader, not in its pictures: each material
has a plain grey base picture and up to three colour-region masks (`ColorRegionMask`, `2`, `3`: a region a channel,
red, green, blue), and the material's `CustomColorX`, `CustomColor0` .. `8` paint them. Which colour each takes is
the costume's palette (`Data/Palettes/<name>/PS_<short>_Default_<name>`: named slots, Body, Belly, Hair ...), through
the skin's table of which slot each material's colour is (`Skin_<short>_Default.BaseMaterialSlotCustomColorAssignments`).
A costume of the game is a palette (the game's own recolours, not tints: checklist 1).

The picture Melee draws is made here once per material and palette (READING of the shader, `MAT_Cha_Standard`, whose
graph is not read): the masks laid in order, colour X under all, then colour N over what is under it as much as
mask channel N says (CM red is 0, green 1, blue 2, CM2 red 3 ...), the base picture's light and dark kept (it is
mid grey: x2), and its ambient occlusion (ORMS red) multiplied in. The normal map, the toon ramp and the rim light are
not carried (STAND-IN: a flat colour picture).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

MASKS = ('ColorRegionMask', 'ColorRegionMask2', 'ColorRegionMask3')
SIDE = 512                      # the pictures are written at this side (the game's are 1024; the route makes them smaller anyway)
# Preferred costume order: default, team colours, then extras that actually exist for this fighter.
COSTUMES = ('Neutral', 'Red', 'Blue', 'Green', 'Black', 'Gold')


def hex_color(h):
    h = h[-6:]
    return np.array([int(h[k:k + 2], 16) / 255.0 for k in (0, 2, 4)])


def params(pak, pkg):
    """Resolved texture packages and display-space colors, including master defaults."""
    from . import materials
    data = materials.read(pak, pkg)
    return data['texture'], {name: materials.srgb(materials.linear_rgb(v)) for name, v in data['vector'].items()}


def palette(pak, short, name):
    """{slot name: rgb} of one of the default skin's palettes."""
    pkg = pak.find(f'PS_{short}_Default_{name}')
    return {r['Key']: hex_color(r['Value']['Hex']) for r in pak.default(pkg).get('CustomColorSlotDefinitions') or []}


def assignments(pak, short):
    """{material slot: {CustomColorN: palette slot}} from the default skin."""
    p = pak.default(pak.find(f'Skin_{short}_Default'))
    return {r['Key']: {x['Key']: x['Value'] for x in r['Value']['MaterialParameterColorSlotNames']}
            for r in p.get('BaseMaterialSlotCustomColorAssignments') or []}


def load_picture(pak, pkg, out):
    from PIL import Image
    files = pak.export([pkg], out)[pkg]
    png = next(f for f in files if f.endswith('.png'))
    return Image.open(png).convert('RGBA')


def picture(pak, material_pkg, slot, assign, pal, out, report=None):
    """The picture of one material in one palette (see the head). -> (PIL picture, words on how)."""
    from PIL import Image
    from . import materials
    data = materials.read(pak, material_pkg)
    tex = data['texture']
    colors = {name: materials.srgb(materials.linear_rgb(v)) for name, v in data['vector'].items()}
    elemental, adaptation = materials.elemental_colors(data)
    colors.update(elemental)
    for param, slot_name in (assign.get(slot) or {}).items():
        if slot_name in pal:
            colors[param] = pal[slot_name]
    # Packed mask channels are independent data. RGBA resizing premultiplies by
    # alpha and erases RGB when the unused fourth channel is zero.
    masks = {i: np.asarray(load_picture(pak, tex[m], out).convert('RGB').resize((SIDE, SIDE)), float) / 255.0
             for i, m in enumerate(MASKS) if m in tex}
    base = np.asarray(load_picture(pak, tex['BaseColor'], out).convert('RGB').resize((SIDE, SIDE)), float)[..., :3] / 255.0 \
        if 'BaseColor' in tex else np.full((SIDE, SIDE, 3), 0.5)
    c = np.zeros((SIDE, SIDE, 3)) + colors.get('CustomColorX', colors.get('CustomColor0', np.array([0.5, 0.5, 0.5])))
    for index, m in masks.items():
        for ch in range(3):
            key = f'CustomColor{index * 3 + ch}'
            if key in colors:
                w = m[..., ch:ch + 1]
                c = c * (1 - w) + colors[key] * w
    c = c * np.clip(base * 2.0, 0.0, 2.0)
    if 'ORMS' in tex:
        orms = np.asarray(load_picture(pak, tex['ORMS'], out).convert('RGB').resize((SIDE, SIDE)), float) / 255.0
        c = c * (0.35 + 0.65 * orms[..., :1])
    img = Image.fromarray(np.rint(np.clip(c, 0, 1) * 255).astype(np.uint8), 'RGB').convert('RGBA')
    if report is not None:
        report.append(dict(slot=slot, material=material_pkg, source=data,
                           elemental=adaptation, approximation='flat color/ambient-occlusion bake'))
    return img, f'{len(masks)} masks, {sum(1 for k in colors if k.startswith("CustomColor"))} colours'


def palette_names(pak, short, limit=6):
    """Default-skin palettes present in this fighter's pak, in stable Melee-friendly order.

    Gold is Zetterburn's palette, not an engine-wide requirement (Ranno has no Gold asset).
    Keep the existing preferred choices where present, then fill from other real palettes.
    """
    prefix = f'PS_{short}_Default_'
    available = {Path(f).stem[len(prefix):] for f in pak.files()
                 if f.endswith('.uasset') and Path(f).name.startswith(prefix)}
    if 'Neutral' not in available:
        raise ValueError(f'{short}: no Neutral default-skin palette in the pak')
    ordered = [n for n in COSTUMES if n in available]
    ordered += sorted(available - set(ordered))
    return ordered[:limit]


def costumes(pak, short, materials, slots, out, names=None, log=print, report=None):
    """[(palette name, {material index: picture})] for each costume. `materials`: the body's material packages in
    the mesh's order, `slots` their slot names."""
    assign = assignments(pak, short)
    out = Path(out)
    rows = []
    for name in palette_names(pak, short) if names is None else names:
        pal = palette(pak, short, name)
        pics, bakes = {}, []
        for k, (pkg, slot) in enumerate(zip(materials, slots)):
            pics[k], how = picture(pak, pkg, slot, assign, pal, out, bakes)
        rows.append((name, pics))
        if report is not None:
            report.append(dict(palette=name, materials=bakes))
        log(f'  palette {name}: {len(pics)} pictures')
    return rows
