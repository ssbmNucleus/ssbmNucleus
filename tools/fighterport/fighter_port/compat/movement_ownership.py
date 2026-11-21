"""Explicit movement ownership, shared by donor and source-native rig pipelines.

Animation flags alone do not establish movement: a physics consumer must use the
extracted axis. These common-state contracts come from Shulk/Mac implementations
and the Melee callbacks. Custom states need a supplied contract, never a guess.
"""
from dataclasses import dataclass,asdict
import struct
import numpy as np
from vault.echo.datroot import parse
from vault.echo.subactions import FighterDat,ACTION_SIZE
from .fobj_reader import read_figatree,native_value,read_varint,FORMAT_WIDTH


@dataclass(frozen=True)
class Contract:
    owner: str
    axes: tuple
    physics: str
    facing: str='current'


PHYSICS_MOTIONS={
    'WalkSlow':'ftCo_Walk_Phys -> ftWalkCommon_800E0060',
    'WalkMiddle':'ftCo_Walk_Phys -> ftWalkCommon_800E0060',
    'WalkFast':'ftCo_Walk_Phys -> ftWalkCommon_800E0060',
    'Turn':'ftCo_Turn_Phys', 'TurnRun':'ftCo_TurnRun_Phys',
    'Dash':'ftCo_Dash_Phys','Run':'ftCo_Run_Phys','RunBrake':'ftCo_RunBrake_Phys',
}
ROOT_MOTIONS={
    'EscapeF':('ftCo_Escape_Phys -> ft_80085004 -> ft_80085030','saved'),
    'EscapeB':('ftCo_Escape_Phys -> ft_80085004 -> ft_80085030','saved'),
    'AttackDash':('ftCo_AttackDash_Phys -> ft_80084FA8 -> ft_80085030','current'),
    'CatchDash':('ftCo_CatchDash_Phys -> ft_80085030','current'),
    'PassiveStandF':('ftCo_PassiveStand_Phys -> ft_80084FA8 -> ft_80085030','current'),
    'PassiveStandB':('ftCo_PassiveStand_Phys -> ft_80084FA8 -> ft_80085030','current'),
}


def common_contract(motion):
    if motion in PHYSICS_MOTIONS:return Contract('PHYSICS',('X','Y','Z'),PHYSICS_MOTIONS[motion])
    if motion in ROOT_MOTIONS:
        callback,facing=ROOT_MOTIONS[motion]
        return Contract('ANIMATION_DELTA',('Z',),callback,facing)
    return None


def inspect_clip(blob,root_joint):
    data,_,roots,_=parse(blob)
    if not roots or len({r for r,_ in roots})!=1:raise ValueError('One animation root required')
    end,counts,tracks,_,_=read_figatree(data,roots[0][0])
    if not 0<=root_joint<len(counts):raise ValueError('Root outside animation skeleton')
    if not np.isfinite(end) or not 0<=end<=100000:raise ValueError('Invalid animation duration')
    values={};times=np.linspace(0,end,max(2,int(end*4)+1))
    for track in tracks:
        if track.node==root_joint and track.type in (5,6,7):
            samples=np.array([native_value(track.events,float(t-track.start)) for t in times])
            if not np.all(np.isfinite(samples)):raise ValueError('Non-finite root curve')
            values['XYZ'[track.type-5]]=dict(min=float(samples.min()),max=float(samples.max()),entry=float(samples[0]),exit=float(samples[-1]),peak=float(np.max(np.abs(samples))))
    return dict(end=end,joints=len(counts),translation=values)


