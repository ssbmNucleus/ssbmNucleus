"""Model extras (Falco's and Fox's gun): the HSDRawViewer `--model` runs, the
Gun Editor's .dat upload, and restore-vanilla. Bug report 76d9cf69d55a: a
skinned gun installed over Falco's blaster halted the game, the editor's .dat
upload failed with an empty "Model export failed: ", and the gun could not be
put back to vanilla.

The fast tests fake the subprocess. The slow ones run the pinned HSDRawViewer
on the vanilla PlFc.dat (no community model): `NUCLEUS_HSDRAW_EXE` points them
at a local build of the fork.
"""
import io
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

import core.config
from core.extra_lookup import get_extra_type
from vault.extras import helpers
from vault.extras import models
from vault.routes.extras import models as model_routes
from projects.routes import extras as project_extras
from shared.vanilla_extract import vanilla_refs

GUN = get_extra_type('Falco', 'gun')


def _done(stdout, returncode=0, stderr=''):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


@pytest.fixture
def fake_tool(monkeypatch, tmp_path):
    """Replace the HSDRawViewer run; `calls` records each command line."""
    calls = []
    outcome = {'result': _done('SUCCESS: done\n'), 'write': None}

    def run(cmd, **_kwargs):
        calls.append([str(part) for part in cmd])
        if outcome['write']:
            outcome['write'](cmd)
        return outcome['result']

    monkeypatch.setattr(helpers, 'HSDRAW_VIEWER_PATH', tmp_path / 'HSDRawViewer.exe')
    monkeypatch.setattr(models.subprocess, 'run', run)
    return calls, outcome


# --------------------------------------------------------------------------
# the --model runs
# --------------------------------------------------------------------------

def test_failure_reason_comes_from_stdout(fake_tool, tmp_path):
    """HSDRawViewer prints its errors on stdout; the reported message was
    built from stderr only and came out empty."""
    _calls, outcome = fake_tool
    outcome['result'] = _done(
        'Exporting model from: x\nERROR: Model operation failed: Non-negative number required.\n'
        'Stack trace:    at HSDRaw.HSDRawFile.Open(Stream stream)\n', returncode=1)
    with pytest.raises(models.ModelToolError) as error:
        models.extract_model_from_dat(tmp_path / 'x.dat', GUN['model_path'], tmp_path / 'x.dae')
    assert str(error.value) == 'Model export failed: Model operation failed: Non-negative number required.'
    assert not isinstance(error.value, models.ModelNotInDat)


def test_a_file_without_the_model_is_model_not_in_dat(fake_tool, tmp_path):
    _calls, outcome = fake_tool
    outcome['result'] = _done(
        "Root 'ftDataFalco' not found. Available roots:\n  - PlyFalco5K_Share_joint\n"
        f"ERROR: Could not find JOBJ at path: {GUN['model_path']}\n", returncode=1)
    with pytest.raises(models.ModelNotInDat, match='Could not find JOBJ'):
        models.extract_model_from_dat(tmp_path / 'PlFcNr.dat', GUN['model_path'], tmp_path / 'x.dae')


def test_exit_zero_without_success_is_a_failure(fake_tool, tmp_path):
    """A build that does not know the operation prints a usage line and
    exits 0; that must not count as a done copy."""
    _calls, outcome = fake_tool
    outcome['result'] = _done("Unknown operation: copy\nUse 'export' or 'import'\n")
    with pytest.raises(models.ModelToolError, match="Use 'export' or 'import'"):
        models.copy_model_between_dats(tmp_path / 'a.dat', GUN['model_path'],
                                       tmp_path / 'b.dat', tmp_path / 'c.dat')


# --------------------------------------------------------------------------
# Gun Editor: .dat upload
# --------------------------------------------------------------------------

@pytest.fixture
def editor(vault, monkeypatch):
    monkeypatch.setattr(helpers, 'STORAGE_PATH', vault.storage)
    vault.write({'characters': {}})
    return vault.client(model_routes, 'extras_bp')


