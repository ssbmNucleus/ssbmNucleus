"""Tucked icons: every L-load alternate keeps a CSS icon, hidden behind its base.

The CSS takes the portrait and the costume count from the selected icon's
fighter, not from the selected fighter, so the L code moves the selected icon
along with the fighter and each alternate needs an icon. Verified in game
(docs/dev/L_LOAD.md), the icon is invisible and can't be hovered when it:

  * has its base's position and scale,
  * has a zero hit box, and
  * is listed immediately BEFORE its base -- later icons draw on top, so the
    base covers it (depth does not decide this, list order does).

`tuck` is the one owner of that shape. Every layout save and every export run
it, so a reflow (MexCLI's Template.Apply, the editor's auto-grid) can never
leave an alternate showing. An alternate is recognised by group membership,
never by its hit box: Template.Apply resets hit boxes.
"""
from __future__ import annotations

# The fields set-css-layout reads back (MexCLI SetCssLayoutCommand).
ICON_KEYS = ('x', 'y', 'z', 'scaleX', 'scaleY', 'fighter', 'sfxID',
             'collisionOffsetX', 'collisionOffsetY', 'collisionSizeX', 'collisionSizeY')
DEFAULT_HIT_BOX = (7.05, 7.2)   # m-ex's MexCharacterSelectIcon default
DEFAULT_SFX = 205               # m-ex's MexCharacterSelectIcon default


def icon_fields(ic: dict) -> dict:
    return {k: ic[k] for k in ICON_KEYS if k in ic}


def _is_tucked(ic: dict) -> bool:
    return not ic.get('collisionSizeX') and not ic.get('collisionSizeY')


def tuck(icons: list[dict], groups: list[dict]) -> tuple[list[dict], dict[int, int]]:
    """Lay `icons` out with every group's alternates tucked behind their base.

    `groups` are resolved ([{"base": ext, "alts": [ext, ...]}]); a group whose
    base has no icon is skipped (its alternates keep whatever they had).
    Returns (icons in set-css-layout shape, {external id: icon index}) -- the
    index map is what the L code's table points at, so read it from here
    rather than from a second get-css-layout.

    A fighter that is no longer an alternate but still has a tucked icon is
    untucked: it gets the default hit box and moves to the end of the list,
    for the grid to place. A zero hit box is a safe marker for that one case:
    an icon without one can never be picked, so outside a group it is always
    a former alternate. (Alternates themselves are found by group membership.)
    """
    first_icon: dict[int, dict] = {}
    for ic in icons:
        first_icon.setdefault(ic['fighter'], ic)
    groups = [g for g in groups if g['base'] in first_icon]
    alts = {alt for g in groups for alt in g['alts']}
    alts_of = {g['base']: g['alts'] for g in groups}

    out: list[dict] = []
    untucked: list[dict] = []
    placed: set[int] = set()
    for ic in icons:
        fighter = ic['fighter']
        if fighter in alts:
            continue                                   # re-inserted behind its base
        if fighter in alts_of and fighter not in placed:
            if _is_tucked(ic):                         # an alternate just made a base
                ic = {**ic, 'collisionSizeX': DEFAULT_HIT_BOX[0],
                      'collisionSizeY': DEFAULT_HIT_BOX[1]}
            for alt in alts_of[fighter]:
                own = first_icon.get(alt, {})
                out.append({**icon_fields(ic), 'fighter': alt,
                            'sfxID': own.get('sfxID', DEFAULT_SFX),
                            'collisionOffsetX': 0.0, 'collisionOffsetY': 0.0,
                            'collisionSizeX': 0.0, 'collisionSizeY': 0.0})
            placed.add(fighter)
        elif _is_tucked(ic):
            untucked.append({**icon_fields(ic), 'collisionSizeX': DEFAULT_HIT_BOX[0],
                             'collisionSizeY': DEFAULT_HIT_BOX[1]})
            continue
        out.append(icon_fields(ic))
    out += untucked

    index: dict[int, int] = {}
    for i, ic in enumerate(out):
        index.setdefault(ic['fighter'], i)
    return out, index


def changed(before: list[dict], after: list[dict]) -> bool:
    """True when `after` differs from the layout `before` (float noise aside)."""
    if len(before) != len(after):
        return True
    for a, b in zip(before, after):
        for k in ICON_KEYS:
            va, vb = a.get(k), b.get(k)
            if isinstance(va, float) or isinstance(vb, float):
                if abs(float(va or 0) - float(vb or 0)) > 1e-4:
                    return True
            elif va != vb:
                return True
    return False


def table(groups: list[dict], index: dict[int, int]) -> list[list[tuple[int, int]]]:
    """[(external id, icon index) for base then alternates] per group, for code.py."""
    return [[(g['base'], index[g['base']])] + [(a, index[a]) for a in g['alts']]
            for g in groups if g['base'] in index]
