"""The same commit, with nothing standing in for anything.

``test_build_commit_transaction.py`` replaces two steps that need a real
project: MexCLI's ``sync-codes`` and HSDRaw's menu reader. A transaction that
only ever works against stand-ins proves the transaction, not the operation. So
this runs both for real:

* a real MEX project - the minimal tree ``mexcli`` will actually open, about
  10 MB of a real build, built by ``devtools/make_build_commit_fixture.py``;
* the real ``mexcli sync-codes``, producing a real ``codes.gct``;
* the real HSDRaw menu reader, reopening the installed ``MnSlChr.usd`` and
  exporting its background bundle;
* the real Halo 3 lobby menu file from the 2026-09-22 experiment.

Both inputs are retail-derived and stay out of git, so this skips with the
command that produces them rather than failing. Every run works on a COPY: the
fixture, like the user's vault, is read-only here.
"""
from tests.paths import BACKEND
import json
import shutil
from pathlib import Path

import pytest

from core import build_authorization as auth_module, build_transaction as bt

FIXTURE = BACKEND / 'artifacts' / 'build-commit-fixture'
HALO = (BACKEND / 'artifacts' / 'harness-experiment-20260922' / 'runs'
        / 'openrouter_z-ai_glm-5.3-flash' / 'T5-halo-css' / 'out' / 'MnSlChr.usd')

pytestmark = [
    pytest.mark.skipif(
        not (FIXTURE / 'project.mexproj').is_file(),
        reason='no real-project fixture; build it with '
               '`python devtools/make_build_commit_fixture.py`'),
    pytest.mark.skipif(
        not HALO.is_file(),
        reason='the harness experiment run outputs are not in this checkout'),
    pytest.mark.slow,
]

CSS_CODE = {'name': 'Disable Hardcoded CSS Animations', 'source': '04263384 48000010'}


@pytest.fixture
def real(tmp_path, monkeypatch):
    """A throwaway copy of the real project, with the real tools in place."""
    from core.config import HSDRAW_EXE, MEXCLI_PATH
    if not Path(MEXCLI_PATH).is_file():
        pytest.skip(f'MexCLI is not built here ({MEXCLI_PATH})')
    if not Path(HSDRAW_EXE).is_file():
        pytest.skip(f'HSDRawViewer is not built here ({HSDRAW_EXE})')

    build_dir = tmp_path / 'RealBuild'
    shutil.copytree(FIXTURE, build_dir)
    workspace = tmp_path / 'workspace'
    (workspace / 'out').mkdir(parents=True)
    shutil.copyfile(HALO, workspace / 'out' / 'MnSlChr.usd')

    monkeypatch.setenv('NUCLEUS_API_WORKSPACE', str(workspace))
    monkeypatch.setenv('NUCLEUS_API_BUILDS', json.dumps([str(build_dir)]))
    monkeypatch.setenv('NUCLEUS_BUILD_TRUST_ROOT', str(tmp_path / 'trust'))
    # No seams: the shipped compiler and the shipped menu reader.
    monkeypatch.setattr(bt, 'FAULT_HOOK', None)

    from nucleus_api import builds, menus
    assert bt.CODE_COMPILER is bt.mexcli_sync_codes
    assert menus.NATIVE_MENU_READER is menus.native_menu_report
    return builds, build_dir, workspace


