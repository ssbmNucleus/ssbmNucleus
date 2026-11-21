"""A face made of whole parts: what the game's clips show and hide, carried as Melee's model states.

Ultimate keeps several meshes for one place on a body (an open eye, a half shut one, a shut one; a closed mouth and
an open one; folded wings and spread ones) and every clip says, frame by frame, which of them are drawn: its
visibility tracks, one for each node it names (the mesh objects called `<node>_VIS_O_OBJShape`, or `<node>Shape`,
are that node's). A node a clip does not name is left to the resting clip (`own_skeleton.REST_CLIP`), which runs
on a clock of its own whatever the fighter is doing: that is how a fighter blinks while it stands.

Melee has the same thing in another shape. A fighter's data lists its drawn pieces in GROUPS of CHOICES (ftData
+0x08): one choice of each group is drawn and the group's others are hidden, or none of them (-1). The engine keeps
the choice of each group (`fp->x5F4_arr`), a script command changes one (31, Change Model State), every change of
action puts them all back to the fighter's defaults (fighter.c:987), and the fighter's load code says what the
defaults are. A fighter has at most ELEVEN groups (ftparts.c ftParts_8007487C stops the game at twelve: Mr. Game &
Watch has the eleven) and 124 pieces (ftParts_80074194).

So, for ANY fighter whose face is part swaps, from its clips alone:

  plan      which nodes are choices of which group. Nodes that are never drawn together can be choices of one
            group; nodes that are always drawn together are one choice. The fewest groups are found (an exact
            colouring of "drawn together"); the body is the first group, with one choice. Should a fighter need more
            groups than the engine has, the two groups seen together least are made one (a stand-in: `joined`).
  pieces    the plan in the costume's piece numbers (`own_skeleton.body` carries every part, `own_data.build`
            writes the lists)
  scripts   every action's script gets a command on each frame its own clip's tracks change a group's choice
  code      the defaults (the resting face) set as the fighter loads, and the resting clip's clock: a group whose
            nodes an action's clip leaves alone follows the resting clip, frame by frame, round and round
  outside a match   the rows of the fighter's other table of actions (the results screen's poses) get their
            commands the same way (`outside_a_match`)

The driver calls `carry` once its scripts are written and `outside_a_match` once the other table's clips are made.

What the engine does with it, as read in the decompilation and seen in the game: the shadow's pass (and one
stage's reflection, and the bubble that shows a fighter off the screen) draws the low-detail lists by the same
choices, and here those lists give the switched groups nothing: the low-detail copy is of what is drawn at rest, so
a shadow is the resting outline. While a fighter is metal the engine draws the "body while metal" lists by the
same choices; they are the high-detail ones again. A hidden piece costs no time; it costs room in the costume
file (`skin_cost.small_pictures`).

What is a reading or a stand-in is said where it is made (search for STAND-IN).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from . import fighters

MOST_GROUPS = 11                   # ftparts.c ftParts_8007487C: "fighter parts model num over!" past this many
MOST_PIECES = 124                   # ftparts.c ftParts_80074194: "fighter parts model dobj num over!"
MODEL, REVERT, REMOVE = 31, 32, 33  # script commands: change one group's choice, all back to the defaults, all to none
END, WAIT, UNTIL, LOOP, AGAIN, CALL, RETURN, GOTO, WRAP = 0, 1, 2, 3, 4, 5, 6, 7, 8
SEARCH = 200000                     # steps the exact search for the fewest groups may take before the greedy answer stands

_READ = {}
# Parts the game shows and hides in its CODE, which no clip's tracks say (found on Wolf: the gun at his hip is a
# part of his body that no clip names, and the game's code hides it while the same gun, a second model the game
# makes as the neutral special starts, is in his hand). Per fighter:
#   'rest'   {node: drawn at rest}
#   'clips'  {clip: {node: (the clip frame it changes on, drawn before it, drawn from it on)}}
# They are added to what the clips say (`read`), so the groups, the scripts and the resting face carry them like
# any other part. A node named here that the body does not have changes nothing. Written in `fighters.py`
# (`code_shown`), the one place a fighter is written into.
CODE_SHOWN = fighters.column('code_shown')


# ---- the game's own word ---------------------------------------------------------------------------------------------
def read(root, fighter, rest_clip=None):
    """Every clip's visibility tracks. -> {'rest': the resting clip's name, 'clips': {clip: {'end': its last frame,
    'tracks': {node: [drawn or not, a frame each (one value: the same throughout)]}}}}"""
    if rest_clip is None:
        from .own_skeleton import REST_CLIP as rest_clip
    key = (str(root), fighter, rest_clip)
    if key not in _READ:
        import ssbh_data_py as ssbh
        motion = Path(root) / 'gamedata' / 'fighter' / fighter / 'motion' / 'body' / 'c00'
        clips = {}
        for path in sorted(motion.glob('*.nuanmb')):
            anim = ssbh.anim_data.read_anim(str(path))
            tracks = {}
            for g in anim.groups:
                if 'Visib' in str(g.group_type):
                    for n in g.nodes:
                        tracks[n.name] = [bool(v) for v in n.tracks[0].values]
            clips[path.stem] = {'end': int(anim.final_frame_index), 'tracks': tracks}
        code = CODE_SHOWN.get(fighter) or {}
        if rest_clip in clips:
            for node, drawn in (code.get('rest') or {}).items():
                clips[rest_clip]['tracks'].setdefault(node, [bool(drawn)])
        for stem, nodes in (code.get('clips') or {}).items():
            if stem in clips:
                for node, (frame, before, after) in nodes.items():
                    last = clips[stem]['end']
                    # (said over the clip's own word: the game's clips do name the gun at his hip, as drawn
                    # throughout, and its code hides it all the same)
                    clips[stem]['tracks'][node] = [bool(before if f < frame else after) for f in range(last + 1)]
        _READ[key] = {'rest': rest_clip, 'clips': clips}
    return _READ[key]


def node_of(name, nodes):
    """The node a mesh object belongs to (the longest that fits), or None for an object no node names."""
    return next((n for n in sorted(nodes, key=lambda n: (-len(n), n))
                 if name == n or name == n + 'Shape' or name.startswith(n + '_VIS')), None)


def _at(track, frame):
    return track[min(int(frame), len(track) - 1)]


def at_rest(clips, rest_clip):
    """{node: drawn when nothing else has spoken}: the resting clip's first frame, and for a node it does not name
    the first frame of the first clip that does (`own_skeleton.shown_at_rest` reads the same way)."""
    first = {}
    for stem in ([rest_clip] if rest_clip in clips else []) + sorted(clips):
        for node, track in clips[stem]['tracks'].items():
            first.setdefault(node, bool(track[0]))
    return first


def pictures(clips, rest_clip):
    """Every different picture the clips can make: {the nodes drawn together: on how many frames}. A node a clip
    does not name is as the resting clip has it, and the resting clip is on any of its frames then (its clock is
    not the clip's): each of its own pictures is laid under each frame of such a clip."""
    first = at_rest(clips, rest_clip)
    nodes = sorted(first)
    rest = clips.get(rest_clip, {'end': 0, 'tracks': {}})
    moving = {n for n, t in rest['tracks'].items() if len(set(t)) > 1}
    under_all = {frozenset(n for n in nodes if (_at(rest['tracks'][n], f) if n in rest['tracks'] else first[n]))
                 for f in range(rest['end'] + 1)}
    out = Counter()
    for stem, clip in clips.items():
        tracks = clip['tracks']
        left = set(nodes) - set(tracks)
        under = sorted({p & left for p in under_all}, key=sorted) if left & moving else \
            [frozenset(n for n in left if first[n])]
        seen = Counter(frozenset(n for n, t in tracks.items() if _at(t, f)) for f in range(clip['end'] + 1))
        for own, frames in seen.items():
            for u in under:
                out[own | u] += frames / len(under)
    return out


# ---- the plan --------------------------------------------------------------------------------------------------------
def fewest(units, together, least=1, search=SEARCH):
    """The units in as few sets as can be with no two of a set ever drawn together. `together`: {unit: the units
    drawn with it}; `least`: a number of sets known to be needed (the most units one picture draws).
    -> [[unit, ...], ...]. Exact while the search stays small (it does for a face); the best found otherwise."""
    order = sorted(units, key=lambda u: (-len(together[u]), u))
    greedy = {}
    for u in order:
        used = {greedy[v] for v in together[u] if v in greedy}
        greedy[u] = next(c for c in range(len(order) + 1) if c not in used)
    best = dict(greedy)
    steps = [0]

    def go(k, col, limit):
        steps[0] += 1
        if steps[0] > search:
            return None
        if k == len(order):
            return dict(col)
        u = order[k]
        used = {col[v] for v in together[u] if v in col}
        for c in range(min(limit, max(col.values(), default=-1) + 2)):
            if c not in used:
                col[u] = c
                got = go(k + 1, col, limit)
                if got:
                    return got
                del col[u]
        return None

    for limit in range(max(greedy.values(), default=-1), max(least, 1) - 1, -1):
        steps[0] = 0
        got = go(0, {}, limit)
        if not got:
            break
        best = got
    sets = defaultdict(list)
    for u in order:
        sets[best[u]].append(u)
    return [sorted(v) for _c, v in sorted(sets.items())]


def plan(clips, rest_clip, most=MOST_GROUPS - 1):
    """Which nodes are choices of which group, from the clips alone (see the module's notes).
    -> {'rest_clip', 'clock_end' (the resting clip's last frame), 'always' (nodes every picture draws: the body's),
        'never' (nodes no picture draws: left out of the costume), 'shown_at_rest' (the switched nodes that are up
        at rest), 'groups': [{'choices': [[node, ...], ...] (the nodes one choice draws), 'seen' (frames each is
        drawn on), 'rest' (the choice at rest, -1 for none), 'moving' (its nodes the resting clip itself switches),
        'clock' ([[frame, choice], ...]: the resting clip's own changes of this group, [] when it makes none)}],
        'joined' (what would not fit, and what stands in)}
    The engine's group of plan group k is k + 1: the body is its first."""
    seen = pictures(clips, rest_clip)
    first = at_rest(clips, rest_clip)
    nodes = sorted(first)
    total = sum(seen.values())
    frames = {n: sum(f for p, f in seen.items() if n in p) for n in nodes}
    always = [n for n in nodes if abs(frames[n] - total) < 1e-6]
    never = [n for n in nodes if frames[n] == 0]
    live = [n for n in nodes if n not in always and n not in never]
    ordered = sorted(seen, key=sorted)
    by_sign = defaultdict(list)
    for n in live:                                      # nodes always drawn together are one unit: one choice
        by_sign[tuple(n in p for p in ordered)].append(n)
    units = sorted(tuple(sorted(v)) for v in by_sign.values())
    unit_of = {u[0]: u for u in units}
    with_ = {u: set() for u in units}
    both = Counter()
    for p, f in seen.items():
        on = [unit_of[n] for n in sorted(p) if n in unit_of]
        for a, b in combinations(on, 2):
            with_[a].add(b)
            with_[b].add(a)
            both[frozenset((a, b))] += f
    def least_sets():
        return fewest(units, with_, max((sum(1 for u in units if u[0] in p) for p in seen), default=1))
    sets = least_sets()
    joined = []
    while len(sets) > most:
        # STAND-IN: more groups than the engine holds. Of two ways, the one that is wrong on fewer frames:
        #   - a part that is up at rest is drawn ALWAYS (taken out of the switching): wrong on the frames it is hidden
        #     (Incineroar, 2026-11-13: his ten claws and two toenails, each hidden on a few clips, were twelve groups);
        #   - the two groups seen together on the fewest frames become one; on those frames the choice seen more often
        #     is drawn and the other is not. Two groups that are both up at rest are never joined: the resting face
        #     could not be drawn (Incineroar's claws were joined with his mouth, and the mouth went).
        cost = lambda a, b: sum(both[frozenset((x, y))] for x in sets[a] for y in sets[b])     # noqa: E731
        up = lambda k: any(first[u[0]] for u in sets[k])                                      # noqa: E731
        pairs = [ab for ab in combinations(range(len(sets)), 2) if not (up(ab[0]) and up(ab[1]))]
        join = min(pairs, key=lambda ab: (cost(*ab), ab)) if pairs else None
        drawn = [u for u in units if first[u[0]]]
        keep_up = min(drawn, key=lambda u: (total - frames[u[0]], u)) if drawn else None
        if keep_up is not None and (join is None or total - frames[keep_up[0]] < cost(*join)):
            joined.append(dict(groups=[[list(keep_up)]], frames_seen_together=0,
                               frames_hidden=round(total - frames[keep_up[0]], 2),
                               how='drawn always: it is up at rest, and hidden on these frames only'))
            units.remove(keep_up)
            always = sorted(always + list(keep_up))
            live = [n for n in live if n not in keep_up]
            del with_[keep_up]
            for v in with_.values():
                v.discard(keep_up)
            sets = least_sets()
            joined = [j for j in joined if 'frames_hidden' in j]     # (the groups are found again: so are the joins)
            continue
        if join is None:
            break
        a, b = join
        joined.append(dict(groups=[[list(u) for u in sets[a]], [list(u) for u in sets[b]]],
                           frames_seen_together=round(cost(a, b), 2),
                           how='where both would be drawn, the one seen on more frames is, and the other is not'))
        sets[a] = sorted(sets[a] + sets[b])
        del sets[b]
    rest = clips.get(rest_clip, {'end': 0, 'tracks': {}})
    moving = {n for n, t in rest['tracks'].items() if len(set(t)) > 1}
    groups = []
    for members in sets:
        choices = sorted(members, key=lambda u: (not first[u[0]], -frames[u[0]], u))     # the resting choice first
        group = dict(choices=[list(u) for u in choices], seen=[round(frames[u[0]], 2) for u in choices],
                     rest=0 if first[choices[0][0]] else -1,
                     moving=sorted(n for u in choices for n in u if n in moving), clock=[])
        groups.append(group)
    groups.sort(key=lambda g: (g['rest'] != 0, g['choices'][0]))       # (a donor's own code sets its first groups to 0)
    out = dict(rest_clip=rest_clip, clock_end=int(rest['end']), always=always, never=never,
               shown_at_rest=sorted(n for n in live if first[n]), groups=groups, joined=joined,
               pictures=len(seen))
    for group in groups:
        if not group['moving']:
            continue
        was = group['rest']
        for f in range(rest['end'] + 1):
            shown = {n for n in live if (_at(rest['tracks'][n], f) if n in rest['tracks'] else first[n])}
            now = choice_of(group, shown)
            if now != was:
                group['clock'].append([f, now])
                was = now
    return out


def choice_of(group, shown):
    """The choice of a group that draws what a picture shows of it: -1 for none. (Where a joined group would draw
    two, the one seen on more frames: the STAND-IN `plan` names.)"""
    on = [k for k, unit in enumerate(group['choices']) if unit[0] in shown]
    if not on:
        return -1
    return max(on, key=lambda k: (group['seen'][k], -k))


def of_fighter(root, fighter, most=MOST_GROUPS - 1):
    """`plan` for a fighter's own clips."""
    got = read(root, fighter)
    from . import own_opacity
    return own_opacity.reserve_faces(plan(got['clips'], got['rest'], most), own_opacity.read(root, fighter))


# ---- the costume -----------------------------------------------------------------------------------------------------
def selection(objects, faces):
    """Which of a model's mesh objects the costume carries: all but those of a node no picture ever draws.
    `objects`: [(name, subindex)] in the model's order. -> [(name, subindex)], in that order."""
    nodes = faces['always'] + faces['never'] + [n for g in faces['groups'] for unit in g['choices'] for n in unit]
    return [(name, sub) for name, sub in objects if node_of(name, nodes) not in faces['never']]


def pieces(objects, faces):
    """The plan in piece numbers. `objects`: the mesh object of each of the costume's body pieces, in the engine's
    order ([(name, subindex)]: `selection`'s). -> {'high': the pieces that are always drawn (the body's group),
    'groups': [[[piece, ...] a choice] a group], 'rest': [each group's choice at rest]}"""
    nodes = faces['always'] + faces['never'] + [n for g in faces['groups'] for unit in g['choices'] for n in unit]
    owner = [node_of(name, nodes) for name, _sub in objects]
    place = {n: (g, c) for g, group in enumerate(faces['groups']) for c, unit in enumerate(group['choices'])
             for n in unit}
    groups = [[[] for _ in group['choices']] for group in faces['groups']]
    high = []
    for number, node in enumerate(owner):
        if node in place:
            g, c = place[node]
            groups[g][c].append(number)
        else:
            high.append(number)
    empty = [faces['groups'][g]['choices'][c] for g, group in enumerate(groups) for c, got in enumerate(group) if not got]
    if empty:
        raise ValueError(f'the model has no mesh for {empty}: a choice that draws nothing is no choice')
    if len(groups) + 1 > MOST_GROUPS:
        raise ValueError(f'{len(groups) + 1} groups: the engine holds {MOST_GROUPS}')
    return dict(high=high, groups=groups, rest=[g['rest'] for g in faces['groups']])


def drawn_at_rest(named):
    """The pieces drawn at rest, from `pieces`: the body's and each group's resting choice."""
    return sorted(named['high'] + [p for group, rest in zip(named['groups'], named['rest']) if rest >= 0
                                   for p in group[rest]])


# ---- an action's frames ----------------------------------------------------------------------------------------------
def frames_of(parts, end):
    """Which clip frame each frame of a job shows, as `own_bank.timeline` lays its parts end to end.
    `parts`: [(clip, keys or None)], keys [[the part's frame, the clip's frame], ...]; `end(clip)`: its last frame.
    -> [(part, clip frame)], one a frame."""
    out = []
    for k, (stem, keys) in enumerate(parts):
        last = float(end(stem))
        keys = [[int(f), float(t)] for f, t in (keys or ([[0, 0.0], [int(last), last]] if last else [[0, 0.0]]))]
        for f in range(keys[-1][0] + 1):
            a = max((key for key in keys if key[0] <= f), key=lambda key: key[0])
            b = min((key for key in keys if key[0] >= f), key=lambda key: key[0])
            t = a[1] if b[0] == a[0] else a[1] + (b[1] - a[1]) * (f - a[0]) / (b[0] - a[0])
            out.append((k, min(max(t, 0.0), last)))
    if len(out) == 1:                                   # one frame in all: a clip has to last, so it holds for one
        out.append(out[0])
    return out


def events(faces, clips, parts, loop=False, clock=True):
    """What an action's script has to say for its face: [(frame, the engine's group, choice)], each the frame a
    group's choice changes on (frame 0: where it starts other than at rest), with the groups the action's clips
    leave to the resting clip ([the engine's groups]) and notes.

    A node a clip does not name is as it is at rest. A group with nodes the resting clip switches, none of which
    any of the action's clips names, is LEFT to the resting clip: nothing is written for it, the port's code moves
    it on the resting clip's own clock (`code`). `clock`: False when there is no code to do that (the group then
    stays as it is at rest: no blink).
    An action that plays round and round says at its start where every group it changes begins, since it comes
    back there with them changed."""
    rest = set(faces['shown_at_rest'])
    live = [n for g in faces['groups'] for unit in g['choices'] for n in unit]
    tracks = [clips.get(stem, {}).get('tracks', {}) for stem, _keys in parts]
    left, notes = [], []
    for g, group in enumerate(faces['groups']):
        moving = set(group['moving'])
        if not group['clock']:
            continue
        named = [moving & set(t) for t in tracks]
        if not any(named):
            if clock:
                left.append(g)
        elif any(n != moving for n in named):
            # STAND-IN: a clip that names some of a group's blinking nodes and not the rest. The ones it leaves are
            # held as they are at rest; the game would run them on the resting clip's clock.
            notes.append(f"group {g + 1}: {sorted(moving - set.intersection(*named))} are left to the resting clip "
                         'beside nodes the clip switches itself; held as at rest')
    end = lambda stem: clips[stem]['end'] if stem in clips else 0     # noqa: E731
    state = {g: group['rest'] for g, group in enumerate(faces['groups'])}
    out, start = [], {}
    for frame, (k, t) in enumerate(frames_of(parts, end)):
        own = tracks[k]
        shown = {n for n in live if (_at(own[n], t + 1e-6) if n in own else n in rest)}
        for g, group in enumerate(faces['groups']):
            if g in left:
                continue
            now = choice_of(group, shown)
            if frame == 0:
                start[g] = now
            if now != state[g]:
                out.append((frame, g + 1, now))
                state[g] = now
    if loop:
        for g in sorted({g for f, g, _c in out if f > 0}):
            if not any(f == 0 and at == g for f, at, _c in out):
                out.append((0, g, start[g - 1]))
    return sorted(out), [g + 1 for g in left], notes


# ---- the scripts -----------------------------------------------------------------------------------------------------
def command(group, choice):
    """The script command that gives a group a choice (the engine reads the choice as nineteen signed bits, which
    the app's table of commands writes as one bit and eighteen: the bit is the sign's)."""
    return (MODEL, {'struct_id': int(group), 'extrabitnonsense': 1 if choice < 0 else 0, 'object_id': int(choice)}, None)


def lay(items, wanted, loops=False, start=1, block=None):
    """A script with model commands at their frames, and without any it had (the donor's, which name the donor's
    groups). `wanted`: [(frame, group, choice)]; `loops`: the action plays round and round and the commands must
    come round with it; `start`: the place a jump to this script's own start names (`scripts` re-points it once
    the script has its new place); `block(place)`: the commands of the block a call or a jump names.
    -> (the script, the wanted commands that could not be placed)

    The script is walked from its start, counting frames through its waits ("wait N frames", "wait until frame
    N"); a wait a command falls inside is cut in two there. What stands in the way of counting is written out,
    as the same commands in the same order, while commands are still waiting to be placed: a jump to another
    block is followed (the block's commands are copied in: the copy is this action's own), a call that waits is
    replaced by what it calls, a counted loop by its body that many times. The walk ends at the end mark or at a
    wait for the clip to come round (the script's own loop): commands for later frames go in before either. It
    also ends at anything that still cannot be counted, and commands for frames after that are not placed."""
    plain = lambda its: [i for i in its if i[0] not in (MODEL, REVERT, REMOVE)]     # noqa: E731
    items = plain(items)
    todo = sorted(wanted)
    out, frame, tail = [], 0, []

    def due(upto):
        got = []
        while todo and todo[0][0] <= upto:
            _f, group, choice = todo.pop(0)
            got.append(command(group, choice))
        return got

    def called(pointer):
        """What a call runs: its block's commands up to the first return, or None when it does not come back."""
        got = []
        for item in block(pointer) if block is not None else []:
            if item[0] == RETURN:
                return plain(got)
            if item[0] in (END, GOTO, WRAP):
                return None
            got.append(item)
        return None

    def waits(its):
        return its is None or any(i[0] in (WAIT, UNTIL, LOOP, AGAIN, CALL) for i in its)

    out += due(0)
    index, followed, ending, written = 0, [], 'end', 0
    while index < len(items):
        item = items[index]
        code, fields, pointer = item
        if code in (WAIT, UNTIL):
            after = frame + int(fields['frame']) if code == WAIT else max(frame, int(fields['frame']))
            while todo and todo[0][0] < after:
                at = todo[0][0]
                out.append((WAIT, {'frame': at - frame}, None) if code == WAIT else (UNTIL, {'frame': at}, None))
                out += due(at)
                frame = at
            out.append((WAIT, {'frame': after - frame}, None) if code == WAIT else item)
            frame = after
            out += due(frame)
        elif code == END:
            tail = items[index:]
            break
        elif code == WRAP:
            ending, tail = 'wrap', items[index:]
            break
        elif code == GOTO and block is not None and pointer != start and len(followed) < 4:
            items = items[:index] + plain(live(block(pointer)))
            followed.append(pointer)
            continue
        elif code == CALL and not waits(called(pointer)):
            out.append(item)                            # it waits for nothing: the frame is the same after it
        elif code in (CALL, LOOP) and todo and written < 16:
            body, after = (called(pointer) if code == CALL else None), index + 1
            if code == LOOP:
                depth, close = 0, None
                for k in range(index + 1, len(items)):
                    depth += (items[k][0] == LOOP) - (items[k][0] == AGAIN)
                    if depth < 0:
                        close = k
                        break
                if close is not None and 1 <= int(fields.get('count', 0)) <= 64:
                    body, after = items[index + 1:close] * int(fields['count']), close + 1
            if body is None:
                ending, tail = 'opaque', items[index:]
                break
            items = items[:index] + body + items[after:]
            written += 1
            continue
        elif code in (CALL, LOOP, AGAIN, RETURN, GOTO):
            ending, tail = 'opaque', items[index:]
            break
        else:
            out.append(item)
        index += 1
    lost = []
    if ending == 'opaque':
        lost, todo = list(todo), []
    while todo:
        at = todo[0][0]
        out.append((UNTIL, {'frame': at}, None))
        out += due(at)
    if loops and ending == 'end' and any(f > 0 for f, _g, _c in wanted):
        out += [(WRAP, {'unknown': 0}, None), (GOTO, {'target': 0, 'pointer': start}, start)]
    # (a block that was copied in and jumps back to its own start comes back to this script's start instead)
    tail = [(c, dict(f, pointer=start), start) if c == GOTO and p in followed else (c, f, p) for c, f, p in tail]
    return out + tail, lost


def live(items):
    """A script's commands up to its first jump or end mark: what the reader gives after one is never run (a
    script that is one jump is followed in the file by the next script's bytes)."""
    for k, item in enumerate(items):
        if item[0] in (END, GOTO):
            return list(items[:k + 1])
    return list(items)


def scripts(pl, faces, clips, jobs, rows, hold=None, clock=True, log=print):
    """Every action's script with its face on it. -> (the fighter data, a report)
    `faces`: the plan; `clips`: `read(...)['clips']`; `jobs`: the clip jobs the bank was made from ([{'motion',
    'parts': [{'stem', 'keys'}], 'loop'}]); `rows`: the bank's report of which actions play which clip ({symbol:
    {'kind', 'motion', 'actions'}}); `hold`: the clip whose first frame an action with no clip of its own holds;
    `clock`: the port's code file is built (it sets the defaults and runs the resting clip's clock). Without it
    every action says every group's choice at its start, and nothing blinks by the resting clip.
    The donor's own model commands come out of every script: they name the donor's groups."""
    from vault.echo.subactions import FighterDat
    fd = FighterDat(pl)
    by_motion = {j['motion']: j for j in jobs}
    wanted, left, notes = {}, {}, []
    for row in rows.values():
        if row.get('kind') == 'SOURCE' and row.get('motion') in by_motion:
            job = by_motion[row['motion']]
            parts, loop = [(p['stem'], p.get('keys')) for p in job['parts']], bool(job.get('loop'))
        elif row.get('kind') == 'HELD' and hold:
            parts, loop = [(hold, [[0, 0.0]])], False
        else:
            continue
        got, free, said = events(faces, clips, parts, loop, clock)
        notes += [f"{row.get('motion')}: {line}" for line in said]
        for index in row.get('actions') or []:
            wanted[index] = (got, loop)
            left[index] = free
    table = fd.action_table[0]
    report = dict(groups=len(faces['groups']) + 1, actions=0, commands=0, donor_commands_removed=0, not_placed={},
                  left={}, notes=notes, joined=faces['joined'])

    def block(pointer):
        return [(c.code, dict(c.fields), c.pointer) for c in fd.decode_script(pointer).commands if not c.after_end]

    for act in list(fd.actions):
        index, old = act.index, act.script_offset
        items = live(fd.script_items(index)) if old is not None else []
        got, loop = wanted.get(index, ([], False))
        if not clock:                                   # no code to set the defaults: every group, every time
            said = {g for f, g, _c in got if f == 0}
            got = sorted(got + [(0, g + 1, group['rest']) for g, group in enumerate(faces['groups'])
                                if g + 1 not in said])
        donors = sum(1 for i in items if i[0] in (MODEL, REVERT, REMOVE))
        far, followed = items, set()                    # ... in the blocks it jumps on to (`lay` copies those in)
        while far and far[-1][0] == GOTO and far[-1][2] not in followed | {old} and len(followed) < 4:
            followed.add(far[-1][2])
            far = live(block(far[-1][2]))
            donors += sum(1 for i in far if i[0] in (MODEL, REVERT, REMOVE))
        for code, _f, pointer in items:                 # ... and in what a script calls (shared: emptied where it lies)
            if code == CALL and pointer:
                for c in fd.decode_script(pointer).commands:
                    if c.code in (MODEL, REVERT, REMOVE) and not c.after_end:
                        fd.dat.set_u32(c.offset, WAIT << 26)            # "wait no frames": the same four bytes, nothing done
                        donors += 1
                        fd._scripts.clear()
        if not got and not donors:
            continue
        start = old if old is not None else table
        new, lost = lay(items, got, loop, start, block)
        change = fd.replace_script(index, new)
        for cmd in fd.script(index).commands:
            if cmd.code == GOTO and cmd.pointer == start:
                fd.dat.set_u32(cmd.offset + 4, change['new_offset'])
        fd._scripts.clear()
        report['donor_commands_removed'] += donors
        if got:
            report['actions'] += 1
            report['commands'] += len(got) - len(lost)
        if lost:
            report['not_placed'][act.motion or str(index)] = [list(e) for e in lost]
    for index, free in left.items():
        if free:
            report['left'][index] = free
    out = fd.to_bytes()
    problems = FighterDat(out).verify_roundtrip()
    if problems:
        raise ValueError(f'the scripts do not write back as read after the faces: {problems[:3]}')
    log(f"faces: {report['groups']} groups; {report['commands']} commands in {report['actions']} actions' scripts; "
        f"{report['donor_commands_removed']} of the donor's taken out; {len(report['left'])} actions leave a group to "
        f"the resting clip; not placed in {sorted(report['not_placed'])}")
    return out, report


def carry(pl, own, root, fighter, jobs, rows, mine=None, kit=True, log=print, demo_jobs=None):
    """The driver's stage: the face a costume carries (`<own>/body/receipt.json`, written by `own_skeleton.body`),
    on every action's script and in the port's code. `mine`: the port's own code so far (`own.build`'s dict, or
    None); `kit`: a code file can be built. -> (the fighter data, the port's own code, a report), the report None
    when the costume carries no parts to show and hide."""
    import json
    from vault.echo.subactions import FighterDat
    from . import own_bank
    receipt = Path(own) / 'body' / 'receipt.json'
    faces = (json.loads(receipt.read_text('utf-8')) if receipt.exists() else {}).get('faces')
    if not faces or not faces.get('groups'):
        return pl, mine, None
    got = read(root, fighter, faces['rest_clip'])
    if json.loads(json.dumps(of_fighter(root, fighter))) != faces:
        raise ValueError("the costume's groups are not the ones the fighter's clips give now: build the body again")
    fd = FighterDat(pl)
    named = fd.dat.u32(fd.dat.ptr(fd.ft_root + 0x08))
    if named != len(faces['groups']) + 1:
        raise ValueError(f"the fighter data names {named} model groups and the costume has {len(faces['groups']) + 1}: "
                         'write the fighter data again for this costume (own_data)')
    pl, report = scripts(pl, faces, got['clips'], jobs, rows, own_bank.HOLD_STEM, clock=bool(kit), log=log)
    report['left_outside_a_match'] = {index: free for index, (_at, _start, _got, _loop, free)
                                      in other_table(pl, faces, got['clips'], fighter, bool(kit), demo_jobs).items() if free}
    if kit:
        mine = code(mine, faces, report['left'], report['left_outside_a_match'])
    report['code'] = bool(kit)
    return pl, mine, report


def other_table(pl, faces, clips, fighter, clock=True, demo_jobs=None):
    """What the fighter's OTHER table of actions (ftData +0x14: the results screen's poses, the cut scenes') has
    to say for its face. A row plays the fighter's clip of its own name, whole, or holds the standing clip's first
    frame (`own_demo.jobs_for`: the rule the clips themselves are made by).
    -> {row: (where the row lies, its script's place or None, [(frame, group, choice)], it plays round and round,
              the groups it leaves to the resting clip)}"""
    from . import own_bank, own_demo
    rows = own_demo.demo_rows(pl)
    jobs, without = own_demo.jobs_for(fighter, rows, sorted(clips))
    if demo_jobs is not None:
        jobs.update(demo_jobs)
    from vault.echo.subactions import ACTION_SIZE, FighterDat
    fd = FighterDat(pl)
    table = fd.dat.ptr(fd.ft_root + 0x14)
    out = {}
    for row in rows:
        job = jobs.get(row['symbol'])
        if job:
            parts = [(part['stem'], part.get('keys')) for part in job['parts']]
        elif row['symbol'] in without:
            parts = [(own_bank.HOLD_STEM, [[0, 0.0]])]
        else:
            continue
        loop = bool(job and job.get('loop'))
        got, free, _notes = events(faces, clips, parts, loop, clock)
        out[row['index']] = (table + row['index'] * ACTION_SIZE, row['script'], got, loop, free)
    return out


def outside_a_match(pl, own, root, fighter, kit=True, log=print, demo_jobs=None):
    """The driver's second stage, after the clips of the fighter's other table of actions are made (`own_demo`):
    those rows' scripts get their faces too (a winner's grin on the results screen is a part swap like any
    other). -> (the fighter data, {row: commands written})"""
    import json
    from vault.echo.subactions import FighterDat
    receipt = Path(own) / 'body' / 'receipt.json'
    faces = (json.loads(receipt.read_text('utf-8')) if receipt.exists() else {}).get('faces')
    if not faces or not faces.get('groups'):
        return pl, {}
    clips = read(root, fighter, faces['rest_clip'])['clips']
    fd = FighterDat(pl)
    dat = fd.dat
    table = dat.ptr(fd.ft_root + 0x14)

    def block(pointer):
        return [(c.code, dict(c.fields), c.pointer) for c in fd.decode_script(pointer).commands if not c.after_end]

    done = {}
    for index, (at, script, got, loop, _free) in sorted(other_table(pl, faces, clips, fighter, bool(kit), demo_jobs).items()):
        if not kit:                                     # (as `scripts`: no code to set the defaults)
            said = {g for f, g, _c in got if f == 0}
            got = sorted(got + [(0, g + 1, group['rest']) for g, group in enumerate(faces['groups']) if g + 1 not in said])
        if not got:
            continue
        start = script if script is not None else table
        new, lost = lay(live(block(script)) if script is not None else [], got, loop, start, block)
        blob, pointers = FighterDat.encode_script(new)
        place = dat.append_struct(blob, pointers)
        dat.set_u32(at + 0x0C, place)
        dat.add_reloc(at + 0x0C)
        fd._scripts.clear()
        for cmd in fd.decode_script(place).commands:
            if cmd.code == GOTO and cmd.pointer == start:
                dat.set_u32(cmd.offset + 4, place)
        fd._scripts.clear()
        done[index] = len(got) - len(lost)
    log(f"faces outside a match: {sum(done.values())} commands in {len(done)} rows of the fighter's other table "
        f'({sorted(done)})')
    return dat.to_bytes(), done


# ---- the code --------------------------------------------------------------------------------------------------------
def code(own, faces, left, other=None, onload=True):
    """The port's own code (`own.build`'s dict, or None when the port has none) with the face's part of it: the
    defaults set as the fighter loads, and the resting clip's clock. `left`: {action: [the engine's groups its
    clips leave to the resting clip]} (`scripts`' report); `other`: the same for the rows of the fighter's other
    table of actions, which a fighter made for a screen that is not a match plays (`other_table`).
    -> the dict `code.source` takes as `own`.

    The clock runs on whatever the fighter does, as the game's does; while an action leaves a group to the resting
    clip the group is given the choice the resting clip has on the clock's frame. The defaults are put back every
    frame too: a donor's own code sets its own groups' defaults when the fighter comes back (Marth: his first two
    to their first choice)."""
    own = dict(own) if own else dict(source=[], frame=[], provides=[], load=[], table=[])
    groups = len(faces['groups']) + 1
    rest = [0] + [g['rest'] for g in faces['groups']]
    keys = sorted((f, g + 1, c) for g, group in enumerate(faces['groups']) for f, c in group['clock'])
    def bits(rows):
        got = [0] * (max([int(a) for a, free in (rows or {}).items() if free], default=-1) + 1)
        for action, free in (rows or {}).items():
            for g in free:
                got[int(action)] |= 1 << g
        return ', '.join(str(m) for m in got or [0])
    lines = [
        '// The face: parts of the model shown and hidden. The scripts switch what their own clips switch; here the',
        "// fighter's defaults (its resting face) are set, and the resting clip's own switches (a blink) are played on",
        '// a clock that runs on through every action, for the groups an action\'s clip leaves alone.',
        f'#define FACE_GROUPS {groups}',
        'static const s8 face_rest[FACE_GROUPS] = {' + ', '.join(str(v) for v in rest) + '};',
        'typedef struct { short frame; s8 group, choice; } FaceKey;',
        'static const FaceKey face_clock[] = {',
        *[f'    {{{f}, {g}, {c}}},' for f, g, c in keys],
        '    {32767, 0, 0},',
        '};',
        f'#define FACE_CLOCK_END {int(faces["clock_end"])}',
        'static const u16 face_left[] = {' + bits(left) + '};',
        "// (a fighter made for a screen that is not a match plays the rows of its other table of actions)",
        'static const u16 face_left_other[] = {' + bits(other) + '};',
        'static short face_time[6];',
        'static void FacesLoad(GOBJ *gobj)',
        '{',
        '    int g;',
        '    for (g = 0; g < FACE_GROUPS; g++)',
        '        Fighter_SetVisGroupDefault(gobj, g, face_rest[g]);',
        '}',
        'static void FacesFrame(FighterData *fd, GOBJ *gobj)',
        '{',
        '    int p = fd->ply, a = fd->action_id, g, i;',
        '    u16 left = 0;',
        '    s8 now[FACE_GROUPS];',
        '    for (g = 0; g < FACE_GROUPS; g++)',
        '    {',
        '        if (fd->dobj_toggle[g].prev_value != face_rest[g])',
        '            Fighter_SetVisGroupDefault(gobj, g, face_rest[g]);',
        '        now[g] = face_rest[g];',
        '    }',
        '    if (fd->ftaction == fd->ftData->ftaction)',
        '    {',
        '        if (a >= 0 && a < (int)(sizeof(face_left) / sizeof(face_left[0])))',
        '            left = face_left[a];',
        '    }',
        '    else if (a >= 0 && a < (int)(sizeof(face_left_other) / sizeof(face_left_other[0])))',
        '        left = face_left_other[a];',
        '    if (++face_time[p] > FACE_CLOCK_END)',
        '        face_time[p] = 0;',
        '    if (!left)',
        '        return;',
        '    for (i = 0; face_clock[i].frame <= face_time[p]; i++)',
        '        now[face_clock[i].group] = face_clock[i].choice;',
        '    for (g = 0; g < FACE_GROUPS; g++)',
        '        if (left & (1 << g))',
        '            Fighter_SetVisGroupCurrent(gobj, g, now[g]);',
        '}',
        '']
    own['source'] = list(own.get('source') or []) + lines
    own['load'] = list(own.get('load') or []) + (['FacesLoad(gobj);'] if onload else [])
    own['frame'] = list(own.get('frame') or []) + ['FacesFrame(fd, gobj);']
    own['provides'] = list(own.get('provides') or []) + [
        f"the resting face as the fighter's defaults, and the resting clip's clock ({len(keys)} switches a round)"]
    return own
