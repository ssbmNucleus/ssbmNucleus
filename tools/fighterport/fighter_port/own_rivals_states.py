"""Common source-window transitions for Rivals specials.

Only explicit, understood predicates are executable. Compiled character checks
remain gaps; they never become unconditional branches. Plans are shared by the
clip allocator and native generator so every reachable clip has a real action.
"""
from copy import deepcopy
from echo_rivals2.branches import branch_stem
from .own_timing import move_timing, NEVER


PREDICATES = {
    'SpecialReleased': '!(fd->input.held & 0x200)',
    'SpecialDown': '(fd->input.held & 0x200)',
    'AttackDown': '(fd->input.held & 0x100)',
    'SpecialPressed': '(fd->input.down & 0x200)',
    'AttackPressed': '(fd->input.down & 0x100)',
    'AttackReleased': '!(fd->input.held & 0x100)',
    'Grounded': '!fd->phys.air_state',
    'Aerial': 'fd->phys.air_state',
}


def predicate(condition, bindings=None, attack=None):
    kind = condition.get('WindowCancelType', '').split('::')[-1]
    custom=(bindings or {}).get((attack,kind))
    if kind not in PREDICATES and custom is None:
        raise ValueError(f'{kind or "missing"} predicate needs a mechanic adapter')
    prerequisite=condition.get('WindowCancelPrerequisite','::None').split('::')[-1]
    guards=dict(PREDICATES,ShieldDown='(fd->input.held & 0x60)')
    if ((prerequisite!='None' or condition.get('NegatePrerequisite')) and custom is None
            or prerequisite not in ('None',*guards)
            or condition.get('CancelIntoAttack', '::None').split('::')[-1] != 'None'
            or condition.get('bPreseveWindowTimer')):
        raise ValueError(f'guarded {kind} branch needs a mechanic adapter')
    result=custom if custom is not None else PREDICATES[kind]
    if prerequisite!='None':
        guard=guards[prerequisite]
        if condition.get('NegatePrerequisite'):guard=f'!({guard})'
        result=f'({result}) && ({guard})'
    return result


