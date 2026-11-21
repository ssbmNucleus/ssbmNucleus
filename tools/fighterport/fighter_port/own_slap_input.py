"""Current-update Slap input predicates mapped to native controller fields.

Source: CTInput.Check / InputValidator.ValidateButton and ValidateCtrlSegment.
Buffered histories and blocked-by event histories require a dedicated adapter.
"""
from .own_slap_expr import Unsupported


STANDARD = {'jump':1, 'spN':4, 'spU':8, 'spD':16, 'spF':32,
            'atkN':64, 'atkU':128, 'atkD':256, 'atkF':512,
            'strU':1024, 'strD':2048, 'strF':4096,
            'shield':8192, 'dodge':16384, 'grab':32768, 'air':65536}


def standard_mask(config):
    """Preserve group AND directional exclusions from StandardInputTrigger.SITcfg."""
    disabled = set((config or {}).get('dc') or [])
    if not disabled:
        return 2, []  # full native IASA, including ordinary movement
    mask = 0
    for name, bit in STANDARD.items():
        group = next((g for g in ('sp','atk','str') if name.startswith(g)), name)
        if name in disabled or group in disabled:
            continue
        if name == 'air' and any('air'+direction in disabled for direction in ('N','U','D','F','B')):
            continue
        mask |= bit
    limits = []
    if 'str' not in disabled and 'strN' not in disabled:
        limits.append('distinct neutral-strong input has no native Melee action')
    if any(group not in disabled and name not in disabled for group,name in (('atk','atkdash'),('str','strdash'))):
        limits.append('source dash-attack input needs an adapter in restricted windows')
    if 'air' not in disabled and any('air'+d in disabled for d in ('N','U','D','F','B')):
        limits.append('direction-restricted aerial attack input needs an adapter')
    return mask, limits


def bindings():
    """FSInput scalar reads; source buttons return 0/1 for released/held."""
    result = {('FSI', name): f'((fd->input.held & {mask}) != 0)'
              for name, mask in dict(attack=0x100, special=0x200, jump=0xC00, grab=0x10, taunt=0x8).items()}
    result.update({('FSI', 'ctrlX'): '(fd->input.lstick.X*r->facing)',
                   ('FSI', 'ctrlXRaw'): 'fd->input.lstick.X',
                   ('FSI', 'ctrlY'): 'fd->input.lstick.Y',
                   ('FSI', 'ctrlMag'): 'sqrtf(fd->input.lstick.X*fd->input.lstick.X + fd->input.lstick.Y*fd->input.lstick.Y)',
                   ('FSI', 'atkctrlX'): '(fd->input.cstick.X*r->facing)',
                   ('FSI', 'atkctrlXRaw'): 'fd->input.cstick.X',
                   ('FSI', 'atkctrlY'): 'fd->input.cstick.Y',
                   ('FSI', 'atkctrlMag'): 'sqrtf(fd->input.cstick.X*fd->input.cstick.X + fd->input.cstick.Y*fd->input.cstick.Y)',
                   ('FSI', 'shield'): 'fd->input.trigger'})
    return result


def condition(node):
    if node.get('f',1)!=1 or node.get('b','None')!='None':
        raise Unsupported('buffered/blocked source input history')
    return validator(node.get('i') or {})


def validator(node):
    kind=node.get('t');compare=node.get('c')
    if kind=='MultiValid':
        terms=[validator(v) for v in node.get('l') or []]
        count=' + '.join(f'!!({v})' for v in terms) or '0'
        if compare=='Any':return f'(({count}) > 0)'
        if compare=='All':return f'(({count}) == {len(terms)})'
        if compare=='One':return f'(({count}) == 1)'
        if compare=='None':return f'(({count}) == 0)'
    mask={'Attack':0x100,'Special':0x200,'Jump':0xC00,'Grab':0x10,'Taunt':0x8}.get(kind)
    if mask is not None:
        held=f'(fd->input.held & {mask})'
        down=f'(fd->input.down & {mask})'
        previous=f'(fd->input.held_prev & {mask})'
        values={'Down':f'({down} != 0)','Held':f'({held} && !{down})',
                'DownOrHeld':f'({held} != 0)','Up':f'({previous} && !{held})',
                'Not':f'(!{held} && !{previous})','NotOrUp':f'(!{held})'}
        if compare in values:return values[compare]
    if kind=='CtrlSegment':
        segment=int(node.get('s',0))
        # Native deadzone/tilt threshold adapt the cardinal regions; diagonal
        # compass sectors remain explicit gaps until their source thresholds are read.
        if segment & ~0x201ff:raise Unsupported('source compass input sectors')
        mask={'Outside':1,'Inside':2,'Entered':4,'Exited':8}.get(compare)
        if mask is None:
            try:mask=int(compare)
            except (TypeError,ValueError):raise Unsupported(f'input segment comparison {compare}')
        if not 0<mask<16:raise Unsupported(f'input segment comparison {compare}')
        facing='1.0f' if node.get('r') else 'r->facing'
        return f'PM_InputSegment(fd,{segment},{mask},{facing})'
    raise Unsupported(f'source input {kind}/{compare}')


HELPERS=r'''
static int PM_InsideSegment(float x,float y,int mask)
{
    float ax=PMAbs(x),ay=PMAbs(y);int region;
    if((mask&1)&&ax<0.01f&&ay<0.01f)return 1;
    if((mask&0x20000)&&ax<0.1f&&ay<0.1f)return 1;
    if(ay>ax)region=y>0 ? (ay>=0.5f?4:2) : (ay>=0.5f?16:8);
    else if(ax>0)region=x>0 ? (ax>=0.5f?64:32) : (ax>=0.5f?256:128);
    else return 0;
    return (mask&region)!=0;
}
static int PM_InputSegment(FighterData *fd,int segment,int comparison,float facing)
{
    int now=PM_InsideSegment(fd->input.lstick.X*facing,fd->input.lstick.Y,segment);
    int prev=PM_InsideSegment(fd->input.lstick_prev.X*facing,fd->input.lstick_prev.Y,segment);
    int status=now ? 2 : 1;
    if(now&&!prev)status|=4;
    if(!now&&prev)status|=8;
    return (status&comparison)!=0;
}
'''
