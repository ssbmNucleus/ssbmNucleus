"""
Tolerant picture comparison for "Currently in MEX" file checks.

The menu tools re-encode pictures when they write them into a game file:
HSDRawViewer's texture import quantizes to the slot's GX format (IA4, I4,
CI8 palettes, RGB5A3...), MexCLI converts icons to its own texture format.
Two encodings of the same picture therefore differ in bytes, so the checks
compare decoded pixels instead, with a tolerance that absorbs re-encoding
noise but not a different picture.

Measured 2026-09-27 on a real m-ex project's IfAll.usd, round-tripping the
128 percent/Ready-Go slots through --hud-textures import/export
(tests/backend/test_menus_file_checks.py re-runs the vanilla and restore round
trips); per-pixel error d = max over RGBA (colors premultiplied by alpha):

  re-encoding noise                         mean d   pixels with d > 40
  vanilla -> same format again              <= 0.04  <= 0.02% (5 CI8 px)
  vanilla -> RGB5A3 -> back (restore path)  <= 5.35  0
  source picture -> RGB5A3 (resized 1-3x)   <= 13.6  0

  real edits
  another digit glyph                       >= 44    >= 27%
  outline 1px thicker / picture moved 1px   >= 15.8  >= 8.5%
  whole category recolored +12 red          10.95 on its worst slot

So a picture matches when few pixels are far off (d > 40 on <= 1% of the
visible pixels: every shape change moves far more) and the mean error is
within the re-encoding noise of that comparison. Callers check every slot
of a category, so a recolor is caught by its worst slot.

Colors are compared premultiplied by alpha, so the color of a (nearly)
transparent pixel doesn't count, and the mean is taken over pixels that are
visible in either picture (a glyph is mostly transparent background).
"""

from pathlib import Path

FAR_DELTA = 40
MAX_FAR_FRACTION = 0.01
# mean-error limits per comparison kind
MEAN_TOL = {
    # file vs a picture decoded from another game file (vanilla export...)
    'reencode': 8.0,
    # file vs the source picture an importer resized and encoded
    'source': 16.0,
}
# A visible pixel: alpha above this in either picture.
VISIBLE_ALPHA = 8


def load_rgba(src):
    """PIL RGBA image from a path or an Image; None when unreadable."""
    try:
        from PIL import Image
        if isinstance(src, (str, Path)):
            with Image.open(src) as im:
                im.load()
                return im.convert('RGBA')
        return src.convert('RGBA')
    except Exception:
        return None


def pixel_diff(a, b):
    """{'max', 'mean', 'far', 'visible', 'resized'} between two pictures (paths or
    images). `b` is resized to `a`'s size when they differ (the importers
    resize to the slot). None when either can't be read."""
    a, b = load_rgba(a), load_rgba(b)
    if a is None or b is None or a.width == 0 or a.height == 0:
        return None
    resized = b.size != a.size
    if resized:
        from PIL import Image
        b = b.resize(a.size, Image.BICUBIC)
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - numpy ships with the app
        np = None
    if np is not None:
        x = np.asarray(a, dtype=np.int32)
        y = np.asarray(b, dtype=np.int32)
        ax, ay = x[..., 3], y[..., 3]
        mask = (ax > VISIBLE_ALPHA) | (ay > VISIBLE_ALPHA)
        d = np.abs(ax - ay)
        for c in range(3):
            d = np.maximum(d, np.abs(x[..., c] * ax - y[..., c] * ay) // 255)
        d = d[mask]
        visible = int(d.size)
        worst = int(d.max()) if visible else 0
        mean = float(d.mean()) if visible else 0.0
        far = int((d > FAR_DELTA).sum())
        return {'max': worst, 'mean': mean, 'far': far, 'visible': visible,
                'resized': resized}

    pa, pb = a.tobytes(), b.tobytes()
    worst = 0
    total = 0
    visible = 0
    far = 0
    for i in range(0, len(pa), 4):
        aa, ab = pa[i + 3], pb[i + 3]
        if aa <= VISIBLE_ALPHA and ab <= VISIBLE_ALPHA:
            continue
        d = abs(aa - ab)
        for c in range(3):
            dc = abs(pa[i + c] * aa - pb[i + c] * ab) // 255
            if dc > d:
                d = dc
        visible += 1
        total += d
        far += d > FAR_DELTA
        if d > worst:
            worst = d
    return {'max': worst, 'mean': (total / visible) if visible else 0.0,
            'far': far, 'visible': visible, 'resized': resized}


def same_picture(a, b, kind='reencode'):
    """True when two pictures show the same thing up to re-encoding noise
    (see the table above); None when they can't be compared (unreadable).
    kind: 'reencode' (both decoded from game files) or 'source' (b is the
    source picture an importer resized and encoded into a)."""
    d = pixel_diff(a, b)
    if d is None:
        return None
    if not d['visible']:
        return True   # both fully transparent
    return (d['far'] <= MAX_FAR_FRACTION * d['visible']
            and d['mean'] <= MEAN_TOL[kind])