def diagnose(motion,flags,clip,contract=None):
    contract=contract or common_contract(motion)
    translation=clip['translation'];nonzero={axis for axis,row in translation.items() if row['peak']>1e-5}
    if contract is None:
        return dict(status='REVIEW_REQUIRED' if nonzero else 'NO_TRANSLATION',issues=[],contract=None)
    issues=[];extracts=bool(flags&0x80000000)
    if contract.owner=='PHYSICS' and nonzero:
        issues.append('UNCONSUMED_EXTRACTED_TRAVEL' if extracts else 'DOUBLE_MODEL_AND_PHYSICS_MOVEMENT')
    if contract.owner=='ANIMATION_DELTA':
        if not extracts and nonzero&set(contract.axes):issues.append('MISSING_EXTRACTION_FLAG')
        if nonzero-set(contract.axes):issues.append('UNCONSUMED_AXES_REQUIRE_BODY_RESIDUAL')
    if contract.owner=='LOCAL_POSE' and extracts and nonzero:issues.append('LOCAL_POSE_WOULD_BE_EXTRACTED')
    if contract.owner not in ('PHYSICS','ANIMATION_DELTA','LOCAL_POSE'):raise ValueError('Unknown movement owner')
    serialized=asdict(contract);serialized['axes']=list(contract.axes)
    return dict(status='REPAIR_REQUIRED' if issues else 'CONTRACT_SATISFIED',issues=issues,contract=serialized,extraction_enabled=extracts)


def zero_root_channels(blob,root_joint,axes=('X','Y','Z')):
    """Zero only numeric payloads: preserve opcodes, clocks, headers and offsets."""
    if not set(axes)<=set('XYZ'):raise ValueError('Unknown translation axis')
    data,_,roots,_=parse(blob);_,_,tracks,_,_=read_figatree(data,roots[0][0]);result=bytearray(blob);spans=[]
    for track in tracks:
        if track.node!=root_joint or track.type not in {5+'XYZ'.index(axis) for axis in axes}:continue
        raw=data[track.pointer:track.pointer+track.length];cursor=0
        while cursor<len(raw):
            word,cursor=read_varint(raw,cursor);op=word&15
            if op==0:break
            if op not in (1,2,3,4,5,6):raise ValueError('Unsupported root opcode')
            for _ in range((word>>4)+1):
                for flag in ([] if op==5 else [track.value_flag])+([track.slope_flag] if op in (4,5) else []):
                    width=FORMAT_WIDTH[flag&224];offset=32+track.pointer+cursor
                    if cursor+width>len(raw):raise ValueError('Truncated root payload')
                    result[offset:offset+width]=bytes(width);spans.append((offset,width));cursor+=width
                if op in (1,2,3,4):_,cursor=read_varint(raw,cursor)
    after=inspect_clip(bytes(result),root_joint)
    if any(after['translation'][axis]['peak']!=0 for axis in axes if axis in after['translation']):raise ValueError('Root zero readback failed')
    allowed={i for offset,width in spans for i in range(offset,offset+width)}
    if any(x!=y and i not in allowed for i,(x,y) in enumerate(zip(blob,result))):raise ValueError('Non-root bytes changed')
    # Packed archives can deduplicate streams across different joints. Byte
    # locality alone is not proof that a root edit preserves the body pose.
    changed={i for i,(x,y) in enumerate(zip(blob,result)) if x!=y}
    selected_types={5+'XYZ'.index(axis) for axis in axes}
    for track in tracks:
        if track.node==root_joint and track.type in selected_types:continue
        if changed.intersection(range(32+track.pointer,32+track.pointer+track.length)):
            raise ValueError('Root stream aliases an unselected body channel; repack before repair')
    return bytes(result),dict(numeric_spans=spans,other_animation_bytes_preserved=True)


