"""Read native attack capsules while frozen, retaining raw evidence.

GALE01 ft/types.h x914[4], lb/types.h HitCapsule (0x138 bytes).
The attachment pointer is +0x48, not +4. All nonzero live states are included.
Cached positions describe the observed phase; they do not prove which position
a collision consumer used. Bracket this read with the caller's game counter.
"""
import math
import struct

from shared.ingame.pose import CaptureError, _read

HITBOX_OFFSET = 0x914
HITBOX_STRIDE = 0x138
HURTBOX_COUNT_OFFSET = 0x119E
HURTBOX_OFFSET = 0x11A0
HURTBOX_STRIDE = 0x4C
HURTBOX_CAPACITY = 15
BODY_COLLISION_STATE_OFFSET = 0x1988
BODY_COLLISION_FLAGS_WORD_OFFSET = 0x221C


def native_hitbox_geometry(fields):
    """Model ftAction_8007121C's encoded geometry conversion.

    GALE01 ftaction.c uses literal 0.003906f, not exact 1/256. The
    editor's z_offset word is assigned to local X; x_offset goes to Z.
    Match single-precision constant and multiplication rounding separately.
    """
    def f32(value):
        return struct.unpack('>f', struct.pack('>f', value))[0]
    factor = f32(0.003906)
    def convert(key, lower, upper):
        value = fields.get(key)
        if type(value) is not int or not lower <= value <= upper:
            raise CaptureError('Invalid encoded hitbox field: ' + key)
        return f32(factor * value)
    return {'radius': convert('size', 0, 65535),
            'local_xyz': [convert(k, -32768, 32767)
                          for k in ('z_offset', 'y_offset', 'x_offset')]}


def decode_hitboxes(raw):
    if not isinstance(raw, bytes) or len(raw) != 4 * HITBOX_STRIDE:
        raise CaptureError('Expected four complete native HitCapsules')
    result = []
    for slot in range(4):
        block = raw[slot*HITBOX_STRIDE:(slot+1)*HITBOX_STRIDE]
        word = lambda offset: struct.unpack_from('>I', block, offset)[0]
        if word(0) == 0:
            continue
        scalar = lambda offset: struct.unpack_from('>f', block, offset)[0]
        vector = lambda offset: list(struct.unpack_from('>3f', block, offset))
        record = {'slot': slot, 'live': word(0), 'raw': block.hex(),
                  'integer_damage': word(8), 'damage': scalar(12),
                  'local_xyz': vector(0x10), 'radius': scalar(0x1c),
                  'angle': word(0x20), 'knockback_growth': word(0x24),
                  'fixed_knockback': word(0x28), 'base_knockback': word(0x2c),
                  'flags_word': word(0x40), 'victim_count': block[0x44],
                  'secondary_victim_count': block[0x45],
                  'bone_pointer': word(0x48), 'world_xyz': vector(0x4c),
                  'previous_world_xyz': vector(0x58),
                  'grabbed_only': bool(block[0x134] & 0x80)}
        numeric = [record['damage'], record['radius'], *record['local_xyz'],
                   *record['world_xyz'], *record['previous_world_xyz']]
        if not all(math.isfinite(x) for x in numeric):
            raise CaptureError(f'Nonfinite live hitbox {slot}')
        result.append(record)
    return result


def capture_hitboxes(d, fighter):
    raw = _read(d, fighter + HITBOX_OFFSET, 4 * HITBOX_STRIDE)
    return {'schema': 'native-hitcapsules-v1', 'raw': raw.hex(), 'live': decode_hitboxes(raw)}


def decode_hit_victims(block):
    """Decode both complete victim arrays; +44/+45 are replacement cursors.

    lbColl_80008688/80008820 fill a NULL slot first. They advance the cursor
    only when all twelve slots are occupied, so cursor zero is not an empty
    contact list. Legacy decode_hitboxes count labels remain for receipt parity.
    """
    if not isinstance(block,bytes) or len(block)!=HITBOX_STRIDE:
        raise CaptureError('Complete hit capsule required for victim lists')
    result={}
    for name,offset,cursor in [('primary',0x74,0x44),('secondary',0xd4,0x45)]:
        if block[cursor]>=12:raise CaptureError('Victim replacement cursor outside array')
        entries=[dict(pointer=struct.unpack_from('>I',block,offset+i*8)[0],timer=struct.unpack_from('>I',block,offset+i*8+4)[0]) for i in range(12)]
        if any(e['pointer'] and (e['pointer']%4 or not 0x80000000<=e['pointer']<0x81800000) for e in entries):
            raise CaptureError('Victim pointer outside aligned MEM1')
        result[name]=dict(replacement_cursor=block[cursor],entries=entries,occupied=sum(bool(e['pointer']) for e in entries))
    return result


