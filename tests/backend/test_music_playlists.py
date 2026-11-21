"""
Music playlists blueprint: weight normalization (shares always sum to
100), equal-share appends, and reading/writing stage playlists straight
from the project workspace JSON (MexCLI mocked at the subprocess seam).
"""
import io
import json
from pathlib import Path

import pytest
from flask import Flask

import projects.routes.music_playlists as mp
import mexcli.commands


# ============= Normalization math =============

def test_normalize_chances_scales_to_100():
    entries = [{'chance': 50}, {'chance': 50}, {'chance': 50}]
    mp._normalize_chances(entries)
    assert [e['chance'] for e in entries] == [34, 33, 33]
    assert sum(e['chance'] for e in entries) == 100


def test_normalize_chances_preserves_ratios():
    entries = [{'chance': 75}, {'chance': 25}]
    mp._normalize_chances(entries)
    assert [e['chance'] for e in entries] == [75, 25]


def test_normalize_chances_all_zero_splits_evenly():
    entries = [{'chance': 0}, {'chance': 0}, {'chance': 0}, {'chance': 0}]
    mp._normalize_chances(entries)
    assert [e['chance'] for e in entries] == [25, 25, 25, 25]


def test_normalize_chances_keeps_explicit_zero():
    entries = [{'chance': 100}, {'chance': 0}]
    mp._normalize_chances(entries)
    assert [e['chance'] for e in entries] == [100, 0]


def test_normalize_chances_empty_is_noop():
    assert mp._normalize_chances([]) == []


def test_appended_entries_equal_share():
    tracks = [{'music_id': 1, 'chance': 50}, {'music_id': 2, 'chance': 50}]
    entries = mp._appended_entries(tracks, 9)
    assert [e['musicId'] for e in entries] == [1, 2, 9]
    assert sum(e['chance'] for e in entries) == 100
    # the new song gets ~a third; the others shrink proportionally
    assert entries[2]['chance'] in (33, 34)


def test_appended_entries_first_song_gets_everything():
    entries = mp._appended_entries([], 5)
    assert entries == [{'musicId': 5, 'chance': 100}]


# ============= Workspace fixture =============

STAGE_NAME = 'Fountain of Dreams'


@pytest.fixture
def project(tmp_path):
    """Minimal workspace: .mexproj + data/stages/*.json + data/music.json."""
    (tmp_path / 'data' / 'stages').mkdir(parents=True)
    music = [{'name': f'Song {i}', 'fileName': f'song_{i}.hps'} for i in range(4)]
    (tmp_path / 'data' / 'music.json').write_text(json.dumps(music), encoding='utf-8')

    def stage(fname, name, entries):
        (tmp_path / 'data' / 'stages' / fname).write_text(
            json.dumps({'name': name, 'playlist': {'entries': entries}}), encoding='utf-8')

    stage('st_0.json', 'Battlefield', [])
    # duplicate name: LAST match must win (mirrors MexCLI's LastOrDefault)
    stage('st_1.json', STAGE_NAME, [{'musicID': 0, 'chanceToPlay': 99}])
    stage('st_2.json', STAGE_NAME, [{'musicID': 1, 'chanceToPlay': 60},
                                    {'musicID': 2, 'chanceToPlay': 40}])

    project_file = tmp_path / 'project.mexproj'
    project_file.write_text(json.dumps({
        'stageSaveMap': {'filePaths': ['st_0.json', 'st_1.json', 'st_2.json']},
        'menuPlaylist': {'entries': [{'musicID': 3, 'chanceToPlay': 75},
                                     {'musicID': 0, 'chanceToPlay': 25}]},
    }), encoding='utf-8')
    return project_file


def test_get_stage_playlist_reads_last_name_match(project):
    tracks = mp._get_stage_playlist(project, STAGE_NAME)
    assert [(t['music_id'], t['chance'], t['name']) for t in tracks] == [
        (1, 60, 'Song 1'), (2, 40, 'Song 2')]


def test_get_stage_playlist_empty_is_vanilla(project):
    assert mp._get_stage_playlist(project, 'Battlefield') == []


def test_get_stage_playlist_unknown_stage_is_none(project):
    assert mp._get_stage_playlist(project, 'Pokemon Stadium') is None


def test_get_menu_playlist(project):
    tracks = mp._get_menu_playlist(project)
    assert [(t['music_id'], t['chance']) for t in tracks] == [(3, 75), (0, 25)]


# ============= Routes (MexCLI mocked) =============

