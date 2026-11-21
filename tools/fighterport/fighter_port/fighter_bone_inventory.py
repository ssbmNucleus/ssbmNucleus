"""Bounds-checked direct-index census of selected ftData consumer structures.

This intentionally does not infer semantic lookup IDs, collision coordinates,
scripts, or runtime callback references from anatomy names.
"""
import struct
import math

from .compat.rig_inventory import Archive


def direct_bone_inventory(payload, joint_count, *, root_name):
    if type(joint_count) is not int or joint_count <= 0:
        raise ValueError('Measured joint count required')
    dat = Archive(payload)
    roots = [offset for name, offset in dat.roots if name == root_name]
    if len(roots) != 1:
        raise ValueError('Exactly one selected fighter root required')
    root = roots[0]
    dat.require(root, 0x60)
    references = []
    absent = []
    hurtboxes = []

    def index(name, offset, width=4):
        dat.require(offset, width)
        value = struct.unpack_from('>i' if width == 4 else '>h', payload, 32 + offset)[0]
        if not 0 <= value < joint_count:
            raise ValueError(f'Out-of-range direct joint index: {name}={value}')
        references.append(dict(consumer=name, offset=offset, width=width, joint=value,
                               status='MEASURED_CURRENT_INDEX_TARGET_UNRESOLVED'))

    for name, slot, size in [('center', 0x34, 8), ('ecb', 0x44, 0x1C), ('special', 0x54, 0x14)]:
        pointer = dat.ptr(root + slot)
        if pointer is None:
            absent.append(name)
            continue
        dat.require(pointer, size)
        if name == 'center':
            index(name, pointer)
        elif name == 'ecb':
            for i in range(6):
                index(f'ecb[{i}]', pointer + i * 2, 2)
        else:
            for i, label in enumerate(('head', 'right_arm', 'left_leg', 'right_leg', 'left_arm')):
                index(f'special.{label}', pointer + i * 4)
    bank = dat.ptr(root + 0x30)
    if bank is None:
        absent.append('hurtboxes')
    else:
        dat.require(bank, 8)
        count = dat.u32(bank)
        if count > 15:
            raise ValueError('Hurtbox count exceeds the native 15-capsule array')
        array = dat.ptr(bank + 4)
        if count and array is None:
            raise ValueError('Nonempty hurtbox bank has no array')
        if array is not None:
            dat.require(array, count * 0x28)
            for i in range(count):
                index(f'hurtbox[{i}]', array + i * 0x28)
                offset = array + i * 0x28
                values = [dat.f32(offset + 0xC + k * 4) for k in range(7)]
                if not all(math.isfinite(v) for v in values) or values[-1] < 0:
                    raise ValueError('Nonfinite or negative hurtbox geometry')
                hurtboxes.append(dict(consumer=f'hurtbox[{i}]',joint=dat.u32(offset),
                    height=dat.u32(offset+4),grabbable=dat.u32(offset+8),a=values[:3],b=values[3:6],radius=values[6]))
    return dict(schema='mocap-direct-bones-v1', status='PARTIAL_CONSUMER_CENSUS', root=root_name,
                joint_count=joint_count, references=references, hurtboxes=hurtboxes, absent=absent, native_ready=False,
                unresolved=['semantic lookup', 'scripts and hitboxes', 'coin collision arrays',
                            'dynamics', 'IK', 'items and articles', 'effects', 'visibility and materials',
                            'callbacks', 'root motion', 'animation coverage',
                            'target bone mapping and collision coordinate conversion'])
