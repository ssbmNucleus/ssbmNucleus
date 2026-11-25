""""Report this chat": one Randall conversation, sent privately to the developer.

The transport is the bug-report worker (`shared/diagnostics/bug_report.py` URL, the same
two-stage POST create + PUT zip), with `kind: "chat"` in the meta so the
private Discord ping reads as a chat report. `randall/routes/chat_reports.py` is
the HTTP surface and supplies the network callables; this module owns the
payload, the scrubbing, the size cap, the frozen bundle and the send state.

Rules, mirrored from the wish submission path (`reports/wishes.py`):

* **Review freezes; submit sends what was frozen.** `prepare()` builds the
  payload, scrubs it, zips it, writes the ZIP to disk and returns the disclosure
  manifest (every member's name, size, sha256) plus one `approval_hash` over the
  worker meta and that manifest. `submit()` re-reads the frozen file, checks its
  hash, and uploads exactly those bytes. Nothing is re-collected at send time.
* **Nothing is sent without an explicit `consent: true`** (a real boolean).
* **Idempotent retry into the same remote report.** The remote id from the
  create call is persisted BEFORE the upload, so a lost acknowledgment retries
  the upload into the same report instead of filing a second one; the worker
  answers that re-upload from its delivery receipt when the first one landed.
  A report is `sent` only on a 2xx from the worker, never inferred from a 404.
  A completed send answers a repeated click with its stored receipt.
* **Secrets never leave.** Every string in the bundle goes through the bug
  report scrubber (`core.log_redaction`: home-dir usernames, bearer tokens,
  OpenRouter/sk- keys, JWTs), any value under a credential-named key is
  replaced, and any credential-looking environment value is masked verbatim.
  The API key is never read into the payload in the first place: the budget
  block is an allowlist of numeric/status fields.
* **Size-capped.** Long tool results and arguments are cut with a visible
  `…[truncated N chars]` marker; inline data URIs are dropped; if the bundle is
  still over budget the caps shrink until it fits.
* **Files, on the user's say-so.** A mods conversation's model-import records
  (scrubbed text) always go; the files the user attached and the preview images
  Randall made go only with `include_files: true` (the modal's toggle, on by
  default), inside one compressed budget under the worker's 64 MB cap. What does
  not fit is listed by name, size and sha256 instead. Vanilla game files, vault
  items and anything outside the app's storage never go. The choice is part of
  the approval hash. See `reports/chat_report_files.py`.
"""
import io
import json
import os
import platform
import re
import sqlite3
import sys
import threading
import time
import uuid
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

from core import config, gates
from core.hashing import sha256_bytes, sha256_file
from core.log_redaction import redact_log_text

from . import chat_report_files as report_files

REPORT_VERSION = 1
KIND = 'chat'
SURFACES = ('mods', 'tracker')

NOTE_MAX = 4000
CONTACT_MAX = 200
#: Per-field caps, in characters. Halved (down to the floors) until the bundle
#: fits the budget.
CONTENT_MAX = 40_000
ARGS_MAX = 4_000
RESULT_MAX = 8_000
FLOOR = 256
#: Strings that look like inline binary (data: URIs, base64 images) above this
#: length are replaced outright -- they are never useful in a transcript.
INLINE_DATA_MIN = 200
#: Uncompressed budget, shared with the bug report path (see bundle_budget()).
DEFAULT_BUDGET = 48 * 1024 * 1024
TRANSCRIPT_PREVIEW_MAX = 60_000
MAX_SEND_ATTEMPTS = 5
LEASE_SECONDS = 300

# X.Y.Z, or with a prerelease tag (0.9.0-preview.7) -- the same shape the
# bug-report worker accepts, so secret-link test builds can send reports.
_APP_VERSION_RE = re.compile(r'^\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]{0,31})?$')
_CHAT_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
#: Keys whose VALUE is a credential wherever they appear in the conversation.
_SECRET_KEYS = frozenset((
    'api_key', 'apikey', 'key_value', 'token', 'access_token', 'refresh_token',
    'account_token', 'patreon_token', 'authorization', 'password', 'secret',
    'client_secret', 'openrouter_key', 'bearer',
))
#: The only entitlement fields a report may carry: ai-entitlement's current ones
#: (shared/account/entitlement.js; the budget fields are USD, which the developer
#: may see), plus `source` and the Tracker fuse's `spent`/`cap` (chatReport.js,
#: budgetFromEntitlement). `api_key` is deliberately absent: the budget SOURCE
#: and state are useful, the key never is.
BUDGET_FIELDS = ('source', 'active', 'linked', 'paused', 'patron_status', 'period_budget',
                 'remaining', 'usage', 'resets_at', 'spent', 'cap')
_ENV_SECRET_NAME = re.compile(r'(KEY|TOKEN|SECRET|PASSWORD)', re.IGNORECASE)
_BASE64_RE = re.compile(r'[A-Za-z0-9+/=\r\n]+')

_lock = threading.Lock()


class ReportError(ValueError):
    """A request that cannot become a report (unknown chat, bad field)."""


# ---------------------------------------------------------------------------
# scrubbing
# ---------------------------------------------------------------------------

def _known_secrets():
    """Credential-looking values from this process's environment, longest first.

    Masked verbatim wherever they appear, so a key that has no recognisable
    shape (a custom provider token) still cannot ride along in a tool result.
    """
    values = set()
    for name, value in os.environ.items():
        if _ENV_SECRET_NAME.search(name) and isinstance(value, str) and len(value.strip()) >= 16:
            values.add(value.strip())
    return sorted(values, key=len, reverse=True)


def scrub_text(text, secrets=None):
    """The bug-report scrubber plus verbatim masking of known secrets."""
    if not isinstance(text, str) or not text:
        return text
    for secret in (secrets if secrets is not None else _known_secrets()):
        if secret in text:
            text = text.replace(secret, '***')
    return redact_log_text(text)


