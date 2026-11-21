"""Before a port's first long stage: everything that can be known in seconds, said at once.

    python -m fighter_port.preflight <fighter> --work <dir> --root <game files> [--own] [--donor Marth]
                                     [--game ultimate|brawl] [--mextk <dir>] [--iso <out>] [--no-extract] [--allow-large]

It is the first stage of `fighter_port.port` on both routes. A fighter nobody has ported yet used to meet its
problems one at a time, each after minutes of a stage (Wolf, ported cold: missing files at stage two, a table
nobody had named, a check of the route's own, a picture format, in four runs). Here each of those is asked
before anything long, ALL of them are printed, and each names the exact file and place that puts it right.

What it does, in order:
  the machine      the app checkout and its tools, the game's archive, MexTK, the donor and its package
  the files        the fighter's files out of the game's archive: taken out now if they are not (a local file,
                   <root>/romfs/data.arc; nothing is downloaded), and the ones each stage reads looked for by name
  what it is told  the fighter's entry in `fighters.py` (the one place a fighter is written into): each value given,
                   worked out or not there, and what stands in; the module of its own special states
  the limits       joints, joint depth, hurtboxes and clip bytes against what the engine holds, as far as each is
                   known this early (the rest are named with the stage that will know them)
  hurtboxes        the game's own table held against the skeleton, as the fighter-data stage will hold it
  effect pictures  every picture of the fighter's effect file read once
  costumes         how many, and the size of any already built against what a match's heap holds

Each line is one of
    ok        looked at, nothing to do
    note      something to know: a value worked out, a stand-in, a thing a later stage will settle
    PROBLEM   the run will fail or come out wrong because of this; the line says what to change and where
and it ends with the count. Any PROBLEM makes the stage fail, which stops the port command there. It writes
<work>/preflight.json with the same lines. It changes nothing in the work folder besides.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
import traceback
from pathlib import Path

ENGINE_JOINTS = ('__engine_Top', '__engine_XRot', '__engine_YRot', '__engine_ExtraMotion')
ROOT_BONES = ('Trans', 'Rot', 'Hip')            # the game's root chain, which the rig wraps the engine's joints round


class Lines:
    """What preflight has to say, gathered and printed as it goes."""

    def __init__(self, out=print):
        self.rows, self._out, self._section = [], out, None

    def section(self, name):
        self._section = name
        self._out(f'\n{name}')

    def _add(self, level, what, text):
        self.rows.append(dict(level=level, section=self._section, what=what, text=text))
        self._out(f"  {level:8} {what}: {text}")

    def ok(self, what, text):
        self._add('ok', what, text)

    def note(self, what, text):
        self._add('note', what, text)

    def problem(self, what, text):
        self._add('PROBLEM', what, text)

    def problems(self):
        return [r for r in self.rows if r['level'] == 'PROBLEM']

    def notes(self):
        return [r for r in self.rows if r['level'] == 'note']


def guarded(lines, what, check, *args):
    """Run one check. A check that falls over is itself a problem to say, and the checks after it still run: the
    point of this stage is that everything is said in one go."""
    try:
        return check(lines, *args)
    except Exception as exc:                            # noqa: BLE001 (said, with where it was)
        where = traceback.extract_tb(exc.__traceback__)[-1]
        lines.problem(what, f'the check itself fell over: {type(exc).__name__}: {exc} '
                            f'({Path(where.filename).name}:{where.lineno})')
        return None


# ------------------------------------------------------------------------------------------------------- the machine
def machine(lines, a):
    """The app checkout and its tools, the reader of the game's models, MexTK, the donor."""
    from . import fighters
    repo = os.environ.get('NUCLEUS_REPO')
    backend = Path(repo) / 'app' / 'backend' if repo else None
    if backend is None or not backend.is_dir():
        lines.problem('the app checkout', 'NUCLEUS_REPO must name the ssbmNucleus app checkout (every stage imports '
                                          'its app/backend): set it in the environment, or give --repo to the port '
                                          f'command. It is {repo!r} now')
    else:
        if str(backend) not in sys.path:
            sys.path.insert(1, str(backend))
        from . import compat
        compat.install()
        from core.config import HSDRAW_EXE, MEXCLI_PATH
        for name, path, used in (('HSDRawViewer', HSDRAW_EXE, 'the body is imported with it (prepare, costumes)'),
                                 ('MexCLI', MEXCLI_PATH, 'the project and every disc are made with it')):
            if Path(path).is_file():
                lines.ok(name, str(path))
            else:
                lines.problem(name, f'not at {path}: {used}. In the app checkout: python tools/build/fetch_native.py all')
        project = Path(a.work) / 'project' / 'project.mexproj'
        from shared.vanilla_extract import vanilla_refs
        iso = vanilla_refs.known_vanilla_iso()
        if iso:
            lines.ok('the vanilla disc', f'{iso} (the project stage builds on it)')
        elif project.exists():
            lines.note('the vanilla disc', f'the app has none recorded; {project} is there and the first project is made '
                                           'from it only once, but each disc starts from a fresh project and needs it')
        else:
            lines.problem('the vanilla disc', 'the app has no vanilla Melee disc recorded, and the project stage makes '
                                              'its project from one: open the app once and point it at the disc '
                                              '(shared/vanilla_extract/vanilla_refs.py keeps where it is)')
    if a.game != 'brawl':
        try:
            import ssbh_data_py                         # noqa: F401
            lines.ok("the reader of the game's models", f'ssbh_data_py from {Path(ssbh_data_py.__file__).parent}')
        except Exception as exc:                        # noqa: BLE001
            lines.problem("the reader of the game's models",
                          f'ssbh_data_py does not import ({type(exc).__name__}: {exc}): set SSBH_DATA_PY to the '
                          'folder it is importable from (<the game files>/pydeps/ssbh_data_py-0.9.1 when not set)')
    if a.own:
        try:
            import pyfqmr                               # noqa: F401
            lines.ok('the triangle merger', 'pyfqmr (the shadow copy of the body is made with it)')
        except Exception as exc:                        # noqa: BLE001
            lines.problem('the triangle merger', f'pyfqmr does not import ({type(exc).__name__}: {exc}): the body\'s '
                                                 'low-detail copy for the shadow is made with it (pip install pyfqmr)')
    from . import code
    kit = code.toolkit(a.mextk)
    if kit:
        lines.ok('MexTK', f"{kit} (the port's code file is built with it)")
    else:
        (lines.problem if a.own else lines.note)(
            'MexTK', f"none at {a.mextk or os.environ.get('MEXTK_DIR') or '(--mextk not given, MEXTK_DIR not set)'}"
            ' (it wants MexTK.exe and mex.h there). Set --mextk or MEXTK_DIR to the toolkit folder. '
            + ('Own-skeleton ports require the native-code compiler for specials and movement; '
               'building without it would leave the specials inert.' if a.own else
               'No custom code is built; the donor states remain and code-driven movement is not carried.'))
    why = fighters.donor_problem(a.donor)
    if why:
        lines.problem('the donor', why)
    else:
        lines.ok('the donor', f"{a.donor} (the one donor measured so far: there is no choice to make. Say with the port "
                              'which Melee fighter would have been closest, and what its states would have saved)')
    package = Path(a.work) / f'{a.donor}.zip'
    if package.is_file():
        import zipfile
        with zipfile.ZipFile(package) as z:
            names = set(z.namelist())
            entry = json.loads(z.read('fighter.json')) if 'fighter.json' in names else None
        files = (entry or {}).get('files') or {}
        lost = [f for f in (files.get('fighterDataPath'), files.get('animFile')) if not f or f not in names]
        if entry is None or lost:
            lines.problem("the donor's package", f'{package} is not a fighter package the driver can read (no '
                                                 f'fighter.json, or it lacks {lost}): delete it and the project stage '
                                                 "exports the donor's again")
        else:
            lines.ok("the donor's package", f'{package} ({package.stat().st_size:,} bytes)')
    else:
        lines.note("the donor's package", f'{package} is not there: the project stage exports it from its new project '
                                          '(a copy from an earlier port of the same donor saves that)')
    if a.iso:
        folder = Path(a.iso).resolve().parent
        if not folder.is_dir():
            lines.problem('the disc to write', f'{a.iso}: its folder {folder} is not there (the build stage does not '
                                               'make it)')
        elif Path(a.iso).exists():
            lines.note('the disc to write', f'{a.iso} is there already and will be written over by the build stage')
        else:
            lines.ok('the disc to write', str(a.iso))
    else:
        lines.note('the disc to write', 'no --iso: the build stage makes the fighter package and no disc'
                                        + ('' if a.own else ', and there is no round'))


