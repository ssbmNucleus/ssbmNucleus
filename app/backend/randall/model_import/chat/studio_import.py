"""Randall's model import in chat: one ``import_model`` job (``model_import/chat/import_job.py``).

* **An import turn.** A new model file, or "import this": Randall is offered ONE
  tool, ``import_model`` (``model_import/chat/import_job.py``), which runs
  rigswap on the model as a long job straight through (it asks the user
  nothing) and saves the costume to the vault; its task card is ``IMPORT_CARD``.
* **Every other turn** is a normal Randall turn: the app's own roster and
  recipes. A turn about a model imported earlier is one of those; in a chat with
  a finished import it is offered ``import_model`` too (``changeable``), so "put
  it on Marth instead" imports the same file again onto that fighter (a second
  costume), and "the legs look wrong" is ``import_model`` with the import's
  project and those words: the import changes that one thing and builds it
  again (a second costume too).
* **Routing** (``turn_mode``) is per turn: a chat started as "Import a model"
  (until its import is done) and an attached model not imported yet. Words
  alone never make an import turn. An import turn is offered ``import_model``
  and the few app tools an import uses (``IMPORT_APP_TOOLS``) INSTEAD of the
  app's whole roster.
* **The fighter picked in the panel** (``context.fighter``, the starting
  point's fighter picker: ``chosen_fighter``) goes into a new ``import_model``
  call that names none (``prepare``), and the card tells the model so. A fighter
  neither picked nor named by the user is left out: the import picks the one
  the model fits best and says why.
* **A model without its textures** is known before the turn's first round
  (``without_textures``, the import's own check): the card says so, so Randall
  never announces an import that will only ask for them, and words written
  before such a call are dropped (``asks_for_textures``).
* **Tools not downloaded** (a packaged app whose model import tools are
  missing or out of date: ``import_job.tools_needed``) are known up front the
  same way (``tools_missing``): the card says so, the call comes back
  ``needs_tools`` with a Download button on its card, and words written before
  it are dropped (``starts_nothing``).
* **Import id -> folder.** The job names its project (``import_job.new_id``);
  the folder is ``<root>/<id>`` where root is ``NUCLEUS_STUDIO_ROOT`` or
  ``<storage>/model_imports``.
* **Pictures.** Every png the reply names (the saved costume's portrait) is
  registered as a chat file, so the chat shows it and the vision layer
  (``assistant/vision.py``) attaches it to the next model request as an image;
  the costume file is a chat file too (``_attach_costume``).
* **Ledger.** Each turn that touched an import adds one ``randall.jsonl`` row
  to its folder: model, rounds, time, cost, tokens and tool calls
  (``record_turn``).
"""
import copy
import json
import logging
import os
import re
import shutil
import time
from collections import Counter
from pathlib import Path

ROOT_ENV = 'NUCLEUS_STUDIO_ROOT'
PREFIX = 'studio:'
IMPORT_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}')
# Narration some models attach out of habit; it changes nothing a tool does.
NARRATION = ('assessment', 'rationale')

# An import turn's backstop, not its working allowance: the turn is one import_model call, maybe the in-game
# test and a docs search, so a turn that reaches these is a model going round in circles.
MAX_ROUNDS = int(os.environ.get('NUCLEUS_STUDIO_MAX_ROUNDS', '150'))
MAX_COST = float(os.environ.get('NUCLEUS_STUDIO_MAX_COST', '3.00'))
WRAP_UP_ROUNDS = max(1, MAX_ROUNDS - 15)
WRAP_UP_COST = MAX_COST * 0.85
WRAP_UP_NOTE = ('Model-import budget for this turn reached. Stop working: call no more tools. Reply with one plain '
                'summary of where the import stands.')

_log = logging.getLogger(__name__)


def root():
    """Where imports live: one folder per import id."""
    configured = os.environ.get(ROOT_ENV, '').strip()
    if configured:
        path = Path(configured)
    else:
        from core import config
        path = Path(config.STORAGE_PATH) / 'model_imports'
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


