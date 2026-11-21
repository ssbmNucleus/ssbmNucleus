"""Route-level regression coverage for backend audio ingestion safety."""

import io
import json
import os
from pathlib import Path
import zipfile

import pytest
from flask import Flask

from vault.routes import character_sounds as sounds
from vault.routes import custom_characters as characters
from vault.routes.custom_characters import audio as cc_audio
from vault.importing import custom_character_zip as cc_zip
from vault.catalog import custom_characters as cc_catalog
from vault.routes import custom_stages as stages
from projects.routes import music_playlists as playlists
from core import metadata as core_metadata
import mexcli.commands


EXPECTED_AUDIO_EXTS = {
    '.wav', '.mp3', '.ogg', '.m4a', '.flac', '.hps', '.brstm', '.dsp',
}


def test_all_backend_audio_routes_share_the_native_decoder_extension_contract():
    assert playlists.MUSIC_IMPORT_EXTS == EXPECTED_AUDIO_EXTS
    assert stages.MUSIC_IMPORT_EXTS == EXPECTED_AUDIO_EXTS
    assert sounds.SOUND_IMPORT_EXTS == EXPECTED_AUDIO_EXTS
    assert cc_audio.SOUND_IMPORT_EXTS == EXPECTED_AUDIO_EXTS


@pytest.fixture
def stage_vault(tmp_path, monkeypatch):
    storage = tmp_path / 'storage'
    stage_root = storage / 'custom_stages'
    stage_root.mkdir(parents=True)
    metadata_file = storage / 'metadata.json'
    metadata_file.write_text(json.dumps({
        'characters': {}, 'stages': {}, 'custom_characters': [],
        'custom_stages': [{'slug': 'test-stage', 'name': 'Test Stage'}],
    }), encoding='utf-8')

    monkeypatch.setattr(stages, 'CUSTOM_STAGES_PATH', stage_root)
    monkeypatch.setattr(core_metadata, 'METADATA_FILE', metadata_file)

    app = Flask(__name__)
    app.register_blueprint(stages.custom_stages_bp)
    with app.test_client() as client:
        yield client, stage_root, metadata_file


@pytest.mark.parametrize(('filename', 'source'), [
    ('music.wav', b'RIFF-valid'),
    ('music.mp3', b'MP3-valid'),
    ('music.hps', b'HPS-valid'),
])
def test_custom_stage_route_normalizes_wav_and_native_hps(
        stage_vault, monkeypatch, filename, source):
    client, stage_root, metadata_file = stage_vault
    calls = []

    def fake_run(cli_args, **_kw):
        command, input_path, output_path = cli_args
        calls.append(command)
        assert command == 'audio-to-hps'
        assert Path(input_path).read_bytes() == source
        Path(output_path).write_bytes(b'normalized-looping-hps')
        return {'success': True}

    monkeypatch.setattr(mexcli.commands, 'run_json', fake_run)
    resp = client.post('/api/mex/custom-stages/test-stage/playlist/add', data={
        'file': (io.BytesIO(source), filename), 'name': 'Track', 'chance': '75',
    }, content_type='multipart/form-data')

    assert resp.status_code == 200, resp.get_json()
    assert calls == ['audio-to-hps']
    assert (stage_root / 'test-stage' / 'music_0.hps').read_bytes() == b'normalized-looping-hps'
    stored = json.loads(metadata_file.read_text(encoding='utf-8'))
    assert stored['custom_stages'][0]['playlist'] == [{'name': 'Track', 'chance': 75}]


def test_custom_stage_corrupt_hps_is_failure_atomic(stage_vault, monkeypatch):
    client, stage_root, metadata_file = stage_vault
    before = metadata_file.read_bytes()

    def fail_conversion(cli_args, **_kw):
        _command, _input_path, output_path = cli_args
        Path(output_path).write_bytes(b'partial-output')
        return {'success': False, 'error': 'HPS decode failed: corrupt header'}

    monkeypatch.setattr(mexcli.commands, 'run_json', fail_conversion)
    resp = client.post('/api/mex/custom-stages/test-stage/playlist/add', data={
        'file': (io.BytesIO(b'corrupt'), 'broken.hps'),
    }, content_type='multipart/form-data')

    assert resp.status_code == 400
    assert 'corrupt header' in resp.get_json()['error']
    assert metadata_file.read_bytes() == before
    assert not (stage_root / 'test-stage' / 'music_0.hps').exists()
    assert not (stage_root / 'test-stage').exists()


