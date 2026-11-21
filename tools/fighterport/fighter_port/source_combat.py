"""Read a bounded converted ACMD game timeline without executing source code.

An animation conversion is not a combat conversion. This reader preserves source
bone names, frame numbers, hit IDs and replacements for an explicit authoring
contract. Unknown control flow is refused; unknown statements remain visible.
The community text format is not a substitute for revision-matched native ACMD.
"""
import hashlib
import math
import re
import numpy as np


def arguments(text):
    values=[];start=0;depth=0;quoted=False
    for i,c in enumerate(text):
        if c=='"' and (i==0 or text[i-1]!='\\'):quoted=not quoted
        if quoted:continue
        if c=='(':depth+=1
        elif c==')':depth-=1
        elif c==',' and depth==0:values.append(text[start:i].strip());start=i+1
        if depth<0:raise ValueError('Unbalanced source arguments')
    if depth or quoted:raise ValueError('Unbalanced source arguments')
    return values+[text[start:].strip()]


def number(value):
    n=float(value)
    if not math.isfinite(n):raise ValueError('Nonfinite source number')
    return int(n) if n.is_integer() else n


def _hash(value):
    m=re.fullmatch(r'Hash40::new\("([^"\n]+)"\)',value)
    if not m:raise ValueError('Expected explicit source bone/attribute name')
    return m[1]


def _flatten(lines):
    """Only unconditional execution guards and fixed finite loops are accepted."""
    result=[];i=0
    while i<len(lines):
        line=lines[i].strip();i+=1
        if not line or line.startswith('//') or line=='}':continue
        if line in ('if macros::is_excute(agent) {','{'):continue
        loop=re.fullmatch(r'for _ in 0\.\.([0-9]+) \{',line)
        if loop:
            count=int(loop[1]);depth=1;body=[]
            if not 1<=count<=128:raise ValueError('Unbounded source loop')
            while i<len(lines) and depth:
                item=lines[i];i+=1;depth+=item.count('{')-item.count('}')
                if depth:body.append(item)
            if depth:raise ValueError('Unclosed source loop')
            result.extend(_flatten(body)*count);continue
        if line.startswith(('if','else','while ','loop ')) or (('{' in line or '}' in line) and not line.endswith(';')):
            raise ValueError('Unsupported source control flow: '+line)
        result.append(line)
    return result


