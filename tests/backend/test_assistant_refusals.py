"""A refusal says what it is, to the model and to the card; generated images have their own allowance.

The bug (2026-10-04, a Dream Land retexture): the recolour rounds used up most of the turn's 10-cent
cap, so every `generate_material` was refused by the coordinator before it was sent. The refusal
reached the model and the card as "The tool could not complete ... check the backend log", the model
retried it twice and told the user the swatch generator "keeps failing on the backend".

No provider is reached: the image endpoint is a stand-in that counts its requests, the main model
a generator that says what each round does.
"""
import base64
import io
import json

import pytest
from PIL import Image

from shared.aiengine import image_api
from randall.assistant import compaction, engine, live_runs, refusals, tools
from randall.assistant.tasks import coordinator, store
from randall.recolor import texture_material

THREE_IMAGES = 'This request already generated its three images; ask again in a new message to make more.'
USAGE_LIMIT = 'This request reached its usage limit, so this step did not run; send a new message to carry on.'


@pytest.fixture(autouse=True)
def fresh(vault, monkeypatch):
    store.close()
    coordinator.CURRENT.set(None)
    monkeypatch.setattr(coordinator, 'backoff', lambda attempt: 0)
    monkeypatch.setattr(engine, 'IMAGE_ALLOWANCE', 3)
    yield vault
    store.close()


def png():
    out = io.BytesIO()
    Image.new('RGBA', (8, 8), (40, 140, 40, 255)).save(out, format='PNG')
    return out.getvalue()


class Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, size):
        yield json.dumps(self.body).encode()


@pytest.fixture
def images(monkeypatch):
    """The image endpoint: every request it receives, each answered with one image billed $0.01."""
    received = []

    def post(url, **kwargs):
        received.append(kwargs['json']['prompt'])
        return Response({'id': f'gen-{len(received)}', 'data': [{'b64_json': base64.b64encode(png()).decode()}],
                         'usage': {'cost': 0.01}})
    monkeypatch.setattr(image_api.requests, 'post', post)
    return received


def material(n, prompt):
    return {'id': f'call-{n}', 'type': 'function',
            'function': {'name': 'generate_material', 'arguments': json.dumps({'prompts': [prompt]})}}


def completion(calls=None, cost=None, text=''):
    return {'type': 'completion', 'finish_reason': 'tool_calls' if calls else 'stop',
            **({'cost_usd': cost} if cost is not None else {}),
            'message': {'role': 'assistant', 'content': text or None, **({'tool_calls': calls} if calls else {})}}


def retexture(monkeypatch, kind):
    """This turn is a retexture whose lab session is open: budgeted (SKIN_MAX_COST) and narrowed."""
    if kind == 'recolor_stage':
        real = engine.StageStart

        class StageTurn(real):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.name, self.stage, self.opened = 'recolor_stage', 'create_review', True
                self.picked, self.session_id = {'stage_code': 'GrOp'}, 's' * 32
        monkeypatch.setattr(engine, 'StageStart', StageTurn)
        return
    real = engine.Workflow

    class SkinTurn(real):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.name, self.stage, self.session_id = 'recolor', 'create_review', 'b' * 32
    monkeypatch.setattr(engine, 'Workflow', SkinTurn)


def turn(monkeypatch, rounds, *, chat_id=None, text='a leaf pattern on the ground'):
    """One user turn: model round i does `rounds[i]` ((calls, cost)), then answers. -> (run, model inputs, events)"""
    seen = []

    def model(messages, *args, **kwargs):
        seen.append(json.loads(json.dumps(messages, default=str)))
        if len(seen) <= len(rounds):
            calls, cost = rounds[len(seen) - 1]
            yield completion(calls, cost)
        else:
            yield completion(cost=0.0, text='Here is what I did.')
    monkeypatch.setattr(engine, '_provider', model)
    run = engine.start(chat_id, text, {}, request_key='k')
    events = [json.loads(line[6:]) for line in live_runs.stream(run) if line.startswith('data: ')]
    return run, seen, events


