"""Open a vanilla costume as a working file, the way the vault tools open a mod.

Randall could only ever reach vault contents, so "recolor vanilla Fox" had no
answer and it would substitute whatever mod for that character happened to be
installed. These costumes are extracted from the user's own ISO into
`VANILLA_ASSETS_DIR`; nothing Nintendo-derived ships with the app.
"""
import hashlib
from pathlib import Path

from core import config
from core.constants import CHAR_PREFIXES, VANILLA_CSS_COLOR_ORDER

from shared import mod_files

# Four Game & Watch colors share one DAT; the color lives in the MxDt row, so
# only the neutral file exists on disk.
SHARED_DAT = {'Mr. Game & Watch'}


def _character(name):
    if not isinstance(name, str):
        raise ValueError('Name a vanilla character.')
    for known in VANILLA_CSS_COLOR_ORDER:
        if known.lower() == name.strip().lower():
            return known
    raise ValueError(f'No vanilla costumes for "{name}". Use a base Melee character name.')


def _costume_dir(character, color):
    prefix = CHAR_PREFIXES.get(character)
    if not prefix:
        raise ValueError(f'No vanilla costume mapping for {character}.')
    code = f'Pl{prefix}{color}'
    return config.VANILLA_ASSETS_DIR / character / code, code


def available_colors(character):
    """Color slots that are actually extracted, in CSS order."""
    colors = ['Nr'] if character in SHARED_DAT else VANILLA_CSS_COLOR_ORDER.get(character, [])
    found = []
    for color in colors:
        directory, code = _costume_dir(character, color)
        if (directory / f'{code}.dat').is_file():
            found.append(color)
    return found


def vanilla_assets_ready():
    """True when at least one character's costumes have been extracted."""
    try:
        return any(available_colors(name) for name in ('Fox', 'Marth', 'Falco'))
    except (OSError, ValueError):
        return False


def open_vanilla_file(character, color=None):
    name = _character(character)
    colors = available_colors(name)
    if not colors:
        raise ValueError(f'Vanilla costumes for {name} are not extracted yet. '
                         'Refresh vanilla assets in Settings and try again.')
    # An omitted color used to return the slot list and ask for a second call.
    # The answer was 'Nr' almost every time, and the handshake cost a whole
    # model round -- measured at 8s of a 74s turn -- for a list the model could
    # have been handed alongside the file. Open the default and list the rest.
    if color is None:
        color = colors[0] if 'Nr' not in colors else 'Nr'
    chosen = next((c for c in colors if c.lower() == str(color).strip().lower()), None)
    if chosen is None:
        raise ValueError(f'{name} has no extracted "{color}" costume. Available: {", ".join(colors)}.')
    directory, code = _costume_dir(name, chosen)
    data = (directory / f'{code}.dat').read_bytes()
    origin = {'character': name, 'vanilla_color': chosen, 'costume_code': code,
              'archive_sha256': hashlib.sha256(data).hexdigest()}
    file = mod_files.register(data, f'{code}.dat', origin=origin)
    result = {'reading': True, 'files': [file], 'character': name, 'color': chosen,
              'costume_code': code, 'colors': colors,
              'note': 'Immutable copy of a vanilla costume. Editing it never touches the '
                      'extracted assets or the vault. `colors` lists this character\'s other '
                      'extracted slots; call again with one only if a different slot is wanted.'}
    preview = directory / 'csp.png'
    if preview.is_file():
        result['files'].append(mod_files.register(preview.read_bytes(), f'{code} portrait.png',
                                                  origin=dict(origin, preview=True)))
    return result
