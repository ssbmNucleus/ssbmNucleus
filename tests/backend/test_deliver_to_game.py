"""The delivery path: a vault costume into the game copy someone plays.

Graded against ASTRA-SESSIONS.md S06 (put it in my game, two projects, none
designated) and S07 (take it out, undo that), including their `must_not` lists,
and against the ASTRA-REVIEW-B1-B2 findings that followed the first version:

  S06  never test the unedited vault original / never choose the newest project
       without the user / never claim automated verification / never treat one
       costume as a full-project test.
  S07  never use folder organization as removal / never claim an undo that did
       not run / never delete both copies / never touch the copy the restored
       project uses.

The synthetic build here has the same on-disk shape a real one has --
``project.mexproj``, ``data/fighters/NNN.json``, ``files/<costume>.dat`` -- and
the export seam writes a REAL GameCube image with REAL payloads, so the checks
that decide `installed` (FST extents, the costume's bytes hashed out of the
disc, the saved copy hashed against the build) all run for real against real
disc bytes. What is stubbed is MexCLI and the length of the game.

`tests/backend/test_real_delivery_activation_restart_and_undo.py` is the counterpart
that runs the native tools end to end; it skips unless a clean Melee ISO,
MexCLI and a vault costume are all present.
"""
import json
import struct
from pathlib import Path

import pytest

from randall.assistant import approvals, tools
from randall.delivery import deliver, deliver_checks, deliver_policy, deliver_receipts, destination, projects
from core import config, playable_iso, state


# --------------------------------------------------------------------------
# a real, small GameCube image -- with payloads, not just names
# --------------------------------------------------------------------------

def write_disc(path, payloads):
    """A genuine GCM: real header, real FST, and every file's real bytes.

    The first version of this helper wrote FST entries pointing at payload that
    was never written. The verifier now hashes what the entry points at, so the
    fixture has to be a disc image that actually contains its files.
    """
    names = list(payloads)
    strings, offsets = b'', []
    for name in names:
        offsets.append(len(strings))
        strings += name.encode('ascii') + b'\0'
    count = len(names) + 1
    table_bytes = count * 12 + len(strings)
    data_start = (0x440 + table_bytes + 31) & ~31

    blobs, extents, cursor = b'', {}, data_start
    for name in names:
        payload = payloads[name]
        extents[name] = (cursor, len(payload))
        padding = (-len(payload)) % 32
        blobs += payload + bytes(padding)
        cursor += len(payload) + padding

    fst = bytearray()
    fst += bytes([1]) + (0).to_bytes(3, 'big') + struct.pack('>II', 0, count)
    for index, name in enumerate(names):
        start, size = extents[name]
        fst += bytes([0]) + offsets[index].to_bytes(3, 'big') + struct.pack('>II', start, size)
    fst += strings

    header = bytearray(0x440)
    header[0x1C:0x20] = bytes.fromhex('c2339f3d')
    struct.pack_into('>II', header, 0x424, 0x440, len(fst))
    image = bytearray(header + fst)
    image += bytes(data_start - len(image))
    image += blobs
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(image))
    return path


COSTUME_BYTES = b'BLUE FOX COSTUME DAT' * 8
OTHER_BYTES = b'SOMEBODY ELSES COSTUME' * 8


def costume_zip(member, payload):
    """A real ZIP holding one costume DAT.

    `projects._guard_install` opens every archive going into a project and runs
    each DAT through the release gate, so the fixture has to be an archive.
    """
    import io
    import zipfile
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr(member, payload)
    return buffer.getvalue()


# --------------------------------------------------------------------------
# fixture
# --------------------------------------------------------------------------

class Recorder:
    """Stands in for the export the Build button runs, and counts its calls."""

    def __init__(self, root):
        self.root = Path(root)
        self.calls = []
        self.fail = None
        self.corrupt = False

    def __call__(self, project, options=None, session=None):
        assert session is not None, 'the delivery must hand its build session through'
        assert getattr(session, 'directory', None) is not None, \
            'the exporter is handed the SESSION, not the context manager'
        self.calls.append((project['id'], dict(options or {})))
        if self.fail:
            return {'state': 'failed', 'error': self.fail, 'artifactId': None}
        artifact = f'build_{len(self.calls)}'
        path = self.root / f'{artifact}.iso'
        files = Path(project['path']).parent / 'files'
        payloads = {'Start.dol': b'DOL' * 16}
        for costume in sorted(files.glob('*.dat')) if files.is_dir() else []:
            payloads[costume.name] = (b'CORRUPT' * 4 if self.corrupt
                                      else costume.read_bytes())
        write_disc(path, payloads)
        return {'state': 'complete', 'error': None, 'artifactId': artifact,
                'path': str(path), 'warnings': [], 'filename': 'game.iso'}


def _make_project(root, name, fighters):
    target = root / name / 'project.mexproj'
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({'build': {'name': name}}))
    (target.parent / 'files').mkdir()
    folder = target.parent / 'data/fighters'
    folder.mkdir(parents=True)
    for fid, fighter_name, costumes in fighters:
        (folder / f'{fid:03}.json').write_text(json.dumps(
            {'name': fighter_name, 'costumes': costumes}))
    return target


@pytest.fixture
def game(vault, monkeypatch, tmp_path):
    """Two builds the user could mean, and one Blue Fox in the library."""
    root = vault.project_root / 'projects'
    root.mkdir(parents=True)
    normal = [{'name': 'Normal', 'file': {'fileName': 'PlFxNr.dat'}}]
    mine = _make_project(root, 'My Melee', [(2, 'Fox', list(normal))])
    friday = _make_project(root, 'Friday Melee', [(2, 'Fox', list(normal))])
    for project in (mine, friday):
        (project.parent / 'files' / 'PlFxNr.dat').write_bytes(b'VANILLA FOX' * 8)
    monkeypatch.setattr(config, 'PROJECTS_PATH', root)
    monkeypatch.setattr(config, 'OUTPUT_PATH', tmp_path / 'output')
    cli = vault.project_root / 'mexcli'
    cli.write_bytes(b'test executable placeholder')
    monkeypatch.setattr(config, 'MEXCLI_PATH', cli)
    monkeypatch.setattr(state, '_current_project_path', friday)   # the OPEN one is not the target
    monkeypatch.setattr(state, 'reload_mex_manager', lambda: None)
    monkeypatch.setattr(deliver_checks, 'MIN_PLAYABLE_ISO_BYTES', 16)

    # A recorded clean Melee source, so the write-protection rules have one.
    from shared.vanilla_extract import vanilla_refs
    clean = tmp_path / 'clean melee.iso'
    clean.write_bytes(b'CLEAN MELEE')
    record = tmp_path / 'vanilla_iso.json'
    record.write_text(json.dumps({'path': str(clean)}), encoding='utf-8')
    monkeypatch.setattr(vanilla_refs, 'ISO_RECORD_PATH', record)
    monkeypatch.setattr(destination, 'launcher_iso', lambda: None)

    vault.write({'characters': {'Fox': {'skins': [
        {'id': 'bluefox', 'name': 'Blue Fox', 'filename': 'bluefox.zip',
         'slippi_safe': True, 'slippi_tested': True, 'slippi_test_date': '2026-09-01',
         'dat_hash': 'abc123'}]}}})
    vault.touch('Fox', 'bluefox.zip', data=costume_zip('PlFxBu.dat', COSTUME_BYTES))

    imports, removals = [], []

    def import_costumes(self, manifest):
        imports.append((str(self.project_path), manifest))
        _append_costume(Path(self.project_path), 2, 'Blue Fox', 'PlFxBu.dat', COSTUME_BYTES)
        return {'totalImported': 1, 'totalFailed': 0, 'perFighter': {'Fox': {'imported': 1}}}

    def remove_costumes(self, manifest):
        removals.append((str(self.project_path), manifest))
        removed = 0
        for fighter, indices in manifest.items():
            for index in sorted((int(i) for i in indices), reverse=True):
                removed += _drop_costume(Path(self.project_path), int(fighter), index)
        return {'success': True, 'totalRemoved': removed, 'totalFailed': 0}

    from mexcli.project import MexManager
    monkeypatch.setattr(MexManager, 'import_costumes', import_costumes)
    monkeypatch.setattr(MexManager, 'remove_costumes', remove_costumes)

    export = Recorder(tmp_path / 'artifacts')
    ids = {project['name']: project['id'] for project in projects.list_projects()['projects']}
    return {'mine': mine, 'friday': friday, 'ids': ids, 'export': export,
            'imports': imports, 'removals': removals, 'vault': vault, 'tmp': tmp_path,
            'clean_iso': clean}