def test_the_real_compiler_and_the_real_menu_reader_commit_the_halo_menu(real):
    builds, build_dir, _ = real
    build = builds.list_builds()[0]
    assert build['committable'] is True
    before_ini = (build_dir / 'files' / 'codes.ini').read_text(encoding='utf-8',
                                                               errors='replace')
    from core.gecko import parse_ini
    before_codes = parse_ini(before_ini)
    assert before_codes, 'the fixture carries a real code list'

    artifact = builds.register_artifact('out/MnSlChr.usd', 'css_menu_file')
    change = builds.prepare_change(build['id'], build['revision'], [artifact['id']],
                                   code_changes={'add': [CSS_CODE]},
                                   task_id='task_real', task_revision=1)
    assert change['status'] == 'prepared', change.get('error')
    # The manifest recognised the real Halo bytes and ran the real structural
    # checks against the SEALED copy.
    verdict = change['compatibility'][artifact['id']]
    assert verdict['package']['package_id'] == 'halo3-matchmaking-lobby'
    assert verdict['structure']['status'] == 'pass'
    assert verdict['structure']['native']['status'] == 'pass'
    assert verdict['structure']['native']['background_bytes'] > 0

    authorization = auth_module.grant(change, granted_by='test', task_id='task_real',
                                      task_revision=1,
                                      accepted_unknown=change['unknown_dimensions'])
    receipt = builds.commit_change(change['prepared_change_id'],
                                   authorization['authorization_id'])

    # The menu file is the Halo one, byte for byte.
    assert bt.sha256_file(build_dir / 'files' / 'MnSlChr.usd') == artifact['sha256']

    # The code list came from the real compiler, and the real GCT carries the
    # code's compiled bytes.
    after = parse_ini((build_dir / 'files' / 'codes.ini').read_text(encoding='utf-8',
                                                                    errors='replace'))
    names = {c['name'] for c in after}
    assert 'Disable Hardcoded CSS Animations' in names
    assert {c['name'] for c in before_codes} <= names, 'every existing code survived'
    report = bt.gct_report(build_dir / 'files' / 'codes.gct')
    assert report['status'] == 'pass', report['reason']
    assert bytes.fromhex('0426338448000010') in report['body']

    checks = {c['check']: c for c in receipt['verification']['checks']}
    assert checks['native_reopen']['status'] == 'pass'
    assert checks['codes_in_gct']['status'] == 'pass'
    assert checks['background_semantics']['status'] == 'pass', (
        'the installed background must match the manifest\'s recorded RE-EXPORT digest, '
        'not the published bundle: HSDRaw reserializes what it exports')
    assert receipt['achieved']['build_inputs_updated'] is True
    assert receipt['achieved']['installed'] is False
    assert receipt['outcome'] == 'partial'


def test_rolling_the_real_change_back_restores_the_real_project(real):
    builds, build_dir, _ = real
    build = builds.list_builds()[0]
    before = {name: bt.sha256_file(build_dir / name)
              for name in ('files/MnSlChr.usd', 'files/codes.ini', 'files/codes.gct')}

    artifact = builds.register_artifact('out/MnSlChr.usd', 'css_menu_file')
    change = builds.prepare_change(build['id'], build['revision'], [artifact['id']],
                                   code_changes={'add': [CSS_CODE]}, task_id='task_real')
    authorization = auth_module.grant(change, granted_by='test', task_id='task_real',
                                      task_revision=1,
                                      accepted_unknown=change['unknown_dimensions'])
    receipt = builds.commit_change(change['prepared_change_id'],
                                   authorization['authorization_id'])
    assert bt.sha256_file(build_dir / 'files' / 'codes.gct') != before['files/codes.gct']

    builds.rollback(receipt['receipt_id'])
    for name, digest in before.items():
        assert bt.sha256_file(build_dir / name) == digest, name
    assert builds.list_builds()[0]['revision'] == build['revision']


def test_the_real_compiler_failing_leaves_the_real_project_untouched(real, monkeypatch):
    """A code list MexCLI refuses must not leave the new menu behind."""
    builds, build_dir, _ = real
    build = builds.list_builds()[0]
    before = {name: bt.sha256_file(build_dir / name)
              for name in ('files/MnSlChr.usd', 'files/codes.ini', 'files/codes.gct')}

    artifact = builds.register_artifact('out/MnSlChr.usd', 'css_menu_file')
    change = builds.prepare_change(build['id'], build['revision'], [artifact['id']],
                                   code_changes={'add': [CSS_CODE]}, task_id='task_real')
    authorization = auth_module.grant(change, granted_by='test', task_id='task_real',
                                      task_revision=1,
                                      accepted_unknown=change['unknown_dimensions'])

    # The REAL compiler, reached for real, and failing for a real reason: the
    # trophy file it opens before it will touch a code list is removed. That
    # file is not part of the build revision or the compiler identity, so the
    # commit gets all the way to `mexcli sync-codes` instead of being turned
    # away by a stale check first - which is what a stand-in compiler did, and
    # why the previous version of this test was passing on the wrong failure.
    trophy = build_dir / 'files' / 'TyDataf.dat'
    kept = trophy.read_bytes()
    trophy.unlink()
    try:
        with pytest.raises(bt.TransactionError) as caught:
            builds.commit_change(change['prepared_change_id'],
                                 authorization['authorization_id'])
    finally:
        trophy.write_bytes(kept)
    assert caught.value.code == 'code_sync_failed', caught.value.code

    from core import build_access
    with build_access.build_session(build_dir):
        pass
    for name, digest in before.items():
        assert bt.sha256_file(build_dir / name) == digest, name
