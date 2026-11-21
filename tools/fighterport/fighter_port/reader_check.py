"""What a game's reader wrote, held against what the port reads, before the port starts (READERS.md).

    python -m fighter_port.reader_check <root> <fighter>

<root>/gamedata/fighter/<fighter>/ is the folder `source_game.py` describes. Each row is a PROBLEM (the port would
stop, or would carry something wrong without a word: fix the reader), a NOTE (left to a stand-in, said so the
port's report is not a surprise), or OK. Preflight runs it for every written game (`preflight.written_files`).

What it catches is what the cold trials lost time to, each found only later in a port or in the game:
  - a name in `melee_attributes` the app does not know is dropped without a word (Rivals 2 gap 19);
  - a roll, getup or ledge climb whose clip leaves the fighter where he started rolls on the spot (Rivals 2 gap 41);
  - time keys that run on to the clip's end free every move at its clip's end (source_game.py; verify 2.2);
  - an `also` name with no number is never found by the donor's table's numbered rows (source_game.py);
  - a skeleton with no `Throw` hangs the shield from the nearest joint (checklist 11.42);
  - a body lying down or facing away (the axes: check them on a picture of the fighter standing);
  - a hitbox or hurtbox on a joint the skeleton does not have, a move playing a clip that was not written.
"""
from __future__ import annotations

import json
import re
import sys
import wave
from pathlib import Path

import numpy as np

MODEL = ('model.nusktb', 'model.numshb', 'model.numdlb', 'model.numatb')
NEEDED = {'fighter': str, 'game': str, 'moves': dict, 'melee_attributes': list, 'source_tables': dict}
# joints the route finds by name: without the first three it cannot carry the fighter right; the rest stand in at
# the next joint up the chain (oneshot.stand_in_landmarks), which the port's report says
MUST_BONES = {'Trans': 'the root the clips move him by', 'Hip': 'the body joint the driver binds first',
              'Throw': 'the joint a held fighter AND the shield hang from (11.42)'}
LANDMARKS = ('Rot', 'Head', 'HandL', 'HandR', 'FootL', 'FootR')
# clips in which Melee moves the fighter by the clip's own root (Trans; Ultimate's fighter faces +Z): +1 ahead,
# -1 back. A reader of a game that moves these in code gives them the travel (echo_rivals2.transcode.TRAVEL).
TRAVEL = {'b02escapef': 1, 'b02escapeb': -1, 'f05passivestandf': 1, 'f05passivestandb': -1,
          'f03downforwardu': 1, 'f03downbacku': -1, 'f04downforwardd': 1, 'f04downbackd': -1,
          'g02cliffclimb': 1, 'g02cliffescape': 1}
LEAST_TRAVEL = 1.0              # the port's units (Ultimate's): a roll goes 25 to 50, a climb 5 to 20


class Said:
    def __init__(self):
        self.rows = []

    def problem(self, what, text):
        self.rows.append(('problem', what, text))

    def note(self, what, text):
        self.rows.append(('note', what, text))

    def ok(self, what, text):
        self.rows.append(('ok', what, text))


def _few(items, n=6):
    items = list(items)
    return ', '.join(map(str, items[:n])) + (f' and {len(items) - n} more' if len(items) > n else '')


def files(said, folder):
    body = folder / 'model' / 'body'
    lost = [n for n in MODEL if not (body / 'c00' / n).is_file()]
    if lost:
        said.problem('the body', f'{_few(lost)} not in {body / "c00"}')
    if not list((body / 'c00').glob('*.nutexb')):
        said.problem('the pictures', f'no .nutexb in {body / "c00"}: the body would be drawn without its pictures')
    costumes = sorted(p.name for p in body.glob('c0*') if p.is_dir())
    empty = [c for c in costumes if not any((body / c).iterdir())]
    if empty:
        said.problem('the costumes', f'{_few(empty)} hold no file (a costume is its pictures, or a body of its own)')
    clips = sorted((folder / 'motion' / 'body' / 'c00').glob('*.nuanmb'))
    if not clips:
        said.problem('the clips', f'none in {folder / "motion" / "body" / "c00"}')
    if not lost and clips:
        said.ok('the files', f'the body, {len(costumes)} costumes ({_few(costumes, 8)}), {len(clips)} clips')
    return {p.stem: p for p in clips}


