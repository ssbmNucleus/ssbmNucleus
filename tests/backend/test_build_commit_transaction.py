"""Installing a menu into the build you play, as a real transaction.

Everything the facade could do before this stopped at a workspace copy: the
2026-09-22 harness experiment produced a correct ``MnSlChr.usd`` and a correct
``codes.ini`` and then had nowhere to put them (REPORT.md, "There is no 'install
this into the build I play'").

These tests hold the commit to the properties that make it safe to have, and to
the ones the 2026-09-22 review said it did not yet have:

* the build the caller NAMED receives both the menu and the code it needs;
* no other build is touched, and no other writer can slip in beside it;
* the codes that build already carried survive, with their enabled flags - a
  disabled one is never flipped on as a side effect;
* an approval is refused once it stops describing reality: the build moved, the
  artifact moved, the proposal itself was edited, the compiler changed, or the
  authorization was already spent;
* a failure injected between two writes leaves nothing half-applied, and a
  failure injected after verification does not LOSE the change either;
* rollback refuses to undo a change somebody has since written over;
* structure means the file's graph resolves, not that a root has the right name;
* two codes writing one address different values is a conflict;
* and the result says, in the result, that nobody looked at the menu and nobody
  rebuilt the disc.

The fixture builds are synthetic: a real MEX project layout
(``project.mexproj``, ``sys/boot.bin``, ``data/mex.json``) and real HAL DAT
headers with a real relocation table, in pytest's tmp_path, so no test can reach
the user's vault. The two steps that genuinely need a real project - MexCLI's
``sync-codes`` and HSDRaw's menu reader - are the declared seams
(:data:`core.build_transaction.CODE_COMPILER`,
:data:`nucleus_api.menus.NATIVE_MENU_READER`); tests pin that the shipped
defaults are the real tools, and ``test_build_commit_real_project.py`` runs both
for real against a minimal real project.
"""
from tests.paths import APP, BACKEND
import json
import pathlib
import struct
from pathlib import Path

import pytest

from core import build_access, build_authorization as auth_module, build_transaction as bt

CSS_ROOT = 'MnSelectChrDataTable'
SSS_ROOT = 'MnSelectStageDataTable'
CSS_CODE = {'name': 'Disable Hardcoded CSS Animations', 'source': '04263384 48000010'}
EXISTING_CODE = {'name': 'UCF', 'creator': 'Dan', 'source': '04001234 60000000',
                 'enabled': True}
DISABLED_CODE = {'name': 'Turbo Mode', 'creator': '', 'source': '04002000 38000001',
                 'enabled': False}

FIXTURE_ROOT = (BACKEND / 'artifacts'
                / 'harness-experiment-20260922' / 'runs')
HALO_INSTALLED = (FIXTURE_ROOT / 'openrouter_z-ai_glm-5.3-flash' / 'T5-halo-css'
                  / 'out' / 'MnSlChr.usd')


# ---------------------------------------------------------------------------
# Fixture material: a structurally real DAT, a real GCT, a real-shaped reader
# ---------------------------------------------------------------------------

def menu_dat(root_symbol=CSS_ROOT, background=b'background-model'):
    """A minimal DAT that actually holds together, with a real joint on the end.

    A header whose size fields agree with the file, a relocation table whose one
    entry resolves, a data table long enough to BE that table, and a background
    slot that is that relocated pointer - pointing at a real 0x40-byte JOBJ,
    because `walk_joint_graph` follows the tree the game follows and a 16-byte
    blob is not one.
    """
    from nucleus_api import menus
    table_size = menus.MENU_TABLE_SIZES[root_symbol]
    slot = menus.BACKGROUND_MODEL_SLOTS[root_symbol]
    table = bytearray(max(table_size, slot + 4))
    joint_at = len(table)
    struct.pack_into('>I', table, slot, joint_at)
    # One joint, no child and no next: those slots are simply not relocated, so
    # the walk visits exactly this node and stops.
    joint = bytearray(menus.JOBJ_SIZE)
    payload = bytes(table) + bytes(joint) + background
    relocations = struct.pack('>I', slot)
    roots = struct.pack('>II', 0, 0)
    strings = root_symbol.encode('ascii') + b'\x00'
    body = (struct.pack('>5I', 0, len(payload), 1, 1, 0) + b'\x00' * 12
            + payload + relocations + roots + strings)
    return struct.pack('>I', len(body)) + body[4:]


def broken_dat(root_symbol=CSS_ROOT):
    """A DAT whose root NAME is right and whose root POINTER is nonsense."""
    payload = b'\x00' * 64
    body = (struct.pack('>5I', 0, len(payload), 0, 1, 0) + b'\x00' * 12 + payload
            + struct.pack('>II', 0x7FFFFFFF, 0) + root_symbol.encode('ascii') + b'\x00')
    return struct.pack('>I', len(body)) + body[4:]


def fake_native_reader(path, menu_type):
    """Stands in for HSDRaw: walks the graph the same way and exports the bundle."""
    import hashlib
    from nucleus_api import menus
    graph = menus.menu_graph_check(path, menu_type)
    if graph['status'] != 'pass':
        return {'status': 'fail', 'background_sha256': None, 'background_bytes': None,
                'reason': graph['reason']}
    data = Path(path).read_bytes()
    integrity = graph['integrity']
    blob = data[0x20 + graph['background_pointer']:0x20 + integrity['data_size']]
    return {'status': 'pass', 'background_sha256': hashlib.sha256(blob).hexdigest(),
            'background_bytes': len(blob), 'reason': None}


def fake_code_compiler(directory, ini_text):
    """Stands in for ``mexcli sync-codes``: writes codes.ini AND a real GCT.

    A real GCT, not a hash under that filename - the verifier looks for the
    header, the footer and each enabled code's compiled bytes, so a stand-in
    that cheated would fail the same check MexCLI's output has to pass.
    """
    from core.gecko import parse_ini, _compiled_bytes
    files = Path(directory) / 'files'
    files.joinpath('codes.ini').write_text(ini_text, encoding='utf-8')
    body = b''
    for code in parse_ini(ini_text):
        if not code['enabled']:
            continue
        blob, error, _ = _compiled_bytes(code['source'])
        if blob and not error:
            body += blob
    files.joinpath('codes.gct').write_bytes(bt.GCT_HEADER + body + bt.GCT_FOOTER)
    return {'applied': ini_text.count('$'), 'enabled': None, 'gct_bytes': len(body) + 16}


def _ini(*codes):
    from core.gecko import serialize_ini
    return serialize_ini([{'name': c['name'], 'creator': c.get('creator', ''),
                           'description': '', 'source': c['source'],
                           'enabled': c.get('enabled', True)} for c in codes])


def make_build(root, name, *, background=b'original-css', codes=(EXISTING_CODE,)):
    directory = root / name
    (directory / 'files').mkdir(parents=True)
    (directory / 'sys').mkdir()
    (directory / 'data').mkdir()
    (directory / 'project.mexproj').write_text(
        json.dumps({'build': {'name': name}}), encoding='utf-8')
    (directory / 'sys' / 'boot.bin').write_bytes(b'GALE01\x00\x02' + b'\x00' * 24)
    (directory / 'data' / 'mex.json').write_text('{}', encoding='utf-8')
    (directory / 'files' / 'MnSlChr.usd').write_bytes(menu_dat(background=background))
    (directory / 'files' / 'codes.ini').write_text(_ini(*codes), encoding='utf-8')
    (directory / 'files' / 'codes.gct').write_bytes(bt.GCT_HEADER + bt.GCT_FOOTER)
    return directory


class Rig:
    """Two builds, a workspace, a trust root, and the shorthand tests keep needing."""

    def __init__(self, api, played_dir, other_dir, ws):
        self.api = api
        self.played_dir = played_dir
        self.other_dir = other_dir
        self.ws = ws

    @property
    def played(self):
        return next(b for b in self.api.list_builds() if b['name'] == 'Played')

    @property
    def untouched(self):
        return next(b for b in self.api.list_builds() if b['name'] == 'Untouched')

    def menu_artifact(self):
        return self.api.register_artifact('out/MnSlChr.usd', 'css_menu_file')

    def prepare(self, code_changes=None, **kwargs):
        build = self.played
        artifact = self.menu_artifact()
        kwargs.setdefault('task_id', 'task_demo')
        return self.api.prepare_change(
            build['id'], build['revision'], [artifact['id']],
            code_changes=code_changes if code_changes is not None else {'add': [CSS_CODE]},
            **kwargs)

    def approve(self, change, accepted=None, **kwargs):
        # The task comes from the PROPOSAL: an approval is a decision about one
        # request, so grant() refuses a task id the proposal does not name.
        return auth_module.grant(
            change, granted_by='user',
            task_id=kwargs.pop('task_id', change.get('task_id') or ''),
            task_revision=kwargs.pop('task_revision', change.get('task_revision', 1)),
            accepted_unknown=(change['unknown_dimensions'] if accepted is None else accepted),
            **kwargs)

    def install(self, code_changes=None, accepted=None, **kwargs):
        change = self.prepare(code_changes, **kwargs)
        return change, self.approve(change, accepted)


@pytest.fixture
def wish_store(tmp_path, monkeypatch):
    """Point the wish backlog at a throwaway database."""
    from core import config
    from randall.assistant.tasks import store
    store.close()
    monkeypatch.setattr(config, 'STORAGE_PATH', tmp_path / 'wish-storage')
    yield
    store.close()


