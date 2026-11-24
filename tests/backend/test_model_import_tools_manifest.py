"""The committed app/utility/model_import_tools.json and how the installer carries model import (no network).

Since 0.9.0 no installer ships Blender or rigswap's Python: the app downloads them on the user's request from the
official sources this manifest pins (docs/dev/MODEL_IMPORT_TOOLS.md), and every installer ships rigswap's own
compiled package plus this manifest, with the assistant. The pin script itself is test_pin_model_import_tools.py;
the app's lookup of the installed tools is test_assistant_import_job.py.
"""
import importlib.util
import json
import re

import pytest

from tests.paths import APP, REPO

MANIFEST_PATH = APP / 'utility' / 'model_import_tools.json'
PLATFORMS = ('win-x64', 'linux-x64', 'osx-arm64')
HEX64 = re.compile(r'[0-9a-f]{64}')


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pin = _load('pin_model_import_tools_for_manifest', REPO / 'tools' / 'build' / 'pin_model_import_tools.py')


@pytest.fixture(scope='module')
def manifest():
    return json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))


@pytest.fixture(scope='module')
def reqs(manifest):
    return pin.requirements(APP / manifest['pin']['requirements'])


def _items(entry):
    return [('blender', entry['blender']), ('python', entry['python']),
            *((f'wheel {w["name"]}', w) for w in entry['wheels'])]


def test_schema_platforms_and_that_the_pin_script_wrote_it(manifest):
    assert manifest['schema'] == 1
    assert tuple(manifest['platforms']) == PLATFORMS == pin.PLATFORMS
    assert MANIFEST_PATH.read_text(encoding='utf-8') == pin.dump(manifest), (
        'hand-edited: regenerate it with python tools/build/pin_model_import_tools.py')


def test_every_file_is_pinned_by_https_url_sha256_and_size(manifest):
    for platform, entry in manifest['platforms'].items():
        for label, item in _items(entry):
            assert item['url'].startswith('https://'), (platform, label)
            assert HEX64.fullmatch(item['sha256']), (platform, label)
            assert isinstance(item['size'], int) and item['size'] > 0, (platform, label)


def test_the_sources_are_the_official_ones(manifest):
    for platform, entry in manifest['platforms'].items():
        assert entry['blender']['url'].startswith('https://download.blender.org/release/Blender4.3/'), platform
        name = entry['blender']['url'].rsplit('/', 1)[1]
        assert len(entry['blender']['mirrors']) >= 2, platform      # its Cloudflare front turns some networks away
        for mirror in entry['blender']['mirrors']:
            assert mirror.startswith('https://') and mirror.endswith('/release/Blender4.3/' + name), (platform, mirror)
        for wheel in entry['wheels']:
            assert wheel['url'].startswith('https://files.pythonhosted.org/'), (platform, wheel['name'])
            assert wheel['url'].endswith('/' + wheel['filename']), (platform, wheel['name'])
    assert manifest['platforms']['win-x64']['python']['url'].startswith('https://www.python.org/ftp/python/')
    tag = manifest['pin']['python_build_standalone']
    for platform in ('linux-x64', 'osx-arm64'):
        python = manifest['platforms'][platform]['python']
        assert python['url'].startswith(
            f'https://github.com/astral-sh/python-build-standalone/releases/download/{tag}/'), platform
        assert python['url'].endswith('-install_only_stripped.tar.gz') and python['release'] == tag


def test_blender_4_3_2_everywhere(manifest):
    assert manifest['pin']['blender'] == '4.3.2'
    for platform, entry in manifest['platforms'].items():
        assert entry['blender']['version'] == '4.3.2', platform
        assert '4.3.2' in entry['blender']['url'].rsplit('/', 1)[1], platform


