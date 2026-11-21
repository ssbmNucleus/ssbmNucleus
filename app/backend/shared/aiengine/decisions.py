"""One typed decision call per turn (TypeSafe Jev, through OpenRouter).

Jev is a decision-only model: it is handed the turn's state plus a fixed
battery of named questions and returns a typed answer with a probability for
each. It cannot emit text, tools or arguments, so nothing it says can become an
action. It does not route a turn: the main model answers every turn that is not
a declared recolor's acquisition (randall/recolor/workflows.py).

`effort` may only LOWER the main model's reasoning budget; 'high' is expressed
as "leave the model's own default alone". So a wrong answer there costs a
slower turn, never a wrong action.

The recolor acquisition answers (wants_vanilla, wants_website, variant_named)
and `pick` hold a higher bar: they WIDEN, offering a tool or allowing a call a
word list would have withheld. Their blast radius is deliberately small — everything they reach is a read-only open or
inspect, downloads stay behind the existing approval, and the ID checks in
_validate_acquisition still run on whatever comes back. Any failure —
flag off, no key, timeout, HTTP error, malformed body — returns None and the
existing regexes decide alone, exactly as they did before this module existed.
"""
import logging
import os
import threading
import time
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

MODEL = 'typesafe/jev-1.13'
URL = 'https://openrouter.ai/api/alpha/decisions'
# 70-500ms is the model's own budget; the ceiling here is the network. A turn
# that would otherwise start a multi-second reasoning round can afford this,
# but not much more, so a slow call is abandoned rather than waited out.
TIMEOUT = (3, 5)
# Acquisition gates that can only WIDEN — they offer a tool, or allow a call, a
# word list would have withheld. Being wrong there reaches for something extra
# rather than merely being slow, so the bar is high.
WIDEN_THRESHOLD = 0.75
# A choice code acts on directly. Below it the existing path decides instead.
PICK_CONFIDENCE = 0.70
# The model's own cardinality ceiling for one choice.
MAX_OPTIONS = 255
# The reasoning budget reads probability MASS, not the winning option's
# confidence. Confidence is a margin: a turn the model is certain needs no deep
# thinking, but which sits between 'low' and 'medium', reports low confidence
# while putting ~1% on 'high'. Only the mass on 'high' should protect the
# default budget; the low/medium split merely says how far to lower it.
HIGH_MASS = 0.15
LOW_MASS = 0.60
# Consecutive failures before the endpoint is left alone for a while. An alpha
# endpoint that starts refusing must not add its timeout to every single turn.
BREAKER_FAILURES = 3
BREAKER_COOLDOWN = 300

QUESTIONS = {
    'effort': {
        'type': 'choice',
        'instructions': 'How much reasoning does answering this request well require?',
        'criteria': {
            'low': 'a direct lookup, a single file inspection, a factual question about '
                   'the app, or continuing an obvious next step',
            'medium': 'a routine multi-step task with a clear path, such as finding a '
                      'costume and opening it, or applying a stated colour change',
            'high': 'open-ended creative work, visual judgment of a render, diagnosing a '
                    'broken model or texture, or planning an unfamiliar multi-part task',
        },
    },
    'wants_vanilla': {
        'type': 'noul',
        'instructions': "The costume the user is after is the game's own stock, "
                        'unmodified one, rather than a mod of it.',
        'criteria': {'true': 'the stock, base-game, original costume',
                     'false': 'a modded costume, or no particular costume'},
    },
    'wants_website': {
        'type': 'noul',
        'instructions': 'The user is pointing at the online mod site as the place to '
                        'look, rather than the costumes already in their local vault.',
        'criteria': {'true': 'look online / on the mod site',
                     'false': 'look in what they already have, or unstated'},
    },
    'variant_named': {
        'type': 'noul',
        'instructions': 'The user named ONE specific colour slot, variant or file of a '
                        "costume to use as the source. A desired FINAL colour is not a "
                        'source variant: "download Kermit and recolour it scarlet" names '
                        'no variant, while "use the red-slot one, then recolour" does.',
        'criteria': {'true': 'a specific existing variant/slot/file was named',
                     'false': 'no variant named, or only a desired end colour'},
    },
}