# --------------------------------------------------------------------------------------------------------- the files
def wanted(root, fighter):
    """The archive paths a port's stages read for one fighter: (the fighter's models, clips and parameters; the
    script module, the shared tables and the files its effect and sound names are read from). The second lot is
    asked for by name and any of it may not exist for a fighter (one with no effect file)."""
    from echo_ultimate.gamedata import arc, moves, names
    own = arc.fighter_paths(arc.listed(root, [f'fighter/{fighter}/']), fighter)
    more = list(moves.archive_paths(fighter).values()) + [p.format(f=fighter) for p in names.LABEL_FILES]
    return own, [p for p in dict.fromkeys(more) if p not in own]


def files(lines, a):
    """The fighter's files out of the archive, taken out now if they are not. -> the fighter's folder under
    <root>/gamedata, or None when the stages cannot read it."""
    from echo_ultimate.gamedata import arc, moves
    from . import source_game
    root = Path(a.root)
    if source_game.written(a.game):
        return written_files(lines, a)
    need = [(root / 'romfs' / 'data.arc', "the game's archive"), (root / 'Hashes_FullPath', "the list of the archive's "
            'paths'), (root / 'ArcExplorer' / 'smash_arc.dll', 'the library the archive is read with')]
    gone = [(p, what) for p, what in need if not p.is_file()]
    for p, what in gone:
        lines.problem(what, f'{p} is not there. --root must be an Ultimate dump folder that holds romfs/data.arc, '
                            'Hashes_FullPath and ArcExplorer/smash_arc.dll')
    if any(p.name == 'Hashes_FullPath' for p, _ in gone):
        return None
    own, more = wanted(root, a.fighter)
    if not own:
        every = arc.fighter_names(root)
        near = difflib.get_close_matches(a.fighter, every, n=5, cutoff=0.5)
        lines.problem('the fighter', f"the archive has no fighter named {a.fighter!r}: the name is the folder's under "
                                     f"fighter/ in {root / 'Hashes_FullPath'} ({len(every)} there"
                                     + (f'; near it: {", ".join(near)}' if near else '') + ')')
        return None
    out = arc.not_out(root, own + more)
    if out and (gone or a.no_extract):
        # (said once: every file a stage reads by name is among them, and listing each would bury the one cause)
        lines.problem("the fighter's files",
                      f'{len(out)} of {len(own) + len(more)} are not out of the archive (the first: {out[0]}), and '
                      + ('the archive cannot be read (above)' if gone else
                         '--no-extract was given. Without it this stage takes them out; by hand: python -c "from '
                         f"echo_ultimate.gamedata import arc; print(arc.fetch_fighter(r'{root}', '{a.fighter}'))\""))
        return None
    if out:
        got = arc.extract(root, root / 'gamedata', out)
        taken = sum(1 for v in got.values() if v)
        absent = [p for p in out if not got.get(p)]
        lines.note("the fighter's files", f'{len(own) + len(more) - len(out)} were out of the archive; {taken} taken out '
                                          f"now into {root / 'gamedata'}"
                                          + (f"; {len(absent)} the archive does not hold: {', '.join(absent[:6])}" if absent else ''))
    else:
        lines.ok("the fighter's files", f"all {len(own) + len(more)} are out of the archive ({root / 'gamedata'})")
    # what each stage reads straight off the disk, by name
    folder = root / 'gamedata' / 'fighter' / a.fighter
    paths = moves.archive_paths(a.fighter)
    named = [(folder / 'model' / 'body' / 'c00' / n, 'prepare (the rig, the body)')
             for n in ('model.nusktb', 'model.numshb', 'model.numdlb', 'model.numatb')]
    named += [(Path(arc.local(root, paths['vl'])), 'prepare (hurtboxes), driver (the specials\' numbers)'),
              (Path(arc.local(root, paths['motion_list'])), 'driver (which clip a move plays, when the fighter may act)'),
              (Path(arc.local(root, paths['scripts'])), 'driver (every hitbox, sound and effect)'),
              (Path(arc.local(root, paths['fighter_param'])), "driver (the fighter's numbers)")]
    lost = [(p, used) for p, used in named if not p.is_file()]
    for p, used in lost:
        lines.problem('a file a stage reads', f'{p} is not there: {used}')
    clips = sorted((folder / 'motion' / 'body' / 'c00').glob('*.nuanmb'))
    if not clips:
        lines.problem("the fighter's clips", f"none in {folder / 'motion' / 'body' / 'c00'}: the rig and the clip bank "
                                             'are made from them')
    else:
        lines.ok("the fighter's clips", f'{len(clips)} in {clips[0].parent}')
    return None if lost or not clips else folder