def read_game(text,game=None):
    starts=list(re.finditer(r'unsafe extern "C" fn (game_[a-z0-9_]+)\([^\n]*\) \{',text))
    selected=[m for m in starts if game is None or m[1]==game]
    if len(selected)!=1:raise ValueError('Select exactly one source game function')
    m=selected[0];end=text.find('unsafe extern',m.end())
    body=text[m.end():end if end>=0 else len(text)]
    # The next function is the boundary even when the converted formatter has
    # irregular indentation. Do not flatten effect/sound/expression sidecars.
    frame=0.;events=[];unknown=[]
    for line in _flatten(body.splitlines()):
        call=re.fullmatch(r'(frame|wait)\(agent\.lua_state_agent,\s*([0-9.]+)\);',line)
        if call:
            value=number(call[2]);new=value if call[1]=='frame' else frame+value
            if new<frame:raise ValueError('Source clock moves backwards')
            frame=new;continue
        event=dict(frame=frame,statement=line)
        if line.startswith('macros::ATTACK(agent,'):
            a=arguments(line[line.index('(')+1:line.rindex(')')])
            if len(a)!=37:raise ValueError('ATTACK signature changed')
            p2=[]
            for value in a[13:16]:
                if value=='None':p2.append(None)
                else:
                    optional=re.fullmatch(r'Some\(([^)]+)\)',value)
                    if not optional:raise ValueError('Invalid capsule endpoint')
                    p2.append(number(optional[1]))
            if any(x is None for x in p2) and not all(x is None for x in p2):raise ValueError('Partial capsule endpoint')
            event.update(kind='attack',id=int(number(a[1])),part=int(number(a[2])),bone=_hash(a[3]),
                         damage=number(a[4]),angle=int(number(a[5])),kbg=int(number(a[6])),fkb=int(number(a[7])),bkb=int(number(a[8])),
                         radius=number(a[9]),p1=[number(x) for x in a[10:13]],p2=None if p2[0] is None else p2,
                         hitlag=number(a[16]),sdi=number(a[17]),setoff=a[18],lr=a[19],set_weight=a[20],
                         shield=number(a[21]),trip=number(a[22]),rehit=int(number(a[23])),booleans=a[24:29],
                         situation=a[29],category=a[30],part_mask=a[31],friendly=a[32],attribute=_hash(a[33]),
                         sound=a[34],sound_attribute=a[35],region=a[36])
        elif line=='AttackModule::clear_all(agent.module_accessor);':event['kind']='clear_all'
        elif (clear:=re.fullmatch(r'AttackModule::clear\(agent.module_accessor, ([0-9]+), false\);',line)):
            event.update(kind='clear',id=int(clear[1]))
        elif (flag:=re.fullmatch(r'WorkModule::(on|off)_flag\(agent.module_accessor, \*([A-Z0-9_]+)\);',line)):
            event.update(kind='flag',flag=flag[2],value=flag[1]=='on')
        elif (rate:=re.fullmatch(r'macros::FT_MOTION_RATE\(agent, ([0-9.]+)\);',line)):
            event.update(kind='rate',value=number(rate[1]))
        else:event['kind']='unhandled';unknown.append(event)
        events.append(event)
    active={};peak=0
    for e in events:
        if e['kind']=='attack':active[e['id']]=e
        elif e['kind']=='clear_all':active.clear()
        elif e['kind']=='clear':active.pop(e['id'],None)
        peak=max(peak,len(active))
    return dict(schema='source-combat-timeline-v1',game=m[1],source_sha256=hashlib.sha256(text.encode()).hexdigest(),
                events=events,unknown=unknown,peak_hitboxes=peak,bones=sorted({e['bone'] for e in events if e['kind']=='attack'}),
                scope='Source animation-frame events only; no target binding, timing adaptation or gameplay acceptance')


def frame_map(source_frame,source_start,source_end,target_end,entry_anchor=0):
    """First target integer pose reaching the declared source animation frame."""
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (source_frame,source_start,source_end,target_end,entry_anchor)):
        raise ValueError('Finite animation clock required')
    if not 0<=source_start<source_end or target_end<=0:raise ValueError('Invalid animation clock')
    if source_frame<source_start:raise ValueError('Combat event was cut out of the animation')
    if entry_anchor:
        if source_start or not 0<entry_anchor<min(source_end,target_end):raise ValueError('Invalid entry-anchored clock')
        if source_frame<=entry_anchor:return max(1,math.ceil(source_frame))
        return math.ceil(entry_anchor+(source_frame-entry_anchor)*(target_end-entry_anchor)/(source_end-entry_anchor)-1e-9)
    return max(1,math.ceil((source_frame-source_start)*target_end/(source_end-source_start)-1e-9))


