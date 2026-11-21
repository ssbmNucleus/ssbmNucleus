"""Real chat/test dispatch with fake builds and processes; never boots Dolphin."""
import json
import threading
import time
import types
import uuid
import zipfile

import pytest
from flask import Flask
from randall.assistant import engine, live_runs, store, tools
from shared import mod_files
from randall.delivery import game_tests as games


def test_a_play_sessions_note_never_says_it_is_running_before_it_is():
    """The reply right after start says where it opens, the port and Stop, without claiming the game is up."""
    building = games._play_note({'running': True, 'status': {'stage': 'building'}})
    assert 'panel on the right' in building and 'port 1' in building and 'Stop' in building
    assert 'not running yet' in building
    live = games._play_note({'running': True, 'status': {'stage': 'playing'}})
    assert 'live' in live and 'not running yet' not in live
    assert 'own game window' in games._play_note({'running': True, 'status': {}}, capture_supported=False)
    assert 'ended' in games._play_note({'running': False})
from core import jobs as core_jobs
from projects.routes import test_in_game as test
import projects.install.test_inputs as test_inputs
from randall.routes.assistant_bp import assistant_bp


def idle():
    return core_jobs.active_job(test.INGAME_KIND) is None


@pytest.fixture
def game(vault, monkeypatch, tmp_path):
    from shared.ingame import boot, embed
    vault.write({'characters': {'Fox': {'skins': [{'id': 'blue', 'name': 'Blue Fox'}]}},
                 'custom_characters': [{'slug': 'new-fox', 'name': 'New Fox'}],
                 'custom_stages': [{'slug': 'arena', 'name': 'Arena'}]})
    vault.touch('Fox', 'blue.zip')
    iso = vault.touch('vanilla.iso')
    monkeypatch.setattr(test, 'STORAGE_PATH', vault.storage)
    monkeypatch.setattr(test_inputs, 'STORAGE_PATH', vault.storage)
    monkeypatch.setattr(core_jobs, '_root_override', tmp_path / 'jobs')
    monkeypatch.setattr(core_jobs, '_jobs', {})
    monkeypatch.setattr(test, '_active_test_session', None)
    monkeypatch.setattr(test, '_test_sessions', {})
    monkeypatch.setattr(test, '_cancelled_test_ids', {})
    monkeypatch.setattr(boot, 'dolphin_running', lambda: [])
    monkeypatch.setattr(embed, 'capture_target', lambda: {'supported': True, 'sessionId': 'capture-one'})
    jobs = []
    monkeypatch.setattr(core_jobs, 'threading', types.SimpleNamespace(Event=threading.Event, Thread=lambda **kw:
        types.SimpleNamespace(start=lambda: jobs.append(kw['target']))))
    monkeypatch.setattr(test, 'get_socketio', lambda: types.SimpleNamespace(emit=lambda *a: None))
    app = Flask(__name__)
    app.register_blueprint(assistant_bp)
    app.config['TESTING'] = True
    runtime = {'app': app, 'settings': {'vanillaIsoPath': str(iso), 'slippiDolphinPath': 'fixture-dolphin'}}
    chat = uuid.uuid4().hex
    return types.SimpleNamespace(app=app, runtime=runtime, chat=chat, jobs=jobs, vault=vault)


def start(game, **target):
    return games.test_in_game('start', runtime=game.runtime, chat_id=game.chat,
        **(target or {'kind': 'costume', 'character': 'Fox', 'skin_id': 'blue'}))['game_test']


def test_launch_is_idempotent_while_playing_and_reload_never_launches(game):
    receipt = start(game)
    assert receipt['running'] and len(game.jobs) == 1
    assert start(game)['session_id'] == receipt['session_id']
    path = f'/api/assistant/chats/{game.chat}/game-tests/{receipt["session_id"]}'
    data = game.app.test_client().get(path).json
    assert data['capture_session_id'] == 'capture-one'
    assert len(game.jobs) == 1
    assert 'fixture-dolphin' not in json.dumps(data)
    assert str(game.vault.storage) not in json.dumps(data)


