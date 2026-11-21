"""A port's own states, after the donor's.

A fighter's special states are a table in the game's code: for each state the
action (clip and script) it plays and the functions that run it. The donor's
table is in the game's executable. m-ex lets a fighter's code file bring a table
of its own, so a port keeps the donor's rows as they are (same functions, by
their addresses) and adds rows to the end for moves the donor has nothing like:
a dive, a charge, a pull along a whip. The added states play clips put on donor
actions the port does not otherwise use.

  donor_states   the donor's rows, read from the executable
  table_text     the C table: the donor's rows, then the port's own
"""
from __future__ import annotations

import struct

FIRST_SPECIAL_STATE = 341       # the first state after the ones every fighter shares
FIRST_SPECIAL_ACTION = 295      # ... and its action
COMMON_STATE_TABLE = 0x803C2800  # NTSC 1.02 ftData_MotionStateList
ROW = 0x20


def dol_at(dol: bytes, address: int, size: int) -> bytes:
    """`size` bytes of a GameCube executable at a memory address."""
    offsets, addresses, sizes = (struct.unpack_from('>18I', dol, o) for o in (0x00, 0x48, 0x90))
    for o, a, s in zip(offsets, addresses, sizes):
        if s and a <= address and address + size <= a + s:
            return dol[o + address - a:o + address - a + size]
    raise ValueError(f'{address:#x} is not in the executable')


def donor_states(dol: bytes, address: int, count: int):
    """The donor's special states: [{action, flags, move, bits, anim, iasa, phys, coll, camera}]."""
    rows = []
    for i in range(count):
        action, flags, move, bits, *calls = struct.unpack('>iIBB2x5I', dol_at(dol, address + i * ROW, ROW))
        if not all(c == 0 or 0x80003100 <= c < 0x80400000 for c in calls):
            raise ValueError(f'state {FIRST_SPECIAL_STATE + i}: the table does not read as functions ({[hex(c) for c in calls]})')
        rows.append(dict(zip(('action', 'flags', 'move', 'bits', 'anim', 'iasa', 'phys', 'coll', 'camera'),
                             (action, flags, move, bits, *calls))))
    return rows


def common_states(dol: bytes):
    """The engine's common attack rows, for custom follow-ups that keep their move identity."""
    return donor_states(dol, COMMON_STATE_TABLE, FIRST_SPECIAL_STATE)


def common_by_motion(dol: bytes, action):
    """Keep the original flags, move/stale ID and callbacks for each ordinary motion."""
    rows = common_states(dol)
    by_action = {}
    for state, row in enumerate(rows):
        by_action.setdefault(row['action'], dict(row, state=state))
    return {motion: by_action[index] for motion, index in action.items() if index in by_action}


def table_text(donor_rows, own_rows):
    """C for the fighter's state table. `own_rows`: [{name, action, flags, move, anim, iasa, phys, coll}]
    with C function names (or 0, or a donor function's address) for the four calls; a row copied from a
    donor's (the same state on another action) keeps its `bits` and `camera` too. They follow the donor's
    rows in order, so the first has state number FIRST_SPECIAL_STATE + len(donor_rows)."""
    def call(v):
        return f'(void *){v:#x}' if isinstance(v, int) and v else (v or '0')

    lines = ["// The donor's own special states, as the game has them, then this port's.",
             '__attribute__((used)) static struct FtState move_logic[] = {']
    for i, r in enumerate(donor_rows):
        lines.append(f"    {{{r['action']}, {r['flags']:#x}, {r['move']:#x}, {r['bits']:#x}, {call(r['anim'])}, {call(r['iasa'])}, "
                     f"{call(r['phys'])}, {call(r['coll'])}, {call(r['camera'])}}},    // {FIRST_SPECIAL_STATE + i}")
    for i, r in enumerate(own_rows):
        lines.append(f"    {{{int(r['action'])}, {int(r['flags']):#x}, {int(r['move']):#x}, {int(r.get('bits') or 0):#x}, "
                     f"{call(r.get('anim'))}, {call(r.get('iasa'))}, "
                     f"{call(r.get('phys'))}, {call(r.get('coll'))}, {call(r.get('camera')) if r.get('camera') else 'Fighter_UpdateCameraBox'}}},    "
                     f"// {FIRST_SPECIAL_STATE + len(donor_rows) + i}: {r['name']}")
    lines += ['};', '']
    return lines


def iasa_wrapper(name, before, original):
    """Run a port's current-input check, then the donor IASA only if it kept the state."""
    call = f'((void (*)(GOBJ *)){original:#x})(gobj)' if isinstance(original, int) and original else \
           f'{original}(gobj)' if original else None
    lines = [f'void {name}(GOBJ *gobj)', '{', '    FighterData *fd = gobj->userdata;',
             '    int state = fd->state_id;', f'    {before}(fd, gobj);']
    if call:
        lines += ['    if (fd->state_id == state)', f'        {call};']
    return lines + ['}', '']


def apply_iasa(donor_rows, state_of, replacements):
    """Install explicit module IASA wrappers on existing donor states before emitting the table."""
    for motion, callback in replacements.items():
        if motion not in state_of:
            raise ValueError(f'cannot wrap missing donor state {motion}')
        index = state_of[motion] - FIRST_SPECIAL_STATE
        if not 0 <= index < len(donor_rows):
            raise ValueError(f'{motion}: donor state index outside table')
        donor_rows[index]['iasa'] = callback