@pytest.fixture
def rig(tmp_path, monkeypatch):
    from nucleus_api import builds as builds_module, menus as menus_module
    builds_root = tmp_path / 'builds'
    builds_root.mkdir()
    played_path = make_build(builds_root, 'Played')
    other_path = make_build(builds_root, 'Untouched', background=b'other-css')
    workspace = tmp_path / 'workspace'
    (workspace / 'out').mkdir(parents=True)

    monkeypatch.setenv('NUCLEUS_API_WORKSPACE', str(workspace))
    monkeypatch.setenv('NUCLEUS_API_BUILDS', json.dumps([str(played_path), str(other_path)]))
    monkeypatch.setenv('NUCLEUS_BUILD_TRUST_ROOT', str(tmp_path / 'trust'))
    monkeypatch.setattr(bt, 'CODE_COMPILER', fake_code_compiler)
    monkeypatch.setattr(bt, 'FAULT_HOOK', None)
    monkeypatch.setattr(menus_module, 'NATIVE_MENU_READER', fake_native_reader)

    (workspace / 'out' / 'MnSlChr.usd').write_bytes(menu_dat(background=b'halo-lobby'))
    (workspace / 'out' / 'shot.png').write_bytes(b'\x89PNG\r\n\x1a\n' + b'author shot')
    return Rig(builds_module, played_path, other_path, workspace)


# ---------------------------------------------------------------------------
# The acceptance properties
# ---------------------------------------------------------------------------

def test_the_selected_build_receives_both_the_menu_and_the_required_code(rig):
    change, auth = rig.install()
    receipt = rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])

    assert receipt['achieved']['build_inputs_updated'] is True
    assert (rig.played_dir / 'files' / 'MnSlChr.usd').read_bytes() == \
        (rig.ws / 'out' / 'MnSlChr.usd').read_bytes()

    from core.gecko import parse_ini
    after = parse_ini((rig.played_dir / 'files' / 'codes.ini').read_text(encoding='utf-8'))
    assert 'Disable Hardcoded CSS Animations' in [c['name'] for c in after]
    assert receipt['codes']['added'] == ['Disable Hardcoded CSS Animations']
    assert receipt['after_revision'] != receipt['before_revision']
    report = bt.gct_report(rig.played_dir / 'files' / 'codes.gct')
    assert report['status'] == 'pass', report['reason']
    assert bytes.fromhex('0426338448000010') in report['body']


def test_another_build_is_untouched_by_a_commit(rig):
    before = rig.untouched
    before_files = {name: (rig.other_dir / name).read_bytes()
                    for name in ('files/MnSlChr.usd', 'files/codes.ini', 'files/codes.gct')}

    change, auth = rig.install()
    rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])

    assert rig.untouched['revision'] == before['revision']
    for name, blob in before_files.items():
        assert (rig.other_dir / name).read_bytes() == blob, name
    assert not (rig.other_dir / bt.JOURNAL_DIRNAME / 'txn').exists()


def test_existing_codes_survive_and_a_disabled_one_is_never_flipped_on(rig):
    (rig.played_dir / 'files' / 'codes.ini').write_text(
        _ini(EXISTING_CODE, DISABLED_CODE), encoding='utf-8')

    change, auth = rig.install()
    assert {c['identity'] for c in change['codes']['preserved']} == {'UCF [Dan]', 'Turbo Mode'}
    rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])

    from core.gecko import parse_ini
    after = {c['name']: c for c in
             parse_ini((rig.played_dir / 'files' / 'codes.ini').read_text(encoding='utf-8'))}
    assert set(after) == {'UCF', 'Turbo Mode', 'Disable Hardcoded CSS Animations'}
    assert after['UCF']['source'].strip() == EXISTING_CODE['source']
    assert after['Turbo Mode']['enabled'] is False, 'a disabled code must stay disabled'


def test_enabling_a_required_code_the_build_has_switched_off_is_an_explicit_operation(rig):
    off = {**CSS_CODE, 'enabled': False}
    (rig.played_dir / 'files' / 'codes.ini').write_text(_ini(EXISTING_CODE, off),
                                                        encoding='utf-8')
    silent = rig.prepare()
    assert silent['status'] == 'blocked'
    assert silent['codes']['enable_required'][0]['reason'] == 'required_but_disabled'
    with pytest.raises(auth_module.AuthorizationError):
        rig.approve(silent)

    asked = rig.prepare(code_changes={'add': [CSS_CODE], 'enable_disabled': True})
    assert asked['status'] == 'prepared'
    assert asked['codes']['enabled'][0]['identity'] == 'Disable Hardcoded CSS Animations'
    receipt = rig.api.commit_change(asked['prepared_change_id'],
                                    rig.approve(asked)['authorization_id'])
    assert receipt['codes']['enabled'][0]['to'] is True


def test_a_stale_approval_is_rejected_when_the_build_moved(rig):
    change, auth = rig.install()
    (rig.played_dir / 'files' / 'codes.ini').write_text(
        _ini(EXISTING_CODE, DISABLED_CODE), encoding='utf-8')
    menu_before = (rig.played_dir / 'files' / 'MnSlChr.usd').read_bytes()

    with pytest.raises(rig.api.BuildChangeRejected) as caught:
        rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    assert caught.value.code == 'stale_authorization'
    assert (rig.played_dir / 'files' / 'MnSlChr.usd').read_bytes() == menu_before


def test_a_stale_approval_is_rejected_when_the_artifact_moved(rig):
    change, auth = rig.install()
    (rig.ws / 'out' / 'MnSlChr.usd').write_bytes(menu_dat(background=b'something-else'))
    with pytest.raises(rig.api.BuildChangeRejected) as caught:
        rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    assert caught.value.code == 'artifact_hash_mismatch'


def test_editing_the_sealed_proposal_after_approval_invalidates_it(rig):
    """The binding is recomputed from the proposal, not read back from it."""
    change, auth = rig.install()
    path = (rig.played_dir / bt.JOURNAL_DIRNAME / 'prepared'
            / f'{change["prepared_change_id"]}.json')
    tampered = json.loads(path.read_text(encoding='utf-8'))
    tampered['codes']['ini'] = tampered['codes']['ini'] + '\n$!Sneaky\n04001111 60000000\n'
    tampered['codes_ini_sha256'] = 'deadbeef' * 8
    path.write_text(json.dumps(tampered), encoding='utf-8')

    with pytest.raises(rig.api.BuildChangeRejected) as caught:
        rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    assert caught.value.code in ('proposal_tampered', 'stale_authorization')
    assert 'Sneaky' not in (rig.played_dir / 'files' / 'codes.ini').read_text(encoding='utf-8')


def test_keeping_the_stored_digest_while_changing_the_executed_text_is_caught(rig):
    """The digest is not a stored string the tamperer can keep."""
    change, auth = rig.install()
    path = (rig.played_dir / bt.JOURNAL_DIRNAME / 'prepared'
            / f'{change["prepared_change_id"]}.json')
    tampered = json.loads(path.read_text(encoding='utf-8'))
    tampered['codes']['ini'] = tampered['codes']['ini'] + '\n$!Sneaky\n04001111 60000000\n'
    # subject_digest and codes_ini_sha256 left EXACTLY as approved
    path.write_text(json.dumps(tampered), encoding='utf-8')
    with pytest.raises(rig.api.BuildChangeRejected):
        rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    assert 'Sneaky' not in (rig.played_dir / 'files' / 'codes.ini').read_text(encoding='utf-8')


def test_an_authorization_for_another_proposal_is_refused(rig):
    first, auth = rig.install()
    (rig.ws / 'out' / 'MnSlChr.usd').write_bytes(menu_dat(background=b'second'))
    second = rig.prepare()
    with pytest.raises(rig.api.BuildChangeRejected) as caught:
        rig.api.commit_change(second['prepared_change_id'], auth['authorization_id'])
    assert caught.value.code == 'authorization_mismatch'


def test_a_spent_authorization_returns_the_receipt_it_already_produced(rig):
    change, auth = rig.install()
    first = rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    again = rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    assert again['receipt_id'] == first['receipt_id']
    assert again['journal_id'] == first['journal_id']


def test_a_changed_code_compiler_invalidates_an_approval(rig, monkeypatch):
    change, auth = rig.install()

    def different_compiler(directory, ini_text):
        return fake_code_compiler(directory, ini_text)

    monkeypatch.setattr(bt, 'CODE_COMPILER', different_compiler)
    monkeypatch.setattr(bt, 'compiler_identity',
                        lambda: {'name': 'other', 'path': None, 'sha256': 'other-hash',
                                 'available': True})
    with pytest.raises(rig.api.BuildChangeRejected) as caught:
        rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    assert caught.value.code == 'compiler_changed'


def test_preparing_against_a_revision_the_build_no_longer_has_is_refused(rig):
    build = rig.played
    (rig.played_dir / 'files' / 'codes.ini').write_text(_ini(DISABLED_CODE), encoding='utf-8')
    artifact = rig.menu_artifact()
    with pytest.raises(rig.api.BuildChangeRejected) as caught:
        rig.api.prepare_change(build['id'], build['revision'], [artifact['id']])
    assert caught.value.code == 'stale_revision'


