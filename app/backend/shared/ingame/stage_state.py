"""Read the NTSC 1.02 engine ground kind, not the SSS icon or StKind.

GALE01 symbols.txt binds stage_info at 0x8049E6C8; gr/types.h places
StageInfo.grkind at +0x88. Ground_801C0754 copies pair->grkind there;
Ground_801BFFB0 resets it to -1. Preserve unknown values rather than guessing
an m-ex stage name. This identifies the selected ground kind, not the loaded
stage asset bytes. Call inside the probe's game-counter bracket.
"""
import struct

from .pose import _read

STAGE_INFO = 0x8049E6C8
GROUND_KIND_OFFSET = 0x88


def capture_stage_state(d):
    raw = _read(d, STAGE_INFO + GROUND_KIND_OFFSET, 4)
    return {'schema': 'gale01-stage-ground-kind-v1',
            'address': STAGE_INFO + GROUND_KIND_OFFSET,
            'raw': raw.hex(), 'ground_kind': struct.unpack('>i', raw)[0]}
