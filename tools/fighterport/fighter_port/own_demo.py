"""The clips a fighter on its OWN skeleton plays outside a match: the results screen's, and the standing clip the
one-player cut scenes use.

A fighter's data has a second table of actions (ftData +0x14, with a pair of bytes an action at +0x18): its "demo"
actions, played by a fighter made for a screen that is not a match. Their clips are not in the fighter's bank. They
sit in other files, and the engine reads them this way (the decompilation: ft/ftdemo.c, ft/ftdata.c, ft/ft_0BEC.c,
ft/ft_0BEF.c, ft/ft_0BF0.c, gm/gmresultplayer.c):

  * `ftDemo_CreateFighter` is told what kind of screen the fighter is for. The kind says which rows of the table
    are given clips and which row the fighter starts in (`SCENES`, `ENTERED`):
        the results screen   rows 0..9    a winner starts in row 0, 2 or 5 (B, Y or X held as the screen loads, else
                                          one of the three by chance: gmresultplayer.c fn_8017A67C) and every loser
                                          in row 9
        the one-player intro rows 10..11  (the "versus" card before a fight: the fighter on the left, on the right)
        the ending           row 12       (the fighter falling as a trophy)
        the cut scenes       row 13       (the fighter standing)
    No code that has been read enters rows 1, 3, 4, 6, 7 or 8, and no state's own function moves a fighter on from
    the row it started in: a winner plays its clip once and holds the last frame (seen in the game as well, a
    winner at the clip's last frame in row 0 for as long as the screen was up).
  * Each screen loads one file and asks it for one root by name (the fighter's "demo strings": results, intro,
    ending, vi wait). `ftData_80085B98` then makes each row's clip "the root's address plus the row's start", and
    refuses a row longer than 0xB000 bytes (the buffer a demo fighter's clip is copied into is that long:
    `ftDemo_ObjAllocInit`; in a match both are 0x8000). So such a file is clips end to end behind one root, and the
    table's starts count from the root.
  * `ftData_80085CD8` copies a row's length out, reads it as an archive of exactly that length and asks it for the
    root the row's symbol names. A clip is laid on the fighter's joints by position, first on first (ftanim.c).
  * Which swing chains follow the clip is the row's own flags and the row's byte pair, as in a match
    (ftdynamics.c ftCo_8009E4A8: `fp->x594` is the playing row's flags, `fp->x28` the pairs at +0x18 for a demo
    fighter).

The donor's package carries two of those files, the results screen's and the cut scenes', made for the donor's
joints; on another skeleton they drive its first joints with turns made for other bones. `build` makes both again
from the fighter's own clips:

  * WHICH CLIP. A row is called what the donor's own symbol calls it (Win1, Win1Wait, ... Lose, Wait1) and takes
    the fighter's clip of that name, whole, frame for frame, by the rule the bank uses for an action with no job
    (`own_bank.default_jobs`: the name in lower case after the clip's three-letter start: Win1 is j02win1, Wait1 is
    a00wait1). A row the fighter has no clip of that name for holds the standing clip's first frame for the
    donor clip's own length, as the bank's does. Never the donor's clip.
  * PACKED as the bank's clips are (`own_bank.make_clip`, `own_bank.make_hold`: the rig's joints in the rig's order,
    the same tolerances, read back and measured), kept in the same cache, and held to the engine's limit for a
    demo row, 0xB000 bytes (a victory clip is long, and at the bank's 0x8000 it is thinned three times as far);
    `capacity` says otherwise.
  * THE ROOT'S TRAVEL stays in the clip, as pose: the donor's demo rows do not have the flag that hands travel
    to physics (this module sets none), and nothing follows a row that could snap the model back.
  * SWING CHAINS. The source says clip by clip how much of each swung joint is left to physics
    (`echo_ultimate.gamedata.swing.blend`); each row's flags are set from the clip it plays, the way
    `own_dynamics.apply` sets an action's. (A victory clip poses the ears by hand: every chain follows the clip.)
  * SCRIPTS. A demo row has a script like any action. The donor's (its voice, its sword's trail and gleam, its
    face's texture frames, pieces of its model shown and hidden) are made for the donor's body: every demo row
    is given a script that does nothing. The source game's own scripts for these clips are not read anywhere yet,
    so the rows are silent.
  * THE INTRO CARD AND THE ENDING. Their clips are in files the package does not hold (one shared archive each
    for every fighter: IrAls.dat, GmRegEnd.dat). m-ex asks first for a file named after the fighter's own root, so
    each is given one (`SCENES`: `shared`, `made_root`), made the same way from the donor clip's length (the
    donor's are 10 and 30 frames: poses), and `final/extra.json` says which files go on the disc as they are and
    what the package's `files` must name. Without the game's archives those rows are left pointing where they did
    and the report says what the engine does.

    pl, files, report = own_demo.build(pl, frozen, root, 'duckhunt', fighter_json['files'], donors_two_files)
    pl, report = own_demo.write(final, pl, frozen, root, 'duckhunt', donor_zip)      # and final/replace.json
"""
from __future__ import annotations

