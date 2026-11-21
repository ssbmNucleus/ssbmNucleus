"""
Tests for vault/climbers/portraits.py — the composited art for an Any Climbers pair.

The CSS icon is the load-bearing case, and it went through three wrong designs
before this one (reported 2026-09-12, in this order):

  1. The partner was cropped to its OWN name-plate row. Those rows differ per
     fighter — Kirby's sits 6px below Jigglypuff's — so Jigglypuff + Kirby drew
     Kirby straight across the word "JIGGLY-".
  2. Cropping art from column 2 took the black matte that the full-bleed icons
     (Fox, Samus, Pichu) carry just inside the grey frame. Sliding art that
     still carried it planted a 1px black bar in the middle of the picture, and
     clearing the chrome to the grey ate the matte and thinned the border.
  3. Sliding the fighters apart to make room cropped the LEADER against the
     frame — 4.5% of Marth, 12.7% of Jigglypuff — which cut Marth's neck off.

The rule that came out of it: the leader's icon is a finished, framed, named
card, so it is used verbatim and the partner rides in a badge.
"""
from tests.paths import BACKEND
import io
import sys
from pathlib import Path

import pytest
from PIL import Image

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

from vault.climbers.portraits import (  # noqa: E402
    ICON_SIZE, _ICON_ART_INSET, _ICON_BADGE_PX, _fit,
    _icon_art_bottom, _load, composite,
)

VANILLA = BACKEND_DIR.parent / 'utility' / 'assets' / 'vanilla'

pytestmark = pytest.mark.skipif(
    not (VANILLA / 'Jigglypuff' / 'css_icon.png').exists(),
    reason='vanilla assets not present')

# Leader, partner. Covers alpha-cut and full-bleed leaders, a flat-black
# fighter both ways round, and the two-line name plate.
PAIRS = [
    ('Jigglypuff', 'Kirby'), ('Kirby', 'Jigglypuff'), ('Fox', 'Falco'),
    ('Bowser', 'Pichu'), ('Marth', 'Roy'), ('Samus', 'Young Link'),
    ('Mr. Game & Watch', 'Peach'), ('Ness', 'Mr. Game & Watch'),
]


ALL_LEADERS = sorted(d.name for d in VANILLA.iterdir()
                     if (d / 'css_icon.png').exists()) if VANILLA.exists() else []


def icon(name):
    return (VANILLA / name / 'css_icon.png').read_bytes()


def stock(name):
    dirs = [d for d in (VANILLA / name).iterdir()
            if d.is_dir() and (d / 'stock.png').exists()]
    default = [d for d in dirs if d.name.endswith('Nr')]
    return ((default or dirs)[0] / 'stock.png').read_bytes() if dirs else None


def rendered(leader, partner):
    data = composite(icon(leader), icon(partner), 'icon', partner_stock=stock(partner))
    return Image.open(io.BytesIO(data)).convert('RGBA')


def leader_icon(leader):
    return _fit(_load(icon(leader)), ICON_SIZE)


def badge_rect(base):
    """Where the badge is allowed to be, or None when the box is too short.
    Top-left corner of the art box, no plate behind it."""
    bottom = _icon_art_bottom(base)
    inset = _ICON_ART_INSET
    size = _ICON_BADGE_PX
    if bottom - inset < size or ICON_SIZE[0] - inset * 2 < size:
        return None
    return (inset, inset, inset + size, inset + size)


@pytest.mark.parametrize('leader,partner', PAIRS)
def test_the_leader_art_is_untouched_outside_the_badge(leader, partner):
    """The headline rule. Every pixel that is not badge must be exactly the
    pixel the game would draw — frame, matte, name plate and the art itself.
    This is what "his neck is cut off" was: art moved and cropped."""
    base = leader_icon(leader)
    out = rendered(leader, partner)
    x0, y0, x1, y1 = badge_rect(base)
    altered = [(x, y) for y in range(ICON_SIZE[1]) for x in range(ICON_SIZE[0])
               if not (x0 <= x < x1 and y0 <= y < y1)
               and out.getpixel((x, y)) != base.getpixel((x, y))]
    assert not altered, f'{len(altered)} leader pixels altered, first at {altered[0]}'