def plan(game, clips=None, *, predicates=None, free_actions=None):
    from .own_template import SPECIALS, CLIPS, FREE_ACTIONS
    clips = dict(CLIPS if clips is None else clips)
    moves = game.get('moves') or {}
    nodes, extra, limits = {}, {}, []
    free = [motion for motion in (FREE_ACTIONS if free_actions is None else free_actions) if motion not in clips.values()]

    def add(clip, motion, sp, air):
        move = moves.get('game_' + clip)
        if not move or not move.get('windows'):
            return None
        nodes[clip] = dict(clip=clip, motion=motion, key=sp['key'], air=air,
                           helpless=sp['helpless'], like=sp['like'][air], move=move,
                           branches=[], captures=[], loop=None)
        return nodes[clip]

    for sp in SPECIALS:
        for air, (clip, motion) in enumerate(zip(sp['clips'], sp['actions'])):
            add(clip, motion, sp, air)
    roots = dict(nodes)

    def destination(node, target):
        if not target:
            return ('exit', 0)
        if target.startswith('Special Fall'):
            return ('fall', 0)
        if target.startswith('Special Land'):
            return ('land', 0)
        # Prefer a seek in the current clip; shared tail windows can also live
        # on a previously allocated path without needing another native action.
        choices = [node] + [n for n in nodes.values() if n is not node
                   and n['key'] == node['key'] and n['air'] == node['air']]
        for candidate in choices:
            for first, window, length in candidate['move']['windows']:
                if window == target:
                    return (candidate['clip'], int(first))
        attack = node['move']['rivals2_attack']
        sp = next(s for s in SPECIALS if s['key'] == node['key'])
        selected = None
        # Reserve both forms together. Some readers provide identical air clips;
        # each still needs the correct native state flags and handover partner.
        for air in (0, 1):
            clip = branch_stem(attack + ('Air' if air and not attack.endswith('Air') else ''), target)[3:]
            if 'game_' + clip not in moves:
                clip = branch_stem(attack, target)[3:]
            if clip not in nodes:
                if 'game_' + clip not in moves:
                    continue
                if not free:
                    raise ValueError(f'no free native action for {target}')
                motion = free.pop(0)
                if add(clip, motion, sp, air) is not None:
                    extra[clip] = motion
            if air == node['air'] and clip in nodes:
                selected = nodes[clip]
        if selected is None:
            raise ValueError(f'no exported clip for destination {target}')
        return (selected['clip'], 1)

    pending = list(nodes)
    visited = set()
    while pending:
        clip = pending.pop(0)
        if clip in visited:
            continue
        visited.add(clip)
        node = nodes[clip]
        for event in node['move'].get('window_cancels') or []:
            context = f'{node["move"].get("rivals2_attack")}/{event.get("window")}'
            try:
                capture = event['condition'].get('WindowCancelType','').split('::')[-1] == 'OnGrab'
                if capture:
                    from .own_rivals_grabs import declaration
                    declaration(game, node['move'], event)
                    guard = None
                else:
                    guard = predicate(event['condition'],predicates,node['move'].get('rivals2_attack'))
                first, last = int(event['first']), int(event['last'])
                if first < 1 or last < first:
                    raise ValueError('invalid branch interval')
                target = destination(node, event['condition'].get('PostCancelWindowStringTableKey', ''))
                node['captures' if capture else 'branches'].append(dict(first=first, last=last, guard=guard, target=target,
                    kind=event['condition']['WindowCancelType'].split('::')[-1]))
            except ValueError as error:
                limits.append(f'{context}: {error}')
        target = node['move'].get('path_end')
        if target:
            try:
                dest = destination(node, target)
                node['loop'] = dest
            except ValueError as error:
                limits.append(f'{node["move"].get("rivals2_attack")}: {error}')
        pending.extend(c for c in nodes if c not in visited and c not in pending)
    # A path ending at another exported phase is an ordinary transition, not
    # necessarily a loop. Reject only a cycle with no supported input/state exit.
    for node in nodes.values():
        cursor=node;seen=set()
        while cursor.get('loop') and not cursor['branches']:
            clip=cursor['clip']
            if clip in seen:
                node['loop']=None
                limits.append(f'{node["move"].get("rivals2_attack")}: loop has no supported exit; use finite native recovery')
                break
            seen.add(clip)
            target=cursor['loop'][0]
            if target not in nodes:break
            cursor=nodes[target]
    return dict(nodes=nodes, clips=extra, roots=list(roots), limits=list(dict.fromkeys(limits)))


