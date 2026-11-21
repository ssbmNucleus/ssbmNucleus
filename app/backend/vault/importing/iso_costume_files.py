"""
Which files on a disc are costumes: the costume archive name pattern, the
two-letter fighter code table, the fighters an ISO scan skips, m-ex custom
fighter slots, and normalizing an archive name to .dat.
"""

from __future__ import annotations

import os
import re
from typing import Optional


# ---------- Constants ----------

CHAR_EXTENSIONS = {
    '.dat', '.lat', '.rat', '.uat', '.vat', '.wat', '.xat', '.yat', '.zat',
    '.aat', '.bat', '.cat', '.eat', '.fat', '.gat', '.hat', '.iat', '.jat', '.kat',
    '.1at', '.2at', '.3at', '.4at', '.5at', '.6at', '.7at', '.8at', '.9at', '.0at',
}

# Costume archive stem: PlXxYy, optionally followed by the suffixes an m-ex
# build gives ADDED costumes -- Nucleus installs name them `<code>Mod`, and
# mexLib's FileManager de-duplicates with `_001`, `_002`, ... (PlSkNrMod.dat,
# PlMtNrMod_001.dat, PlZdNr_001.dat). Groups: fighter code, colour, variant.
_COSTUME_STEM_RE = re.compile(r'^pl(..)(..)((?:mod)?(?:_\d{3,})?)$', re.IGNORECASE)


# ---------- Job state ----------

# Two-letter `Pl<Xx>...` prefix → canonical character name, per
# docs/wiki/reference/new-414/Melee-Files.md. Used to override DATParser's symbol-based
# detection when filename and symbol disagree (e.g. male wireframe DATs share
# the "ftDataBoy" symbol with Young Link, so symbol alone tags the wireframe
# as Young Link). Filename is the more reliable signal — modders don't usually
# rename costume files, they just edit contents.
CHAR_CODE_TO_NAME = {
    'Bo': 'Male Wireframe',
    'Ca': 'C. Falcon',
    'Ch': 'Crazy Hand',
    'Cl': 'Young Link',
    'Dk': 'DK',
    'Dr': 'Dr. Mario',
    'Fc': 'Falco',
    'Fe': 'Roy',
    'Fx': 'Fox',
    'Gk': 'Giga Bowser',
    'Gl': 'Female Wireframe',
    'Gn': 'Ganondorf',
    'Gw': 'Mr. Game & Watch',
    'Kb': 'Kirby',
    'Kp': 'Bowser',
    'Lg': 'Luigi',
    'Lk': 'Link',
    'Mh': 'Master Hand',
    'Mr': 'Mario',
    'Ms': 'Marth',
    'Mt': 'Mewtwo',
    'Nn': 'Ice Climbers (Nana)',
    'Ns': 'Ness',
    'Pc': 'Pichu',
    'Pe': 'Peach',
    'Pk': 'Pikachu',
    'Pp': 'Ice Climbers',
    'Pr': 'Jigglypuff',
    'Sb': 'Sandbag',
    'Sk': 'Sheik',
    'Ss': 'Samus',
    'Ys': 'Yoshi',
    'Zd': 'Zelda',
}


# Characters the user never wants surfaced in scan results. Wireframes and
# bosses aren't selectable in normal play so showing them as importable skins
# is just noise.
SKIP_CHARACTERS = {
    # Kirby + G&W were skipped while their costume imports were broken; both are
    # fixed now (see kirby-costume-fix / gw-csp-fix), so they scan like any other
    # character. Only truly non-importable fighters stay here.
    'Male Wireframe', 'Female Wireframe',
    'Master Hand', 'Crazy Hand', 'Giga Bowser', 'Sandbag',
}


def _character_from_filename(path: str) -> Optional[str]:
    """Map `PlXxYy.dat` -> character name via the 2-char code lookup table."""
    name = os.path.basename(path)
    stem = os.path.splitext(name)[0]
    if len(stem) < 4 or not stem.lower().startswith('pl'):
        return None
    return CHAR_CODE_TO_NAME.get(stem[2:4])


