"""Loop API safety plus optional real MexCLI round trips (MUSIC_LOOP_TEST_CLI)."""
import json
import io
import math
import os
from pathlib import Path
import struct
import subprocess
import wave

import pytest
from flask import Flask
from projects.routes import music_playlists as mp
import mexcli.commands


@pytest.fixture
def editor(tmp_path, monkeypatch):
    project = tmp_path / 'test.mexproj'
    project.write_text('{}')
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data/music.json').write_text(json.dumps([{'name': 'Song', 'fileName': 'song.hps'}]))
    hps = tmp_path / 'files/audio/song.hps'
    hps.parent.mkdir(parents=True)
    hps.write_bytes(b'original')
    monkeypatch.setattr(mp, 'get_current_project_path', lambda: project)
    calls = []

    def run(cli_args, **_kw):
        command, source, *args = cli_args
        calls.append(command)
        if command == 'hps-set-loop':
            Path(args[0]).write_bytes(b'edited')
        return {'success': True, 'duration_ms': 8000, 'loop_start_ms': 2345,
                'loop_enabled': True, 'frequency': 32000}

    monkeypatch.setattr(mexcli.commands, 'run_json', run)
    app = Flask(__name__)
    app.register_blueprint(mp.music_playlists_bp)
    return app.test_client(), project, hps, calls


def test_save_preserves_playlist_and_requires_current_version(editor):
    client, project, hps, calls = editor
    before = project.read_bytes()
    info = client.get('/api/mex/music/0/loop').get_json()
    response = client.post('/api/mex/music/0/loop', json={'version': info['version'], 'loop_start_ms': 2345})
    assert response.status_code == 200
    assert hps.read_bytes() == b'edited'
    assert project.read_bytes() == before
    assert response.json['version'] != info['version']
    calls.clear()
    assert client.post('/api/mex/music/0/loop', json={'version': info['version'], 'loop_start_ms': 1234}).status_code == 409
    assert not calls


@pytest.mark.parametrize('value', [None, True, '', '123', -1, float('inf'), float('nan')])
def test_invalid_time_never_runs_converter(editor, value):
    client, project, hps, calls = editor
    version = mp._loop_version(project, hps)
    response = client.post('/api/mex/music/0/loop', json={'version': version, 'loop_start_ms': value})
    assert response.status_code == 400
    assert hps.read_bytes() == b'original'
    assert not calls


def test_partial_converter_failure_keeps_original(editor, monkeypatch):
    client, project, hps, _ = editor

    def fail(cli_args, **_kw):
        command, source, staged, start = cli_args
        Path(staged).write_bytes(b'partial')
        return {'success': False, 'error': 'Invalid loop point'}

    monkeypatch.setattr(mexcli.commands, 'run_json', fail)
    response = client.post('/api/mex/music/0/loop', json={
        'version': mp._loop_version(project, hps), 'loop_start_ms': 9000})
    assert response.status_code == 400
    assert hps.read_bytes() == b'original'
    assert not list(hps.parent.glob('.music-loop-*'))


def test_project_switch_during_conversion_keeps_original(editor, monkeypatch):
    client, project, hps, _ = editor

    def switch(cli_args, **_kw):
        command, source, staged, start = cli_args
        Path(staged).write_bytes(b'edited')
        monkeypatch.setattr(mp, 'get_current_project_path', lambda: project.parent / 'another.mexproj')
        return {'success': True}

    monkeypatch.setattr(mexcli.commands, 'run_json', switch)
    response = client.post('/api/mex/music/0/loop', json={
        'version': mp._loop_version(project, hps), 'loop_start_ms': 1234})
    assert response.status_code == 409
    assert hps.read_bytes() == b'original'


def test_missing_track_and_path_escape_are_rejected(editor):
    client, project, hps, calls = editor
    assert client.get('/api/mex/music/99/loop').status_code == 404
    (project.parent / 'data/music.json').write_text(json.dumps([{'fileName': '../../../test.mexproj'}]))
    assert client.get('/api/mex/music/0/loop').status_code == 404
    assert not calls


def test_preview_requires_current_project_and_bytes(editor):
    client, project, hps, calls = editor
    assert client.get('/api/mex/music/0/loop/preview?version=stale').status_code == 409
    assert not calls


def _preview_wav(value=1000):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(32000)
        out.writeframes(struct.pack('<h', value) * 3200)
    return stream.getvalue()


def test_preview_replaces_unversioned_silent_cache(editor, monkeypatch):
    client, project, hps, calls = editor
    cache = project.parent / 'cache/music_previews/track_0.wav'
    cache.parent.mkdir(parents=True)
    cache.write_bytes(_preview_wav(0))
    audible = _preview_wav()

    def decode(args, **_kw):
        calls.append(args[0])
        Path(args[2]).write_bytes(audible)
        return {'success': True}

    monkeypatch.setattr(mexcli.commands, 'run_json', decode)
    response = client.get('/api/mex/music/0/loop/preview?version=' + mp._loop_version(project, hps))
    assert response.status_code == 200
    assert response.data == audible
    response.close()
    assert calls == ['hps-to-wav']


