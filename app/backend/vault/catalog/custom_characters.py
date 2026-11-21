"""
Custom characters in the vault, outside the routes: the index reads and writes
(metadata.json["custom_characters"]), slug allocation under the vault root,
the franchise (series) table, fighter.zip rewriting that keeps the embedded
fighter.json in step with the vault copy, and the active-CSP lookup for a skin.

    storage/custom_characters/<slug>/
        fighter.zip     (original ZIP preserved for re-export)
        fighter.json    (extracted metadata)
        css_icon.png    (CSS icon for grid display)
        csp_0.png ...   (per-costume CSP portraits)

No routes. Shared by the vault Custom Characters routes
(vault/routes/custom_characters/), the ISO scan engine
(vault/importing/custom_character_scan.py) and the install routes
(projects/routes/custom_characters.py). Slug naming and the bundled-costume
mirror are vault/importing/custom_character_package.py.
"""

import json
import zipfile

import file_retry
from core.config import STORAGE_PATH, CUSTOM_CHARACTERS_PATH
from core.metadata import load_metadata, save_metadata
from vault.importing.custom_character_package import DEFAULT_META as _DEFAULT_META, dedupe_slug


# Vanilla m-ex series list (index = seriesID in a fresh project).
# The vanilla emblems are copied out of the user's own project (below).
SERIES_NAMES = [
    'F-Zero', 'Donkey Kong', 'Star Fox', 'Game & Watch', 'Ice Climber',
    'Kirby', 'Super Mario', 'Fire Emblem', 'EarthBound', 'Pokémon',
    'Metroid', 'Smash Bros.', 'Yoshi', 'The Legend of Zelda',
    'Master Hand', 'Crazy Hand', 'Special Stages',
]
# Derived from the user's own project at first run and on project open
# (menu_refs.derive_menu_refs copies them out of its assets/series/); nothing
# ships. Resolved per call, not at import.
def SERIES_ASSETS_DIR():
    from shared.vanilla_extract.menu_refs import series_dir
    return series_dir()


def _dedupe_slug(slug):
    """`slug` or `slug-N`, free under this module's CUSTOM_CHARACTERS_PATH (the
    routes' root, which tests repoint)."""
    return dedupe_slug(slug, CUSTOM_CHARACTERS_PATH)


def _read_metadata():
    # Delegates to the core.metadata DAL (the single seam the SQLite migration
    # swaps behind); keeps this module's historical 'custom_characters' default.
    data = load_metadata(default=dict(_DEFAULT_META))
    data.setdefault('custom_characters', [])
    return data


def _write_metadata(data):
    # DAL write is atomic (temp + os.replace); pairs with metadata_lock /
    # metadata_transaction at the mutation sites to prevent lost updates.
    save_metadata(data)


def _find_entry(metadata, slug):
    for c in metadata.get('custom_characters', []):
        if c['slug'] == slug:
            return c
    return None


def _series_icon_path(series_id):
    p = SERIES_ASSETS_DIR() / f'icon_{series_id}.png'
    return p if p.exists() else None


def _series_name(series_id):
    if isinstance(series_id, int) and 0 <= series_id < len(SERIES_NAMES):
        return SERIES_NAMES[series_id]
    return None


def _rewrite_zip_fighter_json(zip_path, out_path, mutate_json=None, drop_entries=None,
                              replace_entries=None):
    """Copy a fighter zip to out_path, optionally mutating the embedded
    fighter.json, dropping entries by name, and/or replacing entry contents
    (replace_entries: {basename: bytes}; missing entries are appended)."""
    drop = {n.lower() for n in (drop_entries or [])}
    replace = {n.lower(): b for n, b in (replace_entries or {}).items()}
    replaced = set()
    with zipfile.ZipFile(zip_path, 'r') as src, \
            zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            basename = item.filename.split('/')[-1]
            if basename.lower() in drop:
                continue
            data = src.read(item.filename)
            if mutate_json and basename.lower() == 'fighter.json':
                meta = json.loads(data)
                meta = mutate_json(meta) or meta
                data = json.dumps(meta, indent=2).encode('utf-8')
            if basename.lower() in replace:
                data = replace[basename.lower()]
                replaced.add(basename.lower())
            dst.writestr(item, data)
        for name, data in (replace_entries or {}).items():
            if name.lower() not in replaced:
                dst.writestr(name, data)


def _rewrite_fighter_zip(char_dir, mutate_json=None, drop_entries=None, replace_entries=None):
    """Rewrite fighter.zip in place: optionally mutate the embedded
    fighter.json (mutate_json receives and returns the parsed dict), drop
    entries by name, and/or replace entry contents. add-fighter reads the
    zip's own fighter.json and assets, so any vault-side change must be
    mirrored here to survive install.
    """
    zip_path = char_dir / 'fighter.zip'
    if not zip_path.exists():
        return False
    tmp_path = zip_path.with_suffix('.zip.tmp')
    _rewrite_zip_fighter_json(zip_path, tmp_path, mutate_json, drop_entries, replace_entries)
    file_retry.replace(tmp_path, zip_path)
    return True


def _update_fighter_json_everywhere(char_dir, mutate):
    """Apply `mutate(fighter_dict)` to BOTH the storage fighter.json and the
    one embedded in fighter.zip."""
    fighter_json_path = char_dir / 'fighter.json'
    with open(fighter_json_path, 'r', encoding='utf-8') as f:
        fighter_data = json.load(f)
    mutate(fighter_data)
    with file_retry.retry_locked(open, fighter_json_path, 'w', encoding='utf-8') as f:
        json.dump(fighter_data, f, indent=2)
    _rewrite_fighter_zip(char_dir, mutate_json=lambda m: (mutate(m), m)[1])
    return fighter_data


# fixed entry names + canonical sizes from MexFighterAssets
FIGHTER_ASSET_SPECS = {
    'icon': ('icon.png', (64, 56)),
    'big_banner': ('big_banner.png', (256, 28)),
    'small_banner': ('small_banner.png', (120, 24)),
}


def _active_csp_path_for_skin(storage_key, skin):
    """Resolve a skin's active SD alternate CSP, if one is selected.

    Shared with the vanilla-costume install path (core.active_portrait), which
    bakes the same pick into vault-costume installs."""
    from core.active_portrait import active_alt_csp_path
    return active_alt_csp_path(STORAGE_PATH / storage_key, skin)
