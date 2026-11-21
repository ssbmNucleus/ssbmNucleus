"""A fighter's own Ultimate particle effects as Melee particle generators in the fighter's own Melee effect file.

Three parts.

1. Melee's side, each writer with a reader so a written file can be read back and compared:
   the particle command list (`encode_commands` / `decode_commands`), one generator (`generator` / `read_generator`),
   the particle bank (`particle_bank` / `read_particle_bank`), GameCube pictures in the three formats used here
   (`encode_image` / `decode_image`: I8, IA8, RGB5A3), the texture bank (`texture_bank` / `read_texture_bank`) and
   the effect file itself (`effect_file` / `read_effect_file`): a DAT with two roots, the fighter's effect table
   and m-ex's `effBehaviorTable`, which says how a script places each generator.

2. The conversion, `convert`: one Ultimate emitter (the numbers `echo_ultimate.effects.emitter` reads) to one
   Melee generator. Melee's particle is a square picture that faces the camera, with one colour, one size, one
   speed and one spread, run by a short list of timed commands. What an emitter has beyond that is not carried,
   and `convert` lists it.

3. What a port driver calls: `Plan` (which sets a fighter's scripts use, at which sizes: the generators, the
   pictures, the file, a report) and `script_items` (the script commands that play a set).

Nothing here was seen in the game. The Melee side follows the decompiled particle code (sysdolphin's particle.c,
psdisp.c) and m-ex's effect code, and its readers and writers agree with the game's own effect files: every
generator in them is read and written back as the same bytes, and the two banks are laid out as Marth's are. The
Ultimate side stands on the readings in `echo_ultimate.effects`. The constants marked READING below are choices
made where the source is silent; each can be changed in one place.

Lengths: Ultimate's sizes, speeds, radii and gravity are multiplied by `scale` (the fighter's drawn scale,
Ultimate units to Melee units) and by the size the script call gives.

How a generator is placed (m-ex's behaviour byte; a script plays generator n of the fighter's own file as effect
6000 + n):
  3  at the joint plus the command's offset, turned to the way the fighter faces (+Z ahead, +Y up, which is the
     space an Ultimate effect is built in, so an emitter's direction is used as it is). Not held by the joint: it
     must end by itself, so it is given a set number of frames. Used for an emitter that gives off once.
  6  held by the joint, turned the same way, and removed when the move ends if the script command's destroy flag
     is set. The command's offset is NOT used by the game for this one, so an offset is added to each particle
     instead (`convert`'s `offset`). Its particles live in the joint's place: they are carried along when the
     joint moves. The joint's own turn is NOT applied to it (only the facing). Used for an emitter that is not
     one-time, which is given no end, and for any emitter of a set the game's script makes FOLLOW its bone
     (EFFECT_FOLLOW...: `convert`'s `held`), which keeps its own end if it has one. (Wolf's Fire Wolf, 2026-11-13:
     its fire, given off once at the point he took off from, burned there while he flew away.)

STAND-INS, made by rule and named per emitter in `Plan.report` (its `stand_in`):
  - an emitter that draws its picture on a 3D shape (see `echo_ultimate.effects.model`, `shapes`): the shape with
    its pictures on it is flattened into one picture as the camera sees it (`fighter_port.effect_shapes`), carried
    by flat particles with the emitter's own timing, colour, alpha and size keys. The shape does not turn in depth:
    its random turn and spin about any axis but the one toward the camera, a size that grows more one way than
    another, and any movement of its picture over it are not carried. A shape that shows nothing from the side is
    not carried, nor one that would be drawn wider than all the camera shows (`WIDEST_STAND_IN`), nor one a port
    makes its own stand-in for (`Plan.by_hand`);
  - an emitter that draws with more than one picture: they are joined into one as its combiner says
    (`echo_ultimate.effects.combiner`, a reading); where that draws a square or a dark box, a picture made
    see-through where it is dark (and cut round, for a square) stands in.

Not carried, by rule (each is listed per emitter in `Plan.report`):
  - an emitter that only bends what is behind it (a refraction), and the map of offsets of one that bends its own
    pictures (see `echo_ultimate.effects.shader_mode`);
  - a 3D shape that is not among the file's models, that lies edge-on to the camera, or that would be drawn wider
    than all the camera shows;
  - emitters inside emitters (what a particle gives off);
  - an emitter that gives off by how far it has moved (see `echo_ultimate.effects.emission`);
  - the second colour (fixed or keyed; how each emitter mixes it in is not known), and the particle colour's own
    way of joining the pictures (Melee multiplies the picture by it);
  - a size much longer one way than the other (drawn as a square of the mean), size that varies from particle to
    particle when the size also changes over the life, turns about any axis but the one toward the camera,
    a pull that is not straight up or down, the random part of the spin;
  - the smaller of the two speeds when an emitter has both an all-direction speed and a directed one;
  - the shape of the space particles start in: any shape is a box here (command A8), and a particle's own
    life sets nothing about its keys: keys are laid out over the longest life, so a particle that draws a shorter
    one is cut off before its last keys;
  - the beat of an emitter that skips frames between givings-off: here it gives off evenly at the same average
    rate.
"""
from __future__ import annotations

import math
import struct
from pathlib import Path

import numpy as np

# ------------------------------------------------------------------------------------------------------------
# READINGS: choices where the source is silent. Change them here after looking in the game.
# ------------------------------------------------------------------------------------------------------------

# Melee's `size` is half the square's width. Ultimate's size is read as the full width.
SIZE_TO_HALF_WIDTH = 0.5
# Velocity is the emitter's direction times its directed speed, as written. Duck Hunt's directions are not of
# length 1 ((-0.2, 0.2, -1.0), (-0.8, 0.5, -1.0)), so a direction's length scales the speed (by up to 1.4 there).
# Whether the game makes the direction length 1 first is not known. True: it is made length 1 here.
DIRECTION_IS_UNIT = False
# How an emitter gives off over time (see `echo_ultimate.effects.emission`, which tells why). True: it gives off
# `rate` particles, skips `interval` frames (plus up to `interval_random`), and gives off again; a one-time
# emitter does so for its first `emit_frames` frames and one that is not one-time without end. False: the
# interval is not used, and an emitter that is not one-time is taken to give off `rate` a frame for `emit_frames`
# of every `loop` frames, evened out (the reading in `echo_ultimate.effects.emitter`'s note).
INTERVAL_APPLIES = True
# Ultimate adds an all-direction speed to a directed one; Melee has one speed and one spread. When the
# all-direction speed is the larger, the generator throws at that speed over this angle (radians) from the
# emitter's direction: pi is every direction.
ALL_DIRECTIONS = math.pi
# A picture cut into frames with the mode 'once' or 'loop' steps through its frame table one entry a frame
# (stopping on the last, or starting again). Duck Hunt's 'once' tables are as long as the life, which fits.
TABLE_STEP_FRAMES = 1
# The sense of a turn about the axis toward the camera: 1 keeps Ultimate's sign, -1 flips it.
ROTATE_SIGN = 1.0
# An emitter's random start turn is read as "turn, plus up to turn_random more", which is the form of Melee's
# command ED. Random size and random life are read as "the value, less up to r per cent".
# The share of its spin a particle keeps each frame (`spin_keep`) sets how far it turns in all; Melee turns it at
# an even rate. False: the spin is taken as constant.
SPIN_KEEP_APPLIES = True
# A size this many times longer one way than the other is reported as not carried (it is drawn square).
LONG_SIZE = 1.5
# Smoke. Every Duck Hunt emitter whose second alpha track is keyed (35, all on the shared smoke pictures) has a
# first alpha track that climbs from near 0 to near 1 over the life, and second alpha values up to 3. Read as
# plain see-through-ness the smoke would thicken until it vanished. READING: for these the first track is what
# is taken off the picture's own alpha (the smoke is eaten away as it climbs) and the second multiplies what is
# left: alpha = (picture alpha - first) * second. Carried as Melee's alpha test (command B3) with a threshold
# that climbs with the first track, and a prim alpha of (1 - first) * second, capped at 1. The edge of the eaten
# smoke is hard here and soft in Ultimate. False: the first track is carried as plain alpha, the second dropped.
DISSOLVE = True
DISSOLVE_STEP = 4                   # frames between the points a dissolve is sampled at (its curve is not a line)
# A first alpha that is fixed at 0 would make a particle that is never seen. Wolf's Fire Wolf flames (three of his
# 121 emitters: the main fire of the move) are such, with a fixed second alpha of 2, and Duck Hunt's trick shot
# has two with a second alpha of 1. READING: these are DISSOLVE's pair too, with nothing eaten: what is drawn is
# the second alpha (capped at 1). False: the fixed 0 is drawn (the particles are not seen).
UNSEEN_IS_DISSOLVE = True
# A picture counts as grey when this share of its visible pixels have channels within GREY_TOLERANCE of each
# other (the game's pictures are block-compressed, which tints grey a little), and its alpha as equal to its
# brightness on the same terms.
GREY_TOLERANCE = 12
GREY_SHARE = 0.995
# A grey picture with no alpha of its own (every pixel opaque) is stored as I8, where the console takes the
# brightness as the alpha too. Duck Hunt's gun sight is such a picture, white lines on black, and two of the three
# emitters that use it blend normally: with the alpha as stored they would draw the black as a solid square.
# READING: the game takes such a picture's see-through-ness from its brightness. False: stored opaque (IA8).
OPAQUE_GREY_IS_MASK = True
MAX_SIDE = 64                       # a picture's frames are made no larger than this a side
MIN_SIDE = 8
# A flattened 3D shape (`Plan`) is stored with no more pixels a side than about this many a Melee unit it is drawn
# across (and at least 16): Melee's camera shows a fighter's height (about 15 units) in some 60 to 100 pixels.
# READING, for room: a speed line 5 units long needs no 64 pixels. And none is stored larger than SHAPE_SIDE:
# Greninja's 34 flattened shapes at 64 a side took 285 KiB, more than the rest of his effects' pictures together.
SHAPE_PIXELS = 4.0
SHAPE_SIDE = 32
# A flattened 3D shape that would be drawn wider than this many Melee units is not carried: Final Destination's
# blast zones are 492 apart, so such a picture covers all the camera ever shows. Greninja's Water Shuriken hold
# has a flare (cmn_flare1, a shape 49 across) of size 45: drawn as read, 2,140 across, it tinted the whole screen
# for as long as he held it. What the game does with that size is not known. The widest of five fighters' other
# 260 flattened shapes is 193 (Charizard's roar).
WIDEST_STAND_IN = 500.0
EDGE_ON = 'its 3D shape shows nothing from the side (it lies edge-on to the camera)'
# A picture cut into many frames is the costly kind (a fire of 16 frames at 64 a side is 128 KiB): a group's
# frames are halved in size until together they take no more than this.
GROUP_BYTES = 32 * 1024
# A picture that is a quarter of a whole is drawn four times by Melee's mirror flags (command B1). The game
# doubles the picture's coordinates and adds 1 to the one that runs down, which puts the picture's right edge
# and its TOP edge at the middle of the square; Ultimate's quarters have the middle at their bottom right corner,
# so their frames are stored upside down. (Read from psdisp.c's texture matrix, and Melee's own files agree: of
# the pictures its generators draw with this command, the 19 with one bright corner all have it at the top
# right.) False: stored as they are.
MIRROR_STORES_FLIPPED = True
BANK_WARNING_BYTES = 256 * 1024     # a texture bank above this is reported (after `Plan.fit` made it smaller)
FIT_LEAST_SIDE = 16                 # `Plan.fit` halves no picture below this a side
# The script call's turn turns the whole effect: the way its particles fly (always) and the way they are pulled.
# READING: whether the game turns the pull with the effect or keeps it to the world's down is not known. True: it
# is turned, and only its up and down part is carried (Melee pulls along up and down only). False: as written.
PULL_TURNS = True
# A streak that flies along its own length (the long axis, turned as the particle is, within ALONG_DEGREES of the
# way it flies) is laid on the screen by its speed (Melee's command E6: the picture's upright axis follows the
# particle's speed as the camera sees it), not at a fixed turn. A fixed turn is right for one facing and one turn
# of the joint only; this one is right for both facings and any turn the fighter's code gives the joint. Such a
# streak is given at least LEAST_SPEED, so that the game has a way to read off it. False: always a fixed turn.
LAY_ALONG_SPEED = True
ALONG_DEGREES = 25.0
LEAST_SPEED = 0.05

BURST_BEHAVIOUR = 3                 # m-ex: at the joint plus the offset, turned to the fighter's facing
STEADY_BEHAVIOUR = 6                # m-ex: held by the joint, turned to the fighter's facing
# m-ex 5 (FollowJointPos): the generator follows the joint and gives its particles off turned as the joint is
# turned (the particle system's joint turn, particle.c, type 0x400), but they stay where they were given off. 6
# turns them to the facing only, so a shape the joint holds and lays along its speed (Greninja's water blades)
# pointed one way whatever the hand did. Such a shape is given off anew each frame with this behaviour, each
# picture lasting RENEWED_LIFE frames (`Plan._flat_shape`). READING: one frame is drawn once.
TURNED_BEHAVIOUR = 5
RENEWED_LIFE = 1
ATTACHED = (5, 6, 7)                # behaviours whose generators the game removes when a move ends
OWN_EFFECT = 6000                   # a script plays generator n of the fighter's own effect file as 6000 + n
MOST_GENERATORS = 1000              # 6000 to 6999: from 7000 on the game looks in another fighter's file
EFFECT_COMMAND = 10                 # the script command that plays an effect

