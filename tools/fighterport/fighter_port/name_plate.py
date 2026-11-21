"""The character-select cell of an added fighter: the game's own frame and name plate around new art.

A 64x56 css/icon asset is a whole roster cell. `css_cell` rebuilds one from a vanilla cell, so the frame and the
plate stay byte-identical to the game's own tiles either side of it, and sets the fighter's name on the plate in
letters cut from the vanilla plates (`glyph_bank`). `harness/roster_tile.py` composes the packaged port's tile
with it. (Moved here from the Pokemon Trainer campaign, which is kept under the tag
archive/fighterport-character-specific-2026-11.)
"""
from pathlib import Path

import numpy as np


def _open(src):
    from PIL import Image
    if hasattr(src, 'mode'):
        return src.convert('RGBA')
    return Image.open(src).convert('RGBA')


# A 64x56 css/icon asset is the whole cell, not a portrait: a 3px rounded grey
# frame, a 58x38 art window, and a baked name plate. Rebuilding it from a
# vanilla cell keeps the frame and the plate byte-identical to the ones either
# side of it on the screen.
CSS_CONTENT = (3, 3, 61, 41)       # x0, y0, x1, y1 of the art window
CSS_PLATE = (41, 53)               # plate rows
CSS_TEXT = (3, 43, 61, 51)         # text band inside the plate
# icon_007 (Ness) is the template: its frame band is 100% neutral grey (no
# costume colour bleeds into row 2 or columns 2/61), and its short name leaves
# a clean plate column to rebuild the plate from.
CSS_TEMPLATE = 'icon_007.png'
CSS_PLATE_COLUMN = 4
# Melee's CSS name font, cut from the vanilla plates. A..Z minus J/Q/V --
# no vanilla fighter name contains them, so no glyph exists to cut.
GLYPH_SOURCES = {
    'icon.png': 'MARIO', 'icon_001.png': 'FOX', 'icon_004.png': 'KIRBY',
    'icon_007.png': 'NESS', 'icon_010.png': 'PIKACHU', 'icon_011.png': 'SAMUS',
    'icon_016.png': 'MARTH', 'icon_017.png': 'ZELDA', 'icon_024.png': 'ROY',
}


def _icon_rgba(css_dir, name):
    from PIL import Image
    return np.asarray(Image.open(Path(css_dir) / name).convert('RGBA')).astype(np.uint8)


def _segment_plate(css_dir, name):
    """Glyph column runs in one vanilla name plate."""
    band = _icon_rgba(css_dir, name)[CSS_TEXT[1]:CSS_TEXT[3],
                                     CSS_TEXT[0]:CSS_TEXT[2], :3].astype(int)
    cols = (band.mean(axis=2) > 110).any(axis=0)
    runs, start = [], None
    for i, v in enumerate(cols):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(cols)))
    merged = []
    for run in runs:
        # a 1px gap is inside a glyph (M, W); letter spacing is >= 2
        if merged and run[0] - merged[-1][1] < 2:
            merged[-1] = (merged[-1][0], run[1])
        else:
            merged.append(run)
    return merged


def glyph_bank(css_dir):
    """{letter: HxWx4 pixels} cut straight out of the vanilla name plates, so
    the text we draw is the game's own font at the game's own antialiasing --
    not a lookalike."""
    bank = {}
    for name, word in GLYPH_SOURCES.items():
        if not (Path(css_dir) / name).exists():
            continue
        runs = _segment_plate(css_dir, name)
        if len(runs) != len(word):
            continue                      # ambiguous segmentation: skip it
        icon = _icon_rgba(css_dir, name)
        for ch, (a, b) in zip(word, runs):
            bank.setdefault(ch, icon[CSS_TEXT[1]:CSS_TEXT[3],
                                     CSS_TEXT[0] + a:CSS_TEXT[0] + b].copy())
    return bank


def name_plate_width(word, bank, tracking=2):
    return (sum(bank[c].shape[1] for c in word)
            + tracking * (len(word) - 1)) if word else 0


def css_cell(art, css_dir, *, word, tracking=2, template=None):
    """A finished 64x56 css/icon: vanilla frame, `art` in the window, `word`
    on the name plate in the game's own font."""
    from PIL import Image
    template = template or CSS_TEMPLATE
    out = _icon_rgba(css_dir, template).copy()
    x0, y0, x1, y1 = CSS_CONTENT

    art = _open(art)
    window = (x1 - x0, y1 - y0)
    if art.size != window:
        art = art.copy()
        art.thumbnail(window, Image.LANCZOS)
    pane = Image.new('RGBA', window, (0, 0, 0, 0))
    pane.alpha_composite(art, ((window[0] - art.width) // 2,
                               window[1] - art.height))
    out[y0:y1, x0:x1] = np.asarray(pane)

    column = _icon_rgba(css_dir, template)[CSS_PLATE[0]:CSS_PLATE[1],
                                           CSS_PLATE_COLUMN:CSS_PLATE_COLUMN + 1]
    out[CSS_PLATE[0]:CSS_PLATE[1], x0:x1] = np.repeat(column, x1 - x0, axis=1)

    bank = glyph_bank(css_dir)
    missing = [c for c in word if c not in bank]
    if missing:
        raise KeyError(f'no vanilla glyph for {missing} (Melee has no J/Q/V '
                       f'in any fighter name, so those letters cannot be cut)')
    width = name_plate_width(word, bank, tracking)
    if width > x1 - x0:
        raise ValueError(f'"{word}" is {width}px; the plate holds {x1 - x0}px')
    x = x0 + ((x1 - x0) - width) // 2
    for ch in word:
        glyph = bank[ch]
        h, w = glyph.shape[:2]
        region = out[CSS_TEXT[1]:CSS_TEXT[1] + h, x:x + w]
        ink = glyph[..., :3].mean(axis=2) > 40
        region[ink] = glyph[ink]
        x += w + tracking
    return Image.fromarray(out, 'RGBA')