def test_custom_stage_metadata_failure_removes_converted_file(stage_vault, monkeypatch):
    client, stage_root, _metadata_file = stage_vault

    def convert(cli_args, **_kw):
        _command, _input_path, output_path = cli_args
        Path(output_path).write_bytes(b'normalized')
        return {'success': True}

    monkeypatch.setattr(mexcli.commands, 'run_json', convert)
    monkeypatch.setattr(stages, '_write_metadata', lambda _data: (_ for _ in ()).throw(
        OSError('metadata disk failure')))
    resp = client.post('/api/mex/custom-stages/test-stage/playlist/add', data={
        'file': (io.BytesIO(b'RIFF'), 'track.wav'),
    }, content_type='multipart/form-data')

    assert resp.status_code == 500
    assert not (stage_root / 'test-stage' / 'music_0.hps').exists()
    assert not (stage_root / 'test-stage').exists()


@pytest.fixture
def sound_pack(tmp_path, monkeypatch):
    storage = tmp_path / 'storage'
    pack = storage / 'Fox' / 'sounds' / 'packs' / 'test-pack'
    pack.mkdir(parents=True)
    (pack / 'pack.json').write_text(json.dumps({'name': 'Test'}), encoding='utf-8')
    (pack / 'bank.ssm').write_bytes(b'ORIGINAL-BANK')
    (pack / 'sound_mods.json').write_text(json.dumps({'1': {'source': 'old.wav'}}), encoding='utf-8')
    monkeypatch.setattr(sounds, 'STORAGE_PATH', storage)

    app = Flask(__name__)
    app.register_blueprint(sounds.character_sounds_bp)
    with app.test_client() as client:
        yield client, pack


def test_sound_replace_validates_with_ssm_replace_and_commits_atomically(
        sound_pack, monkeypatch):
    client, pack = sound_pack
    calls = []

    def fake_run(cli_args, **_kw):
        command, bank, index, upload, output = cli_args
        calls.append(command)
        assert command == 'ssm-replace'
        assert Path(bank).read_bytes() == b'ORIGINAL-BANK'
        assert index == 2
        assert Path(upload).read_bytes() == b'RIFF-new-sound'
        Path(output).write_bytes(b'REBUILT-BANK')
        return {'success': True, 'durationMs': 123, 'frequency': 32000}

    monkeypatch.setattr(mexcli.commands, 'run_json', fake_run)
    resp = client.post(
        '/api/mex/storage/characters/Fox/sound-packs/test-pack/audio/sound/2/replace',
        data={'file': (io.BytesIO(b'RIFF-new-sound'), 'new.wav')},
        content_type='multipart/form-data')

    assert resp.status_code == 200, resp.get_json()
    assert calls == ['ssm-replace']
    assert (pack / 'bank.ssm').read_bytes() == b'REBUILT-BANK'
    mods = json.loads((pack / 'sound_mods.json').read_text(encoding='utf-8'))
    assert mods['1']['source'] == 'old.wav'
    assert mods['2']['source'] == 'new.wav'


@pytest.mark.parametrize('filename', ['bad.hps', 'bad.mp3'])
def test_sound_replace_tool_failure_preserves_bank_and_manifest(
        sound_pack, monkeypatch, filename):
    client, pack = sound_pack
    before_bank = (pack / 'bank.ssm').read_bytes()
    before_mods = (pack / 'sound_mods.json').read_bytes()

    def fail_run(cli_args, **_kw):
        _command, _bank, _index, _upload, output = cli_args
        Path(output).write_bytes(b'PARTIAL-BANK')
        return {'success': False, 'error': 'SSM replace failed: unreadable audio'}

    monkeypatch.setattr(mexcli.commands, 'run_json', fail_run)
    resp = client.post(
        '/api/mex/storage/characters/Fox/sound-packs/test-pack/audio/sound/2/replace',
        data={'file': (io.BytesIO(b'bad'), filename)},
        content_type='multipart/form-data')

    assert resp.status_code == 400
    assert (pack / 'bank.ssm').read_bytes() == before_bank
    assert (pack / 'sound_mods.json').read_bytes() == before_mods


