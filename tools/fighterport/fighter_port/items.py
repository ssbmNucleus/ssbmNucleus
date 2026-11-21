"""A port's projectile: an item of its own in the fighter's data file.

A Melee projectile is an item. Its data (attributes, a model, a state list
with the script that makes its hitbox) sits in the fighter's data file under
ftData+0x48, and its behaviour is code. A donor like Marth has neither, so:

  * the data is transplanted from a fighter that has a simple projectile
    (Mario's fireball: one state, one hitbox) and then given the port's own
    numbers: the hitbox from the Ultimate weapon's script, speed and life from
    its parameters;
  * the behaviour is a few C functions in the port's code file
    (`code.arrow_source`), built the way the m-ex toolkit's Mario example is.

`transplant` copies a struct and everything it points to from one data file
into another without moving any existing byte.
"""
from __future__ import annotations

import struct

ITEMS = 0x48                  # ftData: pointer to the list of item descriptions
# an item description: common attributes, own attributes, hurtboxes, states, model, dynamics
OWN, STATES, MODEL = 4, 0xC, 0x10
SCRIPT = 0xC                  # in a state: joint animation, material animation, parameters, script
HITBOX = 11                   # script command


def transplant(dst, src, start: int) -> int:
    """Copy the struct at `start` of `src` (a Dat), and all it reaches through
    pointers, to the end of `dst`. Each struct keeps its place within a 32-byte
    line (display lists and images must stay aligned). -> its offset in dst"""
    order, seen, stack = [], {}, [start]
    while stack:
        s = stack.pop()
        if s in seen:
            continue
        seen[s] = src.struct_end(s)
        order.append(s)
        stack += [src.u32(off) for off in range(s, seen[s], 4) if off in src.relocs]
    base = (dst.data_size + 0x1F) // 0x20 * 0x20
    place, pos = {}, 0
    for s in order:
        pos += (s - pos) % 0x20
        place[s] = pos
        pos += seen[s] - s
    blob, pointers = bytearray(pos), []
    for s in order:
        blob[place[s]:place[s] + seen[s] - s] = src.buf[0x20 + s:0x20 + seen[s]]
        for off in range(s, seen[s], 4):
            if off in src.relocs:
                at = place[s] + off - s
                struct.pack_into('>I', blob, at, base + place[src.u32(off)])
                pointers.append(at)
    got = dst.append_struct(bytes(blob), pointers, align=0x20)
    assert got == base
    return base + place[start]


