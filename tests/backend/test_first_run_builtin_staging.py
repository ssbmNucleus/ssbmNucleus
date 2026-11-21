"""First-run setup stages built-in fighters instead of rendering them.

Rendering Giga Bowser (4 CSPs, 3 texture recolors, 4 stock icons) added minutes
to first-run setup for a character most users never open. Setup now only parks
the inputs in storage/builtin_seed/; the Custom Characters page builds him on
the first click.
"""

from tests.paths import BACKEND
import ast
import hmac
import io
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from flask import Blueprint, Flask, jsonify, request, send_file


BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

from shared.vanilla_extract.first_run_setup import FirstRunSetup


def _fake_project(temp_project: Path) -> None:
    fighters = temp_project / 'data' / 'fighters'
    files = temp_project / 'files'
    assets = temp_project / 'assets' / 'csp'
    fighters.mkdir(parents=True)
    files.mkdir(parents=True)
    assets.mkdir(parents=True)
    (temp_project / 'temp_project.mexproj').write_text('{}', encoding='utf-8')

    (fighters / '031.json').write_text(json.dumps({
        'name': 'Giga Bowser',
        'files': {'fighterDataPath': 'PlGk.dat', 'animFile': 'PlGkAJ.dat'},
        'costumes': [{'file': {'fileName': 'PlGkNr.dat'}}],
    }), encoding='utf-8')
    # Giga borrows Bowser's demo/result/Kirby-hat files when patched.
    (fighters / '005.json').write_text(json.dumps({
        'name': 'Bowser',
        'files': {'demoFile': 'PlKpDViWaitAJ.dat', 'rstAnimFile': 'GmRstMKp.dat'},
        'costumes': [{'file': {'fileName': 'PlKpNr.dat'}}],
    }), encoding='utf-8')

    for name in ('PlGkNr.dat', 'PlGk.dat', 'PlGkAJ.dat',
                 'PlKpDViWaitAJ.dat', 'GmRstMKp.dat'):
        (files / name).write_bytes(name.encode())
    (assets / 'csp_025.png').write_bytes(b'bowser-csp')


def _setup(tmp_path: Path) -> FirstRunSetup:
    project_root = tmp_path / 'project'
    (project_root / 'storage').mkdir(parents=True)
    return FirstRunSetup(
        project_root,
        tmp_path / 'mexcli.exe',
        storage_path=project_root / 'storage',
    )


def _fake_export(monkeypatch):
    """Stand in for `mexcli export-fighter`, which writes the fighter package."""
    def fake_run(cmd, *args, **kwargs):
        zip_path = Path(cmd[4])
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr('fighter.json', '{}')
            with zf.open('PlGkNr.zip', 'w') as inner:
                with zipfile.ZipFile(inner, 'w') as costume:
                    costume.writestr('PlGkNr.dat', 'PlGkNr.dat')
        return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')
    monkeypatch.setattr(subprocess, 'run', fake_run)


def test_setup_stages_builtin_without_rendering(tmp_path, monkeypatch):
    temp_project = tmp_path / 'temp-project'
    _fake_project(temp_project)
    setup = _setup(tmp_path)
    _fake_export(monkeypatch)

    result = setup.stage_builtin_giga_bowser(temp_project)

    assert result == {'success': True, 'staged': True}
    stage = setup._builtin_stage_dir(setup.BUILTIN_GIGA_SLUG)
    assert (stage / 'fighter.zip').is_file()
    assert json.loads((stage / 'fighter.json').read_text())['name'] == 'Giga Bowser'
    assert (stage / 'base_fighter.json').is_file()
    # The costume model, the ftData the CSP renderer needs beside it, and the
    # files the build step re-injects -- including Bowser's, which only the
    # PATCHED fighter data names.
    for name in ('PlGkNr.dat', 'PlGk.dat', 'PlGkAJ.dat',
                 'PlKpDViWaitAJ.dat', 'GmRstMKp.dat'):
        assert (stage / 'files' / name).is_file(), name
    assert (stage / 'assets' / 'csp_fallback.png').read_bytes() == b'bowser-csp'
    # Nothing rendered, nothing installed: the vault is still empty.
    assert not (setup.project_root / 'storage' / 'custom_characters').exists()
    assert setup._read_metadata()['custom_characters'] == []


def test_staged_builtin_is_pending_until_built(tmp_path, monkeypatch):
    temp_project = tmp_path / 'temp-project'
    _fake_project(temp_project)
    setup = _setup(tmp_path)
    _fake_export(monkeypatch)

    assert setup.builtin_pending_characters() == []

    setup.stage_builtin_giga_bowser(temp_project)

    pending = setup.builtin_pending_characters()
    assert [c['slug'] for c in pending] == [setup.BUILTIN_GIGA_SLUG]
    assert pending[0]['pending_setup'] is True
    assert pending[0]['costume_count'] == len(setup.BUILTIN_GIGA_COSTUMES)