def test_sound_commit_restores_bank_if_manifest_publish_fails(
        sound_pack, tmp_path, monkeypatch):
    _client, pack = sound_pack
    before_bank = (pack / 'bank.ssm').read_bytes()
    before_mods = (pack / 'sound_mods.json').read_bytes()
    rebuilt = tmp_path / 'rebuilt.ssm'
    rebuilt.write_bytes(b'VALIDATED-NEW-BANK')
    real_replace = os.replace
    failed = False

    def fail_manifest_once(source, destination):
        nonlocal failed
        source = Path(source)
        if (not failed and source.name == 'sound_mods.json'
                and source.parent.name.startswith('.sound_commit_')):
            failed = True
            raise OSError('simulated manifest publish failure')
        return real_replace(source, destination)

    monkeypatch.setattr(os, 'replace', fail_manifest_once)
    with pytest.raises(OSError, match='manifest publish failure'):
        sounds._commit_rebuilt_bank(pack, rebuilt, {'2': {'source': 'new.wav'}})

    assert failed
    assert (pack / 'bank.ssm').read_bytes() == before_bank
    assert (pack / 'sound_mods.json').read_bytes() == before_mods


@pytest.mark.parametrize('filename', ['sound.mp3', 'sound.ogg', 'sound.m4a', 'sound.flac'])
def test_direct_sound_api_dispatches_compressed_originals(
        sound_pack, monkeypatch, filename):
    client, pack = sound_pack
    calls = []

    def replace(cli_args, **_kw):
        command, _bank, _index, upload, output = cli_args
        calls.append(command)
        assert Path(upload).suffix == Path(filename).suffix
        Path(output).write_bytes(b'COMPRESSED-REBUILT-BANK')
        return {'success': True}

    monkeypatch.setattr(mexcli.commands, 'run_json', replace)
    resp = client.post(
        '/api/mex/storage/characters/Fox/sound-packs/test-pack/audio/sound/2/replace',
        data={'file': (io.BytesIO(b'compressed'), filename)},
        content_type='multipart/form-data')
    assert resp.status_code == 200, resp.get_json()
    assert calls == ['ssm-replace']
    assert (pack / 'bank.ssm').read_bytes() == b'COMPRESSED-REBUILT-BANK'


def _fighter_zip(*, victory=b'HPS-victory', announcer=b'RIFF-announcer', marker=False):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        if marker:
            zf.writestr(characters.NUCLEUS_EXPORT_MARKER, json.dumps({
                'nucleus_export': characters.NUCLEUS_EXPORT_KIND,
                'entry': {'slug': 'audio-fighter', 'name': 'Audio Fighter'},
            }))
        zf.writestr('fighter.json', json.dumps({
            'name': 'Audio Fighter', 'seriesID': 0, 'costumes': [],
        }))
        if victory is not None:
            zf.writestr('victory_theme.hps', victory)
        if announcer is not None:
            zf.writestr('announcer.wav', announcer)
        zf.writestr('vault_meta.json', json.dumps({'victory_theme_name': 'Audio Win'}))
    return buf.getvalue()


@pytest.fixture
def character_vault(tmp_path, monkeypatch):
    storage = tmp_path / 'storage'
    root = storage / 'custom_characters'
    root.mkdir(parents=True)
    metadata_file = storage / 'metadata.json'
    metadata_file.write_text(json.dumps({'custom_characters': []}), encoding='utf-8')
    # The routes (this package), import (the zip importer), slug allocation (the
    # catalog) and sound edits (audio.py) each hold their own copy of the vault root.
    for module in (characters, cc_zip, cc_catalog, cc_audio):
        monkeypatch.setattr(module, 'CUSTOM_CHARACTERS_PATH', root)
    monkeypatch.setattr(core_metadata, 'METADATA_FILE', metadata_file)

    app = Flask(__name__)
    app.register_blueprint(characters.custom_characters_bp)
    with app.test_client() as client:
        yield client, root, metadata_file


