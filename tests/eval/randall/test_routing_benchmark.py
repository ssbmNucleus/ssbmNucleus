import json

from routing_benchmark import grade, payload_for
from routing_cases import CASES
from tests.gated import needs

# The coach's cases (c..) need the Tracker coach, which the public source drop leaves out.
coach_cases = needs('randall')


def evaluate(identifier, tool=None, args=None, content=None):
    case = next(c for c in CASES if c['id'] == identifier)
    _, schemas = payload_for(case, 'gemini', 'full')
    message = {'content': content}
    if tool:
        message['tool_calls'] = [{'function': {'name': tool, 'arguments': json.dumps(args)}}]
    return grade(case, message, schemas)


@coach_cases
def test_documented_defaults_do_not_count_as_errors():
    assert evaluate('c03', 'find_moments', dict(role='against_me', vs_character='Fox', ender='bair', killed=True, limit=5))['passed']


@coach_cases
def test_correct_tool_with_missing_death_filter_fails():
    score = evaluate('c03', 'find_moments', dict(role='against_me', vs_character='Fox', ender='bair', limit=5))
    assert score['tool_correct'] and not score['passed']


@coach_cases
def test_invented_handle_fails_even_when_schema_valid():
    score = evaluate('c06', 'review_game', {'game_id': 1234})
    assert score['tool_correct'] and not score['passed']


@coach_cases
def test_clarification_requires_nonempty_response_and_no_tools():
    assert evaluate('c09', content='Which game do you mean?')['passed']
    assert not evaluate('c09', content='')['passed']
    assert not evaluate('c09', 'review_game', {'game_id': 7001})['passed']


@coach_cases
def test_clip_labels_are_optional_but_clip_identity_and_order_matter():
    assert evaluate('c08', 'queue_clips', {'moments': [{'ref': 'synthetic-ref-A', 'label': 'A'}, {'ref': 'synthetic-ref-B'}], 'title': 'Clips'})['passed']
    assert not evaluate('c08', 'queue_clips', {'moments': [{'ref': 'synthetic-ref-B'}, {'ref': 'synthetic-ref-A'}]})['passed']
    assert not evaluate('c08', 'queue_clips', {'moments': [{'game_id': 1, 'start_frame': 0, 'end_frame': 100}]})['passed']


@coach_cases
def test_unavailable_tools_and_unknown_arguments_fail():
    assert evaluate('c06', 'made_up_tool', {})['schema_errors']
    assert evaluate('c06', 'review_game', {'game_id': 7001, 'invented': True})['schema_errors']


def test_download_default_variant_is_semantically_equivalent():
    assert evaluate('m08', 'download_website_mods', {'items': [{'post_id': 4102, 'variants': 'default'}, {'post_id': 4103}]})['passed']


@coach_cases
def test_abstentions_do_not_pass_an_explicit_tool_request():
    assert not evaluate('c06', content='I will review it.')['passed']


@coach_cases
def test_equivalent_date_prefixes_pass_but_wrong_windows_fail():
    assert evaluate('c16', 'my_deep_stats', {'character': 'Fox', 'since': '2025-01-01', 'until': '2025-01-31'})['passed']
    assert evaluate('c16', 'my_deep_stats', {'character': 'Fox', 'since': '2025-01', 'until': '2025-01-31'})['passed']
    assert not evaluate('c16', 'my_deep_stats', {'character': 'Fox', 'since': '2025-01-01', 'until': '2025-02-01'})['passed']