def adapt_common_bank(pl,aj,*,root_joint,motions):
    fighter=FighterDat(pl);bank=bytearray(aj);result=bytearray(pl);reports=[];selected=set(motions)
    if selected-set(PHYSICS_MOTIONS)-set(ROOT_MOTIONS):raise ValueError('Custom or unreviewed movement requires an explicit separate contract')
    found=set()
    for action in fighter.actions:
        if action.motion not in selected:continue
        found.add(action.motion);offset=action.anim_offset;blob=bytes(bank[offset:offset+action.anim_size]);contract=common_contract(action.motion)
        before=inspect_clip(blob,root_joint);diagnostic=diagnose(action.motion,action.flags,before)
        if contract.owner=='PHYSICS':
            changed,proof=zero_root_channels(blob,root_joint,contract.axes)
            bank[offset:offset+action.anim_size]=changed
        else:
            if 'UNCONSUMED_AXES_REQUIRE_BODY_RESIDUAL' in diagnostic['issues']:raise ValueError('Preserve unsupported axes as body motion before extracting this clip')
            struct.pack_into('>I',result,32+fighter.action_table[0]+action.index*ACTION_SIZE+16,action.flags|0x80000000)
            proof=dict(animation_bytes_preserved=True)
        reports.append(dict(action=action.index,motion=action.motion,before=before,diagnostic=diagnostic,adaptation=proof))
    if found!=selected:raise ValueError('Requested movement missing from bank')
    # Shared archive ranges must not silently edit an unselected owner.
    for action in fighter.actions:
        if action.motion not in selected and aj[action.anim_offset:action.anim_offset+action.anim_size]!=bank[action.anim_offset:action.anim_offset+action.anim_size]:
            raise ValueError('Root patch aliases an unselected animation')
    return bytes(result),bytes(bank),reports


def _contract(motion,contracts):
    common=common_contract(motion)
    if not contracts or motion not in contracts:return common
    row=contracts[motion]
    if not isinstance(row,dict) or set(row)-{'owner','axes','physics','facing'}:
        raise ValueError('Explicit movement contract fields required')
    result=Contract(row['owner'],tuple(row['axes']),row['physics'],row.get('facing','current'))
    if result.owner not in ('PHYSICS','ANIMATION_DELTA','LOCAL_POSE') or not result.physics or not isinstance(result.physics,str):
        raise ValueError('Movement owner and reviewed physics consumer required')
    if set(result.axes)-set('XYZ') or result.facing not in ('current','saved'):
        raise ValueError('Invalid movement axes or facing')
    if result.owner=='PHYSICS' and set(result.axes)!=set('XYZ'):
        raise ValueError('Physics-owned repair requires all three translation axes')
    if result.owner=='ANIMATION_DELTA' and result.axes!=('Z',):
        raise ValueError('This repair supports the reviewed Z extraction consumer only')
    if common and result!=common:raise ValueError('Cannot override a reviewed common movement consumer')
    return result


def neutralize_translation(blob,joints):
    """Isolate shared streams, neutralize selected translation writers, repack."""
    from .animation_archive import compact,tracks as archive_tracks
    from vault.echo.datroot import build
    original=archive_tracks(blob);data,rel,roots,xrefs=parse(blob);data=bytearray(data)
    _,counts,tracks,_,_=read_figatree(data,roots[0][0]);joints=set(joints)
    if any(type(j) is not int or not 0<=j<len(counts) for j in joints):raise ValueError('Joint outside clip')
    tp=struct.unpack_from('>I',data,roots[0][0]+16)[0]
    for i,track in enumerate(tracks):
        if track.node in joints and track.type in (5,6,7):
            raw=bytes(data[track.pointer:track.pointer+track.length])
            data+=bytes(-len(data)%4);at=len(data);data+=raw
            struct.pack_into('>I',data,tp+12*i+8,at)
    blob=build(bytes(data),rel,roots,xrefs)
    for joint in sorted(joints):blob,_=zero_root_channels(blob,joint)
    blob=compact(blob);after=archive_tracks(blob);node=0
    for i,(left,right) in enumerate(zip(original[2],after[2])):
        while i>=sum(original[1][:node+1]):node+=1
        if not (node in joints and left[0][4] in (5,6,7)) and left!=right:
            raise ValueError('Repack changed an unselected body stream')
    return blob