def written_files(lines, a):
    """The fighter's files as the game's own reader wrote them in Ultimate's shapes (`source_game`). -> the
    fighter's folder, or None."""
    from . import source_game
    folder = source_game.folder(a.root, a.fighter)
    named = [(folder / 'model' / 'body' / 'c00' / n, 'prepare (the rig, the body)')
             for n in ('model.nusktb', 'model.numshb', 'model.numdlb', 'model.numatb')]
    named.append((folder / 'game.json', "prepare (hurtboxes), driver (every move, the fighter's numbers)"))
    lost = [(p, used) for p, used in named if not p.is_file()]
    for p, used in lost:
        lines.problem('a file a stage reads', f"{p} is not there: {used}. The game's reader writes it: "
                                              f"python -m echo_{a.game} <the game's folder> {a.fighter} {a.root}")
    clips = sorted((folder / 'motion' / 'body' / 'c00').glob('*.nuanmb'))
    if not clips:
        lines.problem("the fighter's clips", f"none in {folder / 'motion' / 'body' / 'c00'}")
    else:
        lines.ok("the fighter's files", f'written by echo_{a.game}: {len(clips)} clips in {clips[0].parent}')
    if lost or not clips:
        return None
    # what is in them, held against what the stages read (READERS.md): said here, before an hour of stages
    from . import reader_check
    said = reader_check.check(a.root, a.fighter)
    for level, what, text in said.rows:
        if level != 'ok':
            getattr(lines, level)(f"the reader's {what}", text)
    if not any(level == 'problem' for level, _w, _t in said.rows):
        lines.ok("the reader's output", f'{sum(1 for r in said.rows if r[0] == "ok")} things held against what the '
                                        'stages read (fighter_port.reader_check): nothing wrong')
    return folder