def skeleton(said, folder):
    """{name: world 4x4 (column vectors)} of the rest pose, or None."""
    path = folder / 'model' / 'body' / 'c00' / 'model.nusktb'
    if not path.is_file():
        return None
    try:
        import ssbh_data_py as ssbh
    except ImportError:
        said.note('the skeleton', 'not read: ssbh_data_py is not on the path (SSBH_DATA_PY)')
        return None
    try:
        bones = ssbh.skel_data.read_skel(str(path)).bones
    except Exception as e:
        said.problem('the skeleton', f'{path.name} does not read: {e}')
        return None
    names = [b.name for b in bones]
    world = {}
    for b in bones:
        m = np.asarray(b.transform, float).T
        world[b.name] = world[names[b.parent_index]] @ m if b.parent_index is not None else m
    lost = [f'{n} ({why})' for n, why in MUST_BONES.items() if n not in world]
    if lost:
        said.problem('the joints the route needs', 'none named ' + '; '.join(lost) + ': rename the game\'s own '
                     '(the readers\' NAMES), or add the joint (echo_slapcity.transcode adds Throw)')
    stand = [n for n in LANDMARKS if n not in world]
    if stand:
        said.note('landmark joints', f'none named {_few(stand)}: each stands in at the next joint up the chain')
    standing(said, world)
    return world


def standing(said, world):
    """Ultimate's fighter stands Y up and faces +Z with his left at +X: a body that does not is the axes' fault."""
    y = {n: m[1, 3] for n, m in world.items()}
    head = y.get('Head', max(y.values()))
    feet = [y[n] for n in ('FootL', 'FootR') if n in y]
    hip = y.get('Hip')
    order = [v for v in (head, hip, min(feet) if feet else None) if v is not None]
    if not all(a > b for a, b in zip(order, order[1:])) or head <= 0:
        said.problem('upright', f'the head ({head:.2f}), hip and feet are not one above the other along +Y: the '
                     'axes are wrong (check them on a picture of the fighter standing)')
        return
    ahead = [world[t][2, 3] - world[f][2, 3] for t, f in (('ToeL', 'FootL'), ('ToeR', 'FootR')) if t in world and f in world]
    if ahead and np.mean(ahead) <= 0:
        said.problem('facing', 'the toes are not ahead of the feet along +Z: he faces away (the axes, or a mirror)')
    elif not ahead:
        said.note('facing', 'no ToeL/FootL pair to tell which way he faces: check +Z on a picture')
    height = head - (min(feet) if feet else min(y.values()))
    said.ok('upright', f'stands {height:.1f} units high along +Y' + (', facing +Z' if ahead else ''))


def clips(said, clip_files, world):
    """Each clip moves joints of the skeleton; the clips Melee moves him by travel."""
    try:
        import ssbh_data_py as ssbh
    except ImportError:
        return {}
    frames, strangers, unread, still = {}, [], [], []
    for stem, path in clip_files.items():
        try:
            anim = ssbh.anim_data.read_anim(str(path))
        except Exception as e:
            unread.append(f'{stem} ({e})')
            continue
        frames[stem] = anim.final_frame_index
        nodes = {nd.name: nd for g in anim.groups if g.group_type.name == 'Transform' for nd in g.nodes}
        if world is not None and nodes and not set(nodes) & set(world):
            strangers.append(stem)
        if stem in TRAVEL:
            trans = nodes.get('Trans')
            z = float(trans.tracks[0].values[-1].translation[2] - trans.tracks[0].values[0].translation[2]) \
                if trans and trans.tracks and trans.tracks[0].values else 0.0
            if z * TRAVEL[stem] < LEAST_TRAVEL:
                still.append(f'{stem} ({z:+.1f})')
    if unread:
        said.problem('clips that do not read', _few(unread))
    if strangers:
        said.problem('clips on another skeleton', f'{_few(strangers)} move no joint of this skeleton (renamed in '
                     'the body but not in the clips?)')
    if still:
        said.problem('travel', f'{_few(still)}: the clip leaves him where he started, so he would roll or climb on '
                     f'the spot. Give the root (Trans) the travel along +Z (a game that moves these in code: '
                     f'echo_rivals2.transcode.TRAVEL)')
    looked = [s for s in TRAVEL if s in clip_files]
    if looked and not still:
        said.ok('travel', f'{len(looked)} rolls, getups and ledge clips move him along +Z')
    return frames