def _fighter_path(project_file, fighter_id):
    return Path(project_file).parent / 'data/fighters' / f'{fighter_id:03}.json'


def _append_costume(project_file, fighter_id, name, filename, payload):
    path = _fighter_path(project_file, fighter_id)
    data = json.loads(path.read_text())
    data['costumes'].append({'name': name, 'file': {'fileName': filename}})
    path.write_text(json.dumps(data))
    (Path(project_file).parent / 'files' / filename).write_bytes(payload)


def _drop_costume(project_file, fighter_id, index):
    path = _fighter_path(project_file, fighter_id)
    data = json.loads(path.read_text())
    if index >= len(data['costumes']):
        return 0
    gone = data['costumes'].pop(index)
    path.write_text(json.dumps(data))
    name = (gone.get('file') or {}).get('fileName')
    if name:
        (Path(project_file).parent / 'files' / name).unlink(missing_ok=True)
    return 1


def blue_fox(**extra):
    return {'character': 'Fox', 'skin_id': 'bluefox', **extra}


def run(game, **extra):
    return deliver.deliver_to_game(_export=game['export'], **blue_fox(**extra))


def costumes(project_file, fighter_id=2):
    return json.loads(_fighter_path(project_file, fighter_id).read_text())['costumes']


def offline_destination(game, output, project='My Melee'):
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    return destination.designate('offline_build', project_id=game['ids'][project],
                                 output_iso_path=str(output))


# --------------------------------------------------------------------------
# S06: the destination is chosen by the user, by name
# --------------------------------------------------------------------------

def test_two_builds_and_no_designation_is_a_decision_that_writes_nothing(game):
    result = run(game)
    assert result['state'] == 'waiting_decision' and result['outcome'] is None
    assert result['next']['kind'] == 'decision'
    assert 'My Melee' in result['next']['prompt'] and 'Friday Melee' in result['next']['prompt']
    assert {row['name'] for row in result['facts']['builds']} == {'My Melee', 'Friday Melee'}
    assert not any(result['achieved'].values())
    assert game['imports'] == [] and game['export'].calls == []
    assert len(costumes(game['mine'])) == 1 and len(costumes(game['friday'])) == 1
    assert deliver.list_deliveries() == []


def test_one_build_is_still_a_choice_not_a_default(game, monkeypatch, tmp_path):
    """Being the only project on the machine is not the same as being chosen."""
    only = tmp_path / 'solo'
    only.mkdir()
    _make_project(only, 'Only Melee', [(2, 'Fox', [{'name': 'Normal',
                                                    'file': {'fileName': 'PlFxNr.dat'}}])])
    monkeypatch.setattr(config, 'PROJECTS_PATH', only)
    monkeypatch.setattr(state, '_current_project_path', None)
    result = run(game)
    assert result['state'] == 'waiting_decision'
    assert 'Only Melee' in result['next']['prompt']
    assert game['imports'] == []


def test_named_build_is_the_target_even_when_another_project_is_open(game, tmp_path):
    offline_destination(game, tmp_path / 'games' / 'my.iso')
    result = run(game, project_id=game['ids']['My Melee'])
    assert result['facts']['target_build_id'] == game['ids']['My Melee']
    assert game['imports'][0][0] == str(game['mine'].resolve())
    assert game['export'].calls[0][0] == game['ids']['My Melee']
    assert len(costumes(game['friday'])) == 1
    assert state.get_current_project_path() == game['friday']


def test_no_build_at_all_is_blocked_not_a_guess(game, monkeypatch, tmp_path):
    monkeypatch.setattr(config, 'PROJECTS_PATH', tmp_path / 'empty')
    monkeypatch.setattr(state, '_current_project_path', None)
    result = run(game)
    assert result['outcome'] == 'blocked' and not any(result['achieved'].values())
    assert 'no game copy' in result['facts']['limitation_that_matters'].lower()
    assert game['imports'] == []


def test_naming_a_project_and_a_different_game_copy_is_refused(game, tmp_path):
    record = offline_destination(game, tmp_path / 'games' / 'my.iso')
    result = run(game, destination_id=record['id'], project_id=game['ids']['Friday Melee'])
    assert result['outcome'] == 'blocked'
    assert 'I will not build one and save the other' in \
        result['facts']['limitation_that_matters']
    assert game['imports'] == []


# --------------------------------------------------------------------------
# installed means the file you launch changed -- nothing less
# --------------------------------------------------------------------------

def test_a_project_with_no_playable_copy_is_never_installed(game):
    """The first version called an internal artifact "ready". It is not."""
    result = run(game, project_id=game['ids']['My Melee'])
    assert result['achieved']['prepared'] is True
    assert result['achieved']['exported'] is True
    assert result['achieved']['installed'] is False
    assert result['outcome'] == 'partial'
    assert 'no game copy of yours changed' in result['facts']['summary']
    # Said for a person: no "disc image" on the card (2026-10-06 launch-film run).
    assert 'disc image' not in result['facts']['summary'] + result['facts']['limitation_that_matters']
    # The way on is a call that exists: make this project the game they play
    # (set_as_my_game), or play it now in a test game, which needs no game copy.
    offered = result['next']['allowed_responses']
    assert {row.get('set_as_my_game') for row in offered
            if row.get('action') == 'deliver_to_game'} == {'slippi', 'offline'}
    assert all(row.get('project_id') == game['ids']['My Melee'] for row in offered
               if row.get('action') == 'deliver_to_game')
    assert [row for row in offered if row.get('action') == 'test_in_game'] == [
        {'action': 'test_in_game', 'kind': 'costume', 'character': 'Fox', 'skin_id': 'bluefox',
         'label': 'Just let me play it now'}]
    assert all(row.get('label') for row in offered)


# --------------------------------------------------------------------------
# "make it my game": the user designates on the delivery's approval card
# --------------------------------------------------------------------------

def test_set_as_my_game_designates_the_project_and_installs_into_a_new_file(game):
    assert destination.default_destination() is None
    result = run(game, project_id=game['ids']['My Melee'], set_as_my_game='offline')
    assert result['outcome'] == 'success'
    assert result['achieved']['installed'] is True
    record = destination.default_destination()
    assert record['kind'] == 'offline_build' and record['label'] == 'My Melee'
    assert record['project_ref']['project_id'] == game['ids']['My Melee']
    output = Path(record['output_iso_ref']['path'])
    assert output.name == 'My_Melee (Nucleus).iso'
    assert output.parent == Path(config.OUTPUT_PATH) / 'games'
    assert output.is_file() and playable_iso.produced_by_nucleus(output)
    assert game['clean_iso'].read_bytes() == b'CLEAN MELEE'
    assert len(game['imports']) == 1


def test_the_approval_card_names_the_new_game_and_nothing_is_designated_before_it(
        game, monkeypatch):
    monkeypatch.setattr(deliver, '_default_export', game['export'])
    call = tools.prepare('deliver_to_game', blue_fox(project_id=game['ids']['My Melee'],
                                                     set_as_my_game='offline'))
    preview = json.loads(call.preview)
    assert 'make it the game you play' in preview['title']
    assert 'My_Melee (Nucleus).iso' in preview['consequence']
    assert 'No file you already have is changed' in preview['consequence']
    assert preview['designation']['output_filename'] == 'My_Melee (Nucleus).iso'
    assert preview['confirm_label'] == 'Add it and make My Melee my game'
    assert destination.read_settings()['destinations'] == {}
    assert 'approval' in tools.execute(call)['error']
    assert destination.read_settings()['destinations'] == {}
    result = tools.execute(call, approvals.Grant(call.fingerprint))
    assert result['achieved']['installed'] is True
    assert destination.default_destination()['project_ref']['project_id'] == \
        game['ids']['My Melee']


def test_an_approval_to_make_it_my_game_does_not_survive_another_designation(
        game, monkeypatch, tmp_path):
    monkeypatch.setattr(deliver, '_default_export', game['export'])
    call = tools.prepare('deliver_to_game', blue_fox(project_id=game['ids']['My Melee'],
                                                     set_as_my_game='offline'))
    offline_destination(game, tmp_path / 'games' / 'friday.iso', project='Friday Melee')
    result = tools.execute(call, approvals.Grant(call.fingerprint))
    assert 'changed after you approved' in result['error']
    assert game['imports'] == []
    assert destination.for_project(game['ids']['My Melee']) == []


