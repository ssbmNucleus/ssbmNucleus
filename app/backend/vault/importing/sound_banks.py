"""
Character sound banks in the vault.

Which fighter sound bank (.ssm, project files/audio/us/) each vanilla
character uses, where its sounds live in the vault
(storage/<Character>/sounds/), and seeding each character's pristine
original.ssm (+ names.json) from an extracted project tree.

No routes. Shared by the Sounds routes (vault/routes/character_sounds.py, which
owns the packs and the per-sound edits) and first-run setup
(shared/vanilla_extract/first_run_setup.py), which seeds every bank from its temp
project so sound packs can be created without ever opening a project.
"""

import json
import re
import shutil
from pathlib import Path

from core.config import STORAGE_PATH

# vanilla vault character -> fighter sound bank (project files/audio/us/)
CHAR_BANKS = {
    'Bowser': 'koopa.ssm',
    'C. Falcon': 'captain.ssm',
    'DK': 'dk.ssm',
    'Dr. Mario': 'drmario.ssm',
    'Falco': 'falco.ssm',
    'Fox': 'fox.ssm',
    'Ganondorf': 'ganon.ssm',
    'Ice Climbers': 'ice.ssm',
    'Jigglypuff': 'purin.ssm',
    'Kirby': 'kirby.ssm',
    'Link': 'link.ssm',
    'Luigi': 'luigi.ssm',
    'Mario': 'mario.ssm',
    'Marth': 'mars.ssm',
    'Mewtwo': 'mewtwo.ssm',
    'Mr. Game & Watch': 'gw.ssm',
    'Ness': 'ness.ssm',
    'Peach': 'peach.ssm',
    'Pichu': 'pichu.ssm',
    'Pikachu': 'pikachu.ssm',
    'Roy': 'emblem.ssm',
    'Samus': 'samus.ssm',
    'Yoshi': 'yoshi.ssm',
    'Young Link': 'clink.ssm',
    'Zelda': 'zs.ssm',
}

# alternate fighter names (project fighter lists, older vault names) and
# shared-bank characters, mapped onto the canonical vault folder above
CHAR_ALIASES = {
    'Sheik': 'Zelda',                 # zs.ssm holds both
    'Captain Falcon': 'C. Falcon',
    'Donkey Kong': 'DK',
    'Game & Watch': 'Mr. Game & Watch',
    'Mr. Game and Watch': 'Mr. Game & Watch',
    'GameWatch': 'Mr. Game & Watch',
    'Popo': 'Ice Climbers',
    'Nana': 'Ice Climbers',
}


def _norm(name):
    n = (name or '').lower().replace(' and ', ' & ')
    return re.sub(r'[^a-z0-9&]', '', n)


_LOOKUP = {_norm(k): k for k in CHAR_BANKS}
_LOOKUP.update({_norm(k): v for k, v in CHAR_ALIASES.items()})


def resolve_character(character):
    """Map a character name (vault folder or fighter alias) to its
    canonical vault folder + bank filename. Returns (folder, bank) or
    (None, None) for non-vanilla names."""
    canonical = _LOOKUP.get(_norm(character))
    if canonical is None:
        return None, None
    return canonical, CHAR_BANKS[canonical]


def sounds_dir(canonical):
    """The character's vault sounds folder (original.ssm, names.json, packs/)."""
    return STORAGE_PATH / canonical / 'sounds'


def capture_bank_names(bank, sdir, pdir):
    """Snapshot the bank's sound names out of the project at `pdir` (vanilla
    banks carry real names like v_mars_atk1) into sdir/names.json. A missing
    project or sounds data is a no-op."""
    if pdir is None:
        return
    sounds_data = pdir / 'data' / 'sounds'
    if not sounds_data.exists():
        return
    for gpath in sorted(sounds_data.glob('*.json')):
        try:
            g = json.loads(gpath.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            continue
        if (g.get('fileName') or '').lower() == bank.lower():
            names = [s.get('name') for s in (g.get('sounds') or [])]
            (sdir / 'names.json').write_text(
                json.dumps(names, indent=2), encoding='utf-8')
            return


def seed_original_banks(project_dir):
    """Seed every vanilla character's pristine original.ssm (+ names.json)
    from an extracted project tree (files/audio/us). First-run setup calls
    this with its temp project so sound packs can be created without ever
    opening a project. Idempotent: existing originals are left alone.
    Returns the number of banks seeded."""
    project_dir = Path(project_dir)
    audio_dir = project_dir / 'files' / 'audio' / 'us'
    seeded = 0
    for canonical, bank in CHAR_BANKS.items():
        src = audio_dir / bank
        if not src.exists():
            continue
        sdir = sounds_dir(canonical)
        original = sdir / 'original.ssm'
        if original.exists():
            continue
        sdir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, original)
        capture_bank_names(bank, sdir, project_dir)
        seeded += 1
    return seeded
