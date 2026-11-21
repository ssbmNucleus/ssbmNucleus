"""Opt-in save/reopen regression against a copied vanilla m-ex workspace.

Set VANILLA_REPLACEMENT_TEST_PROJECT to a disposable vanilla project template
and VANILLA_REPLACEMENT_TEST_CLI to a JSON command array for the compiled CLI.
The template is only read; all native mutations run in pytest's copied tree.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest

from core.config import VANILLA_ASSETS_DIR
from falcon_neutralize import convert_falcon_to_color


pytestmark = [pytest.mark.skipif(
    not os.environ.get('VANILLA_REPLACEMENT_TEST_PROJECT')
    or not os.environ.get('VANILLA_REPLACEMENT_TEST_CLI'),
    reason='Requires a vanilla workspace and compiled replacement CLI',
), pytest.mark.slow]


@pytest.fixture(scope='module')
def native(tmp_path_factory):
    directory = tmp_path_factory.mktemp('native-replacement')
    template = Path(os.environ['VANILLA_REPLACEMENT_TEST_PROJECT'])
    project = directory / 'project' / template.name
    shutil.copytree(template.parent, project.parent)
    cli = json.loads(os.environ['VANILLA_REPLACEMENT_TEST_CLI'])

    def run(entries):
        manifest = directory / 'manifest.json'
        manifest.write_text(json.dumps(entries))
        return subprocess.run(cli + ['replace-costume', str(project), str(manifest)],
                              capture_output=True, text=True, timeout=120)

    def package(fighter, code, target=None):
        source = VANILLA_ASSETS_DIR / fighter / code
        payload = (source / f'{code}.dat').read_bytes()
        if target:
            payload = convert_falcon_to_color(payload, target)
        path = directory / f'{code}-{target}.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr(f'{code}.dat', payload)
            portraits = source if fighter != 'Nana' else VANILLA_ASSETS_DIR / 'Ice Climbers/PlPpOr'
            for name in ('csp.png', 'stock.png'):
                archive.write(portraits / name, name)
        return str(path)

    return project, run, package


def fighter_data(project):
    return {d['name']: d for path in project.parent.glob('data/fighters/*.json')
            for d in [json.loads(path.read_text())]}


def snapshot(project):
    return {str(p.relative_to(project.parent)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in project.parent.rglob('*') if p.is_file()}


def test_native_replace_preserves_slots_and_remaps_kirby_copies(native):
    project, run, package = native
    before = fighter_data(project)
    cases = [('Fox', 'PlFxGr', 0, 3, None),
             ('C. Falcon', 'PlCaBu', 2, 2, 'Re'),
             ('C. Falcon', 'PlCaRe', 0, 0, 'Nr'),
             ('Jigglypuff', 'PlPrYe', 2, 4, None),
             ('Kirby', 'PlKbBu', 3, 2, None),
             ('Ice Climbers', 'PlPpOr', 0, 2, None),
             ('Nana', 'PlNnAq', 0, 2, None),
             ('Mr. Game & Watch', 'PlGwNr', 1, 0, None),
             ('Jigglypuff', 'PlPrYe', 0, 4, None),
             ('Jigglypuff', 'PlPrNr', 1, 0, None),
             ('Jigglypuff', 'PlPrBu', 3, 2, None),
             ('Jigglypuff', 'PlPrGr', 4, 3, None)]
    entries = []
    source_hashes = {}
    for fighter, code, index, visibility, color in cases:
        old = before[fighter]['costumes'][index]['file']['fileName']
        path = package(fighter, code, color)
        source_hashes[path] = Path(path).read_bytes()
        entries.append(dict(fighter=fighter, index=index, expectedFile=old,
                            vanillaFile=old, path=path, visibilityIndex=visibility))
    result = run(entries)
    assert result.returncode == 0, result.stdout + result.stderr
    after = fighter_data(project)
    for fighter, old in before.items():
        new = after[fighter]
        assert len(old['costumes']) == len(new['costumes'])
        for key in ('redCostumeIndex', 'blueCostumeIndex', 'greenCostumeIndex'):
            assert old.get(key) == new.get(key)
        replacements = {e['index']: e for e in entries if e['fighter'] == fighter}
        for index, row in enumerate(new['costumes']):
            if index not in replacements:
                assert row == old['costumes'][index]
                continue
            entry = replacements[index]
            assert row['replacesVanillaFile'] == entry['vanillaFile']
            assert row['file']['visibilityIndex'] == entry['visibilityIndex']
            assert row['file']['jointSymbol']
            assert row['file']['fileName'] != entry['expectedFile']
            assert (project.parent / 'files' / row['file']['fileName']).is_file()
        if old.get('kirbyCostumes'):
            assert len(old['kirbyCostumes']) == len(new['kirbyCostumes'])
            source = next((cap for cap in old['kirbyCostumes'] if 'PlKbBuCp' in cap['fileName']), None)
            if source:
                assert new['kirbyCostumes'][3] == source
    for path, contents in source_hashes.items():
        assert Path(path).read_bytes() == contents
    core = json.loads((project.parent / 'data/mex.json').read_text())
    assert '801E0004' in core['source'].replace(' ', '').replace('\n', '').replace('\r', '')
    codes = (project.parent / 'files/codes.ini').read_text()
    assert codes.count('Nucleus: Jigglypuff source costume dynamics') == 1


@pytest.mark.parametrize('bad_kind', ['body', 'hat'])
def test_native_invalid_package_does_not_partially_save(native, bad_kind):
    project, run, package = native
    fighters = fighter_data(project)
    entries = []
    # Stage a valid import first, then fail the accessory conversion. Neither
    # project metadata nor staged files/assets may escape to disk.
    for fighter, code, slot in [('Fox', 'PlFxGr', 0), ('Jigglypuff', 'PlPrYe', 2)]:
        row = fighters[fighter]['costumes'][slot]
        entries.append(dict(fighter=fighter, index=slot, expectedFile=row['file']['fileName'],
                            vanillaFile=row.get('replacesVanillaFile') or row['file']['fileName'],
                            path=package(fighter, code), visibilityIndex=4 if fighter == 'Jigglypuff' else 3))
    bad_package = Path(entries[-1]['path']).with_name(f'bad-{bad_kind}.zip')
    payload = b'not a costume' if bad_kind == 'body' else (
        VANILLA_ASSETS_DIR / 'Jigglypuff/PlPrNr/PlPrNr.dat').read_bytes()
    with zipfile.ZipFile(bad_package, 'w') as archive:
        archive.writestr('PlPrYe.dat', payload)
    entries[-1]['path'] = str(bad_package)
    original = snapshot(project)
    result = run(entries)
    assert result.returncode != 0
    assert 'body model' in result.stdout if bad_kind == 'body' else 'hat model' in result.stdout
    assert snapshot(project) == original