def scrub(value, secrets=None, *, _key=None):
    """Recursively scrub every string; blank values under credential keys."""
    if secrets is None:
        secrets = _known_secrets()
    if isinstance(_key, str) and _key.lower() in _SECRET_KEYS and value not in (None, '', False):
        return '***'
    if isinstance(value, str):
        return scrub_text(value, secrets)
    if isinstance(value, dict):
        # Keys too: model-import records key their asset hashes by absolute path.
        # Only path-shaped keys: a structural key ("user", "counts") must never be
        # rewritten, or a username that is also a key name breaks the report.
        return {(scrub_text(k, secrets) if isinstance(k, str) and ('/' in k or '\\' in k) else k):
                scrub(v, secrets, _key=k)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v, secrets) for v in value]
    return value


# ---------------------------------------------------------------------------
# truncation
# ---------------------------------------------------------------------------

def clip(text, limit):
    """Cut `text` to `limit` chars with a marker saying how much was dropped."""
    if not isinstance(text, str):
        text = json.dumps(text, default=str, ensure_ascii=False)
    if len(text) <= limit:
        return text
    return text[:limit] + f'…[truncated {len(text) - limit} chars]'


def _drop_inline_data(value):
    """Replace data URIs / long base64 blobs anywhere in a structure."""
    if isinstance(value, str):
        if ((len(value) >= INLINE_DATA_MIN and value.startswith('data:'))
                or (len(value) > 2048 and _BASE64_RE.fullmatch(value[:4096]))):
            return f'[inline data omitted, {len(value)} chars]'
        return value
    if isinstance(value, dict):
        return {k: _drop_inline_data(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_drop_inline_data(v) for v in value]
    return value


def _scrub_json_text(text, secrets):
    """A string that may encode JSON (tracker tool arguments/results), scrubbed
    as the structure it encodes so credential keys inside it are still masked."""
    if text.lstrip()[:1] in ('{', '['):
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, (dict, list)):
            return json.dumps(scrub(parsed, secrets), default=str, ensure_ascii=False)
    return scrub_text(text, secrets)


def _scrubbed(value, secrets):
    """Scrub BEFORE any serialisation or cut: key masking needs the structure,
    and a cut can split a secret the text patterns would otherwise catch."""
    if isinstance(value, str):
        return _scrub_json_text(value, secrets)
    return scrub(value, secrets)


def _capped_json(value, limit, secrets=None):
    """A scrubbed JSON value kept as-is when small, else a truncated string of it."""
    value = _scrubbed(_drop_inline_data(value), secrets)
    text = json.dumps(value, default=str, ensure_ascii=False)
    if len(text) <= limit:
        return value
    return clip(text, limit)


def _capped_text(value, limit, secrets=None):
    """A scrubbed string cut to `limit` chars."""
    return clip(_scrubbed(value, secrets), limit)


# ---------------------------------------------------------------------------
# loading a conversation
# ---------------------------------------------------------------------------

def _load_mods_chat(chat_id):
    """The mods-side (assistant) conversation, including a turn still running."""
    import copy
    from randall.assistant import live_runs, store
    chat = store.get(chat_id)
    if not chat:
        return None
    running = False
    with live_runs._lock:
        runs = [run for run in live_runs._runs.values() if run.chat_id == chat_id]
        if runs:
            chat['messages'] = copy.deepcopy(runs[0].messages)
            running = True
    chat['running'] = running
    return chat


def _load_tracker_chat(chat_id):
    # The Tracker coach is its own gate ('randall'), and a build with the assistant
    # but not the coach leaves randall.coach out (core/build_smoke.py): no coach chat
    # exists there to report.
    if gates.enabled('randall'):
        from randall.coach import coach_store
        try:
            chat = coach_store.get_chat(int(chat_id))
        except (TypeError, ValueError):
            return None
        if chat:
            chat['running'] = False
        return chat
    return None


def _model_requests(task_ids):
    """Every traced model request for these tasks: routing (jev), fast lane,
    main model, side models -- with tokens and the provider's reported cost."""
    try:
        from randall.assistant.tasks import store as task_store
    except Exception:
        return {}
    keep = ('role', 'decision_id', 'task_revision', 'attempt', 'status', 'requested_model',
            'resolved_model', 'resolved_provider', 'start_utc', 'duration_ms', 'first_token_ms',
            'input_tokens', 'output_tokens', 'cached_input_tokens', 'reasoning_tokens',
            'reported_cost_usd', 'reconciled_cost_usd', 'cost_status', 'finish_reason',
            'http_status', 'provider_error', 'retry_classification', 'response_validation',
            'task_family')
    out = {}
    for task_id in task_ids:
        try:
            rows = task_store.spans(task_id, kind='model')
        except Exception as exc:  # a broken journal must not block the report
            out[task_id] = {'error': f'{type(exc).__name__}: {str(exc)[:200]}'}
            continue
        out[task_id] = [{k: row.get(k) for k in keep if k in row} for row in rows]
    return out