@pytest.mark.parametrize('leader,partner', PAIRS)
def test_the_badge_stays_inside_the_art_box(leader, partner):
    """Inside the frame and its matte, and above the name plate."""
    base = leader_icon(leader)
    x0, y0, x1, y1 = badge_rect(base)
    assert x0 >= _ICON_ART_INSET
    assert y0 >= _ICON_ART_INSET
    assert x1 <= ICON_SIZE[0] - _ICON_ART_INSET
    assert y1 <= _icon_art_bottom(base), 'badge reaches the name plate'


@pytest.mark.parametrize('leader,partner', PAIRS)
def test_the_partner_is_actually_drawn(leader, partner):
    """A pair card has to look like a pair — the badge must not be empty."""
    base = leader_icon(leader)
    out = rendered(leader, partner)
    x0, y0, x1, y1 = badge_rect(base)
    drawn = sum(out.getpixel((x, y)) != base.getpixel((x, y))
                for y in range(y0, y1) for x in range(x0, x1))
    assert drawn > 100, f'only {drawn} badge pixels drawn'


def test_every_card_gets_the_same_size_badge():
    """One size for the whole roster. A badge that changes size per leader looks
    like a mistake on a grid of cards, and there is room for the big one
    everywhere: the shortest vanilla art box is 32px."""
    sizes = set()
    for name in ALL_LEADERS:
        rect = badge_rect(leader_icon(name))
        assert rect is not None, f'{name} got no badge'
        sizes.add(rect[2] - rect[0])
    assert sizes == {_ICON_BADGE_PX}, f'badge sizes vary across the roster: {sizes}'


def test_a_stock_icon_is_pasted_at_its_native_size_unscaled():
    """24px is the stock icon's own size, so it lands pixel-for-pixel."""
    from vault.climbers.portraits import _icon_badge
    art = _load(stock('Roy'))
    assert art.size == (_ICON_BADGE_PX, _ICON_BADGE_PX), 'stock icons are 24x24'
    badge = _icon_badge(icon('Roy'), stock('Roy'), _ICON_BADGE_PX)
    assert badge.tobytes() == art.tobytes(), 'the stock icon was resampled'


def test_two_line_name_plates_are_found_by_their_rule_line():
    """The plate is located by its near-black full-width rule row. Looking for
    the top of the trailing opaque band instead ran past the plate on the
    full-bleed icons (Ice Climbers measured a 10px art box) and stopped short
    on others (Young Link measured 34 when his plate starts at 41)."""
    two_line = {'Ice Climbers', 'Jigglypuff', 'Mr. Game & Watch'}
    for name in ALL_LEADERS:
        bottom = _icon_art_bottom(leader_icon(name))
        expected = 35 if name in two_line else 41
        assert bottom == expected, f'{name}: plate row {bottom}, expected {expected}'


def test_a_box_too_short_for_the_badge_gets_none_at_all():
    """Guard for an added fighter with almost no art box: better their own card
    than a differently sized badge. Synthesised - no vanilla icon is this short.

    Built with a BRIGHT opaque band so there is no rule line to find, which
    sends _icon_art_bottom down its fallback path; the rule path only searches
    the bottom half and so can never report a box under 25px."""
    from vault.climbers.portraits import _composite_icon
    tiny = leader_icon('Marth').copy()
    for y in range(10, ICON_SIZE[1]):
        for x in range(ICON_SIZE[0]):
            tiny.putpixel((x, y), (200, 200, 200, 255))
    buf = io.BytesIO()
    tiny.save(buf, format='PNG')
    assert _icon_art_bottom(tiny) - _ICON_ART_INSET < _ICON_BADGE_PX, 'fixture is not short'
    out = _composite_icon(buf.getvalue(), icon('Roy'), stock('Roy'))
    assert out.tobytes() == tiny.tobytes(), 'a too-short box must be left alone'


def test_badge_falls_back_to_css_art_when_no_stock_is_available():
    """`partner_stock` is optional; the card must still come out."""
    base = leader_icon('Marth')
    out = Image.open(io.BytesIO(
        composite(icon('Marth'), icon('Roy'), 'icon'))).convert('RGBA')
    assert out.size == ICON_SIZE
    x0, y0, x1, y1 = badge_rect(base)
    drawn = sum(out.getpixel((x, y)) != base.getpixel((x, y))
                for y in range(y0, y1) for x in range(x0, x1))
    assert drawn > 100


def test_icon_keeps_its_size():
    assert rendered('Jigglypuff', 'Kirby').size == ICON_SIZE
