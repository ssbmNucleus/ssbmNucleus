"""The main model's streamed OpenRouter request: the model and its pinned providers, the bounds on one
streamed response, the reasoning budget for the round in flight, and the stop it raises."""

import contextvars
import json
import os
import time

import requests  # noqa: F401 -- tests stand in for requests.post through main_model.requests
from shared.aiengine import fast_lane as _fast_lane, model_upload
from .tasks import coordinator as taskflow


MODEL = os.environ.get('NUCLEUS_ASSISTANT_MODEL', 'z-ai/glm-5.3-flash')
# Providers to prefer for the default model. OpenRouter otherwise spreads a
# turn's rounds across ~30 GLM hosts, and each has its own prompt cache: a
# measured 4-round probe landed on three hosts with 0% cached. Pinned,
# Fireworks cached 75% of the prefix at ~1 s per request; Z.AI cached 99.6%
# but took ~4.5 s. Fallbacks stay on, so an outage costs a cache miss, not a turn.
PROVIDER_ORDER = [p for p in os.environ.get(
    'NUCLEUS_ASSISTANT_PROVIDERS', 'fireworks,z-ai' if MODEL == 'z-ai/glm-5.3-flash' else '').split(',') if p]
# Bounds on ONE streamed model response (see _provider): generous, so an honest
# long round finishes, but a keep-alive-only stream cannot hold a turn forever.
STREAM_LIFETIME_S = 15 * 60
STREAM_IDLE_S = 5 * 60          # without a single data line
# Pinned in every task's configuration snapshot: a run has to be reproducible
# against the whole roster that served it, not just the main model.
FAST_LANE_MODEL = _fast_lane.MODEL


# The main model's reasoning budget for the round in flight. Set by the turn
# loop and read by _provider, so provider stand-ins never have to accept it.
_REASONING = contextvars.ContextVar('randall_reasoning', default=None)


# A stopped turn's line is shown in the chat as Randall's own words: first person, plain, no
# provider or protocol terms, and what the user can do about it.
KEPT = 'Everything so far is kept. Say "continue" and I' + "'ll pick it up."
# A spending or request limit, and a request that had already wrapped up (`tasks/coordinator.py`).
LIMIT_REACHED = "I've hit my limit for this request. Everything so far is kept; ask again and I'll pick it up."
ALREADY_FINISHED = "I'd already wrapped up this request, so I stopped there. Ask again and I'll pick it up."
# The provider answered with an error status. Users never see the provider's name, keys, credits or money;
# the status stays on the exception (`http_status`, `diagnostic`) for the trace and the log.
UNREACHABLE = ("I couldn't reach my AI service just now. Try again in a moment; if it keeps happening, "
               'check Randall access in Settings.')
USED_UP = "This month's Randall usage is used up. It resets on its own; Settings shows when."


class TurnStopped(RuntimeError):
    """An unfinished turn with a user-visible reason, never a normal completion."""
    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


