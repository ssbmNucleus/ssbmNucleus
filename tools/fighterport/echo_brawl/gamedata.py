"""A Brawl fighter read into the shape the port driver takes a fighter in (the one `echo_ultimate.gamedata.moves.load`
gives for Ultimate): per action its hitboxes with first and last frames, grab boxes, throws, the frame the fighter
may act on, the frames nothing can touch it on, and the fighter's numbers under Melee's own names.

Brawl keeps all of it in the fighter's own moveset file, an action a script. Frames here count as players count
them (a move's first frame is 1).
"""
from __future__ import annotations

from pathlib import Path

from . import arc
from .moveset import Moveset, hitbox, timeline

# Brawl's fighter numbers, by their place in its table, under Melee's names for the same thing (the two tables are
# one lineage: Marth's rows agree in meaning all the way down, checked value against value).
ATTRIBUTES = {0: 'initial_walk_speed', 1: 'walk_acceleration', 2: 'max_walk_speed', 3: 'friction', 4: 'initial_dash_speed',
              5: 'stop_turn_initial_speed_a', 6: 'stop_turn_initial_speed_b', 7: 'initial_run_speed', 12: 'jump_startup_lag',
              13: 'initial_horizontal_jump_velocity', 14: 'initial_vertical_jump_velocity',
              15: 'ground_to_air_jump_momentum_multiplier', 16: 'max_shorthop_horizontal_velocity',
              17: 'max_shorthop_vertical_velocity', 18: 'vertical_air_jump_multiplier', 19: 'horizontal_air_jump_multiplier',
              25: 'gravity', 26: 'terminal_velocity', 29: 'aerial_speed', 30: 'aerial_friction',
              31: 'max_aerial_horizontal_speed', 32: 'air_friction', 33: 'fast_fall_terminal_velocity', 44: 'weight',
              80: 'nair_landing_lag', 81: 'fair_landing_lag', 82: 'bair_landing_lag', 83: 'uair_landing_lag', 84: 'dair_landing_lag'}
WHOLE = {12}                        # kept as whole numbers in Brawl's table

# what a hitbox does to what it hits, in the words the driver knows
ELEMENT = {'normal': 'collision_attr_normal', 'slash': 'collision_attr_cutup', 'electric': 'collision_attr_elec',
           'flame': 'collision_attr_fire', 'freezing': 'collision_attr_ice', 'darkness': 'collision_attr_purple',
           'aura': 'collision_attr_aura'}
# the script variables that mean something to a port (Brawl sets and clears them by number)
JAB_NEXT = 0x22000010               # the next jab may be asked for
LANDING_LAG = 0x2200001E            # landing now plays the aerial's landing (outside it the landing is the plain one)
COUNTERING = 0x22000011             # a hit taken now is countered
# clips Brawl plays one after another where Melee (and Ultimate) have one action: a smash attack's wind-up and its
# swing; an up special's start and its rise. {the clip the action is named for: [the clips before it]}
JOINS = {'AttackS4S': ['AttackS4Start'], 'AttackHi4': ['AttackHi4Start'], 'AttackLw4': ['AttackLw4Start'],
         'SpecialHi2': ['SpecialHi1'], 'SpecialAirHi2': ['SpecialAirHi1']}
JOINED = {b for befores in JOINS.values() for b in befores}
CHARGED = ('AttackS4', 'AttackHi4', 'AttackLw4')        # held at the join for as long as the button is

SECOND = '__2'                                          # what a second script under one name is kept as

# Who a hitbox can strike: two bits of its flag word, one for fighters on the ground and one for fighters in the
# air (both set on an ordinary hit). Read off Ike's Aether: the plunge has a hit at 80 degrees with only the first
# bit and its spike, straight down, with only the second: a standing fighter is popped up, one in the air is driven
# down with him into the slam.
TARGETS = {1: 'ground', 2: 'air'}

# Effects: a graphics event names one by a number: the low half is its place in an effect file's own list of names,
# the high half which file (none: the one every fighter shares). The shared ones go by the words the driver knows
# them by (PtcCommonSmashFlashS is sys_smash_flash_s); a few are spelt out differently there.
EFFECT_EVENTS = ('graphic', 'graphic_b', 'graphic_c', 'graphic_d')
EFFECT_WORDS = {'sys_attack_smoke': 'sys_atk_smoke', 'sys_vertical_smoke_a': 'sys_v_smoke_a', 'sys_vertical_smoke_b': 'sys_v_smoke_b',
                'sys_landing_smoke_s': 'sys_landing_smoke', 'sys_horizontal_smoke_a': 'sys_h_smoke_a',
                'sys_horizontal_smoke_b': 'sys_h_smoke_b'}