import hashlib
import json
import struct
import zipfile
from pathlib import Path

from . import own_bank, own_dynamics

ROW = 0x18                        # a row of the demo table: symbol, start, length, script, flags, a word the engine fills
ROWS = 14                         # what `ftDemo_CreateFighter` itself reaches (a few fighters have rows past these
#                                   for cut scenes of their own, asked for through a function of that fighter's)
DEMO_CAPACITY = 0xB000            # ftdata.c ftData_80085B98: a demo row longer than this is refused
CAPACITY = DEMO_CAPACITY          # what clips are held to here
END_SCRIPT = bytes(4)             # a script that does nothing (one "end of script" command)
# what a script the route gives a row may hold: waits and the fighter's own sounds (the donor's rows play sounds
# and effects on this screen too; an effect of the fighter's own needs its effect file, which is not known to be
# loaded here, so none is written)
VOICED = ('end_of_script', 'asynchronous_timer', 'synchronous_timer', 'sound_effect')

# ftdemo.c ftDemo_CreateFighter: the screens a demo fighter is made for, the rows each loads, and the fields of the
# package's `files` that name the root the screen asks for and (when the package carries it) the file it is in.
# `shared`: a screen whose clips the package does not carry: the game keeps every fighter's in one archive, under
# the root the package names. m-ex asks first for a file of the root's own name with .dat on the end (its asm,
# 1P Modes/Intro/LoadLeftAnim.asm and EndingFall/LoadAnim.asm: the root's name, the extension added, "is it on the
# disc", then the root asked of that file). So such a screen is given a file named after a NEW root (`made_root`:
# the donor is still on the roster, and a file under the donor's root's name would be the donor's too), and the
# package's entry is pointed at it (`files` in the report; `own_demo.write` lists both in final/extra.json).
# lbfile.c lbFile_80016204: a file's name is built in a buffer of 0x20 bytes, and a name longer than that stops the
# game ("Error : file name too long ftDemoIntroMotionFileZetterburn.dat", assertion in lbfile.c line 153: the
# one-player intro of a fighter called Zetterburn). With ".dat" and its end the root's own name is 27 at most.
NAME_ROOM = 0x20 - len('.dat') - 1


def made_root(scene, fighter):
    """The root (and, with .dat, the file) a scene's own file is made under: `made_root` with the fighter's name, cut
    so the file's name fits the game's buffer (`NAME_ROOM`): ftDemoIntroMotionFileZetter, ftDemoEndingMotionFileZette."""
    head = scene['made_root'].format(Fighter='')
    return head + fighter.capitalize()[:max(1, NAME_ROOM - len(head))]


SCENES = (
    dict(name='results', first=0, last=9, root='demoResult', file='rstAnimFile'),
    dict(name='intro', first=10, last=11, root='demoIntro', file='demoIntroFile', shared='IrAls.dat',
         made_root='ftDemoIntroMotionFile{Fighter}'),
    dict(name='ending', first=12, last=12, root='demoEnding', file='demoEndingFile', shared='GmRegEnd.dat',
         made_root='ftDemoEndingMotionFile{Fighter}'),
    dict(name='cut scenes', first=13, last=13, root='demoWait', file='demoFile'),
)
# the row a demo fighter starts in, by the function `ftDemo_CreateFighter` runs for the kind of screen
ENTERED = {
    0: 'the results screen: a winner, first pose (B held, or one in three); played once, its last frame held',
    2: 'the results screen: a winner, second pose (Y held, or one in three); played once, its last frame held',
    5: 'the results screen: a winner, third pose (X held, or one in three); played once, its last frame held',
    9: 'the results screen: every loser, round and round',
    10: 'the one-player intro card, the fighter on the left',
    11: 'the one-player intro card, the fighter on the right',
    12: 'the one-player ending, the fighter as a falling trophy',
    13: 'the one-player cut scenes, the fighter standing',
}
NEVER = "no code that has been read enters this row"
NOT_CARRIED = {
    'intro': "the game's shared intro archive (IrAls.dat) was not given, so no file was made for it. m-ex looks on "
             "the disc for a file named after this root with .dat on the end and, finding none, asks that archive "
             "for the root: the donor's own clip, made for the donor's joints",
    'ending': "the game's shared ending archive (GmRegEnd.dat) was not given, so no file was made for it. m-ex "
              "looks on the disc for a file named after this root with .dat on the end and, finding none, asks "
              "that archive for the root: the donor's own clip, made for the donor's joints",
}