def _provider(messages, schemas, key, cancelled, reasoning=None):
    # The model allows 131k completion tokens; 4096 cut off ordinary answers that
    # explain a plan and then call a tool, and a cut-off turn still bills for
    # every token it generated. The real runaway guard is the size check below,
    # so this only has to be large enough to stop truncating honest replies.
    payload = {'model': MODEL, 'messages': messages, 'stream': True, 'max_tokens': 16384,
               'tools': schemas, 'tool_choice': 'auto' if schemas else 'none'}
    # This model otherwise defaults to high reasoning, which has exhausted the
    # completion allowance without yielding an answer in the rig review trial.
    # Keep reasoning enabled but leave room for an executable tool call/review.
    if MODEL == 'deepseek/deepseek-v4.1-flash':
        payload['reasoning'] = {'effort': 'low'}
    # Otherwise the served model thinks at its own default depth on every round,
    # including a one-file lookup. `reasoning` is this turn's decided budget and
    # is only ever lower than that default; None leaves the default in place.
    elif reasoning or _REASONING.get():
        payload['reasoning'] = reasoning or _REASONING.get()
    if not schemas:
        payload.pop('tools')
    if PROVIDER_ORDER:
        payload['provider'] = {'order': PROVIDER_ORDER, 'allow_fallbacks': True}
    # A round carries the turn's image evidence (1.6 MB of body on one fit's
    # fourteen pages), which used to have to upload inside the ten-second
    # connect timeout; post_json times the upload by progress instead, and
    # the traced provider's retry sends smaller pictures after a broken one.
    # That upload can now take a while, so Stop is checked between its blocks:
    # a Stop before the body is all out never reaches the model.
    try:
        sent = model_upload.post_json('https://openrouter.ai/api/v1/chat/completions', payload,
                                      headers={'Authorization': f'Bearer {key}', 'X-Title': 'SSBM Nucleus Assistant',
                                               'HTTP-Referer': 'https://ssbmnucleus.net'},
                                      stream=True, timeout=(10, 60), cancelled=cancelled)
    except model_upload.UploadCancelled:
        return
    with sent as response:
        if response.status_code != 200:
            # A structured error, not a bare RuntimeError: the retry policy has
            # to tell a transient 502 from a permanently bad key, and a flat
            # string makes every provider failure look permanent. The subclass
            # keeps the user-facing message handling below unchanged.
            # 402: the provider has no credit left for this key, which is this month's usage running out.
            raise taskflow.ProviderHTTPError(
                USED_UP if response.status_code == 402 else UNREACHABLE, http_status=response.status_code,
                diagnostic=f'AI provider returned HTTP {response.status_code}')
        calls, content, complete, size, wire_size = {}, '', False, 0, 0
        cost = usage = None
        finish_reason = None
        # OpenRouter names the generation and the host that served it on every
        # chunk. Dropping them left the trace unable to reconcile a charge
        # against the provider's own record, which is the only way an unknown
        # cost ever becomes a known one.
        generation_id = resolved_model = resolved_provider = ''
        # A three-minute cap used to stop long but honest rounds (a model
        # reasoning over a big fit result) and never caught a loop Randall
        # actually makes. What bounds a streamed response now: a silent socket
        # hits the 60-second read timeout above; a stream that sends only
        # keep-alive comments (": OPENROUTER PROCESSING" every few seconds
        # defeats that timeout) stops after STREAM_IDLE_S without a data line;
        # nothing streams past STREAM_LIFETIME_S; every byte, comment or data,
        # counts toward the transfer cap; and Stop is checked on every line.
        started = last_data = time.monotonic()
        for line in response.iter_lines(chunk_size=1):
            if cancelled.is_set():
                return
            wire_size += len(line or b'')
            if wire_size > 16_000_000:
                raise RuntimeError('That reply got too big for me to finish. Try asking for a smaller piece.')
            now = time.monotonic()
            if now - started > STREAM_LIFETIME_S or now - last_data > STREAM_IDLE_S:
                raise TurnStopped('response_timeout', 'My reply took too long, so I stopped. ' + KEPT)
            if not line or not line.startswith(b'data:'):
                continue
            last_data = now
            raw = line[5:].strip()
            if raw == b'[DONE]':
                break
            data = json.loads(raw)
            new_identity = not generation_id and data.get('id')
            generation_id = generation_id or str(data.get('id') or '')
            resolved_model = resolved_model or str(data.get('model') or '')
            resolved_provider = resolved_provider or str(data.get('provider') or '')
            if new_identity:
                # Identity too, and early: without it an unknown charge can
                # never be reconciled against the provider's own record.
                yield {'type': 'billing', 'generation_id': generation_id,
                       'model': resolved_model, 'provider': resolved_provider}
            if data.get('error'):
                raise RuntimeError('My reply was interrupted. Please try again.')
            # The usage block (with the billed cost) rides on the last chunk,
            # which usually carries no choices.
            if isinstance(data.get('usage'), dict):
                usage = data['usage']
                cost = usage.get('cost', cost)
                # Hand the charge over the moment it exists. Everything after
                # this point can still fail validation, and a round that billed
                # and then failed is still a round that billed: a stream with a
                # generation id and $0.04 of usage followed by an invalid tool
                # call used to produce a span with an unknown cost.
                yield {'type': 'billing', 'usage': usage, 'cost_usd': cost,
                       'generation_id': generation_id, 'model': resolved_model,
                       'provider': resolved_provider}
            choices = data.get('choices') or []
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get('delta') or {}
            text = delta.get('content') or ''
            size += len(text)
            if text:
                content += text
                yield {'type': 'delta', 'content': text}
            for part in delta.get('tool_calls') or []:
                index = part['index']
                if index not in calls:
                    if len(calls) >= 8:
                        raise RuntimeError('I tried to do too many things at once. Please try again.')
                    calls[index] = {'id': '', 'type': 'function', 'function': {'name': '', 'arguments': ''}}
                call = calls[index]
                call['id'] += part.get('id') or ''
                size += len(part.get('id') or '')
                for key_name in ('name', 'arguments'):
                    fragment = (part.get('function') or {}).get(key_name) or ''
                    call['function'][key_name] += fragment
                    size += len(fragment)
            if size > 500_000:
                raise RuntimeError('My reply got too long. Try a smaller request; anything I already finished is kept.')
            reason = choice.get('finish_reason')
            if reason:
                finish_reason = reason
                if reason not in ('stop', 'tool_calls'):
                    # Already-streamed prose remains in the transcript, but a
                    # token cutoff is not a completed task. Never replay tools.
                    raise TurnStopped('output_limit' if reason == 'length' else 'provider_stopped',
                        ('My reply ran too long, so I stopped. ' if reason == 'length'
                         else 'My reply was cut off before I finished. ') + KEPT)
                complete = True
        if not complete:
            raise TurnStopped('incomplete_stream', 'The connection dropped before I finished. ' + KEPT)
        if (finish_reason == 'tool_calls' and not calls) or (not calls and not content.strip()):
            raise TurnStopped('empty_response', "I didn't get an answer back that time. " + KEPT)
        for call in calls.values():
            try:
                valid = call['id'] and call['function']['name'] and isinstance(json.loads(call['function']['arguments']), dict)
            except (ValueError, TypeError):
                valid = False
            if not valid:
                raise TurnStopped('incomplete_tool_call', "My next step came through incomplete, so I didn't run it. "
                                 'Say "continue" and I' + "'ll try again.")
        yield {'type': 'completion', 'finish_reason': finish_reason, 'cost_usd': cost, 'usage': usage,
               'generation_id': generation_id, 'model': resolved_model, 'provider': resolved_provider,
               # The usage block was already emitted as a `billing` event, so
               # the turn must not count the same charge a second time.
               'billed_early': usage is not None,
               'message': {'role': 'assistant', 'content': content or None,
               **({'tool_calls': list(calls.values())} if calls else {})}}