def attribute_names():
    """vault.echo.attributes (the app's): (resolve_key, every name), or None."""
    try:
        from vault.echo.attributes import ATTRIBUTES, resolve_key
    except ImportError:
        try:
            import nucleus_root
            sys.path.insert(0, str(nucleus_root.BACKEND))
            from vault.echo.attributes import ATTRIBUTES, resolve_key
        except Exception:
            return None
    return resolve_key, [a[1] for a in ATTRIBUTES]


def numbers(said, ops):
    known = attribute_names()
    if known is None:
        said.note("the fighter's numbers", 'not checked: the app (NUCLEUS_REPO) is not found')
        return
    resolve, names = known
    import difflib
    wrong = []
    for op in ops:
        if not isinstance(op, dict) or op.get('op') != 'set_attribute':
            wrong.append(f'{op!r} (each is {{"op": "set_attribute", "name", "value"}})')
            continue
        try:
            resolve(str(op.get('name')))
        except KeyError:
            near = difflib.get_close_matches(str(op.get('name')), names, 2, 0.6)
            wrong.append(f"{op.get('name')!r}" + (f' (perhaps {" or ".join(near)})' if near else ''))
            continue
        if not isinstance(op.get('value'), (int, float)) or isinstance(op.get('value'), bool):
            wrong.append(f"{op.get('name')}: {op.get('value')!r} is not a number")
    if wrong:
        said.problem("the fighter's numbers", f'{_few(wrong)}: the app would drop each without a word. The names '
                     'are vault/echo/attributes.py\'s (ATTRIBUTES, or an alias in ALIASES)')
    else:
        said.ok("the fighter's numbers", f'{len(ops)} under names the app knows')


def game_json(said, folder, fighter, clip_files, frames, world):
    path = folder / 'game.json'
    if not path.is_file():
        said.problem('game.json', f'{path} is not there')
        return None
    try:
        game = json.loads(path.read_text('utf-8'))
    except ValueError as e:
        said.problem('game.json', f'does not read as JSON: {e}')
        return None
    from . import source_game
    bad = [f'{k} ({t.__name__})' for k, t in NEEDED.items() if not isinstance(game.get(k), t)]
    if bad:
        said.problem('game.json', f'lacks {_few(bad)}: see READERS.md "game.json"')
    if isinstance(game.get('game'), str) and not source_game.written(game['game']):
        said.problem('game.json', f"its game {game['game']!r} is not in source_game.GAMES: add it there")
    if isinstance(game.get('fighter'), str) and game['fighter'] != fighter:
        said.problem('game.json', f"its fighter is {game['fighter']!r}, its folder {fighter!r}")
    if isinstance(game.get('melee_attributes'), list):
        numbers(said, game['melee_attributes'])
    if isinstance(game.get('moves'), dict):
        moves(said, game['moves'], clip_files, frames, world)
    if isinstance(game.get('source_tables'), dict):
        tables(said, game['source_tables'], world)
    return game


WHOLE = {'top'}                 # Ultimate's word for the fighter himself (Melee's TopN): a box placed from his origin


def _joint(name, world):
    if world is None or name is None or str(name).lower() in WHOLE:
        return True
    lower = {n.lower() for n in world}
    return str(name).lower() in lower


