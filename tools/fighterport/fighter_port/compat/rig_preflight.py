"""Read-only layout gates for a fighter-rig capture, before opening Dolphin.

Checks descriptor traversal, draw dispatch and each live action-row node domain.
Passing these gates does not establish state reachability, callback ownership,
source fidelity, material semantics, collision mapping or native acceptance.
"""
from .rig_inventory import Archive, costume_inventory, bank_inventory


def costume_binding(payload, definition, *, costume_index=0):
    """Resolve the actual serialized MexCostume.file root names before launch."""
    if type(costume_index) is not int or not 0<=costume_index<len(definition['costumes']):
        raise ValueError('Explicit costume index outside definition')
    entry=definition['costumes'][costume_index]
    if 'jointSymbol' in entry or 'materialSymbol' in entry:
        raise ValueError('Costume symbols belong under file, not the costume object')
    binding=entry['file'];roots=dict(Archive(payload).roots)
    joint=binding['jointSymbol'];material=binding.get('materialSymbol')
    if joint not in roots or not joint.endswith('_joint') or joint.endswith('_matanim_joint'):
        raise ValueError('Configured costume joint root is absent')
    if material and (material not in roots or not material.endswith('_matanim_joint')):
        raise ValueError('Configured costume material root is absent')
    model=costume_inventory(payload,root_name=joint)
    if definition['boneDefinitions']['lookup']['boneCount']!=model['joint_count']:
        raise ValueError('Definition and costume joint counts differ')
    return dict(status='COSTUME_ROOTS_BOUND',joint=joint,material=material,
                joints=model['joint_count'],drawables=model['dobj_descriptor_count'])


def texture_animation_contract(costume, pl):
    """Refuse a known load-time mismatch before ftAnim_80070308 walks TObjs.

    The texture-animation count belongs to the PL model header. A costume with
    no material-animation root cannot supply the AObjs that a positive count
    requires. Root presence alone does not establish TObj/AObj correspondence,
    and count zero does not make inherited animate_texture script calls safe.
    Those bindings, callbacks and script consumers require separate evidence.
    """
    dat=Archive(pl);roots=[o for n,o in dat.roots if n.startswith('ftData')]
    if len(roots)!=1:raise ValueError('One fighter data root required')
    model=dat.ptr(roots[0]+8)
    if model is None:raise ValueError('Missing fighter model table')
    dat.require(model,12);count=dat.u32(model+8)
    material_roots=[n for n,_ in Archive(costume).roots if n.endswith('_matanim_joint')]
    issues=[]
    if count and not material_roots:
        issues.append(dict(code='TEXTURE_ANIMATION_ROOT_ABSENT',declared_count=count))
    return dict(status='TEXTURE_ANIMATION_LAYOUT_FAIL' if issues else 'TEXTURE_ANIMATION_PREREQUISITE_PASS',
                declared_count=count,material_roots=material_roots,issues=issues,
                tobj_aobj_binding='UNMEASURED' if count else 'NO_LOAD_TIME_TEXTURE_ANIMATION_WALK',
                script_consumers='UNMEASURED',native_accepted=False)


def figatree_nodes(payload):
    dat=Archive(payload)
    if not dat.roots or len({off for _,off in dat.roots})!=1:
        raise ValueError('One figatree root domain required; public aliases may share it')
    root=dat.roots[0][1];dat.require(root,20)
    counts=dat.ptr(root+12)
    if counts is None: raise ValueError('Missing figatree node count table')
    end=dat.struct_end(counts);values=[]
    for slot in range(counts,min(end,counts+256)):
        value=payload[32+slot]
        if value==255:
            if not values:raise ValueError('Empty figatree node table')
            return len(values)
        values.append(value)
    raise ValueError('No bounded figatree node terminator')


