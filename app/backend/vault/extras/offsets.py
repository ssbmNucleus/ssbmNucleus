"""
Where each effect's colors live in a fighter DAT, found by scanning the file
(lasers, side-B, up-B, shine, laser ring), cached by file and mtime.
"""

import os
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# DYNAMIC OFFSET DETECTION
# =============================================================================

# Cache for dynamic offsets: (file_path, mtime) -> offsets dict
_dynamic_offset_cache = {}


def find_laser_offsets(dat_path):
    """Dynamically find laser color matrix offsets in a DAT file.

    Searches for three consecutive 98 00 17 matrices (23 entries each)
    that are exactly 0xA0 (160 bytes) apart. This pattern is consistent
    even when file structure changes due to model imports.

    Args:
        dat_path: Path to the .dat file (PlFc.dat or PlFx.dat)

    Returns:
        Dict with wide/thin/outline offset info, or None if not found
    """
    try:
        with open(dat_path, 'rb') as f:
            data = f.read()
    except Exception as e:
        logger.error(f"Failed to read {dat_path} for laser detection: {e}")
        return None

    # Find all 98 00 17 matrices (23 entries = 0x17)
    candidates = []
    pattern = bytes([0x98, 0x00, 0x17])
    pos = 0
    while True:
        pos = data.find(pattern, pos)
        if pos == -1:
            break
        candidates.append(pos)
        pos += 1

    logger.debug(f"Found {len(candidates)} potential 98 00 17 matrices in {dat_path}")

    # Look for three consecutive matrices exactly 0xA0 apart
    candidate_set = set(candidates)
    for start in candidates:
        second = start + 0xA0
        third = start + 0x140
        if second in candidate_set and third in candidate_set:
            # Verify each matrix has uniform colors (same 2-byte color repeated)
            # Matrix structure: 98 00 17 [VV CC CC] * 23 entries
            # First color at offset 4 (after header + vertex byte)
            valid = True
            for matrix_start in [start, second, third]:
                if matrix_start + 0x60 > len(data):
                    valid = False
                    break
                first_color = data[matrix_start + 4:matrix_start + 6]
                # Check a few more entries to verify uniformity
                for i in range(1, 5):
                    entry_color = data[matrix_start + 4 + (i * 4):matrix_start + 6 + (i * 4)]
                    if entry_color != first_color:
                        valid = False
                        break
                if not valid:
                    break

            if valid:
                logger.info(f"Found laser offsets at 0x{start:X} (wide), 0x{second:X} (thin), 0x{third:X} (outline)")
                result = {
                    'wide': {'start': start, 'end': start + 0x60, 'format': 'RGBY'},
                    'thin': {'start': second, 'end': second + 0x60, 'format': 'RGBY'},
                    'outline': {'start': third, 'end': third + 0x60, 'format': 'RGBY'}
                }
                # The white center line follows the same cluster (audit
                # 2026-07, live-poke verified): an 8-entry `80 00 08` RGB
                # matrix (the line's leading tip) at third+0xA0, then an
                # 18-entry `98 00 12` RGB matrix (the line body) at
                # third+0xC3. Vanilla colors are FFFFFF. Validate headers
                # before exposing -- omit the layers if the layout moved.
                tip_start = third + 0xA0
                center_start = third + 0xC3
                if data[tip_start:tip_start + 3] == bytes([0x80, 0x00, 0x08]):
                    result['tip'] = {'start': tip_start,
                                     'end': tip_start + 0x23, 'format': 'RGB'}
                else:
                    logger.warning("Laser center-line tip header not at "
                                   f"0x{tip_start:X}; omitting 'tip' layer")
                if data[center_start:center_start + 3] == bytes([0x98, 0x00, 0x12]):
                    result['center'] = {'start': center_start,
                                        'end': center_start + 0x4B, 'format': 'RGB'}
                else:
                    logger.warning("Laser center-line header not at "
                                   f"0x{center_start:X}; omitting 'center' layer")
                return result

    logger.warning(f"Could not find laser pattern in {dat_path}")
    return None


