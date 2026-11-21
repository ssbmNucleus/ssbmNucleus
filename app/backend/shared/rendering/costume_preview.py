"""
A vault costume's portrait preview: render a stored costume ZIP's HD
character-select portrait without writing anything.

Shared by the Vault's portrait retakes (vault/routes/storage_costumes/csp.py: the
single generate-csp and the per-character / vault-wide bulk retakes) and
Randall's preview_portrait tool (randall/assistant/tools.py), so all of them
use the identical render path.
"""
import json
import logging
import os
import tempfile
import zipfile
from pathlib import Path

from core.config import STORAGE_PATH
from core.costume_files import find_extracted_costume_archive
from core.safe_archive import safe_extract_zip
from shared.rendering.portrait import render_portrait

logger = logging.getLogger(__name__)


def paired_nana_zip(metadata, skin_meta):
    """The paired hidden Nana skin's zip path for an Ice Climbers Popo skin, or
    None. A vault IC skin is a Popo-only zip; Nana's DAT lives in a separate
    hidden skin entry named by `paired_nana_id` (mirrors test_in_game's
    _paired_nana_zip / the frontend's useCostumes.js pairing)."""
    pair_id = (skin_meta or {}).get('paired_nana_id')
    if not pair_id or not metadata:
        return None
    for char_name, char_data in (metadata.get('characters') or {}).items():
        nana = next((s for s in char_data.get('skins', [])
                     if s.get('id') == pair_id), None)
        if nana and nana.get('filename'):
            path = STORAGE_PATH / char_name / nana['filename']
            if path.exists():
                return path
    logger.warning(f"Paired Nana skin {pair_id} not found in storage")
    return None


def gw_colors_from_zip(zip_path):
    """A costume's G&W colour mod from its gaw.json sidecar, or None.

    Mr. Game & Watch renders white and is recoloured at load. A colour mod keeps
    the vanilla art and stores its colours in this sidecar, so a render that does
    not read it falls back to vanilla slot 0 -- BLACK. Mirrors the same read in
    vault/importing/unified/characters.py.
    """
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            name = next((n for n in zf.namelist()
                         if os.path.basename(n).lower() == 'gaw.json'), None)
            if not name:
                return None
            from core.gaw_colors import gw_colors_from_hex
            parsed = json.loads(zf.read(name))
            return gw_colors_from_hex(parsed.get('fill'), parsed.get('outline'))
    except Exception as e:  # noqa: BLE001 - colours are an upgrade, never a gate
        logger.warning(f"Unreadable gaw.json in {zip_path}: {e}")
        return None


def render_costume_preview(character, zip_path, pose_name, nana_zip_path=None, *, work_dir=None):
    """Render a costume's HD portrait for the given active pose (pose_name=None =>
    default) and return (png_bytes, pose_label). Writes nothing. Shared by the
    single retake (generate_costume_csp) and the per-character bulk retake so both
    use the identical render path -- and both flow through the CSP render pool
    when one is active. Raises on a missing DAT / failed render.

    nana_zip_path: the paired Nana skin's zip for an Ice Climbers Popo costume
    (from paired_nana_zip). Its DAT is fed to generate_csp as the explicit pair
    so the portrait is the Popo+Nana composite -- the Popo zip alone holds no
    Nana DAT, and without the pair the render silently falls back to solo Popo."""
    with tempfile.TemporaryDirectory(dir=work_dir) as temp_dir:
        tdir = Path(temp_dir)
        with zipfile.ZipFile(zip_path, 'r') as zf:
            safe_extract_zip(zf, tdir)
        dat_file = find_extracted_costume_archive(tdir)
        if not dat_file:
            raise ValueError('No costume archive found in costume ZIP')

        paired_dat = None
        if nana_zip_path:
            nana_dir = tdir / '_nana_pair'
            with zipfile.ZipFile(nana_zip_path, 'r') as zf:
                safe_extract_zip(zf, nana_dir)
            paired_dat = find_extracted_costume_archive(nana_dir)
            if not paired_dat:
                logger.warning(f"No costume archive in paired Nana zip {nana_zip_path}")

        scale = 4  # render HD; the in-game SD is derived from it on apply

        # One renderer for every portrait in the app (shared/rendering/portrait.py): it
        # resolves the pose (including scene-mode characters and custom
        # characters, which the copy that used to live here got wrong), keeps
        # the Ice Climbers pair, and carries G&W colours through.
        rendered = render_portrait(
            dat_file, character, pose_name=pose_name, scale=scale,
            paired_dat=paired_dat, gw_colors=gw_colors_from_zip(zip_path))
        csp_output = rendered.path

        if not csp_output or not Path(csp_output).exists():
            raise RuntimeError('Failed to render a portrait for this costume')

        png_bytes = Path(csp_output).read_bytes()
        reject_blank_render(png_bytes)
        # Report the pose that was actually rendered. A pose can be lost (file
        # gone, render failed, or an Ice Climbers pair taking precedence) and
        # the caller writes this label onto the costume -- labelling a default
        # portrait with a pose name overwrites the real posed alternate.
        return png_bytes, (pose_name if rendered.pose_applied else 'Default')


def reject_blank_render(png_bytes):
    """Raise when a portrait is HSDRawViewer's silent blank output (a tiny or
    fully-transparent PNG produced under GPU pressure, reported as success)
    rather than a real render. Keeps blanks out of the retake review grid.
    The rule is shared with the render pool — shared/rendering/render_checks.py."""
    from shared.rendering.render_checks import blank_reason
    reason = blank_reason(png_bytes)
    if reason:
        raise RuntimeError(reason)