def test_stop_is_owned_by_chat_and_does_not_stop_other_sessions(game):
    receipt = start(game)
    sid = receipt['session_id']
    other = game.app.test_client().delete(f'/api/assistant/chats/{uuid.uuid4().hex}/game-tests/{sid}')
    assert other.status_code == 400
    assert not test._active_test_session.stop_event.is_set()
    own = game.app.test_client().delete(f'/api/assistant/chats/{game.chat}/game-tests/{sid}')
    assert own.json['stopRequested'] is True
    assert test._active_test_session.stop_event.is_set()


def test_old_card_cannot_capture_replacement_and_retains_terminal(game):
    receipt = start(game); sid = receipt['session_id']
    session = test._test_sessions[sid]
    session.finished = True
    session.last_event = {'event': 'test_complete', 'payload': {'success': True, 'reason': 'Closed'}}
    final = games.snapshot(game.app, game.chat, sid)
    assert not final['running'] and final['capture_session_id'] is None
    test._test_sessions.clear()  # restart / eviction; keep durable result
    final = games.snapshot(game.app, game.chat, sid)
    assert final['lastEvent']['payload']['reason'] == 'Closed'
    assert len(game.jobs) == 1


def test_restart_reports_interrupted_instead_of_relaunching(game):
    receipt = start(game)
    test._test_sessions.clear()
    result = games.snapshot(game.app, game.chat, receipt['session_id'])
    assert not result['running']
    assert result['lastEvent']['event'] == 'test_error'
    assert len(game.jobs) == 1


@pytest.mark.parametrize('target', [
    {'kind': 'costume', 'character': '../Fox', 'skin_id': 'blue'},
    {'kind': 'costume', 'character': 'Fox', 'skin_id': 'unknown'},
    {'kind': 'custom_character', 'slug': '../new-fox'},
    {'kind': 'custom_character', 'slug': 'unknown'},
    {'kind': 'file', 'file_id': '../content'},
])
def test_invalid_or_unknown_targets_do_not_claim_or_build(game, target):
    with pytest.raises(ValueError): start(game, **target)
    assert not game.jobs and idle()


def test_open_dolphin_is_not_touched(game, monkeypatch):
    from shared.ingame import boot
    monkeypatch.setattr(boot, 'dolphin_running', lambda: [999])
    with pytest.raises(ValueError, match='Close the open'):
        start(game)
    assert not game.jobs and idle()


def test_another_chat_cannot_reuse_or_replace_a_running_game(game):
    receipt = start(game)
    game.chat = uuid.uuid4().hex
    with pytest.raises(ValueError, match='own panel'):
        start(game)
    assert test._active_test_session.id == receipt['session_id']
    assert len(game.jobs) == 1


def test_chat_with_a_running_game_cannot_be_deleted(game):
    start(game)
    response = game.app.test_client().delete(f'/api/assistant/chats/{game.chat}')
    assert response.status_code == 409 and 'in-game session' in response.json['error']
    assert not test._active_test_session.stop_event.is_set()


def test_saved_stage_variant_is_resolved_from_the_stage_registry(game):
    from core.stages import LEGAL_STAGE_CODES, STAGES_BY_CODE
    code = next(iter(LEGAL_STAGE_CODES)); folder = STAGES_BY_CODE[code]['folder']
    data = game.vault.read()
    data['stages'] = {folder: {'variants': [{'id': 'purple', 'name': 'Purple stage'}]}}
    game.vault.write(data); game.vault.add_stage_variant_zip(folder, 'purple')
    listing = games.test_in_game('list', runtime=game.runtime, chat_id=game.chat)
    assert any(x.get('stage_code') == code for x in listing['items'])
    assert start(game, kind='stage_skin', stage_code=code, variant_id='purple')['running']
    assert len(game.jobs) == 1


def test_custom_character_can_select_an_exact_bundled_costume(game):
    receipt = start(game, kind='custom_character', slug='new-fox', costume_index=3)
    record = games._load(game.chat, receipt['session_id'])
    assert record['target']['costumeIndex'] == 3
    assert len(game.jobs) == 1


