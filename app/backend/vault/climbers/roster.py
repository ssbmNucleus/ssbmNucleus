"""Where the pair picker gets its fighters and art.

The Custom Characters vault is project-independent — every other card there can
be created, viewed and deleted with no project open — so the pair picker has to
be too. It reads the bundled vanilla asset tree (`utility/assets/vanilla/`),
which ships with a CSP, stock icon and DAT for every costume of every playable
character, plus a CSS icon.

When a project *is* open its roster wins, so added m-ex fighters and any costume
art the user has modified show up instead of the stock versions.
"""
from __future__ import annotations

import logging
from pathlib import Path

from core.config import VANILLA_ASSETS_DIR
from core.constants import CHAR_PREFIXES, VANILLA_CSS_COLOR_ORDER, vanilla_costume_specs

logger = logging.getLogger(__name__)

# Vanilla asset folders that aren't selectable fighters. Nana has her own
# folder because she is a real fighter, but she only ever exists as the Ice
# Climbers' follower — she is not pickable on either side and ships no
# css_icon.png, so listing her just puts a broken tile in the picker.
_NOT_FIGHTERS = {"custom_poses", "sounds", "Nana"}

# Nana has her own asset folder (she is a real fighter) but only ever exists as
# the Ice Climbers' follower, and Popo's folder is named "Ice Climbers".
_BLOCKED_LEADERS = {"ice climbers", "popo", "nana", "zelda", "sheik"}
# A follower must not itself own a sub-fighter -- Ice Climbers as the partner
# would be Popo spawning his own Nana, a pair nested inside a pair.
_BLOCKED_PARTNERS = {"ice climbers", "popo", "nana", "zelda", "sheik"}


# Melee's real costume order, per character. This CANNOT be derived from the
# bundled asset tree: those folders are named by costume code, and sorting them
# by any rule -- alphabetical, or a hand-written colour ranking -- disagrees
# with the game for 14 of the 26 characters. Samus is `Nr Pi Bk Gr La`, not the
# `Nr Gr Bk La Pi` a colour ranking produces, so slot 1 of a Ganondorf pair was
# previewed as red-beside-green while the installed pair paired red with pink.
#
# The order has to match, because the vault preview and `pairs.materialize`
# must agree and because the engine identifies a costume purely by slot index.
# It is the DOL's costume table (core.constants.VANILLA_CSS_COLOR_ORDER, which
# the costume lists of two independent real projects match exactly); this is
# vanilla game data and does not change.
#
# Mr. Game & Watch is four entries all pointing at the same `PlGwNr.dat` -- his
# team colours are runtime material recolours, not separate costume files. He
# genuinely has four slots, which one folder per code cannot represent.
_VANILLA_COSTUMES = {
    name: [f'Pl{CHAR_PREFIXES[name]}{color}' for color, _slot in vanilla_costume_specs(name)]
    for name in VANILLA_CSS_COLOR_ORDER
}


def _costume_dirs(char_dir: Path) -> list[Path]:
    """A character's costume folders, in the game's slot order.

    One entry per costume *slot*, so a repeated code (Game & Watch) yields the
    same folder more than once. Falls back to the folders on disk for anything
    not in the table -- there should be nothing, but a missing character should
    degrade to a wrong order rather than to no costumes at all.
    """
    codes = _VANILLA_COSTUMES.get(char_dir.name)
    if codes:
        dirs = [char_dir / code for code in codes]
        if all(d.is_dir() for d in dirs):
            return dirs
        logger.warning("vanilla assets for %s are missing costume folders",
                       char_dir.name)
    return sorted(d for d in char_dir.iterdir()
                  if d.is_dir() and d.name.startswith("Pl"))


def is_selectable(name: str) -> bool:
    """Whether a fighter belongs in the picker at all.

    Distinct from the leader/partner blocks, which list a fighter and say why
    it cannot be used: these never appear. Both candidate paths (vanilla and
    project) must agree, or the picker's contents change with a project open.
    """
    return name not in _NOT_FIGHTERS


def _blocked(name: str) -> tuple[str | None, str | None]:
    key = name.strip().lower()
    leader = f"{name} can't lead a pair" if key in _BLOCKED_LEADERS else None
    partner = f"{name} can't be a partner" if key in _BLOCKED_PARTNERS else None
    return leader, partner


def vanilla_candidates() -> list[dict]:
    """Selectable fighters from the bundled vanilla assets — no project needed."""
    if not VANILLA_ASSETS_DIR.exists():
        return []

    out = []
    for char_dir in sorted(VANILLA_ASSETS_DIR.iterdir()):
        if not char_dir.is_dir() or not is_selectable(char_dir.name):
            continue
        costumes = _costume_dirs(char_dir)
        if not costumes:
            continue
        name = char_dir.name
        leader_block, partner_block = _blocked(name)
        out.append({
            "name": name,
            "costumeCount": len(costumes),
            "canLead": leader_block is None,
            "canPartner": partner_block is None,
            "leaderBlockedReason": leader_block,
            "partnerBlockedReason": partner_block,
        })
    return out


# Vanilla series ids, so a pair created with no project open still shows the
# leader's franchise on its card instead of defaulting to series 0 ("F-Zero").
_SERIES = {
    "Mario": 6, "Luigi": 6, "Peach": 6, "Bowser": 6, "Dr. Mario": 6,
    "DK": 1, "Fox": 2, "Falco": 2, "Mr. Game & Watch": 3, "Ice Climbers": 4,
    "Kirby": 5, "Marth": 7, "Roy": 7, "Ness": 8, "Pikachu": 9,
    "Jigglypuff": 9, "Mewtwo": 9, "Pichu": 9, "Samus": 10, "Yoshi": 12,
    "Link": 13, "Zelda": 13, "Sheik": 13, "Young Link": 13, "Ganondorf": 13,
    "C. Falcon": 0,
}


def series_id(name: str) -> int:
    return _SERIES.get(name.strip(), 0)


def vanilla_costume_codes(name: str) -> list[str]:
    """A character's costume codes ('PlFxNr', 'PlFxOr', ...) in slot order."""
    char_dir = VANILLA_ASSETS_DIR / name
    if not char_dir.is_dir():
        return []
    return [d.name for d in _costume_dirs(char_dir)]


# Melee's costume-code suffixes. Only used to label colour slots in the vault
# when there is no project to take real costume names from.
_COLOR_NAMES = {
    "Nr": "Normal", "Re": "Red", "Bu": "Blue", "Gr": "Green", "Ye": "Yellow",
    "Wh": "White", "Bk": "Black", "Or": "Orange", "La": "Lavender",
    "Pi": "Pink", "Aq": "Aqua", "Gy": "Grey", "Br": "Brown",
}


def color_label(code: str, index: int) -> str:
    suffix = code[-2:] if len(code) >= 2 else ""
    return _COLOR_NAMES.get(suffix, f"Color {index + 1}")


def vanilla_art(name: str, color: int, kind: str) -> bytes | None:
    """One fighter's bundled art. kind: 'csp' | 'stock' | 'icon'."""
    char_dir = VANILLA_ASSETS_DIR / name
    if not char_dir.is_dir():
        return None

    if kind == "icon":
        icon = char_dir / "css_icon.png"
        return icon.read_bytes() if icon.exists() else None

    costumes = _costume_dirs(char_dir)
    if not costumes:
        return None
    costume = costumes[min(color, len(costumes) - 1)]
    art = costume / ("csp.png" if kind == "csp" else "stock.png")
    return art.read_bytes() if art.exists() else None
