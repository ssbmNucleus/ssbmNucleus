"""Retail NTSC 1.02 collision rendering, without a debug-menu patch.

ftDrawCommon_800805C8 reads Fighter+0x21FC: MSB-numbered b6 (0x02)
draws attacks, hurt capsules, shields and reflectors; b7 (0x01) draws the
model. Other flags are preserved. Reapply after loading another match.
"""
from .gamestate import Player

MODES = ('off', 'overlay', 'collision')


def set_debug_draw(d, mode='overlay', ports=range(6)):
    if mode not in MODES:
        raise ValueError(f'debug mode must be one of {MODES}')
    result = []
    for port in ports:
        if not isinstance(port, int) or not 0 <= port < 6:
            raise ValueError('port must be 0..5')
        ft = Player(d, port).resolve()
        if not ft or not 0x80000000 <= ft < 0x81800000:
            continue
        addr = ft + 0x21FC
        before = d.u8(addr)
        after = (before & ~3) | {'off': 1, 'overlay': 3, 'collision': 2}[mode]
        d.write_u8(addr, after)
        if d.u8(addr) != after:
            raise RuntimeError(f'debug draw readback failed for port {port}')
        result.append({'port': port, 'mode': mode, 'before': before, 'after': after})
    return result
