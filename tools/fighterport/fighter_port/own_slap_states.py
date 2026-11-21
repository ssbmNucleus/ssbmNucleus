"""Allocate reachable Slap move programs and their actual exported animations.

The reader and native generator share this plan. A ground/air variant is a state,
not a reason to substitute a different source move with a similar clip name.
"""
from .own_timing import move_timing, NEVER, interrupt_callback

ENDINGS = {'neutral': -1, 'idle': -1, 'fall': -1, 'specialfall': -2,
           'landlag_special': -3, 'landlag': -4, 'landlag_lc': -4}


def targets(node):
    if not isinstance(node, dict):
        return
    kind = node.get('t')
    if kind == 'SACTM' and not node.get('s'):
        yield node.get('tm')
    elif kind == 'SACT':
        yield from targets(node.get('a'))
        if node.get('e'):
            yield from targets(node.get('ea'))
    elif kind == 'SAOS':
        for action in node.get('ac') or []:
            yield from targets(action)
    elif kind == 'SAIA':
        yield from targets((node.get('tr') or {}).get('a'))
    else:
        for value in node.values():
            if isinstance(value, dict):
                yield from targets(value)


def plan(game, clips=None):
    from .own_template import CLIPS, SPECIALS, FREE_ACTIONS
    clips = dict(CLIPS if clips is None else clips)
    moves, programs = game.get('moves') or {}, game.get('source_programs') or {}
    nodes, extra, limits = {}, {}, []
    free = [motion for motion in FREE_ACTIONS if motion not in clips.values()]
    for sp in SPECIALS:
        for air, clip in enumerate(sp['clips']):
            move = moves.get('game_' + clip) or {}
            name = move.get('slapcity_move')
            if name and name in programs:
                nodes.setdefault((name, air), dict(name=name, air=air, clip=clip,
                    motion=clips[clip], move=move, sp=sp, root=True))
    pending = list(nodes)
    visited = set()
    while pending:
        key = pending.pop(0)
        if key in visited:
            continue
        visited.add(key)
        parent = nodes[key]
        for event in programs[parent['name']].get('tl') or []:
            for target in targets(event.get('a')):
                if target in ENDINGS:
                    continue
                existing = next((n for (name, _), n in nodes.items() if name == target), None)
                if existing:
                    clip, move, motion, sp = (existing[k] for k in ('clip', 'move', 'motion', 'sp'))
                else:
                    choices = [(stem[5:], move) for stem, move in moves.items()
                               if stem.startswith('game_') and move.get('slapcity_move') == target]
                    if target not in programs or not choices:
                        limits.append(f'{parent["name"]}: transition to {target} has no exported program/clip')
                        continue
                    clip, move = choices[0]
                    motion = clips.get(clip) or extra.get(clip)
                    if motion is None:
                        if not free:
                            raise ValueError(f'no free native action for Slap move {target}')
                        motion = free.pop(0)
                        extra[clip] = motion
                    sp = parent['sp']
                for air in (0, 1):
                    if (target, air) not in nodes:
                        nodes[target, air] = dict(name=target, air=air, clip=clip,
                            motion=motion, move=move, sp=sp, root=False)
                        pending.append((target, air))
    return dict(nodes=nodes, clips=extra, limits=list(dict.fromkeys(limits)))


def apply(ctx, source, rows, bindings, flash, landing):
    from .own_template import spec_of
    from .oneshot import flash_keys
    game = dict(ctx['source_game'], moves=ctx['moves'])
    planned = plan(game)
    on, _lost = spec_of(ctx)
    states, carried, new, state_moves = {}, [], [], {}
    for key, node in planned['nodes'].items():
        motion, air, sp = node['motion'], node['air'], node['sp']
        if node['root']:
            candidates = [state for state, name, _ in bindings if name == node['name']
                          and rows[state-ctx['first']]['action'] == ctx['action'].get(motion)
                          and rows[state-ctx['first']]['flags'] == ctx['row'][sp['like'][air]]['flags']]
            if candidates:
                states[key] = candidates[0]
                state_moves[candidates[0]] = node
            continue
        if not ctx['total'].get(motion) or (on and on.get(motion, '')[3:] != node['clip']):
            raise ValueError(f'Slap transition {node["name"]}/{node["clip"]} was not installed on {motion}')
        state = ctx['first'] + len(rows)
        like = ctx['row'][sp['like'][air]]
        rows.append(dict(name=f'{sp["key"]}: {node["name"]} ({"air" if air else "ground"})',
                         action=ctx['action'][motion], flags=like['flags'], move=like['move'],
                         anim='PM_FollowAnim', iasa=f'PM_FollowIASA_{state}'))
        states[key] = state
        state_moves[state] = node
        bindings.append((state, node['name'], sp['helpless']))
        flash.extend((ctx['action'][motion], *k) for k in flash_keys(node['move'].get('flashes') or [], 0))
        new.append((state, node))
        carried.append(dict(source=node['name'], clip=node['clip'], air=bool(air), state=state))
    forms, endings = [], []
    for state, node in new:
        pair = states.get((node['name'], 1-node['air']), state)
        forms.append(f'    case {state}: return {pair};')
        end, interrupt = move_timing(node['move'])
        source += '\n' + interrupt_callback(f'PM_FollowIASA_{state}', interrupt,
                                             None if node['sp']['helpless'] else interrupt)
    if forms:
        source = source.replace('    return state;                       // (a state not listed:',
            '    switch(state) {\n'+'\n'.join(forms)+'\n    }\n'
            '    return state;                       // (a state not listed:')
    for state, node in state_moves.items():
        end, _ = move_timing(node['move'])
        finish = f'frame>={end}' if end != NEVER else 'FrameTimerCheck(gobj)==0'
        endings.append(f'case {state}: if({finish}) '
                       '{ Leave(gobj,' + str(int(node['sp']['helpless'])) + f',{landing!r}f); }} break;')
        rows[state-ctx['first']]['anim'] = 'PM_Anim'
    source += '\nstatic int PM_HasDue(GOBJ *gobj,int frame);\nvoid PM_Anim(GOBJ *gobj)\n{\n'
    source += 'FighterData *fd=gobj->userdata;int frame;\nif(fd->flags.hitlag)return;frame=Tick(gobj);\n'
    source += 'if(PM_HasDue(gobj,frame))return;\nswitch(fd->state_id) {\n'+'\n'.join(endings)+'\n}\n}\n'
    destinations = {name: (state, state) for name, state in ENDINGS.items()}
    for name, air in states:
        # Both forms are required: an airborne cancel must not enter a grounded row.
        if (name, 0) in states and (name, 1) in states:
            destinations[name] = (states[name, 0], states[name, 1])
    return source, destinations, dict(carried=carried, limits=planned['limits'])