@dataclass(frozen=True)
class Turn:
    """One turn's answers. Fields are None when that answer was unusable."""
    effort: str = None
    vanilla: float = None
    website: float = None
    variant: float = None
    cost: float = 0.0
    seconds: float = 0.0
    # The trace id of the request that produced this answer, so the main rounds
    # that depend on it can name their dependency.
    span_id: str = ''

    def asks_vanilla(self):
        return self.vanilla is not None and self.vanilla >= WIDEN_THRESHOLD

    def asks_website(self):
        return self.website is not None and self.website >= WIDEN_THRESHOLD

    def names_variant(self):
        return self.variant is not None and self.variant >= WIDEN_THRESHOLD

    def reasoning(self):
        """The `reasoning` payload field for the main model, or None to leave the
        model's own default in place. Only ever reduces the budget."""
        return {'effort': self.effort} if self.effort in {'low', 'medium'} else None


@dataclass(frozen=True)
class Choice:
    """One pick from candidate keys code supplied."""
    key: str
    confidence: float
    cost: float = 0.0
    seconds: float = 0.0
    span_id: str = ''


class _Breaker:
    def __init__(self):
        self.failures = 0
        self.opened_at = 0.0
        self.lock = threading.Lock()

    def closed(self):
        with self.lock:
            if self.failures < BREAKER_FAILURES:
                return True
            if time.monotonic() - self.opened_at < BREAKER_COOLDOWN:
                return False
            self.failures = 0  # cooldown elapsed: allow one probe
            return True

    def record(self, ok):
        with self.lock:
            if ok:
                self.failures = 0
            else:
                self.failures += 1
                if self.failures == BREAKER_FAILURES:
                    self.opened_at = time.monotonic()
                    logger.info('Randall decisions: %s consecutive failures, pausing %ss',
                                self.failures, BREAKER_COOLDOWN)


_breaker = _Breaker()
_local = threading.local()


def _session():
    # Reusing the connection removes a TLS handshake from the turn's critical
    # path. Sessions are not thread-safe, so each worker keeps its own.
    session = getattr(_local, 'session', None)
    if session is None:
        session = _local.session = requests.Session()
    return session


def enabled():
    return os.environ.get('NUCLEUS_JEV_ROUTING', '1').lower() not in {'0', 'false', 'off'}


def reset():
    """Test hook: forget breaker state."""
    global _breaker
    _breaker = _Breaker()


def _noul(answers, name):
    answer = answers.get(name)
    if not isinstance(answer, dict) or answer.get('type') != 'noul':
        return None
    value = answer.get('noul')
    return float(value) if isinstance(value, (int, float)) and 0.0 <= value <= 1.0 else None


def _effort(answers):
    """The reasoning band to impose, or None to leave the model's default."""
    answer = answers.get('effort')
    if not isinstance(answer, dict) or answer.get('type') != 'choice':
        return None
    probabilities = answer.get('probabilities')
    if not isinstance(probabilities, dict):
        return None
    high, low = probabilities.get('high'), probabilities.get('low')
    if not isinstance(high, (int, float)) or not isinstance(low, (int, float)):
        return None
    if high >= HIGH_MASS:
        return None
    return 'low' if low >= LOW_MASS else 'medium'


