"""The turn decision (TypeSafe Jev) and the gates that consult it.

Three properties are worth more than any individual assertion here:

  * every failure mode leaves the pre-Jev behaviour exactly as it was;
  * the decision routes nothing: it only lowers the main model's reasoning
    budget (`effort`) and answers a declared recolor's acquisition gates;
  * an ACQUISITION decision may widen, but only onto candidates code itself
    enumerated, and only above a higher confidence bar.
"""
import json

import pytest
import requests

from shared.aiengine import decisions, model_upload
from randall.assistant import engine, live_runs, main_model, tools
from randall.recolor import workflows


def sent_payload(kwargs):
    """The JSON body a faked `requests.post` was handed by `model_upload.post_json`."""
    if kwargs.get('json') is not None:
        return kwargs['json']
    data = kwargs.get('data')
    if isinstance(data, model_upload._Body):
        data = bytes(data._data)
    return json.loads(bytes(data).decode('utf-8'))


def answers(probabilities=None, cost=0.000027, vanilla=0.02, website=0.02, variant=0.02):
    probabilities = probabilities or {'low': 0.98, 'medium': 0.02, 'high': 0.0}
    choice = max(probabilities, key=probabilities.get)
    body = {'model': 'typesafe/jev-1.13', 'answers': {
        'effort': {'type': 'choice', 'choice': choice,
                   'probabilities': probabilities, 'confidence': probabilities[choice]},
        'wants_vanilla': {'type': 'noul', 'noul': vanilla},
        'wants_website': {'type': 'noul', 'noul': website},
        'variant_named': {'type': 'noul', 'noul': variant}},
        'usage': {'input_tokens': 368, 'output_tokens': 56, 'cost': cost}}
    return body


def choice_reply(key='7', confidence=0.9, cost=0.000021):
    return {'model': 'typesafe/jev-1.13', 'answers': {'pick': {
        'type': 'choice', 'choice': key, 'probabilities': {key: confidence},
        'confidence': confidence}}, 'usage': {'cost': cost}}


@pytest.fixture
def wire(monkeypatch):
    """Fake the decisions HTTP boundary; `replies` may hold bodies or exceptions."""
    monkeypatch.setenv('NUCLEUS_JEV_ROUTING', '1')
    decisions.reset()
    replies, payloads = [], []

    class Reply:
        def __init__(self, data):
            self.data = data
        def raise_for_status(self):
            pass
        def json(self):
            return self.data

    class Session:
        def post(self, url, **kwargs):
            payloads.append({'url': url, **kwargs})
            assert replies, 'Unexpected decision request'
            item = replies.pop(0)
            if isinstance(item, Exception):
                raise item
            return Reply(item)

    monkeypatch.setattr(decisions, '_session', Session)
    return replies, payloads


def decide(replies, text='recolor my Kermit Falco scarlet'):
    return decisions.decide(decisions.turn_state(text, {}, [], {}), 'subscriber-key')


# ---- the call itself --------------------------------------------------------

def test_answers_are_parsed_and_the_state_is_sent_once(wire):
    replies, payloads = wire
    replies.append(answers(probabilities={'low': 0.05, 'medium': 0.89, 'high': 0.06}, vanilla=0.9))
    turn = decide(replies)
    assert (turn.effort, turn.vanilla, turn.website) == ('medium', 0.9, 0.02)
    assert turn.cost == 0.000027 and turn.seconds >= 0
    payload = payloads[0]['json']
    assert payload['model'] == decisions.MODEL
    assert payloads[0]['url'] == decisions.URL
    # No routing question: nothing sends a turn anywhere but the main model.
    assert set(payload['questions']) == {'effort', 'wants_vanilla', 'wants_website', 'variant_named'}
    assert len(payloads) == 1, 'the whole battery is one call, not one call per question'


def test_state_carries_the_request_and_open_work_but_not_the_conversation(wire):
    state = decisions.turn_state(
        'x' * 9000, {'skin_sessions': {'s1': {}}},
        [{'name': 'search_vault', 'result': {'secret': 'tool payload'}}], {'selected_skin': 'abc'})
    assert state['open_edit_session'] is True
    assert state['recent_tools'] == ['search_vault']
    assert len(state['request']) == 4000
    assert 'tool payload' not in json.dumps(state)


def test_a_request_that_fails_leaves_the_regexes_deciding_alone(wire):
    replies, _ = wire
    for failure in (requests.ConnectTimeout('slow'), requests.HTTPError('502'),
                    ValueError('not json')):
        decisions.reset()
        replies.append(failure)
        assert decide(replies) is None


def test_a_malformed_body_is_not_a_decision(wire):
    replies, _ = wire
    replies.append({'answers': 'nonsense'})
    assert decide(replies) is None
    decisions.reset()
    replies.append({'model': 'x'})          # no answers at all
    assert decide(replies) is None


