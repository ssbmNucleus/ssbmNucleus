"""Bounded private hurtbox-bank serialization for offline fighter DAT copies.

The writer clones both the bank header and array, then changes only the chosen
fighter root's bank pointer in the original data. Character anatomy, fitting,
gameplay policy, and installation remain caller-owned.
"""
import hashlib
import math
import struct

from .compat.rig_inventory import Archive

MAX_HURTBOXES=15
STRIDE=0x28


def _capsules(capsules,joint_count):
    if not isinstance(capsules,list) or not 1<=len(capsules)<=MAX_HURTBOXES:
        raise ValueError('Explicit nonempty capsule list must contain at most 15 slots')
    rows=[];blob=bytearray(len(capsules)*STRIDE)
    for i,row in enumerate(capsules):
        if not isinstance(row,dict) or set(row)!={'joint','height','grabbable','a','b','radius'}:
            raise ValueError('Exact hurtbox fields required')
        joint,height,grab=row['joint'],row['height'],row['grabbable']
        if type(joint) is not int or not 0<=joint<joint_count:
            raise ValueError('Hurtbox joint outside measured domain')
        if type(height) is not int or height not in (0,1,2):
            raise ValueError('Hurtbox height must be native low/mid/high 0..2')
        if type(grab) is not int or grab not in (0,1):
            raise ValueError('Hurtbox grabbable must be 0 or 1')
        if (not isinstance(row['a'],list) or not isinstance(row['b'],list) or
                len(row['a'])!=3 or len(row['b'])!=3):
            raise ValueError('Hurtbox endpoints must be explicit 3-vectors')
        geometry=[*row['a'],*row['b'],row['radius']]
        if any(type(x) not in (int,float) or isinstance(x,bool) or not math.isfinite(x) for x in geometry):
            raise ValueError('Finite numeric hurtbox geometry required')
        if row['radius']<0:raise ValueError('Hurtbox radius cannot be negative')
        try:packed=struct.pack('>III7f',joint,height,grab,*geometry)
        except (OverflowError,struct.error):raise ValueError('Hurtbox geometry must fit float32') from None
        values=struct.unpack('>III7f',packed)
        if not all(math.isfinite(x) for x in values[3:]):raise ValueError('Hurtbox float32 overflow')
        blob[i*STRIDE:(i+1)*STRIDE]=packed
        rows.append(dict(joint=values[0],height=values[1],grabbable=values[2],a=list(values[3:6]),b=list(values[6:9]),radius=values[9]))
    return bytes(blob),rows


