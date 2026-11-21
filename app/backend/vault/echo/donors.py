"""
Echo donors: the vanilla fighter an Echo (or a Randall clone) is built on.

Name resolution (loose names, MexCLI's fighter names, CHAR_PREFIXES codes),
the fighters out of scope (two data files), the donor's vanilla reference DAT,
and the donor's full package -- exported from the current project with
`mexcli export-fighter` once and cached under storage/echo/donors/<prefix>.zip.

Used by Randall's clone adapter (randall/assistant/clone_character.py).
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

from core.config import STORAGE_PATH
import mexcli.commands
from core.state import get_current_project_path
from shared.rendering.hitbox_elements import CHAR_PREFIXES

DONOR_CACHE = STORAGE_PATH / 'echo' / 'donors'

# Fighters whose data lives in more than one Pl*.dat (transforms / duo) are
# out of the v1 Echo scope: the diff would need two donors.
UNSUPPORTED = {
    'Ice Climbers': 'Nana + Popo share one fighter (two data files)',
    'Zelda': 'transforms into Sheik (two data files)',
    'Sheik': 'transforms into Zelda (two data files)',
}

# MexCLI fighter names differ from the vault's display names in a few places.
MEXCLI_NAMES = {
    'C. Falcon': ['C. Falcon', 'Captain Falcon'],
    'DK': ['DK', 'Donkey Kong'],
    'G&W': ['G&W', 'Mr. Game & Watch', 'Game & Watch'],
    'Dr. Mario': ['Dr. Mario', 'Dr Mario'],
    'Jigglypuff': ['Jigglypuff', 'Purin'],
    'Young Link': ['Young Link', 'Y. Link'],
}


def _norm(s: str) -> str:
    return re.sub(r'[^0-9a-z]+', '', str(s).lower())


def donor_name(name: str) -> str:
    """Loose donor name -> the CHAR_PREFIXES key. Raises KeyError."""
    n = _norm(name)
    for key in CHAR_PREFIXES:
        if _norm(key) == n or any(_norm(a) == n for a in MEXCLI_NAMES.get(key, [])):
            return key
    for key, prefix in CHAR_PREFIXES.items():
        if _norm(prefix) == n:
            return key
    raise KeyError(f"unknown donor {name!r}")


def donor_dat(name: str) -> bytes:
    from shared.vanilla_extract import vanilla_refs
    key = donor_name(name)
    p = vanilla_refs.ensure_vanilla_ref(f"{CHAR_PREFIXES[key]}.dat")
    if p is None:
        raise FileNotFoundError(
            f"no vanilla reference for {key}: record the vanilla ISO in Setup first")
    return Path(p).read_bytes()


def export_donor_zip(donor_key: str) -> bytes:
    """The donor's full package, exported from the current project once and
    cached under storage/echo/donors/<prefix>.zip."""
    prefix = CHAR_PREFIXES[donor_key]
    DONOR_CACHE.mkdir(parents=True, exist_ok=True)
    cached = DONOR_CACHE / f"{prefix}.zip"
    if cached.is_file() and cached.stat().st_size > 0:
        return cached.read_bytes()
    project = get_current_project_path()
    if not project:
        raise RuntimeError("no project open -- creating an Echo needs a project to "
                           "export the donor's costumes and sounds from")
    listing = mexcli.commands.run_json(['list-fighters', project])
    wanted = {_norm(n) for n in [donor_key, *MEXCLI_NAMES.get(donor_key, [])]}
    index = None
    for f in listing.get('fighters') or []:
        if isinstance(f, dict) and _norm(f.get('name', '')) in wanted and not f.get('isMexFighter'):
            index = f.get('internalId')
            break
    if index is None:
        raise RuntimeError(f"{donor_key} not found in the current project's fighter list")
    tmp = Path(tempfile.mktemp(suffix='.zip', prefix='nucleus_echo_donor_'))
    out = mexcli.commands.run_json(['export-fighter', project, index, tmp])
    if not out.get('success') or not tmp.is_file():
        raise RuntimeError(f"export-fighter failed: {out.get('error') or out}")
    data = tmp.read_bytes()
    tmp.unlink(missing_ok=True)
    cached.write_bytes(data)
    return data
