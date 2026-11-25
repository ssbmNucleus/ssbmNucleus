"""An AI's problem report (MCP ``report_problem``): written by the user's own AI, sent only by the user.

The user's AI (an MCP client: Claude Code, Codex...) can say "this went wrong" with ``report_problem``: a short
title, a markdown write-up (at most ``MARKDOWN_MAX``) and, optionally, what it is about BY ID: a model import job
(``job_id``, an ``mcp_model_import`` job), a model import (``import_id``, its folder under the imports root) and a
Randall chat (``chat_id``). Never a path: Nucleus finds the files itself from those ids. The AI may also say its
own model name and reasoning effort.

**Nothing is sent by the call.** ``create`` assembles the package on this computer
(``<storage>/assistant/problem_reports/<id>/``) and the report waits for the person at the window. The window lists
it (``GET /api/mcp/window/problem-reports``, the window-only key) and shows the markdown and every attachment with
its size, with a checkbox for each optional one, and Send and Discard. Send freezes the chosen parts into one ZIP
as a "Report this chat" submission (``review`` -> ``chat_report.freeze``: an approval hash over the worker meta and
the manifest), and the window sends that through the chat report's own submit (``POST
/api/mex/chat-reports/submit``, window only, ``consent: true``): the same worker, transport, lease and retry
rules, filed as a chat report whose surface is ``mcp``. The AI learns the outcome with ``problem_report_status``:
waiting for the user, sent, discarded or expired.

The package:

* ``report.md``: the AI's write-up, scrubbed (always);
* ``metadata.json``: the title, the ids, the AI's model and effort as it gave them, versions (Nucleus, Python, the
  OS, the model import tools' state), the import's timings and its error output (the job's error, the importer's
  failure fields, the last lines of its log), scrubbed (always);
* optional, each with its checkbox: the import's records (the job record, ``workflow/job.json``,
  ``rigswap/result.json``, the ``randall.jsonl`` ledger, the newest part of ``workflow/job.log``), the newest part of
  Nucleus's own log, the chat's transcript, the import's preview pictures, and the source model file (not ticked
  at first: it is the user's own model).

Text is scrubbed with the chat report's scrubber (user names in home-folder paths, tokens, keys, credential-looking
environment values: ``chat_report.scrub`` / ``scrub_text``). Every part is copied into the report's folder when the
report is made and hashed; Send checks each hash, so what goes is what the window showed. A file over
``ATTACHMENT_MAX``, or past ``TOTAL_MAX`` for the report, is listed by name and size and never sent. Disc images and
files from the user's game (``chat_report_files.excluded_reason``) are never collected.

Limits: ``PENDING_MAX`` reports waiting at once and ``PER_HOUR`` made in an hour; one nobody sends within
``PENDING_KEEP`` is dropped (expired); an ended one is forgotten after ``ENDED_KEEP``.
"""
import io
import json
import logging
import os
import platform
import re
import shutil
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from core import config
from core.hashing import sha256_bytes, sha256_file

from . import chat_report

REPORT_VERSION = 1
SURFACE = 'mcp'
DESCRIPTION = 'AI problem report'
TITLE_MAX = 120
MARKDOWN_MAX = 200 * 1024              # bytes of UTF-8
FIELD_MAX = 80                         # the AI's model name and effort
PENDING_MAX = 3                        # reports waiting for the user at once
PER_HOUR = 6                           # reports made in the last hour, whatever became of them
HOUR = 3600
ATTACHMENT_MAX = 24 * 1024 * 1024      # one attachment; a bigger one is listed, not sent
TOTAL_MAX = 40 * 1024 * 1024           # every attachment of one report (the worker takes 64 MB)
TEXT_MAX = 256 * 1024                  # one log or record: its newest part
LOG_LINES = 40                         # the import log's last lines, in metadata.json's error output
PREVIEWS_MAX = 8
PREVIEW_MAX = 4 * 1024 * 1024
PENDING_KEEP = 3 * 24 * 3600
ENDED_KEEP = 24 * 3600
WAIT_MAX = 50

