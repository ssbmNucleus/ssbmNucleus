"""The roster tile of a packaged port: the game's own frame and name plate, the background its own tiles have,
the fighter's face filling the window (no drop shadow, lit as the game's tiles are), its name in the game's letters.

roster_tile(portrait_png_bytes, word, css_dir) -> PNG bytes, or None when the game's own tiles are not at hand
or the name has a letter no fighter of the game's has (the caller then keeps its plain crop).
"""
import io
import sys
import _where  # noqa: E402
from collections import Counter
from pathlib import Path

VANILLA = ('icon_024.png', 'icon_016.png', 'icon_017.png', 'icon.png', 'icon_001.png')   # tiles to learn the background from


SLATE = (60, 65, 96)        # the blue-grey the game's roster panel shows behind its own fighters' tiles


def background(css_dir, pres, window_box):
    """What goes behind the fighter. The game's own tiles are see-through there and its roster panel shows a
    blue-grey behind them; an added fighter's tile is drawn over a darker hatched square instead, so the tile
    carries that blue-grey itself. (If the game's tiles at hand are not see-through, their own colour is used.)"""
    import numpy as np
    x0, y0, x1, y1 = window_box
    seen = Counter()
    for name in VANILLA:
        if (Path(css_dir) / name).exists():
            win = pres._icon_rgba(css_dir, name)[y0:y1, x0:x1]
            for patch in (win[3:10, 4:11], win[3:10, -11:-4]):
                seen.update(tuple(int(v) // 8 * 8 + 4 for v in px[:3]) if px[3] > 127 else None for px in patch.reshape(-1, 4))
    top = seen.most_common(1)[0][0] if seen else None
    return np.array(top if top else SLATE, np.uint8)


def roster_tile(portrait_png, word, css_dir):
    import numpy as np
    from PIL import Image
    sys.path.insert(0, str(_where.PORT_REPO))
    from fighter_port import name_plate as pres
    css_dir = Path(css_dir)
    if not (css_dir / pres.CSS_TEMPLATE).exists():
        print('  no vanilla roster tiles at', css_dir, '- the plain crop is used', flush=True)
        return None
    words = plate_words(word)
    if not any(all(c in pres.glyph_bank(css_dir) for c in w) for w in words):
        print('  the name has a letter the game has no glyph for - the plain crop is used', flush=True)
        return None
    x0, y0, x1, y1 = pres.CSS_CONTENT
    window = (x1 - x0, y1 - y0)
    im = Image.open(io.BytesIO(portrait_png)).convert('RGBA')
    a = np.asarray(im).copy()
    # the figure without its drop shadow (the shadow is see-through, the figure is not), edges kept soft
    alpha = np.clip((a[..., 3].astype(float) - 200.0) / 55.0, 0.0, 1.0)
    a[..., 3] = (alpha * 255).astype(np.uint8)
    solid = alpha > 0.5
    ys, xs = np.nonzero(solid)
    top, tall = int(ys.min()), int(ys.max() - ys.min())
    # the face: the game's tiles are close on it, the top of the hair cut off. The portrait is a bust, its head
    # the top two fifths: the window takes a third of the bust's height from a little under the hair's top,
    # centred where most of the head is (a few long spikes of hair do not pull it aside)
    high = max(8, round(tall * 0.33))
    wide = min(im.width, round(high * window[0] / window[1]))
    high = round(wide * window[1] / window[0])
    first = top + round(tall * 0.07)
    head = solid[top + round(tall * 0.12):top + round(tall * 0.32)]         # the face's rows, under the hair's top
    centre = float((head.sum(axis=0) * np.arange(head.shape[1])).sum() / max(1, head.sum()))
    left = int(min(max(centre - wide / 2, 0), im.width - wide))
    crop = a[first:first + high, left:left + wide].astype(float)
    # lit as the game's tiles are: the brightest of the figure brought near white, the middle lifted, colour a little fuller
    rgb, on = crop[..., :3], crop[..., 3] > 127
    if on.any():
        peak = np.percentile(rgb[on].max(axis=1), 98)
        rgb = np.clip(rgb * (238.0 / max(peak, 1.0)), 0, 255)
        rgb = 255.0 * (rgb / 255.0) ** 0.82
        grey = rgb.mean(axis=2, keepdims=True)
        rgb = np.clip(grey + (rgb - grey) * 1.2, 0, 255)
    crop[..., :3] = rgb
    art = Image.fromarray(crop.astype(np.uint8), 'RGBA').resize(window, Image.LANCZOS)
    back = np.zeros((window[1], window[0], 4), np.uint8)
    back[..., :3] = background(css_dir, pres, pres.CSS_CONTENT)
    back[..., 3] = 255
    pane = Image.fromarray(back, 'RGBA')
    pane.alpha_composite(art)
    glyphs = pres.glyph_bank(css_dir)
    for word in words:                                  # the whole name, else one word of it
        if any(c not in glyphs for c in word):
            continue
        cell = name_cell(pres, pane, css_dir, word)
        if cell is None:
            continue
        if word != words[0]:
            print(f'  the name is wider than the plate: the tile says {word}', flush=True)
        out = io.BytesIO()
        cell.save(out, 'PNG')
        return out.getvalue()
    print('  no word of the name fits the plate even set tightest - the plain crop is used', flush=True)
    return None


def plate_words(name):
    """The words a tile's name plate may say, in the order they are tried: the whole name run together (as the
    game's own plates set it), then each word of it, the last first (the noun: TRAINER, CLIMBERS, FALCON)."""
    parts = [''.join(c for c in w.upper() if c.isalpha()) for w in str(name).split()]
    parts = [p for p in parts if p]
    seen = []
    for w in [''.join(parts)] + parts[::-1]:
        if w and w not in seen:
            seen.append(w)
    return seen


TRACKINGS = (2, 1, 0, -1)   # a long name is set tighter, as the game sets its own; at -1 the letters' outlines touch
                            # (Incineroar, 2026-11-13: "INCINEROAR" is 61 pixels at 0, the plate holds 58)


def name_cell(pres, pane, css_dir, word):
    """The tile with `word` on its plate, set as loosely as it fits; None when it fits at no tracking."""
    for tracking in TRACKINGS:
        try:
            return pres.css_cell(pane, css_dir, word=word, tracking=tracking)
        except ValueError:
            continue
    return None


if __name__ == '__main__':                               # python roster_tile.py <portrait.png> <NAME> <css dir> <out.png>
    made = roster_tile(Path(sys.argv[1]).read_bytes(), sys.argv[2], sys.argv[3])
    if made:
        Path(sys.argv[4]).write_bytes(made)
