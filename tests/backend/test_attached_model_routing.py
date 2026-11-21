"""An attached model and "import this" is an import turn: how an ordinary chat reaches import_model.

Randall eval 2026-09-25: with a Togetic zip attached, "import this" went to the
fast lane, which answered from the docs that "import" means saving a costume.
The import ran only on the user's next message. The words alone never make an
import turn; the attached file does, and a .zip is looked into: a costume pack
is not a model.
"""
import io
import zipfile

import pytest

from shared.aiengine import fast_lane
from randall.assistant import engine, live_runs
from shared import mod_files
from randall.recolor import workflows
from randall.model_import.chat.attached_model import attached_model_waiting

ZIP = {'file_id': 'a' * 32, 'name': 'Togetic.zip', 'extension': '.zip'}
GLB = {'file_id': 'b' * 32, 'name': 'goomba.glb'}
PNG = {'file_id': 'c' * 32, 'name': 'reference.png', 'extension': '.png'}


@pytest.mark.parametrize('text', [
    'import this', 'Import it', 'lets make a model import of this', 'put this on Marth',
    'make it a costume', 'this', 'do it', 'can you import this?', 'try it on Kirby',
])
def test_an_action_on_an_attached_model_is_a_full_turn(text):
    assert attached_model_waiting(text, [PNG, ZIP], []) == ZIP


@pytest.mark.parametrize('text', [
    'what is this?', 'which fighter has the best recovery?', 'how many costumes do I have',
    'what does the second look mean', 'does it have a tail?', '',
])
def test_a_quick_question_is_not_an_import(text):
    assert attached_model_waiting(text, [ZIP], []) is None


def test_only_model_files_that_were_not_imported_yet_count():
    assert attached_model_waiting('import this', [PNG], []) is None
    assert attached_model_waiting('import this', [], []) is None
    assert attached_model_waiting('import this', [GLB], []) == GLB     # extension from the name
    done = [{'name': 'import_model', 'arguments': {'source': ZIP['file_id']}}]      # still running: no result yet
    assert attached_model_waiting('import this', [ZIP], done) is None
    assert attached_model_waiting('import this', [ZIP, GLB], done) == GLB


def test_an_import_that_never_made_a_project_leaves_its_file_to_try_again():
    """F-F-3: the importer not set up (or a refusal) is not a used-up attachment."""
    def call(result):
        return [{'name': 'import_model', 'arguments': {'source': ZIP['file_id']}, 'result': result}]
    not_set_up = {'error': 'rigswap is not set up', 'studio_import': {'tool': 'import_model', 'id': None}}
    stopped = {'status': 'cancelled', 'studio_import': {'tool': 'import_model', 'id': 'togetic-1'}}
    ran = {'status': 'failed', 'error': 'x', 'studio_import': {'tool': 'import_model', 'id': 'togetic-2'}}
    assert attached_model_waiting('try again', [ZIP], call(not_set_up)) == ZIP
    assert attached_model_waiting('import it again', [ZIP], call(stopped)) == ZIP
    assert attached_model_waiting('import this', [ZIP], call(ran)) is None
    assert attached_model_waiting('import this', [ZIP], call(None)) is None, 'still running'


def test_import_this_with_a_zip_attached_reaches_the_main_model_with_the_import_card(vault, monkeypatch):
    monkeypatch.setenv('NUCLEUS_FAST_ROUTING', '1')

    def lane_post(*args, **kwargs):
        raise AssertionError('the fast lane was asked to answer an import')
    monkeypatch.setattr(fast_lane.requests, 'post', lane_post)
    seen = []

    def provider(messages, schemas, *args, **kwargs):
        seen.append([m.get('content') for m in messages if m.get('role') == 'system'])
        yield {'type': 'completion', 'finish_reason': 'stop',
               'message': {'role': 'assistant', 'content': 'Importing it now.'}}
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'import this', {'files': [ZIP]}, request_key='test')
    list(live_runs.stream(run))
    assert seen, 'the main model never ran'
    assert any('TASK RECIPE -- IMPORT A MODEL' in (c or '') for c in seen[0])    # import mode's card
    assert run.answer['routing'].get('attached_model') is True
    assert run.answer['routing'].get('model_import_mode') == 'import'


def test_a_question_with_a_zip_attached_is_an_ordinary_main_model_turn(vault, monkeypatch):
    monkeypatch.setenv('NUCLEUS_FAST_ROUTING', '1')
    asked, offered = [], []

    def lane_post(*args, **kwargs):
        asked.append(kwargs.get('json'))
        raise RuntimeError('offline')
    monkeypatch.setattr(fast_lane.requests, 'post', lane_post)

    def provider(messages, schemas, *args, **kwargs):
        offered.append({s['function']['name'] for s in schemas})
        yield {'type': 'completion', 'finish_reason': 'stop',
               'message': {'role': 'assistant', 'content': 'A zip.'}}
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'what is this?', {'files': [ZIP]}, request_key='test')
    list(live_runs.stream(run))
    routing = run.answer['routing']
    assert not asked, 'no lookup lane answers an assistant turn'
    assert not routing.get('attached_model') and 'model_import_mode' not in routing
    assert 'import_model' not in offered[0] and 'inspect_mod_file' in offered[0]


def _zip(name, members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for member in members:
            archive.writestr(member, b'data')
    return mod_files.register(buffer.getvalue(), name)


@pytest.mark.parametrize('members,model', [
    (['goku/goku.dae', 'goku/tex.png'], True),          # a model with its textures
    (['PlFxNr.dat', 'csp.png'], False),                 # a costume pack: not a model
    (['PlFxNr.dat', 'source/goku.obj'], True),          # a model inside wins
    (['readme.txt'], True),                             # nothing to tell by: as before, a model
])
def test_a_zip_is_a_model_unless_it_is_a_costume_pack(vault, members, model):
    archive = _zip('pack.zip', members)
    assert (attached_model_waiting('recolor this red', [archive], []) is not None) is model
    assert (attached_model_waiting('import this', [archive], []) is not None) is model


def test_a_costume_pack_with_recolor_words_is_never_an_import_turn(vault, monkeypatch):
    """Recolor words used to keep "recolor this red" with a costume pack out of the import (they enrolled the
    recolor workflow); the pack itself does now, since an ordinary chat's words route nowhere."""
    archive = _zip('kermit.zip', ['PlFxNr.dat'])
    monkeypatch.setattr(engine, '_provider', lambda *a, **k: iter([{
        'type': 'completion', 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': 'On it.'}}]))
    run = engine.start(None, 'recolor this red', {'files': [archive]}, request_key='test')
    list(live_runs.stream(run))
    assert 'model_import_mode' not in run.answer['routing']
    assert run.task.family == 'randall_turn'


# Moved from the deleted test_assistant_model_import.py: an attached model is not read as a DAT.
@pytest.mark.parametrize('extension', ['.glb', '.gltf', '.obj'])
def test_model_attachments_are_not_misparsed_as_dat(vault, extension):
    file = mod_files.register(b'model contents', 'model' + extension)
    assert 'roots' not in mod_files.inspect_mod_file(file['file_id'])