def _iso(ts):
    if not isinstance(ts, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec='seconds')
    except (OverflowError, OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# payload
# ---------------------------------------------------------------------------

def _mods_message(index, message, caps, secrets=None):
    from randall.assistant.compaction import model_view
    tools = []
    for tool in message.get('tools') or []:
        # what the model saw: the card-only keys (import_model's flow, ~50 KB) would spend the whole result cap
        result = model_view(tool.get('result'))
        entry = {
            'id': tool.get('id'), 'name': tool.get('name'), 'status': tool.get('status'),
            'started_at': _iso(tool.get('started_at')), 'elapsed_ms': tool.get('elapsed_ms'),
            'arguments': (_capped_json(tool.get('arguments'), caps['args'], secrets)
                          if 'arguments' in tool else None),
            'result': _capped_json(result, caps['result'], secrets) if result is not None else None,
        }
        if isinstance(result, dict) and result.get('error'):
            entry['error'] = _capped_text(str(result['error']), 1000, secrets)
        raw = tool.get('result')
        if isinstance(raw, dict) and raw.get('diagnostic'):     # card-only, so not in `result`: the exception itself
            entry['diagnostic'] = _capped_text(str(raw['diagnostic']), 1000, secrets)
        approval = tool.get('approval')
        if isinstance(approval, dict):
            entry['approval_status'] = approval.get('status')
        if tool.get('reused_operation'):
            entry['reused_operation'] = True
        tools.append(entry)
    context = message.get('context') or {}
    out = {
        'index': index, 'id': message.get('id'), 'role': message.get('role'),
        'at': _iso(message.get('at') or message.get('started_at')),
        'content': _capped_text(message.get('content') or '', caps['content'], secrets),
    }
    if message.get('role') == 'user':
        if context:
            out['context'] = {
                'page': context.get('page'),
                'selection_count': len(context.get('selection') or []),
                'files': [{'name': f.get('name'), 'bytes': f.get('size') or f.get('bytes')}
                          for f in (context.get('files') or []) if isinstance(f, dict)],
            }
        if message.get('input_kind'):
            out['input_kind'] = message['input_kind']
        return out
    for field in ('status', 'error', 'stop_reason', 'run_kind', 'model_rounds', 'round_limit',
                  'last_finish_reason', 'cost_usd', 'cost_parts', 'committed_usd', 'tokens',
                  'routing', 'task_id', 'task_revision', 'task_errors', 'empty_rounds',
                  'action_continuations', 'wrap_up_round'):
        if message.get(field) is not None:
            out[field] = message[field]
    out['tools'] = tools
    return out


def _tracker_message(index, message, caps, secrets=None):
    out = {'index': index, 'role': message.get('role'), 'at': _iso(message.get('at')),
           'content': _capped_text(message.get('content') or '', caps['content'], secrets)}
    if message.get('model'):
        out['model_key'] = message['model']
    if message.get('isError'):
        out['error'] = True
    trace = message.get('trace')
    if isinstance(trace, dict):
        out['trace'] = {
            # `error_detail`: a failed turn's exception, which the chat shows only as a plain sentence (coach_api).
            **{k: trace.get(k) for k in ('mode', 'model', 'nudged', 'tools_dropped', 'dropped', 'error_detail')
               if trace.get(k) is not None},
            'rounds': trace.get('rounds') or [],
            'tools': [{**tool,
                       'arguments': _capped_text(tool.get('arguments') or '', caps['args'], secrets),
                       'result': _capped_text(tool.get('result') or '', caps['result'], secrets)}
                      for tool in (trace.get('tools') or []) if isinstance(tool, dict)],
        }
    return out


def _randall_config(surface):
    """Which models/providers this build routes Randall through. No keys."""
    try:
        if surface == 'mods':
            from randall.assistant import main_model
            from shared.aiengine import decisions
            return {'main_model': main_model.MODEL, 'providers': list(main_model.PROVIDER_ORDER),
                    'router_model': decisions.MODEL, 'router_enabled': decisions.enabled(),
                    'fast_lane_model': main_model.FAST_LANE_MODEL}
        if gates.enabled('randall'):
            from randall.coach import coach_api
            return {'models': {k: v.get('model') for k, v in coach_api.COACH_MODELS.items()},
                    'default': coach_api.DEFAULT_COACH, 'spend': coach_api.spend_status()}
        return {'unavailable': 'coach not in this build'}
    except Exception as exc:
        return {'unavailable': f'{type(exc).__name__}'}


def _errors(messages):
    errors = []
    for m in messages:
        if m.get('role') == 'user':
            continue
        if isinstance(m.get('error'), str):
            errors.append({'message_index': m['index'], 'where': 'turn', 'error': m['error']})
        elif m.get('error') is True:
            errors.append({'message_index': m['index'], 'where': 'turn', 'error': m.get('content', '')[:1000]})
        for te in m.get('task_errors') or []:
            errors.append({'message_index': m['index'], 'where': 'task', 'error': te})
        for tool in m.get('tools') or []:
            if tool.get('error'):
                errors.append({'message_index': m['index'], 'where': f"tool:{tool.get('name')}",
                               'error': tool['error']})
        for tool in (m.get('trace') or {}).get('tools') or []:
            if tool.get('error'):
                errors.append({'message_index': m['index'], 'where': f"tool:{tool.get('name')}",
                               'error': tool['error']})
    return errors


def app_info(app_version):
    return {
        'version': app_version,
        'platform': config.bugreport_channel(),
        'os': platform.platform(terse=False),
        'machine': platform.machine(),
        'python': platform.python_version(),
        'frozen': bool(getattr(sys, 'frozen', False)),
    }


def clean_budget(budget):
    """Allowlisted entitlement fields only -- never the key."""
    if not isinstance(budget, dict):
        return None
    out = {}
    for field in BUDGET_FIELDS:
        value = budget.get(field)
        if isinstance(value, bool) or value is None:
            if value is not None:
                out[field] = value
        elif isinstance(value, (int, float)):
            out[field] = value
        elif isinstance(value, str) and len(value) <= 64:
            out[field] = value
    return out or None


def build_conversation(surface, chat, *, caps, app_version, budget=None, secrets=None):
    """The conversation record. `caps` bounds each long field; every capped
    field is scrubbed before it is cut, and the caller scrubs the whole record."""
    raw = chat.get('messages') or []
    if surface == 'mods':
        messages = [_mods_message(i, m, caps, secrets) for i, m in enumerate(raw) if isinstance(m, dict)]
        task_ids = list(dict.fromkeys(m['task_id'] for m in messages if m.get('task_id')))
        requests = _model_requests(task_ids)
    else:
        messages = [_tracker_message(i, m, caps, secrets) for i, m in enumerate(raw) if isinstance(m, dict)]
        requests = {}
    tool_calls = sum(len(m.get('tools') or []) + len((m.get('trace') or {}).get('tools') or [])
                     for m in messages)
    return {
        'report_version': REPORT_VERSION, 'kind': KIND, 'surface': surface,
        'conversation_id': str(chat.get('id')), 'title': chat.get('title'),
        'turn_running': bool(chat.get('running')),
        'app': app_info(app_version),
        'randall': _randall_config(surface),
        'budget': clean_budget(budget),
        'counts': {
            'messages': len(messages),
            'user': sum(1 for m in messages if m['role'] == 'user'),
            'assistant': sum(1 for m in messages if m['role'] == 'assistant'),
            'tool_calls': tool_calls,
        },
        'messages': messages,
        'model_requests': requests,
        'errors': _errors(messages),
        'caps': dict(caps),
    }


def transcript_markdown(conversation, note='', *, costs=True):
    """A readable rendering of conversation.json -- same data, for humans.

    ``costs=False`` leaves out each reply's dollar cost: the preview the user reads before sending
    (`prepare`). Users never see dollar amounts; the developer's copy (transcript.md) keeps them."""
    lines = [f"# Randall chat report ({conversation['surface']})", '',
             f"- Conversation: `{conversation['conversation_id']}` {conversation.get('title') or ''}".rstrip(),
             f"- App: {conversation['app']['version']} on {conversation['app']['os']}",
             f"- Messages: {conversation['counts']['messages']}, tool calls: "
             f"{conversation['counts']['tool_calls']}, errors: {len(conversation['errors'])}"]
    if conversation.get('turn_running'):
        lines.append('- A turn was still running when this was reported.')
    if note:
        lines += ['', '## What went wrong', '', note]
    lines += ['', '## Transcript', '']
    for m in conversation['messages']:
        who = 'You' if m['role'] == 'user' else 'Randall'
        stamp = f" · {m['at']}" if m.get('at') else ''
        extra = []
        if m.get('model_key'):
            extra.append(m['model_key'])
        routing = m.get('routing') or {}
        if routing.get('workflow'):
            extra.append(f"workflow {routing['workflow']}")
        if costs and m.get('cost_usd') is not None:
            extra.append(f"${m['cost_usd']}")
        if m.get('status') and m['status'] != 'done':
            extra.append(m['status'])
        lines.append(f"### {m['index']}. {who}{stamp}" + (f" ({', '.join(extra)})" if extra else ''))
        lines.append('')
        if m.get('content'):
            lines.append(m['content'])
            lines.append('')
        tools = list(m.get('tools') or []) + list((m.get('trace') or {}).get('tools') or [])
        for tool in tools:
            status = f" [{tool['status']}]" if tool.get('status') else ''
            lines.append(f"- tool `{tool.get('name')}`{status}")
            if tool.get('arguments') not in (None, ''):
                args = tool['arguments'] if isinstance(tool['arguments'], str) else json.dumps(tool['arguments'], ensure_ascii=False)
                lines.append(f"  - args: `{clip(args, 500)}`")
            if tool.get('error'):
                lines.append(f"  - error: {tool['error']}")
        if isinstance(m.get('error'), str):
            lines.append(f"> error: {m['error']}")
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def bundle_budget():
    """The bug report's own zip budget, so both reports share one ceiling."""
    try:
        return int(getattr(config, 'BUGREPORT_ZIP_BUDGET', DEFAULT_BUDGET))
    except Exception:
        return DEFAULT_BUDGET


def _packed(data):
    """Bytes a deflated member takes in the ZIP (data plus headers, roughly)."""
    compressor = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15)
    return len(compressor.compress(data)) + len(compressor.flush()) + 256


