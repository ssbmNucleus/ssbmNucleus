import json

from randall.assistant import continuity, engine, live_runs, store, tools, vision
from shared import mod_files
from randall.recolor import skin_lab as lab
from tests.backend.test_assistant_skin_lab import session, png


def test_old_sources_swatches_and_checkpoint_survive_long_tool_history(session):
    viewer, source = session
    swatch = mod_files.register(png('brown'), 'Generated material.png')
    opened = {'name': 'skin_lab_open', 'arguments': {'file_id': source['file_id']}, 'result': {'session_id': 'test'}}
    receipts = [{'name': 'open_vanilla_file', 'result': {'files': [source]}},
                {'name': 'generate_material', 'result': {'files': [swatch]}}, opened]
    lab.skin_lab('test', 'analyze_palette', texture_indices=[0])
    result = tools.execute(tools.prepare('skin_lab', {'session_id': 'test', 'action': 'recolor',
        'adjustments': [{'index': 0, 'hue_shift': 30}]}))
    assert result['checkpoint_file']['file_id'] != source['file_id']
    receipts.append({'name': 'skin_lab', 'result': result})
    receipts.extend({'name': 'skin_lab', 'result': {'files': []}} for _ in range(30))
    state = continuity.working_context(receipts)
    assert state['material_swatches'][0]['file_id'] == swatch['file_id']
    assert state['skin_sessions'][0]['status'] == 'active'
    lab.skin_lab('test', 'close')
    recovered = continuity.working_context(receipts)
    assert recovered['skin_sessions'][0]['status'] == 'unavailable'
    assert recovered['skin_sessions'][0]['reopen_file_id'] == result['checkpoint_file']['file_id']
    assert mod_files.resolve(swatch['file_id'])[0].exists()
    assert mod_files.resolve(recovered['skin_sessions'][0]['reopen_file_id'])[1]['edited']


def test_all_seven_batch_images_reach_provider_and_arguments_persist(session, monkeypatch):
    count = 0
    def provider(messages, *args):
        nonlocal count
        count += 1
        if count == 1:
            calls = [{'id': str(i), 'function': {'name': 'skin_lab', 'arguments': json.dumps(
                {'session_id': 'test', 'action': 'texture', 'texture_index': i % 3})}} for i in range(7)]
            yield {'type': 'completion', 'message': {'role': 'assistant', 'content': None, 'tool_calls': calls}}
        else:
            images = messages[-1]['content']
            assert sum(i['type'] == 'image_url' for i in images) == 3
            assert sum('Tool image from' in i.get('text', '') for i in images) == 7
            assert sum('PNG bytes identical' in i.get('text', '') for i in images) == 4
            assert [m['role'] for m in messages[-8:-1]] == ['tool'] * 7
            yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Inspected.'}}
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Inspect textures', {}, request_key='private-test-key')
    list(live_runs.stream(run))
    assert run.answer['status'] == 'done', run.answer.get('error')
    assert run.answer['tools'][6]['arguments']['texture_index'] == 0
    saved = json.dumps(store.get(run.chat_id))
    assert 'private-test-key' not in saved and 'data:image' not in saved


def test_continue_rehydrates_actual_pixels_and_old_handles(session, monkeypatch):
    _, source = session
    swatch = mod_files.register(png('brown'), 'Generated material.png')
    receipts = [{'name': 'open_vanilla_file', 'result': {'files': [source]}},
                {'name': 'generate_material', 'result': {'files': [swatch]}}]
    for index in range(24):
        file = mod_files.register(png('pink'), f'Skin texture {index}.png')
        receipts.append({'name': 'skin_lab', 'result': {'files': [file], 'session_id': 'test', 'action': 'texture'}})
    chat_id = store.save(None, [{'role': 'user', 'content': 'leather Puff'},
        {'role': 'assistant', 'content': 'An earlier mistaken description.', 'tools': receipts, 'status': 'error'}])
    def provider(messages, *args):
        context = next(m['content'] for m in messages if m['role'] == 'system' and m['content'].startswith('App context'))
        assert source['file_id'] in context and swatch['file_id'] in context
        evidence = messages[-1]['content']
        assert isinstance(evidence, list)
        # A skin continuation re-sends only the latest image; the swatch stays
        # reachable by its file ID in the app context checked above.
        assert 'omitted' in evidence[0]['text']
        assert sum(i['type'] == 'image_url' for i in evidence) == 1
        assert sum('Tool image from' in i.get('text', '') for i in evidence) == 1
        yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Recovered.'}}
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(chat_id, 'continue', {}, request_key='test')
    list(live_runs.stream(run))
    assert run.answer['status'] == 'done', run.answer.get('error')


