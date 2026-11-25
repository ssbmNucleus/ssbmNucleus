"""Randall's model import: ``import_model``, one call that runs rigswap on the attached model as a long job.

rigswap is a pipeline of its own (its own repo and Python), run here as a subprocess:
``python -m rigswap.plugins.melee.costume <download> <Fighter> <out> --cache <dir>`` loads the download (an archive,
or a GLB/glTF, FBX, DAE or OBJ file), swaps it onto the fighter and exports the fighter's costume file, then writes
``<out>/result.json`` ({status: 'done'|'failed', fighter, dat, seconds, cost_usd, asks, failed: {stage, cause}}).
``model_import/chat/studio_import.py`` routes an import turn here.

* **The call:** ``import_model(source, fighter?, name?)``. A fighter the user named is the app's name for one of the
  fighters rigswap targets (``RIGSWAP_FIGHTERS``, matched by Pl code: the app says 'C. Falcon', rigswap
  'CaptainFalcon'); one it does not target is a refusal naming them (``fighter_of``). None named: rigswap is run with
  ``auto`` and picks the fighter the model fits best itself; its result names the pick and why (``fighter_pick``),
  which the reply says. Changing the fighter afterwards is a new import naming one.
* **The job:** a project folder ``<imports root>/<id>`` (``new_id``) holding rigswap's output (``rigswap/``), the job
  (``workflow/job.json``) and its log (``workflow/job.log``). The upload is the download as studio_import staged it
  (``<imports root>/.uploads``); rigswap's asks are cached under ``<imports root>/.rigswap-cache``, shared by every
  import (``RIGSWAP_CACHE`` moves it), and sent on the turn's own key (``OPENROUTER_API_KEY`` in rigswap's
  environment, never logged). Where rigswap is: ``RIGSWAP_PYTHON`` and ``RIGSWAP_HOME``, else in a packaged app
  the installer's rigswap package (``RIGSWAP_APP``) on the downloaded tools (``model_import/tools``: its Python and
  Blender 4), and the developer's (``DEV_ENV``) in a checkout (``_defaults``). Tools not downloaded yet, or out of
  date, are a reply of their own before anything runs (``needs_tools``, ``tools_reply``): the user downloads them
  from the card or Settings, then asks again. Anything else missing is a failed reply. The vanilla files come from
  the user's disc (``vanilla_files``).
* **A change afterwards:** ``import_model(project, change)``: the user says what looks wrong with a finished import
  ("the legs look wrong", "his head is too big") and rigswap puts that one thing right (``change``): its ``--fix``
  reads the import's record (the facing, the joints of the body, a few sizes, which of the model's pieces it wears,
  what hangs off the body and swings), one look names the entry to change,
  and the costume is built again from the changed record and saved as a second costume; the first stays. The fighter
  stays; a complaint the record cannot hold (a texture, a piece the model never had) is a failed reply that says so. What
  reaches rigswap's look as the complaint is the user's own message, word for word (``said``, filled in by
  ``studio_import.prepare``); the chat model's ``change`` goes beside it as what it understood (``--heard``), which
  the look uses only to tell which part is meant. 2026-11-09: "it's still too big" went on as "make it much smaller,
  around 0.6", and the head came out at 0.6.
* **Done:** the costume file saved to the vault as a new costume (``studio.finish.finish``, the Slippi fix applied,
  the vault record naming the project), once per costume file and name (``finish/finished.json``: a retry adds no
  second copy). A save refused (a fighter that cannot be finished, no vault here) is said; the import is still done.
  The same model on another fighter is a new call: a second costume, the first stays. The in-game test is not part
  of it.
* **Textures first:** before rigswap runs, the files the model names beside itself (an OBJ's materials and colour
  textures, a DAE's images, an FBX's texture files it does not carry inside, a glTF's buffers and images) are looked
  for where rigswap will look (``textures.missing``). Some missing is a reply of its own (``needs_textures``, no
  project made): what is missing in the app's words (``textures.warning``), and the user is asked for a ZIP that holds
  them, or to say they want it without textures (``untextured``: the call again with it set skips the check).
  2026-11-19 (0.9.0 smoke): a bare Clank.obj came without its .mtl and was saved all white without a word.
* **Failed:** nothing is saved. The reply says where rigswap stopped (loading the file, picking the fighter, or
  putting it on the fighter), its cause in rigswap's words, and what the user can do (``failed_reply``, ``failure_next``); the cause
  as rigswap wrote it stays card-only (``diagnostic``).

Progress: every line rigswap prints goes to ``workflow/job.log`` at once and to the running card (``progress``: the
engine shows it), which ``_Progress`` builds and sends on a worker of its own, coalesced (one at most every
``CARD_GAP`` seconds, the newest state; one that shows nothing new is not sent; none after the reply). The card's
``step`` says where the import is in a few plain words (``STEPS``: "loading the model"), read from rigswap's own
stage lines, never its tools' lines with their paths.
"""
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from core.child_env import child_environment
from shared import mod_files

from . import rigswap_temp, textures

NAME = 'import_model'
SOURCE_LABEL = 'model_import_rigswap'  # the vault record's model_import.source
# What rigswap reads (rigswap load/open.py: an archive, or one of its importers' model files): the chat's model files
# (shared/mod_files.py, the one list) but SMD, which Blender has no importer for.
SOURCES = frozenset({'.zip', *mod_files.MODEL_SUFFIXES} - {'.smd'})
JOB = 'job.json'                       # under <project>/workflow/: the costume's name, the upload, the fighter
LOG = 'job.log'                        # under <project>/workflow/: every progress line
OUT = 'rigswap'                        # under <project>: rigswap's out folder (1-load, 2-swap, result.json)
CACHE = '.rigswap-cache'               # under the imports root: rigswap's asks, shared by every import
RESULT = 'result.json'                 # under OUT: how rigswap ended
DONE = 'done.json'                     # under OUT: rigswap's newest result that made a costume (a change starts there)
FIX = '--fix'                          # rigswap's argument for a change: --fix <out> "<what looks wrong>"
HEARD = '--heard'                      # after it: what the chat model made of the user's words, apart from them
CHANGES = 'rigswap/core/complaint'     # under rigswap's home: the module a rigswap that can make a change has
WORDS = 600                            # characters of the user's complaint passed on
MODULE = 'rigswap.plugins.melee.costume'
AUTO = 'auto'                          # rigswap's fighter argument when none was named: it picks one itself
PROGRESS_LINES = 6                     # the newest lines the running card shows
LINE_CHARS = 300                       # a line longer than this is cut on the card (job.log keeps it whole)
CARD_GAP = 1.0                         # seconds: the running card goes out at most this often (``_Progress``)
CLOSE_WAIT = 30.                       # seconds the reply waits for the last running card to be sent
TIMEOUT = 45 * 60.                     # seconds rigswap may run before it is stopped (a few minutes is usual)
# An import over the app's MCP server has rigswap's AI asks answered by the user's own AI (randall/mcp/model_jobs.py):
# RELAY_ENV names the folder they go through (rigswap/ai.py ``relay``), and no OpenRouter key is passed. Each ask
# waits up to RELAY_WAIT_S for its answer (then rigswap uses its default), and the run up to RELAY_TIMEOUT.
RELAY_ENV = 'RIGSWAP_ASK_RELAY'
RELAY_WAIT_ENV = 'RIGSWAP_ASK_RELAY_WAIT_S'
RELAY_WAIT_S = 10 * 60
RELAY_TIMEOUT = 90 * 60.
CANCEL_POLL = 0.5                      # seconds between checks for the user's Stop while rigswap runs

