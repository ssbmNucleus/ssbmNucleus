"""Per-fighter model scale with explicit, separate collision policies.

Engine evidence: ftaction.c loads hit radius directly from script Size / 256;
ftcoll.c passes x34_scale.y to lbColl_8000805C. That is runtime PLAYER scale,
not co_attrs.model_scaling. Offsets instead use the bone world matrix.
Never multiply script radii by donor_model_scale / target_model_scale.
"""
import hashlib
import math
import struct
from pathlib import Path
from vault.echo.subactions import FighterDat, ACTION_SIZE, HEADER_SIZE, write_bits

MODEL_SCALING = 0x8C

def scale_offset(ft):
    attrs = ft.dat.ptr(ft.ft_root)
    if attrs is None:
        raise ValueError('Fighter has no common attributes')
    return HEADER_SIZE + attrs + MODEL_SCALING

def reachable_commands(ft):
    """Visit action/demo roots plus calls/jumps, deduplicating actual commands."""
    pending = [a.script_offset for a in ft.actions if a.script_offset is not None]
    demo = ft.dat.ptr(ft.ft_root + 0x14)
    if demo is not None:
        for i in range((ft.dat.struct_end(demo)-demo)//ACTION_SIZE):
            p = ft.dat.ptr(demo+i*ACTION_SIZE+0x0C)
            if p is not None: pending.append(p)
    blocks, commands = set(), {}
    while pending:
        offset = pending.pop()
        if offset in blocks: continue
        blocks.add(offset)
        script = ft.decode_script(offset)
        if script.unknown_code is not None:
            raise ValueError(f'Undecodable reachable script at {offset:#x}')
        for cmd in script.commands:
            if cmd.after_end: break
            commands.setdefault(cmd.offset, cmd)
            if cmd.code in (5, 7) and cmd.pointer is not None:
                pending.append(cmd.pointer)
            if cmd.code in (0, 6, 7): break
    return commands

def apply(payload, target, *, offset_policy='preserve_local', baseline=None):
    """Return new bytes; optional immutable baseline repairs prior bad rescaling.

    preserve_local leaves offsets as authored. preserve_model_offset preserves
    baseline scale * local offset, including item offsets: ignore_fighter_scale
    affects radius, not the bone matrix. Neither preserves a donor bone's world
    position after changing skeletons. Baseline must share script layout.
    """
    if not math.isfinite(target) or target <= 0:
        raise ValueError('Model scale must be finite and positive')
    if offset_policy not in ('preserve_local','preserve_model_offset'):
        raise ValueError('Unknown offset policy')
    ft = FighterDat(payload)
    ref = FighterDat(baseline if baseline is not None else payload)
    old = struct.unpack_from('>f', ref.dat.buf, scale_offset(ref))[0]
    if not math.isfinite(old) or old <= 0: raise ValueError('Invalid baseline scale')
    current, reference = reachable_commands(ft), reachable_commands(ref)
    changes = []
    for offset, cmd in current.items():
        if cmd.code not in (0x0B,0x0D): continue
        src = reference.get(offset)
        if src is None or src.code != cmd.code:
            raise ValueError(f'Baseline script layout differs at {offset:#x}')
        # Verify that this is the same command after any earlier scale edit.
        for key, value in cmd.fields.items():
            if key not in ('size','x_offset','y_offset','z_offset') and src.fields.get(key)!=value:
                raise ValueError(f'Baseline command identity differs at {offset:#x}: {key}')
        for key in ('size','x_offset','y_offset','z_offset'):
            if key not in cmd.fields: continue
            value = src.fields[key]
            if key!='size' and offset_policy=='preserve_model_offset':
                value = round(value * old / target)
            param = cmd.spec.param(key)
            if not param.min <= value <= param.max:
                raise ValueError(f'Field overflow at {offset:#x}: {key}={value}')
            if value!=cmd.fields[key]:
                write_bits(ft.dat.buf,(HEADER_SIZE+offset)*8+param.bit_offset,param.bits,value)
                changes.append(dict(offset=offset,field=key,before=cmd.fields[key],after=value))
    struct.pack_into('>f',ft.dat.buf,scale_offset(ft),target)
    result = ft.to_bytes()
    return result, dict(schema='fighter-scale-v2',target=target,baseline_scale=old,
        offset_policy=offset_policy,radius_policy='unchanged_from_baseline',
        input_sha256=hashlib.sha256(payload).hexdigest(),
        baseline_sha256=hashlib.sha256(baseline if baseline is not None else payload).hexdigest(),
        output_sha256=hashlib.sha256(result).hexdigest(),changes=changes,
        scope='Local offsets and script radii only; world contact and hurt coverage require live verification.')
