"""A fighter's skeleton as the retarget's rig JSON, read straight from its
costume DAT. No Blender and no model export: the rig file only holds joint
order, parents and rest transforms, and those are in the JObj tree.

    python -m fighter_port.dat_rig PlMsNr.dat Marth.joints.json

Joint names are JOBJ_<n> in tree order (self, child, then sibling), the same
numbering HSDRawViewer's animation import and the fighter's bone table use.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path


def _parse(b):
    fs, ds, rc, rtc, xc = struct.unpack('>IIIII', b[:20])
    data = b[0x20:0x20 + ds]
    p = 0x20 + ds
    relocs = set(struct.unpack('>%dI' % rc, b[p:p + rc * 4]))
    p += rc * 4
    roots = [struct.unpack('>II', b[p + i * 8:p + i * 8 + 8]) for i in range(rtc)]
    strs = b[p + (rtc + xc) * 8:]
    return data, relocs, [(o, strs[s:strs.index(b'\0', s)].decode()) for o, s in roots]


def read_joints(path):
    """[{name, parent, t, r, s}] in tree order from a costume DAT's model root."""
    data, relocs, roots = _parse(Path(path).read_bytes())
    root = next(o for o, n in roots if n.endswith('_joint') and 'matanim' not in n and 'shapeanim' not in n)

    def ptr(o):
        v = struct.unpack_from('>I', data, o)[0]
        return v if (v or o in relocs) else None

    out = []
    stack = [(root, None)]
    while stack:
        j, parent = stack.pop()
        while j is not None:
            v = struct.unpack_from('>9f', data, j + 0x14)
            name = f'JOBJ_{len(out)}'
            out.append({'name': name, 'parent': parent, 'r': list(v[0:3]), 's': list(v[3:6]), 't': list(v[6:9])})
            sibling = ptr(j + 0xC)
            if sibling is not None:
                stack.append((sibling, parent))
            j, parent = ptr(j + 8), name
    return out


def rig_json(path):
    joints = read_joints(path)
    return {'order': [j['name'] for j in joints],
            'parent': {j['name']: j['parent'] for j in joints},
            'rename': {j['name']: j['name'] for j in joints},
            'rest': {j['name']: {'t': j['t'], 'r': j['r'], 's': j['s']} for j in joints}}


def write(dat, out):
    rig = rig_json(dat)
    Path(out).write_text(json.dumps(rig, indent=1), encoding='utf-8')
    return rig


if __name__ == '__main__':
    r = write(sys.argv[1], sys.argv[2])
    print(len(r['order']), 'joints ->', sys.argv[2])
