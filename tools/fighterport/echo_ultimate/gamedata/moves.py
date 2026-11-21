"""A fighter's moves read from the game: hitboxes with real frame windows, grab
boxes, throws, cancel frames and attributes.

Timing rule (fitted on Shulk's jab, up tilt and dash attack, then it
reproduced his other normals): the animation position starts at 1 on game
frame 1 and moves 1/rate per game frame, where rate is the last
FT_MOTION_RATE value (1 until one is set). A script's frame(n) fires on the
first game frame where the position has reached n.
"""
import math
from pathlib import Path

from . import arc, motion_list, names
from .acmd import ATTACK_ARGS, Scripts
from .prc import Prc

EPS = 1e-4
# ATTACK_IGNORE_THROW is the same call for a hitbox that must not hit the fighter being thrown
HITBOX_CALLS = ('ATTACK', 'ATTACK_IGNORE_THROW')
# Which targets a hitbox strikes ("collision situation"): the game's constants for it, by their place in this
# version's table of constants (the scripts hold the place, not the name). Told apart by what they sit on:
# a meteor (angle 270) with a twin of another angle is the airborne-only one of the pair, and a hit with an
# angle that follows the attacker (over 361) beside a twin with a plain angle is airborne-only too.
SITUATION = {'<const 0x4b50>': 'both', '<const 0xe7c4>': 'ground', '<const 0xe7c8>': 'air'}


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def with_real_frames(events):
    """Drop frame/wait markers and give every other event 'real': its game frame (1-based)."""
    g, p, rate, cur = 1, 1.0, 1.0, 1.0
    out = []
    for e in events:
        target = None
        if e['cmd'] == 'frame':
            target = _num(e.get('frame'))
        elif e['cmd'] == 'wait':
            w = _num(e.get('frames'))
            target = cur + w if w is not None else None
        if e['cmd'] in ('frame', 'wait'):
            if target is not None:
                if target > p + EPS:
                    k = math.ceil((target - p) * rate - EPS)
                    g += k
                    p += k / rate
                cur = target
            continue
        if e['cmd'] == 'FT_MOTION_RATE':
            r = _num((e.get('args') or [None])[-1])
            if r:
                rate = r
        out.append({**e, 'real': g})
    return out


def real_frame_of(events, script_frame):
    """Game frame on which animation frame `script_frame` is reached, given the
    script's own motion-rate changes (used for cancel frames)."""
    marked = list(events) + [{'cmd': 'frame', 'frame': float(script_frame)}, {'cmd': '_probe'}]
    ordered = []
    placed = False
    for e in marked[:-2]:
        f = _num(e.get('frame')) if e['cmd'] == 'frame' else None
        if not placed and f is not None and f > script_frame:
            ordered += marked[-2:]
            placed = True
        ordered.append(e)
    if not placed:
        ordered += marked[-2:]
    return next(e['real'] for e in with_real_frames(ordered) if e['cmd'] == '_probe')


def time_keys(events, last_frame=None):
    """Piecewise-linear map from Melee clip frame to Ultimate animation time,
    as [[clip frame, source time], ...] starting at [0, 0].

    Clip frame i is game frame i + 1; source time is the animation position
    minus 1. A break is added wherever the script changes the motion rate, so
    a clip sampled through these keys plays at the speed the game plays it.
    `last_frame` (the move's last frame, cancel frame - 1) closes the list;
    without it the list ends at the last rate change."""
    g, p, rate, cur = 1, 1.0, 1.0, 1.0
    keys = [[0, 0.0]]
    for e in events:
        target = None
        if e['cmd'] == 'frame':
            target = _num(e.get('frame'))
        elif e['cmd'] == 'wait':
            w = _num(e.get('frames'))
            target = cur + w if w is not None else None
        if e['cmd'] in ('frame', 'wait'):
            if target is not None:
                if target > p + EPS:
                    k = math.ceil((target - p) * rate - EPS)
                    g += k
                    p += k / rate
                cur = target
            continue
        if e['cmd'] == 'FT_MOTION_RATE':
            r = _num((e.get('args') or [None])[-1])
            if r and abs(r - rate) > 1e-9:
                if g - 1 > keys[-1][0]:
                    keys.append([g - 1, round(p - 1, 5)])
                rate = r
    if last_frame is not None and last_frame > keys[-1][0]:
        keys.append([int(last_frame), round(p - 1 + (last_frame + 1 - g) / rate, 5)])
    elif last_frame is not None:
        keys = [k for k in keys if k[0] <= last_frame]
    return keys