def test_swapping_the_discs_identity_after_approval_invalidates_it(rig):
    """boot.bin and data/mex.json are part of the revision, not free variables."""
    change, auth = rig.install()
    (rig.played_dir / 'sys' / 'boot.bin').write_bytes(b'GALJ01\x00\x00' + b'\x00' * 24)
    with pytest.raises(rig.api.BuildChangeRejected) as caught:
        rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    assert caught.value.code == 'stale_authorization'


# ---------------------------------------------------------------------------
# Crash and recovery, both directions
# ---------------------------------------------------------------------------

def test_a_failure_injected_between_writes_recovers_cleanly_on_the_next_open(rig, monkeypatch):
    before_menu = (rig.played_dir / 'files' / 'MnSlChr.usd').read_bytes()
    before_ini = (rig.played_dir / 'files' / 'codes.ini').read_text(encoding='utf-8')
    before_revision = rig.played['revision']

    def crash(stage, relpath):
        if stage == 'after_write' and relpath == 'files/MnSlChr.usd':
            raise bt.SimulatedCrash('power cut between the menu write and the code write')

    change, auth = rig.install()
    monkeypatch.setattr(bt, 'FAULT_HOOK', crash)
    with pytest.raises(bt.SimulatedCrash):
        rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    monkeypatch.setattr(bt, 'FAULT_HOOK', None)
    assert (rig.played_dir / 'files' / 'MnSlChr.usd').read_bytes() != before_menu

    actions = rig.api.recover(rig.played['id'])
    assert [a['action'] for a in actions] == ['rolled_back']
    assert 'files/MnSlChr.usd' in actions[0]['restored']
    assert (rig.played_dir / 'files' / 'MnSlChr.usd').read_bytes() == before_menu
    assert (rig.played_dir / 'files' / 'codes.ini').read_text(encoding='utf-8') == before_ini
    assert rig.played['revision'] == before_revision

    change2, auth2 = rig.install()
    assert rig.api.commit_change(change2['prepared_change_id'],
                                 auth2['authorization_id'])['stage'] == 'build_inputs_updated'


def test_a_crash_after_verification_finishes_the_change_rather_than_losing_it(rig, monkeypatch):
    """The files were written AND verified; only the receipt was missing."""
    change, auth = rig.install()

    def crash(stage, relpath):
        if stage == 'before_finalize':
            return                                  # the payload is built first
        if stage == 'after_external':
            return
    monkeypatch.setattr(bt, 'FAULT_HOOK', None)

    # Let the transaction reach 'verified', then die before the receipt lands.
    original = bt._write_finalization

    def die_before_writing(directory, journal):
        raise bt.SimulatedCrash('power cut between verification and the receipt')
    monkeypatch.setattr(bt, '_write_finalization', die_before_writing)
    with pytest.raises(bt.SimulatedCrash):
        rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    monkeypatch.setattr(bt, '_write_finalization', original)

    installed = (rig.played_dir / 'files' / 'MnSlChr.usd').read_bytes()
    assert installed == (rig.ws / 'out' / 'MnSlChr.usd').read_bytes()

    actions = rig.api.recover(rig.played['id'])
    assert [a['action'] for a in actions] == ['finalized']
    assert actions[0]['finalized'], 'the receipt and the spent authorization were written'
    # The change stands, the authorization is spent, and its receipt exists.
    assert (rig.played_dir / 'files' / 'MnSlChr.usd').read_bytes() == installed
    spent = auth_module.load(auth['authorization_id'])
    assert spent['used'] is True and spent['receipt_id']
    assert rig.api.receipt(spent['receipt_id'])['stage'] == 'build_inputs_updated'
    # And it cannot be spent a second time - it returns the same receipt.
    assert rig.api.commit_change(change['prepared_change_id'],
                                 auth['authorization_id'])['receipt_id'] == spent['receipt_id']


def test_an_interrupted_rollback_is_finished_not_left_mixed(rig, monkeypatch):
    before_menu = (rig.played_dir / 'files' / 'MnSlChr.usd').read_bytes()
    change, auth = rig.install()
    receipt = rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])

    seen = []

    def crash(stage, relpath):
        if stage == 'during_restore':
            seen.append(relpath)
            if len(seen) == 2:
                raise bt.SimulatedCrash('power cut halfway through a rollback')
    monkeypatch.setattr(bt, 'FAULT_HOOK', crash)
    with pytest.raises(bt.SimulatedCrash):
        rig.api.rollback(receipt['receipt_id'])
    monkeypatch.setattr(bt, 'FAULT_HOOK', None)

    actions = rig.api.recover(rig.played['id'])
    assert [a['action'] for a in actions] == ['rollback_completed']
    assert (rig.played_dir / 'files' / 'MnSlChr.usd').read_bytes() == before_menu


def test_rollback_refuses_to_undo_a_change_somebody_wrote_over(rig):
    change, auth = rig.install()
    receipt = rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    later = menu_dat(background=b'a-later-change-nobody-asked-to-lose')
    (rig.played_dir / 'files' / 'MnSlChr.usd').write_bytes(later)

    with pytest.raises(rig.api.BuildChangeRejected) as caught:
        rig.api.rollback(receipt['receipt_id'])
    assert caught.value.code == 'stale_rollback'
    assert (rig.played_dir / 'files' / 'MnSlChr.usd').read_bytes() == later


def test_rollback_refuses_when_its_own_backup_is_not_intact(rig):
    change, auth = rig.install()
    receipt = rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    backup = (rig.played_dir / bt.JOURNAL_DIRNAME / 'txn' / receipt['journal_id']
              / 'originals' / 'files__MnSlChr.usd')
    backup.write_bytes(b'not the original')

    with pytest.raises(rig.api.BuildChangeRejected) as caught:
        rig.api.rollback(receipt['receipt_id'])
    assert caught.value.code == 'backup_not_intact'


def test_rollback_puts_the_build_back_exactly(rig):
    before_menu = (rig.played_dir / 'files' / 'MnSlChr.usd').read_bytes()
    before_ini = (rig.played_dir / 'files' / 'codes.ini').read_text(encoding='utf-8')
    before_revision = rig.played['revision']

    change, auth = rig.install()
    receipt = rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    undone = rig.api.rollback(receipt['receipt_id'])

    assert undone['after_revision'] == before_revision
    assert (rig.played_dir / 'files' / 'MnSlChr.usd').read_bytes() == before_menu
    assert (rig.played_dir / 'files' / 'codes.ini').read_text(encoding='utf-8') == before_ini
    assert rig.api.receipt(receipt['receipt_id'])['outcome'] == 'rolled_back'


# ---------------------------------------------------------------------------
# What the result claims
# ---------------------------------------------------------------------------

def test_the_result_says_the_menu_preview_is_unavailable(rig, monkeypatch, tmp_path):
    from core import config
    monkeypatch.setattr(config, 'STORAGE_PATH', tmp_path / 'storage')
    change, auth = rig.install(preview_requested=True, task_id='task_demo')
    assert change['preview']['status'] == 'unavailable'
    receipt = rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    assert receipt['preview']['status'] == 'unavailable'
    assert receipt['achieved']['previewed'] is False
    assert receipt['preview']['wish']['capability'] == 'menu_output_preview'
    assert receipt['outcome'] == 'partial'
    assert any('preview' in line for line in receipt['partial_because'])


def test_a_requested_preview_that_cannot_be_produced_makes_the_outcome_partial(rig):
    change, auth = rig.install(preview_requested=True)
    receipt = rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    assert receipt['outcome'] == 'partial'
    assert len(receipt['partial_because']) == 2


def test_an_incidental_unavailable_preview_manufactures_no_demand(rig, wish_store):
    """Every prepared build calls preview(); filing each one would invent demand."""
    from randall.assistant.tasks import store
    from nucleus_api import menus
    result = menus.preview('out/MnSlChr.usd', task_id='task_demo', task_revision=1)
    assert result['status'] == 'unavailable'
    assert result['wish'] is None
    assert result['wish_recorded']['stored'] is False
    assert result['wish_recorded']['classification'] == 'not_a_blocker'
    assert store.wishes() == []


def test_a_required_preview_records_the_gap_once_per_conversation(rig, wish_store):
    from randall.assistant.tasks import store
    from nucleus_api import menus
    first = menus.preview('out/MnSlChr.usd', task_id='task_demo', task_revision=1,
                          required=True, chat_id='chat_1')
    assert first['wish_recorded']['stored'] is True
    assert first['wish']['capability'] == 'menu_output_preview'
    # The public projection carries typed codes, never the produced file path.
    blob = json.dumps(first['wish'])
    assert 'MnSlChr' not in blob and 'task_demo' not in blob
    assert first['wish']['dedupe_key'] != 'menu_output_preview', \
        'a versionless key would close the old row when a renderer ships'

    menus.preview('out/MnSlChr.usd', task_id='task_demo', task_revision=1,
                  required=True, chat_id='chat_1')
    assert len({w.dedupe_key for w in store.wishes()}) == 1
    second = menus.preview('out/MnSlChr.usd', task_id='task_other', task_revision=1,
                           required=True, chat_id='chat_2')
    assert second['wish_recorded']['requesting_conversations'] >= 2


def test_the_receipt_only_claims_a_saved_request_when_one_was_saved(rig, wish_store):
    change, auth = rig.install(preview_requested=True, task_id='task_demo')
    assert change['preview']['wish_recorded']['stored'] is True
    receipt = rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    assert any('saved on this device' in line for line in receipt['partial_because'])