# ------------------------------------------------------------------ the roster

# The app tools an import turn is offered beside import_model; every other app
# tool is left off. None of them is part of an import, and a model that wanders
# there leaves the job (an `inspect_mod_file` on the source ZIP is how one run
# came to redo a stage). Installing a finished costume is a turn of its own with
# the app's whole roster ("put it in my game" routes to delivery).
IMPORT_APP_TOOLS = (
    # The app's own help: a user may ask how the app works in the middle of an
    # import, and the answer to an import's question is an import turn too.
    'search_docs',
    # The play session, for a request that asks to see or test the costume in game
    # ("...save him to my vault and test him in game"): started once the import has
    # saved it, in the same turn (the card and the reply's `next` say when). It
    # builds its own test copy from clean Melee, so it needs no game copy of the
    # user's. Without it here, the import turn could only promise the test for later.
    'test_in_game',
)


def import_schemas():
    """An import turn's one tool."""
    from . import import_job
    return [copy.deepcopy(import_job.SCHEMA)]


def names():
    """The tool names an import turn's calls go to this module with (``import_model``)."""
    return {s['function']['name'] for s in import_schemas()}


def offer(roster):
    """An import turn's roster: ``import_model``, then the few app tools an import uses
    (``IMPORT_APP_TOOLS``) that this turn's roster holds."""
    own = names()
    return import_schemas() + [s for s in roster if s['function']['name'] in IMPORT_APP_TOOLS
                               and s['function']['name'] not in own]


IMPORT_CARD = """TASK RECIPE -- IMPORT A MODEL
Call import_model once for the model: source = its file ID (recent_attached_files), name = the costume name if they
gave one. Leave fighter unset unless the user named one or picked it in the chooser: the import fits him to the
fighter that suits him best, and a fighter of your own choosing skips that ("whichever fighter he fits" names none).
It is one long job (a few minutes): it decides everything itself, asks the user nothing, and saves the costume to
the vault. Do not call it again for the same model, and do not poll.
Before it runs, say in one short sentence what you are starting ("Starting now: I'll fit him to the fighter that
suits him best and save him to your vault."), unless this card says below that the model came without files it needs
or that the import's tools are not downloaded: then nothing starts, so write nothing before the call. When it returns, reply in one or two short sentences in your
own voice:
- done: the card above your reply shows the saved name, the fighter and the portrait, so never repeat them. Say that
  he (or it) is on the fighter and in their vault; when the import picked the fighter (`fighter_pick`), which one and
  why in a few plain words ("I put him on Ganondorf: ..."); or why it was not saved. The picture is its portrait, for
  you only: never mention it, the import's steps, file names or anything else the user cannot see. No technical
  details, no caveats or guesses of your own. When the reply has `warning` (the import's own check of the finished
  costume), pass it on word for word as its `next` says, never softened, and do not call the costume done or fine.
- failed: the cause the reply gives in plain words, and what the user can do; never a cause of your own (not from
  the model's name or file name either).
- needs_textures: nothing ran. The model names files that did not come with it; `warning` says which, and what each
  one is (an OBJ's .mtl is its materials file, not a texture; images are its textures). Say so plainly, naming each
  file as `warning` does, and ask for a ZIP holding the model with those files, or whether to import it without
  textures. When they say to go on without them, import_model with the same source and untextured true; a ZIP they
  attach is imported instead. Never set untextured on your own.
- needs_tools: nothing ran. Model import needs its tools (Blender and the importer's Python), a one-time download
  the user starts: the card above your reply has a Download button (also in Settings > AI). Say so in one
  or two plain sentences, as its `next` says, and that they can ask you again once the download has finished. Do
  not call import_model again in the same turn.
Another fighter afterwards ("put him on Marth instead"): import_model again with the same source and that fighter.
It saves a second costume; the first stays.
Something looks wrong afterwards ("the legs look wrong", "his head is too big", "he faces backwards", "take the
jetpack off", "his hat is missing", "her hair should move"): import_model
with project = the import's project (from its reply) and change = what the user said, in their words, one thing per
call. It builds him again with that one thing changed and saves a second costume; the first stays. Say what you
changed and ask them to have a look: never say it is fixed, you have not seen it. It can change how the body is read
(which way he faces, where his joints are), a few sizes (head, limbs, trunk, all of him), which of the model's own
pieces the costume wears (leave one out, bring back one it left out) and whether a part hanging off the body (hair,
cloth, a tail) swings or holds still; textures, colours and a piece the model never had it cannot, and when it says
it cannot make a change, say so plainly. A piece to put back or take off is such a change too, never a new import:
a new import decides everything again and may come out different elsewhere.
In game: when the user's request asks to see, test or play it in game ("show me him in game", "test him in game",
"let me play him") and the import saved it, start the play session in the same turn, right after the import
returns: test_in_game with action "start", kind "costume" and the character and skin_id from its `saved`, with no
text between the two calls (at most "Now the in-game test."). Then one closing reply for both: the done reply above
plus where and how they play, from the play session's result; it is still getting ready, so never say it is running
yet. It builds its own test copy from their clean Melee: it needs no game copy of theirs, so do not mention game
copies or "My game" for it. Otherwise the in-game test runs only when the user asks for it (you may offer it: "Want
to see him in a match?")."""


