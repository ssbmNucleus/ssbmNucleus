"""Compile frame-based combat profiles to native Melee subaction scripts.

Frame values are live animation frames, matching the captured motion. Geometry is in
bone-local game units, converted to the engine's 1/256 fixed-point encoding.
All scripts are appended; animation metadata and existing data remain intact.
"""
from __future__ import annotations
import math
from vault.echo.commands import BY_KEY
from vault.echo.subactions import FighterDat


def command(key, **fields):
    return BY_KEY[key].code, fields, None


def fixed(value):
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('geometry must be finite')
    return round(value * 256)


def compile_move(profile):
    """Validate one profile and return a relocatable script item list."""
    total = profile['total']
    if type(total) is not int or total < 2:
        raise ValueError('total frames must be an integer >= 2')
    events = []
    def at(frame, priority, item):
        if type(frame) is not int or not 1 <= frame <= total + 1:
            raise ValueError('event frame outside move')
        events.append((frame, priority, item))
    phases = profile['phases']
    previous_end, out_before = 0, set()
    for k, phase in enumerate(phases):
        start, end = phase['start'], phase['end']
        if not previous_end < start <= end <= total:
            raise ValueError('hit phases must be ordered and disjoint')
        hits = phase['hitboxes']
        if not 1 <= len(hits) <= 4:
            raise ValueError('Melee supports one to four active hitboxes')
        ids = [hit.get('slot', i) for i, hit in enumerate(hits)]
        if len(set(ids)) != len(ids) or any(type(i) is not int or not 0 <= i <= 3 for i in ids):
            raise ValueError('hitbox slots must be four different numbers from 0 to 3')
        if phase.get('continues'):
            # The same attack going on (a weaker late hit, a hitbox that moves): the game strikes a target
            # once for all of it. Melee does the same for a hitbox made again while it is out, and a new one
            # takes over what the others of its group have struck; a clear would let it strike again. Only
            # the hitboxes that are no longer out are taken away.
            if start != previous_end + 1 or not out_before:
                raise ValueError('a phase that continues must follow the one before it at once')
            for gone in sorted(out_before - set(ids)):
                at(start, 0, command('remove_hitbox', index=gone))
        else:
            at(start, 0, command('clear_hitboxes'))
        previous_end, out_before = end, set(ids)
        for i, hit in zip(ids, hits):
            if type(hit['damage']) is not int or hit['damage'] < 0:
                raise ValueError('script damage must be an explicit nonnegative integer')
            if len(hit['position']) != 3 or hit['radius'] <= 0:
                raise ValueError('hitbox requires XYZ position and positive radius')
            x,y,z = map(fixed, hit['position'])
            # (the hit group: hitboxes of one group strike a target once between them; one made again in
            # another group, even while it is out, may strike a target the first group has struck)
            fields = dict(id=i, hit_group=hit.get('group', 0), bone=hit['bone'], damage=hit['damage'],
                          # Editor fields name the packed words backwards:
                          # ftAction_8007121C loads z_offset into local X and
                          # x_offset into local Z. Profiles use actual XYZ.
                          size=fixed(hit['radius']), x_offset=z,y_offset=y,z_offset=x,
                          angle=hit['angle'],knockback_growth=hit['kbg'],
                          base_knockback=hit['bkb'],element=hit.get('element',3),
                          weight_set_knockback=hit.get('fixed_kb',0),
                          # met by another attack on the ground, the two cancel and the fighter is pushed
                          # back, unless the game says this hit is not one that can be met
                          clank=int(hit.get('clank', True)),rebound=int(hit.get('clank', True)),
                          # the sound of the hit: how hard (0 to 2) and what with (1 a punch, 2 a kick, 3 a blade)
                          hit_sfx_severity=hit.get('sound_level', 2),hit_sfx_kind=hit.get('sound_kind', 3),
                          shield_damage=hit.get('shield_damage', 0),     # what it takes off a shield beyond its damage
                          hit_grounded_fighters=int(hit.get('grounded',True)),
                          hit_aerial_fighters=int(hit.get('aerial',True)))
            if any(type(hit[k]) is not bool for k in ('grounded','aerial','clank') if k in hit):
                raise ValueError('hitbox situation masks must be booleans')
            if (type(fields['hit_sfx_severity']) is not int or not 0 <= fields['hit_sfx_severity'] <= 2
                    or type(fields['hit_sfx_kind']) is not int or not 0 <= fields['hit_sfx_kind'] <= 13
                    or type(fields['shield_damage']) is not int or not -128 <= fields['shield_damage'] <= 127):
                raise ValueError('hit sound is a level 0 to 2 and a kind 0 to 13; shield damage -128 to 127')
            if not fields['hit_grounded_fighters'] and not fields['hit_aerial_fighters']:
                raise ValueError('hitbox must target ground or air')
            if hit.get('grabbed_only'):
                fields.update(only_hit_grabbed_fighter=1,clank=0)
            if hit.get('ignore_thrown'):
                fields.update(ignore_thrown_fighters=1)   # strikes anyone but the fighter being thrown
            at(start, 2, command('create_hitbox', **fields))
        # Sound is authored independently. A forced generic swing here replaces
        # the fighter's native effect on the same playback channel.
        if 'sound' in phase:
            at(start, 1, command('sound_effect',behavior=1,**phase['sound']))
        after = phases[k + 1] if k + 1 < len(phases) else None
        if not (after and after.get('continues')):
            at(end+1, 0, command('clear_hitboxes'))
    if 'intangible' in profile:
        # frames on which nothing can touch the fighter (a ledge attack, an attack from the floor, the start of
        # a move): the script the donor had for this action said so for the donor's frames and is replaced here
        start, end = profile['intangible']
        if type(start) is not int or type(end) is not int or not 1 <= start <= end <= total:
            raise ValueError('intangible frames must be ordered and inside the move')
        at(start, 0, command('set_body_collision_state', body_state=2))
        at(end + 1, 0, command('set_body_collision_state', body_state=0))
    if 'charge' in profile:
        at(profile['charge'], 1, command('start_smash_charge',charge_frames=60,
                                       charge_rate=350,color_animation=119))
    if 'landing_window' in profile:
        start,end = profile['landing_window']
        if start >= end:
            raise ValueError('landing window must be ordered')
        at(start,1,command('set_flag',flag=0,value=1))
        at(end,1,command('set_flag',flag=0,value=0))
    for start, end in profile.get('jab_followup_windows', []):
        if type(start) is not int or type(end) is not int or not 1 <= start < end:
            raise ValueError('jab followup windows must be ordered')
        # own_jab evaluates explicit listener windows in IASA. Opcode 0x5C cannot close a gate.
    if 'jab_followup' in profile and 'jab_followup_windows' not in profile:
        # the game's command reads "off unless an item is held" when its field is 1: 0 is what lets the next jab out
        at(profile['jab_followup'],1,command('enable_jab_followup',toggle=0))
    if 'throw' in profile:
        throw = profile['throw']
        if type(throw['damage']) is not int or throw['damage'] < 0:
            raise ValueError('throw damage must be an explicit nonnegative integer')
        at(1,1,command('throw',throw_type=0,damage=throw['damage'],
            angle=throw['angle'],knockback_growth=throw['kbg'],
            base_knockback=throw['bkb'],hit_sfx_severity=2,hit_sfx_kind=2))
        at(1,1,command('throw',throw_type=1,damage=3,angle=361,
            knockback_growth=100,base_knockback=40,hit_sfx_kind=2))
        # The historical editor label for opcode 0x50 is Reverse Direction.
        # Argument 0 sets the release flag consumed by ftCo_800DD724; argument
        # 1 flips facing. Keep the verified donor encoding for release.
        at(throw['release'],2,command('reverse_direction',enabled=0))
        # A throw whose script turns the fighter round (a back throw, before it lets go): the same command
        # with argument 1, which the throw's own code reads before the release on the same frame. The
        # throw's angle is then about the new facing, as the game's number is.
        for frame in profile.get('turns', []):
            at(frame,1,command('reverse_direction',enabled=1))
    at(total,3,command('allow_interrupt'))
    items=[];last=None
    for frame,_,item in sorted(events,key=lambda e:(e[0],e[1])):
        if frame != last:
            items.append(command('asynchronous_timer',frame=frame));last=frame
        items.append(item)
    # Run the actual bit-packer as validation before any fighter is changed.
    FighterDat.encode_script(items)
    return items