WAITING, SENT, DISCARDED, EXPIRED = 'waiting_for_user', 'sent', 'discarded', 'expired'
EVENT = 'mcp_problem_report'
IMPORT_JOB_KIND = 'mcp_model_import'   # randall/mcp/model_jobs.KIND
RECORD = 'report.json'
FILES = 'files'
# Compressing these gains nothing.
_STORED = frozenset(('.png', '.jpg', '.jpeg', '.webp', '.zip', '.glb'))

_REPORT_ID = re.compile(r'^[a-f0-9]{32}$')
_JOB_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$')
_IMPORT_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')
_CHAT_ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
# A value shaped like a path: a slash or backslash, a drive letter, a home folder, a parent step.
_PATH_SHAPED = re.compile(r'[\\/]|^[A-Za-z]:|^~|\.\.')
# A model name may hold a slash ("anthropic/claude-..."), never a path's start.
_PATH_START = re.compile(r'\\|^[A-Za-z]:|^[/~]|\.\.[\\/]')

REFS = {
    'job_id': (_JOB_ID, 'the job_id import_model or fix_import answered with'),
    'import_id': (_IMPORT_ID, "a model import's id (a job result's project)"),
    'chat_id': (_CHAT_ID, "a Randall chat's id"),
}

NOTES = {
    WAITING: ('Waiting for the user to confirm in Nucleus. Nothing has been sent. The Nucleus window shows them the '
              'report and its attachments, and they choose what goes with it and press Send or Discard. Call '
              'problem_report_status again later to learn which.'),
    SENT: 'The user sent it to the Nucleus developer.',
    DISCARDED: 'The user discarded it in Nucleus; nothing was sent.',
    EXPIRED: 'Nobody sent it within 3 days, so Nucleus dropped it; nothing was sent.',
}

_lock = threading.RLock()
_log = logging.getLogger(__name__)


class ReportRefused(ValueError):
    """A report_problem call that cannot become a report. The message is said to the AI as it is."""


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------

def _root():
    folder = Path(config.STORAGE_PATH) / 'assistant' / 'problem_reports'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _folder(report_id):
    if not isinstance(report_id, str) or not _REPORT_ID.fullmatch(report_id):
        return None
    return _root() / report_id


def _read_record(folder):
    try:
        record = json.loads((folder / RECORD).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def _write_record(folder, record):
    record['updated_at'] = time.time()
    temporary = folder / f'{RECORD}.tmp'
    temporary.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding='utf-8')
    os.replace(temporary, folder / RECORD)


def _drop_files(folder):
    shutil.rmtree(folder / FILES, ignore_errors=True)


def _state(folder, record):
    """The report's state now. A report the window sent (one of its frozen submissions is ``sent``) is marked
    sent here, with the worker's receipt, and its files are let go."""
    state = record.get('state') or WAITING
    if state != WAITING:
        return state
    for submission_id in record.get('submissions') or ():
        row = chat_report.submission(submission_id)
        if row and row.get('state') == 'sent':
            receipt = json.loads(row.get('receipt') or '{}')
            record.update(state=SENT, reference=str(receipt.get('id') or '')[:8] or None, sent_at=time.time())
            _write_record(folder, record)
            _drop_files(folder)
            _notify()
            return SENT
    return state


def _reports(now=None):
    """Every report on disk, oldest first, after the time limits are applied."""
    now = now or time.time()
    out = []
    for folder in sorted(_root().iterdir()):
        if not (folder.is_dir() and _REPORT_ID.fullmatch(folder.name)):
            continue
        record = _read_record(folder)
        if record is None:
            continue
        state = _state(folder, record)
        if state == WAITING and record.get('created_at', 0) < now - PENDING_KEEP:
            record['state'] = state = EXPIRED
            _write_record(folder, record)
            _drop_files(folder)
        if state != WAITING and record.get('updated_at', 0) < now - ENDED_KEEP:
            shutil.rmtree(folder, ignore_errors=True)
            continue
        out.append((folder, record))
    return sorted(out, key=lambda item: item[1].get('created_at', 0))


def _notify():
    """Tell the window the waiting reports changed (it also reads them when it connects)."""
    try:
        from core.state import get_socketio
        socketio = get_socketio()
        if socketio is not None:
            socketio.emit(EVENT, {})
    except Exception:  # noqa: BLE001 - the window reads the list again on its next connect
        pass


# ---------------------------------------------------------------------------
# the call's arguments
# ---------------------------------------------------------------------------