def tool_reply(seen, call_id):
    """What the model read for one tool call."""
    return next(json.loads(m['content']) for inputs in seen for m in inputs
                if m.get('role') == 'tool' and m.get('tool_call_id') == call_id)


# --------------------------------------------------------------- images have their own allowance

@pytest.mark.parametrize('kind', ['recolor', 'recolor_stage'])
def test_a_retexture_turn_that_spent_its_text_cap_still_generates_a_material(monkeypatch, images, kind):
    retexture(monkeypatch, kind)
    # The round's own text spend is past the 10-cent cap; it still asks for a material.
    run, seen, _ = turn(monkeypatch, [([material(1, 'green leaves')], 0.12)])
    receipt = run.answer['tools'][0]
    assert receipt['name'] == 'generate_material' and receipt['status'] == 'done', receipt['result']
    assert receipt['result']['files'] and images == [image_api.SWATCH + 'green leaves']
    # ...and the text cap still stops the turn's next round, as before.
    assert run.answer['stop_reason'] == 'round_budget' and len(seen) == 1
    assert run.task.text_committed_usd == pytest.approx(0.12)
    assert run.task.committed_usd == pytest.approx(0.13)


def test_a_material_is_generated_early_in_a_retexture_whatever_its_reservation(monkeypatch, images):
    """The image's 5-cent reservation once needed half the 10-cent cap free: 6 cents of recolour
    rounds refused every material, although one costs about a cent."""
    retexture(monkeypatch, 'recolor_stage')
    run, seen, _ = turn(monkeypatch, [([material(1, 'leaves')], 0.06)])
    assert run.answer['tools'][0]['status'] == 'done' and len(images) == 1
    assert run.answer['status'] == 'done' and len(seen) == 2


def test_the_fourth_image_of_a_turn_is_refused_plainly_and_the_next_turn_has_three_again(monkeypatch, images):
    generated = []
    real = texture_material.generate_material

    def counted(*args, **kwargs):
        generated.append(1)
        return real(*args, **kwargs)
    monkeypatch.setitem(tools.REGISTRY, 'generate_material', tools.ToolSpec('automatic', counted))
    # An ordinary chat (no retexture): the allowance is every turn's.
    rounds = [([material(n, prompt)], 0.001) for n, prompt in enumerate(('moss', 'bark', 'fern', 'vine'), 1)]
    run, seen, events = turn(monkeypatch, rounds + [([material(5, 'vine')], 0.001), ([material(6, 'ivy')], 0.001)])
    receipts = run.answer['tools']
    assert [r['status'] for r in receipts] == ['done', 'done', 'done', 'error', 'error', 'error']
    assert len(images) == 3, 'the fourth image never reached the provider'
    refused = receipts[3]['result']
    assert refused['error'] == THREE_IMAGES and refused['refusal'] == 'image_allowance'
    # The model reads why, that retrying cannot work this turn, and what to tell the user.
    told = tool_reply(seen, 'call-4')
    assert told['error'] == THREE_IMAGES
    assert 'do not call generate_material again' in told['next'] and 'new message' in told['next']
    assert 'backend log' not in json.dumps(told)
    # A second identical call, and another of the same family, are answered without running.
    assert receipts[4]['result'] == refused and receipts[5]['result'] == refused
    assert len(generated) == 4 and len(images) == 3
    # The card's payload carries the same sentence.
    shown = [e['tool'] for e in events if e['type'] == 'tool_result' and e['tool']['id'] == receipts[3]['id']]
    assert shown[-1]['result']['error'] == THREE_IMAGES and shown[-1]['status'] == 'error'
    # The next message is a new turn with its own three images.
    again, _, _ = turn(monkeypatch, [([material(7, 'ivy')], 0.001)], chat_id=run.chat_id)
    assert again.answer['tools'][0]['status'] == 'done' and len(images) == 4