def moves(said, table, clip_files, frames, world):
    """A box's `last` may be None (its script never ends it: out to the clip's end) or before its `first` (made and
    made again on one frame, a choice the game's code makes: the driver keeps the one that stays, SPECIALS.md
    "alternatives"). Special and conditional-only branch time keys are ended by their runtime adapter; their input
    interrupt may precede natural completion (verify 2.2 holds ordinary moves only)."""
    no_clip, late, unordered, off_bone, bad_box = [], [], [], set(), []
    for name, m in table.items():
        clip = m.get('animation')
        stem = Path(clip).stem if clip else None
        if stem and stem not in clip_files:
            choices = m.get('entry_clips') or []
            conditional = choices and (any(c.get('choice') for c in choices) or
                                         not any(c.get('weight', 1) > 0 for c in choices))
            detail = ('; source selects/blends ' + ', '.join(dict.fromkeys(str(c.get('clip')) for c in choices)) +
                      ' at runtime: implement its source_programs control flow') if conditional else ''
            no_clip.append(f'{name} ({clip}{detail})')
        keys = m.get('time_keys') or []
        if any(not (isinstance(k, (list, tuple)) and len(k) == 2) for k in keys) or \
                any(a[0] >= b[0] for a, b in zip(keys, keys[1:])):
            unordered.append(name)
        elif keys and m.get('cancel_frame_real') and keys[-1][0] >= m['cancel_frame_real'] \
                and not name.startswith('game_special') and not m.get('conditional_only'):
            late.append(f"{name} (keys to {keys[-1][0]}, free on {m['cancel_frame_real']})")
        for h in m.get('hitboxes') or []:
            if not _joint(h.get('bone'), world):
                off_bone.add(str(h.get('bone')))
            first, last = h.get('first'), h.get('last')
            if not isinstance(first, int) or not (last is None or isinstance(last, int)) or not (h.get('size') or 0) > 0:
                bad_box.append(f"{name} #{h.get('id')} (first {first}, last {last}, size {h.get('size')})")
    if no_clip:
        said.problem('moves without their clip', f'{_few(no_clip)}: the clip was not written')
    if unordered:
        said.problem('time keys', f'{_few(unordered)}: each key is [move frame, clip frame], the move frames rising')
    if late:
        said.problem('time keys', f'{_few(late)}: the keys must stop on the frame BEFORE the cancel frame (the driver '
                     'plays the clip on past it and frees the move there; keys to the end free him at the clip\'s end)')
    if off_bone:
        said.problem('hitboxes', f'on joints the skeleton has not: {_few(sorted(off_bone))}')
    if bad_box:
        said.problem('hitboxes', f'{_few(bad_box)}: a box has a first frame (an int), a last (an int, or None: to '
                     'the clip\'s end) and a size')
    if not (no_clip or unordered or late or off_bone or bad_box):
        boxes = sum(len(m.get('hitboxes') or []) for m in table.values())
        said.ok('moves', f'{len(table)} moves, {boxes} hitboxes, each on a joint and with its clip')


def tables(said, st, world):
    hurt, ecb = st.get('hurt'), st.get('ecb')
    if not isinstance(hurt, list) or not hurt:
        said.problem('hurtboxes', 'source_tables.hurt is empty: nothing could hit him')
        return
    off = sorted({str(h.get('bone')) for h in hurt if isinstance(h, dict) and not _joint(h.get('bone'), world)})
    thin = [h.get('bone') for h in hurt if isinstance(h, dict) and not (h.get('radius') or 0) > 0]
    if off:
        said.problem('hurtboxes', f'on joints the skeleton has not: {_few(off)}')
    if thin:
        said.problem('hurtboxes', f'with no radius: {_few(thin)}')
    eoff = sorted({str(e.get('bone')) for e in ecb or [] if isinstance(e, dict) and not _joint(e.get('bone'), world)})
    if eoff:
        said.problem('collision joints', f'source_tables.ecb names joints the skeleton has not: {_few(eoff)}')
    if not (off or thin or eoff):
        said.ok('hurtboxes', f'{len(hurt)} hurtboxes and {len(ecb or [])} collision joints, each on a joint')


def plus_rows(fighter):
    """The names the donors' tables take in number order (`+vc_{f}_attack`: vc_<f>_attack01, 02 ...)."""
    from . import voice
    out = set()
    for d in voice.DONOR.values():
        for _samples, tries in d['roles']:
            out |= {t[1:].format(f=fighter).lower() for t in tries if t.startswith('+')}
    return out


