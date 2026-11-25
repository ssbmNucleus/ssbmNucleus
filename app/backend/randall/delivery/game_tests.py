"""Chat-owned manual play sessions over the existing single-mod test engine.

Only exact vault IDs or immutable costume handles reach the builders. App paths
and the Flask application are request-owned and never enter model context.
"""
import json
import re
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path

import file_retry
from core import config
from core.metadata import load_metadata
from shared import mod_files

_lock = threading.RLock()


def settings(value):
    """The in-game test's two paths, each empty or a path on this computer (core/path_safety.local_path): an
    ISO or Dolphin folder named as a share or an NT-namespace path (\\??\\UNC\\host\\...) is refused before
    anything opens it. Raises ValueError (NotLocalPath is one)."""
    from core.path_safety import local_path
    value = {} if value is None else value
    if not isinstance(value, dict) or set(value) - {'vanillaIsoPath', 'slippiDolphinPath'}:
        raise ValueError('Invalid in-game test settings.')
    if any(not isinstance(v, str) or len(v) > 4096 or '\x00' in v for v in value.values()):
        raise ValueError('Invalid in-game test path.')
    return {key: local_path(v, field=key) if v.strip() else v for key, v in value.items()}


def _record_path(session_id):
    try:
        if str(uuid.UUID(session_id)) != session_id:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Use the exact game session ID from a test receipt.')
    return config.STORAGE_PATH / 'assistant' / 'game-tests' / f'{session_id}.json'


def _save(record):
    path = _record_path(record['session_id'])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(record), encoding='utf-8')
    file_retry.replace(temporary, path)


