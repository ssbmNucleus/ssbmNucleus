"""
Texture extras - for hue-shifted textures (Up-B fire, Falcon Punch fire).

Texture export/import via HSDRaw CLI and hue shifting/detection. No routes:
the /api/mex/storage/textures/* endpoints live in texture_routes.py.

Color-picker migration (task #12, 2026-07-02): these textures ARE
CLI-addressable (JOBJ node paths), unlike charge_ball/EfCoData, so the CLI
export -> shift-hue -> import transport stays. What changed is the
USER-FACING parameter: the editor now shows a ColorPicker (target RGB), not
a raw hue-degrees slider, matching `texture_recolor`'s UX. `shift_texture_hue`
still receives plain DEGREES (`target_hue - vanilla_hue`); only how that
number gets computed changed -- from a typed slider value to
`hex_to_hue(color) - vanilla_hue`.

Vanilla-hue SOURCE -- chosen for back-compat, not live-measured:
`resolve_vanilla_hue` reads `type_config['vanilla_hue']`, the same static
config constant `apply_texture_extra_hue` has always used (NOT a fresh
`detect_texture_hue` measurement of the exported PNG, unlike
`texture_recolor.apply_texture_recolor`'s live-measure). This is a deliberate
deviation from texture_recolor's principle: back-compat here is mandatory
(existing saved `{hue: degrees}` mods must reproduce IDENTICAL output), and
the old degrees-slider path never measured the live texture either -- it was
always "shift the exported vanilla PNG by exactly N degrees" with N typed by
the user. Re-deriving vanilla_hue live at apply time would make the SAME
saved color produce a different shift than before if the live-measured hue
ever drifted from the recorded constant (re-imported textures, PNG rounding),
silently breaking #2's byte-for-byte requirement. Using the fixed config
constant keeps a NEW color whose own hue equals an OLD saved `{"hue": N}`
value resolving to the exact same final shift (target_hue - vanilla_hue),
for every install, forever -- see the regression tests in
`tests/backend/test_texture_color_migration.py`
(`test_color_equal_to_old_hue_reproduces_identical_shift`).
`type_config['vanilla_hue']` was itself originally
recorded from a one-time `detect_texture_hue` reading (see
`get_current_texture_hue`), so this is "live-measure once, store in config"
-- the other of texture_recolor's two documented-acceptable designs.

BACK-COMPAT (mandatory, see `resolve_hue_shift`): existing saved vault mods
store `modifications['fire'] = {"hue": <degrees>}` (or, for punch_texture,
whatever key wires it in) predating the color picker. The old numeric
`hue` value is an ABSOLUTE TARGET HUE in degrees, taken as-is (no vanilla-hue
math at this layer -- that's exactly what the old UI's `HuePicker` sent to
`/storage/textures/install`, and `apply_texture_extra_hue` subtracts
vanilla_hue from it same as always). New saves instead store
`{"color": "RRGGBB"}`, a target color, converted to an equivalent absolute
target hue via `hex_to_hue(color)` before reaching
`apply_texture_extra_hue`. Both shapes are accepted by
`resolve_hue_shift`/`install_texture_extra` forever -- no migration pass
rewrites old saved mods; the editor converts old mods for DISPLAY only.
"""

import logging
import subprocess
import shutil
import uuid
from pathlib import Path

import file_retry
from core.extra_lookup import get_storage_character
from core.config import get_subprocess_args

from . import helpers
from vault.extras.helpers import find_dat_file

logger = logging.getLogger(__name__)


def get_texture_targets(type_config):
    """Every (node_path, tex_index) pair a texture extra patches.

    A model's flat texture list can show the same image at several indices
    because multiple TObjs SHARE one image node (audit 2026-07: Falcon's
    Models_0 lists 10 textures = 3 unique nodes). `texture_targets` lists
    ONE index per unique image node -- importing at that index recolors every
    TObj sharing the node; re-shifting a shared node via a second index would
    round-trip it back toward vanilla. Configs without texture_targets fall
    back to the single texture_path/texture_index pair.
    """
    targets = type_config.get('texture_targets')
    if targets:
        return [(t['path'], t['index']) for t in targets]
    return [(type_config['texture_path'], type_config['texture_index'])]