#: Room kept for report.json and files/manifest.json, which are written after
#: the files are chosen.
_MANIFEST_RESERVE = 512 * 1024


def build_bundle(surface, chat, *, note='', contact='', app_version, budget=None,
                 byte_budget=None, now=None, include_files=False, files_budget=None, reuse=None):
    """(zip_bytes, members, report, conversation). Scrubbed and size-capped.

    Members: `report.json` (note, contact, versions, counts), `conversation.json`
    (the full record) and `transcript.md` (the same, readable). The note lives
    only in report.json and transcript.md so the conversation member's hash
    identifies the conversation alone.

    A mods conversation that touched files adds `files/manifest.json` (every
    file considered: included, too large, not selected, left out and why),
    `files/records/*` (model-import records, scrubbed), and with
    `include_files` `files/images/*` and `files/attached/*`. The files part is
    in `report['_files']` (`summary`, `manifest`, `files_sha256`, `dropped`);
    `files_sha256` is computed from the bytes actually written.

    `reuse` (from `_reusable_files`) copies a previewed freeze's `files/`
    members byte for byte instead of collecting again, so Send transmits the
    files the user saw. The whole ZIP stays within `files_budget`; if even the
    manifest cannot fit, the files part is dropped.
    """
    byte_budget = byte_budget or bundle_budget()
    files_budget = files_budget or report_files.FILES_BUDGET
    secrets = _known_secrets()
    # From the whole conversation, before the size loop can drop old messages.
    collected = (_collect(chat, secrets, include_files)
                 if surface == 'mods' and reuse is None else None)
    caps = {'content': CONTENT_MAX, 'args': ARGS_MAX, 'result': RESULT_MAX}
    note = scrub_text((note or '').strip()[:NOTE_MAX], secrets)
    contact = scrub_text((contact or '').strip()[:CONTACT_MAX], secrets)
    truncated = False
    while True:
        conversation = scrub(build_conversation(surface, chat, caps=caps, app_version=app_version,
                                                budget=budget, secrets=secrets), secrets)
        conversation_bytes = json.dumps(conversation, indent=2, ensure_ascii=False,
                                        default=str).encode('utf-8')
        transcript = scrub_text(transcript_markdown(conversation, note), secrets).encode('utf-8')
        if len(conversation_bytes) + len(transcript) <= byte_budget:
            break
        truncated = True
        if all(v <= FLOOR for v in caps.values()):
            # Still too big at the floors: keep the newest messages that fit.
            chat = {**chat, 'messages': (chat.get('messages') or [])[1:]}
            if not chat['messages']:
                break
            continue
        caps = {k: max(FLOOR, v // 2) for k, v in caps.items()}
    report = {
        'kind': KIND, 'report_version': REPORT_VERSION, 'surface': surface,
        'conversation_id': conversation['conversation_id'],
        'submitted_at': datetime.fromtimestamp(now or time.time(), tz=timezone.utc).isoformat(timespec='seconds'),
        'note': note, 'contact': contact,
        'app': conversation['app'], 'budget': conversation['budget'],
        # True when ANY field was cut or dropped, not only when the budget bit.
        'truncated': bool(truncated or b'\xe2\x80\xa6[truncated ' in conversation_bytes
                          or b'[inline data omitted' in conversation_bytes),
        'counts': conversation['counts'],
    }
    if reuse is not None:
        try:
            blob, members = _write_bundle(report, conversation_bytes, transcript, reuse['manifest'],
                                          reuse['entries'], include_files, reuse['dropped'])
        except (report_files.FilesChanged, zipfile.BadZipFile, KeyError, OSError) as exc:
            raise ReportError('review_again') from exc
        if len(blob) > files_budget and reuse['entries']:
            raise ReportError('review_again')
        manifest, dropped = reuse['manifest'], reuse['dropped']
    else:
        for attempt in range(2):
            try:
                blob, members, manifest, dropped = _bundle_with_files(
                    report, conversation_bytes, transcript, collected, include_files, files_budget, secrets)
                break
            except report_files.FilesChanged:
                # A file changed between screening and writing: screen it again.
                report_files.forget_hashes()
                if attempt:
                    raise ReportError('files_changing')
                collected = _collect(chat, secrets, include_files)
    # Not written: report.json carries the short block.
    report['_files'] = {'manifest': manifest, 'summary': report_files.summary_from_manifest(manifest),
                        'dropped': dropped, 'files_sha256': _files_sha256(members, include_files)}
    return blob, members, report, conversation


def _collect(chat, secrets, include_files):
    """The conversation's files, or None. A failure never blocks a report the
    user asked to send without files; with files asked for it is refused plainly."""
    try:
        return report_files.collect(chat, lambda value: scrub(_drop_inline_data(value), secrets),
                                    screen=bool(include_files))
    except Exception as exc:                                    # noqa: BLE001
        if include_files:
            raise ReportError('files_unavailable') from exc
        return None


def _bundle_with_files(report, conversation_bytes, transcript, collected, include_files, files_budget, secrets):
    """(zip bytes, members, manifest, dropped): the files planned into the budget."""
    base = _packed(conversation_bytes) + _packed(transcript) + _MANIFEST_RESERVE
    chosen, manifest = [], None
    for _attempt in range(6):
        if collected is not None:
            chosen, manifest = report_files.plan(collected, base_bytes=base, include_files=include_files,
                                                 budget=files_budget)
            manifest = scrub(manifest, secrets)
        blob, members = _write_bundle(report, conversation_bytes, transcript, manifest,
                                      _manifest_entries(manifest) + chosen, include_files, False)
        # The plan counts exact deflate sizes; this only catches the reserve
        # being too small. Shrink the room for files and plan again.
        if len(blob) <= files_budget or not chosen:
            break
        base += len(blob) - files_budget + 256 * 1024
    if len(blob) > files_budget and _has_files(manifest):
        # Even the list of files does not fit: send the conversation without
        # its files part rather than an oversized bundle.
        blob, members = _write_bundle(report, conversation_bytes, transcript, None, [], include_files, True)
        return blob, members, None, True
    return blob, members, manifest, False


def _manifest_entries(manifest):
    if not _has_files(manifest):
        return []
    data = json.dumps(manifest, indent=1, ensure_ascii=False, default=str).encode('utf-8')
    return [{'path': 'files/manifest.json', 'name': 'manifest.json', 'data': data, 'bytes': len(data),
             'store': False}]


def _files_sha256(members, include_files):
    """Identifies the files part by the bytes written into the ZIP, and the choice."""
    written = [[m['name'], m['sha256']] for m in members if m['name'].startswith('files/')]
    canonical = json.dumps({'include_files': bool(include_files), 'members': written},
                           separators=(',', ':'), ensure_ascii=False)
    return sha256_bytes(canonical.encode('utf-8'))


def _short_files(summary, include_files, dropped):
    short = {'include_files': bool(include_files)}
    if dropped:
        short['dropped'] = 'the list of files was too large to send'
    if summary:
        short.update(records=len(summary['records']), images=len(summary['images']),
                     attachments=len(summary['attachments']), too_large=len(summary['too_large']),
                     left_out=len(summary['excluded']), unavailable=len(summary['unavailable']))
    return short


def _has_files(manifest):
    return bool(manifest and (manifest.get('files') or manifest.get('excluded') or manifest.get('unavailable')))


def _write_bundle(report, conversation_bytes, transcript, manifest, entries, include_files, dropped):
    """Write report.json (with the files summary), the conversation, the
    transcript, then `entries` (the files part, manifest first). Members carry
    the sha256 of the bytes written."""
    report['files'] = _short_files(report_files.summary_from_manifest(manifest), include_files, dropped)
    report_bytes = json.dumps(report, indent=2, ensure_ascii=False, default=str).encode('utf-8')
    buffer = io.BytesIO()
    members = []
    # Fixed timestamps: the same inputs give the same bytes.
    stamp = (2020, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in (('report.json', report_bytes), ('conversation.json', conversation_bytes),
                           ('transcript.md', transcript)):
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
            members.append({'name': name, 'bytes': len(data), 'sha256': sha256_bytes(data)})
        for entry in entries:
            written = report_files.write_member(archive, entry, stamp)
            members.append({'name': entry['path'], 'bytes': entry['bytes'], 'sha256': written})
    return buffer.getvalue(), members


def files_references(surface, chat):
    """A digest of the files this conversation refers to: its attachments and
    the model candidates, alignments and files its tools touched. A previewed
    files part is only reused while this is unchanged."""
    if surface != 'mods':
        return sha256_bytes(b'[]')
    refs = [sorted(group) for group in report_files.references(chat)]
    return sha256_bytes(json.dumps(refs, separators=(',', ':')).encode('utf-8'))


def _frozen_path(row):
    """The previewed ZIP's path once its sha256 (streamed, never read whole) matches."""
    path = Path(row['bundle_path'])
    try:
        digest = sha256_file(path)
    except OSError as exc:
        raise ReportError('review_again') from exc
    if digest != row['bundle_sha256']:
        raise ReportError('review_again')
    return path


def _reusable_files(base_submission, surface, conversation_id, include_files, chat):
    """The `files/` members of a previewed freeze, for Send to copy byte for byte.

    Nothing is read into memory but the small manifest: each entry names the
    member in the previewed ZIP, which `write_member` streams across and checks
    against the sha256 the preview recorded. Refuses with `review_again` when
    that freeze is not this conversation, was made with the other toggle
    setting, the conversation now refers to other files (a new attachment, a
    new fit), or its bytes are gone or changed."""
    row = submission(base_submission) if re.fullmatch(r'[a-f0-9]{32}', str(base_submission)) else None
    if not row or row['surface'] != surface or row['conversation_id'] != conversation_id:
        raise ReportError('review_again')
    approved = json.loads(row['manifest'])
    if approved.get('include_files', False) != include_files:
        raise ReportError('review_again')
    if approved.get('files_references') != files_references(surface, chat):
        raise ReportError('review_again')
    path = _frozen_path(row)
    expected = {m['name']: m['sha256'] for m in approved.get('members') or []}
    entries, manifest = [], None
    try:
        with zipfile.ZipFile(path) as archive:
            dropped = bool((json.loads(archive.read('report.json')).get('files') or {}).get('dropped'))
            for info in archive.infolist():
                if not info.filename.startswith('files/'):
                    continue
                if info.filename not in expected:
                    raise ReportError('review_again')
                entries.append({'path': info.filename, 'name': info.filename, 'zip_source': path,
                                'member': info.filename, 'bytes': info.file_size,
                                'sha256': expected[info.filename],
                                'store': info.compress_type == zipfile.ZIP_STORED})
                if info.filename == 'files/manifest.json':
                    manifest = json.loads(archive.read(info))
    except (zipfile.BadZipFile, KeyError, ValueError, OSError) as exc:
        raise ReportError('review_again') from exc
    return {'entries': entries, 'manifest': manifest, 'dropped': dropped}


def describe(conversation, report):
    """Plain-language lines for the "What gets sent" preview."""
    counts = conversation['counts']
    lines = [
        f"This conversation: {counts['user']} of your messages and {counts['assistant']} of "
        f"Randall's replies, with timestamps.",
    ]
    if counts['tool_calls']:
        lines.append(f"{counts['tool_calls']} tool call(s) Randall made, with their inputs and "
                     'results (long results are shortened).')
    lines.append('Which model and route answered each turn, with usage figures for debugging.')
    if conversation['errors']:
        lines.append(f"{len(conversation['errors'])} error(s) from the conversation.")
    app = conversation['app']
    lines.append(f"App version {app['version']}, {app['os']}.")
    if conversation.get('budget'):
        lines.append('Your monthly Randall usage, for debugging (never your key).')
    lines.append('Your note and contact, if you add them.')
    if report.get('truncated'):
        lines.append('Some long parts were shortened to keep the report small.')
    files = report.get('_files') or {}
    lines += describe_files(files.get('summary'), dropped=files.get('dropped'))
    return lines


def _named(entries):
    return ', '.join(f"{e['name']} ({report_files.mb(e['bytes'])})" for e in entries)


def describe_files(summary, dropped=False):
    """Plain-language lines for the files part of the report."""
    if dropped:
        return ['The list of files in this chat was too long to send, so only the conversation is sent.']
    if not summary:
        return []
    lines = []
    if summary['records']:
        lines.append(f"Randall's model import notes for this chat ({len(summary['records'])} file(s): "
                     'the fit, review and export results), cleaned like the rest.')
    if summary['images']:
        size = report_files.mb(sum(e['bytes'] for e in summary['images']))
        lines.append(f"{len(summary['images'])} preview picture(s) Randall made of your model ({size}).")
    if summary['attachments']:
        lines.append(f"The file(s) you attached, exactly as they are: {_named(summary['attachments'])}.")
    for entry in summary['too_large']:
        lines.append(f"Too large to include: {entry['name']} ({report_files.mb(entry['bytes'])}). "
                     'Only its name, size and list of contents are sent.')
    if not summary['include_files'] and summary['offer_count']:
        lines.append("You turned off your attached files, so they and Randall's preview pictures "
                     'are not sent (only their names and sizes).')
    for entry in summary['excluded']:
        lines.append(f"Never sent: {entry['name']} ({entry['reason']}).")
    for entry in summary['unavailable']:
        reason = entry.get('reason') or 'could not be read'
        verb = 'is ' if reason.startswith('no longer') else ''
        lines.append(f"{entry['name']} {verb}{reason}, so it can't be included.")
    return lines


NOT_INCLUDED = ('Your API key, passwords and sign-in tokens (they are removed if they appear).',
                'Your replay files, your vault, your game ISO and the game files taken from it, '
                'and app logs.',
                'Your computer username (paths are masked).')


# ---------------------------------------------------------------------------
# frozen submissions
# ---------------------------------------------------------------------------

_SCHEMA = '''
CREATE TABLE IF NOT EXISTS chat_report_submissions (
    submission_id TEXT PRIMARY KEY,
    surface TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    approval_hash TEXT NOT NULL,
    bundle_sha256 TEXT NOT NULL,
    bundle_path TEXT NOT NULL,
    meta TEXT NOT NULL,
    manifest TEXT NOT NULL,
    state TEXT NOT NULL,
    remote_id TEXT,
    upload_attempted INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_until REAL,
    receipt TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
'''


def _root():
    directory = config.STORAGE_PATH / 'assistant' / 'chat_reports'
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _connect():
    conn = sqlite3.connect(_root() / 'submissions.db', timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=15000')
    conn.executescript(_SCHEMA)
    return conn


def submission(submission_id):
    conn = _connect()
    try:
        row = conn.execute('SELECT * FROM chat_report_submissions WHERE submission_id=?',
                           (submission_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def approval_hash(meta, manifest):
    canonical = json.dumps({'meta': meta, 'manifest': manifest}, sort_keys=True,
                           separators=(',', ':'), ensure_ascii=False)
    return sha256_bytes(canonical.encode('utf-8'))


def valid_app_version(value):
    value = (value or '').strip()
    return value if _APP_VERSION_RE.match(value) else ''


def prepare(surface, conversation_id, *, note='', contact='', app_version, budget=None,
            byte_budget=None, loader=None, include_files=False, files_budget=None,
            base_submission=None):
    """Freeze the complete outgoing report and return it for approval.

    Nothing is sent. Returns the submission id to quote back, the approval
    hash, the disclosure manifest, the plain-language preview and the readable
    transcript (so the user can see what the developer will see; only each
    reply's dollar cost is left out of it, which `includes` names as usage
    figures for debugging).
    `include_files` must be the boolean True for the user's attachments and
    Randall's preview images to go; it is part of the approval hash.
    `base_submission` (Send) is the previewed freeze: its files part is reused
    byte for byte, and `review_again` is raised if that is no longer possible.
    """
    include_files = include_files is True
    if surface not in SURFACES:
        raise ReportError('unknown_surface')
    conversation_id = str(conversation_id or '').strip()
    if not _CHAT_ID_RE.match(conversation_id):
        raise ReportError('unknown_conversation')
    app_version = valid_app_version(app_version)
    if not app_version:
        raise ReportError('app_version_unknown')
    load = loader or (_load_mods_chat if surface == 'mods' else _load_tracker_chat)
    chat = load(conversation_id)
    if not chat or not chat.get('messages'):
        raise ReportError('unknown_conversation')
    reuse = (_reusable_files(base_submission, surface, conversation_id, include_files, chat)
             if base_submission else None)
    bundle, members, report, conversation = build_bundle(
        surface, chat, note=note, contact=contact, app_version=app_version,
        budget=budget, byte_budget=byte_budget, include_files=include_files,
        files_budget=files_budget, reuse=reuse)
    files_block = report['_files']
    model = None
    if surface == 'mods':
        model = (conversation['randall'] or {}).get('main_model')
    else:
        model = next((m.get('model_key') for m in reversed(conversation['messages'])
                      if m.get('model_key')), None) or (conversation['randall'] or {}).get('default')
    meta = {
        'kind': KIND,
        'app_version': app_version,
        'platform': conversation['app']['platform'],
        # The worker requires a description; an empty note still files.
        'description': report['note'] or 'Randall chat report (no note)',
        'contact': report['contact'],
        'zip_size': len(bundle),
        'truncated': bool(report['truncated']),
        'chat': {'surface': surface, 'message_count': conversation['counts']['messages'],
                 'tool_calls': conversation['counts']['tool_calls'],
                 'errors': len(conversation['errors']),
                 'conversation_id': conversation['conversation_id'][:64],
                 'model': (model or '')[:80]},
    }
    manifest = {'members': members, 'bundle': {'bytes': len(bundle), 'sha256': sha256_bytes(bundle)},
                'include_discord_identity': False,
                # The toggle and every file decision (included, too large, not
                # selected, never sent) are covered by the approval hash.
                'include_files': include_files,
                'files_sha256': files_block['files_sha256'],
                # Which files the conversation referred to when this was frozen:
                # Send reuses these files only while that is unchanged.
                'files_references': files_references(surface, chat)}
    submission_id, digest = freeze(surface, conversation_id, bundle=bundle, meta=meta, manifest=manifest)
    # The frozen transcript.md with each reply's cost left out: the same scrubbed conversation and note.
    transcript = scrub_text(transcript_markdown(conversation, report['note'], costs=False))
    return {
        'submission_id': submission_id,
        'approval_hash': digest,
        'manifest': manifest,
        'meta': meta,
        'includes': describe(conversation, report),
        'not_included': list(NOT_INCLUDED),
        'transcript': clip(transcript, TRANSCRIPT_PREVIEW_MAX),
        'conversation_sha256': next(m['sha256'] for m in members if m['name'] == 'conversation.json'),
        'files_sha256': files_block['files_sha256'],
        'files': _files_view(files_block['summary'], include_files),
        'counts': conversation['counts'],
        'truncated': bool(report['truncated']),
        'turn_running': conversation['turn_running'],
    }


def freeze(surface, conversation_id, *, bundle, meta, manifest):
    """Write one frozen submission, its ZIP and its row, and return (submission_id, approval_hash).

    Nothing is sent: `submit()` sends exactly these bytes once the approval hash
    comes back with `consent: true`. "Report this chat" (`prepare`) and an AI's
    problem report (`problem_report.review`) both freeze here, so both go through
    the same submit, worker, lease and retry rules. `manifest['bundle']['sha256']`
    must be the ZIP's."""
    digest = approval_hash(meta, manifest)
    submission_id = uuid.uuid4().hex
    path = _root() / f'{submission_id}.zip'
    path.write_bytes(bundle)
    now = time.time()
    conn = _connect()
    try:
        _prune(conn, now)
        conn.execute('INSERT INTO chat_report_submissions (submission_id,surface,conversation_id,'
                     'approval_hash,bundle_sha256,bundle_path,meta,manifest,state,created_at,updated_at) '
                     'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                     (submission_id, surface, conversation_id, digest, manifest['bundle']['sha256'],
                      str(path), json.dumps(meta), json.dumps(manifest), 'frozen', now, now))
    finally:
        conn.close()
    return submission_id, digest


def _files_view(summary, include_files):
    """What the modal needs for the toggle: is there anything to offer, and how
    much of it goes when it is on."""
    if not summary:
        return {'include_files': include_files, 'offer_count': 0, 'send_bytes': 0, 'too_large': []}
    sent = [*summary['images'], *summary['attachments']]
    return {'include_files': include_files, 'offer_count': summary['offer_count'],
            'send_bytes': sum(e['bytes'] for e in sent),
            'too_large': [{'name': e['name'], 'bytes': e['bytes']} for e in summary['too_large']]}


#: A frozen ZIP may now be tens of MB, and one is frozen on every open, toggle
#: and Send. Unsent ones are dropped after a day, sent ones after an hour (a
#: repeated click on a sent report answers from its receipt, not the file).
UNSENT_KEEP_SECONDS = 24 * 3600
SENT_KEEP_SECONDS = 3600


def _prune(conn, now):
    rows = conn.execute("SELECT submission_id, bundle_path, state, updated_at FROM chat_report_submissions "
                        "WHERE state != 'sending' AND updated_at < ?", (now - SENT_KEEP_SECONDS,)).fetchall()
    for row in rows:
        keep = SENT_KEEP_SECONDS if row['state'] == 'sent' else UNSENT_KEEP_SECONDS
        if row['updated_at'] >= now - keep:
            continue
        path = Path(row['bundle_path'])
        try:
            if path.parent.resolve() == _root().resolve() and path.suffix == '.zip':
                path.unlink(missing_ok=True)
        except OSError:
            pass


def frozen_bundle(row):
    """The exact bytes that were approved, or ReportError if they changed."""
    try:
        data = open(row['bundle_path'], 'rb').read()
    except OSError as exc:
        raise ReportError('bundle_missing') from exc
    if sha256_bytes(data) != row['bundle_sha256']:
        raise ReportError('bundle_changed')
    return data


class TransportRefused(RuntimeError):
    """The report server answered with a refusal (status + parsed body)."""

    def __init__(self, message, *, status=None, detail=None):
        super().__init__(message)
        self.status = status
        self.detail = detail or {}


def _refusal(exc):
    """Normalise the wish transport's refusal type and ours into (status, detail)."""
    return getattr(exc, 'status', None), getattr(exc, 'detail', None) or {}


def _update(conn, submission_id, **fields):
    fields['updated_at'] = time.time()
    names = ','.join(f'{k}=?' for k in fields)
    conn.execute(f'UPDATE chat_report_submissions SET {names} WHERE submission_id=?',
                 (*fields.values(), submission_id))


def submit(submission_id, *, approval_hash_presented, consent, create, upload, now=None):
    """Send one frozen report. Returns a dict with `state` and details.

    `create(meta) -> remote_id` and `upload(remote_id, bytes) -> {'notified': bool}`
    raise a refusal carrying `.status`/`.detail` for an HTTP refusal and any
    other exception for a network failure.

    States: `sent` | `failed` (retryable; `retry` says so) | `refused`.
    """
    if consent is not True:
        return {'state': 'refused', 'reason': 'consent_required'}
    now = now or time.time()
    conn = _connect()
    try:
        with _lock:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM chat_report_submissions WHERE submission_id=?',
                               (submission_id,)).fetchone()
            if row is None:
                conn.execute('ROLLBACK')
                return {'state': 'refused', 'reason': 'unknown_submission'}
            row = dict(row)
            if row['approval_hash'] != approval_hash_presented:
                conn.execute('ROLLBACK')
                return {'state': 'refused', 'reason': 'consent_invalid'}
            if row['state'] == 'sent' and row['receipt']:
                conn.execute('ROLLBACK')
                return {'state': 'sent', 'reason': 'already_sent', **json.loads(row['receipt'])}
            if row['state'] == 'sending' and (row['lease_until'] or 0) > now:
                conn.execute('ROLLBACK')
                return {'state': 'refused', 'reason': 'already_sending'}
            if row['attempts'] >= MAX_SEND_ATTEMPTS:
                conn.execute('ROLLBACK')
                return {'state': 'refused', 'reason': 'retries_exhausted'}
            _update(conn, submission_id, state='sending', lease_until=now + LEASE_SECONDS,
                    attempts=row['attempts'] + 1)
            conn.execute('COMMIT')
    finally:
        conn.close()

    def finish(state, **fields):
        c = _connect()
        try:
            _update(c, submission_id, state=state, lease_until=None, **fields)
        finally:
            c.close()

    try:
        bundle = frozen_bundle(row)
    except ReportError as exc:
        finish('failed')
        return {'state': 'refused', 'reason': str(exc)}

    meta = json.loads(row['meta'])
    remote_id = row['remote_id']
    stage = 'create'
    try:
        if not remote_id:
            remote_id = create(meta)
            if not remote_id:
                raise TransportRefused('report server returned no id', status=502)
            # Persist BEFORE the upload: a lost acknowledgment must retry into
            # this same report, not file a second one.
            c = _connect()
            try:
                _update(c, submission_id, remote_id=remote_id)
            finally:
                c.close()
        stage = 'upload'
        c = _connect()
        try:
            _update(c, submission_id, upload_attempted=1)
        finally:
            c.close()
        acknowledgment = upload(remote_id, bundle) or {}
    except Exception as exc:                                     # noqa: BLE001
        status, detail = _refusal(exc)
        if status is None:
            finish('failed')
            return {'state': 'failed', 'reason': 'transport_error', 'retry': True,
                    'detail': {'error': str(exc)[:300]}}
        if stage == 'upload' and status in (404, 410):
            # No slot and no delivery receipt under this id. The worker answers
            # a re-upload of a STORED report with 200 from its completion
            # marker, so a 404 is never proof of delivery: the slot expired
            # (perhaps on an earlier attempt whose 410 was lost) or never
            # existed. The next attempt files a new report.
            finish('failed', remote_id=None, upload_attempted=0)
            return {'state': 'failed', 'reason': 'slot_expired', 'retry': True, 'status': status}
        finish('failed')
        return {'state': 'failed', 'reason': 'transport_refused', 'status': status,
                'detail': detail, 'retry': status not in (400, 413, 426)}
    receipt = {'id': remote_id, 'notified': bool(acknowledgment.get('notified')),
               'confirmed': True, 'size': len(bundle)}
    finish('sent', receipt=json.dumps(receipt))
    return {'state': 'sent', **receipt}