def find_sideb_offsets(dat_path):
    """Dynamically find side-B RGBA color offsets in a DAT file.

    Searches for the unique marker pattern 3E 99 99 9A 42 48 00 00 that follows
    the side-B color data. The three 4-byte RGBA values are located
    12 bytes before this marker.

    Args:
        dat_path: Path to the .dat file (PlFc.dat or PlFx.dat)

    Returns:
        Dict with primary/secondary/tertiary offset info, or None if not found
    """
    try:
        with open(dat_path, 'rb') as f:
            data = f.read()
    except Exception as e:
        logger.error(f"Failed to read {dat_path} for side-B detection: {e}")
        return None

    # Search for the unique marker that follows side-B colors
    # This pattern (3E99999A42480000) appears right after the 12 color bytes
    marker = bytes.fromhex('3E99999A42480000')
    pos = data.find(marker)

    if pos > 12:
        # Colors are 12 bytes before the marker
        color_start = pos - 12
        # Verify it looks like RGBA colors (check alpha bytes are reasonable)
        if (data[color_start + 3] == 0xFF and
            data[color_start + 7] == 0xFF and
            data[color_start + 11] == 0xFF):
            logger.info(f"Found side-B offsets at 0x{color_start:X} (marker at 0x{pos:X})")
            return {
                'primary': {'start': color_start, 'size': 4, 'format': 'RGBA'},
                'secondary': {'start': color_start + 4, 'size': 4, 'format': 'RGBA'},
                'tertiary': {'start': color_start + 8, 'size': 4, 'format': 'RGBA'}
            }

    logger.warning(f"Could not find side-B pattern in {dat_path}")
    return None


def find_upb_offsets(dat_path):
    """Dynamically find Up-B (Firefox/Firebird) color offsets in EfFxData.dat.

    Searches for unique patterns to locate:
    - tip: 98 00 20 (32 entries, unique count)
    - body: cluster of 98 00 0A (10-entry matrices)
    - rings: 07 07 07 04 markers (after tip region)
    - trail: kept hardcoded (CF format, complex, early in file)

    Args:
        dat_path: Path to EfFxData.dat

    Returns:
        Dict with detected offsets, or None if not found
    """
    try:
        with open(dat_path, 'rb') as f:
            data = f.read()
    except Exception as e:
        logger.error(f"Failed to read {dat_path} for Up-B detection: {e}")
        return None

    result = {}

    # Find tip: unique 98 00 20 pattern (32 entries)
    tip_pattern = bytes([0x98, 0x00, 0x20])
    tip_pos = data.find(tip_pattern)
    if tip_pos != -1:
        # Tip matrix is 0x80 bytes (128 bytes): 3 header + 32 * 4 entries - 3 = 128
        result['tip'] = {
            'start': tip_pos,
            'end': tip_pos + 0x80,
            'format': 'RGBY',
            'vanilla': 'FE60'
        }
        logger.debug(f"Found Up-B tip at 0x{tip_pos:X}")
    else:
        logger.warning("Could not find Up-B tip pattern (98 00 20)")
        return None

    # Find body: cluster of 98 00 0A matrices (10 entries each)
    # Look for multiple 98 00 0A patterns close together, before the tip
    body_pattern = bytes([0x98, 0x00, 0x0A])
    body_candidates = []
    pos = 0
    while pos < tip_pos:  # Body is before tip
        pos = data.find(body_pattern, pos)
        if pos == -1 or pos >= tip_pos:
            break
        body_candidates.append(pos)
        pos += 1

    # Find a cluster of 98 00 0A matrices (RGB format, close together)
    # Body region spans multiple matrices with consistent spacing
    if len(body_candidates) >= 3:
        # Calculate actual spacing between matrices
        matrix_spacing = body_candidates[1] - body_candidates[0]

        # Find the cluster where matrices have consistent spacing
        cluster_start = None
        cluster_end = None
        for i in range(len(body_candidates) - 2):
            # Check if matrices have consistent spacing (within tolerance)
            spacing1 = body_candidates[i + 1] - body_candidates[i]
            spacing2 = body_candidates[i + 2] - body_candidates[i + 1]
            if abs(spacing1 - spacing2) < 5:  # Consistent spacing
                cluster_start = body_candidates[i]
                # Find the end of the cluster
                last_in_cluster = i
                for j in range(i + 1, len(body_candidates)):
                    if j + 1 < len(body_candidates):
                        next_spacing = body_candidates[j + 1] - body_candidates[j]
                        if abs(next_spacing - matrix_spacing) > 5:
                            break
                    last_in_cluster = j

                # End is last matrix + 0x28 (40 bytes = 10 RGB entries)
                # This matches the hardcoded value which excludes trailing padding
                cluster_end = body_candidates[last_in_cluster] + 0x28
                break

        if cluster_start is not None:
            result['body'] = {
                'start': cluster_start,
                'end': cluster_end,
                'format': 'RGB',
                'vanilla': 'FFFFFF'
            }
            logger.debug(f"Found Up-B body cluster at 0x{cluster_start:X}-0x{cluster_end:X}")

    # Find rings: 07 07 07 04 markers (after tip region)
    rings_pattern = bytes([0x07, 0x07, 0x07, 0x04])
    rings_offsets = []
    pos = tip_pos  # Rings are after tip
    while True:
        pos = data.find(rings_pattern, pos)
        if pos == -1:
            break
        rings_offsets.append(pos)
        pos += 1

    if len(rings_offsets) >= 2:
        # Use first two 07 07 07 04 markers after tip
        result['rings'] = {
            'format': '070707',
            'offsets': rings_offsets[:2]
        }
        logger.debug(f"Found Up-B rings at {[hex(o) for o in rings_offsets[:2]]}")

    # Trail: keep hardcoded (CF format early in file, complex structure)
    # These offsets are stable because they're at the beginning of the file
    result['trail'] = {
        'format': 'CF',
        'offsets': [0x2EE, 0x2F4, 0x324, 0x32B, 0x52E, 0x534]
    }

    if 'tip' in result:
        logger.info(f"Found Up-B offsets: tip=0x{result['tip']['start']:X}")
        return result

    return None


