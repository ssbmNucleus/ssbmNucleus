"""
What a test-in-game build drives, resolved from a request: the build manifest
(inline or from a file), the inputs every build needs (vanilla ISO, Slippi
Dolphin path), and an Ice Climbers Popo skin's paired Nana costume.

No routes. Used by the test-in-game routes (projects/routes/test_in_game.py).
"""

import json
import logging
import os
from core.config import STORAGE_PATH
from core.metadata import load_metadata

logger = logging.getLogger(__name__)


def _paired_nana_zip(character, skin_id):
    """The paired Nana zip path (str) for an Ice Climbers Popo skin, or None.
    Mirrors the frontend's pairing (useCostumes.js): the selected skin's
    `paired_nana_id` names a hidden Nana skin entry whose zip lives in storage."""
    try:
        chars = (load_metadata() or {}).get('characters', {})
        skin = next((s for s in chars.get(character, {}).get('skins', [])
                     if s.get('id') == skin_id), None)
        pair_id = (skin or {}).get('paired_nana_id')
        if not pair_id:
            return None
        for char_name, char_data in chars.items():
            nana = next((s for s in char_data.get('skins', [])
                         if s.get('id') == pair_id), None)
            if nana and nana.get('filename'):
                return str(STORAGE_PATH / char_name / nana['filename'])
        logger.warning(f"paired Nana skin {pair_id} not found in storage metadata")
    except Exception:
        logger.warning("could not resolve a paired Nana costume", exc_info=True)
    return None


def _load_manifest(data):
    """Resolve the build manifest (what to drive) from the request, tolerating
    its absence -- without one we fall back to a boot-health check."""
    manifest = data.get('manifest')
    if isinstance(manifest, dict) and manifest:
        return manifest
    manifest_path = data.get('manifestPath')
    if manifest_path and os.path.exists(manifest_path):
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not read manifestPath {manifest_path}: {e}")
    return None


# --------------------------------------------------------------------------- #
# Shared build->test job for the single-mod testers (custom character / custom  #
# stage / stage skin). `build_callable(progress_cb, log)` builds the temp ISO   #
# at out_iso and returns (manifest, extra) -- the manifest tells the runner what #
# to drive, extra is merged into the test_complete payload.                     #
# --------------------------------------------------------------------------- #
def _common_inputs(data):
    vanilla = data.get('vanillaIsoPath')
    slippi = data.get('slippiDolphinPath')
    obs = int(data.get('observeSeconds', 9) or 9)
    if not vanilla or not os.path.exists(vanilla):
        return None, None, None, f'Vanilla Melee ISO not found: {vanilla}. Set it in Settings.'
    if not slippi:
        return None, None, None, 'slippiDolphinPath is required (set the Slippi path in Settings).'
    return vanilla, slippi, obs, None