# ------------------------------------------------------------------------------------------------- what it is told
def skeleton(folder):
    """The game's own skeleton of the fighter as a rig (order, parent, rest, world)."""
    import ssbh_data_py as ssbh
    from . import native_port as core
    from .ultimate import skeleton_metadata
    return core.rig_from_meta(skeleton_metadata(ssbh.skel_data.read_skel(
        str(Path(folder) / 'model' / 'body' / 'c00' / 'model.nusktb'))))


def told(lines, a, folder, rig):
    """The fighter's entry in fighters.py, value by value, held against the game's files; its bindings; its module."""
    from . import fighters
    here = 'fighter_port/fighters.py'
    entry = fighters.FIGHTERS.get(a.fighter)
    if entry is None:
        lines.note('its entry', f"{a.fighter} has no entry in {here}: nothing has to be written for the command to run. "
                                'Each value below is what stands in; write an entry only for what the game\'s files '
                                'cannot say')
    else:
        unknown = sorted(set(entry) - set(fighters.VALUES))
        if unknown:
            lines.problem('its entry', f"{here}: {a.fighter}'s entry has {unknown}, which nothing reads (the values "
                                       f"are {', '.join(fighters.VALUES)})")
    bones = set(rig.order)
    stems = sorted(p.stem for p in (Path(folder) / 'motion' / 'body' / 'c00').glob('*.nuanmb'))

    # which joint is which
    order = list(rig.order) + [j for j in ENGINE_JOINTS if j not in bones]      # (the rig adds the engine's own)
    bound, source, notes = fighters.bindings(a.fighter, order, rig.parent, rig.world)
    stray = sorted({v for v in bound.values() if v and v not in set(order)})
    if stray:
        lines.problem('bindings', f"bound {source}: {stray} are not bones of the fighter's skeleton. Put the right bone "
                                  f"for each place in {a.fighter}'s `bindings` in {here}")
    missing = [s for s in fighters.NEEDED if not bound.get(s)]
    chain = [b for b in ROOT_BONES if b not in bones]
    if chain or rig.parent.get('Rot') != 'Trans':
        lines.problem('the root chain', f"the skeleton's root is not Trans > Rot > Hip (missing {chain or 'none'}; Rot "
                                        f"hangs from {rig.parent.get('Rot')!r}): own_skeleton.freeze wraps the engine's "
                                        'own joints round that chain and stops on any other (ROOT_CHAIN there)')
    elif missing:
        lines.problem('bindings', f'no joint for {missing}, which the engine turns on every fighter (bound {source}): '
                                  f"name each in {a.fighter}'s `bindings` in {here}")
    else:
        used = sum(1 for v in bound.values() if v)
        lines.ok('bindings', f'{used} of the engine\'s {len(bound)} places have a joint ({source})'
                             + ''.join(f'; {n}' for n in notes))
    empty = fighters.unbound_worth_a_look(bound)
    if empty:
        lines.note('bindings', f'no bone for {empty}: right for a body without that part; if the fighter has it under '
                               f"another name, bind it in {a.fighter}'s `bindings` in {here}")
    hold, who = fighters.item_hold(a.fighter, bound, bones)
    if hold is None:
        told_ = fighters.get(a.fighter, 'item_hold')
        lines.problem('item_hold', (f"{here} gives {told_!r}, which is not a bone of the skeleton" if told_ else
                                    'the skeleton has neither a hold slot nor a semantic hand binding, so there is no item-hold joint '
                                    'and the fighter-data stage stops') + f": name the joint in {a.fighter}'s "
                                    f"`item_hold` in {here}")
    else:
        (lines.ok if who == 'fighters.py' else lines.note)(
            'item_hold', f'{hold} ({who})' + ('' if who == 'fighters.py' else
                                              ': hold the game\'s a00waititem against a00wait1 to see where the '
                                              'fighter really carries a thing; another joint goes in `item_hold`'))

    # the taunt
    taunt = fighters.get(a.fighter, 'taunt')
    appeals = sorted({s[3:] for s in stems if s[3:].startswith('appeal')})
    if taunt and taunt not in appeals:
        lines.problem('taunt', f"{here} gives {taunt!r} and the fighter has no clip of that name (its taunts: "
                               f"{', '.join(appeals) or 'none'})")
    elif taunt:
        lines.ok('taunt', f'{taunt} (fighters.py)')
    else:
        lines.note('taunt', f"not given: the down taunt plays. The fighter's are {', '.join(appeals) or 'none'}; one it "
                            f"is known for goes in `taunt` in {here}")

    # what the game's code does that no file says
    hits, shown, parts = (fighters.get(a.fighter, k) for k in ('code_timed_hits', 'code_shown', 'article_parts'))
    if shown:
        lost = sorted(c for c in (shown.get('clips') or {}) if c not in stems)
        if lost:
            lines.problem('code_shown', f'{here} names clips the fighter does not have: {lost}')
        else:
            lines.ok('code_shown', f"parts the code shows and hides: at rest {shown.get('rest') or {}}, and in "
                                   f"{len(shown.get('clips') or {})} clips")
    else:
        lines.note('code_shown', "not given: a part is drawn by the clips' own word, and a part no clip names is always "
                                 'drawn. List the model\'s parts no clip names and ask of each what the game does with '
                                 'it (a holstered gun the code hides)')
    if parts:
        from echo_ultimate.gamedata import arc
        for part in parts:
            model = Path(folder) / 'model' / part['folder'] / 'c00' / 'model.nusktb'
            listed = arc.listed(a.root, [f"fighter/{a.fighter}/model/{part['folder']}/c00/"])
            if not listed:
                lines.problem('article_parts', f"{here} names the model folder {part['folder']!r}, and the archive has "
                                               f"no fighter/{a.fighter}/model/{part['folder']}/c00")
            elif part['joint'] not in bones:
                lines.problem('article_parts', f"{here} holds {part['folder']} at {part['joint']!r}, which is not a bone "
                                               'of the body')
            elif model.is_file() and part['held_at'] not in _bones(model):
                lines.problem('article_parts', f"{here} lays {part['folder']}'s own {part['held_at']!r} on the body's "
                                               f"{part['joint']}, and that model has no such bone "
                                               f'(it has {sorted(_bones(model))[:12]})')
            else:
                lines.ok('article_parts', f"{part['folder']} carried as the part {part['node']} at {part['joint']}")
    else:
        lines.note('article_parts', 'not given: nothing is put in a hand. A weapon the game keeps as a second model '
                                    f"(the folders beside body: {_model_folders(folder)}) and holds in its code is "
                                    'carried by naming it here, or its move is said to be bare-handed')
    if hits:
        lines.ok('code_timed_hits', f'{len(hits)} moves: {sorted(hits)} (held against the scripts by the driver)')
    else:
        lines.note('code_timed_hits', 'not given: every hitbox is on the frames its script says. A hitbox a script makes '
                                      'and never ends is timed by the game\'s code: its frames come from published '
                                      'frame data')

    # the specials
    name = fighters.specials_name(a.fighter)
    try:
        module = fighters.specials(a.fighter)
    except Exception as exc:                            # noqa: BLE001 (a module that does not import is said now)
        where = traceback.extract_tb(exc.__traceback__)[-1]
        lines.problem('its specials', f'fighter_port/{name}.py does not import: {type(exc).__name__}: {exc} '
                                      f'({Path(where.filename).name}:{where.lineno})')
        return bound
    if module is None:
        there = (Path(__file__).parent / f'{name}.py').is_file()
        if a.own:
            (lines.problem if there else lines.note)(
                'its specials', (f'fighter_port/{name}.py is there and has no build(ctx): the route cannot use it'
                                 if there else
                                 f'no fighter_port/{name}.py: the shared template carries clips and hitboxes; '
                                 'Slap City adds source movement, input callbacks and supported projectile classes; '
                                 'Rivals adds source window physics and supported follow-up states. '
                                 'Unimplemented behavior is listed in the build report'))
        else:
            lines.note('its specials', "on the donor's skeleton the donor's own special states are used with the "
                                       "fighter's clips where they fit (oneshot.special_rows); a move that fits none "
                                       f'gets states of its own in fighter_port/own.py (BUILD) or fighter_port/{name}.py')
    else:
        gives = [n for n in fighters.MODULE_NAMES if getattr(module, n, None)]
        lines.ok('its specials', f"fighter_port/{name}.py gives {', '.join(gives)}"
                                 + ('' if a.mextk or os.environ.get('MEXTK_DIR') else
                                    ' (and is not built without MexTK: see above)'))
    return bound