def apply(payload,*,root_name,joint_count,capsules):
    """Return a new offline PL and preservation/readback receipt.

    ``joint_count`` is the measured parts domain of the intended costume, not
    an unrelated donor's joint count. Only the hurtbox bank is validated here;
    the caller must separately admit center, ECB and other native consumers.
    The existing bank must be nonempty. Its bounded header extent is retained
    verbatim, including opaque tail bytes and their relocations, although the
    native header fields themselves occupy only eight bytes.
    """
    if not isinstance(root_name,str) or not root_name or type(joint_count) is not int or not 1<=joint_count<=255:
        raise ValueError('Explicit root and measured joint domain 1..255 required')
    dat=Archive(payload);roots=[o for n,o in dat.roots if n==root_name]
    if len(roots)!=1:raise ValueError('Exactly one explicitly selected fighter root required')
    root=roots[0];dat.require(root,0x34);bank=dat.ptr(root+0x30)
    if bank is None:raise ValueError('Selected fighter has no hurtbox bank header')
    dat.require(bank,8);header_end=dat.struct_end(bank)
    if header_end<bank+8:raise ValueError('Hurtbox bank header overlaps another structure')
    old_count=dat.u32(bank);old_array=dat.ptr(bank+4)
    if not 1<=old_count<=MAX_HURTBOXES or old_array is None:
        raise ValueError('Existing hurtbox bank must be nonempty, bounded, and relocated')
    old_size=old_count*STRIDE;dat.require(old_array,old_size)
    if dat.struct_end(old_array)<old_array+old_size:
        raise ValueError('Existing hurtbox array crosses a structure boundary')
    if not (old_array+old_size<=bank or bank+(header_end-bank)<=old_array):
        raise ValueError('Hurtbox bank header and array overlap')
    targets={dat.u32(p) for p in dat.relocs}|{o for _,o in dat.roots}
    if any(old_array<=p<old_array+old_size for p in dat.relocs):
        raise ValueError('Hurtbox array contains an unexpected pointer field')
    if any(old_array<t<old_array+old_size for t in targets):
        raise ValueError('Pointer target overlaps the middle of the hurtbox array')
    blob,expected=_capsules(capsules,joint_count)
    original_size=dat.data_size;original_data=bytes(dat.buf[32:32+original_size]);original_relocs=set(dat.relocs)
    old_header_bytes=bytes(dat.buf[32+bank:32+header_end]);old_array_bytes=bytes(dat.buf[32+old_array:32+old_array+old_size])
    new_array=dat.append_struct(blob,align=4)
    header=bytearray(old_header_bytes);struct.pack_into('>II',header,0,len(expected),new_array)
    header_relocs={p-bank for p in original_relocs if bank<=p<header_end}|{4}
    new_bank=dat.append_struct(header,sorted(header_relocs),align=4)
    dat.set_u32(root+0x30,new_bank);dat.add_reloc(root+0x30)
    result=dat.to_bytes();after=Archive(result)
    # All original bytes are preserved except the selected root pointer. Old
    # bank/header bytes remain addressable for any other root sharing them.
    restored=bytearray(result[32:32+original_size]);restored[root+0x30:root+0x34]=original_data[root+0x30:root+0x34]
    if bytes(restored)!=original_data or not original_relocs<=after.relocs:
        raise ValueError('Unexpected mutation outside selected fighter bank pointer')
    if bytes(after.buf[32+bank:32+header_end])!=old_header_bytes or bytes(after.buf[32+old_array:32+old_array+old_size])!=old_array_bytes:
        raise ValueError('Old hurtbox structures were not preserved')
    if after.ptr(root+0x30)!=new_bank or after.u32(new_bank)!=len(expected) or after.ptr(new_bank+4)!=new_array:
        raise ValueError('Private hurtbox bank header readback differs')
    readback=[]
    for i in range(after.u32(new_bank)):
        offset=after.ptr(new_bank+4)+i*STRIDE
        after.require(offset,STRIDE)
        values=struct.unpack_from('>III7f',result,32+offset)
        readback.append(dict(consumer=f'hurtbox[{i}]',joint=values[0],height=values[1],
            grabbable=values[2],a=list(values[3:6]),b=list(values[6:9]),radius=values[9]))
    if readback!=[dict(consumer=f'hurtbox[{i}]',**row) for i,row in enumerate(expected)]:
        raise ValueError('Serialized hurtbox census differs')
    return result,dict(schema='bounded-hurtbox-bank-v2',status='HURTBOX_BANK_WRITTEN_OFFLINE',root=root_name,joint_count=joint_count,
        old_count=old_count,new_count=len(expected),old_bank=bank,new_bank=new_bank,old_array=old_array,new_array=new_array,
        old_header_bytes=len(old_header_bytes),old_array_bytes=len(old_array_bytes),
        old_header_sha256=hashlib.sha256(old_header_bytes).hexdigest(),old_array_sha256=hashlib.sha256(old_array_bytes).hexdigest(),
        new_header_sha256=hashlib.sha256(bytes(after.buf[32+new_bank:32+new_bank+len(header)])).hexdigest(),
        new_array_sha256=hashlib.sha256(bytes(after.buf[32+new_array:32+new_array+len(blob)])).hexdigest(),
        serialized_readback=readback,readback_scope='HURTBOX_BANK_ONLY',other_consumer_admission=False,
        input_sha256=hashlib.sha256(payload).hexdigest(),output_sha256=hashlib.sha256(result).hexdigest(),
        changed_original_range=[root+0x30,root+0x34],old_header_preserved=True,old_array_preserved=True,
        old_relocations_preserved=True,unrelated_original_data_preserved=True,private_header=True,private_array=True,
        native_limit=MAX_HURTBOXES,native_installed=False,runtime_proven=False)
