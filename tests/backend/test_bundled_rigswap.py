"""The rigswap the installer ships (utility/rigswap.manifest.json, tools/build/fetch_rigswap.py): its package only,
pinned, compiled, staged on every platform with the assistant gate. Its Python and Blender are a download
(utility/model_import_tools.json; test_model_import_tools_manifest.py)."""
import importlib.util
import json
import re

import pytest

from tests.paths import APP, REPO

MANIFEST = json.loads((APP / 'utility' / 'rigswap.manifest.json').read_text(encoding='utf-8'))
TREE = APP / 'utility' / 'rigswap' / 'app'
#: The public source drop (tools/public_drop.py rewrite_manifest) points the pin at the public
#: rigswap repo and names its release snapshot by tag until that snapshot's commit exists.
PUBLIC_RIGSWAP = 'https://github.com/ssbmNucleus/rigswap.git'


def _a_whole_commit(pin):
    """A full commit id; or, only where the pin names the public rigswap repo, the tag of this
    version's release snapshot (nucleus-v<app version>), which names exactly one commit."""
    if re.fullmatch(r'[0-9a-f]{40}', pin['commit']):
        return True
    version = json.loads((APP / 'package.json').read_text(encoding='utf-8'))['version']
    return pin['repo'] == PUBLIC_RIGSWAP and pin['commit'] == f'nucleus-v{version}'