def audit_bank(pl,aj,*,root_joint,motions,engine_root_joint=None,contracts=None):
    """Check an explicit selection; unknown/custom consumers stay review-required.

    Callers supply the actual engine translation joint. A source bone called
    'Root' is not evidence that it is the fighter's extraction target.
    """
    if engine_root_joint==root_joint:raise ValueError('Engine outer root and extraction joint must differ')
    selected=set(motions);rows=[];found=set()
    for action in FighterDat(pl).actions:
        if action.motion not in selected:continue
        found.add(action.motion)
        clip=inspect_clip(aj[action.anim_offset:action.anim_offset+action.anim_size],root_joint)
        row=dict(action=action.index,motion=action.motion,clip=clip,
                 **diagnose(action.motion,action.flags,clip,_contract(action.motion,contracts)))
        if engine_root_joint is not None:
            outer=inspect_clip(aj[action.anim_offset:action.anim_offset+action.anim_size],engine_root_joint)
            row['engine_root']=outer
            if any(v['peak']>1e-5 for v in outer['translation'].values()):
                row['issues'].append('ENGINE_ROOT_ANIMATED_TRANSLATION');row['status']='REPAIR_REQUIRED'
        rows.append(row)
    if found!=selected:raise ValueError('Requested movement missing from bank')
    passed=all(row['status'] in ('CONTRACT_SATISFIED','NO_TRANSLATION') for row in rows)
    return dict(status='MOVEMENT_CONTRACTS_PASS' if passed else 'MOVEMENT_REVIEW_REQUIRED',
                root_joint=root_joint,engine_root_joint=engine_root_joint,rows=rows,native_accepted=False,
                scope='Explicit common-state consumers; quarter-frame diagnostic, not complete animation or native acceptance.')


def repair_common_bank(pl,aj,*,root_joint,motions,engine_root_joint=None,contracts=None):
    """Isolate selected streams and repack: safe for shared streams/aliases.

    Unselected FOBJ descriptors and streams remain byte-identical even when a
    selected root initially shares its buffer with a body track or other action.
    Bank offsets/sizes can change; callers must run their capacity gate again.
    """
    from .animation_archive import compact,pack,tracks as archive_tracks
    from vault.echo.datroot import build
    if engine_root_joint==root_joint:raise ValueError('Engine outer root and extraction joint must differ')
    selected=set(motions);ft=FighterDat(pl);entries={};reports=[];found=set()
    if any(_contract(m,contracts) is None for m in selected):
        raise ValueError('Custom or unreviewed movement requires an explicit separate contract')
    for action in ft.actions:
        if not action.symbol or not action.anim_size:continue
        original=aj[action.anim_offset:action.anim_offset+action.anim_size]
        blob=compact(original,symbols=[action.symbol])
        if action.motion in selected:
            found.add(action.motion);contract=_contract(action.motion,contracts)
            before=inspect_clip(blob,root_joint);diagnostic=diagnose(action.motion,action.flags,before)
            neutral={engine_root_joint} if engine_root_joint is not None else set()
            if contract.owner=='PHYSICS':neutral.add(root_joint)
            elif contract.owner=='ANIMATION_DELTA':
                if 'UNCONSUMED_AXES_REQUIRE_BODY_RESIDUAL' in diagnostic['issues']:
                    raise ValueError('Preserve unsupported axes as body motion before extracting this clip')
                ft.dat.set_u32(ft.action_table[0]+action.index*ACTION_SIZE+16,action.flags|0x80000000)
            elif 'LOCAL_POSE_WOULD_BE_EXTRACTED' in diagnostic['issues']:
                raise ValueError('Local-pose extraction flag requires explicit authoring')
            if neutral:blob=neutralize_translation(blob,neutral)
            reports.append(dict(action=action.index,motion=action.motion,before=before,diagnostic=diagnostic,
                                body_streams_preserved=True))
        if action.symbol in entries and entries[action.symbol][1]!=blob:
            raise ValueError('One public symbol requests conflicting movement policies')
        entries[action.symbol]=(action.symbol,blob)
    if found!=selected:raise ValueError('Requested movement missing from bank')
    bank,spans,_=pack(entries.values())
    for action in ft.actions:
        if action.symbol in spans:
            offset,size=spans[action.symbol];at=ft.action_table[0]+action.index*ACTION_SIZE
            ft.dat.set_u32(at+4,offset);ft.dat.set_u32(at+8,size)
    return ft.to_bytes(),bank,reports
