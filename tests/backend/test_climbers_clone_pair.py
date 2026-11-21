"""A pair of two clones (Plusle & Minun on Pichu) through the app's own steps:
the picker lets the partner through, the no-swap flag is kept per pair, and a
test build gets the engine code. (MexCLI keeps sub-fighters and team colours
right through adds and removals since the m-ex fork's v2026.11.03.)
"""
import json
from pathlib import Path

import pytest

from mexcli.project import fighter_files
from projects.install import test_build
from vault.climbers import engine_code, pairs


def _project(tmp_path, fighters):
    (tmp_path / 'data' / 'fighters').mkdir(parents=True)
    for i, fighter in enumerate(fighters):
        (tmp_path / 'data' / 'fighters' / f'{i:03d}.json').write_text(json.dumps(fighter), encoding='utf-8')
    return tmp_path / 'project.mexproj'


def _fighter(name, sub=-1, behavior=0, **fields):
    return {'name': name, 'subCharacter': sub, 'subCharacterBehavior': behavior,
            'costumes': [{}], **fields}


def _specials():
    return [_fighter(name) for name in ('Master Hand', 'Crazy Hand', 'Male Wireframe', 'Female Wireframe',
                                        'Giga Bowser', 'Sandbag')]


def test_candidates_accept_a_partner_built_as_a_pair(tmp_path):
    proj = _project(tmp_path, [_fighter('Pichu'), _fighter('Minun', sub=0)] + _specials())
    row = {c['name']: c for c in pairs.candidates(proj)}['Minun']
    assert row['canPartner'] and row['partnerBlockedReason'] is None
    assert not row['canLead']


def test_candidates_still_refuse_ice_climbers_and_transforms_as_partners(tmp_path):
    proj = _project(tmp_path, [_fighter('Ice Climbers', sub=1), _fighter('Nana'),
                               _fighter('Zelda Clone', sub=3, behavior=1), _fighter('Sheik', sub=2, behavior=1)]
                    + _specials())
    rows = {c['name']: c for c in pairs.candidates(proj)}
    assert not rows['Ice Climbers']['canPartner']
    assert not rows['Zelda Clone']['canPartner']
    assert not rows['Sheik']['canPartner']


def test_no_swap_is_per_pair_and_survives_a_second_call(tmp_path):
    proj = _project(tmp_path, [_fighter('Pichu')])
    assert pairs.no_swap_pairs(proj) == []
    pairs.set_no_swap(proj, 'Plusle & Minun')
    pairs.set_no_swap(proj, 'Plusle & Minun')
    pairs.set_no_swap(proj, 'Other')
    assert pairs.no_swap_pairs(proj) == ['Other', 'Plusle & Minun']


def test_ensure_code_carries_a_no_swap_pair(tmp_path, monkeypatch):
    fighters = [_fighter('Pichu', files={'fighterDataSymbol': 'ftDataPichu'}),
                _fighter('Plusle & Minun', sub=0, files={'fighterDataSymbol': 'ftDataPichu'})]
    proj = _project(tmp_path, fighters)
    pairs.set_no_swap(proj, 'Plusle & Minun')
    added = []

    def run(cmd, **_):
        added.append(cmd[-1])
        return type('Result', (), {'returncode': 0, 'stdout': '', 'stderr': ''})

    monkeypatch.setattr(engine_code.subprocess, 'run', run)
    monkeypatch.setattr(engine_code, 'MEXCLI_PATH', tmp_path)
    assert engine_code.ensure_code(proj)
    assert '3C007FFF' in added[0].split()


def test_a_test_build_export_installs_the_engine_code(tmp_path, monkeypatch):
    proj = _project(tmp_path, [_fighter('Pichu', files={'fighterDataSymbol': 'ftDataPichu'}),
                               _fighter('Double Pichu', sub=0, files={'fighterDataSymbol': 'ftDataPichu'})])
    (tmp_path / 'project.mexproj').write_text('{}', encoding='utf-8')
    ensured = []
    monkeypatch.setattr(engine_code, 'ensure_code', lambda path: ensured.append(path) or True)

    class Mex:
        project_path = str(proj)

        def export_iso(self, out_iso, *_a, **_k):
            Path(out_iso).write_bytes(b'iso')

    test_build._export(Mex(), tmp_path / 'out.iso', None, lambda m: None)
    assert ensured == [str(proj)]


def test_export_of_a_project_without_a_pair_adds_no_code(tmp_path, monkeypatch):
    proj = _project(tmp_path, [_fighter('Pichu')])
    monkeypatch.setattr(engine_code, 'ensure_code',
                        lambda path: pytest.fail('a project with no pair got the code'))
    engine_code.ensure_for_export(proj)


def test_fighters_come_from_the_project_list_not_stale_files(tmp_path):
    """m-ex rewrites fighterSaveMap on Save but never deletes a file, so after a
    fighter is removed data/fighters still holds the old last NNN.json."""
    proj = _project(tmp_path, [_fighter('Pichu'), _fighter('Minun', sub=0), _fighter('Sandbag')])
    proj.write_text(json.dumps({'fighterSaveMap': {'filePaths': ['000.json', '001.json']}}), encoding='utf-8')
    assert [f['name'] for f in pairs.load_fighters(proj)] == ['Pichu', 'Minun']
    assert [p.name for p in fighter_files(tmp_path)] == ['000.json', '001.json']
