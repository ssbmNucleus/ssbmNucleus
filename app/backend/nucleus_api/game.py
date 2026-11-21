"""Run a costume in the actual game and photograph it.

Offline renders show what a costume looks like posed by a Blender rig. Only the
game shows what the game does with it. This module builds a throwaway test ISO
with one costume in it, boots it in an isolated Slippi Dolphin, performs named
moves by single-frame stepping, and captures the exact frames - the same engine
the app's "Test in game" button uses.

One Dolphin runs on this machine at a time. :func:`status` says whether the slot
is free; every call here takes the same machine-wide lock and only ever stops
the process it started.

Worked example - verify a costume you just exported::

    iso = game.build_costume_iso('out/dragon-costume.zip', 'Mewtwo')
    iso['iso_path']; iso['color_index']    # the slot the costume landed in

    shots = game.capture_moves(iso['iso_path'], 'Mewtwo',
                               ['jab:1-3', 'fsmash:10', 'upb:5', 'dashattack:6', 'grab:3'],
                               color=iso['color_index'], destination='out/ingame')
    shots['images']        # one PNG per captured frame
    shots['sheet']         # all of them tiled and labelled - LOOK at this

Building the ISO takes a few minutes and booting takes about 90 seconds, so a
capture run is slow; ask for every move you need in ONE call.
"""
import json
import re
from pathlib import Path

from ._workspace import in_path, out_path

_NEWLINE = chr(10)

def _engine_moves():
    """The move names the capture engine itself accepts.

    Read from the engine, never re-typed here: a hand-copied list said 'dash'
    and 'idle', which the engine rejects (it has 'run' and 'dashattack'), so
    the documented example failed on the first real use.
    """
    from shared.ingame.moves import MOVES as engine
    return tuple(sorted(engine))


MOVES = _engine_moves()


def status():
    """Whether the machine's single Dolphin slot is free.

    Returns:
        dict: ``{'busy': bool, 'owner': str|None, 'pid': int|None}``. When it is
        busy, something else on this machine is driving Dolphin - wait rather
        than killing it.

    Example:
        >>> from nucleus_api import game
        >>> game.status()
        {'busy': False, 'owner': None, 'pid': None}
    """
    from shared.ingame import dolphin_lock
    current = dolphin_lock.status() or {}
    owner = current.get('owner') or {}
    return {'busy': bool(current.get('locked')), 'owner': owner.get('purpose'),
            'pid': owner.get('pid')}


def vanilla_iso():
    """The clean Melee ISO this install builds test ISOs from.

    Returns:
        str | None: its path, or None when no ISO has been configured.

    Example:
        >>> game.vanilla_iso()
        'C:/Users/.../Super Smash Bros. Melee (USA) (En,Ja) (v1.02).iso'
    """
    from core import config
    record = config.STORAGE_PATH.resolve() / 'vanilla_iso.json'
    if not record.is_file():
        return None
    try:
        path = json.loads(record.read_text(encoding='utf-8')).get('path')
    except (OSError, ValueError):
        return None
    return path if path and Path(path).is_file() else None


def build_costume_iso(costume_zip, character, destination=None, nana_zip=None):
    """Build a throwaway ISO containing exactly one extra costume.

    A fresh m-ex project is made from the clean ISO, the costume is imported as
    a new colour slot, and the project is exported. Nothing in the vault or in
    any existing build is touched.

    Args:
        costume_zip: workspace path to a costume .zip.
        character: the fighter the costume belongs to, e.g. 'Mewtwo'.
        destination: workspace .iso path. Defaults to ``out/test.iso``.
        nana_zip: the paired Nana archive, for an Ice Climbers costume.

    Returns:
        dict: ``{'iso_path': str, 'color_index': int, 'character': str,
        'next': str}``. ``color_index`` is the costume slot to pass to
        :func:`capture_moves`.

    Example:
        >>> game.build_costume_iso('out/dragon-costume.zip', 'Mewtwo')
        {'iso_path': 'C:/.../out/test.iso', 'color_index': 4, ...}
    """
    from projects.install.test_build import build_single_costume_iso
    source = in_path(costume_zip)
    clean = vanilla_iso()
    if not clean:
        raise ValueError('No clean Melee ISO is configured in this Nucleus install, '
                         'so a test ISO cannot be built.')
    target = out_path(destination, default_name='test.iso')
    index = build_single_costume_iso(clean, character, str(source), str(target),
                                     nana_zip=str(in_path(nana_zip)) if nana_zip else None)
    if not target.is_file() or not target.stat().st_size:
        raise ValueError('The build produced no ISO.')
    return {'iso_path': str(target), 'color_index': int(index), 'character': character,
            'next': ('capture_moves(iso_path, character, [moves], color=color_index) '
                     'boots this ISO and photographs the costume performing them.')}