PYTHON_ENV, HOME_ENV, CACHE_ENV = 'RIGSWAP_PYTHON', 'RIGSWAP_HOME', 'RIGSWAP_CACHE'
FILES_ENV, TARGETS_ENV = 'RIGSWAP_MELEE_FILES', 'RIGSWAP_MELEE_TARGETS'
# Where rigswap is in a source checkout when the environment does not say: its own venv (Python 3.13 with bpy), its
# core worktree (the merged branch), and what rigswap's own loop gives it (rigswap tools/loop/loop.py): the vanilla
# fighter files it writes the costume into (Pl<code>Nr.dat and Pl<code>.dat), its prepared fighter targets (neither
# has a default in rigswap) and the HSDRawViewer that knows ``--dobjs``. Blender 4 falls back to rigswap's own default.
# All of them sit under RIGSWAP_DEV_ROOT (default ~/projects); each setting's own variable still wins (``_setting``).
DEV_ROOT = Path(os.environ.get('RIGSWAP_DEV_ROOT') or Path.home() / 'projects')
DEV_ENV = {PYTHON_ENV: (DEV_ROOT / 'rigswap/.venv/Scripts/python.exe').as_posix(),
           HOME_ENV: (DEV_ROOT / 'rigswap/.claude/worktrees/core').as_posix(),
           FILES_ENV: (DEV_ROOT / 'rigswap-data/melee-files').as_posix(),
           TARGETS_ENV: (DEV_ROOT / 'rigswap-data/targets/melee').as_posix(),
           'RIGSWAP_HSDRAW': (DEV_ROOT / 'rigswap-data/hsdrawviewer/HSDRawViewer.exe').as_posix()}
# A packaged app's rigswap is the installer's compiled package (tools/build/fetch_rigswap.py, pinned by
# utility/rigswap.manifest.json) run on the tools the user downloaded (model_import/tools, utility/
# model_import_tools.json: a CPython 3.13 with rigswap's wheels, and Blender 4), given the app's HSDRawViewer, the
# vanilla files from the user's own disc (``vanilla_files``) and the targets rigswap makes from them on first use,
# under the imports root.
RIGSWAP_APP = 'utility/rigswap/app'
TARGETS = '.rigswap-targets'           # under the imports root: the fighter targets, made once per machine

# The fighters rigswap targets (rigswap/plugins/melee/facts/fighters.py, the ones in scope), by the Pl code the app's
# catalog gives each (shared/modellab/fighter_catalog._CHAR_TO_CODE). Ice Climbers are not one: one model cannot stand
# in for Popo and Nana.
RIGSWAP_FIGHTERS = {
    'Mr': 'Mario', 'Dr': 'DrMario', 'Lg': 'Luigi', 'Pe': 'Peach', 'Kp': 'Bowser', 'Ys': 'Yoshi', 'Dk': 'DonkeyKong',
    'Ca': 'CaptainFalcon', 'Gn': 'Ganondorf', 'Fc': 'Falco', 'Fx': 'Fox', 'Ns': 'Ness', 'Kb': 'Kirby', 'Ss': 'Samus',
    'Zd': 'Zelda', 'Sk': 'Sheik', 'Lk': 'Link', 'Cl': 'YoungLink', 'Pc': 'Pichu', 'Pk': 'Pikachu',
    'Pr': 'Jigglypuff', 'Mt': 'Mewtwo', 'Gw': 'GameAndWatch', 'Ms': 'Marth', 'Fe': 'Roy'}
NOT_TARGETS = {'Ice Climbers': 'one model cannot stand in for the pair, Popo and Nana'}

SCHEMA = {'type': 'function', 'function': {
    'name': NAME,
    'description': (
        'Imports the attached 3D model (a zip, or a GLB/glTF, FBX, DAE or OBJ file; not SMD) as a Melee costume and '
        'saves it to the vault as a new costume. Takes a few minutes; call it once per model, and do not poll. With '
        'no fighter it puts the model on the fighter it fits best, and the reply says which and why. It asks '
        'nothing while it runs. To put the same model on another fighter, call it again with the same source and '
        'that fighter: it saves a second costume and the first stays. When the user says something about how a '
        'finished import looks is wrong (a part too big, too thin, bent or twisted, facing backwards, "the legs look '
        'wrong", a piece that should not be there such as a pack or a prop, a piece of the model that is missing, '
        'hair, cloth or a tail that should swing or should hold still), call it with project and change instead of '
        'source: it builds him again with that one thing changed and saves a second costume. It cannot change '
        'textures or colours, or add a piece the model never had.'),
    'parameters': {'type': 'object', 'additionalProperties': False, 'properties': {
        'source': {'type': 'string', 'description': 'file ID of the attached model (a new import)'},
        'project': {'type': 'string', 'description': "a finished import's project, from its reply: the import to "
                                                     'change (with change, instead of source)'},
        'change': {'type': 'string', 'description': "what the user says looks wrong, in their own words, with the "
                                                    'body part they named ("the legs are too thin and bend '
                                                    'backwards"); one thing per call. The app sends their own '
                                                    'message along with it, so never add a size, a number or an '
                                                    'amount they did not say'},
        'fighter': {'type': 'string', 'description': "the fighter to put it on: leave it unset unless the user "
                                                     'named one or picked it in the chooser (the import picks the '
                                                     'one he fits best; never choose one yourself)'},
        'name': {'type': 'string', 'description': "the costume's name in the vault (default: the model's file "
                                                  'name)'},
        'untextured': {'type': 'boolean', 'description': 'true only when an import_model reply said the model came '
                                                         'without files it names (its materials file, its textures) '
                                                         'and the user said to import it without them anyway'},
    }, 'required': []}}}


# ------------------------------------------------------------------ small helpers

def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _write(path, data):
    """Atomic JSON publish: a reader sees the old file or the new one, never half of it."""
    from file_retry import replace
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + '.pending')
    pending.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    replace(pending, path)


def costume_name(source_name):
    """A vault name from the model's file name: 'elemental-hero-neos.zip' -> 'Elemental Hero Neos'."""
    words = re.sub(r'[\W_]+', ' ', Path(str(source_name)).stem).split()
    return ' '.join(w[:1].upper() + w[1:] for w in words)[:60] or 'Imported model'


def new_id(source_name):
    """A project id (studio_import.IMPORT_ID): the file name's slug plus a short suffix."""
    slug = re.sub(r'[^a-z0-9]+', '-', Path(str(source_name)).stem.lower()).strip('-')[:40] or 'model'
    return f'{slug}-{uuid.uuid4().hex[:6]}'


# ------------------------------------------------------------------ the fighter

def fighters():
    """The app's names of the fighters an import can put a model on, in the catalog's order."""
    from shared.modellab.fighter_catalog import _CHAR_TO_CODE
    return [name for name, code in _CHAR_TO_CODE.items() if code in RIGSWAP_FIGHTERS]


def _ask_which(said):
    return (f"{said} Tell the user, and ask which fighter they want instead (or leave fighter unset, and the import "
            f"picks the one he fits best). The fighters: {', '.join(fighters())}.")


def app_fighter(rigswap_name):
    """The app's name of the fighter rigswap calls ``rigswap_name`` ('CaptainFalcon' -> 'C. Falcon'), else None."""
    from shared.modellab.fighter_catalog import _CHAR_TO_CODE
    key = re.sub(r'[^a-z0-9]', '', str(rigswap_name or '').lower())
    code = next((c for c, name in RIGSWAP_FIGHTERS.items() if name.lower() == key), None) if key else None
    return next((n for n, c in _CHAR_TO_CODE.items() if c == code), None) if code else None


def fighter_of(value):
    """(the app's name, rigswap's name) of the fighter ``value`` names: the app's names and aliases
    (studio_import.fighter_choice: 'falcon' -> 'C. Falcon') or rigswap's own ('CaptainFalcon'). A ValueError the chat
    model can act on (it names the fighters) when rigswap does not target it."""
    from shared.modellab.fighter_catalog import _CHAR_TO_CODE
    from .studio_import import fighter_choice
    name = fighter_choice(value) or app_fighter(value)
    if name in NOT_TARGETS:
        raise ValueError(_ask_which(f'An imported model cannot go on {name}: {NOT_TARGETS[name]}.'))
    code = _CHAR_TO_CODE.get(name)
    if code not in RIGSWAP_FIGHTERS:
        raise ValueError(_ask_which(f'{value!r} is not a fighter an imported model can go on.'))
    return name, RIGSWAP_FIGHTERS[code]


