"""Read-only NTSC 1.02 fighter pose/visibility capture.

Call while the debugger is frozen. Multiple reads are not an atomic snapshot.
Layouts: melee ft/types.h, ft/dobjlist.h, baselib/jobj.h and baselib/dobj.h.
The caller supplies the proven rig count; FighterBone has no inline count.
"""
import math
import struct

POSE_SCHEMA = 'hsd-jobj-local-srt-v2-xyz'
USE_QUATERNION = 0x20000
JOBJ_MTX_DIRTY = 1 << 6
MEM1_START, MEM1_END = 0x80000000, 0x81800000


class CaptureError(ValueError):
    """Required memory was absent, malformed, or outside MEM1."""


def validate_captured_worlds(joints, expected_count):
    """Validate an offline serialized world table before numerical comparisons.

    JSON input is not trusted merely because the live reader validates memory.
    In particular, NaN residuals must not pass a comparison by returning False.
    This checks world matrices and ordering only, not local-pose semantics.
    """
    if type(expected_count) is not int or expected_count <= 0:
        raise CaptureError('Positive exact joint count required')
    if not isinstance(joints, list) or len(joints) != expected_count:
        raise CaptureError('Incomplete serialized world table')
    for index, joint in enumerate(joints):
        if not isinstance(joint, dict) or type(joint.get('index')) is not int or joint['index'] != index:
            raise CaptureError('Serialized joints must have exact ordered indices')
        world = joint.get('world')
        if not isinstance(world, list) or len(world) != 12 or any(
                type(value) not in (int, float) or not math.isfinite(value) for value in world):
            raise CaptureError('Finite row-major 3x4 cached matrix required')
    return joints


def _read(d, address, size):
    if (not isinstance(address, int) or address % 4 or
            not MEM1_START <= address <= MEM1_END - size):
        raise CaptureError(f'Invalid MEM1 read: {address!r}, {size} bytes')
    raw = d.bytes(address, size)
    if raw is None or len(raw) != size:
        raise CaptureError(f'Short MEM1 read at {address:#x}: expected {size}')
    return raw


def _word(d, address):
    return struct.unpack('>I', _read(d, address, 4))[0]


def _fighter(address):
    if (type(address) is not int or address % 4 or
            not MEM1_START <= address <= MEM1_END - 0x2220):
        raise CaptureError(f'Invalid or unresolved fighter: {address!r}')


def _floats(raw, offset, count, label):
    values = list(struct.unpack_from('>' + 'f' * count, raw, offset))
    if not all(math.isfinite(v) for v in values):
        raise CaptureError(f'Nonfinite {label}')
    return values


def _joint(d, pointer):
    raw = _read(d, pointer, 0x80)
    flags = struct.unpack_from('>I', raw, 0x14)[0]
    # The fourth rotation word is unused storage for Euler joints, not an angle.
    rotation = list(struct.unpack_from('>4f', raw, 0x1c))
    used = rotation if flags & USE_QUATERNION else rotation[:3]
    if not all(math.isfinite(v) for v in used):
        raise CaptureError('Nonfinite active joint rotation')
    aobj = struct.unpack_from('>I', raw, 0x7c)[0]
    frame = _floats(_read(d, aobj, 8), 4, 1, 'AObj frame')[0] if aobj else None
    return {
        'pointer': pointer, 'flags': flags,
        # HSD lazily sets up world matrices. This is a raw diagnostic bit, not
        # proof that the cache is stale (or that a clear cache is correct).
        'matrix_dirty': bool(flags & JOBJ_MTX_DIRTY),
        'rotation_kind': 'quaternion_xyzw' if flags & USE_QUATERNION else 'euler_xyz',
        'rotation_xyz': rotation[:3],
        'rotation_xyzw': [v if math.isfinite(v) else None for v in rotation],
        'rotation_words': list(struct.unpack_from('>4I', raw, 0x1c)),
        'scale': _floats(raw, 0x2c, 3, 'scale'),
        'translation': _floats(raw, 0x38, 3, 'translation'),
        'world': _floats(raw, 0x44, 12, 'world matrix'),
        'aobj_frame': frame,
    }


def capture_pose(d, fighter, joint_count, *, secondary=False):
    """Capture full local SRT/world matrices without interpreting game state.

    Null secondary joints/AObjs are represented by None. Invalid non-null
    pointers fail; they are never silently treated as missing animation.
    Quaternion storage is preserved without relabelling it as Euler angles.
    World matrices are cached engine values: a late state change can update
    local SRT before all caches refresh. Keep matrix_dirty and adjacent samples;
    do not silently recompute, discard, or accept a mismatching world matrix.
    """
    _fighter(fighter)
    if type(joint_count) is not int or not 1 <= joint_count <= 4096:
        raise CaptureError('joint_count must be a verified count in 1..4096')
    table = _word(d, fighter + 0x5e8)
    parts = _read(d, table, 16 * joint_count)
    joints = []
    for index in range(joint_count):
        primary, overlay = struct.unpack_from('>II', parts, 16 * index)
        joint = _joint(d, primary)
        joint.update(index=index, part_flags=parts[16 * index + 8])
        if secondary:
            joint['overlay'] = _joint(d, overlay) if overlay else None
        joints.append(joint)
    return {'schema': POSE_SCHEMA, 'joint_count': joint_count, 'parts_table': table,
            'anim_frame_raw': _floats(_read(d, fighter + 0x894, 4), 0, 1, 'animation frame')[0],
            'joints': joints}


def capture_visibility(d, fighter, *, expected_count=None, max_objects=4096):
    """Capture model-part selection and DObj flags; does not judge visibility.

    Render passes can transiently hide every DObj. A visibility verdict needs
    draw-phase witnesses/images as well as these raw fields.
    """
    _fighter(fighter)
    if type(max_objects) is not int or not 0 <= max_objects <= 4096:
        raise CaptureError('max_objects must be in 0..4096')
    raw = _read(d, fighter + 0x5ac, 0x60)
    count, table = struct.unpack_from('>II', raw, 0x40)
    if not 0 <= count <= max_objects or (expected_count is not None and count != expected_count):
        raise CaptureError(f'Unexpected DObj count {count}, expected {expected_count}')
    pointers = _read(d, table, 4 * count) if count else b''
    objects = []
    for index in range(count):
        pointer = struct.unpack_from('>I', pointers, 4 * index)[0]
        flags = _word(d, pointer + 0x14)
        objects.append({'index': index, 'pointer': pointer, 'flags': flags,
                        'hidden': bool(flags & 1)})
    bits = _read(d, fighter + 0x221c, 4)
    return {'schema': 'ft-parts-vis-v1', 'dobj_count': count, 'dobj_table': table,
            'model_count': struct.unpack_from('>I', raw)[0],
            'cleared': list(raw[4:9]),
            'lookups': list(struct.unpack_from('>5I', raw, 0xc)),
            'states': [{'prev_raw': raw[0x48+2*i], 'idx_raw': raw[0x49+2*i]}
                       for i in range(12)],
            'flags_221d': bits[1], 'flags_221e': bits[2],
            'model_override': bool(bits[1] & 0x20),
            'whole_model_invisible': bool(bits[2] & 0x84), 'objects': objects}