@pytest.fixture
def client(project, monkeypatch):
    monkeypatch.setattr(mp, 'get_current_project_path', lambda: project)
    playlist_add_calls = []

    def fake_set_stage_playlist(project_file, stage_name, entries):
        # emulate the CLI: write the entries into the stage's workspace json
        stages_dir = project.parent / 'data' / 'stages'
        target = None
        for fname in json.loads(project.read_text(encoding='utf-8'))['stageSaveMap']['filePaths']:
            data = json.loads((stages_dir / fname).read_text(encoding='utf-8'))
            if data['name'].lower() == stage_name.lower():
                target = fname
        data = json.loads((stages_dir / target).read_text(encoding='utf-8'))
        data['playlist'] = {'entries': [
            {'musicID': e['musicId'], 'chanceToPlay': e['chance']} for e in entries]}
        (stages_dir / target).write_text(json.dumps(data), encoding='utf-8')
        return {'success': True}

    monkeypatch.setattr(mp, '_set_stage_playlist', fake_set_stage_playlist)

    def fake_add_playlist_music(project_file, hps, name, target, entries, stage_name=None):
        assert project_file == project
        assert sum(e['musicId'] == -1 for e in entries) == 1
        music_path = project.parent / 'data' / 'music.json'
        music = json.loads(music_path.read_text(encoding='utf-8'))
        music_id = len(music)
        file_name = f'uploaded_{music_id}.hps'
        music.append({'name': name, 'fileName': file_name})
        music_path.write_text(json.dumps(music), encoding='utf-8')
        audio_dir = project.parent / 'files' / 'audio'
        audio_dir.mkdir(parents=True, exist_ok=True)
        (audio_dir / file_name).write_bytes(Path(hps).read_bytes())
        resolved = [
            {'musicId': music_id if e['musicId'] == -1 else e['musicId'],
             'chance': e['chance']}
            for e in entries
        ]
        playlist_add_calls.append({
            'target': target, 'stage_name': stage_name,
            'entries': [dict(e) for e in entries], 'hps': Path(hps).read_bytes(),
        })
        if target == 'stage':
            fake_set_stage_playlist(project, stage_name, resolved)
        else:
            data = json.loads(project.read_text(encoding='utf-8'))
            data['menuPlaylist'] = {'entries': [
                {'musicID': e['musicId'], 'chanceToPlay': e['chance']} for e in resolved]}
            project.write_text(json.dumps(data), encoding='utf-8')
        return {'success': True, 'musicId': music_id, 'entries': resolved}

    monkeypatch.setattr(mp, '_add_playlist_music', fake_add_playlist_music)

    app = Flask(__name__)
    app.register_blueprint(mp.music_playlists_bp)
    test_client = app.test_client()
    test_client.playlist_add_calls = playlist_add_calls
    return test_client


def test_get_stage_music_normalizes_display(client):
    resp = client.get('/api/mex/das/GrIz/stage-music')
    data = resp.get_json()
    assert data['success'] and data['project_open']
    assert data['vanilla'] is False
    assert [t['chance'] for t in data['tracks']] == [60, 40]


def test_get_stage_music_empty_synthesizes_vanilla(client):
    # Battlefield's playlist is empty -> the stage's actual vanilla songs
    # (main + unlock-gated 12% alternate) are served as the tracks
    resp = client.get('/api/mex/das/GrNBa/stage-music')
    data = resp.get_json()
    assert data['success'] and data['vanilla'] is True
    assert [(t['music_id'], t['chance']) for t in data['tracks']] == [(81, 88), (38, 12)]


def test_set_stage_music_renormalizes(client):
    resp = client.post('/api/mex/das/GrIz/stage-music/set',
                       json={'entries': [{'music_id': 1, 'chance': 30},
                                         {'music_id': 2, 'chance': 30},
                                         {'music_id': 3, 'chance': 30}]})
    data = resp.get_json()
    assert data['success']
    chances = [t['chance'] for t in data['tracks']]
    assert sum(chances) == 100
    assert chances == [34, 33, 33]


def test_set_stage_music_empty_restores_vanilla(client):
    resp = client.post('/api/mex/das/GrIz/stage-music/set', json={'entries': []})
    data = resp.get_json()
    assert data['success'] and data['vanilla'] is True
    # response shows the vanilla songs the stage now falls back to
    assert [(t['music_id'], t['chance']) for t in data['tracks']] == [(49, 100)]


def test_set_stage_music_materializes_vanilla(client):
    # editing a vanilla stage's mix writes a real playlist
    resp = client.post('/api/mex/das/GrNBa/stage-music/set',
                       json={'entries': [{'music_id': 81, 'chance': 60},
                                         {'music_id': 38, 'chance': 40}]})
    data = resp.get_json()
    assert data['success'] and data['vanilla'] is False
    assert [(t['music_id'], t['chance']) for t in data['tracks']] == [(81, 60), (38, 40)]


