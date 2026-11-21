"""Read current common-motion identity and archive length before authoring.

This checks bank facts and the common state-name table, not state lifetime,
hitstun, callbacks, animation rate, or equivalence to Ultimate timing.
"""
import hashlib
import math
import struct
from pathlib import Path

from vault.echo import subactions
from shared.ingame import motion_states


def read_motion_contract(pl_bytes, aj_bytes, *, action, state, motion):
    if type(action) is not int or type(state) is not int:
        raise ValueError('Action and state must be integer indices')
    if not isinstance(motion, str) or not motion:
        raise ValueError('Motion name required')
    if motion_states.MOTION_STATES.get(state) != motion:
        raise ValueError(f'State {state} does not name {motion} in the common state table')
    fd = subactions.FighterDat(pl_bytes)
    if not 0 <= action < len(fd.actions):
        raise ValueError('Action outside current bank')
    row = fd.actions[action]
    if row.motion != motion:
        raise ValueError(f'Action {action} names {row.motion}, not {motion}')
    start, size = row.anim_offset, row.anim_size
    if start < 0 or size < 32 or start + size > len(aj_bytes):
        raise ValueError('Current animation slice outside AJ')
    blob = aj_bytes[start:start + size]
    extent, data_size, relocations, roots, refs = struct.unpack_from('>5I', blob)
    tables_end = 32 + data_size + 4 * relocations + 8 * (roots + refs)
    if extent != len(blob) or data_size < 12 or tables_end >= len(blob) or roots != 1:
        raise ValueError('Malformed standalone animation archive')
    dat = subactions.Dat(blob)
    symbol, root = dat.roots[0]
    if symbol != row.symbol or not 0 <= root <= data_size - 12:
        raise ValueError('Current animation public root differs or lies outside data')
    end = dat.f32(root + 8)
    if not math.isfinite(end) or end < 0:
        raise ValueError('Invalid animation frame header')
    sha = lambda b: hashlib.sha256(b).hexdigest()
    return {
        'action': action, 'state': state, 'motion': motion, 'symbol': symbol,
        'archive_end': end, 'offset': start, 'bytes': size, 'sha256': sha(blob),
        'pl_sha256': sha(pl_bytes), 'aj_sha256': sha(aj_bytes),
        'implementation_sha256': {
            str(Path(p).resolve()): sha(Path(p).read_bytes())
            for p in (__file__, subactions.__file__, motion_states.__file__)
        },
        'scope': 'Current archive identity and common state name only; native duration and consumer semantics require a separate contract.'
    }


def require_motion_contract(pl_bytes, aj_bytes, *, action, state, motion, archive_end):
    if type(archive_end) not in (int, float) or not math.isfinite(archive_end) or archive_end < 0:
        raise ValueError('Finite nonnegative expected archive end required')
    result = read_motion_contract(pl_bytes, aj_bytes, action=action, state=state, motion=motion)
    if result['archive_end'] != archive_end:
        raise ValueError(f"Current {motion} archive ends at {result['archive_end']}, not declared {archive_end}")
    return result
