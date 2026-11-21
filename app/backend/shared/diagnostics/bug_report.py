"""
Diagnostics a user sends us: the logs zip and the bug-report worker's settings.

`_build_logs_zip` builds the zip behind Settings' "Download logs"
(`/api/mex/logs/download`) and the in-app bug report (`/api/mex/bugreport`),
both in shared/routes/setup.py. The worker URL, the report zip budget, the
platform channel and the Discord bearer helper are the transport the Randall
routes reuse for feature requests and "Report this chat"
(randall/routes/wishes.py and chat_reports.py read this module as their
transport, so there is one report pipeline and one set of worker limits).
"""

import io
import os
import sys
import zipfile
import platform
import logging
from datetime import datetime
from pathlib import Path

from core.config import PROJECT_ROOT, LOGS_PATH, BUGREPORT_ZIP_BUDGET
# Part of the transport surface the Randall report routes read from this module.
from core.config import bugreport_channel  # noqa: F401
from core.log_redaction import redact_log_text as _redact_log_text

logger = logging.getLogger(__name__)


# Caps so a logs zip can't balloon (Slippi crash .dmp files can be large, and the
# User tree also holds replays/ISOs we must NEVER sweep in).
_SLIPPI_LOG_MAX_FILE = 25 * 1024 * 1024     # 25 MB per file
_SLIPPI_LOG_MAX_TOTAL = 100 * 1024 * 1024   # 100 MB total

# Dolphin ships these .txt files in its install root — they're distribution files,
# not logs. The top-level scan must skip them so a bug report doesn't end up
# counting e.g. license.txt + portable.txt as "Slippi logs" and mislead triage.
_SLIPPI_NON_LOG_FILES = frozenset({
    'license.txt',
    'portable.txt',
    'readme.txt',
})


# Text log files get a redaction pass before they leave the machine (both the
# user-facing zip download and the bug-report upload): the OS username in
# absolute paths, and anything token-shaped (core/log_redaction.py, imported
# above as _redact_log_text). Binary files (.dmp) are untouched.
_REDACT_TEXT_SUFFIXES = frozenset({'.log', '.txt', '.ini'})


def _is_redactable_text(p: Path) -> bool:
    """True for .log/.txt/.ini files, including rotated variants (.log.1)."""
    suffix = p.suffix.lower()
    if suffix in _REDACT_TEXT_SUFFIXES:
        return True
    # RotatingFileHandler renames to mex_api.log.1 — suffix becomes '.1'
    suffixes = p.suffixes
    return (len(suffixes) >= 2 and suffix[1:].isdigit()
            and suffixes[-2].lower() in _REDACT_TEXT_SUFFIXES)


def _zip_add_redacted(zf: zipfile.ZipFile, p: Path, arc: str) -> None:
    """Add one file to the zip, redacting it first when it's a text log."""
    if _is_redactable_text(p):
        text = p.read_text(encoding='utf-8', errors='replace')
        zf.writestr(arc, _redact_log_text(text))
    else:
        zf.write(p, arc)


def _add_slippi_dolphin_logs(zf: zipfile.ZipFile, slippi_path: str,
                             budget_bytes: int | None = None) -> tuple[int, bool]:
    """Add the user's Slippi Dolphin logs + crash dumps to the zip under
    slippi-dolphin/. Only known log/dump locations are touched (Dolphin's Logs
    folder + .dmp/.log/.txt at known top levels) so we never pull in replays or
    ISOs. Size-capped (plus an optional overall budget for the bug-report
    path). Returns (files added, hit a cap)."""
    root = Path(slippi_path)
    if not root.is_dir():
        return 0, False
    # Deliberately NOT slippi_user_dir(): this bundler must stay scoped to the
    # folder the caller pointed at. The XDG fallback would reach into the real
    # ~/.config/SlippiOnline and pull files from outside the requested path.
    # (Consequence: Linux Dolphin logs, which live in XDG, are not collected —
    # that needs to be an explicit, separate opt-in, not a silent side effect.)
    user = root / 'User'
    added = 0
    total = 0
    capped = False
    cap_total = _SLIPPI_LOG_MAX_TOTAL if budget_bytes is None else min(_SLIPPI_LOG_MAX_TOTAL, budget_bytes)

    def _add(p: Path, arc: str):
        nonlocal added, total, capped
        try:
            sz = p.stat().st_size
        except OSError:
            return
        if sz > _SLIPPI_LOG_MAX_FILE or total + sz > cap_total:
            capped = True
            return
        try:
            _zip_add_redacted(zf, p, arc)
        except OSError:
            return
        total += sz
        added += 1

    # Dolphin's Logs folder (recursive — small text logs).
    logs_dir = user / 'Logs'
    if logs_dir.is_dir():
        for p in sorted(logs_dir.rglob('*')):
            if p.is_file():
                _add(p, f"slippi-dolphin/Logs/{p.relative_to(logs_dir).as_posix()}")

    # Crash dumps / stray logs at known top levels (non-recursive so we don't
    # walk into Slippi/replays or Games/ISOs). Covers the netplay dir, its User
    # dir, and the Slippi Launcher dir above it.
    for base, prefix in ((root, 'netplay'), (user, 'User'), (root.parent, 'launcher')):
        if base.is_dir():
            for p in sorted(base.iterdir()):
                if (p.is_file()
                        and p.suffix.lower() in ('.dmp', '.log', '.txt')
                        and p.name.lower() not in _SLIPPI_NON_LOG_FILES):
                    _add(p, f"slippi-dolphin/{prefix}/{p.name}")

    return added, capped


