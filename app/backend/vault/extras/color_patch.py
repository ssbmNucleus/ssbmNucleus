"""
Writing effect colors into a DAT: color matrices, CF/070707 color runs, shine
color slots and sparkle, model TEV colors, the generic hex patcher every color
extra goes through, and the offset guard and mask spans that keep a write on
the bytes it owns.
"""

import logging
import uuid
import struct
import file_retry
from pathlib import Path
from vault.extras import relocate as _relocate

logger = logging.getLogger(__name__)


def compute_mask_spans(offsets):
    """Every (start, len) byte span the given offsets dict can write colors
    into -- ALL layers, not just the ones in the current modifications, since
    a PREVIOUS install may have recolored any of them. The context guard
    ignores these spans when comparing the target's neighborhood to vanilla,
    so a recolored sibling layer (e.g. the CF secondary at primary+7) doesn't
    break the layout-identity proof for the layer being written.
    """
    spans = []
    for offset_info in (offsets or {}).values():
        fmt = offset_info.get('format', 'RGBY')
        if 'records' in offset_info:  # CF-multi (shine sparkles)
            for rec in offset_info['records']:
                for key in ('color', 'secondary'):
                    if rec.get(key) is not None:
                        spans.append((rec[key], 3))
            continue
        if 'offsets' in offset_info:
            for off in offset_info['offsets']:
                if fmt == 'CF':
                    spans.append((off + 2, 3))
                elif fmt == '070707':
                    spans.append((off + 4, 3))
                    spans.append((off + 8, 3))
                else:  # direct RGB slots
                    spans.append((off, 3))
            continue
        if 'ranges' in offset_info:
            for r in offset_info['ranges']:
                spans.append((r['start'], r['end'] - r['start']))
            continue
        start = offset_info.get('start')
        if start is None:
            continue
        if 'size' in offset_info:
            spans.append((start, offset_info['size']))
        elif fmt == 'CF':
            spans.append((start + 2, 3))
        elif fmt == '070707':
            spans.append((start + 4, 3))
            spans.append((start + 8, 3))
        elif 'end' in offset_info:
            spans.append((start, offset_info['end'] - start))
    return spans


def _resolve_offset(safety, layer_id, offset, expected_bytes, also_valid=None,
                    block_kind='ptcl', marker_len=1, force_relocate=False,
                    write_len=None):
    """Guard+relocate a single write point. Returns the offset to actually
    write at, or None if the write should be skipped (already logged and
    recorded in safety['skipped']).

    If `safety` is None, this is a no-op passthrough (returns `offset`
    unchanged) so callers that don't opt in are unaffected.
    """
    if safety is None:
        return offset
    result = _relocate.resolve_write_offset(
        safety.get('vanilla_path'), safety['dat_path'], offset, expected_bytes,
        extra_id=safety.get('extra_id', '?'), layer_id=layer_id,
        also_valid=also_valid, block_kind=block_kind, marker_len=marker_len,
        force_relocate=force_relocate, write_len=write_len,
        mask_spans=safety.get('mask_spans'))
    if result.get('skip'):
        safety['skipped'].append(result)
        return None
    return result['offset']


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def ensure_laser_ring_anim_disabled(extra_type_id, modifications):
    """For laser_ring mods, make sure the six FObj color-animation tracks get
    disabled whenever a custom color is applied.

    The 'hue1'..'hue6' layers are the trackType bytes of the matanim tracks
    (KONST_R/G/B + TEV0_R/G/B) that drive the flash colors to hardcoded
    vanilla values every frame -- with them left intact, custom color1/color2
    are invisible (verified in-game 2026-07, docs/dev/EXTRAS_AUDIT.md). The editor
    writes 00 for all six on save; this injects them for any mod that carries
    color layers but not the track bytes, so such mods behave identically.

    Returns the (possibly augmented) modifications dict.
    """
    if extra_type_id != 'laser_ring' or not isinstance(modifications, dict):
        return modifications
    if not any(layer in modifications for layer in ('color1', 'color2')):
        return modifications
    hue_layers = [f'hue{i}' for i in range(1, 7)]
    if any(layer in modifications for layer in hue_layers):
        return modifications
    modifications = dict(modifications)
    for layer in hue_layers:
        modifications[layer] = {'color': '00'}
    logger.info("[laser_ring] injected trackType=00 for hue1-6 "
                "(flash animation must be disabled for custom colors)")
    return modifications