def test_finishing_a_project_only_delivery_promotes_that_build_without_a_second_slot(game):
    first = run(game, project_id=game['ids']['My Melee'])
    assert first['outcome'] == 'partial' and first['achieved']['installed'] is False
    finished = run(game, project_id=game['ids']['My Melee'], set_as_my_game='offline')
    assert finished['achieved']['installed'] is True
    assert finished['facts']['resumed'] is True
    assert finished['facts']['receipt_id'] == first['facts']['receipt_id']
    assert len(game['imports']) == 1, 'the costume is imported once'
    assert len(game['export'].calls) == 1, 'the verified build is promoted, not rebuilt'
    assert [c['name'] for c in costumes(game['mine'])] == ['Normal', 'Blue Fox']
    undone = deliver.undo_delivery(finished['facts']['receipt_id'], _export=game['export'])
    assert undone['outcome'] == 'success'
    assert [c['name'] for c in costumes(game['mine'])] == ['Normal']


def test_a_slippi_launcher_on_the_clean_melee_file_is_left_alone(game, monkeypatch):
    """The clean file has no mods to lose: no "start a separate copy" question, and it is
    never written. The new copy is saved, and is active once Launcher points at it."""
    monkeypatch.setattr(destination, 'launcher_iso', lambda: str(game['clean_iso']))
    plan, preview = deliver.plan_delivery(blue_fox(project_id=game['ids']['My Melee'],
                                                   set_as_my_game='slippi'))
    assert plan['designation']['played_status'] == 'played_is_clean_source'
    assert any('keeps opening clean melee.iso' in line for line in preview['limitations'])
    result = run(game, project_id=game['ids']['My Melee'], set_as_my_game='slippi')
    assert game['clean_iso'].read_bytes() == b'CLEAN MELEE'
    record = destination.default_destination()
    assert record['kind'] == 'slippi_netplay'
    assert record['played_iso_decision']['status'] == 'played_is_clean_source'
    assert Path(record['output_iso_ref']['path']).is_file()
    assert result['achieved']['exported'] is True
    assert result['outcome'] == 'partial' and 'not active yet' in result['facts']['summary']


def test_making_a_slippi_game_over_a_modded_played_file_still_asks_first(
        game, tmp_path, monkeypatch):
    played = tmp_path / 'Melee (modded).iso'
    played.write_bytes(b'not clean melee')
    monkeypatch.setattr(destination, 'launcher_iso', lambda: str(played))
    asked = run(game, project_id=game['ids']['My Melee'], set_as_my_game='slippi')
    assert asked['outcome'] == 'blocked'
    assert 'separate copy from clean Melee' in asked['facts']['limitation_that_matters']
    assert destination.read_settings()['destinations'] == {} and game['imports'] == []
    done = run(game, project_id=game['ids']['My Melee'], set_as_my_game='slippi',
               start_from_clean=True)
    assert done['achieved']['exported'] is True
    assert played.read_bytes() == b'not clean melee'


def test_set_as_my_game_is_refused_when_that_project_already_is_one(game, tmp_path):
    offline_destination(game, tmp_path / 'games' / 'my.iso')
    result = run(game, project_id=game['ids']['My Melee'], set_as_my_game='offline')
    assert result['outcome'] == 'blocked'
    assert 'already set as the game you play' in result['facts']['limitation_that_matters']
    assert game['imports'] == []


def test_a_delivery_never_closes_the_chats_task_mid_turn(game):
    """The task is the run's objective; a partial delivery that finished it made the
    next model round refuse ("That task already finished as partial; it cannot spend
    more"), and that refusal was the user's last line."""
    from randall.assistant import turn_facts
    from randall.assistant.tasks import coordinator
    task = coordinator.start('', family='randall_turn')
    with coordinator.attach(task):
        result = run(game, project_id=game['ids']['My Melee'])
        assert result['outcome'] == 'partial' and result['state'] == 'completed'
        assert not task.finished
        task.admit()                      # the reply round after the tool may still run
    assert task.envelope.facts['receipt_id'] == result['facts']['receipt_id']
    answer = {'status': 'done', 'tools': [{'name': 'deliver_to_game', 'status': 'done',
                                           'result': result}]}
    assert turn_facts._turn_outcome(type('R', (), {'answer': answer})(), task)[0] == 'partial'


def test_a_designated_offline_copy_is_written_verified_and_ready(game, tmp_path):
    output = tmp_path / 'games' / 'My Melee (Nucleus).iso'
    offline_destination(game, output)
    result = run(game)
    assert result['outcome'] == 'success'
    assert result['achieved'] == {'prepared': True, 'exported': True,
                                  'installed': True, 'previewed': False}
    assert result['facts']['summary'] == ('Saved to My offline build. '
                                          'Your updated game copy is ready.')
    assert output.is_file()
    assert destination.produced_by_nucleus(output)
    saved = next(c for c in result['checks'] if c['check_id'] == 'saved_copy_matches_build')
    assert saved['status'] == 'pass'
    disc = next(c for c in result['checks'] if c['check_id'] == 'costume_in_disc_image')
    assert disc['status'] == 'pass'
    for key in ('what_changed', 'where', 'limitation_that_matters', 'how_to_undo'):
        assert result['facts'][key]
    assert 'Fox slot 2' in result['facts']['what_changed']


def test_an_offline_copy_with_no_bound_player_offers_to_choose_one(game, tmp_path):
    """"Open game" needs a player the user bound; otherwise say so."""
    offline_destination(game, tmp_path / 'games' / 'my.iso')
    result = run(game)
    assert result['achieved']['installed'] is True
    actions = [row.get('action') for row in result['next']['allowed_responses']]
    assert 'choose_emulator' in actions
    assert 'choose an emulator' in result['next']['prompt']


def test_a_disc_image_with_the_right_name_but_the_wrong_bytes_is_not_installed(game, tmp_path):
    """A filename is not evidence: the payload is hashed against the project."""
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    game['export'].corrupt = True
    result = run(game)
    assert result['achieved']['installed'] is False
    assert result['achieved']['exported'] is False
    assert result['outcome'] == 'partial'
    disc = next(c for c in result['checks'] if c['check_id'] == 'costume_in_disc_image')
    assert disc['status'] == 'fail' and disc['measured_values']['wrong_bytes'] == ['PlFxBu.dat']
    assert not output.exists(), 'an unverified build must never be written to the played file'


def test_export_failure_leaves_prepared_and_resumes_without_reinstalling(game, tmp_path):
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    game['export'].fail = 'MexCLI ran out of disk space'
    first = run(game)
    assert first['achieved'] == {'prepared': True, 'exported': False,
                                 'installed': False, 'previewed': False}
    assert first['outcome'] == 'partial'
    assert 'ran out of disk space' in first['facts']['limitation_that_matters']
    assert len(game['imports']) == 1

    game['export'].fail = None
    second = run(game)
    assert second['achieved']['installed'] is True
    assert second['facts']['receipt_id'] == first['facts']['receipt_id']
    assert len(game['imports']) == 1, 'the resumed attempt must not install a second time'
    assert [c['name'] for c in costumes(game['mine'])] == ['Normal', 'Blue Fox']


def test_prepare_only_stops_at_the_project_files_and_says_so(game, tmp_path):
    offline_destination(game, tmp_path / 'games' / 'my.iso')
    result = run(game, outcome='prepare')
    assert result['outcome'] == 'success'
    assert result['achieved']['prepared'] and not result['achieved']['installed']
    assert game['export'].calls == []
    assert 'not been rebuilt' in result['facts']['limitation_that_matters']
    assert 'deliver_to_game' in [row.get('action') for row in result['next']['allowed_responses']]


def test_prepare_then_install_finishes_the_missing_phases(game, tmp_path):
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    prepared = run(game, outcome='prepare')
    assert game['export'].calls == []
    installed = run(game, outcome='install')
    assert installed['facts']['receipt_id'] == prepared['facts']['receipt_id']
    assert installed['achieved']['installed'] is True
    assert len(game['imports']) == 1 and len(game['export'].calls) == 1
    assert output.is_file()


# --------------------------------------------------------------------------
# write protection: what this app may and may not write over
# --------------------------------------------------------------------------

def test_the_clean_melee_iso_can_never_be_a_destination(game):
    with pytest.raises(destination.DestinationError) as error:
        destination.designate('offline_build', project_id=game['ids']['My Melee'],
                              output_iso_path=str(game['clean_iso']))
    assert 'clean Melee file' in str(error.value)
    assert destination.read_settings()['destinations'] == {}


