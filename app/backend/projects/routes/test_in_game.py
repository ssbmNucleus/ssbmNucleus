"""
Test-in-game Blueprint -- boot a freshly-built ISO in an isolated throwaway
Dolphin, drive it to a real OFFLINE match, select the modded character/stage,
trigger effects, and report PASS / CRASH / HUNG with a screenshot.

Every test and capture is one `ingame` job (core/jobs.py, single: one Dolphin
at a time): a REST kickoff returns its id, and progress and the result are the
job record. An interactive session also streams its scoped test_progress /
test_complete / test_error events. The job owns the Dolphin it launched, so one
left open when it ends, or when Nucleus dies, is closed. All the actual driving
lives in the self-contained `ingame` engine (stdlib + Pillow, no extra
installs); this blueprint is just the HTTP/socket shell + input validation. It
NEVER goes online -- the engine aborts if it ever sees the online scene -- so it
can't disrupt the user's Slippi or waste a real player's time.
"""

import base64
import logging
import os
import shutil
import threading
from mexcli.project import MexExportCancelled  # noqa: E402  (on sys.path via core.config)
from collections import OrderedDict
from dataclasses import dataclass, field
from uuid import UUID, uuid4
from datetime import datetime
from pathlib import Path

from flask import Blueprint, request, jsonify, send_file

from core import jobs
from core.config import OUTPUT_PATH, STORAGE_PATH
from core.path_safety import resolve_under_root
from core.run_retention import prune_test_scratch
from core.state import get_socketio
from projects.install.test_inputs import _paired_nana_zip, _load_manifest, _common_inputs

logger = logging.getLogger(__name__)

test_in_game_bp = Blueprint('test_in_game', __name__)

# One test at a time: two Dolphins would fight over the screen + pipe. The
# slot is the active `ingame` job; these hold interactive sessions' state.
INGAME_KIND = 'ingame'
_test_lock = threading.Lock()
_active_test_session = None
_test_sessions = OrderedDict()
_cancelled_test_ids = OrderedDict()


def _same_file(a, b):
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except (TypeError, ValueError, OSError):
        return False


def _clean_ingame(name, value):
    """Close a Dolphin an in-game job launched and still owned when it ended or
    Nucleus died (core/jobs.py): that pid only, and only while it is still the
    recorded executable started at the recorded time. Never by image name."""
    if not name.startswith('dolphin:'):
        return None
    import psutil
    try:
        process = psutil.Process(int(value['pid']))
        exe, started = process.exe(), process.create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None  # gone, or a process that is not ours to inspect
    created = value.get('created')
    if not _same_file(exe, value.get('exe')) or (created is not None and abs(started - created) > 1.0):
        return None  # the pid was reused
    try:
        process.terminate()
        try:
            process.wait(timeout=5)
        except psutil.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    except psutil.NoSuchProcess:
        return None
    logger.warning('Closed test Dolphin %s that an in-game job left open', value['pid'])
    return 'The test Dolphin it opened was closed.'


def _automated_test_kwargs(job, publish, session):
    """run_test's keywords: a playable session's own (its stop is the panel's
    Stop), else the job's stop, which ends an automated run's waits."""
    return _interactive_test_kwargs(publish, session) or {'stop_event': job.stop_event}


def _cancel_ingame(job):
    """A Cancel from the jobs list (core/jobs.py). An interactive session stops
    as its panel's Stop does. An automated test or capture already has the
    job's stop in its Dolphin boot (it ends the lock queue, boot and menu
    waits); the test Dolphin it owns is closed too, for a wait that only
    watches the process. The runner unwinds through its own teardown and the
    job ends cancelled (_run_build_test, core/jobs.py)."""
    with _test_lock:
        session = _test_sessions.get(job.id)
    if session is not None:
        session.stop_event.set()
        return
    for name, value in (job.snapshot().get('owned') or {}).items():
        _clean_ingame(name, value)


jobs.register_kind(INGAME_KIND, label='In-game test', cleanup=_clean_ingame,
                   on_cancel=_cancel_ingame)


def _owning_dolphin(job, fn):
    """Run fn(job) with every Dolphin a boot launches owned by the job."""
    from shared.ingame import boot

    def launched(pid, exe):
        try:
            import psutil
            created = psutil.Process(pid).create_time()
        except Exception:  # noqa: BLE001 - the exe path still identifies it
            created = None
        owned = {'pid': pid, 'exe': str(exe), 'created': created}
        job.own(f'dolphin:{pid}', owned)
        if job.should_stop():   # cancelled while it was launching
            _clean_ingame(f'dolphin:{pid}', owned)

    token = boot.ON_LAUNCH.set(launched)
    try:
        return fn(job)
    finally:
        boot.ON_LAUNCH.reset(token)