def effect_list(pac: bytes):
    """The names in an effect file's list, by number (None where the list has a gap)."""
    import struct
    listing = next((f['data'] for f in arc.read(pac)[1] if f['data'][:4] == b'EFLS'), None)
    if listing is None:
        return []
    out = []
    for i in range(struct.unpack_from('>H', listing, 4)[0]):
        at = struct.unpack_from('>I', listing, 0x10 + 16 * i + 4)[0]
        out.append(listing[at:listing.index(b'\0', at)].decode('ascii', 'replace') if 0 < at < len(listing) else None)
    return out


def own_effects(root, fighter):
    """{('own', number): the driver's word} for the fighter's own effects (ike_hunka for PtcIkeHunka), from the list
    in its effect file ({} when that file is not there)."""
    import re
    path = next(iter(sorted(Path(root).rglob(f'ef_{fighter}.pac'))), None)
    out = {}
    for number, name in enumerate(effect_list(path.read_bytes()) if path else []):
        if name and name.startswith('Ptc'):
            out[('own', number)] = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', name[len('Ptc'):]).lower()
    return out


def common_effects(root):
    """{number: the driver's word} for the effects every fighter shares ({} when the disc's effect file is not there)."""
    import re
    path = next(iter(sorted(Path(root).rglob('ef_common.pac'))), None)
    out = {}
    for number, name in enumerate(effect_list(path.read_bytes()) if path else []):
        if name and name.startswith('PtcCommon'):
            word = 'sys_' + re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', name[len('PtcCommon'):]).lower()
            out[number] = EFFECT_WORDS.get(word, word)
    return out


# Faces: a clip's visibility animation shows one face at a time, each under a bone of its own. What the eyes are
# doing under each, by the bone's name (the first that fits): half shut, shut (a blink, or eyes screwed up in pain),
# else open.
FACES = (('blinkhalf', 'half'), ('blink', 'closed'), ('ouch', 'closed'))


def faces(shown, shift=0.0):
    """[(frame, 'open' | 'half' | 'closed')] at the first frame and at every change, from a clip's visibility
    animation ({bone: [shown on each frame]}); [] when it shows no face but the resting one throughout."""
    tracks = [(next(state for word, state in FACES if word in name.lower()), flags) for name, flags in shown.items()
              if any(word in name.lower() for word, _ in FACES)]
    if not tracks or not any(any(flags) for _state, flags in tracks):
        return []
    out = []
    for f in range(max(len(flags) for _state, flags in tracks)):
        on = [state for state, flags in tracks if f < len(flags) and flags[f]]
        state = 'closed' if 'closed' in on else 'half' if 'half' in on else 'open'
        if not out or out[-1][1] != state:
            out.append((int(round(f + 1 + shift)), state))
    return out


# sounds: the events that play one by its number in the sound archive; the game's own word for a sound where the
# driver's sound tables use another; the least a sample must be to count (the archive has empty places)
SOUND_EVENTS = ('sound', 'sound_b', 'sound_c', 'sound_victory', 'sound_other')
SOUND_WORDS = {'damage_hoshikie': 'knockout'}
SOUND_LEAST = 0.05                                      # seconds


def sound_archive(root):
    """The disc's sound archive, or None."""
    return next(iter(sorted(Path(root).rglob('*.brsar'))), None)


def sound_word(name, fighter):
    """A sound's name in the words the driver's sound tables use (snd_vc_Ike_Attack01 -> vc_ike_attack01; the
    crowd's chant and the announcer's call go by their own)."""
    n = name.lower()
    n = n[4:] if n.startswith('snd_') else n
    if n == f'vc_ouen_{fighter}':
        return f'vc_{fighter}_cheer'
    if n == f'se_narration_characall_{fighter}':
        return f'vc_narration_characall_{fighter}'
    for theirs, ours in SOUND_WORDS.items():
        n = n.replace(theirs, ours)
    return n


