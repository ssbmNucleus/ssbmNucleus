"""Randall's model import: one ``import_model`` job (model_import/chat/import_job.py) that runs rigswap as a
subprocess, offered on an import turn (routed per turn by model_import/chat/studio_import.py) and, for another fighter
after a finished import, on the normal turns after it.

No model request and no real rigswap run: the provider is a stand-in, and rigswap is a tiny fake package
(``FAKE_COSTUME``, run as a real subprocess by the app's Python) that prints a few lines and writes the result.json
the real entry point writes, as the test's ``FAKE_RIGSWAP`` says. The vault save (studio.finish.finish) is a stand-in
too, except in the tests of the save itself. A change to a finished import (``--fix``) is the same stand-in.
"""
import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from randall.assistant import compaction, engine, live_runs, store, tools
from shared import mod_files
from randall.model_import.chat import import_job, studio_import
from randall.model_import.chat.attached_model import attached_model_waiting
from randall.model_import.studio import finish as finishing

FLASH = 'z-ai/glm-5.3-flash'

# rigswap.plugins.melee.costume's stand-in: its arguments and environment to seen.json, a few lines to stdout, then
# what FAKE_RIGSWAP says: done (a costume file and result.json; ``auto`` picks Ganondorf), load (failed loading), crash
# (no result.json). ``--fix <out> "<words>"`` is a change to the costume already made there (done.json): it writes
# fixed.json (what it was told) and a new costume file with ``changed`` and ``why``, or, told "the texture", fails at
# stage fix in the look's words.
FAKE_COSTUME = r'''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
cache = args[args.index('--cache') + 1]
if args[0] == '--fix':
    out, words = Path(args[1]), args[2]
    heard = args[args.index('--heard', 3) + 1] if '--heard' in args[3:] else None
    last = json.loads((out / 'done.json').read_text(encoding='utf-8'))
    n = 1 + len(list(out.glob('2-swap-fix*')))
    (out / 'fixed.json').write_text(json.dumps(dict(words=words, heard=heard, cache=cache, n=n)), encoding='utf-8')
    print('looking at what was said', flush=True)
    result = dict(fighter=last['fighter'], seconds=30.0, cost_usd=0.004, asks=1)
    if 'texture' in words:
        result.update(status='failed', failed=dict(stage='fix', cause='Unfixable: the texture is wrong, not the body'))
    else:
        dat = out / f'2-swap-fix{n}' / '4-export' / f"{last['fighter']}.dat"
        dat.parent.mkdir(parents=True, exist_ok=True)
        dat.write_bytes(b'HSD costume stand-in, changed ' * (8 + n))
        result.update(status='done', dat=str(dat.resolve()), changed={'head': [1.0, 0.8]},
                      why='the head is too big for the body.', record=str(dat.parent.parent / 'record.json'))
        if os.environ.get('FAKE_RIGSWAP') == 'wreck':
            result.update(warning='this probably did not work: the legs are folded under the body')
        (out / 'done.json').write_text(json.dumps(result), encoding='utf-8')
    (out / 'result.json').write_text(json.dumps(result), encoding='utf-8')
    sys.exit(0 if result['status'] == 'done' else 1)
download, fighter, out = [a for i, a in enumerate(args) if a != '--cache' and (i == 0 or args[i - 1] != '--cache')]
out = Path(out)
out.mkdir(parents=True, exist_ok=True)
(out / 'seen.json').write_text(json.dumps(dict(
    download=download, fighter=fighter, cache=cache, cwd=os.getcwd(), key=os.environ.get('OPENROUTER_API_KEY'),
    pythonpath=os.environ.get('PYTHONPATH'))), encoding='utf-8')
mode = os.environ.get('FAKE_RIGSWAP', 'done')
print(f'loading {Path(download).name}', flush=True)
if mode == 'crash':
    print('Traceback (most recent call last): boom', flush=True)
    sys.exit(3)
if mode == 'hang':
    import time
    time.sleep(120)
result = dict(fighter=fighter, seconds=42.5, cost_usd=0.0123, asks=7)
if mode == 'load':
    result.update(status='failed', failed=dict(stage='load', cause='RuntimeError: nothing to open in '
                                               f'{Path(download).name}: model.smd: SMD is not read'))
else:
    if fighter == 'auto':
        fighter = 'Ganondorf'
        result.update(fighter=fighter, fighter_pick=dict(fighter=fighter, why='his broad build and long cape.',
                                                         picked=True))
    print(f'swapping onto {fighter}', flush=True)
    dat = out / '2-swap' / '4-export' / f'{fighter}.dat'
    dat.parent.mkdir(parents=True, exist_ok=True)
    dat.write_bytes(b'HSD costume stand-in ' * 8)
    result.update(status='done', dat=str(dat.resolve()))
    if mode != 'no-record':
        result.update(record=str(dat.parent.parent / 'record.json'))
    if mode == 'wreck':
        result.update(warning='this probably did not work: the legs are folded under the body')
    (out / 'done.json').write_text(json.dumps(result), encoding='utf-8')
(out / 'result.json').write_text(json.dumps(result), encoding='utf-8')
sys.exit(0 if result['status'] == 'done' else 1)
'''


@pytest.fixture
def studio_root(vault, tmp_path, monkeypatch):
    root = tmp_path / 'imports'
    monkeypatch.setenv(studio_import.ROOT_ENV, str(root))
    return root


@pytest.fixture
def fake_rigswap(tmp_path, monkeypatch):
    """A rigswap home holding only the costume entry point's stand-in, run by this Python. -> the home"""
    home = tmp_path / 'rigswap-home'
    package = home / 'rigswap' / 'plugins' / 'melee'
    package.mkdir(parents=True)
    for folder in (home / 'rigswap', home / 'rigswap' / 'plugins', package):
        (folder / '__init__.py').write_text('', encoding='utf-8')
    (package / 'costume.py').write_text(FAKE_COSTUME, encoding='utf-8')
    (home / 'rigswap' / 'core').mkdir()
    (home / 'rigswap' / 'core' / 'complaint.py').write_text('', encoding='utf-8')     # it can make a change
    monkeypatch.setenv(import_job.PYTHON_ENV, sys.executable)
    monkeypatch.setenv(import_job.HOME_ENV, str(home))
    monkeypatch.delenv(import_job.CACHE_ENV, raising=False)
    monkeypatch.setenv('FAKE_RIGSWAP', 'done')
    monkeypatch.setenv('PYTHONPATH', str(tmp_path / 'app-path'))
    return home


def _zip(path):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('model.obj', 'v 0 0 0\n')
    return path


def _png(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (64, 48), (40, 160, 200)).save(path)
    return path


def _attached_zip(tmp_path):
    with open(_zip(tmp_path / 'neos.zip'), 'rb') as stream:
        return mod_files.register(stream.read(), 'elemental-hero-neos.zip')


def fake_finish(calls):
    """studio.finish.finish's stand-in: records the call, writes a portrait where the real one does."""
    def finish(dat, fighter, name, *, slot=None, out_dir, slippi_fix=False, project=None, source='model_import_v2',
               **kwargs):
        calls.append(dict(dat=Path(dat), fighter=fighter, name=name, slot=slot, slippi_fix=slippi_fix,
                          project=Path(project), source=source))
        csp = _png(Path(out_dir) / 'csp.png')
        return dict(csp=str(csp), stock=None, installable=True, notes=[], install={}, seconds=1.0,
                    vault=dict(character=fighter, skin_id=f'skin-{len(calls)}', name=name, costume_code='PlCaNr',
                               slot=0, project=str(project), slippi_safe=True))
    return finish


def _call(arguments, *, key='turn-key', progress=None, cancelled=None):
    return tools.execute(studio_import.prepare('import_model', arguments), image_key=key, progress=progress,
                         cancelled=cancelled)


def _seen(reply, root):
    return json.loads((root.resolve() / reply['project'] / import_job.OUT / 'seen.json').read_text(encoding='utf-8'))


# ------------------------------------------------------------------ the import_model reply

