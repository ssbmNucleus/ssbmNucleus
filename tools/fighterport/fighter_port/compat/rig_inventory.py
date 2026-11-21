"""Read-only costume and animation-bank inventory before choosing a rig strategy.

Reads HSD_Joint/HSD_DObjDesc layouts (jobj.h/dobj.h), not runtime HSD_JObj.
Counts are file-derived, not proof of the runtime parts table or visibility list.
Instances and non-DObj joint unions are refused rather than counted as meshes.
No imports from character pilots, no encoding, no emulator, no asset mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
from pathlib import Path

from vault.echo import subactions


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Archive(subactions.Dat):
    """Bounds-checked container for the specific structures walked below."""

    def __init__(self, data):
        if len(data) < 32:
            raise ValueError('Truncated DAT header')
        size, extent, relocations, roots, refs = struct.unpack_from('>5I', data)
        tables_end = 32 + extent + 4 * relocations + 8 * (roots + refs)
        if size != len(data) or tables_end > len(data):
            raise ValueError('DAT extent or tables outside file')
        for i in range(relocations):
            slot = struct.unpack_from('>I', data, 32 + extent + 4 * i)[0]
            if slot % 4 or slot + 4 > extent:
                raise ValueError('Relocation slot outside data or unaligned')
        try:
            super().__init__(data)
        except (ValueError, struct.error, IndexError) as error:
            raise ValueError('Malformed DAT tables') from error
        if len(self.relocs) != relocations:
            raise ValueError('Duplicate relocation slot')
        for _, root in self.roots:
            self.require(root, 1)

    def require(self, offset, length):
        if type(offset) is not int or offset < 0 or offset + length > self.data_size:
            raise ValueError('Structure outside DAT data')

    def ptr(self, offset):
        self.require(offset, 4)
        value = self.u32(offset)
        if offset not in self.relocs:
            if value:
                raise ValueError('Non-null pointer missing relocation')
            return None
        self.require(value, 1)
        return value


def costume_inventory(payload, root_name=None):
    dat = Archive(payload)
    roots = [(name, offset) for name, offset in dat.roots
             if name.endswith('_joint') and not name.endswith(('_matanim_joint', '_anim_joint', '_shapeanim_joint'))]
    if root_name is not None:
        roots = [(name, offset) for name, offset in roots if name == root_name]
    if len(roots) != 1:
        raise ValueError('Exactly one explicitly selected costume joint root required')
    name, root = roots[0]
    joints, seen, dobjs = [], set(), set()
    pending = [(root, None)]
    while pending:
        offset, parent = pending.pop()
        if offset in seen:
            raise ValueError('Repeated/cyclic joint; instance expansion unsupported')
        seen.add(offset)
        dat.require(offset, 0x40)
        flags = dat.u32(offset + 4)
        if flags & ((1 << 5) | (1 << 12) | (1 << 14)):
            raise ValueError('Particle, instance or spline joint requires a separate reader')
        values = [dat.f32(offset + 0x14 + 4 * i) for i in range(9)]
        if not all(math.isfinite(v) for v in values):
            raise ValueError('Non-finite joint rest transform')
        objects = []
        dobj = dat.ptr(offset + 0x10)
        while dobj is not None:
            if dobj in dobjs:
                raise ValueError('Repeated/cyclic DObj descriptor')
            dobjs.add(dobj)
            dat.require(dobj, 16)
            objects.append(dobj)
            dobj = dat.ptr(dobj + 4)
        index = len(joints)
        joints.append(dict(index=index, offset=offset, parent=parent, flags=flags,
                           rotation=values[:3], scale=values[3:6], translation=values[6:],
                           dobj_offsets=objects))
        sibling, child = dat.ptr(offset + 12), dat.ptr(offset + 8)
        if sibling is not None:
            pending.append((sibling, parent))
        if child is not None:
            pending.append((child, index))
    return dict(sha256=sha(payload), bytes=len(payload), root=name,
                joint_count=len(joints), dobj_descriptor_count=len(dobjs), joints=joints,
                scope='File descriptor topology and rest SRT only; no skin, runtime count or compatibility pass.')


def compare_costumes(baseline, candidate):
    """Index comparison, deliberately not an anatomical correspondence guess."""
    old, new = baseline['joints'], candidate['joints']
    common = min(len(old), len(new))
    changed_parent = [i for i in range(common) if old[i]['parent'] != new[i]['parent']]
    changed_rest = [i for i in range(common)
                    if any(old[i][k] != new[i][k] for k in ('rotation', 'scale', 'translation'))]
    return dict(common_indices=common, baseline_joint_count=len(old), candidate_joint_count=len(new),
                parent_changed_indices=changed_parent, rest_changed_indices=changed_rest,
                additional_candidate_indices=list(range(len(old), len(new))),
                removed_baseline_indices=list(range(len(new), len(old))),
                baseline_index_topology_preserved=len(new) >= len(old) and not changed_parent,
                inherited_animation_compatibility='UNMEASURED',
                scope='Same-index comparison only. Equal topology does not imply equal anatomy or compatible animation.')


def bank_inventory(pl, aj):
    dat = Archive(pl)
    if sum(name.startswith('ftData') for name, _ in dat.roots) != 1:
        raise ValueError('Exactly one ftData root required')
    fighter = subactions.FighterDat(pl)
    table, count = fighter.action_table
    if table is None or not count:
        raise ValueError('Missing action table')
    rows = []
    for row in fighter.actions:
        item = dict(action=row.index, motion=row.motion, symbol=row.symbol,
                    flags=row.flags, flags2=row.flags2, script_offset=row.script_offset,
                    offset=row.anim_offset, bytes=row.anim_size)
        if row.anim_size == 0:
            item['archive_status'] = 'ABSENT'
        else:
            start, size = row.anim_offset, row.anim_size
            if start + size > len(aj):
                raise ValueError(f'Action {row.index} archive outside AJ')
            blob = aj[start:start + size]
            archive = Archive(blob)
            if (row.symbol not in dict(archive.roots)
                    or len({off for _,off in archive.roots}) != 1):
                raise ValueError(f'Action {row.index} archive symbol mismatch')
            root = archive.roots[0][1]
            archive.require(root, 12)
            end = archive.f32(root + 8)
            if not math.isfinite(end) or end < 0:
                raise ValueError(f'Action {row.index} invalid frame header')
            item.update(archive_status='PRESENT', archive_end=end, sha256=sha(blob))
        rows.append(item)
    return dict(pl_sha256=sha(pl), aj_sha256=sha(aj), action_count=len(rows),
                archive_rows=sum(r['archive_status'] == 'PRESENT' for r in rows), rows=rows,
                scope='Stored action inventory, not reachable-state coverage, source fidelity or native lifetime.')


def build_report(costume, pl, aj, *, baseline_costume=None, joint_root=None):
    result = dict(schema='mocap-rig-inventory-v1', status='INVENTORIED_NOT_GAME_ACCEPTED',
                  costume=costume_inventory(costume, joint_root), bank=bank_inventory(pl, aj))
    if baseline_costume is not None:
        result['baseline_costume'] = costume_inventory(baseline_costume, joint_root)
        result['same_index_comparison'] = compare_costumes(result['baseline_costume'], result['costume'])
    result['implementation_sha256'] = {
        str(Path(p).resolve()): sha(Path(p).read_bytes()) for p in (__file__, subactions.__file__)
    }
    result['unmeasured'] = ['semantic bone lookup', 'skin weights and bind compatibility',
                            'hitbox/hurtbox/ECB attachments', 'effects/items/grabs',
                            'procedural bone ownership', 'animation fidelity and complete gameplay coverage']
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('costume', 'pl', 'aj', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--baseline-costume', type=Path)
    parser.add_argument('--joint-root')
    args = parser.parse_args(argv)
    if args.out.exists():
        raise ValueError('Refusing to overwrite an inventory receipt')
    paths = {key: getattr(args, key) for key in ('costume', 'pl', 'aj', 'baseline_costume') if getattr(args, key)}
    snapshots = {key: path.read_bytes() for key, path in paths.items()}
    report = build_report(**snapshots, joint_root=args.joint_root)
    report['inputs'] = {key: dict(path=str(path.resolve()), sha256=sha(snapshots[key])) for key, path in paths.items()}
    if any(path.read_bytes() != snapshots[key] for key, path in paths.items()):
        raise ValueError('Input changed during inventory')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(status=report['status'], joints=report['costume']['joint_count'],
                          dobjs=report['costume']['dobj_descriptor_count'], actions=report['bank']['action_count'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
