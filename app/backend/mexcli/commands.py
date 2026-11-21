"""Running MexCLI: the one helper the backend spawns it through.

``run`` spawns MexCLI and returns the CompletedProcess. ``run_json`` runs it and
returns the JSON object it printed, taking the project's build lock for the
commands that save the workspace. ``parse_json`` is the parsing on its own, for
callers that spawn MexCLI themselves (stdin payloads, their own lock).

``mexcli.project.MexManager`` keeps its own spawn: it runs the binary it was given,
from the project folder, and raises MexManagerError on output it cannot parse.
(Two parsers on purpose: this one returns {} on noise, that one raises.)
"""

import json
import subprocess
from pathlib import Path

from core import config
from core.config import get_subprocess_args

MEXCLI = config.MEXCLI_PATH

# MexCLI commands that open+save the project workspace. These must hold the
# project lock so they can't run concurrently with a background costume reorder
# or an export. Read-only commands (ssm-info, sem-resolve, ssm-to-wav, …) are
# intentionally omitted so they never block behind a long export.
MUTATING_COMMANDS = frozenset({
    'add-music', 'set-fighter-music', 'set-fighter-announcer',
    'set-fighter-announcer-id', 'set-stage-playlist', 'set-menu-playlist', 'add-series',
    'import-ssm',
})


def run(args, *, cwd=None, timeout=None, check=True):
    """Run ``MEXCLI *args`` and return the CompletedProcess.

    Arguments are passed through ``str()``. Output is captured as text, the
    console window is hidden on Windows, and ``cwd`` defaults to PROJECT_ROOT.
    ``check`` and ``timeout`` behave as in ``subprocess.run``.
    """
    return subprocess.run(
        [str(MEXCLI), *[str(a) for a in args]],
        capture_output=True, text=True, check=check, timeout=timeout,
        cwd=str(config.PROJECT_ROOT if cwd is None else cwd), **get_subprocess_args()
    )


def parse_json(stdout, *, first_brace=False):
    """The JSON object MexCLI printed after its log lines, or {} when there is none.

    MexCLI prints indented JSON, often after progress noise like 'Trimmed
    Image ...', so naive last-line parsing yields '}' and silently fails. The
    default takes the object that starts on the last line beginning with '{'
    (or the whole output when it starts with '{'). ``first_brace=True`` parses
    from the first '{' to the end instead.
    """
    if first_brace:
        stdout = stdout or ''
        try:
            return json.loads(stdout[stdout.index('{'):])
        except (ValueError, json.JSONDecodeError):
            return {}
    s = (stdout or '').strip()
    idx = s.rfind('\n{')
    candidate = s[idx + 1:] if idx != -1 else (s if s.startswith('{') else None)
    if candidate is None:
        return {}
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return {}


def _target_project(args):
    """The .mexproj a mutating command writes: its first argument after the command."""
    if len(args) > 1 and str(args[1]).lower().endswith('.mexproj'):
        return Path(str(args[1]))
    return None


def run_json(args, *, cwd=None, timeout=None, first_brace=False, returncode=True):
    """Run a MexCLI command and return its parsed JSON output (or {}).

    The exit code is added as ``_returncode`` unless ``returncode`` is False.
    Commands in MUTATING_COMMANDS run inside the open project's build session
    (or under ``mexcli_lock`` when no project is open), and a non-zero exit
    there raises ``build_access.TransactionError``.
    """
    args = list(args)
    cmd = str(args[0]) if args else ''

    def _exec():
        result = run(args, cwd=cwd, timeout=timeout, check=False)
        out = parse_json(result.stdout, first_brace=first_brace)
        if returncode:
            out['_returncode'] = result.returncode
        return out, result.returncode

    if cmd not in MUTATING_COMMANDS:
        return _exec()[0]
    # These commands open and SAVE the whole MexManager workspace, so they go
    # through the same build session every other writer uses: the cross-process
    # lock as well as this process's, recovery before the write, and a bracket
    # around the save so a death in the middle is detected instead of leaving a
    # half-saved project nobody can account for.
    from core import build_access
    from core.state import get_current_project_path, mexcli_lock
    # The lock and journal must be for the project the command writes. Every
    # mutating command names its project right after the command word; the open
    # project is only the fallback, and a caller that captured another one
    # (an install that outlived a switch) must not protect the wrong build.
    project_path = _target_project(args) or get_current_project_path()
    if project_path is None:
        with mexcli_lock:
            return _exec()[0]
    with build_access.build_session(Path(project_path).parent, timeout=120.0) as session:
        with session.external_save(f'mexcli {cmd}'):
            out, code = _exec()
            if code:
                raise build_access.TransactionError(
                    'mexcli_failed', f'mexcli {cmd} exited {code}')
            return out
