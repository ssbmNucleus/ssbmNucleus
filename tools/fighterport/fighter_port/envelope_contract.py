"""Preserve weighted transforms across HSD's first-weight rigid fast path.

Melee uses first_weight >= 1 - FLT_EPSILON; the current importer uses the
number of entries and the exporter uses first_weight == 1. Split a problematic
entry into two entries for the SAME joint, so all three use blended matrices.
No weight renormalization, joint reassignment or influence discard is allowed.
"""
import math
import struct

RIGID_THRESHOLD=1.-2.**-23


def f32(value):return struct.unpack('>f',struct.pack('>f',value))[0]


def prepare_links(links):
    if not links or len(links)>6:raise ValueError('One to six explicit source influences required')
    if any(type(j) is not int or j<0 or type(w) not in (float,int) or not math.isfinite(w) or w<0 or f32(w)!=w for j,w in links):
        raise ValueError('Finite nonnegative float32 source weights and joint indices required')
    result=list(links)
    first=result[0][1]
    split=(len(result)==1 and first!=1.) or (len(result)>1 and first>=RIGID_THRESHOLD)
    if split:
        j,w=result[0];a=f32(w/2);b=f32(w-a)
        if a+b!=w or len(result)==6:raise ValueError('Exact weight split exceeds importer representation')
        result=[(j,a),(j,b)]+result[1:]
    # Only a single, exactly unit weight may use the rigid representation.
    if (len(result)==1)!=(result[0][1]>=RIGID_THRESHOLD) or (len(result)==1)!=(result[0][1]==1.):
        raise ValueError('Importer/exporter/engine matrix modes disagree')
    return result,dict(split=split,source_entries=len(links),encoded_entries=len(result),
        weight_total_before=sum(w for _,w in links),weight_total_after=sum(w for _,w in result),
        mode='RIGID' if len(result)==1 else 'BLENDED')
