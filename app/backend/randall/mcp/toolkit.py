"""The creation toolkit gateway: ``native_port`` and ``stage_workbench`` over the app's MCP, run by a source checkout.

Fighter ports (the Rivals 2 / Ultimate / Brawl / Slap City readers and the port engine) and the stage builder are
developer tools with heavy dependencies (.NET, UnityPy, ssbh_data_py, ...); the installed app does not carry them.
Instead the app forwards those two tools to a checkout the user sets up once (``tools/creation/setup.ps1``, see
``tools/creation/SETUP.md``) and names with ``connect_creation_toolkit``:

* **Always listed.** Both tools are in tools/list with the harness's own description and inputSchema
  (``toolkit_schemas.py``, a static copy), each description led by ``NEEDS``.
* **Not set up:** a call is isError with the steps (clone ``REPO_URL``, run the setup script, connect the
  folder), and a model with a shell is told to ask the user first.
* **Set up:** the call goes to a child process, ``<toolkit python> <toolkit>/tools/harness/harness_mcp.py`` over
  stdio, kept alive across calls (initialized once, restarted when it died), and its result comes back as it is.
  Only these two names are ever forwarded. The child gets the app's environment without its NUCLEUS_* settings
  (data root, tokens) or a frozen Python's variables: it is a checkout with its own data, not this app.

The folder is saved in ``<storage>/assistant/mcp.json`` once the person in the app's window allowed it
(``window.confirm``): connecting it means running its Python, so the AI client's own approval prompt is not enough.
A network folder is refused before anything is opened or run, and ``creation_toolkit_status`` (read-only) never runs
the saved program.
"""
import base64
import io
import itertools
import json
import re
import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path

from core import config
from core.child_env import child_environment
from core.path_safety import NotLocalPath, is_network_path, local_path

from . import content, window
from .toolkit_schemas import TOOLS as HARNESS_TOOLS

# The toolkit's repository (owner: confirm the public URL at launch). Settings > AI's setup-guide link
# (frontend/src/settings/CreationToolkitSection.jsx CREATION_TOOLKIT_GUIDE) is this plus SETUP.md on main; a test
# (tests/tools/test_app_mcp_toolkit_schemas.py) keeps the two in step.
REPO_URL = 'https://github.com/ssbmNucleus/ssbmNucleus'
SETUP_SCRIPT = 'tools/creation/setup.ps1'
HARNESS = 'tools/harness/harness_mcp.py'
PYTHONS = ('app/venv/Scripts/python.exe', 'app/venv/bin/python', '.venv/Scripts/python.exe', '.venv/bin/python')
FORWARDED = ('native_port', 'stage_workbench')
# The dev harness's other tools a user's AI may run through toolkit_call. Left out on purpose: the dev backend (api,
# backend_start/stop, vault_import, vault_list, retake_csp, build_modded_iso: the app's own tools do these), raw RAM
# pokes (read_ram, write_ram, ram_search, poke_dat, effect_probe), maintenance (csp_regression, mex_codes,
# wait_for_file), hsdraw (the app has its own) and rigswap (import_model is the user's model import).
PASSTHROUGH = ('harness_info', 'dolphin_status', 'boot_match', 'do_move', 'step', 'send_input', 'debug_draw',
               'game_state', 'screenshot', 'set_player', 'freeze', 'end_session', 'frameshot', 'stage_shot',
               'run_ingame_test', 'fps_batch', 'netplay_desync', 'extras_doctor', 'mexcli', 'fsm_patch', 'iso_file',
               'dat_probe', 'detect_content', 'decomp', 'render_csp', 'render_stock')
NEEDS = 'Needs the Nucleus creation toolkit (a source checkout); the app asks for it if it is not set up.\n'
SETTINGS_KEY = 'creation_toolkit'
PROBE_SECONDS = 60
CONFIRM_SECONDS = 300           # how long connect waits for the person's answer in the window
# What tools/creation/requirements.txt installs, by import name. A Python without them still connects (ports can
# name another Python in app/scratch/creation/settings.json), but the report says which are missing.
MODULES = ('UnityPy', 'fmod_toolkit', 'ssbh_data_py', 'scipy', 'shapely', 'pyfqmr', 'yaml', 'cv2')
_PROBE = ('import importlib.util, json; '
          f'print(json.dumps([m for m in {list(MODULES)!r} if importlib.util.find_spec(m) is None]))')
