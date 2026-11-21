"""A Brawl fighter's moveset file (the misc data in FitX.pac): its numbers, its animations' names, and the script of
every action (when hitboxes come out, what they do, when the fighter cannot be touched, when it may act).

The file is one block of data with a table of named sections. `data` is the fighter itself; the `param...`
sections are the numbers its specials' code reads, under the game's own names.

A script is a list of events of 8 bytes: a kind (two bytes), how many arguments, where they are. An argument is
8 bytes: what it is (0 a whole number, 1 a number in 60000ths, 2 an offset, 3 yes/no, 5 a variable,
6 a requirement) and its value.
"""
from __future__ import annotations

import struct

BASE = 0x20                         # offsets in the file are from the end of its header

# the `data` section's header: where each of its tables is
HEADER = ('subaction_flags', 'model_visibility', 'attributes', 'sse_attributes', 'misc', 'common_action_flags', 'action_flags',
          'unknown7', 'action_interrupts', 'entry_actions', 'exit_actions', 'action_pre', 'subaction_main', 'subaction_gfx',
          'subaction_sfx', 'subaction_other', 'anchored_items', 'gooey_bomb', 'bone_ref1', 'bone_ref2', 'entry_overrides',
          'exit_overrides', 'unknown22', 'arm_cannon', 'unknown24', 'static_articles', 'entry_article', 'unknown27')

EVENTS = {
    0x0001: 'wait', 0x0002: 'wait_until', 0x0004: 'loop', 0x0005: 'loop_end', 0x0007: 'call', 0x0008: 'return', 0x0009: 'goto',
    0x000A: 'if', 0x000B: 'and', 0x000C: 'or', 0x000D: 'else_if', 0x000E: 'else', 0x000F: 'end_if', 0x0010: 'switch',
    0x0011: 'case', 0x0012: 'default', 0x0013: 'end_switch',
    0x0200: 'change_action_status', 0x0201: 'change_action', 0x0206: 'enable_action_status', 0x0208: 'disable_action_status',
    0x020A: 'allow_interrupts', 0x020B: 'disallow_interrupts',
    0x0400: 'change_subaction', 0x0407: 'frame_speed',
    0x0500: 'reverse_direction',
    0x0600: 'hitbox', 0x0601: 'change_hitbox_damage', 0x0602: 'change_hitbox_size', 0x0603: 'delete_hitbox', 0x0604: 'clear_hitboxes',
    0x0605: 'body_collision', 0x0606: 'undo_bone_collision', 0x0608: 'bone_collision', 0x060A: 'grab_box', 0x060D: 'clear_grab_boxes',
    0x060E: 'throw', 0x060F: 'throw_release', 0x0610: 'inert_collision', 0x0615: 'special_hitbox', 0x0617: 'defensive_collision',
    0x061B: 'move_hitbox', 0x062B: 'thrown_hitbox',
    0x0707: 'rumble', 0x070B: 'rumble_loop',
    0x0800: 'edge_slide',
    0x0A00: 'sound', 0x0A01: 'sound_b', 0x0A02: 'sound_c', 0x0A03: 'stop_sound', 0x0A05: 'sound_victory', 0x0A09: 'sound_other',
    0x0B00: 'model_changer', 0x0B01: 'model_changer_b', 0x0B02: 'visibility',
    0x0C05: 'terminate_instance', 0x0C06: 'final_smash_state', 0x0C08: 'terminate_self', 0x0C09: 'ledge_grab', 0x0C0B: 'low_voice',
    0x0C19: 'damage_fall', 0x0C23: 'time_manipulation', 0x0C25: 'tag_display',
    0x0E00: 'set_air_ground', 0x0E01: 'add_momentum', 0x0E02: 'disallow_movement', 0x0E06: 'disallow_vertical', 0x0E08: 'set_momentum',
    0x1000: 'generate_article', 0x1003: 'remove_article', 0x1005: 'article_visibility',
    0x1100: 'graphic', 0x1101: 'graphic_b', 0x1102: 'external_graphic', 0x1103: 'sword_glow', 0x1105: 'sword_glow_off',
    0x1115: 'terminate_graphic', 0x111A: 'graphic_c', 0x111B: 'graphic_d',
    0x1200: 'set_variable', 0x1201: 'add_variable', 0x1202: 'sub_variable', 0x1206: 'float_set', 0x1207: 'float_add',
    0x120A: 'bit_set', 0x120B: 'bit_clear',
    0x1400: 'aesthetic_wind', 0x1404: 'terminate_wind',
    0x1A00: 'screen_shake', 0x1A04: 'camera_closeup', 0x1A08: 'normal_camera',
    0x1E00: 'armour', 0x1E03: 'add_damage',
    0x1F00: 'pickup_item', 0x1F01: 'throw_item', 0x1F02: 'drop_item', 0x1F03: 'consume_item', 0x1F05: 'beam_sword_trail',
    0x1F0C: 'fire_weapon', 0x1F0E: 'cracker_launcher',
    0x2100: 'flash_overlay_off', 0x2101: 'flash_overlay', 0x2102: 'change_flash', 0x2105: 'flash_light',
    0x6400: 'allow_interrupt',
}