def check(args):
    """Refuse a call that cannot run, in words the chat model can act on; a fighter as the app names it. -> args

    A change (``project`` and ``change``) keeps only those and a name: its fighter is the import's own, and its
    model the one already imported."""
    if args.get('project') or args.get('change'):
        if args.get('change') is not None and not isinstance(args['change'], str):
            raise ValueError('change is what the user says looks wrong, in words ("the legs look wrong"). Another '
                             'fighter is a new import: source and fighter, no project.')
        words = ' '.join(str(args.get('change') or '').split())
        if not args.get('project') or not words:
            raise ValueError("To change a finished import, import_model takes both project (the import's project, "
                             'from its reply) and change (what the user says looks wrong, in their words). A new '
                             'import takes source instead.')
        said = ' '.join(str(args.get('said') or '').split())    # the user's own message: prepare fills it in
        return {k: v for k, v in dict(project=args['project'], change=words[:WORDS], name=args.get('name'),
                                      said=said[:WORDS]).items() if v}
    if not args.get('source'):
        raise ValueError('import_model takes source: the file ID of the attached model (recent_attached_files).')
    if args.get('fighter'):
        args['fighter'] = fighter_of(args['fighter'])[0]
    # untextured: the user said to go on without the texture files the model names (``needs_textures``); only a
    # plain yes counts, and it is kept only when set
    if str(args.pop('untextured', '')).strip().lower() in ('true', '1', 'yes'):
        args['untextured'] = True
    return args


# ------------------------------------------------------------------ the running card

def _steady(value):
    """A card as what it shows, without the times that tick on their own (every ``seconds``): two cards that show the
    same thing compare equal."""
    if isinstance(value, dict):
        return {k: _steady(v) for k, v in value.items() if k != 'seconds'}
    if isinstance(value, list):
        return [_steady(v) for v in value]
    return value


class _Progress:
    """The job's log: every line to <project>/workflow/job.log at once, and the running card via ``progress``
    (``shown``: what every card carries besides its lines, the fighter; ``step``: where the import is, in words, read
    from every line as it comes, ``next_step``). ``refresh``: the card again with no new line.

    The card is built and sent by a worker of its own (``_send``), never on the thread that logged: sending it (the
    chat saved, the stream) takes time the thread reading rigswap's output must not wait for. Cards are coalesced: one
    at most every ``CARD_GAP`` seconds, the newest state each time (the lines that came meanwhile are all in it), and
    one that shows nothing new is not sent. ``close`` (the reply follows) sends the card still due and ends the
    worker: no running card comes after the reply."""

    def __init__(self, progress, root, project_id, started, shown=None):
        self.progress, self.root, self.id, self.started, self.lines = progress, Path(root), project_id, started, []
        self.static = dict(shown or {})
        self.step = None
        self.lock = threading.RLock()
        self.wake = threading.Condition(self.lock)
        self.due = self.closed = self.abandoned = False
        self.worker = self.last = self.shown = None

    def __call__(self, line):
        line = str(line)
        with self.lock:
            self.lines.append(line)
            self.step = next_step(self.step, line)
            if not self.static.get('fighter'):
                onto = next((m.group(1) for m in (p.match(line) for p in _ONTO_LINES) if m), None)
                fighter = app_fighter(onto) if onto and onto != AUTO else None
                if fighter:     # a new dict, never one changed in place: the card worker spreads it unlocked
                    self.static = {**self.static, 'fighter': fighter}
            try:
                folder = self.root / 'workflow'
                if self.root.is_dir():
                    folder.mkdir(exist_ok=True)
                    with open(folder / LOG, 'a', encoding='utf-8') as stream:
                        stream.write(f'{time.strftime("%H:%M:%S")} {line}\n')
            except OSError:
                pass
            self._due()

    def refresh(self):
        with self.lock:
            self._due()

    def close(self):
        """The reply follows: the card still due goes now, then no more (waits for the worker)."""
        with self.lock:
            self.closed = True
            self.wake.notify_all()
            worker = self.worker
        if worker is not None:
            worker.join(timeout=CLOSE_WAIT)
            # A send that hangs: whatever it builds now is never sent after the reply. One already inside
            # ``progress`` may still finish after it: the engine drops it then (engine.py ``update_batch``).
            if worker.is_alive():
                self.abandoned = True
                logging.getLogger(__name__).warning('the running card of %s did not finish sending', self.id)

    def _due(self):
        """A card is due (under the lock): the worker sends it when the gap since the last one allows."""
        if self.progress is None or self.closed:
            return
        self.due = True
        if self.worker is None:
            self.worker = threading.Thread(target=self._send, name=f'import-card-{self.id}', daemon=True)
            self.worker.start()
        self.wake.notify_all()

    def _send(self):
        while True:
            with self.lock:
                while not self.due and not self.closed:
                    self.wake.wait()
                while not self.closed and self.last is not None and time.monotonic() < self.last + CARD_GAP:
                    self.wake.wait(self.last + CARD_GAP - time.monotonic())
                if not self.due:            # closed, nothing left to send
                    return
                self.due = False
                lines, step = list(self.lines[-PROGRESS_LINES:]), self.step
            self._card(lines, step)
            with self.lock:
                self.last = time.monotonic()

    def _card(self, lines, step=None):
        try:
            card = dict(status='running', project=self.id, **self.static,
                        progress=[line if len(line) <= LINE_CHARS else line[:LINE_CHARS - 1] + '…' for line in lines],
                        **({'step': STEPS[step]} if step else {}),
                        seconds=round(time.monotonic() - self.started, 1), studio_import={'tool': NAME, 'id': self.id})
            shown = _steady(card)
            if shown == self.shown or self.abandoned:
                return
            self.progress(card)
            self.shown = shown
        except Exception:       # a card that cannot update never stops the import
            logging.getLogger(__name__).debug('running card not sent for %s', self.id, exc_info=True)


# ------------------------------------------------------------------ rigswap

def _frozen():
    return bool(getattr(sys, 'frozen', False))


BLENDER_ENV = 'RIGSWAP_BLENDER4'


def _defaults():
    """What rigswap is given where the environment says nothing: in a source checkout ``DEV_ENV``; in a packaged app
    the installer's rigswap package (``RIGSWAP_APP``), the downloaded tools' Python and Blender 4 (when they are the
    ones this app pins: ``model_import/tools/service.installed``), the app's HSDRawViewer (the headless one on macOS
    and Linux) and the targets folder. The vanilla files are the app's to fetch (``vanilla_files``)."""
    if not _frozen():
        return DEV_ENV
    from core.config import HSDRAW_EXE, RESOURCES_DIR
    from randall.model_import.tools import service
    from . import studio_import
    tools = service.installed() or {}
    found = {PYTHON_ENV: tools.get('python'), HOME_ENV: Path(RESOURCES_DIR) / RIGSWAP_APP, 'RIGSWAP_HSDRAW': HSDRAW_EXE,
             TARGETS_ENV: Path(studio_import.root()) / TARGETS, BLENDER_ENV: tools.get('blender')}
    return {name: str(path) for name, path in found.items() if path}


def _setting(name):
    """An environment setting for rigswap, else its default (``_defaults``), else None."""
    return (os.environ.get(name) or '').strip() or _defaults().get(name) or None


# The model import tools (docs/dev/MODEL_IMPORT_TOOLS.md): a packaged app downloads rigswap's Python and Blender 4 on
# the user's request. Not there, or not the ones this app pins: the import says so (``tools_reply``) and starts
# nothing.
TOOLS_MISSING = ("model import needs its tools (Blender and the importer's Python), and they are not downloaded "
                 'yet. Download them in Settings > AI > Model import tools')
TOOLS_OUTDATED = ('model import needs an update of its tools (Blender and the importer\'s Python) for this version '
                  'of the app. Update them in Settings > AI > Model import tools')
TOOLS_DOWNLOADING = 'model import\'s tools are still downloading; it can run once the download has finished'
TOOLS_UNSUPPORTED = 'model import is not available on this computer yet'
# {download}: the size and where the files come from, this platform's (``_download``: the Settings card's sources).
TOOLS_NEXT = (
    'Nothing ran and nothing was saved: {words}. The card above your reply has a Download button for them '
    '({download}; also in Settings > AI). Say this in one '
    'or two plain sentences: the tools need downloading first, and once that has finished they can ask you to '
    'import it again. Do not call import_model again this turn.')