INIT_SECONDS = 180
CALL_SECONDS = 4 * 3600
PROTOCOL = '2025-06-18'

_log = logging.getLogger(__name__)

TOOLS = [dict(tool, description=NEEDS + tool['description'],
              annotations={'title': tool['name'].replace('_', ' ').capitalize(), 'readOnlyHint': False,
                           'destructiveHint': False, 'openWorldHint': False})
         for tool in HARNESS_TOOLS]
GATEWAY_TOOLS = [
    {'name': 'connect_creation_toolkit',
     'description': ('Connect the Nucleus creation toolkit: a source checkout of Nucleus that native_port and '
                     'stage_workbench run in. path is the checkout folder after its setup script ran '
                     f'({SETUP_SCRIPT}). Checks that it holds {HARNESS} and a working Python in app/venv or .venv, '
                     'asks the user to allow it in the Nucleus window (it runs that Python), saves it, and reports '
                     'what it found. A folder on this computer only. Waiting for the answer can take a while: a '
                     'job_id answer is followed with job_status.'),
     'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': ['path'],
                     'properties': {'path': {'type': 'string', 'description': 'Absolute path of the checkout.'}}},
     'annotations': {'title': 'Connect creation toolkit', 'readOnlyHint': False, 'destructiveHint': False,
                     'openWorldHint': False}},
    {'name': 'toolkit_tools',
     'description': (NEEDS + "The creation toolkit's other tools, run with toolkit_call: frame-exact move screenshots "
                     '(frameshot), stage screenshots (stage_shot), a solo match driven frame by frame with hitboxes '
                     'shown (boot_match, do_move, step, send_input, debug_draw, game_state, screenshot, end_session), '
                     'ISO crash and FPS checks (run_ingame_test, fps_batch), a two-account Slippi netplay desync test '
                     '(netplay_desync), extras triage (extras_doctor), the m-ex CLI (mexcli: select-screen layouts, '
                     'music, sound banks), Crazy Hand FSM patches (fsm_patch), ISO and DAT readers (iso_file, '
                     'dat_probe, detect_content), portraits and stock icons from any costume DAT (render_csp, '
                     'render_stock) and the Melee decompilation (decomp). Without names: each one\'s name and summary. '
                     'With names: their full descriptions and inputSchemas, to call them right. Start in-game work '
                     'with harness_info.'),
     'inputSchema': {'type': 'object', 'additionalProperties': False, 'properties': {
         'names': {'type': 'array', 'items': {'type': 'string', 'enum': list(PASSTHROUGH)}, 'minItems': 1,
                   'maxItems': 8}}},
     'annotations': {'title': 'Toolkit tools', 'readOnlyHint': True, 'openWorldHint': False}},
    {'name': 'toolkit_call',
     'description': (NEEDS + 'Run one creation-toolkit tool by name with its arguments (toolkit_tools gives each '
                     "one's inputSchema). Slow ones (a boot, a batch, the desync test) answer with a job_id: follow it "
                     'with job_status. Their files stay in the toolkit checkout; results say where.'),
     'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': ['tool'], 'properties': {
         'tool': {'type': 'string', 'enum': list(PASSTHROUGH)},
         'arguments': {'type': 'object', 'description': "The tool's own arguments (default {})."}}},
     'annotations': {'title': 'Toolkit call', 'readOnlyHint': False, 'destructiveHint': False,
                     'openWorldHint': True}},
    {'name': 'creation_toolkit_status',
     'description': ('Whether the creation toolkit (for native_port and stage_workbench) is set up: the folder '
                     'saved, whether it is valid and why not, and the setup steps when it is missing.'),
     'inputSchema': {'type': 'object', 'additionalProperties': False, 'properties': {}},
     'annotations': {'title': 'Creation toolkit status', 'readOnlyHint': True, 'openWorldHint': False}},
]
NAMES = FORWARDED + tuple(tool['name'] for tool in GATEWAY_TOOLS)


# ------------------------------------------------------------------ the saved folder

def _settings_path():
    return Path(config.STORAGE_PATH) / 'assistant' / 'mcp.json'