def test_a_file_nucleus_did_not_make_is_never_written_over(game, tmp_path):
    foreign = tmp_path / 'games' / 'someone elses build.iso'
    foreign.parent.mkdir(parents=True, exist_ok=True)
    foreign.write_bytes(b'NOT OURS')
    with pytest.raises(destination.DestinationError) as error:
        destination.designate('offline_build', project_id=game['ids']['My Melee'],
                              output_iso_path=str(foreign))
    assert str(error.value) == destination.FOREIGN_FILE
    assert foreign.read_bytes() == b'NOT OURS'


def test_only_a_nucleus_made_copy_is_replaced_and_only_after_verification(game, tmp_path):
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    first = run(game)
    assert first['achieved']['installed'] is True
    first_digest = destination.digest_file(output)

    # A second delivery of the same costume changes nothing and rewrites nothing.
    second = run(game)
    assert second['facts']['receipt_id'] == first['facts']['receipt_id']
    assert destination.digest_file(output) == first_digest
    assert len(game['imports']) == 1 and len(game['export'].calls) == 1

    # The marker is what makes the copy ours; without it we refuse it.
    destination.marker_path(output).unlink()
    assert destination.produced_by_nucleus(output) is False
    available = destination.availability(destination.default_destination())
    assert available['ready'] is False and available['blocker'] == 'output_not_ours'


def test_a_delivery_into_a_foreign_output_refuses_before_writing(game, tmp_path):
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    output.write_bytes(b'SOMEONE PUT THIS HERE')      # no marker
    result = run(game)
    assert result['outcome'] == 'blocked'
    assert destination.FOREIGN_FILE in result['facts']['limitation_that_matters']
    assert output.read_bytes() == b'SOMEONE PUT THIS HERE'
    assert game['imports'] == []


def test_the_played_iso_rule_refuses_to_start_over_quietly(game, tmp_path, monkeypatch):
    played = tmp_path / 'Melee (modded).iso'
    played.write_bytes(b'not clean melee')
    monkeypatch.setattr(destination, 'launcher_iso', lambda: str(played))
    (tmp_path / 'games').mkdir(exist_ok=True)
    with pytest.raises(destination.DestinationError) as error:
        destination.designate('slippi_netplay', project_id=game['ids']['My Melee'],
                              output_iso_path=str(tmp_path / 'games' / 'out.iso'))
    assert 'separate copy from clean Melee' in str(error.value)
    assert destination.read_settings()['destinations'] == {}

    with pytest.raises(destination.DestinationError) as same:
        destination.designate('slippi_netplay', project_id=game['ids']['My Melee'],
                              output_iso_path=str(played), start_from_clean=True)
    assert 'cannot write over' in str(same.value) or \
        str(same.value) == destination.FOREIGN_FILE
    assert played.read_bytes() == b'not clean melee'


# --------------------------------------------------------------------------
# every write target, not just the primary one
# --------------------------------------------------------------------------