def shift_texture_hue(input_png, output_png, hue_degrees):
    """Shift hue of texture, preserving alpha and luminance.

    Args:
        input_png: Path to input PNG file
        output_png: Path to save hue-shifted PNG
        hue_degrees: Hue shift amount in degrees (0-360)

    Returns:
        True if successful
    """
    from PIL import Image
    import colorsys

    img = Image.open(input_png).convert('RGBA')
    pixels = img.load()

    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = pixels[x, y]
            # Convert to HLS (hue, lightness, saturation)
            h, l, s = colorsys.rgb_to_hls(r/255, g/255, b/255)
            # Shift hue
            h = (h + hue_degrees/360) % 1.0
            # Convert back to RGB
            r, g, b = colorsys.hls_to_rgb(h, l, s)
            pixels[x, y] = (int(r*255), int(g*255), int(b*255), a)

    img.save(output_png)
    logger.info(f"Hue shifted texture saved to {output_png}")
    return True


def export_texture(dat_path, node_path, tex_index, output_png):
    """Export texture from DAT using HSDRaw CLI.

    Args:
        dat_path: Path to the .dat file
        node_path: Path within DAT to JOBJ containing texture
        tex_index: Index of texture to export
        output_png: Path to save exported PNG

    Returns:
        True if successful, raises exception on failure
    """
    if not helpers.HSDRAW_VIEWER_PATH:
        raise RuntimeError("HSDRawViewer path not configured")

    cmd = [
        str(helpers.HSDRAW_VIEWER_PATH),
        '--texture', 'export',
        str(dat_path),
        node_path,
        str(tex_index),
        str(output_png)
    ]

    logger.info(f"Running texture export: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, **get_subprocess_args())

    if result.returncode != 0:
        logger.error(f"Texture export failed: {result.stderr}")
        raise RuntimeError(f"Texture export failed: {result.stderr}")

    logger.info(f"Texture export output: {result.stdout}")
    return True


def import_texture(dat_path, node_path, tex_index, input_png, output_dat):
    """Import texture into DAT using HSDRaw CLI.

    Args:
        dat_path: Path to the source .dat file
        node_path: Path within DAT to JOBJ containing texture
        tex_index: Index of texture to replace
        input_png: Path to the PNG file to import
        output_dat: Path to save the modified .dat file

    Returns:
        True if successful, raises exception on failure
    """
    if not helpers.HSDRAW_VIEWER_PATH:
        raise RuntimeError("HSDRawViewer path not configured")

    cmd = [
        str(helpers.HSDRAW_VIEWER_PATH),
        '--texture', 'import',
        str(dat_path),
        node_path,
        str(tex_index),
        str(input_png),
        str(output_dat)
    ]

    logger.info(f"Running texture import: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, **get_subprocess_args())

    if result.returncode != 0:
        logger.error(f"Texture import failed: {result.stderr}")
        raise RuntimeError(f"Texture import failed: {result.stderr}")

    logger.info(f"Texture import output: {result.stdout}")
    return True


def resolve_vanilla_hue(character, extra_type, type_config):
    """The vanilla dominant hue to shift FROM. Reads the config's recorded
    `vanilla_hue` constant -- NOT a fresh live measurement -- see the module
    docstring's "Vanilla-hue SOURCE" section for why this deliberately
    differs from texture_recolor's live-measure-every-time principle
    (back-compat: the old degrees-slider path never re-measured either)."""
    return type_config.get('vanilla_hue', 30)


def resolve_hue_shift(character, extra_type, type_config, modifications):
    """BACK-COMPAT entry point: turn a saved mod's texture modifications into
    the `hue` (absolute target-hue degrees) value `apply_texture_extra_hue`
    expects, accepting BOTH shapes forever:

      - OLD: {"hue": <degrees>} -- a raw hue-DEGREES value the old slider UI
        sent directly to /storage/textures/install. Passed through unchanged
        (no vanilla-hue math -- that's exactly what the old code path did).
      - NEW: {"color": "RRGGBB"} -- a target RGB color from the ColorPicker.
        Converted via target_hue = hex_to_hue(color); the eventual shift
        (target_hue - vanilla_hue) is computed downstream in
        apply_texture_extra_hue, so this returns target_hue itself (an
        absolute hue in degrees, same units/shape as the old "hue" value --
        apply_texture_extra_hue has always treated its `hue` parameter as an
        absolute target hue, not a shift amount).

    Returns None if modifications has neither key (caller should skip/no-op).
    """
    if modifications is None:
        return None
    if 'color' in modifications and modifications['color']:
        from .texture_recolor import hex_to_hue
        return hex_to_hue(modifications['color'])
    if 'hue' in modifications and modifications['hue'] is not None:
        return float(modifications['hue'])
    return None


def color_to_hue_shift(character, extra_type, type_config, target_hex):
    """Regression-testable pure step: target color -> equivalent hue-shift
    DEGREES against the resolved vanilla hue. Exists so the self-test can
    assert color==vanilla_hue+180 reproduces the old hue=180 shift without
    needing the CLI (see tests/backend or the mission's ad hoc check)."""
    from .texture_recolor import hex_to_hue
    target_hue = hex_to_hue(target_hex)
    vanilla_hue = resolve_vanilla_hue(character, extra_type, type_config)
    return target_hue - vanilla_hue


def ensure_vanilla_texture(character, extra_type, type_config, target=0):
    """Ensure a vanilla reference texture exists, exporting if necessary.

    Args:
        character: Character name
        extra_type: Extra type ID (e.g., 'upb_texture')
        type_config: Extra type configuration
        target: Index into get_texture_targets() -- each target keeps its OWN
            vanilla reference because the copies are not all the same image
            (e.g. Falcon's Models_0 holds lava tiles, ember tiles and a fire
            wisp). Target 0 keeps the legacy `<extra>_vanilla.png` cache name.

    Returns:
        Path to vanilla texture PNG, or None on failure
    """
    # Get storage character
    storage_char = get_storage_character(character, extra_type)

    # Create textures directory
    textures_dir = helpers.STORAGE_PATH / storage_char / 'textures'
    textures_dir.mkdir(parents=True, exist_ok=True)

    suffix = "" if target == 0 else f"_t{target}"
    vanilla_png = textures_dir / f"{extra_type}_vanilla{suffix}.png"

    # If vanilla already exists, return it
    if vanilla_png.exists():
        logger.info(f"Using existing vanilla texture: {vanilla_png}")
        return vanilla_png

    # Export vanilla texture from MEX project
    try:
        files_dir = helpers.get_project_files_dir()
    except Exception as e:
        logger.error(f"Cannot get project files dir: {e}")
        return None

    target_file = type_config['target_file']
    dat_path = find_dat_file(files_dir, target_file)

    if not dat_path or not dat_path.exists():
        logger.error(f"Could not find {target_file} to export vanilla texture")
        return None

    try:
        node_path, tex_index = get_texture_targets(type_config)[target]
        export_texture(dat_path, node_path, tex_index, vanilla_png)
        logger.info(f"Exported vanilla texture to {vanilla_png}")
        return vanilla_png
    except Exception as e:
        logger.error(f"Failed to export vanilla texture: {e}")
        return None


def _import_over(dat_path, node_path, tex_index, png):
    """Replace one texture of `dat_path` in place; nothing else in the file moves.

    HSDRaw's import re-serializes the whole archive: unreferenced data is
    dropped and blocks move. The colour extras in the same file address their
    bytes by vanilla offset, so after a Falcon Punch fire hue the next colour
    write and the colour restore could no longer find most of them (bug 11-19).
    The import therefore runs on a temporary copy only, and just the texture's
    encoded pixels and palette are copied back over the same bytes
    (texture_layout.transplant_texture). Colour edits, an image shine and its
    revert header all stay byte for byte. A texture that does not fit in place
    (other size, format or palette) raises TextureLayoutError and the file is
    left as it was.
    """
    from .texture_layout import transplant_texture

    dat_path = Path(dat_path)
    original = dat_path.read_bytes()
    token = uuid.uuid4().hex
    source_dat = dat_path.with_name(f'.{dat_path.stem}_{token}_source.dat')
    temp_dat = dat_path.with_name(f'.{dat_path.stem}_{token}_result.dat')
    staged = dat_path.with_name(f'.{dat_path.stem}_{token}_staged.dat')
    try:
        source_dat.write_bytes(original)
        import_texture(source_dat, node_path, tex_index, png, temp_dat)
        patched = transplant_texture(original, temp_dat.read_bytes(), node_path, tex_index)
        if patched != original:
            staged.write_bytes(patched)
            file_retry.replace(staged, dat_path)
    finally:
        for leftover in (source_dat, temp_dat, staged):
            leftover.unlink(missing_ok=True)


def apply_texture_extra_hue(character, extra_type, type_config, hue, dat_path):
    """Hue-shift EVERY target texture of a texture extra in dat_path.

    The shift amount is (hue - vanilla_hue); each target is shifted from its
    own vanilla reference so repeated installs don't compound.
    """
    vanilla_hue = type_config.get('vanilla_hue', 30)
    hue_shift = hue - vanilla_hue
    storage_char = get_storage_character(character, extra_type)
    textures_dir = helpers.STORAGE_PATH / storage_char / 'textures'
    textures_dir.mkdir(parents=True, exist_ok=True)

    for i, (node_path, tex_index) in enumerate(get_texture_targets(type_config)):
        vanilla_png = ensure_vanilla_texture(character, extra_type, type_config,
                                             target=i)
        if not vanilla_png:
            raise RuntimeError(
                f"no vanilla reference texture for {extra_type} target {i}")
        if abs(hue_shift) < 1:
            shifted_png = vanilla_png
        else:
            shifted_png = textures_dir / f"{extra_type}_hue_{int(hue)}_t{i}.png"
            shift_texture_hue(str(vanilla_png), str(shifted_png), hue_shift)
        _import_over(dat_path, node_path, tex_index, shifted_png)
    logger.info(f"[OK] Applied {extra_type} hue {hue} "
                f"({len(get_texture_targets(type_config))} texture targets)")


def restore_texture_extra(character, extra_type, type_config, dat_path):
    """Restore every target texture of a texture extra to vanilla."""
    for i, (node_path, tex_index) in enumerate(get_texture_targets(type_config)):
        vanilla_png = ensure_vanilla_texture(character, extra_type, type_config,
                                             target=i)
        if not vanilla_png:
            raise RuntimeError(
                f"no vanilla reference texture for {extra_type} target {i}")
        _import_over(dat_path, node_path, tex_index, vanilla_png)
    logger.info(f"[OK] Restored vanilla textures for {character}/{extra_type}")


def detect_texture_hue(png_path):
    """Analyze a texture and detect its dominant hue.

    Args:
        png_path: Path to PNG file

    Returns:
        Dominant hue in degrees (0-360), or None if detection fails
    """
    from PIL import Image
    import colorsys

    try:
        img = Image.open(png_path).convert('RGBA')
        pixels = img.load()

        # Collect hues from non-transparent, saturated pixels
        hue_votes = {}

        for y in range(img.height):
            for x in range(img.width):
                r, g, b, a = pixels[x, y]
                if a < 32:  # Skip mostly transparent pixels
                    continue

                h, l, s = colorsys.rgb_to_hls(r/255, g/255, b/255)

                # Only count pixels with decent saturation and not too dark/light
                if s > 0.2 and 0.1 < l < 0.9:
                    # Round hue to nearest 5 degrees for binning
                    hue_deg = int(round(h * 360 / 5) * 5) % 360
                    hue_votes[hue_deg] = hue_votes.get(hue_deg, 0) + 1

        if not hue_votes:
            logger.warning(f"No saturated pixels found in {png_path}")
            return None

        # Return the most common hue
        dominant_hue = max(hue_votes, key=hue_votes.get)
        logger.info(f"Detected dominant hue: {dominant_hue} degrees from {png_path}")
        return dominant_hue

    except Exception as e:
        logger.error(f"Failed to detect hue from {png_path}: {e}")
        return None