def decode_hurtboxes(raw, count):
    """Decode the native prefix selected by the fighter's hurt-capsule count.

    Cached endpoints are phase-dependent, stale storage until the game updates
    them. Nonfinite cached components are represented as None while raw retains
    their exact bits. Local geometry is always required to be finite.
    """
    if not isinstance(count, int) or isinstance(count, bool) or not 0 <= count <= HURTBOX_CAPACITY:
        raise CaptureError('Hurt-capsule count must be an integer from 0 through 15')
    expected = HURTBOX_CAPACITY * HURTBOX_STRIDE
    if not isinstance(raw, bytes) or len(raw) != expected:
        raise CaptureError('Expected complete 15-entry native hurt-capsule array')
    result = []
    for slot in range(count):
        block = raw[slot*HURTBOX_STRIDE:(slot+1)*HURTBOX_STRIDE]
        word = lambda offset: struct.unpack_from('>I', block, offset)[0]
        scalar = lambda offset: struct.unpack_from('>f', block, offset)[0]
        vector = lambda offset: list(struct.unpack_from('>3f', block, offset))
        state = word(0)
        if state not in (0, 1, 2):
            raise CaptureError(f'Invalid hurtbox state {state} in slot {slot}')
        cached_a = vector(0x28)
        cached_b = vector(0x34)
        cached_positions_finite = all(math.isfinite(x) for x in [*cached_a, *cached_b])
        grabbable_word = word(0x48)
        record = {
            'slot': slot, 'state': state, 'raw': block.hex(),
            'local_a': vector(4), 'local_b': vector(0x10), 'scale': scalar(0x1C),
            'bone_pointer': word(0x20), 'flags_byte': block[0x24],
            'skip_update_pos': bool(block[0x24] & 0x80),
            'cached_a': [x if math.isfinite(x) else None for x in cached_a],
            'cached_b': [x if math.isfinite(x) else None for x in cached_b],
            'cached_positions_finite': cached_positions_finite,
            'bone_index': word(0x40), 'height': word(0x44),
            'grabbable_word': grabbable_word, 'grabbable': bool(grabbable_word),
        }
        if not all(math.isfinite(x) for x in
                   [*record['local_a'], *record['local_b'], record['scale']]):
            raise CaptureError(f'Nonfinite hurtbox local geometry {slot}')
        result.append(record)
    return result


def capture_hurtboxes(d, fighter):
    # _read intentionally permits aligned MEM1 reads only. Retain the requested
    # byte while fetching its containing native word.
    count_word = _read(d, fighter + HURTBOX_COUNT_OFFSET - 2, 4)
    raw_count = count_word[2:3]
    count = raw_count[0]
    raw = _read(d, fighter + HURTBOX_OFFSET, HURTBOX_CAPACITY * HURTBOX_STRIDE)
    return {'schema': 'native-hurtcapsules-v1', 'raw_count': raw_count.hex(),
            'count': count, 'raw': raw.hex(),
            'hurtboxes': decode_hurtboxes(raw, count)}


def capture_body_collision_state(d, fighter):
    """Capture fighter-wide collision state without deriving intangibility.

    GALE01 ft/types.h defines enum_t x1988 and s32 x198C. Command 26 reaches
    ftColl_8007B62C and writes x1988; collision consumers also inspect x198C
    and x221D_b6. The latter is byte +0x221D mask 0x02 on big-endian GALE01.
    """
    raw_states = _read(d, fighter + BODY_COLLISION_STATE_OFFSET, 8)
    persistent_state, timed_state = struct.unpack('>II', raw_states)
    for label, value in (('persistent', persistent_state), ('timed', timed_state)):
        if value not in (0, 1, 2):
            raise CaptureError(f'Invalid {label} body collision state {value}')
    raw_flags = _read(d, fighter + BODY_COLLISION_FLAGS_WORD_OFFSET, 4)
    flags_byte = raw_flags[1]
    return {
        'schema': 'native-body-collision-state-v1',
        'raw_states': raw_states.hex(),
        'persistent_state': persistent_state,
        'timed_state': timed_state,
        'raw_flags_word': raw_flags.hex(),
        'flags_221d': flags_byte,
        'x221d_b6': bool(flags_byte & 0x02),
        'state_domain': {'0': 'normal', '1': 'invulnerable', '2': 'intangible'},
        'interpretation_limit': 'Fields are reported independently; no total-body intangibility verdict is derived.',
    }