def _text_argument(arguments, key, limit, *, required=False):
    value = arguments.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ReportRefused(f'{key} must be a nonempty string.')
    value = value.strip()
    if len(value) > limit:
        raise ReportRefused(f'{key} is {len(value)} characters; at most {limit}.')
    return value


def checked_arguments(arguments):
    """(title, markdown, refs, reported_by) from report_problem's arguments, or ReportRefused."""
    allowed = ('title', 'markdown', *REFS, 'model', 'effort')
    extra = sorted(set(arguments) - set(allowed))
    if extra:
        raise ReportRefused(f"Unknown arguments: {', '.join(extra)}. Accepted: {', '.join(allowed)}. Nothing is "
                            'taken by path: name the import or chat by its id and Nucleus finds the files.')
    title = ' '.join(_text_argument(arguments, 'title', TITLE_MAX, required=True).split())
    markdown = arguments.get('markdown')
    if not isinstance(markdown, str) or not markdown.strip():
        raise ReportRefused('markdown must be a nonempty string: what went wrong, in markdown.')
    size = len(markdown.encode('utf-8'))
    if size > MARKDOWN_MAX:
        raise ReportRefused(f'markdown is {size} bytes; at most {MARKDOWN_MAX} ({MARKDOWN_MAX // 1024} KB). Shorten '
                            'it: the logs and records go with the report on their own.')
    refs = {}
    for key, (pattern, what) in REFS.items():
        value = arguments.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise ReportRefused(f'{key} must be {what}.')
        value = value.strip()
        if _PATH_SHAPED.search(value):
            raise ReportRefused(f'{key} must be {what}, not a path: Nucleus finds the files itself.')
        if not pattern.fullmatch(value):
            raise ReportRefused(f'{key} must be {what}.')
        refs[key] = value
    reported_by = {}
    for key in ('model', 'effort'):
        value = _text_argument(arguments, key, FIELD_MAX)
        if value is not None:
            if _PATH_START.search(value):
                raise ReportRefused(f'{key} must be a name (e.g. a model id), not a path.')
            reported_by[key] = value
    return title, markdown, refs, reported_by


# ---------------------------------------------------------------------------
# gathering what the ids name
# ---------------------------------------------------------------------------

def _inside(path, folder):
    try:
        resolved = Path(path).resolve()
        return resolved if resolved.is_relative_to(Path(folder).resolve()) and resolved.is_file() else None
    except (OSError, ValueError):
        return None


def _tail(path, limit=TEXT_MAX):
    """The newest ``limit`` bytes of a text file, as text, with a marker when the start was left out."""
    size = path.stat().st_size
    with open(path, 'rb') as handle:
        if size > limit:
            handle.seek(size - limit)
        data = handle.read(limit)
    text = data.decode('utf-8', errors='replace')
    if size > limit:
        text = f'...[the first {size - limit} bytes are left out]\n' + text.split('\n', 1)[-1]
    return text


def _iso(stamp):
    if not isinstance(stamp, (int, float)):
        return None
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec='seconds')


def _import_job(job_id):
    from core import jobs
    record = jobs.get(job_id)
    if not isinstance(record, dict) or record.get('kind') != IMPORT_JOB_KIND:
        raise ReportRefused(f'No model import job {job_id}: job_id is the one import_model or fix_import '
                            'answered with.')
    return record


def _import_folder(import_id):
    from randall.model_import.chat import studio_import
    try:
        folder = studio_import._folder(import_id)
    except ValueError:
        raise ReportRefused(f'No model import {import_id}.') from None
    if not folder.is_dir():
        raise ReportRefused(f'No model import {import_id} on this computer.')
    return folder


def _chat_transcript(chat_id, app_version, secrets):
    chat = chat_report._load_mods_chat(chat_id)
    if not chat or not chat.get('messages'):
        raise ReportRefused(f'No Randall chat {chat_id}.')
    caps = {'content': chat_report.CONTENT_MAX, 'args': chat_report.ARGS_MAX, 'result': chat_report.RESULT_MAX}
    conversation = chat_report.build_conversation('mods', chat, caps=caps, app_version=app_version or 'dev',
                                                  secrets=secrets)
    conversation = chat_report.scrub(conversation, secrets)
    return chat_report.scrub_text(chat_report.transcript_markdown(conversation, costs=False), secrets)


