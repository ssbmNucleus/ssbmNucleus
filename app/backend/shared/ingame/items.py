"""GALE01 item setup and bounded native item readback for frozen solo sessions.

StartMeleeRules +B/+20, it_804A0E30, Item and HSD_GObj layouts are from
mn/types.h, it/types.h and baselib/gobj.h. Item creation and pickup stay native.
"""
import math
import struct
from . import match_setup

SPAWNER=0x804A0E30
ENTITIES=0x804D782C


def address(value,size=4):
    if not isinstance(value,int) or value%4 or not 0x80000000<=value<=0x81800000-size:
        raise ValueError('Item pointer outside aligned MEM1')
    return value


def configure_rules(d,kinds):
    kinds=list(kinds)
    if not kinds or len(set(kinds))!=len(kinds) or any(type(k) is not int or not 0<=k<35 for k in kinds):
        raise ValueError('Unique native common item kinds required')
    mask=sum(1<<k for k in kinds);changes=[]
    # The SSS finalizer rebuilds match rules from menu preferences. Bind the
    # actual GALE01 accessor: newer decomp struct comments have moved offsets.
    if d.bytes(0x8015CC58,12)!=bytes.fromhex('806d884038631cb04e800020'):
        raise ValueError('Unrecognized native item preference accessor')
    mapping=list(d.bytes(0x803B7844,32))
    if any(mapping.count(k)!=1 for k in kinds):raise ValueError('Ambiguous item preference mapping')
    prefs=address(d.u32(match_setup.VSDATA_PTR)+0x1cb0,16)
    saved=[dict(address=prefs,raw=d.bytes(prefs,1).hex()),dict(address=prefs+8,raw=d.bytes(prefs+8,8).hex())]
    preference_mask=sum(1<<mapping.index(k) for k in kinds)
    d.write_u8(prefs,4);d.write_u32(prefs+8,preference_mask>>32);d.write_u32(prefs+12,preference_mask&0xffffffff)
    bases=match_setup._player_bases(d)
    for players in bases:
        rules=address(players-0x60,0x60)
        changes.append(dict(address=rules,frequency_before=d.u8(rules+11),mask_before=d.bytes(rules+0x20,8).hex()))
        d.write_u8(rules+11,4)
        d.write_u32(rules+0x20,mask>>32);d.write_u32(rules+0x24,mask&0xffffffff)
        if d.u8(rules+11)!=4 or d.bytes(rules+0x20,8)!=struct.pack('>Q',mask):raise ValueError('Item rules readback differs')
    return dict(kinds=kinds,frequency=4,changes=changes,saved=saved)


def spawner(d):
    count=d.u8(SPAWNER+4);total=d.u16(SPAWNER+12)
    if not 1<=count<=35 or not total:raise ValueError('Native item spawner is not initialized')
    kinds=address(d.u32(SPAWNER+8),count);weights=address(d.u32(SPAWNER+16),count*2)
    values=list(d.bytes(kinds,count))
    if any(k>=35 for k in values) or len(set(values))!=count:raise ValueError('Invalid native item pick table')
    return dict(count=count,total=total,kinds_pointer=kinds,weights_pointer=weights,kinds=values,countdown=d.u32(SPAWNER))


def next_spawn(d,kind):
    """Select an already allowed kind and request one native ambient attempt.

    Caller restores the returned byte spans in finally. The existing allocation
    is retained; no GObj, item pointer, item ownership or fighter state is forged.
    """
    table=spawner(d)
    if kind not in table['kinds']:raise ValueError('Requested kind absent from initialized native table')
    spans=[(SPAWNER,20),(table['kinds_pointer'],table['count']),(table['weights_pointer'],table['count']*2)]
    saved=[dict(address=p,raw=d.bytes(p,n).hex()) for p,n in spans]
    receipt=dict(original=table,saved=saved,kind=kind)
    try:
        d.write_u8(table['kinds_pointer'],kind)
        d.write_u16(table['weights_pointer'],0)
        d.write_u8(SPAWNER+4,1);d.write_u16(SPAWNER+12,1);d.write_u32(SPAWNER,1)
        if spawner(d)['kinds']!=[kind]:raise ValueError('Item spawn selection readback differs')
    except Exception:
        restore_spawn(d,receipt);raise
    return receipt


def restore_spawn(d,receipt):
    for span in reversed(receipt['saved']):
        raw=bytes.fromhex(span['raw'])
        for i,value in enumerate(raw):d.write_u8(span['address']+i,value)


def read_items(d):
    root=address(d.u32(ENTITIES),0x28);gobj=d.u32(root+0x24);seen=set();rows=[]
    while gobj:
        address(gobj,0x38)
        if gobj in seen or len(seen)>=128:raise ValueError('Cyclic or oversized native item list')
        seen.add(gobj)
        if d.u16(gobj)!=6 or d.u8(gobj+2)!=9:raise ValueError('Unexpected native item GObj class/link')
        data=address(d.u32(gobj+0x2c),0x51c)
        if d.u32(data+4)!=gobj:raise ValueError('Item entity backpointer differs')
        pos=[d.f32(data+0x4c+i*4) for i in range(3)]
        if not all(math.isfinite(v) for v in pos):raise ValueError('Nonfinite native item position')
        rows.append(dict(gobj=gobj,data=data,kind=d.u32(data+0x10),state=d.u32(data+0x24),position=pos,owner=d.u32(data+0x518)))
        gobj=d.u32(gobj+8)
    return rows