def _fetch():
    spec = importlib.util.spec_from_file_location('fetch_rigswap', REPO / 'tools' / 'build' / 'fetch_rigswap.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_wheel_is_pinned_by_version_and_hash():
    text = (APP / 'utility' / 'rigswap.requirements.txt').read_text(encoding='utf-8')
    rows = re.findall(r'^([A-Za-z0-9_.-]+)==(\S+) \\\n    --hash=sha256:([0-9a-f]{64})$', text, re.M)
    names = {name.lower() for name, _, _ in rows}
    assert {'bpy', 'numpy', 'pillow', 'requests'} <= names
    pinned = [line for line in text.splitlines() if '==' in line and not line.startswith('#')]
    assert len(rows) == len(pinned), 'a requirement without its hash'


def test_rigswap_is_a_whole_commit_and_only_blender4s_files_ship_as_source():
    pin = MANIFEST['rigswap']
    assert _a_whole_commit(pin), pin['commit']
    assert pin['entry'] == 'rigswap.plugins.melee.costume'
    assert pin['source_kept'] == ['rigswap/load/convert.py', 'rigswap/load/materials.py']
    assert MANIFEST['unpack_to'] == 'utility/rigswap/app'
    assert MANIFEST['entrypoint'] == 'rigswap/plugins/melee/costume.pyc'
    # the runtime moved to model_import_tools.json: nothing here downloads anything
    assert not {'url', 'sha256', 'size', 'requirements', 'wheels'} & set(MANIFEST)


def test_the_source_check_names_any_rigswap_source_but_the_kept(tmp_path):
    fetch = _fetch()
    manifest = {'rigswap': {'source_kept': ['rigswap/load/convert.py']}}
    package = tmp_path / 'rigswap' / 'load'      # tmp_path is utility/rigswap/app
    package.mkdir(parents=True)
    (package / 'convert.py').write_text('', encoding='utf-8')
    (package / 'open.pyc').write_bytes(b'')
    said = []
    assert fetch._sources(tmp_path, manifest, said.append)
    (package / 'open.py').write_text('', encoding='utf-8')
    assert not fetch._sources(tmp_path, manifest, said.append) and 'rigswap/load/open.py' in said[-1]


def test_the_compiler_is_always_a_cpython_313(monkeypatch):
    """The bytecode ships to every platform's downloaded 3.13: a build venv of another version (the Mac's may be
    3.12) compiles with a 3.13 found or fetched, never with itself."""
    fetch = _fetch()
    monkeypatch.setattr(fetch, '_version_of', lambda python: (3, 12, 9) if python == 'py312' else (3, 13, 18))
    with pytest.raises(SystemExit, match='3.13'):
        fetch.compiler('py312')
    assert fetch.compiler('py313') == 'py313'
    monkeypatch.setattr(fetch.sys, 'version_info', (3, 12, 9, 'final', 0))
    monkeypatch.setattr(fetch.shutil, 'which', lambda name: 'found313' if name == 'python3.13' else None)
    assert fetch.compiler() == 'found313'
    monkeypatch.setattr(fetch.shutil, 'which', lambda name: None)
    monkeypatch.setattr(fetch, '_pinned_python', lambda: 'pinned313')
    assert fetch.compiler() == 'pinned313'


def test_it_ships_on_every_platform_with_the_assistant_gate_and_lands_where_the_app_looks():
    from randall.model_import.chat import import_job
    rules = json.loads((REPO / 'tools' / 'build' / 'ship_rules.json').read_text(encoding='utf-8'))
    staged = [e for e in rules['stage']['common'] if e['src'] == 'utility/rigswap/app']
    assert staged and staged[0]['dst'] == import_job.RIGSWAP_APP and staged[0]['ships_with_gate'] == 'assistant'
    verify = [e for e in rules['verify']['common'] if isinstance(e, dict)]
    assert {'path': f'{import_job.RIGSWAP_APP}/{MANIFEST["entrypoint"]}', 'ships_with_gate': 'assistant'} in verify
    package = json.loads((APP / 'package.json').read_text(encoding='utf-8'))
    copied = [e for e in package['build']['extraResources']
              if isinstance(e, dict) and e['from'] == MANIFEST['unpack_to']]
    assert copied and copied[0]['to'] == import_job.RIGSWAP_APP


def test_every_build_script_builds_the_package_behind_the_assistant_gate():
    for script in ('build.bat', 'build-linux.sh', 'build-macos.sh'):
        text = (REPO / 'tools' / 'build' / script).read_text(encoding='utf-8')
        gate, fetch = text.find('ship_guard.py" gate assistant'), text.find('fetch_rigswap.py"')
        assert 0 <= gate < fetch, script
        assert 'fetch_blender' not in text, script


def _guard():
    spec = importlib.util.spec_from_file_location('ship_guard_under_test', REPO / 'tools' / 'build' / 'ship_guard.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_stage_scrub_keeps_rigswaps_bytecode_and_still_drops_other_caches(tmp_path):
    """preview.24's first build refused to package: scrub rule build-leftovers deleted every *.pyc, rigswap's
    compiled package with them, and costume.pyc was then missing from the stage."""
    guard = _guard()
    (tmp_path / '.nucleus-package-stage').write_text('', encoding='utf-8')
    shipped = tmp_path / 'utility' / 'rigswap' / 'app' / 'rigswap' / 'plugins' / 'melee' / 'costume.pyc'
    stray = tmp_path / 'utility' / 'processor' / 'tool.pyc'
    for f in (shipped, stray):
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b'')
    assert guard._scrub(tmp_path) == 0
    assert shipped.is_file() and not stray.exists()


def test_the_stage_refuses_a_rigswap_tree_fetched_for_another_commit(tmp_path):
    """The manifest pins rigswap's commit but the tree is fetched apart from the build: a pin moved without a
    re-fetch would ship the old importer, so the stage compares the staged receipt with the manifest."""
    tree = tmp_path / 'utility' / 'rigswap' / 'app'
    tree.mkdir(parents=True)
    receipt = {'manifest': 'utility/rigswap.manifest.json', 'rigswap_commit': MANIFEST['rigswap']['commit'],
               'python': [3, 13, 17]}
    (tree / '.fetch-receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
    assert _guard()._stale_trees(tmp_path) == []
    receipt['rigswap_commit'] = '0' * 40
    (tree / '.fetch-receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
    assert 'rigswap_commit' in _guard()._stale_trees(tmp_path)[0]


@pytest.mark.skipif(not (TREE / '.fetch-receipt.json').is_file(),
                    reason='no rigswap tree here (python tools/build/fetch_rigswap.py)')
def test_the_tree_on_disk_is_the_one_the_manifest_pins():
    assert _fetch().check(MANIFEST, log=print)