def on_the_donor(lines, a, folder=None):
    """A fighter carried onto the donor's skeleton: the body that is brought, and where its specials are written."""
    from . import fighters
    work = Path(a.work)
    made = sorted((work / 'package' / 'costumes').glob('*Nr.dat'))
    body = getattr(a, 'body', None)
    if body and Path(body).is_file():
        lines.ok('the body', f'{body} ({Path(body).stat().st_size:,} bytes)')
    elif made:
        lines.ok('the body', f'{made[0]} (made by an earlier run of the costumes stage)')
    elif body:
        lines.problem('the body', f'--body {body} is not there')
    else:
        # (a note, not a problem: the first run of a Brawl port is made without one, to get the model ready to import)
        lines.note('the body', 'no --body was given and the work folder has no costume yet: on the donor\'s skeleton '
                               "the body is brought, as the app's model importer made it (this command never imports "
                               'it: that costs money). The stages up to the driver and the sounds run without it; '
                               'the costumes stage stops')
    try:
        named = fighters.written_on_the_donor(a.fighter)
    except Exception as exc:                            # noqa: BLE001 (the driver's module needs the app checkout)
        lines.note('its specials', f'the tables were not read ({type(exc).__name__}: {exc})')
        return
    every = ', '.join(f'{module}.{name}' for module, name, _what in fighters.ON_THE_DONOR)
    if named:
        lines.ok('its specials', f"{a.fighter} is written in " + '; '.join(f'{m}.{n} ({what})' for m, n, what in named)
                 + f'. Every table of this route: {every}')
    else:
        lines.note('its specials', f"nothing is written for {a.fighter}: the donor's own special states are used with "
                                   'whichever of its clips fit them (oneshot.special_rows). What the game keeps in '
                                   'code and no file says (where a shot is kept, armour, a charge\'s numbers, a move '
                                   f'of its own) goes in the table beside the code that reads it: {every}')
    if folder is not None:
        taunt = fighters.get(a.fighter, 'taunt')
        appeals = sorted({p.stem[3:] for p in (Path(folder) / 'motion' / 'body' / 'c00').glob('*appeal*.nuanmb')})
        (lines.ok if taunt in appeals else lines.note)(
            'taunt', f'{taunt} (fighters.py)' if taunt in appeals else
            f"the down taunt plays; the fighter's are {', '.join(appeals) or 'none'}; another goes in `taunt` in "
            'fighter_port/fighters.py')