def test_add_to_vanilla_stage_keeps_default_songs(client, monkeypatch):
    # adding a song to a vanilla stage seeds the playlist with the
    # vanilla entries instead of silently dropping them
    def convert(cli_args, **_kw):
        _command, _source, output = cli_args
        Path(output).write_bytes(b'normalized')
        return {'success': True}

    monkeypatch.setattr(mexcli.commands, 'run_json', convert)
    resp = client.post('/api/mex/das/GrNBa/stage-music/tracks/add', data={
        'file': (io.BytesIO(b'RIFF'), 'new-song.wav'), 'name': 'New Song',
    }, content_type='multipart/form-data')
    data = resp.get_json()
    assert data['success'] and data['vanilla'] is False
    assert [t['music_id'] for t in data['tracks']] == [81, 38, 4]
    chances = [t['chance'] for t in data['tracks']]
    assert sum(chances) == 100
    assert chances[2] in (33, 34)  # newcomer gets an equal share


@pytest.mark.parametrize(('filename', 'payload'), [
    ('track.wav', b'RIFF-valid-wav'),
    ('track.mp3', b'MP3-valid'),
    ('track.ogg', b'OGG-valid'),
    ('track.m4a', b'M4A-valid'),
    ('track.flac', b'FLAC-valid'),
    ('track.hps', b'HPS-valid-native'),
    ('track.brstm', b'BRSTM-valid'),
    ('track.dsp', b'DSP-valid'),
])
def test_add_stage_track_normalizes_every_supported_music_upload(
        client, monkeypatch, filename, payload):
    calls = []

    def fake_run(cli_args, **_kw):
        command, *args = cli_args
        calls.append((command, *args))
        assert command == 'audio-to-hps'
        assert Path(args[0]).read_bytes() == payload
        Path(args[1]).write_bytes(b'normalized-looping-hps')
        return {'success': True}

    monkeypatch.setattr(mexcli.commands, 'run_json', fake_run)
    resp = client.post('/api/mex/das/GrNBa/stage-music/tracks/add', data={
        'file': (io.BytesIO(payload), filename),
        'name': 'Validated Track',
    }, content_type='multipart/form-data')

    assert resp.status_code == 200, resp.get_json()
    assert [call[0] for call in calls] == ['audio-to-hps']
    assert len(client.playlist_add_calls) == 1
    combined = client.playlist_add_calls[0]
    assert combined['target'] == 'stage'
    assert combined['stage_name'] == 'Battlefield'
    assert sum(e['musicId'] == -1 for e in combined['entries']) == 1
    assert combined['hps'] == b'normalized-looping-hps'


def test_add_menu_track_uses_one_combined_mutation_after_conversion(client, monkeypatch):
    conversions = []

    def convert(cli_args, **_kw):
        command, source, output = cli_args
        conversions.append(command)
        assert Path(source).suffix == '.flac'
        Path(output).write_bytes(b'normalized-menu-hps')
        return {'success': True}

    monkeypatch.setattr(mexcli.commands, 'run_json', convert)
    resp = client.post('/api/mex/menu-music/tracks/add', data={
        'file': (io.BytesIO(b'FLAC-original'), 'menu.flac'), 'name': 'Menu New',
    }, content_type='multipart/form-data')

    assert resp.status_code == 200, resp.get_json()
    assert conversions == ['audio-to-hps']
    assert len(client.playlist_add_calls) == 1
    combined = client.playlist_add_calls[0]
    assert combined['target'] == 'menu'
    assert combined['stage_name'] is None
    assert sum(e['musicId'] == -1 for e in combined['entries']) == 1
    assert combined['hps'] == b'normalized-menu-hps'
    assert [track['music_id'] for track in resp.get_json()['tracks']] == [3, 0, 4]


@pytest.mark.parametrize(('target', 'stage_name', 'expected_tail'), [
    ('menu', None, ['Menu Song', 'menu']),
    ('stage', 'Battlefield', ['Stage Song', 'stage', 'Battlefield']),
])
def test_add_playlist_music_cli_contract(
        monkeypatch, target, stage_name, expected_tail):
    captured = {}

    class Result:
        returncode = 0
        stdout = json.dumps({'success': True, 'musicId': 12})

    def fake_run(args, **kwargs):
        captured['args'] = args
        captured.update(kwargs)
        return Result()

    monkeypatch.setattr(mp.subprocess, 'run', fake_run)
    entries = [{'musicId': 3, 'chance': 50}, {'musicId': -1, 'chance': 50}]
    name = f'{target.title()} Song'
    out = mp._add_playlist_music(
        Path('test.mexproj'), Path('normalized.hps'), name,
        target, entries, stage_name=stage_name)

    assert captured['args'][1:4] == [
        'add-playlist-music', 'test.mexproj', 'normalized.hps']
    assert captured['args'][4:] == expected_tail
    assert json.loads(captured['input']) == entries
    assert captured['capture_output'] is True
    assert captured['text'] is True
    assert out == {'success': True, 'musicId': 12, '_returncode': 0}