def test_python_is_313_at_the_pinned_versions(manifest):
    for platform, entry in manifest['platforms'].items():
        python = entry['python']
        assert python['version'] == manifest['pin']['python'][platform], platform
        assert python['version'].startswith('3.13.'), platform
        assert python['site_packages'] and python['entrypoint'] and python['wheel_verify'], platform
    win = manifest['platforms']['win-x64']['python']
    assert (win['format'], win['kind'], win['entrypoint']) == ('zip', 'embeddable', 'python.exe')
    for platform in ('linux-x64', 'osx-arm64'):
        python = manifest['platforms'][platform]['python']
        assert (python['format'], python['kind'], python['entrypoint']) == ('tar.gz', 'standalone', 'bin/python3')


def test_the_wheels_are_the_requirements_list_on_every_platform(manifest, reqs):
    wanted = [(name, version) for name, version, _ in reqs]
    for platform, entry in manifest['platforms'].items():
        assert [(w['name'], w['version']) for w in entry['wheels']] == wanted, platform
        assert all(w['filename'].endswith('.whl') for w in entry['wheels']), platform


def test_windows_wheels_are_the_requirements_hashes(manifest, reqs):
    hashes = {name: hashes for name, _, hashes in reqs}
    for wheel in manifest['platforms']['win-x64']['wheels']:
        assert wheel['sha256'] in hashes[wheel['name']], wheel['name']


def test_each_platform_gets_its_own_bpy(manifest):
    tails = {'win-x64': 'win_amd64.whl', 'linux-x64': 'x86_64.whl', 'osx-arm64': 'arm64.whl'}
    for platform, entry in manifest['platforms'].items():
        bpy = next(w for w in entry['wheels'] if w['name'] == 'bpy')
        assert bpy['filename'].startswith('bpy-5.2.2-cp313-cp313-') and bpy['filename'].endswith(tails[platform])


def test_the_blender_layouts(manifest):
    win = manifest['platforms']['win-x64']['blender']
    assert (win['format'], win['entrypoint']) == ('zip', 'blender.exe')
    assert 'blender.pdb' in win['trim'] and '4.3/scripts/addons_core/cycles' in win['trim']
    linux = manifest['platforms']['linux-x64']['blender']
    assert (linux['format'], linux['entrypoint']) == ('tar.xz', 'blender')
    mac = manifest['platforms']['osx-arm64']['blender']
    assert (mac['format'], mac['root']) == ('dmg', 'Blender.app')
    assert mac['entrypoint'] == 'Blender.app/Contents/MacOS/Blender'
    assert mac['verify'] and all(p.startswith('Blender.app/') for p in mac['verify'])
    assert mac['trim'] == [], 'deleting files inside the signed Blender.app breaks its seal'
    for platform, entry in manifest['platforms'].items():
        blender = entry['blender']
        # what rigswap's Collada conversion needs must survive the trim
        assert not set(blender['trim']) & set(blender['verify']), platform
        assert any('io_scene_gltf2' in p for p in blender['verify']), platform


def test_download_sizes_are_plausible(manifest):
    totals = pin.totals(manifest)
    assert set(totals) == set(PLATFORMS)
    for platform, size in totals.items():
        assert 400e6 < size < 1.5e9, (platform, size)
        bpy = next(w for w in manifest['platforms'][platform]['wheels'] if w['name'] == 'bpy')
        assert bpy['size'] > 100e6, platform
        assert manifest['platforms'][platform]['blender']['size'] > 200e6, platform


def test_each_platforms_size_on_disk_is_measured_from_its_pinned_downloads(manifest):
    """0.9.0 build 3 smoke: the size the card shows before the download was a guess from per-format ratios (Linux:
    "about 2 GB", 2.32 GB landed). Each platform's ``on_disk`` is a real install's, of exactly these downloads, so the
    estimate is that install's size; a moved pin needs a new measurement (its real import gives the receipt)."""
    from randall.model_import.tools import assemble
    for platform, entry in manifest['platforms'].items():
        assert set(assemble.measured(entry)) == set(entry.get('on_disk') or {}) == {'blender', 'runtime'}, (
            f'{platform}: record a receipt of the pinned downloads with '
            'python tools/build/pin_model_import_tools.py --measured <receipt.json>')
        assert 1e9 < assemble.estimate(assemble.files_for(entry)) < 3e9, platform


