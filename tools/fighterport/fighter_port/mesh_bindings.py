"""Read actual drawable skinning references before pruning or replacing a rig.

Inventories PObj binding descriptors, not display-list usage or deformed vertices.
Every referenced joint is retained conservatively, including zero-weight entries.
"""
import argparse
import math
import struct
from pathlib import Path
from .compat.rig_inventory import Archive,costume_inventory
from .workbench import fingerprint,check_pins,write_new


def inventory(payload,*,root_name=None,weight_sum_tolerance=1e-4):
    if type(weight_sum_tolerance) not in (float,int) or not math.isfinite(weight_sum_tolerance) or not 0<=weight_sum_tolerance<=.001:
        raise ValueError('Explicit weight tolerance in 0..0.001 required')
    dat=Archive(payload);model=costume_inventory(payload,root_name)
    indices={row['offset']:row['index'] for row in model['joints']}
    objects={};drawables=[];envelopes={};referenced=set();weighted=set();unresolved=[]

    def joint(offset):
        if offset not in indices:raise ValueError('Mesh references a joint outside the selected skeleton')
        return indices[offset]

    def envelope(offset):
        if offset in envelopes:return envelopes[offset]
        rows=[];slot=offset;end=dat.struct_end(offset)
        while True:
            if slot+4>end:raise ValueError('Unterminated envelope before next DAT object')
            target=dat.ptr(slot)
            if target is None:break
            if slot+8>end:raise ValueError('Truncated envelope weight')
            j=joint(target);weight=dat.f32(slot+4)
            if not math.isfinite(weight) or weight<0:raise ValueError('Nonfinite or negative envelope weight')
            rows.append(dict(joint=j,weight=weight));slot+=8
        if not rows:raise ValueError('Empty envelope')
        total=sum(r['weight'] for r in rows)
        result=dict(offset=offset,weights=rows,weight_sum=total,weight_sum_error=abs(total-1),
            within_weight_tolerance=abs(total-1)<=weight_sum_tolerance)
        envelopes[offset]=result
        referenced.update(r['joint'] for r in rows);weighted.update(r['joint'] for r in rows if r['weight']>0)
        return result

    def polygon(offset):
        if offset in objects:return objects[offset]
        dat.require(offset,0x18)
        flags,blocks=struct.unpack_from('>HH',payload,32+offset+0xC)
        display=dat.ptr(offset+0x10)
        if blocks and display is None:raise ValueError('Nonempty display list has no data')
        if display is not None:dat.require(display,blocks*32)
        row=dict(offset=offset,flags=flags,display_bytes=blocks*32,display_list_consumption='UNMEASURED')
        kind=flags&0x3000
        if flags&4 or kind not in (0,0x2000):
            row.update(binding='UNSUPPORTED_UNION',resolved=False)
            unresolved.append(offset)
        elif kind==0x2000:
            table=dat.ptr(offset+0x14)
            if table is None:raise ValueError('Envelope table absent')
            ids=[];slot=table;end=dat.struct_end(table)
            while True:
                if slot+4>end:raise ValueError('Unterminated envelope pointer table')
                target=dat.ptr(slot)
                if target is None:break
                envelope(target);ids.append(target);slot+=4
            if not ids:raise ValueError('Empty envelope table')
            row.update(binding='ENVELOPE',resolved=True,envelope_offsets=ids)
        else:
            target=dat.ptr(offset+0x14)
            if target is None:row.update(binding='RIGID_OWNER',resolved=True)
            else:
                j=joint(target);referenced.add(j)
                row.update(binding='SHARED_VERTEX_JOINT',joint=j,resolved=True)
        objects[offset]=row
        return row

    for owner in model['joints']:
        for dobj in owner['dobj_offsets']:
            chain=[];seen=set();offset=dat.ptr(dobj+0xC)
            while offset is not None:
                if offset in seen:raise ValueError('Cyclic PObj chain')
                seen.add(offset);polygon(offset);chain.append(offset);offset=dat.ptr(offset+4)
            if chain:referenced.add(owner['index'])
            drawables.append(dict(offset=dobj,owner=owner['index'],pobj_offsets=chain))
    errors=[r['offset'] for r in envelopes.values() if not r['within_weight_tolerance']]
    complete=not unresolved and not errors
    return dict(schema='mocap-mesh-bindings-v1',status='BINDING_DESCRIPTORS_MEASURED' if complete else 'BINDING_DESCRIPTORS_REQUIRE_REVIEW',
        root=model['root'],joints=model['joint_count'],drawables=drawables,pobjs=list(objects.values()),
        envelopes=list(envelopes.values()),referenced_joints=sorted(referenced),positive_weight_joints=sorted(weighted),
        unsupported_pobjs=unresolved,out_of_tolerance_envelopes=errors,weight_sum_tolerance=weight_sum_tolerance,
        maximum_weight_sum_error=max((r['weight_sum_error'] for r in envelopes.values()),default=0.),
        native_accepted=False,pruning_ready=False,
        scope='Conservative stored references, including drawable owners and zero-weight joints. Vertex/display-list indices, materials, inverse binds, deformation and engine consumers remain separate gates.')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--costume',type=Path,required=True)
    p.add_argument('--root-name');p.add_argument('--out',type=Path,required=True)
    a=p.parse_args(argv)
    if a.out.exists():raise ValueError('New binding inventory required')
    pins=dict(costume=fingerprint(a.costume),implementation=fingerprint(__file__))
    result=inventory(a.costume.read_bytes(),root_name=a.root_name);check_pins(pins)
    result['inputs']=pins;write_new(a.out,result)
    print(result['status'],len(result['drawables']),'drawables',len(result['pobjs']),'polygons',len(result['envelopes']),'envelopes')


if __name__=='__main__':main()