def sound_names(root):
    """{number: name} of every sound in the disc's archive ({} with no archive)."""
    from . import brsar
    path = sound_archive(root)
    return {s['id']: s['name'] for s in brsar.sounds(path)} if path else {}


def sound_bank(root, fighter):
    """The fighter's own samples by kind, named in the driver's words -> {'se': {name: (name, sound)}, 'vc': ...,
    'cheer': ..., 'call': ...}; a sound is {'pcm', 'rate', ...} (`brsar.fighter_sounds`). Empty places are left out."""
    from . import brsar
    out = {'se': {}, 'vc': {}, 'cheer': {}, 'call': {}}
    path = sound_archive(root)
    if not path:
        return out
    for name, sound in brsar.fighter_sounds(path, fighter).items():
        if len(sound['pcm']) < SOUND_LEAST * sound['rate'] or not abs(sound['pcm']).max():
            continue
        word = sound_word(name, fighter)
        kind = ('cheer' if word.endswith('_cheer') else 'call' if 'narration' in word else
                'vc' if word.startswith(f'vc_{fighter}_') else 'se' if word.startswith(f'se_{fighter}_') else None)
        if kind:
            out[kind][word] = (word, sound)
    return out


def sfx(m, index, names, fighter, shift=0.0):
    """What an action's sound script plays, in the words the driver reads sounds in. A voice the game picks itself
    (an attack's grunt) is named as the fighter's attack voice with no number."""
    out = []
    for played, _frame, e in real_frames(m.script('sfx', index))[0]:
        f, a = int(round(played + shift)), e['args']
        if e['event'] in SOUND_EVENTS and a and isinstance(a[0], int) and a[0] in names:
            out.append({'cmd': 'PLAY_SE', 'real': f, 'name': sound_word(names[a[0]], fighter), 'args': [a[0]]})
        elif e['event'] == 'low_voice':
            out.append({'cmd': 'PLAY_SE', 'real': f, 'name': f'vc_{fighter}_attack', 'args': []})
    return out


def find(root, fighter):
    """The fighter's folder on the extracted disc and its files' common name (fighter/ike, FitIke)."""
    file = next(p for p in Path(root).rglob('Fit*.pac')
                if p.parent.name == fighter and p.parent.parent.name == 'fighter' and p.stem.lower() == 'fit' + fighter.lower())
    return file.parent, file.stem


def read_moveset(root, fighter):
    folder, stem = find(root, fighter)
    return Moveset(arc.read((folder / f'{stem}.pac').read_bytes())[1][0]['data'])


def real_frames(events):
    """[(frame as played, event)]: a script's frames are its animation's, and a change of the animation's speed
    stretches the wait that follows it. -> (rows, [(script frame, frame as played)] at each change)"""
    rows = timeline(events)
    out, marks, rate, anchor = [], [(1.0, 1.0)], 1.0, (1.0, 1.0)
    for frame, e in rows:
        played = anchor[1] + (frame - anchor[0]) / rate
        if e['event'] == 'frame_speed' and e['args'] and isinstance(e['args'][0], (int, float)) and e['args'][0] > 0:
            anchor, rate = (frame, played), float(e['args'][0])
            marks.append(anchor)
        out.append((played, frame, e))
    return out, marks