def _bones(skeleton_file):
    import ssbh_data_py as ssbh
    return {b.name for b in ssbh.skel_data.read_skel(str(skeleton_file)).bones}


def _model_folders(folder):
    models = Path(folder) / 'model'
    return sorted(p.name for p in models.iterdir() if p.is_dir() and p.name != 'body') if models.is_dir() else []


# -------------------------------------------------------------------------------------------------------- the limits
def depth(order, parent):
    """How deep a joint tree is: the most joints above any one joint."""
    deep = {}
    for j in order:                                     # (a parent comes before its children in a rig's order)
        deep[j] = deep[parent[j]] + 1 if parent.get(j) is not None else 0
    return max(deep.values(), default=0)


def limits(lines, a, rig):
    """Joints, depth and clip bytes against what the engine holds, as far as each is known now (PORT_CHECKLIST 11.1)."""
    from . import own_bank, own_data
    work = Path(a.work)
    source, deep = len(rig.order), depth(rig.order, rig.parent)
    frozen_path = work / 'rig' / f'rig-{a.fighter}.json'
    if frozen_path.is_file():
        frozen = json.loads(frozen_path.read_text('utf-8'))
        joints, rig_deep = len(frozen['order']), depth(frozen['order'], frozen['parent'])
        say = (f'{joints} in the rig {frozen_path.name} ({source} of the game\'s, the engine\'s own and '
               f'{joints - source - len(ENGINE_JOINTS)} helpers); the engine holds {own_data.MAX_PARTS}')
        (lines.ok if joints <= own_data.MAX_PARTS else lines.problem)('joints', say)
        say = f'{rig_deep} deep in the rig; the engine walks {own_data.MAX_DEPTH - 1}'
        (lines.ok if rig_deep < own_data.MAX_DEPTH else lines.problem)('joint depth', say)
    else:
        # The rig is the game's bones, the four joints the engine itself drives, and a helper wherever a clip
        # turns or scales a joint in a way Melee's joints cannot follow (found by reading every clip: the prepare
        # stage). So only the least is known now.
        least = source + len(ENGINE_JOINTS)
        say = (f"{source} bones in the game's skeleton: the rig will have at least {least} (with the engine's own "
               f'{len(ENGINE_JOINTS)}), and a helper for each joint a clip turns in a way Melee cannot (Duck Hunt 13, '
               f'Wolf 10): the engine holds {own_data.MAX_PARTS}')
        from . import own_skeleton
        if own_skeleton.tight(source):
            # (the rig folds the bones that cost no pose, and gives a helper only for an uneven scale:
            # own_skeleton.fold_plan; at the least, every bone the skin does not use is folded)
            try:
                skinned = own_skeleton._skinned(a.fighter, a.root)
            except Exception:                           # (no model to read: said by the files' own line)
                skinned = set(rig.order)
            kept = sum(1 for j in rig.order if j in skinned or j in own_skeleton.ROOT_CHAIN)
            say += (f'. Over the limit with room for {own_skeleton.HELPER_ROOM} helpers: the prepare stage folds the '
                    f'bones that cost no pose into the bone above them (the skin uses {kept} of the {source}; a bone '
                    'no clip moves goes too) and gives a helper only where a scale is uneven (own_skeleton, '
                    '"a skeleton over the joint limit"); it says the real count in its first lines')
            if kept + len(ENGINE_JOINTS) > own_data.MAX_PARTS:
                lines.note('joints', say + '. Animated leaf bones may also need folding into their parents. '
                           'Prepare preserves engine bindings, records each approximation, and checks the final rig limit.')
            else:
                lines.note('joints', say)
        elif least > own_data.MAX_PARTS:
            lines.problem('joints', say + '. This fighter cannot keep every bone: checklist 11.1')
        elif least + 15 > own_data.MAX_PARTS:
            lines.note('joints', say + '. CLOSE: the prepare stage says the real count after the rig (about a minute in)')
        else:
            lines.ok('joints', say + '; the real count is in the prepare stage\'s first lines')
        # (the engine's joints add three levels above the body: one over Trans, two over Rot; a helper adds one)
        least = deep + 3
        say = (f"{deep} deep in the game's skeleton: at least {least} in the rig; the engine walks "
               f'{own_data.MAX_DEPTH - 1}')
        if least >= own_data.MAX_DEPTH:
            lines.problem('joint depth', say + '. Too deep as it is: checklist 11.1')
        elif least + 3 >= own_data.MAX_DEPTH:
            lines.note('joint depth', say + '. CLOSE: a helper above a deep joint adds a level; prepare says')
        else:
            lines.ok('joint depth', say)
    # (the driver's own folder: `port` from the one command, `route` in a hand-run build; the newer if both)
    banks = [p for p in (work / n / 'bank' / 'report.json' for n in ('port', 'route')) if p.is_file()]
    if banks:
        totals = json.loads(max(banks, key=lambda p: p.stat().st_mtime).read_text('utf-8'))['totals']
        largest = totals['largest']
        say = (f"the largest of the bank's {totals.get('clips')} is {largest.get('symbol')} at {largest['bytes']:,} bytes "
               f"({totals.get('loosened')} were thinned to fit); the engine refuses a clip over {own_bank.CAPACITY:,}")
        (lines.ok if largest['bytes'] <= own_bank.CAPACITY else lines.problem)('clip bytes', say)
    else:
        lines.note('clip bytes', f'not known before the clip bank is made (the driver stage): it thins a clip that '
                                 f'would be over the engine\'s {own_bank.CAPACITY:,} bytes and says how many it thinned')