def test_the_receipt_says_so_when_the_request_could_not_be_saved(rig, monkeypatch):
    from nucleus_api import menus
    monkeypatch.setattr(menus, '_record_preview_wish',
                        lambda *a, **k: (None, {'stored': False, 'error': 'disk full'}))
    change, auth = rig.install(preview_requested=True, task_id='task_demo')
    receipt = rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    assert any('could not be saved' in line for line in receipt['partial_because'])


def test_preparation_against_an_uncommittable_build_records_nothing(tmp_path, monkeypatch,
                                                                    wish_store):
    """Validation is not a request to install."""
    from randall.assistant.tasks import store
    extracted = tmp_path / 'storage-build'
    (extracted / 'files').mkdir(parents=True)
    (extracted / 'files' / 'MnSlChr.usd').write_bytes(menu_dat())
    monkeypatch.setenv('NUCLEUS_API_WORKSPACE', str(tmp_path / 'ws2'))
    monkeypatch.setenv('NUCLEUS_API_BUILDS', json.dumps([str(extracted)]))
    monkeypatch.setenv('NUCLEUS_BUILD_TRUST_ROOT', str(tmp_path / 'trust2'))
    from nucleus_api import builds as builds_module
    row = builds_module.list_builds()[0]
    result = builds_module.prepare_change(row['id'], None, [])
    assert result['error']['code'] == 'unsupported_build_commit'
    assert 'dedupe_key' not in result['wish'], 'a candidate, not a record'
    assert store.wishes() == []

    # The install path, where the capability really was required, does record it.
    record = builds_module.record_build_commit_gap(row, task_id='task_install',
                                                   chat_id='chat_1')
    assert record is not None and record.persisted is True
    assert record.wish.capability == 'unsupported_build_commit'
    assert [w.capability for w in store.wishes()] == ['unsupported_build_commit']


def test_the_receipt_does_not_claim_the_game_was_installed(rig):
    change, auth = rig.install()
    receipt = rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    assert receipt['achieved'] == {'prepared': True, 'build_inputs_updated': True,
                                   'exported': False, 'installed': False, 'previewed': False}
    assert receipt['stage'] == 'build_inputs_updated'
    assert receipt['playable']['status'] == 'not_verified'
    assert 'Export' in receipt['next']['operation']


def test_an_author_screenshot_is_a_reference_and_never_a_preview(rig):
    build = rig.played
    menu = rig.menu_artifact()
    shot = rig.api.register_artifact('out/shot.png', 'reference_screenshot')
    assert shot['role'] == 'reference' and shot['destination'] is None

    change = rig.api.prepare_change(build['id'], build['revision'], [menu['id'], shot['id']],
                                    code_changes={'add': [CSS_CODE]}, task_id='task_demo')
    assert [r['id'] for r in change['references']] == [shot['id']]
    assert [w['artifact_id'] for w in change['writes']] == [menu['id']]
    receipt = rig.api.commit_change(change['prepared_change_id'],
                                    rig.approve(change)['authorization_id'])
    assert receipt['achieved']['previewed'] is False
    assert receipt['references'][0]['role'] == 'reference'


def test_the_receipt_names_the_hashes_on_both_sides(rig):
    change, auth = rig.install()
    receipt = rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    installed = receipt['installed'][0]
    assert installed['destination'] == 'files/MnSlChr.usd'
    assert installed['sha256'] == bt.sha256_file(rig.played_dir / 'files' / 'MnSlChr.usd')
    assert installed['replaced_sha256'] == change['rollback']['files']['files/MnSlChr.usd']
    assert receipt['codes']['required'][0]['content_hash']
    assert {c['check'] for c in receipt['verification']['checks']} >= {
        'installed_bytes', 'menu_graph', 'native_reopen', 'codes_present', 'codes_compiled',
        'codes_in_gct'}


# ---------------------------------------------------------------------------
# Authorization is not the library's to give
# ---------------------------------------------------------------------------

def test_the_facade_has_no_way_to_authorize_its_own_change(rig):
    import inspect
    from nucleus_api import builds
    granting = [name for name, value in vars(builds).items()
                if inspect.isfunction(value) and not name.startswith('_')
                and ('approve' in name or 'grant' in name or 'authorize' in name)]
    assert granting == [], f'{granting} could mint an authorization from model-facing code'
    ask = rig.api.authorization_request(rig.prepare()['prepared_change_id'])
    assert ask['granted_by'] == 'the user, through the approval endpoint'
    assert ask['endpoint'].startswith('POST /api/mex/builds/changes/')


def test_an_authorization_must_name_a_grantor_a_task_and_only_real_unknowns(rig):
    change = rig.prepare()
    task = change['task_id']
    with pytest.raises(auth_module.AuthorizationError) as caught:
        auth_module.grant(change, granted_by='', task_id=task, task_revision=1)
    assert caught.value.code == 'no_grantor'
    with pytest.raises(auth_module.AuthorizationError) as caught:
        auth_module.grant(change, granted_by='user', task_id='', task_revision=1)
    assert caught.value.code == 'no_task'
    with pytest.raises(auth_module.AuthorizationError) as caught:
        auth_module.grant(change, granted_by='user', task_id=task, task_revision=1,
                          accepted_unknown=['something:nobody-was-shown'])
    assert caught.value.code == 'unknown_not_in_proposal'


def test_an_approval_must_be_about_the_request_the_proposal_names(rig):
    change = rig.prepare(task_id='task_demo', task_revision=1)
    with pytest.raises(auth_module.AuthorizationError) as caught:
        auth_module.grant(change, granted_by='user', task_id='some_other_task',
                          task_revision=1)
    assert caught.value.code == 'task_mismatch'
    with pytest.raises(auth_module.AuthorizationError) as caught:
        auth_module.grant(change, granted_by='user', task_id='task_demo', task_revision=7)
    assert caught.value.code == 'task_mismatch'


def test_a_task_revised_after_approval_invalidates_the_decision(rig, monkeypatch):
    """The AUTHORITATIVE revision, not the one the proposal saved."""
    from randall.assistant.tasks import store as task_store
    change, auth = rig.install(task_id='task_demo', task_revision=1)
    monkeypatch.setattr(task_store, 'current_task_revision',
                        lambda task_id: {'revision': 2, 'cancelled': False, 'known': True})
    with pytest.raises(rig.api.BuildChangeRejected) as caught:
        rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    assert caught.value.code == 'stale_authorization'


def test_a_cancelled_task_cannot_be_satisfied_by_its_old_approval(rig, monkeypatch):
    from randall.assistant.tasks import store as task_store
    change, auth = rig.install(task_id='task_demo', task_revision=1)
    monkeypatch.setattr(task_store, 'current_task_revision',
                        lambda task_id: {'revision': 1, 'cancelled': True, 'known': True})
    with pytest.raises(rig.api.BuildChangeRejected) as caught:
        rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    assert caught.value.code == 'task_cancelled'


def test_the_task_is_part_of_what_the_user_agreed_to(rig):
    from core.build_authorization import BOUND_FIELDS
    assert 'task_id' in BOUND_FIELDS and 'task_revision' in BOUND_FIELDS


def test_records_live_outside_the_workspace_the_caller_can_write(rig, tmp_path):
    artifact = rig.menu_artifact()
    trust = tmp_path / 'trust'
    assert (trust / 'artifacts' / f'{artifact["id"]}.json').is_file()
    assert not list((rig.ws).rglob('*.json')), 'no registration lives where the caller writes'


def test_a_registration_cannot_redirect_a_write_by_editing_its_record(rig):
    artifact = rig.menu_artifact()
    record_path = (Path(auth_module.trust_root()) / 'artifacts' / f'{artifact["id"]}.json')
    record = json.loads(record_path.read_text(encoding='utf-8'))
    record['destination'] = 'sys/main.dol'
    record['role'] = 'install'
    record_path.write_text(json.dumps(record), encoding='utf-8')
    # Destination and role are re-derived from the KIND, never read back.
    assert rig.api.artifact(artifact['id'])['destination'] == 'files/MnSlChr.usd'
    build = rig.played
    change = rig.api.prepare_change(build['id'], build['revision'], [artifact['id']])
    assert [w['destination'] for w in change['writes']] == ['files/MnSlChr.usd']


@pytest.mark.parametrize('bad', ['../../../etc/passwd', 'art_' + '../' * 4, '', 'art_xyz',
                                 'art_' + 'g' * 16, 'art_' + 'a' * 15])
def test_ids_that_are_not_ids_never_become_paths(rig, bad):
    with pytest.raises(rig.api.BuildChangeRejected) as caught:
        rig.api.artifact(bad)
    assert caught.value.code in ('malformed_id', 'unknown_artifact')
    assert caught.value.code == 'malformed_id'


def test_a_link_planted_in_the_workspace_cannot_redirect_a_read(rig, tmp_path):
    target = tmp_path / 'outside.usd'
    target.write_bytes(menu_dat(background=b'not from the workspace'))
    link = rig.ws / 'out' / 'linked.usd'
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip('this machine does not allow creating symlinks')
    with pytest.raises((rig.api.BuildChangeRejected, bt.TransactionError, ValueError)):
        rig.api.register_artifact('out/linked.usd', 'css_menu_file')


