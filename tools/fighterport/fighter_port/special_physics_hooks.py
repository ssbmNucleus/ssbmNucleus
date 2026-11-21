"""Compose clone-local post-physics hooks onto explicit special states.

This edits the generated private fighter table only. Selectors are runtime
Fighter state IDs, never fighter-DAT action ordinals.
"""
import hashlib,re

_ROW=re.compile(r'(\{ /\* state (\d+) .*?\n    \},)',re.S)
_SLOT=re.compile(r'(/\*\.physics_callback\s*=\*/)([^\n]+),')

def compose(sources,selection,*,namespace,post_hook='Moves_PostPhysics'):
    """Wrap selected private physics callbacks, then call ``post_hook``."""
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',namespace):raise ValueError('Unique C hook namespace required')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',post_hook):raise ValueError('C post-hook function required')
    if not isinstance(selection,dict) or set(selection)!={'domain','runtime_states'}:
        raise ValueError('Explicit runtime-state selection required')
    if selection['domain']!='fighter_state_id':raise ValueError('Special hooks select runtime fighter state IDs, not action ordinals')
    states=selection['runtime_states']
    if not isinstance(states,list) or not states or len(states)!=len(set(states)) or any(type(v) is not int or v<341 for v in states):
        raise ValueError('Unique special runtime state IDs required')
    marker=f'{namespace}SpecialPhysics_'
    if marker in sources.get('fighter.c','') or marker in sources.get('moves.c',''):
        raise ValueError('Special physics hook namespace already installed')
    wanted=set(states);rows=[];wrappers=[]
    before=hashlib.sha256(sources['fighter.c'].encode()).hexdigest()
    def replace(match):
        state=int(match[2]);block=match[1]
        if state not in wanted:return block
        slot=_SLOT.search(block)
        if not slot:raise ValueError(f'Missing special physics slot for state {state}')
        original=slot[2].strip();name=f'{namespace}SpecialPhysics_{state}'
        call='' if original=='0' else f'((void (*)(GOBJ *))({original}))(gobj);'
        wrapper=f'static void {name}(GOBJ *gobj) {{ {call} {post_hook}(gobj,gobj->userdata); }}'
        wrappers.append(wrapper);rows.append(dict(runtime_state=state,before=original,after=name,wrapper=wrapper))
        return block[:slot.start(2)]+' '+name+block[slot.end(2):]
    changed=_ROW.sub(replace,sources['fighter.c'])
    found={row['runtime_state'] for row in rows}
    if found!=wanted:raise ValueError(f'Selected special states missing from private table: {sorted(wanted-found)}')
    sources['fighter.c']=changed;sources['moves.c']+='\n'+'\n'.join(wrappers)+'\n'
    return dict(schema='special-physics-post-hook-v1',domain='fighter_state_id',namespace=namespace,
                post_hook=post_hook,selected=list(states),rows=rows,fighter_before_sha256=before,
                fighter_after_sha256=hashlib.sha256(changed.encode()).hexdigest())

def install(sources,*,states,namespace,hook='Moves_PostPhysics'):
    """Build-facing convenience API with an unambiguous ``states`` name."""
    return compose(sources,dict(domain='fighter_state_id',runtime_states=states),
                   namespace=namespace,post_hook=hook)
