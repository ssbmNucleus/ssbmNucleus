"""Prepare a static imported costume for the donor's required texture slots.

Only costume DATs are rewritten. Fighter scripts and relocation layout remain
untouched. A static material shim satisfies blink writes without restoring the
donor's face textures onto unrelated imported geometry.
"""
from pathlib import Path
import json
import struct
import subprocess

from vault.echo.datroot import parse, build
from shared.rendering.datprobe import DatFile
from shared.rendering.lowpoly_promote import _walk_matanim_joints, blink_indices, verify_blink
from .provenance import fingerprint


def add_empty_material_tree(payload):
    """Create a matching empty material-animation tree for a new skeleton.

    A neutral texture-animation shim requires a real matanim tree to attach to.
    Existing material trees are refused; original costume data stays byte-exact.
    """
    from .compat.rig_inventory import costume_inventory, Archive
    model=costume_inventory(payload);archive=Archive(payload)
    if any(n.endswith('_matanim_joint') for n,_ in archive.roots):
        raise ValueError('Costume already has a material-animation tree')
    data,relocs,roots,refs=parse(payload);before=data;data=bytearray(data)
    data.extend(bytes((-len(data))%32));base=len(data)
    joints=model['joints'];offsets={j['offset']:base+i*16 for i,j in enumerate(joints)}
    data.extend(bytes(len(joints)*16))
    for i,joint in enumerate(joints):
        for old_slot,new_slot in ((8,0),(12,4)):
            target=archive.ptr(joint['offset']+old_slot)
            if target is not None:
                if target not in offsets:raise ValueError('Material tree link outside skeleton')
                slot=base+i*16+new_slot;struct.pack_into('>I',data,slot,offsets[target]);relocs.append(slot)
    symbol=model['root'].removesuffix('_joint')+'_matanim_joint'
    result=build(data,relocs,roots+[(base,symbol)],refs)
    if result[32:32+len(before)]!=before:raise ValueError('Original costume data changed')
    return result,dict(status='EMPTY_MATERIAL_TREE_SHIMS_REQUIRED',joints=len(joints),symbol=symbol,
                       original_data_bytes_preserved=len(before),native_accepted=False)


def static_materials(costume, fighter, joint_symbol, out, hsdraw):
    costume, fighter, out, hsdraw = map(Path, (costume, fighter, out, hsdraw))
    if out.exists():
        raise ValueError('choose a new costume output')
    data, relocs, roots, xrefs = parse(costume.read_bytes())
    if any(name.startswith('ftData') for _, name in roots):
        raise ValueError('expected a costume, not a fighter DAT')
    material_symbol = joint_symbol.removesuffix('_joint') + '_matanim_joint'
    mat_roots = [(o,n) for o,n in roots if n.endswith('_matanim_joint')]
    if len(mat_roots) != 1 or joint_symbol not in dict((n,o) for o,n in roots):
        raise ValueError('expected one model and one material-animation tree')
    probe = DatFile(costume)
    nodes = _walk_matanim_joints(probe, mat_roots[0][0])
    mutable = bytearray(data)
    # The importer restores donor joint flags, but imported alpha-cutout
    # materials may need a render pass the donor did not use at that joint.
    # HSD's XLU materials with full material alpha also render as TEXEDGE.
    # Preserve skeleton/physics flags and add only the missing draw bits.
    flag_changes = []
    def visit(joint):
        if joint is None:
            return False
        flags = probe.u32(joint+4)
        own = False
        if not flags & ((1 << 5) | (1 << 14)):
            dobj = probe.ptr(joint+16)
            while dobj is not None:
                mat = probe.ptr(dobj+8)
                own |= mat is not None and bool(probe.u32(mat+4) & (1 << 30))
                dobj = probe.ptr(dobj+4)
        child = visit(probe.ptr(joint+8)) if not flags & (1 << 12) else False
        updated = flags | ((1 << 20) if own else 0) | ((1 << 30) if child else 0)
        if updated != flags:
            struct.pack_into('>I',mutable,joint+4,updated)
            flag_changes.append({'offset':joint,'before':flags,'after':updated})
        sibling = visit(probe.ptr(joint+12))
        return own or child or sibling
    visit(next(o for o,n in roots if n == joint_symbol))
    removed = {node+8 for node in nodes}
    for slot in removed:
        struct.pack_into('>I',mutable,slot,0)
    roots = [(o, material_symbol if (o,n) == mat_roots[0] else n) for o,n in roots]
    out.parent.mkdir(parents=True,exist_ok=True)
    blank = out.with_suffix('.blank-materials.dat')
    blank.write_bytes(build(mutable,[r for r in relocs if r not in removed],roots,xrefs))
    required = blink_indices(fighter)
    # The existing tool also supports shims alone: invalid promotion indices
    # are filtered before any swaps, leaving geometry/DObj ordering intact.
    args = [str(hsdraw),'--promote-lowpoly',str(blank),joint_symbol,
            '-1','-1','-','-1',str(out),','.join(f'{i}:8' for i in required)]
    p = subprocess.run(args,capture_output=True,text=True,timeout=180)
    out.with_suffix('.materials.log').write_text(p.stdout+p.stderr)
    if p.returncode or not out.exists() or not verify_blink(out,required):
        raise RuntimeError('static costume failed donor texture-animation validation; inspect materials log')
    report = {'schema':1,'input':fingerprint(costume),'fighter':fingerprint(fighter),
              'output':fingerprint(out),'required_texture_indices':required,
              'joint_symbol':joint_symbol,'material_symbol':material_symbol,
              'render_flag_changes':flag_changes,
              'policy':'static materials; neutral texture-animation shims; no donor facial textures',
              'code':fingerprint(Path(__file__)),'tool':fingerprint(hsdraw)}
    out.with_suffix('.materials.json').write_text(json.dumps(report,indent=2))
    return report