def action(m, index, bones, shift=0.0, names=None, fighter=None, effects=None):
    """One action's script read into the driver's entry. `shift`: frames played before it (a wind-up joined on)."""
    rows, marks = real_frames(m.script('main', index))
    hits, live, other, flags, turns = [], {}, [], [], []
    armour, momentum, counter, ledge = [], [], [], None
    cancel = None
    body = []                                           # (frame, state)
    run = 0
    grab_end = None
    whole = lambda f: int(round(f + shift))
    for played, _frame, e in rows:
        f, kind, args = whole(played), e['event'], e['args']
        if kind in ('hitbox', 'special_hitbox') and len(args) >= 13 and all(isinstance(a, (int, float)) for a in args[:13]):
            h = hitbox(args, kind == 'special_hitbox')
            if not live:
                run += 1                                # a new attack: nothing was out
            old = live.pop(h['id'], None)
            if old is not None:
                old['last'] = f - 1
            bone = bones[h['bone']] if 0 <= h['bone'] < len(bones) else None
            row = {'id': h['id'], 'bone': 'top' if h['bone'] == 0 else (bone or f'bone{h["bone"]}').lower(), 'damage': float(h['damage']),
                   'angle': h['angle'], 'kbg': h['kbg'], 'bkb': h['bkb'], 'fkb': h['fkb'], 'size': h['size'],
                   'x': h['x'], 'y': h['y'], 'z': h['z'], 'first': f, 'last': None, 'run': run,
                   'effect': ELEMENT.get(h['effect'], 'collision_attr_normal'), 'shield_damage': h['shield_damage'],
                   'hitlag': h['hitlag'], 'targets': TARGETS.get(h['flags'] >> 16 & 3), 'flags': h['flags']}
            live[h['id']] = row
            hits.append(row)
        elif kind == 'clear_hitboxes':
            for row in live.values():
                row['last'] = f - 1
            live = {}
        elif kind == 'delete_hitbox' and args and isinstance(args[0], int):
            row = live.pop(args[0], None)
            if row is not None:
                row['last'] = f - 1
        elif kind == 'grab_box' and len(args) >= 8:
            # (number, bone, size, x, y, z, what the caught fighter does, whom: 1 standing, 2 in the air, 3 both)
            whom = {1: '<const 0xe7c4>', 2: '<const 0xe7c8>'}.get(args[7])
            other.append({'cmd': 'CATCH', 'real': f, 'args': [args[0], 'top' if args[1] == 0 else bones[args[1]].lower(), args[2],
                                                               args[3], args[4], args[5], args[3], args[4], args[5], args[6], whom]})
        elif kind == 'clear_grab_boxes':
            grab_end = grab_end or f
        elif kind == 'throw' and len(args) >= 7 and args[0] == 0:
            # (which, bone, damage, angle, growth, set knockback, base, ...): the throw itself; number 1 is the hit a
            # fighter that breaks free takes
            other.append({'cmd': 'ATTACK_ABS', 'real': f, 'args': list(args[:7])})
        elif kind == 'throw_release':
            other.append({'cmd': 'ATK_HIT_ABS', 'real': f, 'args': []})
        elif kind == 'allow_interrupt':
            cancel = cancel or f
        elif kind == 'body_collision' and args and isinstance(args[0], int):
            body.append((f, args[0]))
        elif kind == 'reverse_direction':
            turns.append(f)
        elif kind in ('bit_set', 'bit_clear') and args and isinstance(args[0], tuple):
            which = args[0][1] & 0xFFFFFFFF
            if which in (JAB_NEXT, LANDING_LAG):
                flags.append({'cmd': 'on_flag' if kind == 'bit_set' else 'off_flag', 'real': f, 'which': which})
            elif which == COUNTERING:
                counter.append(f)
        elif kind == 'armour' and args and isinstance(args[0], int):
            # (what kind: 0 none, 1 against any hit, 2 up to a strength; then that strength)
            armour.append((f, args[0], float(args[1]) if len(args) > 1 and isinstance(args[1], (int, float)) else 0.0))
        elif kind == 'set_momentum' and len(args) >= 2 and all(isinstance(a, (int, float)) for a in args[:2]):
            momentum.append([f, float(args[0]), float(args[1])])
        elif kind == 'ledge_grab':
            ledge = ledge or f
    untouched, invincible = None, False
    on = next((f for f, state in body if state in (1, 2)), None)
    if on is not None:
        off = next((f for f, state in body if state == 0 and f > on), None)
        untouched = [on, off] if off else None
        invincible = next(state for f, state in body if f == on) == 1      # struck but unharmed, not passed through
    # stretches on which a hit does not stagger the fighter: [first frame, the frame it ends on]
    spans, since = [], None
    for f, state, _strength in armour:
        if state and since is None:
            since = f
        elif not state and since is not None:
            spans.append([since, f])
            since = None
    # the frames the clip is played on against the clip's own frames, wherever its speed changes
    keys = [[whole(p) - 1, round(a - 1.0, 5)] for a, p in marks]
    return {'hitboxes': hits, 'other': other, 'motion_rates': [], 'flags': flags, 'turns': turns, 'articles': [], 'article_frames': [],
            'cancel_frame_script': cancel, 'cancel_frame_real': cancel, 'intangible': untouched, 'catch_end': grab_end,
            'invincible': invincible, 'armour': spans, 'momentum': momentum, 'ledge_grab': ledge,
            'counter': [counter[0], counter[-1]] if len(counter) >= 2 else None,
            'effects': trail(m, index, bones, shift, effects),
            'flashes': flashes(m, index, shift),
            'sounds': sfx(m, index, names, fighter, shift) if names else [], '_keys': keys}