def test_preview_source_bytes_invalidate_cache_even_with_preserved_mtime(editor, monkeypatch):
    client, project, hps, calls = editor
    def decode(args, **_kw):
        calls.append(args[0])
        Path(args[2]).write_bytes(_preview_wav(1000 if hps.read_bytes() == b'original' else 2000))
        return {'success': True}
    monkeypatch.setattr(mexcli.commands, 'run_json', decode)
    def preview():
        response = client.get('/api/mex/music/0/loop/preview?version=' + mp._loop_version(project, hps))
        data = response.data
        response.close()
        assert response.status_code == 200
        return data
    first = preview()
    assert preview() == first
    assert len(calls) == 1
    stat = hps.stat()
    hps.write_bytes(b'replaced')
    os.utime(hps, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert preview() == _preview_wav(2000)
    assert len(calls) == 2


@pytest.mark.parametrize('reported_success', [False, True])
def test_failed_or_truncated_preview_is_not_reused(editor, monkeypatch, reported_success):
    client, project, hps, calls = editor
    def decode(args, **_kw):
        calls.append(args[0])
        Path(args[2]).write_bytes(_preview_wav()[:44] if len(calls) == 1 else _preview_wav())
        return {'success': reported_success if len(calls) == 1 else True}
    monkeypatch.setattr(mexcli.commands, 'run_json', decode)
    url = '/api/mex/music/0/loop/preview?version=' + mp._loop_version(project, hps)
    response = client.get(url)
    assert response.status_code == 500
    response.close()
    response = client.get(url)
    assert response.status_code == 200
    assert response.data == _preview_wav()
    response.close()
    assert len(calls) == 2


def test_preview_new_source_does_not_replace_an_open_download(editor, monkeypatch):
    client, project, hps, calls = editor
    def decode(args, **_kw):
        calls.append(args[0])
        Path(args[2]).write_bytes(_preview_wav(1000 if hps.read_bytes() == b'original' else 2000))
        return {'success': True}
    monkeypatch.setattr(mexcli.commands, 'run_json', decode)
    old = client.get('/api/mex/music/0/loop/preview?version=' + mp._loop_version(project, hps), buffered=False)
    try:
        hps.write_bytes(b'replaced')
        new = client.get('/api/mex/music/0/loop/preview?version=' + mp._loop_version(project, hps), buffered=False)
        try:
            assert new.status_code == 200
            assert new.data == _preview_wav(2000)
            assert old.data == _preview_wav(1000)
        finally:
            new.close()
    finally:
        old.close()
    # A later preview retires old files once the streaming consumer releases it.
    response = client.get('/api/mex/music/0/loop/preview?version=' + mp._loop_version(project, hps))
    response.close()
    assert len(list((project.parent / 'cache/music_previews').glob('*.wav'))) == 1


@pytest.mark.parametrize('change', ['decoder', 'truncated_cache'])
def test_preview_regenerates_after_decoder_update_or_cache_damage(editor, monkeypatch, change):
    client, project, hps, calls = editor
    decoder = project.parent / 'mexcli.exe'
    decoder.write_bytes(b'v1')
    monkeypatch.setattr(mexcli.commands, 'MEXCLI', decoder)
    def decode(args, **_kw):
        calls.append(args[0])
        Path(args[2]).write_bytes(_preview_wav())
        return {'success': True}
    monkeypatch.setattr(mexcli.commands, 'run_json', decode)
    url = '/api/mex/music/0/loop/preview?version=' + mp._loop_version(project, hps)
    response = client.get(url)
    response.close()
    if change == 'decoder':
        decoder.write_bytes(b'updated decoder')
    else:
        cache = next((project.parent / 'cache/music_previews').glob('*.wav'))
        cache.write_bytes(_preview_wav()[:44])
    response = client.get(url)
    assert response.status_code == 200
    assert response.data == _preview_wav()
    response.close()
    assert len(calls) == 2


@pytest.mark.slow
def test_real_hps_loop_round_trip(editor, monkeypatch, tmp_path):
    """Run with MUSIC_LOOP_TEST_CLI='["dotnet", "/.../mexcli.dll"]'."""
    cli = os.environ.get('MUSIC_LOOP_TEST_CLI')
    if not cli:
        pytest.skip('Set MUSIC_LOOP_TEST_CLI to exercise the compiled audio codec')
    cli = json.loads(cli)
    client, project, hps, _ = editor

    def run(*args):
        result = subprocess.run(cli + list(map(str, args)), capture_output=True, text=True, timeout=45)
        return json.loads(result.stdout)

    monkeypatch.setattr(mexcli.commands, 'run_json', lambda cli_args, **_kw: run(*cli_args))
    wav = tmp_path / 'source.wav'
    with wave.open(str(wav), 'wb') as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(32000)
        out.writeframes(b''.join(struct.pack('<hh', int(8000 * math.sin(i * 2 * math.pi * 440 / 32000)),
                                           int(6000 * math.sin(i * 2 * math.pi * 660 / 32000))) for i in range(256000)))
    assert run('audio-to-hps', wav, hps)['success']
    original = tmp_path / 'before.wav'
    assert run('hps-to-wav', hps, original)['success']
    for start in (2345, 0, 7123.456):
        info = client.get('/api/mex/music/0/loop').json
        result = client.post('/api/mex/music/0/loop', json={'version': info['version'], 'loop_start_ms': start})
        assert result.status_code == 200, result.json
        reread = run('hps-loop-info', hps)
        assert reread['loop_enabled']
        assert abs(reread['loop_start_ms'] - start) < 3
        decoded = tmp_path / 'after.wav'
        assert run('hps-to-wav', hps, decoded)['success']
        with wave.open(str(original), 'rb') as a, wave.open(str(decoded), 'rb') as b:
            assert a.getparams() == b.getparams()
            assert a.readframes(a.getnframes()) == b.readframes(b.getnframes())
    before = hps.read_bytes()
    info = client.get('/api/mex/music/0/loop').json
    result = client.post('/api/mex/music/0/loop', json={'version': info['version'], 'loop_start_ms': info['duration_ms']})
    assert result.status_code == 400
    assert hps.read_bytes() == before
    assert client.get('/api/mex/music/0/loop/preview?version=' + info['version']).status_code == 200


def _decode_adpcm(data, coefs, hist1=0, hist2=0):
    out = []
    for frame in range(len(data) // 8):
        header = data[frame * 8]
        scale = (1 << (header & 15)) * 2048
        c1, c2 = coefs[(header >> 4) * 2], coefs[(header >> 4) * 2 + 1]
        for i in range(14):
            nibble = data[frame * 8 + 1 + i // 2]
            nibble = nibble >> 4 if i % 2 == 0 else nibble & 15
            if nibble >= 8:
                nibble -= 16
            sample = max(-32768, min(32767, (c1 * hist1 + c2 * hist2 + scale * nibble + 1024) >> 11))
            hist2, hist1 = hist1, sample
            out.append(sample)
    return out


@pytest.mark.slow
def test_long_song_far_loop_encodes_like_melee(tmp_path):
    """#86: Melee reloads each HPS block header's predictor and sample history
    at every block and at the loop, so they must match continuous decoding;
    the loop must start a block exactly and no block may be a sliver."""
    cli = os.environ.get('MUSIC_LOOP_TEST_CLI')
    if not cli:
        pytest.skip('Set MUSIC_LOOP_TEST_CLI to exercise the compiled audio codec')
    cli = json.loads(cli)

    def run(*args):
        result = subprocess.run(cli + list(map(str, args)), capture_output=True, text=True, timeout=120)
        return json.loads(result.stdout)

    rate, seconds = 32000, 40
    wav, hps, looped = tmp_path / 'long.wav', tmp_path / 'long.hps', tmp_path / 'looped.hps'
    with wave.open(str(wav), 'wb') as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(rate)
        # Odd length so the final block is not a whole number of frames.
        out.writeframes(b''.join(struct.pack('<hh', int(12000 * math.sin(i * 2 * math.pi * 523 / rate)),
                                           int(9000 * math.sin(i * 2 * math.pi * 1319 / rate)))
                                 for i in range(rate * seconds + 777)))
    assert run('audio-to-hps', wav, hps)['success']
    # 1531.25 ms = 49000 samples = 28000 bytes: a whole 56-sample group that
    # is also a multiple of 56 bytes, which the old writer shifted and zeroed.
    saved = run('hps-set-loop', hps, looped, 1531.25)
    assert saved['success'] and saved['loop_start_ms'] == 1531.25

    data = looped.read_bytes()
    coefs = struct.unpack('>16h', data[0x20:0x40])
    blocks, pos = [], 0x80
    while True:
        length, end, nxt = struct.unpack('>iii', data[pos:pos + 12])
        ps, hist1, hist2 = struct.unpack('>hhh', data[pos + 12:pos + 18])
        blocks.append((pos, length // 2, ps, hist1, hist2, data[pos + 0x20:pos + 0x20 + length // 2]))
        if nxt <= pos:
            break
        assert nxt == pos + 0x20 + length
        pos = nxt

    loop_byte = 28000
    offsets = [0]
    for block in blocks:
        offsets.append(offsets[-1] + block[1])
    loop_index = [b[0] for b in blocks].index(nxt)
    assert offsets[loop_index] == loop_byte
    assert all(size % 32 == 0 and 16384 <= size <= 32768 for _, size, *_ in blocks)

    pcm = _decode_adpcm(b''.join(b[5] for b in blocks), coefs)
    for start, (_, _, ps, hist1, hist2, chunk) in zip(offsets, blocks):
        sample = start // 8 * 14
        assert ps == chunk[0]
        assert (hist1, hist2) == ((pcm[sample - 1], pcm[sample - 2]) if sample else (0, 0))
