# Randall

The one current description of Randall. Written 2026-10-02 from the code (starting points and turn
routing revised 2026-10-03); where an older doc said something else, the code won (the differences are
listed in "Where this corrects older docs").
Retired docs: in git history before 2026-10-03 (the four Randall docs, the model-import plans).

Randall is Nucleus's AI helper. Earlier generations were deleted on 2026-10-02 ([History](#history)).

| Part | What it is | Where |
|---|---|---|
| **Assistant** | The chat panel: a normal chat plus five starting points (retexture a costume, import a character model, create a character (not built), retexture a stage, and import a stage model, which is listed but not built); in any chat also stage edits, find and download mods, clone a character, in-game tests, deliver to the game, "Report this chat". | `backend/randall/` (`assistant/` the chat, `recolor/`, `model_import/`, `website/`, `delivery/`, `reports/`; index in its [README](../../app/backend/randall/README.md)), `backend/shared/modellab/`, `frontend/src/randall/assistant/` |
| **Coach** | The Tracker's stats coach ("Analyst" tab): answers over baseline packs and the player's own replay index. | `backend/randall/coach/`, `frontend/src/randall/coach/` |
| **aiengine** | The shared runtime both use: the fast lane (coach lookups, recolor acquisition), the per-turn decision, image generation, image upload. | `backend/shared/aiengine/` |

`tools/harness/harness_mcp.py` (the `melee-harness` server, [MCP_SERVER.md](MCP_SERVER.md)) is the
developer test harness. It is not a Randall surface and Randall does not call it.

## What it is to a user

### Assistant panel

A persistent chat panel (`AssistantPanel.jsx`), mounted on first use and kept alive while closed or
while the user switches modes. Randall's voice (`assistant/prompt.py` VOICE, launch-film pass 2026-10-06): friendly,
confident and brief, one or two sentences, no jargon, never restating a card on screen, ending with at most one
offer. The fixed sentences the backend hands the chat (stop and limit lines in `main_model.py`/`engine.py`, delivery
summaries and limitations) are written in the same voice; a stopped turn's line is first person and says what the
user can do ("I've hit my limit for this request. ... ask again and I'll pick it up."). It knows the page, the selected character or stage, attached files and
the vault selection (the `context` the frontend sends, see "Request path"). Everything it does to the
user's data is either read-only, a private working copy, or goes through an approval card.

A chat is a normal chat (**Ask**) or starts from one of five starting points (task pill or
empty-state tile), the launchable tasks (`recipes.LAUNCHABLE`), shown in two labelled groups (`group`): Characters, then Stages.
The user-facing word is "Retexture"; ids, code and the model-facing cards keep "recolor" (the two recolor cards
say in their title line that the user may call it retexturing).
Each names the picker the panel shows when starting it (`picker`) and whether it can be started
(`available`), both served in `GET /status` `tasks[]` (decided 2026-10-03 for the first release):

| Task id | Label | `picker` | `available` | What the user gets |
|---|---|---|---|---|
| `recolor_part` | Retexture a costume | `costume` | true | A new colour or material look on one costume, saved as a new vault costume. The picked costume arrives as `context.selection` and is opened by code. |
| `model_import` | Import a character model | `fighter` | true | A 3D model (zip, glb, gltf, obj, fbx, dae, smd) turned into a Melee costume in the vault. The picked fighter arrives as `context.fighter` and the import goes on it. |
| `create_character` | Create a character | none | **false** | Nothing in Randall: a disabled "Use MCP" tile ("Use MCP (Settings > AI): build a whole new fighter, starting from a model."). No card, no tools, no routing; a request naming it reads as a normal chat ([stub](../../app/backend/randall/create_character/README.md)). Not the ordinary `create_clone_character` ability, which clones an existing fighter in any chat. |
| `recolor_stage` | Retexture a stage | `stage` | true | New colours on one stage in the Stage Lab, saved as a new vault stage variant. The picked stage arrives as one `context.selection` entry of kind `stage` and is opened by code. |
| `stage_import` | Import a stage model | none | **false** | Nothing in Randall: a disabled "Use MCP" tile. No card, no tools, no routing; a request naming it reads as a normal chat ([stub](../../app/backend/randall/stage_import/README.md)). |

Not launchable but reachable as follow-ups (`recipes.FAMILY_TOOLS`): `deliver_to_game`,
`verify_in_game`. A task is offered only while at least one of its operations is switched on in this
build; `GET /api/assistant/status` returns the list as `tasks`. Model import is always offered, and the
stub is always listed (as not available). `recipes.startable` is the set a chat can actually be started
as (the available rows); `task_id` and `chat_task` know only those.

Also in any chat, as ordinary abilities: find and download mods from the website and the vault (the
find-a-mod card arrives with the first website call), recolor (the recolor card arrives with the first
skin call), clone a character, manual in-game test, stage edits, install into a project, organize vault
skins, wiki help (`search_docs`), like a website mod (needs the Nucleus account), and a model import when
a model file is attached and asked about.

"Find a mod" and "Menu background" were starting points until 2026-10-03. A chat stored with either
task opens as a normal chat (`store` reads the stored id through `recipes.task_id`; `chat_task` drops
it), with no card from its old task and no nudge.

### Tracker coach

The "Analyst" tab in Tracker (`CoachPage.jsx`). The player asks about their own games, matchups,
habits and the population baseline; the coach calls stats tools and answers, with clickable clips.
It never edits anything. It is stats-only: there is no playbook (removed 2026-07-13).

Both chats need an active Patreon AI entitlement. The viewer refreshes entitlement before each turn and
passes the provisioned OpenRouter key in the request's `api_key`. The backend keeps it in memory for
that turn. Neither chat reads the local OpenRouter key, and a depleted allowance does not fall back to
one (`engine.start` raises "Link an active Patreon membership" when there is no key;
`coach_api.dev_key_available()` returns False).

## Request path (assistant)

All routes are `/api/assistant/*` (`randall/routes/assistant_bp.py`), 404 when the `assistant`
gate is off.

| Route | Purpose |
|---|---|
| `GET /status`, `GET /app-context` | Availability, the `tasks` catalog, the live app snapshot (`app_context.read`). |
| `POST /chat` | One user message. SSE stream of the reply. Limits: 8,000 characters, `context` 12,000 bytes JSON. |
| `GET /chats`, `GET/DELETE /chats/<id>` | History from `chats.db`; each row carries its `task`. |
| `POST /chats/<id>/inputs`, `PATCH/DELETE .../inputs/<input_id>`, `POST .../inputs/batch` | The queue of messages sent while a turn runs (queue and steering). |
| `POST /runs/<run_id>/cancel` | Stop. |
| `POST /chats/<id>/approvals/<approval_id>`, `GET .../approvals/<id>/files` | Approve or deny a prepared action (window only: the window-only key `X-Nucleus-UI-Key`, `core/ui_channel.py`, so an MCP client or script cannot answer one); page a download's file inventory. |
| `POST /website/download`, `/website/vault-status`, `/website/like`, `/website/like-status` | Direct download from a website card (no model round), vault presence, account likes. |
| `POST /files`, `GET /files/<id>`, `GET /previews/<id>`, `GET/DELETE /chats/<id>/game-tests/<session>`, `POST /actions/<id>/undo` | Files and previews, play-session status and Stop, undo of a vault organization. |
| `POST /destination`, `POST /destination/<id>/activation`, `GET /deliveries`, `POST /deliveries/<id>/undo` | "My game" and delivery receipts. |

`CONTEXT_FIELDS` is the whole whitelist the client may send: `page, character, stage, selection, files,
editor, task, fighter`. A `task` the build cannot start (not in `recipes.startable`, which leaves out the
`stage_import` and `create_character` stubs) is dropped; a `fighter` is kept as the import roster's own name (`/status`
`import_fighters`) or dropped; a `selection` entry of kind `stage` is checked (`assistant_bp._stage_item`)
and dropped when the Stage Lab cannot open it, every other entry passes untouched. `allow_changes` in a
body is rejected.