def _tools_state():
    try:
        from randall.model_import.chat import import_job
        need = import_job.tools_needed()
    except Exception:  # noqa: BLE001 - a version line never stops a report
        return 'unknown'
    return 'ready' if not need else str(need.get('state') or 'missing')


def _app_log():
    """Nucleus's own newest log file (``mex_api_<date>.log``), or None."""
    folder = Path(config.LOGS_PATH)
    if not folder.is_dir():
        return None
    logs = sorted(folder.glob('mex_api_*.log'))
    return logs[-1] if logs else None


def _source_model(path_text):
    """The source model an import was made from, when it may go: (path, None), else (None, why not)."""
    from core.path_safety import NotLocalPath, local_path
    from randall.model_import.chat import import_job
    from . import chat_report_files as report_files
    try:
        path = Path(local_path(str(path_text), field='source'))
    except (NotLocalPath, ValueError, TypeError):
        return None, 'not a file on this computer'
    suffix = path.suffix.lower()
    if suffix in report_files.DISC_IMAGES or suffix not in import_job.SOURCES:
        return None, 'not a model file'
    if not path.is_file():
        return None, 'no longer on this computer'
    try:
        reason = report_files.excluded_reason(path, {'name': path.name})
    except Exception:  # noqa: BLE001 - a file that cannot be screened does not go
        reason = report_files.UNREADABLE
    return (None, reason) if reason else (path, None)


class _Package:
    """The parts of one report, written into its folder as they are added."""

    def __init__(self, folder):
        self.folder = folder
        self.entries = []
        self.total = 0
        (folder / FILES).mkdir(parents=True, exist_ok=True)

    def _name(self, name):
        names = {entry['name'] for entry in self.entries}
        stem, dot, suffix = name.rpartition('.')
        candidate, n = name, 2
        while candidate in names:
            candidate = f'{stem}-{n}.{suffix}' if dot else f'{name}-{n}'
            n += 1
        return candidate

    def add(self, name, label, kind, *, data=None, source=None, optional=True, include=True, size=None):
        """One part: ``data`` (bytes) or ``source`` (a file copied in). Over a limit: listed, not kept."""
        size = len(data) if data is not None else (size if size is not None else source.stat().st_size)
        entry = {'name': self._name(name), 'label': label, 'kind': kind, 'bytes': size, 'optional': optional,
                 'include': include if optional else True, 'too_large': False, 'sha256': None, 'file': None}
        if optional and (size > ATTACHMENT_MAX or self.total + size > TOTAL_MAX):
            entry.update(too_large=True, include=False)
            self.entries.append(entry)
            return entry
        stored = self.folder / FILES / f'{len(self.entries):02d}{Path(entry["name"]).suffix.lower()}'
        if data is not None:
            stored.write_bytes(data)
        else:
            shutil.copyfile(source, stored)
        entry.update(file=stored.name, sha256=sha256_file(stored), bytes=stored.stat().st_size)
        if optional:
            self.total += entry['bytes']
        self.entries.append(entry)
        return entry

    def text(self, name, label, kind, text, **options):
        return self.add(name, label, kind, data=text.encode('utf-8'), **options)

    def json(self, name, label, kind, value, **options):
        return self.text(name, label, kind, json.dumps(value, indent=1, ensure_ascii=False, default=str), **options)


def _job_view(record):
    keep = ('id', 'kind', 'label', 'status', 'detail', 'error', 'params', 'extra', 'result')
    view = {key: record.get(key) for key in keep if record.get(key) is not None}
    extra = dict(view.get('extra') or {})
    extra.pop('asks', None)            # the relay folder: a temporary path, nothing to read
    view['extra'] = extra
    for key in ('created_at', 'started_at', 'ended_at'):
        view[key] = _iso(record.get(key))
    return view


def _errors(job, folder):
    """The error output: the job's error, the importer's own failure fields, the last lines of its log."""
    out = {}
    if job:
        if job.get('error'):
            out['job_error'] = job['error']
        result = job.get('result') if isinstance(job.get('result'), dict) else {}
        failure = {key: result[key] for key in ('error', 'status', 'warning', 'diagnostic', 'cause', 'failure')
                   if result.get(key)}
        if failure:
            out['importer'] = failure
    if folder is not None:
        log = _inside(folder / 'workflow' / 'job.log', folder)
        if log is not None:
            out['import_log_tail'] = _tail(log, 64 * 1024).splitlines()[-LOG_LINES:]
    return out