def costume_contract(payload):
    dat=Archive(payload);model=costume_inventory(payload);joints=model['joints']
    depth=[];issues=[];drawable_count=0
    for row in joints:
        parent=row['parent'];depth.append(0 if parent is None else depth[parent]+1)
        if depth[-1]>=30:issues.append(dict(code='ANIMATION_TRAVERSAL_DEPTH',joint=row['index'],depth=depth[-1]))
        for offset in row['dobj_offsets']:
            drawable_count+=1;material=dat.ptr(offset+8)
            if material is None:issues.append(dict(code='MISSING_MATERIAL',dobj=offset));continue
            dat.require(material,0x18);mode=dat.u32(material+4)
            classes=[1<<19,1<<20] if mode&(1<<30) else [1<<18]
            active=[bit for bit in classes if row['flags']&bit]
            if not active:issues.append(dict(code='DRAW_CLASS_DISABLED',joint=row['index'],dobj=offset))
            ancestors=[];ancestor=parent
            while ancestor is not None:
                ancestors.append(ancestor);ancestor=joints[ancestor]['parent']
            if active and not any(all(joints[i]['flags']&(bit<<10) for i in ancestors) for bit in active):
                issues.append(dict(code='ANCESTOR_DRAW_TRAVERSAL_DISABLED',joint=row['index'],dobj=offset))
    if not drawable_count:issues.append(dict(code='NO_DRAWABLES'))
    return dict(joints=len(joints),drawables=drawable_count,max_depth=max(depth),issues=issues,
                status='LAYOUT_GATES_PASS' if not issues else 'LAYOUT_GATES_FAIL')


def visibility_contract(pl, drawable_count, *, root_name=None, costume_index=0, hidden_dobjs=None):
    """Check body alternatives consumed by ftParts_80074B6C in traversal order.

    Mode 2 belongs to the separate metal model and uses a different DObj domain.
    This gate covers ordinary body modes 0, 1 and 3; it does not accept metal.
    """
    dat=Archive(pl);roots=[(n,o) for n,o in dat.roots if n==root_name or root_name is None and n.startswith('ftData')]
    if len(roots)!=1 or type(drawable_count) is not int or not 1<=drawable_count<=255:
        raise ValueError('One fighter root and byte-indexed drawable domain required')
    model=dat.ptr(roots[0][1]+8)
    if model is None:raise ValueError('Missing fighter model table')
    count=dat.u32(model);table=dat.ptr(model+4)
    if not 1<=count<=11 or table is None:raise ValueError('Invalid visibility group domain')
    if type(costume_index) is not int or costume_index<0:raise ValueError('Nonnegative costume index required')
    # A flat array of four pointers per costume, not a pointer-to-costume array.
    dat.require(table+costume_index*16,16)
    result=_visibility_modes(dat,table+costume_index*16,count,drawable_count,fallback=table)
    if hidden_dobjs is not None:
        if not isinstance(hidden_dobjs,list) or len(set(hidden_dobjs))!=len(hidden_dobjs) or any(type(i) is not int or not 0<=i<drawable_count for i in hidden_dobjs):
            raise ValueError('Unique in-domain hidden drawable indices required')
        by_mode={mode:sorted(set(hidden_dobjs)-{i for row in result['rows'] if row['mode']==mode for i in row['drawables']}) for mode in (0,1,3)}
        missing=sorted(set().union(*by_mode.values()))
        for mode,ids in by_mode.items():
            if ids:result['issues'].append(dict(code='OFFLINE_VISIBILITY_NOT_BOUND',mode=mode,drawables=ids))
        result.update(hidden_dobjs=hidden_dobjs,unbound_hidden_dobjs=missing,
                      unbound_hidden_by_mode=by_mode,
                      runtime_selection='UNMEASURED: group coverage does not prove initialization or state switching')
        result['status']='VISIBILITY_LAYOUT_FAIL' if result['issues'] else 'VISIBILITY_LAYOUT_PASS'
    return result


def _visibility_modes(dat, table, count, drawable_count, *, fallback=None):
    issues=[];rows=[]
    for mode in (0,1,3):
        groups=dat.ptr(table+4*mode)
        if groups is None and fallback is not None:groups=dat.ptr(fallback+4*mode)
        if groups is None:continue
        for group in range(count):
            header=groups+8*group;variants=dat.u32(header);entries=dat.ptr(header+4)
            if variants>256 or variants and entries is None:raise ValueError('Invalid visibility alternatives')
            seen=set()
            for variant in range(variants):
                at=entries+8*variant;n=dat.u32(at);indices=dat.ptr(at+4)
                if n>256 or n and indices is None:raise ValueError('Invalid drawable selection')
                ids=[]
                if n:
                    dat.require(indices,n);ids=list(dat.buf[32+indices:32+indices+n])
                if any(i>=drawable_count for i in ids):issues.append(dict(code='VISIBILITY_DRAWABLE_OUT_OF_RANGE',mode=mode,group=group,variant=variant))
                overlap=seen.intersection(ids)
                if overlap:issues.append(dict(code='VISIBILITY_ALTERNATIVES_OVERLAP',mode=mode,group=group,variant=variant,drawables=sorted(overlap)))
                seen.update(ids);rows.append(dict(mode=mode,group=group,variant=variant,drawables=ids))
    return dict(status='VISIBILITY_LAYOUT_PASS' if not issues else 'VISIBILITY_LAYOUT_FAIL',issues=issues,rows=rows,metal_model_unchecked=True)