def _ask(state, questions, key):
    """(answers, cost, seconds, span_id) or None. Never raises: a decision is optional.

    Recorded as a `jev` model span when a task is attached. This is the turn's
    first paid request, and it was invisible in the measured experiment's
    accounting; it is not now.

    Two orderings here are deliberate:

    * **Usage is recorded before the answer is validated.** A reply that billed
      and then failed our schema check is still a charge, and recording it after
      the `raise` lost it.
    * **No retry.** The router's documented behaviour on any failure is to fall
      through to the existing regexes, not to ask again -- so the span says
      `fallback_no_retry` rather than leaving a reader to wonder whether a retry
      was forgotten.
    """
    if not enabled() or not key or not _breaker.closed():
        return None
    from randall.assistant.tasks import coordinator as taskflow
    tick = time.monotonic()
    span_id = ''
    try:
        with taskflow.model_request('jev', requested_model=MODEL, task_family='routing',
                                    timeout_s=TIMEOUT[1], retry_policy='fallback_no_retry',
                                    max_attempts=1,
                                    prompt_template_version=taskflow.canonical_hash(questions),
                                    input_artifacts=[taskflow.canonical_hash(state)]) as span:
            span_id = span.span_id
            response = _session().post(
                URL, json={'model': MODEL, 'state': state, 'questions': questions},
                timeout=TIMEOUT,
                headers={'Authorization': f'Bearer {key}', 'X-Title': 'SSBM Nucleus Assistant',
                         'HTTP-Referer': 'https://ssbmnucleus.net'})
            span.http_status = getattr(response, 'status_code', None)
            response.raise_for_status()
            data = response.json()
            span.provider_generation_id = str(data.get('id') or '')
            span.resolved_model = str(data.get('model') or MODEL)
            span.resolved_provider = str(data.get('provider') or '')
            # Billing evidence first, validation second.
            span.record_usage(data.get('usage') or {})
            cost = (data.get('usage') or {}).get('cost')
            answers = data['answers']
            if not isinstance(answers, dict):
                span.response_validation = 'invalid_answers'
                raise ValueError('answers')
            span.response_validation = 'valid'
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        _breaker.record(False)
        logger.info('Randall decisions unavailable (%s: %s)', type(exc).__name__, exc)
        return None
    _breaker.record(True)
    return (answers, float(cost) if isinstance(cost, (int, float)) else 0.0,
            time.monotonic() - tick, span_id)


def decide(state, key, questions=None):
    """Answer this turn's battery, or None when the answers are unavailable.

    `state` is a small summary of the turn, not the conversation: the whole
    battery is evaluated against it in parallel, so it is sent once."""
    result = _ask(state, questions or QUESTIONS, key)
    if result is None:
        return None
    answers, cost, seconds, span_id = result
    turn = Turn(effort=_effort(answers),
                vanilla=_noul(answers, 'wants_vanilla'),
                website=_noul(answers, 'wants_website'),
                variant=_noul(answers, 'variant_named'),
                cost=cost, seconds=seconds, span_id=span_id)
    logger.info('Randall decision seconds=%.3f effort=%s vanilla=%s website=%s variant=%s '
                'cost=%.6f', turn.seconds, turn.effort, turn.vanilla, turn.website, turn.variant,
                turn.cost)
    return turn


def pick(state, options, instructions, key):
    """Choose one of CODE'S OWN candidate keys, or None to leave it to the
    existing path.

    `options` is {key: description}. The model picks a key from the map it was
    handed and code runs whatever that key means — it never writes an
    identifier, so a wrong answer is the wrong candidate from a real list, never
    an invented one. Below PICK_CONFIDENCE this declines rather than guesses.
    """
    options = dict(options)
    if not 2 <= len(options) <= MAX_OPTIONS:
        return None
    result = _ask(state, {'pick': {'type': 'choice', 'instructions': instructions,
                                   'criteria': options}}, key)
    if result is None:
        return None
    answers, cost, seconds, span_id = result
    answer = answers.get('pick')
    if not isinstance(answer, dict) or answer.get('choice') not in options:
        return None
    confidence = answer.get('confidence')
    if not isinstance(confidence, (int, float)) or confidence < PICK_CONFIDENCE:
        logger.info('Randall pick declined (confidence=%s of %s options)', confidence, len(options))
        return None
    logger.info('Randall pick seconds=%.3f key=%s confidence=%.2f cost=%.6f',
                seconds, answer['choice'], confidence, cost)
    return Choice(key=answer['choice'], confidence=float(confidence), cost=cost,
                  seconds=seconds, span_id=span_id)


def turn_state(user_text, working_state, receipts=(), view=None):
    """The minimal picture a routing question needs: what was asked, and what is
    already open. Conversation history and tool payloads are deliberately left
    out: the battery is answered against this small state, not the conversation."""
    return {
        'request': (user_text or '')[:4000],
        'open_edit_session': bool((working_state or {}).get('skin_sessions')),
        'recent_tools': [r.get('name') for r in list(receipts)[-6:] if r.get('name')],
        'selected_in_app': sorted(k for k, v in (view or {}).items() if v)[:12],
    }