def test_character_zip_route_normalizes_victory_hps_and_announcer_wav(
        character_vault, monkeypatch):
    client, root, metadata_file = character_vault
    calls = []

    def fake_run(cli_args, **_kw):
        command, input_path, output_path = cli_args
        calls.append(command)
        if command == 'audio-to-hps':
            source = Path(input_path).read_bytes()
            Path(output_path).write_bytes(
                b'normalized-announcer-hps' if source.startswith(b'RIFF')
                else b'normalized-victory-hps')
            return {'success': True}
        if command == 'hps-to-wav':
            assert Path(input_path).read_bytes() == b'normalized-announcer-hps'
            Path(output_path).write_bytes(b'RIFF-normalized-announcer')
            return {'success': True}
        raise AssertionError(command)

    monkeypatch.setattr(mexcli.commands, 'run_json', fake_run)
    cc_zip.import_custom_character_zip_bytes(_fighter_zip(), 'fighter')

    assert calls == ['audio-to-hps', 'hps-to-wav', 'audio-to-hps']
    char_dir = root / 'audio-fighter'
    assert (char_dir / 'victory_theme.hps').read_bytes() == b'normalized-victory-hps'
    assert (char_dir / 'announcer.wav').read_bytes() == b'RIFF-normalized-announcer'
    entry = json.loads(metadata_file.read_text(encoding='utf-8'))['custom_characters'][0]
    assert entry['victory_theme'] == {'name': 'Audio Win'}
    assert entry['has_announcer'] is True


@pytest.mark.parametrize(('victory', 'announcer', 'label'), [
    (b'CORRUPT-HPS', None, 'victory_theme.hps'),
    (None, b'CORRUPT-WAV', 'announcer.wav'),
])
def test_character_zip_rejects_corrupt_audio_before_writing_vault(
        character_vault, monkeypatch, victory, announcer, label):
    client, root, metadata_file = character_vault
    before = metadata_file.read_bytes()

    def fail_run(cli_args, **_kw):
        command, _input_path, _output_path = cli_args
        assert command == 'audio-to-hps'
        return {'success': False, 'error': 'Unsupported or unreadable audio file'}

    monkeypatch.setattr(mexcli.commands, 'run_json', fail_run)
    with pytest.raises(ValueError) as error:
        cc_zip.import_custom_character_zip_bytes(
            _fighter_zip(victory=victory, announcer=announcer), 'bad')

    assert label in str(error.value)
    assert list(root.iterdir()) == []
    assert metadata_file.read_bytes() == before


def test_full_vault_export_audio_is_validated_before_restore(
        character_vault, monkeypatch):
    _client, root, metadata_file = character_vault
    before = metadata_file.read_bytes()
    monkeypatch.setattr(mexcli.commands, 'run_json', lambda *_args, **_kw: {
        'success': False, 'error': 'corrupt HPS'})

    with pytest.raises(ValueError, match='Invalid victory_theme.hps'):
        cc_zip.import_custom_character_zip_bytes(
            _fighter_zip(victory=b'CORRUPT', announcer=None, marker=True), 'fallback')

    assert list(root.iterdir()) == []
    assert metadata_file.read_bytes() == before


def _seed_fighter_sound_bank(root):
    char_dir = root / 'audio-fighter'
    char_dir.mkdir()
    sound_buf = io.BytesIO()
    with zipfile.ZipFile(sound_buf, 'w') as sound_zip:
        sound_zip.writestr('group.json', json.dumps({'sounds': []}))
        sound_zip.writestr('fighter.ssm', b'ORIGINAL-FIGHTER-BANK')
    with zipfile.ZipFile(char_dir / 'fighter.zip', 'w') as fighter_zip:
        fighter_zip.writestr('fighter.json', json.dumps({'name': 'Audio Fighter'}))
        fighter_zip.writestr('sound.zip', sound_buf.getvalue())
    return char_dir


def _read_packed_fighter_bank(fighter_zip_path):
    with zipfile.ZipFile(fighter_zip_path) as fighter_zip:
        with zipfile.ZipFile(io.BytesIO(fighter_zip.read('sound.zip'))) as sound_zip:
            return sound_zip.read('fighter.ssm')