def patch_matrix_colors(data, new_color=None, color_format="RGBY", vanilla_color=None, color_map=None):
    """Replace colors in 98 matrix format data.

    The 98 matrix format has:
    - Header: 98 00 NN (3 bytes) where NN is index count
    - Then repeating entries, each 4 bytes:
      - 1 byte: vertex index
      - 2 or 3 bytes: color (RGBY or RGB)
      - 1 or 0 bytes: coordinate (if RGBY) or none (if RGB)

    RGBY format (2-byte colors, 4-byte entries):
    98 00 17 22 FC 00 03 23 FC 00 05 21 FC 00 ...
              ^^ ^^^^    ^^ ^^^^    ^^^^
              |  color   |  color   color

    RGB format (3-byte colors, 4-byte entries):
    98 00 12 05 FF FF FF 04 FF FF FF 03 FF FF FF ...
              ^^ ^^^^^^    ^^^^^^    ^^^^^^
              |  color     color     color

    Note: Some matrices have alternating color/position entries. When vanilla_color
    is provided, only entries matching that color are patched (safe mode).

    Args:
        data: Bytes data from the offset range
        new_color: 2-byte RGBY or 3-byte RGB color value (used if color_map not provided)
        color_format: "RGBY" for 2-byte colors, "RGB" for 3-byte colors
        vanilla_color: If provided, only patch entries matching this color (bytes)
        color_map: Dict mapping vanilla color hex strings to new color hex strings.
                   Example: {"621F": "0FF0", "AB9F": "0A45"}
                   If provided, replaces only colors matching map keys.

    Returns:
        Patched bytes data
    """
    result = bytearray(data)
    color_len = 3 if color_format == "RGB" else 2

    # Header is 3 bytes (98 00 NN), first entry starts at position 3
    # Each entry: 1 byte vertex + color bytes + remaining bytes = 4 bytes total
    # First color at position 4 (3 header + 1 vertex)
    pos = 4  # First color position
    patched_count = 0

    # If color_map provided, use targeted replacement
    if color_map:
        # Pre-convert map keys/values to bytes for efficiency
        byte_map = {}
        for vanilla_hex, new_hex in color_map.items():
            try:
                vanilla_bytes = bytes.fromhex(vanilla_hex)
                new_bytes = bytes.fromhex(new_hex)
                if len(vanilla_bytes) == color_len and len(new_bytes) == color_len:
                    byte_map[vanilla_bytes] = new_bytes
            except ValueError:
                continue

        while pos + color_len - 1 < len(result):
            current_color = bytes(result[pos:pos + color_len])
            if current_color in byte_map:
                new_bytes = byte_map[current_color]
                for i in range(color_len):
                    result[pos + i] = new_bytes[i]
                patched_count += 1
            pos += 4  # Move to next color (4 bytes per entry)
    else:
        # Original behavior: replace all/matching colors with single new_color
        while pos + color_len - 1 < len(result):
            current_color = bytes(result[pos:pos + color_len])
            # If vanilla_color specified, only patch matching entries (safe mode)
            # This prevents corrupting position data in mixed-format matrices
            should_patch = vanilla_color is None or current_color == vanilla_color
            if should_patch:
                for i in range(color_len):
                    result[pos + i] = new_color[i]
                patched_count += 1
            pos += 4  # Move to next color (4 bytes per entry)

    return bytes(result)