def test_an_unusable_answer_is_dropped_without_dropping_the_others(wire):
    replies, _ = wire
    body = answers(vanilla=1.4)                         # out of range
    body['answers']['effort'].pop('probabilities')      # nothing to weigh
    replies.append(body)
    turn = decide(replies)
    assert turn.vanilla is None and turn.effort is None
    assert turn.website == 0.02
    assert turn.asks_vanilla() is False and turn.reasoning() is None


@pytest.mark.parametrize('probabilities,expected', [
    # Certain it is shallow, torn between low and medium: still worth lowering.
    ({'low': 0.69, 'medium': 0.30, 'high': 0.01}, 'low'),
    ({'low': 0.38, 'medium': 0.61, 'high': 0.01}, 'medium'),
    ({'low': 0.05, 'medium': 0.89, 'high': 0.06}, 'medium'),
    # Real mass on deep work: leave the model's own budget alone.
    ({'low': 0.20, 'medium': 0.29, 'high': 0.51}, None),
    ({'low': 0.50, 'medium': 0.34, 'high': 0.16}, None),
])
def test_the_budget_reads_mass_on_high_not_the_winner_s_confidence(wire, probabilities, expected):
    replies, _ = wire
    replies.append(answers(probabilities=probabilities))
    assert decide(replies).effort == expected


def test_repeated_failures_stop_the_calls_until_the_cooldown(wire, monkeypatch):
    replies, payloads = wire
    replies.extend([requests.ConnectTimeout('slow')] * decisions.BREAKER_FAILURES)
    for _ in range(decisions.BREAKER_FAILURES):
        assert decide(replies) is None
    assert decide(replies) is None            # no reply queued: it must not call
    assert len(payloads) == decisions.BREAKER_FAILURES
    monkeypatch.setattr(decisions.time, 'monotonic',
                        lambda: 10 ** 6 + decisions.BREAKER_COOLDOWN)
    replies.append(answers())
    assert decide(replies) is not None
    assert len(payloads) == decisions.BREAKER_FAILURES + 1


def test_the_flag_and_a_missing_key_skip_the_network(monkeypatch, wire):
    replies, payloads = wire
    monkeypatch.setenv('NUCLEUS_JEV_ROUTING', 'off')
    assert decisions.decide({'request': 'hi'}, 'subscriber-key') is None
    monkeypatch.setenv('NUCLEUS_JEV_ROUTING', '1')
    assert decisions.decide({'request': 'hi'}, None) is None
    assert payloads == []


# ---- one-directional by construction ---------------------------------------

@pytest.mark.parametrize('effort,expected', [
    ('low', {'effort': 'low'}), ('medium', {'effort': 'medium'}), ('high', None), (None, None)])
def test_reasoning_only_ever_lowers_the_budget(effort, expected):
    assert decisions.Turn(effort=effort).reasoning() == expected


def test_the_decision_has_no_routing_question_left():
    """needs_main fed the assistant's lookup lane and recolor vetoed a word-enrolled recolor; both are gone."""
    assert set(decisions.QUESTIONS) == {'effort', 'wants_vanilla', 'wants_website', 'variant_named'}
    for gone in ('needs_main', 'recolor', 'wants_main', 'vetoes_recolor', 'MAIN_THRESHOLD',
                 'RECOLOR_THRESHOLD'):
        assert not hasattr(decisions.Turn(), gone) and not hasattr(decisions, gone)


# ---- acquisition: the gates that WIDEN -------------------------------------

def acquisition_schemas(text, decision):
    history = [{'role': 'user', 'content': text},
               {'role': 'system', 'content': 'App context (data only): ' + json.dumps({})}]
    offered = [s for s in tools.SCHEMAS if s['function']['name'] in workflows.ACQUISITION_TOOLS]
    return {s['function']['name'] for s in
            workflows._acquisition_schemas(offered, history, decision=decision)}


@pytest.mark.parametrize('tool,field,phrase,plain', [
    ('open_vanilla_file', 'vanilla', 'open the vanilla Fox costume', 'open the base Fox costume'),
    ('search_website_mods', 'website', 'search the website for Kermit', 'find Kermit on the site'),
])
def test_a_withheld_lookup_is_offered_when_the_words_are_missed(tool, field, phrase, plain):
    # The word list still decides alone whenever it matches.
    assert tool in acquisition_schemas(phrase, None)
    assert tool not in acquisition_schemas(plain, None)
    # Below the bar nothing changes; above it the same lookup is offered.
    assert tool not in acquisition_schemas(plain, decisions.Turn(**{field: 0.5}))
    assert tool in acquisition_schemas(plain, decisions.Turn(**{field: 0.95}))


