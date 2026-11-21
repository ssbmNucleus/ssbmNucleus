"""
The extras configuration and everything that compares a DAT with its vanilla
reference under the configured storage root.

init_extras_api() (called once by app.py) sets STORAGE_PATH, the project files
lookup and the HSDRawViewer path; the extras modules read them as
helpers.STORAGE_PATH and so on. The functions that need the storage root's
vanilla reference DATs live beside that state: the write-safety context, the
resolved current colors of an extra, a texture recolor's status, and restoring
an extra's vanilla color bytes. find_dat_file locates a fighter DAT in the
project files.
"""

import os
import logging
import uuid
import struct
import file_retry
from pathlib import Path
from vault.extras import relocate as _relocate
from vault.extras.color_patch import (compute_mask_spans, _resolve_offset,
    _safety_vanilla_bytes, file_color_mask_spans, _resolve_model_tev_rgb)
from vault.extras.color_read import read_current_colors

# Callers reach these as helpers.<name> (the color routes, devtools/extras_doctor).
from vault.extras.offsets import get_dynamic_offsets  # noqa: F401
from vault.extras.color_patch import patch_shine_color_slots  # noqa: F401
from vault.extras.derive import derive_modifications_from_dat  # noqa: F401

logger = logging.getLogger(__name__)


# These will be set by init_extras_api()
STORAGE_PATH = None
get_project_files_dir = None
HSDRAW_VIEWER_PATH = None


def init_extras_api(storage_path, project_files_dir_func, hsdraw_viewer_path=None):
    """Initialize the extras API with required dependencies from app.py."""
    global STORAGE_PATH, get_project_files_dir, HSDRAW_VIEWER_PATH
    STORAGE_PATH = storage_path
    get_project_files_dir = project_files_dir_func
    HSDRAW_VIEWER_PATH = hsdraw_viewer_path


# =============================================================================
# OFFSET SAFETY: guard + relocation (backend/vault/extras/relocate.py)
# =============================================================================
#
# apply_hex_patches / patch_shine_sparkle_color accept an optional `safety`
# context (see `make_write_safety()`) so every extras write path benefits
# from vanilla-byte guarding without each format branch reimplementing it.
# When `safety` is None the functions behave EXACTLY as before (write
# unconditionally) -- existing callers that don't pass it are unaffected.

def make_write_safety(dat_path, extra_id, target_file, vanilla_map=None):
    """Build the `safety` context threaded through apply_hex_patches /
    patch_shine_sparkle_color. Resolves the vanilla reference DAT from
    STORAGE_PATH/test-base/files/<target_file> if available.

    Args:
        dat_path: the file actually being patched (for guard reads)
        extra_id: extra type id, for warning/skip messages
        target_file: filename used to locate the vanilla reference DAT
        vanilla_map: optional dict layer_id -> vanilla hex string (from the
            extra type config's 'vanilla' dict) used as the guard baseline

    Returns a dict consumed by _resolve_offset (never raises).
    """
    vanilla_path = None
    try:
        vanilla_path = _relocate.vanilla_reference_path(STORAGE_PATH, target_file)
    except Exception as e:
        logger.debug(f"[relocate] could not resolve vanilla reference for {target_file}: {e}")
    return {
        'dat_path': dat_path,
        'extra_id': extra_id,
        'vanilla_path': vanilla_path,
        'vanilla_map': vanilla_map or {},
        'mask_spans': [],  # (start, len) color spans this extra can write --
                           # excluded from the context guard's neighborhood
                           # compare (see compute_mask_spans)
        'skipped': [],  # list of skip dicts appended to as writes are attempted
    }


def find_dat_file(files_dir, target_file):
    """Find a .dat file in the MEX build files directory.

    Args:
        files_dir: Path to MEX build/files directory
        target_file: Target filename (e.g., 'PlFc.dat')

    Returns:
        Path to the file if found, None otherwise
    """
    # Check common locations
    possible_paths = [
        files_dir / target_file,
        files_dir / "PlCo" / target_file,  # Character data folder
        files_dir / "fighter" / target_file,
    ]

    for path in possible_paths:
        if path.exists():
            return path

    # Search recursively if not found in common locations
    matches = list(files_dir.rglob(target_file))
    return matches[0] if matches else None


