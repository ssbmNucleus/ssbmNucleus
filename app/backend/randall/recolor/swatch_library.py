"""Generated material swatches, kept by theme so a repeat theme costs nothing.

Every generate_material call is a billed image request and a model round spent
writing prompts. The swatches it returns are ordinary working files that
already persist, so this is only an index: which saved swatch was drawn for
which surface theme ("lava", "camo"). A later request naming the same theme is
offered those swatches first; the model still decides whether one fits.
"""
import json
import re
import threading
import time

from shared import mod_files

# Themes that are a SURFACE, not a colour scheme. "Lava Bowser" recoloured red
# reads as a red Bowser; the theme needs generated detail (cracks, glow, grain).
# Plain metals and colours (gold, silver, black) stay palette work.
SURFACE_WORDS = re.compile(
    r'\b(lava|magma|molten|fire|flame|flaming|ice|icy|frozen|crystal|crystals|gem|diamond|'
    r'metal|metallic|chrome|steel|iron|rust|rusty|stone|rock|marble|wood|wooden|camo|'
    r'camouflage|zebra|leopard|tiger|snake|scales|scaly|galaxy|space|cosmic|nebula|'
    r'circuit|plaid|tartan|denim|leather|fur|furry|slime|zombie|lightning|electric|'
    r'water|ocean|glitter|holographic|aztec|tribal|mosaic|graffiti)\b', re.I)
# Near-synonyms share one theme, so "molten" finds swatches drawn for "lava".
SAME_THEME = {'magma': 'lava', 'molten': 'lava', 'flame': 'fire', 'flaming': 'fire',
              'icy': 'ice', 'frozen': 'ice', 'crystals': 'crystal', 'metallic': 'metal',
              'rusty': 'rust', 'rock': 'stone', 'wooden': 'wood', 'camouflage': 'camo',
              'scaly': 'scales', 'cosmic': 'galaxy', 'space': 'galaxy', 'nebula': 'galaxy',
              'furry': 'fur', 'electric': 'lightning', 'ocean': 'water'}
MAX_ENTRIES = 400
OFFER = 6
_lock = threading.Lock()


def surface_themes(text):
    """Surface themes the text names, canonical and in order, without repeats."""
    text = re.sub(r'\bice climbers?\b', ' ', text or '', flags=re.I)   # a fighter, not a theme
    return list(dict.fromkeys(SAME_THEME.get(m.casefold(), m.casefold())
                              for m in SURFACE_WORDS.findall(text)))


def _path():
    return mod_files.root().parent / 'swatch_library.json'


def _read():
    try:
        entries = json.loads(_path().read_text(encoding='utf-8'))
        return entries if isinstance(entries, list) else []
    except (OSError, ValueError):
        return []


def record(materials):
    """Index freshly generated swatches ({prompt, file_id}) by their themes."""
    fresh = [{'prompt': m['prompt'], 'file_id': m['file_id'], 'themes': surface_themes(m['prompt']),
              'created': round(time.time())} for m in materials if surface_themes(m.get('prompt'))]
    if not fresh:
        return
    with _lock:
        entries = (_read() + fresh)[-MAX_ENTRIES:]
        _path().write_text(json.dumps(entries, indent=1), encoding='utf-8')


def find(themes):
    """Saved swatches for any of these themes, newest first; missing files skipped."""
    wanted = set(themes)
    found = []
    for entry in reversed(_read()):
        if wanted & set(entry.get('themes') or ()):
            try:
                mod_files.resolve(entry['file_id'])
            except (ValueError, OSError, KeyError):
                continue
            found.append({'prompt': entry['prompt'], 'file_id': entry['file_id']})
            if len(found) == OFFER:
                break
    return found