def test_checkpoint_failure_reports_live_success_without_hiding_risk(session, monkeypatch):
    viewer, _ = session
    def fail(): raise RuntimeError('disk unavailable')
    viewer.export_dat = fail
    result = continuity.record_skin_result('skin_material', {'session_id': 'test', 'action': 'apply'}, {'updated_textures': [0]})
    assert result['updated_textures'] == [0] and 'recovery copy' in result['checkpoint_error']
    state = continuity.working_context([{'name': 'skin_material', 'result': result}])
    assert 'checkpoint_error' in state['skin_sessions'][0]


def test_apply_receipt_keeps_preview_controls_for_continuation(session):
    receipts = [{'name': 'skin_material', 'result': {'preview_id': 'plan', 'session_id': 'test',
                 'material_file_id': 'swatch', 'texture_indices': [0], 'controls': {'strength': 0.6}}},
                {'name': 'skin_material', 'result': {'preview_id': 'plan', 'session_id': 'test', 'action': 'apply'}}]
    preview = continuity.working_context(receipts)['material_previews'][0]
    assert preview['material_file_id'] == 'swatch' and preview['controls']['strength'] == 0.6
    assert preview['action'] == 'apply'


def test_latest_only_keeps_the_latest_render_and_the_fresh_batch():
    from randall.assistant.vision import context_images
    def receipt(name, fid, action=None):
        return {'name': name, 'result': {'files': [{'file_id': fid, 'extension': '.png'}],
                                         **({'action': action} if action else {})}}
    loader = lambda name, result: [{'type': 'image_url', 'image_url': {'url': result['files'][0]['file_id']}}]
    receipts = [receipt('skin_lab_open', 'open-render'), receipt('generate_material', 'swatch'),
                receipt('skin_lab', 'old-render', 'recolor'), receipt('skin_lab', 'new-render', 'recolor'),
                receipt('skin_material', 'preview-sheet', 'preview')]
    urls = lambda content: [i['image_url']['url'] for i in content if i['type'] == 'image_url']
    fresh = context_images(receipts, loader=loader, fresh_receipts=receipts[-1:], latest_only=True)
    assert urls(fresh) == ['new-render', 'preview-sheet'], 'latest render + what just arrived, nothing older'
    assert urls(context_images(receipts[:4], loader=loader, latest_only=True)) == ['new-render']


def test_plain_label_origin_opens_and_edits_without_a_costume_target(session, monkeypatch):
    """A model import's costume is registered with a plain label as its origin ('model_import_v2'), not the
    vault's dict. The Skin Lab opens and edits it like any other, with no costume to point an editor at."""
    from core import viewer_tools
    from randall.recolor import autosave, costume_colours
    from tests.backend.test_assistant_skin_lab import dat
    viewer, _ = session
    plain = mod_files.register(dat(), 'PlFxNr.dat', origin='model_import_v2')
    monkeypatch.setattr(lab, 'ViewerSession', lambda *args, **kwargs: viewer)
    for name in ('find_scene_file', 'find_aj_file', 'find_fighter_data_file'):
        monkeypatch.setattr(viewer_tools, name, lambda character: None)
    monkeypatch.setattr(viewer_tools, 'find_available_port', lambda: 12345)
    opened = tools.execute(tools.prepare('skin_lab_open', {'file_id': plain['file_id']}))
    assert 'error' not in opened, opened
    sid = opened['session_id']
    assert opened['source_file_id'] == plain['file_id'] and 'skin_target' not in opened
    lab.skin_lab(sid, 'analyze_palette', texture_indices=[0])
    edited = tools.execute(tools.prepare('skin_lab', {'session_id': sid, 'action': 'recolor',
        'adjustments': [{'index': 0, 'hue_shift': 30}]}))
    assert 'error' not in edited and 'checkpoint_error' not in edited, edited
    assert 'skin_target' not in edited
    assert mod_files.resolve(edited['checkpoint_file']['file_id'])[1]['origin'] == 'model_import_v2'
    assert autosave._snapshot(autosave.COSTUME, sid)['label'] == 'Costume'
    assert costume_colours._hidden({'source': mod_files.resolve(plain['file_id'])[1]}) == {}
    lab.skin_lab(sid, 'close')
