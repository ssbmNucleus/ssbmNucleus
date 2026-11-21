from tests.paths import BACKEND
import builtins
import hashlib
import io
import os
import shutil
import sys
import time
import uuid
import zipfile
from pathlib import Path

import pytest
from flask import Flask


BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

import importlib.util

# The logs zip and the bug-report worker settings the setup routes use.
from shared.diagnostics import bug_report  # noqa: E402
from core import jobs  # noqa: E402


def _load_setup_module():
    module_name = 'nucleus_setup_blueprint_test'
    module_path = BACKEND_DIR / 'shared' / 'routes' / 'setup.py'
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def setup_module():
    module = _load_setup_module()
    module.clear_iso_verification_cache()
    yield module
    module.clear_iso_verification_cache()


@pytest.fixture
def workspace_iso_dir():
    temp_dir = BACKEND_DIR.parent / 'storage' / 'pytest_setup_blueprint' / uuid.uuid4().hex
    temp_dir.mkdir(parents=True, exist_ok=True)
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def job_records(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, '_root_override', tmp_path / 'jobs')
    monkeypatch.setattr(jobs, '_jobs', {})


def _run_setup_job(client, iso):
    """Start setup and wait for its job (core/jobs.py) to end; the record is
    the only place a rejected ISO's reason lands."""
    resp = client.post('/api/mex/setup/start', json={'isoPath': str(iso)})
    assert resp.status_code == 200
    job_id = resp.get_json()['jobId']
    deadline = time.monotonic() + 5
    while not jobs.get(job_id).get('ended_at'):
        assert time.monotonic() < deadline, jobs.get(job_id)
        time.sleep(0.005)
    return jobs.get(job_id)


