"""Remove donor body-DObj alternatives from a single always-visible native mesh.

Clear ALL body modes together: clearing only high-poly leaves the low-poly
initialization pass hiding unrelated DObjs. Mode 2 has a separate metal domain.
No expression or alternate LOD geometry is claimed by this static policy.
"""
from vault.echo.subactions import FighterDat

def apply(payload):
    ft=FighterDat(payload);dat=ft.dat
    model=dat.ptr(ft.ft_root+8)
    if model is None:raise ValueError('No fighter model lookup')
    count=dat.u32(model);table=dat.ptr(model+4)
    if not 1<=count<=11 or table is None:raise ValueError('Invalid model visibility domain')
    costumes=(dat.struct_end(table)-table)//16
    if not 1<=costumes<=32:raise ValueError('Invalid costume visibility table size')
    # A shared new array of empty variant groups is safe across body modes:
    # the engine only reads it; all model state writes are to Fighter storage.
    empty=dat.append_struct(bytes(count*8),[])
    changed=[]
    for costume in range(costumes):
        for mode in (0,1,3):
            slot=table+costume*16+4*mode
            changed.append(dict(costume=costume,mode=mode,before=dat.ptr(slot),after=empty))
            dat.set_u32(slot,empty);dat.add_reloc(slot)
    return ft.to_bytes(),dict(schema='static-body-visibility-v1',groups=count,costumes=costumes,
        body_modes=[0,1,3],changes=changed,policy='all native body DObjs remain outside donor visibility alternatives',
        limitation='No expression swaps or separate low-poly geometry; metal model remains a separate unchecked domain')