# ---------------------------------------------------------------------------
# Compatibility: structure, target and codes
# ---------------------------------------------------------------------------

def test_a_root_name_alone_is_not_a_structure_check(rig):
    """Astra's probe: the app's detector still reads the root NAME off this."""
    from vault.importing.unified.detection import dat_root_symbols
    from nucleus_api import menus
    broken = rig.ws / 'out' / 'broken.usd'
    broken.write_bytes(broken_dat())
    assert dat_root_symbols(broken.read_bytes()) == [CSS_ROOT]

    assert menus.dat_integrity(broken)['status'] == 'fail'
    verdict = menus.check_compatibility(broken, 'css')
    assert verdict['structure']['status'] == 'fail'
    assert 'does not hold together' in verdict['structure']['evidence']


def test_a_menu_file_with_no_background_pointer_is_refused(rig):
    from nucleus_api import menus
    payload = b'\x00' * 0x40
    body = (struct.pack('>5I', 0, len(payload), 0, 1, 0) + b'\x00' * 12 + payload
            + struct.pack('>II', 0, 0) + CSS_ROOT.encode() + b'\x00')
    flat = struct.pack('>I', len(body)) + body[4:]
    path = rig.ws / 'out' / 'noslot.usd'
    path.write_bytes(flat)
    assert menus.dat_integrity(path)['status'] == 'pass'
    assert menus.menu_graph_check(path, 'css')['status'] == 'fail'
    artifact = rig.api.register_artifact('out/noslot.usd', 'css_menu_file')
    build = rig.played
    change = rig.api.prepare_change(build['id'], build['revision'], [artifact['id']])
    assert change['status'] == 'blocked'


def test_a_malformed_menu_file_blocks_even_with_every_unknown_accepted(rig):
    broken = rig.ws / 'out' / 'broken.usd'
    broken.write_bytes(broken_dat())
    artifact = rig.api.register_artifact('out/broken.usd', 'css_menu_file')
    build = rig.played
    change = rig.api.prepare_change(build['id'], build['revision'], [artifact['id']])
    assert change['status'] == 'blocked'
    with pytest.raises(auth_module.AuthorizationError) as caught:
        auth_module.grant(change, granted_by='user', task_id='t', task_revision=1)
    assert caught.value.code == 'blocked_change'


def test_a_vanilla_looking_menu_file_is_never_evidence_of_compatibility(rig):
    from nucleus_api import menus
    verdict = menus.check_compatibility(
        'out/MnSlChr.usd', 'css',
        target={'game_code': 'GALE01', 'disc_revision': 2, 'menu_variant': 'mex'},
        existing_codes=[])
    assert verdict['structure']['status'] == 'pass'
    assert verdict['target']['status'] == 'unknown'
    assert 'proves nothing' in verdict['target']['evidence']


def test_a_target_the_build_cannot_report_is_unknown_not_a_pass(rig):
    """A recorded observation only covers the signature fields it recorded."""
    from nucleus_api import menus
    package = next(p for p in menus.compatibility_manifest()['packages']
                   if p['package_id'] == 'halo3-matchmaking-lobby')
    found = {'package': package, 'package_id': package['package_id'],
             'name': package['name'], 'matched_by': 'installed_menu_file_sha256'}
    # A field the build cannot REPORT is unknown, not fail: nobody measured it,
    # and `fail` would say this package is known not to work here.
    no_variant = menus._target_dimension(
        package, {'game_code': 'GALE01', 'disc_revision': 2, 'menu_variant': None}, found)
    assert no_variant['status'] == 'unknown'
    assert 'menu_variant' in no_variant['evidence']
    assert 'cannot be compared' in no_variant['evidence']

    # A field it reports DIFFERENTLY is a fail: that was measured.
    other_disc = menus._target_dimension(
        package, {'game_code': 'GALE01', 'disc_revision': 0, 'menu_variant': 'mex'}, found)
    assert other_disc['status'] == 'fail'
    full = menus._target_dimension(
        package, {'game_code': 'GALE01', 'disc_revision': 2, 'menu_variant': 'mex'}, found)
    assert full['status'] == 'unknown'
    assert 'did not record WHICH menu file' in full['evidence']


def test_an_unknown_compatibility_dimension_must_be_accepted_explicitly(rig):
    change = rig.prepare()
    assert change['unknown_dimensions'], 'a synthetic menu file is in no manifest'
    auth = rig.approve(change, accepted=[])
    with pytest.raises(rig.api.BuildChangeRejected) as caught:
        rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    assert caught.value.code == 'compatibility_unknown'
    assert 'not a pass' in str(caught.value)


def test_two_codes_writing_one_address_different_values_is_a_conflict(rig):
    """Astra reproduced `pass` here: differently named, same address, different value."""
    from nucleus_api import codes
    rival = {'name': 'Something Else', 'source': '04263384 60000000'}
    clash = codes.address_conflicts([CSS_CODE, rival])
    assert clash['conflicts'][0]['address'] == '0x80263384'

    (rig.played_dir / 'files' / 'codes.ini').write_text(_ini(EXISTING_CODE, rival),
                                                        encoding='utf-8')
    change = rig.prepare()
    assert change['status'] == 'blocked'
    assert any(c['reason'] == 'same_address_different_value'
               for c in change['codes']['conflicts'])


def test_the_same_code_name_with_different_bytes_is_a_conflict_not_an_overwrite(rig):
    change = rig.prepare(code_changes={'add': [{'name': 'UCF', 'creator': 'Dan',
                                                'source': '04009999 60000000'}]})
    assert change['status'] == 'blocked'
    conflict = next(c for c in change['codes']['conflicts']
                    if c['reason'] == 'same_identifier_different_bytes')
    assert conflict['existing_content_hash'] != conflict['content_hash']


def test_a_caller_added_code_the_analyzer_cannot_model_is_an_unknown_of_the_proposal(rig):
    """It was recorded in the merge and left out of what the user had to accept."""
    exotic = {'name': 'Exotic', 'source': 'CC000000 00000000'}
    change = rig.prepare(code_changes={'add': [CSS_CODE, exotic]})
    assert any(u['identity'] == 'Exotic' for u in change['codes']['unknown'])
    assert 'code:Exotic' in change['unknown_dimensions']
    auth = rig.approve(change, accepted=[d for d in change['unknown_dimensions']
                                          if d != 'code:Exotic'])
    with pytest.raises(rig.api.BuildChangeRejected) as caught:
        rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    assert caught.value.code == 'compatibility_unknown'
    assert 'code:Exotic' in str(caught.value)


def test_an_identical_code_body_is_deduplicated_rather_than_added_twice(rig):
    (rig.played_dir / 'files' / 'codes.ini').write_text(
        _ini(EXISTING_CODE, CSS_CODE), encoding='utf-8')
    change, auth = rig.install()
    assert change['codes']['added'] == []
    assert change['codes']['duplicates'][0]['reason'] == 'already_present'
    rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    from core.gecko import parse_ini
    after = parse_ini((rig.played_dir / 'files' / 'codes.ini').read_text(encoding='utf-8'))
    assert [c['name'] for c in after].count('Disable Hardcoded CSS Animations') == 1


def test_a_published_description_that_lost_a_line_is_not_quietly_usable(rig):
    from nucleus_api import codes
    found = codes.from_published_description(
        '$Disable Hardcoded CSS Animations\n04263384 48000010\nnot hex at all\n',
        'ssbmnucleus.net post 14063')
    assert found['authorizes_install'] is False
    assert found['codes'][0]['status'] == 'invalid'
    assert found['codes'][0]['dropped_lines'] == ['not hex at all']
    assert found['warnings']


def test_an_extracted_build_folder_returns_unsupported_build_commit_and_a_wish(tmp_path,
                                                                               monkeypatch):
    extracted = tmp_path / 'storage-build'
    (extracted / 'files').mkdir(parents=True)
    (extracted / 'files' / 'MnSlChr.usd').write_bytes(menu_dat())
    monkeypatch.setenv('NUCLEUS_API_WORKSPACE', str(tmp_path / 'ws'))
    monkeypatch.setenv('NUCLEUS_API_BUILDS', json.dumps([str(extracted)]))
    monkeypatch.setenv('NUCLEUS_BUILD_TRUST_ROOT', str(tmp_path / 'trust'))
    from nucleus_api import builds as builds_module

    row = builds_module.list_builds()[0]
    assert row['committable'] is False and row['format'] == 'extracted_files'
    result = builds_module.prepare_change(row['id'], None, [])
    assert result['error']['code'] == 'unsupported_build_commit'
    assert result['wish']['kind'] == 'capability_gap'
    assert result['achieved']['installed'] is False


# ---------------------------------------------------------------------------
# One lock, honoured by every writer
# ---------------------------------------------------------------------------

def test_the_commit_holds_a_lock_no_other_writer_can_take(rig, monkeypatch):
    seen = {}

    def compiler(directory, ini_text):
        from core.state import mexcli_lock
        seen['mexcli_held'] = mexcli_lock._is_owned()
        try:
            bt.build_lock(directory, timeout=0.2)
            seen['second_writer'] = 'acquired'
        except bt.BuildBusyError:
            seen['second_writer'] = 'refused'
        return fake_code_compiler(directory, ini_text)

    monkeypatch.setattr(bt, 'CODE_COMPILER', compiler)
    change, auth = rig.install()
    rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    assert seen['mexcli_held'] is True
    assert seen['second_writer'] == 'refused'