def test_verify_iso_file_uses_cache_until_metadata_changes(workspace_iso_dir, monkeypatch, setup_module):
    iso_bytes = b'nucleus-test-iso'
    iso_path = workspace_iso_dir / 'GALE01.iso'
    iso_path.write_bytes(iso_bytes)
    monkeypatch.setattr(setup_module, 'VANILLA_ISO_MD5', hashlib.md5(iso_bytes).hexdigest())

    real_open = builtins.open
    open_calls = {'count': 0}

    def counting_open(file, mode='r', *args, **kwargs):
        if 'rb' in mode and Path(file).resolve() == iso_path.resolve():
            open_calls['count'] += 1
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, 'open', counting_open)

    first = setup_module.verify_iso_file(iso_path)
    second = setup_module.verify_iso_file(iso_path)

    assert first['valid'] is True
    assert first['cached'] is False
    assert second['valid'] is True
    assert second['cached'] is True
    assert open_calls['count'] == 1

    stat = iso_path.stat()
    os.utime(iso_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    third = setup_module.verify_iso_file(iso_path)

    assert third['valid'] is True
    assert third['cached'] is False
    assert open_calls['count'] == 2


def _write_fake_iso(path, size, game_id=b'GALE01', version=0x02, head=None):
    """A file whose disc header (game ID, version, GameCube magic) matches
    Melee, padded to `size`. `head` replaces the first bytes outright."""
    header = bytearray(0x20)
    header[:6] = game_id
    header[7] = version
    header[0x1C:0x20] = b'\xc2\x33\x9f\x3d'
    with open(path, 'wb') as f:
        f.write(head if head is not None else header)
        if size > 0x20:
            f.seek(size - 1)
            f.write(b'\x00')


def test_name_score_prefers_vanilla_over_mod_names(setup_module):
    score = setup_module._vanilla_name_score
    assert score(Path('Melee.iso')) > score(Path('acebuild.iso'))
    assert score(Path('vanilla.iso')) > score(Path('z20XX 4.05 Corona Beginnings.iso'))
    assert score(Path('SSBM.iso')) > score(Path('Akaneia Build.iso'))


def test_finds_vanilla_among_mods_and_hashes_likely_one_first(workspace_iso_dir, monkeypatch, setup_module):
    """A modded build shares vanilla's header+size, so we must MD5 — but the
    vanilla-looking name is hashed FIRST and we early-exit, so the modded
    acebuild.iso is never hashed (the bug: header-only picked the mod)."""
    size = 4096
    monkeypatch.setattr(setup_module, 'VANILLA_ISO_EXPECTED_SIZE', size)

    vanilla = workspace_iso_dir / 'Melee.iso'
    mod = workspace_iso_dir / 'acebuild.iso'
    _write_fake_iso(vanilla, size)
    # give the mod distinct bytes so its md5 differs from vanilla's
    _write_fake_iso(mod, size)
    with open(mod, 'r+b') as f:
        f.seek(16)
        f.write(b'MODDEDBYTES')

    monkeypatch.setattr(setup_module, 'VANILLA_ISO_MD5',
                        hashlib.md5(vanilla.read_bytes()).hexdigest())

    hashed = []
    real_verify = setup_module.verify_iso_file

    def tracking_verify(p):
        hashed.append(Path(p).name)
        return real_verify(p)

    monkeypatch.setattr(setup_module, 'verify_iso_file', tracking_verify)

    found = setup_module.find_vanilla_melee_iso(str(workspace_iso_dir))
    assert found == str(vanilla)
    assert hashed == ['Melee.iso']  # early-exit: mod never hashed


def test_scan_skips_non_melee_header(workspace_iso_dir, monkeypatch, setup_module):
    size = 4096
    monkeypatch.setattr(setup_module, 'VANILLA_ISO_EXPECTED_SIZE', size)
    # Right size, wrong game id -> must be ignored before any hashing.
    _write_fake_iso(workspace_iso_dir / 'OtherGame.iso', size, game_id=b'GZLE01')

    found = setup_module.find_vanilla_melee_iso(str(workspace_iso_dir))
    assert found is None


def _nkit_head():
    head = bytearray(0x204)
    head[:6] = b'GALE01'
    head[7] = 0x02
    head[0x1C:0x20] = b'\xc2\x33\x9f\x3d'
    head[0x200:0x204] = b'NKIT'
    return bytes(head)


@pytest.mark.parametrize('name, kwargs, size, reason, says', [
    ('a.rvz', {'head': b'RVZ\x01' + bytes(60)}, 4096, 'compressed', 'Convert File'),
    ('a.gcz', {'head': b'\x01\xc0\x0b\xb1' + bytes(60)}, 4096, 'compressed', 'GCZ'),
    ('a.ciso', {'head': b'CISO' + bytes(60)}, 4096, 'compressed', 'full, uncompressed 1.02 dump'),
    ('a.nkit.iso', {'head': _nkit_head()}, 4096, 'nkit', 'NKit'),
    ('notes.iso', {'head': b'hello world' * 10}, 4096, 'not_gamecube', 'not a GameCube'),
    ('pal.iso', {'game_id': b'GALP01'}, 4096, 'wrong_game', 'another region of Melee'),
    ('zelda.iso', {'game_id': b'GZLE01'}, 4096, 'wrong_game', 'a different game'),
    ('v100.iso', {'version': 0x00}, 4096, 'wrong_version', 'NTSC 1.00'),
    ('trim.iso', {}, 2048, 'trimmed', 'trimmed'),
    ('ok.iso', {}, 4096, None, None),
])
def test_disc_shape_problem_names_the_format(workspace_iso_dir, monkeypatch, setup_module,
                                             name, kwargs, size, reason, says):
    monkeypatch.setattr(setup_module, 'VANILLA_ISO_EXPECTED_SIZE', 4096)
    path = workspace_iso_dir / name
    _write_fake_iso(path, size, **kwargs)
    problem = setup_module._disc_shape_problem(path)
    if reason is None:
        assert problem is None
    else:
        assert problem[0] == reason
        assert says in problem[1]


def _deny_reads(monkeypatch, target):
    """Make opening `target` fail the way macOS privacy (TCC) refuses it."""
    real_open = builtins.open

    def denying_open(file, mode='r', *args, **kwargs):
        if Path(file).resolve() == Path(target).resolve():
            raise PermissionError(1, 'Operation not permitted', str(file))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, 'open', denying_open)