def flashes(m, index, shift=0.0):
    """The colour an action lays over the fighter's body, from its graphics script: [[frame, [red, green, blue,
    alpha], frames it takes to get there]] (0: at once; alpha 0: none). A script sets a colour, has it change into
    another over some frames, and takes it off. (A light thrown on the fighter from one side is another event and is
    not read.)"""
    out = []
    for played, _frame, e in real_frames(m.script('gfx', index))[0]:
        f, a = int(round(played + shift)), e['args']
        if e['event'] == 'flash_overlay' and len(a) >= 4 and all(isinstance(v, int) for v in a[:4]):
            out.append([f, [int(v) for v in a[:4]], 0])
        elif e['event'] == 'change_flash' and len(a) >= 5 and all(isinstance(v, int) for v in a[:5]):
            out.append([f, [int(v) for v in a[1:5]], int(a[0])])
        elif e['event'] == 'flash_overlay_off':
            out.append([f, [0, 0, 0, 0], 0])
    return out


def trail(m, index, bones, shift=0.0, effects=None):
    """The frames a sword's trail is drawn on and where along the blade it runs, from the action's graphics script,
    in the words the driver reads a trail in (bone, the blade's two ends in the bone's own axes); and the shared
    effects it draws (`effects`: {number: word}), each with the bone it is on and its place (x, y, z)."""
    out = []
    for played, _frame, e in real_frames(m.script('gfx', index))[0]:
        f, a = int(round(played + shift)), e['args']
        # an effect's number is its place in a file's list, and above that which file: none for the shared ones, the
        # fighter's own otherwise
        word = None
        if e['event'] in EFFECT_EVENTS and effects and a and isinstance(a[0], int):
            word = effects.get(a[0]) if a[0] < 0x10000 else effects.get(('own', a[0] & 0xFFFF))
        if word and len(a) >= 5 and isinstance(a[1], int) and all(isinstance(v, (int, float)) for v in a[2:5]):
            # (number, bone, then its place: forward, up, across)
            bone = 'top' if a[1] == 0 else (bones[a[1]].lower() if 0 <= a[1] < len(bones) else 'top')
            out.append({'cmd': 'EFFECT', 'real': f, 'name': None, 'args': [word, bone, float(a[4]), float(a[3]), float(a[2])]})
            continue
        if e['event'] == 'sword_glow' and len(a) >= 10 and all(isinstance(v, (int, float)) for v in a[2:10]):
            # (colour, fade, bone, x y z, bone, x y z, ...)
            one, two = (bones[int(a[i])].lower() if 0 <= int(a[i]) < len(bones) else None for i in (2, 6))
            out.append({'cmd': 'AFTER_IMAGE4_ON_arg29', 'real': f, 'name': None,
                        'args': [f'brawl_trail_{int(a[0])}', f'brawl_trail_{int(a[0])}', int(a[1]), one, float(a[3]), float(a[4]),
                                 float(a[5]), two, float(a[7]), float(a[8]), float(a[9])]})
        elif e['event'] == 'sword_glow_off':
            out.append({'cmd': 'AFTER_IMAGE_OFF', 'real': f, 'name': None, 'args': list(a[:2])})
    return out