# ---- reading ---------------------------------------------------------------------------------------------------------
def demo_rows(pl_bytes):
    """The demo table of a fighter's data: [{'index', 'symbol', 'motion', 'start', 'size', 'script', 'flags',
    'pair'}], 'motion' being the part of the symbol between _ACTION_ and _figatree. [] when the data has none."""
    from vault.echo.subactions import FighterDat, motion_from_symbol
    ft = FighterDat(bytes(pl_bytes))
    dat = ft.dat
    table, pairs = dat.ptr(ft.ft_root + 0x14), dat.ptr(ft.ft_root + 0x18)
    out = []
    for i in range((dat.struct_end(table) - table) // ROW if table is not None else 0):
        at = table + i * ROW
        name = dat.ptr(at)
        symbol = dat.cstring(name) if name is not None else None
        pair = None
        if pairs is not None and pairs + 2 * i + 1 < dat.struct_end(pairs):
            pair = (dat.buf[0x20 + pairs + 2 * i], dat.buf[0x20 + pairs + 2 * i + 1])
        out.append(dict(index=i, symbol=symbol, motion=motion_from_symbol(symbol), start=dat.u32(at + 4),
                        size=dat.u32(at + 8), script=dat.ptr(at + 0x0C), flags=dat.u32(at + 0x10), pair=pair))
    return out


def scene_of(index):
    """The screen a row belongs to (`SCENES`), or None for a row past the ones `ftDemo_CreateFighter` reaches."""
    return next((s for s in SCENES if s['first'] <= index <= s['last']), None)


def root_data(blob, root):
    """A demo file as the engine has it once loaded: (its data, where the root named `root` is in it)."""
    from vault.echo import datroot
    data, _relocations, roots, _extern = datroot.parse(blob)
    at = next((offset for offset, name in roots if name == root), None)
    if at is None:
        raise ValueError(f'the file has no root {root} (it has {[n for _, n in roots]})')
    return data, at


def cut(data, at, row):
    """A row's clip, cut from a loaded file the way `ftData_80085B98` and `ftData_80085CD8` do."""
    return bytes(data[at + row['start']:at + row['start'] + row['size']])


def holds(blob, symbol):
    """Whether these bytes are one archive whose only root is `symbol`."""
    from vault.echo import datroot
    try:
        _data, _relocations, roots, extern = datroot.parse(blob)
    except Exception:
        return False
    return [n for _, n in roots] == [symbol] and not extern


def pack_file(root, entries):
    """A demo file: the clips end to end (each starting on a 0x20 boundary, as the donor's do) behind one root.
    `entries`: (symbol, bytes) in order. -> (the file, {symbol: (its start from the root, its length)})"""
    from vault.echo import datroot
    data, spans = own_bank.assemble(entries)
    return datroot.build(data, [], [(0, root)], []), spans


# ---- which clip ------------------------------------------------------------------------------------------------------
def jobs_for(fighter, rows, stems):
    """One job a symbol for the rows that have a clip: the fighter's clip of the row's own name, whole
    (`own_bank.default_jobs`). -> ({symbol: job}, {symbol: why it has none})"""
    named = {}
    for row in rows:
        if row['symbol'] and row['size'] and row['motion']:
            named.setdefault(row['motion'], []).append(row)
    loops = {m: any(r['flags'] & own_bank.LOOPS for r in rs) for m, rs in named.items()}
    jobs, without = own_bank.default_jobs(fighter, {m: rs[0] for m, rs in named.items()}, loops, stems)
    by_motion = {j['motion']: j for j in jobs}
    return ({r['symbol']: by_motion[m] for m, rs in named.items() if m in by_motion for r in rs},
            {r['symbol']: without[m] for m, rs in named.items() if m in without for r in rs})


def swing_word(chains, shares, stem, rows):
    """What a row's flags and second pair byte should say about the swing chains under the clip `stem`.
    `shares`: what `swing.blend` gave (None when the fighter has no such file); `rows`: the rows of "joints that
    follow the clip" the fighter's data already holds. -> (flag bits, the row's number, what that is in words)"""
    if not chains or shares is None:
        return 0, 0, 'every chain swings'
    row = own_dynamics.row_for(chains, shares.get(stem, shares.get(None, {})))
    if all(v == own_dynamics.OFF for v in row):
        return own_dynamics.FOLLOW_CLIP, 0, 'every chain follows the clip'
    if not any(row):
        return 0, 0, 'every chain swings'
    if list(row) in rows:
        return own_dynamics.USE_ROW, rows.index(list(row)), f'row {rows.index(list(row))} {list(row)}'
    return 0, 0, f"every chain swings (the source's word is {list(row)}, a row the fighter's data does not hold)"


# ---- making ----------------------------------------------------------------------------------------------------------
def _settings(capacity, reducer):
    """What a made clip depends on besides its job: the bank's own numbers and the bank's code."""
    code = hashlib.sha256(Path(own_bank.__file__).read_bytes()).hexdigest()[:16]
    return dict(codec=own_bank.CODEC, code=code, budgets=own_bank.BUDGETS, turn_floor=own_bank.TURN_FLOOR,
                turn_cap=own_bank.TURN_CAP, least_reach=own_bank.LEAST_REACH, size_tolerance=own_bank.SIZE_TOLERANCE,
                grid=own_bank.GRID, eval_grid=own_bank.EVAL_GRID, error=own_bank.ERROR,
                scale_error=own_bank.SCALE_ERROR, still=own_bank.STILL, capacity=capacity,
                reducer=getattr(reducer, '__name__', 'reduce_track'))


def _cached(cache, key, make):
    """`make()` -> (bytes, row), kept under `key` in the folder `cache` when there is one. -> (bytes, row, hit)"""
    if cache and (cache / f'{key}.dat').exists() and (cache / f'{key}.json').exists():
        return (cache / f'{key}.dat').read_bytes(), json.loads((cache / f'{key}.json').read_text('utf-8')), True
    blob, row = make()
    if cache:
        (cache / f'{key}.dat').write_bytes(blob)
        (cache / f'{key}.json').write_text(json.dumps(row), 'utf-8')
    return blob, row, False


def build(pl_bytes, frozen, root, fighter, files, donor, *, cache=None, capacity=CAPACITY, log=print,
          hold=own_bank.HOLD_STEM, reducer=None, source=None, script_for=None, continuations=False):
    """A fighter's data and the donor's demo files -> (the data with its demo table repointed, the new files, a report).

    `pl_bytes`: the fighter's data as it will ship (already on the rig). `frozen`: the rig file's contents.
    `root`: the folder that holds gamedata/fighter/<fighter>. `files`: the `files` block of the donor package's
    fighter.json (the names of the demo files and of their roots). `donor`: {file name: bytes} for the demo files
    the package carries, the donor's own, and the game's shared archives a screen's `shared` names (IrAls.dat,
    GmRegEnd.dat) when they are to hand. `cache`: a folder to keep made clips in (the bank's will do).
    `script_for(line)`: the script (bytes) for a row that plays the fighter's own clip, from the row's line of
    the report (its `stem`, `frames`, `motion`), or None for a row that stays silent: the source game's sounds
    for a win pose, on its own frames. Only waits and sounds may be in it (`VOICED`).
    -> (bytes, {file name: bytes}, report). Rows of a screen whose file is not given are left as they are;
    `report['files_block']` is what the package's `files` must say for the screens given files of their own."""
    from vault.echo.subactions import FighterDat
    rows = demo_rows(pl_bytes)
    if not rows:
        raise ValueError('this fighter data has no demo actions')
    source = source or own_bank.Source(root, fighter, frozen)
    order = source.target.order
    nodes = len(order)
    engine = [order.index(j) for j in source.above]
    cache = Path(cache) if cache else None
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
    rig_hash = own_bank._key({k: frozen[k] for k in ('order', 'parent', 'rest')},
                             frozen['provenance'].get('scale_helpers'), frozen['provenance'].get('chart_helpers'))
    settings = _settings(capacity, reducer)
    if continuations:
        from . import own_demo_segments

    # the screens whose file the package carries, each row's own clip checked to be where the table says it is
    made_for, loaded, donor_sizes, block = [], {}, {}, {}
    files = dict(files)
    for scene in SCENES:
        name = files.get(scene['file']) if scene['file'] else None
        held_in = name or scene.get('shared')
        blob = next((b for n, b in donor.items() if held_in and n.lower() == held_in.lower()), None)
        if blob is None or not files.get(scene['root']):
            continue
        try:
            data, at = root_data(blob, files[scene['root']])
        except ValueError:
            if name:
                raise
            continue                                    # the game's archive has no clips under this root
        if not name:
            # a file of the fighter's own, under a root of its own (from here on `files` names both)
            root_name = made_root(scene, fighter)
            name = root_name + '.dat'
            block.update({scene['root']: root_name, scene['file']: name})
        for row in rows[scene['first']:scene['last'] + 1]:
            if row['symbol'] and row['size'] and not holds(cut(data, at, row), row['symbol']):
                raise ValueError(f"demo row {row['index']} ({row['symbol']}): {name} does not hold this clip where "
                                 "the fighter data says; give the donor's own file")
        loaded[scene['name']] = (name, data, at)
        donor_sizes[scene['name']] = len(blob)
        made_for.append(scene)
    files.update(block)
    wanted = [r for s in made_for for r in rows[s['first']:s['last'] + 1]]
    jobs, without = jobs_for(fighter, wanted, source.stems())
    # Swing, embedded visibility and sounds must agree before identical animations share a tail.
    chains = (frozen.get('swing') or {}).get('chains') or []
    shares = _shares(source) if chains else None
    swing_rows = own_dynamics.read(pl_bytes)['rows'] if chains else []
    prepared, continuation_chains = {}, []
    if continuations and any(s['name']=='results' for s in made_for):
        from . import own_opacity
        opacity = own_opacity.read(root,fighter) or {}
        def playback_key(job):
            parts = job['parts']
            if len(parts)!=1 or parts[0].get('keys') or job.get('loop'):
                return None
            stem = parts[0]['stem']
            raw = source.clip(stem)
            script = script_for(dict(stem=stem,motion=job['motion'],frames=raw.end,kind='SOURCE')) if script_for else None
            return own_bank._key(source.hash(stem),bool(job.get('loop')),
                {k:v for k,v in parts[0].items() if k!='stem'},
                opacity.get('clips',{}).get(stem),
                None if shares is None else shares.get(stem,shares.get(None,{})),
                bytes(script).hex() if script else None)
        jobs,prepared,continuation_chains = own_demo_segments.prepare(
            source,jobs,wanted,settings,rig_hash,capacity,reducer,cache,playback_key,log)

    pose, hits, out_files, spans_of = None, 0, {}, {}
    table = {r['index']: dict(index=r['index'], motion=r['motion'], symbol=r['symbol'],
                              engine=ENTERED.get(r['index'], NEVER)) for r in rows}
    for scene in made_for:
        name, data, at = loaded[scene['name']]
        entries, done = [], {}
        for row in sorted(rows[scene['first']:scene['last'] + 1], key=lambda r: r['start']):
            line = table[row['index']]
            line.update(scene=scene['name'], file=name)
            if not row['symbol'] or not row['size']:
                line.update(kind='EMPTY', why='the donor has no clip here either')
                continue
            symbol = row['symbol']
            if symbol not in done:
                donor_frames = own_bank.read_clip(cut(data, at, row))['frames']
                job = jobs.get(symbol)
                travel, why = (None, without.get(symbol, 'the fighter has no clip of this name'))
                if job is not None:
                    travel, why = own_bank.job_travel(source, job)
                if travel is None:
                    pose = pose or own_bank.hold_pose(source, hold)
                    key = own_bank._key('hold', settings, rig_hash, symbol, donor_frames, hold, source.hash(hold),
                                        source.hash(None))
                    blob, made, hit = _cached(cache, key, lambda: own_bank.make_hold(source, symbol, donor_frames,
                                                                                    pose, capacity))
                    made = dict(made, kind='HELD', why=why, stem=None, donor_frames=donor_frames)
                else:
                    keep = ''.join(a for a in 'XYZ' if a in travel)
                    key = own_bank._key('clip', settings, rig_hash, symbol, job['parts'], bool(job.get('loop')), keep,
                                        [source.hash(p['stem']) for p in job['parts']], source.hash(None))
                    if symbol in prepared:
                        blob,made,hit = prepared[symbol]
                    else:
                        blob, made, hit = _cached(cache, key, lambda: own_bank.make_clip(source, symbol, job, keep,
                                                                                        capacity, reducer))
                    made = dict(made, kind='SOURCE', stem=job['parts'][0]['stem'], donor_frames=donor_frames,
                                travel_kept=keep)
                hits += hit
                done[symbol] = made
                entries.append((symbol, blob))
                log(f"  demo {row['index']:>2} {row['motion']:<14} {made['kind']:<6} {made['stem'] or 'held':<12} "
                    f"{made['frames']:>5.0f}f {made['bytes']:>6}B  budget {made['budget']:<8} off "
                    f"{made['error']['whole']:.5f} whole, {made['error']['between']:.5f} between"
                    + (f"  (was {made['tried'][0]['bytes']}B)" if len(made['tried']) > 1 else ''))
            line.update({k: done[symbol].get(k) for k in ('kind', 'stem', 'why', 'frames', 'donor_frames', 'bytes',
                                                          'budget', 'travel_kept', 'loop_gap', 'source_first', 'source_last', 'source_motion')})
            line.update(whole=done[symbol]['error']['whole'], between=done[symbol]['error']['between'],
                        thinned=len(done[symbol]['tried']) > 1)
        out_files[name], spans_of[scene['name']] = pack_file(files[scene['root']], entries)

    # the table: each made row's start and length, its swing flags, and a script that does nothing for every row
    ft = FighterDat(bytes(pl_bytes))
    dat = ft.dat
    quiet = dat.append_struct(END_SCRIPT)
    at_table, at_pairs = dat.ptr(ft.ft_root + 0x14), dat.ptr(ft.ft_root + 0x18)
    emptied, voiced = {}, {}
    for row in rows:
        at = at_table + row['index'] * ROW
        line = table[row['index']]
        scene = scene_of(row['index'])
        if scene is None:
            line.update(scene=None, kind='LEFT', why="a row past the ones ftDemo_CreateFighter reaches: a cut scene "
                                                     "of the donor's own, asked for through the donor's function")
        elif scene not in made_for:
            line.update(scene=scene['name'], file=None, kind='DONOR', why=NOT_CARRIED.get(scene['name'],
                        'the file this screen loads was not given'), root=files.get(scene['root']))
        elif row['symbol'] in spans_of[scene['name']]:
            start, length = spans_of[scene['name']][row['symbol']]
            dat.set_u32(at + 4, start)
            dat.set_u32(at + 8, length)
            bits, which, words = swing_word(chains, shares, line.get('stem'), swing_rows)
            flags = dat.u32(at + 0x10) & ~own_dynamics.BOTH | bits
            if line.get('source_first') is not None:
                flags &= ~own_bank.LOOPS  # donor Win*Wait rows loop; a continuation must reach its boundary
            dat.set_u32(at + 0x10, flags)
            if at_pairs is not None and row['pair'] is not None:
                dat.buf[0x20 + at_pairs + 2 * row['index'] + 1] = which
            line['swing'] = words
        if row['script'] is not None:
            held = [c.key for c in ft.decode_script(row['script']).commands if c.key != 'end_of_script']
            if held:
                emptied[row['index']] = sorted(set(held))
            own = script_for(line) if script_for and line.get('kind') == 'SOURCE' else None
            if own:
                dat.set_u32(at + 0x0C, dat.append_struct(bytes(own)))
                voiced[row['index']] = line.get('stem')
            else:
                dat.set_u32(at + 0x0C, quiet)
    new_pl = dat.to_bytes()

    checked = verify(new_pl, out_files, files, nodes, engine, capacity, voiced=set(voiced))
    left = {n: dict(root=files.get(s['root']), rows=[r['index'] for r in rows[s['first']:s['last'] + 1]],
                    engine=NOT_CARRIED.get(n, 'the file this screen loads was not given'))
            for s in SCENES if s not in made_for for n in [s['name']]}
    report = dict(
        schema='own-demo-1', fighter=fighter, continuations=continuation_chains, jobs=jobs, rig_joints=nodes, capacity=capacity, engine_capacity=DEMO_CAPACITY,
        files={loaded[s['name']][0]: dict(bytes=len(out_files[loaded[s['name']][0]]), root=files[s['root']],
                                          scene=s['name'], clips=len(spans_of[s['name']]),
                                          donor_bytes=donor_sizes[s['name']]) for s in made_for},
        rows=[table[r['index']] for r in rows],
        held={l['motion']: l['why'] for l in table.values() if l.get('kind') == 'HELD'},
        thinned=[l['motion'] for l in table.values() if l.get('thinned')],
        not_carried=left, files_block=block,
        scripts=dict(emptied=emptied, voiced=voiced,
                     why="the donor's script under a demo row is made for the donor's body: every row's is taken out, "
                         "and a row the route gives a script for plays the source game's sounds for its clip"),
        swing=dict(chains=[c['joints'][0] for c in chains], source_says=None if shares is None else 'swingblend.prc'),
        cached=hits, verify=checked)
    if not checked['ok']:
        raise ValueError('the demo files do not read back: ' + '; '.join(checked['problems'][:5]))
    return new_pl, out_files, report


def _shares(source):
    """What the source says, clip by clip, of how much of each swung joint is left to physics."""
    import ssbh_data_py as ssbh
    from echo_ultimate.gamedata import swing
    bones = [b.name for b in ssbh.skel_data.read_skel(str(source.skeleton)).bones]
    return swing.blend(source.motion, bones, source.stems())


# ---- reading back ----------------------------------------------------------------------------------------------------
def verify(pl_bytes, made, files, nodes, engine=(), capacity=CAPACITY, voiced=()):
    """The written files, read the way the game will: each screen's file loaded, its root found by name, and each
    row's clip cut from "the root plus the row's start" for the row's length. Each cut must be one archive of
    exactly that length whose root is the row's symbol, a clip of `nodes` joints with no curve on the joints
    numbered in `engine`, no longer than `capacity` (and never longer than the engine's own limit); a row with no
    symbol has no start and no length; and every row's script does nothing.
    `made`: {file name: bytes}. -> {'ok', 'problems', 'rows', 'clips', 'largest'}"""
    from vault.echo.subactions import FighterDat
    rows = demo_rows(pl_bytes)
    ft = FighterDat(bytes(pl_bytes))
    problems, seen, largest = [], {}, ('', 0)
    checked = 0
    for scene in SCENES:
        name = files.get(scene['file']) if scene['file'] else None
        blob = next((b for n, b in made.items() if name and n.lower() == name.lower()), None)
        if blob is None:
            continue
        if struct.unpack_from('>I', blob)[0] != len(blob):
            problems.append(f'{name}: the file says it is {struct.unpack_from(">I", blob)[0]} bytes and is {len(blob)}')
        try:
            data, at = root_data(blob, files[scene['root']])
        except Exception as exc:
            problems.append(f'{name}: {exc}')
            continue
        for row in rows[scene['first']:scene['last'] + 1]:
            label = f"demo row {row['index']} ({row['motion']})"
            if not row['symbol']:
                if row['start'] or row['size']:
                    problems.append(f'{label}: no symbol, yet a start or a length')
                continue
            checked += 1
            start, length = row['start'], row['size']
            if start % own_bank.ALIGN or at + start + length > len(data):
                problems.append(f'{label}: {start}..{start + length} is off a 0x20 boundary or past the file')
                continue
            if length > min(capacity, DEMO_CAPACITY):
                problems.append(f'{label}: {length} bytes; the limit is {min(capacity, DEMO_CAPACITY)}')
            piece = cut(data, at, row)
            if not holds(piece, row['symbol']):
                problems.append(f"{label}: the cut is not one archive rooted {row['symbol']}")
                continue
            if struct.unpack_from('>I', piece)[0] != length:
                problems.append(f"{label}: the archive says it is {struct.unpack_from('>I', piece)[0]} bytes, the "
                                f'table {length}')
            if seen.setdefault(row['symbol'], (name, start, length)) != (name, start, length):
                problems.append(f'{label}: two rows of one symbol point at different clips')
            if length > largest[1]:
                largest = (row['motion'], length)
            if own_bank.node_count(piece) != nodes:
                problems.append(f'{label}: {own_bank.node_count(piece)} joints; the rig has {nodes}')
                continue
            clip = own_bank.read_clip(piece)
            if clip['kind'] != 1 or clip['flags'] != 0 or any(clip['counts'][i] for i in engine):
                problems.append(f"{label}: a wrong header, or a curve on one of the engine's own joints")
    for row in rows:
        if row['script'] is None:
            continue
        keys = [c.key for c in ft.decode_script(row['script']).commands]
        if row['index'] in voiced:
            if any(k not in VOICED for k in keys):
                problems.append(f"demo row {row['index']} ({row['motion']}): its script does more than wait and "
                                f"play sounds ({sorted(set(keys) - set(VOICED))})")
        elif any(k != 'end_of_script' for k in keys):
            problems.append(f"demo row {row['index']} ({row['motion']}): its script still does something")
    return dict(ok=not problems, problems=problems, rows=checked, clips=len(seen),
                largest=dict(motion=largest[0], bytes=largest[1]), rig_joints=nodes)


# ---- the route's hook ------------------------------------------------------------------------------------------------
def shared(log=print):
    """The game's own archives that hold every fighter's intro and ending clips, from the original disc the app
    keeps: {file name: bytes}; a file that cannot be had is left out (its screen then keeps the donor's clip)."""
    out = {}
    try:
        from shared.vanilla_extract import vanilla_refs
    except Exception as exc:                            # the app's reader is not here
        log(f'demo clips: the original disc is not to hand ({type(exc).__name__}); intro and ending stay the donor\'s')
        return out
    for name in sorted({s['shared'] for s in SCENES if s.get('shared')}):
        try:
            path = vanilla_refs.ensure_vanilla_ref(name)
            if path:
                out[name] = Path(path).read_bytes()
        except Exception as exc:
            log(f'demo clips: {name} could not be read from the original disc ({type(exc).__name__}: {exc})')
    return out


def write(final, pl_bytes, frozen, root, fighter, donor_zip, *, cache=None, log=print, capacity=CAPACITY,
          script_for=None, continuations=False):
    """`build` for a donor package, its files written into the folder `final`.

    The new demo files go in under the package's own names for them, and `final/replace.json` ({a file of the
    package: the file in `final` that takes its place}) is given a line for each; lines already there for other
    files stay. -> (the fighter data to write, the report)"""
    final = Path(final)
    with zipfile.ZipFile(donor_zip) as z:
        files = json.loads(z.read('fighter.json'))['files']
        names = {n.lower(): n for n in z.namelist()}
        donor = {names[files[k].lower()]: z.read(names[files[k].lower()]) for k in ('rstAnimFile', 'demoFile')
                 if files.get(k) and files[k].lower() in names}
    donor.update(shared(log))
    new_pl, made, report = build(pl_bytes, frozen, root, fighter, files, donor, cache=cache, capacity=capacity,
                                 log=log, script_for=script_for, continuations=continuations)
    listed = final / 'replace.json'
    replace = json.loads(listed.read_text('utf-8')) if listed.exists() else {}
    own = set(report['files_block'].values())
    for name, blob in made.items():
        (final / name).write_bytes(blob)
        if name not in own:
            replace[name] = name
    listed.write_text(json.dumps(replace, indent=1), 'utf-8')
    # files the package never had: each goes on the disc as it is, and the package's entry is pointed at its root
    extra = dict(files=sorted(n for n in made if n in own),
                 fighter_files={k: v for k, v in report['files_block'].items() if not k.endswith('File')})
    (final / 'extra.json').write_text(json.dumps(extra, indent=1), 'utf-8')
    report['written'] = {name: str(final / name) for name in made}
    rows = [r for r in report['rows'] if r.get('kind') in ('SOURCE', 'HELD')]
    log(f"demo clips: {sum(r['kind'] == 'SOURCE' for r in rows)} rows play the fighter's own clip, "
        f"{sum(r['kind'] == 'HELD' for r in rows)} hold a pose ({', '.join(report['held']) or 'none'}); "
        + '; '.join(f"{n} {f['bytes']:,} bytes (the donor's {f['donor_bytes']:,})" for n, f in report['files'].items())
        + f"; {len(report['scripts']['voiced'])} rows play their own sounds"
        + f"; largest clip {report['verify']['largest']['bytes']:,} of {capacity:,}; {report['cached']} from the cache; "
        f"not carried: {', '.join(report['not_carried']) or 'nothing'}")
    return new_pl, report