@pytest.mark.parametrize('kind,slug', [('custom_character', 'new-fox'), ('custom_stage', 'arena')])
def test_custom_targets_use_the_existing_builder(game, kind, slug):
    items = games.test_in_game('list', runtime=game.runtime, chat_id=game.chat)['items']
    assert any(x['slug'] == slug for x in items)
    assert start(game, kind=kind, slug=slug)['running']
    assert len(game.jobs) == 1


def test_exact_exported_costume_builds_without_a_vault_import(game, monkeypatch):
    from projects.install import test_build
    data = b'exact-exported-bytes'
    file = mod_files.register(data, 'PlFxNr.dat', origin={'character': 'Fox', 'costume_code': 'PlFxNr'}, edited=True)
    monkeypatch.setattr(mod_files, 'dat_roots', lambda path: ['PlyFox5K_Share_joint'])
    built = []
    def build(iso, character, archive, output, **kwargs):
        with zipfile.ZipFile(archive) as z:
            built.append((character, z.read('PlFxNr.dat')))
        return 5
    monkeypatch.setattr(test_build, 'build_single_costume_iso', build)
    callbacks, real_start = [], test._start_build_test_job
    monkeypatch.setattr(test, '_start_build_test_job', lambda output, slippi, obs, callback:
                        callbacks.append(callback) or real_start(output, slippi, obs, callback))
    before = game.vault.read()
    receipt = start(game, kind='file', file_id=file['file_id'])
    manifest, _ = callbacks[0](lambda *a: None, lambda *a: None)
    assert built == [('Fox', data)] and manifest['costume']['colorIndex'] == 5
    assert game.vault.read() == before and receipt['running']


def test_file_is_revalidated_before_async_build(game, monkeypatch):
    file = mod_files.register(b'original', 'PlFxNr.dat', origin={'character': 'Fox', 'costume_code': 'PlFxNr'})
    monkeypatch.setattr(mod_files, 'dat_roots', lambda path: ['root'])
    callbacks, real_start = [], test._start_build_test_job
    monkeypatch.setattr(test, '_start_build_test_job', lambda output, slippi, obs, callback:
                        callbacks.append(callback) or real_start(output, slippi, obs, callback))
    start(game, kind='file', file_id=file['file_id'])
    path, _ = mod_files.resolve(file['file_id']); path.write_bytes(b'changed')
    with pytest.raises(ValueError, match='changed'):
        callbacks[0](lambda *a: None, lambda *a: None)


def test_engine_receipt_and_provider_do_not_contain_local_paths(game, monkeypatch):
    messages = []
    def provider(history, *args):
        messages.extend(history)
        calls = [] if any(m.get('role') == 'tool' for m in history) else [
            {'id': 'play', 'function': {'name': 'test_in_game', 'arguments': json.dumps(
                {'action': 'start', 'kind': 'costume', 'character': 'Fox', 'skin_id': 'blue'})}}]
        yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Ready to play.', 'tool_calls': calls}}
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Play Blue Fox', {}, request_key='test', game_runtime=game.runtime)
    list(live_runs.stream(run))
    transcript = store.get(run.chat_id)
    assert transcript['messages'][-1]['tools'][0]['result']['game_test']['running']
    assert 'fixture-dolphin' not in json.dumps([messages, transcript])
    assert str(game.vault.storage) not in json.dumps([messages, transcript])
    assert len(game.jobs) == 1


def test_tool_rejects_paths_and_ui_endpoint_obeys_assistant_gate(game, monkeypatch):
    with pytest.raises(ValueError):
        tools.prepare('test_in_game', {'action': 'start', 'isoPath': 'arbitrary.iso'})
    receipt = start(game)
    monkeypatch.setenv('NUCLEUS_ASSISTANT', '0')
    response = game.app.test_client().get(f'/api/assistant/chats/{game.chat}/game-tests/{receipt["session_id"]}')
    assert response.status_code == 404