def test_combined_stage_add_failure_leaves_no_orphan_workspace_files(
        client, project, monkeypatch):
    def snapshot():
        return {
            str(path.relative_to(project.parent)): path.read_bytes()
            for path in project.parent.rglob('*') if path.is_file()
        }

    before = snapshot()
    conversions = []
    mutations = []

    def convert(cli_args, **_kw):
        command, _source, output = cli_args
        conversions.append(command)
        Path(output).write_bytes(b'normalized-but-not-committed')
        return {'success': True}

    def fail_combined(project_file, hps, name, target, entries, stage_name=None):
        mutations.append({
            'project': project_file, 'hps': Path(hps).read_bytes(), 'name': name,
            'target': target, 'entries': entries, 'stage_name': stage_name,
        })
        return {'success': False, 'error': 'simulated single-save failure'}

    monkeypatch.setattr(mexcli.commands, 'run_json', convert)
    monkeypatch.setattr(mp, '_add_playlist_music', fail_combined)
    resp = client.post('/api/mex/das/GrNBa/stage-music/tracks/add', data={
        'file': (io.BytesIO(b'MP3-original'), 'failure.mp3'), 'name': 'Must Not Persist',
    }, content_type='multipart/form-data')

    assert resp.status_code == 500
    assert resp.get_json()['error'] == 'simulated single-save failure'
    assert conversions == ['audio-to-hps']
    assert len(mutations) == 1
    assert mutations[0]['target'] == 'stage'
    assert sum(e['musicId'] == -1 for e in mutations[0]['entries']) == 1
    assert snapshot() == before


def test_add_stage_track_rejects_corrupt_native_hps_without_project_mutation(
        client, project, monkeypatch):
    before_project = project.read_bytes()
    before_music = (project.parent / 'data' / 'music.json').read_bytes()
    calls = []

    def fake_run(cli_args, **_kw):
        command, *_args = cli_args
        calls.append(command)
        return {'success': False, 'error': 'Unsupported or unreadable audio file'}

    monkeypatch.setattr(mexcli.commands, 'run_json', fake_run)
    resp = client.post('/api/mex/das/GrNBa/stage-music/tracks/add', data={
        'file': (io.BytesIO(b'not-an-hps'), 'broken.hps'),
    }, content_type='multipart/form-data')

    assert resp.status_code == 400
    assert 'unreadable audio' in resp.get_json()['error'].lower()
    assert calls == ['audio-to-hps']
    assert project.read_bytes() == before_project
    assert (project.parent / 'data' / 'music.json').read_bytes() == before_music


def test_add_stage_track_reports_wav_conversion_failure_cleanly(client, monkeypatch):
    monkeypatch.setattr(mexcli.commands, 'run_json', lambda *_args, **_kw: {
        'success': False, 'error': 'HPS encode failed: invalid channel data'})
    resp = client.post('/api/mex/das/GrNBa/stage-music/tracks/add', data={
        'file': (io.BytesIO(b'bad-wav'), 'broken.wav'),
    }, content_type='multipart/form-data')

    assert resp.status_code == 400
    assert resp.get_json() == {
        'success': False, 'error': 'HPS encode failed: invalid channel data'}


@pytest.mark.parametrize('filename', ['track.mp3', 'track.ogg', 'track.m4a', 'track.flac'])
def test_direct_api_dispatches_compressed_music_conversion_failure(
        client, monkeypatch, filename):
    calls = []

    def fail_conversion(cli_args, **_kw):
        command, input_path, _output_path = cli_args
        calls.append(command)
        assert command == 'audio-to-hps'
        assert Path(input_path).suffix == Path(filename).suffix
        return {'success': False, 'error': 'Decoder rejected compressed audio'}

    monkeypatch.setattr(mexcli.commands, 'run_json', fail_conversion)
    resp = client.post('/api/mex/das/GrNBa/stage-music/tracks/add', data={
        'file': (io.BytesIO(b'compressed'), filename),
    }, content_type='multipart/form-data')
    assert resp.status_code == 400
    assert resp.get_json()['error'] == 'Decoder rejected compressed audio'
    assert calls == ['audio-to-hps']


def test_set_stage_music_rejects_bad_entries(client):
    resp = client.post('/api/mex/das/GrIz/stage-music/set',
                       json={'entries': [{'chance': 50}]})
    assert resp.status_code == 400


def test_stage_music_unknown_stage_404(client):
    assert client.get('/api/mex/das/GrTe/stage-music').status_code == 404


def test_set_menu_music_rejects_empty(client):
    resp = client.post('/api/mex/menu-music/set', json={'entries': []})
    assert resp.status_code == 400