def _assemble(folder, *, title, markdown, refs, reported_by, now):
    secrets = chat_report._known_secrets()
    scrub_text = lambda text: chat_report.scrub_text(text, secrets)       # noqa: E731
    scrub = lambda value: chat_report.scrub(value, secrets)                # noqa: E731
    app_version = (os.environ.get('NUCLEUS_APP_VERSION') or '').strip()
    package = _Package(folder)

    job = _import_job(refs['job_id']) if 'job_id' in refs else None
    import_id = refs.get('import_id')
    if import_id is None and job is not None:
        result = job.get('result') if isinstance(job.get('result'), dict) else {}
        import_id = result.get('project') or (job.get('extra') or {}).get('project')
    import_folder = _import_folder(import_id) if import_id else None
    transcript = _chat_transcript(refs['chat_id'], app_version, secrets) if 'chat_id' in refs else None

    source, why_not = None, None
    source_text = job['params'].get('source') if job is not None and isinstance(job.get('params'), dict) else None
    if source_text is None and import_folder is not None:
        settings = _inside(import_folder / 'workflow' / 'job.json', import_folder)
        try:
            source_text = json.loads(settings.read_text(encoding='utf-8')).get('download') if settings else None
        except (OSError, ValueError, AttributeError):
            source_text = None
    if isinstance(source_text, str) and source_text:
        source, why_not = _source_model(source_text)

    timings = {}
    if job is not None:
        started, ended = job.get('started_at'), job.get('ended_at')
        timings['job'] = {'created_at': _iso(job.get('created_at')), 'started_at': _iso(started),
                          'ended_at': _iso(ended), 'status': job.get('status'),
                          'seconds': round(ended - started, 1) if isinstance(started, (int, float))
                          and isinstance(ended, (int, float)) else None}
        if (job.get('extra') or {}).get('seconds') is not None:
            timings['import_seconds'] = job['extra']['seconds']
    metadata = {
        'report_version': REPORT_VERSION,
        'title': title,
        'created_at': _iso(now),
        'refs': dict(refs, **({'import_id': import_id} if import_id and 'import_id' not in refs else {})),
        'reported_by': dict(reported_by, via='MCP (the user\'s own AI)'),
        'versions': dict(chat_report.app_info(app_version or 'dev'), model_import_tools=_tools_state()),
        'timings': timings,
        'errors': _errors(job, import_folder),
    }
    if why_not:
        metadata['source_model'] = f'not attached: {why_not}'
    package.text('report.md', "Your AI's report", 'markdown', scrub_text(markdown), optional=False)
    package.json('metadata.json', 'Versions, timings and error output', 'metadata', scrub(metadata), optional=False)

    if job is not None:
        package.json('import/mcp-job.json', "The import job's record", 'record', scrub(_job_view(job)))
    if import_folder is not None:
        for relative, label in (('workflow/job.json', "The import's settings"),
                                ('rigswap/result.json', 'How the importer ended'),
                                ('randall.jsonl', "The import's AI ledger (models, rounds, time)"),
                                ('workflow/job.log', "The import's log")):
            path = _inside(import_folder / relative, import_folder)
            if path is not None:
                package.text(f'import/{Path(relative).name}', label, 'record', scrub_text(_tail(path)))
    log = _app_log()
    if log is not None:
        package.text('logs/nucleus.log', "Nucleus's log (its newest part)", 'log', scrub_text(_tail(log)))
    if transcript is not None:
        package.text('chat/transcript.md', 'The Randall chat', 'transcript', transcript)

    if import_folder is not None:
        pictures = []
        result = (job or {}).get('result') if isinstance((job or {}).get('result'), dict) else {}
        named = [p for p in result.get('pictures') or () if isinstance(p, str)]
        for candidate in [*named, *sorted(import_folder.glob('*.png'))]:
            path = _inside(candidate, import_folder)
            if path is not None and path.suffix.lower() == '.png' and path not in pictures \
                    and path.stat().st_size <= PREVIEW_MAX:
                pictures.append(path)
        for path in pictures[:PREVIEWS_MAX]:
            package.add(f'previews/{path.name}', 'A preview picture', 'preview', source=path)

    if source is not None:
        package.add(f'source/{source.name}', 'The model file it was made from', 'source', source=source,
                    include=False)
    return package.entries