def _start_ingame_job(fn, *, label, job_id=None):
    """Start fn(job) as the one `ingame` job; raises jobs.JobBusy while another
    runs, ValueError for an id an earlier job used."""
    return jobs.start(INGAME_KIND, lambda job: _owning_dolphin(job, fn),
                      label=label, job_id=job_id, single=True)


def _busy(job_id):
    return jsonify({'success': False, 'jobId': job_id,
                    'error': 'A test is already running. Please wait for it to finish.'}), 409


def _client_job_id(data):
    """The id a client chose for its job (a UUID), so it can find the job even
    if the start response is lost. None when not given; raises when invalid."""
    return str(UUID(data['jobId'])) if 'jobId' in data else None


def _test_scratch(protect_iso):
    """The runs folder, after pruning old test scratch. Called inside the job:
    a storage failure fails the job instead of holding the slot."""
    runs_root = STORAGE_PATH / 'test-runs'
    runs_root.mkdir(parents=True, exist_ok=True)
    prune_test_scratch(STORAGE_PATH, protect_iso=protect_iso)
    return runs_root


@dataclass
class _TestSession:
    id: str
    stop_event: threading.Event = field(default_factory=threading.Event)
    finished: bool = False
    sequence: int = 0
    status: dict | None = None
    last_event: dict | None = None


class _TestStopped(Exception):
    """A requested stop reached a safe boundary before Dolphin launch."""


def _emit_test(socketio, session, event, payload):
    """An interactive session's scoped event, also kept for its status."""
    with _test_lock:
        if session.finished:
            return
        session.sequence += 1
        payload = {**payload, 'sessionId': session.id, 'sequence': session.sequence,
                   'interactive': True}
        if event == 'test_progress':
            session.status = payload
        else:
            session.finished = True
        session.last_event = {'event': event, 'payload': payload}
    if socketio is not None:
        socketio.emit(event, payload)


def _test_result_payload(result):
    return {
        'success': bool(result.get('success') if result.get('interactive') else result.get('pass')),
        'interactive': bool(result.get('interactive')),
        'verdict': result.get('verdict'), 'reason': result.get('reason'),
        'checks': result.get('checks', []), 'screenshot': result.get('screenshot'),
        'drove': result.get('drove', []),
        'onlineAborted': result.get('online_aborted', False),
    }


def _interactive_test_kwargs(publish, session):
    if session is None:
        return {}

    def state_changed(state):
        phase = state.get('phase', 'loading')
        publish('test_progress', {
            **state, 'stage': phase, 'percentage': 100 if phase == 'playing' else None,
        })

    return {'interactive': True, 'stop_event': session.stop_event,
            'on_interactive_state': state_changed}


def _release_test_job(session):
    global _active_test_session
    with _test_lock:
        if session is not None and session is _active_test_session:
            _active_test_session = None


# Screenshots a test or capture took, one folder per job; records carry their
# URLs, never the image. An `ingame` record stays in memory for the session and
# goes to disk and to every GET /api/jobs, so a base64 PNG in it (one per check)
# was downloaded again on every window load and reconnect.
SHOTS_ROOT = OUTPUT_PATH / 'test-shots'
SHOTS_KEPT = 20
_DATA_URI = 'data:image/png;base64,'


def _save_shot(job_id, name, image):
    """Write one screenshot (PNG bytes or a PNG data URI) beside its job and
    return the URL the window loads it from (through backendMediaUrl)."""
    if isinstance(image, str):
        if not image.startswith(_DATA_URI):
            return image
        image = base64.b64decode(image[len(_DATA_URI):])
    folder = SHOTS_ROOT / job_id
    new = not folder.exists()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f'{name}.png').write_bytes(image)
    if new:
        _prune_shots(job_id)
    return f'/api/mex/test-in-game/shots/{job_id}/{name}.png'


