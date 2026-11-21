"""The one real-project delivery test: native tools, a real disc, a real undo.

Everything in `test_deliver_to_game.py` runs against a synthetic build and a
stubbed MexCLI. That proves the orchestration and the honesty rules; it cannot
prove that a real import produces a DAT the real exporter puts on a real disc,
that the shared build session works against the real exporter, or that an undo
returns a real project and a real playable copy to where they were.

This test does that, once, end to end:

* a FRESH editable project made from the user's clean Melee ISO by real
  ``mexcli create`` -- so nothing of theirs is touched;
* an UNRELATED existing customization imported into it first, which the
  delivery and the undo must both leave alone;
* a REAL Nucleus playable copy built and saved BEFORE the delivery, so the
  restoration the undo performs is checked against bytes that actually existed
  rather than against an empty starting point;
* another project left "open" in the app, which must not be the one built;
* the approved tool path, with the real `run_export_job(background=False)` and
  the delivery's own build session handed through;
* hash checks on the exported artifact, on the saved copy, and on the costume's
  payload INSIDE the disc image's file table;
* Launcher activation before and after selection;
* a simulated backend restart, a retry that must not install twice, then Undo
  and a second, harmless Undo.

**Gated.** It needs a clean Melee ISO, MexCLI and a vault costume, it writes
several GB and it takes minutes, so it skips unless
``NUCLEUS_REAL_DELIVERY_TEST=1``. The booting leg the review also describes
("boot that exact saved ISO and capture the costume") is NOT performed here:
this repository's standing rule is that an agent never launches Dolphin. It is
left as an explicitly skipped step behind ``NUCLEUS_DELIVERY_BOOT_TEST`` so a
human can run it, and the result of this test is reported as structural
verification, never as gameplay acceptance.
"""
import json
import os
import shutil
import time
from pathlib import Path

import pytest

from randall.assistant import approvals, tools
from randall.delivery import deliver, deliver_policy, deliver_steps, destination, projects
from core import config, state

REQUESTED = os.environ.get('NUCLEUS_REAL_DELIVERY_TEST') == '1'


def _clean_iso():
    try:
        from shared.vanilla_extract.vanilla_refs import known_vanilla_iso
        return known_vanilla_iso()
    except Exception:  # noqa: BLE001
        return None


def _real_costumes(character='Fox', wanted=2):
    """Two distinct costume ZIPs for one fighter out of the user's real vault."""
    from core.metadata import load_metadata
    data = load_metadata(default={}) or {}
    rows = []
    for skin in (data.get('characters', {}).get(character, {}) or {}).get('skins', []):
        if skin.get('type') == 'folder' or skin.get('visible') is False or skin.get('is_nana'):
            continue
        archive = Path(config.STORAGE_PATH) / character / (skin.get('filename')
                                                           or f"{skin['id']}.zip")
        if archive.is_file():
            rows.append((skin, archive))
        if len(rows) == wanted:
            break
    return rows


def _requirements():
    missing = []
    if not REQUESTED:
        missing.append('NUCLEUS_REAL_DELIVERY_TEST=1')
    if _clean_iso() is None:
        missing.append('a configured clean Melee ISO')
    if not Path(config.MEXCLI_PATH).is_file():
        missing.append('MexCLI')
    if REQUESTED and len(_real_costumes()) < 2:
        missing.append('two Fox costumes in the vault')
    return missing


pytestmark = [pytest.mark.skipif(bool(_requirements()),
                                 reason='needs ' + ', '.join(_requirements() or ['nothing'])), pytest.mark.slow]


def _digest(path):
    return destination.digest_file(path)