def patch_shine_color_slots(dat_path, type_config, modifications):
    """Write shine colors by vanilla vertex identity, independent of current hue.

    Matching current colors loses the distinction between edge/fill or the
    two flash channels after a uniform recolor. Instead the vanilla display
    lists identify each channel's slots. Match their complete non-color
    layout in the current DAT, requiring exactly one match, so HSDRaw
    relocation is supported without trusting the original file offsets.
    """
    from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref

    selected = {key: modifications.get(key, {}).get('color')
                for key in ('primary', 'secondary', 'flash1', 'flash2')}
    selected = {key: bytes.fromhex(value) for key, value in selected.items() if value}
    if any(len(value) != 2 for value in selected.values()):
        raise ValueError('Shine colors must contain exactly two RGBY bytes')
    if not selected:
        return 0
    ref = ensure_vanilla_ref(type_config['target_file'])
    if not ref:
        raise ValueError('A vanilla reference is required to identify shine color slots')
    vanilla_data = Path(ref).read_bytes()
    dat_path = Path(dat_path)
    target = dat_path.read_bytes()
    result = bytearray(target)
    written_spans = 0
    for start, channel in locate_shine_color_slots(vanilla_data, target, type_config, selected):
        result[start:start + 2] = selected[channel]
        written_spans += 1

    temporary = dat_path.with_name(f'.{dat_path.name}.{uuid.uuid4().hex}.shine-colors')
    try:
        temporary.write_bytes(result)
        file_retry.replace(temporary, dat_path)
    finally:
        temporary.unlink(missing_ok=True)
    return written_spans


def locate_shine_color_slots(vanilla_data, target, type_config, wanted):
    """Every (target offset, channel) 2-byte RGBY color slot of the shine
    channel groups that contain a channel in `wanted`, identified by vanilla
    vertex identity (see patch_shine_color_slots). Raises ValueError when a
    wanted group's display list can't be identified exactly once -- the
    caller must then neither write nor trust a reading.
    """
    vanilla = type_config['vanilla']
    groups = [
        ([type_config['offsets']['hex']], ('primary', 'secondary')),
        (type_config.get('flash_offsets', {}).get('ranges', []), ('flash1', 'flash2')),
    ]
    located = []
    for ranges, channels in groups:
        if not any(channel in wanted for channel in channels):
            continue
        if not ranges:
            raise ValueError(f'No display-list ranges configured for {channels[0]}')
        base = min(item['start'] for item in ranges)
        end = base
        slots = {}
        for item in ranges:
            start = item['start']
            if vanilla_data[start:start + 1] != b'\x98':
                raise ValueError(f'Invalid vanilla shine display list at 0x{start:X}')
            count = int.from_bytes(vanilla_data[start + 1:start + 3], 'big')
            primitive_end = start + 3 + count * 4
            if not count or primitive_end > len(vanilla_data):
                raise ValueError('Invalid vanilla shine vertex count')
            end = max(end, primitive_end)
            for vertex in range(count):
                color_at = start + 4 + vertex * 4
                value = vanilla_data[color_at:color_at + 2].hex().upper()
                channel = next((key for key in channels if vanilla[key].upper() == value), None)
                if channel:
                    slots[color_at - base] = channel
        if not all(channel in slots.values() for channel in channels):
            raise ValueError('Vanilla shine display list does not identify both color channels')
        template = vanilla_data[base:end]
        masked = {position + byte for position in slots for byte in (0, 1)}
        fixed = [(index, value) for index, value in enumerate(template) if index not in masked]
        matches = []
        position = target.find(template[:3])
        while position >= 0:
            if position + len(template) <= len(target) and all(
                    target[position + index] == value for index, value in fixed):
                matches.append(position)
            position = target.find(template[:3], position + 1)
        if len(matches) != 1:
            raise ValueError(f'Cannot safely identify shine {channels[0]} display list '
                             f'({len(matches)} layout matches)')
        for relative, channel in slots.items():
            if channel in wanted:
                located.append((matches[0] + relative, channel))
    return located