TOOLS_NEXT_MCP = (
    'Nothing was started: {words}. Tell the user to open SSBM Nucleus, go to Settings > AI > Model import '
    'tools and press Download ({download}), then call '
    'import_model again. Do not try to download them yourself.')


def tools_needed():
    """None when rigswap has what it runs on; else what the tools lack (``service.need``: state, sizes). Only a
    packaged app downloads its tools: a checkout runs ``DEV_ENV``, and a RIGSWAP_PYTHON and RIGSWAP_BLENDER4 given
    in the environment stand in for them."""
    if not _frozen() or ((os.environ.get(PYTHON_ENV) or '').strip() and (os.environ.get(BLENDER_ENV) or '').strip()):
        return None
    from randall.model_import.tools import service
    try:
        return service.need()
    except Exception:          # the import says what it can; a broken status never hides the real cause
        logging.getLogger(__name__).warning('import_model: the tools status failed', exc_info=True)
        return None


def tools_words(need):
    state = (need or {}).get('state')
    return {'update_needed': TOOLS_OUTDATED, 'downloading': TOOLS_DOWNLOADING,
            'unsupported': TOOLS_UNSUPPORTED}.get(state, TOOLS_MISSING)


def _size(value):
    value = int(value or 0)
    return f'about {value / 1e9:.1f} GB' if value >= 1e9 else f'about {max(1, round(value / 1e6))} MB'


def _download(need):
    """'about 779 MB, a one-time download from download.blender.org, python-build-standalone (GitHub) and PyPI
    (files.pythonhosted.org)': the size and this platform's sources (``service.need`` ``sources``: what the Settings
    card names, from the manifest and ``service.SOURCES``)."""
    size = _size(need.get('needed_bytes') or need.get('download_bytes'))
    named = [str(s) for s in need.get('sources') or () if s]
    places = ', '.join(named[:-1]) + f' and {named[-1]}' if len(named) > 1 else ''.join(named)
    return f'{size}, a one-time download' + (f' from {places}' if places else '')


def tools_reply(need, *, mcp=False):
    """The reply of an import that cannot run because the tools are missing or out of date: nothing ran, the user
    downloads them (the card's Download button, Settings) and asks again. Over MCP the words send them to Settings;
    nothing downloads by itself."""
    words = tools_words(need)
    tools = {key: need.get(key) for key in ('state', 'download_bytes', 'needed_bytes', 'disk_bytes')}
    return dict(status='needs_tools', tools=tools, warning=words[0].upper() + words[1:] + '.',
                next=(TOOLS_NEXT_MCP if mcp else TOOLS_NEXT).format(words=words, download=_download(need)))


def setup():
    """(rigswap's Python, its source root), or a string saying what is missing (a failed reply's diagnostic). The
    entry point is source in a checkout and bytecode where the installer compiled it. A packaged app whose downloaded
    tools are missing or out of date: their words (``TOOLS_MISSING``...)."""
    need = tools_needed()
    if need:
        return tools_words(need)
    python, home = _setting(PYTHON_ENV), _setting(HOME_ENV)
    if not python or not Path(python).is_file():
        return f'{PYTHON_ENV} ' + (f'names no Python: {python}' if python else 'is not set')
    entry = Path(home or '') / Path(*MODULE.split('.'))
    if not home or not any(entry.with_suffix(end).is_file() for end in ('.py', '.pyc')):
        return f'{HOME_ENV} ' + (f'holds no {MODULE}: {home}' if home else 'is not set')
    return Path(python), Path(home)


# The vanilla files rigswap reads, from the user's own disc: each target fighter's costume, data and animations, and
# the common fighter file (rigswap plugins/melee: export, targets/prepare.py, targets/frames.py).
VANILLA = tuple(f'Pl{code}{end}.dat' for code in RIGSWAP_FIGHTERS for end in ('Nr', '', 'AJ')) + ('PlCo.dat',)
NO_DISC = 'the importer needs your vanilla Melee disc, and none is set in Settings'


def vanilla_files():
    """The folder holding ``VANILLA``, each taken from the user's vanilla disc the first time it is needed
    (shared/vanilla_extract/vanilla_refs: never a file of ours), or what is missing, in words."""
    from shared.vanilla_extract import vanilla_refs
    found = {name: vanilla_refs.ensure_vanilla_ref(name) for name in VANILLA}
    missing = [name for name, path in found.items() if path is None]
    if not missing:
        return found[VANILLA[0]].parent
    if vanilla_refs.known_vanilla_iso() is None:
        return NO_DISC
    return (f'{len(missing)} of the fighter files could not be read from your vanilla Melee disc '
            f"({', '.join(missing[:3])})")


def _secret_file():
    return Path(os.environ.get('USERPROFILE') or Path.home()) / '.nucleus-secrets' / 'openrouter.key'


def openrouter_key(key=None):
    """The OpenRouter key rigswap's asks send with: the turn's own (``key``), else OPENROUTER_API_KEY (not a 1Password
    reference), else the secrets file. None when there is none. Never printed or logged."""
    if isinstance(key, str) and key.strip():
        return key.strip()
    value = (os.environ.get('OPENROUTER_API_KEY') or '').strip()
    if value and not value.startswith('op://'):
        return value
    secret = _secret_file()
    try:
        value = secret.read_text(encoding='utf-8').strip() if secret.is_file() else ''
    except OSError:
        value = ''
    return value or None


def _environment(key, files=None, relay=None, temp=None):
    """rigswap's environment: the app's, with its defaults where the app's says nothing (``files``: the vanilla
    files' folder), unbuffered UTF-8 output, no Python path of the app's, and the turn's key as OPENROUTER_API_KEY
    (``openrouter_key``: the turn's own, else the machine's). No key found: none is passed, and rigswap looks for its
    own. ``relay``: the folder rigswap's asks go through instead (RELAY_ENV), with no key at all. ``temp``: the run's
    own temp folder (``rigswap_temp.make``), as its TMPDIR, TEMP and TMP, and so its tools' (Blender's).
    Nothing else of Nucleus's (core/child_env.py): no backend token, window key or other credential, since rigswap
    and Blender read the downloaded model; the OpenRouter key below is the one secret it is given on purpose."""
    env = child_environment(python=True)
    for name, value in {**_defaults(), **({FILES_ENV: str(files)} if files else {})}.items():
        if not (env.get(name) or '').strip():
            env[name] = value
    # No bytecode: rigswap's package sits inside the install (a signed macOS bundle, a read-only AppImage), and
    # the loose .py files Blender 4 needs (load/convert.py, materials.py) got __pycache__ written beside them.
    env.update(PYTHONDONTWRITEBYTECODE='1')
    if temp is not None:
        env.update(TMPDIR=str(temp), TEMP=str(temp), TMP=str(temp))
    if relay is not None:
        env.update({RELAY_ENV: str(relay), RELAY_WAIT_ENV: str(RELAY_WAIT_S)})
        env.pop('OPENROUTER_API_KEY', None)
        return env
    env.pop(RELAY_ENV, None)
    found = openrouter_key(key)
    if found:
        env['OPENROUTER_API_KEY'] = found
    else:
        env.pop('OPENROUTER_API_KEY', None)
    return env


STOP_GRACE = 5.0       # seconds rigswap's process group gets to end on SIGTERM before SIGKILL (macOS, Linux)


def _own_group():
    """Popen arguments: on macOS and Linux rigswap leads a session of its own, so a stop reaches what it started
    (Blender 4, the headless viewer) and nothing else; Windows stops the tree by PID."""
    return {} if os.name == 'nt' else {'start_new_session': True}