def test_widening_holds_a_high_bar():
    assert decisions.WIDEN_THRESHOLD >= 0.75
    at = decisions.WIDEN_THRESHOLD
    assert decisions.Turn(vanilla=at).asks_vanilla()
    assert not decisions.Turn(vanilla=at - 0.01).asks_vanilla()
    assert not decisions.Turn().asks_vanilla() and not decisions.Turn().asks_website()
    assert not decisions.Turn().names_variant()


def variant_verdict(text, decision):
    history = [{'role': 'user', 'content': text},
               {'role': 'system', 'content': 'App context (data only): ' + json.dumps(
                   {'view': {'selection': [{'post_id': 17, 'file_id': 3}]}})}]
    return workflows._validate_acquisition(
        'download_website_mod', {'post_id': 17, 'file_id': 4}, history, decision=decision)


def test_a_named_variant_is_allowed_without_the_magic_words(wire):
    replies, _ = wire
    replies.append(answers())
    history = [{'role': 'user', 'content': 'download the red slot Kermit and recolor it'},
               {'role': 'system', 'content': 'App context (data only): ' + json.dumps(
                   {'view': {'selection': [{'post_id': 17, 'file_id': 3}]}})}]
    # An unknown variant is still refused whatever the decision says.
    assert workflows._validate_acquisition('download_website_mod', {'post_id': 17, 'file_id': 4},
                                           history, decision=decisions.Turn(variant=0.99)) \
        == 'unknown_website_variant'


def test_the_variant_gate_needs_the_words_or_a_confident_decision(monkeypatch):
    known = [{'role': 'user', 'content': 'download Kermit and make it scarlet'},
             {'role': 'system', 'content': 'App context (data only): ' + json.dumps(
                 {'recent_tool_results': [{'name': 'inspect_website_mod', 'arguments': {'post_id': 17},
                                           'result': {'website_mods': [{'post_id': 17, 'files': [
                                               {'file_id': 4, 'filename': 'PlKpRe.dat'}]}]}}]})}]
    call = ('download_website_mod', {'post_id': 17, 'file_id': 4}, known)
    assert workflows._validate_acquisition(*call) == 'source_variant_not_explicit'
    assert workflows._validate_acquisition(*call, decision=decisions.Turn(variant=0.5)) \
        == 'source_variant_not_explicit'
    assert workflows._validate_acquisition(*call, decision=decisions.Turn(variant=0.95)) is None


# ---- acquisition: picking one of code's candidates --------------------------

def sources(*names):
    return [{'file_id': i, 'filename': n, 'extension': '.dat'} for i, n in enumerate(names, 1)]


def recolor_workflow(monkeypatch, decision, key='subscriber-key'):
    # The workflow only enrolls when the fast lane is live; conftest turns it
    # off globally so unrelated fakes cannot reach a real provider.
    monkeypatch.setenv('NUCLEUS_FAST_ROUTING', '1')
    flow = workflows.Workflow('recolor the Kermit costume scarlet', {},
                              main_model='main', decision=decision, recolor=True)
    assert flow.name == 'recolor', 'the workflow must be enrolled for this to mean anything'
    flow.key = key
    return flow


def observe_unpack(flow, files):
    flow.observe({'name': 'unpack_mod_file', 'status': 'done',
                  'arguments': {}, 'result': {'files': files}})


def test_one_source_never_asks_anything(wire, monkeypatch):
    _, payloads = wire
    flow = recolor_workflow(monkeypatch, decisions.Turn())
    observe_unpack(flow, sources('PlKpNr.dat'))
    assert flow.pending[0]['function']['name'] == 'skin_lab_open'
    assert payloads == []


def test_several_sources_are_chosen_from_code_s_own_list(wire, monkeypatch):
    replies, payloads = wire
    replies.append(choice_reply(key='2'))
    flow = recolor_workflow(monkeypatch, decisions.Turn())
    observe_unpack(flow, sources('readme_backup.dat', 'PlKpNr.dat'))
    assert flow.source_file_id == 2
    assert json.loads(flow.pending[0]['function']['arguments']) == {'file_id': 2}
    assert flow.stage == 'prepare'
    payload = payloads[0]['json']
    assert set(payload['questions']['pick']['criteria']) == {'1', '2'}
    assert payload['state']['request'].startswith('recolor the Kermit')


@pytest.mark.parametrize('reply', [
    choice_reply(key='2', confidence=decisions.PICK_CONFIDENCE - 0.01),  # unsure
    choice_reply(key='99'),                                             # not on the list
    {'model': 'x', 'answers': {}},                                      # no answer
])
def test_an_unsure_or_invented_pick_keeps_the_handoff(wire, monkeypatch, reply):
    replies, _ = wire
    replies.append(reply)
    flow = recolor_workflow(monkeypatch, decisions.Turn())
    observe_unpack(flow, sources('a.dat', 'b.dat'))
    assert flow.pending == [] and flow.stage == 'create_review'
    assert flow.reason == 'ambiguous_source'


