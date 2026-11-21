"""Explicit bone-local hitbox conversion, with native XYZ and fixed readback.

The script editor calls the first coordinate Z; ftaction.c assigns it to X.
Never infer an anatomical mirror from those field labels or from a bone index.
This module changes offsets only. Radius, timing, damage and knockback remain
separate authoring decisions. A bind-basis conversion is not a moveset port.
"""
import hashlib
import numpy as np
from vault.echo.subactions import FighterDat,HEADER_SIZE,write_bits
from .compat.fighter_scale import reachable_commands
from .collision_coordinates import affine

FIELDS=('z_offset','y_offset','x_offset')

def local_xyz(fields):
    return np.array([fields[k]/256.0 for k in FIELDS])

def rebase_point(point,old_bind,new_bind,*,model_transform,max_error=0.02):
    old,new,model=map(affine,(old_bind,new_bind,model_transform))
    point=np.asarray(point,dtype=float)
    if point.shape!=(3,) or not np.isfinite(point).all():raise ValueError('Finite local XYZ point required')
    if not np.isfinite(max_error) or max_error<0:raise ValueError('Finite nonnegative error budget required')
    expected=model@old@np.r_[point,1.]
    local=np.linalg.solve(new,expected)[:3]
    fixed=np.rint(local*256)
    if not np.isfinite(fixed).all() or np.any(fixed < -32768) or np.any(fixed > 32767):
        raise ValueError('Rebased hitbox exceeds signed 16-bit offset range')
    fields={key:int(v) for key,v in zip(FIELDS,fixed)}
    measured=new@np.r_[local_xyz(fields),1.]
    error=float(np.linalg.norm(measured[:3]-expected[:3]))
    if error>max_error:raise ValueError('Stored hitbox exceeds the requested coordinate error budget')
    return dict(fields=fields,local_xyz=local_xyz(fields).tolist(),world_error=error,
                expected_world=expected[:3].tolist(),stored_world=measured[:3].tolist())

def apply(payload,bindings):
    """Bindings name exact reachable command offsets and their input fields.

    Each entry supplies old_bind/new_bind/model_transform (4x4 affine) and an
    expected_fields preimage. The immutable SHA prevents accidental double
    conversion. Common-bone resolution belongs to the explicit binding author.
    """
    digest=hashlib.sha256(payload).hexdigest()
    if bindings.get('input_sha256')!=digest:raise ValueError('Hitbox binding input SHA mismatch')
    ft=FighterDat(payload);commands=reachable_commands(ft);rows=[];seen=set()
    for entry in bindings['commands']:
        offset=entry['offset']
        if type(offset) is not int or offset in seen:raise ValueError('Unique command offsets required')
        seen.add(offset);cmd=commands.get(offset)
        if cmd is None or cmd.code!=0x0B:raise ValueError('Binding does not name a reachable Create Hitbox')
        if entry['expected_fields']!=cmd.fields:raise ValueError('Hitbox preimage differs')
        r=rebase_point(local_xyz(cmd.fields),entry['old_bind'],entry['new_bind'],
                       model_transform=entry['model_transform'],max_error=bindings.get('max_error',0.02))
        for key,value in r['fields'].items():
            param=cmd.spec.param(key)
            write_bits(ft.dat.buf,(HEADER_SIZE+offset)*8+param.bit_offset,param.bits,value)
        rows.append(dict(offset=offset,bone=cmd.fields['bone'],before=local_xyz(cmd.fields).tolist(),**r))
    blob=ft.to_bytes();readback=reachable_commands(FighterDat(blob))
    for offset,cmd in commands.items():
        after=readback[offset]
        for key,value in cmd.fields.items():
            if offset in seen and key in FIELDS:continue
            if after.fields[key]!=value:raise ValueError('Hitbox repair changed an unselected field')
    return blob,dict(schema='hitbox-coordinate-rebase-v1',input_sha256=digest,
        output_sha256=hashlib.sha256(blob).hexdigest(),rows=rows,
        radius_policy='unchanged',native_accepted=False,
        scope='Explicit coordinate conversion and fixed-point readback; animation timing and live contact require separate verification')