def prepare(costume,pl,aj,*,required_actions,animation_capacity=32768,foreign_skeletons=None,movement_root=None,visibility_manifest=None):
    if type(animation_capacity) is not int or animation_capacity not in (32768,65504,131040):raise ValueError('Explicit supported animation capacity required')
    if (not isinstance(required_actions,list) or not required_actions or
            any(type(i) is not int or i<0 for i in required_actions) or len(set(required_actions))!=len(required_actions)):
        raise ValueError('Explicit unique required action indices required')
    model=costume_contract(costume);bank=bank_inventory(pl,aj);rows=[];issues=list(model['issues'])
    foreign_skeletons=foreign_skeletons or {}
    if not isinstance(foreign_skeletons,dict) or any(str(int(k))!=k or not 0<=int(k)<bank['action_count'] for k in foreign_skeletons):
        raise ValueError('Explicit foreign action domain required')
    for action,contract in foreign_skeletons.items():
        if (set(contract)!={'skeleton_kind','nodes','sha256'} or type(contract['skeleton_kind']) is not int or
                not 0<=contract['skeleton_kind']<64 or type(contract['nodes']) is not int or not 1<=contract['nodes']<=255 or
                not isinstance(contract['sha256'],str) or len(contract['sha256'])!=64):
            raise ValueError('Bound foreign skeleton contract required')
        if int(action) in required_actions:raise ValueError('Borrowed victim animation cannot satisfy an owned rig action')
    hidden=None
    if visibility_manifest is not None:
        import hashlib
        if visibility_manifest.get('costume_sha256')!=hashlib.sha256(costume).hexdigest():
            raise ValueError('Visibility manifest differs from costume')
        hidden=visibility_manifest['hidden_dobjs']
    visibility=visibility_contract(pl,model['drawables'],hidden_dobjs=hidden);issues.extend(visibility['issues'])
    texture_animation=texture_animation_contract(costume,pl);issues.extend(texture_animation['issues'])
    if any(i>=bank['action_count'] for i in required_actions):raise ValueError('Required action outside bank')
    for row in bank['rows']:
        current=dict(action=row['action'],motion=row['motion'],required=row['action'] in required_actions)
        if row['archive_status']=='ABSENT':
            current['status']='ABSENT'
            if current['required']:issues.append(dict(code='REQUIRED_ANIMATION_ABSENT',action=row['action']))
            if str(row['action']) in foreign_skeletons:issues.append(dict(code='FOREIGN_ANIMATION_ABSENT',action=row['action']))
        else:
            blob=aj[row['offset']:row['offset']+row['bytes']];count=figatree_nodes(blob)
            foreign=foreign_skeletons.get(str(row['action']))
            if foreign:
                actual=dict(skeleton_kind=row['flags']&63,nodes=count,sha256=row['sha256'])
                current.update(nodes=count,skeleton_kind=actual['skeleton_kind'],status='FOREIGN_SKELETON_MATCH' if actual==foreign else 'FOREIGN_SKELETON_MISMATCH')
                if actual!=foreign:issues.append(dict(code='FOREIGN_SKELETON_MISMATCH',action=row['action']))
            else:
                current.update(nodes=count,status='MATCH' if count==model['joints'] else 'RIG_NODE_MISMATCH')
                if count!=model['joints']:issues.append(dict(code='RIG_NODE_MISMATCH',action=row['action'],nodes=count))
            if row['bytes']>animation_capacity:issues.append(dict(code='ANIMATION_BUFFER_EXCEEDED',action=row['action'],bytes=row['bytes']))
        rows.append(current)
    movement=None
    if movement_root is not None:
        from .movement_ownership import audit_bank,common_contract
        motions=[r['motion'] for r in bank['rows'] if r['action'] in required_actions and common_contract(r['motion'])]
        movement=audit_bank(pl,aj,root_joint=movement_root,motions=motions)
        for row in movement['rows']:
            issues.extend(dict(code=code,action=row['action']) for code in row['issues'])
    result=dict(status='LAYOUT_GATES_PASS' if not issues else 'LAYOUT_GATES_FAIL',costume=model,visibility=visibility,texture_animation=texture_animation,actions=rows,issues=issues,
                required_actions=required_actions,native_accepted=False,
                scope='All present action rows checked; required action list is explicit, not an inferred reachable-state proof.')
    if movement is not None:result['movement']=movement
    return result