# ---------------------------------------------------------------------------
# the MCP side: make one, say how it stands
# ---------------------------------------------------------------------------

def create(arguments, *, now=None):
    """report_problem: assemble and keep one report for the user to review. Sends nothing. -> the record."""
    title, markdown, refs, reported_by = checked_arguments(arguments)
    now = now or time.time()
    with _lock:
        reports = _reports(now)
        waiting = sum(1 for folder, record in reports if (record.get('state') or WAITING) == WAITING)
        if waiting >= PENDING_MAX:
            raise ReportRefused(f'{waiting} problem reports already wait for the user in Nucleus. Ask them to send or '
                                'discard those first; nothing was made.')
        recent = sum(1 for folder, record in reports if record.get('created_at', 0) > now - HOUR)
        if recent >= PER_HOUR:
            raise ReportRefused(f'{recent} problem reports were made in the last hour, the most Nucleus takes. Try '
                                'again later; nothing was made.')
        report_id = uuid.uuid4().hex
        folder = _root() / report_id
        folder.mkdir()
        try:
            entries = _assemble(folder, title=title, markdown=markdown, refs=refs, reported_by=reported_by, now=now)
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        record = {'id': report_id, 'state': WAITING, 'title': chat_report.scrub_text(title), 'refs': refs,
                  'reported_by': reported_by, 'created_at': now, 'attachments': entries, 'submissions': []}
        _write_record(folder, record)
    _log.info('Problem report %s made by an MCP client (%s parts); waiting for the user', report_id, len(entries))
    _notify()
    return record


def _public_entry(entry):
    return {key: entry.get(key) for key in ('name', 'label', 'kind', 'bytes', 'optional', 'include', 'too_large')}


def status(report_id):
    """problem_report_status: {report_id, status, note, reference?} or ReportRefused for an unknown id."""
    folder = _folder(report_id)
    with _lock:
        if folder is not None and folder.is_dir():
            _reports()                  # the time limits: an old waiting report has expired by now
        record = _read_record(folder) if folder is not None else None
        if record is None:
            raise ReportRefused(f'No problem report {report_id} (reports are forgotten a day after they end).')
        state = _state(folder, record)
    out = {'report_id': report_id, 'status': state, 'title': record.get('title'), 'note': NOTES[state]}
    if state == SENT and record.get('reference'):
        out['reference'] = record['reference']
    return out


def made(record):
    """report_problem's answer for a report it made."""
    return {'report_id': record['id'], 'status': WAITING, 'sent': False,
            'note': ('Waiting for you to confirm in Nucleus: the report is shown in the Nucleus window, nothing has '
                     'been sent. Tell the user it is there for them to read, choose what goes with it and press '
                     'Send or Discard. Call problem_report_status with this report_id to learn which.'),
            'attachments': [_public_entry(e) for e in record['attachments']]}


# ---------------------------------------------------------------------------
# the window's side: list, freeze for sending, discard
# ---------------------------------------------------------------------------

def pending():
    """The reports waiting for the user, oldest first, as the window shows them."""
    out = []
    with _lock:
        for folder, record in _reports():
            if (record.get('state') or WAITING) != WAITING:
                continue
            report_md = next((e for e in record['attachments'] if e['kind'] == 'markdown'), None)
            try:
                markdown = (folder / FILES / report_md['file']).read_text(encoding='utf-8') if report_md else ''
            except OSError:
                markdown = ''
            out.append({'id': record['id'], 'title': record.get('title'), 'markdown': markdown,
                        'created_at': record.get('created_at'), 'reported_by': record.get('reported_by') or {},
                        'refs': record.get('refs') or {},
                        'attachments': [_public_entry(e) for e in record['attachments']]})
    return out


def _waiting_record(report_id):
    folder = _folder(report_id)
    record = _read_record(folder) if folder is not None else None
    if record is None:
        raise chat_report.ReportError('unknown_report')
    state = _state(folder, record)
    if state != WAITING:
        raise chat_report.ReportError(f'report_{state}')
    return folder, record