# ------------------------------------------------------------------------------------------------------------
# particle commands
# ------------------------------------------------------------------------------------------------------------

# Commands with a fixed layout: code -> its arguments (struct letters, big-endian; 'e' is a count of one byte,
# or two when the first has its top bit set). Codes below 0x80 are waits (0x00) and picture changes (0x40);
# 0x80 to 0x9F set or add to position and velocity; 0xC0 to 0xDF set the two colours.
FIXED = {
    0xA0: 'ef',   0xA1: '',     0xA2: 'f',    0xA3: 'f',
    0xA4: 'H',    0xA5: 'H',    0xA6: 'HH',   0xA7: 'B',
    0xA8: 'fff',  0xA9: 'f',    0xAA: 'HH',   0xAB: 'f',
    0xAC: 'eff',  0xAD: '',     0xAE: '',     0xAF: '',
    0xB0: '',     0xB1: '',     0xB2: '',     0xB3: 'eBBB',
    0xB4: '',     0xB5: '',     0xB6: 'ef',   0xB7: 'B',
    0xB8: 'Bff',  0xB9: 'H',    0xBA: 'bbbb', 0xBB: 'bbbb',
    0xBC: 'BB',   0xBD: 'ff',   0xBE: 'fff',  0xBF: 'B',
    0xE0: 'bbbb', 0xE1: 'B',    0xE2: '',     0xE3: 'B',
    0xE4: 'B',    0xE5: 'B',    0xE6: '',     0xE7: '',
    0xE8: 'f',    0xEC: 'Bf',   0xED: 'ffB',  0xEE: '',
    0xEF: 'HB',   0xF0: 'HB',   0xF1: 'H',    0xF2: 'H',
    0xF3: '', 0xF4: '', 0xF5: '', 0xF6: '', 0xF7: '', 0xF8: '', 0xF9: '',
    0xFA: 'B',    0xFB: '',     0xFC: '',     0xFD: '',
    0xFE: '',     0xFF: '',
}
END_CODES = (0xFD, 0xFE, 0xFF)      # nothing after one of these is run
WAIT, PICTURE, ADD_POSITION, PRIM = 0x00, 0x40, 0x88, 0xC0
SIZE, LIFE, SCATTER, SIZE_RANDOM, MIRROR_BOTH, ALPHA_TEST, SPIN = 0xA0, 0xA6, 0xA8, 0xAC, 0xB1, 0xB3, 0xB6
RANDOM_PICTURE, RANDOM_SPEED, RANDOM_TURN, END = 0xBC, 0xBD, 0xED, 0xFF
ALONG_SPEED = 0xE6                  # the picture's upright axis follows the particle's speed on the screen
MAX_WAIT, MAX_COUNT = 0x1FFF, 0x7FFF
ALPHA_AT_LEAST = 0x33               # alpha test mode: keep a pixel whose alpha is at least the first number


def _read_count(data, at):
    value = data[at]
    at += 1
    if value & 0x80:
        value = ((value & 0x7F) << 8) | data[at]
        at += 1
    return value, at


def _write_count(value):
    if not 0 <= value <= MAX_COUNT:
        raise ValueError(f'a count of {value} does not fit (0 to {MAX_COUNT})')
    return bytes([value]) if value < 0x80 else bytes([0x80 | (value >> 8), value & 0xFF])


def _read_wait(code, data, at):
    value = code & 0x1F
    if code & 0x20:
        value = (value << 8) | data[at]
        at += 1
    return value, at


def _write_wait(base, value):
    if not 0 <= value <= MAX_WAIT:
        raise ValueError(f'a wait of {value} does not fit (0 to {MAX_WAIT})')
    return bytes([base | value]) if value < 0x20 else bytes([base | 0x20 | (value >> 8), value & 0xFF])


def decode_commands(data, start=0, stop_at_end=True):
    """A command list as [(code, arguments)], and where it ends.

    A wait is (0x00, [frames]); a picture change (0x40, [frames to wait after it, picture number]). The position
    and velocity commands keep their axes in the code and take [{'x': .., 'y': .., 'z': ..}]; the colour commands
    keep their channels in the code and take [count, {'r': .., 'g': .., 'b': .., 'a': ..}]."""
    at, out = start, []
    while at < len(data):
        code = data[at]
        at += 1
        if code < 0x40:
            wait, at = _read_wait(code, data, at)
            out.append((WAIT, [wait]))
        elif code < 0x80:
            wait, at = _read_wait(code, data, at)
            out.append((PICTURE, [wait, data[at]]))
            at += 1
        elif code < 0xA0:
            values = {}
            for bit, axis in ((1, 'x'), (2, 'y'), (4, 'z')):
                if code & bit:
                    values[axis] = struct.unpack_from('>f', data, at)[0]
                    at += 4
            out.append((code, [values]))
        elif 0xC0 <= code < 0xE0:
            count, at = _read_count(data, at)
            channels = {}
            for bit, channel in ((1, 'r'), (2, 'g'), (4, 'b'), (8, 'a')):
                if code & bit:
                    channels[channel] = data[at]
                    at += 1
            out.append((code, [count, channels]))
        elif code == 0xE9:
            flags, timing = data[at], data[at + 1]
            at += 2
            deltas = []
            for bit in (1, 2, 4, 8):
                if flags & bit:
                    deltas.append(struct.unpack_from('>b', data, at)[0])
                    at += 1
            out.append((code, [flags, timing, deltas]))
        elif code in (0xEA, 0xEB):
            count, at = _read_count(data, at)
            flags = data[at]
            at += 1
            colour = alpha = None
            if flags & 1:
                colour = data[at]
                at += 1
            if flags & 8:
                alpha = data[at]
                at += 1
            out.append((code, [count, flags, colour, alpha]))
        else:
            arguments = []
            for letter in FIXED[code]:
                if letter == 'e':
                    value, at = _read_count(data, at)
                else:
                    value = struct.unpack_from('>' + letter, data, at)[0]
                    at += struct.calcsize('>' + letter)
                arguments.append(value)
            out.append((code, arguments))
        if stop_at_end and code in END_CODES:
            break
    return out, at


def encode_commands(commands):
    """[(code, arguments)] as bytes: the other way of `decode_commands`. A position, velocity or colour command
    may be given by its base code (0x88, 0xC0, ...): the axes and channels are taken from its dict."""
    out = bytearray()
    for code, arguments in commands:
        if code == WAIT:
            out += _write_wait(WAIT, arguments[0])
        elif code == PICTURE:
            out += _write_wait(PICTURE, arguments[0]) + bytes([arguments[1]])
        elif 0x80 <= code < 0xA0:
            values = arguments[0]
            mask = sum(bit for bit, axis in ((1, 'x'), (2, 'y'), (4, 'z')) if axis in values)
            out += bytes([(code & 0xF8) | mask])
            for axis in 'xyz':
                if axis in values:
                    out += struct.pack('>f', values[axis])
        elif 0xC0 <= code < 0xE0:
            count, channels = arguments
            mask = sum(bit for bit, channel in ((1, 'r'), (2, 'g'), (4, 'b'), (8, 'a')) if channel in channels)
            out += bytes([(code & 0xF0) | mask]) + _write_count(count)
            out += bytes(channels[channel] for channel in 'rgba' if channel in channels)
        elif code == 0xE9:
            flags, timing, deltas = arguments
            out += bytes([code, flags, timing]) + struct.pack(f'>{len(deltas)}b', *deltas)
        elif code in (0xEA, 0xEB):
            count, flags, colour, alpha = arguments
            out += bytes([code]) + _write_count(count) + bytes([flags])
            if flags & 1:
                out += bytes([colour])
            if flags & 8:
                out += bytes([alpha])
        else:
            layout = FIXED[code]
            if len(layout) != len(arguments):
                raise ValueError(f'command {code:#x} takes {len(layout)} arguments, not {len(arguments)}')
            out += bytes([code])
            for letter, value in zip(layout, arguments):
                out += _write_count(value) if letter == 'e' else struct.pack('>' + letter, value)
    return bytes(out)


def waits(commands):
    """The frames a command list waits in all (it must be at least the particle's life, or the particle ends early)."""
    return sum(arguments[0] for code, arguments in commands if code in (WAIT, PICTURE))


# ------------------------------------------------------------------------------------------------------------
# a generator and the particle bank
# ------------------------------------------------------------------------------------------------------------

HEADER = '>HHHHI12f'                # a generator's first 0x3C bytes; its commands follow
HEADER_BYTES = struct.calcsize(HEADER)
DISC = 0                            # the shape of the space particles start in (the only one written here)
# flags of a generator's `kind`
GRAVITY, FRICTION, PRIM_ENV, IMMEDIATE, ADDITIVE = 0x1, 0x2, 0x80, 0x100, 0x400000
BANK_VERSION = 0x42                 # the game takes 0x40 to 0x43 and stops on anything else


def generator(commands, *, tex_group=0, gen_life=1, life=1, kind=0, gravity=0.0, friction=1.0,
              velocity=(0.0, 0.0, 0.0), radius=0.0, angle=0.0, random=-1.0, size=1.0, shape=DISC,
              params=(0.0, 0.0, 0.0)):
    """One generator: its header and its particles' commands (a list for `encode_commands`, or bytes).

    gen_life: frames it gives particles off for (0: until it is removed). life: a particle's frames.
    random: below 0, that many particles a frame (fractions carry over); above, up to that many, at random.
    velocity: the way and the speed particles leave at. angle: how far, in radians, a particle's way may lean from
    it. size: half the width of the square. gravity is taken off the upward speed each frame, and the speed is
    multiplied by friction each frame, only when `kind` has GRAVITY and FRICTION."""
    if not 0 <= gen_life <= 0xFFFF or not 0 <= life <= 0xFFFF:
        raise ValueError('a generator and a particle live at most 65535 frames')
    body = bytes(commands) if isinstance(commands, (bytes, bytearray)) else encode_commands(commands)
    return struct.pack(HEADER, shape, tex_group, gen_life, life, kind, gravity, friction, *velocity, radius, angle,
                       random, size, *params) + body


def read_generator(data, at=0):
    """A generator's numbers and commands, from its block: the other way of `generator`. `length` is how many
    bytes it takes, to the end of its commands."""
    shape, tex_group, gen_life, life, kind, gravity, friction, vx, vy, vz, radius, angle, random, size, p1, p2, p3 = \
        struct.unpack_from(HEADER, data, at)
    commands, end = decode_commands(data, at + HEADER_BYTES)
    return dict(shape=shape, tex_group=tex_group, gen_life=gen_life, life=life, kind=kind, gravity=gravity,
                friction=friction, velocity=(vx, vy, vz), radius=radius, angle=angle, random=random, size=size,
                params=(p1, p2, p3), commands=commands, length=end - at)


