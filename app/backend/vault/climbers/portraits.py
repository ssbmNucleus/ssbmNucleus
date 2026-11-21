"""Composite portrait/icon art for an Any Climbers pair.

A pair occupies one CSS slot but is two fighters, so its portrait has to show
both. Rendering them into a single 3D scene is what the game does for the Ice
Climbers, but that scene is posed specifically for Popo and Nana -- it does not
generalise to an arbitrary duo. So we composite in 2D instead, from the art each
fighter already has for that colour slot.

The CSP keeps both fighters at their **native size and aspect** and simply slides
them apart horizontally, then crops back to the CSP frame. Scaling them down to
fit side by side would leave the pair looking small and letterboxed next to every
other portrait on the CSS; overlapping keeps it reading like a real CSP.

Deliberately crude. The goal is that every colour slot has something
recognisable; a hand-authored portrait can replace it through the normal
costume CSP tools.
"""
from __future__ import annotations

import io

from PIL import Image

CSP_SIZE = (136, 188)
STOCK_SIZE = (24, 24)
ICON_SIZE = (64, 56)

# How far each fighter slides from centre, in pixels, per asset kind. Nothing
# is ever scaled down to make room: shrinking art to fit two into one frame
# changes how big the characters read next to every other portrait and icon on
# the screen. Both fighters stay at native size and the frame just crops.
_CSP_PARTNER_DX = -26
_CSP_LEADER_DX = 14
_STOCK_PARTNER_DX = -6
_STOCK_LEADER_DX = 5

# The CSS icon tucks the partner in BEHIND the leader, shifted left.
# The plate's grey border is 2px. Inside it, the full-bleed icons (Fox, Samus,
# Pichu, the Climbers) carry their OWN 1px black matte -- measured, not assumed:
# Fox's column 2 is opaque black where Jigglypuff's is alpha 0. That matte reads
# as part of the border, so it has to be treated as border: sliding art that
# still carries it drags a black bar into the middle of the picture, and
# clearing the chrome up to the grey eats the matte and thins the frame. Both
# of those were visible on the Fox + Falco card.
_ICON_FRAME_INSET = 2
_ICON_ART_INSET = _ICON_FRAME_INSET + 1
# The icon slides BOTH fighters apart, like the CSP does, so each one still
# reads at 64x56. The leader moves less: the plate underneath carries their
# name, so they stay the subject.
# The icon does NOT slide its fighters. It is 64x56 of framed, named, cropped
# artwork -- there is no room to move anything without cropping the leader (a
# +10 slide threw away 4.5% of Marth and 12.7% of Jigglypuff, severing necks at
# the frame) and no way to butt two full-bleed photos together without a seam.
# So the leader's icon is used AS IS and the partner rides along as a badge,
# which is the only arrangement that neither edits the leader nor hides the
# partner behind an opaque icon.
# ONE size for every card. The stock icon is natively 24x24, so at 24 it is
# pasted pixel-for-pixel with no resampling at all, and every pair card carries
# an identically sized badge. The smallest vanilla art box is 31px tall, so
# this always fits; an icon that somehow cannot hold it gets no badge rather
# than a different-sized one.
_ICON_BADGE_PX = 24