def test_import_model_runs_rigswap_saves_to_the_vault_and_reports(studio_root, fake_rigswap, tmp_path, monkeypatch):
    calls, cards = [], []
    monkeypatch.setattr(finishing, 'finish', fake_finish(calls))
    source = _attached_zip(tmp_path)
    reply = _call({'source': source['file_id'], 'fighter': 'falcon', 'name': ''}, progress=cards.append)
    assert reply['status'] == 'done', reply
    project = reply['project']
    folder = studio_root.resolve() / project
    assert reply['studio_import'] == {'tool': 'import_model', 'id': project}
    # rigswap's call: its CamelCase fighter (by Pl code), the staged upload, the shared cache, the turn's key
    seen = _seen(reply, studio_root)
    assert seen['fighter'] == 'CaptainFalcon' and Path(seen['download']).name == 'elemental-hero-neos.zip'
    assert Path(seen['cache']) == studio_root.resolve() / import_job.CACHE, 'one cache under the imports root'
    assert Path(seen['cwd']) == fake_rigswap and seen['pythonpath'] is None, "rigswap's own source, not the app's"
    assert seen['key'] == 'turn-key', "rigswap's asks go on the turn's own key"
    # the reply: the done keys, rigswap's cost and time, none of v4's
    assert reply['fighter'] == 'C. Falcon' and reply['costume_name'] == 'Elemental Hero Neos'
    assert reply['cost_usd'] == pytest.approx(0.0123) and reply['seconds'] == 42.5
    assert {'status', 'project', 'fighter', 'costume_name', 'seconds', 'cost_usd', 'dat', 'saved', 'vault_changed',
            'next'} <= set(reply)
    assert not {'choices', 'flow', 'sheet', 'stages', 'fighter_pick', 'failed'} & set(reply)
    assert Path(reply['dat']) == folder / 'rigswap' / '2-swap' / '4-export' / 'CaptainFalcon.dat'
    assert [f['extension'] for f in reply['files']] == ['.png', '.dat'], \
        'its portrait, then the costume file itself (the workbench shows it in 3D), are chat files'
    # the vault save: finish directly, on the app's fighter, once, with its receipt
    assert calls == [dict(dat=Path(reply['dat']), fighter='C. Falcon', name='Elemental Hero Neos', slot=None,
                          slippi_fix=True, project=folder, source='model_import_rigswap')]
    receipt = import_job._read(folder / 'finish' / 'finished.json')
    assert receipt['name'] == 'Elemental Hero Neos' and len(receipt['dat_sha256']) == 64
    assert receipt['result']['vault']['skin_id'] == 'skin-1'
    assert reply['saved']['name'] == 'Elemental Hero Neos' and reply['saved']['character'] == 'C. Falcon'
    assert reply['vault_changed'] is True, 'the app refetches its vault list (AssistantPanel), as after every vault save'
    assert 'test_in_game' in reply['next'] and '"skin-1"' in reply['next'] and 'C. Falcon' in reply['next']
    # progress: every line to job.log, the running card with the newest lines and the fighter; never the key
    assert cards and all(card['status'] == 'running' and card['studio_import']['id'] == project
                         and card['fighter'] == 'C. Falcon' for card in cards)
    assert any('loading elemental-hero-neos.zip' in line for card in cards for line in card['progress'])
    # ...and where the import is, in words (import_job.STEPS: the chip for an import the user's AI runs shows it)
    assert all(card.get('step') in (None, *import_job.STEPS.values()) for card in cards)
    assert cards[-1]['step'] == 'saving it to your vault'
    log = (folder / 'workflow' / import_job.LOG).read_text(encoding='utf-8')
    assert 'swapping onto CaptainFalcon' in log and 'saved as' in log and 'turn-key' not in log
    assert import_job._read(folder / 'workflow' / import_job.JOB)['rigswap'] == 'CaptainFalcon'
    assert import_job.openrouter_key() != 'turn-key', 'only for the job'


def test_no_fighter_named_lets_rigswap_pick_and_the_reply_says_which_and_why(studio_root, fake_rigswap, tmp_path,
                                                                            monkeypatch):
    calls = []
    monkeypatch.setattr(finishing, 'finish', fake_finish(calls))
    reply = _call({'source': _attached_zip(tmp_path)['file_id']})
    assert reply['status'] == 'done', reply
    assert _seen(reply, studio_root)['fighter'] == 'auto', 'no fighter: rigswap picks one'
    assert reply['fighter'] == 'Ganondorf' and calls[0]['fighter'] == 'Ganondorf', "rigswap's pick, as the app names it"
    assert reply['fighter_pick'] == dict(fighter='Ganondorf', why='his broad build and long cape.', picked=True)
    assert ('No fighter was named, so the import picked Ganondorf because: his broad build and long cape. Say'
            in reply['next']) and '"I put him on Ganondorf: ..."' in reply['next'], 'its reason, one full stop'
    assert 'fighter_pick' in compaction.model_view(reply), 'the chat model reads it, to tell the user'
    # No answer from its asks: rigswap's first fighter stands, and the user hears it could not tell.
    unsure = import_job._outcome('neos-2', tmp_path, dict(status='done', fighter='Mario', fighter_pick=dict(
        fighter='Mario', why='', picked=False)), fighter=None, name='Neos', log=lambda *_: None)
    assert unsure['fighter'] == 'Mario' and unsure['fighter_pick']['picked'] is False
    assert 'could not tell which one he fits best, so he is on Mario' in unsure['next']
    assert 'picked Mario because' not in unsure['next']