def texture_recolor_status(dat_path, type_config):
    """'vanilla' | 'custom' | 'unknown' for a texture_recolor extra, by its
    exact bytes -- not by the dominant-hue swatch, which is an estimate that
    differs from the config's swatch even on untouched files.

    Every span an install rewrites (texel block or live palette entries) is
    compared with the vanilla reference file. All equal: vanilla. Otherwise
    custom, but only where the bytes around every differing span still match
    vanilla (the texture sits where the config says); if not, the file's
    layout moved and nothing can be said: unknown. No vanilla reference:
    unknown.
    """
    from .texture_recolor import recolor_spans
    target_file = type_config['target_file']
    vanilla_path = _relocate.vanilla_reference_path(STORAGE_PATH, target_file)
    if not vanilla_path or not os.path.exists(vanilla_path):
        return 'unknown'

    def differs(start, length):
        current = _relocate.read_bytes(dat_path, start, length)
        return len(current) != length or current != _relocate.read_bytes(vanilla_path, start, length)

    spans = recolor_spans(type_config['texture'])
    changed = [span for span in spans if differs(*span)]
    if not changed:
        return 'vanilla'
    # Palettes sit back to back, so prove the layout around each contiguous
    # run of spans (a single palette's neighbors are its masked siblings).
    blocks = []
    for start, length in sorted(spans):
        if blocks and start <= blocks[-1][1]:
            blocks[-1][1] = max(blocks[-1][1], start + length)
        else:
            blocks.append([start, start + length])
    masks = file_color_mask_spans(target_file)
    changed_blocks = [(start, end) for start, end in blocks
                      if any(start <= c < end for c, _length in changed)]
    if all(_relocate.context_guard(vanilla_path, dat_path, start, end - start, masks)
           for start, end in changed_blocks):
        return 'custom'
    return 'unknown'