def _load(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGBA")


def _fit(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Letterbox `image` onto a `size` canvas without ever changing its aspect."""
    if image.size == size:
        return image
    scale = min(size[0] / image.width, size[1] / image.height)
    scaled = image.resize((max(1, round(image.width * scale)),
                           max(1, round(image.height * scale))), Image.LANCZOS)
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    canvas.alpha_composite(scaled, ((size[0] - scaled.width) // 2,
                                    (size[1] - scaled.height) // 2))
    return canvas


def _solo(art: bytes, size: tuple[int, int]) -> Image.Image:
    """One fighter's art on the target canvas, aspect preserved."""
    return _fit(_load(art), size)


def _overlap(leader_png: bytes, partner_png: bytes, size: tuple[int, int],
             partner_dx: int, leader_dx: int) -> Image.Image:
    """Slide two same-size assets apart at native scale, then crop to frame."""
    width, height = size
    pad = max(abs(partner_dx), abs(leader_dx)) + 8
    wide = Image.new("RGBA", (width + pad * 2, height), (0, 0, 0, 0))
    wide.alpha_composite(_fit(_load(partner_png), size), (pad + partner_dx, 0))
    wide.alpha_composite(_fit(_load(leader_png), size), (pad + leader_dx, 0))
    return wide.crop((pad, 0, pad + width, height))


def _composite_csp(leader_png: bytes, partner_png: bytes) -> Image.Image:
    return _overlap(leader_png, partner_png, CSP_SIZE,
                    _CSP_PARTNER_DX, _CSP_LEADER_DX)


def _composite_stock(leader_png: bytes, partner_png: bytes) -> Image.Image:
    return _overlap(leader_png, partner_png, STOCK_SIZE,
                    _STOCK_PARTNER_DX, _STOCK_LEADER_DX)


# The plate opens with a near-black rule line spanning the full width of the
# icon. Measured across the vanilla cast that row sits at mean brightness
# 10-13; the darkest art row that is also full width is far above it, so the
# threshold is not delicate. Both halves of the test matter: Mr. Game & Watch
# is a black silhouette (rows at mean 10.8) but only ~24px of them are opaque,
# and Young Link's art goes full width at row 34 while his plate starts at 41.
_PLATE_RULE_MAX_MEAN = 25


def _icon_art_bottom(image: Image.Image) -> int:
    """First row of the CSS icon's name plate.

    Found by its opening RULE LINE, not by where opaque rows start. Looking for
    the top of the trailing opaque band works only while the art above is
    alpha-cut: the full-bleed icons are opaque to the frame, so on the Ice
    Climbers that walk ran clean past the plate and called the art box 10px
    tall when it is 32 -- which then shrank their badge for no reason.
    """
    alpha = image.split()[3]
    width, height = image.size

    def opaque_row(y: int) -> bool:
        return all(alpha.getpixel((x, y)) > 200 for x in range(width))

    def mean_row(y: int) -> float:
        return sum(sum(image.getpixel((x, y))[:3]) / 3 for x in range(width)) / width

    # The plate always occupies the bottom of the icon, so only look there; the
    # FIRST qualifying row going down is its top (lower dark rows are text).
    for y in range(height // 2, height):
        if opaque_row(y) and mean_row(y) < _PLATE_RULE_MAX_MEAN:
            return y

    # No rule line found (an icon that is not a vanilla-style plate): fall back
    # to the old trailing-opaque-band walk rather than claiming the whole icon.
    y = height - 1
    while y >= 0 and not opaque_row(y):
        y -= 1
    while y >= 0 and opaque_row(y):
        y -= 1
    return max(1, y + 1)


def _icon_badge(partner_png: bytes, partner_stock: bytes | None,
                size: int) -> Image.Image:
    """A small round portrait of the partner, for the corner of the leader's card.

    The stock icon is the right asset for this -- it is drawn to be legible at
    this size. Falling back to a crop of the partner's CSS art keeps the
    function total when no stock is available; it just reads less clearly.
    """
    if partner_stock:
        art = _load(partner_stock)
    else:
        whole = _fit(_load(partner_png), ICON_SIZE)
        art = whole.crop((_ICON_ART_INSET, _ICON_ART_INSET,
                          ICON_SIZE[0] - _ICON_ART_INSET, _icon_art_bottom(whole)))
        side = min(art.width, art.height)
        art = art.crop(((art.width - side) // 2, 0, (art.width + side) // 2, side))
    # A stock icon is already 24x24; pasting it untouched keeps it crisp.
    return art if art.size == (size, size) else art.resize((size, size), Image.LANCZOS)


def _composite_icon(leader_png: bytes, partner_png: bytes,
                    partner_stock: bytes | None = None) -> Image.Image:
    """The leader's CSS icon, untouched, with the partner badged into a corner.

    Nothing about the leader's icon is moved, cropped or recoloured: the card
    stays the card the game would draw, frame and name and all. The badge sits
    inside the ART BOX -- above the name plate, inside the frame and its matte --
    and is skipped entirely when the box is too short to hold a legible one
    (the Ice Climbers' name wraps to two lines, leaving ~10px of art).
    """
    base = _fit(_load(leader_png), ICON_SIZE).copy()
    inset = _ICON_ART_INSET
    bottom = _icon_art_bottom(base)

    # No plate or ring behind it: the stock icon already carries its own
    # outline, which is what makes it legible on any background.
    size = _ICON_BADGE_PX
    if bottom - inset < size or ICON_SIZE[0] - inset * 2 < size:
        return base

    badge = _icon_badge(partner_png, partner_stock, size)
    base.alpha_composite(badge, (inset, inset))   # top-left corner of the art box
    return base


_KINDS = {
    "csp": (CSP_SIZE, _composite_csp),
    "stock": (STOCK_SIZE, _composite_stock),
    "icon": (ICON_SIZE, _composite_icon),
}


def composite(leader_png: bytes, partner_png: bytes, kind: str = "csp",
              partner_stock: bytes | None = None) -> bytes:
    """Overlap two same-kind PNGs into one. Leader is drawn in front.

    Either side may be missing (empty bytes); the other is then used on its own,
    so a pair whose partner art is unavailable still gets a usable asset.

    `partner_stock` is only read for kind="icon", where the partner appears as a
    corner badge rather than overlapped art -- pass the partner's stock icon and
    the badge is drawn from the asset meant to be legible that small.
    """
    if kind not in _KINDS:
        raise ValueError(f"unknown portrait kind: {kind}")
    size, build = _KINDS[kind]

    if leader_png and partner_png:
        image = (build(leader_png, partner_png, partner_stock) if kind == "icon"
                 else build(leader_png, partner_png))
    elif leader_png or partner_png:
        image = _solo(leader_png or partner_png, size)
    else:
        image = Image.new("RGBA", size, (0, 0, 0, 0))

    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()