def test_a_build_session_recovers_before_it_hands_the_build_over(rig, monkeypatch):
    def crash(stage, relpath):
        if stage == 'after_write':
            raise bt.SimulatedCrash('died mid-write')
    before = (rig.played_dir / 'files' / 'MnSlChr.usd').read_bytes()
    change, auth = rig.install()
    monkeypatch.setattr(bt, 'FAULT_HOOK', crash)
    with pytest.raises(bt.SimulatedCrash):
        rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    monkeypatch.setattr(bt, 'FAULT_HOOK', None)

    with build_access.build_session(rig.played_dir) as session:
        assert session.recovery, 'entering a session repairs what it finds'
        assert (rig.played_dir / 'files' / 'MnSlChr.usd').read_bytes() == before


@pytest.mark.parametrize('module_name,function_name,marker', [
    ('projects/routes/menus/backgrounds.py', 'install_bg_to_mex', 'build_session'),
    ('projects/routes/menus/backgrounds.py', 'install_sss_bg_to_mex', 'build_session'),
    ('projects/routes/menus/doors.py', 'install_door_mod', 'build_session'),
    ('projects/routes/menus/icons.py', 'install_single_css_icon', 'build_session'),
    ('projects/routes/codes.py', 'sync_project_codes', 'build_session'),
    ('projects/install/export_job.py', 'run_export_job', 'build_access.build_session'),
])
def test_every_app_writer_goes_through_the_one_build_access_service(module_name,
                                                                    function_name, marker):
    """A gate one writer honours is not a gate."""
    source = (BACKEND / module_name).read_text(encoding='utf-8')
    assert f'def {function_name}(' in source, f'{function_name} moved; update this test'
    body = source.split(f'def {function_name}(', 1)[1]
    for stop in ('\n@menus_bp.route', '\n@codes_bp.route', '\n@export_bp.route', '\ndef '):
        body = body.split(stop, 1)[0] if stop in body else body
    assert marker in body, f'{module_name}:{function_name} writes the build without the lock'


def test_opening_a_project_recovers_it():
    source = (BACKEND
              / 'projects' / 'routes' / 'project.py').read_text(encoding='utf-8')
    body = source.split('def open_project(', 1)[1].split('\n@project_bp.route', 1)[0]
    assert 'build_access.recover_on_open(' in body


def test_the_css_background_route_installs_the_menu_and_its_code_together():
    """It used to copy the menu, then TRY the code and log a warning on failure."""
    source = (BACKEND / 'projects' / 'routes' / 'menus'
              / 'backgrounds.py').read_text(encoding='utf-8')
    body = source.split('def install_bg_to_mex(', 1)[1].split('\n@menus_bp.route', 1)[0]
    assert 'session.apply(' in body and 'code_ini=' in body
    assert "'add-code'" not in body, 'add-code silently skipped a same-named code'
    assert 'Failed to add Gecko code' not in body, 'a swallowed code failure'


# ---------------------------------------------------------------------------
# Seams, manifest and packaging
# ---------------------------------------------------------------------------

def test_the_shipped_seams_are_the_real_tools():
    import importlib
    fresh_bt = importlib.reload(importlib.import_module('core.build_transaction'))
    fresh_menus = importlib.reload(importlib.import_module('nucleus_api.menus'))
    assert fresh_bt.CODE_COMPILER is fresh_bt.mexcli_sync_codes
    assert fresh_menus.NATIVE_MENU_READER is fresh_menus.native_menu_report
    assert fresh_bt.MANAGED_FILES == ('files/MnSlChr.usd', 'files/MnSlMap.usd',
                                      'files/codes.ini', 'files/codes.gct')
    assert fresh_bt.IDENTITY_FILES == ('sys/boot.bin', 'data/mex.json')


def test_a_gct_that_is_only_a_nonempty_file_does_not_pass(tmp_path):
    """The old verifier accepted any nonempty codes.gct - a hash passed it."""
    import hashlib
    fake = tmp_path / 'codes.gct'
    fake.write_bytes(hashlib.sha256(b'x').digest())
    assert bt.gct_report(fake)['status'] == 'fail'
    real = tmp_path / 'real.gct'
    real.write_bytes(bt.GCT_HEADER + bytes.fromhex('0426338448000010') + bt.GCT_FOOTER)
    assert bt.gct_report(real)['status'] == 'pass'


def test_a_destination_outside_the_managed_set_is_refused(rig):
    with pytest.raises(bt.TransactionError) as caught:
        with bt.build_lock(rig.played_dir):
            bt.apply_change(rig.played_dir,
                            [{'relpath': 'sys/main.dol',
                              'source': rig.ws / 'out' / 'MnSlChr.usd', 'sha256': None}],
                            label='should not happen')
    assert caught.value.code == 'unmanaged_destination'


def test_the_compatibility_manifest_is_versioned_and_self_consistent():
    from nucleus_api import codes, menus
    manifest = menus.compatibility_manifest()
    assert manifest['manifest_version'] >= 2
    assert manifest['policy']['unknown_is_not_pass'] is True
    ids = [p['package_id'] for p in manifest['packages']]
    assert 'halo3-matchmaking-lobby' in ids and 'dvd-menu-css-background' in ids
    for package in manifest['packages']:
        assert package['menu_type'] in ('css', 'sss')
        assert package['structure']['required_roots'] and package['structure']['evidence']
        assert package['digests']['roundtrip_background_sha256']
        for target in package.get('targets') or []:
            assert target['required_signature_fields']
            assert target['observation']['not_recorded'], \
                'an observation must say what it did NOT record'
            assert target['evidence']
        for code in package['required_codes']:
            assert code['content_hash'] == codes.content_hash(code['source'])
            assert code['origin'] and code['reason'] and code['evidence']
    dvd = next(p for p in manifest['packages'] if p['package_id'] == 'dvd-menu-css-background')
    assert dvd['targets'] == [], 'never booted, so it must claim no target'


def test_the_frozen_backend_ships_the_compatibility_manifest():
    spec = (APP.parent / 'tools' / 'build'
            / 'mex_backend.spec').read_text(encoding='utf-8')
    assert "'menus/compatibility_manifest.json'" in spec
    manifest = (BACKEND / 'data' / 'menus'
                / 'compatibility_manifest.json')
    assert manifest.is_file()
    json.loads(manifest.read_text(encoding='utf-8'))


@pytest.mark.skipif(not HALO_INSTALLED.is_file(),
                    reason='the harness experiment run outputs are not in this checkout')
def test_the_halo_fixture_is_recognised_by_its_bytes(tmp_path, monkeypatch):
    workspace = tmp_path / 'ws'
    (workspace / 'out').mkdir(parents=True)
    monkeypatch.setenv('NUCLEUS_API_WORKSPACE', str(workspace))
    (workspace / 'out' / 'MnSlChr.usd').write_bytes(HALO_INSTALLED.read_bytes())
    from nucleus_api import menus

    found = menus.identify_package('out/MnSlChr.usd')
    assert found['package_id'] == 'halo3-matchmaking-lobby'
    assert found['matched_by'] == 'installed_menu_file_sha256'
    verdict = menus.check_compatibility(
        'out/MnSlChr.usd', 'css',
        target={'game_code': 'GALE01', 'disc_revision': 2, 'menu_variant': 'mex'},
        existing_codes=[])
    assert verdict['structure']['status'] == 'pass'
    assert verdict['target']['status'] == 'unknown', \
        'the observation did not record its base menu file'
    assert [c['name'] for c in verdict['required_codes']] == [
        'Disable Hardcoded CSS Animations']



def test_commit_is_refused_outright_when_build_writing_is_switched_off(rig, monkeypatch):
    """A gate that half-applies is worse than no gate."""
    change, auth = rig.install()
    before = {name: bt.sha256_file(rig.played_dir / name)
              for name in ('files/MnSlChr.usd', 'files/codes.ini', 'files/codes.gct')}
    monkeypatch.setenv('NUCLEUS_BUILD_COMMIT', '0')

    result = rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    assert result['outcome'] == 'build_commit_disabled'
    assert result['error']['code'] == 'build_commit_disabled'
    assert result['achieved']['build_inputs_updated'] is False
    for name, digest in before.items():
        assert bt.sha256_file(rig.played_dir / name) == digest, name
    assert auth_module.load(auth['authorization_id'])['used'] is False

    monkeypatch.delenv('NUCLEUS_BUILD_COMMIT')
    assert rig.api.commit_change(change['prepared_change_id'],
                                 auth['authorization_id'])['stage'] == 'build_inputs_updated'


def test_preparation_touches_nothing_while_committing_is_switched_off(rig, monkeypatch):
    """"No build bytes change" has to include the journal's."""
    before = sorted(pathlib.Path(rig.played_dir).rglob('*'))
    monkeypatch.setenv('NUCLEUS_BUILD_COMMIT', '0')
    change = rig.prepare()
    assert change['status'] == 'blocked'
    assert change['error']['code'] == 'build_commit_disabled'
    assert change['commit_enabled'] is False
    assert 'no queue' in change['error']['message'] or 'no queue' in         change['error']['message'].lower()
    assert sorted(pathlib.Path(rig.played_dir).rglob('*')) == before