def compile_events(timeline,clock,bindings,policy):
    """Compile an explicitly reviewed sphere adaptation, never donor geometry.

    Every omitted hit or statement needs a reason in the caller's policy.
    Source IDs retain their native slots until an explicit clear. The caller
    supplies the actual animation clock and measured local binding matrices.
    """
    from .combat import command,fixed
    from vault.echo.subactions import FighterDat
    if not policy.get('engine_differences'):
        raise ValueError('Explicit cross-engine combat adaptation required')
    if policy.get('capsules')!='enclosing_sphere' or policy.get('fractional_damage')!='ceil':
        raise ValueError('Explicit capsule and fractional damage policy required')
    if policy.get('motion_rates')!='animation_pose_clock':raise ValueError('Declare animation-pose clock ownership')
    if policy.get('rehits')!='explicit_refresh':raise ValueError('Declare repeat-hit adaptation')
    if policy.get('groups')!='source_part':raise ValueError('Declare source-part hit-history mapping')
    omitted=policy.get('omit_hit_ids',{});ignored=policy.get('omit_statements',{})
    if any(not reason for reason in list(omitted.values())+list(ignored.values())):raise ValueError('Omissions need reasons')
    slots={};items=[];geometry=[];last=None;adaptations=[]
    def emit(frame,item):
        nonlocal last
        native=frame_map(frame,**clock)
        if native>clock['target_end']:
            raise ValueError('Source event outside the actual animation domain')
        if native!=last:items.append(command('asynchronous_timer',frame=native));last=native
        items.append(item)
        return native
    events=[(e['frame'],i*3,e) for i,e in enumerate(timeline['events'])]
    # Melee has no Ultimate rehit interval field. Refresh exactly this hit at
    # the mapped source intervals, stopping at its next update or clear.
    for i,e in enumerate(timeline['events']):
        if e['kind']!='attack' or not e['rehit']:continue
        stop=next((x['frame'] for x in timeline['events'][i+1:] if x['kind']=='clear_all' or
                   (x['kind'] in ('clear','attack') and x['id']==e['id'])),None)
        if stop is None:raise ValueError('Repeat hit has no terminating update/clear')
        at=e['frame']+e['rehit']
        while at<stop:
            events.extend([(at,i*3+1,dict(kind='clear',id=e['id'],frame=at)),
                           (at,i*3+2,dict(e,frame=at,rehit=0))])
            at+=e['rehit']
    for _,_,e in sorted(events,key=lambda row:(row[0],row[1])):
        kind=e['kind'];frame=e['frame']
        if kind=='attack':
            if str(e['id']) in omitted:
                adaptations.append(dict(frame=frame,omitted_hit=e['id'],reason=omitted[str(e['id'])]));continue
            if not 0<=e['part']<=7:raise ValueError('Source part outside native hit-group domain')
            if e['bone'] not in bindings:raise ValueError('Missing named source bone: '+e['bone'])
            binding=bindings[e['bone']];matrix=np.asarray(binding['matrix'],float)
            if type(binding.get('bone')) is not int or not 0<=binding['bone']<=255:
                raise ValueError('Explicit native raw bone index required')
            if e['radius']<=0 or e['rehit']<0:raise ValueError('Invalid source radius/rehit interval')
            if matrix.shape!=(4,4) or not np.isfinite(matrix).all() or not np.allclose(matrix[3],[0,0,0,1]):
                raise ValueError('Invalid measured bone binding')
            if not np.allclose(matrix[:3,:3].T@matrix[:3,:3],np.eye(3),atol=1e-4) or np.linalg.det(matrix[:3,:3])<0:
                raise ValueError('Scaled/reflected binding needs explicit radius and handedness authoring')
            point=np.asarray(e['p1'],float);radius=e['radius']
            if e['p2'] is not None:
                other=np.asarray(e['p2'],float);radius+=float(np.linalg.norm(other-point))/2;point=(point+other)/2
            local=(matrix@np.r_[point,1])[:3]
            if e['id'] not in slots:
                free=[i for i in range(4) if i not in slots.values()]
                if not free:raise ValueError('More than four live source hits; author a reviewed adaptation')
                slots[e['id']]=free[0]
            angle=e['angle']
            if angle>361:
                if str(angle) not in policy.get('angles',{}):raise ValueError('Unsupported Ultimate angle')
                angle=policy['angles'][str(angle)]
            if e['attribute'] not in policy.get('elements',{}):raise ValueError('Explicit native element mapping required')
            situation=e['situation'].removeprefix('*COLLISION_SITUATION_MASK_')
            if situation not in ('G','A','GA'):raise ValueError('Unknown collision situation')
            if e['setoff'] not in ('*ATTACK_SETOFF_KIND_ON','*ATTACK_SETOFF_KIND_OFF','*ATTACK_SETOFF_KIND_THRU'):
                raise ValueError('Unknown source clank mode')
            if e['lr'] not in ('*ATTACK_LR_CHECK_F','*ATTACK_LR_CHECK_B','*ATTACK_LR_CHECK_POS'):
                raise ValueError('Unknown source facing mode')
            x,y,z=map(fixed,local)
            fields=dict(id=slots[e['id']],hit_group=e['part'],bone=binding['bone'],use_common_bone_ids=0,
                        damage=math.ceil(e['damage']),size=fixed(radius),z_offset=x,y_offset=y,x_offset=z,
                        angle=angle,knockback_growth=e['kbg'],weight_set_knockback=e['fkb'],base_knockback=e['bkb'],
                        item_hit_interaction=1,clank=int(e['setoff']=='*ATTACK_SETOFF_KIND_ON'),rebound=1,
                        element=policy['elements'][e['attribute']],shield_damage=round(e['shield']),
                        hit_sfx_severity={'*ATTACK_SOUND_LEVEL_S':0,'*ATTACK_SOUND_LEVEL_M':1,'*ATTACK_SOUND_LEVEL_L':2}.get(e['sound'],2),
                        hit_sfx_kind=2 if 'KICK' in e['sound_attribute'] else 3,
                        hit_grounded_fighters=int(situation in ('G','GA')),hit_aerial_fighters=int(situation in ('A','GA')))
            native=emit(frame,command('create_hitbox',**fields))
            geometry.append(dict(source_frame=frame,native_frame=native,source_id=e['id'],source_bone=e['bone'],
                                 source_p1=e['p1'],source_p2=e['p2'],native_fields=fields,local_xyz=local.tolist(),radius=radius,
                                 source_radius=e['radius'],rehit=e['rehit']))
        elif kind=='clear_all':emit(frame,command('clear_hitboxes'));slots.clear()
        elif kind=='clear':
            if e['id'] in slots:emit(frame,command('remove_hitbox',index=slots.pop(e['id'])))
        elif kind=='flag':
            if e['flag']=='FIGHTER_STATUS_ATTACK_AIR_FLAG_ENABLE_LANDING':
                emit(frame,command('set_flag',flag=0,value=int(e['value'])))
            elif e['flag'] in ('FIGHTER_STATUS_ATTACK_FLAG_ENABLE_COMBO','FIGHTER_STATUS_ATTACK_FLAG_ENABLE_NO_HIT_COMBO'):
                emit(frame,command('enable_jab_followup',toggle=int(e['value'])))
            elif e['flag']=='FIGHTER_STATUS_ATTACK_FLAG_START_SMASH_HOLD':
                emit(frame,command('start_smash_charge',charge_frames=60,charge_rate=350,color_animation=119))
            elif e['statement'] not in ignored:raise ValueError('Unreviewed source flag: '+e['flag'])
        elif kind=='rate':adaptations.append(dict(frame=frame,source_rate=e['value'],policy='Events follow the converted animation pose clock'))
        elif e['statement'] not in ignored:raise ValueError('Unreviewed source statement: '+e['statement'])
    if slots:raise ValueError('Uncleared hitboxes at source script end')
    items.append(command('end_of_script'))
    encoded,pointers=FighterDat.encode_script(items)
    if pointers:raise ValueError('Source combat compiler unexpectedly emitted pointers')
    return items,dict(geometry=geometry,adaptations=adaptations,policy=policy,clock=clock,
                      source_sha256=timeline['source_sha256'],script_sha256=hashlib.sha256(encoded).hexdigest(),
                      status='SOURCE_GEOMETRY_COMPILED_NOT_GAMEPLAY_ACCEPTED')