def norm_attack(args):
    """ATTACK arguments by name. 33 arguments means no second point (a sphere)."""
    a = list(args)

    def starts(n):
        """The last n values begin like a hitbox: a small id, a part, then a bone name."""
        return (len(a) >= n and isinstance(a[-n], int) and not isinstance(a[-n], bool) and 0 <= a[-n] < 16
                and isinstance(a[-n + 2], str) and not a[-n + 2].startswith('<'))

    # values built for an earlier call can still be in front (seen on Byleth: 35 values for a 33-value hitbox)
    if starts(36):
        a = a[-36:]
    elif starts(33):
        a = a[-33:]
        a = a[:12] + [None, None, None] + a[12:]
    elif len(a) == 33:
        a = a[:12] + [None, None, None] + a[12:]
    elif len(a) > 36:
        a = a[-36:]
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in zip(ATTACK_ARGS, a)}


def hitboxes(events):
    """Hitboxes with their first and last active game frame, and what the script says of who they strike:
    `targets` 'both', 'ground' or 'air' (None when the script's mark is not one known here); `catch_only`,
    the fighter this one is holding and nobody else; `ignore_throw`, anyone but the fighter being thrown.
    `run` numbers the attack a hitbox is part of: the game strikes a target once for as long as some hitbox
    of the attack is out, so hitboxes made while others are still out (a weaker late hit taking a hitbox's
    place) share a run, and one made after all were cleared starts the next."""
    live, done, run = {}, [], 0
    for e in with_real_frames(events):
        if e['cmd'] in HITBOX_CALLS:
            a = norm_attack(e['args'])
            hid = a.get('id')
            if not live:
                run += 1
            if hid in live:
                live[hid]['last'] = e['real'] - 1
                done.append(live.pop(hid))
            live[hid] = {'first': e['real'], 'last': None, **a, 'targets': SITUATION.get(str(a.get('ground_air'))),
                         'catch_only': False, 'ignore_throw': e['cmd'] == 'ATTACK_IGNORE_THROW', 'run': run}
        elif e['cmd'] == 'AttackModule::set_catch_only_all':
            on = next((v for v in e.get('made', []) if isinstance(v, bool)), True)
            for h in live.values():                     # said of every hitbox that is out
                h['catch_only'] = bool(on)
        elif e['cmd'] == 'AttackModule::clear_all':
            for h in live.values():
                h['last'] = e['real'] - 1
            done += list(live.values())
            live = {}
        elif e['cmd'] == 'AttackModule::clear':
            hid = (e.get('regs') or [None])[0]
            if not isinstance(hid, int):
                hid = next((v for v in e.get('made', []) if isinstance(v, int) and not isinstance(v, bool)), None)
            if hid in live:
                live[hid]['last'] = e['real'] - 1
                done.append(live.pop(hid))
    done += list(live.values())
    return sorted(done, key=lambda h: (h['first'], h['id'] if isinstance(h['id'], int) else 99))


# The numbers of a fighter's dodges and rolls (fighter_param_motion.prc, a row a fighter) and the few numbers every
# fighter shares that a port reads (common.prc). The files hold only hashes of their names; these are the names.
MOTION_FIELDS = tuple(f'escape_{d}_{w}' for d in ('n', 'f', 'b', 'air') for w in ('hit_xlu_frame', 'hit_normal_frame', 'cancel_frame'))
COMMON_FIELDS = ('guard_off_cancel_frame',)


def flashes(rows):
    """The colour a script lays over the fighter's body, from its effect script's rows, in the words the driver plays
    a flash in (the Brawl reader's): [[frame, [red, green, blue, alpha] of 255, frames it takes to get there]] (0: at
    once; alpha 0: none). FLASH sets a colour, FLASH_FRM has it change into another over some frames, COL_NORMAL
    takes it off. (BURN_COLOR and the lights thrown on him from one side are other events and are not read.)"""
    out = []
    for e in rows:
        a = [v for v in e.get('args') or [] if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if e['cmd'] == 'FLASH' and len(a) >= 4 and e.get('real'):
            out.append([int(e['real']), [int(round(255 * v)) for v in a[:4]], 0])
        elif e['cmd'] == 'FLASH_FRM' and len(a) >= 5 and e.get('real'):
            out.append([int(e['real']), [int(round(255 * v)) for v in a[1:5]], int(a[0])])
        elif e['cmd'] == 'COL_NORMAL' and e.get('real') and out:
            out.append([int(e['real']), [0, 0, 0, 0], 0])
    return out


def archive_paths(fighter):
    return {'scripts': f'prebuilt:/nro/release/lua2cpp_{fighter}.nro',
            'motion_list': f'fighter/{fighter}/motion/body/c00/motion_list.bin',
            'fighter_param': 'fighter/common/param/fighter_param.prc',
            'fighter_param_motion': 'fighter/common/param/fighter_param_motion.prc',
            'common': 'fighter/common/param/common.prc',
            'vl': f'fighter/{fighter}/param/vl.prc'}


def _leaves(node):
    """Every named value of a parameter file, whatever table it is in (the first row of a list)."""
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, (dict, list)):
                yield from _leaves(v)
            else:
                yield str(k), v
    elif isinstance(node, list):
        for v in node[:1]:
            yield from _leaves(v)