def _settings():
    try:
        data = json.loads(_settings_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def saved_path():
    value = _settings().get(SETTINGS_KEY)
    return value if isinstance(value, str) and value.strip() else None


def _save(path):
    target = _settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    data = dict(_settings(), **{SETTINGS_KEY: str(path)})
    temporary = target.with_name(target.name + '.tmp')
    temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
    os.replace(temporary, target)


def setup_steps():
    return [f'Clone {REPO_URL} into a folder: git clone {REPO_URL} "<folder>"',
            f'Run its setup script: powershell -NoProfile -ExecutionPolicy Bypass -File "<folder>\\{SETUP_SCRIPT}"',
            'Call connect_creation_toolkit with that folder\'s absolute path.']


def setup_message(name, reason):
    steps = ' '.join(f'{n}. {step}' for n, step in enumerate(setup_steps(), 1))
    return (f'The Nucleus creation toolkit is not set up ({reason}), so {name} cannot run yet. native_port and '
            'stage_workbench run in a source checkout of Nucleus that this app forwards them to. To set it up: '
            f'{steps} If you have a shell (for example Claude Code), first ask the user "Can I clone the Nucleus '
            'creation toolkit and set it up?" and do it only if they say yes. If you cannot run commands, tell the '
            'user the setup guide is in SSBM Nucleus under Settings > AI > Creation toolkit. stage_workbench also '
            'needs the .NET SDK, and native_port reads source games the user owns.')


# ------------------------------------------------------------------ checking a folder

def _no_window():
    return subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def inspect(path, *, probe=True):
    """What is in ``path``: {path, valid, reason?, python?, harness?, dotnet?}. ``probe`` runs the Python once."""
    report = {'path': str(path) if path else None, 'valid': False}
    if not path:
        return dict(report, reason='no folder is saved')
    try:
        folder = Path(local_path(path, field='folder'))                # the request-path gate
    except NotLocalPath as refused:
        if refused.reason == 'network':
            return dict(report, reason=f'{path} is a network folder; the toolkit must be a folder on this computer')
        return dict(report, reason=f'{path} is not an absolute path')
    if not folder.is_absolute():
        return dict(report, reason=f'{folder} is not an absolute path')
    if not folder.is_dir():
        return dict(report, reason=f'there is no folder at {folder}')
    folder = folder.resolve()
    if is_network_path(folder):
        return dict(report, reason=f'{folder} is on another computer; the toolkit must be a folder on this computer')
    harness = folder / HARNESS
    if not harness.is_file():
        return dict(report, path=str(folder),
                    reason=f'{HARNESS} is missing there, so it is not a Nucleus creation toolkit checkout')
    python = next((folder / rel for rel in PYTHONS if (folder / rel).is_file()), None)
    if python is None:
        return dict(report, path=str(folder), harness=str(harness),
                    reason=f'it has no Python in app/venv or .venv (run {SETUP_SCRIPT} there)')
    found = {}
    if probe:
        try:
            ran = subprocess.run([str(python), '-c', _PROBE], capture_output=True, timeout=PROBE_SECONDS,
                                 creationflags=_no_window(), env=_environment())
        except (OSError, subprocess.TimeoutExpired) as exc:
            return dict(report, path=str(folder), harness=str(harness), python=str(python),
                        reason=f'its Python does not run ({type(exc).__name__}: {exc})')
        if ran.returncode != 0:
            detail = (ran.stderr or b'').decode('utf-8', 'replace').strip()[-300:]
            return dict(report, path=str(folder), harness=str(harness), python=str(python),
                        reason=f'its Python exited with {ran.returncode}' + (f': {detail}' if detail else ''))
        found = _missing_packages(ran.stdout)
    return dict(report, path=str(folder), valid=True, harness=str(harness), python=str(python),
                dotnet=shutil.which('dotnet'), **found)


def _missing_packages(stdout):
    """{missing_packages, packages_note} from the probe's output, or {} when nothing is missing or it said nothing
    readable."""
    lines = (stdout or b'').decode('utf-8', 'replace').strip().splitlines()
    try:
        missing = json.loads(lines[-1]) if lines else None
    except ValueError:
        missing = None
    if not isinstance(missing, list) or not missing:
        return {}
    return {'missing_packages': missing,
            'packages_note': (f"Its Python lacks {', '.join(map(str, missing))} (tools/creation/requirements.txt), so "
                              'the native_port readers that use them will fail. Run the setup script again '
                              f'({SETUP_SCRIPT}), or name a Python that has them as "python" in '
                              'app/scratch/creation/settings.json (tools/creation/SETUP.md).')}


# ------------------------------------------------------------------ the child

def _environment():
    """The child's environment: this process's, without the app's own settings and secrets (every NUCLEUS_*:
    data root, scratch, backend token; credentials such as *_API_KEY) or a frozen Python's variables
    (core/child_env.py)."""
    return child_environment(python=True)


class ChildGone(RuntimeError):
    pass


class _Child:
    """One harness process over stdio: requests matched to responses by id, notifications dropped."""

    def __init__(self, report):
        self.report = report
        self.ids = itertools.count(1)
        self.pending = {}           # id -> [event, response]
        self.lock = threading.Lock()
        log = Path(config.LOGS_PATH) / 'creation_toolkit.log'
        log.parent.mkdir(parents=True, exist_ok=True)
        self.stderr = open(log, 'ab')
        try:
            self.process = subprocess.Popen(
                [report['python'], '-u', report['harness']], cwd=report['path'], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=self.stderr, env=_environment(), creationflags=_no_window())
        except OSError:
            self.stderr.close()
            raise
        from core.child_procs import own
        own(self.process)
        threading.Thread(target=self._read, name='creation-toolkit-reader', daemon=True).start()
        try:
            self.request('initialize', {'protocolVersion': PROTOCOL, 'capabilities': {},
                                        'clientInfo': {'name': 'ssbm-nucleus',
                                                       'version': os.environ.get('NUCLEUS_APP_VERSION', 'dev')}},
                         timeout=INIT_SECONDS)
            self._write({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        except Exception:
            self.stop()
            raise

    def alive(self):
        return self.process.poll() is None

    def _write(self, message):
        line = (json.dumps(message, separators=(',', ':')) + '\n').encode('utf-8')
        with self.lock:
            try:
                self.process.stdin.write(line)
                self.process.stdin.flush()
            except (OSError, ValueError) as exc:
                raise ChildGone(f'the toolkit process is not accepting input ({exc})') from exc

    def _read(self):
        try:
            for raw in self.process.stdout:
                try:
                    message = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(message, dict) or 'id' not in message or 'method' in message:
                    continue        # a notification (progress) or a request of the child's: nothing waits on it
                with self.lock:
                    slot = self.pending.pop(message['id'], None)
                if slot is not None:
                    slot[1] = message
                    slot[0].set()
        finally:
            with self.lock:
                waiting, self.pending = list(self.pending.values()), {}
            for slot in waiting:
                slot[0].set()       # response None: the child is gone

    def request(self, method, params, *, timeout):
        request_id = next(self.ids)
        slot = [threading.Event(), None]
        with self.lock:
            self.pending[request_id] = slot
        self._write({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params})
        if not slot[0].wait(timeout):
            with self.lock:
                self.pending.pop(request_id, None)
            raise TimeoutError(f'the creation toolkit did not answer {method} within {int(timeout)} s')
        if slot[1] is None:
            raise ChildGone(f'the creation toolkit process stopped (exit code {self.process.poll()})')
        return slot[1]

    def stop(self):
        try:
            if self.alive():
                self.process.terminate()
                self.process.wait(timeout=5)
        except Exception:  # noqa: BLE001
            try:
                self.process.kill()
            except Exception:  # noqa: BLE001
                pass
        try:
            self.stderr.close()
        except OSError:
            pass


_child = None
_child_lock = threading.Lock()


def _running_child(report):
    """The child for ``report``'s folder, started (or restarted) when needed."""
    global _child
    with _child_lock:
        if _child is not None and (_child.report['path'] != report['path'] or not _child.alive()):
            _child.stop()
            _child = None
        if _child is None:
            _child = _Child(report)
        return _child


def stop():
    global _child
    with _child_lock:
        if _child is not None:
            _child.stop()
            _child = None


# ------------------------------------------------------------------ the tools

def status(arguments):
    if arguments:
        return content.error('creation_toolkit_status takes no arguments.')
    path = saved_path()
    if not path:
        return content.tool_result('creation_toolkit_status', {
            'configured': False, 'valid': False, 'reason': 'No creation toolkit is set up.', 'repo': REPO_URL,
            'setup': setup_steps()})
    report = inspect(path, probe=False)       # read-only: looks at the folder, runs nothing
    with _child_lock:
        running = _child is not None and _child.alive() and _child.report['path'] == report.get('path')
    result = dict(report, configured=True, running=running)
    if not report['valid']:
        result['setup'] = setup_steps()
    return content.tool_result('creation_toolkit_status', result, is_error=False)


def connect(arguments):
    if not isinstance(arguments, dict) or set(arguments) != {'path'} or not isinstance(arguments['path'], str):
        return content.error('connect_creation_toolkit takes exactly one argument, path (an absolute folder path).')
    report = inspect(arguments['path'].strip(), probe=False)    # nothing runs before the person allows it
    if not report['valid']:
        return content.error(f"That folder cannot be the creation toolkit: {report['reason']}. "
                             + ' '.join(f'{n}. {step}' for n, step in enumerate(setup_steps(), 1)))
    allowed = window.confirm(
        'creation_toolkit', title='Connect a creation toolkit?',
        message=(f"Your AI asks to connect the creation toolkit in {report['path']}. Nucleus will run the Python in "
                 f"that folder ({report['python']}) for native_port and stage_workbench. Allow it only for a "
                 'Nucleus checkout you set up yourself.'),
        detail={'path': report['path'], 'python': report['python']}, confirm_text='Allow',
        timeout=CONFIRM_SECONDS)
    if allowed is None:
        return content.error(f'Nobody answered the question in the Nucleus window within {CONFIRM_SECONDS // 60} '
                             'minutes, so nothing was connected. Ask the user to look at the Nucleus window, then '
                             'call connect_creation_toolkit again.')
    if not allowed:
        return content.error('The user declined connecting this folder in the Nucleus window. Nothing was connected '
                             'or run. Do not ask again unless they say so.')
    report = inspect(report['path'])
    if not report['valid']:
        return content.error(f"That folder cannot be the creation toolkit: {report['reason']}.")
    _save(report['path'])
    stop()      # the next call starts the toolkit from the folder just saved
    note = ('Connected: native_port and stage_workbench now run in this checkout. Start with native_port '
            '{"op":"info"} or stage_workbench {"op":"guide"}.')
    if not report.get('dotnet'):
        note += ' No .NET SDK was found on PATH: stage_workbench inspect and graft need it.'
    if report.get('packages_note'):
        note += ' ' + report['packages_note']
    return content.tool_result('connect_creation_toolkit', dict(report, connected=True, note=note))


def _usable(name):
    """(report, None) for the connected toolkit, or (None, the isError setup result) when there is none."""
    path = saved_path()
    if not path:
        return None, content.error(setup_message(name, 'no toolkit folder is connected'))
    with _child_lock:
        live = _child is not None and _child.alive() and _child.report['path'] == str(Path(path).resolve())
    report = inspect(path, probe=not live)
    if not report['valid']:
        return None, content.error(setup_message(name, f"the saved folder {path} is not usable: {report['reason']}"))
    return report, None


def forward(name, arguments, *, via=None):
    """One harness tool call, run by the toolkit: native_port / stage_workbench, or a PASSTHROUGH tool through
    toolkit_call (``via``). -> its tools/call result, as it is. The child's progress notifications are dropped."""
    if name not in FORWARDED + PASSTHROUGH:
        raise ValueError(f'{name} is not a creation toolkit tool.')
    if not isinstance(arguments, dict):
        return content.error('Tool arguments must be an object.')
    report, refused = _usable(via or name)
    if refused:
        return refused
    try:
        response = _running_child(report).request('tools/call', {'name': name, 'arguments': arguments},
                                                  timeout=CALL_SECONDS)
    except (ChildGone, TimeoutError, OSError) as exc:
        _log.warning('creation toolkit: %s failed: %s', name, exc)
        log = Path(config.LOGS_PATH) / 'creation_toolkit.log'
        return content.error(f'{name} did not finish: {exc}. The toolkit log is {log}; the toolkit restarts on '
                             'the next call.')
    if isinstance(response.get('error'), dict):
        return content.error(f"The creation toolkit refused {name}: {response['error'].get('message')}")
    result = response.get('result')
    if not isinstance(result, dict):
        return content.error(f'The creation toolkit answered {name} without a result.')
    return result


PICTURES = 4                    # pictures a toolkit_call result carries inline; the rest stay paths
PICTURE_WIDTH = 960
_PICTURE = re.compile(r'\.(png|jpe?g)$', re.IGNORECASE)


def _paths_in(value, out):
    if isinstance(value, dict):
        for item in value.values():
            _paths_in(item, out)
    elif isinstance(value, list):
        for item in value:
            _paths_in(item, out)
    elif isinstance(value, str) and _PICTURE.search(value.strip()) and len(value) < 1024:
        try:
            path = Path(local_path(value, field='picture'))   # never a share: is_file would connect to it
        except NotLocalPath:
            return
        if path.is_absolute() and path.is_file() and path not in out:
            out.append(path)


def _picture(path):
    from PIL import Image
    with Image.open(path) as img:
        img = img.convert('RGB')
        if img.width > PICTURE_WIDTH:
            img = img.resize((PICTURE_WIDTH, round(img.height * PICTURE_WIDTH / img.width)))
        buf = io.BytesIO()
        img.save(buf, format='PNG')
    return {'type': 'image', 'data': base64.b64encode(buf.getvalue()).decode('ascii'), 'mimeType': 'image/png'}


def with_pictures(result):
    """A harness result names its pictures as file paths (frameshot, stage_shot, render_csp...): attach the first
    PICTURES of them as images, so a client that cannot open files (a desktop chat app) still sees them."""
    blocks = result.get('content') if isinstance(result, dict) else None
    if result.get('isError') or not isinstance(blocks, list) or any(
            isinstance(b, dict) and b.get('type') == 'image' for b in blocks):
        return result
    paths = []
    for block in blocks:
        if isinstance(block, dict) and block.get('type') == 'text' and isinstance(block.get('text'), str):
            try:
                _paths_in(json.loads(block['text']), paths)
            except ValueError:
                _paths_in(block['text'].split(), paths)
    if not paths:
        return result
    shown = []
    for path in paths[:PICTURES]:
        try:
            shown.append(_picture(path))
        except Exception as exc:  # noqa: BLE001 - an unreadable picture stays a path
            _log.warning('creation toolkit: could not attach %s: %s', path, exc)
    if not shown:
        return result
    note = f'The first {len(shown)} of the {len(paths)} pictures named above are attached.'
    return dict(result, content=blocks + [content.text({'pictures': note})] + shown)


def toolkit_call(arguments):
    """toolkit_call {tool, arguments?}: one PASSTHROUGH tool, forwarded."""
    if not isinstance(arguments, dict) or set(arguments) - {'tool', 'arguments'} or 'tool' not in arguments:
        return content.error("toolkit_call takes 'tool' and optional 'arguments'.")
    tool, inner = arguments['tool'], arguments.get('arguments', {})
    if tool not in PASSTHROUGH:
        return content.error(f'{tool!r} is not a toolkit tool. toolkit_tools lists them: {", ".join(PASSTHROUGH)}.')
    if not isinstance(inner, dict):
        return content.error('arguments must be an object.')
    return with_pictures(forward(tool, inner, via='toolkit_call'))


def toolkit_tools(arguments):
    """toolkit_tools {names?}: the PASSTHROUGH tools as the toolkit lists them (summaries, or full schemas)."""
    if not isinstance(arguments, dict) or set(arguments) - {'names'}:
        return content.error("toolkit_tools takes only 'names'.")
    names = arguments.get('names')
    if names is not None and (not isinstance(names, list) or not names
                              or any(n not in PASSTHROUGH for n in names)):
        return content.error(f'names must list toolkit tools: {", ".join(PASSTHROUGH)}.')
    report, refused = _usable('toolkit_tools')
    if refused:
        return refused
    try:
        response = _running_child(report).request('tools/list', {}, timeout=INIT_SECONDS)
    except (ChildGone, TimeoutError, OSError) as exc:
        return content.error(f'The creation toolkit did not answer: {exc}. It restarts on the next call.')
    listed = [t for t in ((response.get('result') or {}).get('tools') or [])
              if isinstance(t, dict) and t.get('name') in PASSTHROUGH]
    if names:
        tools = [{'name': t['name'], 'description': t.get('description', ''), 'inputSchema': t.get('inputSchema')}
                 for t in listed if t['name'] in names]
    else:
        tools = [{'name': t['name'], 'summary': (t.get('description') or '').split('. ')[0][:240]} for t in listed]
    missing = [n for n in (names or PASSTHROUGH) if n not in {t['name'] for t in listed}]
    result = {'tools': tools, 'call_with': 'toolkit_call {"tool": "<name>", "arguments": {...}}'}
    if missing:
        result['not_in_this_toolkit'] = missing      # an older checkout; pulling it adds them
    return content.tool_result('toolkit_tools', result)