def install_scripts(payload,scripts):
    """Reuse only old script spans referenced exclusively by selected rows.

    Nonselected pointers, interior entry points, roots and unknown/truncated
    old blocks prevent reuse. New pointer-free scripts may share exact bytes.
    Everything outside reusable spans and selected action pointers stays put.
    """
    import struct
    from vault.echo.subactions import FighterDat,ACTION_SIZE,HEADER_SIZE
    from vault.echo.datroot import parse
    ft=FighterDat(payload);table=ft.action_table[0]
    if any(type(i) is not int or not 0<=i<len(ft.actions) for i in scripts):raise ValueError('Invalid selected action')
    slots={table+i*ACTION_SIZE+12 for i in scripts}
    # HSD_ArchiveLocateExtern follows a data-relative chain ending at -1.
    # These write sites are not represented by ordinary relocation entries.
    data,_,_,xrefs=parse(payload);external=set()
    for offset,_ in xrefs:
        seen_chain=set()
        while offset!=0xffffffff:
            if offset%4 or offset<0 or offset+4>len(data) or offset in seen_chain:
                raise ValueError('Invalid external reference chain')
            seen_chain.add(offset);external.add(offset)
            offset=struct.unpack_from('>I',data,offset)[0]
    if slots&external:raise ValueError('Selected script pointer is externally rebound')
    pools=[];seen=set()
    for index in scripts:
        old=ft.script(index)
        if old is None or old.offset in seen:continue
        seen.add(old.offset)
        terminal=next((c for c in old.commands if c.code==0),None)
        if terminal is None:continue
        start,end=old.offset,terminal.offset+terminal.size
        if any(start<=offset<end for offset in external):continue
        incoming=[r for r in ft.dat.relocs if start<=ft.dat.u32(r)<end]
        if any(r not in slots or ft.dat.u32(r)!=start for r in incoming) or any(start<=off<end for _,off in ft.dat.roots):continue
        pools.append([start,end])
    data=bytearray(ft.dat.buf[HEADER_SIZE:HEADER_SIZE+ft.dat.data_size]);relocs=set(ft.dat.relocs)
    for start,end in pools:
        data[start:end]=bytes(end-start)
        relocs={r for r in relocs if not start<=r<end}
    receipts=[];shared={};original_size=len(data)
    for index,items in sorted(scripts.items()):
        blob,pointers=FighterDat.encode_script(items)
        if pointers:raise ValueError('Source script reuse requires pointer-free output')
        if blob in shared:offset=shared[blob];allocation='shared'
        else:
            fits=[p for p in pools if p[1]-p[0]>=len(blob)]
            if fits:
                pool=min(fits,key=lambda p:p[1]-p[0]);offset=pool[0];pool[0]+=len(blob);allocation='owned_old_span'
            else:
                offset=(len(data)+3)//4*4;data+=bytes(offset-len(data)+len(blob));allocation='appended'
            data[offset:offset+len(blob)]=blob;shared[blob]=offset
        pointer=table+index*ACTION_SIZE+12;struct.pack_into('>I',data,pointer,offset);relocs.add(pointer)
        receipts.append(dict(action=index,bytes=len(blob),offset=offset,allocation=allocation))
    ft.dat._rebuild(bytes(data),relocs);result=ft.dat.to_bytes();check=FighterDat(result)
    for index,items in scripts.items():
        if FighterDat.encode_script(check.script_items(index))!=FighterDat.encode_script(items):raise ValueError('Source script readback differs')
    return result,dict(rows=receipts,data_growth=len(data)-original_size)