def resolve_current_colors(dat_path, offsets, extra_id, target_file,
                           vanilla_map=None, trusted_layers=(), config_offsets=None):
    """Read each layer's current color where a guarded install would write it.

    read_current_colors() seeks the raw config offsets. After an HSDRaw
    re-save (texture/model import) or in a fighter DAT with a non-vanilla
    layout those point at unrelated bytes, so the "Currently in MEX" card
    showed garbage colors or a false Vanilla while installs relocated or
    skipped correctly. This locates every layer with the SAME machinery the
    write path uses (make_write_safety + _resolve_offset: vanilla-byte guard,
    neighborhood guard, ptcl operand identity, model signature scan; model
    TEV RGB slots via _resolve_model_tev_rgb). Formats the writer patches
    without relocation (98 matrices, 42_48, direct `size` spans) are read in
    place only when their surrounding bytes still match the vanilla file.

    The neighborhood guard masks every color span configured in this FILE
    (file_color_mask_spans), not only this extra's: a recolored sibling
    effect changes only its own spans and must not make this layer look
    shifted. That is at least as permissive as the write guard, never less.

    Args:
        trusted_layers: layer ids whose offsets came from dynamic detection
            (get_dynamic_offsets found them by content in THIS file); they
            are read in place, as before.
        config_offsets: the extra's configured (vanilla-layout) offsets, used
            to read a trusted layer's reference bytes from the vanilla file.

    Returns:
        (colors, unresolved, verified, reference): `colors` has one entry per
        layer that could be located; `unresolved` lists {'layer_id',
        'reason'} for the rest; `reference` holds, per located layer, the
        vanilla file's bytes at the SAME slot -- the exact vanilla value,
        unlike the config's representative swatches. `verified` is False
        when no vanilla reference is available -- nothing can be proven then,
        so every layer is read in place exactly like read_current_colors()
        (the previous behavior) and `reference` is empty.
    """
    safety = make_write_safety(dat_path, extra_id, target_file, vanilla_map)
    vanilla_path = safety.get('vanilla_path')
    if not vanilla_path or not os.path.exists(vanilla_path):
        return read_current_colors(dat_path, offsets), [], False, {}
    safety['mask_spans'] = file_color_mask_spans(target_file, offsets)

    colors = {}
    reference = {}
    unresolved = []

    def read_at(position, length, path=dat_path):
        data = _relocate.read_bytes(path, position, length)
        return data.hex().upper() if len(data) == length else None

    def in_place(layer_id, info, path=dat_path):
        try:
            return read_current_colors(path, {layer_id: info}).get(layer_id)
        except (OSError, IndexError, KeyError, TypeError):
            return None

    def last_reason(default):
        return safety['skipped'][-1].get('reason', default) if safety['skipped'] else default

    for layer_id, info in offsets.items():
        fmt = info.get('format', 'RGBY')
        color = None
        ref = None
        reason = 'offset could not be located in this file'

        if layer_id in trusted_layers:
            color = in_place(layer_id, info)
            config_info = (config_offsets or {}).get(layer_id)
            ref = in_place(layer_id, config_info, vanilla_path) if config_info else None
        elif 'model_tev_anchor' in info:
            positions = info.get('offsets', [info.get('start')])
            try:
                destination = _resolve_model_tev_rgb(
                    vanilla_path, dat_path, positions[0], info['model_tev_anchor'])
                color = read_at(destination, 3)
                ref = read_at(positions[0], 3, vanilla_path)
            except (ValueError, TypeError, OSError, IndexError, struct.error) as error:
                reason = str(error)
        elif 'offsets' in info:
            if fmt not in ('CF', '070707', 'RGB'):
                continue  # read_current_colors has no reading for these either
            vbytes = _safety_vanilla_bytes(safety, layer_id, info, 3)
            for i, offset in enumerate(info['offsets']):
                if fmt == '070707':
                    marker = _resolve_offset(safety, f"{layer_id}[{i}]", offset, None,
                                             block_kind='model', marker_len=4, write_len=11)
                    position = None if marker is None else marker + 4
                else:
                    position = _resolve_offset(
                        safety, f"{layer_id}[{i}]", offset + (2 if fmt == 'CF' else 0),
                        vbytes, block_kind='ptcl', write_len=3)
                if position is not None:
                    color = read_at(position, 3)
                    ref = read_at(offset + {'070707': 4, 'CF': 2}.get(fmt, 0), 3, vanilla_path)
                    break
            reason = last_reason(reason)
        elif 'ranges' in info or 'size' in info or fmt == '42_48' or fmt not in ('CF', '070707'):
            # Written in place without relocation (98 matrices, 42_48,
            # direct spans): trust the raw offset only while the bytes around
            # it still match vanilla.
            spans = [(r['start'], r['end'] - r['start']) for r in info.get('ranges', [])]
            if not spans:
                start = info.get('start', 0)
                if fmt == '42_48':
                    spans = [(start, info.get('size', 12))]
                elif 'size' in info:
                    spans = [(start, info['size'])]
                elif 'end' in info:
                    spans = [(start, info['end'] - start)]
                else:
                    spans = [(start, 4 + (3 if fmt == 'RGB' else 2))]
            if all(_relocate.context_guard(vanilla_path, dat_path, start, length,
                                           safety['mask_spans'])
                   for start, length in spans):
                color = in_place(layer_id, info)
                ref = in_place(layer_id, info, vanilla_path)
            else:
                reason = 'the bytes around this layer no longer match the vanilla layout'
        elif fmt == 'CF':
            start = info.get('start', 0)
            vbytes = _safety_vanilla_bytes(safety, layer_id, info, 3)
            position = _resolve_offset(safety, layer_id, start + 2, vbytes,
                                       block_kind='ptcl', write_len=3)
            color = None if position is None else read_at(position, 3)
            ref = read_at(start + 2, 3, vanilla_path)
            reason = last_reason(reason)
        else:  # single 070707 block
            start = info.get('start', 0)
            marker = _resolve_offset(safety, layer_id, start, None,
                                     block_kind='model', marker_len=4, write_len=11)
            color = None if marker is None else read_at(marker + 4, 3)
            ref = read_at(start + 4, 3, vanilla_path)
            reason = last_reason(reason)

        if color:
            colors[layer_id] = color
            if ref:
                reference[layer_id] = ref
        else:
            unresolved.append({'layer_id': layer_id, 'reason': reason})
    return colors, unresolved, True, reference