def _foreign(path, data=b'SOMEBODY ELSE MADE THIS'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_a_foreign_file_at_the_backup_name_is_never_replaced(game, tmp_path, monkeypatch):
    """The backup name is allocated exclusively; it never lands on a file."""
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    run(game)                                      # first delivery: output exists now

    taken = []

    def always_taken(directory, name_factory, attempts=8):
        # Every generated name is already occupied by somebody else's file.
        for _ in range(attempts):
            taken.append(_foreign(Path(directory) / name_factory()))
        raise playable_iso.ProtectedPath('Could not reserve a free filename beside your '
                                         'game copy.')

    monkeypatch.setattr(playable_iso, '_create_exclusive', always_taken)
    game['vault'].write({'characters': {'Fox': {'skins': [
        {'id': 'bluefox', 'name': 'Blue Fox', 'filename': 'bluefox.zip', 'slippi_safe': True},
        {'id': 'redfox', 'name': 'Red Fox', 'filename': 'redfox.zip', 'slippi_safe': True}]}}})
    game['vault'].touch('Fox', 'redfox.zip', data=costume_zip('PlFxRd.dat', OTHER_BYTES))
    from mexcli.project import MexManager
    original = MexManager.import_costumes
    MexManager.import_costumes = lambda self, manifest: (
        _append_costume(Path(self.project_path), 2, 'Red Fox', 'PlFxRd.dat', OTHER_BYTES)
        or {'totalImported': 1, 'totalFailed': 0})
    try:
        result = deliver.deliver_to_game(_export=game['export'], character='Fox',
                                         skin_id='redfox')
    finally:
        MexManager.import_costumes = original
    assert result['achieved']['installed'] is False
    assert 'reserve a free filename' in result['facts']['limitation_that_matters']
    for path in taken:
        assert path.read_bytes() == b'SOMEBODY ELSE MADE THIS'


def test_the_clean_melee_file_is_never_taken_as_a_backup_name(game, tmp_path, monkeypatch):
    """A generated backup name that lands on the clean ISO is skipped, not used."""
    clean = game['clean_iso']
    names = iter([clean.name, 'free-name.iso'])
    monkeypatch.setattr(playable_iso.os, 'urandom', lambda n: b'\x01' * n)
    chosen = playable_iso._create_exclusive(clean.parent, lambda: next(names))
    assert chosen.name == 'free-name.iso'
    assert clean.read_bytes() == b'CLEAN MELEE'
    chosen.unlink()


def test_pruning_never_deletes_a_file_whose_marker_no_longer_matches(game, tmp_path):
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    run(game)
    # A backup that somebody has since replaced: the marker is stale, so the
    # bytes are not ours and the file stays exactly where it is.
    impostor = output.with_name(f'{output.stem}.previous-stale{output.suffix}')
    impostor.write_bytes(b'NOT WHAT THE MARKER SAYS')
    playable_iso.write_marker(impostor, {'output_digest': 'sha256:' + '0' * 64})
    assert playable_iso.prune_backups(output, keep=0) == []
    assert impostor.read_bytes() == b'NOT WHAT THE MARKER SAYS'


def test_pruning_never_deletes_the_clean_iso_or_a_designated_copy(game, tmp_path):
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    # A clean-Melee file sitting under the backup glob, with a matching marker.
    trap = output.with_name(f'{output.stem}.previous-trap{output.suffix}')
    trap.write_bytes(b'CLEAN MELEE')
    playable_iso.write_marker(trap, {'output_digest': playable_iso.digest_file(trap)})
    from shared.vanilla_extract import vanilla_refs
    Path(vanilla_refs.ISO_RECORD_PATH).write_text(json.dumps({'path': str(trap)}),
                                                  encoding='utf-8')
    assert playable_iso.prune_backups(output, keep=0) == []
    assert trap.is_file()


def test_pruning_removes_at_most_one_of_our_own_stale_copies(game, tmp_path):
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    ours = []
    for index in range(3):
        path = output.with_name(f'{output.stem}.previous-{index}{output.suffix}')
        path.write_bytes(b'OUR OLD BUILD %d' % index)
        playable_iso.write_marker(path, {'output_digest': playable_iso.digest_file(path)})
        ours.append(path)
    assert len(playable_iso.prune_backups(output, keep=0)) == 1
    assert sum(1 for path in ours if path.is_file()) == 2


def test_a_destination_replaced_during_the_copy_is_not_overwritten(game, tmp_path,
                                                                   monkeypatch):
    """The check-to-write interval: somebody else's file arrives mid-copy."""
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    real_copy = playable_iso.shutil.copyfile

    def copy_then_intrude(src, dst):
        real_copy(src, dst)
        _foreign(output)                      # a foreign ISO appears at the target
    monkeypatch.setattr(playable_iso.shutil, 'copyfile', copy_then_intrude)
    result = run(game)
    assert result['achieved']['installed'] is False
    assert destination.FOREIGN_FILE in result['facts']['limitation_that_matters']
    assert output.read_bytes() == b'SOMEBODY ELSE MADE THIS'


def test_the_launcher_selected_path_is_refused_even_when_it_does_not_exist_yet(game, tmp_path,
                                                                              monkeypatch):
    wanted = tmp_path / 'games' / 'Melee.iso'
    wanted.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(playable_iso, 'launcher_iso', lambda: str(wanted))
    monkeypatch.setattr(destination, 'launcher_iso', lambda: str(wanted))
    assert not wanted.exists()
    with pytest.raises(destination.DestinationError) as error:
        destination.designate('offline_build', project_id=game['ids']['My Melee'],
                              output_iso_path=str(wanted))
    assert 'Slippi Launcher is set to open' in str(error.value)


def test_a_foreign_file_at_the_marker_name_is_never_replaced(game, tmp_path):
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    squatter = playable_iso.marker_path(output)
    _foreign(squatter, b'{"not": "ours"}')
    result = run(game)
    assert result['achieved']['installed'] is False
    assert 'did not write' in result['facts']['limitation_that_matters']
    assert squatter.read_bytes() == b'{"not": "ours"}'


def test_the_save_button_obeys_the_same_rule(game, tmp_path):
    """The export screen's Save is the same publisher, so the rule covers it."""
    import projects.install.export_job as export_module
    artifact = tmp_path / 'artifacts' / 'build_x.iso'
    write_disc(artifact, {'Start.dol': b'DOL' * 16})

    refused = export_module.copy_artifact_to(artifact, game['clean_iso'])
    assert isinstance(refused, playable_iso.ProtectedPath)
    assert game['clean_iso'].read_bytes() == b'CLEAN MELEE'

    foreign = _foreign(tmp_path / 'games' / 'theirs.iso')
    assert isinstance(export_module.copy_artifact_to(artifact, foreign),
                      playable_iso.ProtectedPath)
    assert foreign.read_bytes() == b'SOMEBODY ELSE MADE THIS'

    fresh = tmp_path / 'games' / 'ours.iso'
    assert export_module.copy_artifact_to(artifact, fresh) is None
    assert playable_iso.produced_by_nucleus(fresh)
    # saving over our own build again is allowed, and keeps the previous bytes
    assert export_module.copy_artifact_to(artifact, fresh) is None


# --------------------------------------------------------------------------
# activation follows play mode, not the record's kind
# --------------------------------------------------------------------------

def test_a_slippi_copy_is_saved_but_not_active_until_the_launcher_points_at_it(
        game, tmp_path, monkeypatch):
    played = tmp_path / 'Melee.iso'
    played.write_bytes(b'whatever they play now')
    output = tmp_path / 'games' / 'My Melee (Nucleus).iso'
    output.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(destination, 'launcher_iso', lambda: str(played))
    record = destination.designate('slippi_netplay', project_id=game['ids']['My Melee'],
                                   output_iso_path=str(output), start_from_clean=True)
    result = run(game)
    assert output.is_file() and played.read_bytes() == b'whatever they play now'
    assert result['achieved']['exported'] is True
    assert result['achieved']['installed'] is False
    assert result['outcome'] == 'partial'
    assert 'not active yet' in result['facts']['summary']
    assert 'Slippi Launcher' in result['next']['prompt']
    assert destination.get(record['id'])['activation']['status'] == 'pending'

    monkeypatch.setattr(destination, 'launcher_iso', lambda: str(output))
    assert destination.confirm_activation(record['id'])['status'] == 'verified'
    finished = run(game)
    assert finished['achieved']['installed'] is True


def test_a_project_destination_played_on_slippi_still_needs_the_launcher_step(
        game, tmp_path, monkeypatch):
    """Activation branches on PLAY MODE. Branching on kind exempted this case."""
    output = tmp_path / 'games' / 'proj.iso'
    output.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(destination, 'launcher_iso', lambda: str(tmp_path / 'other.iso'))
    destination.designate('project', project_id=game['ids']['My Melee'],
                          play_mode='slippi_netplay', output_iso_path=str(output))
    result = run(game)
    assert result['achieved']['installed'] is False
    assert 'not active yet' in result['facts']['limitation_that_matters']


def test_an_unreadable_launcher_configuration_is_unknown_and_offered_as_your_word(
        game, tmp_path, monkeypatch):
    output = tmp_path / 'games' / 'my.iso'
    output.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(destination, 'launcher_iso', lambda: str(tmp_path / 'played.iso'))
    (tmp_path / 'played.iso').write_bytes(b'played')
    record = destination.designate('slippi_netplay', project_id=game['ids']['My Melee'],
                                   output_iso_path=str(output), start_from_clean=True)
    monkeypatch.setattr(destination, 'launcher_iso', lambda: None)
    result = run(game)
    assert result['facts']['activation']['status'] == 'unknown'
    assert 'cannot tell what your player will open' in \
        result['facts']['limitation_that_matters']
    assert 'i_selected_this_file' in [row.get('action')
                                      for row in result['next']['allowed_responses']]
    assert destination.confirm_activation(record['id'],
                                          by_user=True)['status'] == 'user_confirmed'
    assert run(game)['achieved']['installed'] is True


# --------------------------------------------------------------------------
# S06: evidence kinds stay apart, and a label is reported as what it is
# --------------------------------------------------------------------------

def test_verification_facts_keep_play_and_checks_and_build_apart(game, tmp_path):
    offline_destination(game, tmp_path / 'games' / 'my.iso')
    facts = run(game)['facts']['verification']
    assert set(facts) == {'interactive_play', 'automated_costume_checks', 'full_build_checks'}
    assert 'Not run' in facts['automated_costume_checks']
    assert 'Not run' in facts['full_build_checks']
    assert 'rest of the build was not re-verified' in facts['full_build_checks']


def test_a_validator_label_is_reported_with_its_provenance(game, tmp_path):
    offline_destination(game, tmp_path / 'games' / 'my.iso')
    result = run(game)
    label = next(c for c in result['checks'] if c['check_id'] == 'slippi_online_label')
    assert label['status'] == 'pass'
    assert 'checked by the importer' in label['measured_values']['provenance']
    assert label['measured_values']['tested_bytes'] == 'abc123'
    assert 'Nothing was tested just now' in label['reason']


def test_a_hand_set_label_is_never_reported_as_a_check(game, tmp_path):
    data = game['vault'].read()
    data['characters']['Fox']['skins'][0].update({'slippi_manual_override': True,
                                                  'slippi_tested': False})
    game['vault'].write(data)
    offline_destination(game, tmp_path / 'games' / 'my.iso')
    result = run(game)
    label = next(c for c in result['checks'] if c['check_id'] == 'slippi_online_label')
    assert label['status'] == 'unknown'
    assert 'set by hand' in label['measured_values']['provenance']
    assert any('set by hand' in line for line in result['limitations'])


def test_an_unsafe_costume_bound_for_an_online_copy_stops_and_asks(game, tmp_path,
                                                                   monkeypatch):
    """A warning added afterwards is not a choice. This one is asked first."""
    data = game['vault'].read()
    data['characters']['Fox']['skins'][0].update({'slippi_safe': False, 'slippi_tested': True})
    game['vault'].write(data)
    output = tmp_path / 'games' / 'my.iso'
    output.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(destination, 'launcher_iso', lambda: None)
    destination.designate('slippi_netplay', project_id=game['ids']['My Melee'],
                          output_iso_path=str(output), start_from_clean=True)

    with pytest.raises(deliver_policy.OnlineRiskUndecided):
        deliver.plan_delivery(blue_fox())
    asked = run(game)
    assert asked['state'] == 'waiting_decision'
    assert 'NOT safe for online play' in asked['facts']['limitation_that_matters']
    actions = [row.get('action') for row in asked['next']['allowed_responses']]
    assert actions == ['deliver_to_game', 'designate_destination']
    assert game['imports'] == [] and not output.exists()

    _plan, preview = deliver.plan_delivery(blue_fox(online_risk_accepted=True))
    assert any('NOT safe for online play' in line for line in preview['limitations'])
    assert any('likely to cause problems online' in line for line in preview['limitations'])
    decided = run(game, online_risk_accepted=True)
    assert decided['achieved']['exported'] is True


# --------------------------------------------------------------------------
# S07: undo restores the game, names what came back, never touches the library
# --------------------------------------------------------------------------

def test_undo_restores_the_project_and_the_copy_you_were_playing(game, tmp_path):
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    output.write_bytes(b'')                       # no previous copy of ours yet
    output.unlink()
    delivered = run(game)
    assert delivered['achieved']['installed'] is True
    with_costume = destination.digest_file(output)

    result = deliver.undo_delivery(delivered['facts']['receipt_id'], _export=game['export'])
    assert result['outcome'] == 'success'
    assert game['removals'] == [(str(game['mine'].resolve()), {'2': [1]})]
    assert [c['name'] for c in costumes(game['mine'])] == ['Normal']
    assert destination.digest_file(output) != with_costume
    assert destination.produced_by_nucleus(output)
    gone = next(c for c in result['checks'] if c['check_id'] == 'costume_absent_from_disc_image')
    assert gone['status'] == 'pass'
    back = next(c for c in result['checks'] if c['check_id'] == 'playable_copy_restored')
    assert back['status'] == 'pass'


def test_undo_puts_the_exact_previous_playable_copy_back(game, tmp_path):
    """Two deliveries: undoing the second restores the FIRST one's bytes."""
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    first = run(game)
    after_first = destination.digest_file(output)

    # a second, different costume
    game['vault'].write({'characters': {'Fox': {'skins': [
        {'id': 'bluefox', 'name': 'Blue Fox', 'filename': 'bluefox.zip', 'slippi_safe': True,
         'slippi_tested': True},
        {'id': 'redfox', 'name': 'Red Fox', 'filename': 'redfox.zip', 'slippi_safe': True,
         'slippi_tested': True}]}}})
    game['vault'].touch('Fox', 'redfox.zip', data=costume_zip('PlFxRd.dat', OTHER_BYTES))
    from mexcli.project import MexManager
    original = MexManager.import_costumes

    def second_import(self, manifest):
        _append_costume(Path(self.project_path), 2, 'Red Fox', 'PlFxRd.dat', OTHER_BYTES)
        return {'totalImported': 1, 'totalFailed': 0, 'perFighter': {'Fox': {'imported': 1}}}

    MexManager.import_costumes = second_import
    try:
        second = deliver.deliver_to_game(_export=game['export'], character='Fox',
                                         skin_id='redfox')
    finally:
        MexManager.import_costumes = original
    assert second['achieved']['installed'] is True
    assert destination.digest_file(output) != after_first

    result = deliver.undo_delivery(second['facts']['receipt_id'], _export=game['export'])
    assert result['outcome'] == 'success'
    assert destination.digest_file(output) == after_first, \
        'the copy the user was playing before must come back, byte for byte'
    assert [c['name'] for c in costumes(game['mine'])] == ['Normal', 'Blue Fox']
    assert deliver.read_receipt(first['facts']['receipt_id'])['status'] == 'completed'


def test_a_resumed_delivery_does_not_replace_the_restoration_material(game, tmp_path):
    """The bug a real run found: a retry moved its own copy aside as "previous".

    A resumed delivery whose playable copy is already the build it should be
    must not copy over it, because that would file the delivery's own output as
    the thing to restore -- and the undo would then put the costume back.
    """
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    first = run(game)
    after_first = destination.digest_file(output)

    game['vault'].write({'characters': {'Fox': {'skins': [
        {'id': 'bluefox', 'name': 'Blue Fox', 'filename': 'bluefox.zip', 'slippi_safe': True},
        {'id': 'redfox', 'name': 'Red Fox', 'filename': 'redfox.zip', 'slippi_safe': True}]}}})
    game['vault'].touch('Fox', 'redfox.zip', data=costume_zip('PlFxRd.dat', OTHER_BYTES))
    from mexcli.project import MexManager
    original = MexManager.import_costumes
    MexManager.import_costumes = lambda self, manifest: (
        _append_costume(Path(self.project_path), 2, 'Red Fox', 'PlFxRd.dat', OTHER_BYTES)
        or {'totalImported': 1, 'totalFailed': 0})
    try:
        second = deliver.deliver_to_game(_export=game['export'], character='Fox',
                                         skin_id='redfox')
        exports_after_second = len(game['export'].calls)
        resumed = deliver.deliver_to_game(_export=game['export'], character='Fox',
                                          skin_id='redfox')
    finally:
        MexManager.import_costumes = original
    assert resumed['facts']['receipt_id'] == second['facts']['receipt_id']
    assert len(game['export'].calls) == exports_after_second, 'nothing to rebuild'
    receipt = deliver.read_receipt(second['facts']['receipt_id'])
    assert receipt['backup']['digest'] == after_first,         'the restoration material stays the copy from before this delivery'

    undone = deliver.undo_delivery(second['facts']['receipt_id'], _export=game['export'])
    assert undone['outcome'] == 'success'
    assert destination.digest_file(output) == after_first


def test_undo_out_of_order_is_refused_rather_than_shifting_a_later_delivery(game, tmp_path):
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    first = run(game)
    game['vault'].write({'characters': {'Fox': {'skins': [
        {'id': 'bluefox', 'name': 'Blue Fox', 'filename': 'bluefox.zip', 'slippi_safe': True},
        {'id': 'redfox', 'name': 'Red Fox', 'filename': 'redfox.zip', 'slippi_safe': True}]}}})
    game['vault'].touch('Fox', 'redfox.zip', data=costume_zip('PlFxRd.dat', OTHER_BYTES))
    from mexcli.project import MexManager
    original = MexManager.import_costumes
    MexManager.import_costumes = lambda self, manifest: (
        _append_costume(Path(self.project_path), 2, 'Red Fox', 'PlFxRd.dat', OTHER_BYTES)
        or {'totalImported': 1, 'totalFailed': 0})
    try:
        deliver.deliver_to_game(_export=game['export'], character='Fox', skin_id='redfox')
    finally:
        MexManager.import_costumes = original

    result = deliver.undo_delivery(first['facts']['receipt_id'], _export=game['export'])
    assert result['outcome'] == 'blocked'
    assert 'Red Fox' in result['facts']['limitation_that_matters']
    assert game['removals'] == []
    assert [c['name'] for c in costumes(game['mine'])] == ['Normal', 'Blue Fox', 'Red Fox']


def test_undo_refuses_when_the_costume_in_that_slot_is_no_longer_the_one_delivered(
        game, tmp_path):
    """Position plus filename is not identity; the bytes are."""
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    delivered = run(game)
    (game['mine'].parent / 'files' / 'PlFxBu.dat').write_bytes(b'SOMEBODY REPLACED THIS')
    result = deliver.undo_delivery(delivered['facts']['receipt_id'], _export=game['export'])
    assert result['outcome'] == 'blocked'
    assert 'that costume file has changed since' in result['limitations'][0]
    assert game['removals'] == []
    assert [c['name'] for c in costumes(game['mine'])] == ['Normal', 'Blue Fox']


def test_a_failed_rebuild_during_undo_is_resumable_not_already_undone(game, tmp_path):
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    delivered = run(game)
    game['export'].fail = 'the build died'
    first = deliver.undo_delivery(delivered['facts']['receipt_id'], _export=game['export'])
    assert first['outcome'] == 'partial'
    assert deliver.read_receipt(delivered['facts']['receipt_id'])['status'] == 'undoing'
    assert 'could not be rebuilt' in first['facts']['limitation_that_matters']

    game['export'].fail = None
    second = deliver.undo_delivery(delivered['facts']['receipt_id'], _export=game['export'])
    assert second['outcome'] == 'success'
    assert 'already undone' not in json.dumps(second).lower()
    assert deliver.read_receipt(delivered['facts']['receipt_id'])['status'] == 'undone'


def test_undo_names_what_was_restored_and_never_says_nothing_to_restore(game, tmp_path):
    offline_destination(game, tmp_path / 'games' / 'my.iso')
    delivered = run(game)
    result = deliver.undo_delivery(delivered['facts']['receipt_id'], _export=game['export'])
    assert 'nothing to restore' not in json.dumps(result).lower()
    assert 'Fox slot 2' in result['facts']['restored']
    assert 'My Melee' in result['facts']['summary']
    assert result['facts']['library_copy'] == 'untouched'
    assert (game['vault'].storage / 'Fox/bluefox.zip').is_file()
    assert any('still in your library' in line for line in result['limitations'])


def test_undo_twice_does_not_remove_a_second_slot(game, tmp_path):
    offline_destination(game, tmp_path / 'games' / 'my.iso')
    delivered = run(game)
    deliver.undo_delivery(delivered['facts']['receipt_id'], _export=game['export'])
    result = deliver.undo_delivery(delivered['facts']['receipt_id'], _export=game['export'])
    assert result['outcome'] == 'success'
    assert 'already' in result['facts']['summary']
    assert len(game['removals']) == 1


def test_undo_is_itself_undone_by_delivering_again(game, tmp_path):
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    delivered = run(game)
    deliver.undo_delivery(delivered['facts']['receipt_id'], _export=game['export'])
    again = run(game)
    assert again['achieved']['installed'] is True
    assert [c['name'] for c in costumes(game['mine'])] == ['Normal', 'Blue Fox']
    assert again['facts']['receipt_id'] != delivered['facts']['receipt_id']


# --------------------------------------------------------------------------
# restoration has to be true, not merely reported
# --------------------------------------------------------------------------

def _two_member_delivery(game, output):
    """A delivery that adds TWO costume files in one go (a paired install)."""
    offline_destination(game, output)
    from mexcli.project import MexManager
    original = MexManager.import_costumes

    def pair(self, manifest):
        _append_costume(Path(self.project_path), 2, 'Blue Fox', 'PlFxBu.dat', COSTUME_BYTES)
        _append_costume(Path(self.project_path), 2, 'Blue Fox Alt', 'PlFxB2.dat', OTHER_BYTES)
        return {'totalImported': 2, 'totalFailed': 0}

    MexManager.import_costumes = pair
    try:
        return run(game)
    finally:
        MexManager.import_costumes = original


def test_one_member_already_gone_is_not_all_of_them_removed(game, tmp_path):
    """"Not all present" was being read as "all removed", with zero removals."""
    output = tmp_path / 'games' / 'my.iso'
    delivered = _two_member_delivery(game, output)
    assert len(deliver.read_receipt(delivered['facts']['receipt_id'])['added']) == 2

    _drop_costume(game['mine'], 2, 1)               # one of the two, removed by hand
    assert [c['name'] for c in costumes(game['mine'])] == ['Normal', 'Blue Fox Alt']

    result = deliver.undo_delivery(delivered['facts']['receipt_id'], _export=game['export'])
    assert game['removals'], 'the member that is still there must still be removed'
    assert [c['name'] for c in costumes(game['mine'])] == ['Normal']
    assert result['outcome'] == 'success'
    every = next(c for c in result['checks'] if c['check_id'] == 'every_delivered_costume_removed')
    assert every['status'] == 'pass'


def test_a_part_removed_delivery_is_not_reported_as_restored(game, tmp_path):
    output = tmp_path / 'games' / 'my.iso'
    delivered = _two_member_delivery(game, output)
    receipt = deliver.read_receipt(delivered['facts']['receipt_id'])
    _drop_costume(game['mine'], 2, 1)
    state_now = deliver.current_state(deliver.read_receipt(receipt['receipt_id']))
    assert state_now['members_found'] == 1 and state_now['members_total'] == 2
    assert state_now['in_project'] is False
    assert state_now['restored'] is False, 'one costume is still in the build'


def test_undo_will_not_write_the_old_bytes_into_a_different_game(game, tmp_path):
    """The destination was repointed after the delivery: A's bytes must not land in B."""
    first = tmp_path / 'games' / 'a.iso'
    record = offline_destination(game, first)
    delivered = run(game)
    assert first.is_file()

    (tmp_path / 'other').mkdir()
    second = tmp_path / 'other' / 'b.iso'
    destination.designate('offline_build', destination_id=record['id'],
                          project_id=game['ids']['My Melee'], output_iso_path=str(second))

    result = deliver.undo_delivery(delivered['facts']['receipt_id'], _export=game['export'])
    assert result['outcome'] == 'blocked'
    assert 'points at a different file' in result['facts']['limitation_that_matters']
    assert not second.exists()
    assert game['removals'] == []
    assert [c['name'] for c in costumes(game['mine'])] == ['Normal', 'Blue Fox']


def test_an_unverifiable_rebuild_is_never_published_by_undo(game, tmp_path, monkeypatch):
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    delivered = run(game)
    delivered_bytes = output.read_bytes()

    def rubbish(project, options=None, session=None):
        path = game['export'].root / 'rubbish.iso'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'NOT A DISC IMAGE' * 64)
        return {'state': 'complete', 'error': None, 'artifactId': 'rubbish',
                'path': str(path), 'warnings': [], 'filename': 'game.iso'}

    result = deliver.undo_delivery(delivered['facts']['receipt_id'], _export=rubbish)
    assert result['outcome'] == 'partial'
    assert output.read_bytes() == delivered_bytes, 'unchecked bytes never reach the game'
    assert deliver.read_receipt(delivered['facts']['receipt_id'])['status'] == 'undoing'


