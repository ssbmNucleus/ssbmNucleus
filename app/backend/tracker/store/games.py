"""An indexed game's row, and what a replay's ids map to in the app: the vanilla
asset folders (stock and stage icons) and the Vault stage folders (Watch with
mods). Shared by the Replays, Lite, Watch, icon and Combo Video routes.
"""
import os


# .slp external character id -> vanilla assets folder name
EXT_CHAR_FOLDERS = {
    0: "C. Falcon", 1: "DK", 2: "Fox", 3: "Mr. Game & Watch", 4: "Kirby",
    5: "Bowser", 6: "Link", 7: "Luigi", 8: "Mario", 9: "Marth",
    10: "Mewtwo", 11: "Ness", 12: "Peach", 13: "Pikachu", 14: "Ice Climbers",
    15: "Jigglypuff", 16: "Samus", 17: "Yoshi", 18: "Zelda", 19: "Sheik",
    20: "Falco", 21: "Young Link", 22: "Dr. Mario", 23: "Roy", 24: "Pichu",
    25: "Ganondorf",
}
# CHAR_PREFIXES keys mostly match the folder names; G&W is the exception
_PREFIX_KEY_OVERRIDES = {"Mr. Game & Watch": "G&W"}

# stage id -> Gr file code (SSS icons copied out of the user's own game,
# menu_refs.stage_art_path); the 6 tourney stages use the full art first-run
# setup extracts into utility/assets/stages instead.
STAGE_GR_CODES = {
    4: "Cs", 5: "Kg", 6: "Ze", 7: "Cn", 9: "Ot", 10: "Mc", 11: "Rc",
    12: "Gd", 13: "Gb", 14: "Sh", 15: "Kr", 16: "Yt", 17: "Gr", 18: "Fs",
    19: "I1", 20: "I2", 22: "Ve", 23: "Pu", 24: "Bb", 25: "Im", 27: "Fz",
    29: "Oy", 30: "Ok",
}
STAGE_ART_FILES = {
    2: "fountain of dreams.png", 3: "pokemon stadium.png",
    8: "yoshis story.png", 28: "dreamland.png",
    31: "battlefield.png", 32: "final destination.png",
}
# every stage id a vanilla replay can legitimately have — modded stage ids
# ("Stage 326") are excluded from the browser entirely
VANILLA_STAGE_IDS = sorted(set(STAGE_GR_CODES) | set(STAGE_ART_FILES))

# replay stage id -> (vault stage folder, project Gr file code, root ext).
# Only the 6 tourney stages have vault variants to offer. Derived from the
# stage registry (core/stages.py); the DAS root is the English .usd for
# Stadium only.
from core.stages import LEGAL_STAGE_CODES as _LEGAL_STAGE_CODES  # noqa: E402
from core.stages import STAGES_BY_CODE as _STAGES_BY_CODE  # noqa: E402

STAGE_VAULT = {
    _STAGES_BY_CODE[code]["slippi_id"]: (
        _STAGES_BY_CODE[code]["folder"],
        code,
        ".usd" if _STAGES_BY_CODE[code]["dual_root"] else ".dat",
    )
    for code in _LEGAL_STAGE_CODES
}


def _validate_indexed_path(conn, path):
    """Only act on paths that are actually in the index (no arbitrary exec)."""
    if not path:
        return None
    row = conn.execute("SELECT path FROM games WHERE path=?", (path,)).fetchone()
    return row["path"] if row and os.path.exists(row["path"]) else None


def _game_row(conn, game_id):
    row = conn.execute("SELECT * FROM games WHERE id=? AND parse_ok=1",
                       (game_id,)).fetchone()
    return row


def _fighter_name(ext_id):
    folder = EXT_CHAR_FOLDERS.get(ext_id)
    return _PREFIX_KEY_OVERRIDES.get(folder, folder) if folder else None