def hurtboxes(lines, a, folder, rig):
    """The game's own hurtbox table: how many, on which bones, and the left and right pairs held against the skeleton
    the way the fighter-data stage holds them (so a table that stage would stop on is said now)."""
    import numpy as np
    from . import fighters, own_data
    order = list(rig.order)
    index = {j: i for i, j in enumerate(order)}
    try:
        from . import source_game
        src = (source_game.tables(a.root, a.fighter) if source_game.written(a.game) else
               own_data.source_tables((Path(folder) / 'param' / 'vl.prc').read_bytes(), order))
    except ValueError as exc:
        lines.problem('hurtboxes', f"the game's table (hit_data in param/vl.prc) does not read against the skeleton: "
                                   f'{exc} (own_data.source_tables)')
        return
    count = len(src['hurt'])
    say = f"{count} in the game's table; Melee holds {own_data.MAX_HURTBOXES}"
    if not 1 <= count <= own_data.MAX_HURTBOXES:
        lines.problem('hurtboxes', say + '. The fighter-data stage stops on this: the table has to be cut to the '
                                         f'{own_data.MAX_HURTBOXES} that matter (own_data.build takes `source` in place '
                                         'of the game\'s table)')
        return
    lines.ok('hurtboxes', say + f" (on {', '.join(r['bone'] for r in src['hurt'])})")
    parents = [None if rig.parent[j] is None else index[rig.parent[j]] for j in order]
    worlds = np.array([rig.world[j] for j in order])
    check = own_data.capsule_check(own_data.hurtboxes(src['hurt'], order), order, parents, worlds,
                                   accepted=tuple(fighters.get(a.fighter, 'lopsided') or ()))
    for line in own_data.sides_problems(check):
        lines.problem('hurtboxes, left and right', line)
    for line in own_data.lopsided_notes(check):
        lines.note('hurtboxes, left and right', line)
    if check['sides_ok'] and not own_data.lopsided_notes(check):
        lines.ok('hurtboxes, left and right', f"{len(check['pairs'])} pairs, each the other's mirror image")


def effect_pictures(lines, a):
    """Every picture of the fighter's effect file read once: one the reader cannot read costs what is drawn with it."""
    from echo_ultimate import effects
    path = Path(a.root) / 'gamedata' / 'effect' / 'fighter' / a.fighter / f'ef_{a.fighter}.eff'
    if not path.is_file():
        lines.note('effect pictures', f'{a.fighter} has no effect file of its own ({path.name}): its scripts\' own '
                                      'effects are not drawn')
        return
    unread, read = effects.unread_pictures(path)
    if unread:
        lines.note('effect pictures', f'{read} read; {len(unread)} in a format the reader does not know: '
                                      + ', '.join(f'{n} ({f:#x})' for n, f in unread)
                                      + '. The effects drawn with them are not carried (the run goes on, the driver\'s '
                                        'report lists them). To carry them add the format to FORMATS and `textures` '
                                        'in echo_ultimate/effects.py')
    else:
        lines.ok('effect pictures', f'all {read} of {path.name} read')