def prepare_contract(fighter, animation, manifest, directory):
    """Compile a pinned source contract and compare it to selected installed rows.

    Hashes cover the input pair, source text bytes, and each actual animation
    span. Bindings and cross-engine decisions remain explicit author inputs.
    A matching script is source-contract evidence, not a live contact verdict.
    """
    import struct
    from pathlib import Path
    from vault.echo.subactions import FighterDat
    from .compat.animation_archive import tracks
    digest=lambda data:hashlib.sha256(data).hexdigest()
    if manifest.get('schema')!='source-combat-contract-v1':raise ValueError('Unknown source combat contract')
    for key,data in (('fighter_sha256',fighter),('animation_sha256',animation)):
        if manifest.get(key)!=digest(data):raise ValueError('Input hash mismatch: '+key)
    ft=FighterDat(fighter);scripts={};rows=[]
    entries=manifest.get('actions',[])
    if not entries:raise ValueError('Select source combat actions explicitly')
    for entry in entries:
        index=entry['action']
        if type(index) is not int or not 0<=index<len(ft.actions) or index in scripts:
            raise ValueError('Invalid or duplicate selected action')
        action=ft.actions[index]
        if not action.anim_size or action.motion!=entry['motion']:raise ValueError('Action motion preimage differs')
        span=animation[action.anim_offset:action.anim_offset+action.anim_size]
        if len(span)!=action.anim_size or digest(span)!=entry['animation_sha256']:
            raise ValueError('Action animation preimage differs')
        source_path=Path(directory)/entry['source']
        source=source_path.read_bytes()
        if digest(source)!=entry['source_sha256']:raise ValueError('Source text hash mismatch')
        clock=entry['clock']
        actual_end=struct.unpack_from('>f',tracks(span)[0],8)[0]
        if clock.get('source_start')!=0:raise ValueError('Restore trimmed source poses before combat import')
        if clock.get('target_end')!=actual_end:raise ValueError('Declared clock differs from actual animation')
        # Entry anchoring is only valid with a separately installed rate owner.
        if clock.get('entry_anchor') and not entry.get('playback_contract'):
            raise ValueError('Entry-anchored clock requires an explicit playback contract')
        timeline=read_game(source.decode('utf-8'),entry.get('game'))
        items,receipt=compile_events(timeline,clock,entry['bindings'],entry['policy'])
        expected,_=FighterDat.encode_script(items)
        existing=ft.script_items(index)
        actual=FighterDat.encode_script(existing)[0] if existing is not None else b''
        receipt.update(action=index,motion=action.motion,source=str(source_path.resolve()),
                       source_file_sha256=digest(source),animation_sha256=digest(span),
                       installed_script_matches=actual==expected)
        scripts[index]=items;rows.append(receipt)
    return scripts,dict(schema='source-combat-audit-v1',rows=rows,
                        mismatched_actions=[r['action'] for r in rows if not r['installed_script_matches']],
                        status='SOURCE_SCRIPTS_MATCH' if all(r['installed_script_matches'] for r in rows) else 'SOURCE_SCRIPTS_DIFFER',
                        acceptance='Selected scripts only; requires source pose, live geometry, contacts and callback validation')


