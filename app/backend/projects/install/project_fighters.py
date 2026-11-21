"""
The open project's fighters on disk: a fighter's JSON found by name in
data/fighters (no MexCLI call, which can lock the files), and which vanilla
costume file a project costume row replaces.

No routes. Used by the project routes (projects/routes/project.py) and the
project costume routes (projects/routes/costumes.py).
"""

import json
from pathlib import Path

from core.constants import CHAR_PREFIXES, VANILLA_CSS_COLOR_ORDER
from core.state import get_current_project_path


def find_fighter_json_by_name(fighter_name):
    """Find fighter JSON file by scanning data/fighters/ directory.
    Returns (path, data) tuple or (None, None) if not found.
    This avoids calling MexCLI which can cause file locking issues."""
    current_project_path = get_current_project_path()
    if current_project_path is None:
        return None, None

    fighters_dir = current_project_path.parent / "data" / "fighters"
    if not fighters_dir.exists():
        return None, None

    # Scan the project's fighter JSON files to find matching name
    from mexcli.project import fighter_files
    for json_file in fighter_files(current_project_path):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if data.get('name', '').lower() == fighter_name.lower():
                    return json_file, data
        except (json.JSONDecodeError, IOError):
            continue

    return None, None


def vanilla_replacement_target(fighter, costume):
    """Use the original DAT identity, not the current/reorderable row number."""
    name = costume.get('replacesVanillaFile') or costume.get('fileName') or ''
    prefix = CHAR_PREFIXES.get(fighter)
    colors = VANILLA_CSS_COLOR_ORDER.get(fighter, [])
    stem = Path(name.rstrip('.')).stem
    if not prefix or len(stem) != 6 or stem[:4] != f'Pl{prefix}' or stem[4:] not in colors:
        return None
    return {'file': name, 'color': stem[4:], 'visibilityIndex': colors.index(stem[4:])}