def restore_extra_color_bytes(dat_path, type_config, offsets=None, report=None):
    """Restore each writable operand's exact reference bytes, preserving siblings.

    Grouped swatches are representative colors, not a lossless vanilla
    recipe. Locate the original write spans using unchanged archive layout,
    particle operand identity, or a unique masked model/context signature.
    Only those spans are copied; no whole-file or whole-model replacement.
    """
    from core.extra_types import EXTRA_TYPES

    dat_path = Path(dat_path)
    ref = _relocate.vanilla_reference_path(STORAGE_PATH, type_config['target_file'])
    if not ref:
        raise ValueError('A vanilla reference is required to restore exact effect colors')
    vanilla = Path(ref).read_bytes()
    target = dat_path.read_bytes()
    offsets = type_config.get('offsets', {}) if offsets is None else offsets
    model_anchors = {position: info['model_tev_anchor']
                     for info in offsets.values() if 'model_tev_anchor' in info
                     for position in info.get('offsets', [info.get('start')])}
    groups = []  # (source block start, block length, writable relative spans)
    for info in offsets.values():
        fmt = info.get('format', 'RGBY')
        if 'records' in info:
            for record in info['records']:
                for key in ('color', 'secondary'):
                    if record.get(key) is not None:
                        groups.append((record[key], 3, [(0, 3)]))
        elif 'offsets' in info or fmt == '070707':
            for start in info.get('offsets', [info.get('start')]):
                if fmt == '070707':
                    groups.append((start, 11, [(4, 3), (8, 3)]))
                else:
                    position = start + (2 if fmt == 'CF' else 0)
                    groups.append((position, 3, [(0, 3)]))
        elif 'ranges' in info or ('end' in info and 'size' not in info):
            width = 3 if fmt == 'RGB' else 2
            for region in info.get('ranges', [info]):
                start, end = region['start'], region['end']
                # The writer also edits the matrix's first reference color;
                # it can differ from the representative config swatch.
                reference_colors = {vanilla[start + 4:start + 4 + width]}
                if info.get('vanilla'):
                    reference_colors.add(bytes.fromhex(info['vanilla']))
                slots = [(position, width) for position in range(4, end - start - width + 1, 4)
                         if not info.get('vanilla') or vanilla[start + position:start + position + width]
                         in reference_colors]
                groups.append((start, end - start, slots))
        else:
            start = info.get('start')
            if start is None:
                continue
            size = info.get('size', 12 if fmt == '42_48' else 3)
            if fmt == 'CF':
                start += 2
            groups.append((start, size, [(0, size)]))

    # Mask every configured sibling's color writes for layout comparison;
    # sibling colors are allowed to differ but will never be restored here.
    masks = compute_mask_spans(offsets)
    for configs in EXTRA_TYPES.values():
        for config in configs:
            if config.get('target_file') == type_config['target_file']:
                masks.extend(compute_mask_spans(config.get('offsets', {})))
                masks.extend((r['start'], r['end'] - r['start'])
                             for r in config.get('flash_offsets', {}).get('ranges', []))
    intervals = []
    for start, size in sorted(masks):
        if intervals and start <= intervals[-1][1]:
            intervals[-1] = (intervals[-1][0], max(intervals[-1][1], start + size))
        else:
            intervals.append((start, start + size))
    unshifted = len(vanilla) == len(target)
    cursor = 0
    if unshifted:
        for start, end in intervals + [(len(vanilla), len(vanilla))]:
            if vanilla[cursor:start] != target[cursor:start]:
                unshifted = False
                break
            cursor = end

    # Keep kind AND absolute color ordinal together. PrimCol and EnvCol are
    # interleaved, so indexing a kind-filtered list with the global ordinal
    # can misidentify secondaries after a file rewrite.
    operand_map = {}
    if not unshifted:
        try:
            parser = _relocate._ptcl_parse()
            _, old_scripts = parser.parse_bank(vanilla)
            _, new_scripts = parser.parse_bank(target)
            new_by_index = {script.index: script for script in new_scripts}
            for script in old_scripts:
                other = new_by_index.get(script.index)
                if other is None or len(script.colors) != len(other.colors):
                    continue
                for original, current in zip(script.colors, other.colors):
                    if all(original[key] == current[key] for key in ('kind', 'channels', 'size')):
                        for byte in range(original['size']):
                            operand_map[original['file_off'] + byte] = current['file_off'] + byte
        except Exception as error:
            logger.debug(f'Particle restore identity unavailable: {error}')

    result = bytearray(target)
    skipped = []
    restored_spans = 0
    for start, size, spans in groups:
        if start < 0 or start + size > len(vanilla):
            raise ValueError(f'Configured color span lies outside vanilla DAT: 0x{start:X}')
        if start in model_anchors:
            try:
                if size != 3 or spans != [(0, 3)]:
                    raise ValueError('Model TEV restoration only supports independent RGB slots')
                destination = _resolve_model_tev_rgb(ref, dat_path, start, model_anchors[start])
            except (ValueError, TypeError, OSError, IndexError, struct.error) as error:
                skipped.append({'layer_id': f'0x{start:X}', 'reason': str(error)})
                continue
        else:
            destination = start if unshifted else None
        if destination is None and all(start + i in operand_map for i in range(size)):
            candidate = operand_map[start]
            if all(operand_map[start + i] == candidate + i for i in range(size)):
                destination = candidate
        if destination is None and _relocate.context_guard(ref, dat_path, start, size, masks):
            destination = start
        if destination is None:
            # Prefer the model block's own non-color layout. Direct operands
            # need surrounding context; exact same patterns elsewhere are
            # ambiguous and are refused rather than guessed by proximity.
            block_mask = {relative + byte for relative, length in spans for byte in range(length)}
            fixed = [(i, vanilla[start + i]) for i in range(size) if i not in block_mask]
            window_start, window_end = start, start + size
            if len(fixed) < 8:
                window_start, window_end = max(0, start - 24), min(len(vanilla), start + size + 24)
                fixed = [(i - window_start, vanilla[i]) for i in range(window_start, window_end)
                         if not any(lo <= i < hi for lo, hi in intervals)]
            matches = []
            if len(fixed) >= 8:
                anchor, value = fixed[0]
                position = target.find(bytes([value]))
                while position >= 0:
                    base = position - anchor
                    if base >= 0 and base + window_end - window_start <= len(target) and all(
                            target[base + i] == byte for i, byte in fixed):
                        matches.append(base + start - window_start)
                        if len(matches) > 1:
                            break
                    position = target.find(bytes([value]), position + 1)
            if len(matches) == 1:
                destination = matches[0]
        if destination is None:
            skipped.append({'layer_id': f'0x{start:X}', 'reason': 'No unique reference layout or operand identity'})
            continue
        for relative, length in spans:
            result[destination + relative:destination + relative + length] = vanilla[start + relative:start + relative + length]
            restored_spans += 1

    temporary = dat_path.with_name(f'.{dat_path.name}.{uuid.uuid4().hex}.restore-colors')
    try:
        temporary.write_bytes(result)
        file_retry.replace(temporary, dat_path)
    finally:
        temporary.unlink(missing_ok=True)
    if report is not None:
        report['restored_spans'] = report.get('restored_spans', 0) + restored_spans
    return skipped
