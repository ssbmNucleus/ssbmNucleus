"""
Reading the colors an effect currently has in a DAT: shine gradients and
sparkle, every color layer at its offsets, and the vanilla/custom/unknown
verdict over them.
"""

import logging
from pathlib import Path
from vault.extras import relocate as _relocate
from vault.extras.color_patch import _resolve_offset, locate_shine_color_slots

logger = logging.getLogger(__name__)


def read_shine_gradient_colors(dat_path, hex_offset):
    """Read the two-color gradient from shine hex region.

    The shine hex region contains two alternating colors:
    - Primary (vanilla 621F): bright edge/outline vertices
    - Secondary (vanilla AB9F): fill/interior vertices

    We read all colors in the matrix and identify the two distinct values.

    Args:
        dat_path: Path to EfFxData.dat
        hex_offset: Dict with start/end for the hex region

    Returns:
        Dict with 'primary' and 'secondary' color hex strings
    """
    start = hex_offset.get('start', 0)
    end = hex_offset.get('end', start)

    with open(dat_path, 'rb') as f:
        f.seek(start)
        data = f.read(end - start)

    # Find all distinct 2-byte RGBY colors in the matrix
    # Header is 3 bytes (98 00 NN), entries are 4 bytes each (vertex + 2-byte color + coord)
    colors_found = {}
    pos = 4  # First color position (after header + vertex byte)
    while pos + 1 < len(data):
        color = data[pos:pos + 2].hex().upper()
        colors_found[color] = colors_found.get(color, 0) + 1
        pos += 4

    # Sort by frequency - secondary (fill) usually has more vertices
    sorted_colors = sorted(colors_found.items(), key=lambda x: x[1], reverse=True)

    if len(sorted_colors) >= 2:
        # Most common = secondary (fill), second = primary (edge)
        secondary = sorted_colors[0][0]
        primary = sorted_colors[1][0]
    elif len(sorted_colors) == 1:
        # Only one color found (already uniform)
        primary = secondary = sorted_colors[0][0]
    else:
        # Fallback to vanilla
        primary = '621F'
        secondary = 'AB9F'

    return {
        'primary': primary,
        'secondary': secondary
    }


def read_shine_sparkle_color(dat_path, sparkles_offset, default='FFFFFF'):
    """Read the current sparkle color from the shine extra's CF-multi records.

    Marker-verifies each record's marker byte is 'CF' (template lesson 1)
    before trusting its offsets; a record whose marker byte doesn't match is
    skipped (logged) rather than blindly written to. Reads the FIRST valid
    record's color byte as the representative "current" color (both records
    are written identically by apply/install, so they should already agree).

    Args:
        dat_path: Path to EfFxData.dat
        sparkles_offset: Dict with format='CF-multi' and a 'records' list of
            {marker, color, secondary} offset dicts
        default: Returned when no marker-verified record is found. Callers
            that must distinguish "read failed" from "actually white" pass
            None (e.g. derive_modifications_from_dat).

    Returns:
        6-char uppercase hex RGB string, or `default` if no valid record is
        found
    """
    records = sparkles_offset.get('records', [])
    with open(dat_path, 'rb') as f:
        for rec in records:
            marker_off = rec.get('marker')
            color_off = rec.get('color')
            if marker_off is None or color_off is None:
                continue
            f.seek(marker_off)
            marker_byte = f.read(1)
            if marker_byte != b'\xCF':
                logger.warning(
                    f"[Shine Sparkles] Marker mismatch at 0x{marker_off:X} "
                    f"(got {marker_byte.hex().upper()}, expected CF) -- skipping record"
                )
                continue
            f.seek(color_off)
            return f.read(3).hex().upper()
    return default