def test_unreadable_iso_is_reported_as_unreadable_not_invalid(workspace_iso_dir, monkeypatch,
                                                              setup_module, job_records):
    iso = workspace_iso_dir / 'Melee.iso'
    _write_fake_iso(iso, 4096)
    _deny_reads(monkeypatch, iso)
    monkeypatch.setattr(setup_module, 'FirstRunSetup', lambda *_a: type(
        'S', (), {'check_setup_needed': lambda self: {'complete': True}})())
    client = _bugreport_app(setup_module)

    resp = client.post('/api/mex/verify-iso', json={'isoPath': str(iso)})
    assert resp.status_code == 403
    body = resp.get_json()
    assert body['reason'] == 'unreadable'
    assert 'Operation not permitted' in body['error']

    record = _run_setup_job(client, iso)
    assert record['status'] == 'failed'
    assert record['extra']['reason'] == 'unreadable'
    assert 'Operation not permitted' in record['error']

    problems = client.post('/api/mex/setup/health', json={'isoPath': str(iso)}).get_json()['problems']
    assert [p['id'] for p in problems] == ['iso_unreadable']
    assert 'Operation not permitted' in problems[0]['message']


def test_unreadable_message_tells_mac_users_where_to_allow_access(monkeypatch, setup_module):
    err = PermissionError(1, 'Operation not permitted', '/Users/x/Downloads/Melee.iso')
    monkeypatch.setattr(setup_module.sys, 'platform', 'darwin')
    reason, message = setup_module._unreadable_problem(err)
    assert reason == 'unreadable'
    assert 'Operation not permitted' in message
    assert 'Privacy & Security > Files and Folders' in message


def test_setup_start_explains_a_modified_102_disc(workspace_iso_dir, monkeypatch, setup_module,
                                                  job_records):
    monkeypatch.setattr(setup_module, 'VANILLA_ISO_EXPECTED_SIZE', 4096)
    iso = workspace_iso_dir / 'Melee.iso'
    _write_fake_iso(iso, 4096)

    record = _run_setup_job(_bugreport_app(setup_module), iso)
    assert record['status'] == 'failed'
    assert record['extra']['reason'] == 'modified'
    assert record['extra']['md5'] == hashlib.md5(iso.read_bytes()).hexdigest()
    assert 'modded build or a scrubbed dump' in record['error']


def test_scan_raises_for_an_unlistable_folder(workspace_iso_dir, monkeypatch, setup_module):
    """glob() reported a refused folder as empty ("no ISO found"); the scan
    must surface the refusal so auto-detect can say why."""
    def refuse(self):
        raise PermissionError(1, 'Operation not permitted', str(self))

    monkeypatch.setattr(Path, 'iterdir', refuse)
    with pytest.raises(PermissionError):
        setup_module.find_vanilla_melee_iso(str(workspace_iso_dir))


def test_logs_zip_bundles_logs_and_diagnostics(tmp_path, monkeypatch, setup_module):
    logs = tmp_path / 'logs'
    logs.mkdir()
    (logs / 'mex_api.log').write_text('hello log', encoding='utf-8')
    (logs / 'csp_generation.log').write_text('csp log', encoding='utf-8')
    monkeypatch.setattr(bug_report, 'LOGS_PATH', logs)

    app = Flask(__name__)
    app.register_blueprint(setup_module.setup_bp)
    resp = app.test_client().get('/api/mex/logs/download')

    assert resp.status_code == 200
    assert resp.mimetype == 'application/zip'
    with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
        names = set(zf.namelist())
        assert 'diagnostics.txt' in names
        assert 'logs/mex_api.log' in names
        assert 'logs/csp_generation.log' in names
        assert zf.read('logs/mex_api.log') == b'hello log'


def test_logs_zip_ok_when_logs_dir_missing(tmp_path, monkeypatch, setup_module):
    """Even with no logs folder the zip still builds (carries diagnostics)."""
    monkeypatch.setattr(bug_report, 'LOGS_PATH', tmp_path / 'nonexistent')
    app = Flask(__name__)
    app.register_blueprint(setup_module.setup_bp)
    resp = app.test_client().get('/api/mex/logs/download')

    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
        assert 'diagnostics.txt' in zf.namelist()