def _fake_finished_seed(setup: FirstRunSetup) -> None:
    """The vault state a completed build leaves behind."""
    char_dir = setup.project_root / 'storage' / 'custom_characters' / setup.BUILTIN_GIGA_SLUG
    char_dir.mkdir(parents=True, exist_ok=True)
    (char_dir / 'fighter.json').write_text(json.dumps({
        'costumes': [{'file': {'fileName': f"PlGk{spec['code']}.dat"}}
                     for spec in setup.BUILTIN_GIGA_COSTUMES],
        'redCostumeIndex': 1, 'blueCostumeIndex': 2, 'greenCostumeIndex': 3,
    }), encoding='utf-8')
    with zipfile.ZipFile(char_dir / 'fighter.zip', 'w') as zf:
        for spec in setup.BUILTIN_GIGA_COSTUMES:
            stem = f"PlGk{spec['code']}"
            with zf.open(f'{stem}.zip', 'w') as inner:
                with zipfile.ZipFile(inner, 'w') as costume:
                    costume.writestr(f'{stem}.dat', stem)
    setup._write_metadata({'custom_characters': [
        {'slug': setup.BUILTIN_GIGA_SLUG, 'name': 'Giga Bowser',
         'source': 'builtin', 'builtin': True},
    ]})


def test_built_builtin_is_no_longer_offered(tmp_path, monkeypatch):
    temp_project = tmp_path / 'temp-project'
    _fake_project(temp_project)
    setup = _setup(tmp_path)
    _fake_export(monkeypatch)
    setup.stage_builtin_giga_bowser(temp_project)
    _fake_finished_seed(setup)

    assert setup.builtin_pending_characters() == []
    # A repeat setup run leaves the finished character alone.
    assert setup.stage_builtin_giga_bowser(temp_project) == {
        'success': True, 'staged': False, 'reason': 'already_present',
    }
    # ...and a repeat build request is a no-op that keeps the staged inputs.
    assert setup.build_builtin_character(setup.BUILTIN_GIGA_SLUG) == {
        'success': True, 'seeded': False, 'reason': 'already_present',
    }
    assert (setup._builtin_stage_dir(setup.BUILTIN_GIGA_SLUG) / 'fighter.zip').is_file()


def test_deleted_builtin_is_offered_again(tmp_path, monkeypatch):
    """Discord 2026-09-18: deleting Giga Bowser after building him made him
    impossible to build again. The staged inputs can only be produced from the
    extracted vanilla project during first-run setup, so a build must not
    delete them; after a delete the greyed-out card comes back."""
    temp_project = tmp_path / 'temp-project'
    _fake_project(temp_project)
    setup = _setup(tmp_path)
    _fake_export(monkeypatch)
    setup.stage_builtin_giga_bowser(temp_project)
    _fake_finished_seed(setup)
    assert setup.builtin_pending_characters() == []
    # Clicking the card again while he is installed must not consume the seed.
    assert setup.build_builtin_character(setup.BUILTIN_GIGA_SLUG)['success'] is True

    # What the delete route does: drop the folder and the metadata entry.
    shutil.rmtree(setup.storage_path / 'custom_characters' / setup.BUILTIN_GIGA_SLUG)
    setup._write_metadata({'custom_characters': []})

    assert [c['slug'] for c in setup.builtin_pending_characters()] == [setup.BUILTIN_GIGA_SLUG]


def test_build_refuses_unknown_or_unstaged_builtin(tmp_path):
    setup = _setup(tmp_path)

    assert setup.build_builtin_character('marth')['success'] is False
    result = setup.build_builtin_character(setup.BUILTIN_GIGA_SLUG)
    assert result['success'] is False
    assert 'not staged' in result['error']


def _icon_app(characters_path):
    """Actual icon route + production auth middleware, without app startup."""
    app = Flask(__name__)
    scope = dict(app=app, hmac=hmac, request=request, jsonify=jsonify,
                 send_file=send_file, _backend_token='builtin-icon-test-token',
                 _PUBLIC_MEDIA_PREFIXES=(), CUSTOM_CHARACTERS_PATH=characters_path,
                 custom_characters_bp=Blueprint('icon_test', __name__))
    for path, names in ((BACKEND_DIR / 'app.py', {'_valid_backend_token', 'require_backend_token'}),
                        (BACKEND_DIR / 'vault/routes/custom_characters/__init__.py', {'get_custom_character_icon'})):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        assert len(nodes) == len(names)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), scope)
    app.register_blueprint(scope['custom_characters_bp'])
    assert not app.testing  # Most blueprint tests bypass this exact auth check.
    return app