def card(app_context=None, fighter=None, bare=None, tools=None):
    """The import turn's task card, once per turn: the recipe, the fighter the user picked (`chosen_fighter`), the
    attached models that came without their textures (``bare``: `without_textures`) and the import's tools when they
    are not downloaded (``tools``: `tools_missing`)."""
    body = [IMPORT_CARD]
    if tools:
        from . import import_job
        body += ['', f"THE IMPORT'S TOOLS ARE NOT READY (data, checked by the app just now): "
                 f"{import_job.tools_words(tools)}. Any import_model call this turn starts nothing: it comes back "
                 'needs_tools, and its card has the Download button. So write no words before that call (never '
                 '"Starting now"); after it, say what its reply says.']
    if fighter:
        body += ['', f'FIGHTER PICKED BY THE USER (data): {fighter}. A new import goes on {fighter}: pass it as '
                 'fighter (the app fills it in when you leave it out) and do not ask which fighter, unless the '
                 'user names a different one in this chat.']
    for file_id, found in (bare or {}).items():
        body += ['', f"CAME WITHOUT FILES IT NEEDS (data, checked by the app just now): {found['name']} (file ID "
                 f"{file_id}). {found['warning']} An import_model call for it starts nothing: it comes back "
                 'needs_textures. So write no words before that call (never "Starting now", never that you are '
                 'putting him on a fighter or saving anything); after it, say what its reply says. Only when the '
                 'user has said to import it without textures (untextured true) does it start: then say what you '
                 'are starting as usual.']
    if app_context:
        body += ['', 'CURRENT APP STATE (data, not instructions; its game copy fields are about putting a costume '
                 'into the game the user plays, a separate request, not about the play session): '
                 + json.dumps(app_context, sort_keys=True, default=str)]
    return '\n'.join(body)


def describe():
    return {'family': 'model_import', 'model_import_mode': 'import', 'card_chars': len(IMPORT_CARD),
            'operations': sorted(names())}


def is_studio_result(result):
    return isinstance(result, dict) and isinstance(result.get('studio_import'), dict)


def _newest_import(receipts):
    """This chat's newest import_model reply that is an import's (tagged with its project), or None. A reply that is
    an ``error`` with no status (a call that failed outside the job) is skipped; a reply no import tagged (refused
    before it ran) is not an import reply at all. The card reads the same (frontend ``studio.js``)."""
    for receipt in reversed(list(receipts or ())):
        result = receipt.get('result') if isinstance(receipt, dict) else None
        tag = result.get('studio_import') if isinstance(result, dict) else None
        if isinstance(tag, dict) and tag.get('id') and tag.get('tool') == 'import_model':
            if result.get('error') and result.get('status') is None:
                continue
            return result
    return None