def test_logs_zip_includes_slippi_dolphin_logs(tmp_path, monkeypatch, setup_module):
    """When a slippiPath is given, Dolphin's logs + crash dumps come along, but
    replays/ISOs in the User tree are NOT swept in."""
    monkeypatch.setattr(bug_report, 'LOGS_PATH', tmp_path / 'applogs')

    slippi = tmp_path / 'Slippi Launcher' / 'netplay'
    (slippi / 'User' / 'Logs').mkdir(parents=True)
    (slippi / 'User' / 'Slippi').mkdir(parents=True)  # replays — must be ignored
    (slippi / 'User' / 'Logs' / 'dolphin.log').write_text('dolphin crashed', encoding='utf-8')
    (slippi / 'User' / 'exception.dmp').write_bytes(b'DMP')
    (slippi / 'User' / 'Slippi' / 'Game_20260101.slp').write_bytes(b'REPLAY')
    (slippi.parent / 'launcher.log').write_text('launcher', encoding='utf-8')
    # Dolphin distro .txt files at the netplay root — not logs, must be skipped.
    (slippi / 'license.txt').write_text('GPL', encoding='utf-8')
    (slippi / 'portable.txt').write_text('', encoding='utf-8')

    app = Flask(__name__)
    app.register_blueprint(setup_module.setup_bp)
    resp = app.test_client().get(f'/api/mex/logs/download?slippiPath={slippi}')

    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
        names = set(zf.namelist())
        assert 'slippi-dolphin/Logs/dolphin.log' in names
        assert 'slippi-dolphin/User/exception.dmp' in names
        assert 'slippi-dolphin/launcher/launcher.log' in names
        # the replay must NOT be in the zip
        assert not any(n.endswith('.slp') for n in names)
        # Dolphin distro files must NOT be in the zip
        assert not any(n.endswith(('license.txt', 'portable.txt')) for n in names)


def test_logs_zip_denylists_dolphin_distro_files_and_notes_logging_off(tmp_path, monkeypatch, setup_module):
    """A Slippi folder holding only Dolphin's distro .txt files (license.txt,
    portable.txt) has no real logs: those files must not be bundled or counted,
    and diagnostics must report 0 and tell the reporter to enable Dolphin's
    'Write to File' logging."""
    monkeypatch.setattr(bug_report, 'LOGS_PATH', tmp_path / 'applogs')

    slippi = tmp_path / 'Slippi Launcher' / 'netplay'
    slippi.mkdir(parents=True)
    (slippi / 'license.txt').write_text('GPL', encoding='utf-8')
    (slippi / 'portable.txt').write_text('', encoding='utf-8')

    app = Flask(__name__)
    app.register_blueprint(setup_module.setup_bp)
    resp = app.test_client().get(f'/api/mex/logs/download?slippiPath={slippi}')

    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
        names = set(zf.namelist())
        assert not any(n.startswith('slippi-dolphin/') for n in names)
        diag = zf.read('diagnostics.txt').decode('utf-8')
    assert 'Slippi log/dump files: 0' in diag
    assert 'Write to File' in diag


# ---------------------------------------------------------------------------
# Bug report: redaction, budget, and the submit route
# ---------------------------------------------------------------------------

def test_redact_log_text_masks_usernames_and_tokens(setup_module):
    home = str(Path.home())
    text = '\n'.join([
        f"loaded iso from {home}" + r"\melee\game.iso",
        r"other user C:\Users\someone.else\AppData\Local\SSBM Nucleus",
        "linux /home/bob/.melee-nexus and mac /Users/carol/Library",
        "GET /cb?token=sekrit-value&x=1",
        "Authorization: Bearer abcdef123456789.zzz",
        '{"access_token": "eyJJJJ", "refresh_token": "rrrr"}',
    ])
    out = bug_report._redact_log_text(text)
    username = Path.home().name
    assert home not in out
    # own home collapses to ~, foreign homes keep structure with <user>
    assert r'~\melee\game.iso' in out
    assert 'someone.else' not in out
    assert r'C:\Users\<user>\AppData' in out
    assert '/home/<user>/' in out and '/Users/<user>/' in out
    assert 'sekrit-value' not in out and 'token=***' in out
    assert 'abcdef123456789.zzz' not in out and 'Bearer ***' in out
    assert 'eyJJJJ' not in out and 'rrrr' not in out
    # sanity: plain text untouched
    assert bug_report._redact_log_text('hello log') == 'hello log'