def test_the_build_commit_gate_is_registered_and_off_in_packaged_builds():
    from core import gates
    assert 'build_commit' in gates.GATES
    assert gates.GATES['build_commit'].env == 'NUCLEUS_BUILD_COMMIT'
    assert 'NUCLEUS_BUILD_COMMIT' in gates.packaged_off_env()


def test_one_build_session_flows_through_an_export_and_never_falls_back(rig, tmp_path):
    """A caller that already holds the build passes its session through.

    The build's cross-process lock is a file lock on a fresh handle, so a second
    session for the same build inside one operation would refuse itself; and
    mexcli_lock is re-entrant on the OWNING thread only, so a background export
    would wait on the lock its own caller holds. Both are refused, loudly.
    """
    from projects.install.export_job import ExportRequestError, run_export_job
    with build_access.build_session(rig.played_dir) as session:
        with pytest.raises(ExportRequestError) as caught:
            run_export_job({'filename': 'x.iso'}, background=True,
                           project_path=rig.played_dir / 'project.mexproj',
                           mex_manager=object(), build_guard=session)
        assert 'background export' in str(caught.value)

        with pytest.raises(ExportRequestError) as caught:
            run_export_job({'filename': 'x.iso'}, background=False,
                           project_path=rig.other_dir / 'project.mexproj',
                           mex_manager=object(), build_guard=session)
        assert 'handed a session for' in str(caught.value)


# ---------------------------------------------------------------------------
# Astra's re-review: a build nobody can account for is not handed out
# ---------------------------------------------------------------------------

def test_an_unreadable_journal_quarantines_the_build_instead_of_being_skipped(rig):
    """Skipping it answers "nothing was wrong", which nobody established."""
    change, auth = rig.install()
    receipt = rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    journal = (rig.played_dir / bt.JOURNAL_DIRNAME / 'txn' / receipt['journal_id']
               / 'journal.json')
    journal.write_text('{ this is not json', encoding='utf-8')

    with pytest.raises(build_access.BuildQuarantined) as caught:
        with build_access.build_session(rig.played_dir):
            pass
    assert 'could not be read' in str(caught.value)
    assert bt.quarantined(rig.played_dir)


def test_recovery_that_cannot_restore_quarantines_rather_than_reporting_success(rig,
                                                                                monkeypatch):
    """Astra's probe returned `rollback_completed` having restored nothing."""
    change, auth = rig.install()

    def crash(stage, relpath):
        if stage == 'after_write':
            raise bt.SimulatedCrash('died mid-write')
    monkeypatch.setattr(bt, 'FAULT_HOOK', crash)
    with pytest.raises(bt.SimulatedCrash):
        rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    monkeypatch.setattr(bt, 'FAULT_HOOK', None)

    txn = sorted((rig.played_dir / bt.JOURNAL_DIRNAME / 'txn').iterdir())[-1]
    (txn / 'originals' / 'files__MnSlChr.usd').write_bytes(b'not the original')

    with pytest.raises(build_access.BuildQuarantined):
        with build_access.build_session(rig.played_dir):
            pass
    problems = bt.quarantined(rig.played_dir)
    assert problems and 'missing or altered' in problems[0]['problem']


def test_opening_a_build_says_when_it_cannot_be_recovered(rig):
    change, auth = rig.install()
    receipt = rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    (rig.played_dir / bt.JOURNAL_DIRNAME / 'txn' / receipt['journal_id']
     / 'journal.json').write_text('broken', encoding='utf-8')

    health = build_access.recover_on_open(rig.played_dir)
    assert health['status'] == 'quarantined'
    assert health['problems'] and health['message']


def test_a_clean_build_opens_clean_and_says_so(rig):
    health = build_access.recover_on_open(rig.played_dir)
    assert health == {'status': 'clean', 'actions': [], 'problems': [], 'message': ''}


def test_an_interrupted_whole_workspace_save_quarantines_the_build(rig):
    """MexCLI rewrites many files at once; it cannot be undone file by file."""
    with build_access.build_session(rig.played_dir) as session:
        record = bt.begin_external_save(rig.played_dir, 'mexcli set-css-icon')
        assert record['state'] == bt.EXTERNAL_SAVE
        assert session.token
    # The process died before end_external_save: the journal is still open.
    with pytest.raises(build_access.BuildQuarantined) as caught:
        with build_access.build_session(rig.played_dir):
            pass
    assert 'whole-workspace save' in str(caught.value)


def test_a_completed_whole_workspace_save_leaves_the_build_usable(rig):
    with build_access.build_session(rig.played_dir) as session:
        with session.external_save('mexcli set-css-icon'):
            pass
    with build_access.build_session(rig.played_dir) as session:
        assert session.recovery == []


def test_a_failed_whole_workspace_save_quarantines_the_build(rig):
    with pytest.raises(RuntimeError):
        with build_access.build_session(rig.played_dir) as session:
            with session.external_save('mexcli set-css-icon'):
                raise RuntimeError('mexcli exited 1')
    assert bt.quarantined(rig.played_dir)


def test_a_finalization_path_a_project_supplied_is_never_written(rig, tmp_path):
    """Recovery reads journals out of the build; a project could author one."""
    change, auth = rig.install()
    receipt = rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])
    journal_path = (rig.played_dir / bt.JOURNAL_DIRNAME / 'txn' / receipt['journal_id']
                    / 'journal.json')
    journal = json.loads(journal_path.read_text(encoding='utf-8'))
    outside = tmp_path / 'planted.json'
    journal['state'] = bt.VERIFIED
    journal['finalize'] = [{'kind': 'receipt', 'id': '../../../planted',
                            'json': {'owned': True}},
                           {'path': str(outside), 'json': {'owned': True}}]
    journal_path.write_text(json.dumps(journal), encoding='utf-8')

    with pytest.raises(build_access.BuildQuarantined):
        with build_access.build_session(rig.played_dir):
            pass
    assert not outside.exists(), 'a journal does not get to name a destination'


def test_a_rollback_interrupted_before_its_receipt_is_finished_by_recovery(rig, monkeypatch):
    change, auth = rig.install()
    receipt = rig.api.commit_change(change['prepared_change_id'], auth['authorization_id'])

    real = bt._write_finalization

    def die(directory, journal):
        raise bt.SimulatedCrash('died before the receipt')

    monkeypatch.setattr(bt, '_write_finalization', die)
    with pytest.raises(bt.SimulatedCrash):
        rig.api.rollback(receipt['receipt_id'])
    monkeypatch.setattr(bt, '_write_finalization', real)

    actions = rig.api.recover(rig.played['id'])
    assert [a['action'] for a in actions] == ['rollback_completed']
    assert rig.api.receipt(receipt['receipt_id'])['outcome'] == 'rolled_back'


# ---------------------------------------------------------------------------
# Astra's re-review: the gate, the compiler, and the code analysis
# ---------------------------------------------------------------------------

def test_the_packaged_build_really_turns_the_gate_off():
    """The Python table said packaged_off; electron's list did not carry it."""
    from core import gates
    main = (APP / 'electron' / 'main.js').read_text(
        encoding='utf-8')
    block = main.split('PACKAGED_OFF_GATES', 1)[1].split(']', 1)[0]
    for env in gates.packaged_off_env():
        assert f"'{env}'" in block, f'{env} is packaged_off in Python but not in electron'


def test_the_compiler_identity_covers_its_managed_implementation():
    """mexcli.exe is a launcher; the behaviour is in the DLLs beside it."""
    identity = bt.compiler_identity()
    assert set(bt.COMPILER_FILES) >= {'mexcli.exe', 'mexcli.dll', 'mexLib.dll', 'HSDRaw.dll'}
    if identity['available']:
        assert len(identity['parts']) > 1
        assert identity['sha256'] != identity['parts']['mexcli.exe']


def test_two_writes_that_overlap_without_sharing_a_start_address_conflict():
    """Astra's probe: 0x80001000 (32-bit) and 0x80001001 (byte) reported clean."""
    from nucleus_api import codes
    clash = codes.address_conflicts([
        {'name': 'Word', 'source': '04001000 11111111'},
        {'name': 'Byte', 'source': '00001001 00000022'}])
    assert clash['conflicts'], 'an overlapping byte write is a conflict'


def test_two_c2_bodies_of_the_same_length_are_not_called_redundant():
    """Their 'value' was `branch+N`, so different code looked identical."""
    from nucleus_api import codes
    result = codes.address_conflicts([
        {'name': 'A', 'source': 'C2001000 00000001\n60000000 00000000'},
        {'name': 'B', 'source': 'C2001000 00000001\n38000001 00000000'}])
    assert result['conflicts'] and not result['redundant']
    assert {u['identity'] for u in result['unresolved']} == {'A', 'B'}


def test_an_injected_body_is_an_unmodelled_effect_not_a_summary():
    from nucleus_api import codes
    targets = codes.write_targets('C2001000 00000001\n60000000 00000000')
    assert targets['writes'][0]['unmodelled_body'] is True
    assert targets['analyzable'] is False


def test_the_code_verdict_stays_unknown_because_maincode_is_not_in_codes_ini(rig):
    from nucleus_api import menus
    package = next(p for p in menus.compatibility_manifest()['packages']
                   if p['package_id'] == 'halo3-matchmaking-lobby')
    verdict, _ = menus._codes_dimension(package, [], [], False)
    assert verdict['status'] == 'unknown'
    assert verdict['complete_set'] is False
    assert any('MainCode' in line for line in verdict['unexamined'])