def _upload(client, filename):
    return client.post('/api/mex/storage/models/create', data={
        'file': (io.BytesIO(b'not checked here'), filename),
        'character': 'Falco', 'extraType': 'gun', 'name': 'Test gun'})


def test_costume_dat_upload_names_the_file_to_use(editor, fake_tool, vault):
    _calls, outcome = fake_tool
    outcome['result'] = _done(f"ERROR: Could not find JOBJ at path: {GUN['model_path']}\n", returncode=1)
    response = _upload(editor, 'PlFcNr.dat')
    assert response.status_code == 400
    error = response.get_json()['error']
    assert error.startswith('PlFcNr.dat has no Gun Model in it. Upload the PlFc.dat')
    assert not list((vault.storage / 'Falco' / 'models').iterdir())
    assert vault.read()['characters'] == {}


def test_other_export_failures_carry_the_reason(editor, fake_tool):
    _calls, outcome = fake_tool
    outcome['result'] = _done('ERROR: Model operation failed: Unable to read beyond the end of the stream.\n',
                              returncode=1)
    response = _upload(editor, 'PlFc.dat')
    assert response.status_code == 500
    assert response.get_json()['error'] == (
        'Model export failed: Model operation failed: Unable to read beyond the end of the stream.')
    assert not list((helpers.STORAGE_PATH / 'Falco' / 'models').iterdir())   # no half-made folder


def _export_writes_textures(cmd):
    """What `--model export` leaves: the .dae, its textures beside it under
    fixed names, and a .textures.json sidecar."""
    dae = Path(cmd[-1])
    dae.write_text(f'<dae {dae.stem}/>')
    (dae.parent / 'Texture_0_CMP.png').write_text(dae.stem)
    (dae.parent / (dae.name + '.textures.json')).write_text('{}')


def test_each_gun_keeps_its_own_textures(editor, fake_tool, vault):
    """Two guns uploaded from .dat files. Both used to export into Falco/models/,
    and the second one's Texture_0_CMP.png overwrote the first's."""
    _calls, outcome = fake_tool
    outcome['write'] = _export_writes_textures
    mods = [_upload(editor, 'PlFc.dat').get_json()['mod'] for _ in range(2)]
    assert mods[0]['id'] != mods[1]['id']
    for mod in mods:
        assert mod['model_file'] == f"models/{mod['id']}/{mod['id']}.dae"
        dae = vault.storage / 'Falco' / mod['model_file']
        assert dae.read_text() == f"<dae {mod['id']}/>"
        assert (dae.parent / 'Texture_0_CMP.png').read_text() == mod['id']
        assert not list(dae.parent.glob('*_temp.dat'))


def test_deleting_a_gun_removes_its_folder(editor, fake_tool, vault):
    _calls, outcome = fake_tool
    outcome['write'] = _export_writes_textures
    keep, gone = (_upload(editor, 'PlFc.dat').get_json()['mod'] for _ in range(2))
    response = editor.post('/api/mex/storage/models/delete',
                           json={'character': 'Falco', 'extraType': 'gun', 'modId': gone['id']})
    assert response.status_code == 200, response.get_json()
    assert sorted(p.name for p in (vault.storage / 'Falco' / 'models').iterdir()) == [keep['id']]
    assert [m['id'] for m in vault.read()['characters']['Falco']['extras']['gun']] == [keep['id']]


def test_deleting_an_older_flat_gun_keeps_the_shared_textures(tmp_path):
    """A gun stored before the per-gun folders loses its .dae and sidecar; the
    textures stay, since another gun of that time may use the same names."""
    flat = tmp_path / 'models'
    flat.mkdir()
    for name in ('gun_old.dae', 'gun_old.dae.textures.json', 'Texture_0_CMP.png', 'gun_other.dae'):
        (flat / name).write_text('x')
    models.remove_model_files(tmp_path, 'models/gun_old.dae', 'gun_old')
    assert sorted(p.name for p in flat.iterdir()) == ['Texture_0_CMP.png', 'gun_other.dae']


