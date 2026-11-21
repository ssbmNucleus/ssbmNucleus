"""The texture-pack listener (shared/routes/slippi.py): a refused start leaves
Dolphin and the running listener as they were, and Clear does not delete what
a running listener has matched."""
import pytest
import time
from pathlib import Path
from flask import Flask

from core import jobs
from shared.routes import slippi
from projects.install import texture_pack


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(slippi, "OUTPUT_PATH", tmp_path / "output")
    monkeypatch.setattr(jobs, '_root_override', tmp_path / 'jobs')
    monkeypatch.setattr(jobs, '_jobs', {})
    monkeypatch.setattr(texture_pack.TexturePackMatcher, '_find_hd_csp_by_hash', lambda *a: None)
    running = jobs.Job(slippi.MATCH_KIND, params={'slippiPath': str(tmp_path / 'SlippiA')})
    jobs._jobs[running.id] = running
    app = Flask(__name__)
    app.register_blueprint(slippi.slippi_bp)
    return app.test_client(), tmp_path, running


def test_a_start_without_its_mapping_changes_nothing(client):
    c, tmp_path, running = client
    other = tmp_path / "SlippiB"
    r = c.post("/api/mex/texture-pack/start-listening",
               json={"buildId": "never-built", "slippiPath": str(other)})
    assert r.status_code == 404
    # B's Dolphin is not left dumping textures with no listener to undo it
    assert not slippi.get_dolphin_gfx_ini_path(str(other)).exists()
    # and Stop still turns off the running listener's own Dolphin
    assert jobs.active_job(slippi.MATCH_KIND) is running
    assert running.params['slippiPath'] == str(tmp_path / 'SlippiA')


def test_clear_waits_for_the_running_listener(client):
    c, tmp_path, _running = client
    pack = slippi.slippi_user_dir(str(tmp_path / "SlippiA")) / "Load" / "Textures" / "GALE01" / "ssbm-nucleus"
    (pack / "build").mkdir(parents=True)
    (pack / "build" / "tex1_136x188_matched.png").write_bytes(b"png")
    r = c.post("/api/mex/texture-pack/clear", json={"slippiPath": str(tmp_path / "SlippiA")})
    assert r.status_code == 409
    assert (pack / "build" / "tex1_136x188_matched.png").exists()
    # another Slippi folder is not the listener's
    r = c.post("/api/mex/texture-pack/clear", json={"slippiPath": str(tmp_path / "SlippiB")})
    assert r.status_code == 200


def mapping_for(root, count=1):
    source = root / 'portrait.png'
    source.write_bytes(b'portrait')
    mapping = texture_pack.TexturePackMapping('build', 'build', 'now')
    for index in range(count):
        mapping.add_costume(texture_pack.CostumeMapping(
            index=index, character='Fox', costume_index=index, skin_id=f'fox{index}',
            real_csp_path=str(source)))
    slippi.OUTPUT_PATH.mkdir(parents=True, exist_ok=True)
    path = slippi.OUTPUT_PATH / 'build_texture_mapping.json'
    mapping.save(path)
    return mapping, path


def wait_job(job_id):
    deadline = time.time() + 5
    while time.time() < deadline:
        record = jobs.get(job_id)
        if record['status'] in jobs.FINAL:
            return record
        time.sleep(0.01)
    pytest.fail(f'Texture job did not finish: {jobs.get(job_id)}')


def test_matching_real_dump_finishes_and_restores_dump_settings(client):
    c, root, _ = client
    jobs._jobs.clear()
    mapping, path = mapping_for(root)
    dolphin = str(root / 'SlippiA')
    slippi.set_dolphin_texture_settings(dolphin, dump_textures=False)
    dump = slippi.slippi_user_dir(dolphin) / 'Dump/Textures/GALE01'
    dump.mkdir(parents=True)
    texture_pack.generate_encoded_placeholder(0).save(dump / 'tex1_test.png')
    response = c.post('/api/mex/texture-pack/start-listening',
                      json={'buildId': 'build', 'slippiPath': dolphin})
    assert response.status_code == 200
    record = wait_job(response.json['job_id'])
    assert record['status'] == 'done', record['error']
    assert record['result']['matchedCount'] == 1
    assert record['owned'] == {}
    assert (Path(record['result']['texturePackPath']) / 'tex1_test.png').read_bytes() == b'portrait'
    assert texture_pack.TexturePackMapping.load(path).get_matched_count() == 1
    assert slippi.get_dolphin_texture_settings(dolphin) == {'dump_textures': False, 'hires_textures': True}
    assert c.get('/api/mex/texture-pack/status').status_code == 404
    assert c.post('/api/mex/texture-pack/stop-listening').status_code == 404


def test_cancel_stops_between_textures_and_keeps_completed_matches(client, monkeypatch):
    _, root, _ = client
    jobs._jobs.clear()
    mapping, path = mapping_for(root, count=2)
    dolphin = str(root / 'SlippiA')
    dump = slippi.slippi_user_dir(dolphin) / 'Dump/Textures/GALE01'
    dump.mkdir(parents=True)
    for index in range(2):
        texture_pack.generate_encoded_placeholder(index).save(dump / f'tex1_{index}.png')
    original = texture_pack.TexturePackMatcher._process_match
    def match_then_stop(matcher, costume, dumped_file):
        original(matcher, costume, dumped_file)
        jobs.cancel(matcher.job.id)
    monkeypatch.setattr(texture_pack.TexturePackMatcher, '_process_match', match_then_stop)
    record = jobs.run_inline(slippi.MATCH_KIND,
                            lambda job: slippi.run_texture_matching(job, mapping, path, dolphin))
    assert record['status'] == 'done'
    assert record['result']['stopped'] is True
    assert record['result']['matchedCount'] == 1
    assert texture_pack.TexturePackMapping.load(path).get_matched_count() == 1
    assert slippi.get_dolphin_texture_settings(dolphin)['dump_textures'] is None


@pytest.mark.parametrize('previous', [None, False, True])
def test_matching_recovery_restores_settings_and_removes_partial_files(client, previous):
    _, root, _ = client
    dolphin = str(root / 'SlippiA')
    slippi.set_dolphin_texture_settings(dolphin, dump_textures=True, hires_textures=True)
    partial = root / 'texture-match-dead.png.part'
    partial.write_bytes(b'partial')
    mapping = root / 'texture-match-dead.json.part'
    mapping.write_bytes(b'partial mapping')
    finished = root / 'finished.png'
    finished.write_bytes(b'keep')
    record = jobs.Job(slippi.MATCH_KIND, job_id='dead').snapshot()
    record.update(status='running', owner=None, owned={
        'dump_settings': {'slippi_path': dolphin, 'dump_textures': previous},
        'partial': str(partial), 'mapping_partial': str(mapping)})
    jobs._write(record)
    [recovered] = jobs.recover_interrupted()
    assert recovered['status'] == 'interrupted' and recovered['owned'] == {}
    assert not partial.exists() and not mapping.exists()
    assert finished.read_bytes() == b'keep'
    assert slippi.get_dolphin_texture_settings(dolphin)['dump_textures'] is previous


def test_overlapping_listener_is_refused(client):
    c, root, active = client
    mapping_for(root)
    response = c.post('/api/mex/texture-pack/start-listening',
                      json={'buildId': 'build', 'slippiPath': str(root / 'SlippiB')})
    assert response.status_code == 409
    assert response.json['job_id'] == active.id
    assert not slippi.get_dolphin_gfx_ini_path(str(root / 'SlippiB')).exists()