def game_scripts(registered) -> set:
    """The places of the move scripts to read: every `animcmd_game` registration, and an `animcmd_game_share` one
    for a name no `animcmd_game` registers. Shulk's five Monado Arts (game_specialnjump ... game_specialairnsmash)
    are registered ONLY as shared scripts; read without them, the arts had no move, so their own sound and effect
    scripts (the art's voice line, its glow) were passed over with them."""
    game = {r['name'] for r in registered if r['agent'] == 'animcmd_game'}
    return {n for n, r in enumerate(registered)
            if r['agent'] == 'animcmd_game' or (r['agent'] == 'animcmd_game_share' and r['name'] not in game)}


def own_registrations(registered) -> set:
    """Which registrations are the fighter's own, by their place in the list. One function of the game's registers
    every script of a kind (the moves' scripts, their effects, their sounds) for the fighter AND for each of its
    weapons, one after another, and nothing in a registration says whose it is. But no one of them registers a name
    twice: so the list of a kind falls into runs, a new run wherever a name comes that the run already has, and the
    fighter's (some hundred scripts against a weapon's few) is the longest. Only a name registered more than once
    needs the answer; for those, the registration in the longest run is the fighter's. -> the places of those."""
    out = set()
    kinds = {}
    for n, r in enumerate(registered):
        kinds.setdefault(r['agent'], []).append((n, r['name']))
    for rows in kinds.values():
        runs, seen = [[]], set()
        for n, name in rows:
            if name in seen:
                runs.append([])
                seen = set()
            seen.add(name)
            runs[-1].append((n, name))
        longest = max(runs, key=len)
        twice = {name for _n, name in rows if sum(1 for _m, other in rows if other == name) > 1}
        out |= {n for n, name in longest if name in twice}
    return out