Picker contracts (what a starting point's first message carries):

- **Recolor, `picker: 'costume'`**: `context.selection` with exactly one entry, either a vault costume
  `{"character": "Fox", "skin_id": "<vault id>"}` (`id` is read as `skin_id`, as `search_vault` items
  carry it) or a stock costume `{"character": "Fox", "vanilla": true, "color"?: "Nr"}`
  (`workflows.picked_costume`). The recolor workflow opens exactly that costume with `open_vault_file` /
  `open_vanilla_file`, issued by code: no search, no fast-lane round, whatever the words name. Several
  entries, or a website variant `{"post_id", "file_id"}`, go to the acquisition lane as before.
- **Import, `picker: 'fighter'`**: `context.fighter`, a fighter name (`studio_import.fighter_choice`
  reads the roster's names, any case, and the importer's aliases). The newest user message carrying one
  wins (`studio_import.chosen_fighter`). A new `import_model(source)` call that names no fighter gets it
  (`studio_import.prepare(..., fighter=)`; the receipt shows it), the import card says so, and the
  import never asks which fighter (D2 runs only when none was named). A fighter the model's call names
  stays only when the user's own messages in the chat name a fighter (`studio_import.named_fighter`: roster
  names, the importer's aliases and `SPOKEN` forms, whole words; it errs towards finding one). Otherwise it is
  the model's guess: it gives way to the picked fighter, or with none picked is dropped so the import's fit
  step chooses (`prepare(..., words=)`; 2026-10-06, "whichever fighter he actually fits" was sent as G&W).
- **Stage recolor, `picker: 'stage'`**: `context.selection` with exactly one entry of kind `stage`: a vault
  stage variant `{"kind": "stage", "stage": "GrNBa", "id": "<variant id>", "name": "Battlefield · Night Sky"}`
  or the stock stage `{"kind": "stage", "stage": "GrNBa", "vanilla": true, "name": "Battlefield (stock)"}`.
  `stage` is a code from `/status` `recolor_stages` (`recolor/stage_lab.supported_stages`: the 29 versus
  stages of `core/stages.ALL_STAGES`; a vault folder slug is read as its code), `id` is the variant id the
  Vault's stage list serves (the archive `<storage>/das/<folder>/<id>.zip` must exist), `name` is a label
  (trimmed, at most 120 characters; the stage's own name when missing). The blueprint returns the entry with
  exactly those keys or drops it. On turn one code opens it with `stage_lab_open(stage_code, variant_id?)`
  (`recolor/stage_start.picked_stage`, `StageStart`): no search, no model round.

Inside the engine (`randall/assistant/engine.py`, the turn loop; `main_model.py` holds the model request, `live_runs.py` the runs, approvals and SSE stream):

- Main model `z-ai/glm-5.3-flash` (`NUCLEUS_ASSISTANT_MODEL` overrides), providers pinned to
  `fireworks,z-ai` for prompt-cache hits (`NUCLEUS_ASSISTANT_PROVIDERS`). Streaming OpenRouter tool calls.
- Tools exist only in `assistant/tools.py` (`SCHEMAS` and its dispatch share one allowlist). The client
  never sends tool history or system messages. No shell, HTTP, path or MCP passthrough exists.
- Each tool is automatic or approval-gated. `approvals.py` issues expiring one-use grants bound to the
  exact prepared call; decisions are persisted before execution and survive viewer reloads.
- A task card (`recipes.CARDS`, version in `RECIPES_VERSION`) is attached once, naming the signatures
  that task needs: before the first call for a declared task or a follow-up, else with the first call
  of its kind. See "How a turn is routed".
- One provider reply and one direct download may run at a time (409 otherwise).
- Recolor budget, costume and stage alike: a prompt to wrap up at 15 rounds, stop at 20 rounds or 10 cents
  of text spend (`SKIN_WRAP_UP`, `SKIN_MAX_ROUNDS`, `SKIN_MAX_COST`; a stage turn gets `STAGE_WRAP_UP_NOTE`). Once its lab
  session is open the turn sees only `SKIN_TOOLS` / `STAGE_TOOLS`, whether code opened it (a workflow turn) or
  the model did (an ordinary chat's first session); the next message gets the whole roster back. Model import
  budget: 150 rounds, 3.00 USD per turn (`NUCLEUS_STUDIO_MAX_ROUNDS`, `NUCLEUS_STUDIO_MAX_COST`). Other turns have no fixed cap; the panel
  shows a "Still working" notice after two minutes or 12 rounds (`LongRunningNotice.jsx`).
- Generated images have their own allowance in every turn (a retexture or an ordinary chat): 3 billed images
  per user turn (`engine.IMAGE_ALLOWANCE`, `NUCLEUS_IMAGE_ALLOWANCE`), counted in images, not dollars
  (`coordinator.TaskContext.allow_images`). One `generate_material` sheet is one image (up to four swatches);
  `style=artwork` is one per prompt. An image is admitted while the turn has images left, whatever the text
  spent, and the money caps above read text spend only (`TaskContext.text_committed_usd`): the image's real
  charge still counts in the chat's cost (`cost_parts.images`), the task's accounting and the Patreon key's
  own limit. Until 2026-10-04 an image was admitted against the 10 cents with a 5-cent reservation (about
  five times its measured cost), so a retexture whose recolour rounds had spent 5 cents could generate nothing.
- Refusals say themselves (`assistant/refusals.py`). A paid request the coordinator refuses before sending it
  (the spending limit, the request limit, the turn's images used up, a stop, a newer message, a finished task,
  a dispatch it could not record) reaches the tool card as one plain sentence ("This request already generated
  its three images; ask again in a new message to make more.", "This request reached its usage limit, so this
  step did not run; send a new message to carry on.") and the model as that sentence plus `next`: retrying
  cannot work this turn, tell the user what was and was not done. After a refusal that lasts the turn
  (`LASTS_THE_TURN`) every later call of the same paid family (`PAID_FAMILY`: `generate_material`) gets the
  same result without running. Only an unexpected exception gets the generic "The tool could not complete...",
  with the exception in `diagnostic` (card-only, `compaction.UI_ONLY_ANY`; "Report this chat" keeps it).
  Turn-level stops (the round and cost budgets above) end the turn with their own sentence on the answer.

### How a turn is routed

Since 2026-10-03 the user's words pick no task; only the chat's starting point, its attachments and the
tools the model calls do. In order (`engine._run_turn`):

1. A card-button download (`POST /website/download`) runs its one tool; nothing below applies.
2. One typed decision (`decisions.decide`, Jev): `effort`, which can only lower the main model's
   reasoning budget, and the recolor acquisition gates (`wants_vanilla`, `wants_website`,
   `variant_named`). It sends no turn anywhere.
3. The chat's declared task (`recipes.chat_task`, its first user message): `recolor_part`,
   `model_import`, `recolor_stage`, or none (`stage_import` and `create_character` are never declared tasks). A finished import
   lets its chat go (`turn_facts._pinned_task`).
4. The card before the first call (`recipes.turn_family`): a follow-up the words ask for
   (`recipes.FOLLOW_UPS`, the only word list left: "put it in my game" -> `deliver_to_game`; "test it in
   game", "show me him in game", "let me play him" -> `verify_in_game`), else the declared task, else none.
   A model import that has not saved its costume yet is never displaced by follow-up words (nothing is made
   yet: "import him and test him in game" is the import), and neither is a waiting attached model (step 5). The delivery card must be there before
   the first call (it keeps Randall on `deliver_to_game` instead of an `install_project_mods` approval),
   and naming the follow-up keeps a recolor chat from opening a source costume again.
5. Attachments (`attached_model.attached_model_waiting`): a model file the chat has not imported and the
   message asks to act on. A `.zip` is opened: one holding fighter DATs and no 3D model is a costume
   pack, not a model. In a recolor chat, a model-only file attached to this message gets the
   one-sentence nudge to an import chat (`recipes.task_mismatch`, `routing.task_mismatch`; the panel
   shows a button). In an ordinary chat it makes the turn an import turn.
6. An import turn (`studio_import.turn_mode`): a declared import (until done), the waiting model, or an
   import from before 2026-10-03 that stopped on a question (`studio_import.unfinished`: the next message
   carries it on). Its roster is `import_model` and `search_docs`, its card the import card, and the picked
   fighter is filled in. Without an attached file an ordinary chat is not an import turn: the prompt tells
   Randall to ask for the file. After a finished import, the chat's normal turns are offered `import_model`
   beside the app's roster (`studio_import.changeable`), so a change the user asks for reaches it.
7. The recolor workflow (`engine._recolor_enrollment`, `workflows.Workflow`): only in a recolor chat,
   on a turn whose card is the recolor (not a follow-up), with no nudge and no model waiting, not a
   question, refusal or several costumes (`one_recolor`), and no skin session yet. Acquire: code opens
   the picked costume, else the stock default of the one fighter the words name; otherwise the
   acquisition lane (Gemini, `workflows.ACQUIRE`). Prepare: code (`skin_lab_open`, then `texture_usage` and the
   first `texture_sheet` in one round). Then the main model.
   In a stage recolor chat the engine uses `recolor/stage_start.StageStart` instead
   (`engine._stage_enrollment`: the same conditions with `recolor_stage`; plus exactly one picked stage, no
   Stage Lab session opened in the chat yet, not a question or refusal): code issues `stage_lab_open` for
   the picked stage, then the main model works with the stage card. No acquisition lane; the open is the
   prepare step (its result carries the first picture, the labelled texture sheets and the texture rows).
8. Everything else: the main model with the whole roster. The card follows the first called tool
   (`recipes.family_for_tool`): a website tool or `present_vault_skins` -> find-a-mod, a skin tool ->
   recolor, a Stage Lab tool (`stage_lab_open`, `stage_lab`) -> stage recolor, `test_in_game` -> verify,
   `deliver_to_game` -> delivery. Tools that also serve other work (`search_vault`, `save_mod_copy`,
   `open_vault_file`, `list_projects`) attach nothing.

Budgets follow the same signals: the recolor budget for a workflow turn (costume or stage) or a turn that
opens a chat's first skin or stage session itself; the import budget for an import turn (`turn_facts._turn_family`: a declared
import, an unfinished older import, or a waiting model, never the words).

Removed on 2026-10-03: "Find a mod" and "Menu background" as starting points; the `menu_background`
family (its card, which pointed at a menu workflow that never existed, its tools entry, trigger and the
colour/menu overlap rules); the word triggers for recolor, model import, find-a-mod and menus, and the
word-based mismatch nudges; the assistant's general fast lane (Gemini answering lookups, domain `mod`,
its intent regex and rules; the useful search rules moved to the find-a-mod card); the decision
questions `needs_main` and `recolor`; and the recolor workflow in an ordinary chat (word enrolment).
The tools all stay.

## Workflows end to end

Each line is: entry -> task -> delivery -> approval.

### 1. Model import (`model_import`)

The whole path, stage by stage, with the files and the tests: [`randall/model_import/README.md`](../../app/backend/randall/model_import/README.md).

- **Entry.** An Import a character model chat (its fighter picked in the panel), or an ordinary chat with a
  waiting model attachment the message asks about. `studio_import.turn_mode` makes the turn an import
  turn: Randall is offered `import_model` and a few app tools (`search_docs`, `test_in_game`) instead of the
  whole roster. A request that asks to see or test the model in game gets its play session in the same turn,
  after the save (the done reply's `next` names the call); it needs no game copy of the user's.
- **Task.** `model_import/chat/import_job.py` runs **rigswap** (its own repo and Python) as a subprocess, since
  2026-10-29: `RIGSWAP_PYTHON -m rigswap.plugins.melee.costume <upload> <Fighter|auto> <project>/rigswap --cache
  <imports root>/.rigswap-cache`, in `RIGSWAP_HOME`. A packaged app runs the installer's own rigswap package
  (`resources/utility/rigswap/app`, built by `tools/build/fetch_rigswap.py`, on every platform) on the model import
  tools the user downloads from Settings (a CPython 3.13 with rigswap's wheels, and Blender 4.3.2:
  [MODEL_IMPORT_TOOLS.md](MODEL_IMPORT_TOOLS.md), `model_import/tools/`); without them an import starts nothing and
  replies `needs_tools`, and its card has a Download button. A source checkout runs the developer's (`DEV_ENV`). rigswap makes each fighter's targets from the user's own disc the first time an import needs them
  (nothing Nintendo-derived ships); one missing is a failed reply before anything runs. A fighter the user named or
  picked is mapped to rigswap's name by
  Pl code (`RIGSWAP_FIGHTERS`); with none, rigswap picks the one the model fits best (`auto`) and its result says
  which and why (`fighter_pick`). rigswap's asks go on the turn's own key (`OPENROUTER_API_KEY` in its environment,
  never logged); every line it prints goes to `workflow/job.log` and the running card. It runs straight through:
  nothing is asked of the user. The in-game test is not part of the import. The user's Stop ends rigswap by its PID
  tree. The v4 engine that ran before rigswap was deleted on 2026-11-03 (the tag `archive/v4-importer` marks the last
  commit with it). On macOS and Linux rigswap leads its own process group, so the Stop reaches the Blender and the
  headless viewer it started.
- **Ends in.** `done` (rigswap's costume file saved to the vault as a new costume by `studio/finish.finish`, its
  receipt `finish/finished.json`; the reply has the fighter, `fighter_pick` when it picked, the costume name,
  rigswap's seconds and cost, the portrait) or `failed` (where rigswap stopped: loading the model file or putting it
  on the fighter, its cause in its own words, what the user can do; nothing saved; rigswap's raw cause card-only as
  `diagnostic`) or `cancelled` (the user pressed Stop; nothing saved, even when rigswap had already finished). The
  card shows the saved name and the portrait, so the chat model's closing reply is one or two
  sentences of its own that add to the card and never restate it, and say the fighter it picked and why when it
  picked (`import_job.DONE_NEXT`, `PICKED_NEXT`, `studio_import.IMPORT_CARD`). When the request also asked to see or
  test it in game, the saved reply's `next` starts with `PLAY_FIRST`: call `test_in_game` with no text before it,
  then write that one closing reply after it returns, adding where and how they play from the session's `note`
  (`game_tests._play_note`: the panel on the right, straight into a match, controller port 1, Stop; never "running"
  before the session is live). The engine enforces the one reply (`engine._after_import`): in the round right after
  a saved import, with `test_in_game` on offer, the model's words are held until its calls are known; when it calls
  `test_in_game` they are dropped from the reply and the stream (kept in the model's context and in the answer's
  `dropped_interim`), otherwise they are sent as they were.
- **Another fighter afterwards.** `import_model` again with the same source and that fighter: a second costume; the
  first stays. Carrying on an older import that stopped on a question, the end summary's `choices`, the card's
  `flow` and picture sheet and SMD sources went with v4.
- **Something looks wrong afterwards.** `import_model(project, change)`: the import's project and what the user said
  ("the legs look wrong"). The complaint that reaches rigswap is the user's own newest message, word for word
  (`studio_import.prepare` adds it as `said`); the chat model's wording goes beside it (`--heard`) only to tell
  which part is meant, so a size it adds of its own is not used. `import_job.change` runs rigswap's
  `--fix <project>/rigswap "<words>"`: one look reads the
  import's record (its facing, the joints of its body, four sizes) beside pictures of the finished costume and names
  the one entry to change; rigswap builds the costume again from the changed record. It is saved as a second costume
  (`<name> 2`, receipt `finish-2/`); the first stays, and `workflow/job.json` notes the change (`changes`). The reply
  says what was changed (`changed`, `why`) and its `next` (`CHANGED_NEXT`) has Randall ask the user to look: nothing
  has seen the result, so it is never called fixed. A complaint the record cannot hold (a texture, a missing piece)
  fails at stage `fix` in the look's own words; a rigswap without the change code, or an import with no record, is
  a failed reply that says to import it again (`NO_CHANGES`, `NOT_CHANGEABLE`).
- **Texture files first.** Before rigswap runs, `chat/textures.missing` looks for the files the model names (an
  OBJ's materials and colour maps, a DAE's images, an FBX's external texture files, a glTF's buffers and images)
  where rigswap will (beside a bare file, anywhere in a ZIP). Some missing is a `needs_textures` reply with no
  project: Randall names them and asks for a ZIP with them, or goes on with `untextured: true` once the user says so
  (`import_job.textures_reply`, `TEXTURES_NEXT`; over MCP `TEXTURES_NEXT_MCP`, answered at once by `import_model`).
  The turn knows before its first round: as an import turn is set up, `studio_import.without_textures` runs the same
  check on the attached models not imported yet, and the card names each one that lacks its textures and has Randall
  write nothing before that call (the recipe's "Starting now" sentence is for an import that starts). The engine
  holds a backstop like `_after_import`'s: until the turn's first import call, with such a model attached, the
  model's words are held until its calls are known, and dropped (`dropped_interim`) when one is an `import_model`
  that will come back `needs_textures` (`studio_import.asks_for_textures`: that source, no `untextured`). 0.9.0 smoke:
  "Starting now: I'll put Sack Boy on Ness and save him to your vault." above "nothing was imported yet". The chat's
  import card shows the reply as waiting (a `!` in the warning colour, outcome `waiting`), never a ✓.
- **The import's own check.** rigswap looks once at its finished costume in the fighter's idle and run frames and
  says only whether it is a wreck (not upright, or in pieces); its result's `warning` goes into the reply, the import
  card shows it as written, and the `next` (`WARNED_NEXT`, right after the reply's first fact) quotes it whole and
  has Randall pass it on word for word, never softened ("may", "might") and never called done. 0.9.0 smoke: "this
  probably did not work: Small parts float apart..." had reached the user as "small parts may float apart".
- **Approval.** None for the import itself (it writes only a new vault costume and a project folder).
  Any later install into a project uses the project approvals below.
- **Where it writes.** `<storage>/model_imports/<id>/` (or `NUCLEUS_STUDIO_ROOT`): `rigswap/` (rigswap's out
  folder and its `result.json`), `workflow/job.json`, `workflow/job.log`, `finish/` (the portrait and the save's
  receipt), `randall.jsonl` (per-turn model, cost, tokens).
- **Frontend.** `StudioCards.jsx` and `studio.js` route cards by the `studio_import` reply tag: the import card (the
  fighter, its time on the status bar's clock, the running lines, where it stopped, the portrait, the saved costume).
  An older chat's v4 import reply draws plainly from the same fields, with no buttons. `activity.js` names every
  studio call. The workbench beside the chat (`workbench.js` reads the transcript, `WorkbenchPanel.jsx` draws it)
  shows an import only once its reply carries the costume file: it opens on that file in 3D on the reply's fighter
  (also when the user had hidden it, for an import that finishes while its chat is open: `opensFor`), titled with the
  costume's name and fighter, with In game once it is tested. An import has no Pictures tab and no step under the
  title: the card shows its steps and its portrait. A running import, or a reply without a costume file (failed,
  `needs_textures`, `needs_tools`, stopped), leaves the panel as it was. Pictures (every render of the chat, grouped
  by step) and the step under the title are Skin Lab's and Stage Lab's only.

### 2. Recolor, Skin Lab and Stage Lab (`recolor_part`, `recolor_stage`)

The pipeline stage by stage, with its tools, files and tests: [`randall/recolor/README.md`](../../app/backend/randall/recolor/README.md). Palette math, materials and the swatch library are described in [RANDALL_RECOLOR.md](RANDALL_RECOLOR.md).

- **Entry.** A Retexture a costume chat (its costume picked in the panel). In an ordinary chat Randall
  recolors with the main model and the whole roster; no workflow runs there (the turn that opens its first
  session is budgeted and narrowed like a workflow turn from then on).
- **Sessions reopen.** A Skin Lab or Stage Lab session that closed (15 idle minutes, `close`, a restart) reopens
  from its last checkpoint on its next call, under the same session id, with its reset originals, palette
  analysis and scope choice (`recolor/lab_common.live`; the recolor README has where each is kept).
- **Task.** A fixed ownership split (`recolor/workflows.py`): acquisition of the source costume is code when it
  can be (the picked costume, or the named fighter's stock default), otherwise the acquisition lane
  (Gemini Flash Lite: vault first, then website, vanilla only on an explicit request);
  preparation is code (`skin_lab_open`, `texture_usage`, first `texture_sheet`); the creative work (parts,
  palette, materials, review renders) is the main model. Tools: `skin_lab_open`, `skin_lab`,
  `skin_material`, `generate_material`, `open_vault_file`, `open_vanilla_file`, `inspect_mod_file`,
  `unpack_mod_file`, `hsdraw`, `save_mod_copy`. All edits are copy-only; every output is a new immutable
  file handle (`shared/mod_files.py`); no vault item is ever overwritten.
- **Generated materials** call an image model (`shared/aiengine/image_api.py`, default `meta/muse-image`,
  `NUCLEUS_MATERIAL_MODEL`) on the request's key, within the turn's own allowance of images (3,
  `IMAGE_ALLOWANCE`; see "Request path"); swatches are indexed by theme (`recolor/swatch_library.py`)
  so a repeated theme is free.
- **Stages.** `stage_lab_open` / `stage_lab` (`recolor/stage_lab.py`, `assistant/stage_scene.py`) use the live Stage
  Creator renderer for textures, materials and scenery. A *Retexture a stage* chat (`recolor_stage`) is these
  two tools with a one-step start: code opens the picked stage (the open returns the first picture, labelled
  texture sheets and texture rows), the main model does the rest with the stage card
  (`recipes.CARDS['recolor_stage']`): batched exact-colour edits (`recolor` with `edits`), `reset_texture`,
  and generated materials through the costume pipeline's own `generate_material` + `skin_material`, which take a
  Stage Lab session too (`recolor/lab_common.py` is what both labs share). Greyscale (intensity) slots refuse
  colour, which the saved file would drop. It saves a new vault stage variant only when asked
  (`stage_lab action=save` -> `shared/rendering/stage_editor.save_copy`). Steps, limits and state: the
  recolor README's [Stage retexture](../../app/backend/randall/recolor/README.md#stage-retexture).
- **Workbench 3D view.** Each lab checkpoint whose edit changed only textures and material values carries
  `viewer_update` (card-only, `compaction.UI_ONLY_ANY`; `assistant/continuity.py`): `WorkbenchViewer.jsx` puts
  them into the renderer already running (`updateTexture`, `setMaterialColors`, `setMaterial`;
  `workbench.swapPlan`) instead of relaunching it (6-10 s of process and GL start-up per edit), keeping the
  camera and animation. Scenery, a different file or a failed swap reloads as before. A file of another subject or
  on another fighter loads with a fresh camera (`workbench.freshCamera`: each fighter's scene camera differs, Fox's
  22 units away at 70 degrees, Bowser's 1747 at 2). Another subject also starts in its pose: the picked animation is
  kept per subject (`workbench.wantedAnimation`), and since `loadDat` carries an animation over to a file whose
  fighter has it, one playing is stopped first (`resetView`). A right-drag pans by the renderer's own camera
  (`exportScene` z and field of view, `viewerInput.cameraPanStep`), so the model stays under the cursor on both
  axes; Pose in the animation list is the renderer's `resetView` with the camera then put back where the user had
  it (`workbench.cameraBack`); the reset button resets the camera and plays the animation again.
- **Delivery.** `save_mod_copy` (automatic when the user asks to save) imports a new standard costume with
  fresh CSP and stock icon and normal Slippi validation. Idle sessions close after 15 minutes.
- **Switches.** `NUCLEUS_RECOLOR_WORKFLOW=0` turns the workflow off; `NUCLEUS_FAST_ROUTING=0` turns
  off the acquisition lane (and the coach's fast lane): the workflow then runs only when code can open
  the source itself.

### 3. Download from the website (ordinary ability, "Add to Nucleus")

- **Entry.** Any chat: `search_website_mods` / `inspect_website_mod` (`randall/website/`), whose first
  call brings the find-a-mod card (`recipes.CARDS['find_mod']`), or a download button on a card
  (`POST /website/download`, which bypasses model routing).
- **Source.** The site's public mods API, `https://ssbmnucleus.net/api/public/v1` (documented in the
  website repo's `docs/public-api.md`), through `website_posts._api` with a `SSBM-Nucleus/<version>
  (Randall)` User-Agent: `GET /mods` for search (`q`, `character`, `creator` (the tool's `author`
  filter; a site without `creator` gets `author` instead), comma-separated `tags` /
  `exclude_tags` with the category as a tag, `sort=newest|downloads|likes`, `order`, `limit`), and
  `GET /mods/{id}` for one mod, where a 404 means it is not public. Cards credit the API's `creator`
  (`website_posts.credit`): `creator`, `author` (the uploading account) and `credit`, which reads
  "mcromich (via SSBM Textures)" for the mods re-uploaded from SSBM Textures. Pages use the API's opaque cursor:
  the tool takes `cursor` and returns `next_cursor`. The API leaves out files the site hides, so a
  `file_id` that is not listed is refused with that reason. Only likes (`api_like_status`,
  `api_toggle_like`, with the user's token) and the effect-type list (`api_get_effect_types`) still use
  the Supabase RPCs (`_rpc`); costume/stage/effect exports still come from the site's `/export-nucleus`
  route.
- **Task.** `download_website_mod` and `download_website_mods` (up to 24 posts, one combined approval).
  The bytes are downloaded into quarantine while the preview is built (`website_quarantine.py`), checked
  (`website_safety.py`: archive containment, nested archive budget, Slippi preflight), then imported into
  the vault through the same path as the website's `nucleus://import` handoff (`website_protocol.py`).
  A whole mod, or a published file that is not one of the three export types, is fetched through the
  API's counted `download_url`, which credits the creator: `_download` follows exactly one redirect, from
  `/api/public/v1/mods/<id>/download` to `media.ssbmnucleus.net`, and refuses every other redirect.
- **Approval.** Always. The card states what the object actually is and where it lands; the grant is bound
  to the object's hash (`approvals.py`). Unsafe costumes offer Fix, Add without fixing, or Cancel
  (`SlippiApprovalDialog.jsx`). Duplicates are skipped and recover their vault id.
- **Delivery.** The vault only, not a build (the tool description says so, and the answer must).
- **Gate.** `NUCLEUS_ANY_MOD_DOWNLOAD` (packaged off): with it closed only the three published export
  types (`character_dat`, `stage_dat`, `effects_dat`) download; anything else says to use the website
  button.
- **Likes.** `set_website_mod_like` needs the Nucleus account session (separate from Patreon).

### 4. Menu mods (no task)

No menu workflow exists, and since 2026-10-03 there is no menu task or card either. A menu mod is found,
downloaded and inspected with the ordinary tools like any mod. Writing a prepared menu change into a
managed build is behind the `build_commit` gate (closed in packaged builds).

### 5. Projects (`install_project_mods`)

`list_projects`, `inspect_project`, `create_project`, `install_project_mods` (`delivery/projects.py`). Create uses
the recorded vanilla ISO and MexCLI `create` in a new managed directory and never changes the active
project. Install takes up to 50 exact vault costumes (paired Nana included) and appends slots with MexCLI
`import-costumes`. Both need approval; the approval binds file sizes, mtimes and source hashes, and
execution revalidates under the shared MexCLI lock. No project deletion, slot replacement, ISO export or
stage/extras installation exists. Partial failures report real counts.

### 6. Clone a character (`create_clone_character`)

An exported costume `file_id` plus a name becomes a separate custom m-ex fighter (`assistant/clone_character.py`
over `backend/vault/echo/`): the original plus red, blue, green and gold costumes with rendered CSPs, stock
icons, CSS icon and name banners. The donor's gameplay is unchanged. Ice Climbers, Zelda/Sheik and Game &
Watch are excluded. Work is staged and published as one vault entry; failed renders never substitute
donor art; the same recipe returns the existing entry. Rendering does not establish gameplay acceptance.

### 7. In-game tests (`test_in_game`)

A manual offline play session in a live Dolphin card (`delivery/game_tests.py`). It is how Randall shows
something in game ("show me him in game", "let me play it"): it builds its own test copy from the clean Melee
file, so it needs no designated game copy and changes none. Targets: exact vault costumes,
exported costume handles, custom characters or stages, saved DAS variants. Start returns at once; the user
plays on controller 1 and stops with the card's Stop button or a chat request. One game at a time; a
restarted or evicted session shows unavailable and is never relaunched. ISO and Dolphin paths come from
the frontend's `game_settings` on each chat request and stay on the in-memory runtime, outside model
context. Sessions: `<storage>/assistant/game-tests/<session>.json`. Randall cannot see video or certify
gameplay.

### 8. Deliver to the game (`deliver_to_game`, `undo_delivery`)

`delivery/deliver.py` moves a vault costume into the copy of the game the user plays, through "My game"
(`delivery/destination.py`: a record the user created by an explicit action; Randall never picks a destination).
Five journaled phases (install, export, verify_build, promote, activate), a receipt written before the
first mutation, resumable, and undo by content hash. It never overwrites the clean Melee ISO and never
claims gameplay verified.

With no game copy designated (fixed 2026-10-06; before, nothing in the app could designate one: `POST
/destination` had no caller, so every such delivery ended at "a disc image exists, but nothing you launch
changed"), the sequence is: `create_project` when there is no project (approval), then
`deliver_to_game(project_id, set_as_my_game="slippi"|"offline")` (approval). That second card is the explicit
user action that designates: it names the project and the new file (`destination.suggested_output`:
`<output>/games/<project> (Nucleus).iso`), and `deliver._designate_approved` re-plans, designates
(`destination.designate`, `make_default=True`) and delivers to the new record. The played-ISO rule runs before
the card: a Slippi Launcher pointed at the clean Melee file itself has nothing to lose (`played_is_clean_source`),
a modded file still asks for `start_from_clean`. A Slippi copy is saved but stays `partial` until Launcher opens
the new file (Randall never edits Launcher settings). A delivery that already stopped at the project
("no game copy is set") is finished by the same call: its receipt is adopted (`deliver._adopt_project_only`)
and its verified build promoted, never imported into a second slot. A delivery's outcome is its own result's;
it never closes the chat's task mid-turn (`deliver_replies._finish`), which used to end the turn on "That task
already finished as partial; it cannot spend more". **Gate `NUCLEUS_DELIVERY`, packaged off:** closed means the call refuses with a
typed sentence.

### 9. Wishes and capability gaps

When Randall hits something the app cannot do, `assistant/capabilities.py` (declared data: scope,
limitation sentence, alternatives) decides whether it is a confirmed gap; only then
`reports/wishes.py` records a local wish and counts demand. Routes: `/api/mex/wishes` (list, review,
submit, decline, `capability_status`) in `randall/routes/wishes.py`. Submission is user-driven,
summary-only, anonymous unless identity is approved, and bound to a frozen reviewed ZIP. Gate
`NUCLEUS_WISH_SUBMIT` (packaged off) stops anything leaving the machine; wishes are still recorded.

### 10. Task journal

`assistant/tasks/` is the durable layer under all of the above: `contracts.py` (result envelope:
execution state is separate from outcome; a missing cost is `unknown`, never zero), `coordinator.py`
(task lifecycle, spans, stop at safe boundaries, resume from recorded stages, never replay a commit),
`events.py` (progress without model calls), `store.py` (SQLite journal and traces).

Each task names its owning process (`config_snapshot.owner`, as `core/jobs.py` records do). At startup
`app.py` runs `coordinator.resume_pending()`: a task no live process owns has its open model attempts and side
effects marked `unresolved` and is closed `failed` with error kind `interrupted` and the fact `interrupted`, so
a continuation in the same chat carries its spend (`turn_facts._carried_ledger`). The chat is saved once more
after the objective closes, so the reload after `done` reads the final task card.

### 11. Report this chat

Available on three surfaces: assistant, Tracker coach and the mobile vault's Randall tab
(`services/mobile/src/randall.js`, which has its own `randall-chat` edge function and is outside this doc).

- **UI.** A flag icon in the chat header (`ChatReportModal.jsx`, `chatReport.js`), disabled mid-turn. The
  modal shows exactly what will be sent; one checkbox includes attached files and preview pictures.
- **Flow.** `POST /api/mex/chat-reports/review` freezes a scrubbed ZIP under
  `<storage>/assistant/chat_reports/` and returns an `approval_hash`; `POST .../submit` (window only, the
  window-only key `X-Nucleus-UI-Key`: the consent is the person's) sends exactly the frozen bytes (`randall/routes/chat_reports.py`, `reports/chat_report.py`,
  `chat_report_files.py`). Transport is the bug-report worker (R2 bucket and a private Discord post):
  `randall/reports/report_transport.py` creates the remote report and uploads the frozen ZIP to the worker
  URL in `shared/diagnostics/bug_report.py` (the in-app bug report's module).
  Reports are anonymous.
- **Contents.** `report.json`, `conversation.json`, `transcript.md`, plus `files/` when approved.
  Mods turns include routing, cost parts, traced model requests and a failed tool's `diagnostic`. Coach turns include a bounded `trace`
  (`coach_api._trace_*`) that is never replayed to the model.
- **Scrubbing.** Everything passes the bug-report scrubber (paths, tokens, `sk-or-v1-` keys) before it is
  serialised or capped; results cap at 8 KB, arguments at 4 KB.
- **Release order.** (1) Deploy the worker first: `cd services/cloudflare/bugreport-worker && npm test &&
  npx wrangler deploy`, once per bucket add the receipt retention rule (`wrangler r2 bucket lifecycle add
  nucleus-bug-reports --prefix d/ --expire-days 90`); before that, desktop reports arrive labelled as plain bug
  reports and mobile reports fail. (2) Release the app. (3) `python services/mobile/build.py <site_dir>`, then
  `wrangler pages deploy`. Reports are kept 90 days in R2; desktop reports from an outdated app get 426.

## Tracker coach

- **Routes.** `randall/routes/coach.py`: `GET/POST /api/nucleome/coach/chats`,
  `GET/DELETE .../chats/<id>`, `GET/POST .../profile`, `GET .../status`, `POST .../chat` (SSE). They
  sit on the Tracker blueprint (`nucleome_bp` from `tracker/routes/nucleome.py`), so the endpoint
  names stay `nucleome.coach_*` and the Tracker gate (`NUCLEUS_NUCLEOME`) runs first; `app.py`
  imports the module before registering the blueprint. Every route carries `_requires_randall` (404
  when `NUCLEUS_RANDALL=0`).
- **Loop.** `coach_api.stream_chat`: up to 8 rounds (`MAX_ROUNDS`), 30 history messages
  (`MAX_HISTORY`), a per-process spend fuse of 2.00 USD (`SpendTracker`). Events: `tool`, `answer`,
  `error`. Clip tokens are handed to the model as small integers and swapped for real refs afterwards,
  so a fabricated clip cannot reach the UI.
- **Models.** Selectable `COACH_MODELS`: `minimax` (`minimax/minimax-m3`, default), `glm`
  (`z-ai/glm-5.2`), `deepseek` (`deepseek/deepseek-v4-pro`). The fast lane handles retrieval turns.
- **Tools.** `coach_tools_v2.TOOLS` has 30 tools (the registry and schemas; the tools live in `coach_tools_stats.py`, `coach_tools_corpus.py`, `coach_tools_combos.py` and `coach_tools_games.py`, the packs they read in `coach_data.py`, the prompt in `coach_prompt.py`): baseline and personal stats (`player_summary`,
  `matchup_stats`, `compare_to_baseline`, `death_breakdown`, `defense_stats`, `stage_stats`,
  `situation_table`, `my_situation_mix`, `tier_baseline`, `corpus_matchups`, `corpus_stats`,
  `corpus_trend`, `my_deep_stats`, `start_deep_analysis`), game and clip tools (`find_games`,
  `review_game`, `query_game_interactions`, `find_moments`, `session_report`, `queue_clips`), and
  combo/habit analysis (`punish_structure`, `scout_opponent`, `how_i_get_opened`, `kill_efficiency`,
  `combo_dropoff`, `metric_trend`, `stock_flow`, `punish_by_percent_zone`, `set_lens`, `leak_scan`).
  `coach_tools_live.py` merges the live replay index scopes into the pack tools.
- **Data.** Baseline packs bundled from `backend/tracker/baselines/`, how they are built and the
  Falco-tuned limits of the OOS classifier: [COACH_BASELINES.md](COACH_BASELINES.md). Personal packs come
  only from the user's mined replays (`deep_stats.build_player_pack`, `tracker/stats/`); missing mining gives setup guidance,
  never the bundled Falco fixture. The user-editable profile is a kv row (`coach_profile.py`); chats are
  rows in `nucleome.db` (`coach_store.py`).
- **Evaluation.** `eval/randall/v2_lane.py` is the live benchmark that picks the coach's model.

## Gates and what ships

The authority is `backend/core/gates.py` (`GATES`); `electron/main.js` mirrors it
(`tests/backend/test_gates.py` fails on drift), and [PREVIEW-0.9.0.md](PREVIEW-0.9.0.md) is the preview policy in
prose. Every gate is default-on in dev and off only when its variable is exactly `0`.

| Gate (variable) | Packaged | Preview package | Covers |
|---|---|---|---|
| `assistant` (`NUCLEUS_ASSISTANT`) | on (since 0.9.0) | on | The whole assistant API and the app MCP; frontend `ASSISTANT_ENABLED` (dev, or `VITE_ASSISTANT_PREVIEW=1`, which the build scripts set when `ship_guard.py gate assistant` passes). |
| `randall` (`NUCLEUS_RANDALL`) | off | off | The coach routes and the Analyst tab; frontend `RANDALL_ENABLED`. Its code (`randall.coach`) is left out of packages. |
| `delivery` (`NUCLEUS_DELIVERY`) | off | off | Delivering into a playable build. |
| `build_commit` (`NUCLEUS_BUILD_COMMIT`) | off | off | Committing a prepared menu/code change into a managed build. |
| `wish_submit` (`NUCLEUS_WISH_SUBMIT`) | off | off | Sending a wish off the machine. |
| `any_mod_download` (`NUCLEUS_ANY_MOD_DOWNLOAD`) | off | off | Downloading any website mod type, not just the three export types. |

So today (0.9.0): the public installer ships the assistant (Randall's chat and the app MCP) but not the coach,
and the three write paths behind the assistant stay shut in every package. The gate can still hold the
assistant back for a build (`packaged_off=True` in `core/gates.py` plus `main.js`; ARCHITECTURE §7). Tracker itself
(`NUCLEUS_NUCLEOME`) shipped in 0.7.0; the Randall tab inside it did not. Other env switches that are not
gates: `NUCLEUS_FAST_ROUTING`, `NUCLEUS_JEV_ROUTING`, `NUCLEUS_RECOLOR_WORKFLOW` (all default on).

## Runtime: aiengine

`backend/shared/aiengine/` holds the provider plumbing. Its modules:

| Module | Job |
|---|---|
| `fast_lane.py` | Per-turn Gemini delegation for the coach's lookups (domain `coach`) and the recolor workflow's acquisition stage (a `LanePolicy`); an ordinary assistant turn never uses it. `google/gemini-2.5-flash-lite` pinned to Google AI Studio on OpenRouter. At most 4 fast requests per turn; read-only lookups only; whole tool batch validated before it is published; any unsupported call, unknown handle, failed tool or provider error causes a sticky handoff of the original messages and completed tool results to the main model. Timeout 3 s connect / 8 s read, no retry. |
| `decisions.py` | One typed decision per assistant turn (`typesafe/jev-1.13` through OpenRouter): `effort` (only lowers the main model's reasoning budget) and the recolor acquisition gates (`wants_vanilla`, `wants_website`, `variant_named`, and `pick` among unpacked files). It routes nothing. `NUCLEUS_JEV_ROUTING=0` disables. |
| `image_api.py` | One OpenRouter image request per call, for material swatches; several swatches are drawn as one gridded sheet and cropped. No retry after a timeout (it may have been billed). Each request is admitted against the turn's image allowance (a call needing more images than are left is refused before any request). |
| `model_upload.py` | Encodes images for model requests (downscaled JPEG) and posts bodies in blocks with a stall timeout, for slow uplinks. |
| `keystore.py` | The user's own OpenRouter key, encrypted at rest (Windows DPAPI; base64 elsewhere) in `<storage>/openrouter.key`; env `OPENROUTER_API_KEY` is the fallback. Used as a swatch fallback; Randall chat does not read it. |

**Provider.** Randall chat and image generation go through OpenRouter on the Patreon-provisioned request key. Per-request keys for image generation win over the stored key. There is no local model engine.

## Data Randall writes

All under `config.STORAGE_PATH` (`<project>/storage` in dev) unless noted.

| Path | What |
|---|---|
| `assistant/chats.db` | Assistant chats and pending queued inputs. |
| `assistant/files/`, `assistant/previews/` | Attached and derived files under opaque UUIDs; preview PNGs. Also `assistant/models/` (read by chat reports). |
| `assistant/tasks/tasks.db`, `tasks/artifacts/<task>/`, `tasks/traces/` | The task journal, per-task artifacts, exported JSONL traces. |
| `assistant/settings.json` | "My game" destinations (absolute paths stay here, never sent to the model). |
| `assistant/deliveries/` | Delivery receipts. |
| `assistant/game-tests/<session>.json` | Chat ownership and terminal receipts of play sessions. |
| `assistant/chat_reports/` | Frozen report ZIPs and `submissions.db`. |
| `model_imports/<id>/` | Model-import projects (see workflow 1). |
| `openrouter.key` | aiengine keystore: the user's own key. |
| `nucleome.db` | Coach chats and the coach profile (with the rest of Tracker's index). |

Chat history never contains keys, encoded images or executable tool history.

## Module map

Backend, `app/backend/`:

| Path | One line |
|---|---|
| `randall/` | One folder per job; [`randall/README.md`](../../app/backend/randall/README.md) is the index. `assistant/` registers the tools of the pipeline packages and reads `reports/`; the pipeline packages import `assistant/` helpers but never the turn loop (`engine.py`). Reorganised 2026-10-03: tool names, schemas, prompts, cards, URLs, DB names and storage paths did not change; logger names follow the module paths. |
| `randall/assistant/` | The chat itself: `engine.py` (the turn loop: routing, budgets, the task each turn runs under; "How a turn is routed"), `live_runs.py` (live runs, queued inputs, approvals, the SSE stream), `main_model.py` (the streamed main-model request and the models a run pins: `FAST_LANE_MODEL`), `prompt.py` (the system prompt), `tool_stage.py` (one tool call as a journalled stage), `turn_facts.py` (a turn's pinned task, budget family and outcome), `tools.py` (the tool registry: every schema and the dispatch), `refusals.py` (a refused or failed tool call as the result the model and the card read), `recipes.py` (task cards and routing), `approvals.py` (grants and the `PreparedCall` they bind), `store.py` (chats.db), `compaction.py`, `continuity.py` (working state from receipts), `app_context.py`, `capabilities.py`, `vision.py`. Shared by the pipelines: `mod_files.py` (chat file handles), `hsdraw.py` (HSDRaw operations and `save_mod_copy`), `stage_scene.py` (stage scenery operations), `vault_items.py` (vault rows as tools read and show them), `clone_character.py`. |
| `randall/assistant/tasks/` | The task journal: contracts, coordinator (task context and traced model requests; `content_hash.py`, `stage_journal.py` for stages and tool journaling), events, SQLite store. |
| `randall/recolor/` | Recolor a costume and recolor a stage ([README](../../app/backend/randall/recolor/README.md)): `workflows.py` (the costume recolor workflow: acquire, prepare, create and review), `skin_lab.py`, `texture_inspection.py`, `materials.py`, `texture_material.py`, `swatch_library.py`, `vanilla.py` (stock costumes as working files), `stage_lab.py` (the Stage Lab and its stage list), `stage_start.py` (a stage recolor chat's start: code opens the picked stage), `lab_common.py` (what both labs share: the session lookup, greyscale slots, per-texture colour edits, the cached UV layout), `model_colours.py` (colour in no texture, vertex colours and colour keys, edited the same way in both labs) with each lab's side in `stage_colours.py` and `costume_colours.py`. |
| `randall/create_character/` | Create a character: not built; a README only (what it will be, model import as step one, the owner's open questions). |
| `randall/stage_import/` | Import a stage model: not built; a README only (what it will be, the owner's open questions). |
| `randall/model_import/chat/` | The model import in chat ([README](../../app/backend/randall/model_import/README.md)): `studio_import.py` (import turns, the roster and card, the picked fighter, running `import_model`, pictures, the ledger), `import_job.py` (the job: rigswap as a subprocess, the fighter it goes on or picks, Stop, the reply, the vault save), `attached_model.py` (an attached model waiting to be imported), `textures.py` (the texture files a model names, looked for before rigswap runs). |
| `randall/website/` | Find and download mods: `website.py` (approval-bound downloads and imports), `website_search.py`, `website_posts.py` (posts, cards, likes), `website_exports.py`, `website_scope.py`, `website_receipts.py`, `website_bulk.py`, `website_quarantine.py`, `website_safety.py`, `website_artwork.py`, `website_protocol.py`, `vault_presence.py` (which downloads are in the vault). |
| `randall/delivery/` | Put a result in the game: `projects.py` (project tools), `destination.py` ("My game"), `deliver.py` (+ `deliver_policy`, `deliver_project`, `deliver_receipts`, `deliver_steps`, `deliver_checks`, `deliver_replies`), `game_tests.py` (play sessions and the automated check). |
| `randall/reports/` | What Randall sends to the developer: `chat_report.py`, `chat_report_files.py` ("Report this chat"); `wishes.py`, the public wish API over `wish_gate`, `wish_evidence`, `wish_keys`, `wish_ledger`, `wish_text`, `wish_submit` (capability gaps recorded locally, sent only on the user's word); `report_transport.py` (the bug-report worker's two-stage create/upload transport both share; the worker URL comes from `shared/diagnostics/bug_report.py`). |
| `randall/routes/` | `assistant_bp.py` (`/api/assistant`), `chat_reports.py`, `wishes.py`, `coach.py` (the coach's `/api/nucleome/coach/*`, on the Tracker blueprint). |
| `randall/model_import/` | The model import: `chat/` (above), `studio/finish.py` (the vault save) and `studio/slippi.py` (the Slippi check). The v4 engine (`workflow/`, the studio stages, the geometry modules) was deleted 2026-11-03; the tag `archive/v4-importer` marks the last commit with it. |
| `randall/coach/` | `coach_api.py` (SSE loop), `coach_tools_v2.py` (tool registry and schemas), `coach_tools_stats.py`, `coach_tools_corpus.py`, `coach_tools_combos.py`, `coach_tools_games.py` and `coach_tools_live.py` (tools), `coach_data.py` (packs, profile, glossaries), `coach_prompt.py`, `coach_runner.py` (vendored OpenRouter plumbing), `coach_store.py`, `coach_profile.py`. |
| `shared/modellab/` | The fighter table the model import reads (`fighter_catalog.py`: the app's fighter names and Pl codes). The rest went with the v4 importer. |
| `shared/aiengine/` | The shared runtime (above). |
| `tracker/` (read by the coach) | `store/` (`indexer`, `identity`, `game_trace`, `slippi_rank`), `stats/` (`aggregate`, `deep_stats`, vendored `analyzer` + `pack_math`), `video/` (`clip_refs`, `interactions`), and the packs in `baselines/`. |
| `eval/corpus/randall_tasks/` | The Randall task evaluation harness (`tests/backend/test_eval_randall_tasks.py`). |

Frontend, `app/frontend/src/`:

| Path | One line |
|---|---|
| `randall/assistant/` | The panel: `AssistantPanel.jsx`, the composer and the starting points (`Composer`, `TaskPicker`, `StartPicker`, `pickPopover.js`, `startPick.js`), task cards (`TaskCards`), tool cards (vault, website, project, stage, game test, studio), approval and download dialogs, `WorkbenchPanel` and `WorkbenchViewer`, `stream.js` (SSE), `transcript.js`, `activity.js`. |
| `randall/chat/` | `ChatUI.jsx` (shell shared by assistant and coach), `ChatReportModal.jsx`, `chatReport.js`, `visibleText.js`. |
| `randall/coach/` | `CoachPage.jsx`, `coachAnswer.jsx` (markdown answers with inline clip tokens, the clip reel), `CoachIndicators.jsx` and `ProfileCard.jsx` (the coach profile, "Randall's memory"). |
| `shared/lib/EditorContext.js` | The Texture Lab link: one mounted conversation follows the user into the Skin and Stage Creator (`vault/editors/`). |

### Starting-point pickers

Frontend only (2026-10-03; laid out as the Claude app's new chat 2026-10-04). Everything is in the composer
(`randall/assistant/Composer.jsx`): one box, the textarea on top and a control row inside it (attach, the task
pill, the starting pick; send at the right; `ChatInput`'s `controls`, the stacked layout; the coach keeps the
one-row box).

- **New chat.** An empty chat (`AssistantPanel` `startScreen`: not loading, no messages) puts the bar in the
  middle of the page (`.coach-inputarea.is-start`: still bottom-anchored, at `calc(50% - 64px)`, so rows added
  above the box grow upward), with Randall and "What are we making today?" over the box and the starting
  points as chips under it (`TaskPicker.StartChips`, one per `status.tasks` row, in its order): a row per
  `group` with the group's name in a small column at the left (above the chips when the panel is narrower
  than 860px). Characters: "Retexture a costume", "Import a character model", "Create a character". Stages:
  "Retexture a stage", "Import a stage model". The two stubs are `available: false`: a dashed chip that is not
  a button (not focusable, nothing to press) with its icon, label and a "Use MCP" tag, which a screen
  reader reads with the rest. Greeting and chips are out of the bar's flow, so nothing about choosing moves
  the box. The first message turns the chat into a transcript and the bar glides to the bottom (280ms, none
  with reduced motion). A remembered chat opens as loading (bar at the bottom), so the bar never glides on launch.
- **A workflow chosen** (a chip, the pill's menu, or a sidebar row: all three are `pickTask`/`newChat(id)`,
  the same state): nothing appears in the page. The chips fade out (`is-away`, `inert`, still mounted) and the
  control row shows the task pill and, for a task whose row names a `picker`, the pick control
  (`StartPicker.StartPickControl`): "Choose costume" / "Choose fighter" / "Choose stage", then the pick's
  thumbnail and name ("Fox · Blue Hoodie", "Marth", "Battlefield · Night Sky") with × to clear. Focus goes to
  the message box. The pill's menu (`TaskPill`) lists Ask (a plain chat: the chips come back), then every
  starting point under its group, the stubs `aria-disabled` with "Use MCP" (reachable with the arrows,
  nothing happens on them). A narrow panel (under 480px) shows the pill as its icon only while a pick control
  shares the row. The pick is optional: typing the costume, fighter or stage still works, and nothing blocks
  sending. The sidebar rows and "Start another" list only the startable rows (`taskModes.startableTasks`).
- **AI Choice** (fighter picker only, first tile; `costumePicks.aiPick`, `{kind:'fighter', auto:true, character:''}`):
  "let Randall pick the fighter". It sends NO `fighter` (the context is byte-identical to no pick), the control
  reads "AI Choice" with a "?" tile, the placeholder "Attach a model. Randall picks the fighter.", no sent note.
  Searchable by ai/random/auto/choice. The tile is drawn (`GalleryGrid` `glyph`): Melee has no random icon and
  first-run setup extracts no locked-slot icon from the ISO.
- **The popover.** The pick control opens the picker in a non-modal `role="dialog"` anchored to the composer
  box (the stacked box is positioned; the control is not), at its left edge, as wide as the box up to 520px,
  above or below it by `pickPopover.popoverPlacement` (GallerySelect's rule: below unless under 320px there and
  more above; height what that side leaves inside the chat page, at most 60% of the window; the grid scrolls
  inside). It closes on a pick (focus to the message box), on Escape once the picker has no step to go back
  to, on a press outside (GallerySelect's `mousedown` check), or when focus moves outside it; those return
  focus to the control. Arrow keys open it from the control. Enter in its search box picks the first match,
  and an empty search swallows Enter: the popover sits in the message form, so it must never send the message.
- **Pickers.** `vault/picker/CostumePicker.jsx`: the Tracker's watch-with-mods grid (`shared/ui/GalleryGrid`,
  which `GallerySelect` renders unchanged), filling the popover. `picker: 'costume'` picks a fighter (26, with vault counts),
  then one of its vault costumes or stock colour slots (`GET /api/mex/vanilla/costumes/<fighter>`, badged
  "Stock"; an empty vault says so and offers the stock ones). `picker: 'fighter'` picks a fighter only, from
  `/status` `import_fighters` (no Ice Climbers). `vault/picker/StagePicker.jsx` (`picker: 'stage'`, the same
  card, grid and keyboard model; pure helpers in `stagePicks.js`) picks a stage from `/status`
  `recolor_stages` (pictured by `art`: the full stage art for the six tournament stages, the stage-select icon
  for the rest; badged with its vault variant count), then one of its vault variants (the Vault's own list,
  `GET /api/mex/das/storage/variants`, pictured by `screenshotUrl` when it has one) or the stock stage (badged
  "Stock"). Arrow keys move, Enter picks, Escape goes back a step (`GalleryGrid.searchBoxKeys` from the
  search box); thumbnails load lazily.
- **After the pick.** The pick control shows it and the placeholder names it ("What look do you want for Fox ·
  Blue Hoodie?"). A costume or stage pick clears skins attached to the composer (`choosePick`), so the "N skins
  attached" row and the pick never show the same thing.
- **What is sent** (`randall/assistant/startPick.js`, first message only, with `task`): a vault costume
  appends `{id, character, name}` to `context.selection` (the Vault selection's shape); a stock slot appends
  `{character, vanilla: true, color, name}` (no `id`); a fighter is `context.fighter` (`'Fox'`); a stage is the
  single `selection` entry `{kind: 'stage', stage, id, name}` or `{kind: 'stage', stage, vanilla: true, name}`
  (skins attached to the composer are set aside, as for a costume). The sent message shows them as notes
  ("Fox · Blue Hoodie", "For Marth", "Battlefield · Night Sky").
- **Backend.** `assistant_bp` whitelists `fighter` (`CONTEXT_FIELDS`): an import fighter by the roster's own
  name (any case; `Captain Falcon` -> `C. Falcon`) is kept, anything else is dropped silently, like an
  unknown `task`. `/status` serves the same list as `import_fighters` (`assistant_bp.import_fighters`:
  the fighters rigswap targets, `import_job.fighters`: every fighter but the Ice Climbers). A stage entry is checked by `assistant_bp._stage_item`
  against `recolor_stages` and the vault (see "Picker contracts").
- **Old chats.** A chat stored under a retired task id (`find_mod`, `menu_background`), or under a stub
  (`stage_import`, `create_character`, which no request can start), has no label, pill, badge or follow-up in this build and reads
  as a normal chat.
- **After a stage recolor.** "Start another" appears under the reply whose `stage_lab` call saved a variant
  (`taskModes.TERMINAL_TOOLS.recolor_stage`: a `stage_lab` receipt with `action: 'save'` or a `variantId`;
  any other Stage Lab call is a step). There is no same-chat follow-up chip: a stage cannot be delivered.
- **History sidebar.** `ChatSidebar` (`randall/chat/ChatUI.jsx`, both surfaces) follows the Claude desktop
  layout: sidebar toggle, search (titles of the loaded chats, in the page), "+ New" and the three startable
  starting points as rows (the stub is left out: a disabled row reads poorly at 288px), one-line chats under
  date headings (`chatList.js`), a status dot (the open chat only: running, or its last reply failed), the
  task in the row's tooltip, "Show N more", and the account footer.
- **Tests.** `GallerySelect.test.js` (the Tracker markup against the pre-move capture), `CostumePicker.test.js`,
  `costumePicks.test.js`, `StagePicker.test.js`, `stagePicks.test.js`, `startPick.test.js` (the exact context
  JSON), `Composer.test.js` (the new chat, a workflow chosen, a sent chat, old task ids), `TaskPicker.test.js`
  (the chips with the stubs, the pill and its menu), `StartPicker.test.js` (the pick control and popover: keys,
  pick, clear, close), `pickPopover.test.js`, `taskModes.test.js`, `chatList.test.js`, `ChatSidebar.test.js`; backend
  `test_assistant_bp_fighter_context.py`, `test_assistant_stage_recolor.py` (status, the stub, the stage
  selection, code opening the picked stage).

## Tests

Backend (`tests/backend/`): `test_assistant*.py` (45 files: approvals, downloads, clone character,
game tests, import job, inputs, materials, mod files, projects, skin lab, stage scene, stage
recolor, studio import, task coordinator and store, texture, website, workflows and more), `test_deliver_to_game.py`,
`test_real_delivery_activation_restart_and_undo.py`, `test_wishes.py`, `test_chat_reports.py`,
`test_no_retired_model_import.py`, `test_coach_loop.py`,
`test_coach_runner_store.py`, `test_singularity_coach.py`, `test_fast_lane.py`,
`test_decisions.py`, `test_eval_randall_tasks.py`, and the gate tests `test_gates.py` (table versus
`main.js`) and `test_preview_policy.py` (preview environment versus `main.js` and `PREVIEW-0.9.0.md`).

Frontend: `node --test` `*.test.js` beside the components in `randall/assistant/` and `randall/chat/`.

## History

Randall has had four generations. Do not rebuild the first three; their code is archived and the
history is on GitHub.

| Generation | What it was | Removed | Archive |
|---|---|---|---|
| Randall MCP (standalone) | An external agent connected to local Nucleus tools (`docs/RANDALL_MCP.md`, `MCP_DEVELOPMENT_SETUP.md`, the `NUCLEUS_AGENT` gate). | 2026-10-02 (cleanup-2026-10 2.2) | Docs only, in git history. |
| `randall/agent_bridge` | The in-app side of that MCP: session ownership, schema validation, broader native tools. 11 files. | 2026-10-02 (2.1) | `ssbmNucleus-archive\agent_bridge.zip` |
| `randall/sandbox` and `randall/scriptlane` | A scripted-edit lane, built but unwired, excluded from the installer. 73 files. | 2026-10-02 (2.3) | `ssbmNucleus-archive\sandbox.zip`, `scriptlane.zip` |
| Model Studio | The AI Model Studio (`blueprints/model_lab.py`, the storage modal, `scripts/modellab/`). Its shared helpers moved to `backend/shared/modellab/`. | 2026-10-02 (2.4) | `ssbmNucleus-archive\scripts-modellab.zip`; the write-up is in git history before 2026-10-03 |
| The old model-fit tools (`model_fit`, `model_mesh`, `model_revise`, `model_candidate`, `model_physics`) | The v1/v2 assistant model import, replaced by the one `import_model` job (v4). | earlier | Plans: retired docs, in git history before 2026-10-03 |
| The v4 model import | The scripted studio import (`model_import/workflow/`, the studio stages, the geometry modules, all of `shared/modellab/` but the fighter table, `eval/model_import/`), which `import_model` ran until rigswap replaced it on 2026-10-29. | 2026-11-03 | Tag `archive/v4-importer` |
| AI Skin/Stage Studio (gate `ai_lab`) + local diffusion/Ollama engine | The Settings AI Studio cards, the "New AI skin"/"New AI stage" buttons and modals, the REST skin-lab and stage-lab routes, and the local diffusion + Ollama engine stack. Randall's recolor never used them. | 2026-10-04 | `ssbmNucleus-archive\ai-studio.zip` |

The four retired Randall docs (assistant reference, contract, workflow inventory, chat reports) are
in git history before 2026-10-03. They describe the earlier
generations and a September 2026 planning snapshot; use them as history only.

## Where this corrects older docs

- `ASSISTANT.md` listed `model_fit`, `model_mesh`, `model_revise`, `model_candidate`, `model_physics` as
  assistant tools. `tools.py` registers none of them; model import is the single `import_model` job.
- `ASSISTANT.md` described `workflows.py` as "the first workflow" with future ones planned. Only the
  recolor lane exists; the task catalog (`recipes.LAUNCHABLE`) is the real workflow list.
- `app/CLAUDE.md` called `model_import/` "the v3 import", later "the v4 model import". The import is rigswap, run by
  `model_import/chat/import_job.py`; the v4 driver is deleted.
- `COACH_BASELINES.md` lists 12 coach tools and `research/README.md` says 16; `coach_tools_v2.TOOLS`
  has 30.
- `coach_chat` still defaults the legacy `mode` field to `"playbook"`; `stream_chat` maps every mode to
  the one stats-only variant.
- `aiengine` is not a local model runtime (that was removed 2026-10-04): it is the image engine plus the shared
  fast lane, the per-turn decision, key store and upload helpers.
- `RANDALL_CONTRACT.md` and `RANDALL_WORKFLOWS.md` described an MCP surface and an artist mode as Randall
  surfaces; both are gone (MCP) or developer-only (`eval/`).