def review(report_id, *, include, app_version=''):
    """The window's Send, step one: freeze the report with the parts the user ticked as a chat report submission.
    Sends nothing. -> {submission_id, approval_hash, manifest, meta}; ``POST /api/mex/chat-reports/submit`` sends it.
    ``include``: the names of the optional parts to send (a part over the limits never goes)."""
    if not isinstance(include, list) or not all(isinstance(name, str) for name in include):
        raise chat_report.ReportError('bad_include')
    version = chat_report.valid_app_version((os.environ.get('NUCLEUS_APP_VERSION') or '').strip() or app_version)
    if not version:
        raise chat_report.ReportError('app_version_unknown')
    with _lock:
        folder, record = _waiting_record(report_id)
        entries = {entry['name']: entry for entry in record['attachments']}
        chosen = set(include)
        if chosen - set(entries):
            raise chat_report.ReportError('unknown_attachment')
        going = [e for e in record['attachments']
                 if not e['optional'] or (e['name'] in chosen and not e['too_large'])]
        left_out = [{'name': e['name'], 'bytes': e['bytes'], 'why': 'too large' if e['too_large'] else 'not chosen'}
                    for e in record['attachments'] if e not in going]
        buffer = io.BytesIO()
        members = []
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            summary = {'report_version': REPORT_VERSION, 'kind': 'problem_report', 'report_id': report_id,
                       'title': record.get('title'), 'app_version': version, 'refs': record.get('refs') or {},
                       'reported_by': record.get('reported_by') or {},
                       'included': [e['name'] for e in going], 'left_out': left_out}
            data = json.dumps(summary, indent=1, ensure_ascii=False).encode('utf-8')
            archive.writestr('report.json', data)
            members.append({'name': 'report.json', 'bytes': len(data), 'sha256': sha256_bytes(data)})
            for entry in going:
                try:
                    data = (folder / FILES / entry['file']).read_bytes()
                except OSError as exc:
                    raise chat_report.ReportError('bundle_missing') from exc
                if sha256_bytes(data) != entry['sha256']:
                    raise chat_report.ReportError('bundle_changed')
                method = zipfile.ZIP_STORED if Path(entry['name']).suffix.lower() in _STORED else zipfile.ZIP_DEFLATED
                archive.writestr(entry['name'], data, compress_type=method)
                members.append({'name': entry['name'], 'bytes': len(data), 'sha256': entry['sha256']})
        bundle = buffer.getvalue()
        reported_by = record.get('reported_by') or {}
        meta = {
            'kind': chat_report.KIND,
            'app_version': version,
            'platform': config.bugreport_channel(),
            'description': chat_report.clip(f"{DESCRIPTION}: {record.get('title') or ''}", 3900),
            'contact': '',
            'zip_size': len(bundle),
            'truncated': False,
            'chat': {'surface': SURFACE, 'message_count': None, 'tool_calls': None, 'errors': None,
                     'conversation_id': report_id, 'model': str(reported_by.get('model') or '')[:80]},
        }
        manifest = {'members': members, 'bundle': {'bytes': len(bundle), 'sha256': sha256_bytes(bundle)},
                    'include_discord_identity': False, 'problem_report': report_id,
                    'left_out': left_out}
        submission_id, digest = chat_report.freeze(SURFACE, report_id, bundle=bundle, meta=meta, manifest=manifest)
        record.setdefault('submissions', []).append(submission_id)
        _write_record(folder, record)
    return {'submission_id': submission_id, 'approval_hash': digest, 'manifest': manifest, 'meta': meta}


def discard(report_id):
    """The window's Discard: nothing is sent, and the report's parts are deleted."""
    with _lock:
        folder, record = _waiting_record(report_id)
        record['state'] = DISCARDED
        _write_record(folder, record)
        _drop_files(folder)
    _log.info('Problem report %s discarded by the user', report_id)
    _notify()
    return True


def wait_for_change(report_id, seconds):
    """status() once the report is no longer waiting, or after ``seconds``."""
    deadline = time.monotonic() + max(0, min(WAIT_MAX, seconds))
    answer = status(report_id)
    while answer['status'] == WAITING and time.monotonic() < deadline:
        time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
        answer = status(report_id)
    return answer
