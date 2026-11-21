"""Mechanic coverage is independent of special slots and successful compilation.

Expected mechanics come from the port review; source-only entry points add
automatic obligations. Adapters must name a real generated handler and state
their adaptation. An unclaimed obligation stays unfinished in every package.
"""
import re

PROFILES={
    'ranno': {
        'stored_darts':'Neutral charge, storage and projectile release',
        'poison':'Poison application and attack/contact rules',
        'recovery':'Rising recovery, dive and landing',
        'spin_fan':'Spin projectile fan',
        'tongue_capture':'Tongue opponent capture and pull',
        'stage_sling':'Tongue stage-contact sling',
        'bubble_launch':'Tongue-to-bubble self launch',
        'bubble_capture':'Steerable bubble, opponent capture and escape',
    },
    'loxodont': {
        'boulder_charge':'Boulder charge, aim and release scaling',
        'boulder_batting':'Attacks redirect and strengthen the boulder',
        'lava_pools':'Boulder/side-special pools, activation and removal',
        'molten_resource':'Molten charge pickup, cap and stock reset',
        'powered_down':'Resource-dependent down-special branches and shield override',
        'powered_strongs':'Resource-powered strong attack aftershocks',
        'command_grab':'Side-special native capture and release',
        'recovery':'Rising recovery and damaging landing',
    },
}


def requirements(game):
    result={f'mechanic:{key}':dict(id=f'mechanic:{key}',label=label,kind='mechanic')
            for key,label in PROFILES.get(game.get('fighter'),{}).items()}
    if game.get('game')!='rivals2':return list(result.values())
    for move in (game.get('moves') or {}).values():
        attack=move.get('rivals2_attack')
        if not attack:continue
        if move.get('entry_trigger')=='compiled' and move.get('conditional_only') and move.get('windows'):
            target=move['windows'][0][1]
            key=f'branch:{attack}:{target}'
            result[key]=dict(id=key,label=f'{attack}: compiled entry into {target}',kind='source_branch')
        for event in move.get('window_cancels') or []:
            c=event['condition'];kind=c.get('WindowCancelType','').split('::')[-1]
            if kind.startswith('CharacterSpecific'):
                target=c.get('PostCancelWindowStringTableKey','')
                key=f'condition:{attack}:{kind}:{target}'
                result[key]=dict(id=key,label=f'{attack}: {kind} selects {target}',kind='source_condition')
        for creation in move.get('articles') or []:
            if creation.get('trigger')=='compiled':
                key=f'article:{attack}:{creation["id"]}'
                result[key]=dict(id=key,label=f'{attack}: compiled {creation["id"]} creation',kind='source_article')
    return list(result.values())


def assess(game,mine):
    expected={row['id']:row for row in requirements(game)}
    source='\n'.join(mine.get('source') or [])+'\n'+'\n'.join(i.get('code','') for i in mine.get('items') or [])
    claims={}
    for claim in mine.get('mechanics') or []:
        status=claim.get('status')
        if status not in ('implemented','adapted','unfinished'):raise ValueError('unknown mechanic status')
        if not claim.get('id') or not claim.get('detail'):raise ValueError('mechanic requires an id and explanation')
        handler=claim.get('handler','')
        if status!='unfinished':
            if not re.fullmatch(r'[A-Za-z_]\w*',handler):raise ValueError('mechanic requires a generated native handler')
            if not re.search(r'\b'+re.escape(handler)+r'\s*\([^;{}]*\)\s*\{',source):
                raise ValueError(f'mechanic handler {handler} is not built')
        for key in [claim['id'],*claim.get('covers',[])]:
            if key in claims:raise ValueError(f'duplicate mechanic claim: {key}')
            claims[key]=claim
            if key not in expected:
                if key!=claim['id']:raise ValueError(f'mechanic claims absent source obligation: {key}')
                expected[key]=dict(id=key,label=claim.get('label',key),kind='mechanic')
    rows=[]
    for key,requirement in expected.items():
        claim=claims.get(key,{})
        rows.append(dict(requirement,status=claim.get('status','unfinished'),handler=claim.get('handler'),
            detail=claim.get('detail','No runtime implementation has been declared for this mechanic.'),
            implementation=claim.get('id')))
    return dict(schema=1,scope='Declared mechanics and detected source obligations; not exhaustive gameplay certification',
                assessed=bool(rows),entries=rows,unfinished=[r['id'] for r in rows if r['status']=='unfinished'])


def claim(key,handler,detail,*,covers=(),adapted=True):
    return dict(id='mechanic:'+key,handler=handler,detail=detail,
                status='adapted' if adapted else 'implemented',covers=list(covers))