def test_a_verified_build_that_changed_is_rebuilt_not_published(game, tmp_path):
    """Verification stays authoritative: the bytes published are the bytes checked."""
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    first = run(game)
    artifact = Path(deliver.read_receipt(first['facts']['receipt_id'])['after']
                    ['artifact']['path'])
    artifact.write_bytes(b'TAMPERED' * 64)          # somebody edited the build
    output.unlink()                                  # and the save has to happen again
    destination.marker_path(output).unlink(missing_ok=True)

    exports = len(game['export'].calls)
    second = run(game)
    assert len(game['export'].calls) == exports + 1, 'the tampered build is rebuilt'
    assert second['achieved']['installed'] is True
    assert destination.digest_file(output) != 'sha256:' + '0' * 64
    assert output.read_bytes()[:8] != b'TAMPERED'


def test_the_switch_closes_undo_as_well_as_delivery(game, tmp_path, monkeypatch):
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    delivered = run(game)
    saved = output.read_bytes()
    monkeypatch.setenv('NUCLEUS_DELIVERY', '0')
    result = deliver.undo_delivery(delivered['facts']['receipt_id'], _export=game['export'])
    assert result['outcome'] == 'blocked'
    assert 'switched off in this build' in result['facts']['limitation_that_matters']
    assert game['removals'] == []
    assert output.read_bytes() == saved
    assert [c['name'] for c in costumes(game['mine'])] == ['Normal', 'Blue Fox']


