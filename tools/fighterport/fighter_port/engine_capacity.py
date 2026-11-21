"""Read GALE01 allocation sites before attempting a reordered fighter rig.

This is a static DOL measurement, not an emulator or Gecko interpreter. A
recognized immediate is useful evidence only with its surrounding instructions.
Runtime patches, allocator behavior and other engine consumers remain unproven.
"""
import argparse
import hashlib
import struct
from pathlib import Path

from .workbench import fingerprint, check_pins, write_new


class DolImage:
    def __init__(self, data):
        if len(data) < 0x100:
            raise ValueError('Truncated DOL header')
        self.data = bytes(data)
        self.sections = []
        for index in range(18):
            offset, address, size = (struct.unpack_from('>I', data, base + index * 4)[0]
                                     for base in (0, 0x48, 0x90))
            if not size:
                continue
            if offset < 0x100 or offset + size > len(data) or address + size > 0x100000000:
                raise ValueError('DOL section outside file or address space')
            for old in self.sections:
                if max(offset, old['offset']) < min(offset + size, old['offset'] + old['size']):
                    raise ValueError('Overlapping DOL file sections')
                if max(address, old['address']) < min(address + size, old['address'] + old['size']):
                    raise ValueError('Overlapping DOL memory sections')
            self.sections.append(dict(offset=offset, address=address, size=size, text=index < 7))

    def code(self, address, size):
        if type(address) is not int or type(size) is not int or address % 4 or size <= 0 or size % 4:
            raise ValueError('Aligned nonempty instruction span required')
        spans = [s for s in self.sections if s['text'] and
                 s['address'] <= address and address + size <= s['address'] + s['size']]
        if len(spans) != 1:
            raise ValueError('Instruction span not contained in one executable section')
        start = spans[0]['offset'] + address - spans[0]['address']
        return self.data[start:start + size]


# Source bindings: fighter.c:Fighter_800679B0, ftparts.c:ftParts_SetupParts,
# ft/types.h:ASSERT_SIZE(FighterBone, 0x10). ABI/profile is explicitly GALE01.
SITES = {
    'parts_allocation_bytes': (0x80067A04, [0x387F0058, 0x38800000, 0x38A00004, 0x48313339], 1, 16),
    'dobj_allocation_bytes': (0x80067A14, [0x387F0084, 0x38800000, 0x38A00004, 0x48313329], 1, 4),
    'parts_setup_limit': (0x80074420, [0x80030008, 0x28000000, 0x408101A4], 1, 1),
}


def measure_dol(data):
    return measure_code(DolImage(data).code)