def _is_custom_fighter_file(path: str) -> bool:
    """True for costume files that belong to an m-ex CUSTOM fighter slot.

    Added fighters get freshly generated Pl codes (e.g. PlQpQg.dat in a build
    with a custom 'Qp' character). Their CONTENT still carries the symbols of
    whatever vanilla fighter they were cloned from, so symbol-based detection
    would happily misfile them as e.g. Fox skins — but they belong to the
    custom fighter (the custom-characters ISO scan extracts them properly,
    fighter + costumes together). Filename code not in the vanilla table =
    custom fighter slot.

    Extra COSTUME slots for vanilla fighters (PlFxYe, PlFxAg, ...) keep the
    vanilla character code and are NOT matched by this.
    """
    name = os.path.basename(path)
    stem = os.path.splitext(name)[0]
    if len(stem) < 4 or not stem.lower().startswith('pl'):
        return False
    return stem[2:4] not in CHAR_CODE_TO_NAME


def _is_character_file(path: str) -> bool:
    """Decide whether a filename looks like a per-color costume archive.

    Per docs/wiki/reference/new-414/Melee-Files.md the Melee `Pl*` namespace covers several
    different file kinds — only one of them is a costume:

        PlCo.dat        common player data    (skip)
        PlXx.dat        shared character data (skip — 4-char stem)
        PlXxAJ.dat      animation joint file  (skip — 'AJ' suffix)
        PlXxYy.dat      *costume* archive     (keep — 6-char stem)

    DATParser.is_character_costume() filters out anything that slipped through
    at the content level via the `Ply...5K_Share_joint` symbol check, but it's
    expensive (parses every DAT). This pre-filter trims the obvious shared /
    animation files by name alone so we never even hash them.

    Color (last 2 chars) is intentionally NOT constrained — mods are free to
    invent new slot codes like `Zz`, `Q1`, etc., and we want to surface those.

    Costumes an m-ex build ADDED carry a variant suffix (PlSkNrMod.dat,
    PlMtNrMod_001.dat) — see _COSTUME_STEM_RE. Requiring a bare 6-char stem
    made every Nucleus-built ISO scan as "no new content". Kirby copy-hat
    (PlKbCpFx, PlKbNrCpDk) and demo-wait (PlFxDViWaitAJ) files still fail.
    """
    stem, ext = os.path.splitext(os.path.basename(path))
    if ext.lower() not in CHAR_EXTENSIONS:
        return False
    parts = _split_costume_stem(stem)
    # PlXxAJ.dat is the animation joint archive — same shape as a costume
    # but the "AJ" colour gives it away.
    return parts is not None and parts[1].lower() != 'aj'


def _split_costume_stem(stem: str) -> Optional[tuple[str, str, str]]:
    """`PlMtNrMod_001` -> ('PlMtNr', 'Nr', 'mod_001'); None if not a costume stem.
    PlXx (shared data, 4 chars) and PlCo never match."""
    m = _COSTUME_STEM_RE.match(stem)
    if not m:
        return None
    return stem[:6], m.group(2), m.group(3).lower()


def _ensure_dat_ext(name: str) -> str:
    """Normalize an archive filename to .dat (or leave .usd alone).

    MEX-built ISOs use extra-slot extensions (.lat / .rat / .xat / ...) as a
    slot marker, but the binary format is identical to .dat. We rename to
    .dat so HSDRawViewer and the import helpers (which only recognise .dat
    and .usd) treat them as costumes. Don't *append* .dat on top of the old
    extension — replace it, otherwise we get names like PlMrNr.lat.dat.
    """
    if not name:
        return 'costume.dat'
    if name.lower().endswith(('.dat', '.usd')):
        return name
    stem, _ = os.path.splitext(name)
    return stem + '.dat'
