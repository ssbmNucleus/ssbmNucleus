"""Restore Vanilla Background (tracker #95).

Installing a CSS background rewrites the background inside the project's
MnSlChr.usd and adds the "Disable Hardcoded CSS BG Anim" code, with no backup.
The restore route re-imports the vanilla background (exported from the vanilla
MnSlChr.usd) into the project's file, drops that code while keeping every other
one, and clears the per-project "installed" record.
"""
import json
import subprocess
from pathlib import Path

from flask import Flask

from vault.routes.menus import menus_bp
from vault.menus import installed as helpers
from projects.routes.menus import backgrounds as project_backgrounds


CODES_INI = (
    "$!Some Other Code\n04000000 60000000\n"
    "$!Disable Hardcoded CSS BG Anim\n04263384 48000010\n"
)


def _setup(tmp_path, monkeypatch):
    project = tmp_path / 'proj'
    files = project / 'files'
    files.mkdir(parents=True)
    mexproj = project / 'project.mexproj'
    mexproj.write_text('{}')
    (files / 'MnSlChr.usd').write_bytes(b'CUSTOM')
    (files / 'codes.ini').write_text(CODES_INI)
    (project / helpers.INSTALLED_MENUS_FILE).write_text(json.dumps({'installed': {
        'css:background': {'id': 'bg1', 'name': 'Crashy'},
        'css:doors': {'id': 'd1', 'name': 'Doors'},
    }}))

    vanilla = tmp_path / 'vanilla' / 'MnSlChr.usd'
    vanilla.parent.mkdir()
    vanilla.write_bytes(b'VANILLA')

    monkeypatch.setattr(project_backgrounds, 'get_current_project_path', lambda: mexproj)
    monkeypatch.setattr(project_backgrounds, 'get_project_files_dir', lambda: files)
    monkeypatch.setattr('core.state.get_current_project_path', lambda: mexproj)
    fake_exe = tmp_path / 'fake.exe'
    fake_exe.write_text('')
    monkeypatch.setattr(project_backgrounds, 'HSDRAW_EXE', fake_exe)
    monkeypatch.setattr(project_backgrounds, 'MEXCLI_PATH', fake_exe)
    monkeypatch.setattr('shared.vanilla_extract.vanilla_refs.ensure_vanilla_ref',
                        lambda name, *a, **k: vanilla if name == 'MnSlChr.usd' else None)

    hsd_calls = []

    def fake_hsd(args, timeout=120):
        hsd_calls.append(list(args))
        if args[1] == 'export':
            (Path(args[3]) / 'background.dat').write_bytes(Path(args[2]).read_bytes() + b'-BG')
        else:  # import <project> <bg.dat> <out>
            Path(args[4]).write_bytes(Path(args[3]).read_bytes() + b'-IN-PROJECT')
        return object()

    monkeypatch.setattr(project_backgrounds, '_run_hsd_cli', fake_hsd)

    synced = {}

    def fake_run(cmd, **kwargs):
        assert cmd[1] == 'sync-codes'
        text = Path(cmd[3]).read_text()
        synced['ini'] = text
        (files / 'codes.ini').write_text(text)
        return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')

    monkeypatch.setattr(project_backgrounds.subprocess, 'run', fake_run)

    app = Flask(__name__)
    app.register_blueprint(menus_bp)
    return app.test_client(), project, files, hsd_calls, synced


def test_restore_vanilla_css_background(tmp_path, monkeypatch):
    client, project, files, hsd_calls, synced = _setup(tmp_path, monkeypatch)

    assert client.get('/api/mex/menus/css/background/status').get_json()['custom'] is True

    resp = client.post('/api/mex/menus/css/background/restore-vanilla')
    body = resp.get_json()
    assert resp.status_code == 200, body
    assert body['success'] and body['codeRemoved']

    # Vanilla background exported, then imported into the PROJECT's file with its scene.
    assert hsd_calls[0][:2] == ['--css-bg', 'export']
    assert hsd_calls[1][:2] == ['--css-bg', 'import']
    assert hsd_calls[1][2] == str(files / 'MnSlChr.usd')
    assert '--include-scene' in hsd_calls[1]
    assert (files / 'MnSlChr.usd').read_bytes() == b'VANILLA-BG-IN-PROJECT'

    # Only the background's code is dropped.
    assert 'Disable Hardcoded CSS BG Anim' not in synced['ini']
    assert '$!Some Other Code' in synced['ini']

    # Record cleared for the CSS background only.
    installed = json.loads((project / helpers.INSTALLED_MENUS_FILE).read_text())['installed']
    assert 'css:background' not in installed and 'css:doors' in installed

    assert client.get('/api/mex/menus/css/background/status').get_json()['custom'] is False


def test_restore_needs_a_vanilla_iso(tmp_path, monkeypatch):
    client, _project, files, _calls, _synced = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr('shared.vanilla_extract.vanilla_refs.ensure_vanilla_ref', lambda *a, **k: None)
    resp = client.post('/api/mex/menus/css/background/restore-vanilla')
    assert resp.status_code == 400
    assert (files / 'MnSlChr.usd').read_bytes() == b'CUSTOM'
