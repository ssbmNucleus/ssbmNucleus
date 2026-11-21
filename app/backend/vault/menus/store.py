"""
Where the menu mod library lives on disk and how its catalogs are read and written.

One folder per kind under storage/menus/ (icon grids, backgrounds, doors, pause
screens, HUD typefaces), each with a metadata.json catalog and a mod.json per mod.
"""

from core.config import STORAGE_PATH
from core.metadata import load_metadata, save_metadata


# ─────────────────────────────────────────────────────────────────────────────
# Storage paths
# ─────────────────────────────────────────────────────────────────────────────

MENUS_PATH = STORAGE_PATH / 'menus'
CSS_PATH = MENUS_PATH / 'css'

ICON_GRID_PATH = CSS_PATH / 'icon_grid'
ICON_GRID_PATH.mkdir(parents=True, exist_ok=True)
ICON_GRID_METADATA = ICON_GRID_PATH / 'metadata.json'

BG_PATH = CSS_PATH / 'background'
BG_PATH.mkdir(parents=True, exist_ok=True)
BG_METADATA = BG_PATH / 'metadata.json'

DOORS_PATH = CSS_PATH / 'doors'
DOORS_PATH.mkdir(parents=True, exist_ok=True)
DOORS_METADATA = DOORS_PATH / 'metadata.json'

PAUSE_PATH = MENUS_PATH / 'pause'
PAUSE_PATH.mkdir(parents=True, exist_ok=True)
PAUSE_METADATA = PAUSE_PATH / 'metadata.json'

PERCENT_PATH = MENUS_PATH / 'percent'
PERCENT_PATH.mkdir(parents=True, exist_ok=True)
PERCENT_METADATA = PERCENT_PATH / 'metadata.json'

SCREENSHOT_CANDIDATES = ['screenshot_0.png', 'screenshot.png', 'preview.png']


# ─────────────────────────────────────────────────────────────────────────────
# Catalog / mod.json persistence (parameterized — shared by icons & backgrounds)
# ─────────────────────────────────────────────────────────────────────────────

def load_catalog(metadata_path, version):
    """Load a mod catalog ({'version': ..., 'mods': [...]}) from metadata_path.

    Returns a fresh empty catalog (with the given version string) when the
    file is missing or unreadable.
    """
    return load_metadata(default={'version': version, 'mods': []}, path=metadata_path)


def save_catalog(metadata_path, data):
    save_metadata(data, path=metadata_path)


def load_mod_json(base_path, mod_id):
    """Load <base_path>/<mod_id>/mod.json, or None if missing/unreadable."""
    return load_metadata(default=None, path=base_path / mod_id / 'mod.json')


def save_mod_json(base_path, mod_id, mod):
    save_metadata(mod, path=base_path / mod_id / 'mod.json')