def find_shine_offsets(dat_path):
    """Dynamically find Shine (Reflector) color offsets in EfFxData.dat.

    Searches for unique patterns to locate:
    - hex: 98 00 2B (43 entries, unique count)
    - inner: 98 00 1B (27 entries, unique count)
    - outer: 3 consecutive 98 00 0F (15-entry matrices)
    - bubble: 12 bytes before 3E99999A42480000 marker

    Args:
        dat_path: Path to EfFxData.dat

    Returns:
        Dict with detected offsets, or None if not found
    """
    try:
        with open(dat_path, 'rb') as f:
            data = f.read()
    except Exception as e:
        logger.error(f"Failed to read {dat_path} for Shine detection: {e}")
        return None

    result = {}

    # Find hex: unique 98 00 2B pattern (43 entries)
    hex_pattern = bytes([0x98, 0x00, 0x2B])
    hex_pos = data.find(hex_pattern)
    if hex_pos != -1:
        # 43 entries * 4 bytes each + 3 header = 175 bytes, round to 0xB0
        result['hex'] = {
            'start': hex_pos,
            'end': hex_pos + 0xB0,
            'format': 'RGBY'
        }
        logger.debug(f"Found Shine hex at 0x{hex_pos:X}")
    else:
        logger.warning("Could not find Shine hex pattern (98 00 2B)")
        return None

    # Find inner: 98 00 1B pattern (27 entries) - search AFTER hex
    # There are multiple 98 00 1B in the file, inner is the one after hex
    inner_pattern = bytes([0x98, 0x00, 0x1B])
    inner_pos = data.find(inner_pattern, hex_pos + 0xB0)  # Start after hex region
    if inner_pos != -1:
        # 27 entries * 4 bytes + 3 header = 111 bytes, round to 0x70
        result['inner'] = {
            'start': inner_pos,
            'end': inner_pos + 0x70,
            'format': 'RGBY'
        }
        logger.debug(f"Found Shine inner at 0x{inner_pos:X}")

    # Find outer: 3 consecutive 98 00 0F matrices (15 entries each)
    outer_pattern = bytes([0x98, 0x00, 0x0F])
    outer_candidates = []
    pos = hex_pos if hex_pos != -1 else 0  # Search after hex
    while True:
        pos = data.find(outer_pattern, pos)
        if pos == -1:
            break
        outer_candidates.append(pos)
        pos += 1

    # Look for 3 consecutive 98 00 0F matrices close together
    for i in range(len(outer_candidates) - 2):
        first = outer_candidates[i]
        second = outer_candidates[i + 1]
        third = outer_candidates[i + 2]
        # Each 15-entry matrix is about 0x3F bytes (63), with overlapping ends
        # Hardcoded uses 0x40, 0x41, 0x42 for the three ranges respectively
        if second - first < 0x50 and third - second < 0x50:
            result['outer'] = {
                'format': '98_multi',
                'ranges': [
                    {'start': first, 'end': first + 0x40},
                    {'start': second, 'end': second + 0x41},
                    {'start': third, 'end': third + 0x42}
                ]
            }
            logger.debug(f"Found Shine outer at 0x{first:X}, 0x{second:X}, 0x{third:X}")
            break

    # Find bubble: 12 bytes before 3E99999A42480000 marker (same as side-B)
    bubble_marker = bytes.fromhex('3E99999A42480000')
    bubble_pos = data.find(bubble_marker)
    if bubble_pos > 12:
        # The bubble colors are 12 bytes before the marker
        bubble_start = bubble_pos - 12
        result['bubble'] = {
            'start': bubble_start,
            'format': '42_48',
            'size': 12
        }
        logger.debug(f"Found Shine bubble at 0x{bubble_start:X}")

    if 'hex' in result:
        logger.info(f"Found Shine offsets: hex=0x{result['hex']['start']:X}")
        return result

    return None