def test_chat_request_keeps_settings_outside_persisted_context(game, monkeypatch):
    received = {}
    def fake_start(chat_id, message, context, **kwargs):
        received.update(context=context, **kwargs)
        return object()
    monkeypatch.setattr(engine, 'start', fake_start)
    monkeypatch.setattr(live_runs, 'stream', lambda _: iter(()))
    response = game.app.test_client().post('/api/assistant/chat', json={
        'message': 'Play this', 'api_key': 'test', 'context': {'character': 'Fox'},
        'game_settings': game.runtime['settings']})
    assert response.status_code == 200
    assert received['context'] == {'character': 'Fox'}
    assert received['game_runtime']['settings'] == game.runtime['settings']
    assert received['game_runtime']['app'] is game.app
    response = game.app.test_client().post('/api/assistant/chat', json={
        'message': 'Play', 'api_key': 'test', 'game_settings': {'arbitrary_path': 'bad'}})
    assert response.status_code == 400


# --- action=verify: the AUTOMATED gate, not the play session ------------------- #

def _verifiable(monkeypatch):
    file = mod_files.register(b'costume bytes', 'PlFxNr.dat',
                              origin={'character': 'Fox', 'costume_code': 'PlFxNr'},
                              edited=True)
    monkeypatch.setattr(mod_files, 'dat_roots', lambda path: ['PlyFox5K_Share_joint'])
    return file


def _stub_verify(monkeypatch, seen, outcome='unknown', block=None):
    from shared.ingame import verify_costume

    def fake_verify(candidate, character, **kw):
        seen['character'] = character
        with zipfile.ZipFile(candidate) as archive:
            seen['names'] = archive.namelist()
            seen['bytes'] = archive.read('PlFxNr.dat')
        seen['candidate_sha256'] = verify_costume.sha256_file(candidate)
        seen['destination'] = kw['destination']
        seen['lock_wait'] = kw['lock_wait']
        seen['stop_event'] = kw.get('stop_event')
        if block is not None:
            block.wait(5)
        return {'game_verification': {
            'profile_version': 'costume_verification_v1',
            'candidate_hash': 'sha256:abc',
            'iso_identity': {'insertion_verified': True},
            'costume_slot': 4,
            'captures': [{'move': 'jab', 'frame': 1, 'path': 'a.png', 'hash': 'sha256:d'},
                         {'move': 'run', 'frame': 15, 'path': None, 'hash': None}],
            'ram_observations': {}, 'outcome': outcome,
            'timing': {'boot': 92.0, 'total': 240.0}},
            'outcome_reasons': ['run:15: no capture exists for it'],
            'limitations': ['frames_fresh: 1 capture was byte-identical'],
            'execution_evidence': {'status': 'incomplete', 'checks': [
                {'check_id': 'captures_present', 'status': 'fail', 'reason': 'run:15'}]},
            'appearance_checks': [{'move': 'jab', 'frame': 1, 'status': 'pass',
                                   'reason': ''}]}

    from shared.ingame import verify_costume
    monkeypatch.setattr(verify_costume, 'verify', fake_verify)
    return fake_verify


def _finish(receipt, game):
    """Wait for the background verification and return its final summary."""
    for _ in range(300):
        out = games.test_in_game('status', session_id=receipt['verification_id'],
                                 runtime=game.runtime,
                                 chat_id=game.chat)['game_verification']
        if out['state'] != 'running':
            return out
        time.sleep(0.02)
    raise AssertionError('the verification never finished')


def test_verify_seals_the_exact_bytes_and_returns_the_measured_outcome(game, monkeypatch):
    file = _verifiable(monkeypatch)
    # Held until the receipt is read: an unheld stub can finish on its thread
    # first and the receipt then reads 'completed' (seen in the 0.8.17 stage).
    seen, release = {}, threading.Event()
    _stub_verify(monkeypatch, seen, block=release)
    receipt = games.test_in_game('verify', kind='file', file_id=file['file_id'],
                                 runtime=game.runtime,
                                 chat_id=game.chat)['game_verification']
    assert receipt['state'] == 'running'       # returns at once, never blocks
    release.set()
    out = _finish(receipt, game)
    assert seen['character'] == 'Fox'
    assert seen['names'] == ['PlFxNr.dat'] and seen['bytes'] == b'costume bytes'
    assert seen['lock_wait'] == 0.0            # a busy Dolphin is left alone
    assert seen['stop_event'] is not None      # Stop has something to route to
    assert out['outcome'] == 'unknown'
    assert out['costume_slot'] == 4
    assert out['frames_captured'] == 1 and out['frames_requested'] == 2
    assert out['execution_evidence'] == 'incomplete'
    assert 'not a pass' in out['note']
    # no app path, dolphin path or storage root reaches model context
    assert 'fixture-dolphin' not in json.dumps(out)
    assert str(game.vault.storage) not in json.dumps(out)