def test_redact_log_text_masks_all_observed_leak_shapes(setup_module):
    # Every shape here leaked a raw username in real report bugreport-968a8ba8.
    # "Denzel" is deliberately not the local username: the path regex alone must
    # catch these, without help from the local-home replace or username scrub.
    lines = [
        # mexcli.project command echo
        r"Running MexCLI command: C:\Users\Denzel\AppData\Local\Programs\SSBM Nucleus\resources\utility\mex\mexcli.exe info C:\Users\Denzel\AppData\Local\SSBM Nucleus\projects\Build\project.mexproj",
        # xdelta3 command line
        r'xdelta3 -d -s "C:\Users\Denzel\AppData\Local\SSBM Nucleus\vanilla.iso" patch.xdelta out.iso',
        # JSON blob with escaped backslashes
        '"isoPath": "C:\\\\Users\\\\Denzel\\\\Documents\\\\SSBM\\\\Super Smash Bros. Melee.iso",',
        # JSON-in-JSON (electron-diagnostics stdout echo of a werkzeug line)
        '"[stdout] GET /api/mex/texture-pack/stats?slippiPath=C:\\\\\\\\Users\\\\\\\\Denzel\\\\\\\\AppData HTTP/1.1"',
        # projects.routes.project log lines
        r"2026-08-22 16:07:54,988 - projects.routes.project - INFO - ISO Path: C:\Users\Denzel\Documents\SSBM\Super Smash Bros. Melee.iso",
        r"2026-08-22 14:59:28,312 - projects.routes.export - INFO - Saved ISO to C:\Users\Denzel\Documents\SSBM\Build.iso (1392.3 MB)",
    ]
    for line in lines:
        out = bug_report._redact_log_text(line)
        assert 'Denzel' not in out, line
        assert '<user>' in out, line
    # escaped-backslash form keeps its JSON escaping intact
    out = bug_report._redact_log_text(lines[2])
    assert 'C:\\\\Users\\\\<user>\\\\Documents' in out


def test_logs_zip_redacts_rotated_logs_and_extra_files(tmp_path, monkeypatch, setup_module):
    logs = tmp_path / 'logs'
    logs.mkdir()
    leak = r'Saved ISO to C:\Users\Denzel\Documents\SSBM\Build.iso'
    (logs / 'mex_api_20260822.log.1').write_text(leak, encoding='utf-8')
    monkeypatch.setattr(bug_report, 'LOGS_PATH', logs)

    extra = {'electron-diagnostics.json':
             '{"userData": "C:\\\\Users\\\\Denzel\\\\AppData\\\\Roaming\\\\ssbm-nucleus"}'}
    buf, added, _, _ = bug_report._build_logs_zip(extra_files=extra)
    assert added == 1
    with zipfile.ZipFile(buf) as zf:
        rotated = zf.read('logs/mex_api_20260822.log.1').decode('utf-8')
        assert 'Denzel' not in rotated and r'C:\Users\<user>' in rotated
        electron = zf.read('electron-diagnostics.json').decode('utf-8')
        assert 'Denzel' not in electron and 'C:\\\\Users\\\\<user>' in electron


def test_logs_zip_redacts_text_logs(tmp_path, monkeypatch, setup_module):
    logs = tmp_path / 'logs'
    logs.mkdir()
    home = str(Path.home())
    (logs / 'mex_api.log').write_text(f'opened {home}' + r'\x.iso' + ' token=abc123', encoding='utf-8')
    (logs / 'crash.dmp').write_bytes(b'BINARY' + home.encode())  # binaries untouched
    monkeypatch.setattr(bug_report, 'LOGS_PATH', logs)

    app = Flask(__name__)
    app.register_blueprint(setup_module.setup_bp)
    resp = app.test_client().get('/api/mex/logs/download')

    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
        log_text = zf.read('logs/mex_api.log').decode('utf-8')
        assert home not in log_text and 'abc123' not in log_text
        assert zf.read('logs/crash.dmp').startswith(b'BINARY')  # bytes preserved
        diag = zf.read('diagnostics.txt').decode('utf-8')
        assert home not in diag
        assert 'Redaction:' in diag