def find_laser_ring_offsets(dat_path):
    """Dynamically find laser ring color offsets in EfFxData.dat.

    Searches for unique pattern 85 80 08 0f 07 07 07 07 which precedes the colors.
    Then calculates hue byte offsets relative to the color position.

    Structure at pattern:
    - 85 80 08 0f: prefix (4 bytes)
    - 07 07 07 07: marker (4 bytes)
    - RR GG BB 00: color1 (4 bytes) at prefix+8
    - RR GG BB 00: color2 (4 bytes) at prefix+12

    Hue bytes are at fixed offsets from color1:
    - hue1: color1 + 0x678
    - hue2: color1 + 0x68C
    - hue3: color1 + 0x6A0
    - hue4: color1 + 0x6B4
    - hue5: color1 + 0x6C8
    - hue6: color1 + 0x6DC

    Args:
        dat_path: Path to EfFxData.dat

    Returns:
        Dict with detected offsets, or None if not found
    """
    try:
        with open(dat_path, 'rb') as f:
            data = f.read()
    except Exception as e:
        logger.error(f"Failed to read {dat_path} for laser ring detection: {e}")
        return None

    # Search for unique prefix pattern 85 80 08 0f 07 07 07 07
    prefix = bytes([0x85, 0x80, 0x08, 0x0f, 0x07, 0x07, 0x07, 0x07])
    prefix_pos = data.find(prefix)

    if prefix_pos == -1:
        logger.warning("Could not find laser ring pattern (85 80 08 0f 07 07 07 07)")
        return None

    # Color positions relative to prefix
    color1_pos = prefix_pos + 8   # After 85 80 08 0f 07 07 07 07
    color2_pos = prefix_pos + 12  # After color1 + separator

    logger.info(f"Found laser ring: color1=0x{color1_pos:X}, color2=0x{color2_pos:X}")

    # Hue byte offsets relative to color1
    hue_offsets = [0x678, 0x68C, 0x6A0, 0x6B4, 0x6C8, 0x6DC]

    result = {
        'color1': {'start': color1_pos, 'size': 3, 'format': 'RGB'},
        'color2': {'start': color2_pos, 'size': 3, 'format': 'RGB'},
    }

    for i, offset in enumerate(hue_offsets, 1):
        result[f'hue{i}'] = {'start': color1_pos + offset, 'size': 1, 'format': 'BYTE'}

    logger.info(f"Laser ring hue1 at 0x{color1_pos + 0x678:X}")

    return result


def get_dynamic_offsets(dat_path, extra_type_id, fallback_offsets):
    """Get offsets for an extra type, using dynamic detection if applicable.

    For laser, sideb, upb, shine, and laser_ring types, attempts dynamic detection first,
    falling back to hardcoded offsets if detection fails.

    Results are cached by (file_path, mtime) to avoid re-scanning.

    Args:
        dat_path: Path to the .dat file
        extra_type_id: The extra type ID (e.g., 'laser', 'sideb', 'upb', 'shine', 'laser_ring')
        fallback_offsets: Hardcoded offsets to use if detection fails

    Returns:
        Dict of offset info for each layer
    """
    # Check if this type needs dynamic detection
    if extra_type_id not in ('laser', 'sideb', 'upb', 'shine', 'laser_ring'):
        return fallback_offsets

    # Check cache
    try:
        mtime = os.path.getmtime(dat_path)
        cache_key = (str(dat_path), mtime, extra_type_id)
        if cache_key in _dynamic_offset_cache:
            logger.debug(f"Using cached offsets for {extra_type_id} in {dat_path}")
            return _dynamic_offset_cache[cache_key]
    except Exception:
        pass

    # Attempt dynamic detection
    detected = None
    if extra_type_id == 'laser':
        detected = find_laser_offsets(dat_path)
    elif extra_type_id == 'sideb':
        detected = find_sideb_offsets(dat_path)
    elif extra_type_id == 'upb':
        detected = find_upb_offsets(dat_path)
    elif extra_type_id == 'shine':
        detected = find_shine_offsets(dat_path)
    elif extra_type_id == 'laser_ring':
        detected = find_laser_ring_offsets(dat_path)

    if detected:
        logger.info(f"Using dynamically detected offsets for {extra_type_id}")
        # MERGE detected over the config offsets instead of replacing them:
        # layers that only exist in the config (e.g. upb small_trail/dots/
        # charge_lines/flare, laser center/tip) must survive detection, or
        # saved mods silently skip them (audit 2026-07: the driver patches
        # from config and verified those layers, but this path dropped them).
        merged = {**(fallback_offsets or {}), **detected}
        try:
            _dynamic_offset_cache[cache_key] = merged
        except Exception:
            pass
        return merged
    else:
        logger.info(f"Dynamic detection failed for {extra_type_id}, using hardcoded offsets")
        return fallback_offsets
