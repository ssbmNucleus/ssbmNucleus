"""
char_select.py -- character name resolution + the calibrated CSS cursor grid
(grid.json) for closed-loop selection. Ported from tools/ingame/nucleus/char_select.py
(the dev CLI main() and its Dolphin/Pipe imports dropped -- the runner only
needs the lookups here).
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _grid_path():
    """Resolve grid.json in dev (next to this module) and frozen (PyInstaller
    bundles it under <_MEIPASS>/shared/ingame/grid.json) layouts."""
    candidates = [os.path.join(HERE, "grid.json")]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "shared", "ingame", "grid.json"))
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0]


GRID_PATH = _grid_path()

ALIASES = {
    "doc": "drmario", "doctormario": "drmario",
    # the vault's display name is "C. Falcon" -> raw_key "cfalcon"
    "cfalcon": "falcon", "captainfalcon": "falcon", "captfalcon": "falcon",
    "ganon": "ganondorf", "dk3": "dk", "donkeykong": "dk",
    "sheik": "zelda",  # the CURSOR can only reach Zelda's cell; ckind() resolves
                       # sheik to her own external id first (see CKIND_NO_CELL)
    "gnw": "gameandwatch", "gw": "gameandwatch", "mrgameandwatch": "gameandwatch",
    "mrgamewatch": "gameandwatch", "gamewatch": "gameandwatch",
    "puff": "jigglypuff", "jiggs": "jigglypuff",
    "pika": "pikachu", "mew2": "mewtwo",
    "ics": "iceclimbers", "icies": "iceclimbers", "popo": "iceclimbers",
    "sopo": "iceclimbers", "solopopo": "iceclimbers",
    "yl": "younglink", "yink": "younglink",
}

# CSS grid index (Dr.Mario=0 ... Fox=10 ... Roy=24) -- the value at 0x803F0E0A.
CSS_INDEX = {
    "drmario": 0, "mario": 1, "luigi": 2, "bowser": 3, "peach": 4, "yoshi": 5,
    "dk": 6, "falcon": 7, "ganondorf": 8,
    "falco": 9, "fox": 10, "ness": 11, "iceclimbers": 12, "kirby": 13,
    "samus": 14, "zelda": 15, "link": 16, "younglink": 17,
    "pichu": 18, "pikachu": 19, "jigglypuff": 20, "mewtwo": 21,
    "gameandwatch": 22, "marth": 23, "roy": 24,
}

# External character id (the match player block's "c_kind") -- what the cursor-free
# memory selection writes to pick a fighter without steering. DISTINCT from the
# CSS grid index above: this is the engine's character id (Fox=0x02, Marth=0x09
# verified live; "no pick"/Master Hand = 0x1A).
CKIND = {
    "falcon": 0x00, "dk": 0x01, "fox": 0x02, "gameandwatch": 0x03, "kirby": 0x04,
    "bowser": 0x05, "link": 0x06, "luigi": 0x07, "mario": 0x08, "marth": 0x09,
    "mewtwo": 0x0A, "ness": 0x0B, "peach": 0x0C, "pikachu": 0x0D, "iceclimbers": 0x0E,
    "jigglypuff": 0x0F, "samus": 0x10, "yoshi": 0x11, "zelda": 0x12, "falco": 0x14,
    "younglink": 0x15, "drmario": 0x16, "roy": 0x17, "pichu": 0x18, "ganondorf": 0x19,
}

# Full engine fighters that have NO CSS CELL of their own, so they're reachable
# only by the cursor-free memory selection. Sheik is the engine's 0x13 (the gap
# between Zelda 0x12 and Falco 0x14) but the CSS only shows Zelda -- ckind()
# resolves these BEFORE the alias table collapses the name to its cell-mate;
# the cursor path (norm/cell/css_index) still lands on Zelda, and the runner
# transforms with down-B after the match starts.
#
# ICE CLIMBERS ARE DELIBERATELY *NOT* HERE, and this is the trap to avoid:
# the engine really does have a solo-Popo external id -- ftMapping_list (decomp
# src/melee/pl/player.c) maps CKIND_POPONANA (0x0E) -> {FTKIND_POPO,
# FTKIND_NANA} and CHKIND_POPO (0x20) -> {FTKIND_POPO, 0xFF} = no partner --
# and booting 0x20 does spawn Popo alone. It was tried and REJECTED for two
# reasons, both verified 2026-07-31:
#   1) 0x20 ignores the costume slot. colors 0-3 all render the default blue
#      (`output/popo-colors` contact sheet), while 0x0E gives blue/green/
#      orange/red -- so it cannot grade a COSTUME, which is the only reason to
#      photograph Popo alone.
#   2) 0x20 is inside the m-ex ADDED-FIGHTER range (0x1A = the 1st added
#      fighter), so on any built Nucleus ISO with >= 7 added characters it
#      silently spawns somebody else entirely.
# Nana is suppressed at CAPTURE time instead -- gamestate.Follower.stash(),
# used by frameshot -- which keeps the real Ice Climbers costume load.
CKIND_NO_CELL = {"sheik": 0x13}


def load_grid():
    with open(GRID_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def raw_key(name):
    """The name reduced to lowercase alphanumerics, BEFORE alias resolution --
    use this to recognise a specific request (e.g. sheik) that norm() would
    collapse into its CSS cell-mate."""
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def norm(name):
    key = raw_key(name)
    return ALIASES.get(key, key)


def css_index(name):
    return CSS_INDEX.get(norm(name))


def ckind(name):
    """External character id for the cursor-free memory selection, or None for an
    unknown / custom fighter (caller should fall back to the cursor)."""
    key = raw_key(name)
    if key in CKIND_NO_CELL:
        return CKIND_NO_CELL[key]
    return CKIND.get(ALIASES.get(key, key))


def cell(grid, name):
    key = norm(name)
    if key not in grid:
        raise KeyError(f"no grid cell for '{name}' (known: {', '.join(sorted(grid))})")
    return grid[key]


def select(cur, grid, name, costume=0, lock=True):
    x, y = cell(grid, name)
    return cur.select(x, y, costume=costume, lock=lock)