def test_a_costume_whose_bytes_changed_is_a_new_delivery_not_an_old_receipt(game, tmp_path):
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    first = run(game)
    game['vault'].touch('Fox', 'bluefox.zip',
                        data=costume_zip('PlFxBu.dat', b'DIFFERENT BYTES' * 8))
    second = run(game)
    assert second['facts']['receipt_id'] != first['facts']['receipt_id']
    assert len(game['imports']) == 2, 'changed bytes are imported, not assumed installed'


def test_an_interrupted_import_is_reconciled_instead_of_repeated(game, tmp_path):
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    delivered = run(game)
    receipt = deliver.read_receipt(delivered['facts']['receipt_id'])
    # As if the app died with the import in flight: intent journalled, result not.
    receipt['phases']['install'] = {'status': 'started'}
    receipt['added'] = []
    receipt['status'] = 'running'
    deliver_receipts._write_receipt(receipt)
    imports = len(game['imports'])

    resumed = run(game)
    assert len(game['imports']) == imports, 'the costume is already in; do not import it twice'
    assert [c['name'] for c in costumes(game['mine'])] == ['Normal', 'Blue Fox']
    assert deliver.read_receipt(resumed['facts']['receipt_id'])['phases']['install'][
        'status'] == 'done'


def test_two_windows_cannot_interleave_a_settings_write(game, tmp_path):
    from core import file_lock
    (tmp_path / 'games').mkdir(parents=True, exist_ok=True)
    with file_lock.exclusive(destination.settings_path(), timeout=1.0):
        with pytest.raises(destination.DestinationError) as error:
            destination.designate('offline_build', project_id=game['ids']['My Melee'],
                                  output_iso_path=str(tmp_path / 'games' / 'x.iso'))
    assert 'Another Nucleus window' in str(error.value)
    assert destination.read_settings()['destinations'] == {}


# --------------------------------------------------------------------------
# journal and recovery
# --------------------------------------------------------------------------

def test_a_receipt_exists_before_the_first_mutation(game, tmp_path, monkeypatch):
    offline_destination(game, tmp_path / 'games' / 'my.iso')
    seen = {}
    from mexcli.project import MexManager
    original = MexManager.import_costumes

    def spy(self, manifest):
        seen['receipts'] = deliver.list_deliveries()
        return original(self, manifest)

    monkeypatch.setattr(MexManager, 'import_costumes', spy)
    run(game)
    assert seen['receipts'], 'the journal must be on disk before anything is installed'
    assert seen['receipts'][0]['status'] == 'running'


def test_recovery_reconciles_a_delivery_the_app_did_not_see_finish(game, tmp_path):
    offline_destination(game, tmp_path / 'games' / 'my.iso')
    delivered = run(game)
    receipt = deliver.read_receipt(delivered['facts']['receipt_id'])
    receipt['status'] = 'running'                    # as if the app died mid-phase
    receipt['achieved'] = {'prepared': False, 'exported': False,
                           'installed': False, 'previewed': False}
    deliver_receipts._write_receipt(receipt)
    reconciled = deliver.recover_deliveries()
    assert reconciled and reconciled[0]['status'] == 'completed'
    assert deliver.read_receipt(delivered['facts']['receipt_id'])['achieved']['installed'] is True


def test_current_state_is_the_only_source_of_achieved(game, tmp_path):
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    delivered = run(game)
    receipt = deliver.read_receipt(delivered['facts']['receipt_id'])
    assert deliver.current_state(receipt)['complete'] is True
    output.unlink()                                   # the user moved their game file
    state_now = deliver.current_state(receipt)
    assert state_now['saved'] is False and state_now['complete'] is False
    assert deliver_receipts._achieved(receipt, state_now)['installed'] is False