def load(fighter, root, lengths=None, stems=None):
    """-> the driver's `game`. `lengths`: {Brawl clip name: frames} (to close each action's time keys and to join a
    smash's wind-up onto its swing); `stems`: {Brawl clip name: the clip file's stem} as the clips were written out."""
    m = read_moveset(root, fighter)
    from . import brres
    folder, stem = find(root, fighter)
    body = arc.read((folder / f'{stem}00.pac').read_bytes())[1][0]['data']
    bones = [b['name'] for b in brres.bones(body, next(iter(brres.folders(body)['3DModels(NW4R)'].values())))[0]]
    from .transcode import ultimate_name
    bones = [ultimate_name(b) for b in bones]
    lengths, stems = lengths or {}, stems or {}
    names = sound_names(root)
    shared = {**common_effects(root), **own_effects(root, fighter)}
    from .transcode import motion_file
    motion, _clips = motion_file(root, fighter)
    seen_faces = {name: brres.visibility(motion, at)[1] for name, at in brres.folders(motion).get('AnmVis(NW4R)', {}).items()}
    moves, motions, seen, later = {}, {}, set(), {}
    for s in m.subactions():
        name = s['name']
        if not name or name in JOINED:
            continue
        if name in seen:
            # a second script under a name already read: kept when its hits are not the first's (the release of a
            # charge held to its fullest is its own script: other hitboxes, no armour). It plays the same clip.
            first = 'game_' + stems.get(name, 'z00' + name.lower())[3:]
            if first in moves and first not in later and name not in JOINS:
                again = action(m, s['index'], bones, 0.0, names, fighter, shared)
                if again['hitboxes'] and again['hitboxes'] != moves[first]['hitboxes']:
                    again.pop('_keys', None)
                    again['time_keys'], again['animation'] = moves[first]['time_keys'], moves[first]['animation']
                    moves[first + SECOND] = again
                    later[first] = first + SECOND
            continue
        seen.add(name)
        # (a clip of N frames hands over after N - 1: Ike's forward smash, a wind-up of 25 frames and a swing whose
        # hitboxes come out on its frame 7, is known to hit on frame 31)
        shift, fronts = 0.0, []
        for before in JOINS.get(name, []):
            index = next((x['index'] for x in m.subactions() if x['name'] == before), None)
            if index is not None and lengths.get(before):
                fronts.append(action(m, index, bones, shift, names, fighter, shared))
                shift += float(lengths[before] - 1)
        entry = action(m, s['index'], bones, shift, names, fighter, shared)
        # the face on each frame: the clip's own, after those of the clips joined on before it
        entry['faces'], before = [], 0.0
        for part in JOINS.get(name, []) + [name]:
            if part in seen_faces:
                for frame, state in faces(seen_faces[part], before):
                    if not entry['faces'] or entry['faces'][-1][1] != state:
                        entry['faces'].append([frame, state])
            before += float((lengths.get(part) or 1) - 1)
        for front in reversed(fronts):                  # what the clips before it do comes first
            for key in ('hitboxes', 'other', 'flags', 'turns', 'armour', 'momentum', 'effects', 'flashes', 'sounds'):
                entry[key] = front[key] + entry[key]
            entry['intangible'] = entry['intangible'] or front['intangible']
        total = (lengths.get(name) or 0) + shift
        if shift and name.startswith(CHARGED):
            entry['flags'].insert(0, {'cmd': 'on_flag', 'real': int(shift), 'which': 'charge'})
        last = (entry['cancel_frame_real'] - 1) if entry['cancel_frame_real'] else (int(total) - 1 if total else None)
        keys = [k for k in entry.pop('_keys') if last is None or k[0] < last]
        keys = [[0, 0.0]] + [[k[0], k[1] + shift] for k in keys if k[0] > 0]
        if last is not None and last > keys[-1][0]:
            rate = 1.0
            keys.append([int(last), round(keys[-1][1] + (last - keys[-1][0]) * rate, 5)])
        entry['time_keys'] = keys
        file_stem = stems.get(name, 'z00' + name.lower())
        entry['animation'] = file_stem + '.nuanmb'
        key = 'game_' + file_stem[3:]
        moves[key] = entry
        if entry['cancel_frame_real'] or entry['intangible']:
            motions[file_stem] = {'game': key, 'cancel_frame': entry['cancel_frame_real'], 'intangible': entry['intangible']}
    table = m.attributes()
    melee = []
    for index, name in ATTRIBUTES.items():
        _off, as_float, as_int = table[index]
        melee.append({'op': 'set_attribute', 'name': name, 'value': float(as_int if index in WHOLE else as_float)})
    params = {k: [(f if abs(f) < 1e6 and (abs(f) > 1e-6 or i == 0) else i) for _o, f, i in m.params(k)]
              for k in m.sections if k.startswith('param')}
    return {'fighter': fighter, 'game': 'brawl', 'attributes': {}, 'melee_attributes': melee, 'moves': moves,
            'same_name_scripts': later, 'registered_scripts': {'subactions': len(seen)}, 'motions': motions, 'motion_params': {},
            'own_params': params, 'bones': bones}