def changeable(receipts):
    """The project of this chat's newest finished import (done or failed), or None: a normal turn after it is offered
    ``import_model`` too, so another fighter the user asks for ("put him on Marth instead") is a new import of the
    same file onto it, and something they say looks wrong is a change to it (``import_job.change``)."""
    result = _newest_import(receipts)
    if result is not None and result.get('status') in ('done', 'failed'):
        return result['studio_import']['id']
    return None


def turn_mode(recipe_family, receipts, *, waiting=False):
    """'import' when this turn is a model import, else None (Randall's normal turn, the app's own roster).

    An import turn: a model file attached and not imported yet (``waiting``,
    attached_model.attached_model_waiting) or a chat started as a model import
    (the ``model_import`` family: recipes.turn_family). Any other turn, one about
    a model imported earlier included, is a normal turn (offered import_model for
    another fighter: ``changeable``). An import from before rigswap that stopped
    on a question is not carried on (``receipts`` is kept for the caller's
    signature)."""
    if waiting or recipe_family == 'model_import':
        return 'import'
    return None


# ------------------------------------------------------------------ the picked fighter

# Other names for a fighter, beside the roster's own (``fighter_choice``).
ALIASES = {'captain falcon': 'C. Falcon', 'falcon': 'C. Falcon', 'c falcon': 'C. Falcon',
           'donkey kong': 'DK', 'game and watch': 'Mr. Game & Watch', 'game & watch': 'Mr. Game & Watch',
           'mr game and watch': 'Mr. Game & Watch', 'gnw': 'Mr. Game & Watch', 'g&w': 'Mr. Game & Watch',
           'doctor mario': 'Dr. Mario', 'dr mario': 'Dr. Mario', 'ics': 'Ice Climbers', 'ic': 'Ice Climbers',
           'popo': 'Ice Climbers', 'nana': 'Ice Climbers', 'young link': 'Young Link', 'yl': 'Young Link',
           'puff': 'Jigglypuff', 'ganon': 'Ganondorf', 'mew two': 'Mewtwo'}


def fighter_choice(value):
    """The fighter `value` names, as the importer names it ('falcon' -> 'C. Falcon'), else None.

    For a picker's value (``context.fighter``): a string naming a base-roster fighter, case and punctuation
    free, or one of ``ALIASES``. Anything else is None, never an error. A fighter the import cannot target
    (Ice Climbers) is still returned: the import refuses it with its reason."""
    if not isinstance(value, str) or not value.strip() or len(value) > 40:
        return None
    from shared.modellab.fighter_catalog import _CHAR_TO_CODE
    known = {name.lower(): name for name in _CHAR_TO_CODE}
    key = ' '.join(value.replace('.', ' ').replace('_', ' ').split()).lower()
    for candidate in (value.strip().lower(), key):
        if candidate in known:
            return known[candidate]
    if key in ALIASES:
        return ALIASES[key]
    squashed = {name.replace('.', '').replace(' ', ''): fighter for name, fighter in known.items()}
    return squashed.get(key.replace(' ', ''))


# Names people use for a fighter beyond the roster's own and ``ALIASES`` (``named_fighter``).
SPOKEN = {'doc': 'Dr. Mario', 'jiggs': 'Jigglypuff', 'pika': 'Pikachu', 'gw': 'Mr. Game & Watch',
          'mr game': 'Mr. Game & Watch', 'ylink': 'Young Link', 'y link': 'Young Link', 'cf': 'C. Falcon'}


def _spoken(value):
    """``value`` lowercased with dots, underscores and dashes as spaces, spaces collapsed: 'Mr. Game & Watch' ->
    'mr game & watch'."""
    return ' '.join(re.sub(r'[._-]', ' ', str(value).lower()).split())