def test_a_failed_load_says_where_and_why_and_saves_nothing(studio_root, fake_rigswap, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(finishing, 'finish', fake_finish(calls))
    monkeypatch.setenv('FAKE_RIGSWAP', 'load')
    reply = _call({'source': _attached_zip(tmp_path)['file_id'], 'fighter': 'Marth'})
    failed = reply['failed']
    assert reply['status'] == 'failed' and calls == [] and 'costume_name' not in reply and 'saved' not in reply
    assert not (studio_root.resolve() / reply['project'] / 'finish').exists(), 'nothing saved'
    assert reply['studio_import']['id'] == reply['project'] and reply['fighter'] == 'Marth'
    assert failed['stage'] == 'load' and failed['kind'] == 'located' and failed['where'] == 'while loading the model file'
    assert failed['cause'] == 'nothing to open in elemental-hero-neos.zip: model.smd: SMD is not read', \
        "rigswap's words, without its exception type"
    assert 'another format' in failed['can_do'][0] and 'SMD is not read' in failed['can_do'][0]
    assert reply['next'].startswith('Nothing was saved. The import stopped while loading the model file because: '
                                    'nothing to open in elemental-hero-neos.zip')
    assert "do not infer one from the model's name or file name" in reply['next']
    assert reply['diagnostic'].startswith('RuntimeError: nothing to open'), 'the cause as rigswap wrote it'
    assert 'diagnostic' not in compaction.model_view(reply), 'card-only: the chat model never relays it'
    assert reply['cost_usd'] == pytest.approx(0.0123)
    # A failure always carries an error: the tool stage, the receipt and the task outcome read it (F-D-3).
    assert reply['error'] == failed['cause']
    from randall.assistant import turn_facts
    assert turn_facts._receipt_outcome({'result': reply}) == 'partial'


def test_stop_ends_rigswap_and_saves_nothing(studio_root, fake_rigswap, tmp_path, monkeypatch):
    """F-F-1: Stop reaches the import: rigswap is ended at once, not after its 45 minutes."""
    calls, cards = [], []
    monkeypatch.setattr(finishing, 'finish', fake_finish(calls))
    monkeypatch.setenv('FAKE_RIGSWAP', 'hang')
    started = time.monotonic()
    reply = _call({'source': _attached_zip(tmp_path)['file_id'], 'fighter': 'Marth'}, progress=cards.append,
                  cancelled=lambda: bool(cards) or time.monotonic() - started > 3)
    assert time.monotonic() - started < 30, 'ended by the Stop, not by the timeout'
    assert reply['status'] == 'cancelled' and reply['saved'] is None and calls == []
    assert 'error' not in reply, 'a Stop is not a failure'


def test_a_stop_that_lands_after_rigswap_still_saves_nothing(tmp_path):
    reply = import_job._outcome('neos-3', tmp_path, dict(status='done', fighter='Marth', dat=str(tmp_path / 'x.dat')),
                                fighter='Marth', name='Neos', log=lambda *_: None, cancelled=lambda: True)
    assert reply['status'] == 'cancelled' and reply['saved'] is None


def test_a_save_whose_receipt_cannot_be_written_is_still_reported_saved(studio_root, fake_rigswap, tmp_path,
                                                                         monkeypatch):
    """F-F-4: the costume is in the vault before finished.json is written; a failed write must not turn the reply
    into "Nothing was saved"."""
    calls = []
    monkeypatch.setattr(finishing, 'finish', fake_finish(calls))
    real_write = import_job._write

    def write(path, data):
        if Path(path).name == 'finished.json':
            raise PermissionError('denied')
        return real_write(path, data)
    monkeypatch.setattr(import_job, '_write', write)
    reply = _call({'source': _attached_zip(tmp_path)['file_id'], 'fighter': 'Marth'})
    assert reply['status'] == 'done' and len(calls) == 1
    assert reply['saved']['skin_id'] == 'skin-1' and reply['vault_changed'] is True


def test_rigswap_that_ends_without_a_result_is_an_internal_error(studio_root, fake_rigswap, tmp_path, monkeypatch):
    monkeypatch.setattr(finishing, 'finish', lambda *a, **k: pytest.fail('saved'))
    monkeypatch.setenv('FAKE_RIGSWAP', 'crash')
    reply = _call({'source': _attached_zip(tmp_path)['file_id'], 'fighter': 'Fox'})
    assert reply['status'] == 'failed' and reply['failed']['stage'] is None
    assert reply['failed']['kind'] == 'unexpected' and reply['failed']['cause'] == 'an internal error in the importer'
    assert 'something went wrong on your side' in reply['next']
    assert 'exited 3 without result.json' in reply['diagnostic'] and 'boom' in reply['diagnostic']


@pytest.mark.parametrize('failed, fighter, kind, where, can_do', [
    (dict(stage='swap', cause='Failed: no two legs on either side of the mirror plane'), 'Marth', 'located',
     'while putting the model on Marth', 'import it onto another fighter'),
    (dict(stage='swap', cause="KeyError: 'head'"), None, 'unexpected', 'while putting the model on the fighter',
     'report it'),
    (dict(stage='load', cause='RuntimeError: '), None, 'unexpected', 'while loading the model file', 'report it'),
    (dict(stage='pick', cause='RuntimeError: no answer from the fighter asks'), None, 'located',
     'while picking the fighter it fits best', 'import it again naming the fighter to put it on'),
    ({}, 'Fox', 'unexpected', None, 'report it'),
])
def test_a_failure_is_said_in_rigswaps_own_words_or_as_an_internal_error(failed, fighter, kind, where, can_do):
    said = import_job.failed_reply(failed, fighter)
    assert (said['kind'], said['where'], said['can_do'][0]) == (kind, where, can_do)
    if kind == 'located':
        assert said['cause'] == failed['cause'].partition(': ')[2], "rigswap's words, without its exception type"
        assert said['stage'] != 'swap' or 'another model of the character' in said['can_do'][1]
    else:
        assert said['cause'] == 'an internal error in the importer', 'never a bare exception'


def test_rigswap_not_set_up_is_a_failed_reply_before_anything_runs(studio_root, fake_rigswap, tmp_path, monkeypatch):
    monkeypatch.setenv(import_job.PYTHON_ENV, str(tmp_path / 'nowhere' / 'python.exe'))
    reply = _call({'source': _attached_zip(tmp_path)['file_id'], 'fighter': 'Fox'})
    assert reply['status'] == 'failed' and reply['error'] == import_job.NOT_SET_UP
    assert reply['failed']['cause'] == import_job.NOT_SET_UP and reply['failed']['can_do'] == ['report it']
    assert reply['failed']['kind'] == 'located' and f'because: {import_job.NOT_SET_UP}' in reply['next']
    assert 'cannot tell whether' not in reply['next'], 'a known cause is not said as an unknown one'
    assert reply['diagnostic'].startswith('RIGSWAP_PYTHON names no Python')
    assert reply['studio_import'] == {'tool': 'import_model', 'id': None}
    assert [p.name for p in studio_root.iterdir()] == ['.uploads'], 'no project made'
    monkeypatch.setenv(import_job.PYTHON_ENV, sys.executable)
    monkeypatch.setenv(import_job.HOME_ENV, str(tmp_path))
    assert import_job.setup().startswith('RIGSWAP_HOME holds no rigswap.plugins.melee.costume')


def _packaged(monkeypatch, tmp_path):
    """A packaged app: the installer's resources under tmp_path, no rigswap setting in the environment."""
    import core.config
    for name in (import_job.PYTHON_ENV, import_job.HOME_ENV, import_job.TARGETS_ENV, 'RIGSWAP_HSDRAW',
                 import_job.BLENDER_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(core.config, 'RESOURCES_DIR', tmp_path / 'resources')
    monkeypatch.setenv(studio_import.ROOT_ENV, str(tmp_path / 'imports'))
    return core.config


def test_a_packaged_app_runs_the_installers_rigswap_on_the_downloaded_tools(tmp_path, monkeypatch):
    """rigswap's package ships compiled in the installer (utility/rigswap/app); its Python and Blender 4 are the
    tools the user downloaded (model_import/tools/service.installed), never the developer's."""
    from randall.model_import.tools import service
    config = _packaged(monkeypatch, tmp_path)
    tools_dir = tmp_path / 'data' / 'tools' / 'model-import'
    python = tools_dir / 'runtime' / ('python.exe' if os.name == 'nt' else 'bin/python3')
    blender = tools_dir / 'blender' / ('blender.exe' if os.name == 'nt' else 'blender')
    monkeypatch.setattr(service, 'need', lambda: None)
    monkeypatch.setattr(service, 'installed', lambda: {'python': python, 'blender': blender})
    assert import_job.setup() == f'RIGSWAP_PYTHON names no Python: {python}'
    python.parent.mkdir(parents=True)
    python.write_bytes(b'')
    app = tmp_path / 'resources' / 'utility' / 'rigswap' / 'app'
    assert import_job.setup() == f'RIGSWAP_HOME holds no rigswap.plugins.melee.costume: {app}'
    entry = app / 'rigswap' / 'plugins' / 'melee' / 'costume.pyc'
    entry.parent.mkdir(parents=True)
    entry.write_bytes(b'')
    assert import_job.setup() == (python, app), 'its entry point ships compiled'
    env = import_job._environment(None, tmp_path / 'vanilla')
    assert env[import_job.FILES_ENV] == str(tmp_path / 'vanilla')
    assert env[import_job.TARGETS_ENV] == str(tmp_path / 'imports' / import_job.TARGETS)
    assert env['RIGSWAP_HSDRAW'] == str(config.HSDRAW_EXE)
    assert env[import_job.BLENDER_ENV] == str(blender), 'the downloaded Blender 4'
    monkeypatch.setattr(service, 'installed', lambda: None)
    assert import_job.BLENDER_ENV not in import_job._environment(None), 'no tools: none is named'


NEED = {'state': 'not_installed', 'download_bytes': 779_000_000, 'needed_bytes': 779_000_000,
        'disk_bytes': 2_200_000_000, 'pieces': ['not for the reply'],
        'sources': ['download.blender.org', 'python.org', 'PyPI (files.pythonhosted.org)']}


def test_a_packaged_app_without_its_tools_says_so_and_starts_nothing(studio_root, fake_rigswap, tmp_path,
                                                                     monkeypatch):
    from randall.model_import.tools import service
    _packaged(monkeypatch, tmp_path)
    monkeypatch.setenv(studio_import.ROOT_ENV, str(studio_root))
    monkeypatch.setattr(service, 'need', lambda: dict(NEED))
    assert import_job.setup() == import_job.TOOLS_MISSING
    reply = _call({'source': _attached_zip(tmp_path)['file_id'], 'fighter': 'Fox'})
    assert reply['status'] == 'needs_tools', reply
    assert reply['tools'] == {k: NEED[k] for k in ('state', 'download_bytes', 'needed_bytes', 'disk_bytes')}
    assert reply['warning'].startswith('Model import needs its tools')
    assert 'about 779 MB' in reply['next'] and 'Download button' in reply['next']
    assert 'Do not call import_model again this turn' in reply['next']
    made = [p.name for p in studio_root.iterdir()] if studio_root.exists() else []
    assert made in ([], ['.uploads']), 'no project made'
    over_mcp = import_job.tools_reply(dict(NEED, state='update_needed'), mcp=True)
    assert over_mcp['warning'].startswith('Model import needs an update of its tools')
    assert 'Settings > AI > Model import tools' in over_mcp['next']
    assert 'Download button' not in over_mcp['next'] and 'Do not try to download them yourself' in over_mcp['next']
    assert import_job.tools_words({'state': 'downloading'}) == import_job.TOOLS_DOWNLOADING
    assert import_job.tools_words({'state': 'unsupported'}) == import_job.TOOLS_UNSUPPORTED


def test_the_tools_words_name_this_platforms_sources():
    """0.9.0 build 3 smoke: the words said "blender.org, python.org and PyPI" on macOS and Linux too, where the
    Python is python-build-standalone's. They name the sources the Settings card names (service.need's sources,
    from the manifest and service.SOURCES)."""
    windows = import_job.tools_reply(dict(NEED))
    assert ('about 779 MB, a one-time download from download.blender.org, python.org and PyPI '
            '(files.pythonhosted.org)') in windows['next']
    mac = dict(NEED, sources=['download.blender.org', 'python-build-standalone (GitHub)',
                              'PyPI (files.pythonhosted.org)'])
    for reply in (import_job.tools_reply(mac), import_job.tools_reply(mac, mcp=True)):
        assert ('a one-time download from download.blender.org, python-build-standalone (GitHub) and PyPI '
                '(files.pythonhosted.org)') in reply['next']
        assert 'python.org' not in reply['next']
    assert 'press Download (about 779 MB, a one-time download), then' in \
        import_job.tools_reply(dict(NEED, sources=[]), mcp=True)['next']


def test_tools_are_only_asked_of_a_packaged_app_without_its_own_setting(tmp_path, monkeypatch):
    from randall.model_import.tools import service
    monkeypatch.setattr(service, 'need', lambda: dict(NEED))
    monkeypatch.setattr(sys, 'frozen', False, raising=False)
    assert import_job.tools_needed() is None, 'a checkout runs DEV_ENV'
    _packaged(monkeypatch, tmp_path)
    assert import_job.tools_needed()['state'] == 'not_installed'
    monkeypatch.setenv(import_job.PYTHON_ENV, sys.executable)
    assert import_job.tools_needed(), 'a Python alone does not stand in for Blender'
    monkeypatch.setenv(import_job.BLENDER_ENV, str(tmp_path / 'blender'))
    assert import_job.tools_needed() is None, 'both named in the environment stand in for the tools'

    def broken():
        raise OSError('status failed')
    monkeypatch.delenv(import_job.BLENDER_ENV)
    monkeypatch.setattr(service, 'need', broken)
    assert import_job.tools_needed() is None, 'a broken status never hides the real cause'


class _Process:
    """subprocess.Popen's stand-in for _stop: alive until told it ended."""
    pid = 4242

    def __init__(self, ends_on_term=True):
        self.ends_on_term, self.ended, self.waited, self.killed = ends_on_term, False, [], False

    def poll(self):
        return 0 if self.ended else None

    def wait(self, timeout=None):
        self.waited.append(timeout)
        if not self.ended:
            raise import_job.subprocess.TimeoutExpired('rigswap', timeout)
        return 0

    def kill(self):
        self.killed = True


def test_a_stop_on_macos_and_linux_ends_rigswaps_whole_process_group(monkeypatch):
    """rigswap starts Blender 4 and the headless viewer: killing rigswap alone left them running on POSIX. It now
    leads a session of its own; a stop sends its group SIGTERM, then SIGKILL after STOP_GRACE."""
    import signal
    monkeypatch.setattr(import_job.os, 'name', 'posix')
    assert import_job._own_group() == {'start_new_session': True}
    sent = []
    process = _Process()

    def killpg(pid, sig):
        sent.append((pid, sig))
        if sig == signal.SIGTERM and process.ends_on_term:
            process.ended = True
    monkeypatch.setattr(import_job.os, 'killpg', killpg, raising=False)
    why = []
    import_job._stop(process, why)
    sigkill = getattr(signal, 'SIGKILL', 9)
    assert why == ['stopped'] and sent == [(4242, signal.SIGTERM), (4242, sigkill)]
    assert process.waited == [import_job.STOP_GRACE] and not process.killed
    sent.clear()
    process = _Process(ends_on_term=False)
    import_job._stop(process, [])
    assert sent == [(4242, signal.SIGTERM), (4242, sigkill)], 'what ignores SIGTERM is killed after the grace'
    sent.clear()
    process.ended = True
    import_job._stop(process, [])
    assert sent == [], 'nothing is sent to a rigswap that already ended'

    def gone(pid, sig):
        raise ProcessLookupError
    monkeypatch.setattr(import_job.os, 'killpg', gone, raising=False)
    process = _Process()
    import_job._stop(process, [])
    assert process.waited == [] and not process.killed

    def not_ours(pid, sig):
        raise PermissionError
    monkeypatch.setattr(import_job.os, 'killpg', not_ours, raising=False)
    process = _Process()
    import_job._stop(process, [])
    assert process.killed, 'no group of its own: rigswap alone, by its PID'


def test_windows_keeps_stopping_rigswaps_tree_by_pid(monkeypatch):
    import core.config
    monkeypatch.setattr(import_job.os, 'name', 'nt')
    assert import_job._own_group() == {}
    ran = []
    monkeypatch.setattr(import_job.subprocess, 'run', lambda command, **kw: ran.append(command))
    monkeypatch.setattr(core.config, 'get_subprocess_args', lambda: {})
    import_job._stop(_Process(), [])
    assert ran == [['taskkill', '/PID', '4242', '/T', '/F']]


@pytest.mark.skipif(os.name == 'nt', reason='process groups are POSIX')
def test_a_real_stop_on_posix_ends_the_child_rigswap_started(tmp_path):
    import subprocess
    pid_file = tmp_path / 'child.pid'
    script = ('import subprocess, sys, time\n'
              'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])\n'
              f'open({str(pid_file)!r}, "w").write(str(child.pid))\n'
              'time.sleep(120)\n')
    process = subprocess.Popen([sys.executable, '-c', script], **import_job._own_group())
    deadline = time.monotonic() + 20
    while not pid_file.exists() or not pid_file.read_text():
        assert time.monotonic() < deadline, 'the child never started'
        time.sleep(0.05)
    child = int(pid_file.read_text())
    import_job._stop(process, [])
    process.wait(10)
    deadline = time.monotonic() + 10
    while True:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        assert time.monotonic() < deadline, 'the child outlived the stop'
        time.sleep(0.05)


def test_a_packaged_app_takes_the_vanilla_files_from_the_users_disc(monkeypatch, tmp_path):
    from shared.vanilla_extract import vanilla_refs
    asked = []

    def ensure(name):
        asked.append(name)
        return tmp_path / name
    monkeypatch.setattr(vanilla_refs, 'ensure_vanilla_ref', ensure)
    assert import_job.vanilla_files() == tmp_path
    assert set(asked) == set(import_job.VANILLA) and {'PlFxNr.dat', 'PlFx.dat', 'PlFxAJ.dat', 'PlCo.dat'} <= set(asked)
    monkeypatch.setattr(vanilla_refs, 'ensure_vanilla_ref', lambda name: None)
    monkeypatch.setattr(vanilla_refs, 'known_vanilla_iso', lambda: None)
    assert import_job.vanilla_files() == import_job.NO_DISC
    monkeypatch.setattr(vanilla_refs, 'known_vanilla_iso', lambda: tmp_path / 'melee.iso')
    assert import_job.vanilla_files().startswith(f'{len(import_job.VANILLA)} of the fighter files could not be read')


def test_no_disc_is_said_as_the_cause_before_anything_runs(studio_root, fake_rigswap, tmp_path, monkeypatch):
    monkeypatch.setenv(import_job.FILES_ENV, '')
    monkeypatch.setattr(import_job, 'DEV_ENV', {k: v for k, v in import_job.DEV_ENV.items() if k != import_job.FILES_ENV})
    monkeypatch.setattr(import_job, 'vanilla_files', lambda: import_job.NO_DISC)
    reply = _call({'source': _attached_zip(tmp_path)['file_id'], 'fighter': 'Fox'})
    assert reply['status'] == 'failed' and reply['failed']['kind'] == 'located'
    assert f'because: {import_job.NO_DISC}' in reply['next'] and 'vanilla Melee disc in Settings' in reply['next']
    assert [p.name for p in studio_root.iterdir()] == ['.uploads'], 'no project made'


def test_a_save_that_is_refused_is_said_and_the_import_is_still_done(studio_root, fake_rigswap, tmp_path, monkeypatch):
    def refused(*args, **kwargs):
        raise finishing.NotSupportedYet('Ice Climbers costumes are a Popo/Nana pair')
    monkeypatch.setattr(finishing, 'finish', refused)
    reply = _call({'source': _attached_zip(tmp_path)['file_id'], 'fighter': 'Fox'})
    assert reply['status'] == 'done' and reply['saved'] is None and 'vault_changed' not in reply
    assert reply['not_saved'].startswith('Ice Climbers') and 'test_in_game' not in reply['next']


def test_the_vault_save_keeps_a_receipt_and_a_retry_adds_no_second_copy(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(finishing, 'finish', fake_finish(calls))
    folder = tmp_path / 'neos-1a2b3c'
    dat = folder / 'rigswap' / 'Fox.dat'
    dat.parent.mkdir(parents=True)
    dat.write_bytes(b'costume' * 8)
    first = import_job._save(folder, dat, 'Fox', 'Neos')
    again = import_job._save(folder, dat, 'Fox', 'Neos')
    assert len(calls) == 1 and 'already saved' in again['note'] and again['vault'] == first['vault']
    import_job._save(folder, dat, 'Fox', 'Neos 2')
    assert len(calls) == 2, 'another name is another costume'
    with pytest.raises(finishing.FinishError, match='no costume file'):
        import_job._save(folder, folder / 'missing.dat', 'Fox', 'Neos')
    with pytest.raises(finishing.FinishError, match='which fighter'):
        import_job._save(folder, dat, None, 'Neos')


def test_fighters_map_to_rigswaps_by_pl_code():
    from shared.modellab.fighter_catalog import _CHAR_TO_CODE
    assert import_job.fighter_of('C. Falcon') == ('C. Falcon', 'CaptainFalcon')
    assert import_job.fighter_of('captain falcon') == ('C. Falcon', 'CaptainFalcon')
    assert import_job.fighter_of('CaptainFalcon') == ('C. Falcon', 'CaptainFalcon'), "rigswap's own name too"
    assert import_job.fighter_of('DK') == ('DK', 'DonkeyKong')
    assert import_job.fighter_of('GameAndWatch') == ('Mr. Game & Watch', 'GameAndWatch')
    assert import_job.fighter_of('young link') == ('Young Link', 'YoungLink')
    assert import_job.app_fighter('DrMario') == 'Dr. Mario' and import_job.app_fighter('auto') is None
    assert import_job.fighters() == [n for n in _CHAR_TO_CODE if n != 'Ice Climbers'] and len(import_job.fighters()) == 25
    assert all(import_job.app_fighter(import_job.fighter_of(n)[1]) == n for n in import_job.fighters())
    with pytest.raises(ValueError, match='cannot go on Ice Climbers') as refused:
        import_job.fighter_of('popo')
    assert 'Marth' in str(refused.value) and 'leave fighter unset' in str(refused.value)
    with pytest.raises(ValueError, match="'Waluigi' is not a fighter"):
        import_job.fighter_of('Waluigi')


def test_the_fighter_table_matches_the_viewers_prefixes():
    from shared.modellab.fighter_catalog import _CHAR_TO_CODE
    from core.viewer_tools import VIEWER_CHAR_PREFIXES
    for char, code in _CHAR_TO_CODE.items():
        assert VIEWER_CHAR_PREFIXES['G&W' if char == 'Mr. Game & Watch' else char] == 'Pl' + code


@pytest.mark.parametrize('arguments, words', [
    ({}, 'import_model takes source'),
    ({'source': 'a' * 32, 'fighter': 'Ice Climbers'}, 'cannot go on Ice Climbers'),
    ({'source': 'a' * 32, 'fighter': 'Waluigi'}, 'is not a fighter an imported model can go on'),
    ({'project': 'neos-1'}, 'takes both project'),
    ({'change': 'the legs look wrong'}, 'takes both project'),
    ({'project': 'neos-1', 'change': 'the legs look wrong'}, "There is no import 'neos-1' here"),
    ({'project': '../neos', 'change': 'the legs look wrong'}, 'project must be a short import id'),
    ({'resume': 'neos-1', 'answer': 'B pose'}, "'resume' is not a parameter"),
])
def test_prepare_names_what_is_wrong_with_an_import_call(studio_root, arguments, words):
    with pytest.raises(ValueError, match=words):
        studio_import.prepare('import_model', arguments)


def test_the_schema_leaves_the_fighter_to_the_user_or_the_import():
    parameters = import_job.SCHEMA['function']['parameters']
    assert parameters['required'] == [], 'a new import takes source, a change project and change (check)'
    assert set(parameters['properties']) == {'source', 'fighter', 'name', 'project', 'change', 'untextured'}
    assert 'leave it unset unless the user named one' in parameters['properties']['fighter']['description']
    assert 'a few minutes' in import_job.SCHEMA['function']['description']
    assert 'looks is wrong' in import_job.SCHEMA['function']['description'], 'what a change is for'


def test_the_source_is_an_attachment_never_a_path(studio_root, fake_rigswap, monkeypatch):
    monkeypatch.setattr(import_job, 'rigswap', lambda *a, **k: pytest.fail('ran'))
    reply = _call({'source': 'C:/Windows/win.ini'})
    assert 'file ID of the attached model' in reply['error']


# ------------------------------------------------------------------ a change to a finished import

def _imported(tmp_path, monkeypatch, calls):
    monkeypatch.setattr(finishing, 'finish', fake_finish(calls))
    reply = _call({'source': _attached_zip(tmp_path)['file_id'], 'fighter': 'falcon'})
    assert reply['status'] == 'done', reply
    return reply


def test_what_looks_wrong_is_changed_and_saved_as_a_second_costume(studio_root, fake_rigswap, tmp_path, monkeypatch):
    calls, cards = [], []
    first = _imported(tmp_path, monkeypatch, calls)
    project = first['project']
    folder = studio_root.resolve() / project
    assert f'project "{project}" and change set to their words' in first['next'], 'the first reply says how'
    # a fighter the panel picked, or one the model adds, is not part of a change: it stays on its own
    prepared = studio_import.prepare('import_model', {'project': project, 'change': '  his head is\n too big ',
                                                      'fighter': 'Marth'}, fighter='Fox')
    assert json.loads(prepared.arguments) == {'project': project, 'change': 'his head is too big'}
    reply = tools.execute(prepared, image_key='turn-key', progress=cards.append)
    assert reply['status'] == 'done' and reply['project'] == project and reply['fighter'] == 'C. Falcon', reply
    assert reply['studio_import'] == {'tool': 'import_model', 'id': project}
    fixed = import_job._read(folder / 'rigswap' / 'fixed.json')
    assert fixed['words'] == 'his head is too big', "the user's words, as one argument"
    assert fixed['heard'] is None, 'a call made with no chat behind it: its words are the complaint'
    assert Path(fixed['cache']) == studio_root.resolve() / import_job.CACHE
    # a second costume: its own name, receipt and portrait; the first is untouched
    assert [c['name'] for c in calls] == ['Elemental Hero Neos', 'Elemental Hero Neos 2']
    assert calls[1]['dat'] == folder / 'rigswap' / '2-swap-fix1' / '4-export' / 'CaptainFalcon.dat'
    assert calls[1]['fighter'] == 'C. Falcon' and calls[1]['project'] == folder
    assert import_job._read(folder / 'finish' / 'finished.json')['name'] == 'Elemental Hero Neos'
    assert import_job._read(folder / 'finish-2' / 'finished.json')['name'] == 'Elemental Hero Neos 2'
    assert reply['saved']['name'] == 'Elemental Hero Neos 2' and reply['vault_changed'] is True
    assert [f['extension'] for f in reply['files']] == ['.png', '.dat']
    # the reply: what changed and why, said as a change and never as fixed
    assert reply['changed'] == 'head: 1.0 -> 0.8' and reply['why'] == 'the head is too big for the body.'
    assert 'one thing changed (head: 1.0 -> 0.8), because: the head is too big for the body.' in reply['next']
    assert 'Never say it is fixed' in reply['next'] and 'the first is still in their vault' in reply['next']
    assert {'changed', 'why', 'next', 'project'} <= set(compaction.model_view(reply)), 'the chat model reads them'
    assert any('looking at what was said' in line for card in cards for line in card['progress'])
    job = import_job._read(folder / 'workflow' / import_job.JOB)
    assert job['changes'] == [dict(words='his head is too big', name='Elemental Hero Neos 2', status='done',
                                   saved=True, changed='head: 1.0 -> 0.8')]
    # another change starts from the changed costume and is the third
    again = _call({'project': project, 'change': 'the legs look wrong'})
    assert again['saved']['name'] == 'Elemental Hero Neos 3'
    assert calls[2]['dat'] == folder / 'rigswap' / '2-swap-fix2' / '4-export' / 'CaptainFalcon.dat'


def test_the_users_own_message_is_the_complaint_and_the_models_wording_goes_beside_it(studio_root, fake_rigswap,
                                                                                      tmp_path, monkeypatch):
    """2026-11-09: "it's still too big" went on as "make it much smaller, around 0.6", and the head came out at 0.6.
    The complaint the import reads is the user's newest message, word for word; what the chat model made of it goes
    beside it, for which part is meant."""
    calls = []
    first = _imported(tmp_path, monkeypatch, calls)
    project = first['project']
    folder = studio_root.resolve() / project
    words = ['Import this model.', "It's   still\ntoo big."]
    made_up = 'make the head much smaller, around 0.6'
    prepared = studio_import.prepare('import_model', {'project': project, 'change': made_up}, words=words)
    assert json.loads(prepared.arguments) == {'project': project, 'change': made_up, 'said': "It's still too big."}
    reply = tools.execute(prepared, image_key='turn-key')
    assert reply['status'] == 'done', reply
    fixed = import_job._read(folder / 'rigswap' / 'fixed.json')
    assert fixed['words'] == "It's still too big." and fixed['heard'] == made_up
    change = import_job._read(folder / 'workflow' / import_job.JOB)['changes'][0]
    assert change['words'] == "It's still too big." and change['heard'] == made_up
    assert "It's still too big." in (folder / 'workflow' / import_job.LOG).read_text(encoding='utf-8')
    # said is the app's to fill, never the chat model's
    with pytest.raises(ValueError, match="'said' is not a parameter"):
        studio_import.prepare('import_model', {'project': project, 'change': 'x', 'said': 'make it tiny'}, words=words)
    # the chat model passing the user's words as they are: one complaint, nothing beside it
    same = studio_import.prepare('import_model', {'project': project, 'change': "it's still too big."}, words=words)
    tools.execute(same, image_key='turn-key')
    fixed = import_job._read(folder / 'rigswap' / 'fixed.json')
    assert fixed['words'] == "It's still too big." and fixed['heard'] is None


def test_a_change_the_import_cannot_make_says_so_and_keeps_the_costume(studio_root, fake_rigswap, tmp_path,
                                                                        monkeypatch):
    calls = []
    first = _imported(tmp_path, monkeypatch, calls)
    folder = studio_root.resolve() / first['project']
    reply = _call({'project': first['project'], 'change': 'the texture on his face is blurry'})
    assert reply['status'] == 'failed' and len(calls) == 1, 'nothing new is saved'
    failed = reply['failed']
    assert failed['stage'] == 'fix' and failed['kind'] == 'located' and failed['where'] == \
        'while working out what to change'
    assert failed['cause'] == 'the texture is wrong, not the body', "the look's own words, its type cut off"
    assert reply['next'].startswith('The change was not made and nothing new was saved; the costume from before is '
                                    'still in their vault. The import stopped while working out what to change')
    assert 'Nothing was saved' not in reply['next']
    assert import_job._read(folder / 'workflow' / import_job.JOB)['changes'][0]['saved'] is False
    # the costume it started from still stands: the next change is made, and is the second costume
    again = _call({'project': first['project'], 'change': 'his head is too big'})
    assert again['status'] == 'done' and again['saved']['name'] == 'Elemental Hero Neos 2'


def test_an_import_or_an_importer_that_cannot_be_changed_says_to_import_it_again(studio_root, fake_rigswap, tmp_path,
                                                                                  monkeypatch):
    calls = []
    monkeypatch.setenv('FAKE_RIGSWAP', 'no-record')         # made by a rigswap that kept no record
    first = _imported(tmp_path, monkeypatch, calls)
    reply = _call({'project': first['project'], 'change': 'the legs look wrong'})
    assert reply['status'] == 'failed' and reply['error'] == import_job.NOT_CHANGEABLE and len(calls) == 1
    assert reply['failed']['can_do'][0] == 'import the model again, then say what looks wrong'
    assert reply['studio_import']['id'] == first['project']
    # a rigswap with no change code (an installer's older one): said before anything runs
    (fake_rigswap / 'rigswap' / 'core' / 'complaint.py').unlink()
    monkeypatch.setattr(import_job, 'rigswap', lambda *a, **k: pytest.fail('ran'))
    reply = _call({'project': first['project'], 'change': 'the legs look wrong'})
    assert reply['error'] == import_job.NO_CHANGES and 'complaint' in reply['diagnostic']


def test_a_costume_the_imports_own_check_calls_a_wreck_is_said_as_one(studio_root, fake_rigswap, tmp_path,
                                                                       monkeypatch):
    monkeypatch.setenv('FAKE_RIGSWAP', 'wreck')
    reply = _imported(tmp_path, monkeypatch, [])
    assert reply['saved'] and reply['warning'] == 'this probably did not work: the legs are folded under the body'
    # 0.9.0 smoke: "this probably did not work: Small parts float apart..." reached the user as "small parts may
    # float apart". The verdict goes to the model whole, quoted, with the order not to soften it, and it comes right
    # after the one fact the reply opens with, before anything else the reply is told.
    said = reply['next']
    assert ('''the import's own check of the finished costume says: "this probably did not work: the legs are '''
            '''folded under the body" Add one sentence that passes this on word for word''') in said
    assert 'never soften it ("may", "might"' in said and 'never call the costume done or fine' in said
    assert said.index('folded under the body') < said.index('The picture is its portrait')
    assert 'no caveats or guesses of your own' in said
    assert 'warning' in compaction.model_view(reply)
    fine = import_job._outcome('neos-2', tmp_path, dict(status='done', fighter='Mario'), fighter=None, name='Neos',
                               log=lambda *_: None)
    assert 'warning' not in fine and "import's own check" not in fine['next']
    changed = import_job._outcome('neos-2', tmp_path, dict(status='done', fighter='Mario', changed={'head': [1, .8]},
                                                           warning='this probably did not work: in pieces.'),
                                  fighter=None, name='Neos', log=lambda *_: None)
    assert '"this probably did not work: in pieces." Add one sentence' in changed['next']


def test_a_model_without_the_textures_it_names_is_asked_about_before_anything_runs(studio_root, fake_rigswap,
                                                                                    tmp_path, monkeypatch):
    """0.9.0 smoke: a bare Clank.obj came without its Clank.mtl and was saved all white without a word."""
    calls = []
    monkeypatch.setattr(finishing, 'finish', fake_finish(calls))
    clank = mod_files.register(b'mtllib Clank.mtl\r\nv 0 0 0\r\n', 'Clank.obj')
    reply = _call({'source': clank['file_id']})
    assert reply['status'] == 'needs_textures' and reply['textures'] == ['Clank.mtl']
    # 0.9.0 smoke: Randall called the missing Clank.mtl "a texture file". It is the model's materials file.
    assert reply['warning'] == ('Clank.obj came without the materials file Clank.mtl. Without it the model would '
                                'import with no textures (all white).')
    assert reply['next'].startswith('Nothing was imported yet. ' + reply['warning'])
    assert 'naming each missing file as the warning does (a materials file is not a texture)' in reply['next']
    assert 'attach a ZIP' in reply['next'] and 'untextured true' in reply['next']
    assert reply['studio_import'] == {'tool': 'import_model', 'id': None}, 'no project: the file is still waiting'
    assert [p.name for p in studio_root.iterdir()] == ['.uploads'] and not calls, 'rigswap never ran'
    receipts = [dict(name='import_model', arguments={'source': clank['file_id']}, result=reply)]
    attached = [dict(clank, extension='.obj')]
    assert attached_model_waiting('nah just go ahead without them', attached, receipts)['file_id'] == clank['file_id']
    assert attached_model_waiting('yes', attached, receipts) is not None, 'any answer is an answer to it'
    assert attached_model_waiting('yes', attached, []) is None
    # the user said to go on without them: the same source with untextured runs the import
    reply = _call({'source': clank['file_id'], 'untextured': True})
    assert reply['status'] == 'done' and reply['saved'] and 'warning' not in reply
    assert len(calls) == 1
    assert 'untextured' not in import_job.check({'source': clank['file_id'], 'untextured': False})
    assert import_job.check({'source': clank['file_id'], 'untextured': 'true'})['untextured'] is True
    over_mcp = import_job.textures_reply(dict(model='Clank.obj', missing=['Clank.mtl'], source='Clank.obj'), mcp=True)
    assert 'put those files beside the model' in over_mcp['next'] and 'attach' not in over_mcp['next']


# ------------------------------------------------------------------ routing

def _provider(seen, plan=()):
    plan = list(plan)

    def provider(messages, schemas, key, cancelled):
        seen.append(dict(names=[s['function']['name'] for s in schemas],
                         system=[m['content'] for m in messages if m['role'] == 'system']))
        if plan:
            name, arguments = plan.pop(0)
            yield {'type': 'completion', 'message': {'role': 'assistant', 'content': None, 'tool_calls': [
                {'id': f'c{len(seen)}', 'function': {'name': name, 'arguments': json.dumps(arguments)}}]}}
        else:
            yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Okay.'}}
    return provider


IMPORT_ROSTER = {'import_model'} | set(studio_import.IMPORT_APP_TOOLS)


def test_an_import_turn_is_offered_import_model_alone_with_its_card(studio_root, monkeypatch):
    seen = []
    monkeypatch.setattr(engine, '_provider', _provider(seen))
    # The words alone, in an ordinary chat, are an ordinary turn: no import_model.
    plain = engine.start(None, 'import this model onto Pikachu', {}, request_key='k')
    list(live_runs.stream(plain))
    assert 'import_model' not in seen[0]['names'] and 'search_vault' in seen[0]['names']
    assert 'model_import_mode' not in store.get(plain.chat_id)['messages'][-1]['routing']
    seen.clear()
    # A chat started as "Import a model" is an import turn.
    run = engine.start(None, 'import this model onto Pikachu', {'task': 'model_import'}, request_key='k')
    list(live_runs.stream(run))
    assert set(seen[0]['names']) == IMPORT_ROSTER
    card = next(text for text in seen[0]['system'] if 'TASK RECIPE -- IMPORT A MODEL' in text)
    assert 'AN UNFINISHED IMPORT' not in card, 'no carrying on'
    assert 'import_model again with the same source and that fighter' in card, 'another fighter is a new import'
    assert "with project = the import's project (from its reply) and change = what the user said" in card
    saved = store.get(run.chat_id)['messages'][-1]
    assert saved['routing']['model_import_mode'] == 'import'
    assert saved['recipes'][0]['model_import_mode'] == 'import'


def test_the_import_then_a_turn_about_it_is_a_normal_turn(studio_root, fake_rigswap, tmp_path, monkeypatch):
    """"The knee caps stick out" after an import gets Randall's normal roster and no import card; import_model is
    offered for another fighter or a change to the import (its description says when)."""
    monkeypatch.setattr(finishing, 'finish', fake_finish([]))
    source = _attached_zip(tmp_path)
    seen = []
    monkeypatch.setattr(engine, '_provider', _provider(seen, [('import_model', {'source': source['file_id'],
                                                                                 'fighter': 'C. Falcon'})]))
    run = engine.start(None, 'Import this model onto C. Falcon.', {'files': [source]}, request_key='k')
    list(live_runs.stream(run))
    answer = store.get(run.chat_id)['messages'][-1]
    assert [t['name'] for t in answer['tools']] == ['import_model'] and answer['tools'][0]['status'] == 'done'
    assert answer['tools'][0]['result']['files'], 'the portrait reached the chat'
    assert set(seen[0]['names']) == IMPORT_ROSTER
    folder = studio_root.resolve() / answer['tools'][0]['result']['project']
    assert json.loads((folder / 'randall.jsonl').read_text().splitlines()[-1])['tools'] == {'import_model': 1}, \
        'the ledger row, with no studio project.json'
    asked = len(seen)
    list(live_runs.stream(engine.start(run.chat_id, 'the knee caps stick out, make them follow the knee', {},
                                       request_key='k')))
    turn = seen[asked]
    assert 'search_vault' in turn['names'] and 'import_model' in turn['names'], \
        "the app's whole roster, and import_model for another fighter or a change"
    assert not any('TASK RECIPE -- IMPORT A MODEL' in text for text in turn['system'])
    normal = store.get(run.chat_id)['messages'][-1]
    assert 'model_import_mode' not in normal['routing']
    # Another task's words get the app's roster too; a new model attached is a new import.
    list(live_runs.stream(engine.start(run.chat_id, 'search the website for a Marth costume', {}, request_key='k')))
    assert 'search_vault' in seen[-1]['names'] and 'website_search' not in IMPORT_ROSTER
    other = mod_files.register(_zip(tmp_path / 'b.zip').read_bytes(), 'goomba.zip')
    list(live_runs.stream(engine.start(run.chat_id, 'import this', {'files': [other]}, request_key='k')))
    assert set(seen[-1]['names']) == IMPORT_ROSTER


@pytest.mark.parametrize('family, text, receipts, mode', [
    ('model_import', 'import this model onto Fox', [], 'import'),
    (None, 'hello', [], None),
    (None, 'the knee caps stick out', 'done', None),
    ('model_import', 'lets do another model import', 'done', 'import'),
    ('verify_in_game', 'test it in game', 'done', None),
    ('deliver_to_game', 'put it in my game', 'done', None),
    (None, 'put him on Marth instead', 'done', None),
    # An import from before rigswap that stopped on a question is not carried on: a normal turn.
    (None, 'taller', 'needs_user', None),
    (None, 'go on', 'refused', None),
    ('recolor_part', 'make the cape red', 'needs_user', None),
    ('verify_in_game', 'test it in game', 'needs_user', None),
])
def test_routing(studio_root, family, text, receipts, mode):
    """``text`` is the turn's words; the family is what recipes.turn_family makes of the chat's task and them
    (a declared task, or a follow-up its words ask for)."""
    receipts = [dict(name='import_model', result=dict(status=receipts, studio_import={'tool': 'import_model',
                                                                                      'id': 'neos-1'}))] if receipts else []
    assert studio_import.turn_mode(family, receipts) == mode
    assert studio_import.turn_mode(family, receipts, waiting=True) == 'import', 'a new model is a new import'
    assert studio_import.changeable(receipts) == ('neos-1' if receipts and receipts[0]['result']['status'] == 'done'
                                                  else None)


def test_naming_an_imported_costume_is_a_normal_turn(studio_root, monkeypatch):
    folder = studio_root / 'neos-1a2b3c'
    (folder / 'finish').mkdir(parents=True)
    (folder / 'finish' / 'finished.json').write_text(json.dumps({'name': 'Elemental Hero Neos'}))
    seen = []
    monkeypatch.setattr(engine, '_provider', _provider(seen))
    list(live_runs.stream(engine.start(None, 'the knees on my Elemental Hero Neos stick out', {}, request_key='k')))
    assert 'import_model' not in seen[0]['names']
    assert not any('TASK RECIPE -- IMPORT A MODEL' in text for text in seen[0]['system'])


def test_the_import_models_source_counts_as_imported():
    zipped = {'file_id': 'a' * 32, 'name': 'neos.zip', 'extension': '.zip'}
    done = [{'name': 'import_model', 'arguments': {'source': zipped['file_id']}}]
    assert attached_model_waiting('import this', [zipped], done) is None
    assert attached_model_waiting('import this', [zipped], []) == zipped


# ------------------------------------------------------------------ the vault record and rigswap's key

def test_the_vault_record_names_the_project(vault, tmp_path, monkeypatch):
    from vault.importing.unified import characters
    from core.metadata import load_metadata, metadata_transaction

    def importer(archive, info, name, auto_fix=False, custom_name=None):
        with metadata_transaction(default={}) as metadata:
            skins = metadata.setdefault('characters', {}).setdefault(info['character'], {}).setdefault('skins', [])
            skin = f'skin{len(skins) + 1}'
            skins.append(dict(id=skin, name=custom_name, filename=f'{skin}.zip'))
        return dict(success=True, skin_id=skin)
    monkeypatch.setattr(characters, 'import_character_costume', importer)
    entry, _ = finishing.save_to_vault(b'dat', 'C. Falcon', 'PlCaNr', 'Neos', source='model_import_rigswap',
                                       project=tmp_path / 'imports' / 'neos-1')
    stored = load_metadata(default={})['characters']['C. Falcon']['skins'][0]
    assert stored['model_import'] == dict(source='model_import_rigswap', project=str(tmp_path / 'imports' / 'neos-1'))
    assert entry['model_import']['project'] == stored['model_import']['project']
    finishing.save_to_vault(b'dat', 'C. Falcon', 'PlCaNr', 'Old')      # no project: the record has none
    assert 'project' not in load_metadata(default={})['characters']['C. Falcon']['skins'][-1]['model_import']


def test_rigswap_is_given_the_turns_key_else_the_machines(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'env-key')
    assert import_job.openrouter_key() == 'env-key' and import_job.openrouter_key('given') == 'given'
    assert import_job._environment('turn-key')['OPENROUTER_API_KEY'] == 'turn-key'
    assert import_job._environment(None)['OPENROUTER_API_KEY'] == 'env-key', "the machine's, without a turn key"
    monkeypatch.setenv('OPENROUTER_API_KEY', 'op://<vault>/<item>/credential')
    secret = tmp_path / 'openrouter.key'
    monkeypatch.setattr(import_job, '_secret_file', lambda: secret)
    assert import_job.openrouter_key() is None, 'a 1Password reference is not a key'
    assert 'OPENROUTER_API_KEY' not in import_job._environment(None), 'no key: rigswap looks for its own'
    secret.write_text(' file-key\n', encoding='utf-8')
    assert import_job.openrouter_key() == 'file-key', 'the secrets file'


def test_an_import_over_mcp_relays_rigswaps_asks_and_passes_no_key(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'env-key')
    env = import_job._environment('turn-key', relay=tmp_path / 'asks')
    assert env[import_job.RELAY_ENV] == str(tmp_path / 'asks') and 'OPENROUTER_API_KEY' not in env
    assert env[import_job.RELAY_WAIT_ENV] == str(import_job.RELAY_WAIT_S)
    monkeypatch.setenv(import_job.RELAY_ENV, 'left-over')
    assert import_job.RELAY_ENV not in import_job._environment('turn-key'), 'a chat import asks on its key'


# ------------------------------------------------------------------ the vault save itself (studio.finish)

@pytest.mark.parametrize('fighter', ['Ice Climbers', 'Nana', 'Popo'])
def test_finish_refuses_unsupported_fighters(fighter, tmp_path):
    with pytest.raises(finishing.NotSupportedYet, match='not supported yet'):
        finishing.finish(tmp_path / 'x.dat', fighter, 'name', out_dir=tmp_path)


def test_finish_checks_slot_and_name(tmp_path):
    with pytest.raises(finishing.FinishError, match='slots 0..4'):
        finishing.costume_code('Mario', 9)
    assert finishing.costume_code('Mario', None) == ('Mario', 'PlMrNr', 0)
    assert finishing.costume_code('Mario', 1)[1] == 'PlMrYe'
    with pytest.raises(finishing.FinishError, match='name'):
        finishing.finish(tmp_path / 'x.dat', 'Mario', '  ', out_dir=tmp_path)


@pytest.fixture
def vault_tools(monkeypatch):
    """Real importer; the portrait renderer and Slippi check replaced."""
    from vault.importing.unified import characters
    from shared import mod_files
    png = io.BytesIO()
    Image.new('RGB', (136, 188), (200, 30, 30)).save(png, 'PNG')
    stock = io.BytesIO()
    Image.new('RGBA', (24, 24), (200, 30, 30, 255)).save(stock, 'PNG')
    monkeypatch.setattr(characters, 'build_csp_and_stock', lambda *a, **k: dict(
        csp=png.getvalue(), csp_source='generated', stock=stock.getvalue(), stock_source='generated'))
    monkeypatch.setattr(characters, 'validate_for_slippi', lambda path, auto_fix=False: dict(
        slippi_safe=True, fix_applied=False, output='ok'))
    monkeypatch.setattr(characters, '_maybe_diet_fix', lambda data, name, character=None: (data, None))
    monkeypatch.setattr(mod_files, 'dat_roots', lambda path: ['PlyMario5K_Share_joint'])


def test_finish_saves_a_new_costume_into_a_temporary_vault(vault_tools, monkeypatch, tmp_path):
    from core import config
    real_storage = config.STORAGE_PATH
    installs = []

    def install(archive, character, vanilla_iso=None, log=None):
        installs.append((Path(archive), character))
        return dict(checked=True, ok=True, new_slot=5)

    monkeypatch.setattr(finishing, 'install_check', install)
    dat = tmp_path / 'PlMrNr.dat'
    dat.write_bytes(b'imported costume')
    storage = tmp_path / 'storage'
    result = finishing.finish(dat, 'Mario', 'Mario 64', out_dir=tmp_path / 'out', storage_root=storage)
    assert config.STORAGE_PATH == real_storage, 'storage is restored after the call'
    assert result['installable'] is True and result['notes'] == []
    assert Path(result['csp']).is_file() and Path(result['stock']).is_file()
    vault = result['vault']
    archive = Path(vault['archive'])
    assert archive.is_file() and storage.resolve() in archive.resolve().parents
    assert installs == [(archive, 'Mario')]
    with zipfile.ZipFile(archive) as z:
        dats = [n for n in z.namelist() if n.endswith('.dat')]
        assert len(dats) == 1 and z.read(dats[0]) == b'imported costume'
    metadata = json.loads((storage / 'metadata.json').read_text())
    skins = metadata['characters']['Mario']['skins']
    assert len(skins) == 1 and skins[0]['name'] == 'Mario 64' and skins[0]['costume_code'] == 'PlMrNr'
    assert skins[0]['model_import']['source'] == 'model_import_v2'
    # a second finish makes another costume, never renames the first
    again = finishing.finish(dat, 'Mario', 'Mario 64', out_dir=tmp_path / 'out2', storage_root=storage)
    assert again['vault']['skin_id'] != vault['skin_id']
    assert len(json.loads((storage / 'metadata.json').read_text())['characters']['Mario']['skins']) == 2


def test_finish_reports_a_failed_install(vault_tools, monkeypatch, tmp_path):
    monkeypatch.setattr(finishing, 'install_check', lambda *a, **k: dict(
        checked=True, ok=False, reason='MexCLI import-costume answered {}'))
    dat = tmp_path / 'PlMrNr.dat'
    dat.write_bytes(b'imported costume')
    result = finishing.finish(dat, 'Mario', 'x', slot=2, out_dir=tmp_path / 'out', storage_root=tmp_path / 's')
    assert result['installable'] is False and result['vault']['costume_code'] == 'PlMrBk'
    assert any('install check failed' in n for n in result['notes'])


@pytest.mark.parametrize('fighter, code', [('Mr. Game & Watch', 'PlGwNr'), ('Mario', 'PlMrNr')])
def test_only_a_game_and_watch_save_carries_a_white_slot_colour(vault_tools, monkeypatch, tmp_path, fighter, code):
    """G&W's game code paints every material with the slot's fill (m-ex GawColors), black unless the costume's
    gaw.json says otherwise; an import draws its own textures, so his save carries a white fill and his usual
    outline. The vault keeps the sidecar, records it, and colours the portrait with it; no other fighter gets one."""
    from vault.importing.unified import characters
    rendered = []
    png = io.BytesIO()
    Image.new('RGB', (136, 188), (200, 30, 30)).save(png, 'PNG')
    monkeypatch.setattr(characters, 'build_csp_and_stock', lambda *a, **k: rendered.append(k.get('gw_colors')) or dict(
        csp=png.getvalue(), csp_source='generated', stock=png.getvalue(), stock_source='generated'))
    monkeypatch.setattr(finishing, 'install_check', lambda *a, **k: dict(checked=True, ok=True, new_slot=4))
    dat = tmp_path / f'{code}.dat'
    dat.write_bytes(b'imported costume')
    storage = tmp_path / 'storage'
    result = finishing.finish(dat, fighter, 'Tung', out_dir=tmp_path / 'out', storage_root=storage)
    gaw = fighter == 'Mr. Game & Watch'
    with zipfile.ZipFile(result['vault']['archive']) as z:
        sidecars = [n for n in z.namelist() if n.lower() == 'gaw.json']
        assert len(sidecars) == gaw
        if gaw:
            assert json.loads(z.read(sidecars[0])) == {'fill': '#FFFFFFFF', 'outline': '#80FFFFFF'}
    skin = json.loads((storage / 'metadata.json').read_text())['characters'][fighter]['skins'][0]
    assert skin.get('gaw_colors') == ({'fill': '#FFFFFFFF', 'outline': '#80FFFFFF'} if gaw else None)
    assert rendered == [{'fill': (255, 255, 255), 'outline': (255, 255, 255, 128)} if gaw else None]
    assert result['installable'] is True and result['notes'] == []


def test_check_archive_finds_changed_bytes_and_missing_art(tmp_path):
    archive = tmp_path / 'c.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('PlMrNrMod.dat', b'changed')
        z.writestr('csp.png', b'x')
    problems = finishing.check_archive(archive, b'original', 'PlMrNr')
    assert any('differs' in p for p in problems) and any('stc.png' in p for p in problems)
    assert not any('differs' in p for p in finishing.check_archive(archive, b'original', 'PlMrNr', allow_changed=True))


# ------------------------------------------------------------------ the running card

def _until(seen, test, seconds=10.):
    until = time.monotonic() + seconds
    while time.monotonic() < until and not test(list(seen)):
        time.sleep(.01)


def test_the_running_card_is_built_off_the_reading_thread_coalesced_and_never_after_the_reply(tmp_path, monkeypatch):
    """Sending a card takes time (the chat saved, the stream written): the thread reading rigswap's output never
    waits for it. Lines that come while a card is being sent go out together in the next one, the newest state; a
    card that shows nothing new is not sent; close (the reply follows) sends what is still due and nothing after."""
    monkeypatch.setattr(import_job, 'CARD_GAP', .05)
    sent = []

    def slow(card):
        time.sleep(.2)          # the chat saved, the stream written
        sent.append(card)
    log = import_job._Progress(slow, tmp_path, 'neos-1', time.monotonic(), shown=dict(fighter='Fox'))
    began = time.monotonic()
    for n in range(20):
        log(f'line {n}')
    assert time.monotonic() - began < .15, 'logging never waits for a card to be built and sent'
    assert (tmp_path / 'workflow' / import_job.LOG).read_text().count('line ') == 20, 'every line in job.log at once'
    _until(sent, lambda seen: seen and seen[-1]['progress'][-1] == 'line 19', 5.)
    assert 1 <= len(sent) <= 3, f'coalesced: {len(sent)} cards for 20 lines'
    assert sent[-1]['progress'] == [f'line {n}' for n in range(14, 20)], 'the newest state, its newest lines'
    assert sent[-1]['fighter'] == 'Fox' and 'flow' not in sent[-1]
    before = len(sent)
    for _ in range(3):
        log.refresh()           # nothing it shows changed
    time.sleep(.5)
    assert len(sent) == before, 'a card that shows nothing new is not sent'
    log('x' * 1000)
    log.close()
    assert len(sent[-1]['progress'][-1]) == import_job.LINE_CHARS, 'a long line is cut on the card'
    assert 'x' * 1000 in (tmp_path / 'workflow' / import_job.LOG).read_text(), '...and kept whole in job.log'
    after = len(sent)
    log('line 21')
    log.refresh()
    time.sleep(.3)
    assert len(sent) == after, 'no running card after the reply'


def test_the_step_is_read_from_rigswaps_own_stage_lines_and_only_goes_forward():
    """The card's ``step`` (the MCP chip's words): rigswap's stage lines and this module's own move it; the lines of
    the tools rigswap runs (Blender's, with a clock and file paths) never do, nor does a line that reads like an
    earlier stage once a later one began."""
    step = import_job.next_step
    for line, found in (('import Neos.glb onto the fighter it fits best', 'load'), ('loading clank.zip', 'load'),
                        ('change neos-1 on Marth: the legs look wrong', 'fix'), ('looking at what was said', 'fix'),
                        ('getting Fox ready from the game files', 'ready'),
                        (f'swapping onto {import_job.AUTO}', 'pick'), ('swapping onto CaptainFalcon', 'swap'),
                        ('picked Fox: the closest build', 'swap'), ('building it again onto Fox', 'again'),
                        ('saving the costume to the vault', 'save')):
        assert step(None, line) == found, line
    raw = r"00:03.485 render | Saved: 'E:\Nucleus Data\storage\model_imports\clank-a370ff\front-1.png'"
    assert step(None, raw) is None and step('swap', raw) == 'swap'
    assert step('swap', 'loading clank.zip') == 'swap', 'never back'
    assert step('pick', 'swapping onto Fox') == 'swap' and step('fix', 'building it again onto Fox') == 'again'
    assert set(import_job.STEPS) == set(import_job._STEP_RANK)


def test_the_running_card_carries_the_step_in_words(tmp_path):
    sent = []
    log = import_job._Progress(sent.append, tmp_path, 'clank-1', time.monotonic(), shown=dict(fighter='Kirby'))
    log('loading clank.zip')
    log(r'00:01.141 blend | Read blend: "E:\Nucleus Data\clank-a370ff\1-Clank.blend"')
    log.close()
    assert sent[-1]['step'] == 'loading the model' and sent[-1]['progress'][-1].startswith('00:01.141 blend')
    early = []
    quiet = import_job._Progress(early.append, tmp_path, 'clank-2', time.monotonic())
    quiet('rigswap 1.4')
    quiet.close()
    assert 'step' not in early[-1], 'no step until a stage begins'


def test_the_running_card_names_the_fighter_rigswap_picks(tmp_path):
    """No fighter named: the card names the one rigswap picks, in the app's words, from that line on (the window's
    chip says "as Fox"); a fighter the user named is never replaced."""
    def card(lines, shown=None):
        sent = []
        log = import_job._Progress(sent.append, tmp_path, 'pick-1', time.monotonic(), shown=shown)
        for line in lines:
            log(line)
        log.close()
        return sent[-1]
    assert 'fighter' not in card(['loading sack.zip', 'swapping onto auto'])
    assert card(['loading sack.zip', 'picked Fox: the closest build'])['fighter'] == 'Fox'
    assert card(['loading sack.zip', 'swapping onto CaptainFalcon'])['fighter'] == 'C. Falcon'
    assert card(['picked Fox: the closest build', 'swapping onto Marth'])['fighter'] == 'Fox', 'the first one holds'
    assert card(['picked Fox: the closest build'], shown=dict(fighter='Ness'))['fighter'] == 'Ness'


def test_a_running_card_that_lands_after_the_reply_never_replaces_it(studio_root, fake_rigswap, tmp_path,
                                                                    monkeypatch):
    """A running card whose send hung past the reply (``_Progress.close`` gives up waiting for it) can still reach
    the engine afterwards: the receipt keeps the reply, in memory, in the chat store and in the stream."""
    monkeypatch.setattr(finishing, 'finish', fake_finish([]))
    source = _attached_zip(tmp_path)
    late, real = [], import_job.run

    def run(args, *, key=None, progress=None, cancelled=None, relay=None):
        late.append(progress)
        return real(args, key=key, progress=progress)
    monkeypatch.setattr(import_job, 'run', run)
    plan = [('import_model', {'source': source['file_id'], 'fighter': 'C. Falcon'})]

    def provider(messages, schemas, key, cancelled):
        if plan:
            name, arguments = plan.pop(0)
            yield {'type': 'completion', 'message': {'role': 'assistant', 'content': None, 'tool_calls': [
                {'id': 'c1', 'function': {'name': name, 'arguments': json.dumps(arguments)}}]}}
        else:
            yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Done.'}}
    monkeypatch.setattr(engine, '_provider', provider)
    turn = engine.start(None, 'Import this model onto C. Falcon.', {'files': [source]}, request_key='k')
    list(live_runs.stream(turn))
    receipt = turn.answer['tools'][0]
    assert receipt['status'] == 'done' and receipt['result']['status'] == 'done'
    project = receipt['result']['project']
    late[0](dict(status='running', project=project, progress=['a card that hung'],
                 studio_import={'tool': 'import_model', 'id': project}))
    assert receipt['status'] == 'done' and receipt['result']['status'] == 'done', 'the reply stays'
    stored = store.get(turn.chat_id)['messages'][-1]['tools'][0]
    assert stored['status'] == 'done' and stored['result']['status'] == 'done'
    assert turn.events.empty() or all(event.get('tool', {}).get('result', {}).get('status') != 'running'
                                      for event in list(turn.events.queue)), 'nothing streamed after it'


def test_a_late_running_update_never_lands_on_the_next_calls_receipt(studio_root, tmp_path, monkeypatch):
    """Two import_model calls in one turn: the first one's running card, arriving while the second runs, is neither
    the second's (its own receipt is bound) nor written over the first's reply."""
    progresses = []

    def run(args, *, key=None, progress=None, cancelled=None, relay=None):
        progresses.append(progress)
        if len(progresses) == 2:
            progresses[0](dict(status='running', progress=['the first call, late']))
            progress(dict(status='running', progress=['the second call']))
        return dict(status='done', progress=[f'reply {len(progresses)}'])
    monkeypatch.setattr(import_job, 'run', run)
    source = _attached_zip(tmp_path)
    plan = [('c1', 'import_model', {'source': source['file_id']}), ('c2', 'import_model', {'source': source['file_id']})]

    def provider(messages, schemas, key, cancelled):
        if plan:
            call, name, arguments = plan.pop(0)
            yield {'type': 'completion', 'message': {'role': 'assistant', 'content': None, 'tool_calls': [
                {'id': call, 'function': {'name': name, 'arguments': json.dumps(arguments)}}]}}
        else:
            yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Done.'}}
    monkeypatch.setattr(engine, '_provider', provider)
    turn = engine.start(None, 'Import this model.', {'files': [source]}, request_key='k')
    events = [json.loads(line[len('data: '):]) for line in live_runs.stream(turn) if line.startswith('data: ')]
    first, second = turn.answer['tools'][:2]
    shown = [(e['tool']['id'], (e['tool'].get('result') or {}).get('progress')) for e in events
             if e['type'] == 'tool_result']
    assert (second['id'], ['the first call, late']) not in shown, "the first call's card is not the second's"
    assert (second['id'], ['the second call']) in shown
    assert (first['id'], ['the first call, late']) not in shown, 'nor written over the reply it came after'
    assert first['result']['progress'] == ['reply 1'] and second['result']['progress'] == ['reply 2']


def test_a_crash_in_the_job_is_said_as_the_importers_fault(studio_root, fake_rigswap, tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise TypeError("'NoneType' object is not subscriptable")
    monkeypatch.setattr(import_job, 'rigswap', broken)
    reply = _call({'source': _attached_zip(tmp_path)['file_id']})
    assert reply['error'] == 'an internal error in the importer', 'the error closes no question, in plain words'
    assert reply['failed']['kind'] == 'unexpected' and 'status' not in reply
    assert "TypeError: 'NoneType'" not in json.dumps(compaction.model_view(reply)), 'the model never sees it'
    assert reply['diagnostic'] == "TypeError: 'NoneType' object is not subscriptable", 'kept for the report'
    assert 'cannot tell' in reply['next'] and "do not infer one from the model's name or file name" in reply['next']