def test_build_logs_zip_budget_keeps_newest(tmp_path, monkeypatch, setup_module):
    logs = tmp_path / 'logs'
    logs.mkdir()
    old = logs / 'old.log'
    new = logs / 'new.log'
    old.write_text('o' * 4000, encoding='utf-8')
    new.write_text('n' * 4000, encoding='utf-8')
    os.utime(old, (1_000_000, 1_000_000))
    os.utime(new, (2_000_000, 2_000_000))
    monkeypatch.setattr(bug_report, 'LOGS_PATH', logs)

    buf, added, _, truncated = bug_report._build_logs_zip(budget_bytes=5000)
    with zipfile.ZipFile(buf) as zf:
        names = set(zf.namelist())
    assert added == 1 and truncated is True
    assert 'logs/new.log' in names and 'logs/old.log' not in names


def _bugreport_app(setup_module):
    app = Flask(__name__)
    app.register_blueprint(setup_module.setup_bp)
    return app.test_client()


class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._payload = payload

    def json(self):
        return self._payload


def test_bugreport_passes_426_through(tmp_path, monkeypatch, setup_module):
    monkeypatch.setattr(bug_report, 'LOGS_PATH', tmp_path / 'logs')
    monkeypatch.setenv('NUCLEUS_APP_VERSION', '0.1.0')
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs)
        return _FakeResp(426, {'error': 'outdated', 'latest': '9.9.9', 'url': 'https://x/dl'})

    monkeypatch.setattr(setup_module.requests, 'post', fake_post)
    resp = _bugreport_app(setup_module).post('/api/mex/bugreport', json={'description': 'it broke'})
    assert resp.status_code == 426
    data = resp.get_json()
    assert data['success'] is False
    assert data['error'] == 'update_required'
    assert data['latest'] == '9.9.9' and data['url'] == 'https://x/dl'
    assert calls, 'worker POST should have been attempted'


def test_bugreport_requires_description(tmp_path, monkeypatch, setup_module):
    monkeypatch.setattr(bug_report, 'LOGS_PATH', tmp_path / 'logs')
    resp = _bugreport_app(setup_module).post('/api/mex/bugreport', json={})
    assert resp.status_code == 400


def test_bugreport_happy_path_uploads_zip(tmp_path, monkeypatch, setup_module):
    logs = tmp_path / 'logs'
    logs.mkdir()
    (logs / 'mex_api.log').write_text('boom', encoding='utf-8')
    monkeypatch.setattr(bug_report, 'LOGS_PATH', logs)
    monkeypatch.setenv('NUCLEUS_APP_VERSION', '0.7.1')
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen['meta'] = json
        assert json['zip_size'] > 0 and json['description'] == 'it broke'
        return _FakeResp(200, {'id': 'a' * 32, 'max_zip_bytes': 1 << 26})

    def fake_put(url, data=None, headers=None, timeout=None):
        seen['url'] = url
        seen['zip'] = data
        assert len(data) == seen['meta']['zip_size']
        return _FakeResp(200, {'ok': True, 'id': 'a' * 32, 'notified': True})

    monkeypatch.setattr(setup_module.requests, 'post', fake_post)
    monkeypatch.setattr(setup_module.requests, 'put', fake_put)
    resp = _bugreport_app(setup_module).post('/api/mex/bugreport', json={
        'description': 'it broke',
        'contact': 'me#123',
        'renderer_errors': [{'ts': 't', 'message': 'x'}],
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True and data['id'] == 'a' * 32 and data['notified'] is True
    assert seen['url'].endswith(f"/{'a' * 32}/zip")
    with zipfile.ZipFile(io.BytesIO(seen['zip'])) as zf:
        names = set(zf.namelist())
        assert {'diagnostics.txt', 'report.json', 'renderer-errors.json', 'logs/mex_api.log'} <= names