def _stop(process, why):
    """End rigswap and what it started (Blender, HSDRawViewer): by its PID or its own process group, never by image
    name."""
    why.append('stopped')
    if process.poll() is not None:
        return
    if os.name == 'nt':
        from core.config import get_subprocess_args
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True,
                       **get_subprocess_args())
        return
    import signal
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:         # not a group of its own after all: rigswap alone, as before
        process.kill()
        return
    try:
        process.wait(STOP_GRACE)
    except subprocess.TimeoutExpired:
        pass
    try:                            # what ignored SIGTERM, or outlived rigswap in its group
        os.killpg(process.pid, getattr(signal, 'SIGKILL', 9))
    except (ProcessLookupError, PermissionError):
        pass


def rigswap(python, home, download, fighter, out, *, cache, key=None, files=None, log=print, cancelled=None,
            change=None, heard=None, relay=None):
    """Run rigswap on ``download`` for ``fighter`` (rigswap's name) into ``out``, each line it prints to ``log`` as it
    comes; ``files``: the vanilla files' folder (``vanilla_files``) when the environment names none. ``change``: what
    looks wrong with the costume already made in ``out``, in the user's words: rigswap changes that one thing and
    builds it again (``FIX``; ``download`` and ``fighter`` are not read); ``heard``: what the chat model made of
    those words, shown to rigswap's look apart from them (``HEARD``). -> its result.json; a failed result with no
    stage when it wrote none (it did not start, crashed or ran past ``TIMEOUT``), its exit and last lines in
    ``error``. ``cancelled``: polled while it runs; true ends rigswap. ``relay``: the folder its asks are answered
    through (``_environment``), which gives it RELAY_TIMEOUT. Its temp files go in a folder of the run's own, removed
    when rigswap has ended, however it ended (``rigswap_temp``: a stopped run cannot clean up after itself)."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / RESULT).unlink(missing_ok=True)      # a change starts from DONE, which stays
    if change is not None:
        command = ([str(python), '-m', MODULE, FIX, str(out), str(change)]
                   + ([HEARD, str(heard)] if heard else []) + ['--cache', str(cache)])
    else:
        command = [str(python), '-m', MODULE, str(download), fighter, str(out), '--cache', str(cache)]
    started, tail, why = time.monotonic(), [], []
    from randall.model_import.tools import service
    service.import_started()        # Remove waits while rigswap runs on the downloaded tools
    temp = None
    try:
        temp = rigswap_temp.make()
        return _run_rigswap(command, home, out, key, files, relay, cancelled, log, started, tail, why, temp)
    finally:
        rigswap_temp.remove(temp)
        service.import_ended()


def _run_rigswap(command, home, out, key, files, relay, cancelled, log, started, tail, why, temp=None):
    from core.config import get_subprocess_args
    try:
        process = subprocess.Popen(command, cwd=str(home), stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                   errors='replace', bufsize=1,
                                   **{**get_subprocess_args(), 'env': _environment(key, files, relay, temp)},
                                   **_own_group())
    except OSError as exc:
        return dict(status='failed', failed=dict(stage=None, cause=None), seconds=0., cost_usd=0.,
                    error=f'rigswap did not start: {type(exc).__name__}: {exc}')
    limit = RELAY_TIMEOUT if relay is not None else TIMEOUT
    watchdog = threading.Timer(limit, _stop, (process, why))
    watchdog.daemon = True
    watchdog.start()
    returned = threading.Event()
    if cancelled is not None:
        def stop_on_cancel():
            while not returned.wait(CANCEL_POLL):
                if cancelled():
                    _stop(process, why)
                    return
        threading.Thread(target=stop_on_cancel, daemon=True, name='rigswap-stop').start()
    try:
        for line in process.stdout:
            line = line.rstrip()
            if line.strip():
                tail = (tail + [line])[-8:]
                log(line)
        code = process.wait()
    finally:
        returned.set()
        watchdog.cancel()
        if process.poll() is None:
            _stop(process, why)
    try:
        result = json.loads((out / RESULT).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        result = None
    if isinstance(result, dict) and result.get('status') in ('done', 'failed'):
        return result
    ended = f'stopped after {limit:.0f} s' if why else f'exited {code}'
    return dict(status='failed', failed=dict(stage=None, cause=None), seconds=round(time.monotonic() - started, 1),
                cost_usd=0., error=f'rigswap {ended} without {RESULT}; its last lines: ' + ' | '.join(tail))


# ------------------------------------------------------------------ the costume and the vault

def _save(folder, dat, fighter, name, receipts='finish'):
    """The vault save (studio.finish.finish, looked up at call time so a harness can stand in for it): the costume
    file as a new costume on ``fighter`` (the app's name), the Slippi fix applied, the record naming the project. Once
    per costume file and name: ``finish/finished.json`` keeps the receipt, and a retry adds no second copy
    (``receipts``: the folder of a change's own receipt and portrait, ``finish-2`` for the first change)."""
    from core.hashing import sha256_file
    from randall.model_import.studio import finish as finishing
    if not dat or not Path(dat).is_file():
        raise finishing.FinishError('The import wrote no costume file.')
    if not fighter:
        raise finishing.FinishError('The import did not say which fighter it put the model on.')
    receipt = Path(folder) / receipts / 'finished.json'
    key = dict(dat_sha256=sha256_file(dat), name=name, slot=None)
    if receipt.is_file():
        done = _read(receipt)
        if all(done.get(k) == v for k, v in key.items()):
            return dict(done['result'], note='This exact costume was already saved; nothing new was added.')
    # Owner decision 2026-09-27: finishing always applies the Slippi fix.
    result = finishing.finish(dat, fighter, name, out_dir=receipt.parent, slippi_fix=True, project=Path(folder),
                              source=SOURCE_LABEL)
    result = json.loads(json.dumps(result, default=str))
    try:
        _write(receipt, dict(key, result=result))
    except OSError:
        # The costume is in the vault already: it is reported saved. Only a same-project retry's skip is lost.
        logging.getLogger(__name__).warning('import_model: the save receipt was not written', exc_info=True)
    return result


def _saved(receipt):
    vault = receipt.get('vault') or {}
    return dict(name=vault.get('name'), character=vault.get('character'), skin_id=vault.get('skin_id'),
                costume_code=vault.get('costume_code'), slot=vault.get('slot'), installable=receipt.get('installable'),
                slippi_safe=vault.get('slippi_safe'), project=vault.get('project'), notes=receipt.get('notes') or [],
                **({'note': receipt['note']} if receipt.get('note') else {}))


# ------------------------------------------------------------------ the reply

# Where rigswap stops, in words: its stages (result.json's failed.stage), and what a user of the chat can do about a
# failure in each. Loading reads the file (an archive or a model file); getting ready makes the fighters rigswap reads
# from the user's game files, once per machine (rigswap's costume.ready); picking (no fighter named) chooses the
# fighter the model fits best; swapping puts the model on the fighter.
STAGES = {'fix': ('Work out the change', 'while working out what to change'),
          'load': ('Load the model', 'while loading the model file'),
          'ready': ('Get the fighters ready', 'while getting the fighters ready from your game files'),
          'pick': ('Pick the fighter', 'while picking the fighter it fits best'),
          'swap': ('Put it on the fighter', 'while putting the model on {fighter}')}
# The same stages while they run, as a running import shows them (the card's ``step``, which the window's chip for an
# import the user's AI runs over MCP shows), plus a change's build (``again``) and the vault save. Each starts with
# the line rigswap (plugins/melee/costume.py) or this module prints as it begins; the step is never read from the
# lines of the tools rigswap runs (Blender's, with their clocks and file paths). A step only goes forward, so a stray
# line that reads like an earlier stage's never takes it back.
STEPS = {'fix': 'working out the change', 'load': 'loading the model', 'ready': 'getting the fighters ready',
         'pick': 'picking the fighter', 'swap': 'putting it on the fighter', 'again': 'building it again',
         'save': 'saving it to your vault'}
_STEP_RANK = {'fix': 0, 'load': 0, 'ready': 1, 'pick': 2, 'swap': 3, 'again': 3, 'save': 4}
_STEP_LINES = ((re.compile(r'import \S.* onto |loading \S'), 'load'),
               (re.compile(r'change \S.* on \S.*: |looking at what was said$|changing \S'), 'fix'),
               (re.compile(r'getting \S+ ready from the game files'), 'ready'),
               (re.compile(rf'swapping onto {AUTO}$'), 'pick'),
               (re.compile(r'swapping onto \S|picked \S+: |the draft looks wrong'), 'swap'),
               (re.compile(r'building it again onto \S'), 'again'),
               (re.compile(r'saving the costume to the vault$'), 'save'))
# rigswap's line when it picks the fighter itself (no fighter named), or once it puts the model on one: the running
# card names that fighter from then on, so the window's chip says "as Mario" (0.9.0 launch video: it never did).
_ONTO_LINES = (re.compile(r'picked (\S+): '), re.compile(r'swapping onto (\S+)$'))


def next_step(step, line):
    """The running import's step (a ``STEPS`` key) after ``line``; ``step``: the one before it (None at first)."""
    for pattern, found in _STEP_LINES:
        if pattern.match(line):
            return found if step is None or _STEP_RANK[found] >= _STEP_RANK[step] else step
    return step


CAN_DO = {
    'fix': ('say what looks wrong another way: which part of the body, and how (too big, too thin, bent the wrong '
            'way, facing backwards, a piece to take off or put back, a part that should swing or hold still)',
            'import it onto another fighter', 'report it'),
    'load': ('attach the model again in another format (FBX, DAE, OBJ or GLB/glTF; SMD is not read), or as an archive '
             'holding the model file with its textures', 'report it'),
    'ready': ('check that the disc set in Settings is an unmodified Melee 1.02 disc, then import it again',
              'report it'),
    'pick': ('import it again naming the fighter to put it on', 'report it'),
    'swap': ('import it onto another fighter', 'import another model of the character (another download or version)',
             'report it'),
}
CAN_DO_ELSE = ('report it',)
CAN_DO_DISC = ('set their vanilla Melee disc in Settings, then import it again', 'report it')
CAN_DO_UNEXPECTED = ('report it', 'import it again')
# The exception types whose words are rigswap's own reason (its located ``Failed``, and what its loading and body
# reading raise with the reason in the message); any other is an internal error, said as one.
PLAIN = ('Failed', 'RuntimeError', 'ValueError', 'Unfixable')
NOT_SET_UP = 'the importer is not set up in this copy of the app'
NO_CHANGES = 'the importer in this copy of the app cannot change a finished import yet'
NOT_CHANGEABLE = 'this import has no finished costume that can be changed (it failed, or it was made before changes)'
CAN_DO_AGAIN = ('import the model again, then say what looks wrong', 'report it')
# A change that failed saved nothing new; the costume it started from is untouched (said in place of FAILED_NEXT's
# and UNEXPECTED_NEXT's first sentence).
NOT_CHANGED = 'The change was not made and nothing new was saved; the costume from before is still in their vault.'
FAILED_NEXT = ('Nothing was saved. The import stopped{where} because: {cause}. Tell the user this cause in a sentence '
               'or two of plain words and nothing more: do not add a reason of your own, and do not infer one from '
               "the model's name or file name. If the cause does not say why, say you could not tell why. Then offer "
               'what they can do: {can_do}.')
UNEXPECTED_NEXT = ('Nothing was saved. The import stopped{where} because of {cause}. Tell the user in a sentence or '
                   'two of plain words that something went wrong on your side, that you cannot tell whether it was '
                   'you or something in their model, and that they can report it; do not add a reason of your own, '
                   "and do not infer one from the model's name or file name. Then offer what they can do: {can_do}.")
CAUSE = 600             # characters of the cause kept in the reply


def failed_reply(failed, fighter=None):
    """The reply's ``failed`` from rigswap's (result.json's {stage, cause}, the cause as ``Type: words``):
    dict(stage ('load', 'swap' or None: rigswap wrote no result), name, where, kind ('located': its own words, or
    'unexpected': an internal error, said as one), cause, can_do)."""
    stage = failed.get('stage') if failed.get('stage') in STAGES else None
    raw = str(failed.get('cause') or '').strip()
    kind_of, _, words = raw.partition(': ')
    name, where = STAGES.get(stage, (None, None))
    where = where.format(fighter=fighter or 'the fighter') if where else None
    if stage and kind_of in PLAIN and words.strip():
        return dict(stage=stage, name=name, where=where, kind='located', cause=words.strip()[:CAUSE],
                    can_do=list(CAN_DO[stage]))
    return dict(stage=stage, name=name, where=where, kind='unexpected', cause='an internal error in the importer',
                can_do=list(CAN_DO_UNEXPECTED))


def failure_next(failed):
    """The reply's ``next`` for a failure: the cause as the import gave it, nothing added, and what the user can do.
    ``failed``: ``failed_reply``'s, or ``unexpected``'s for a fault outside rigswap's stages."""
    listed = '; '.join(failed.get('can_do') or CAN_DO_UNEXPECTED)
    cause = str(failed.get('cause') or 'the import did not say').rstrip('.')
    where = f" {failed['where']}" if failed.get('where') else ''
    if failed.get('kind') == 'unexpected':
        return UNEXPECTED_NEXT.format(where=where, cause=cause, can_do=listed)
    return FAILED_NEXT.format(where=where, cause=cause, can_do=listed)


def unexpected(diagnostic, cause='an internal error in the importer', can_do=CAN_DO_UNEXPECTED, kind='unexpected'):
    """The reply for a fault outside rigswap's own stages (the import not set up, a crash in this module): said as
    one, or with ``kind='located'`` as the known cause it is, its detail card-only (``diagnostic``, kept for "Report
    this chat")."""
    failed = dict(stage=None, name=None, where=None, kind=kind, cause=cause, can_do=list(can_do))
    return dict(status='failed', error=cause, failed=failed, next=failure_next(failed),
                diagnostic=str(diagnostic)[:800])


DONE_NEXT = (
    'The card above your reply already shows the saved name, the fighter and its portrait, so do not repeat them. '
    'Reply in one or two short sentences in your own voice: that he (or it) is on {fighter} and in their vault; if it '
    'was not saved, say why in one sentence.{warned}{picked} The picture is its portrait, for you only: never mention '
    'it. No steps, no technical details, no caveats or guesses of your own about how it looks; never mention the '
    'import itself, file names or anything else the user cannot see. If the user wants it on another fighter, call import_model again '
    'with the same source and that fighter: it saves a second costume. If the user says something about how he looks '
    'is wrong (a part too big, thin, bent or twisted, facing backwards, a piece to take off or one that is missing, '
    'a part that should swing or hold still), call import_model with project "{project}" '
    'and change set to their words: it builds him again with that one thing changed. The in-game test runs only if '
    'they ask for it.')
# A change that was made (result.json's ``changed`` {entry: [was, is]} and ``why``, the look's sentence): the user
# hears what was changed, and is asked to look. Nothing here has seen the result, so it is never called fixed.
CHANGED_NEXT = (
    'The card above your reply already shows the saved name, the fighter and its portrait, so do not repeat them. '
    'The import was built again with one thing changed ({changed}){why}. Reply in one or two short sentences in your '
    'own voice: what you changed, in plain words without numbers or joint names, that it is saved as a second costume '
    'and the first is still in their vault, and ask them to have a look; if it was not saved, say why in one '
    'sentence.{warned} Never say it is fixed or looks right: you have not seen it. The picture is its portrait, for you '
    'only: never mention it. No steps, no technical details; never mention the import itself, file names or anything '
    'else the user cannot see. If something still looks wrong to them, call import_model again with project '
    '"{project}" and change set to their words. The in-game test runs only if they ask for it.')
# rigswap's own look at the finished costume called it a wreck (result.json's ``warning``): the user hears its words as
# they are. 2026-11-19 (0.9.0 smoke): "this probably did not work: Small parts float apart from the body during the
# run" reached the user as "One caution: small parts may float apart", so its verdict is passed on whole.
WARNED_NEXT = (" But the import's own check of the finished costume says: \"{warning}\" Add one sentence that passes "
               "this on word for word (\"The import's own check says this probably did not work: ...\"): never soften "
               'it ("may", "might", "a bit", "one caution") and never call the costume done or fine. Then offer to '
               'try putting it right if they tell you what looks wrong, or to import it onto another fighter.')
# No fighter named: rigswap picked one (result.json's fighter_pick), and the user hears which and why; or it could not
# tell (picked false: its first fighter stood), and the user hears that.
PICKED_NEXT = (' No fighter was named, so the import picked {fighter} because: {why}. Say which fighter and that '
               'reason in a few plain words of your own ("I put him on {fighter}: ..."), without numbers.')
UNPICKED_NEXT = (' No fighter was named and the import could not tell which one he fits best, so he is on {fighter}. '
                 'Say so in a few plain words, and that they can name another fighter to import him onto.')
# A saved costume can be played at once: a request that already asked to see or test it in game gets its play
# session in the same turn instead of a promise. The play instruction comes FIRST and holds the reply back until the
# session has started: read after DONE_NEXT's "Reply in one or two short sentences", it made the model write its
# summary, call test_in_game in the same response, then write the summary again (2026-10-06 take4: two near-identical
# replies four seconds apart). `PLAY_ELSE` replaces DONE_NEXT's last sentence.
PLAY_FIRST = (
    'First, in game: if the user asked in this request to see, test or play it in game, call test_in_game now with '
    'action "start", kind "costume", character "{character}" and skin_id "{skin_id}", with no text before the call '
    '(at most "Now the in-game test."). Write the reply below only after test_in_game returns, once, as your one '
    'closing reply for both (two or three short sentences in all), adding what its result says about where and how '
    'they play. The game is still getting ready then, so never say it is running or that he is in the game yet. It '
    'builds its own test copy from their clean Melee and needs no game copy of theirs, so say nothing about game '
    'copies or "My game". The reply: ')
# The model names files that did not come with it (``textures.missing``: its materials file, its textures): nothing
# runs, and the user is asked. Each file is called what the warning calls it (0.9.0 smoke: Randall called a missing
# Clank.mtl "a texture file").
TEXTURES_NEXT = (
    'Nothing was imported yet. {warning} Say that plainly in one or two short sentences, naming each missing file as '
    'the warning does (a materials file is not a texture), '
    'and ask the user to attach a ZIP that holds the model together with those files, or to say if they want it '
    'imported without textures anyway. Do not call import_model again until they answer. A ZIP they attach is a new '
    'import of that ZIP; only when they say to go on without the textures, call import_model with the same source '
    'and untextured true.')
TEXTURES_NEXT_MCP = (
    'Nothing was imported yet. {warning} Tell the user that plainly, naming each missing file as the warning does (a '
    'materials file is not a texture). To import it with its '
    'textures, put those files beside the model (or zip the model together with them) and call import_model again. '
    'Only if the user says to import it without textures, call import_model again with the same source and '
    'untextured true.')


def textures_reply(gap, *, mcp=False):
    """The reply for a model without the texture files it names (``textures.missing``'s ``gap``): nothing ran, no
    project. ``mcp``: for the user's own AI over the app's MCP server (``TEXTURES_NEXT_MCP``)."""
    warning = textures.warning(gap)
    return dict(status='needs_textures', textures=list(gap['missing']), warning=warning,
                next=(TEXTURES_NEXT_MCP if mcp else TEXTURES_NEXT).format(warning=warning))


# A Stop: rigswap was ended and nothing saved. The turn usually ends with it; if the model does read it, one line.
CANCELLED_NEXT = ('The user stopped this import, so nothing was saved. Say so in one short sentence; do not start '
                  'it again unless they ask.')
PLAY_ELSE = (' If they did not ask for it, you may end by offering it in a few words ("Want to see him in a '
             'match?"); the in-game test runs only if they ask for it.')


def _picked(result, fighter):
    """rigswap's pick when no fighter was named (result.json's fighter_pick {fighter, why, picked}), the fighter as
    the app names it: {fighter, why, picked} (picked false: it could not tell, and its first fighter stood), else
    None."""
    pick = result.get('fighter_pick')
    if not isinstance(pick, dict) or not fighter:
        return None
    return dict(fighter=fighter, why=str(pick.get('why') or '').strip()[:400] or None, picked=bool(pick.get('picked')))


def _stopped(project_id, fighter, log):
    """The reply for an import the user stopped: nothing saved."""
    log('stopped by the user: nothing saved')
    return dict(status='cancelled', project=project_id, fighter=fighter, saved=None, next=CANCELLED_NEXT)


def _changed(result):
    """What a change changed, for the chat model: result.json's ``changed`` ({entry: [was, is]}) as 'head: 1.0 ->
    0.8; left leg ankle: foot.L -> shin.L', else None (a first import)."""
    changed = result.get('changed')
    if not isinstance(changed, dict) or not changed:
        return None
    return '; '.join(f'{entry}: {pair[0]} -> {pair[1]}' if isinstance(pair, (list, tuple)) and len(pair) == 2
                     else str(entry) for entry, pair in changed.items())[:400]


def _outcome(project_id, folder, result, *, fighter, name, log, cancelled=None, receipts='finish'):
    """The reply for rigswap's result: failed (nothing saved), or done (saved, or the save refused and said).
    ``fighter``: the one named (the app's name), else None and the one rigswap picked. ``cancelled``: checked
    once more right before the vault save, so a Stop never ends in a saved costume. ``receipts``: where the save's
    receipt goes (``_save``). A change's result (``changed``) is said as one (``CHANGED_NEXT``)."""
    fighter = fighter or app_fighter(result.get('fighter'))
    common = dict(project=project_id, fighter=fighter, seconds=round(float(result.get('seconds') or 0.), 1),
                  cost_usd=round(float(result.get('cost_usd') or 0.), 6))
    picked = _picked(result, fighter)
    if picked:
        common['fighter_pick'] = picked
    if result.get('status') != 'done':
        failed = failed_reply(result.get('failed') or {}, fighter)
        # `error` as on every other failed reply: the tool stage, the receipt and the task outcome
        # all read a failure from it.
        reply = dict(status='failed', **common, error=failed['cause'], failed=failed, next=failure_next(failed))
        # rigswap's cause as it wrote it (its exception type too), or why it wrote none: card-only
        # (compaction.UI_ONLY), kept for "Report this chat"
        diagnostic = (result.get('failed') or {}).get('cause') or result.get('error')
        if diagnostic:
            reply['diagnostic'] = str(diagnostic)[:800]
        return reply
    if cancelled is not None and cancelled():
        return _stopped(project_id, fighter, log)
    log('saving the costume to the vault')
    try:
        receipt = _save(folder, result.get('dat'), fighter, name, receipts)
    except ValueError as exc:       # finish.FinishError: a fighter that cannot be finished, no costume file
        log(f'not saved: {exc}')
        extra = dict(saved=None, not_saved=str(exc)[:400])
    else:
        log(f"saved as {(receipt.get('vault') or {}).get('name')!r}")
        # vault_changed: the app's vault list refetches (AssistantPanel), as after every other vault save.
        extra = dict(saved=_saved(receipt), vault_changed=True)
        if receipt.get('csp'):
            extra['pictures'] = [str(receipt['csp'])]       # its portrait: the card's picture, and the model's
    reply = dict(status='done', **common, costume_name=name, **extra)
    if result.get('dat'):
        # the costume file: studio_import registers it as a chat file, and the workbench loads a reply's DAT in its
        # 3D viewer on the reply's fighter
        reply['dat'] = str(result['dat'])
    said = ''
    if picked and picked['picked']:
        said = PICKED_NEXT.format(fighter=fighter, why=(picked['why'] or 'the import did not say').rstrip('. '))
    elif picked:
        said = UNPICKED_NEXT.format(fighter=fighter)
    warned = ''
    if result.get('warning'):
        # rigswap's look at its own finished costume called it a wreck: said to the user
        reply['warning'] = ' '.join(str(result['warning']).split())[:300]
        warned = WARNED_NEXT.format(warning=reply['warning'])
    changed = _changed(result)
    if changed:
        reply.update(changed=changed, why=str(result.get('why') or '').strip()[:400] or None)
        why = f", because: {reply['why'].rstrip('. ')}" if reply['why'] else ''
        reply['next'] = CHANGED_NEXT.format(changed=changed, why=why, project=project_id, warned=warned)
    else:
        reply['next'] = DONE_NEXT.format(fighter=fighter or 'the fighter', picked=said, project=project_id,
                                         warned=warned)
    saved = extra.get('saved') or {}
    if saved.get('character') and saved.get('skin_id'):
        reply['next'] = (PLAY_FIRST.format(character=saved['character'], skin_id=saved['skin_id'])
                         + reply['next'].removesuffix(' The in-game test runs only if they ask for it.')
                         + PLAY_ELSE)
    return reply


def run(args, *, key=None, progress=None, cancelled=None, relay=None):
    """One import_model call. -> the reply (the caller tags it and attaches its pictures). ``relay``: the folder
    rigswap's asks are answered through instead of ``key`` (an import over the app's MCP server)."""
    from . import studio_import
    args = check(dict(args))
    if args.get('project'):
        return change(args['project'], args['change'], said=args.get('said'), name=args.get('name'), key=key,
                      progress=progress, root=studio_import.root(), cancelled=cancelled, relay=relay)
    return start(args['source'], fighter=args.get('fighter'), name=args.get('name'), key=key, progress=progress,
                 root=studio_import.root(), cancelled=cancelled, relay=relay, untextured=bool(args.get('untextured')))


def can_change(home):
    """Whether the rigswap at ``home`` can change a finished import (it has ``CHANGES``, source or compiled)."""
    return any((Path(home) / CHANGES).with_suffix(end).is_file() for end in ('.py', '.pyc'))


def change(project, words, *, said=None, name=None, key=None, progress=None, root, cancelled=None, relay=None):
    """One change to the finished import ``root/<project>``: what the user says looks wrong is put right by rigswap
    (``FIX``) and the costume built again, saved as a second costume named ``name`` (default: the import's name and
    the count, 'Neos 2'). ``said``: the user's own message, which is what rigswap's look is given as the complaint;
    ``words``, the chat model's wording of it, then goes beside it as what was understood (``HEARD``). With no
    ``said`` (a call made outside a chat) ``words`` is the complaint. The fighter is the import's own. An import with
    no finished costume, or one made by a rigswap that kept no record, is a failed reply that says to import it
    again."""
    own = ' '.join(str(said or '').split())[:WORDS]
    heard = words if own and own.lower() != str(words).lower() else None
    words = own or words
    need = tools_needed()
    if need:
        logging.getLogger(__name__).info('import_model: the change waits on the tools (%s)', need.get('state'))
        return dict(tools_reply(need, mcp=relay is not None), project=project)
    found = setup()
    if isinstance(found, str):
        logging.getLogger(__name__).warning('import_model: rigswap is not set up (%s)', found)
        return unexpected(found, cause=NOT_SET_UP, can_do=CAN_DO_ELSE, kind='located')
    python, home = found
    if not can_change(home):
        return unexpected(f'{HOME_ENV} holds no {CHANGES}: {home}', cause=NO_CHANGES, can_do=CAN_DO_AGAIN,
                          kind='located')
    files = None if _setting(FILES_ENV) else vanilla_files()
    if isinstance(files, str):
        logging.getLogger(__name__).warning('import_model: no vanilla files (%s)', files)
        return unexpected(files, cause=files, can_do=CAN_DO_DISC, kind='located')
    folder = Path(root) / project
    try:
        job, last = _read(folder / 'workflow' / JOB), _read(folder / OUT / DONE)
    except (OSError, ValueError):
        job = last = None
    if not isinstance(job, dict) or not isinstance(last, dict) or last.get('status') != 'done' \
            or not last.get('record'):
        return dict(unexpected(f'{project}: no {DONE} with a record', cause=NOT_CHANGEABLE, can_do=CAN_DO_AGAIN,
                               kind='located'), project=project)
    fighter = job.get('fighter') or app_fighter(last.get('fighter'))
    made = [c for c in job.get('changes') or [] if isinstance(c, dict)]
    n = 2 + sum(1 for c in made if c.get('saved'))
    name = (name or '').strip() or f"{job.get('name') or 'Imported model'} {n}"[:60]
    cache = Path(_setting(CACHE_ENV) or Path(root) / CACHE)
    started = time.monotonic()
    log = _Progress(progress, folder, project, started, shown=dict(fighter=fighter) if fighter else None)
    try:
        log(f"change {job.get('source') or project} on {fighter or 'its fighter'}: {words}")
        result = rigswap(python, home, None, None, folder / OUT, cache=cache, key=key, files=files, log=log,
                         cancelled=cancelled, change=words, heard=heard, relay=relay)
        if cancelled is not None and cancelled():
            return _stopped(project, fighter, log)
        log(f"rigswap {result.get('status')} in {float(result.get('seconds') or 0.):.1f}s")
        reply = _outcome(project, folder, result, fighter=fighter, name=name, log=log, cancelled=cancelled,
                         receipts=f'finish-{n}')
        if reply.get('status') == 'failed' and isinstance(reply.get('next'), str):
            reply['next'] = reply['next'].replace('Nothing was saved.', NOT_CHANGED, 1)
        try:
            _write(folder / 'workflow' / JOB, dict(job, changes=made + [dict(
                words=words, **({'heard': heard} if heard else {}), name=name, status=reply.get('status'),
                saved=bool(reply.get('saved')),
                changed=reply.get('changed'))]))
        except OSError:
            logging.getLogger(__name__).warning('import_model: the change was not noted in %s', JOB, exc_info=True)
        return reply
    finally:
        log.close()             # the last running card before the reply, none after it


def start(source_path, *, fighter=None, name=None, key=None, progress=None, root, cancelled=None, relay=None,
          untextured=False):
    """A new import of ``source_path`` (a local file, the download) into ``root/<new id>``: onto ``fighter``, else
    onto the one rigswap picks (``AUTO``). A model without the texture files it names is not imported but said
    (``textures_reply``), unless ``untextured``: the user said to go on without them."""
    fighter, target = fighter_of(fighter) if fighter else (None, AUTO)
    need = tools_needed()
    if need:
        logging.getLogger(__name__).info('import_model: waits on the tools (%s)', need.get('state'))
        return tools_reply(need, mcp=relay is not None)
    found = setup()
    if isinstance(found, str):
        logging.getLogger(__name__).warning('import_model: rigswap is not set up (%s)', found)
        return unexpected(found, cause=NOT_SET_UP, can_do=CAN_DO_ELSE, kind='located')
    python, home = found
    files = None if _setting(FILES_ENV) else vanilla_files()
    if isinstance(files, str):
        logging.getLogger(__name__).warning('import_model: no vanilla files (%s)', files)
        return unexpected(files, cause=files, can_do=CAN_DO_DISC, kind='located')
    source_path = Path(source_path)
    gap = None if untextured else textures.missing(source_path)
    if gap:
        logging.getLogger(__name__).info('import_model: %s came without %s', source_path.name, gap['missing'])
        return textures_reply(gap, mcp=relay is not None)
    project_id = new_id(source_path.name)
    folder = Path(root) / project_id
    (folder / 'workflow').mkdir(parents=True, exist_ok=True)
    name = (name or '').strip() or costume_name(source_path.name)
    cache = Path(_setting(CACHE_ENV) or Path(root) / CACHE)
    _write(folder / 'workflow' / JOB, dict(name=name, source=source_path.name, download=str(source_path),
                                           fighter=fighter, rigswap=target, engine=MODULE))
    started = time.monotonic()
    log = _Progress(progress, folder, project_id, started, shown=dict(fighter=fighter) if fighter else None)
    try:
        log(f"import {source_path.name} onto {fighter or 'the fighter it fits best'}")
        result = rigswap(python, home, source_path, target, folder / OUT, cache=cache, key=key, files=files, log=log,
                         cancelled=cancelled, relay=relay)
        if cancelled is not None and cancelled():
            return _stopped(project_id, fighter, log)
        log(f"rigswap {result.get('status')} in {float(result.get('seconds') or 0.):.1f}s")
        return _outcome(project_id, folder, result, fighter=fighter, name=name, log=log, cancelled=cancelled)
    finally:
        log.close()             # the last running card before the reply, none after it