def apply(ctx, source, rows, bindings, flash, landing):
    from .oneshot import flash_keys
    from .own_template import spec_of
    game = dict(ctx['source_game'], moves=ctx['moves'])
    planned = ctx.get('rivals_plan') or plan(game)
    on, _lost = spec_of(ctx)
    nodes = deepcopy(planned['nodes'])
    by_action = {row['action']: i + ctx['first'] for i, row in enumerate(rows)}
    for clip, node in nodes.items():
        motion = node['motion']
        if clip not in planned['clips']:
            node['state'] = by_action.get(ctx['action'].get(motion))
            continue
        if not ctx['total'].get(motion) or (on and on.get(motion, '')[3:] != clip):
            raise ValueError(f'Rivals branch {clip} was not installed on {motion}')
        state = ctx['first'] + len(rows)
        like = ctx['row'][node['like']]
        rows.append(dict(name=f'{node["key"]}: {node["move"]["windows"][0][1]}',
            action=ctx['action'][motion], flags=like['flags'], move=like['move']))
        node['state'] = state
        bindings.append((state, ctx['action'][motion], node['move'], node['helpless']))
        flash.extend((ctx['action'][motion], *k) for k in flash_keys(node['move'].get('flashes') or [], 0))
    valid = {c:n for c,n in nodes.items() if n.get('state') is not None}

    def jump(node, target):
        clip, frame = target
        if clip == 'exit':
            return f'Leave(gobj,{int(node["helpless"])},{landing!r}f);'
        if clip == 'fall':
            return f'Leave(gobj,1,{landing!r}f);'
        if clip == 'land':
            return f'Fighter_EnterSpecialLanding(gobj,0,{landing!r}f);'
        if clip not in valid:
            raise ValueError(f'Rivals transition destination {clip} is not built')
        return f'RV_Jump(gobj,{valid[clip]["state"]},{frame});'

    cases, endings, inputs, forms, carried = [], [], [], [], []
    for clip, node in valid.items():
        state = node['state']
        cases.append(f'case {state}:')
        for event in node['branches']:
            cases.append(f'if(frame>={event["first"]} && frame<={event["last"]} && ({event["guard"]})) '
                         '{ ' + jump(node, event['target']) + ' return 1; }')
            carried.append(dict(source=clip, first=event['first'], last=event['last'],
                                condition=event['kind'], destination=event['target'][0]))
        cases.append('break;')
        end, interrupt = move_timing(node['move'])
        end = end if end != NEVER else int(node['move']['windows'][-1][0] + node['move']['windows'][-1][2])
        finish = jump(node, node['loop']) if node['loop'] else jump(node, ('exit', 0))
        endings.append(f'case {state}: if(frame>={end}) {{ {finish} }} break;')
        if interrupt != NEVER:
            inputs.append(f'case {state}: if(frame>={interrupt}) {{ '
                          'if(!fd->phys.air_state) Fighter_IASACheck_AllGrounded(gobj);'
                          + ('' if node['helpless'] else ' else Fighter_IASACheck_AllAerial(gobj);') + ' } break;')
        if clip in planned['clips']:
            target = next((n for n in valid.values() if n['key']==node['key'] and n['air']!=node['air']
                           and n['move']['windows'][0][1]==node['move']['windows'][0][1]), node)
            forms.append(f'    case {state}: return {target["state"]};')
    if forms:
        source = source.replace('    return state;                       // (a state not listed:',
            '    switch(state) {\n' + '\n'.join(forms) + '\n    }\n'
            '    return state;                       // (a state not listed:')
    installed = {node['state'] for node in valid.values()}
    for index, row in enumerate(rows, ctx['first']):
        if index in installed:
            row.update(anim='RV_Anim', iasa='RV_IASA')
    source += RUNTIME.replace('@branches@','\n'.join(cases)).replace('@endings@','\n'.join(endings)).replace('@inputs@','\n'.join(inputs))
    return source, dict(carried=carried, limits=planned['limits'],
        adaptations=['Current native input drives source release/press branches; native ledges and landing remain authoritative.'])


RUNTIME = r'''
static void RV_Jump(GOBJ *gobj,int state,int frame)
{
    FighterData *fd=gobj->userdata;
    ActionStateChange(frame-1,1,0,gobj,state,0,0);
    Fighter_AdvanceScript(gobj);
    t_frame[fd->ply]=frame;
}
static int RV_Branch(GOBJ *gobj)
{
    FighterData *fd=gobj->userdata;int frame=t_frame[fd->ply];
    if(fd->flags.hitlag)return 0;
    switch(fd->state_id) {@branches@}
    return 0;
}
void RV_Anim(GOBJ *gobj)
{
    FighterData *fd=gobj->userdata;int frame;
    if(fd->flags.hitlag)return;
    frame=Tick(gobj);
    if(RV_Branch(gobj))return;
    switch(fd->state_id) {@endings@}
}
void RV_IASA(GOBJ *gobj)
{
    FighterData *fd=gobj->userdata;int frame=t_frame[fd->ply];
    if(fd->flags.hitlag || RV_Branch(gobj))return;
    switch(fd->state_id) {@inputs@}
}
'''