@pytest.fixture
def real_game(tmp_path, monkeypatch):
    """An isolated storage, projects folder and output folder. The vault is read-only."""
    storage = tmp_path / 'storage'
    (storage / 'Fox').mkdir(parents=True)
    projects_root = tmp_path / 'projects'
    projects_root.mkdir()
    output_root = tmp_path / 'output'
    output_root.mkdir()

    subject, subject_zip = _real_costumes()[0]
    unrelated, unrelated_zip = _real_costumes()[1]
    shutil.copyfile(subject_zip, storage / 'Fox' / subject_zip.name)

    from core import metadata as core_metadata
    monkeypatch.setattr(core_metadata, 'METADATA_FILE', storage / 'metadata.json')
    monkeypatch.setattr(config, 'STORAGE_PATH', storage)
    monkeypatch.setattr(config, 'PROJECTS_PATH', projects_root)
    monkeypatch.setattr(config, 'OUTPUT_PATH', output_root)
    import projects.install.export_job as export_module
    monkeypatch.setattr(export_module, 'OUTPUT_PATH', output_root)
    monkeypatch.setattr(export_module, 'STORAGE_PATH', storage)
    core_metadata.save_metadata({'characters': {'Fox': {'skins': [
        {**subject, 'filename': subject_zip.name}]}}})

    # Another project left open: the delivery must build the one it was told to.
    other = projects_root / 'Other Melee' / 'project.mexproj'
    (other.parent / 'data' / 'fighters').mkdir(parents=True)
    other.write_text(json.dumps({'build': {'name': 'Other Melee'}}))
    (other.parent / 'files').mkdir()
    monkeypatch.setattr(state, '_current_project_path', other)

    return {'storage': storage, 'projects': projects_root, 'output': output_root,
            'subject': subject, 'unrelated_zip': unrelated_zip, 'other': other,
            'tmp': tmp_path}


def _create_real_project(root, name):
    """A fresh MEX project from the user's clean ISO. Nothing of theirs is touched."""
    import subprocess
    directory = Path(root) / name
    result = subprocess.run(
        [str(config.MEXCLI_PATH), 'create', str(_clean_iso()), str(directory), name],
        capture_output=True, text=True, cwd=config.PROJECT_ROOT,
        **config.get_subprocess_args())
    project = directory / 'project.mexproj'
    assert result.returncode == 0 and project.is_file(), \
        f'mexcli create failed: {result.stdout[-2000:]}\n{result.stderr[-2000:]}'
    return project


def _fighter(project, name='Fox'):
    from mexcli.project import MexManager
    return MexManager(str(config.MEXCLI_PATH), str(project)).get_fighter_by_name(name)


def _fighter_file(project, character='Fox'):
    """A real project numbers its fighters by INTERNAL id, which is not the CSS
    order: ``002.json`` is Captain Falcon. Resolve by name."""
    folder = Path(project).parent / 'data' / 'fighters'
    for path in sorted(folder.glob('*.json')):
        if not path.stem.isdigit():
            continue
        if json.loads(path.read_text(encoding='utf-8-sig')).get('name') == character:
            return path
    raise AssertionError(f'{character} is not a fighter in this project')


def _costume_files(project, character='Fox'):
    data = json.loads(_fighter_file(project, character).read_text(encoding='utf-8-sig'))
    return [(c.get('name', ''), (c.get('file') or {}).get('fileName', ''))
            for c in data.get('costumes', [])]