def handle(args):
    """Shared Randall/harness operations; stage into a fresh directory only."""
    import json
    from pathlib import Path
    path=Path(args['combat_contract']).resolve()
    manifest=json.loads(path.read_text())
    fighter=Path(args['fighter']).read_bytes();animation=Path(args['animation']).read_bytes()
    scripts,report=prepare_contract(fighter,animation,manifest,path.parent)
    if args['op']=='source_combat_audit':return report
    if args['op']!='source_combat_install':raise ValueError('Unknown source combat operation')
    out=Path(args['out']).resolve()
    if out.exists():raise ValueError('Choose a fresh source combat output directory')
    changed,allocation=install_scripts(fighter,scripts)
    updated=dict(manifest,fighter_sha256=hashlib.sha256(changed).hexdigest())
    # Resolve source paths before moving the contract to another directory.
    updated['actions']=[dict(e,source=str((path.parent/e['source']).resolve())) for e in manifest['actions']]
    _,check=prepare_contract(changed,animation,updated,out)
    if check['status']!='SOURCE_SCRIPTS_MATCH':raise ValueError('Installed source script readback differs')
    out.mkdir(parents=True)
    (out/'fighter.dat').write_bytes(changed);(out/'animation.dat').write_bytes(animation)
    (out/'combat-contract.json').write_text(json.dumps(updated,indent=2))
    report.update(output=str(out),allocation=allocation,readback=check,
                  status='SOURCE_SCRIPTS_STAGED_NOT_GAMEPLAY_ACCEPTED')
    (out/'source-combat.json').write_text(json.dumps(report,indent=2))
    return report
