"""Order a pair's colour slots so the two fighters' costumes actually match.

Melee's costume slots are not a shared palette. Ganondorf ships
`Nr Re Bu Gr La` and Samus ships `Nr Gr Bk La Pi`, so the pair's slot 1 is
Ganondorf's *red* beside Samus's *green*. Every fighter orders its colours
differently, so this is wrong for most duos rather than a few.

**Only the leader's order is ours to choose.** `Player_80031CB0` preloads the
main fighter and the sub-fighter with the same `color`, so the partner's costume
id is always the pair's slot index -- there is no way to point slot 1 at a
different partner costume without reordering the partner character itself. What
the pair package *does* own is the leader's costume list (it is a duplicate
fighter), so the matching is done by permuting that: slot *s* shows leader
costume `plan[s]` beside partner costume *s*.

Past the end of the partner's list `ftData_800855C8` clamps the id to 0:

    if (color != 0xFF && color >= ...numCostumes) { color = 0; }

so a pair may safely have more colours than the partner owns -- those slots just
show the partner's default. That is what makes a Mr. Game & Watch partner (one
costume) work instead of collapsing the pair to a single colour.

Two signals decide the match:

1. **What the costume looks like.** Averaging a whole CSP mostly measures skin
   and hair -- the parts that *don't* change -- so the colour is taken only from
   the pixels that differ across that fighter's own costumes. Those pixels are
   the costume. CSPs for one fighter share a pose, so they are pixel-aligned and
   a plain cross-costume spread isolates them.

2. **The costume code.** `Re`/`Gr`/`La`... are authored intent, worth a nudge
   where the pixels are ambiguous. It matters most for `Nr`: every fighter's
   default is a different colour, but two defaults together is the iconic
   pairing and the one the CSS shows first.

Deliberately numpy-only -- `scipy.optimize.linear_sum_assignment` would be the
textbook call here, but scipy is not bundled in the frozen build and is far too
heavy to add for a <=6x6 cost matrix.
"""
from __future__ import annotations

import io
import itertools
import logging

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# A pixel counts as part of the character (not background) only if it is opaque
# in every costume, so the silhouette is the same set for all of them.
_ALPHA_FLOOR = 128

# Share of the silhouette treated as "this is the costume". Melee costumes
# recolour a minority of the body -- Ganondorf's tunic, Samus's armour -- so a
# high percentile keeps skin and hair out of the signature.
_COSTUME_PIXEL_PERCENTILE = 70.0

# Below this many costume pixels the spread mask is noise (a costume that only
# differs by a few pixels, or art that isn't actually aligned); fall back to the
# whole silhouette rather than reporting the colour of a handful of stray texels.
_MIN_COSTUME_PIXELS = 40

# Same costume code on both sides multiplies the distance by this. A nudge, not
# an override: it breaks ties toward authored intent and keeps Nr with Nr,
# without letting a code name beat an obvious colour match.
_CODE_MATCH_FACTOR = 0.55

# Lightness matters less than hue here. Two fighters in "some red" read as a
# matched pair even if one is markedly darker; red beside green never does.
_L_WEIGHT = 0.5

# Tie-break toward leaving the leader's costumes where they were. Only decides
# slots whose partner colour is identical -- every slot past the partner's list
# shows the same default, so without this their order would be arbitrary.
_IDENTITY_NUDGE = 0.01

# Above this the permutation search is skipped for a greedy pass. Vanilla tops
# out at 6 costumes, so this is only reachable with custom fighters.
_BRUTE_FORCE_LIMIT = 8


def partner_slot(slot: int, partner_count: int) -> int:
    """The partner costume the engine will actually load for a pair slot."""
    return slot if 0 <= slot < partner_count else 0


def _load_rgba(art: bytes | None) -> np.ndarray | None:
    if not art:
        return None
    try:
        with Image.open(io.BytesIO(art)) as im:
            return np.asarray(im.convert("RGBA"), dtype=np.float32)
    except Exception:
        logger.debug("climbers colour: unreadable costume art", exc_info=True)
        return None