def patch_shine_sparkle_color(dat_path, sparkles_offset, color_hex, safety=None):
    """Write the sparkle color to BOTH the primary and secondary (colorpos+7)
    positions of every marker-verified CF-multi record.

    Per research/docs-research/effect-maps/fox-falco-shine-sparkles.md: the secondary
    color dominates sustained tint (template lesson 3), so the same user
    color is written to both positions of both records.

    Args:
        dat_path: Path to EfFxData.dat
        sparkles_offset: Dict with format='CF-multi' and a 'records' list of
            {marker, color, secondary} offset dicts
        color_hex: 6-char hex RGB string to write
        safety: optional context from make_write_safety() -- when the CF
            marker isn't where expected (file re-saved/shifted), attempts
            ptcl-bank relocation instead of just skipping the record.
    """
    try:
        color_bytes = bytes.fromhex(color_hex)
    except ValueError:
        logger.warning(f"[Shine Sparkles] Invalid hex color: {color_hex}")
        return
    if len(color_bytes) != 3:
        logger.warning(f"[Shine Sparkles] Invalid color length: {color_hex}, expected 3 bytes (RGB)")
        return

    records = sparkles_offset.get('records', [])
    with file_retry.retry_locked(open, dat_path, 'r+b') as f:
        for i, rec in enumerate(records):
            marker_off = rec.get('marker')
            color_off = rec.get('color')
            secondary_off = rec.get('secondary')
            if marker_off is None or color_off is None:
                continue
            f.seek(marker_off)
            marker_byte = f.read(1)
            if marker_byte != b'\xCF':
                if safety is not None:
                    # The CF marker-byte check above already proved this
                    # offset is stale -- skip the guard and relocate directly
                    # using the PRIMARY color offset's ptcl-bank identity
                    # (marker = color_off - 2 for CF).
                    resolved = _resolve_offset(
                        safety, f"sparkles_rec{i}_primary", color_off,
                        None, block_kind='ptcl', force_relocate=True)
                    if resolved is not None:
                        f.seek(resolved - 2)
                        if f.read(1) == b'\xCF':
                            f.seek(resolved)
                            f.write(color_bytes)
                            if secondary_off is not None:
                                # secondary sits at primary+7 in vanilla; keep
                                # the same delta from the relocated primary.
                                delta = secondary_off - color_off
                                f.seek(resolved + delta)
                                f.write(color_bytes)
                            continue
                    logger.warning(
                        f"[Shine Sparkles] Marker mismatch at 0x{marker_off:X} "
                        f"(got {marker_byte.hex().upper()}, expected CF) and "
                        f"relocation failed -- skipping record"
                    )
                else:
                    logger.warning(
                        f"[Shine Sparkles] Marker mismatch at 0x{marker_off:X} "
                        f"(got {marker_byte.hex().upper()}, expected CF) -- skipping record"
                    )
                continue
            f.seek(color_off)
            f.write(color_bytes)
            if secondary_off is not None:
                f.seek(secondary_off)
                f.write(color_bytes)
    logger.info(f"[OK] Patched shine sparkles at {len(records)} record(s) with color {color_hex}")


def _safety_vanilla_bytes(safety, layer_id, offset_info, expected_len):
    """The vanilla bytes a guarded write (and a resolved read) checks at a
    layer's offset: the extra's vanilla map entry, else the offset's own
    'vanilla', truncated to `expected_len`. None when there is none."""
    if safety is None:
        return None
    hexstr = safety.get('vanilla_map', {}).get(layer_id) or offset_info.get('vanilla')
    if not hexstr:
        return None
    try:
        b = bytes.fromhex(hexstr)
    except ValueError:
        return None
    return b[:expected_len] if len(b) >= expected_len else None


def file_color_mask_spans(target_file, offsets=None):
    """Every color span ANY configured extra can write in `target_file`
    (plus `offsets`, e.g. dynamically detected ones). A recolor of a sibling
    extra only changes bytes inside these, so they are ignored when a
    layer's neighborhood is compared to vanilla to prove the layout."""
    from core.extra_types import EXTRA_TYPES
    from .texture_recolor import recolor_spans
    spans = compute_mask_spans(offsets or {})
    for configs in EXTRA_TYPES.values():
        for config in configs:
            if config.get('target_file') == target_file:
                spans.extend(compute_mask_spans(config.get('offsets', {})))
                spans.extend((r['start'], r['end'] - r['start'])
                             for r in config.get('flash_offsets', {}).get('ranges', []))
                if config.get('format') == 'texture_recolor' and config.get('texture'):
                    try:
                        spans.extend(recolor_spans(config['texture']))
                    except (KeyError, TypeError, ValueError):
                        pass
    return spans