# --------------------------------------------------------------------------
# the preview switch
# --------------------------------------------------------------------------

def test_the_preview_switch_blocks_honestly_instead_of_half_delivering(game, monkeypatch,
                                                                      tmp_path):
    offline_destination(game, tmp_path / 'games' / 'my.iso')
    monkeypatch.setenv('NUCLEUS_DELIVERY', '0')
    result = run(game)
    assert result['outcome'] == 'blocked'
    assert not any(result['achieved'].values())
    assert 'switched off in this build' in result['facts']['limitation_that_matters']
    assert game['imports'] == [] and game['export'].calls == []
    assert 'install_project_mods' in [row.get('action')
                                      for row in result['next']['allowed_responses']]
    assert result['wish_ids'] == []


# --------------------------------------------------------------------------
# app context
# --------------------------------------------------------------------------

def test_app_context_separates_a_file_check_from_a_hash_check(game):
    from randall.assistant import app_context
    context = app_context.read()
    assert context['schema_version'] == 1
    assert context['vanilla_iso']['hash_verified'] is None
    assert 'never runs one' in context['vanilla_iso']['note']
    assert context['destination'] is None
    assert 'designate_destination' in context['actions']
    assert context['active_project']['name'] == 'Friday Melee'


def test_app_context_reports_the_designation_and_the_public_view_hides_paths(game, tmp_path):
    from randall.assistant import app_context
    offline_destination(game, tmp_path / 'games' / 'offline.iso')
    context = app_context.read()
    assert context['destination']['project_name'] == 'My Melee'
    assert context['destination']['output_filename'] == 'offline.iso'
    assert context['destination_availability']['ready'] is True
    assert 'deliver_to_game' in context['actions']
    blob = json.dumps(app_context.public(context))
    assert str(tmp_path) not in blob


def test_candidates_are_never_selected_for_the_user(game, monkeypatch, tmp_path):
    iso = tmp_path / 'Melee.iso'
    iso.write_bytes(b'x')
    monkeypatch.setattr(destination, 'launcher_iso', lambda: str(iso))
    found = destination.candidates()
    assert [entry['selected'] for entry in found['slippi']] == [False]
    assert all(entry['selected'] is False for entry in found['projects'])
    assert found['searched']
    assert destination.read_settings()['default_destination_id'] is None


def test_a_designated_destination_whose_project_vanished_asks_for_repair(game, tmp_path):
    offline_destination(game, tmp_path / 'games' / 'my.iso')
    for path in sorted(game['mine'].parent.rglob('*'), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    game['mine'].parent.rmdir()
    result = run(game)
    assert result['outcome'] == 'blocked'
    assert 'not where it was' in result['facts']['limitation_that_matters']
    assert game['export'].calls == []


def test_model_facing_facts_never_carry_absolute_paths(game, tmp_path):
    offline_destination(game, tmp_path / 'games' / 'my.iso')
    result = run(game)
    blob = json.dumps({'facts': result['facts'], 'artifacts': result['artifacts'],
                       'limitations': result['limitations']})
    assert str(tmp_path) not in blob
    assert str(game['mine'].parent) not in blob


# --------------------------------------------------------------------------
# the HTTP surface the cards use
# --------------------------------------------------------------------------

def _client(monkeypatch, game):
    from flask import Flask
    from randall.routes.assistant_bp import assistant_bp
    monkeypatch.setattr(deliver, '_default_export', game['export'])
    app = Flask(__name__)
    app.register_blueprint(assistant_bp, url_prefix='/api/assistant')
    return app.test_client()


def test_a_card_can_list_deliveries_without_paths_and_undo_one(game, monkeypatch, tmp_path):
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    delivered = run(game)
    client = _client(monkeypatch, game)

    listed = client.get('/api/assistant/deliveries').get_json()['deliveries']
    assert listed[0]['receipt_id'] == delivered['facts']['receipt_id']
    assert listed[0]['costume'] == 'Blue Fox'
    assert listed[0]['achieved']['installed'] is True
    assert listed[0]['can_undo'] is True
    assert str(tmp_path) not in json.dumps(listed)

    undone = client.post(
        f"/api/assistant/deliveries/{delivered['facts']['receipt_id']}/undo").get_json()
    assert undone['outcome'] == 'success'
    assert undone['facts']['restored']
    assert [c['name'] for c in costumes(game['mine'])] == ['Normal']
    assert client.get('/api/assistant/deliveries').get_json()['deliveries'][0]['can_undo']         is False


def test_the_undo_endpoint_reports_an_unknown_receipt_without_raising(game, monkeypatch):
    client = _client(monkeypatch, game)
    response = client.post('/api/assistant/deliveries/delivery_deadbeefdeadbeef/undo')
    assert response.status_code == 200
    assert response.get_json()['outcome'] == 'blocked'
    assert client.post('/api/assistant/deliveries/not-a-receipt/undo').status_code == 400


def test_a_vault_item_carries_the_labels_provenance_for_the_cards(game):
    from randall.assistant.vault_items import _item
    from core.metadata import load_metadata
    skin = load_metadata(default={})['characters']['Fox']['skins'][0]
    item = _item('Fox', skin)
    assert item['slippi_verdict'] == 'safe'
    assert 'checked by the importer' in item['slippi_evidence']
    assert item['slippi_tested'] is True and item['dat_hash'] == 'abc123'
    assert item['slippi_test_date'] == '2026-09-01'

    hand_set = {**skin, 'slippi_manual_override': True, 'slippi_tested': False}
    by_hand = _item('Fox', hand_set)
    assert by_hand['slippi_verdict'] == 'safe'
    assert 'set by hand' in by_hand['slippi_evidence']
    assert by_hand['slippi_manual_override'] is True


# --------------------------------------------------------------------------
# the tool surface
# --------------------------------------------------------------------------

def test_the_tool_requires_approval_and_revalidates_its_subject(game, monkeypatch, tmp_path):
    offline_destination(game, tmp_path / 'games' / 'my.iso')
    monkeypatch.setattr(deliver, '_default_export', game['export'])
    call = tools.prepare('deliver_to_game', blue_fox())
    assert 'approval' in tools.execute(call)['error']
    assert game['imports'] == []
    game['vault'].touch('Fox', 'bluefox.zip', data=costume_zip('PlFxBu.dat', b'A DIFFERENT COSTUME' * 8))
    assert 'changed' in tools.execute(call, approvals.Grant(call.fingerprint))['error']
    assert game['imports'] == []


def test_an_approval_does_not_survive_the_destination_being_repointed(game, monkeypatch,
                                                                     tmp_path):
    record = offline_destination(game, tmp_path / 'games' / 'a.iso')
    monkeypatch.setattr(deliver, '_default_export', game['export'])
    call = tools.prepare('deliver_to_game', blue_fox())
    (tmp_path / 'elsewhere').mkdir()
    destination.designate('offline_build', destination_id=record['id'],
                          project_id=game['ids']['My Melee'],
                          output_iso_path=str(tmp_path / 'elsewhere' / 'a.iso'))
    result = tools.execute(call, approvals.Grant(call.fingerprint))
    assert 'changed after you approved' in result['error']
    assert game['imports'] == []
    assert not (tmp_path / 'elsewhere' / 'a.iso').exists()


def test_the_approved_tool_delivers_and_the_undo_tool_reverses_it(game, monkeypatch, tmp_path):
    output = tmp_path / 'games' / 'my.iso'
    offline_destination(game, output)
    monkeypatch.setattr(deliver, '_default_export', game['export'])
    call = tools.prepare('deliver_to_game', blue_fox())
    assert 'Blue Fox' in json.loads(call.preview)['title']
    result = tools.execute(call, approvals.Grant(call.fingerprint))
    assert result['achieved']['installed'] is True
    undone = tools.execute(tools.prepare('undo_delivery',
                                         {'receipt_id': result['facts']['receipt_id']}))
    assert undone['outcome'] == 'success'
    assert [c['name'] for c in costumes(game['mine'])] == ['Normal']


def test_the_four_project_tools_still_work(game):
    listing = projects.list_projects()
    assert {p['name'] for p in listing['projects']} == {'My Melee', 'Friday Melee'}
    inspected = projects.inspect_project(game['ids']['My Melee'], 'Fox')
    assert inspected['costumes'] == [{'slot': 1, 'name': 'Normal', 'filename': 'PlFxNr.dat'}]
    for name in ('list_projects', 'inspect_project', 'create_project', 'install_project_mods'):
        assert name in tools.REGISTRY