@pytest.mark.parametrize('frozen', [False, True], ids=['source', 'packaged-layout'])
def test_builtin_build_preserves_icon_costumes_and_serves_authenticated_png(tmp_path, monkeypatch, frozen):
    """Real staged build/ZIP/metadata writes; only native rendering is synthetic."""
    from PIL import Image

    setup = _setup(tmp_path)
    project = tmp_path / 'mex-project'
    _fake_project(project)
    _fake_export(monkeypatch)
    assert setup.stage_builtin_giga_bowser(project)['staged'] is True

    # Exercise both source lookup and the actual PyInstaller bundle layout.
    bundle_root = tmp_path / 'bundle' if frozen else setup.project_root
    icon = bundle_root / 'backend/assets/builtin/giga-bowser/icon.png'
    icon.parent.mkdir(parents=True)
    shipped_icon = BACKEND_DIR / 'assets/builtin/giga-bowser/icon.png'
    shutil.copy2(shipped_icon, icon)
    with Image.open(icon) as image:
        image.verify()
    monkeypatch.setattr(sys, 'frozen', frozen, raising=False)
    if frozen:
        monkeypatch.setattr(sys, '_MEIPASS', str(bundle_root), raising=False)
    assert setup._bundled_giga_icon() == icon

    portrait = tmp_path / 'rendered.png'
    Image.new('RGBA', (136, 188), (160, 90, 20, 255)).save(portrait)
    stock = io.BytesIO()
    Image.new('RGBA', (24, 24), (160, 90, 20, 255)).save(stock, format='PNG')
    monkeypatch.setattr(setup, '_render_giga_csp', lambda _: portrait)
    def recolor(base, destination, spec):
        destination.write_bytes(base.read_bytes() + spec['code'].encode())
        return destination
    monkeypatch.setattr(setup, '_make_giga_recolor_dat', recolor)
    monkeypatch.setattr(setup, '_make_giga_stock', lambda *_: stock.getvalue())
    result = setup.build_builtin_character(setup.BUILTIN_GIGA_SLUG)
    assert result == {'success': True, 'seeded': True}

    char_dir = setup.storage_path / 'custom_characters/giga-bowser'
    css_icon = char_dir / 'css_icon.png'
    assert css_icon.read_bytes() == icon.read_bytes()
    entry = setup._read_metadata()['custom_characters'][0]
    assert entry['has_css_icon'] is True
    assert entry['costume_count'] == 4
    assert len(entry['costume_meta']) == 4
    fighter = json.loads((char_dir / 'fighter.json').read_text())
    assert [fighter[key] for key in ('redCostumeIndex', 'blueCostumeIndex', 'greenCostumeIndex')] == [1, 2, 3]
    with zipfile.ZipFile(char_dir / 'fighter.zip') as package:
        assert package.read('icon.png') == css_icon.read_bytes()
        assert json.loads(package.read('fighter.json')) == fighter
        for index, spec in enumerate(setup.BUILTIN_GIGA_COSTUMES):
            stem = f"PlGk{spec['code']}"
            assert (char_dir / 'costumes' / f'{stem}.zip').read_bytes() == package.read(f'{stem}.zip')
            with zipfile.ZipFile(io.BytesIO(package.read(f'{stem}.zip'))) as costume:
                assert costume.read(f'{stem}.dat')
                for name in ('csp.png', 'stc.png'):
                    with Image.open(io.BytesIO(costume.read(name))) as image:
                        image.verify()
            for path in (char_dir / f'csp_{index}.png', char_dir / f'stock_{index}.png'):
                with Image.open(path) as image:
                    image.verify()

    # Healthy four-costume setup is recognized, never rerendered on reopening.
    assert setup._giga_bowser_seed_current(char_dir) is True
    assert setup.builtin_pending_characters() == []
    monkeypatch.setattr(setup, '_render_giga_csp', lambda *_: pytest.fail('healthy built-in was rerendered'))
    assert setup.build_builtin_character(setup.BUILTIN_GIGA_SLUG) == {
        'success': True, 'seeded': False, 'reason': 'already_present'}

    client = _icon_app(char_dir.parent).test_client()
    endpoint = '/api/mex/custom-characters/giga-bowser/icon'
    assert client.get(endpoint).status_code == 401
    response = client.get(endpoint, query_string={'_nucleus_token': 'builtin-icon-test-token', 'v': '17'})
    try:
        assert response.status_code == 200
        assert response.mimetype == 'image/png'
        assert response.data == css_icon.read_bytes()
        with Image.open(io.BytesIO(response.data)) as image:
            image.verify()
    finally:
        response.close()