def test_real_delivery_activation_restart_and_undo(real_game, monkeypatch, tmp_path):
    from core import iso_reads
    from mexcli.project import MexManager

    # ---- a real project with an unrelated customization already in it -------
    project = _create_real_project(real_game['projects'], 'My Melee')
    manager = MexManager(str(config.MEXCLI_PATH), str(project))
    before_unrelated = len(_costume_files(project))
    manager.import_costume('Fox', str(real_game['unrelated_zip']))
    unrelated = _costume_files(project)[-1]
    assert unrelated[1], 'the unrelated customization has a costume file'
    unrelated_digest = _digest(Path(project).parent / 'files' / unrelated[1])
    assert len(_costume_files(project)) == before_unrelated + 1
    state.reload_mex_manager()

    project_id = next(row['id'] for row in projects.list_projects()['projects']
                      if row['name'] == 'My Melee')

    # ---- a real playable copy that EXISTS before the delivery --------------
    # Built and saved through the ordinary export + Save path, so the undo later
    # has genuine prior bytes to restore rather than nothing.
    import projects.install.export_job as export_module
    from core import playable_iso
    output = tmp_path / 'games' / 'My Melee (Nucleus).iso'
    output.parent.mkdir(parents=True)
    played = tmp_path / 'games' / 'Melee.iso'
    played.write_bytes(b'the file they play today')
    monkeypatch.setattr(destination, 'launcher_iso', lambda: str(played))
    monkeypatch.setattr(playable_iso, 'launcher_iso', lambda: str(played))

    session, closer = deliver_steps._build_session({'path': str(project), 'name': 'My Melee',
                                                    'id': project_id})
    try:
        prior = deliver_steps._default_export({'path': str(project), 'name': 'My Melee',
                                               'id': project_id},
                                              {'filename': 'My Melee.iso'}, session=session)
    finally:
        closer.__exit__(None, None, None)
    assert prior['state'] == 'complete', prior
    assert export_module.copy_artifact_to(Path(prior['path']), output) is None
    assert playable_iso.produced_by_nucleus(output)
    before_bytes = _digest(output)

    record = destination.designate('slippi_netplay', project_id=project_id,
                                   output_iso_path=str(output), start_from_clean=True)
    assert played.read_bytes() == b'the file they play today', \
        'designating must never write to the file they play now'
    assert _digest(output) == before_bytes, 'designating must not touch the copy either'

    # ---- the approved tool path, with the real exporter --------------------
    subject = real_game['subject']
    args = {'character': 'Fox', 'skin_id': subject['id']}
    call = tools.prepare('deliver_to_game', args)
    assert 'approval' in tools.execute(call)['error']
    started = time.monotonic()
    result = tools.execute(call, approvals.Grant(call.fingerprint))
    elapsed = time.monotonic() - started
    assert 'task_id' in result, result          # not the tool's error shape
    assert result.get('error') is None, (result.get('error'), result.get('limitations'))
    assert result['outcome'] in ('success', 'partial'), (result['outcome'],
                                                         result['limitations'])
    assert elapsed < 30 * 60, f'the delivery took {elapsed:.0f}s'

    # the NAMED project was built, not the open one
    assert result['facts']['target_build_id'] == project_id
    assert state.get_current_project_path() == real_game['other']
    assert not any(real_game['other'].parent.rglob('*.dat'))

    receipt_id = result['facts']['receipt_id']
    receipt = deliver.read_receipt(receipt_id)
    added = receipt['added']
    assert added and added[0]['filename']

    # ---- the disc image really contains the costume's bytes ----------------
    artifact = Path(receipt['after']['artifact']['path'])
    assert artifact.is_file() and artifact.stat().st_size > deliver_policy.MIN_PLAYABLE_ISO_BYTES
    entries = iso_reads.fst_entries(artifact)
    for slot in added:
        assert slot['filename'] in entries, slot['filename']
        on_disc = iso_reads.file_digest(artifact, slot['filename'], entries=entries)
        in_project = _digest(Path(project).parent / 'files' / slot['filename'])
        assert f'sha256:{on_disc}' == in_project, slot['filename']
    # the unrelated customization survived the build
    assert unrelated[1] in entries
    assert f"sha256:{iso_reads.file_digest(artifact, unrelated[1], entries=entries)}" == \
        unrelated_digest

    # ---- saved, but not active until the Launcher points at it -------------
    assert output.is_file()
    assert _digest(output) == _digest(artifact), 'the saved copy is the build, byte for byte'
    assert _digest(output) != before_bytes, 'and it is not the copy from before'
    assert receipt['before']['output']['digest'] == before_bytes
    assert receipt['backup'] and receipt['backup']['digest'] == before_bytes, \
        'the copy they were playing is kept, so the undo has it to put back'
    assert destination.produced_by_nucleus(output)
    assert played.read_bytes() == b'the file they play today'
    assert result['achieved']['exported'] is True
    assert result['achieved']['installed'] is False
    assert result['facts']['activation']['status'] == 'pending'

    monkeypatch.setattr(destination, 'launcher_iso', lambda: str(output))
    assert destination.confirm_activation(record['id'])['status'] == 'verified'
    assert deliver.current_state(deliver.read_receipt(receipt_id))['complete'] is True

    # ---- restart the backend, then retry: no second install, no second build
    from core import jobs
    monkeypatch.setattr(jobs, '_jobs', {})        # a new process holds no jobs; records stay on disk
    recovered = deliver.recover_deliveries()
    assert any(row['receipt_id'] == receipt_id and row['status'] == 'completed'
               for row in recovered)
    costumes_before_retry = _costume_files(project)
    saved_before_retry = _digest(output)
    retry = deliver.deliver_to_game(**args)
    assert retry['facts']['receipt_id'] == receipt_id
    assert retry['achieved']['installed'] is True
    assert _costume_files(project) == costumes_before_retry, 'a retry must not install again'
    assert _digest(output) == saved_before_retry

    # ---- the booting leg is a human's to run -------------------------------
    # Deliberately not booted here: this repository's rule is that an agent never
    # launches Dolphin, and a structural pass is not gameplay acceptance anyway.
    # The saved copy and the costume file to look for are printed so a person
    # can finish the leg by hand; nothing automated claims that result.
    if os.environ.get('NUCLEUS_DELIVERY_BOOT_TEST') == '1':
        print('BOOT THIS BY HAND:', output)
        print('AND LOOK FOR:', [slot['filename'] for slot in added])
        pytest.skip('booting the saved copy is a manual step; this test launches no player')

    # ---- undo: the project and the playable copy both go back --------------
    undone = deliver.undo_delivery(receipt_id)
    if os.environ.get('NUCLEUS_DELIVERY_DUMP'):
        Path(os.environ['NUCLEUS_DELIVERY_DUMP']).write_text(
            json.dumps({'envelope': undone, 'receipt': deliver.read_receipt(receipt_id)},
                       indent=1, default=str), encoding='utf-8')
    assert undone['outcome'] == 'success', (
        undone['limitations'],
        [(c['check_id'], c['status'], c['reason']) for c in undone['checks']],
        undone['achieved'], deliver.read_receipt(receipt_id).get('undo_state'))
    remaining = _costume_files(project)
    assert unrelated in remaining, 'the unrelated customization must survive the undo'
    assert all(slot['filename'] != name for slot in added for _n, name in remaining)
    assert _digest(Path(project).parent / 'files' / unrelated[1]) == unrelated_digest

    assert output.is_file() and destination.produced_by_nucleus(output)
    assert _digest(output) == before_bytes, \
        'the exact copy they were playing before the delivery comes back'
    restored_entries = iso_reads.fst_entries(output)
    assert unrelated[1] in restored_entries, 'the unrelated costume must still be on the disc'
    leftover = next(c for c in undone['checks']
                    if c['check_id'] == 'costume_absent_from_disc_image')
    if leftover['status'] == 'pass':
        for slot in added:
            assert slot['filename'] not in restored_entries
    else:
        # MexCLI left the file in the project; it is no longer a colour anyone
        # can pick, which is what the costume table check establishes.
        assert leftover['status'] == 'warn'
        assert any('unused leftover' in line for line in undone['limitations'])
    assert played.read_bytes() == b'the file they play today'

    # ---- a second undo is harmless ----------------------------------------
    again = deliver.undo_delivery(receipt_id)
    assert again['outcome'] == 'success'
    assert 'already' in again['facts']['summary']
    assert _costume_files(project) == remaining
