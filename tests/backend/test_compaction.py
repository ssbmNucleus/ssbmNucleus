"""Older tool results shrink to what later steps need; the newest stay whole."""
import json

from randall.assistant import compaction


def _big():
    return {'operation': 'mesh', 'candidate_id': 'c' * 32, 'selection_id': 's' * 32,
            'error': None, 'note': 'n' * 1000, 'warnings': ['w1', 'w2'],
            'inventory': [{'group': i, 'triangles': i * 10} for i in range(500)],
            'files': [{'file_id': 'f1', 'name': 'page.png', 'sha256': 'x' * 64, 'extension': '.png'}],
            'bind_fit_cost': 0.12, 'regions': {f'r{i}': list(range(50)) for i in range(40)}}


def test_a_small_result_is_left_alone():
    small = {'operation': 'x', 'note': 'fine'}
    assert compaction.compact_result(small) is small


def test_a_big_result_keeps_ids_notes_files_and_names_what_it_dropped():
    out = compaction.compact_result(_big())
    assert out['candidate_id'] == 'c' * 32 and out['selection_id'] == 's' * 32
    assert out['warnings'] == ['w1', 'w2'] and out['note'].endswith('...')
    assert out['files'] == [{'file_id': 'f1', 'name': 'page.png'}]
    assert out['bind_fit_cost'] == 0.12
    assert 'inventory' not in out and 'regions' not in out
    assert 'inventory' in out['shortened'] and 'regions' in out['shortened']
    assert len(json.dumps(out)) < len(json.dumps(_big())) / 10


def test_only_the_newest_two_tool_messages_stay_whole():
    messages = [{'role': 'tool', 'content': json.dumps(_big())} for _ in range(4)]
    pending = []
    for message in messages:
        pending.append(message)
        compaction.compact_older(pending)
    sizes = [len(m['content']) for m in messages]
    assert sizes[0] < sizes[2] / 10 and sizes[1] < sizes[2] / 10
    assert sizes[2] == sizes[3] == len(json.dumps(_big()))
    assert len(pending) == 2


def test_an_earlier_turns_receipt_is_shortened_for_the_app_context():
    receipt = {'name': 'model_mesh', 'status': 'done', 'arguments': {'candidate_id': 'c' * 32},
               'result': _big(), 'started_at': 1}
    out = compaction.compact_receipt(receipt)
    assert set(out) == {'name', 'status', 'arguments', 'result'}
    assert out['result']['candidate_id'] == 'c' * 32 and 'inventory' not in out['result']


def test_a_huge_new_result_is_trimmed_by_its_biggest_lists_and_says_so():
    out = compaction.fit_fresh(_big(), budget=4000)
    assert len(json.dumps(out)) <= 4000
    assert out['candidate_id'] == 'c' * 32 and out['note'] == _big()['note']
    assert len(out['inventory']) < 500 and 'inventory (first' in out['trimmed']


def test_a_normal_new_result_is_untouched():
    small = {'operation': 'x', 'rows': list(range(20))}
    assert compaction.fit_fresh(small) is small


def test_only_a_model_imports_card_only_keys_are_kept_from_the_model():
    """UI_ONLY is import_model's (a result tagged studio_import): another tool's key of the same name is its own."""
    imported = {'status': 'done', 'flow': {'phases': []}, 'studio_import': {'tool': 'import_model', 'id': 'x'}}
    assert 'flow' not in compaction.model_view(imported) and 'flow' in imported, 'the transcript keeps it'
    assert 'flow' not in compaction.fit_fresh(imported) and 'flow' not in compaction.compact_result(imported)
    other = {'status': 'done', 'flow': 'a pipe flow the tool reports'}
    assert compaction.model_view(other) is other
    assert compaction.fit_fresh(other)['flow'] == 'a pipe flow the tool reports'
