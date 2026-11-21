"""Numeric-slot bone contracts; editor and decomp labels are not interchangeable.

The field order below is the storage layout in HSDRaw's SBM_BoneLookupTable.
It does not claim that a similarly named engine enum has the same numeric slot.
"""
SLOTS = ('top trans xRot yRot hip waist lLegA lLeg lKnee lFootA lFoot '
         'rLegA rLeg rKnee rFootA rFoot waistB bust lClavicle lShoulderA '
         'lShoulder lArm lHand lIndex1 lIndex2 lMiddle1 lMiddle2 lRing1 '
         'lRing2 lPinky1 lPinky2 lHave lThumb1 lThumb2 neckN headN rClavicle '
         'rShoulderA rShoulder rArm rHand rIndex1 rIndex2 rMiddle1 rMiddle2 '
         'rRing1 rRing2 rPinky1 rPinky2 rHave rThumb1 rThumb2 throw extra').split()


def count_check(count):
    if type(count) is not int or not 1 <= count <= 255:
        raise ValueError('Bone count must be 1..255; index 255 is the absent sentinel')


def decode(forward, reverse, count):
    count_check(count)
    if len(forward) != 54 or len(reverse) != count:
        raise ValueError('Exact forward and reverse table domains required')
    if any(type(i) is not int or not (0 <= i < count or i == 255) for i in forward):
        raise ValueError('Forward table contains invalid joint index')
    if any(type(i) is not int or not (0 <= i < 54 or i == 255) for i in reverse):
        raise ValueError('Reverse table contains invalid semantic slot')
    aliases = {}
    for slot, joint in enumerate(forward):
        if joint != 255:aliases.setdefault(joint, []).append(slot)
    for joint, slot in enumerate(reverse):
        if joint in aliases:
            if slot not in aliases[joint]:raise ValueError('Reverse table does not identify a matching forward slot')
        elif slot != 255:raise ValueError('Unmapped helper has a reverse semantic slot')
    return dict(schema='mocap-numeric-bone-lookup-v1', count=count,
        forward=list(forward), reverse=list(reverse),
        slots=[dict(slot=i,editor_label=SLOTS[i],joint=None if j==255 else j) for i,j in enumerate(forward)],
        aliases=[dict(joint=j,slots=slots,reverse_winner=reverse[j]) for j,slots in sorted(aliases.items()) if len(slots)>1],
        hsdraw_last_slot_wins=all(reverse[j]==slots[-1] for j,slots in aliases.items()),
        native_accepted=False)


def from_editor_json(value):
    if set(value)-set(SLOTS)-{'boneCount','trimmedSize'} or set(SLOTS)-set(value):
        raise ValueError('Complete recognized editor lookup fields required')
    count=value['boneCount'];count_check(count)
    forward=[value[name] for name in SLOTS]
    if any(type(j) is not int or not (0<=j<count or j==255) for j in forward):
        raise ValueError('Invalid editor joint index')
    reverse=[255]*count
    for slot,joint in enumerate(forward):
        if joint!=255:reverse[joint]=slot
    result=decode(forward,reverse,count)
    result['scope']='Editor JSON projected through HSDRaw last-slot-wins behavior; compare exported and live tables separately.'
    return result


def from_plco(payload, fighter_kind):
    """Read a selected exported ftLoadCommonData table through DAT relocations.

    The caller binds fighter_kind to the project/ISO fighter definition; this
    pointer array has no embedded count from which to discover roster identity.
    """
    from .rig_inventory import Archive
    if type(fighter_kind) is not int or not 0<=fighter_kind<=255:
        raise ValueError('Explicit fighter kind in 0..255 required')
    dat=Archive(payload)
    roots=[offset for name,offset in dat.roots if name=='ftLoadCommonData']
    if len(roots)!=1:raise ValueError('One ftLoadCommonData root required')
    table=dat.ptr(roots[0]+0x10)
    if table is None:raise ValueError('Common bone lookup array absent')
    row=dat.ptr(table+fighter_kind*4)
    if row is None:raise ValueError('Selected fighter lookup absent')
    dat.require(row,12);reverse=dat.ptr(row);forward=dat.ptr(row+4);count=dat.u32(row+8)
    count_check(count)
    if reverse is None or forward is None:raise ValueError('Lookup data pointer absent')
    dat.require(reverse,count);dat.require(forward,54)
    r=decode(list(payload[32+forward:32+forward+54]),list(payload[32+reverse:32+reverse+count]),count)
    r.update(fighter_kind=fighter_kind,offsets=dict(table=table,row=row,forward=forward,reverse=reverse),
             scope='Exported numeric lookup; caller binds fighter kind and disc identity.')
    return r


def compile_lookup(order, bindings, *, alias_winners=None):
    """Resolve 54 explicit joint names/None entries against one frozen rig order."""
    count_check(len(order))
    if any(not isinstance(j,str) or not j for j in order) or len(set(order))!=len(order):
        raise ValueError('Unique nonempty joint names required')
    if not isinstance(bindings,list) or len(bindings)!=54:
        raise ValueError('All 54 numeric slots need explicit bindings, including absent slots')
    index={j:i for i,j in enumerate(order)};forward=[];groups={}
    for slot,joint in enumerate(bindings):
        if joint is not None and (not isinstance(joint,str) or joint not in index):
            raise ValueError(f'Unknown bound joint at slot {slot}')
        forward.append(255 if joint is None else index[joint])
        if joint is not None:groups.setdefault(joint,[]).append(slot)
    expected={j:slots[-1] for j,slots in groups.items() if len(slots)>1}
    winners={} if alias_winners is None else alias_winners
    if (not isinstance(winners,dict) or winners!=expected or
            any(type(slot) is not int for slot in winners.values())):
        raise ValueError('Every alias requires its explicit HSDRaw last-slot reverse winner')
    reverse=[255]*len(order)
    for slot,joint in enumerate(forward):
        if joint!=255:reverse[joint]=slot
    result=decode(forward,reverse,len(order));result['joint_order']=list(order)
    result['editor_json']=dict(boneCount=len(order),**dict(zip(SLOTS,forward)))
    result['scope']='Explicit numeric lookup only. Root conventions and consumer behavior require separate evidence.'
    return result


def remap_references(references, source_order, target_order, bindings):
    """Resolve every recorded direct consumer; no missing or anatomy-based fallback."""
    for order in (source_order,target_order):
        count_check(len(order))
        if any(not isinstance(j,str) or not j for j in order) or len(set(order))!=len(order):
            raise ValueError('Unique named rig order required')
    if not references or len({r['consumer'] for r in references})!=len(references):
        raise ValueError('Unique nonempty consumer references required')
    if set(bindings)!={r['consumer'] for r in references}:
        raise ValueError('Every recorded consumer requires an explicit target binding')
    result=[]
    for ref in references:
        old=ref['joint'];target=bindings[ref['consumer']]
        if type(old) is not int or not 0<=old<len(source_order):raise ValueError('Source reference outside rig')
        if not isinstance(target,str) or target not in target_order:raise ValueError('Target reference outside rig')
        result.append(dict(consumer=ref['consumer'],source_index=old,source_joint=source_order[old],
                           target_index=target_order.index(target),target_joint=target,
                           geometry_status='LOCAL_COORDINATE_REVIEW_REQUIRED'))
    return dict(status='EXPLICIT_INDICES_RESOLVED_GEOMETRY_PENDING',references=result,native_accepted=False)