def load(fighter, root, extra_names=()):
    """Everything this package can read for one fighter.

    `root` is the dump folder (romfs/data.arc, ArcExplorer/smash_arc.dll and,
    for names, Hashes_FullPath). Needed files are extracted on first use into
    <root>/gamedata/."""
    root = Path(root)
    paths = archive_paths(fighter)
    got = arc.extract(root, root / 'gamedata', list(paths.values()))
    files = {k: got[v] for k, v in paths.items()}
    if not files['scripts']:
        raise FileNotFoundError(f'no script module for {fighter!r} in the archive ({paths["scripts"]})')
    known = names.candidates(fighter, root / 'Hashes_FullPath', extra_names)
    labelled = arc.extract(root, root / 'gamedata', [p.format(f=fighter) for p in names.LABEL_FILES])
    for path in labelled.values():                      # effect and sound names (a file may be absent)
        if path:
            known |= names.labels_in(path)

    attributes = {}
    if files['fighter_param']:
        table = Prc(Path(files['fighter_param']).read_bytes(), known).root.get('fighter_param_table', [])
        row = next((r for r in table if r.get('fighter_kind') == f'fighter_kind_{fighter}'), None)
        if row:
            attributes = {k: (v if isinstance(v, (int, float, bool, str)) else repr(v)) for k, v in row.items()}

    motions, by_clip = {}, {}
    if files['motion_list']:
        ml = motion_list.read(files['motion_list'], known)
        if ml['bytes_left']:
            raise ValueError(f'motion list did not parse cleanly ({ml["bytes_left"]} bytes left)')
        motions = {m['game']: m for m in ml['motions']}
        # by clip: the frame the fighter may act on and the frames it cannot be hit on. Most common actions
        # (a tech, a getup, a ledge climb) run the game's shared scripts, which a fighter does not register,
        # so these are the only place their frames are written. (The first row of a clip is the plain one.)
        for m in ml['motions']:
            stem = str((m.get('animations') or [''])[0]).rsplit('.', 1)[0]
            if stem and stem not in by_clip and (m.get('cancel_frame') or m.get('intangible_end')):
                by_clip[stem] = {'game': str(m['game']), 'cancel_frame': m.get('cancel_frame') or None,
                                 'intangible': [m.get('intangible_start'), m.get('intangible_end')]
                                 if m.get('intangible_end') else None}

    motion_params = {}
    if files.get('fighter_param_motion'):
        table = Prc(Path(files['fighter_param_motion']).read_bytes(), known | set(MOTION_FIELDS)).root
        rows = next((v for v in table.values() if isinstance(v, list)), [])
        row = next((r for r in rows if str(r.get('fighter_kind')) == f'fighter_kind_{fighter}'), None)
        if row:
            motion_params = {str(k): v for k, v in row.items() if str(k) in MOTION_FIELDS and isinstance(v, (int, float))}
    if files.get('common'):
        shared = dict(_leaves(Prc(Path(files['common']).read_bytes(), set(COMMON_FIELDS)).root))
        motion_params.update({k: shared[k] for k in COMMON_FIELDS if isinstance(shared.get(k), (int, float))})

    sc = Scripts(files['scripts'], known)
    moves, later = {}, {}
    own = own_registrations(sc.registered)
    read = game_scripts(sc.registered)
    for n, r in enumerate(sc.registered):
        if n not in read:
            continue
        events = sc.decode(r['body'])
        timed = with_real_frames(events)
        m = motions.get(r['name'], {})
        cancel = m.get('cancel_frame') or None
        entry = {
            'hitboxes': hitboxes(events),
            'other': [{'cmd': e['cmd'], 'real': e['real'], 'args': e.get('args')}
                      for e in timed if e['cmd'] in ('CATCH', 'ATTACK_ABS', 'ATK_HIT_ABS', 'SEARCH')],
            # the frame a grab's boxes are gone on: where the script stops the grab from clashing, after it reached out
            'catch_end': next((e['real'] for e in timed if e['cmd'] == 'GrabModule::set_rebound'
                               and (e.get('made') or [None])[0] is False
                               and any(c['cmd'] == 'CATCH' and c['real'] < e['real'] for c in timed)), None),
            'motion_rates': [{'real': e['real'], 'rate': (e.get('args') or [None])[-1]}
                             for e in timed if e['cmd'] == 'FT_MOTION_RATE'],
            'animation': (m.get('animations') or [None])[0],
            'flags': [{'cmd': e['cmd'].split('::')[1], 'real': e['real']}
                      for e in timed if e['cmd'] in ('WorkModule::on_flag', 'WorkModule::off_flag')],
            # the frames on which the script turns the fighter to face the other way
            'turns': [e['real'] for e in timed if e['cmd'] == 'REVERSE_LR'],
            # the weapon or projectile models this script creates, by the game's own id for each
            'articles': [str(e['made'][0]) for e in timed
                         if e['cmd'] == 'ArticleModule::generate_article' and e.get('made')],
            'article_frames': [e['real'] for e in timed
                               if e['cmd'] == 'ArticleModule::generate_article' and e.get('made')],
            'cancel_frame_script': cancel,
            'cancel_frame_real': real_frame_of(events, cancel) if cancel else None,
            'time_keys': time_keys(events, real_frame_of(events, cancel) - 1 if cancel else None),
            'intangible': [m.get('intangible_start'), m.get('intangible_end')] if m.get('intangible_end') else None,
        }
        # A weapon (Byleth's whip sword, his axe; Duck Hunt's aiming reticle, his can) registers scripts under the
        # fighter's own move names. The fighter's own holds the hitboxes; the others are kept apart.
        if n in own:
            if r['name'] in moves:
                later.setdefault(r['name'], []).append(moves[r['name']])
            moves[r['name']] = entry
        elif r['name'] in moves:
            later.setdefault(r['name'], []).append(entry)
        else:
            moves[r['name']] = entry
    # what a move shows and plays, from its effect_ and sound_ scripts (the fighter's own)
    seen = set()
    for n, r in sorted(enumerate(sc.registered), key=lambda x: (x[0] not in own, x[0])):
        kind = {'animcmd_effect': 'effects', 'animcmd_sound': 'sounds'}.get(r['agent'])
        move = 'game_' + r['name'].split('_', 1)[1] if kind and '_' in r['name'] else None
        if move not in moves or (kind, move) in seen:
            continue
        seen.add((kind, move))
        rows = []
        for e in with_real_frames(sc.decode(r['body'])):
            args = e.get('args') or []
            name = next((a for a in args if isinstance(a, str) and not a.startswith('<')), None)
            rows.append({'cmd': e['cmd'], 'real': e['real'], 'name': name, 'args': args[:14]})
        moves[move][kind] = rows
        if kind == 'effects' and flashes(rows):
            moves[move]['flashes'] = flashes(rows)
    return {'fighter': fighter, 'attributes': attributes, 'moves': moves, 'same_name_scripts': later,
            'motions': by_clip, 'motion_params': motion_params,
            'registered_scripts': {k: sum(1 for r in sc.registered if r['agent'] == k)
                                   for k in sorted({r['agent'] for r in sc.registered})}}