def _shot_specs(moves):
    specs = []
    for entry in moves or []:
        text = str(entry).strip()
        name, _, frames = text.partition(':')
        if name not in MOVES:
            raise ValueError(f'Unknown move {name!r}. Choose from: {", ".join(MOVES)}.')
        if frames and not re.fullmatch(r'[0-9,\-]+', frames):
            raise ValueError("Frames look like '1-8' or '1,5,9'.")
        specs.append(f'{name}:{frames}' if frames else f'{name}:1')
    if not specs:
        raise ValueError('Name at least one move to capture.')
    return specs


def capture_moves(iso_path, character, moves, color=0, destination='out/ingame',
                  stage='finaldestination', closeup=True, timeout=1800):
    """Boot an ISO, perform moves frame by frame and photograph exact frames.

    The match is solo (no CPU, no menu cursor): the player block is written
    straight to game RAM. Each move is executed by single-frame stepping, so
    frame 1 really is the move's first frame.

    Args:
        iso_path: workspace path to the ISO, from :func:`build_costume_iso`.
        character: fighter name, e.g. 'Mewtwo'.
        moves: list of ``'move'`` or ``'move:frames'`` strings, e.g.
            ``['jab:1-3', 'fsmash:10', 'upb:5', 'dashattack:6', 'grab:3']``.
            :data:`MOVES` is the exact set the engine accepts - note that
            running is ``'run'`` and the dash attack is ``'dashattack'``; there
            is no ``'dash'``.
        color: costume slot to wear - the ``color_index`` from the build.
        destination: workspace folder for the PNGs.
        stage: stage name, default 'finaldestination'.
        closeup: park the camera on the fighter before every capture.
        timeout: seconds to allow the whole run (a boot alone costs ~90 s).

    Returns:
        dict: ``{'images': [png path, ...], 'sheet': png path, 'log': str,
        'next': str}``. ``sheet`` tiles every capture with its move and frame
        written on - open that first.

    Example:
        >>> game.capture_moves('out/test.iso', 'Mewtwo', ['jab:1-3'], color=4)
        {'images': ['C:/.../out/ingame/mewtwo-jab-f01.png', ...], 'sheet': '...'}
    """
    current = status()
    if current['busy']:
        raise ValueError(f"Dolphin is already running on this machine (pid {current['pid']}, "
                         f"{current['owner']}). Wait for it instead of starting another.")
    source = in_path(iso_path)
    folder = out_path(destination, make_parents=False)
    folder.mkdir(parents=True, exist_ok=True)
    # IN-PROCESS. This used to spawn a second interpreter running the capture
    # engine as a script. In a packaged build the interpreter path is the
    # PyInstaller bootloader rather than a Python that can run a script, and
    # the developer tools folder is not shipped at all, so that worked in a
    # checkout and failed on every user's PC -- the same shape of defect as the
    # parts-table miss. Running the capture here also keeps the machine-wide
    # Dolphin lock with ONE pid across the whole run.
    argv = ['--iso', str(source),
            '--char', str(character).lower().replace(' ', '').replace('.', ''),
            '--color', str(int(color)), '--stage', stage, '--out', str(folder)]
    if closeup:
        argv += ['--closeup', '--plain-bg']
    for spec in _shot_specs(moves):
        argv += ['--shot', spec]
    lines = []
    images, failure = _capture_in_process(argv, folder, lines, timeout)
    log = _NEWLINE.join(lines)[-6000:]
    if failure and not images:
        raise ValueError('The in-game capture produced nothing: '
                         + f'{failure}. Log tail: ' + log[-1500:])
    sheet = _sheet(images, folder / 'contact-sheet.png') if images else None
    return {'images': images, 'sheet': sheet, 'log': log,
            'next': 'Open the sheet and say what the costume actually does in each pose.'}