def test_image_spend_still_counts_everywhere_it_did(monkeypatch, images):
    rounds = [([material(n, prompt)], 0.002) for n, prompt in enumerate(('moss', 'bark'), 1)]
    run, _, _ = turn(monkeypatch, rounds)
    # The chat's cost (what the panel shows and the report carries), the task's ledger and its trace.
    assert run.answer['cost_parts']['images'] == pytest.approx(0.02)
    assert run.answer['cost_usd'] == pytest.approx(0.02 + 0.002 * 2)
    assert run.task.committed_usd == pytest.approx(0.024)
    book = store.accounting(run.answer['task_id'])
    assert book['reported_usd'] == pytest.approx(0.024)
    spans = [s for s in store.model_spans(run.answer['task_id']) if s.role == 'image']
    assert [s.reported_cost_usd for s in spans] == [pytest.approx(0.01)] * 2
    # Only the money guards leave the images out.
    assert run.task.text_committed_usd == pytest.approx(0.004)


def test_a_transient_status_bills_nothing_and_gives_its_image_back(monkeypatch):
    replies = [Response({'error': 'busy'}, status=400)]

    def post(*args, **kwargs):
        return replies.pop(0) if replies else Response({'data': [{'b64_json': base64.b64encode(png()).decode()}],
                                                        'usage': {'cost': 0.01}})
    monkeypatch.setattr(image_api.requests, 'post', post)
    task = coordinator.start('randall_turn', cost_budget_usd=0.0)
    task.allow_images(1)
    with coordinator.attach(task):
        pngs, metadata = image_api.generate_material_sheet(['denim'], key='k')
        assert pngs and metadata['cost_usd'] == 0.01, 'one allowed image, two dispatches: the 400 was refunded'
        assert task.images_left() == 0
        with pytest.raises(coordinator.ImageAllowanceReached):
            image_api.generate_material_sheet(['denim'], key='k')


def test_an_artwork_call_needing_more_images_than_are_left_is_refused_before_any_request(monkeypatch, images):
    task = coordinator.start('randall_turn')
    task.allow_images(3)
    with coordinator.attach(task):
        with pytest.raises(ValueError, match='has 3 generated images left and this call needs 4'):
            image_api.generate_material_sheet(['a', 'b', 'c', 'd'], key='k', style='artwork')
        assert images == []
        image_api.generate_material_sheet(['a', 'b', 'c'], key='k', style='artwork')
    assert len(images) == 3 and task.images_left() == 0


def test_without_an_allowance_an_image_spends_from_the_money_budget_as_before():
    task = coordinator.start('recolor', cost_budget_usd=0.01)
    with coordinator.attach(task):
        with pytest.raises(coordinator.BudgetExceeded) as refused:
            coordinator.run_model_request('image', lambda span: span.record_cost(0.12))
    assert refused.value.kind == 'spending' and not isinstance(refused.value, coordinator.ImageAllowanceReached)


# --------------------------------------------------------------- a budget refusal says itself

def nested_paid_request(calls):
    """A tool whose work makes a paid text request (a vision question, as a nested labeller asks)."""
    def run(**kwargs):
        calls.append(kwargs)
        coordinator.run_model_request('vision', lambda span: span.record_cost(0.001))
        return {'note': 'done'}
    return tools.ToolSpec('automatic', run)


def test_a_spending_refusal_reaches_the_model_and_the_card_and_is_not_retried(monkeypatch):
    retexture(monkeypatch, 'recolor')
    ran = []
    monkeypatch.setitem(tools.REGISTRY, 'generate_material', nested_paid_request(ran))
    # 9.6 cents of text: the vision question's reservation no longer fits under the 10-cent cap,
    # a chat round's still does.
    run, seen, events = turn(monkeypatch, [([material(1, 'leaves')], 0.096), ([material(2, 'leaves')], 0.0),
                                           ([material(3, 'bark')], 0.0)])
    receipts = run.answer['tools']
    first = receipts[0]['result']
    assert first['error'] == USAGE_LIMIT and first['refusal'] == 'spending_limit'
    # The budget's dollar figures are for the developer: "Report this chat" keeps them; the card and model never see them.
    assert first['diagnostic'].startswith('cost budget $0.10')
    told = tool_reply(seen, 'call-1')
    assert told['error'] == USAGE_LIMIT
    assert 'usage limit' in told['next'] and 'do not retry' in told['next'] and 'new message' in told['next']
    assert 'could not complete' not in json.dumps(told) and 'diagnostic' not in told
    shown = [e['tool'] for e in events if e['type'] == 'tool_result' and e['tool']['id'] == receipts[0]['id']]
    assert shown[-1]['result']['error'] == USAGE_LIMIT
    # The identical call and another of its family are answered from the refusal: the tool never runs.
    assert len(ran) == 1
    assert receipts[1]['result'] == first and receipts[2]['result'] == first