# --------------------------------------------------------------------------
# restore-vanilla for a model extra
# --------------------------------------------------------------------------

@pytest.fixture
def project(vault, monkeypatch):
    target = vault.touch('project', 'files', 'PlFc.dat', data=b'custom gun')
    reference = vault.touch('test-base', 'files', 'PlFc.dat', data=b'vanilla gun')
    monkeypatch.setattr(helpers, 'get_project_files_dir', lambda: target.parent)
    monkeypatch.setattr(vanilla_refs, 'ensure_vanilla_ref', lambda name, **kw: reference)
    return vault.client(project_extras, 'extras_bp'), target, reference


def _restore(client):
    return client.post('/api/mex/storage/extras/restore-vanilla',
                       json={'character': 'Falco', 'extraType': 'gun'})


def test_restore_vanilla_copies_the_model_from_the_reference(project, fake_tool):
    client, target, reference = project
    calls, outcome = fake_tool
    # the copy writes its output DAT, which then replaces the project's
    outcome['write'] = lambda cmd: Path(cmd[-1]).write_bytes(b'project with the vanilla gun')
    response = _restore(client)
    assert response.status_code == 200, response.get_json()
    assert calls == [[str(helpers.HSDRAW_VIEWER_PATH), '--model', 'copy', str(target),
                      GUN['model_path'], str(reference), str(target.with_name('PlFc_temp.dat'))]]
    assert target.read_bytes() == b'project with the vanilla gun'
    assert not target.with_name('PlFc_temp.dat').exists()


def test_failed_restore_leaves_the_project_dat_alone(project, fake_tool):
    client, target, _reference = project
    _calls, outcome = fake_tool
    outcome['write'] = lambda cmd: Path(cmd[-1]).write_bytes(b'half written')
    outcome['result'] = _done('ERROR: Could not find JOBJ at path in the source DAT: x\n', returncode=1)
    response = _restore(client)
    assert response.status_code == 409
    assert 'Could not find JOBJ' in response.get_json()['error']
    assert target.read_bytes() == b'custom gun'
    assert not target.with_name('PlFc_temp.dat').exists()


def test_restore_without_a_vanilla_reference_says_so(project, fake_tool, monkeypatch):
    client, target, _reference = project
    calls, _outcome = fake_tool
    monkeypatch.setattr(vanilla_refs, 'ensure_vanilla_ref', lambda name, **kw: None)
    response = _restore(client)
    assert response.status_code == 409
    assert 'No vanilla PlFc.dat' in response.get_json()['error']
    assert calls == []
    assert target.read_bytes() == b'custom gun'


# --------------------------------------------------------------------------
# slow: the real HSDRawViewer on the vanilla PlFc.dat
# --------------------------------------------------------------------------

SKELETON, SKELETON_ROOT = 1, 2
POBJ_ENVELOPE = 1 << 13


def _article_joints(path):
    """[(joint flags, parent index, [PObj flags of each DObj's PObjs])] of
    Falco's gun article, depth first."""
    d = Path(path).read_bytes()
    _size, data_size, relocs, roots, refs = struct.unpack_from('>5I', d, 0)
    table = 0x20 + data_size + relocs * 4
    strings = table + (roots + refs) * 8
    named = {}
    for i in range(roots):
        offset, name = struct.unpack_from('>2I', d, table + i * 8)
        named[d[strings + name:d.index(b'\0', strings + name)].decode()] = offset

    def u32(offset):
        return struct.unpack_from('>I', d, 0x20 + offset)[0]

    articles = u32(named['ftDataFalco'] + 0x48)
    root = u32(u32(u32(articles + 4) + 0x10))      # Articles_1 -> Model_ -> RootModelJoint
    out = []

    def walk(joint, parent):
        while joint:
            index = len(out)
            pobjs = []
            dobj = u32(joint + 0x10)
            while dobj:
                pobj = u32(dobj + 0x0C)
                while pobj:
                    pobjs.append(struct.unpack_from('>H', d, 0x20 + pobj + 0x0C)[0])
                    pobj = u32(pobj + 0x04)
                dobj = u32(dobj + 0x04)
            out.append((u32(joint + 0x04), parent, pobjs))
            walk(u32(joint + 0x08), index)
            joint = u32(joint + 0x0C)
    walk(root, None)
    return out