def _align(value, to):
    return -(-value // to) * to


def particle_bank(generators, bank=0):
    """The particle bank: a version, how many generators, where each starts, then the generators (bytes from
    `generator`; None leaves a number empty, which a script must never play). Under m-ex the game numbers a
    bank's generators from its own slot, so the first number written here (0) is not used."""
    head = 12 + 4 * len(generators)
    at, offsets, body = _align(head, 8), [], bytearray()
    for block in generators:
        if block is None:
            offsets.append(0)
            continue
        offsets.append(at)
        body += block + bytes(_align(len(block), 8) - len(block))
        at += _align(len(block), 8)
    out = struct.pack('>HHii', BANK_VERSION, bank, 0, len(generators)) + struct.pack(f'>{len(offsets)}i', *offsets)
    return out + bytes(_align(head, 8) - head) + bytes(body)


def read_particle_bank(data):
    """The generators of a particle bank, each as its own bytes (to the end of its commands), None for an empty
    number: the other way of `particle_bank`."""
    version, _bank, _first, count = struct.unpack_from('>HHii', data, 0)
    if not 0x40 <= version <= 0x43:
        raise ValueError(f'not a particle bank the game takes (version {version:#x})')
    out = []
    for offset in struct.unpack_from(f'>{count}i', data, 12):
        if not offset:
            out.append(None)
            continue
        out.append(bytes(data[offset:offset + read_generator(data, offset)['length']]))
    return out


# ------------------------------------------------------------------------------------------------------------
# pictures and the texture bank
# ------------------------------------------------------------------------------------------------------------

I8, IA8, RGB5A3 = 1, 3, 5           # the game's numbers for the formats written here
FORMAT_NAMES = {0: 'I4', I8: 'I8', 2: 'IA4', IA8: 'IA8', 4: 'RGB565', RGB5A3: 'RGB5A3', 6: 'RGBA8', 8: 'C4', 9: 'C8',
                10: 'C14X2', 14: 'CMPR'}
# format -> (block width, block height, bytes a block); a picture is stored block by block
BLOCKS = {0: (8, 8, 32), 1: (8, 4, 32), 2: (8, 4, 32), 3: (4, 4, 32), 4: (4, 4, 32), 5: (4, 4, 32), 6: (4, 4, 64),
          8: (8, 8, 32), 9: (8, 4, 32), 10: (4, 4, 32), 14: (8, 8, 32)}
PALETTED = (8, 9, 10)
GROUP_HEAD = 0x18                   # a texture group's own numbers, before its list of pictures


def image_bytes(fmt, width, height):
    """How many bytes one picture of this format and size takes."""
    bw, bh, size = BLOCKS[fmt]
    return (-(-width // bw)) * (-(-height // bh)) * size


def _to_blocks(pixels, bw, bh):
    """Rows of pixels (height, width, bytes a pixel) in the order the console stores them: block by block."""
    height, width, depth = pixels.shape
    padded = np.zeros((_align(height, bh), _align(width, bw), depth), dtype=np.uint8)
    padded[:height, :width] = pixels
    rows, columns = padded.shape[0] // bh, padded.shape[1] // bw
    return padded.reshape(rows, bh, columns, bw, depth).transpose(0, 2, 1, 3, 4).tobytes()


def _from_blocks(data, width, height, bw, bh, depth):
    rows, columns = -(-height // bh), -(-width // bw)
    blocks = np.frombuffer(bytes(data[:rows * columns * bw * bh * depth]), dtype=np.uint8)
    pixels = blocks.reshape(rows, columns, bh, bw, depth).transpose(0, 2, 1, 3, 4).reshape(rows * bh, columns * bw, depth)
    return pixels[:height, :width]


def encode_image(image, fmt):
    """An RGBA picture (PIL) as the console stores it. I8 keeps the red channel alone (the console reads it back
    as both brightness and alpha), IA8 red and alpha, RGB5A3 colour with either 5 bits a channel (alpha of 224
    and up, stored as opaque) or 4 bits a channel and 3 of alpha."""
    pixels = np.asarray(image.convert('RGBA'), dtype=np.uint8)
    if fmt == I8:
        return _to_blocks(pixels[..., 0:1], 8, 4)
    if fmt == IA8:
        return _to_blocks(pixels[..., [3, 0]], 4, 4)
    if fmt == RGB5A3:
        r, g, b, a = (pixels[..., i].astype(np.uint16) for i in range(4))
        solid = 0x8000 | ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)
        clear = ((a >> 5) << 12) | ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4)
        words = np.where(a >= 224, solid, clear).astype(np.uint16)
        return _to_blocks(np.stack([(words >> 8).astype(np.uint8), (words & 0xFF).astype(np.uint8)], axis=-1), 4, 4)
    raise ValueError(f'picture format {FORMAT_NAMES.get(fmt, fmt)} is not written here')


def decode_image(data, fmt, width, height):
    """A stored picture as an RGBA picture (PIL): the other way of `encode_image`, as the console shows it."""
    from PIL import Image
    if fmt == I8:
        grey = _from_blocks(data, width, height, 8, 4, 1)[..., 0]
        rgba = np.stack([grey, grey, grey, grey], axis=-1)
    elif fmt == IA8:
        both = _from_blocks(data, width, height, 4, 4, 2)
        rgba = np.stack([both[..., 1], both[..., 1], both[..., 1], both[..., 0]], axis=-1)
    elif fmt == RGB5A3:
        both = _from_blocks(data, width, height, 4, 4, 2).astype(np.uint16)
        words = (both[..., 0] << 8) | both[..., 1]
        solid = words & 0x8000 != 0
        five = lambda v: (v << 3) | (v >> 2)
        four = lambda v: (v << 4) | v
        three = lambda v: (v << 5) | (v << 2) | (v >> 1)
        r = np.where(solid, five((words >> 10) & 31), four((words >> 8) & 15))
        g = np.where(solid, five((words >> 5) & 31), four((words >> 4) & 15))
        b = np.where(solid, five(words & 31), four(words & 15))
        a = np.where(solid, 255, three((words >> 12) & 7))
        rgba = np.stack([r, g, b, a], axis=-1)
    else:
        raise ValueError(f'picture format {FORMAT_NAMES.get(fmt, fmt)} is not read here')
    return Image.fromarray(np.ascontiguousarray(rgba).astype(np.uint8))


def texture_bank(groups):
    """The texture bank: how many groups, where each starts, then each group (how many pictures, their format
    and size, where each is) with its pictures after it. A generator names a group and its commands pick a picture
    of it by number. groups: [{'format', 'width', 'height', 'images': [bytes]}], no palettes.

    Every picture starts on a multiple of 32 bytes from the start of the bank, so the bank itself must be put on
    a multiple of 32 in the file (`effect_file` does): the console needs picture data so in memory."""
    at = _align(4 + 4 * len(groups), 32)
    starts, parts = [], []
    for group in groups:
        fmt, images = group['format'], group['images']
        if fmt in PALETTED:
            raise ValueError('pictures with a palette are not written here')
        size = image_bytes(fmt, group['width'], group['height'])
        if not images or any(len(image) != size for image in images):
            raise ValueError(f'a group needs pictures of {size} bytes each for its format and size')
        starts.append(at)
        head = GROUP_HEAD + 4 * len(images)
        first = at + _align(head, 32)
        offsets = [first + i * _align(size, 32) for i in range(len(images))]
        block = struct.pack('>5IHH', len(images), fmt, 0, group['width'], group['height'], 0, 0)
        block += struct.pack(f'>{len(offsets)}I', *offsets)
        block += bytes(_align(head, 32) - head)
        for image in images:
            block += image + bytes(_align(size, 32) - size)
        parts.append(block)
        at += len(block)
    head = struct.pack('>I', len(groups)) + struct.pack(f'>{len(starts)}I', *starts)
    return head + bytes(_align(len(head), 32) - len(head)) + b''.join(parts)


def read_texture_bank(data):
    """The groups of a texture bank, [{'format', 'width', 'height', 'images': [bytes], 'offsets': where each
    picture is from the start of the bank}]: the other way of `texture_bank`. Palettes are not read."""
    count, = struct.unpack_from('>I', data, 0)
    out = []
    for start in struct.unpack_from(f'>{count}I', data, 4):
        number, fmt, _tlut, width, height, _palnum, _palflag = struct.unpack_from('>5IHH', data, start)
        if fmt not in BLOCKS:
            raise ValueError(f'a texture group has a format the game does not take ({fmt})')
        offsets = list(struct.unpack_from(f'>{number}I', data, start + GROUP_HEAD))
        size = image_bytes(fmt, width, height)
        out.append(dict(format=fmt, width=width, height=height, offsets=offsets,
                        images=[bytes(data[o:o + size]) for o in offsets]))
    return out


# ------------------------------------------------------------------------------------------------------------
# the effect file
# ------------------------------------------------------------------------------------------------------------

BEHAVIOURS = 'effBehaviorTable'     # m-ex looks this root up by name
FILE_HEAD = 0x20
TABLE_AT, LOOKUP_AT, BYTES_AT = 0x00, 0x10, 0x20     # where the two roots and the behaviour bytes sit in the data


def effect_file(symbol, generators, behaviours, groups):
    """A fighter's own effect file: a DAT whose root `symbol` points at the particle bank and the texture bank
    (no models), and whose root `effBehaviorTable` holds one byte a generator: how a script places it.

    generators: bytes from `generator`. behaviours: one number each (see the module's note). groups: as
    `texture_bank` takes. The game fixes up the addresses inside the two banks itself, so the file's own list
    of addresses names only the three outside them; the texture bank sits on a multiple of 32 bytes."""
    if len(generators) != len(behaviours):
        raise ValueError('one behaviour a generator')
    if not generators or not groups:
        raise ValueError('the game needs both banks: at least one generator and one texture group')
    if len(generators) > MOST_GENERATORS:
        raise ValueError(f'a script can name {MOST_GENERATORS} generators of a file, not {len(generators)}')
    if any(block is None for block in generators):
        raise ValueError('an empty generator number is not written: a script that played it would crash')
    for number, (block, behaviour) in enumerate(zip(generators, behaviours)):
        if not 0 <= behaviour <= 7:
            raise ValueError(f'generator {number}: there is no behaviour {behaviour} (0 to 7)')
        # the game checks neither the group a generator names nor the picture a command names
        got = read_generator(block)
        if got['tex_group'] >= len(groups):
            raise ValueError(f"generator {number} names texture group {got['tex_group']} of {len(groups)}")
        images = len(groups[got['tex_group']]['images'])
        for code, arguments in got['commands']:
            last = (arguments[1] if code == PICTURE else
                    arguments[0] + max(arguments[1] - 1, 0) if code == RANDOM_PICTURE else 0)
            if last >= images:
                raise ValueError(f'generator {number} shows picture {last} of a group that holds {images}')
    particles, textures = particle_bank(generators), texture_bank(groups)
    particles_at = _align(BYTES_AT + len(behaviours), 32)
    textures_at = _align(particles_at + len(particles), 32)
    data = bytearray(_align(textures_at + len(textures), 4))
    struct.pack_into('>II', data, TABLE_AT, particles_at, textures_at)
    struct.pack_into('>iIiI', data, LOOKUP_AT, 0, 0, len(behaviours), BYTES_AT)
    data[BYTES_AT:BYTES_AT + len(behaviours)] = bytes(behaviours)
    data[particles_at:particles_at + len(particles)] = particles
    data[textures_at:textures_at + len(textures)] = textures
    relocations = [TABLE_AT, TABLE_AT + 4, LOOKUP_AT + 12]
    names = symbol.encode('ascii') + b'\0' + BEHAVIOURS.encode('ascii') + b'\0'
    roots = struct.pack('>IIII', TABLE_AT, 0, LOOKUP_AT, len(symbol) + 1)
    tail = struct.pack(f'>{len(relocations)}I', *relocations) + roots + names
    head = struct.pack('>5I', FILE_HEAD + len(data) + len(tail), len(data), len(relocations), 2, 0) + bytes(12)
    return head + bytes(data) + tail


def read_dat(data):
    """A DAT's parts: {'data': its data section, 'relocations': [where an address sits], 'roots': {name: where}}."""
    size, data_size, relocations, roots, references = struct.unpack_from('>5I', data, 0)
    if size != len(data):
        raise ValueError(f'the file says it is {size} bytes long and is {len(data)}')
    at = FILE_HEAD + data_size
    where = list(struct.unpack_from(f'>{relocations}I', data, at))
    at += 4 * relocations
    rows = [struct.unpack_from('>II', data, at + 8 * i) for i in range(roots)]
    text = at + 8 * (roots + references)
    named = {}
    for offset, name_at in rows:
        end = data.index(b'\0', text + name_at)
        named[data[text + name_at:end].decode('ascii')] = offset
    return dict(data=bytes(data[FILE_HEAD:FILE_HEAD + data_size]), relocations=where, roots=named)


def read_effect_file(data):
    """An effect file's parts: {'symbol', 'generators': [bytes, or None for an empty number], 'behaviours': [one
    number a generator], 'groups' (as `read_texture_bank` gives), 'models': how many models its table holds,
    'model_behaviours', 'particles_at', 'textures_at': where the two banks start in the data section}.
    The other way of `effect_file`. It also reads a vanilla fighter's file (Marth's EfMsData.dat): that has no
    `effBehaviorTable`, so both lists of behaviours are None, and its models are counted and not read."""
    dat = read_dat(data)
    body, roots = dat['data'], dat['roots']
    symbol = next((name for name in roots if name != BEHAVIOURS), None)
    if symbol is None:
        raise ValueError('this file has no effect table')
    table = roots[symbol]
    particles_at, textures_at = struct.unpack_from('>II', body, table)
    if BEHAVIOURS in roots:
        models, model_bytes, count, own_bytes = struct.unpack_from('>iIiI', body, roots[BEHAVIOURS])
        model_behaviours, behaviours = list(body[model_bytes:model_bytes + models]), list(body[own_bytes:own_bytes + count])
    else:
        # a vanilla file: its table runs to the first thing any address in the file points at, 0x14 bytes a model
        targets = [struct.unpack_from('>I', body, where)[0] for where in dat['relocations']]
        end = min([t for t in targets if t > table] + [len(body)])
        models, model_behaviours, behaviours = (end - table - 8) // 0x14, None, None
    out = dict(symbol=symbol, models=models, model_behaviours=model_behaviours, behaviours=behaviours,
               particles_at=particles_at, textures_at=textures_at, generators=[], groups=[])
    if particles_at and textures_at:
        out['generators'] = read_particle_bank(body[particles_at:])
        out['groups'] = read_texture_bank(body[textures_at:])
    return out


# ------------------------------------------------------------------------------------------------------------
# one Ultimate emitter -> one Melee generator
# ------------------------------------------------------------------------------------------------------------

def _track(keys, life):
    """Keys with times of 0 to 1 over a life as [(frame, value as an array)], one a frame (the later key wins)."""
    out = {}
    for key in keys:
        frame = int(round(min(max(float(key['time']), 0.0), 1.0) * life))
        out[frame] = np.atleast_1d(np.asarray(key['value'], dtype=float))
    return sorted(out.items(), key=lambda item: item[0])


def _value(track, frame):
    """A track's value on a frame: a straight line between keys, held before the first and after the last."""
    if frame <= track[0][0]:
        return track[0][1]
    for (a, va), (b, vb) in zip(track, track[1:]):
        if frame <= b:
            return va + (vb - va) * ((frame - a) / (b - a))
    return track[-1][1]


def _key_at(keys, time):
    """A key track's value (a number or a tuple) at a time of the life (0 to 1): a straight line between its keys."""
    track = sorted(((float(k['time']), np.asarray(k['value'], dtype=float)) for k in keys), key=lambda t: t[0])
    value = _value(track, float(time))
    return float(value) if np.ndim(value) == 0 else tuple(float(v) for v in value)


def _byte(value):
    return int(min(max(round(float(value) * 255.0), 0), 255))


def _in_use(keys, default):
    """Whether a key table holds more than the one default key (used when the emitter's track modes are not given)."""
    return len(keys) > 1 or any(not np.allclose(np.atleast_1d(k['value']), default, atol=1e-6) for k in keys)


def _wait(frames):
    out = []
    while frames > 0:
        step = min(frames, MAX_WAIT)
        out.append((WAIT, [step]))
        frames -= step
    return out


MOST_THIN = 16.0                    # a streak's picture is no thinner than one part in this many of its length
TOWARD_CAMERA = 0.9                 # a streak whose length lies this much along the camera's line shows as a dot


def streak(emitter):
    """An emitter whose particle is much longer one way than the other, at the middle of its life (LONG_SIZE):
    (how many times longer, capped at MOST_THIN; which of its own axes is the long one, 'x' or 'y'), else None."""
    keys = emitter['size_keys'] or [dict(time=0.0, value=(1.0, 1.0, 1.0))]
    track = _track([dict(time=key['time'], value=(key['value'][0], key['value'][1])) for key in keys],
                   max(1, int(round(emitter['life']))))
    kx, ky = (float(v) for v in _value(track, max(1, int(round(emitter['life']))) / 2.0)[:2])
    w, h = abs(float(emitter['size'][0]) * kx), abs(float(emitter['size'][1]) * ky)
    if max(w, h) <= LONG_SIZE * max(min(w, h), 1e-9):
        return None
    return min(MOST_THIN, max(w, h) / max(min(w, h), 1e-9)), 'y' if h >= w else 'x'


def _turned(vector, turn):
    """A vector turned about x, then y, then z (radians). READING: the order the game turns in is not known; the
    streaks met so far are turned about one axis only, where it makes no difference."""
    x, y, z = (float(v) for v in vector)
    rx, ry, rz = (float(v) for v in turn)
    y, z = y * math.cos(rx) - z * math.sin(rx), y * math.sin(rx) + z * math.cos(rx)
    x, z = x * math.cos(ry) + z * math.sin(ry), -x * math.sin(ry) + z * math.cos(ry)
    x, y = x * math.cos(rz) - y * math.sin(rz), x * math.sin(rz) + y * math.cos(rz)
    return x, y, z


def streak_turn(emitter, along, call_turn=(0.0, 0.0, 0.0)):
    """Where a streak points on Melee's screen: the turn (radians, from upright) that lays a picture's upright
    axis along it, or None when it points at the camera. The streak's long axis is turned by the emitter's own
    turn, then by the script call's (degrees); in the effect's space z is ahead and y up, and Melee looks at a
    fighter from the side, so ahead is across the screen and up is up."""
    axis = (0.0, 1.0, 0.0) if along == 'y' else (1.0, 0.0, 0.0)
    d = _turned(_turned(axis, emitter['turn']), [math.radians(float(v)) for v in call_turn])
    if abs(d[0]) > TOWARD_CAMERA:
        return None
    return math.atan2(d[2], d[1])


def convert(emitter, scale=1.0, size=1.0, *, tex_group=0, images=0, offset=(0.0, 0.0, 0.0), modes=None, mirror='none',
            long=None, turn=(0.0, 0.0, 0.0),
            emission=None, held=False, along_speed=False, joint_turned=False, lasting=0):
    """One Ultimate emitter as one Melee generator.

    emitter: the dict `echo_ultimate.effects.emitter` gives. scale: Ultimate units to Melee units. size: the size
    the script call gives. tex_group and images: the texture group that holds the emitter's first picture cut into
    its frames, and how many frames that is (0: no picture, the particle is a plain coloured square). offset: for
    a generator held by the joint, where its particles start from the joint, in Melee units in the effect's own
    space (x to the side, y up, z ahead); the game does not use the script command's offset for those. modes: the
    dict `echo_ultimate.effects.track_modes` gives (which of the colour and alpha tracks are live); without it a
    track is taken as keyed when it has keys. mirror: what `echo_ultimate.effects.mirror` gives ('both': the
    picture is a quarter of a whole, drawn mirrored across and down, which Melee does with command B1). emission:
    the dict `echo_ultimate.effects.emission` gives (the frames skipped between givings-off); without it none are.
    turn: the script call's turn (degrees): it turns the way particles fly, the pull (PULL_TURNS) and a streak's
    lay. held: the script call makes the effect follow its bone (EFFECT_FOLLOW...): the generator is held by the
    joint even when the emitter is one-time (which keeps its end). along_speed: the picture's upright axis is laid
    along the particle's speed on the screen (command E6) whenever it has one (a flattened shape whose emitter lays
    it along its speed: `Plan`). joint_turned: held by the joint and given off turned as the joint is turned
    (TURNED_BEHAVIOUR): its speed, and so its lay, is in the joint's own space. lasting: a steady emitter's generator
    gives off for this many frames and ends, instead of having no end (0): for an effect a fighter's code keeps up
    by giving it again while it lasts (a mode's aura), which then never outlives the mode, and whose generator no
    change of state is needed to end.

    -> {'generator': bytes, 'behaviour': how a script places it, 'delay': frames after the script call it starts,
        'steady': whether it has no end (held by the joint), 'held': whether the joint holds it, 'commands',
        'header': the header's numbers, 'dropped': what the emitter has that is not carried, 'notes': what was
        approximated}

    The rules, in the order the header and the commands are made:
    - one-time: it gives off `rate` particles, skips its interval, and gives off again, for `emit_frames` frames;
      here the same number of particles evenly over those frames (with no interval: `rate` a frame for
      `emit_frames` frames, exactly), then it ends. Not one-time: with no end, `rate` for each (interval + 1)
      frames, evenly. Both give their first particle at once. (See INTERVAL_APPLIES for the other reading.)
    - speed: the directed speed times the direction, as written, with the spread angle; or, when the
      all-direction speed is the larger, that speed over every direction. Either is turned by the call's turn.
      A random speed of r per cent: each particle's speed is set between (1 - r/100) and 1 times it (command BD,
      which sets a speed, not a share of one).
    - gravity pulls down when the emitter's pull (turned by the call's turn: PULL_TURNS) points down (-y), up when
      it points up; drag multiplies the speed each frame.
    - life, and a random life of r per cent as a life between (1 - r/100) and 1 times it (command A6).
    - the picture: frame 0, a random one of the first `frames_random`, or its frame table stepped through. Its
      command is the first of the list.
    - colour and alpha: the keys of both tracks on one timeline of prim colour commands, each fading to the next
      key; a track that is not keyed gives the fixed colour. See DISSOLVE for an emitter with two alpha tracks.
    - size: half the mean of the size's x and y, times the size keys (the mean of each key's x and y).
    - the turn about the axis toward the camera: the start turn and its random part (command ED), the spin as
      one even turn over the life (command B6). A streak that flies along its length is laid by its speed
      (command E6, see LAY_ALONG_SPEED), any other streak at the fixed turn `streak_turn` gives.
    - where particles start: an offset (generators held by the joint), then a random place in a box of the
      emitter's radius (command A8) for any shape but a point.
    The commands end with waits up to the life, then the end command."""
    dropped, notes = [], []
    k = float(scale) * float(size)
    life = max(1, min(int(emitter['life']), 0xFFFF))
    modes = modes or {}
    first, events = [], {}

    # how it gives particles off
    steady = not emitter['one_time']
    rate, emit_frames = float(emitter['rate']), max(1, int(emitter['emit_frames']))
    if rate <= 0:
        raise ValueError(f"emitter {emitter.get('name')!r} gives off no particles")
    skipped = dict(emission or {}) if INTERVAL_APPLIES else {}
    # frames from one giving-off to the next, on average
    every = 1.0 + max(0, int(skipped.get('interval', 0))) + max(0, int(skipped.get('interval_random', 0))) / 2.0
    if steady and INTERVAL_APPLIES:
        random, gen_life = -(rate / every), 0
        if every > 1:
            notes.append(f'gives off evenly, {-random:.3g} a frame, where the game gives off {rate:g} every {every:g} frames')
    elif steady:
        loop = max(int(emitter['loop']), emit_frames)
        random, gen_life = -(rate * emit_frames / loop), 0
        if loop > emit_frames:
            notes.append(f'gives off evenly, {-random:.3g} a frame, where the game gives off {rate:g} a frame for '
                         f'{emit_frames} of every {loop} frames')
    else:
        times = max(1, math.ceil(emit_frames / every))          # how many times it gives off
        gen_life = 1 if times == 1 else int(round((times - 1) * every)) + 1
        gen_life = min(gen_life, 0xFFFF)
        if gen_life == 1 or (every == 1 and rate >= 1):
            random = -rate
        else:
            # under one a frame the game gives the first at once (the flag below), so the rest are spread over the
            # frames; a little is added so that rounding does not lose the last particle
            total = rate * times
            random = -(max(total - (1.0 if total < gen_life else 0.0), 0.0) + 0.01) / gen_life
        if every > 1 and times > 1:
            notes.append(f'gives off evenly, {rate * times:g} particles in {gen_life} frames, where the game gives off '
                         f'{rate:g} every {every:g} frames')
    if steady and lasting:
        gen_life = max(1, min(int(lasting), 0xFFFF))
        notes.append(f'gives off for {gen_life} frames and ends (the code gives it again while it lasts), where the '
                     'game gives off until it is removed')
    held = bool(steady or held or joint_turned)
    behaviour = TURNED_BEHAVIOUR if joint_turned else STEADY_BEHAVIOUR if held else BURST_BEHAVIOUR
    kind = IMMEDIATE | (ADDITIVE if emitter['blend'] == 'add' else 0)
    call_turn = [math.radians(float(t)) for t in turn]

    # speed and spread
    direction = np.asarray(emitter['direction'], dtype=float)
    length = float(np.linalg.norm(direction))
    if DIRECTION_IS_UNIT and length > 1e-9:
        direction = direction / length
    along, around = float(emitter['speed_along']), float(emitter['speed'])
    if around > along:
        speed, angle = around, ALL_DIRECTIONS
        if along > 0:
            dropped.append(f'a directed speed of {along:g} beside a larger all-direction speed of {around:g}')
        if length <= 1e-9:
            direction = np.array([0.0, 1.0, 0.0])
        way = direction / max(float(np.linalg.norm(direction)), 1e-9)
    else:
        speed, angle = along, math.radians(float(emitter['spread_degrees']))
        if around > 0:
            dropped.append(f'an all-direction speed of {around:g} beside the directed speed of {along:g}')
        way = direction
    way = np.asarray(_turned(way, call_turn))
    velocity = way * speed * k
    reach = float(np.linalg.norm(velocity))
    if reach <= 1e-9:
        velocity, angle = np.zeros(3), 0.0

    # a streak that flies along its own length is laid by its speed (LAY_ALONG_SPEED): its lay is the turn from
    # the way it flies to its picture's long axis (0 or a half turn along y, a quarter turn along x)
    by_speed = None
    if LAY_ALONG_SPEED and long and along >= around and reach > 1e-9:
        axis = (0.0, 1.0, 0.0) if long[1] == 'y' else (1.0, 0.0, 0.0)
        d = np.asarray(_turned(_turned(axis, emitter['turn']), call_turn))
        cos = float(np.dot(d, velocity)) / max(float(np.linalg.norm(d)) * reach, 1e-9)
        if abs(cos) >= math.cos(math.radians(ALONG_DEGREES)):
            if long[1] == 'y':
                by_speed = 0.0 if cos > 0 else math.pi
            else:
                by_speed = math.pi / 2.0 if cos > 0 else -math.pi / 2.0
            if reach < LEAST_SPEED:
                velocity, reach = velocity * (LEAST_SPEED / reach), LEAST_SPEED
                notes.append(f'flies at {LEAST_SPEED:g} a frame at least, so that the game lays it by its speed')
    elif along_speed and reach > 1e-9:
        by_speed = 0.0
        if reach < LEAST_SPEED:
            velocity, reach = velocity * (LEAST_SPEED / reach), LEAST_SPEED
            notes.append(f'flies at {LEAST_SPEED:g} a frame at least, so that the game lays it by its speed')

    # gravity and drag
    pull = np.asarray(emitter['gravity_direction'], dtype=float)
    if PULL_TURNS:
        pull = np.asarray(_turned(pull, call_turn))
    gravity = float(emitter['gravity']) * -float(pull[1]) * k
    if abs(gravity) > 1e-9:
        kind |= GRAVITY
    else:
        gravity = 0.0
    if abs(float(emitter['gravity'])) > 1e-9 and (abs(pull[0]) > 1e-6 or abs(pull[2]) > 1e-6):
        dropped.append(f'a pull to the side ({pull[0]:.3g}, {pull[1]:.3g}, {pull[2]:.3g}'
                       + (', as the call turns it' if PULL_TURNS and any(abs(t) > 1e-9 for t in call_turn) else '')
                       + '): only its up and down part is carried')
    friction = float(emitter['drag'])
    if abs(friction - 1.0) > 1e-9:
        kind |= FRICTION
    else:
        friction = 1.0

    # life
    spread = float(emitter['life_random'])
    if spread > 0:
        least = max(1, int(round(life * (1.0 - min(spread, 100.0) / 100.0))))
        if least < life:
            # the command counts the frame it runs on, as a new particle's own life does
            first.append((LIFE, [least + 1, life - least + 1]))
            notes.append(f'lives {least} to {life} frames; its keys are laid out over {life}')

    # the picture
    if images:
        mode = emitter['frames']
        table = [min(max(int(t), 0), images - 1) for t in emitter['frame_table']]
        choices = min(int(emitter['frames_random']), images)
        if mode == 'random' and choices > 1:
            first.append((RANDOM_PICTURE, [0, choices]))
        elif mode == 'over_life' and len(table) > 1:
            # a table longer than the life puts several steps on a frame: the last of them is shown
            steps = {int(round(i * life / len(table))): pose for i, pose in enumerate(table)}
            for frame, pose in sorted(steps.items()):
                events.setdefault(frame, []).append((PICTURE, [0, pose]))
        elif mode in ('once', 'loop') and len(table) > 1:
            last = None
            for frame in range(0, life, TABLE_STEP_FRAMES):
                step = frame // TABLE_STEP_FRAMES
                pose = table[step % len(table)] if mode == 'loop' else table[min(step, len(table) - 1)]
                if pose != last:
                    events.setdefault(frame, []).append((PICTURE, [0, pose]))
                    last = pose
        else:
            if mode not in ('one', 'random', 'over_life', 'once', 'loop'):
                notes.append(f'its way through the frames of its picture ({mode}) is not known: frame 0 is shown')
            first.append((PICTURE, [0, table[0] if table and mode in ('over_life', 'once', 'loop') else 0]))
        if mirror == 'both':
            first.append((MIRROR_BOTH, []))
        elif mirror != 'none':
            dropped.append(f'its picture is repeated or mirrored in a way that is not known (mode {mirror}): drawn once')
    else:
        notes.append('no picture: a plain coloured square')
    if len(emitter['textures']) > 1:
        dropped.append(f"{len(emitter['textures']) - 1} more picture(s) beside the first")

    # colour and alpha
    def live(name, keys, default):
        mode = modes.get(name)
        if mode is None:
            mode = 'keys' if keys and (name in ('colour', 'alpha') or _in_use(keys, default)) else 'fixed'
        elif mode not in ('fixed', 'keys', 'random'):
            notes.append(f'its {name} track is driven in a way that is not known (mode {mode}): the fixed value is used')
        return mode if keys else 'fixed'

    fixed = [float(c) for c in emitter['colour']]
    colour_mode = live('colour', emitter['colour_keys'], 1.0)
    if colour_mode == 'keys':
        colour = _track(emitter['colour_keys'], life)
    elif colour_mode == 'random':
        colour = [(0, np.mean([k_['value'] for k_ in emitter['colour_keys']], axis=0))]
        dropped.append(f"each particle takes one of {len(emitter['colour_keys'])} colours: all take their mean")
    else:
        colour = [(0, np.asarray(fixed[:3]))]
    alpha_mode = live('alpha', emitter['alpha_keys'], 1.0)
    alpha_keyed = alpha_mode == 'keys'
    if alpha_mode == 'random':
        dropped.append(f"each particle takes one of {len(emitter['alpha_keys'])} alphas: all take the fixed one")
    alpha = _track(emitter['alpha_keys'], life) if alpha_keyed else [(0, np.asarray([fixed[3]]))]
    if live('colour2', emitter.get('colour2_keys') or [], 1.0) != 'fixed':
        dropped.append('the second colour track')
    second = emitter.get('alpha2_keys') or []
    second_keyed = live('alpha2', second, 1.0) == 'keys'
    dissolve = bool(DISSOLVE and second_keyed and alpha_keyed and alpha[-1][1][0] > alpha[0][1][0])
    unseen = bool(UNSEEN_IS_DISSOLVE and not dissolve and alpha_mode == 'fixed' and fixed[3] <= 0.01)
    if second_keyed and not dissolve and not unseen:
        dropped.append('the second alpha track')
    opacity = _track(second, life) if dissolve else None
    if unseen:
        dissolve = True
        opacity = _track(second, life) if second_keyed else [(0, np.asarray([float((emitter.get('colour2') or (1.0,) * 4)[3])]))]
        notes.append('a fixed alpha of 0 (a particle that is never seen): read as a dissolve with nothing eaten, its '
                     'second alpha as its see-through-ness (see UNSEEN_IS_DISSOLVE)')

    def tint(frame):
        r, g, b = (_byte(c) for c in _value(colour, frame))
        if not dissolve:
            return (r, g, b, _byte(_value(alpha, frame)[0])), None
        eaten = min(max(float(_value(alpha, frame)[0]), 0.0), 1.0)
        shown = min(max((1.0 - eaten) * float(_value(opacity, frame)[0]), 0.0), 1.0)
        # the test is on what is drawn (picture alpha times prim alpha), so the threshold is scaled the same way
        # (nothing is eaten from a particle read as unseen: no test)
        return (r, g, b, _byte(shown)), None if unseen else int(min(max(round(eaten * shown * 255.0), 1), 255))

    points = {0} | {f for f, _ in colour} | {f for f, _ in alpha}
    if dissolve:
        points |= {f for f, _ in opacity} | set(range(0, life, DISSOLVE_STEP))
        if not unseen:
            notes.append('two alpha tracks, read as smoke that is eaten away: an alpha test that climbs with the first, '
                         'the second as its see-through-ness (a reading, see DISSOLVE)')
    points = sorted(f for f in points if f <= life)
    now, test = tint(0)
    if now != (255, 255, 255, 255):
        first.append((PRIM, [0, dict(zip('rgba', now))]))
    if test is not None:
        first.append((ALPHA_TEST, [0, ALPHA_AT_LEAST, test, 255]))
    for a, b in zip(points, points[1:]):
        target, target_test = tint(b)
        if a >= life:
            break
        if target != now:
            events.setdefault(a, []).append((PRIM, [b - a, dict(zip('rgba', target))]))
            now = target
        if target_test is not None and target_test != test:
            events.setdefault(a, []).append((ALPHA_TEST, [b - a, ALPHA_AT_LEAST, target_test, 255]))
            test = target_test

    # size. A streak (`long`: how many times longer than wide, and along which axis) is drawn on a square as long
    # as it is, its picture made thin in the square (`texture_group`'s `thin`); its width over its life stays the
    # picture's, since a Melee particle has one size.
    sx, sy = float(emitter['size'][0]), float(emitter['size'][1])
    keys = emitter['size_keys'] or [dict(time=0.0, value=(1.0, 1.0, 1.0))]
    shapes = [(sx * key['value'][0], sy * key['value'][1]) for key in keys]
    if long:
        n = 1 if long[1] == 'y' else 0
        base = SIZE_TO_HALF_WIDTH * (sx, sy)[n] * k
        track = _track([dict(time=key['time'], value=key['value'][n]) for key in keys], life)
        notes.append(f'a streak {long[0]:.3g} times longer than wide: its picture is made thin in a square as long '
                     f'as the streak; the width keeps one share of the length through its life')
    else:
        base = SIZE_TO_HALF_WIDTH * (sx + sy) / 2.0 * k
        track = _track([dict(time=key['time'], value=(key['value'][0] + key['value'][1]) / 2.0) for key in keys], life)
        if any(max(w, h) > LONG_SIZE * max(min(w, h), 1e-9) for w, h in shapes):
            w, h = max(shapes, key=lambda s: max(s) / max(min(s), 1e-9))
            dropped.append(f'a size much longer one way than the other ({w * k:.3g} by {h * k:.3g}): drawn as a square')
    start = base * float(_value(track, 0)[0])
    changes = any(abs(float(v[0]) - float(track[0][1][0])) > 1e-6 for _, v in track)
    vary = (float(emitter['size_random'][0]) + float(emitter['size_random'][1])) / 2.0
    if vary > 0 and not changes:
        vary = min(vary, 100.0) / 100.0
        first.append((SIZE_RANDOM, [0, start * (1.0 - vary), start * vary]))
    elif vary > 0:
        dropped.append(f'a size that varies by {vary:g} per cent from particle to particle (its size changes over the life)')
    current = start
    for (a, _), (b, value) in zip(track, track[1:]):
        target = base * float(value[0])
        if a < life and abs(target - current) > 1e-6:
            events.setdefault(a, []).append((SIZE, [b - a, target]))
            current = target

    # the turn about the axis toward the camera. A streak is laid where it points on the screen (`streak_turn`),
    # which takes in its turns about the other axes and the script call's turn.
    if by_speed is not None:
        lay = by_speed
        first.append((ALONG_SPEED, []))
        notes.append('a streak that flies along its length: laid by its speed on the screen (command E6)' if long
                     else 'laid along its speed on the screen (command E6), as its emitter lays its shape')
    else:
        lay = streak_turn(emitter, long[1], turn) if long else None
        if long and lay is None:
            dropped.append('a streak that points at the camera: drawn upright')
    start_turn, turn_more = (lay if lay is not None else float(emitter['turn'][2])), float(emitter['turn_random'][2])
    if abs(start_turn) > 1e-6 or abs(turn_more) > 1e-6:
        # (the lay by speed is in Melee's own sense of a turn, not Ultimate's)
        first.append((RANDOM_TURN, [(1.0 if by_speed is not None else ROTATE_SIGN) * start_turn,
                                    ROTATE_SIGN * turn_more, 0]))
    spin, keep = float(emitter['spin'][2]), float(emitter['spin_keep'])
    if SPIN_KEEP_APPLIES and 0.0 <= keep < 1.0:
        total = spin * (1.0 - keep ** life) / (1.0 - keep)
    else:
        total = spin * life
    if abs(total) > 1e-6:
        first.append((SPIN, [min(life, MAX_COUNT), ROTATE_SIGN * total]))
    if abs(float(emitter['spin_random'][2])) > 1e-6:
        dropped.append('the random part of its spin')
    others = ('turn_random', 'spin', 'spin_random') if lay is not None else ('turn', 'turn_random', 'spin', 'spin_random')
    if any(abs(float(emitter[name][axis])) > 1e-6 for name in others for axis in (0, 1)):
        dropped.append('turns about its x and y axes (a Melee particle only turns about the axis toward the camera)')

    # where particles start
    if held and any(abs(float(o)) > 1e-9 for o in offset):
        first.append((ADD_POSITION, [dict(zip('xyz', (float(o) for o in offset)))]))
    if emitter['shape'] != 'point':
        box = [abs(float(r)) * k for r in emitter['radius']]
        if any(r > 1e-6 for r in box):
            first.append((SCATTER, box))
            notes.append(f"starts in a box of {box[0]:.3g} by {box[1]:.3g} by {box[2]:.3g} each way, where the game has a {emitter['shape']}")
    vary = float(emitter['speed_random'])
    if vary > 0 and reach > 1e-9:
        vary = min(vary, 100.0) / 100.0
        first.append((RANDOM_SPEED, [reach * (1.0 - vary), reach * vary]))

    # the timeline: what runs on the first frame (the picture before the rest), then each later change after a
    # wait, then the end
    commands, at = first + events.pop(0, []), 0
    commands.sort(key=lambda command: command[0] not in (PICTURE, RANDOM_PICTURE, MIRROR_BOTH))
    for frame in sorted(f for f in events if f < life):
        commands += _wait(frame - at)
        commands += events[frame]
        at = frame
    commands += _wait(life - at)
    commands.append((END, []))
    header = dict(tex_group=tex_group, gen_life=gen_life, life=life, kind=kind, gravity=gravity, friction=friction,
                  velocity=tuple(float(v) for v in velocity), radius=0.0, angle=float(angle), random=float(random),
                  size=float(start))
    return dict(generator=generator(commands, **header), behaviour=behaviour, delay=int(emitter['start']), steady=steady,
                held=held, commands=commands, header=header, dropped=dropped, notes=notes)


# ------------------------------------------------------------------------------------------------------------
# an emitter's picture as a texture group
# ------------------------------------------------------------------------------------------------------------

def picture_format(image):
    """The format a picture is stored in: I8 when it is grey and its alpha is its brightness (or it has no alpha
    of its own: see OPAQUE_GREY_IS_MASK), IA8 when it is grey with an alpha of its own, RGB5A3 when it has colour."""
    pixels = np.asarray(image.convert('RGBA')).astype(int)
    seen = pixels[pixels[..., 3] > 0]
    if not len(seen):
        return I8
    spread = seen[:, :3].max(axis=1) - seen[:, :3].min(axis=1)
    if np.mean(spread <= GREY_TOLERANCE) < GREY_SHARE:
        return RGB5A3
    every = pixels.reshape(-1, 4)
    if OPAQUE_GREY_IS_MASK and every[:, 3].min() == 255:
        return I8
    same = np.abs(every[:, 3] - every[:, 0]) <= GREY_TOLERANCE
    return I8 if np.mean(same) >= GREY_SHARE else IA8


def _mask(image):
    """A picture that is to be stored as I8, as the one number the console keeps of each pixel, in all four
    channels' place: its brightness when it has no alpha of its own, else its alpha (which its brightness equals)."""
    from PIL import Image
    red, _, _, alpha = image.convert('RGBA').split()
    one = red if alpha.getextrema()[0] == 255 else alpha
    return Image.merge('RGBA', (one, one, one, Image.new('L', image.size, 255)))


def _side(length, most):
    """The power of two a side of this many pixels is stored at: the largest that is not above it, within limits."""
    side = MIN_SIDE
    while side * 2 <= min(length, most):
        side *= 2
    return side


def _resize(image, width, height):
    """A picture at another size. Colour is weighted by alpha so see-through pixels do not darken the edges."""
    from PIL import Image
    if image.size == (width, height):
        return image
    pixels = np.asarray(image.convert('RGBA')).astype(np.float32) / 255.0
    alpha = pixels[..., 3]
    how = Image.BOX if width <= image.width and height <= image.height else Image.BILINEAR
    small = lambda channel: np.asarray(Image.fromarray(np.ascontiguousarray(channel, dtype=np.float32))
                                       .resize((width, height), how))
    out_alpha = small(alpha)
    channels = [small(pixels[..., i] * alpha) / np.maximum(out_alpha, 1e-6) for i in range(3)]
    out = np.stack(channels + [out_alpha], axis=-1)
    return Image.fromarray((np.clip(out, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8))


def texture_group(image, grid=(1, 1), mirrored=False, max_side=None, group_bytes=None, thin=None):
    """A picture cut into its grid of frames (`grid`: how many across, how many down; frames are numbered along
    each row, top row first), each frame resized to powers of two, as one texture group. A frame is no larger than
    `max_side` (MAX_SIDE) a side, and is halved until the group's frames together take no more than `group_bytes`
    (GROUP_BYTES). (A particle's square is stretched over the frame whatever the frame's own shape, as in Ultimate.)
    mirrored: the picture is a quarter of a whole that Melee is to draw four times (see MIRROR_STORES_FLIPPED).
    thin: (how many times longer than wide, 'x' or 'y') for a streak: each frame is drawn that thin across the
    middle of its square, long along that axis, with nothing either side (a Melee particle is always square)."""
    from PIL import Image
    across, down = max(1, int(grid[0])), max(1, int(grid[1]))
    max_side, group_bytes = max_side or MAX_SIDE, group_bytes or GROUP_BYTES
    fmt = picture_format(image)
    if fmt == I8:
        image = _mask(image)
    width, height = image.width // across, image.height // down
    out_width, out_height = _side(width, max_side), _side(height, max_side)
    while across * down * image_bytes(fmt, out_width, out_height) > group_bytes and max(out_width, out_height) > MIN_SIDE:
        out_width, out_height = max(MIN_SIDE, out_width // 2), max(MIN_SIDE, out_height // 2)
    images = []
    for row in range(down):
        for column in range(across):
            frame = image.crop((column * width, row * height, (column + 1) * width, (row + 1) * height))
            frame = _resize(frame, out_width, out_height)
            if thin:
                ratio, along = thin
                narrow = ((max(2, round(out_width / ratio)), out_height) if along == 'y'
                          else (out_width, max(2, round(out_height / ratio))))
                square = Image.new('RGBA', (out_width, out_height), (0, 0, 0, 255 if fmt == I8 else 0))
                square.paste(_resize(frame, *narrow), ((out_width - narrow[0]) // 2, (out_height - narrow[1]) // 2))
                frame = square
            if mirrored and MIRROR_STORES_FLIPPED:
                frame = frame.transpose(Image.FLIP_TOP_BOTTOM)
            images.append(encode_image(frame, fmt))
    return dict(format=fmt, width=out_width, height=out_height, images=images)


def sheet(groups, labels=None, background=(34, 34, 48), cell=96):
    """Every picture of every group as the console will show it, side by side on a dark background, each row a
    group with its number, format and size and its label (`labels`: {group number: text, of up to four lines}):
    for looking at what a written bank holds."""
    from PIL import Image, ImageDraw
    labels = labels or {}
    most = max((len(group['images']) for group in groups), default=1)
    text = 260
    out = Image.new('RGB', (text + most * (cell + 8) + 8, max(1, len(groups)) * (cell + 8) + 8), background)
    draw = ImageDraw.Draw(out)
    for row, group in enumerate(groups):
        top = 8 + row * (cell + 8)
        label = f"{row}: {FORMAT_NAMES.get(group['format'], group['format'])} {group['width']}x{group['height']} x{len(group['images'])}"
        draw.text((8, top + 4), label, fill=(235, 235, 235))
        for line, words in enumerate(str(labels.get(row, '')).split('\n')[:4]):
            draw.text((8, top + 20 + 14 * line), words[:42], fill=(170, 200, 255))
        for column, data in enumerate(group['images']):
            picture = decode_image(data, group['format'], group['width'], group['height'])
            scale = min(cell / picture.width, cell / picture.height)
            picture = picture.resize((max(1, int(picture.width * scale)), max(1, int(picture.height * scale))), Image.NEAREST)
            out.paste(picture, (text + column * (cell + 8), top), picture)
    return out


# ------------------------------------------------------------------------------------------------------------
# what a port driver calls
# ------------------------------------------------------------------------------------------------------------

class Plan:
    """The generators and pictures a fighter's own effects need, gathered as its scripts are written.

        plan = Plan(effect_path, scale)
        uses = plan.use('duckhunt_atk_smoke_r', size=0.7)        # [(delay, generator number, behaviour)]
        items = script_items(uses, bone, offset)                 # the script commands, each with its delay
        data = plan.file('effDhDataTable')                       # the effect file, once every move is written
        plan.report()                                            # what was carried and what was not

    A set is converted once for each size (and, for its generators held by the joint, each offset; for its
    emitters whose particles fly, are pulled or are streaks, each turn) it is used at. `generators`, `behaviours`,
    `lives`, `groups` and `group_labels` hold what has been made so far."""

    def __init__(self, effect_path, scale, max_side=None):
        """effect_path: the fighter's Ultimate effect file. scale: Ultimate units to Melee units (the fighter's
        drawn scale). max_side: the most pixels a side a picture's frames are stored at (MAX_SIDE when not given)."""
        from echo_ultimate import effects
        self._effects = effects
        self.path = Path(effect_path)
        self.scale = float(scale)
        self.max_side = max_side
        self._group_sets = {}                           # group number -> the sets that use it
        data = self.path.read_bytes()
        self.v = effects.particle_data(data)
        self.names = effects.names(data)                # {the name a script uses: set name}
        self.sets = effects.effects(self.v)             # {set name: [emitter rows]}
        self.generators, self.behaviours, self.groups, self.group_labels = [], [], [], []
        self.lives = []                                 # each generator's own end (frames; 0: none, the move ends it)
        self._pictures = None                           # {picture number: (name, image)}
        self.unread, self._unread_numbers, self._read = [], {}, 0   # pictures the reader cannot read (`pictures`)
        self._group_of = {}                           # (picture number, grid, mirrored) -> group number
        self._made = {}                                 # (set, emitter index, size, offset, turn, held) -> generator number
        self._uses = {}                                 # (set, size, offset, turn, follow) -> [(delay, generator, behaviour)]
        self._rows = {}                                 # set name -> [report row an emitter]
        self._shapes = None                             # {model number: shape} (`shapes`)
        self._texture_names = None
        self._hand = set()                              # (set, emitter name): a stand-in the port makes itself (`by_hand`)
        self._joined = {}                               # group key -> (what the emitter's pictures got, why, notes)
        self._sources = []                              # what each group was made from (`_new_group`, for `fit`)
        self.fitted = []                                # labels of the groups `fit` made smaller

    def set_name(self, name):
        """The set a name stands for: a set's own name, or the name a script calls it by."""
        if name in self.sets:
            return name
        found = self.names.get(str(name).lower())
        if found is None:
            raise KeyError(f'{name!r} is not an effect set of {self.path.name}, nor a script name for one')
        return found

    def pictures(self):
        """Read the file's pictures (once). -> (how many were read, [(name, format)] of those in a format the reader
        does not know). An unread picture costs the emitters drawn with it (`_row` says so of each), not the run."""
        if self._pictures is None:
            names = self._effects.texture_names(self.v)
            unread = []
            images = dict(self._effects.textures(self._effects.texture_archive(self.v), unread))
            self._pictures = {n: (name, images[name]) for n, name in names.items() if name in images}
            self.unread, self._read = unread, len(images)
            self._unread_numbers = {n: fmt for n, name in names.items() for other, fmt in unread if other == name}
        return self._read, list(self.unread)

    def _picture(self, number):
        self.pictures()
        return self._pictures.get(number)

    def _group(self, number, grid, mirrored=False, thin=None):
        """The texture group for a picture cut by a grid (made on first use) and how many frames it holds.
        `thin`: a streak's shape (see `texture_group`)."""
        thin = (round(float(thin[0]), 1), thin[1]) if thin else None
        key = (number, tuple(grid), bool(mirrored), thin)
        if key not in self._group_of:
            name, image = self._picture(number)
            self._group_of[key] = self._new_group('plain', f"{name} {grid[0]}x{grid[1]}{' mirrored' if mirrored else ''}"
                                                  + (f' thin 1:{thin[0]:g} along {thin[1]}' if thin else ''),
                                                  image, grid, mirrored, self.max_side, thin)
        index = self._group_of[key]
        return index, len(self.groups[index]['images'])

    def _new_group(self, kind, label, image, grid, mirrored, max_side, thin=None):
        """Make and keep a texture group (`texture_group`), with what it was made from, so that `fit` can make it
        again smaller. kind: 'plain' (a picture of the file), 'joined' (`_joined_group`), 'shape' (`_flat_shape`).
        -> its number."""
        self.groups.append(texture_group(image, grid, mirrored, max_side, thin=thin))
        self.group_labels.append(label)
        self._sources.append(dict(kind=kind, image=image, grid=grid, mirrored=mirrored, thin=thin))
        return len(self.groups) - 1

    def fit(self, limit=None):
        """Make pictures smaller until the texture bank takes no more than `limit` bytes (BANK_WARNING_BYTES): each
        step halves the side of the group that takes the most bytes, of the flattened 3D shapes first (they are
        stand-ins already), then of the joined pictures, then of any (none below FIT_LEAST_SIDE). A group keeps its
        frames, so the generators drawn with it need no change. Called by `file`; `report` names what it halved.
        -> [labels of the groups made smaller]."""
        limit = BANK_WARNING_BYTES if limit is None else limit
        order = {'shape': 0, 'joined': 1, 'plain': 2}
        while self.groups and len(texture_bank(self.groups)) > limit:
            can = [i for i, g in enumerate(self.groups) if max(g['width'], g['height']) // 2 >= FIT_LEAST_SIDE]
            if not can:
                break
            i = min(can, key=lambda i: (order[self._sources[i]['kind']], -len(self.groups[i]['images'])
                                        * image_bytes(self.groups[i]['format'], self.groups[i]['width'], self.groups[i]['height'])))
            source, group = self._sources[i], self.groups[i]
            smaller = texture_group(source['image'], source['grid'], source['mirrored'],
                                    max(group['width'], group['height']) // 2, thin=source['thin'])
            assert len(smaller['images']) == len(group['images'])
            self.groups[i] = smaller
            if self.group_labels[i] not in self.fitted:
                self.fitted.append(self.group_labels[i])
        return list(self.fitted)

    def shapes(self):
        """The file's 3D shapes (`echo_ultimate.effects.shapes`), read once."""
        if self._shapes is None:
            self._shapes = self._effects.shapes(self.v)
        return self._shapes

    def by_hand(self, name, emitter_name):
        """Say that the port makes its own stand-in (`stand_in`) for one emitter that draws on a 3D shape: `use`
        then leaves that emitter out instead of flattening its shape (Wolf's sheath of fire). Said before the set
        is first used: a shape already flattened is not taken back."""
        set_name = self.set_name(name)
        for index, row in enumerate(self.sets[set_name]):
            made = (self._rows.get(set_name) or [None] * (index + 1))[index]
            if made is not None and made['emitter'] == emitter_name and made.get('model') is not None and made['generators']:
                raise ValueError(f'{set_name} {emitter_name}: its shape is already flattened (say `by_hand` before `use`)')
            if made is not None and made['emitter'] == emitter_name:
                self._rows[set_name][index] = None              # made again, by hand, when next asked
        self._hand.add((set_name, emitter_name))

    def drawn(self, emitter, at):
        """The numbers of the pictures an emitter draws, in its own order: none for one that only bends what is
        behind it (a refraction), and, for one that bends its own pictures, all but the map of offsets (by its
        name: `echo_ultimate.effects.bends`; when none is so named, the first). See `echo_ultimate.effects.shader_mode`."""
        effects, numbers = self._effects, list(emitter['textures'])
        mode = effects.shader_mode(self.v, at)
        if mode == 'refraction':
            return []
        if mode == 'distortion' and numbers:
            if self._texture_names is None:
                self._texture_names = effects.texture_names(self.v)
            maps = [n for n in numbers if effects.bends(self._texture_names.get(n, ''))]
            numbers = [n for n in numbers if n not in maps] if maps else numbers[1:]
        return numbers

    def _row(self, set_name, index, row):
        """The report row of one emitter, made once: why it is not carried at all, if it is not. An emitter that
        draws on a 3D shape has its model's number (`model`); one that draws with more than one picture, or bends
        its pictures, says so (`pictures`: how many it has and draws; `use` adds what they got)."""
        rows = self._rows.setdefault(set_name, [None] * len(self.sets[set_name]))
        if rows[index] is None:
            effects, at = self._effects, row['binary']
            emitter = effects.emitter(self.v, at)
            entry = dict(emitter=emitter['name'], carried=True, steady=not emitter['one_time'], generators=[],
                         not_carried=[], notes=[])
            shape = effects.model(self.v, at)
            mode = effects.shader_mode(self.v, at)
            drawn = self.drawn(emitter, at)
            if shape is not None:
                entry['model'] = shape
            if len(emitter['textures']) > 1 or mode != 'plain':
                entry['pictures'] = dict(count=len(emitter['textures']), drawn=len(drawn), mode=mode)
            unread = [n for n in drawn if self._picture(n) is None]
            if row.get('inside'):
                entry.update(carried=False, not_carried=[f"an emitter inside another ({row['inside']}): what its particles give off"])
            elif mode == 'refraction':
                entry.update(carried=False, not_carried=['it only bends what is behind it (a refraction): it has nothing '
                                                         'of its own to draw'])
            elif emitter['textures'] and not drawn:
                entry.update(carried=False, not_carried=['its only picture is a map of offsets: it only bends what is behind it'])
            elif shape is not None and shape not in self.shapes():
                entry.update(carried=False, not_carried=[f"draws its picture on a 3D shape (model {shape:#010x}) that is "
                                                         "not among the file's models"])
            elif shape is not None and (set_name, emitter['name']) in self._hand:
                entry.update(carried=False, not_carried=[f'draws its picture on a 3D shape (model {shape:#010x}): the '
                                                         "port makes its own stand-in for it"])
            elif effects.emission(self.v, at)['by_distance']:
                entry.update(carried=False, not_carried=['gives off by how far it has moved, not by time'])
            elif emitter['rate'] <= 0:
                entry.update(carried=False, not_carried=['gives off no particles'])
            elif unread:
                number = unread[0]
                entry.update(carried=False, not_carried=[
                    f"its picture ({number:#x}) is in a format the reader does not know ({self._unread_numbers[number]:#x}: "
                    'echo_ultimate/effects.py FORMATS)' if number in self._unread_numbers
                    else f"its picture ({number:#x}) is not among the file's pictures"])
            if 'pictures' in entry and not entry['carried']:
                entry['pictures']['got'] = 'left out'
            rows[index] = entry
        return rows[index]

    def _joined_group(self, entry, emitter, at, drawn, mirrored, thin):
        """The texture group of an emitter that draws with more than one picture, or not with its first: its drawn
        pictures joined into one (`effect_shapes.join`, as its combiner says, `echo_ultimate.effects.combiner`), or,
        where that draws a square or a dark box (`effect_shapes.draws_square`), a STAND-IN picture that is not one
        (`effect_shapes.stand_in`). -> (group, frames, grid). The emitter's row says which it got and why."""
        from . import effect_shapes as fs
        thin = (round(float(thin[0]), 1), thin[1]) if thin else None
        grid = tuple(emitter['grid']) if drawn[0] == emitter['textures'][0] else (1, 1)
        joins = self._effects.combiner(self.v, at)
        slots = [emitter['textures'].index(n) for n in drawn]
        colour = tuple(joins['colour'][s - 1] for s in slots[1:])
        alpha = tuple(joins['alpha'][s - 1] for s in slots[1:])
        additive = emitter['blend'] == 'add'
        key = ('joined', tuple(drawn), colour, alpha, grid, bool(mirrored), thin, additive)
        if key not in self._group_of:
            names = [self._picture(n)[0] for n in drawn]
            images = [self._picture(n)[1] for n in drawn]
            picture = fs.join(images, grid, colour, alpha) if len(images) > 1 else images[0]
            cell = picture.crop((0, 0, picture.width // grid[0], picture.height // grid[1]))
            square, why = fs.draws_square(cell, additive)
            notes = [f'{name} is not drawn: it is a map of offsets (it bends the others)'
                     for n, name in zip(emitter['textures'], [self._picture(n)[0] if self._picture(n) else hex(n)
                                                             for n in emitter['textures']]) if n not in drawn]
            unknown = sorted({str(j) for j in colour + alpha if j not in ('multiply', 'add', 'subtract')})
            if unknown:
                notes.append(f'joins its pictures in a way that is not known ({", ".join(unknown)}): multiplied')
            how = 'combined' if len(images) > 1 else 'one drawn'
            if len(images) > 1:
                notes.append('its pictures ' + ', '.join(names) + ' joined into one: colour '
                             + ', '.join(colour) + '; alpha ' + ', '.join(alpha) + ' (a reading: see effects.combiner)')
            if square:
                picture, how = fs.stand_in(picture, grid, cut_round=square == 'square'), 'stand-in'
                notes.append(f'STAND-IN picture: what its pictures make drew a {"square" if square == "square" else "dark box"} '
                             f'here ({why}): made see-through where it is dark'
                             + (' and cut round' if square == 'square' else ''))
            if how == 'one drawn':                      # its one picture as it is: shared with every other emitter's
                self._group_of[key] = self._group(drawn[0], grid, mirrored, thin)[0]
            else:
                self._group_of[key] = self._new_group(
                    'joined', '+'.join(names) + f" {grid[0]}x{grid[1]} {how}{' mirrored' if mirrored else ''}"
                    + (f' thin 1:{thin[0]:g} along {thin[1]}' if thin else ''), picture, grid, mirrored, self.max_side, thin)
            self._joined[key] = (how, notes)
        index = self._group_of[key]
        how, notes = self._joined[key]
        entry['pictures']['got'] = how
        entry['pictures']['notes'] = notes
        if how == 'stand-in':
            said = next(n for n in notes if n.startswith('STAND-IN'))
            if said not in entry.setdefault('stand_in', []):
                entry['stand_in'].append(said)
        return index, len(self.groups[index]['images']), grid

    def _flat_shape(self, entry, emitter, at, size, offset, turn, held, lasting=0):
        """One emitter that draws its picture on a 3D shape as a STAND-IN: the shape, its pictures on it (joined as
        `_joined_group` joins them), turned by the emitter's own turn (and, when it is laid in the effect's space and
        not turned to face the camera, by the script call's), flattened as the camera sees it
        (`effect_shapes.flatten`), carried by flat particles with the emitter's own timing, colour, alpha and size
        keys, as wide as the shape is drawn. A turn about the axis toward the camera (the start turn, its random
        part, the spin) is the particle's own turn; where any other turn is given, the shape is drawn so turned.
        An emitter that lays its shape along its speed lays the picture so (command E6). One picture a shape,
        picture and turn, shared by the emitters that draw the same. -> what `convert` gives, or a string saying why
        it is not carried: the shape shows nothing from the side, or it would be drawn wider than WIDEST_STAND_IN
        (the row then says so)."""
        from . import effect_shapes as fs
        effects = self._effects
        model, shape = entry['model'], self.shapes()[entry['model']]
        draw = effects.draw_type(self.v, at)
        drawn = self.drawn(emitter, at)
        additive = emitter['blend'] == 'add'
        speedy = max(float(emitter['speed']), float(emitter['speed_along'])) > 1e-9
        by_speed = draw in fs.BY_SPEED and speedy
        facing = draw in fs.FACING_CAMERA
        t = [float(x) for x in emitter['turn']]
        call = [0.0, 0.0, 0.0] if facing else [math.radians(float(x)) for x in turn]
        axis = 2 if facing else 0                       # the shape's axis toward the camera
        rest = [i for i in range(3) if i != axis]
        dropped = []
        if by_speed:
            bake, call_bake, own_turn = t, [0.0, 0.0, 0.0], 0.0
        elif all(abs(t[i]) < 1e-6 and abs(call[i]) < 1e-6 for i in rest):
            bake, call_bake, own_turn = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], t[axis] + call[axis]
        else:
            bake, call_bake, own_turn = t, call, 0.0
        # how big it is drawn: at each size key, the half side of the square about the origin that holds it
        base = [float(s) for s in emitter['size']]
        keys = emitter['size_keys'] or [dict(time=0.0, value=(1.0, 1.0, 1.0))]
        views = [fs.view(shape['positions'], draw, [base[i] * float(k['value'][i]) for i in range(3)], bake, call_bake)
                 for k in keys]
        reaches = [fs.reach(a, u) for a, u, _ in views]
        largest = int(np.argmax(reaches))
        half = reaches[largest]
        if half <= 1e-6:
            return EDGE_ON
        drawn_across = 2.0 * half * self.scale * float(size)
        if drawn_across > WIDEST_STAND_IN:
            return (f"its 3D shape {shape['name']} would be drawn {drawn_across:,.0f} across at its largest (size "
                    f"{max(abs(s) for s in base):g}), wider than all the camera shows (more than {WIDEST_STAND_IN:g}): "
                    'not drawn')
        spans = [(float(np.ptp(a)), float(np.ptp(u))) for a, u, _ in views]
        ratio = lambda s: max(s[0], 1e-6) / max(s[1], 1e-6)
        if any(max(ratio(s), ratio(spans[largest])) > LONG_SIZE * min(ratio(s), ratio(spans[largest])) for s in spans):
            dropped.append('it grows more one way than another over its life: drawn at its largest shape, grown evenly')
        drawn_size = [base[i] * float(keys[largest]['value'][i]) for i in range(3)]
        grid = tuple(emitter['grid']) if drawn[0] == emitter['textures'][0] else (1, 1)
        joins = effects.combiner(self.v, at)
        slots = [emitter['textures'].index(n) for n in drawn]
        colour = tuple(joins['colour'][s - 1] for s in slots[1:])
        alpha = tuple(joins['alpha'][s - 1] for s in slots[1:])
        unit = max(max(abs(s) for s in drawn_size), 1e-9)
        key = ('shape', model, tuple(drawn), colour, alpha, grid, draw, tuple(round(x, 2) for x in bake),
               tuple(round(x, 2) for x in call_bake), tuple(round(s / unit, 3) for s in drawn_size), additive)
        if key not in self._group_of:
            from PIL import Image
            images = [self._picture(n)[1] for n in drawn]
            sheet = fs.join(images, grid, colour, alpha)            # (one picture alone: a mask made see-through)
            across, down = grid
            w, h = sheet.width // across, sheet.height // down
            side = fs.RENDER_SIDE
            frames = Image.new('RGBA', (side * across, side * down))
            for r in range(down):
                for c in range(across):
                    frame = fs.flatten(shape, sheet.crop((c * w, r * h, (c + 1) * w, (r + 1) * h)), draw, half,
                                       drawn_size, bake, call_bake, additive, side)
                    frames.paste(frame, (c * side, r * side))
            if frames.getextrema()[3][1] < 5:
                self._group_of[key] = None
            else:
                # no more pixels than it is drawn large (SHAPE_PIXELS a Melee unit, at its first use; SHAPE_SIDE)
                across_units = 2.0 * half * self.scale * float(size)
                most = min(self.max_side or MAX_SIDE, SHAPE_SIDE,
                           max(MIN_SIDE * 2, _side(int(across_units * SHAPE_PIXELS) * 2, 1 << 12)))
                self._group_of[key] = self._new_group('shape', f"{shape['name']} with " + '+'.join(self._picture(n)[0] for n in drawn)
                                                      + f' {grid[0]}x{grid[1]} flattened ({draw})', frames, grid, False, most)
        group = self._group_of[key]
        if group is None:
            return EDGE_ON
        images = len(self.groups[group]['images'])
        out = dict(emitter)
        sign = 1.0 if facing else ROTATE_SIGN           # see `convert`: the turn toward the camera of a laid shape
        out.update(textures=drawn[:1], grid=grid, size=(2.0 * half,) * 3,
                   size_keys=[dict(time=k['time'], value=(r / half,) * 3) for k, r in zip(keys, reaches)],
                   turn=(0.0, 0.0, sign * own_turn), turn_random=(0.0, 0.0, sign * float(emitter['turn_random'][axis])),
                   spin=(0.0, 0.0, sign * float(emitter['spin'][axis])),
                   spin_random=(0.0, 0.0, float(emitter['spin_random'][axis])))
        if by_speed:
            out.update(turn=(0.0, 0.0, 0.0), turn_random=(0.0, 0.0, 0.0), spin=(0.0, 0.0, 0.0), spin_random=(0.0, 0.0, 0.0))
        renewed = by_speed and held                     # (TURNED_BEHAVIOUR: given off anew each frame)
        if renewed:
            when = float(keys[largest]['time'])
            out.update(life=RENEWED_LIFE, life_random=0.0, size_keys=[], frames='one', frame_table=[], frames_random=0,
                       **{name: [dict(time=0.0, value=_key_at(out[name], when))]
                          for name in ('colour_keys', 'alpha_keys', 'colour2_keys', 'alpha2_keys') if out.get(name)})
            if emitter['one_time']:
                out.update(rate=1.0, emit_frames=max(1, int(emitter['emit_frames']) + int(emitter['life']) - 1))
            else:
                out.update(rate=1.0, emit_frames=1, loop=1)
            dropped.append(f'given off anew each frame, turned as the joint is turned (behaviour {TURNED_BEHAVIOUR}), '
                           'each picture as it is at its largest: its colour, alpha, size and frames over its life '
                           'are not carried')
        if grid != tuple(emitter['grid']):
            out.update(frames='one', frame_table=[], frames_random=0)
        names = 'xyz'
        other = rest if not by_speed else [0, 1, 2]
        if any(abs(float(emitter['turn_random'][i])) > 1e-6 for i in other):
            dropped.append('its random turn about its ' + ' and '.join(names[i] for i in other
                                                                         if abs(float(emitter['turn_random'][i])) > 1e-6)
                           + ' axis: the shape is drawn at one turn')
        if any(abs(float(emitter['spin'][i])) > 1e-6 for i in other):
            dropped.append('its spin about its ' + ' and '.join(names[i] for i in other if abs(float(emitter['spin'][i])) > 1e-6)
                           + ' axis: the shape is drawn at one turn')
        mirror = effects.mirror(self.v, at)
        if mirror != 'none':
            dropped.append(f'its picture is mirrored on the shape in a way not carried (mode {mirror})')
        got = convert(out, self.scale, size, tex_group=group, images=images, offset=offset, turn=turn, held=held,
                      modes=effects.track_modes(self.v, at), mirror='none',
                      emission=None if renewed else effects.emission(self.v, at), along_speed=by_speed,
                      joint_turned=renewed, lasting=lasting)
        if got['held']:
            dropped.append('held by the joint: the game shows its picture the same way when he faces left')
        got['dropped'] = dropped + got['dropped']
        said = (f"STAND-IN: its 3D shape {shape['name']} ({draw}) flattened into one picture as the camera sees it "
                f'from his side, {drawn_across:.3g} across at its largest, with its timing, colour, alpha and size '
                'keys; the shape does not turn in depth, and any movement of its picture over the shape is not carried')
        if said not in entry.setdefault('stand_in', []):
            entry['stand_in'].append(said)
        if 'pictures' in entry:
            entry['pictures']['got'] = 'combined' if len(drawn) > 1 else 'one drawn'
        return got, group, images

    def _add(self, made, got, entry, set_name, group, images):
        """Keep one converted generator (once per `made` key)."""
        if images:
            self._group_sets.setdefault(group, set()).add(set_name)
        self._made[made] = (len(self.generators), got['behaviour'], got['delay'])
        self.generators.append(got['generator'])
        self.behaviours.append(got['behaviour'])
        self.lives.append(int(got['header']['gen_life']))
        entry['generators'].append(self._made[made][0])
        entry['bytes'] = len(got['generator'])

    def use(self, name, size=1.0, offset=(0.0, 0.0, 0.0), turn=(0.0, 0.0, 0.0), follow=False, lasting=0, only=None):
        """The generators that play a set at a size: [(frames after the script call, generator number, behaviour)],
        one for each of its emitters that is carried, in the set's own order. `name`: the set's name or the name a
        script uses. `offset`: where the particles of a generator held by the joint start from it, in Melee units
        in the effect's own space (x to the side, y up, z ahead): the game does not use a script command's offset
        for a generator held by a joint. (A one-time emitter's generator takes the script command's own offset: see
        `script_items`.) `turn`: the script call's turn in degrees; it turns the way the set's particles fly and
        lays its streaks (`convert`). `follow`: the call makes the effect follow its bone (EFFECT_FOLLOW...): every
        generator of the set is held by the joint. `lasting`: its steady emitters' generators give off for that many
        frames and end (`convert`): for an effect the fighter's code gives again while it lasts. `only`: the names of
        the emitters to use (the others of the set are not used by this call, and their report rows say so when no
        other call uses them): a code that shows only part of a set (the symbol of an effect, not its flash)."""
        set_name = self.set_name(name)
        size = round(float(size), 4)
        offset = tuple(round(float(o), 3) for o in offset)
        turn = tuple(round(float(t), 2) for t in turn)
        lasting = int(lasting or 0)
        only = tuple(sorted(only)) if only is not None else None
        key = (set_name, size, offset, turn, bool(follow), lasting, only)
        if key in self._uses:
            return list(self._uses[key])
        effects, out = self._effects, []
        if only is not None:
            names_ = {effects.emitter(self.v, row['binary'])['name'] for row in self.sets[set_name]}
            unknown = sorted(set(only) - names_)
            if unknown:
                raise KeyError(f'{set_name} has no emitter named {unknown} (it has {sorted(names_)})')
        for index, row in enumerate(self.sets[set_name]):
            entry = self._row(set_name, index, row)
            if not entry['carried']:
                continue
            emitter = effects.emitter(self.v, row['binary'])
            if only is not None and emitter['name'] not in only:
                if not entry['generators']:
                    said = 'not used: the port shows only part of this set (`use(only=...)`)'
                    if said not in entry['notes']:
                        entry['notes'].append(said)
                continue
            held = entry['steady'] or bool(follow)
            life = lasting if entry['steady'] else 0
            if entry.get('model') is not None:
                made = (set_name, index, size, offset if held else None, turn, held, 'shape', life)
                if made not in self._made:
                    flat = self._flat_shape(entry, emitter, row['binary'], size, offset, turn, held, life)
                    if isinstance(flat, str) and entry['generators']:
                        continue                        # (drawn at another turn or size, it showed)
                    if isinstance(flat, str):
                        entry.update(carried=False, not_carried=[flat])
                        entry.pop('stand_in', None)
                        if 'pictures' in entry:
                            entry['pictures']['got'] = 'left out'
                        continue
                    got, group, images = flat
                    self._add(made, got, entry, set_name, group, images)
                    entry['not_carried'] = got['dropped']
                    entry['notes'] = got['notes']
                number, behaviour, delay = self._made[made]
                out.append((delay, number, behaviour))
                continue
            long = streak(emitter)
            # the turn matters to an emitter whose particles fly or are pulled, or that is a streak
            turned = long or emitter['speed_along'] > 0 or emitter['speed'] > 0 or abs(float(emitter['gravity'])) > 1e-9
            made = (set_name, index, size, offset if held else None, turn if turned else None, held, life)
            if made not in self._made:
                mirror = effects.mirror(self.v, row['binary'])
                drawn = self.drawn(emitter, row['binary'])
                passed, joined = emitter, []
                if emitter['textures'] and (len(emitter['textures']) > 1 or drawn != emitter['textures'][:1]):
                    group, images, grid = self._joined_group(entry, emitter, row['binary'], drawn, mirror == 'both', long)
                    passed = dict(emitter, textures=drawn[:1], grid=grid)
                    if grid != tuple(emitter['grid']):
                        passed.update(frames='one', frame_table=[], frames_random=0)
                    joined = entry['pictures'].get('notes') or []
                else:
                    group, images = (self._group(emitter['textures'][0], emitter['grid'], mirror == 'both', long)
                                     if emitter['textures'] else (0, 0))
                got = convert(passed, self.scale, size, tex_group=group, images=images, offset=offset,
                              long=long, turn=turn, held=held,
                              modes=effects.track_modes(self.v, row['binary']), mirror=mirror,
                              emission=effects.emission(self.v, row['binary']), lasting=life)
                self._add(made, got, entry, set_name, group, images)
                entry['not_carried'] = got['dropped']
                entry['notes'] = joined + got['notes']
            number, behaviour, delay = self._made[made]
            out.append((delay, number, behaviour))
        self._uses[key] = out
        return list(out)

    def ends(self, number):
        """Whether generator `number` ends by itself (a one-time emitter's), held by a joint or not."""
        return self.lives[int(number)] > 0

    def stand_in(self, name, emitter_name, picture, width, size=1.0, offset=(0.0, 0.0, 0.0), follow=True):
        """A STAND-IN for one emitter of a set that draws its picture on a 3D shape (which Melee cannot draw): flat
        particles of a picture of the file (`picture`, by its name: a soft round one stands in for a sheath of
        fire), `width` Melee units across at their largest, with the emitter's own timing, colour, alpha and size
        keys, given off at the joint (held by it when `follow`) plus `offset`. The picture is mirrored as the
        file's own emitters that draw it are. -> [(delay, generator number, behaviour)], as `use` gives. The
        emitter's report row says it is a stand-in, and what of it."""
        set_name = self.set_name(name)
        effects = self._effects
        index = next((i for i, row in enumerate(self.sets[set_name])
                      if effects.emitter(self.v, row['binary'])['name'] == emitter_name), None)
        if index is None:
            raise KeyError(f'{set_name} has no emitter named {emitter_name!r}')
        number = next((n for n, label in effects.texture_names(self.v).items() if label == picture), None)
        if number is None or self._picture(number) is None:
            raise KeyError(f'{picture!r} is not a picture of {self.path.name} that the reader can read')
        size = round(float(size), 4)
        offset = tuple(round(float(o), 3) for o in offset)
        row = self.sets[set_name][index]
        entry = self._row(set_name, index, row)
        made = ('stand-in', set_name, index, picture, round(float(width), 3), size, offset, bool(follow))
        if made not in self._made:
            emitter = dict(effects.emitter(self.v, row['binary']))
            # the shape's own size says nothing of a flat picture's: the width is the stand-in's own (see `convert`:
            # Melee's size is half the width, times the drawn scale and the call's size, times the size keys)
            largest = max([(float(key['value'][0]) + float(key['value'][1])) / 2.0 for key in emitter['size_keys'] or []]
                          or [1.0])
            across = float(width) / (2.0 * SIZE_TO_HALF_WIDTH * self.scale * size * max(largest, 1e-6))
            emitter.update(textures=[number], grid=(1, 1), frames='one', frame_table=[], frames_random=0,
                           size=(across, across, across), size_random=(0.0, 0.0, 0.0), speed=0.0, speed_along=0.0,
                           speed_random=0.0, gravity=0.0, shape='point', radius=(0.0, 0.0, 0.0),
                           turn=(0.0, 0.0, 0.0), turn_random=(0.0, 0.0, 0.0), spin=(0.0, 0.0, 0.0),
                           spin_random=(0.0, 0.0, 0.0))
            mirror = next((effects.mirror(self.v, other['binary']) for rows in self.sets.values() for other in rows
                           if not other.get('inside')
                           and (effects.emitter(self.v, other['binary'])['textures'] or [None])[0] == number), 'none')
            group, images = self._group(number, (1, 1), mirror == 'both')
            got = convert(emitter, self.scale, size, tex_group=group, images=images, offset=offset, held=follow,
                          modes=effects.track_modes(self.v, row['binary']), mirror=mirror,
                          emission=effects.emission(self.v, row['binary']))
            self._add(made, got, entry, set_name, group, images)
            said = (f'STAND-IN: flat {picture} {float(width):.3g} across, its timing, colour, alpha and size keys'
                    + (', held by the joint' if follow else ''))
            if said not in entry.setdefault('stand_in', []):
                entry['stand_in'].append(said)
        number, behaviour, delay = self._made[made]
        return [(delay, number, behaviour)]

    def file(self, symbol):
        """The effect file with every generator and picture used so far, its table root named `symbol`, its
        pictures first made small enough to fit (`fit`)."""
        self.fit()
        groups = self.groups
        if self.generators and not groups:
            # the game reads a generator's texture group even when its particles show no picture
            from PIL import Image
            groups = [dict(format=I8, width=8, height=8, images=[encode_image(Image.new('RGBA', (8, 8), (255,) * 4), I8)])]
        return effect_file(symbol, self.generators, self.behaviours, groups)

    def report(self):
        """What was carried and what was not: {'sets': {set name: [a row an emitter: its name, whether it is carried,
        whether it is steady (not one-time: held by the joint, with no end), its generator numbers, what of it is
        not carried, what was approximated]}, 'groups': each texture group's picture, format, size, bytes and the
        sets that use it, 'bytes': how many generators and the sizes of the two banks, 'warnings'}."""
        groups = [dict(group=i, picture=label, format=FORMAT_NAMES[g['format']], width=g['width'], height=g['height'],
                       images=len(g['images']), bytes=len(g['images']) * image_bytes(g['format'], g['width'], g['height']),
                       sets=sorted(self._group_sets.get(i, ())))
                  for i, (g, label) in enumerate(zip(self.groups, self.group_labels))]
        sizes = dict(generators=len(self.generators),
                     particle_bank=len(particle_bank(self.generators)) if self.generators else 0,
                     texture_bank=len(texture_bank(self.groups)) if self.groups else 0)
        warnings = []
        if sizes['texture_bank'] > BANK_WARNING_BYTES:
            warnings.append(f"the texture bank is {sizes['texture_bank']} bytes, above {BANK_WARNING_BYTES}")
        for name, fmt in self.unread:
            warnings.append(f'picture {name} is in a format the reader does not know ({fmt:#x}): what is drawn with it '
                            'is not carried')
        return dict(sets={name: [dict(row) for row in rows if row is not None] for name, rows in self._rows.items()},
                    groups=groups, bytes=sizes, warnings=warnings, fitted=list(self.fitted),
                    unread_pictures=[dict(name=name, format=hex(fmt)) for name, fmt in self.unread])


def script_items(uses, bone, offset=(0.0, 0.0, 0.0), destroy=False, ends=()):
    """The script commands that play what `Plan.use` gave: [(frames after the call, fields of a code-10 command)],
    the fields as `vault.echo.subactions.FighterDat.encode_script` takes them (an item is (10, fields, None)).

    bone: the joint's number in the Melee fighter. offset: from that joint, in the joint's own space, in Melee
    units (x, y, z). The script reader names the command's three offsets z, y, x in that order, so the first, the
    joint's x, goes in its field 'z' and the joint's z in its field 'x'. destroy: set the command's flag that has
    the game remove the fighter's held effects when the move ends. A generator held by a joint with no end of its
    own is always given it; one held that ends by itself (its number in `ends`: `Plan.ends`) takes the call's. The
    game does not use the offset for a held one (see `Plan.use`)."""
    x, y, z = (int(round(float(o) * 256.0)) for o in offset)
    out = []
    for delay, number, behaviour in uses:
        held = behaviour in ATTACHED
        endless = held and number not in ends
        fields = dict(bone_id=int(bone), use_common_bone_ids=0, destroy_on_state_change=int(bool(destroy or endless)),
                      unk1=0, gfx_id=OWN_EFFECT + int(number), unk2=0, z=0 if held else x, y=0 if held else y,
                      x=0 if held else z, range_z=0, range_y=0, range_x=0)
        out.append((int(delay), fields))
    return out