def _load(chat_id, session_id):
    try:
        record = json.loads(_record_path(session_id).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ValueError('Game session not found in this conversation.')
    if record['chat_id'] != chat_id:
        raise ValueError('This game session belongs to another conversation.')
    return record


# The functions below import projects.routes.test_in_game and call its route
# handlers in-process through _invoke, on purpose: the one-Dolphin session state
# and the claim rules live in those handlers, so a chat-owned session goes
# through exactly what the Test in Game buttons do instead of a second copy of
# that logic. This is the one deliberate route import outside a blueprint's own
# halves; keep it to these fixed handlers.
def _invoke(app, fn, body=None, query=None):
    # Fixed internal handlers, never a model-supplied route. The caller already
    # passed normal assistant API authentication and the assistant feature gate.
    with app.test_request_context(json=body or {}, query_string=query or {}):
        response = app.make_response(fn())
        data = response.get_json()
        if response.status_code >= 400:
            raise ValueError(data.get('error', 'The in-game session could not start.'))
        return data


def has_active_session(app, chat_id):
    from projects.routes import test_in_game as test  # in-process handler call: see _invoke
    with _lock:
        live = _invoke(app, test.test_in_game_status)
        if live['running'] and live.get('sessionId'):
            try:
                _load(chat_id, live['sessionId'])
                return True
            except ValueError:
                pass
        return False


def snapshot(app, chat_id, session_id, stop=False):
    from projects.routes import test_in_game as test  # in-process handler call: see _invoke
    with _lock:
        record = _load(chat_id, session_id)
        if stop and not record.get('terminal'):
            _invoke(app, test.stop_test_in_game, {'sessionId': session_id, 'cancelPending': True})
        live = _invoke(app, test.test_in_game_status, query={'sessionId': session_id})
        if not live['running']:
            terminal = live.get('lastEvent') or record.get('terminal') or {
                'event': 'test_error', 'payload': {'error': 'This game session is no longer available. Start a new test.'}}
            record['terminal'] = terminal
            _save(record)
            live['lastEvent'] = terminal
        capture = None
        capture_supported = True
        # A stale card must never capture the next session's Dolphin window.
        with test._test_lock:
            if live['running'] and test._active_test_session and test._active_test_session.id == session_id:
                from shared.ingame import embed
                target = embed.capture_target()
                capture = target.get('sessionId')
                capture_supported = target.get('supported', True)
        return {'session_id': session_id, 'label': record['label'], 'running': live['running'],
                'status': live.get('status'), 'lastEvent': live.get('lastEvent'),
                'stopRequested': live.get('stopRequested', False), 'capture_session_id': capture,
                'capture_supported': capture_supported,
                'note': _play_note(live, capture_supported)}


def _play_note(live, capture_supported=True):
    """What the model may tell the user about a play session, said for its state: where it opens, the controller
    port, what Stop does, and never "it is running" while it is still being built (2026-10-06 take4: the reply right
    after start has to say what happens next without claiming the game is up)."""
    tail = ' Ending it is not an automated gameplay pass.'
    if not live.get('running'):
        return 'Interactive play session, ended.' + tail
    where = ('in the panel on the right' if capture_supported
             else 'in its own game window')
    if ((live.get('status') or {}).get('stage') or '') == 'playing':
        return (f'Interactive play session, live {where}: it went straight into a match, and they play on '
                'controller port 1 until they press Stop.' + tail)
    return (f'Interactive play session, still getting ready: it opens {where} and goes straight into a match '
            '(nothing to pick), they play on controller port 1, and Stop ends it. It is not running yet, so do '
            'not say it is.' + tail)


def _component(value):
    if not isinstance(value, str) or not value or len(value) > 160 or any(c in value for c in '/\\\x00:') or value in {'.', '..'}:
        raise ValueError('Choose an exact vault ID or character name.')
    return value


def _target(kind, character=None, skin_id=None, slug=None, file_id=None, stage_code=None, variant_id=None, costume_index=None):
    from projects.routes import test_in_game as test  # in-process handler call: see _invoke
    from randall.assistant.vault_items import _skin
    data = load_metadata(default={})
    if costume_index is not None and (kind != 'custom_character' or type(costume_index) is not int or not 0 <= costume_index <= 255):
        raise ValueError('Use a zero-based costume_index only for a custom character.')
    if (stage_code or variant_id) and kind != 'stage_skin':
        raise ValueError('Stage selections require kind=stage_skin.')
    if kind == 'costume' and character and skin_id and not (slug or file_id):
        character, skin = _skin(data, _component(character), _component(skin_id))
        return test.start_costume_test, {'character': character, 'skinId': skin_id,
            'colorName': skin.get('name') or skin_id}, f"{character} — {skin.get('name') or skin_id}"
    if kind in {'custom_character', 'custom_stage'} and slug and not (character or skin_id or file_id):
        _component(slug)
        collection = 'custom_characters' if kind == 'custom_character' else 'custom_stages'
        item = next((x for x in data.get(collection, []) if x.get('slug') == slug), None)
        if not item:
            raise ValueError('Target not found. Use list before choosing an exact slug.')
        fn = test.start_custom_character_test if kind == 'custom_character' else test.start_custom_stage_test
        if costume_index is not None:
            return test.start_custom_character_skin_test, {'slug': slug, 'costumeIndex': costume_index}, f"{item.get('name') or slug} — costume {costume_index + 1}"
        return fn, {'slug': slug}, item.get('name') or slug
    if kind == 'stage_skin' and stage_code and variant_id and not (character or skin_id or slug or file_id):
        from core.stages import STAGES_BY_CODE, LEGAL_STAGE_CODES
        if stage_code not in LEGAL_STAGE_CODES:
            raise ValueError('In-game stage-skin tests support the six DAS stages.')
        stage = STAGES_BY_CODE[stage_code]
        variant_id = _component(variant_id)
        stage_info = data.get('stages', {}).get(stage['folder'], {})
        variant = next((v for v in stage_info.get('variants', []) if v.get('id') == variant_id), None)
        if not variant or not (config.STORAGE_PATH / 'das' / stage['folder'] / f'{variant_id}.zip').is_file():
            raise ValueError('Saved stage variant not found. Save the Stage Lab copy first.')
        label = variant.get('name') or variant_id
        return test.start_stage_skin_test, {'stageCode': stage_code, 'stageFolder': stage['folder'], 'variantId': variant_id, 'name': label}, label
    if kind == 'file' and file_id and not (character or skin_id or slug):
        path, info = mod_files.resolve(file_id)
        origin = mod_files.origin_of(info)
        from core.constants import CHAR_PREFIXES
        character, code = origin.get('character'), origin.get('costume_code')
        if (info['extension'] not in {'.dat', '.usd'} or character not in CHAR_PREFIXES
                or not isinstance(code, str) or not re.fullmatch(r'Pl' + re.escape(CHAR_PREFIXES[character]) + r'[A-Za-z0-9]{2}', code)):
            raise ValueError('Use an exported costume file with a known target fighter. Fit/export the model first.')
        if origin.get('paired') or character in {'Ice Climbers', 'Nana'}:
            raise ValueError('Test paired costumes together from the saved vault pair.')
        mod_files.dat_roots(path)
        return None, {'file_id': file_id, 'character': character, 'costume_code': code}, info['name']
    raise ValueError('Choose one target: costume (character + skin_id), file (file_id), or custom_character/custom_stage (slug).')


def _start_file(app, body, file_id, character, costume_code):
    from projects.routes import test_in_game as test  # in-process handler call: see _invoke
    with app.test_request_context(json=body):
        out_iso = config.STORAGE_PATH / 'test-builds' / f"chat-{body['sessionId']}.iso"

        def build(progress_cb, log):
            from projects.install.test_build import build_single_costume_iso
            path, info = mod_files.resolve(file_id)  # Recheck exact bytes at execution.
            with tempfile.TemporaryDirectory(prefix='game-test-', dir=mod_files.root()) as scratch:
                archive = Path(scratch) / 'costume.zip'
                with zipfile.ZipFile(archive, 'w') as output:
                    output.writestr(costume_code + info['extension'], path.read_bytes())
                index = build_single_costume_iso(body['vanillaIsoPath'], character, archive, out_iso,
                                                progress_cb=progress_cb, log=log)
            return {'costume': {'fighter': character, 'colorIndex': index, 'name': info['name']}}, {}

        response = app.make_response(
            test._start_build_test_job(out_iso, body['slippiDolphinPath'], 9, build))
        if response.status_code >= 400:
            raise ValueError(response.get_json()['error'])


def _verify_archive(file_id, folder):
    """The exact working-copy bytes, packaged DETERMINISTICALLY for verification.

    Re-resolved at execution time, exactly as the interactive path does: a
    verification of bytes other than the ones the caller named is worse than no
    verification at all.

    The archive is built with a fixed timestamp and no compression, so the same
    DAT always produces the same package hash. A default `writestr` stamps the
    current time into the zip, which made every invocation a different
    "candidate" and defeated the cache it was supposed to hit.
    """
    path, info = mod_files.resolve(file_id)
    origin = info.get('origin') or {}
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / 'candidate.zip'
    entry = zipfile.ZipInfo(origin['costume_code'] + info['extension'],
                            date_time=(1980, 1, 1, 0, 0, 0))
    entry.compress_type = zipfile.ZIP_STORED
    entry.external_attr = 0o644 << 16
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr(entry, path.read_bytes())
    return archive, info


# Automated verification runs, by id. Each one owns a worker thread and a
# cancellation event; Stop routes straight to that event rather than to the
# interactive session lock, which has nothing to do with it.
_verifications = {}


def _verification_dir(verification_id):
    return config.STORAGE_PATH / 'assistant' / 'verifications' / verification_id


def _verification_summary(record):
    """What the model is told. No app paths, no Dolphin path, no storage root."""
    out = {'verification_id': record['verification_id'], 'label': record['label'],
           'character': record['character'], 'profile_version': record['profile'],
           'state': record['state'], 'outcome': record.get('outcome'),
           'note': ('Measured in-game verification. Only outcome="verified" '
                    'means the profile was captured and every measurement '
                    'passed; "unknown" means a required measurement could not '
                    'be taken, which is not a pass.')}
    manifest = record.get('manifest')
    if not manifest:
        out['progress'] = record.get('progress')
        if record.get('error'):
            out['error'] = record['error']
        return out
    inner = manifest['game_verification']
    captured = [c for c in inner['captures'] if c.get('path')]
    out.update({
        'candidate_hash': inner['candidate_hash'],
        'costume_slot': inner['costume_slot'],
        'outcome': inner['outcome'],
        'reasons': manifest['outcome_reasons'][:12],
        'limitations': manifest['limitations'][:12],
        'execution_evidence': manifest['execution_evidence']['status'],
        'checks': [{'check_id': c['check_id'], 'status': c['status'],
                    'reason': c['reason']}
                   for c in manifest['execution_evidence']['checks']],
        'appearance_checks': [{'move': a['move'], 'frame': a['frame'],
                               'status': a['status'], 'reason': a['reason']}
                              for a in manifest['appearance_checks']],
        'frames_captured': len(captured),
        'frames_requested': len(inner['captures']),
        'timing': inner['timing'],
        'insertion_verified': (inner['iso_identity'] or {}).get('insertion_verified'),
    })
    return out


def verify(app, chat_id, kind=None, character=None, skin_id=None, file_id=None,
           profile='costume_verification_v1', timeout=None, wait=0.0):
    """Start an automated in-game verification of one costume. Returns at once.

    This is NOT the interactive play session: nothing is handed to a controller
    and no play card is opened. The coordinator takes the machine's single
    Dolphin slot, builds a private verification package from these exact bytes,
    boots the isolated emulator, reads back from RAM which fighter and which
    costume slot actually loaded, captures the profile's frames with a camera
    fixed in advance, and measures them.

    It runs on its own worker so the tool call does not block for minutes, and
    it carries a cancellation event that `action='stop'` routes straight to. A
    busy Dolphin is reported and left alone. Completing the capture run is not
    a pass, and a measurement that could not be taken is `unknown`.
    """
    from projects.routes import test_in_game as test  # in-process handler call: see _invoke
    from shared.ingame import verify_costume as verifier
    if kind != 'file' or not file_id or character or skin_id:
        raise ValueError('Automated verification takes kind=file with an exported '
                         'costume file_id. Fit/export the model first.')
    _, target, label = _target('file', file_id=file_id)
    with _lock:
        # The interactive slot and the verification slot are the same machine.
        live = _invoke(app, test.test_in_game_status)
        if live['running']:
            raise ValueError('An in-game session is already running on this machine. '
                             'Stop it before starting an automated verification.')
        for other in _verifications.values():
            if other['chat_id'] == chat_id and other['state'] == 'running':
                return _verification_summary(other)
        verification_id = str(uuid.uuid4())
        folder = _verification_dir(verification_id)
        folder.mkdir(parents=True, exist_ok=True)
        archive, info = _verify_archive(file_id, folder / 'input')
        record = {'verification_id': verification_id, 'chat_id': chat_id,
                  'label': label, 'character': target['character'],
                  'profile': profile, 'state': 'running', 'outcome': None,
                  'progress': 'building the verification package',
                  'stop': threading.Event(), 'manifest': None, 'error': None}
        _verifications[verification_id] = record

    def run():
        try:
            record['manifest'] = verifier.verify(
                str(archive), target['character'], destination=str(folder),
                profile=profile, lock_wait=0.0, label=info['name'],
                stop_event=record['stop'],
                timeout=verifier.WATCHDOG_SECONDS if timeout is None
                else float(timeout),
                log=lambda message: record.update(progress=str(message)[:200]))
            record['outcome'] = record['manifest']['game_verification']['outcome']
            record['state'] = 'completed'
        except Exception as exc:
            record['error'] = f'{type(exc).__name__}: {exc}'
            record['state'] = 'failed'
        finally:
            record['stop'].set()

    worker = threading.Thread(target=run, name=f'verify-{verification_id[:8]}',
                              daemon=True)
    record['thread'] = worker
    worker.start()
    if wait:
        worker.join(float(wait))
    return _verification_summary(record)


def verification_status(chat_id, verification_id, stop=False):
    """Inspect, or cancel, ONE automated verification owned by this conversation.

    Cancelling sets that run's own event; the coordinator closes the emulator
    instance it started and nothing else on the machine is touched.
    """
    record = _verifications.get(str(verification_id))
    if record is None or record['chat_id'] != chat_id:
        raise ValueError('Verification not found in this conversation.')
    if stop and record['state'] == 'running':
        record['stop'].set()
        record['progress'] = 'cancelling: stopping the emulator this run started'
        thread = record.get('thread')
        if thread is not None:
            thread.join(30)
    return _verification_summary(record)


def test_in_game(action, kind=None, character=None, skin_id=None, slug=None, file_id=None,
                 session_id=None, query='', stage_code=None, variant_id=None, costume_index=None,
                 *, runtime=None, chat_id=None):
    if not runtime or not runtime.get('app') or not chat_id:
        raise ValueError('In-game testing requires the running Nucleus chat.')
    app = runtime['app']
    if action == 'list':
        if not isinstance(query, str) or len(query) > 160:
            raise ValueError('Use a short search query.')
        data = load_metadata(default={})
        items = [{'kind': kind, 'slug': item['slug'], 'name': item.get('name') or item['slug']}
                 for kind, key in [('custom_character', 'custom_characters'), ('custom_stage', 'custom_stages')]
                 for item in data.get(key, []) if item.get('slug')
                 and query.casefold() in (item.get('name') or item['slug']).casefold()]
        from core.stages import STAGES_BY_CODE, LEGAL_STAGE_CODES
        items.extend({'kind': 'stage_skin', 'stage_code': code, 'variant_id': v['id'], 'name': v.get('name') or v['id']}
                     for code in LEGAL_STAGE_CODES
                     for v in data.get('stages', {}).get(STAGES_BY_CODE[code]['folder'], {}).get('variants', [])
                     if v.get('id') and query.casefold() in (v.get('name') or v['id']).casefold())
        return {'items': items[:50], 'total': len(items), 'note': 'Use search_vault for standard costumes.'}
    if action in {'status', 'stop'}:
        # A session_id that names an automated verification routes to THAT
        # run's own cancellation event, not to the interactive session lock.
        if session_id and str(session_id) in _verifications:
            return {'game_verification': verification_status(
                chat_id, session_id, stop=action == 'stop')}
        return {'game_test': snapshot(app, chat_id, session_id, stop=action == 'stop')}
    if action == 'verify':
        if session_id:
            raise ValueError('Only status/stop take a session_id.')
        paths = settings(runtime.get('settings'))
        if not paths.get('vanillaIsoPath') or not Path(paths['vanillaIsoPath']).is_file():
            raise ValueError('Set your vanilla Melee ISO path in Settings before verifying.')
        return {'game_verification': verify(app, chat_id, kind=kind, character=character,
                                            skin_id=skin_id, file_id=file_id)}
    if action != 'start' or session_id:
        raise ValueError('Use start, verify, status, stop or list; only status/stop take a session_id.')
    fn, target, label = _target(kind, character, skin_id, slug, file_id, stage_code, variant_id, costume_index)
    paths = settings(runtime.get('settings'))
    if not paths.get('vanillaIsoPath') or not Path(paths['vanillaIsoPath']).is_file() or not paths.get('slippiDolphinPath'):
        raise ValueError('Set your vanilla Melee ISO and Slippi Dolphin paths in Settings before testing.')
    from projects.routes import test_in_game as test  # in-process handler call: see _invoke
    with _lock:
        current = _invoke(app, test.test_in_game_status)
        if current['running']:
            try:
                record = _load(chat_id, current['sessionId'])
            except ValueError:
                raise ValueError('Another in-game test is running. Stop it from its own panel first.')
            if record['target'] != target or record['kind'] != kind:
                raise ValueError('Another target is playing. Stop that session before starting this one.')
            return {'game_test': snapshot(app, chat_id, record['session_id'])}
        session_id = str(uuid.uuid4())
        record = dict(session_id=session_id, chat_id=chat_id, target=target, kind=kind, label=label)
        _save(record)
        body = {**paths, **target, 'interactive': True, 'sessionId': session_id}
        try:
            if fn is None:
                _start_file(app, body, **target)
            else:
                _invoke(app, fn, body)
        except Exception as exc:
            record['terminal'] = {'event': 'test_error', 'payload': {'error': str(exc)}}
            _save(record)
            raise
        return {'game_test': snapshot(app, chat_id, session_id)}
