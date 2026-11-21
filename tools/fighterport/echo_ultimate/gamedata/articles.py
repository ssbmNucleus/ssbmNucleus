"""A fighter's articles (the game's word for what a fighter makes: a can, a clay pigeon, a bullet, an aiming
reticle) as their own move scripts say them, and the fighter's own sounds and effects that hang on no move script.

One function of the game registers every script of a kind for the fighter and then for each of its articles, one
after another, and nothing in a registration says whose it is (see `moves.own_registrations`). No one of them
registers a name twice, so the list falls into runs: a new run wherever a name comes that the run already has, or
where the scripts' code jumps to another part of the file (each owner's scripts lie together). The longest run is
the fighter's; every other run is one article's. `moves.load` keeps the fighter's and, of an article's, only the
scripts whose names the fighter's do not also use. This reads them all, run by run.

    load(fighter, root, names) -> {'articles': [{'scripts': {name: script}, 'first': n}, ...],
                                   'unscripted': {'game_<clip>': {'sounds': [...], 'effects': [...]}}}

A script is {'hitboxes': as `moves.hitboxes` gives them, 'events': every other call with its game frame}.
`names`: more script names to try against the file's hashes (an article's states are not named after clips).
"""
from pathlib import Path

from . import arc, moves, names as names_
from .acmd import Scripts

# Script names of articles that no clip is named after (found by hashing likely words: a can stands, is at its most
# shots, explodes; a clay is hit; a bullet moves; Greninja's shuriken is shot, and at its fullest is a maxshot and
# a maxvanish). Each word is tried alone and run together with one other (`max` + `shot`). More: `prc_names --scripts`.
ARTICLE_WORDS = ('stand', 'max', 'explode', 'hit', 'move', 'fly', 'shot', 'shoot', 'vanish', 'start', 'end', 'loop',
                 'burst', 'fall', 'landing', 'wait', 'attack', 'charge', 'turn', 'bound', 'reflect', 'appear', 'disappear',
                 'break', 'throw', 'air', 'ground', 'spin', 'catch', 'release')
ARTICLE_SCRIPTS = ARTICLE_WORDS + tuple(a + b for a in ARTICLE_WORDS for b in ARTICLE_WORDS if a != b)
GAP = 0x4000                    # scripts of one owner lie within this much of each other in the file


def runs(registered, agent='animcmd_game'):
    """The registrations of one kind as runs of one owner each: [[(place in the list, registration)]]."""
    out, seen, last = [], set(), None
    for n, r in enumerate(registered):
        if r['agent'] != agent:
            continue
        if not out or r['name'] in seen or (last is not None and abs(r['func'] - last) > GAP):
            out.append([])
            seen = set()
        seen.add(r['name'])
        out[-1].append((n, r))
        last = r['func']
    return out


def script(sc, r):
    """One registered script: its hitboxes, and every other call with the game frame it is made on."""
    events = sc.decode(r['body'])
    timed = moves.with_real_frames(events)
    return {'hitboxes': moves.hitboxes(events),
            'events': [{'cmd': e['cmd'], 'real': e['real'], 'args': e.get('args'), 'made': e.get('made')}
                       for e in timed if e['cmd'] not in moves.HITBOX_CALLS]}


def load(fighter, root, names=()):
    """The articles' own scripts, in the order the game registers them, and what the fighter's sound and effect
    scripts say for clips that have no move script (see the module's notes)."""
    root = Path(root)
    paths = moves.archive_paths(fighter)
    got = arc.extract(root, root / 'gamedata', [paths['scripts']])
    if not got[paths['scripts']]:
        raise FileNotFoundError(f'no script module for {fighter!r} in the archive')
    more = {kind + s for s in tuple(names) + ARTICLE_SCRIPTS for kind in names_.SCRIPT_KINDS}
    known = names_.candidates(fighter, root / 'Hashes_FullPath', more)
    for path in arc.extract(root, root / 'gamedata', [p.format(f=fighter) for p in names_.LABEL_FILES]).values():
        if path:
            known |= names_.labels_in(path)
    sc = Scripts(got[paths['scripts']], known)
    game = runs(sc.registered)
    own = max(game, key=len)
    articles = [{'first': run[0][0], 'scripts': {r['name']: script(sc, r) for _n, r in run}}
                for run in game if run is not own]
    # the fighter's own sound and effect scripts whose clip has no move script: {game_<clip>: {sounds, effects}}
    scripted = {r['name'] for _n, r in own}
    unscripted = {}
    for kind, agent in (('sounds', 'animcmd_sound'), ('effects', 'animcmd_effect')):
        for run in runs(sc.registered, agent):
            if len(run) < len(own) // 2:
                continue                                # an article's
            for _n, r in run:
                move = 'game_' + r['name'].split('_', 1)[1] if '_' in r['name'] and not r['name'].startswith('0x') else None
                if move is None or move in scripted:
                    continue
                rows = []
                for e in moves.with_real_frames(sc.decode(r['body'])):
                    args = e.get('args') or []
                    name = next((a for a in args if isinstance(a, str) and not a.startswith('<')), None)
                    rows.append({'cmd': e['cmd'], 'real': e['real'], 'name': name, 'args': args[:14]})
                unscripted.setdefault(move, {})[kind] = rows
    return {'fighter': fighter, 'articles': articles, 'unscripted': unscripted}