def item_list(d):
    """(ftData offset, [item description offsets or None]) of a fighter data file."""
    ft = next(off for name, off in d.roots if name.startswith('ftData'))
    array = d.ptr(ft + ITEMS)
    if array is None:
        return ft, []
    return ft, [d.ptr(array + 4 * i) for i in range((d.struct_end(array) - array) // 4)]


def add_item(pl: bytes, template_pl: bytes, template_index: int, Dat):
    """`pl` with one more item, copied from item `template_index` of another
    fighter's data file. -> (bytes, the new item's index, its description offset)"""
    d, t = Dat(pl), Dat(template_pl)
    ft, mine = item_list(d)
    source = item_list(t)[1][template_index]
    if source is None:
        raise ValueError(f'the template has no item {template_index}')
    desc = transplant(d, t, source)
    entries = mine + [desc]
    blob = b''.join(struct.pack('>I', e or 0) for e in entries)
    array = d.append_struct(blob, [4 * i for i, e in enumerate(entries) if e is not None], align=4)
    d.set_u32(ft + ITEMS, array)
    d.add_reloc(ft + ITEMS)
    return d.to_bytes(), len(entries) - 1, desc


def unlight(d, joint):
    """Every joint under `joint` asks for no lights, and every material of theirs is "constant" (its own
    colour times its picture) with that colour white."""
    seen, todo = set(), [joint]
    while todo:
        j = todo.pop()
        if j is None or j in seen:
            continue
        seen.add(j)
        flags = d.u32(j + 4)
        d.set_u32(j + 4, flags & ~JOINT_LIT)
        todo += [d.ptr(j + 8), d.ptr(j + 0xC)]              # child, next
        piece = d.ptr(j + 0x10) if not flags & JOINT_NOT_MESH else None
        while piece is not None:
            material = d.ptr(piece + 8)
            if material is not None:
                d.set_u32(material + 4, (d.u32(material + 4) & ~RENDER_LIT) | RENDER_CONSTANT)
                colours = d.ptr(material + 0xC)
                if colours is not None:
                    d.set_u32(colours + 4, 0xFFFFFFFF)      # its own ("diffuse") colour
            piece = d.ptr(piece + 4)


def set_model(pl: bytes, desc: int, addon: bytes, Dat, unlit=True) -> bytes:
    """Give the item at `desc` the model in an add-on file (`weapons.build_addon`), and drop
    the template's animations of its old model from every state."""
    d, a = Dat(pl), Dat(addon)
    symbol = next(off for name, off in a.roots if name == 'mexCostume')
    joint = transplant(d, a, a.ptr(a.u32(a.ptr(symbol + 0xC))))
    d.set_u32(d.ptr(desc + MODEL), joint)
    if unlit:
        # Drawn in its own colours, whatever the stage lights do and whichever way it is turned: no joint asks
        # for lights, and every material is "constant" (its own colour times its picture) with that colour white.
        # (With lights a flat shape is bright on one face and dark on the other, so a shot let go to the right
        # was a dark shape and the same shot let go to the left a bright one.)
        unlight(d, joint)
    states = d.ptr(desc + STATES)
    gone = set()
    for state in range(states, d.struct_end(states), 0x10):
        for field in (state, state + 4):                # joint animation, material animation
            if d.ptr(field) is not None:
                d.set_u32(field, 0)
                gone.add(field)
    if gone:                                            # a zero that stays in the pointer list would not be null in game
        d._rebuild(bytes(d.buf[0x20:0x20 + d.data_size]), d.relocs - gone)
    return d.to_bytes()


SPIN = 0xC                    # common attributes: how fast the model turns in flight
JOINT_LIT, JOINT_NOT_MESH = 0x80, 0x4020      # joint flags: lit by the scene's lights; holds a curve or particles, not a mesh
RENDER_CONSTANT, RENDER_LIT = 0x1, 0xC        # a material's render flags: its own colour; shaded and shone on by lights


def set_spin(pl: bytes, desc: int, speed: float, Dat) -> bytes:
    """How fast the item's model turns as it flies (a thrown thing tumbles; an arrow must not)."""
    d = Dat(pl)
    d.set_f32(d.ptr(desc) + SPIN, speed)
    return d.to_bytes()


def set_own_attributes(pl: bytes, desc: int, values, Dat) -> bytes:
    """Give the item at `desc` a new block of own attributes (floats, read by the item's code)."""
    d = Dat(pl)
    block = d.append_struct(struct.pack(f'>{len(values)}f', *values), align=4)
    d.set_u32(desc + OWN, block)
    d.add_reloc(desc + OWN)
    return d.to_bytes()


# Script commands: wait so many frames; an item's "no hitboxes" (a fighter's is 16). (An item's script does
# not count its own frames, so the other timer, "until frame N", waits N frames from where it stands: seen in
# game as hits at 6, 18, 36 and 60 frames for a script written 6, 12, 18, 24. The game's own item scripts
# use this one.)
TIMER, NO_HITBOXES = 1, 15
SET_VAR = 17                  # ... and "set the item's first script variable" (the game's own item scripts end states with it)
DONE = 'done'                 # in `set_script` events: the script is over (the item's code reads the variable)
GROUP = (9, 3)                # in a hitbox command: which run of hits it belongs to (bit offset, bits)


def add_state(pl: bytes, desc: int, Dat):
    """One more state for the item at `desc`, after the ones it has (a state counts while it has a script).
    -> (bytes, the new state's number); give it a script with `set_script`."""
    d = Dat(pl)
    states = d.ptr(desc + STATES)
    count = 0
    while states + 0x10 * count + SCRIPT in d.relocs:
        count += 1
    size = 0x10 * count
    blob = bytes(d.buf[0x20 + states:0x20 + states + size]) + bytes(0x10)
    array = d.append_struct(blob, [off for off in range(0, size, 4) if states + off in d.relocs], align=4)
    d.set_u32(desc + STATES, array)
    return d.to_bytes(), count


def set_script(pl: bytes, desc: int, state: int, events, Dat) -> bytes:
    """Give state `state` of the item a script of hits: `events` is [(frame, hitbox values or None or DONE)],
    a hitbox (the fields `set_hitbox` takes) put out on that frame, None for none from then on, DONE to raise
    the item's first script variable (a hit stops the item's script for a few frames like a fighter's, so
    only the script knows when it has run out). Each hitbox
    is the item's first one with those values changed, in a run of its own unless `group` explicitly shares
    a run between simultaneous hitboxes: the game lets a hitbox of a
    new run hit again what the last one hit, which is how one shot hits several times."""
    from vault.echo import subactions as sa
    d = Dat(pl)
    states = d.ptr(desc + STATES)
    first = d.ptr(states + SCRIPT)
    spec, wait = sa.COMMANDS[HITBOX], sa.COMMANDS[TIMER]
    if first is None or d.buf[0x20 + first] >> 2 != HITBOX:
        raise ValueError("the item's first script does not start with a hitbox to copy")
    template = bytes(d.buf[0x20 + first:0x20 + first + spec.size + 4])       # an item's is a word longer than a fighter's
    known = {q.key: q for q in spec.params}
    frame_field = next(q for q in wait.params if q.key == 'frame')
    out, now, run = bytearray(), 0, 0
    for frame, hitbox in sorted(events, key=lambda e: e[0]):
        if frame > now:
            raw = bytearray(wait.size)
            sa.write_bits(raw, 0, 6, TIMER)
            sa.write_bits(raw, frame_field.bit_offset, frame_field.bits, int(frame - now))
            out += raw
            now = frame
        if hitbox is None or hitbox == DONE:
            raw = bytearray(4)
            sa.write_bits(raw, 0, 6, NO_HITBOXES if hitbox is None else SET_VAR)
            if hitbox == DONE:
                raw[3] = 1
            out += raw
            continue
        raw = bytearray(template)
        for key, value in hitbox.items():
            if key == 'group':
                if not isinstance(value, int) or not 0 <= value < (1 << GROUP[1]):
                    raise ValueError(f'group={value} out of range [0, 7]')
                continue
            if key == 'again':
                # the item-only word starts with a count of frames after which the same hitbox may hit the
                # same target again by itself (0: never; the script's own runs of hits are then the only ones)
                raw[spec.size] = int(value)
                continue
            q = known[key]
            if not q.min <= int(value) <= q.max:
                raise ValueError(f'{key}={value} out of range [{q.min}, {q.max}]')
            sa.write_bits(raw, q.bit_offset, q.bits, int(value))
        sa.write_bits(raw, GROUP[0], GROUP[1], hitbox.get('group', run % (1 << GROUP[1])))
        run += 1
        out += raw
    out += bytes(4)                                         # the end of the script
    script = d.append_struct(bytes(out), align=4)
    slot = d.ptr(desc + STATES) + 0x10 * state + SCRIPT
    d.set_u32(slot, script)
    d.add_reloc(slot)
    return d.to_bytes()


def set_hitbox(pl: bytes, desc: int, hitbox: dict, FighterDat) -> bytes:
    """Give the first hitbox of the item's first state script the values in `hitbox`
    (script field names: damage, angle, knockback_growth, base_knockback, size, element, ...).

    The fields are written where they are, bit by bit. An item's hitbox command is one
    word longer than a fighter's, and that word holds flags only items have (one of them
    lets it hit fighters at all), so the script must not be re-encoded as a fighter's."""
    from vault.echo import subactions as sa
    fd = FighterDat(pl)
    d = fd.dat
    script = d.ptr(d.ptr(desc + STATES) + SCRIPT)
    if script is None:
        raise ValueError('the item has no state script to carry a hitbox')
    spec = sa.COMMANDS[HITBOX]
    at = 0x20 + script
    if d.buf[at] >> 2 != HITBOX:
        raise ValueError("the item's script does not start with its hitbox")
    raw = bytearray(d.buf[at:at + spec.size])
    known = {q.key: q for q in spec.params}
    for key, value in hitbox.items():
        q = known[key]
        if not q.min <= int(value) <= q.max:
            raise ValueError(f'{key}={value} out of range [{q.min}, {q.max}]')
        sa.write_bits(raw, q.bit_offset, q.bits, int(value))
    d.buf[at:at + spec.size] = raw
    return d.to_bytes()