def _resolve_model_tev_rgb(vanilla_path, target_path, offset, anchor):
    """Locate a TEV RGB slot by its masked block AND relocation-linked owner.

    ``model_tev_anchor`` is the file offset of 07 07 07 04, twelve bytes
    into an HSD_TObjTevDesc. Its RGB slots are anchor+4/+8/+12. Identical
    arc TEVs are common, so a bare marker or color match is insufficient:
    also match the owning TObj and ImageDesc with pointer fields masked.
    Alpha stays untouched, including an independently customized alpha.
    """
    from shared.rendering.datprobe import DatFile

    if not vanilla_path or not Path(vanilla_path).is_file():
        raise ValueError('A vanilla reference is required for model TEV RGB writes')
    if not isinstance(anchor, int) or offset - anchor not in (4, 8, 12):
        raise ValueError('Model TEV RGB offset must be anchor+4, +8, or +12')
    original, target = DatFile(vanilla_path), DatFile(target_path)
    block_start = anchor - 12

    def block_signature(dat, start):
        if start < 32 or start + 32 > 32 + dat.data_size:
            return None
        block = bytearray(dat.raw[start:start + 32])
        if block[12:16] != b'\x07\x07\x07\x04':
            return None
        # All three RGBA values may differ. Only the chosen RGB is written.
        block[16:28] = bytes(12)
        return bytes(block)

    def normalized_structure(dat, start, size):
        if start < 0 or start + size > dat.data_size:
            raise ValueError('Model owner lies outside the DAT data section')
        raw = bytearray(dat.raw[start + 32:start + 32 + size])
        for pointer in dat.relocs:
            if start <= pointer < start + size:
                if pointer + 4 > start + size:
                    raise ValueError('Misaligned pointer at model owner boundary')
                raw[pointer - start:pointer - start + 4] = bytes(4)
        return bytes(raw)

    def owner_signatures(dat, tev_start):
        signatures = set()
        for pointer in dat.relocs:
            if dat.u32(pointer) != tev_start - 32:
                continue
            tobj = pointer - 0x58
            if tobj < 0 or tobj + 0x5C > dat.data_size or tobj + 0x4C not in dat.relocs:
                continue
            image = dat.ptr(tobj + 0x4C)
            if image is None or image < 0 or image + 0x18 > dat.data_size:
                continue
            if image not in dat.relocs:
                continue
            # Width, height, GX format and mip settings remain part of the
            # identity; the relocated texel-data address does not.
            signatures.add((normalized_structure(dat, tobj, 0x5C),
                            normalized_structure(dat, image, 0x18)))
        return signatures

    expected = block_signature(original, block_start)
    if expected is None:
        raise ValueError('Invalid vanilla model TEV anchor')
    owners = owner_signatures(original, block_start)
    if not owners:
        raise ValueError('Vanilla model TEV has no verifiable texture owner')
    matches = []
    marker = target.raw.find(b'\x07\x07\x07\x04', 32, 32 + target.data_size)
    while marker >= 0:
        candidate = marker - 12
        if (block_signature(target, candidate) == expected
                and owners.intersection(owner_signatures(target, candidate))):
            matches.append(marker)
        marker = target.raw.find(b'\x07\x07\x07\x04', marker + 1, 32 + target.data_size)
    if len(matches) != 1:
        raise ValueError(f'Cannot safely identify model TEV ({len(matches)} owner/layout matches)')
    return matches[0] + offset - anchor