def measure_code(read):
    result = {}
    for name, (address, expected, variable, stride) in SITES.items():
        raw = read(address, len(expected) * 4)
        if len(raw) != len(expected) * 4:
            raise ValueError('Short capacity code read')
        words = list(struct.unpack('>' + 'I' * len(expected), raw))
        masked = words[:]
        masked[variable] &= 0xFFFF0000
        if masked != expected:
            raise ValueError(f'Unrecognized GALE01 capacity site: {name}')
        value = words[variable] & 0xFFFF
        # Allocation li is signed; the setup cmplwi is unsigned.
        if not value or (stride != 1 and value >= 0x8000) or value % stride:
            raise ValueError(f'Invalid size/stride at {name}')
        result[name] = dict(address=f'0x{address:08x}', words=[f'{w:08x}' for w in words],
                            value=value, stride=stride, count=value // stride)
    return dict(profile='GALE01-static-capacity-v1', sites=result,
                joint_capacity=min(result['parts_allocation_bytes']['count'], result['parts_setup_limit']['count']),
                dobj_capacity=result['dobj_allocation_bytes']['count'])


def decode_allocator(raw, stride):
    if len(raw) != 0x2C or type(stride) is not int or stride <= 0:
        raise ValueError('Full allocator descriptor and positive stride required')
    used, size, mask = (struct.unpack_from('>I', raw, offset)[0] for offset in (8, 0x20, 0x24))
    # HSD_ObjAllocInit stores align-1, then rounds size with that mask.
    alignment = mask + 1
    valid = bool(size and size % stride == 0 and alignment <= 0x80000000 and
                 alignment & (alignment-1) == 0 and size % alignment == 0)
    return dict(raw=raw.hex(), used=used, size=size, alignment_mask=mask, alignment=alignment,
                stride=stride, count=size//stride if valid else None,
                status='INITIALIZED_DESCRIPTOR' if valid else 'INVALID_OR_UNINITIALIZED')


def extend_parts_capacity(data, joints):
    """Prepare a standalone capacity experiment; never installs or accepts a rig.

    Only the recognized 140-record GALE01 profile is an allowed input. Both
    allocation and setup guard change together. Other limits remain unchanged.
    """
    if type(joints) is not int or not 140 < joints <= 255:
        raise ValueError('Capacity experiment requires 141..255 joints')
    before = measure_dol(data)
    if before['sites']['parts_allocation_bytes']['count'] != 140 or before['sites']['parts_setup_limit']['count'] != 140:
        raise ValueError('Unmodified 140-part profile required')
    image = DolImage(data)
    output = bytearray(data)
    changes = []
    for address, word in ((0x80067A08, 0x38800000 | joints*16), (0x80074424, 0x28000000 | joints)):
        original = image.code(address, 4)
        section = next(s for s in image.sections if s['text'] and s['address'] <= address < s['address']+s['size'])
        offset = section['offset'] + address-section['address']
        replacement = struct.pack('>I', word)
        output[offset:offset+4] = replacement
        changes.append(dict(address=f'0x{address:08x}', offset=offset, before=original.hex(), after=replacement.hex()))
    after = measure_dol(output)
    if after['joint_capacity'] != joints or after['dobj_capacity'] != before['dobj_capacity']:
        raise ValueError('Capacity patch readback differs')
    changed = [i for i, (a,b) in enumerate(zip(data,output)) if a != b]
    allowed = {c['offset']+i for c in changes for i in range(4)}
    if set(changed)-allowed:
        raise ValueError('Unrelated DOL bytes changed')
    return bytes(output), dict(schema='mocap-capacity-experiment-v1', status='PREPARED_NATIVE_UNTESTED',
        input_sha256=hashlib.sha256(data).hexdigest(), output_sha256=hashlib.sha256(output).hexdigest(),
        requested_joints=joints, changes=changes, changed_bytes=len(changed), native_ready=False,
        scope='Two static instructions only. Other consumers, rig mapping, and increased-count fighters are unvalidated.')


ANIMATION_GUARD_ADDRESS = 0x8006F578
ANIMATION_GUARD_WORDS = [0x2C1A0000, 0x41800024, 0x8897000C, 0x387E0000,
                       0x4CC63182, 0x482D611D, 0x387F0000, 0x388002FF,
                       0x38AD8378, 0x48318C85, 0x801705E8]


def animation_binding_limit(read):
    """ftAnim_8006F4C8 signed index guard, including its assertion call context."""
    raw=read(ANIMATION_GUARD_ADDRESS,4*len(ANIMATION_GUARD_WORDS))
    if len(raw)!=4*len(ANIMATION_GUARD_WORDS):raise ValueError('Short animation guard read')
    words=list(struct.unpack('>'+str(len(ANIMATION_GUARD_WORDS))+'I',raw))
    count=words[0]&0xffff;words[0]&=0xffff0000
    if words!=ANIMATION_GUARD_WORDS or not 1<=count<=255:
        raise ValueError('Unrecognized animation binding guard')
    return dict(address=f'0x{ANIMATION_GUARD_ADDRESS:08x}',count=count,raw=raw.hex())


def measure_rig_limits(data):
    allocation=measure_dol(data);binding=animation_binding_limit(DolImage(data).code)
    return dict(schema='GALE01-rig-limits-v2-animation-binding',allocation=allocation,
        animation_binding=binding,joint_capacity=min(allocation['joint_capacity'],binding['count']),
        dobj_capacity=allocation['dobj_capacity'],native_accepted=False)


def extend_rig_capacity(data,joints):
    """Grow allocation, setup and animation binding together; retain the guards.

    The older two-word capacity experiment intentionally remains reproducible.
    Its profile is insufficient for a new rig whose animations exceed 140 nodes.
    """
    binding=animation_binding_limit(DolImage(data).code)
    if binding['count']!=140:raise ValueError('Original 140-node animation guard required')
    output,receipt=extend_parts_capacity(data,joints)
    image=DolImage(data);address=ANIMATION_GUARD_ADDRESS
    section=next(s for s in image.sections if s['text'] and s['address']<=address<s['address']+s['size'])
    offset=section['offset']+address-section['address'];patched=bytearray(output)
    replacement=struct.pack('>I',0x2C1A0000|joints);patched[offset:offset+4]=replacement
    changes=receipt['changes']+[dict(address=f'0x{address:08x}',offset=offset,before=image.code(address,4).hex(),after=replacement.hex())]
    allowed={c['offset']+i for c in changes for i in range(4)}
    if any(a!=b and i not in allowed for i,(a,b) in enumerate(zip(data,patched))):raise ValueError('Unrelated capacity bytes changed')
    if measure_rig_limits(patched)['joint_capacity']!=joints:raise ValueError('Combined rig limit differs')
    return bytes(patched),dict(receipt,schema='mocap-rig-capacity-experiment-v2',changes=changes,
        output_sha256=hashlib.sha256(patched).hexdigest(),changed_bytes=sum(a!=b for a,b in zip(data,patched)),
        scope='Three bounded instructions: allocation, setup and animation binding. Other runtime consumers unaccepted.')


def assess(data, *, joints, dobjs=None, gct=None):
    if type(joints) is not int or joints <= 0 or (dobjs is not None and (type(dobjs) is not int or dobjs < 0)):
        raise ValueError('Measured positive joint count and optional nonnegative DObj count required')
    measured = measure_dol(data)
    failures = []
    if joints > measured['joint_capacity']:
        failures.append('joints_exceed_static_allocation_or_setup_limit')
    if joints > 255:
        failures.append('joints_exceed_byte_lookup_with_255_sentinel')
    if dobjs is not None and dobjs > measured['dobj_capacity']:
        failures.append('dobjs_exceed_static_allocation')
    patches = dict(status='NOT_SUPPLIED')
    if gct is not None:
        if len(gct) < 16 or len(gct) % 8 or gct[:8] != bytes.fromhex('00d0c0de00d0c0de') or gct[-8:] != bytes.fromhex('f000000000000000'):
            raise ValueError('Malformed GCT envelope')
        patches = dict(status='ENVELOPE_ONLY_RUNTIME_EFFECTS_UNRESOLVED', bytes=len(gct),
                       sha256=hashlib.sha256(gct).hexdigest())
    return dict(schema='mocap-engine-capacity-v1',
                status='STATIC_CAPACITY_EXCEEDED' if failures else 'WITHIN_MEASURED_STATIC_CAPACITY',
                requested=dict(joints=joints, dobjs=dobjs), measured=measured, failures=failures,
                runtime_patches=patches, native_ready=False,
                unresolved=['live allocation and setup code including runtime hooks',
                            'actual runtime JObj and DObj counts', 'other engine consumer limits'],
                scope='Static sites only; DObj descriptor count is not a live draw-list count. No patch execution is inferred.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dol', type=Path, required=True)
    parser.add_argument('--gct', type=Path)
    parser.add_argument('--joints', type=int, required=True)
    parser.add_argument('--dobjs', type=int)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    pins = {name: fingerprint(path) for name, path in dict(dol=args.dol, gct=args.gct, implementation=__file__).items() if path is not None}
    result = assess(args.dol.read_bytes(), joints=args.joints, dobjs=args.dobjs,
                    gct=args.gct.read_bytes() if args.gct else None)
    result['inputs'] = pins
    check_pins(pins)
    write_new(args.out, result)
    print(result['status'])


if __name__ == '__main__':
    main()