def nth_actions(actions, which):
    """Of actions that share a motion, the one at place `which` (0 the first) for each motion."""
    count, keep = {}, []
    for a in sorted(actions, key=lambda x: x.index):
        k = count.get(a.motion, 0)
        count[a.motion] = k + 1
        if k == which:
            keep.append(a)
    return keep


def install_profiles(data, spec):
    if spec.get('schema') != 1:
        raise ValueError('combat profiles require schema 1')
    fighter=FighterDat(data); prepared=[];seen=set()
    for profile in spec['moves']:
        actions=[a for a in fighter.actions if a.motion in profile['motions']]
        missing=set(profile['motions'])-{a.motion for a in actions}
        if missing:
            raise ValueError(f'missing action motions: {sorted(missing)}')
        if profile.get('occurrence') is not None:
            # one of several actions that share a motion (a donor's ordinary and full release): the first, or the second
            actions=nth_actions(actions,profile['occurrence'])
            if not actions:
                raise ValueError(f"the donor has no action number {profile['occurrence']+1} for {sorted(profile['motions'])}")
        items=compile_move(profile)
        for action in actions:
            if action.index in seen:
                raise ValueError('duplicate combat target')
            seen.add(action.index);prepared.append((profile['id'],action.index,items))
    report=[]
    for name,index,items in prepared:
        report.append(dict(id=name,**fighter.replace_script(index,items)))
    return fighter.to_bytes(),report