def apply_hex_patches(dat_path, offsets, modifications, safety=None):
    """Apply color patches to a .dat file.

    Args:
        dat_path: Path to the .dat file
        offsets: Dict of layer_id -> {start, end/size, format, offsets} offset info
        modifications: Dict of layer_id -> {color: "FC00" or "FFFFFFFF"} modifications
        safety: optional context from make_write_safety(). When provided,
            every write point is guarded against the vanilla_map[layer_id]
            bytes (falling back to offset_info['vanilla'] when the layer
            isn't in vanilla_map) before writing; on a guard failure it
            attempts offset relocation (ptcl-bank identity for CF/RGB,
            signature scan for 070707/98/42_48) and SKIPS the write (logging
            a warning + recording in safety['skipped']) if relocation also
            fails. When None (default), behaves exactly as before.

    Supports multiple formats:
    - Matrix format (has 'end'): Uses patch_matrix_colors for 98 00 ## ## format
    - Direct format (has 'size'): Writes color bytes directly at offset (for 42_48 RGBA)
    - CF format (format='CF'): Writes 3-byte RGB at offset+2, supports 'offsets' list
    - 070707 format (format='070707'): Writes 3-byte RGB at offset+1 and offset+5
    - RGB with model_tev_anchor: independent TEV RGB with mandatory model-owner
      layout proof, including reapplication after DAT relocation.
    """
    def _vanilla_bytes_for(layer_id, offset_info, expected_len):
        return _safety_vanilla_bytes(safety, layer_id, offset_info, expected_len)

    def _matrix_color_map(data, color_len, vanilla_hex, new_hex):
        """Match set for safe-mode matrix patches: vanilla color AND the
        matrix's CURRENT first color entry. Safe mode exists to protect
        position bytes in mixed matrices, but matching only vanilla makes a
        SECOND install (or restore) a silent no-op -- the entries hold the
        previous mod's color by then. The first entry is by-format a color
        entry (read_current_colors reads the same position), so its current
        value is the previously-applied color when the matrix was recolored.
        """
        cmap = {vanilla_hex: new_hex}
        first = bytes(data[4:4 + color_len]).hex().upper()
        if len(first) == color_len * 2:
            cmap.setdefault(first, new_hex)
        return cmap

    if safety is not None and not safety.get('mask_spans'):
        safety['mask_spans'] = compute_mask_spans(offsets)

    with file_retry.retry_locked(open, dat_path, 'r+b') as f:
        for layer_id, layer_mods in modifications.items():
            if layer_id not in offsets:
                logger.warning(f"Unknown layer '{layer_id}' in modifications, skipping")
                continue

            offset_info = offsets[layer_id]
            color_format = offset_info.get('format', 'RGBY')  # Default to RGBY for backwards compat
            color_hex = layer_mods.get('color', '')

            if 'model_tev_anchor' in offset_info:
                if safety is None:
                    raise ValueError('Model TEV RGB writes require a write-safety context')
                try:
                    color_bytes = bytes.fromhex(color_hex)
                    if color_format != 'RGB' or len(color_bytes) != 3 or offset_info.get('size', 3) != 3:
                        raise ValueError('Model TEV colors must contain exactly three RGB bytes')
                    positions = offset_info.get('offsets', [offset_info.get('start')])
                    # Flush earlier standard writes before inspecting this file
                    # through a separate reader; only color bytes are masked.
                    f.flush()
                    destinations = [_resolve_model_tev_rgb(
                        safety.get('vanilla_path'), dat_path, position,
                        offset_info['model_tev_anchor']) for position in positions]
                except (ValueError, TypeError, OSError, IndexError, struct.error) as error:
                    safety['skipped'].append({'extra_id': safety.get('extra_id', '?'),
                                              'layer_id': layer_id, 'reason': str(error)})
                    continue
                for destination in destinations:
                    f.seek(destination)
                    f.write(color_bytes)
                continue

            # Handle multi-offset formats (CF or 070707 with 'offsets' list)
            if 'offsets' in offset_info:
                offsets_list = offset_info['offsets']
                try:
                    color_bytes = bytes.fromhex(color_hex)
                    if len(color_bytes) != 3:
                        logger.warning(f"Invalid color length for {layer_id}: {color_hex}, expected 3 bytes (RGB)")
                        continue
                except ValueError:
                    logger.warning(f"Invalid hex color for {layer_id}: {color_hex}")
                    continue

                vbytes = _vanilla_bytes_for(layer_id, offset_info, 3)

                if color_format == 'CF':
                    # CF format: color at each offset+2
                    n_written = 0
                    for i, offset in enumerate(offsets_list):
                        color_off = offset + 2
                        target = _resolve_offset(
                            safety, f"{layer_id}[{i}]", color_off, vbytes,
                            block_kind='ptcl', write_len=3) if safety else color_off
                        if target is None:
                            continue
                        f.seek(target)
                        f.write(color_bytes)
                        n_written += 1
                    logger.debug(f"Patched CF {layer_id} at {n_written}/{len(offsets_list)} offsets with color {color_hex}")
                elif color_format == '070707':
                    # 070707 format: color at offset+4 and offset+8 (after 07 07 07 04 marker)
                    # write_len=11 spans marker..second color so the context
                    # guard proves the neighborhood; the color spans
                    # themselves are already in mask_spans.
                    n_written = 0
                    for i, offset in enumerate(offsets_list):
                        marker_target = _resolve_offset(
                            safety, f"{layer_id}[{i}]", offset, None,
                            block_kind='model', marker_len=4,
                            write_len=11) if safety else offset
                        if marker_target is None:
                            continue
                        f.seek(marker_target + 4)
                        f.write(color_bytes)
                        f.seek(marker_target + 8)
                        f.write(color_bytes)
                        n_written += 1
                    logger.debug(f"Patched 070707 {layer_id} at {n_written}/{len(offsets_list)} offsets with color {color_hex}")
                elif color_format == 'RGB':
                    # direct RGB slots: 3 bytes exactly at each offset (Mewtwo
                    # bolts: one picker drives the same slot in four records)
                    n_written = 0
                    for i, offset in enumerate(offsets_list):
                        target = _resolve_offset(
                            safety, f"{layer_id}[{i}]", offset, vbytes,
                            block_kind='ptcl', write_len=3) if safety else offset
                        if target is None:
                            continue
                        f.seek(target)
                        f.write(color_bytes)
                        n_written += 1
                    logger.debug(f"Patched RGB {layer_id} at {n_written}/{len(offsets_list)} offsets with color {color_hex}")
                continue

            # Handle 98_multi format (multiple 98 matrix ranges with same color)
            if 'ranges' in offset_info:
                ranges_list = offset_info['ranges']
                if not color_hex:
                    color_hex = 'FC00'  # Default RGBY
                try:
                    color_bytes = bytes.fromhex(color_hex)
                    if len(color_bytes) != 2:
                        logger.warning(f"Invalid color length for {layer_id}: {color_hex}, expected 2 bytes (RGBY)")
                        continue
                except ValueError:
                    logger.warning(f"Invalid hex color for {layer_id}: {color_hex}")
                    continue

                # Get vanilla color for safe mode if specified
                vanilla_hex = offset_info.get('vanilla')

                # Patch each range. In safe mode, match vanilla AND the
                # range's current first color entry so re-installs/restores
                # aren't no-ops (see _matrix_color_map).
                for range_info in ranges_list:
                    start = range_info['start']
                    end = range_info['end']
                    f.seek(start)
                    data = f.read(end - start)
                    if vanilla_hex:
                        cmap = _matrix_color_map(data, 2, vanilla_hex.upper(), color_hex)
                        modified = patch_matrix_colors(data, color_format='RGBY', color_map=cmap)
                    else:
                        modified = patch_matrix_colors(data, color_bytes, 'RGBY', None)
                    f.seek(start)
                    f.write(modified)
                logger.debug(f"Patched 98_multi {layer_id} at {len(ranges_list)} ranges with color {color_hex}")
                continue

            start = offset_info.get('start', 0)

            # Handle 42_48 format (3x RGBA colors)
            if color_format == '42_48':
                size = offset_info.get('size', 12)
                if not color_hex:
                    color_hex = '808080FFFFFFFFFFFFFFFFFF'  # Default gray/white
                try:
                    color_bytes = bytes.fromhex(color_hex)
                    if len(color_bytes) != size:
                        logger.warning(f"Invalid color length for {layer_id}: {color_hex}, expected {size} bytes")
                        continue
                except ValueError:
                    logger.warning(f"Invalid hex color for {layer_id}: {color_hex}")
                    continue
                f.seek(start)
                f.write(color_bytes)
                logger.debug(f"Patched 42_48 {layer_id} at 0x{start:X} with color {color_hex}")
                continue

            # Determine patch mode based on offset_info structure
            if 'size' in offset_info:
                # Direct write mode - for 42_48 RGBA format
                size = offset_info['size']
                if not color_hex:
                    color_hex = '0099FFFF'  # Default blue RGBA

                try:
                    color_bytes = bytes.fromhex(color_hex)
                    if len(color_bytes) != size:
                        logger.warning(f"Invalid color length for {layer_id}: {color_hex}, expected {size} bytes")
                        continue
                except ValueError:
                    logger.warning(f"Invalid hex color for {layer_id}: {color_hex}")
                    continue

                # Write directly at offset
                f.seek(start)
                f.write(color_bytes)
                logger.info(f"[Patch] Direct write {layer_id} at 0x{start:X} with {color_hex} ({len(color_bytes)} bytes)")

            elif color_format == 'CF':
                # Single CF offset: color at offset+2
                if not color_hex:
                    color_hex = 'FFFFFF'
                try:
                    color_bytes = bytes.fromhex(color_hex)
                    if len(color_bytes) != 3:
                        logger.warning(f"Invalid color length for {layer_id}: {color_hex}, expected 3 bytes")
                        continue
                except ValueError:
                    logger.warning(f"Invalid hex color for {layer_id}: {color_hex}")
                    continue
                vbytes = _vanilla_bytes_for(layer_id, offset_info, 3)
                target = _resolve_offset(
                    safety, layer_id, start + 2, vbytes,
                    block_kind='ptcl', write_len=3) if safety else start + 2
                if target is None:
                    continue
                f.seek(target)
                f.write(color_bytes)
                logger.debug(f"Patched CF {layer_id} at 0x{target:X} with color {color_hex}")

            elif color_format == '070707':
                # Single 070707 offset: color at offset+4 and offset+8 (after 07 07 07 04 marker)
                if not color_hex:
                    color_hex = 'FFFFFF'
                try:
                    color_bytes = bytes.fromhex(color_hex)
                    if len(color_bytes) != 3:
                        logger.warning(f"Invalid color length for {layer_id}: {color_hex}, expected 3 bytes")
                        continue
                except ValueError:
                    logger.warning(f"Invalid hex color for {layer_id}: {color_hex}")
                    continue
                marker_target = _resolve_offset(
                    safety, layer_id, start, None,
                    block_kind='model', marker_len=4,
                    write_len=11) if safety else start
                if marker_target is None:
                    continue
                f.seek(marker_target + 4)
                f.write(color_bytes)
                f.seek(marker_target + 8)
                f.write(color_bytes)
                logger.debug(f"Patched 070707 {layer_id} at 0x{marker_target:X} with color {color_hex}")

            elif 'end' in offset_info:
                # Matrix patch mode - for 98 00 ## ## format
                end = offset_info['end']
                if not color_hex:
                    color_hex = 'FC00' if color_format == 'RGBY' else 'FFFFFF'

                # Determine expected color byte length based on format
                expected_len = 3 if color_format == 'RGB' else 2

                # Parse color bytes
                try:
                    color_bytes = bytes.fromhex(color_hex)
                    if len(color_bytes) != expected_len:
                        logger.warning(f"Invalid color length for {layer_id} ({color_format}): {color_hex}, expected {expected_len} bytes")
                        continue
                except ValueError:
                    logger.warning(f"Invalid hex color for {layer_id}: {color_hex}")
                    continue

                # Read the section
                f.seek(start)
                data = f.read(end - start)

                # Get vanilla color for safe mode (only patch matching entries)
                # This prevents corrupting position data in mixed-format matrices.
                # Safe mode matches vanilla AND the current first color entry so
                # a re-install / restore over a previous mod isn't a no-op.
                vanilla_hex = offset_info.get('vanilla')

                if vanilla_hex:
                    color_len = 3 if color_format == 'RGB' else 2
                    cmap = _matrix_color_map(data, color_len, vanilla_hex.upper(), color_hex)
                    modified = patch_matrix_colors(data, color_format=color_format, color_map=cmap)
                else:
                    modified = patch_matrix_colors(data, color_bytes, color_format, None)

                # Write back
                f.seek(start)
                f.write(modified)

                logger.debug(f"Patched {layer_id} ({color_format}) at 0x{start:X}-0x{end:X} with color {color_hex}")

    if safety is not None:
        return safety['skipped']
    return []