def _capture_in_process(argv, folder, lines, timeout):
    """Run the capture engine here, under a wall-clock ceiling.

    Returns (image paths, failure reason|None). The worker is a daemon thread
    so a ceiling breach stops this call returning nothing forever; the capture
    engine tears its own emulator down through its retained child handle.
    """
    import threading
    from devtools import frameshot as fs

    def log(message):
        lines.append(str(message))

    result = {}

    def work():
        try:
            args = fs.build_parser().parse_args(argv)
            targets = [fs.make_target(args.char, args.color,
                                      fs.parse_shots(args))]
            rows, _boots, _kept = fs.run_targets(
                args, Path(args.iso).resolve(), targets, folder, True, None)
            result['rows'] = rows
        except BaseException as exc:                  # noqa: BLE001
            result['error'] = f'{type(exc).__name__}: {exc}'

    previous, fs.log = fs.log, log
    try:
        worker = threading.Thread(target=work, name='capture-moves', daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            result['error'] = f'the capture run exceeded {timeout}s'
    finally:
        fs.log = previous
    images = sorted(str(p) for p in folder.rglob('*.png'))
    failure = result.get('error')
    if failure is None:
        broken = [r for r in (result.get('rows') or []) if r.get('status') != 'ok']
        if broken:
            failure = '; '.join(f"{r['id']}: {r['status']} {r.get('reason', '')}"
                                for r in broken)
    return images, failure


def _sheet(images, target, columns=4, cell=320):
    """Tile captures into one labelled image, so every pose is looked at together."""
    from PIL import Image, ImageDraw
    tiles = [p for p in images if Path(p).name != 'contact-sheet.png']
    if not tiles:
        return None
    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new('RGB', (columns * cell, rows * (cell + 18)), (18, 24, 34))
    draw = ImageDraw.Draw(sheet)
    for position, path in enumerate(tiles):
        x, y = (position % columns) * cell, (position // columns) * (cell + 18)
        try:
            with Image.open(path) as tile:
                tile = tile.convert('RGB')
                tile.thumbnail((cell - 8, cell - 8))
                sheet.paste(tile, (x + 4, y + 4 + (cell - 8 - tile.height) // 2))
        except OSError:
            draw.text((x + 6, y + 6), 'unreadable', fill=(200, 120, 120))
        draw.text((x + 6, y + cell + 2), Path(path).stem[:44], fill=(140, 200, 255))
    sheet.save(target, format='PNG')
    return str(target)


def verify_costume(candidate_file, character, destination='out/verification',
                   profile='costume_verification_v1', lock_wait=0, timeout=None,
                   use_cache=True, keep_iso=False):
    """Run a costume in the game under a fixed capture profile and MEASURE it.

    This is the metered verification path, not the free-form one above. It
    builds a private verification package from the candidate's exact bytes,
    boots the isolated emulator, reads back from RAM which fighter and which
    costume slot the match actually loaded, captures the profile's frames with a
    camera fixed in advance, and measures every frame.

    It never turns a completed capture run into a pass. A measurement that could
    not be taken is ``unknown``; a profile entry the engine does not support
    makes the profile incomplete and is recorded.

    Args:
        candidate_file: workspace path to the costume .zip to verify.
        character: the fighter it belongs to, e.g. 'Mewtwo'.
        destination: workspace folder for the captures, sheet and manifest.
        profile: capture-profile version. 'costume_verification_v1' captures
            idle, run frames 5 and 15, jab 1-3, forward smash 10, up-B 5, dash
            attack 6 and grab 3.
        lock_wait: seconds to queue for the machine's single Dolphin slot. 0
            means report a busy Dolphin and leave it alone.
        timeout: watchdog, in seconds, over the whole boot-and-capture phase.
            The default is :data:`shared.ingame.verify_costume.WATCHDOG_SECONDS`; when
            it expires the emulator this run started is stopped and the outcome
            is 'failed' with reason 'timeout'.
        use_cache: skip the run when the same bytes were verified under the same
            profile, engine and toolchain, and the stored evidence still hashes.

    Returns:
        dict: ``{'outcome': 'verified'|'incomplete'|'unknown'|'failed',
        'reasons': [...], 'manifest': str, 'sheet': str|None, 'timing': {...},
        'game_verification': {...}}``. ``game_verification`` is the review
        record's field; ``manifest`` is the JSON written beside the captures.

    Example:
        >>> game.verify_costume('out/dragon-costume.zip', 'Mewtwo')
        {'outcome': 'failed', 'reasons': ['...run-f05.png: the actor is clipped...']}
    """
    from shared.ingame import verify_costume as verifier
    source = in_path(candidate_file)
    folder = out_path(destination, make_parents=False)
    folder.mkdir(parents=True, exist_ok=True)
    manifest = verifier.verify(str(source), character, destination=str(folder),
                               profile=profile, lock_wait=float(lock_wait or 0),
                               timeout=verifier.WATCHDOG_SECONDS if timeout is None
                               else float(timeout), use_cache=bool(use_cache),
                               keep_iso=bool(keep_iso))
    record = manifest['game_verification']
    return {'outcome': record['outcome'], 'reasons': manifest['outcome_reasons'],
            'manifest': str(folder / 'verification.json'),
            'sheet': manifest.get('contact_sheet'),
            'timing': record['timing'],
            'limitations': manifest['limitations'],
            'game_verification': record,
            'next': 'Open the sheet and read the manifest.'}


def verification_self_consistency(manifest, character=None):
    """Reasons this manifest is not usable as evidence about anything. -> list.

    Args:
        manifest: a verification manifest.
        character: the fighter the costume targets, when known.

    Returns:
        list[str]: empty when the manifest is internally consistent.

    Example:
        >>> game.verification_self_consistency(result)
        []
    """
    record = (manifest or {}).get('game_verification') or {}
    problems = []
    if (manifest or {}).get('schema') != 'game-verification-v1':
        problems.append('this is not a game-verification manifest')
        return problems
    if not str(record.get('candidate_hash') or '').startswith('sha256:'):
        problems.append('the manifest names no candidate hash')
    checks = ((manifest.get('execution_evidence') or {}).get('checks') or [])
    statuses = {c.get('status') for c in checks}
    statuses |= {a.get('status') for a in (manifest.get('appearance_checks') or [])}
    outcome = record.get('outcome')
    if outcome == 'verified' and statuses - {'pass'}:
        problems.append('the manifest says "verified" while its own checks are '
                        + ', '.join(sorted(s for s in statuses if s != 'pass')))
    if outcome in {'incomplete', None}:
        problems.append(f'the run did not finish (outcome {outcome!r}), so it is '
                        'not evidence about these bytes')
    run_character = (manifest.get('run') or {}).get('character')
    if character and run_character and str(run_character).lower() != str(character).lower():
        problems.append(f'these captures are of {run_character}, not {character}')
    if not (record.get('iso_identity') or {}).get('insertion_verified'):
        problems.append("the candidate's own bytes were not confirmed on the "
                        "built disc, so the captures are not attributable to them")
    return problems


def verification_profile(profile='costume_verification_v1'):
    """What a capture profile asks for, resolved against the engine's move catalog.

    Args:
        profile: the profile version.

    Returns:
        dict: entries with ``status`` 'supported' or 'unsupported', the expected
        captures, and ``complete``. An unsupported entry is never dropped.

    Example:
        >>> game.verification_profile()['complete']
        True
    """
    from shared.ingame import verify_costume as verifier
    return verifier.resolve_profile(profile)


def read_captures(destination='out/ingame'):
    """The per-capture sidecars a run wrote: action state, animation frame, position.

    Args:
        destination: the workspace folder a :func:`capture_moves` run wrote to.

    Returns:
        list[dict]: one entry per move, as the capture engine recorded it.

    Example:
        >>> game.read_captures('out/ingame')[0]['file']
        'C:/.../workspace/out/ingame/mewtwo-jab.json'
    """
    folder = out_path(destination, make_parents=False)
    rows = []
    for path in sorted(folder.rglob('*.json')):
        try:
            rows.append({'file': str(path), **json.loads(path.read_text(encoding='utf-8'))})
        except (OSError, ValueError):
            continue
    return rows