def named_fighter(texts):
    """The first fighter the user's own words name ('put him on Young Link', 'falcon pls'), else None.

    Any roster name, ``ALIASES`` or ``SPOKEN`` form, as a whole word,
    case and punctuation free. It errs towards finding one ("the link to the model" names Link): what it is for is
    the opposite case, a request that names none ("whichever fighter he actually fits"), where a fighter the chat
    model passes anyway is its own guess (``prepare``)."""
    from shared.modellab.fighter_catalog import _CHAR_TO_CODE
    forms = {_spoken(name): name for name in _CHAR_TO_CODE}
    forms.update({_spoken(alias): fighter for alias, fighter in {**ALIASES, **SPOKEN}.items()})
    for text in ([texts] if isinstance(texts, str) else list(texts or ())):
        words = _spoken(text) if isinstance(text, str) else ''
        for form in sorted(forms, key=len, reverse=True):
            if re.search(r'(?<![a-z0-9])' + re.escape(form) + r'(?![a-z0-9])', words):
                return forms[form]
    return None


def chosen_fighter(messages):
    """The fighter the user picked for this chat's import: the newest user message whose context carries a
    ``fighter`` this module knows (``fighter_choice``), else None."""
    for message in reversed(list(messages or ())):
        if isinstance(message, dict) and message.get('role') == 'user':
            context = message.get('context')
            fighter = fighter_choice(context.get('fighter')) if isinstance(context, dict) else None
            if fighter:
                return fighter
    return None


# ------------------------------------------------------------------ a model without its textures, known up front

# The newest attached models a turn checks for their textures as it is set up (``without_textures``); the import reads
# the one it imports once more itself.
TEXTURE_CHECKS = 3


def without_textures(attachments, receipts=()):
    """The attached models not imported yet (``attached_model.models_waiting``) that came without texture files they
    name, checked as the turn is set up, before the model writes a word: {file ID: {name, warning}}.

    The same check the import makes before it runs (``import_job.start``: ``textures.missing`` on the staged upload,
    ``_source_path``), so an import_model call for one of them comes back ``needs_textures`` unless it says
    ``untextured``. 0.9.0 smoke: the card asked for "Starting now: I'll put Sack Boy on Ness and save him to your
    vault" before the call, and the call then said nothing was imported. The card names them (``card``) and the engine
    drops words written before such a call (``asks_for_textures``). A file that cannot be staged or read is left out:
    the import says what it makes of it."""
    from . import textures
    from .attached_model import models_waiting
    found = {}
    for item in models_waiting(attachments, receipts)[-TEXTURE_CHECKS:]:
        try:
            gap = textures.missing(_source_path(item['file_id']))
        except (OSError, ValueError):       # not a chat file here (any more), or it could not be staged
            continue
        except Exception:                   # a check before the turn never costs the turn
            _log.warning('texture check before the turn failed for %s', item.get('name'), exc_info=True)
            continue
        if gap:
            found[str(item['file_id'])] = dict(name=str(item.get('name') or gap['source']),
                                               warning=textures.warning(gap))
    return found


def tools_missing():
    """What the import's tools lack before the turn's first round (``import_job.tools_needed``), else None: an
    import_model call this turn comes back ``needs_tools``."""
    from . import import_job
    return import_job.tools_needed()


def starts_nothing(function, bare, tools=None):
    """Whether a model's tool call will start nothing and only say why: an import_model that comes back
    ``needs_textures`` (``asks_for_textures``), or any import_model while the tools are not ready (``tools``). The
    engine drops the words written before it."""
    from . import import_job
    if tools and isinstance(function, dict) and function.get('name') == import_job.NAME:
        return True
    return asks_for_textures(function, bare)