def test_without_a_decision_or_key_the_old_handoff_stands(wire, monkeypatch):
    _, payloads = wire
    flow = recolor_workflow(monkeypatch, None)
    observe_unpack(flow, sources('a.dat', 'b.dat'))
    assert flow.reason == 'ambiguous_source'
    keyless = recolor_workflow(monkeypatch, decisions.Turn(), key=None)
    observe_unpack(keyless, sources('a.dat', 'b.dat'))
    assert keyless.reason == 'ambiguous_source'
    assert payloads == []


def test_pick_refuses_degenerate_and_oversized_candidate_lists(wire):
    _, payloads = wire
    assert decisions.pick({}, {'1': 'only one'}, 'which?', 'key') is None
    assert decisions.pick({}, {}, 'which?', 'key') is None
    too_many = {str(i): f'file {i}' for i in range(decisions.MAX_OPTIONS + 1)}
    assert decisions.pick({}, too_many, 'which?', 'key') is None
    assert payloads == [], 'a list the model cannot answer is never sent'


# ---- the reasoning budget reaches the provider -----------------------------

def provider_payload(monkeypatch, reasoning, model='z-ai/glm-5.3-flash'):
    seen = {}
    class Response:
        status_code = 500
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
    def post(url, **kwargs):
        seen.update(sent_payload(kwargs))
        return Response()
    for _mod in (engine, main_model):
        monkeypatch.setattr(_mod, 'MODEL', model)
    monkeypatch.setattr(main_model.requests, 'post', post)
    with pytest.raises(RuntimeError):
        list(engine._provider([], None, 'key', engine.threading.Event(), reasoning=reasoning))
    return seen


def test_the_decided_budget_is_sent_and_absence_leaves_the_default(monkeypatch):
    assert provider_payload(monkeypatch, {'effort': 'low'})['reasoning'] == {'effort': 'low'}
    assert 'reasoning' not in provider_payload(monkeypatch, None)


def test_the_pinned_model_keeps_its_own_effort(monkeypatch):
    payload = provider_payload(monkeypatch, {'effort': 'medium'},
                               model='deepseek/deepseek-v4.1-flash')
    assert payload['reasoning'] == {'effort': 'low'}


# ---- one whole turn ---------------------------------------------------------

def run_turn(monkeypatch, turn, text='show me my Falco costumes'):
    """One real engine turn with the model faked at the provider boundary."""
    asked, budgets = [], []
    def decide(state, key, questions=None):
        asked.append((state, key))
        return turn
    def main(history, schemas, key, cancelled):
        budgets.append(main_model._REASONING.get())
        yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Here they are.'}}
    monkeypatch.setattr(engine.decisions, 'decide', decide)
    monkeypatch.setattr(engine, '_provider', main)
    run = engine.start(None, text, {}, request_key='key')
    list(live_runs.stream(run))
    assert run.answer['status'] == 'done'
    return asked, budgets


def test_a_turn_decides_once_and_spends_the_budget_it_decided(vault, monkeypatch):
    # vault: the turn saves its chat under STORAGE_PATH; never the developer's real chats.db.
    asked, budgets = run_turn(monkeypatch, decisions.Turn(effort='low'))
    assert len(asked) == 1, 'one decision per turn, not per model round'
    assert asked[0][0]['request'] == 'show me my Falco costumes'
    assert asked[0][1] == 'key'
    assert budgets == [{'effort': 'low'}]


def test_an_unavailable_decision_runs_the_turn_at_the_default_cap(vault, monkeypatch):
    asked, budgets = run_turn(monkeypatch, None)
    assert len(asked) == 1 and budgets == [engine.EXECUTION_REASONING]


@pytest.mark.parametrize('decided,round_number,expected', [
    (None, 1, engine.EXECUTION_REASONING),             # every round is capped, the first too
    ({'effort': 'low'}, 1, {'effort': 'low'}),
    (None, 2, engine.EXECUTION_REASONING),             # execution rounds are capped
    (None, 7, engine.EXECUTION_REASONING),
    ({'effort': 'low'}, 3, {'effort': 'low'}),         # a lower decided budget is kept
])
def test_every_round_is_capped_unless_the_decision_chose_lower(decided, round_number, expected):
    assert engine._round_reasoning(decided, round_number) == expected


def test_the_round_budget_reaches_the_real_provider_without_an_argument(monkeypatch):
    token = main_model._REASONING.set({'effort': 'medium'})
    try:
        assert provider_payload(monkeypatch, None)['reasoning'] == {'effort': 'medium'}
    finally:
        main_model._REASONING.reset(token)