def sounds(said, folder, fighter, game):
    sound = folder / 'sound'
    index_file = sound / 'sounds.json'
    if not index_file.is_file():
        said.note('sounds', 'no sound/sounds.json: every donor voice is made silent, the donor\'s other sounds stay')
        return
    try:
        index = json.loads(index_file.read_text('utf-8'))
    except ValueError as e:
        said.problem('sounds', f'sounds.json does not read: {e}')
        return
    lost, not_pcm, unnamed, numberless = [], [], [], []
    plus = plus_rows(fighter)
    words = set()
    for name, row in index.items():
        words.add(name.lower())
        f = sound / str((row or {}).get('file'))
        if not f.is_file():
            lost.append(name)
        else:
            try:
                with wave.open(str(f)) as w:
                    if w.getsampwidth() != 2:
                        not_pcm.append(f'{name} ({8 * w.getsampwidth()}-bit)')
            except (wave.Error, EOFError) as e:
                not_pcm.append(f'{name} ({e})')
        if not re.match(r'(se|vc)_', name.lower()):
            unnamed.append(name)
        for also in (row or {}).get('also') or []:
            words.add(str(also).lower())
            if str(also).lower() in plus:
                numberless.append(f'{name}: {also}')
    if lost:
        said.problem('sounds', f'files not there: {_few(lost)}')
    if not_pcm:
        said.problem('sounds', f'not 16-bit PCM WAVs: {_few(not_pcm)}')
    if unnamed:
        said.note('sounds', f'named outside Ultimate\'s words (se_<f>_..., vc_<f>_...): {_few(unnamed)}; a move '
                  'that plays one by that name still finds it, the donor\'s table does not')
    if numberless:
        said.problem('sounds', f'`also` names with no number: {_few(numberless)}. The donor\'s table takes these in '
                     f'number order (vc_{fighter}_attack01, 02 ...) and never finds a plain word')
    played = sorted({str(e.get('name')).lower() for m in ((game or {}).get('moves') or {}).values()
                     for e in m.get('sounds') or [] if e.get('name')} - words)
    if played:
        said.note('sounds', f'{len(played)} sounds the moves play are not in the sound folder (silent): {_few(played)}')
    if not (lost or not_pcm or numberless):
        said.ok('sounds', f'{len(index)} sounds')


def identity(said, folder):
    ident = folder / 'identity'
    if not ident.is_dir():
        said.note('identity', 'no identity folder: the donor\'s series emblem and victory fanfare stay')
        return
    have = [n for n in ('series_icon.png', 'victory.wav', 'identity.json') if (ident / n).is_file()]
    if (ident / 'series_icon.png').is_file():
        try:
            from PIL import Image
            with Image.open(ident / 'series_icon.png') as im:
                im.verify()
        except ImportError:
            pass
        except Exception as e:
            said.problem('identity', f'series_icon.png does not open: {e}')
    if (ident / 'identity.json').is_file():
        try:
            json.loads((ident / 'identity.json').read_text('utf-8'))
        except ValueError as e:
            said.problem('identity', f'identity.json does not read: {e}')
    lacking = [n for n in ('series_icon.png', 'victory.wav') if n not in have]
    if lacking:
        said.note('identity', f'no {" or ".join(lacking)}: the donor\'s stays for it')
    else:
        said.ok('identity', 'the series emblem and the victory fanfare')


def check(root, fighter):
    """-> Said: rows of (level, what, text) for <root>/gamedata/fighter/<fighter>."""
    from . import source_game
    said = Said()
    folder = source_game.folder(root, fighter)
    if not folder.is_dir():
        said.problem('the folder', f'{folder} is not there: the game\'s reader writes it')
        return said
    clip_files = files(said, folder)
    world = skeleton(said, folder)
    frames = clips(said, clip_files, world)
    game = game_json(said, folder, fighter, clip_files, frames, world)
    sounds(said, folder, fighter, game)
    identity(said, folder)
    return said


def main(argv=None):
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) != 2:
        raise SystemExit(__doc__.split('\n\n')[1])
    said = check(*args)
    for level, what, text in said.rows:
        print(f'{level.upper():8s} {what}: {text}')
    problems = sum(1 for r in said.rows if r[0] == 'problem')
    print(f'{problems} problems' if problems else 'no problems: the port can start')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