def test_the_candidate_package_is_byte_identical_every_time(game, monkeypatch):
    """A timestamped zip made every invocation a different candidate hash, so
    the cache this feeds could never hit."""
    file = _verifiable(monkeypatch)
    hashes = set()
    for _ in range(2):
        seen = {}
        _stub_verify(monkeypatch, seen)
        receipt = games.test_in_game('verify', kind='file', file_id=file['file_id'],
                                     runtime=game.runtime,
                                     chat_id=game.chat)['game_verification']
        _finish(receipt, game)
        hashes.add(seen['candidate_sha256'])
    assert len(hashes) == 1


def test_stop_routes_to_the_verifications_own_cancellation(game, monkeypatch):
    file = _verifiable(monkeypatch)
    seen, release = {}, threading.Event()
    _stub_verify(monkeypatch, seen, block=release)
    receipt = games.test_in_game('verify', kind='file', file_id=file['file_id'],
                                 runtime=game.runtime,
                                 chat_id=game.chat)['game_verification']
    for _ in range(300):
        if seen.get('stop_event') is not None:
            break
        time.sleep(0.02)
    release.set()
    out = games.test_in_game('stop', session_id=receipt['verification_id'],
                             runtime=game.runtime,
                             chat_id=game.chat)['game_verification']
    assert seen['stop_event'].is_set(), 'Stop must reach the run, not the play lock'
    assert out['verification_id'] == receipt['verification_id']


def test_a_verification_belongs_to_its_own_conversation(game, monkeypatch):
    file = _verifiable(monkeypatch)
    _stub_verify(monkeypatch, {})
    receipt = games.test_in_game('verify', kind='file', file_id=file['file_id'],
                                 runtime=game.runtime,
                                 chat_id=game.chat)['game_verification']
    _finish(receipt, game)
    with pytest.raises(ValueError, match='not found in this conversation'):
        games.test_in_game('status', session_id=receipt['verification_id'],
                           runtime=game.runtime, chat_id=uuid.uuid4().hex)


def test_verify_refuses_while_an_interactive_session_is_running(game, monkeypatch):
    file = _verifiable(monkeypatch)
    start(game)
    from shared.ingame import verify_costume
    monkeypatch.setattr(verify_costume, 'verify', lambda *a, **k: pytest.fail(
        'a running session means the Dolphin slot is taken; leave it alone'))
    with pytest.raises(ValueError, match='already running'):
        games.test_in_game('verify', kind='file', file_id=file['file_id'],
                           runtime=game.runtime, chat_id=game.chat)


def test_verify_only_accepts_an_exported_costume_file(game, monkeypatch):
    from shared.ingame import verify_costume
    monkeypatch.setattr(verify_costume, 'verify',
                        lambda *a, **k: pytest.fail('unreachable'))
    for bad in ({'kind': 'costume', 'character': 'Fox', 'skin_id': 'blue'},
                {'kind': 'custom_character', 'slug': 'new-fox'},
                {'kind': 'file'}):
        with pytest.raises(ValueError):
            games.test_in_game('verify', runtime=game.runtime,
                               chat_id=game.chat, **bad)


def test_verify_is_an_advertised_action_of_the_tool(game):
    schema = next(s for s in tools.SCHEMAS if s['function']['name'] == 'test_in_game')
    assert 'verify' in schema['function']['parameters']['properties']['action']['enum']
    assert 'measure' in schema['function']['description'].lower()
