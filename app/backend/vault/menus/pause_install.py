"""
Pause screen (GmPause) mod install engine: write a stored pause mod into a
GmPause.usd on disk with HSDRawViewer --pause-screen import.

No routes. Used by the pause install route (projects/routes/menus/pause.py), by
the in-game capture build (projects/install/test_build.build_pause_mod_iso) and by
the capture flow that stores the live screenshot (projects/routes/test_in_game.py).
See vault/routes/menus/pause.py for the mod storage layout.
"""

import json
import shutil
import tempfile
from pathlib import Path

import file_retry
from core.config import HSDRAW_EXE

from vault.menus.store import PAUSE_PATH, load_mod_json, save_mod_json
from vault.menus.hsd import _run_hsd_cli


def build_replacement_spec(mod, mod_dir):
    """Build the --pause-screen import replacement list for a mod.
    Raises RuntimeError when the mod's payload files are missing."""
    replacements = []
    if mod.get('textures'):
        for tex in mod['textures']:
            tex_path = mod_dir / 'textures' / tex['file']
            if not tex_path.exists():
                continue
            # User-edited slots carry arbitrary color images → RGB5A3; textures
            # extracted from a compiled mod re-inject in their original format.
            fmt = 'rgb5a3' if tex.get('replaced') else 'original'
            replacements.append({'index': tex['index'], 'png': str(tex_path), 'format': fmt})
        if not replacements:
            raise RuntimeError('No textures stored for this mod')
    elif mod.get('source') == 'image':
        picture = mod_dir / 'picture.png'
        if not picture.exists():
            raise RuntimeError('picture.png missing from mod')
        replacements.append({'target': 'main', 'png': str(picture), 'format': 'rgb5a3'})
    else:
        raise RuntimeError('No textures stored for this mod')
    return replacements


def apply_pause_mod(mod_id, gmpause_path):
    """Apply a stored pause mod to a GmPause.usd on disk (in place) via
    HSDRawViewer --pause-screen import. Raises on failure. Also used by
    test_build.build_pause_mod_iso for the in-game capture flow."""
    mod = load_mod_json(PAUSE_PATH, mod_id)
    if not mod:
        raise RuntimeError('Mod not found')
    gmpause_path = Path(gmpause_path)
    if not gmpause_path.exists():
        raise RuntimeError(f'GmPause.usd not found at {gmpause_path}')
    if not HSDRAW_EXE.exists():
        raise RuntimeError(f'HSDRawViewer not found at {HSDRAW_EXE}')

    replacements = build_replacement_spec(mod, PAUSE_PATH / mod_id)

    # A scanner may still hold the output in here; scratch left behind must not fail the install.
    with tempfile.TemporaryDirectory(prefix='pause_install_', ignore_cleanup_errors=True) as tmp:
        spec_path = Path(tmp) / 'spec.json'
        with open(spec_path, 'w', encoding='utf-8') as f:
            json.dump({'replacements': replacements}, f)

        output_usd = Path(tmp) / 'GmPause.usd'
        result = _run_hsd_cli([
            '--pause-screen', 'import',
            str(gmpause_path), str(spec_path), str(output_usd)
        ])
        if result is None:
            raise RuntimeError('HSDRawViewer --pause-screen import failed')
        if not output_usd.exists():
            raise RuntimeError('Import produced no output file')

        file_retry.retry_locked(shutil.copy, str(output_usd), str(gmpause_path))
    return mod


def set_mod_screenshot(mod_id, png_bytes):
    """Save captured PNG bytes as a pause mod's preview screenshot."""
    mod = load_mod_json(PAUSE_PATH, mod_id)
    if not mod:
        raise RuntimeError('Mod not found')
    mod_dir = PAUSE_PATH / mod_id
    mod_dir.mkdir(parents=True, exist_ok=True)
    (mod_dir / 'screenshot.png').write_bytes(png_bytes)
    mod['screenshot'] = 'screenshot.png'
    save_mod_json(PAUSE_PATH, mod_id, mod)
    return mod