def _srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB 0-255 -> CIE L*a*b* (D65). Input (..., 3), output (..., 3)."""
    c = np.clip(rgb, 0.0, 255.0) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]], dtype=np.float32)
    xyz = (lin @ m.T) / np.array([0.95047, 1.00000, 1.08883], dtype=np.float32)
    eps, kappa = 216.0 / 24389.0, 24389.0 / 27.0
    f = np.where(xyz > eps, np.cbrt(xyz), (kappa * xyz + 16.0) / 116.0)
    fx, fy, fz = f[..., 0], f[..., 1], f[..., 2]
    return np.stack([116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)],
                    axis=-1)


def signatures(arts: list[bytes | None]) -> list[np.ndarray | None]:
    """One Lab colour per costume, taken from the pixels that vary between them.

    `arts` is one fighter's costume art in slot order. A slot whose art is
    missing or unreadable gets None and is matched on its code alone.
    """
    frames = [_load_rgba(a) for a in arts]
    usable = [f for f in frames if f is not None]
    if not usable:
        return [None] * len(arts)

    # Costume art for one fighter is the same render at the same size. If a
    # project has re-rendered one costume at a different size, comparing pixels
    # across them is meaningless -- drop to per-costume whole-silhouette means.
    shape = usable[0].shape
    aligned = len(usable) > 1 and all(f.shape == shape for f in usable)

    mask = None
    if aligned:
        stack = np.stack(usable)  # (n, h, w, 4)
        opaque = np.all(stack[..., 3] >= _ALPHA_FLOOR, axis=0)  # (h, w)
        if opaque.any():
            # How much this pixel's colour moves across the fighter's costumes.
            spread = (stack[..., :3].max(axis=0) - stack[..., :3].min(axis=0)).sum(axis=-1)
            cut = np.percentile(spread[opaque], _COSTUME_PIXEL_PERCENTILE)
            candidate = opaque & (spread > max(float(cut), 1.0))
            if int(candidate.sum()) >= _MIN_COSTUME_PIXELS:
                mask = candidate

    out: list[np.ndarray | None] = []
    for frame in frames:
        if frame is None:
            out.append(None)
            continue
        if mask is not None:
            pixels = frame[..., :3][mask]
        else:
            own = frame[..., 3] >= _ALPHA_FLOOR
            pixels = frame[..., :3][own] if own.any() else np.empty((0, 3), np.float32)
        out.append(_srgb_to_lab(pixels.mean(axis=0)) if pixels.size else None)
    return out


def _code(entry: str | None) -> str:
    """Melee costume codes end in the colour ('PlGnRe' -> 're')."""
    text = (entry or "").strip().lower()
    return text[-2:] if len(text) >= 2 else text


def _distance(lead_sig, part_sig, lead_code: str, part_code: str) -> float:
    if lead_sig is None or part_sig is None:
        # No usable art on one side: the code is all there is to go on.
        return 0.0 if lead_code and lead_code == part_code else 100.0
    d = lead_sig - part_sig
    dist = float(np.sqrt((_L_WEIGHT * d[0]) ** 2 + d[1] ** 2 + d[2] ** 2))
    if lead_code and lead_code == part_code:
        dist *= _CODE_MATCH_FACTOR
    return dist


def _greedy(cost: np.ndarray) -> list[int]:
    """Repeatedly take the cheapest remaining leader/slot pairing."""
    n = cost.shape[0]
    plan = [-1] * n
    work = cost.copy()
    for _ in range(n):
        lead, slot = np.unravel_index(int(np.argmin(work)), work.shape)
        plan[int(slot)] = int(lead)
        work[lead, :] = np.inf
        work[:, slot] = np.inf
    return plan


def plan(leader_arts: list[bytes | None], leader_codes: list[str],
         partner_arts: list[bytes | None], partner_codes: list[str]) -> list[int]:
    """Which leader costume belongs at each of the pair's colour slots.

    The pair gets one slot per leader costume, so every one of the leader's
    colours stays selectable even when the partner has fewer (or, like
    Mr. Game & Watch, exactly one). Returns a permutation of the leader's
    costume indices, one entry per slot.

    Chosen to minimise total colour distance across the whole set rather than
    greedily per slot, so one slot with no good option cannot spoil the rest.
    """
    n = len(leader_arts)
    if n == 0:
        return []
    partner_n = len(partner_arts)
    if partner_n == 0:
        return list(range(n))

    lead_sigs = signatures(leader_arts)
    part_sigs = signatures(partner_arts)
    lead_codes = [_code(c) for c in leader_codes] + [""] * n
    part_codes = [_code(c) for c in partner_codes] + [""] * partner_n

    # cost[leader costume][pair slot]
    cost = np.empty((n, n), dtype=np.float64)
    for slot in range(n):
        p = partner_slot(slot, partner_n)
        for lead in range(n):
            cost[lead, slot] = (
                _distance(lead_sigs[lead], part_sigs[p],
                          lead_codes[lead], part_codes[p])
                + _IDENTITY_NUDGE * abs(lead - slot))

    # Slot 0 is the pair's default -- the colour the CSS shows, the one the
    # vault card and the composited CSS icon are drawn from -- so it is always
    # the two fighters' own defaults, never the closest colour match. Left to
    # the optimiser, "Mario & Luigi" defaults to *green* Mario, because Luigi's
    # default is green and that scores better than red beside green.
    cost[1:, 0] = np.inf
    cost[0, 1:] = np.inf

    if n > _BRUTE_FORCE_LIMIT:
        return _greedy(cost)

    slots = np.arange(n)
    best, best_total = tuple(range(n)), np.inf
    for perm in itertools.permutations(range(n)):
        total = float(cost[perm, slots].sum())
        if total < best_total:
            best, best_total = perm, total
    return list(best)