def asks_for_textures(function, bare):
    """Whether a model's tool call (``function``: its name and arguments) is an import_model that will come back
    ``needs_textures``: a new import of a source in ``bare`` (``without_textures``) that does not say ``untextured``.
    The words the model wrote before it are dropped (``engine``), so a turn that starts nothing never says it is
    starting."""
    from . import import_job
    if not bare or not isinstance(function, dict) or function.get('name') != import_job.NAME:
        return False
    args = function.get('arguments')
    try:
        args = json.loads(args) if isinstance(args, str) else args
    except ValueError:
        return False
    if not isinstance(args, dict) or args.get('project') or args.get('change'):
        return False
    if str(args.get('untextured', '')).strip().lower() in ('true', '1', 'yes'):
        return False
    return str(args.get('source')) in bare


# ------------------------------------------------------------------ calls

def prepare(name, arguments, *, fighter=None, words=None):
    """Validate one import_model call. -> tools.PreparedCall (automatic policy).

    ``fighter``: the fighter the user picked (``chosen_fighter``). A call that names no fighter goes on it. A change
    to a finished import (``project`` and ``change``) takes no fighter: it stays on its own.

    ``words``: the user's messages in this chat (None: not known, and a fighter the call names stays). A call keeps a
    fighter it names only when those words name one (``named_fighter``); otherwise it is the chat model's own guess
    and gives way to the picked fighter, or, with none picked, is dropped so the import picks the one the model fits
    best (rigswap's ``auto``). 2026-10-06: "put him in melee on whichever fighter he actually fits" was sent as
    fighter "Mr. Game & Watch", which skipped the fit and drew him as a black silhouette."""
    from randall.assistant.approvals import PreparedCall
    from . import import_job
    by_name = {s['function']['name']: s['function']['parameters'] for s in import_schemas()}
    if name not in by_name:
        raise ValueError(f'{name} is not a model-import tool. Tools: {", ".join(sorted(by_name))}.')
    args = json.loads(arguments) if isinstance(arguments, str) else arguments
    if not isinstance(args, dict):
        raise ValueError('Tool arguments must be an object.')
    schema = by_name[name]
    args = {k: v for k, v in args.items() if k in schema['properties'] or k not in NARRATION}
    unknown = sorted(set(args) - set(schema['properties']))
    missing = sorted(set(schema['required']) - set(args))
    if unknown or missing:
        detail = [f'{k!r} is not a parameter of {name}.' for k in unknown]
        if missing:
            detail.append('Required and missing: ' + ', '.join(repr(k) for k in missing) + '.')
        detail.append('Accepted parameters: ' + ', '.join(sorted(schema['properties'])) + '.')
        raise ValueError('Invalid tool arguments. ' + ' '.join(detail))
    args = {k: v for k, v in args.items() if v is not None and v != ''}
    if args.get('project') or args.get('change'):
        # A change to a finished import: its fighter is the import's own, so none is filled in or passed on. The
        # user's own newest message goes with it (``said``): that, not the chat model's wording of it, is the
        # complaint the import's look reads (import_job.change).
        args = import_job.check(args)
        said = next((' '.join(text.split()) for text in reversed(list(words or ())) if isinstance(text, str)
                     and text.strip()), None)
        if said:
            args['said'] = said[:import_job.WORDS]
        if not _folder(args['project']).is_dir():
            raise ValueError(f"There is no import {args['project']!r} here. project is the one an import_model "
                             'reply in this chat gave; for a model not imported yet, pass source instead.')
        return PreparedCall(PREFIX + name, json.dumps(args, sort_keys=True), 'null', 'null', 'automatic')
    if args.get('fighter') and words is not None and not named_fighter(words):
        _log.info('import_model: fighter %r was not named by the user; %s', args['fighter'],
                  f'using the picked {fighter!r}' if fighter else 'the import picks one')
        del args['fighter']
    if fighter and not args.get('fighter'):
        args['fighter'] = fighter
    args = import_job.check(args)
    return PreparedCall(PREFIX + name, json.dumps(args, sort_keys=True), 'null', 'null', 'automatic')


