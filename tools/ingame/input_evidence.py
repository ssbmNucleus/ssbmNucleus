"""Bounds-checked, read-only GALE01 controller delivery evidence.

Layouts are pinned by the local Melee decomp's ``controller.h`` and
``ft/types.h``.  Symbol addresses are from ``config/GALE01/symbols.txt``.
This reader reports stored values and raw producing blocks; it does not decide
whether an input should cause an action or whether a controller is functional.
"""
import math
import struct

from shared.ingame.items import address as _mem1_address
from shared.ingame.pose import CaptureError, _read


PAD_GAME_STATUS = 0x804C21CC
PAD_STATUS_SIZE = 0x44
COMMON_DATA_POINTER = 0x804D6554
COMMON_DATA_CAPTURE_SIZE = 0x5C


def _address(value, size, label):
    """Apply the shared aligned-MEM1 convention with capture semantics."""
    try:
        return _mem1_address(value, size)
    except ValueError as exc:
        raise CaptureError(f'Invalid {label}: {value!r}') from exc


def _finite_floats(raw, offsets, label):
    values = [struct.unpack_from('>f', raw, offset)[0] for offset in offsets]
    if not all(math.isfinite(value) for value in values):
        raise CaptureError(f'Nonfinite {label}')
    return values


def capture_input_evidence(d, fighter):
    """Capture raw-pad, fighter-filtered, previous, timer and threshold data.

    The game should be frozen and the caller should bracket this multi-read
    snapshot with a stable frame counter.  No memory is written.
    """
    _address(fighter, 0x674, 'fighter pointer')
    raw_blocks = []

    def read(address, size, name):
        raw = _read(d, address, size)
        raw_blocks.append({
            'name': name, 'address': address, 'size': size, 'raw': raw.hex(),
        })
        return raw

    identity = read(fighter + 0x618, 4, 'fighter_controller_identity')
    controller = identity[0]
    if controller not in range(4):
        raise CaptureError(f'Invalid fighter controller index: {controller}')

    pad_address = PAD_GAME_STATUS + controller * PAD_STATUS_SIZE
    pad = read(pad_address, PAD_STATUS_SIZE, 'hsd_pad_game_status')
    raw_stick = list(struct.unpack_from('>bb', pad, 0x18))
    pad_stick = _finite_floats(pad, (0x20, 0x24), 'normalized pad left stick')

    fighter_input = read(fighter + 0x620, 0x54, 'fighter_input_and_timers')
    current = _finite_floats(fighter_input, (0, 4), 'fighter left stick')
    previous = _finite_floats(fighter_input, (8, 12), 'previous fighter left stick')

    common_pointer_raw = read(COMMON_DATA_POINTER, 4, 'p_ft_common_data')
    common_pointer = struct.unpack('>I', common_pointer_raw)[0]
    _address(common_pointer, COMMON_DATA_CAPTURE_SIZE, 'ftCommonData pointer')
    common = read(common_pointer, COMMON_DATA_CAPTURE_SIZE, 'ft_common_input_thresholds')
    threshold_offsets = {
        'horizontal_deadzone': 0x00,
        'walk_threshold': 0x24,
        'walk_middle_threshold': 0x28,
        'walk_fast_threshold': 0x2C,
        'turn_threshold': 0x34,
        'turn_run_threshold': 0x38,
        'dash_threshold': 0x3C,
        'run_threshold': 0x58,
    }
    threshold_values = _finite_floats(
        common, tuple(threshold_offsets.values()), 'common input threshold')
    thresholds = dict(zip(threshold_offsets, threshold_values))
    thresholds['dash_window'] = struct.unpack_from('>i', common, 0x40)[0]

    return {
        'schema': 'gale01-input-evidence-v1',
        'fighter': fighter,
        'controller_index': controller,
        'pad': {
            'table_address': PAD_GAME_STATUS,
            'entry_address': pad_address,
            'entry_size': PAD_STATUS_SIZE,
            'raw_left_stick_s8': raw_stick,
            'raw_left_stick_bytes': pad[0x18:0x1A].hex(),
            'normalized_left_stick': pad_stick,
        },
        'fighter_input': {
            'left_stick': current,
            'previous_left_stick': previous,
            'tilt_timer_x': fighter_input[0x50],
        },
        'common': {
            'pointer_address': COMMON_DATA_POINTER,
            'pointer': common_pointer,
            'thresholds': thresholds,
        },
        'raw_blocks': raw_blocks,
        'limits': [
            'Read-only stored input evidence; no action or delivery verdict.',
            'Caller must freeze and independently bracket the multi-read snapshot.',
        ],
    }
