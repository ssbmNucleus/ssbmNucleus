"""On-demand built-ins use the shared job lifecycle and retain retry inputs."""
from pathlib import Path

import pytest
from flask import Flask

from core import jobs
from vault.routes import custom_characters as routes
from shared.vanilla_extract.first_run_setup import FirstRunSetup


@pytest.fixture(autouse=True)
def isolated_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, '_root_override', tmp_path / 'jobs')
    monkeypatch.setattr(jobs, '_jobs', {})


def test_builtin_recovery_removes_recolors_and_preserves_seed(tmp_path):
    seed = tmp_path / 'builtin_seed'
    seed.mkdir()
    (seed / 'fighter.zip').write_bytes(b'seed')
    recolors = tmp_path / 'giga_recolors_dead'
    recolors.mkdir()
    (recolors / 'PlGkBu.dat').write_bytes(b'partial')
    record = jobs.Job(routes.BUILTIN_KIND, job_id='dead').snapshot()
    record.update(status='running', owner=None, owned={'recolors': str(recolors)})
    jobs._write(record)
    [recovered] = jobs.recover_interrupted()
    assert recovered['status'] == 'interrupted' and recovered['owned'] == {}
    assert not recolors.exists()
    assert (seed / 'fighter.zip').read_bytes() == b'seed'


def test_builtin_owns_recolors_before_render_and_cleans_on_cancel(tmp_path, monkeypatch):
    setup = FirstRunSetup(tmp_path, tmp_path / 'MexCLI.exe')
    seen = []

    def render(stage, recolors, progress):
        record = jobs.list_jobs(kind=routes.BUILTIN_KIND)[0]
        assert record['owned']['recolors'] == str(recolors)
        seen.append(recolors)
        (recolors / 'partial.dat').write_bytes(b'partial')
        jobs.cancel(record['id'])
        progress('render', 20, 'Next costume', 1, 4)
        pytest.fail('Cancellation did not stop the next costume')

    monkeypatch.setattr(setup, '_build_giga', render)
    monkeypatch.setattr(setup, 'build_builtin_character',
                        lambda slug, progress, job: setup._build_giga_from_stage(tmp_path, progress, job=job))
    record = jobs.run_inline(routes.BUILTIN_KIND,
                            lambda job: routes.run_builtin_setup(job, setup, 'giga-bowser'))
    assert record['status'] == 'cancelled'
    assert seen and not seen[0].exists()


def test_builtin_unsuccessful_build_fails_record():
    class Setup:
        def build_builtin_character(self, slug, progress, job):
            return {'success': False, 'error': 'Missing seed'}
    record = jobs.run_inline(routes.BUILTIN_KIND,
                            lambda job: routes.run_builtin_setup(job, Setup(), 'giga-bowser'))
    assert record['status'] == 'failed' and record['error'] == 'Missing seed'


def test_builtin_start_returns_id_and_rejects_overlap(monkeypatch):
    class Setup:
        def builtin_pending_characters(self):
            return [{'slug': 'giga-bowser', 'name': 'Giga Bowser', 'costume_count': 4}]
    class Never:
        def __init__(self, **kwargs): pass
        def start(self): pass
    monkeypatch.setattr(routes, '_first_run_setup', Setup)
    monkeypatch.setattr(jobs.threading, 'Thread', Never)
    app = Flask(__name__)
    app.register_blueprint(routes.custom_characters_bp)
    client = app.test_client()
    url = '/api/mex/custom-characters/builtins/giga-bowser/setup'
    first = client.post(url)
    assert first.status_code == 200
    assert jobs.get(first.json['job_id'])['kind'] == routes.BUILTIN_KIND
    second = client.post(url)
    assert second.status_code == 409
    assert second.json['job_id'] == first.json['job_id']
    assert client.get(url + '/status').status_code == 404
