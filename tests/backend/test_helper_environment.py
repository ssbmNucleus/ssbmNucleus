"""Helper programs start without Nucleus's settings and secrets (core/child_env.py).

A helper (MexCLI, HSDRaw, Blender, Dolphin, rigswap, ...) reads files Nucleus did not make. Before, each one
inherited the backend's whole environment, the backend token and the window's key included, so a file that
could make it misbehave could also drive the backend as the window does. These start real child processes
through the app's own runners, with the helper's executable swapped for this Python reporting what it can see.
"""
import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.gated import needs
from tests.paths import BACKEND, REPO

SECRETS = {'NUCLEUS_BACKEND_TOKEN': 'backend-secret', 'NUCLEUS_UI_APPROVAL_KEY': 'window-secret',
           'OPENROUTER_API_KEY': 'sk-or-secret', 'GITHUB_TOKEN': 'ghp-secret'}
SEEN = ('import json, os, sys; seen = [n for n in %r if n in os.environ]; '
        'text = json.dumps({"success": True, "seen": seen}); '
        'open(sys.argv[1], "w").write(text) if len(sys.argv) > 1 else print(text)') % (sorted(SECRETS),)


@pytest.fixture(autouse=True)
def secrets_in_the_backend(monkeypatch):
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)


def seen(output):
    return json.loads(output.strip().splitlines()[-1])['seen']


def test_the_shared_helper_arguments_leave_the_secrets_out_and_keep_the_rest():
    from core import config
    args = config.get_subprocess_args()
    assert not set(SECRETS) & set(args['env']) and args['env']['PATH']
    ran = subprocess.run([sys.executable, '-c', SEEN], capture_output=True, text=True, timeout=60,
                         **config.get_subprocess_args())
    assert ran.returncode == 0, ran.stderr
    assert seen(ran.stdout) == []


def test_mexcli_runs_without_the_secrets(monkeypatch, tmp_path):
    from mexcli import commands, project
    monkeypatch.setattr(commands, 'MEXCLI', sys.executable)
    assert seen(commands.run(['-c', SEEN]).stdout) == []
    mexproj = tmp_path / 'project.mexproj'
    mexproj.write_text('{}')
    manager = project.MexManager(cli_path=sys.executable, project_path=str(mexproj))
    assert manager._run_command('-c', SEEN)['seen'] == []


def test_mexcli_projects_own_copy_of_the_rule_matches_core(monkeypatch):
    """mexcli/project.py cannot import core (test_backend_layout), so it writes the rule out; it must not drift."""
    from core.child_env import child_environment
    from mexcli import project
    for name in ('NUCLEUS_DATA_ROOT', 'nucleus_lower', '_MEIPASS2', '_PYI_APPLICATION_HOME_DIR', 'PYTHONPATH',
                 'PYTHONHOME', 'SOME_SECRET', 'A_SECRET_KEY', 'DB_PASSWORD', 'KEEP_ME', 'TOKENS_DIR'):
        monkeypatch.setenv(name, 'x')
    assert project._helper_environment() == child_environment()
    assert 'KEEP_ME' in child_environment() and 'TOKENS_DIR' in child_environment()


@needs('assistant')
def test_hsdraw_the_toolkit_and_rigswap_get_no_backend_secrets(monkeypatch, tmp_path):
    from core import config
    from randall.assistant import hsdraw
    from randall.mcp import toolkit
    from randall.model_import.chat import import_job
    monkeypatch.setattr(config, 'HSDRAW_EXE', Path(sys.executable))
    assert seen(hsdraw._run(['-c', SEEN], tmp_path)) == []
    assert not set(SECRETS) & set(toolkit._environment())
    rigswap = import_job._environment(None)
    assert [name for name in SECRETS if name in rigswap] == ['OPENROUTER_API_KEY'], 'its own key, on purpose'
    assert import_job._environment('turn-key')['OPENROUTER_API_KEY'] == 'turn-key'


def test_a_game_started_for_the_user_gets_no_secrets(tmp_path):
    from shared.ingame import boot
    out = tmp_path / 'seen.json'
    boot.start_detached([sys.executable, '-c', SEEN, str(out)], cwd=str(tmp_path)).wait(60)
    assert seen(out.read_text()) == []


@needs('play')
def test_a_play_game_gets_no_secrets():
    from play import launch
    assert not set(SECRETS) & set(launch.game_environment())


def test_the_build_worker_gets_a_token_of_its_own_and_not_the_windows_key(monkeypatch):
    from tracker.replays import watch_mods
    started = {}

    class Started(Exception):
        pass

    def popen(args, **kwargs):
        started.update(kwargs)
        raise Started

    monkeypatch.setattr(watch_mods.subprocess, 'Popen', popen)
    worker = watch_mods._Worker()
    with pytest.raises(Started):
        worker.start()
    env = started['env']
    assert env['NUCLEUS_BACKEND_TOKEN'] == worker.token != SECRETS['NUCLEUS_BACKEND_TOKEN']
    assert 'NUCLEUS_UI_APPROVAL_KEY' not in env and env['NUCLEUS_WORKER'] == '1'


# Started on purpose with the backend's own environment (or one that needs nothing filtered): system tools given
# only a PID or an image name, and the developer-only scripts that assemble the repository's own code.
NO_ENV_NEEDED = {
    'app/backend/core/child_procs.py': 'taskkill on a child PID',
    'app/backend/randall/model_import/chat/import_job.py:_stop': 'taskkill on rigswap\'s PID',
    'app/backend/shared/ingame/boot.py:dolphin_running': 'tasklist by image name',
    'app/backend/projects/lload/gen_code.py': 'developer-only assembler run',
    'app/backend/projects/nowplaying/gen_code.py': 'developer-only assembler run',
    'app/backend/vault/climbers/engine/gen_engine_code.py': 'developer-only assembler run',
}
STARTS = {'Popen', 'run', 'call', 'check_call', 'check_output'}


def _unfiltered_starts():
    """Every subprocess start in the shipped backend that neither passes env= nor the shared helper arguments."""
    listed = subprocess.run(['git', 'ls-files', '--', 'app/backend/*.py'], cwd=REPO, capture_output=True,
                            text=True, check=True).stdout.split()
    found = []
    for rel in listed:
        if rel.startswith('app/backend/devtools/'):
            continue
        source = (REPO / rel).read_text(encoding='utf-8')
        if 'subprocess' not in source:
            continue
        tree = ast.parse(source)
        functions = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for inner in ast.walk(node):
                    functions.setdefault(id(inner), node.name)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in STARTS and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == 'subprocess'):
                continue
            splats = [ast.unparse(k.value) for k in node.keywords if k.arg is None]
            if any(k.arg == 'env' for k in node.keywords) or any(
                    'get_subprocess_args' in s or 'subprocess_kwargs' in s for s in splats):
                continue
            where = f'{rel}:{functions.get(id(node), "<module>")}'
            if rel in NO_ENV_NEEDED or where in NO_ENV_NEEDED:
                continue
            found.append(f'{where} line {node.lineno}')
    return found


def test_every_helper_the_backend_starts_gets_a_filtered_environment():
    """A new subprocess call passes **config.get_subprocess_args() or env=child_environment(...), or says above
    why the backend's own environment is fine for it."""
    assert _unfiltered_starts() == []
    assert BACKEND.is_dir()