# what a hitbox's flag word says (the effect is its low five bits; the rest by bit)
EFFECTS = {0: 'normal', 1: 'none', 2: 'slash', 3: 'electric', 4: 'freezing', 5: 'flame', 6: 'coin', 7: 'reverse', 8: 'trip',
           9: 'sleep', 11: 'bury', 12: 'stun', 14: 'flower', 17: 'grass', 18: 'water', 19: 'darkness', 20: 'paralyze',
           21: 'aura', 22: 'plunge', 23: 'down', 24: 'no_flinch'}


class Moveset:
    def __init__(self, data: bytes):
        self.data = data
        size, lookup, n_lookup, n_sections, n_external = struct.unpack_from('>5i', data, 0)
        table = BASE + lookup + n_lookup * 4
        strings = table + (n_sections + n_external) * 8
        self.sections, self.external = {}, {}
        for i in range(n_sections + n_external):
            off, name = struct.unpack_from('>ii', data, table + i * 8)
            text = data[strings + name:].split(b'\x00')[0].decode('ascii', 'replace')
            (self.sections if i < n_sections else self.external)[text] = off
        self.relocations = set(struct.unpack_from(f'>{n_lookup}i', data, BASE + lookup))
        # every offset the file points at, in order: a table runs until the next thing pointed at
        targets = {self.i32(r) for r in self.relocations} | set(self.sections.values()) | {lookup}
        self._ends = sorted(t for t in targets if 0 <= t <= lookup)
        self.header = dict(zip(HEADER, struct.unpack_from(f'>{len(HEADER)}i', data, BASE + self.sections['data'])))
        self.limit = lookup
        # a script may call one that lives in the file every fighter shares: the place its offset would go is on a
        # chain that starts at the shared script's entry in the table of names
        self.external_at = {}
        for name, at in self.external.items():
            while 0 < at < lookup and at not in self.external_at:
                self.external_at[at] = name
                at = self.i32(at)

    # ---- plain reads (offsets are from BASE)
    def i32(self, off):
        return struct.unpack_from('>i', self.data, BASE + off)[0]

    def f32(self, off):
        return struct.unpack_from('>f', self.data, BASE + off)[0]

    def text(self, off):
        return self.data[BASE + off:].split(b'\x00')[0].decode('ascii', 'replace')

    def end_of(self, off):
        """Where the block that starts at `off` ends: the next offset the file points at."""
        import bisect
        i = bisect.bisect_right(self._ends, off)
        return self._ends[i] if i < len(self._ends) else off

    # ---- the fighter's tables
    def subactions(self):
        """[{'index', 'name', 'blend', 'flags'}]: every animation slot, by number."""
        start = self.header['subaction_flags']
        count = (self.end_of(start) - start) // 8
        out = []
        for i in range(count):
            blend, flags, _pad, name = struct.unpack_from('>BBhi', self.data, BASE + start + i * 8)
            out.append({'index': i, 'name': self.text(name) if name > 0 else None, 'blend': blend, 'flags': flags})
        return out

    def attributes(self, count=None):
        """The fighter's numbers as (offset, float, int) rows; what each is, is the caller's to say."""
        start = self.header['attributes']
        count = count or (self.end_of(start) - start) // 4
        return [(i * 4, self.f32(start + i * 4), self.i32(start + i * 4)) for i in range(count)]

    def switches(self):
        """The model's switches: parts of it shown one group at a time (the sword in hand or not, the eyes of a final
        smash). -> ([[[bone number, ...] for each group] for each switch], {switch: the group shown at rest}); a
        switch with no group named for rest shows none."""
        at = self.header['model_visibility']
        if at <= 0:
            return [], {}
        sets, count, defaults, n_defaults = (self.i32(at + 4 * i) for i in range(4))
        first = self.i32(sets)                          # the first set of switches (a fighter's ordinary model)
        out = []
        for s in range(count):
            groups, n_groups = self.i32(first + 8 * s), self.i32(first + 8 * s + 4)
            row = []
            for g in range(n_groups):
                bones, n_bones = self.i32(groups + 8 * g), self.i32(groups + 8 * g + 4)
                row.append([self.i32(bones + 4 * k) for k in range(n_bones)] if n_bones else [])
            out.append(row)
        return out, {self.i32(defaults + 8 * k): self.i32(defaults + 8 * k + 4) for k in range(n_defaults)}

    def params(self, section):
        """A `param...` section's values as (offset, float, int) rows."""
        start = self.sections[section]
        return [(i * 4, self.f32(start + i * 4), self.i32(start + i * 4)) for i in range((self.end_of(start) - start) // 4)]

    def script(self, kind, index, depth=0):
        """The events of subaction `index`'s script of a kind ('main', 'gfx', 'sfx', 'other')."""
        table = self.header['subaction_' + kind]
        return self.events(self.i32(table + index * 4), depth)

    def events(self, off, depth=0):
        """[{'event', 'code', 'args'}] from `off` to the script's end. A call to another script in the file is
        followed (to a small depth), its events put in place of the call."""
        out = []
        if off <= 0:
            return out
        while True:
            ns, eid, count, _unk, args_at = struct.unpack_from('>BBBBi', self.data, BASE + off)
            code = ns << 8 | eid
            if code == 0 and count == 0:
                break
            args = []
            if count and not 0 < args_at < self.limit:
                break                                   # not an event: the script has run out
            for k in range(count):
                kind, value = struct.unpack_from('>ii', self.data, BASE + args_at + k * 8)
                if kind == 2 and args_at + k * 8 + 4 in self.external_at:
                    args.append(('shared', self.external_at[args_at + k * 8 + 4]))
                    continue
                args.append(value / 60000.0 if kind == 1 else bool(value) if kind == 3 else
                            ('var', value) if kind == 5 else ('req', value) if kind == 6 else ('at', value) if kind == 2 else value)
            name = EVENTS.get(code, f'{code:04x}')
            if (name in ('call', 'goto') and args and isinstance(args[0], tuple) and args[0][0] == 'at' and depth < 3
                    and 0 < args[0][1] < self.limit):
                inner = self.events(args[0][1], depth + 1)
                out += inner
                if name == 'goto':
                    break
            else:
                out.append({'event': name, 'code': code, 'args': args})
            off += 8
            if len(out) > 4000:
                break
        return out


def hitbox(args, special=False):
    """What a hitbox event says, in plain names. (A special hitbox has two more arguments: flags of its own.)"""
    bone_id, damage, angle, wdsk_kbg, shield_bkb, size, x, y, z, trip, hitlag, sdi, flags = args[:13]
    return {'id': bone_id & 0xFFFF, 'bone': bone_id >> 16, 'damage': damage, 'angle': angle,
            'kbg': wdsk_kbg & 0xFFFF, 'fkb': wdsk_kbg >> 16, 'bkb': shield_bkb & 0xFFFF, 'shield_damage': shield_bkb >> 16,
            'size': size, 'x': x, 'y': y, 'z': z, 'trip': trip, 'hitlag': hitlag, 'sdi': sdi, 'flags': flags & 0xFFFFFFFF,
            'effect': EFFECTS.get(flags & 0x1F, flags & 0x1F), 'special': special}


LOOP_MOST = 256                     # no script loops more often than this (a guard against a count read wrong)


def unrolled(events):
    """A script's events with its loops written out: what lies between `loop n` and `loop_end`, n times over. A loop
    with no count (below 1: it goes round for as long as the action lasts) is written once: the clip it is in plays
    round, and its script with it."""
    def body(i):
        seq = []
        while i < len(events):
            e = events[i]
            if e['event'] == 'loop':
                inner, i = body(i + 1)
                n = e['args'][0] if e['args'] and isinstance(e['args'][0], int) else 1
                seq += inner * max(1, min(n, LOOP_MOST))
            elif e['event'] == 'loop_end':
                return seq, i + 1
            else:
                seq.append(e)
                i += 1
        return seq, i
    return body(0)[0]


def timeline(events):
    """A script's events with the frame each runs on -> [(frame, event)]. Frames count from 1; a `wait` moves on by
    its number, a `wait_until` to its number; a frame-speed change is kept as an event; loops are written out."""
    frame, out = 1.0, []
    for e in unrolled(events):
        if e['event'] == 'wait' and e['args'] and isinstance(e['args'][0], (int, float)):
            frame += float(e['args'][0])
        elif e['event'] == 'wait_until' and e['args'] and isinstance(e['args'][0], (int, float)):
            frame = max(frame, float(e['args'][0]) + 1.0)
        else:
            out.append((frame, e))
    return out
