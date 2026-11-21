# Import a model

The model import turns a 3D model the user attaches (a zip, or a glb/gltf, fbx, dae or obj file; **not smd**) into a
Melee costume for one fighter and saves it in the vault as a **new** costume. In a chat it is one tool call,
`import_model`, that runs the whole import as a long job. **The engine is rigswap** (its own repo and Python, run as a
subprocess: `python -m rigswap.plugins.melee.costume <download> <Fighter|auto> <out> --cache <dir>`), since
2026-10-29. The v4 engine that ran before it was deleted on 2026-11-03; the tag `archive/v4-importer` marks the last
commit with it.

**It runs straight through.** rigswap asks the user nothing; it ends `done` (the costume saved), `failed` (nothing
saved, the reply says where and why) or `cancelled` (the user pressed Stop; nothing saved). With no fighter named,
rigswap picks the one the model fits best (`auto`) and says which and why (`fighter_pick`); the chat tells the user
("I put him on Ganondorf: ..."). **Another fighter afterwards** ("put it on Marth instead") is `import_model` again
with the same source and that fighter: a **second** costume; the first stays. **Something looks wrong afterwards**
("the legs look wrong") is `import_model` with the import's `project` and the user's words as `change`: rigswap
changes one entry of the import's record and builds the costume again, also a second costume (step 7).

## The path, in order

1. **Chat start (the user, then code).** One of these makes a turn an *import turn*
   (`chat/studio_import.turn_mode`, called from `assistant/engine.py`):
   - **The Import a character model tile.** The user picks the tile and, optionally, a fighter
     (`frontend/src/randall/assistant/StartPicker.jsx` over `vault/picker/CostumePicker.jsx`, `picker: 'fighter'`;
     the roster is `/status` `import_fighters`, `routes/assistant_bp.py`). The first message carries
     `context.task = 'model_import'` and `context.fighter`; the blueprint keeps a fighter only when it is one the
     import can target. `recipes.chat_task` makes the chat a declared import until its import is done
     (`assistant/turn_facts._pinned_task`).
   - **An attached model in an ordinary chat.** A model-like file the chat has not imported yet, attached and
     asked about ("import this") (`chat/attached_model.attached_model_waiting`; a zip that holds costume DATs and
     no 3D model is a costume pack, not a model). Words alone never start an import.
   - Out: an import turn. Its roster is `import_model` plus `search_docs` and `test_in_game` (`studio_import.offer`,
     `IMPORT_APP_TOOLS`) instead of the app's whole roster; its card is `studio_import.IMPORT_CARD` plus the picked
     fighter (`studio_import.chosen_fighter`, `studio_import.card`) and each attached model that came without its
     textures (`studio_import.without_textures`, step 2). Budget: 150 rounds and 3.00 USD a turn, with a
     wrap-up note at 135 rounds or 85 % of the cost (`studio_import.MAX_ROUNDS`, `MAX_COST`, `WRAP_UP_*`;
     `NUCLEUS_STUDIO_MAX_ROUNDS`, `NUCLEUS_STUDIO_MAX_COST`).
   - After a finished import (done), the chat's normal turns are offered `import_model` beside the app's roster
     (`studio_import.changeable`, `engine.py`), for the same model on another fighter or a change to it (step 7).