def _unskinned_envelopes(joints):
    """Envelope PObjs the game cannot draw: no SKELETON / SKELETON_ROOT joint
    at or above theirs (displayfunc.c line 422, HSD_JObjFindSkeleton)."""
    bad = 0
    for flags, parent, pobjs in joints:
        skeleton = flags & (SKELETON | SKELETON_ROOT)
        walk = parent
        while not skeleton and walk is not None:
            skeleton = joints[walk][0] & (SKELETON | SKELETON_ROOT)
            walk = joints[walk][1]
        if not skeleton:
            bad += sum(1 for pobj in pobjs if pobj & POBJ_ENVELOPE)
    return bad


@pytest.fixture
def real_tool(tmp_path, monkeypatch):
    exe = Path(core.config.HSDRAW_EXE)
    if not exe.is_file():
        pytest.skip(f'HSDRawViewer is not fetched here ({exe})')
    reference = vanilla_refs.ensure_vanilla_ref('PlFc.dat')
    if reference is None:
        pytest.skip('No vanilla PlFc.dat (record a vanilla ISO first)')
    monkeypatch.setattr(helpers, 'HSDRAW_VIEWER_PATH', exe)
    vanilla = tmp_path / 'PlFc_vanilla.dat'
    shutil.copyfile(reference, vanilla)
    return vanilla


def _skinned_gun(work, vanilla):
    """The vanilla gun as a skinned model: exported, with the `_SINGLE` mesh
    names that make the import bind each mesh rigidly taken off, so every
    mesh imports as envelope-weighted geometry on the article's root joint --
    the shape of a gun modelled on the root (the reported one)."""
    export = work / 'export'
    export.mkdir()
    models.extract_model_from_dat(vanilla, GUN['model_path'], export / 'gun.dae')
    skinned = work / 'skinned'
    shutil.copytree(export, skinned)
    dae = skinned / 'gun.dae'
    dae.write_text(dae.read_text(encoding='utf-8').replace('_SINGLE', ''), encoding='utf-8')
    return dae


@pytest.mark.slow
def test_skinned_gun_import_keeps_a_skeleton_over_its_envelopes(real_tool, tmp_path):
    vanilla = real_tool
    assert all(not flags & (SKELETON | SKELETON_ROOT) for flags, _p, _d in _article_joints(vanilla))
    dae = _skinned_gun(tmp_path, vanilla)
    installed = tmp_path / 'PlFc_skinned.dat'
    models.import_model_to_dat(vanilla, GUN['model_path'], dae, installed)
    joints = _article_joints(installed)
    assert sum(1 for _f, _p, pobjs in joints for pobj in pobjs if pobj & POBJ_ENVELOPE) > 0
    assert _unskinned_envelopes(joints) == 0


@pytest.mark.slow
def test_model_copy_puts_the_vanilla_gun_back(real_tool, tmp_path):
    vanilla = real_tool
    dae = _skinned_gun(tmp_path, vanilla)
    project = tmp_path / 'PlFc.dat'
    models.import_model_to_dat(vanilla, GUN['model_path'], dae, project)
    assert _article_joints(project) != _article_joints(vanilla)
    restored = tmp_path / 'PlFc_restored.dat'
    models.copy_model_between_dats(project, GUN['model_path'], vanilla, restored)
    assert _article_joints(restored) == _article_joints(vanilla)