@pytest.mark.parametrize('filename', ['voice.wav', 'voice.ogg'])
def test_custom_fighter_sound_replace_is_validated_and_published_atomically(
        character_vault, monkeypatch, filename):
    client, root, _metadata_file = character_vault
    char_dir = _seed_fighter_sound_bank(root)

    def fake_run(cli_args, **_kw):
        command, bank, index, upload, output = cli_args
        assert command == 'ssm-replace'
        assert Path(bank).read_bytes() == b'ORIGINAL-FIGHTER-BANK'
        assert index == 4
        assert Path(upload).read_bytes() == b'RIFF-replacement'
        assert Path(upload).suffix == Path(filename).suffix
        Path(output).write_bytes(b'REBUILT-FIGHTER-BANK')
        return {'success': True, 'durationMs': 12, 'frequency': 32000}

    monkeypatch.setattr(mexcli.commands, 'run_json', fake_run)
    resp = client.post('/api/mex/custom-characters/audio-fighter/audio/sound/4/replace', data={
        'file': (io.BytesIO(b'RIFF-replacement'), filename),
    }, content_type='multipart/form-data')

    assert resp.status_code == 200, resp.get_json()
    assert _read_packed_fighter_bank(char_dir / 'fighter.zip') == b'REBUILT-FIGHTER-BANK'
    assert (char_dir / 'audio_cache' / 'bank.ssm').read_bytes() == b'REBUILT-FIGHTER-BANK'
    assert (char_dir / 'sound_original.ssm').read_bytes() == b'ORIGINAL-FIGHTER-BANK'
    mods = json.loads((char_dir / 'sound_mods.json').read_text(encoding='utf-8'))
    assert mods['4']['source'] == filename


@pytest.mark.parametrize('filename', ['voice.hps', 'voice.m4a'])
def test_custom_fighter_sound_tool_failure_leaves_no_edit_artifacts(
        character_vault, monkeypatch, filename):
    client, root, _metadata_file = character_vault
    char_dir = _seed_fighter_sound_bank(root)
    before_zip = (char_dir / 'fighter.zip').read_bytes()

    def fail_run(cli_args, **_kw):
        _command, _bank, _index, _upload, output = cli_args
        Path(output).write_bytes(b'PARTIAL')
        return {'success': False, 'error': 'SSM replace failed: corrupt HPS'}

    monkeypatch.setattr(mexcli.commands, 'run_json', fail_run)
    resp = client.post('/api/mex/custom-characters/audio-fighter/audio/sound/4/replace', data={
        'file': (io.BytesIO(b'corrupt'), filename),
    }, content_type='multipart/form-data')

    assert resp.status_code == 400
    assert (char_dir / 'fighter.zip').read_bytes() == before_zip
    assert (char_dir / 'audio_cache' / 'bank.ssm').read_bytes() == b'ORIGINAL-FIGHTER-BANK'
    assert not (char_dir / 'sound_original.ssm').exists()
    assert not (char_dir / 'sound_mods.json').exists()


def test_custom_fighter_sound_commit_rolls_back_all_destinations(
        character_vault, monkeypatch):
    _client, root, _metadata_file = character_vault
    char_dir = _seed_fighter_sound_bank(root)
    bank = cc_audio._extract_fighter_ssm(char_dir)
    before_zip = (char_dir / 'fighter.zip').read_bytes()
    before_bank = bank.read_bytes()
    real_replace = characters.os.replace
    failed = False

    def fail_manifest_once(source, destination):
        nonlocal failed
        source = Path(source)
        if (not failed and source.name == 'sound_mods.json'
                and source.parent.name.startswith('.fighter_sound_commit_')):
            failed = True
            raise OSError('simulated fighter manifest failure')
        return real_replace(source, destination)

    monkeypatch.setattr(characters.os, 'replace', fail_manifest_once)
    with pytest.raises(OSError, match='fighter manifest failure'):
        cc_audio._commit_fighter_sound_bank(
            char_dir, b'REBUILT', {'4': {'source': 'voice.wav'}}, keep_original=True)

    assert failed
    assert (char_dir / 'fighter.zip').read_bytes() == before_zip
    assert bank.read_bytes() == before_bank
    assert not (char_dir / 'sound_mods.json').exists()
    assert not (char_dir / 'sound_original.ssm').exists()