2. **The call (the main model, then code).** The main model calls `import_model(source=<file id>, fighter?, name?)`
   once. `chat/studio_import.prepare` drops a fighter the user never named or picked, fills in the picked one, and
   validates the call (`chat/import_job.check`: a source; a fighter is one rigswap targets, `import_job.fighter_of`,
   matched to rigswap's name by Pl code, `RIGSWAP_FIGHTERS`: 'C. Falcon' is 'CaptainFalcon'; Ice Climbers are
   refused, naming the fighters). `studio_import.execute` copies the upload to `<root>/.uploads/<file id>/<its name>`
   and runs `chat/import_job.run` -> `import_job.start`. First the texture files the model names are looked for
   where rigswap will look (`chat/textures.missing`: beside a bare file, which in a chat is alone in its upload
   folder; anywhere in a ZIP). It reads an OBJ's `mtllib` files and their `map_Kd`, a DAE's `<image><init_from>`
   (not `data:` URIs), an FBX's `Texture`/`Video` `FileName`/`RelativeFilename` less what a `Video` carries inside
   (`Content`), and a glTF's buffer and image `uri`s; a GLB carries everything, and a file it cannot read is never
   flagged. Some missing is the reply `{status: 'needs_textures', textures, warning, next}` (`import_job.textures_reply`,
   `TEXTURES_NEXT`): no project, nothing run, the file still waiting (`attached_model._asked_for_textures` keeps the
   user's answer an import turn). Randall says which files are missing and asks for a ZIP holding them, or whether
   to go on without them: then `import_model(source, untextured=true)` skips the check. (0.9.0 smoke: a bare
   Clank.obj without its .mtl was saved all white without a word.) The turn knows this before its first round:
   `studio_import.without_textures` runs the same check on the waiting attachments' staged uploads as the turn is set
   up, so the card names each model that lacks its textures and has Randall write nothing before that call (the
   recipe's "Starting now" sentence is for an import that starts), and the engine drops words written before a call
   that will only ask (`studio_import.asks_for_textures`, beside `engine._after_import`). 0.9.0 smoke: "Starting now:
   I'll put Sack Boy on Ness and save him to your vault." above "nothing was imported yet". The chat's import card
   shows it waiting (a `!`), never a ✓. Then a new project folder `<root>/<id>`
   (`import_job.new_id`) with `workflow/job.json`. `<root>` is `NUCLEUS_STUDIO_ROOT`, else `<storage>/model_imports`. No approval card: the
   import writes only its own project folder and, at the end, a new vault costume.

3. **rigswap (a subprocess).** `import_job.rigswap` runs `RIGSWAP_PYTHON -m rigswap.plugins.melee.costume <upload>
   <Fighter, or auto> <project>/rigswap --cache <root>/.rigswap-cache` in `RIGSWAP_HOME`. Each setting comes from the
   environment, else `import_job._defaults`. A packaged app runs the installer's rigswap package
   (`resources/utility/rigswap/app`: compiled at a pinned commit by `tools/build/fetch_rigswap.py` from
   `utility/rigswap.manifest.json`, on every platform) on **the model import tools** the user downloads from
   Settings > AI > Model import tools (`tools/`, below: a CPython 3.13 with rigswap's pinned wheels, and
   Blender 4.3.2), with the app's HSDRawViewer, and keeps its targets in `<imports root>/.rigswap-targets`. Tools not
   downloaded, being downloaded, or not the ones this app pins: the import starts nothing and replies
   `{status: 'needs_tools', tools: {state, download_bytes, needed_bytes, disk_bytes}, warning, next}`
   (`import_job.tools_reply`; the chat's import card then shows a Download button, and the turn's card says so before
   the first round: `studio_import.tools_missing`, `starts_nothing`). A RIGSWAP_PYTHON and RIGSWAP_BLENDER4 in the
   environment stand in for them. A source checkout uses the developer's, `import_job.DEV_ENV`. The vanilla fighter files (`RIGSWAP_MELEE_FILES`) are read from the user's own disc
   (`import_job.vanilla_files`; no disc set is a failed reply that says so). The targets are Nintendo-derived and
   never ship: rigswap makes each one from those files the first time an import needs it (`costume.ready`, about ten
   seconds a fighter, once per computer). A missing Python or home is a failed reply before anything runs
   (`import_job.setup`, said as that cause). Each run's TMPDIR, TEMP and TMP name a folder of its own,
   `<scratch>/rigswap-tmp-<8>` (`chat/rigswap_temp.py`), removed when rigswap ends however it ends (done, failed,
   stopped), so a stopped run's Blender session folder and scripts go with it; the backend's start removes what
   earlier runs left in the scratch, by exact shape only. The project folder stays as the import's record.
   `RIGSWAP_CACHE` moves the shared cache. rigswap's environment has the turn's key as `OPENROUTER_API_KEY`
   (`import_job.openrouter_key`; never logged) and no `PYTHONPATH` of the app's. Every line it prints goes to
   `workflow/job.log` and to the running card (`import_job._Progress`: coalesced, the newest six lines and the
   fighter). The user's Stop ends it and what it started (`import_job._stop`, polled every `CANCEL_POLL`: its PID tree on
   Windows; on macOS and Linux rigswap leads a session of its own, sent SIGTERM, then SIGKILL after `STOP_GRACE`), and
   so does
   `import_job.TIMEOUT` (45 minutes). It writes `<project>/rigswap/result.json` (`{status, fighter, dat, seconds,
   cost_usd, asks, failed: {stage, cause}, fighter_pick?}`); with `auto`, `fighter` is its pick and `fighter_pick`
   `{fighter, why, picked}` says why.

4. **Done: the save (code).** `import_job._save` calls `studio/finish.finish` directly on rigswap's costume file and
   the app's name for its fighter (`import_job.app_fighter`), the Slippi fix applied and the vault record's
   `model_import` `{source: 'model_import_rigswap', project}`. `finish/finished.json` keeps the receipt: a retry with
   the same file and name adds no second copy. A save that is refused (no vault here, a fighter that cannot be
   finished) is said (`not_saved`); the import is still `done`. A Stop that lands after rigswap finished still saves
   nothing. The reply: `status, project, fighter, costume_name, seconds, cost_usd` (rigswap's own), `dat, saved,
   vault_changed, next`, and `fighter_pick` when it picked; `next` is `DONE_NEXT` (+ `PICKED_NEXT`, or
   `UNPICKED_NEXT` when its asks gave no answer and rigswap's first fighter stood, + `PLAY_FIRST`/`PLAY_ELSE` once
   saved). Its picture is the costume's portrait (`finish`'s CSP); `studio_import._attach_costume` registers the DAT
   so the workbench shows it in 3D. `studio_import.record_turn` appends the chat model's share (rounds, time, cost,
   tokens) to `<project>/randall.jsonl`.

5. **Failed (code).** Nothing is saved. `import_job.failed_reply` reads result.json's `failed`: where (`load`: while
   loading the model file; `pick`: while picking the fighter, no fighter named; `swap`: while putting the model on
   the fighter), the cause in rigswap's words when it is one of its own (`Failed`, `RuntimeError`, `ValueError`: the
   type is cut off), else "an internal error in the importer"; and what the user can do (`CAN_DO`: load -> attach it
   in another format or as an archive with its textures; pick -> name the fighter; swap -> another fighter, or
   another model of the character; and report it). rigswap's cause as it wrote it (or why it wrote no result) stays
   card-only as `diagnostic`, which "Report this chat" sends.

6. **After the save (other packages, ordinary turns).** "Put it in my game" is `deliver_to_game`
   (`../delivery/deliver.py`, approval-gated); "test it in game" is `test_in_game` on the saved costume or the
   exported file (`../delivery/game_tests.py`). A request that already asked to see or test it in game ("...save
   him to my vault and test him in game") gets the play session in the import turn itself, right after the save:
   the reply's `next` names the `test_in_game` call (`chat/import_job.PLAY_FIRST`), and the play session builds its
   own test copy from clean Melee, so no game copy of the user's is involved; a separate fighter from it is
   `create_clone_character` (`../assistant/clone_character.py`).

7. **Something looks wrong (the main model, then code, then rigswap).** The user says what ("the legs look wrong",
   "his head is too big", "he faces backwards") and the main model calls `import_model(project=<the import's>,
   change=<their words>)`. `studio_import.prepare` takes no fighter for it, refuses a project that is no folder
   here, and adds the user's own newest message to the call (`said`): that message, word for word, is the complaint
   rigswap's look reads, and the chat model's `change` goes beside it as what was understood (`--heard`), used only
   to tell which part is meant. A size the chat model adds of its own is not the user's (2026-11-09: "it's still too
   big" went on as "around 0.6"). `import_job.change` reads the import's `workflow/job.json` and `rigswap/done.json` (rigswap's newest result
   that made a costume) and runs `RIGSWAP_PYTHON -m rigswap.plugins.melee.costume --fix <project>/rigswap "<the
   user's message>" --heard "<the chat model's change>" --cache ...`. rigswap's `costume.fix` asks one look (`core/complaint.py`: the source, the finished costume in the
   fighter's frames, the fighter's own stance, the record said in words, and the numbered joints) which entry of the
   import's `record.json` to change: a size (`head`, `limbs`, `trunk`, `size`: the look says which way, and how much
   only when the user named an amount; else it is one modest step), the `front`, joints by number, whether a part
   hanging off the body swings or holds still (`parts`: hair, cloth, a tail, or stiff, for the joint where it
   leaves the body and all below it), or a piece of the model to leave out or bring back (`drop`: the look says
   which way and the user's words for the piece, and the rebuild, which has the model open, shows its pieces on
   numbered tiles to one more look that says which they are: rigswap's `core/pieces.py`; since 2026-11-10). It
   writes the changed record beside the load and builds again into `rigswap/2-swap-fix<n>`. Done: the costume is
   saved as a second costume named `<name> 2` (`finish-2/finished.json`), the reply carries `changed` and `why`, and
   its `next` is `CHANGED_NEXT`: say what was changed, that the first costume stays, and ask the user to look
   (nothing has seen the result, so it is never called fixed). Failed: nothing new is saved and the first costume
   stays (`NOT_CHANGED`); stage `fix` is a complaint the record cannot hold, in the look's words (`Unfixable`). A
   rigswap that has no `core/complaint` (`import_job.can_change`) or an import with no record is a failed reply that
   says to import it again. `job.json` keeps each change (`changes`: words, name, status, saved, changed).

**The import's own check.** After every build rigswap looks once at the finished costume in the fighter's idle and
run frames (`plugins/melee/tripwire.py`) and says only whether it is a wreck: not upright, or in pieces. When a look
filled the body's record and the check alarms, rigswap asks a second model for the body and builds once more; if the
check still alarms the result carries `warning`, the reply does too (the card shows it as written), and `WARNED_NEXT`
quotes it whole and has Randall pass it on word for word, never softened. No look is trusted to call a costume good, so nothing loops on one.

## When it does stop

Only on a real failure (step 5) or the user's Stop; nothing is saved. Before rigswap runs: no source, a fighter it
does not target (Ice Climbers, or not a fighter: refused at `prepare`), rigswap not set up
(`import_job.NOT_SET_UP`), no vanilla disc set (`import_job.NO_DISC`). In rigswap: the file cannot be opened or holds
no model it reads (`load`), the fighter could not be picked (`pick`), or the model cannot be put on the fighter
(`swap`). A crash, a run past the timeout or a run that wrote no result.json is "an internal error in the importer".
The vault refusing the costume is not a failure: the import is `done`, not saved. Older chats hold v4 replies
(`needs_user`, `refused`, a `flow`, `choices`); the card draws them plainly and nothing carries them on (a new
`import_model` call is a new import).

## Where state lives

- **The project:** `<storage>/model_imports/<id>/` (or `NUCLEUS_STUDIO_ROOT`): `rigswap/` (rigswap's out folder:
  its stages, `2-swap/4-export/<Fighter>.dat`, `2-swap/record.json` (what the build read of the model: a change
  edits one entry of it), `result.json`, `done.json`, and `2-swap-fix<n>/` per change), `workflow/job.json` (the
  costume's name, the upload, the fighter as the app and rigswap name it, and each change), `workflow/job.log` (every
  line rigswap printed), `finish/` (the portrait and `finished.json`, the save's receipt; `finish-<n>/` for a
  change's costume), `randall.jsonl` (one row per chat turn). Uploads are staged in
  `<root>/.uploads/`; rigswap's asks are cached in `<root>/.rigswap-cache/` (`RIGSWAP_CACHE` moves it), shared by
  every import.
- **While it runs:** the running card only (`import_job._Progress`).
- **In the chat:** the `import_model` receipts in `<storage>/assistant/chats.db`; the pictures and the costume file
  as chat files in `<storage>/assistant/files/` (`shared/mod_files.py`).

## Files

| Path | What it does |
|---|---|
| `chat/studio_import.py` | When a turn is an import turn; its roster and card; the finished import another fighter can follow; the picked fighter; preparing and running `import_model`; attaching its picture and the costume file; the per-turn ledger |
| `chat/import_job.py` | The `import_model` job (`SCHEMA`): the fighter (app name <-> rigswap's), rigswap as a subprocess, the running card, Stop, the vault save with its receipt, the reply (done, the fighter it picked, a failure said), and a change to a finished import (`change`) |
| `chat/attached_model.py` | An attached model waiting to be imported (how an ordinary chat starts one) |
| `studio/finish.py` | The vault save: costume DAT -> new vault costume with its portrait, stock icon and Slippi fix (`finish`, `costume_code`, `vault_storage`) |
| `studio/slippi.py` | The Slippi check on a costume DAT (`check`) |

`studio/` keeps its name because the Pokemon-cast build tools outside the repo import `finish` and `slippi` from it.
The one helper outside this folder is `shared/modellab/fighter_catalog.py` (the app's fighter names and Pl codes).

## Tests

From the repo root (`test_assistant_import_job.py` runs a fake rigswap package as a real subprocess):

```
app\venv\Scripts\python -m pytest -q -p no:cacheprovider tests/backend/test_assistant_import_job.py tests/backend/test_assistant_studio_import.py tests/backend/test_attached_model_routing.py tests/backend/test_assistant_bp_fighter_context.py tests/backend/test_no_retired_model_import.py
```