def _build_diagnostics_text(slippi_path: str = '', app_logs: int = 0,
                            slippi_logs: int = 0) -> str:
    """A short system summary bundled alongside the logs so a bug report has
    context (app paths, OS, python, what was gathered) without the user having
    to describe it."""
    lines = [
        'SSBM Nucleus diagnostics',
        f'Generated: {datetime.now().isoformat()}',
        f'App version: {os.environ.get("NUCLEUS_APP_VERSION") or "unknown (dev)"}',
        f'Platform: {platform.platform()}',
        f'Python: {sys.version.split()[0]}',
        f'Frozen build: {bool(getattr(sys, "frozen", False))}',
        f'Project root: {PROJECT_ROOT}',
        f'Logs path: {LOGS_PATH}',
        f'App log files: {app_logs}',
        f'Slippi Dolphin path: {slippi_path or "(not provided)"}',
        f'Slippi log/dump files: {slippi_logs}',
    ]
    # If we were pointed at a Slippi folder but found no actual logs, say why:
    # Dolphin doesn't log to disk by default, and an in-game Melee crash leaves
    # no host minidump — so "0" is normal, not a collection failure. Tell the
    # next reporter how to get real logs.
    if slippi_path and slippi_logs == 0:
        lines.append(
            'Note: no Dolphin file logs found. Dolphin does not write logs to '
            'disk by default -- enable Config -> Logging -> "Write to File" in '
            'Slippi Dolphin and reproduce to capture them. (An in-game Melee '
            'crash also produces no host minidump.)'
        )
    lines.append('Redaction: usernames in paths masked, token-shaped values blanked')
    return _redact_log_text('\n'.join(lines) + '\n')


def _build_logs_zip(slippi_path: str = '', extra_files: dict | None = None,
                    budget_bytes: int | None = None) -> tuple[io.BytesIO, int, int, bool]:
    """Build the diagnostics zip in memory: logs/**, optional slippi-dolphin/**,
    any extra_files ({arcname: text}), and diagnostics.txt last so it can report
    what was gathered. Text logs are redacted (see _redact_log_text).

    With budget_bytes set (the bug-report path — the upload endpoint caps the
    zip), app logs are added NEWEST first and adding stops at the budget;
    without it (the user-facing download) everything is included in path order.
    Returns (buffer, app_logs_added, slippi_logs_added, truncated)."""
    buf = io.BytesIO()
    added = 0
    slippi_added = 0
    truncated = False
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        files = [p for p in LOGS_PATH.rglob('*') if p.is_file()] if LOGS_PATH.is_dir() else []
        if budget_bytes is not None:
            def _mtime(p):
                try:
                    return p.stat().st_mtime
                except OSError:
                    return 0
            files.sort(key=_mtime, reverse=True)
        else:
            files.sort()
        used = 0
        for log_file in files:
            try:
                size = log_file.stat().st_size
            except OSError:
                continue
            if budget_bytes is not None and used + size > budget_bytes:
                truncated = True
                continue
            try:
                _zip_add_redacted(zf, log_file, f'logs/{log_file.relative_to(LOGS_PATH).as_posix()}')
                added += 1
                used += size
            except OSError as e:
                logger.warning(f"Could not add log to zip: {log_file} ({e})")
        if slippi_path:
            slippi_budget = None if budget_bytes is None else max(0, budget_bytes - used)
            slippi_added, slippi_capped = _add_slippi_dolphin_logs(zf, slippi_path, slippi_budget)
            truncated = truncated or slippi_capped
        # extra_files carry machine-generated text too (electron stdout echoes
        # absolute paths); redact them like any log. The un-redacted
        # description/contact still reach the worker via the report meta.
        for arcname, content in (extra_files or {}).items():
            zf.writestr(arcname, _redact_log_text(content))
        # diagnostics written last so it can report what was gathered
        zf.writestr('diagnostics.txt',
                    _build_diagnostics_text(slippi_path, added, slippi_added))
    buf.seek(0)
    return buf, added, slippi_added, truncated


# The bugreport worker (services/cloudflare/bugreport-worker) — stores the zip
# in R2 and pings the developer's PRIVATE Discord channel. Override for local
# testing with `wrangler dev`.
_BUGREPORT_URL = os.environ.get('NUCLEUS_BUGREPORT_URL', 'https://ssbmnucleus.net/bugreport')
# Uncompressed budget for the report zip (core.config; the chat report shares it).
_BUGREPORT_ZIP_BUDGET = BUGREPORT_ZIP_BUDGET
_BUGREPORT_DESCRIPTION_MAX = 4000


def _bugreport_auth_headers() -> dict:
    """Bearer header for the backend's Discord sign-in (shared/account) when there
    is one. Reports are anonymous otherwise — never an error: nobody signed in
    just to file a bug."""
    try:
        from shared.account import discord
        token = discord.session_token()
        if token:
            return {'Authorization': f'Bearer {token}'}
    except Exception:
        pass
    return {}