def _import_id(value):
    if not isinstance(value, str) or not IMPORT_ID.fullmatch(value):
        raise ValueError('project must be a short import id: letters, digits, - and _ (up to 64), '
                         'starting with a letter or digit.')
    return value


def _folder(import_id):
    folder = (root() / _import_id(import_id)).resolve()
    if folder.parent != root():
        raise ValueError('Invalid import id.')
    return folder


def _source_path(value):
    """The attached upload as a file with its real name (the studio reads the
    format from the extension). Only attachments: never a path the model names."""
    from shared import mod_files
    if isinstance(value, str) and re.fullmatch(r'[a-f0-9]{32}', value):
        path, info = mod_files.resolve(value)
        staged = root() / '.uploads' / info['file_id']
        staged.mkdir(parents=True, exist_ok=True)
        target = staged / info['name']
        if not target.is_file() or target.stat().st_size != path.stat().st_size:
            shutil.copy2(path, target)
        return target
    raise ValueError('source must be the file ID of the attached model (see recent_attached_files).')


def execute(call, key=None, progress=None, cancelled=None):
    """Run one prepared import_model call. -> JSON reply, tagged and with its pictures as chat files.

    ``key``: the turn's own OpenRouter key; rigswap's asks send with it (never written anywhere). ``progress``:
    import_model's running card (a callable taking the partial reply). ``cancelled``: true once the user pressed
    Stop (the import ends rigswap and saves nothing).
    """
    from . import import_job
    name = call.name[len(PREFIX):]
    if name != import_job.NAME:         # prepare() only lets import_model through
        return {'error': f'{name} is not a model-import tool. Tools: {import_job.NAME}.'}
    return _execute_import(json.loads(call.arguments), key, progress, cancelled)


def _execute_import(args, key, progress, cancelled=None):
    """import_model: the job's reply, tagged with its project and with its pictures and costume file as chat
    files."""
    return run_import(args, key=key, progress=progress, cancelled=cancelled, source_is_attachment=True)


def run_import(args, *, key=None, progress=None, cancelled=None, source_is_attachment=False, relay=None):
    """One import or change (``import_job.run``) -> its reply, tagged with its project and with its pictures and
    costume file as chat files. ``source`` is the attached model's file ID in a chat (``source_is_attachment``),
    and a local file path for the app's MCP server (randall/mcp/model_jobs.py), whose caller is the user's own AI
    on their own computer. ``relay``: the folder rigswap's asks are answered through (``import_job.run``)."""
    from . import import_job
    try:
        if args.get('source') and source_is_attachment:
            args['source'] = str(_source_path(args['source']))
        reply = import_job.run(args, key=key, progress=progress, cancelled=cancelled, relay=relay)
    except ValueError as exc:       # a refusal the job worded (the call's own mistake: the chat model mends it)
        reply = {'error': str(exc) or type(exc).__name__}
    except Exception as exc:   # a job failing is an answer, not a dead turn
        _log.exception('import_model failed')
        # A fault outside rigswap's stages: said as one, with the same rule as its failures (import_job.failure_next):
        # never a cause the model makes up, and in plain words; the exception itself is in the log and in
        # ``diagnostic`` (card-only, kept for "Report this chat").
        reply = import_job.unexpected(f'{type(exc).__name__}: {str(exc)[:800]}')
        reply.pop('status')
    reply = json.loads(json.dumps(reply, default=str))
    import_id = reply.get('project')
    try:
        folder = _folder(import_id) if import_id else None
    except ValueError:
        folder = None
    reply['studio_import'] = {'tool': import_job.NAME, 'id': import_id if folder is not None and folder.is_dir()
                              else None}
    if reply['studio_import']['id']:
        _attach_pictures(reply, folder)
        _attach_costume(reply, folder)
    return reply


_registered = {}     # (path, mtime_ns, size) -> chat file description


def _png_in(value, folder):
    """``value`` as a png file under the import's folder or the imports root, resolved; else None."""
    if not isinstance(value, str) or not value.lower().endswith('.png'):
        return None
    path = Path(value).resolve()
    if not (path.is_relative_to(folder) or path.is_relative_to(root())) or not path.is_file():
        return None
    return path