def costumes(lines, a):
    """How many costumes the game has on this body, and the size of any already built against a match's heap."""
    from . import recolors, skin_cost
    folders = recolors.costume_folders(a.root, a.fighter, 'c00')
    lines.ok('costumes', f"{len(folders)} share the first's model: {', '.join(folders)}"
                         + ('' if len(folders) <= 8 else ' (the first 8 are made: a fighter here has 8 file codes)'))
    built = sorted((Path(a.work) / 'package' / 'costumes').glob('*.dat'))
    if not built:
        if a.own:
            lines.note('costume size', 'not known before the body is made: the prepare stage prints the first '
                                       "costume's bytes by kind, and the costumes stage stops on one over "
                                       f'{skin_cost.COSTUME_MOST:,} (a match holds each costume whole in a heap of '
                                       '6,599,680 bytes: two of 2.9 MB did not load)')
        return
    largest = max(built, key=lambda p: p.stat().st_size)
    kinds = skin_cost.bytes_by_kind(largest.read_bytes())
    stop = skin_cost.too_large(largest.name, kinds)
    by = '; '.join(f"pictures {fmt} {row['bytes']:,}" for fmt, row in kinds['pictures']['by_format'].items())
    say = (f"{len(built)} built; the largest is {largest.name}, {kinds['bytes']:,} bytes ({by}; display lists "
           f"{kinds['display_lists']:,}; the rest {kinds['rest']:,})")
    if stop and not a.own:
        # (the donor's skeleton: an imported body is a fraction of this size, and that route's stage has no stop)
        lines.note('costume size', say + f'. Over {skin_cost.COSTUME_MOST:,}: read the heap in the game '
                                         '(harness/heap_probe.py) before believing this disc')
    elif stop and not a.allow_large:
        lines.problem('costume size', say + '. ' + stop)
    elif stop:
        lines.note('costume size', say + f'. Over {skin_cost.COSTUME_MOST:,}, and --allow-large was given: read the heap '
                                         'in the game before believing this disc')
    else:
        lines.ok('costume size', say + (f'; the costumes stage stops over {skin_cost.COSTUME_MOST:,}' if a.own else ''))


# ---------------------------------------------------------------------------------------------------------- the run
def run(a, out=print):
    """Every check, in order. -> the lines (`Lines`)."""
    lines = Lines(out)
    skeleton_ = 'its own skeleton' if a.own else "the donor's skeleton"
    out(f'preflight: {a.fighter} from {a.game}, on {skeleton_}, donor {a.donor}, in {a.work}')
    lines.section('the machine')
    guarded(lines, 'the machine', machine, a)
    from . import source_game
    if a.game != 'ultimate' and not source_game.written(a.game):
        lines.section("the fighter's files")
        root = Path(a.root)
        if root.is_dir():
            lines.ok('the game files', f'{root} (the Brawl reader looks for its own files in it as each stage needs '
                                       'them; this stage does not know their names)')
        else:
            lines.problem('the game files', f'{root} is not a folder: --root is the Brawl disc, extracted')
        if a.own:
            lines.problem('the route', "--own carries an Ultimate fighter: its rig and clips are read from that game's "
                                       'files (own_route.run)')
        else:
            lines.section(f'what {a.fighter} is told')
            guarded(lines, 'what it is told', on_the_donor, a)
        return lines
    lines.section("the fighter's files")
    folder = guarded(lines, "the fighter's files", files, a)
    if folder is None:
        lines.note('the rest', 'not looked at: what the fighter is told, the limits, its hurtboxes and its effect '
                               'pictures are read from its files')
        return lines
    rig = guarded(lines, "the fighter's skeleton", lambda _lines: skeleton(folder))
    if rig is not None and a.own:
        lines.section(f'what {a.fighter} is told (fighter_port/fighters.py)')
        guarded(lines, 'what it is told', told, a, folder, rig)
        lines.section("the engine's limits")
        guarded(lines, 'the limits', limits, a, rig)
        guarded(lines, 'hurtboxes', hurtboxes, a, folder, rig)
    elif rig is not None:
        lines.section(f'what {a.fighter} is told')
        lines.note('the route', "on the donor's skeleton the fighter's clips are carried onto the donor's bones: its "
                                "joints, their depth and its hurtboxes are the donor's, so none is counted here")
        guarded(lines, 'what it is told', on_the_donor, a, folder)
    lines.section('effects and costumes')
    guarded(lines, 'effect pictures', effect_pictures, a)
    guarded(lines, 'costumes', costumes, a)
    return lines


def main(argv=None):
    from fighter_port import source_game
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('fighter')
    p.add_argument('--work', required=True)
    p.add_argument('--root', required=True)
    p.add_argument('--game', default='ultimate', choices=('ultimate', 'brawl') + source_game.GAMES)
    p.add_argument('--donor', default='Marth')
    p.add_argument('--own', action='store_true')
    p.add_argument('--mextk')
    p.add_argument('--iso')
    p.add_argument('--body', help="(on the donor's skeleton) the body as the model importer made it")
    p.add_argument('--no-extract', action='store_true', help='say what is not out of the archive and take nothing out')
    p.add_argument('--allow-large', action='store_true', help='a costume over the size a match is known to hold is a '
                                                              'note here, not a problem')
    a = p.parse_args(argv)
    lines = run(a)
    problems, notes = lines.problems(), lines.notes()
    work = Path(a.work)
    if work.is_dir():
        (work / 'preflight.json').write_text(json.dumps(
            dict(fighter=a.fighter, game=a.game, donor=a.donor, own=bool(a.own), problems=len(problems),
                 notes=len(notes), lines=lines.rows), indent=1), 'utf-8')
    print(f"\npreflight: {len(problems)} problem{'s' if len(problems) != 1 else ''}, {len(notes)} "
          f"note{'s' if len(notes) != 1 else ''}" + (':' if problems else '. Nothing stops the run.'))
    for row in problems:
        print(f"  PROBLEM  {row['what']}: {row['text']}")
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