def read_current_colors(dat_path, offsets):
    """Read current colors from a .dat file.

    Args:
        dat_path: Path to the .dat file
        offsets: Dict of layer_id -> {start, end/size, format, ...} offset info

    Returns:
        Dict of layer_id -> color hex string

    Supports multiple formats:
    - Matrix format (has 'end'): Reads from 98 00 ## ## format (offset +4 for header)
    - Direct format (has 'size'): Reads bytes directly at offset (for 42_48 RGBA)
    - CF format (format='CF'): Reads 3-byte RGB at offset+2
    - 070707 format (format='070707'): Reads 3-byte RGB at offset+4
    - Multi format (has 'offsets' list): Reads from first offset in the list
    - 98_multi format (has 'ranges' list): Reads from first range's first color
    - 42_48 format: Reads 12 bytes (3x RGBA) directly
    """
    colors = {}
    with open(dat_path, 'rb') as f:
        for layer_id, offset_info in offsets.items():
            fmt = offset_info.get('format', 'RGBY')

            # Handle multi-offset format (CF or 070707 with list of offsets)
            if 'offsets' in offset_info:
                first_offset = offset_info['offsets'][0]
                if fmt == 'CF':
                    # CF format: color at offset+2
                    f.seek(first_offset + 2)
                    color_bytes = f.read(3)
                elif fmt == '070707':
                    # 070707 format: color at offset+4 (after 07 07 07 04 marker)
                    f.seek(first_offset + 4)
                    color_bytes = f.read(3)
                elif fmt == 'RGB':
                    # direct RGB slots: 3 bytes exactly at each offset (used when
                    # one logical layer spans several records but each offset
                    # already points at the color bytes, e.g. Mewtwo bolts)
                    f.seek(first_offset)
                    color_bytes = f.read(3)
                else:
                    continue
                colors[layer_id] = color_bytes.hex().upper()
                continue

            # Handle 98_multi format (multiple 98 matrix ranges)
            if 'ranges' in offset_info:
                first_range = offset_info['ranges'][0]
                start = first_range['start']
                # Read first color in the matrix (at position 4 from start)
                f.seek(start + 4)
                color_bytes = f.read(2)  # RGBY format
                colors[layer_id] = color_bytes.hex().upper()
                continue

            start = offset_info.get('start', 0)

            if fmt == '42_48':
                # 42_48 format: 3x RGBA colors (12 bytes)
                size = offset_info.get('size', 12)
                f.seek(start)
                color_bytes = f.read(size)
                colors[layer_id] = color_bytes.hex().upper()
            elif 'size' in offset_info:
                # Direct read mode - for RGBA format
                size = offset_info['size']
                f.seek(start)
                color_bytes = f.read(size)
                colors[layer_id] = color_bytes.hex().upper()
            elif fmt == 'CF':
                # CF format: color at offset+2
                f.seek(start + 2)
                color_bytes = f.read(3)
                colors[layer_id] = color_bytes.hex().upper()
            elif fmt == '070707':
                # 070707 format: color at offset+4 (after 07 07 07 04 marker)
                f.seek(start + 4)
                color_bytes = f.read(3)
                colors[layer_id] = color_bytes.hex().upper()
            else:
                # Matrix read mode - for 98 00 ## ## format
                color_format = fmt
                color_len = 3 if color_format == 'RGB' else 2
                # Read first color in the matrix (at position 4 from start)
                # Header is 3 bytes (98 00 NN), then 1 byte vertex, then color bytes
                f.seek(start + 4)
                color_bytes = f.read(color_len)
                colors[layer_id] = color_bytes.hex().upper()
    return colors


def current_verdict(colors, vanilla, offsets, unresolved_ids=(), reference=None):
    """'vanilla' | 'custom' | 'unknown' for a set of current colors.

    Only vanilla entries that are real layers (keys of `offsets`) count:
    `color1`/`color2` summary swatches of fan-out extras are representative
    colors with no bytes of their own, and comparing them to nothing made
    such extras read Custom on an untouched project. Each counted layer is
    compared to `reference[layer]` (the vanilla file's exact bytes at the
    same slot) when known, else to the config's vanilla value. A layer that
    differs is proof of Custom even if others could not be read; otherwise
    any unread layer (or nothing to compare at all) means Unknown -- never a
    guess.
    """
    unresolved_ids = set(unresolved_ids)
    reference = reference or {}
    compared = [layer for layer in vanilla if layer in offsets]
    if any(layer not in unresolved_ids
           and colors.get(layer, '').upper()
           != str(reference.get(layer) or vanilla[layer]).upper()
           for layer in compared):
        return 'custom'
    if not compared or any(layer in unresolved_ids for layer in compared):
        return 'unknown'
    return 'vanilla'


def read_shine_colors_resolved(dat_path, type_config, vanilla_path):
    """Current shine primary/secondary by vanilla vertex identity -- the same
    slot location patch_shine_color_slots writes through. Each channel's
    color is its most common value across its slots. Raises ValueError when
    the display list can't be identified exactly once."""
    vanilla_data = Path(vanilla_path).read_bytes()
    target = Path(dat_path).read_bytes()
    found = {}
    for start, channel in locate_shine_color_slots(
            vanilla_data, target, type_config, {'primary', 'secondary'}):
        value = target[start:start + 2].hex().upper()
        counts = found.setdefault(channel, {})
        counts[value] = counts.get(value, 0) + 1
    return {channel: max(counts.items(), key=lambda item: item[1])[0]
            for channel, counts in found.items()}


def read_shine_sparkle_resolved(dat_path, sparkles_offset, safety):
    """Current sparkle color where patch_shine_sparkle_color(safety=) would
    write it: the first record whose CF marker is in place, else the first
    record found again by ptcl operand identity. None when neither works
    (instead of read_shine_sparkle_color's white default)."""
    for i, rec in enumerate(sparkles_offset.get('records', [])):
        marker_off = rec.get('marker')
        color_off = rec.get('color')
        if marker_off is None or color_off is None:
            continue
        if _relocate.read_bytes(dat_path, marker_off, 1) == b'\xCF':
            data = _relocate.read_bytes(dat_path, color_off, 3)
            if len(data) == 3:
                return data.hex().upper()
            continue
        resolved = _resolve_offset(safety, f"sparkles_rec{i}_primary", color_off,
                                   None, block_kind='ptcl', force_relocate=True)
        if resolved is not None and _relocate.read_bytes(dat_path, resolved - 2, 1) == b'\xCF':
            data = _relocate.read_bytes(dat_path, resolved, 3)
            if len(data) == 3:
                return data.hex().upper()
    return None