def _register(path, folder):
    """A png ``_png_in`` found, as a chat file, once per file and change (``_registered``). -> the chat file
    description. Raises OSError/ValueError when it cannot be registered."""
    from shared import mod_files
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    info = _registered.get(key)
    if info is None:
        label = str(path.relative_to(folder) if path.is_relative_to(folder) else path.name)
        label = re.sub(r'[\\/]+', '_', label)
        if len(label) > 150:
            label = label[-150:]
        info = mod_files.register(path.read_bytes(), label, origin='model_import_v2')
        _registered[key] = info
    return info


def _attach_pictures(reply, folder):
    """Register the reply's own pictures (the saved costume's portrait) as chat files, shown to the model."""
    pictures = reply.get('pictures')
    if not isinstance(pictures, list):
        return
    files = []
    for value in pictures:
        try:
            path = _png_in(value, folder)
            if path is not None:
                files.append(dict(_register(path, folder), path=str(path)))
        except (OSError, ValueError) as exc:
            _log.warning('import picture not attached: %s (%s)', value, exc)
    if files:
        reply['files'] = files


def _attach_costume(reply, folder):
    """The costume file the import wrote (the reply's ``dat``), registered as a chat file after the pictures.

    The workbench loads a DAT a reply carries in its 3D viewer, on the reply's fighter, so the finished costume
    shows in 3D on its own. Information only: a file that is missing, outside the import's folder or cannot be
    registered is logged and left out, never an error.
    """
    from shared import mod_files
    value = reply.get('dat')
    if not isinstance(value, str) or not value.lower().endswith('.dat'):
        return
    try:
        path = Path(value).resolve()
        if not path.is_relative_to(folder) or not path.is_file():
            return
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        info = _registered.get(key)
        if info is None:
            info = mod_files.register(path.read_bytes(), path.name, origin='model_import_v2')
            _registered[key] = info
        reply.setdefault('files', []).append(dict(info, path=str(path)))
    except (OSError, ValueError) as exc:
        _log.warning('import costume not attached: %s (%s)', value, exc)


# ------------------------------------------------------------------ ledger

def record_turn(answer, *, chat_id=None, model=None):
    """One randall.jsonl row per import this turn touched: the chat model's
    share of the import (rounds, time, cost, tokens, tool calls)."""
    receipts = [r for r in answer.get('tools') or [] if is_studio_result(r.get('result'))]
    by_import = {}
    for receipt in receipts:
        import_id = receipt['result']['studio_import'].get('id')
        if import_id:
            by_import.setdefault(import_id, []).append(receipt)
    side = [r for r in receipts if not r['result']['studio_import'].get('id')]
    for import_id, rows in by_import.items():
        try:
            folder = _folder(import_id)
        except ValueError:
            continue
        if not folder.is_dir():
            continue
        row = dict(time=time.time(), chat_id=chat_id, answer_id=answer.get('id'), model=model,
                   status=answer.get('status'), stop_reason=answer.get('stop_reason'),
                   rounds=answer.get('model_rounds'),
                   seconds=round(time.time() - (answer.get('started_at') or time.time()), 1),
                   cost_usd=answer.get('cost_usd'), cost_parts=answer.get('cost_parts'),
                   tokens=answer.get('tokens'), tool_calls=len(rows) + len(side),
                   tool_errors=sum(1 for r in rows + side if r.get('status') == 'error'),
                   tools=dict(Counter(r.get('name') for r in rows + side)),
                   shared_with=sorted(set(by_import) - {import_id}))
        try:
            with open(folder / 'randall.jsonl', 'a', encoding='utf-8') as stream:
                stream.write(json.dumps(row, default=str) + '\n')
        except OSError as exc:
            _log.warning('randall.jsonl not written for %s: %s', import_id, exc)