# --------------------------------------------------------------- an unexpected failure stays generic

def test_an_unexpected_failure_shows_the_generic_text_and_keeps_its_detail_off_the_model(monkeypatch):
    def broken(**kwargs):
        raise RuntimeError('internal detail C:/Users/someone/secret.dat')
    monkeypatch.setitem(tools.REGISTRY, 'generate_material', tools.ToolSpec('automatic', broken))
    run, seen, events = turn(monkeypatch, [([material(1, 'leaves')], 0.001)])
    result = run.answer['tools'][0]['result']
    assert result['error'] == refusals.GENERIC and 'refusal' not in result
    assert result['diagnostic'].startswith('RuntimeError: internal detail')
    told = tool_reply(seen, 'call-1')
    assert told == {'error': refusals.GENERIC}
    assert 'internal detail' not in json.dumps(seen)
    assert 'diagnostic' not in compaction.compact_receipt(run.answer['tools'][0]).get('result', {})
    # The report bundle keeps it.
    from randall.reports import chat_report
    entry = chat_report._mods_message(0, run.answer, {'args': 4000, 'result': 8000, 'content': 8000})['tools'][0]
    assert entry['diagnostic'].startswith('RuntimeError: internal detail')


def test_a_failure_around_the_tool_is_generic_too_and_names_no_exception_to_the_model(monkeypatch):
    def escaping(*args, **kwargs):
        raise KeyError('journal row')
    monkeypatch.setattr(engine, '_execute_tool', escaping)
    run, seen, _ = turn(monkeypatch, [([material(1, 'leaves')], 0.001)])
    assert tool_reply(seen, 'call-1') == {'error': refusals.GENERIC}
    assert run.answer['tools'][0]['result']['diagnostic'] == "KeyError: 'journal row'"


@pytest.mark.parametrize('exc,kind,status', [
    (coordinator.ImageAllowanceReached(3), 'image_allowance', 'error'),
    (coordinator.BudgetExceeded('This task hit its usage limit.', diagnostic='cost budget $0.10'), 'spending_limit',
     'error'),
    (coordinator.BudgetExceeded('This task reached its limit of 400 model requests.', kind='requests'),
     'request_limit', 'error'),
    (coordinator.TaskCancelled('The task was cancelled.'), 'stopped', 'cancelled'),
    (coordinator.RevisionSuperseded(1, 2), 'superseded', 'error'),
    (coordinator.TaskFinished('That task already finished as success; it cannot spend more.'), 'finished', 'error'),
    (coordinator.DispatchNotRecorded('the attempt could not be journalled, so it was not sent'),
     'not_recorded', 'error'),
])
def test_every_coordinator_refusal_has_its_own_plain_sentence(monkeypatch, exc, kind, status):
    def refusing(**kwargs):
        raise exc
    monkeypatch.setitem(tools.REGISTRY, 'generate_material', tools.ToolSpec('automatic', refusing))
    result = tools.execute(tools.prepare('generate_material', {'prompts': ['x']}))
    assert result['refusal'] == kind
    said = result.get('error') or result.get('note')
    assert said and '$' not in said and 'backend log' not in said and 'could not complete' not in said
    assert (result.get('approval_status') == 'cancelled') == (status == 'cancelled')
    assert 'diagnostic' not in compaction.model_view(result)