def _prune_shots(current):
    """Keep the newest SHOTS_KEPT jobs' screenshots (the window shows the last)."""
    try:
        folders = sorted((p for p in SHOTS_ROOT.iterdir() if p.is_dir() and p.name != current),
                         key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for old in folders[SHOTS_KEPT - 1:]:
        shutil.rmtree(old, ignore_errors=True)


def _shots_to_files(job_id, payload):
    """A test's result payload with its screenshots written out as files."""
    out = dict(payload)
    if out.get('screenshot'):
        out['screenshot'] = _save_shot(job_id, 'shot', out['screenshot'])
    if isinstance(out.get('checks'), list):
        out['checks'] = [
            {**check, 'screenshot': _save_shot(job_id, f'check-{i}', check['screenshot'])}
            if isinstance(check, dict) and check.get('screenshot') else check
            for i, check in enumerate(out['checks'])]
    return out


@test_in_game_bp.route('/api/mex/test-in-game/shots/<job_id>/<name>', methods=['GET'])
def test_shot(job_id, name):
    """One screenshot a test or capture took (see _save_shot)."""
    try:
        path = resolve_under_root(SHOTS_ROOT, f'{job_id}/{name}', field='shot')
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    if path.suffix != '.png' or not path.is_file():
        return jsonify({'success': False, 'error': 'Screenshot not found.'}), 404
    return send_file(path, mimetype='image/png')


@test_in_game_bp.route('/api/mex/test-in-game/start', methods=['POST'])
def start_test_in_game():
    """
    Start an in-game test as the `ingame` job (see _start_build_test_job).

    Body:
    {
        "isoPath": "...",            // required: the exported ISO to test
        "slippiDolphinPath": "...",  // required: the user's Slippi Dolphin path
        "manifest": { ... },         // optional: what mods to drive (see runner)
        "manifestPath": "...",       // optional: a JSON file with the manifest
        "observeSeconds": 9,         // optional: in-game watch window per check
        "hiresTextures": false,      // optional: pre-seed + enable HD textures
        "loadSeed": "..."            // optional: a Load/Textures dir to pre-seed
    }
    """
    data = request.json or {}
    iso_path = data.get('isoPath')
    slippi_path = data.get('slippiDolphinPath')

    if not iso_path or not os.path.exists(iso_path):
        return jsonify({'success': False,
                        'error': f'ISO not found: {iso_path}'}), 400
    if not slippi_path:
        return jsonify({'success': False,
                        'error': 'slippiDolphinPath is required (set the Slippi path in Settings).'}), 400

    manifest = _load_manifest(data)
    observe_seconds = int(data.get('observeSeconds', 9) or 9)
    hires_textures = bool(data.get('hiresTextures', False))
    load_seed = data.get('loadSeed')

    return _start_build_test_job(
        iso_path, slippi_path, observe_seconds, lambda progress, log: (manifest, {}),
        remove_iso=False, runner_options={'hires_textures': hires_textures, 'load_seed': load_seed},
        build_message='Starting in-game test…',
        started='In-game test started', mode='manifest' if manifest else 'boot-health',
    )


@test_in_game_bp.route('/api/mex/test-in-game/costume', methods=['POST'])
def start_costume_test():
    """
    Test ONE character costume in game: build a minimal temp ISO (vanilla + just
    this costume), boot it, select that character + costume, play a short match,
    and report PASS / CRASH with a screenshot. Runs as the same job as /start.

    Body:
    {
        "character": "Fox",          // required: storage character (display name)
        "skinId": "<id>",            // required: storage skin id
        "colorName": "...",          // optional: for the result label
        "vanillaIsoPath": "...",     // required: the user's vanilla Melee ISO
        "slippiDolphinPath": "...",  // required: the user's Slippi Dolphin path
        "observeSeconds": 9          // optional
    }
    """
    data = request.json or {}
    character = data.get('character')
    skin_id = data.get('skinId')
    color_name = data.get('colorName') or ''
    vanilla_iso = data.get('vanillaIsoPath')
    slippi_path = data.get('slippiDolphinPath')
    observe_seconds = int(data.get('observeSeconds', 9) or 9)

    if not character or not skin_id:
        return jsonify({'success': False, 'error': 'character and skinId are required.'}), 400
    if not vanilla_iso or not os.path.exists(vanilla_iso):
        return jsonify({'success': False,
                        'error': f'Vanilla Melee ISO not found: {vanilla_iso}. Set it in Settings.'}), 400
    if not slippi_path:
        return jsonify({'success': False,
                        'error': 'slippiDolphinPath is required (set the Slippi path in Settings).'}), 400

    skin_zip = STORAGE_PATH / character / f"{skin_id}.zip"
    if not skin_zip.exists():
        return jsonify({'success': False,
                        'error': f'Costume archive not found: {skin_zip}'}), 400

    # Ice Climbers skins are a Popo/Nana PAIR of zips linked in the storage
    # metadata; importing only the selected (Popo) zip would leave Nana vanilla
    # in the test ISO. Resolve the paired Nana zip so the build installs both.
    nana_zip = _paired_nana_zip(character, skin_id)

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_iso = STORAGE_PATH / 'test-builds' / f'test_{character}_{stamp}.iso'.replace(' ', '_')

    def build(progress_cb, log):
        from projects.install.test_build import build_single_costume_iso
        index = build_single_costume_iso(
            vanilla_iso=vanilla_iso, character=character, skin_zip=str(skin_zip),
            out_iso=str(out_iso), nana_zip=nana_zip, progress_cb=progress_cb, log=log,
        )
        return ({'costume': {'fighter': character, 'colorIndex': index, 'name': color_name}},
                {'costumeIndex': index, 'character': character, 'colorName': color_name})

    return _start_build_test_job(out_iso, slippi_path, observe_seconds, build,
                                 started='Costume test started')


def _start_build_test_job(out_iso, slippi_path, observe_seconds, build_callable, *,
                          started='In-game test started', remove_iso=True, runner_options=None,
                          build_message='Building a one-mod test ISO…', **started_extra):
    """Start a build-and-test as the `ingame` job and answer the request.

    One lifecycle for builds, automated checks and cancellable manual previews.
    Refuses before anything is built while another in-game job runs or the
    user's own Dolphin is open; the engine's later guard still handles a Dolphin
    opened during the build. An interactive session's id is its job's id.
    """
    global _active_test_session
    data = request.get_json(silent=True) or {}
    interactive = data.get('interactive', False)
    if not isinstance(interactive, bool):
        return jsonify({'success': False, 'error': 'interactive must be a boolean.'}), 400
    try:
        if interactive:
            job_id = str(UUID(data['sessionId'])) if 'sessionId' in data else str(uuid4())
        else:
            job_id = _client_job_id(data)
    except (ValueError, TypeError, AttributeError):
        field_name = 'sessionId' if interactive else 'jobId'
        return jsonify({'success': False, 'error': f'{field_name} must be a UUID.'}), 400
    if interactive:
        with _test_lock:
            if job_id in _test_sessions or job_id in _cancelled_test_ids:
                return jsonify({'success': False, 'error': 'This test session already exists. Start a new session.'}), 409
    running = jobs.active_job(INGAME_KIND)
    if running is not None:
        return _busy(running.id)
    from shared.ingame.boot import dolphin_running
    if dolphin_running():
        return jsonify({
            'success': False, 'code': 'dolphin_open', 'dolphinOpen': True,
            'error': 'Close the open Slippi Dolphin or Dolphin window, then start the test again. '
                     'The in-game test needs its own Dolphin window to receive controls.',
        }), 409
    session = _TestSession(job_id) if interactive else None
    with _test_lock:
        # Stop can arrive while kickoff is still checking Dolphin processes.
        if session is not None and job_id in _cancelled_test_ids:
            return jsonify({'success': False, 'error': 'This test session was cancelled.'}), 409
        try:
            job_id = _start_ingame_job(
                lambda job: _run_build_test(
                    job, session, out_iso, slippi_path, observe_seconds, build_callable,
                    remove_iso=remove_iso, runner_options=runner_options,
                    build_message=build_message),
                label=started.removesuffix(' started'), job_id=job_id)
        except jobs.JobBusy as busy:
            return _busy(busy.job_id)
        except ValueError:  # an earlier job used this id
            if session is None:
                return jsonify({'success': False, 'error': 'jobId must be a new UUID.'}), 400
            return jsonify({'success': False, 'error': 'This test session already exists. Start a new session.'}), 409
        if session is not None:
            # Registered before the worker can emit: it waits on this lock.
            _active_test_session = session
            _test_sessions[job_id] = session
            while len(_test_sessions) > 16:
                _test_sessions.popitem(last=False)
    return jsonify({'success': True, 'message': started, 'jobId': job_id, **started_extra,
                    **({'sessionId': job_id, 'interactive': True} if session else {})})


def _run_build_test(job, session, out_iso, slippi_path, observe_seconds, build_callable, *,
                    remove_iso, runner_options, build_message):
    """The `ingame` job of a build-and-test. Returns the result payload; a
    failure fails the job. An interactive session also gets its events."""
    socketio = get_socketio()

    def publish(event, payload):
        if event == 'test_progress':
            percentage = payload.get('percentage')
            job.progress(percentage / 100 if percentage is not None else None,
                         payload.get('message'), stage=payload.get('stage'))
        if session is not None:
            _emit_test(socketio, session, event, payload)

    # The build reports 0-100 (projects.install.test_build BAR_*); it gets
    # 6-40 of the panel's bar. A plain log line keeps the bar where it is,
    # and the bar never moves backwards.
    bar = {'at': 6}

    def build_log(msg):
        publish('test_progress', {'stage': 'building', 'percentage': bar['at'], 'message': msg})

    def build_progress(percentage, message):
        bar['at'] = max(bar['at'], 6 + int(percentage * 0.34))
        publish('test_progress', {
            'stage': 'building', 'percentage': bar['at'], 'message': message})

    def test_emit(stage, percentage, message):
        publish('test_progress', {
            'stage': stage,
            'percentage': 40 + int(percentage * 0.6) if percentage is not None else None,
            'message': message})

    def stopped():
        """The panel's Stop (an interactive session) or a Cancel from the jobs list."""
        return job.should_stop() or (session is not None and session.stop_event.is_set())

    def check_stop():
        if stopped():
            raise _TestStopped()

    try:
        from shared.ingame.runner import run_test
        check_stop()
        runs_root = _test_scratch(out_iso)
        publish('test_progress', {'stage': 'building' if remove_iso else 'starting',
                                 'percentage': 3, 'message': build_message})
        # A Stop during the build kills the ISO export (projects.install.test_build
        # polls this through MexCLI); a Stop between steps is caught below.
        from projects.install import test_build as _tb
        _tok = _tb.STOP_CHECK.set(stopped)
        try:
            manifest, extra = build_callable(build_progress, build_log)
        finally:
            _tb.STOP_CHECK.reset(_tok)
        check_stop()
        result = run_test(
            iso_path=str(out_iso), slippi_path=slippi_path, runs_root=str(runs_root),
            manifest=manifest, emit=test_emit,
            log=lambda m: logger.info(f"[test-in-game] {m}"),
            observe_seconds=observe_seconds,
            **(runner_options or {}), **_automated_test_kwargs(job, publish, session),
        )
        if session is None and job.should_stop():
            # Cancel closed the test Dolphin; what the runner saw is not a verdict.
            raise _TestStopped()
        payload = _shots_to_files(job.id, {**(extra or {}), **_test_result_payload(result)})
        publish('test_complete', payload)
        logger.info(f"[test-in-game] done: verdict={result.get('verdict')}")
        return payload
    except (_TestStopped, MexExportCancelled):
        if session is None:
            raise jobs.Cancelled() from None
        payload = {'success': True, 'interactive': True,
                   'verdict': 'stopped', 'reason': 'Test stopped before Dolphin opened.'}
        publish('test_complete', payload)
        return payload
    except Exception as e:
        publish('test_error', {'success': False, 'error': str(e)})
        raise
    finally:
        if remove_iso:
            try:
                Path(out_iso).unlink(missing_ok=True)
            except OSError:
                logger.warning('Could not remove temporary test ISO %s', out_iso, exc_info=True)
        _release_test_job(session)


@test_in_game_bp.route('/api/mex/test-in-game/custom-character', methods=['POST'])
def start_custom_character_test():
    """Test ONE custom (m-ex) fighter in game: build a temp ISO with just that
    fighter (placed in the CSS grid), boot it, select it, play a short match.
    Body: { slug, name?, vanillaIsoPath, slippiDolphinPath, observeSeconds? }."""
    data = request.json or {}
    slug = data.get('slug')
    if not slug:
        return jsonify({'success': False, 'error': 'slug is required.'}), 400
    vanilla, slippi, obs, err = _common_inputs(data)
    if err:
        return jsonify({'success': False, 'error': err}), 400

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_iso = (STORAGE_PATH / 'test-builds' / f'test_char_{slug}_{stamp}.iso')

    def build(progress_cb, log):
        from projects.install.test_build import build_custom_character_iso
        r = build_custom_character_iso(vanilla, slug, str(out_iso), progress_cb=progress_cb, log=log)
        return ({'character': {'name': r['name'], 'cssIcon': r['cssIcon']}},
                {'modName': r['name'], 'cssIcon': r['cssIcon']})

    return _start_build_test_job(out_iso, slippi, obs, build, started='Custom character test started')


@test_in_game_bp.route('/api/mex/test-in-game/custom-character-skin', methods=['POST'])
def start_custom_character_skin_test():
    """Test ONE specific skin of a custom (m-ex) fighter in game: build a temp
    ISO with that fighter, import the chosen vault custom skin onto it (or pick a
    bundled costume slot), select that exact costume on the CSS, play a short
    match. Body: { slug, skinId? | costumeIndex?, colorName?, vanillaIsoPath,
    slippiDolphinPath, observeSeconds? }."""
    data = request.json or {}
    slug = data.get('slug')
    skin_id = data.get('skinId')
    costume_index = data.get('costumeIndex')
    color_name = data.get('colorName') or ''
    if not slug:
        return jsonify({'success': False, 'error': 'slug is required.'}), 400
    if not skin_id and costume_index is None:
        return jsonify({'success': False, 'error': 'skinId or costumeIndex is required.'}), 400
    vanilla, slippi, obs, err = _common_inputs(data)
    if err:
        return jsonify({'success': False, 'error': err}), 400

    skin_zip = None
    if skin_id:
        skin_zip = STORAGE_PATH / 'custom_characters' / slug / 'skins' / f'{skin_id}.zip'
        if not skin_zip.exists():
            return jsonify({'success': False,
                            'error': f'Custom skin archive not found: {skin_zip}'}), 400

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_iso = (STORAGE_PATH / 'test-builds' / f'test_charskin_{slug}_{stamp}.iso')

    def build(progress_cb, log):
        from projects.install.test_build import build_custom_character_iso
        r = build_custom_character_iso(
            vanilla, slug, str(out_iso),
            skin_zip=str(skin_zip) if skin_zip else None,
            costume_index=int(costume_index) if costume_index is not None else None,
            progress_cb=progress_cb, log=log)
        mod_name = f"{r['name']} — {color_name}" if color_name else r['name']
        return ({'character': {'name': r['name'], 'cssIcon': r['cssIcon'],
                               'colorIndex': r['colorIndex']}},
                {'modName': mod_name, 'cssIcon': r['cssIcon'],
                 'colorIndex': r['colorIndex']})

    return _start_build_test_job(out_iso, slippi, obs, build, started='Custom character skin test started')


@test_in_game_bp.route('/api/mex/test-in-game/custom-stage', methods=['POST'])
def start_custom_stage_test():
    """Test ONE custom (m-ex) stage in game: build a temp ISO with just that stage
    (placed on the SSS), boot it, select it, play a short match.
    Body: { slug, name?, vanillaIsoPath, slippiDolphinPath, observeSeconds? }."""
    data = request.json or {}
    slug = data.get('slug')
    if not slug:
        return jsonify({'success': False, 'error': 'slug is required.'}), 400
    vanilla, slippi, obs, err = _common_inputs(data)
    if err:
        return jsonify({'success': False, 'error': err}), 400

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_iso = (STORAGE_PATH / 'test-builds' / f'test_stage_{slug}_{stamp}.iso')

    def build(progress_cb, log):
        from projects.install.test_build import build_custom_stage_iso
        r = build_custom_stage_iso(vanilla, slug, str(out_iso), progress_cb=progress_cb, log=log)
        return ({'customStage': {'name': r['name'], 'sssIcon': r['sssIcon']}},
                {'modName': r['name'], 'sssIcon': r['sssIcon']})

    return _start_build_test_job(out_iso, slippi, obs, build, started='Custom stage test started')


@test_in_game_bp.route('/api/mex/test-in-game/stage-skin', methods=['POST'])
def start_stage_skin_test():
    """Test ONE stage skin (DAS variant) in game: build a temp ISO with the DAS
    framework + that skin behind a hold button, boot it, select the base stage
    holding the button, play a short match.
    Body: { stageCode, stageFolder, variantId, name?, button?, vanillaIsoPath,
    slippiDolphinPath, observeSeconds? }."""
    data = request.json or {}
    stage_code = data.get('stageCode')
    stage_folder = data.get('stageFolder')
    variant_id = data.get('variantId')
    button = (data.get('button') or 'X').upper()
    variant_name = data.get('name') or variant_id
    if not stage_code or not stage_folder or not variant_id:
        return jsonify({'success': False,
                        'error': 'stageCode, stageFolder and variantId are required.'}), 400
    vanilla, slippi, obs, err = _common_inputs(data)
    if err:
        return jsonify({'success': False, 'error': err}), 400

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_iso = (STORAGE_PATH / 'test-builds' / f'test_skin_{stage_code}_{stamp}.iso')

    interactive = data.get('interactive') is True

    def build(progress_cb, log):
        from projects.install.test_build import build_stage_skin_iso
        r = build_stage_skin_iso(vanilla, stage_code, stage_folder, variant_id, str(out_iso),
                                 button=button, progress_cb=progress_cb, log=log,
                                 **({'default_variant': True} if interactive else {}))
        return ({'das': {'stage': r['stage'], 'button': r['button'], 'defaultVariant': interactive}},
                {'modName': variant_name, 'das': r})

    return _start_build_test_job(out_iso, slippi, obs, build, started='Stage skin test started')


def _start_capture(fn, *, label, message, **extra):
    """Start a capture as the `ingame` job and answer the request. The body may
    name the job's id (`jobId`, a UUID); the result is the job's."""
    data = request.get_json(silent=True) or {}
    try:
        job_id = _start_ingame_job(fn, label=label, job_id=_client_job_id(data))
    except jobs.JobBusy as busy:
        return _busy(busy.job_id)
    except (ValueError, TypeError, AttributeError):
        return jsonify({'success': False, 'error': 'jobId must be a new UUID.'}), 400
    return jsonify({'success': True, 'message': message, 'jobId': job_id, **extra})


def _capture_progress(job):
    def emit(stage, percentage, message):
        job.progress(percentage / 100, message, stage=stage)
    return emit


def _remove_iso(out_iso):
    try:
        Path(out_iso).unlink(missing_ok=True)
    except OSError:
        logger.warning('Could not remove temporary capture ISO %s', out_iso, exc_info=True)


@test_in_game_bp.route('/api/mex/test-in-game/capture-stage-screenshot', methods=['POST'])
def start_capture_stage_screenshot():
    """Capture a clean in-game SCREENSHOT of a DAS stage variant (like a CSP for a
    stage) and save it as the variant's preview. Builds the one-skin ISO, boots it
    in the throwaway Dolphin, loads the stage ALONE (1-player, no timer) with the
    DAS button held, poses a deterministic whole-stage camera, and grabs the
    frame. The image is RETURNED (not saved) so the user can review it and choose
    whether to replace the variant's current screenshot (the frontend then saves
    via /storage/stages/update-screenshot). Runs as the `ingame` job; its result
    is { screenshot (a /shots URL), stageFolder, variantId }.
    Body: { stageCode, stageFolder, variantId, button?, vanillaIsoPath,
    slippiDolphinPath, jobId? }."""
    data = request.json or {}
    stage_code = data.get('stageCode')
    stage_folder = data.get('stageFolder')
    variant_id = data.get('variantId')
    button = (data.get('button') or 'X').upper()
    if not stage_code or not stage_folder or not variant_id:
        return jsonify({'success': False,
                        'error': 'stageCode, stageFolder and variantId are required.'}), 400
    vanilla, slippi, _obs, err = _common_inputs(data)
    if err:
        return jsonify({'success': False, 'error': err}), 400

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_iso = (STORAGE_PATH / 'test-builds' / f'cap_{stage_code}_{stamp}.iso')

    def run(job):
        emit = _capture_progress(job)
        try:
            from projects.install.test_build import build_stage_skin_iso
            from shared.ingame.capture import capture_stage
            from shared.ingame.melee_sss import INTERNAL_STAGE_ID

            runs_root = _test_scratch(out_iso)
            emit('building', 3, 'Building a one-skin test ISO…')
            r = build_stage_skin_iso(
                vanilla, stage_code, stage_folder, variant_id, str(out_iso),
                button=button,
                progress_cb=lambda p, m: emit('building', 6 + int(p * 0.30), m),
                log=lambda m: logger.info(f"[capture] {m}"))

            stage_name = r['stage']
            internal_id = INTERNAL_STAGE_ID.get(stage_name)
            res = capture_stage(
                str(out_iso), slippi, str(runs_root),
                internal_id=internal_id, hold=r['button'], framing_key=stage_name,
                emit=lambda s, p, m: emit(s, 40 + int(p * 0.6), m),
                log=lambda m: logger.info(f"[capture] {m}"), stop_event=job.stop_event)

            if not res.get('ok') or not res.get('png'):
                raise RuntimeError(res.get('reason') or 'screenshot capture failed')

            # Don't save yet -- hand the captured image back so the user can review
            # it and choose whether to replace the variant's current screenshot.
            shot = _save_shot(job.id, 'shot', res['png'])
            logger.info(f"[capture] captured {stage_folder}/{variant_id} (awaiting replace confirmation)")
            return {'screenshot': shot, 'stageFolder': stage_folder, 'variantId': variant_id}
        finally:
            _remove_iso(out_iso)

    return _start_capture(run, label='Stage screenshot capture',
                          message='Stage screenshot capture started')


@test_in_game_bp.route('/api/mex/test-in-game/capture-pause-screenshot', methods=['POST'])
def start_capture_pause_screenshot():
    """Capture a LIVE in-game screenshot of a pause screen mod. Builds a
    vanilla+mod ISO (the mod applied to GmPause.usd), boots it in the throwaway
    Dolphin, loads Battlefield alone (invisible fighter, no timer), PAUSES the
    match, and grabs the pause overlay. The shot is saved as the mod's preview
    screenshot and also returned. Runs as the `ingame` job; its result is
    { screenshot (a /shots URL), modId }.
    Body: { modId, vanillaIsoPath, slippiDolphinPath, jobId? }."""
    data = request.json or {}
    mod_id = data.get('modId')
    if not mod_id:
        return jsonify({'success': False, 'error': 'modId is required.'}), 400
    vanilla, slippi, _obs, err = _common_inputs(data)
    if err:
        return jsonify({'success': False, 'error': err}), 400

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_iso = (STORAGE_PATH / 'test-builds' / f'cap_pause_{stamp}.iso')

    def run(job):
        emit = _capture_progress(job)
        try:
            from projects.install.test_build import build_pause_mod_iso
            from shared.ingame.capture import capture_pause
            from vault.menus.pause_install import set_mod_screenshot

            runs_root = _test_scratch(out_iso)
            emit('building', 3, 'Building a test ISO with the pause mod…')
            build_pause_mod_iso(
                vanilla, mod_id, str(out_iso),
                progress_cb=lambda p, m: emit('building', 6 + int(p * 0.30), m),
                log=lambda m: logger.info(f"[capture] {m}"))

            res = capture_pause(
                str(out_iso), slippi, str(runs_root),
                emit=lambda s, p, m: emit(s, 40 + int(p * 0.6), m),
                log=lambda m: logger.info(f"[capture] {m}"), stop_event=job.stop_event)

            if not res.get('ok') or not res.get('png'):
                raise RuntimeError(res.get('reason') or 'screenshot capture failed')

            # The live pause shot IS the mod's best preview -- save it directly.
            set_mod_screenshot(mod_id, res['png'])
            shot = _save_shot(job.id, 'shot', res['png'])
            logger.info(f"[capture] captured pause screenshot for mod {mod_id}")
            return {'screenshot': shot, 'modId': mod_id}
        finally:
            _remove_iso(out_iso)

    return _start_capture(run, label='Pause screenshot capture',
                          message='Pause screenshot capture started')


@test_in_game_bp.route('/api/mex/test-in-game/window/capture-target', methods=['GET', 'POST'])
def test_window_capture_target():
    """Electron-only caller uses the normal backend token; no arbitrary PID input."""
    from shared.ingame import embed
    if request.method == 'GET':
        return jsonify({'success': True, **embed.capture_target()})
    data = request.json or {}
    try:
        result = embed.present_capture(data.get('sessionId'), data.get('hwnd'),
                                       data.get('mode'), data.get('ownerHwnd'), data.get('ownerPid'))
        return jsonify({'success': True, **result})
    except ValueError as error:
        return jsonify({'success': False, 'error': str(error)}), 400


@test_in_game_bp.route('/api/mex/test-in-game/window/position', methods=['POST'])
def position_test_window():
    """Pin the running test's Dolphin render window over the frontend's
    placeholder (shared/ingame/embed.py): borderless, always-on-top, never activated.
    Body: { x, y, width, height } in PHYSICAL screen pixels. Returns
    found=false until Dolphin's render window exists -- the frontend keeps
    polling through the build/boot phase."""
    if os.name != 'nt':
        # supported:false lets DolphinEmbedPanel show an honest "separate
        # window" state instead of waiting forever for an embed.
        return jsonify({'success': False, 'found': False, 'supported': False,
                        'error': 'Window embedding is only supported on Windows.'}), 400
    data = request.json or {}
    try:
        x, y = int(data['x']), int(data['y'])
        w, h = int(data['width']), int(data['height'])
    except (KeyError, TypeError, ValueError):
        return jsonify({'success': False, 'found': False,
                        'error': 'x, y, width and height (integers) are required.'}), 400
    from shared.ingame import embed
    return jsonify({'success': True, **embed.position(x, y, w, h)})


@test_in_game_bp.route('/api/mex/test-in-game/window/park', methods=['POST'])
def park_test_window():
    """Move the test Dolphin's render window offscreen (the placeholder is
    hidden or the panel unmounted). Best-effort; no-op when nothing is active."""
    if os.name != 'nt':
        return jsonify({'success': True, 'found': False, 'supported': False})
    from shared.ingame import embed
    return jsonify({'success': True, **embed.park()})


@test_in_game_bp.route('/api/mex/test-in-game/status', methods=['GET'])
def test_in_game_status():
    """One interactive session (`?sessionId=`), else whether any in-game job runs."""
    requested = request.args.get('sessionId')
    running = jobs.active_job(INGAME_KIND) is not None
    with _test_lock:
        session = _test_sessions.get(requested) if requested else _active_test_session
        return jsonify({
            'success': True,
            'running': bool(session and not session.finished) if requested else running,
            'sessionId': session.id if session else requested,
            'interactive': session is not None,
            'stopRequested': bool(session and session.stop_event.is_set()),
            'status': session.status if session else None,
            'lastEvent': session.last_event if session else None,
        })


@test_in_game_bp.route('/api/mex/test-in-game/stop', methods=['POST'])
def stop_test_in_game():
    data = request.get_json(silent=True) or {}
    session_id = data.get('sessionId')
    if not isinstance(session_id, str) or not session_id:
        return jsonify({'success': False, 'error': 'sessionId is required.'}), 400
    if data.get('cancelPending') is True:
        try:
            session_id = str(UUID(session_id))
        except (ValueError, TypeError, AttributeError):
            return jsonify({'success': False, 'error': 'sessionId must be a UUID.'}), 400
    with _test_lock:
        session = _test_sessions.get(session_id)
        if session is None:
            if data.get('cancelPending') is not True:
                return jsonify({'success': False, 'error': 'Test session not found.'}), 404
            # A dropped POST response is ambiguous. Remember this explicit Stop
            # even if kickoff has not arrived, without touching the active job.
            _cancelled_test_ids[session_id] = None
            while len(_cancelled_test_ids) > 256:
                _cancelled_test_ids.popitem(last=False)
            session = _TestSession(session_id)
            session.stop_event.set()
            session.finished = True
            session.sequence = 1
            session.last_event = {'event': 'test_complete', 'payload': {
                'sessionId': session_id, 'sequence': 1, 'interactive': True,
                'success': True, 'verdict': 'stopped', 'reason': 'Pending test cancelled.',
            }}
            _test_sessions[session_id] = session
            # Never evict the running session when pending requests are cancelled.
            while len(_test_sessions) > 16:
                oldest = next(key for key, value in _test_sessions.items()
                              if value is not _active_test_session)
                del _test_sessions[oldest]
        if session.finished:
            return jsonify({'success': True, 'sessionId': session_id, 'running': False})
        if session is not _active_test_session:
            return jsonify({'success': False, 'error': 'This test session is no longer active.'}), 409
        session.stop_event.set()
    return jsonify({'success': True, 'sessionId': session_id, 'running': True, 'stopRequested': True})