# ---------------------------------------------------------------------------
# Astra's re-review 8 and 9: the stage-select layout, and a real graph walk
# ---------------------------------------------------------------------------

def _real_menu_files(stem):
    """Every real menu file of that kind on this machine, newest first."""
    from core import config
    found = []
    for base in (Path(config.PROJECTS_PATH), Path(config.STORAGE_PATH)):
        if base.is_dir():
            found += sorted(base.glob(f'*/files/{stem}.usd'))
            found += sorted(base.glob(f'*/files/{stem}.dat'))
    return found


@pytest.mark.skipif(not _real_menu_files('MnSlMap'),
                    reason='no real MnSlMap.usd on this machine')
def test_the_stage_select_table_is_read_with_its_own_layout():
    """The SSS was checked as if it were the CSS: wrong root, wrong offset.

    `MnSelectMapDataTable` is not what the file carries - it is
    `MnSelectStageDataTable` - and its background is at 0xB0. Offset 0x10 in
    that table is the LARGE ICON model, which is also a relocated pointer, so
    the old check read a real pointer to the wrong thing and called it a pass.
    """
    from nucleus_api import menus
    from nucleus_api._workspace import library_path
    source = library_path(_real_menu_files('MnSlMap')[0].resolve(), why='a real SSS file')

    roots = [entry['name'] for entry in menus.dat_integrity(source)['roots']]
    assert 'MnSelectStageDataTable' in roots

    graph = menus.menu_graph_check(source, 'sss')
    assert graph['status'] == 'pass', graph['reason']
    assert graph['root'] == 'MnSelectStageDataTable'
    assert graph['background_slot'] == 0xB0
    assert graph['graph']['nodes'] >= 1 and graph['graph']['cycle'] is None

    assert menus.BACKGROUND_MODEL_SLOTS['MnSelectStageDataTable'] == 0xB0
    assert menus.BACKGROUND_MODEL_SLOTS['MnSelectChrDataTable'] == 0x10


@pytest.mark.skipif(not _real_menu_files('MnSlChr'),
                    reason='no real MnSlChr.usd on this machine')
def test_a_real_character_select_file_walks_a_real_joint_tree():
    from nucleus_api import menus
    from nucleus_api._workspace import library_path
    source = library_path(_real_menu_files('MnSlChr')[0].resolve(), why='a real CSS file')
    graph = menus.menu_graph_check(source, 'css')
    assert graph['status'] == 'pass', graph['reason']
    assert graph['graph']['nodes'] > 1, 'a real backdrop is more than one joint'
    assert graph['graph']['depth'] >= 1


def test_a_stage_select_file_is_refused_when_its_table_is_too_short(rig):
    """A table shorter than HSDRaw's TrimmedSize is not that table."""
    from nucleus_api import menus
    short = bytearray(menu_dat(SSS_ROOT))
    # Declare the same root over a CSS-sized table.
    payload_size = struct.unpack('>I', bytes(short[4:8]))[0]
    assert payload_size > 0xD0
    tiny = menu_dat(CSS_ROOT)
    tiny = tiny.replace(CSS_ROOT.encode(), SSS_ROOT.encode()[:len(CSS_ROOT)])
    path = rig.ws / 'out' / 'short-sss.usd'
    path.write_bytes(tiny)
    report = menus.menu_graph_check('out/short-sss.usd', 'sss')
    assert report['status'] == 'fail'


def test_a_background_pointing_at_itself_is_a_cycle_not_a_pass(rig):
    """Bounds-checking says the number is inside the file, nothing more."""
    from nucleus_api import menus
    root_size = menus.MENU_TABLE_SIZES[CSS_ROOT]
    table = bytearray(root_size)
    joint_at = root_size
    struct.pack_into('>I', table, menus.BACKGROUND_MODEL_SLOTS[CSS_ROOT], joint_at)
    joint = bytearray(menus.JOBJ_SIZE)
    struct.pack_into('>I', joint, menus.JOBJ_CHILD, joint_at)     # its own child
    payload = bytes(table) + bytes(joint)
    relocations = struct.pack('>II', menus.BACKGROUND_MODEL_SLOTS[CSS_ROOT],
                              joint_at + menus.JOBJ_CHILD)
    body = (struct.pack('>5I', 0, len(payload), 2, 1, 0) + b'\x00' * 12 + payload
            + relocations + struct.pack('>II', 0, 0) + CSS_ROOT.encode() + b'\x00')
    blob = struct.pack('>I', len(body)) + body[4:]
    path = rig.ws / 'out' / 'cycle.usd'
    path.write_bytes(blob)

    assert menus.dat_integrity('out/cycle.usd')['status'] == 'pass', 'it is a valid DAT'
    report = menus.menu_graph_check('out/cycle.usd', 'css')
    assert report['status'] == 'fail'
    assert 'cycle' in report['reason']
    assert report['graph']['cycle'] == joint_at


def test_a_background_joint_with_no_room_for_itself_is_refused(rig):
    """A joint one byte from the end of the data section is not a joint."""
    from nucleus_api import menus
    root_size = menus.MENU_TABLE_SIZES[CSS_ROOT]
    table = bytearray(root_size)
    struct.pack_into('>I', table, menus.BACKGROUND_MODEL_SLOTS[CSS_ROOT], root_size)
    payload = bytes(table) + b'\x00'          # one byte where a 0x40 JOBJ belongs
    relocations = struct.pack('>I', menus.BACKGROUND_MODEL_SLOTS[CSS_ROOT])
    body = (struct.pack('>5I', 0, len(payload), 1, 1, 0) + b'\x00' * 12 + payload
            + relocations + struct.pack('>II', 0, 0) + CSS_ROOT.encode() + b'\x00')
    path = rig.ws / 'out' / 'stub.usd'
    path.write_bytes(struct.pack('>I', len(body)) + body[4:])

    report = menus.menu_graph_check('out/stub.usd', 'css')
    assert report['status'] == 'fail'
    assert 'needs 64 bytes' in report['reason']


def test_a_relocation_table_past_the_budget_is_refused_not_walked(rig):
    """A stranger's DAT is walked while this process holds the build lock."""
    from nucleus_api import menus
    payload = b'\x00' * 0x40
    claimed = menus.MAX_RELOCATIONS + 1
    body = (struct.pack('>5I', 0, len(payload), claimed, 1, 0) + b'\x00' * 12 + payload
            + b'\x00' * (claimed * 4) + struct.pack('>II', 0, 0)
            + CSS_ROOT.encode() + b'\x00')
    path = rig.ws / 'out' / 'huge.usd'
    path.write_bytes(struct.pack('>I', len(body)) + body[4:])
    report = menus.dat_integrity('out/huge.usd')
    assert report['status'] == 'fail'
    assert 'relocation entries' in report['reason']


def test_the_graph_budgets_are_declared_and_bounded():
    from nucleus_api import menus
    assert 0 < menus.MAX_GRAPH_DEPTH <= 4096
    assert 0 < menus.MAX_GRAPH_NODES <= 1_000_000
    assert 0 < menus.MAX_RELOCATIONS <= 5_000_000


# ---------------------------------------------------------------------------
# Astra's security re-review: a dropped line is never a valid code
# ---------------------------------------------------------------------------

def test_a_bom_before_the_header_no_longer_hides_a_dropped_line():
    """The BOM stopped '$Test' looking like a header, so nothing was attributed."""
    from nucleus_api import codes
    found = codes.from_published_description(
        '﻿$Test\n04001000 11111111\nnot hex at all\n', 'probe')
    row = found['codes'][0]
    assert row['name'] == 'Test'
    assert row['status'] == 'invalid' and row['valid'] is False
    assert row['dropped_lines'] == ['not hex at all']
    assert "'not hex at all'" in row['error'], 'the line is quoted, escaped'
    assert found['warnings']


def test_a_loose_description_block_no_longer_hides_a_dropped_line():
    from nucleus_api import codes
    found = codes.from_published_description(
        'Cool Code\nThis is what it does.\n04001000 11111111\nnot hex at all\n', 'probe')
    row = found['codes'][0]
    assert row['status'] == 'invalid' and row['dropped_lines'] == ['not hex at all']


def test_a_dropped_line_is_quoted_escaped_not_pasted_into_the_message():
    from nucleus_api import codes
    found = codes.from_published_description(
        '$Test\n04001000 11111111\n‮not hex\n', 'probe')
    row = found['codes'][0]
    assert row['status'] == 'invalid'
    assert '‮' not in row['error'] and '\x07' not in row['error']
    assert '\\u202e' in row['error'] and '\\x07' in row['error']


def test_prose_after_the_code_block_is_not_called_a_dropped_line():
    from nucleus_api import codes
    found = codes.from_published_description(
        '$Good\n04001000 11111111\n\nThanks for reading!\n', 'probe')
    assert found['codes'][0]['status'] == 'valid'
    assert found['codes'][0]['dropped_lines'] == []


def test_an_ini_with_a_bom_still_parses_its_first_code():
    from core.gecko import parse_ini
    parsed = parse_ini('﻿$!Disable Hardcoded CSS Animations\n04263384 48000010\n')
    assert [c['name'] for c in parsed] == ['Disable Hardcoded CSS Animations']
    assert parsed[0]['enabled'] is True