def test_the_licences_are_named(manifest, reqs):
    licence = manifest['license']
    assert licence['blender']['spdx'] == 'GPL-2.0-or-later'
    assert licence['blender']['source'] == 'https://download.blender.org/source/'
    assert set(licence['python']) == set(PLATFORMS)
    assert {name for name, _, _ in reqs} <= set(licence['packages'])


def test_blender_is_credited_in_the_shipped_notices(manifest):
    notices = (APP / 'THIRD_PARTY_NOTICES.md').read_text(encoding='utf-8')
    section = notices.split('### Blender', 1)
    assert len(section) == 2, 'THIRD_PARTY_NOTICES.md has no Blender entry'
    body = section[1].split('\n### ', 1)[0]
    assert 'GPL-2.0-or-later' in body
    assert manifest['pin']['blender'] in body
    assert 'download.blender.org/source/' in body, 'GPL needs a source offer'


# ------------------------------------------------------------------ what the installer carries

def _rules():
    return json.loads((REPO / 'tools' / 'build' / 'ship_rules.json').read_text(encoding='utf-8'))


def _platform_lists(section):
    return {key: value for key, value in section.items() if isinstance(value, list)}


def test_every_installer_stages_rigswap_and_the_manifest_with_the_assistant():
    """ship_rules.json must COPY both into the stage (extraResources copies from the stage, not the repo) and fail
    a build that lacks them; both follow the assistant gate."""
    rules = _rules()
    common = rules['stage']['common']
    for src, kind in (('utility/rigswap/app', 'dir'), ('utility/model_import_tools.json', 'file')):
        staged = [e for e in common if e.get('src') == src]
        assert len(staged) == 1 and staged[0]['dst'] == src and staged[0]['kind'] == kind, src
        assert not staged[0].get('optional'), f'a missing {src} must fail the build'
        assert staged[0].get('ships_with_gate') == 'assistant', src
    verify = [e for e in rules['verify']['common'] if isinstance(e, dict)]
    for path in ('utility/rigswap/app/rigswap/plugins/melee/costume.pyc', 'utility/model_import_tools.json'):
        assert {'path': path, 'ships_with_gate': 'assistant'} in verify, path


def test_no_installer_carries_blender_or_rigswaps_python_any_more():
    rules = _rules()
    for section in ('stage', 'verify'):
        for platform, entries in _platform_lists(rules[section]).items():
            text = json.dumps(entries)
            assert 'utility/blender' not in text, (section, platform)
            assert 'utility/rigswap/python' not in text, (section, platform)
    package = json.loads((APP / 'package.json').read_text(encoding='utf-8'))['build']
    top = {e['from']: e for e in package['extraResources'] if isinstance(e, dict)}
    assert top['utility/rigswap/app']['to'] == 'utility/rigswap/app'
    assert top['utility/model_import_tools.json']['to'] == 'utility/model_import_tools.json'
    for platform in ('win', 'linux', 'mac'):
        for entry in (package.get(platform) or {}).get('extraResources') or []:
            source = entry['from'] if isinstance(entry, dict) else entry
            assert not source.startswith(('utility/blender', 'utility/rigswap')), (platform, source)


def test_rigswap_ships_only_with_the_assistant(monkeypatch):
    """The model import follows the assistant gate: a stable build ships it since 0.9.0, a build that holds the
    assistant back leaves it out, and a preview that asks for the assistant ships it again."""
    guard = _load('ship_guard_for_manifest', REPO / 'tools' / 'build' / 'ship_guard.py')
    monkeypatch.delenv('NUCLEUS_PREVIEW_FEATURES', raising=False)
    from core.gates import GATES
    assert guard.gate_ships('assistant') is (not GATES['assistant'].packaged_off)
    assert guard.gate_ships('assistant') is True     # 0.9.0: the assistant ships
    monkeypatch.setenv('NUCLEUS_PREVIEW_FEATURES', 'assistant')
    assert guard.gate_ships('assistant') is True
