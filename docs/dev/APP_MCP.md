# Nucleus as an MCP server (the user's own AI)

SSBM Nucleus serves Randall's tools over MCP, so a person with only the installed app can connect Claude Code,
Claude Desktop or Codex and let that AI work on their vault, website downloads and builds. This is a product
surface. The private developer harness `melee-harness` (`tools/harness/harness_mcp.py`, [MCP_SERVER.md](MCP_SERVER.md))
is a different server; the app only forwards two of its tools (below).

It ships with the assistant (`NUCLEUS_ASSISTANT`, the `randall` package): in every build since 0.9.0, stable
included. A build that holds the assistant back (ARCHITECTURE §7) keeps the endpoint and answers every request
with a clear JSON-RPC error.

## Pieces

| Piece | File | What it does |
|---|---|---|
| Endpoint | `app/backend/shared/routes/mcp.py` (`mcp_bp`) | `POST /api/mcp`: one JSON-RPC 2.0 message in, plain JSON out (streamable HTTP without SSE; 202 and no body for notifications and client responses). GET/DELETE answer 405. The backend token (`X-Nucleus-Token`) is checked like every `/api/` route. Assistant off: error `-32001` "This build of SSBM Nucleus has the assistant switched off ...". Always registered; imports `randall.mcp` only behind `gates.enabled('assistant')`. |
| Server | `app/backend/randall/mcp/server.py` | `initialize` (echoes 2024-11-05, 2025-03-26 or 2025-06-18, else 2025-06-18; serverInfo `ssbm-nucleus`; capabilities.tools; instructions), `ping`, `tools/list`, `tools/call`. A tool failure is an `isError` result, never a 500. |
| Randall's tools | `randall/mcp/randall_tools.py` | `tools.REGISTRY` ∩ `tools.SCHEMAS`, same descriptions and parameters, through `tools.prepare` and `tools.execute`. |
| Model import | `randall/mcp/model_jobs.py`, `randall/model_import/chat/ask_checks.py` | `import_model`, `fix_import`, `job_status`, `answer_import`, `cancel_import` over `core.jobs` jobs (kind `mcp_model_import`); the caller answers rigswap's AI asks. |
| Import chip | `app/frontend/src/randall/assistant/McpImportChip.jsx`, `mcpImport.js` | While an `mcp_model_import` job runs, a chip in the app header (and in the fullscreen skin editor's header, which hides it) says what the AI is importing, with Cancel (below). App.jsx reads the vault again when one ends with a costume saved. |
| Collection and builds | `randall/mcp/build_tools.py`, `menu_grid.py` | The app's own Import, Install, music and Export buttons: each tool runs the route handler behind its button in-process, pinned to the build named (below). `menu_grid.py` is the window's select-screen re-fit, ported. |
| Slow calls | `randall/mcp/calls.py` | A call not done within 45 s is answered with `{job_id: "call-...", status: "running"}`; `job_status` returns its result later (kept 1 h, newest 64). |
| Images | `randall/mcp/content.py` | Pictures a tool makes (portraits, Skin/Stage Lab renders, vault skin cards, at most 8) go out as MCP `image` content beside the JSON text. |
| Creation toolkit gateway | `randall/mcp/toolkit.py`, `toolkit_schemas.py` | `native_port` and `stage_workbench`, forwarded to a source checkout (below). |
| Vault refresh | `randall/mcp/window.py` (`vault_changed`), `randall_tools.call`, `build_tools.call`, `app/frontend/src/randall/assistant/mcpImport.js` (`useMcpVaultChanged`) | Any other tool whose reply says `vault_changed` (a Stage Lab or Skin Lab save, a website download, an imported file) emits `mcp_vault_changed` on Socket.IO, and App.jsx reads the vault again, as after the same tool in Randall's chat. Before 0.9.0 only model imports did, so a stage the AI saved showed after a window reload. |
| Window questions | `randall/mcp/window.py` (`confirm`), `GET`/`POST /api/mcp/window/confirmations[/<id>]`, `app/frontend/src/randall/assistant/mcpAccount.js` (`createMcpConfirmWatcher`) | A question only the person in the app may answer (below: connecting a creation toolkit). The backend posts it, emits `mcp_confirm` on Socket.IO and waits; App.jsx shows it with `appConfirm` (Allow / Deny) and sends the answer. Both routes need the window-only key `X-Nucleus-UI-Key` (`core/ui_channel.py`, the same check as the build-change approval card), so the AI client, holding only the backend token, can neither read nor answer one. |
| Network paths | `core/path_safety.py` (`is_network_path`, `local_path`), `server.call_tool` | No argument of any tool may be a network path (`\\host\share`, `\\host@SSL\...`, `\\?\UNC\...`, `\\.\...`, the NT namespace `\??\...`, `//host/...`, `file://host/...`, with either slash): `call_tool` refuses it before the tool runs, since opening one offers the user's NTLM hash to that host and running a program from one runs the host's code. `attach_file`, `import_to_vault`, `import_model`, `save_build_iso`, `test_in_game`'s ISO and Dolphin paths, the toolkit folder (also a saved one, and the pictures its results name) and the window's Dolphin folder go through the request-path gate `local_path` themselves: a drive-letter absolute path (a POSIX absolute path off Windows), nothing relative. A mapped drive letter is allowed. The HTTP routes use the same gate: `app.py` refuses a request whose JSON, form or query string has a path key (`path_safety.REQUEST_PATH_KEYS`: `slippiPath`, `vanillaIsoPath`, `isoPath`, `kitPath`, `gccBin`, `destination`, ...) that fails it, with 400 `not_a_local_path`. |
| Discovery file | `app/electron/mcp/discovery.js` | `<userData>/mcp-endpoint.json` = `{"url":"http://127.0.0.1:<port>/api/mcp","token":"<backend token>","pid":<main pid>}`, written by `main.js` once the backend is up, removed on quit (by the process that wrote it). userData is per user. `NUCLEUS_MCP_DISCOVERY` moves it (tests). |
| Relay | `app/electron/mcp/relay.js` | `SSBM Nucleus.exe --mcp`, handled at the top of `main.js` before the single-instance lock, windows and updater. The Electron process only finds the discovery file and runs `relay.js` again as a plain Node process (`ELECTRON_RUN_AS_NODE=1`, stdio inherited), then exits with it: on Windows the Electron browser process cannot read stdin (its `process.stdin` ends at once). The relay is a stdio MCP server: newline JSON-RPC in, POSTed with the token, one JSON line out; notifications get nothing back. No app running (no file, or its pid is dead): it starts the same exe without `--mcp` (on Linux the AppImage file, not the relay's own mount: `shell/stable-executable.js`), detached, and waits up to 90 s for the file; if none comes every request gets `-32002` "SSBM Nucleus is not running ... Open SSBM Nucleus". Connection refused or 401 (the app restarted): it finds the new endpoint. Console output goes to stderr; only JSON-RPC reaches stdout. Exits when stdin closes. `NUCLEUS_MCP_NO_LAUNCH=1` turns the auto-start off. |
| AI usage | `randall/mcp/credits.py`, `POST /api/mcp/account`, `app/frontend/src/randall/assistant/mcpAccount.js` | Whose usage AI calls spend: the signed-in person's, as in the chat (below). |
| Settings card | `app/frontend/src/settings/McpSection.jsx` (+ `mcpCommands.js`) | Settings > AI > "Connect your own AI (MCP)", only when `ASSISTANT_ENABLED`. Copyable commands from `window.electron.getMcpLaunch()` (`mcp:launch` in `electron/ipc/system.js`: the app's own executable, plus the app folder in a checkout). On Linux that is the AppImage file (`$APPIMAGE`), never `process.execPath`, which inside an AppImage is its `/tmp/.mount_*` FUSE mount and is gone when the app quits (`electron/shell/stable-executable.js`); a macOS `.app` gives the binary inside the bundle. |
| Problem reports | `randall/mcp/report_tools.py`, `randall/reports/problem_report.py`, `GET /api/mcp/window/problem-reports`, `POST .../<id>/review`, `POST .../<id>/discard`, `app/frontend/src/randall/assistant/McpProblemReports.jsx`, `problemReport.js` | `report_problem` assembles a report for the developer on this computer and sends nothing; the person reads it in the window, ticks what goes, and sends it through "Report this chat"'s own submit, or discards it (below). |
| Frozen build | `tools/build/mex_backend.spec` | `collect_submodules('randall.mcp')` under `ASSISTANT_SHIPS`. Nothing imports `tools/`. |

## Connecting

Installed (the card shows these with the real path):

```
claude mcp add --scope user nucleus -- "C:\Users\<you>\AppData\Local\Programs\SSBM Nucleus\SSBM Nucleus.exe" --mcp
codex mcp add nucleus -- "C:\...\SSBM Nucleus.exe" --mcp
```

`--scope user` makes it available in every Claude Code project (the default scope is the current folder only).
Claude Desktop, `claude_desktop_config.json` (Settings > Developer > Edit Config):

```json
{"mcpServers": {"nucleus": {"command": "C:\\...\\SSBM Nucleus.exe", "args": ["--mcp"]}}}
```

From a checkout: `app/node_modules/electron/dist/electron.exe <checkout>/app --mcp`. Talking to the endpoint
directly (no relay): POST to the discovery file's `url` with `X-Nucleus-Token: <token>`.

The AI client starts the relay when it starts, and the relay starts Nucleus if it is not running, so opening
Claude Desktop opens Nucleus. A cold start can be longer than a client's connect timeout (Claude Code:
`MCP_TIMEOUT`); the client then shows the server as failed until it reconnects.

Electron's browser process writes one empty line (CRLF) to stdout on Windows as it starts, before any app code
runs (Electron 44.10.2; no flag or `ELECTRON_NO_ATTACH_CONSOLE` changes it). So a client reading `--mcp` sees one
blank line before the first JSON-RPC message. The MCP TypeScript SDK's stdio client (1.25.2, checked live against
`--mcp`) passes it to its error handler ("Unexpected end of JSON input") and goes on; other clients (Codex) were
not checked. Starting the relay without the browser process avoids it:
`ELECTRON_RUN_AS_NODE=1 "<exe>" "<resources>\app.asar\electron\mcp\relay.js"` runs the relay directly (Node mode
reads scripts inside app.asar), but then `NUCLEUS_MCP_RELAY_FILE` must name the discovery file, since only the
Electron process knows userData.

That browser process shows nothing, but Chromium in it still started a GPU process and opened its disk caches in
the session folder, which is the running app's userData: the 0.9.0 smoke test's relay printed "Unable to move the
cache: Access is denied" and "Gpu Cache Creation failed: -2" to the client's stderr. Before ready,
`relay.quietChromium` turns off hardware acceleration, the GPU, the shader and HTTP caches, and points
`sessionData` at a folder of the relay's own, `%TEMP%\ssbm-nucleus-mcp\<pid>` (userData, where the discovery file
is, stays the app's). Chromium still holds that folder as the relay exits, so each relay sweeps the folders of
relays that have ended (`tests/electron/mcp-relay.test.js`; checked live 11-19: two dev relays at once on one
userData, stderr empty).

## Tools

`tools/list` gives 60 tools (annotations in brackets: RO read-only, D destructive, W open world).

Randall's: `search_vault` [RO], `inspect_mod` [RO], `present_vault_skins` [RO], `search_docs` [RO],
`search_website_mods` [RO W], `inspect_website_mod` [RO W], `download_website_mod` [W, approval],
`download_website_mods` [W, approval], `list_projects` [RO], `inspect_project` [RO], `create_project` [approval],
`install_project_mods` [D, approval], `preview_portrait`, `organize_skins` [D, approval], `generate_material` [W],
`skin_material`, `skin_lab_open`, `skin_lab`, `stage_lab_open`, `stage_lab`, `hsdraw_capabilities` [RO],
`open_vault_file`, `open_vanilla_file`, `inspect_mod_file` [RO], `unpack_mod_file`, `hsdraw`, `save_mod_copy`,
`test_in_game`, `create_clone_character`, `deliver_to_game` [D, approval], `undo_delivery` [D].

MCP-only: `undo_organization` [D] (the Undo button on an organize card), `attach_file` (an absolute file path
becomes a chat file id, what dropping a file in the chat does), `import_model` [W], `fix_import` [W],
`job_status` [RO], `answer_import`, `cancel_import`, `search_vault_stages` [RO] (the vault's stage skins by stage with their `variant_id`s, and
every stage code: what the chat's stage picker gives it; `search_vault` is costumes only), `game_screenshot`
[RO] (a picture of a running `test_in_game` play session's own Dolphin window, by its session_id: the chat
shows that session in its panel instead), `native_port`,
`stage_workbench`, `toolkit_tools` [RO], `toolkit_call` [W], `connect_creation_toolkit`, `creation_toolkit_status`
[RO], `report_problem` (a report the user sends from the window, below; the call sends nothing),
`problem_report_status` [RO].

Collection and builds (MCP-only, below): `import_to_vault`, `search_vault_mods` [RO], `install_stage_skin` [D],
`install_custom_characters` [D], `install_custom_stages` [D], `install_extra` [D], `inspect_project_stages` [RO],
`get_music_playlist` [RO], `set_music_playlist` [D], `add_music_track`, `export_build`, `save_build_iso` [D].

Not offered: `set_website_mod_like` (needs the account sign-in only the window holds; the chat hides it too
without one).

MCP-only arguments for what the chat takes from the window: `choice` on `download_website_mod(s)` (`fix` or
`import_as_is`) and `slippi` on `download_website_mod`; `vanilla_iso_path` on `test_in_game` (defaults to the
one the backend knows). The Dolphin `test_in_game` starts is never an argument (security review 11-19, M1): it is
the folder set in Settings, which the window mirrors to `POST /api/mcp/window {"slippi_dolphin_path": ...}` at
launch and when Settings changes it (a network path is refused; the route needs the window-only key, so the AI
client cannot name a folder itself), else Slippi Launcher's own `netplay` folder
(`randall/mcp/window.py`). `test_in_game`
notes say the game opens in its own Dolphin window, not "the panel on the right". A few descriptions get an `[MCP]` note:
`stage_lab_open` lists the legal stage codes, and `stage_lab` says how to read identify's `area` (largest
share over two views; go by the game camera for what a player sees), that a spot with no id is one the id picture
cannot read (FD's sky is vertex colours under fog and additive blending), not one with nothing to edit, and to
check the render before describing it (the 11-18 user test recolored FD's side walls and called the sky purple).

`stage_lab` takes the argument shapes a client sends one step from its own (while filming 0.9.0 an AI's three
`recolor` calls were all refused for their shape, and the error did not say which one it wants). Before the call
is checked, `tools.prepare` runs `tools.reshape` over the schema (`tools.RESHAPE`, `stage_lab` only): a JSON
string where an object, list, number or boolean goes is decoded (`"edits": "[{...}]"`, `"camera": "{...}"`), one
item where a list goes is wrapped (one edit object, `texture_indices: 4`, one `[x, y]` point), and a one-item list
where one whole number goes is unwrapped (`texture_index: [3]`). Then `stage_lab.recolor_args`: a `recolor` with
its colour at the top level for several textures (`texture_indices`, or a list in `texture_index`; before this it
silently recolored the whole stage), or with an edit's own fields beside one `texture_index` (`set_hue`,
`set_saturation`, `mask`), becomes one edit per texture, and an edit naming `texture_indices` is split the same
way. A material colour (`set_material`, and its `apply` kind) also takes `#rrggbb` and `[r, g, b]`, which keep the
field's own alpha, and `[r, g, b, a]` (`materials.rgba_hex`). What is still wrong is refused with the shape the
action takes and an example (`stage_lab.RECOLOR_SHAPE` / `APPLY_SHAPE`, also added to `prepare`'s
unknown-parameter refusal), and the schema says it too: the `recolor` line of the description, and the `edits`,
`texture_index`, `texture_indices` and `value` parameters (`tests/backend/test_stage_lab_shapes.py`).

The chat's own words that are wrong over MCP are replaced in `tools/list` (`randall_tools.REWORD` and
`PARAM_REWORD`; a test checks each old text is still in the chat's schema): `skin_lab`/`stage_lab`'s `name` and
`save_mod_copy` say a result is saved "when the turn ends" (there are no turns: over MCP a Skin Lab result is
exported and passed to `save_mod_copy`, a Stage Lab one is kept with `action=save`; the preview.36 test AI
trusted the parameter and saved nothing), and `test_in_game` says not to poll and that it cannot see the game.
Over MCP `test_in_game action=status` takes `wait_seconds` (at most 40, under the 45 s call limit): it repeats
the status, outside the turn lock, until the session plays or ends. `job_status` with a play session's id does
the same (`randall_tools.is_game_session`/`game_status`), since that is where a client waits for everything
else.

### Approval mapping

In the app an approval tool (`download_website_mod`, `download_website_mods`, `create_project`,
`install_project_mods`, `organize_skins`, `deliver_to_game`) shows a preview card and runs after the click. An MCP
client asks its user before each tool call, and that ask is the approval: the call is prepared and applied in one
go through the card's own path (`tools.prepare` -> `approvals.Grant(fingerprint, choice)` -> `tools.execute`).
`choice` picks one of the card's options (default: the option the card preselects; an option the card does not
offer is refused). The result carries `approved` (`title`, `description`, `question`, `consequence`, and `choice`
and `offered` when the card had options). A website download's safety review is answered "approved" with the
chosen action, as a click would.

### Jobs

- `import_model {source, fighter?, name?, untextured?}`: `source` is an absolute path to a model file on this computer: a
  .zip, or a file the importer reads (`import_job.SOURCES`: the chat's model kinds from `shared/mod_files.py`,
  FBX included, but not SMD). It checks the file, then the model import tools: a packaged app whose tools (Blender
  and rigswap's Python, a download in Settings > AI > Model import tools) are missing, downloading or out
  of date answers at once, not `isError`, with `{status: 'needs_tools', tools: {state, download_bytes, needed_bytes,
  disk_bytes}, warning, next}` (`next` gives the size and this platform's sources, the Settings card's:
  python-build-standalone on macOS and Linux), starts nothing and never downloads them itself (`fix_import` too). Then the
  importer's setup, then the texture files the model names
  (beside it, or in its ZIP: `chat/textures.missing`); some missing answers at once, not `isError`, with
  `{status: 'needs_textures', textures, warning, next}` and starts nothing, unless the call has `untextured: true`
  (the user said to go on without them). Otherwise it starts a `mcp_model_import` job (one at a time) and returns its
  `job_id`. `fix_import {project, change, said?, name?}` starts a fix of a finished import. `job_status {job_id}`
  gives status, progress, the project id and the result (with pictures); failed and interrupted jobs are
  `isError`. `job_status` long-polls: it waits up to `wait_seconds` (default 25, at most 50) for a running job
  to end, so a client with no sleep tool just calls it again (the 11-18 user test: a `claude -p` run quit while
  waiting, and the rerun polled in a tight loop). A done job's `result.next` is reworded for MCP
  (`model_jobs.mcp_next`: no card above the reply; a change is `fix_import`).
- The importer's AI asks are the caller's to answer (owner 11-18: "randall should just be for randall in the
  app"). The job hands rigswap a relay folder (`import_job.RELAY_ENV` = `RIGSWAP_ASK_RELAY`, a temp folder that
  goes with the job) and no OpenRouter key; rigswap (`rigswap/ai.py` `_relayed`) writes each ask there as
  `ask-<id>.json`: the instructions it would have sent as the system prompt, the question, the answer schema, and
  the paths of the pictures it would have sent (`sent-*` JPEGs, 1280 px). `job_status` stops waiting as soon as an
  ask is open and answers `status: "needs_answers"` with `asks` (`ask_id`, `round`, `instructions`, `question`,
  `answer_schema`, `pictures`, and `refused_answer` when the last answer did not fit), each ask's pictures
  following as image blocks after a text line naming it (at most `ASK_PICTURES` = 8 per call; later asks wait for
  the next call, counted in `more_asks`). `answer_import {job_id, answers: [{ask_id, answer}]}` first holds a
  skeleton answer to the rules rigswap's skeleton reading holds it to after the schema
  (`model_import/chat/ask_checks.py`, by the ask's `round`: `core fill` / `core fill again` are
  `rigswap/core/fill.py` `entries`, `core fill limb` / `core fill limb again` are its `_limb_fault`). An answer
  that breaks one (an arm named without its hand, a joint not in the ask's table, one side of a pair...) is
  `refused` at once with rigswap's own words ("the left arm names no hand") and is not written: rigswap's schema
  lets a hand be null, takes such an answer, and only says so in a new round ("An earlier answer could not be
  used: ..."; 0.9.0 build 3 smoke). A null neck and anything that needs the model (which side a limb lies on,
  whether the body builds) stay rigswap's, and a value of the wrong kind is left to rigswap's schema check. The
  rules are restated, not imported (rigswap runs in its own Python); `tests/backend/test_relay_answer_checks.py`
  runs the pinned rigswap's own `entries` and `_limb_fault`, from a rigswap clone, on the same answers. Otherwise it
  writes `answer-<id>.json` and waits up to 3 s for rigswap to read it: `accepted`, or `refused` with rigswap's own
  schema check (`problem-<id>.json`; 3 answers per ask) so the client answers again. An ask with no answer for
  10 min (`RELAY_WAIT_S`) takes rigswap's default, and a relayed run may take 90 min (`RELAY_TIMEOUT`) before it is
  stopped. Answers are cached under the model name `client`, apart from OpenRouter's. In-app chat imports still
  ask on the turn's key: rigswap asks its model itself and re-asks it on such a fault, so no app code sees those
  answers.
- **Cancel.** While an `mcp_model_import` job is queued or running, the window shows a chip in the app header,
  between the wordmark and the tabs (`McpImportChip.jsx`; in the fullscreen skin editor, which hides the app
  header, in that editor's header): "Your AI · Neos as Marth · putting it on the fighter · Cancel" (a `fix_import`:
  "Your AI · changing Neos on Marth · ..."). It reads the job store, fed by the `job` socket event, so nothing
  polls; the job's `extra` carries `model` (the name the costume is saved under, no file extension), `fighter`
  (when known before rigswap picks), `change` (`model_jobs.shown`), `step` and `asking`. `step` is a few plain
  words (`import_job.STEPS`, read from rigswap's own stage lines, never its tools' lines with their clocks and
  paths); `asking` is true while an ask waits in the relay folder, and the chip then says "waiting on your AI's
  answer". The job's `detail` stays rigswap's raw last line, for `job_status`; the chip never shows it. Cancel is
  `POST /api/jobs/<id>/cancel`, as every job's; the chip shows "Stopping…" until the job ends `cancelled`, then
  "Import stopped: nothing saved" for 4 s, and goes. Done and failed jobs just leave it (the vault and the AI say
  how they went). It sits in the header's flow, so it never covers the Dolphin embed or a 3D viewer's controls,
  and takes only the room the wordmark and tabs leave (they never wrap or move): the step shortens first, then
  the model's name, then the fighter; Cancel always shows and the tooltip has the whole sentence.
- `cancel_import {job_id}` is the same stop for the AI (the user said stop; a wrong file or fighter). It waits up to
  15 s for the job to end and answers `stopped` (nothing saved), `stopping` (still ending: follow `job_status`),
  or, for a job that was not running, `already_finished` (with what it saved), `already_failed`,
  `already_stopped` or `already_ended`. Either stop ends rigswap's process tree by PID (`import_job._stop`); the
  import's `cancelled` poll marks the job `extra.stopping`, so the chip shows a stop the AI asked for too. A stop
  that arrives after the vault save leaves the job `done` with the costume, so "stopped" always means nothing
  was saved.
- When a job ends `done` with a costume saved (`result.vault_changed`), App.jsx reads the vault again
  (`useMcpImportSaved`), as Randall's own import does through AssistantPanel's `onRefresh`.
- Any other call slower than 45 s returns `call-...`; `job_status` with it gives the result once done.

### Collection and builds

`randall/mcp/build_tools.py` gives the AI what the window's buttons do for a mod collection and its builds (the
11-18 user tests found these missing). No tool re-implements an app operation: each runs the Flask handler behind
its button in-process (`_route`, the `game_tests._invoke` pattern), so a result is the app's own answer.

- **Which build.** Install, music and export calls take a `project_id` from `list_projects`. The handlers act on
  "the open project", so the call pins that build for its one request (`g.nucleus_project`, which `core.state`
  reads before the open project; `pin_request_project` sets the same for every real request). The window keeps
  its own project and is not told: a page already showing that build shows the change once reopened.
- **Approval** as for the other tools: a call that changes something runs when called. Those calls run one at a
  time (`build_tools._lock`).
- `import_to_vault {path | paths (1-20), slippi?, duplicates?, kind?, title?}`: `POST /api/mex/import/file`
  (`vault/routes/import_unified/routes.py` `import_file`) with the file uploaded the way the window uploads it.
  Pictures picked together go as one upload, anything else one file at a time (`useFileImport.js` `toUnits`). The
  importer's questions get the window's batch answers (`importWithAutoAnswers`): Slippi problems `fix`, what the
  vault has `skip`, a file that could be several kinds the importer's `default` option (its `hints` sent as form
  fields). `slippi: "import_as_is"`, `duplicates: "import_anyway"` and `kind: "<option key>"` choose otherwise; a
  `kind` the importer does not offer is refused with its options and nothing imported. The result names what was
  asked and answered (`answered`), what was added with the ids the install tools take (`added`: `costumes`
  {character, skin_id}, `stage_skins` {stage_code, variant_id}, `custom_characters` and `custom_stages` {slug},
  `extras` {character, extra_type, extra_id}, `patches`, `bundles`, `menu_mods`), `already_in_vault`, `failed` and
  `next`.
- `search_vault_mods {kind, query?, character?}` [RO]: the vault's custom characters and custom stages (slugs) or a
  fighter's extras (each type with its saved `extra_id`s), read from the metadata like `search_vault_stages`.
- `install_stage_skin {project_id, stage_code, variant_id}` [D] (ids from `search_vault_stages`): on the six
  tournament stages, `das_get_status`, then `das_install` when that stage has no Dynamic Alternate Stages yet (new
  builds get it on creation; the result says `dynamic_alternate_stages_set_up_now`), then `das_import_variant`
  with the vault listing's `zipPath` (`das_list_storage_variants`); a Stadium `transformFix` report is passed on.
  Other stages: `stage_slot_install`, which replaces the stage.
- `install_custom_characters {project_id, slugs}` [D]: `install_custom_characters_batch`, then the character
  select re-fit the Install page runs after it: `menu_grid.auto_css_layout`, a port of `cssGridLayout.js`
  `computeAutoCssLayout`, read and saved through `GET`/`POST /api/mex/menus/css/layout`. The result's
  `character_select_grid` gives the screen's `rows` of fighter names, top to bottom and left to right, and
  `added_at` (row, column) for each character just added. A re-fit that fails is reported; the characters stay.
- `install_custom_stages {project_id, slugs}` [D]: `install_custom_stages_batch`, then the stage select re-fit
  (`useCustomStages.js` `autoApplySssGrid`: every page but the first, six wide) through `/api/mex/menus/sss/layout`.
- `install_extra {project_id, character, extra_type, extra_id}` [D]: `POST /api/mex/storage/extras/install`, or
  `/storage/models/install` for a model extra (`useExtras.js`'s rule).
- `inspect_project_stages {project_id}` [RO]: per tournament stage its DAS state and alternates
  (`das_get_stage_variants`, which renames legacy `.usd` alternates to `.dat` as the Stages page does), the other
  stages that are not vanilla with a count per slot state (`stages_slots`), and the custom stages in the build.
- `get_music_playlist` [RO], `set_music_playlist` [D], `add_music_track` `{project_id, playlist, ...}`: the music
  editor's handlers (`projects/routes/music_playlists.py`). `playlist` is `menu` or a tournament stage code (the
  editor has no others). Set takes `[{music_id, chance}]` (chances rescaled to 100; an empty list is vanilla music
  for a stage, refused for the menu). Add uploads one local song (`MUSIC_IMPORT_EXTS`), converted and appended at
  an equal share.
- `export_build {project_id, filename?, csp_compression?, color_smash?}`: `export_job.run_export_job` with
  `background=True` and that build's path and MexManager (the Build button's function, also Randall delivery's).
  Defaults as the Export page: compression from `GET /api/mex/recommended-compression`, name
  `<build>_<YYYY-MM-DD>_<HH-MM>.iso`. It answers with `job_id`, the export's artifact id. `job_status` follows it:
  `server.call_tool` hands an `iso_export` id to `build_tools.job_status` (the same long-poll), which gives
  `percent`, `detail` and, when done, filename, bytes, warnings and `next`; failed is `isError`.
- `save_build_iso {job_id, destination}` [D]: `POST /api/mex/export/save` (`save_iso`, through
  `playable_iso.publish`, so the clean ISO and files Nucleus did not make are refused). `destination` is a folder
  or a path ending in `.iso`.

None of these needs the clean Melee ISO: an export starts from the build. The xdelta patch export
(`/api/mex/xdelta/create`) is the step that diffs against it, and it is not offered.

### AI usage (who pays)

The AI-backed tools (`credits.AI_TOOLS`: `generate_material`, the one call the chat hands its turn's key,
`assistant/engine.py` `image_key`, that a client AI cannot do itself: it makes images) spend the same Randall
usage as the in-app chat: the signed-in person's Patreon-provisioned key and allowance. The model import is not
one of them: its asks are answered by the client AI (Jobs above), so it needs no sign-in and spends nothing.

- The window holds the Patreon app token. `App.jsx` (`randall/assistant/mcpAccount.js`) sends it to
  `POST /api/mcp/account {"token": ...}` at launch and on every entitlement change: a link sends the new token, a
  sign-out (including the automatic one on `invalid_token`) sends `null`. The backend keeps it in memory only
  (never on disk, in a log or in an answer); quitting ends it. The route needs the window-only key
  `X-Nucleus-UI-Key` (`core/ui_channel.py`): the AI client holds the backend token too, and could otherwise
  sign the backend out or hand it someone else's token.
- Before each AI call the backend asks the website's `ai-entitlement` function with that token, as the chat does
  before each turn, and applies `access.js` `assistantAccess` rule for rule: active with usage left and a key ->
  that key, for this call only; used up (with the free refill or monthly reset date), paused, not a member, not
  ready, or the check failed -> `isError` with the app's own words and nothing sent. An `invalid_token` answer
  forgets the token.
- Nobody signed in: the machine's own OpenRouter key (`OPENROUTER_API_KEY`, else `~/.nucleus-secrets/openrouter.key`)
  is the developer fallback. A signed-in person's verdict is final: used-up usage is never sent on that key.
- Neither: `isError` "The AI parts of Nucleus need you signed in: open SSBM Nucleus and connect Patreon in Settings
  ... Searching, the vault, builds and the labs still work without it."
- A chat turn's own caps (images per turn) have no MCP equivalent: there are no turns. Each call is bounded by its
  arguments (`generate_material` takes at most 4 prompts), and the provider key's own limit still applies.

### Problem reports

`report_problem {title, markdown, job_id?, import_id?, chat_id?, model?, effort?}` lets the user's AI write a
problem report for the developer. **Nothing is sent by the call.** It names what the report is about by id only: an
`mcp_model_import` job (`job_id`), a model import's folder under the imports root (`import_id`, a result's
`project`; a job's own project is found from the job) and a Randall chat (`chat_id`). Any other argument, a path in
an id (a slash, a backslash, a drive letter, `~`, `..`) and a model name or effort shaped like a path are refused
before anything is read; a network path is refused by `call_tool` as for every tool. An id that names nothing is
refused too, and nothing is made.

Nucleus assembles the package itself (`randall/reports/problem_report.py`) in
`<storage>/assistant/problem_reports/<id>/`:

- always: `report.md` (the markdown, at most 200 KB, refused over that) and `metadata.json` (title, the ids, the AI's
  model and effort as it gave them, versions: Nucleus, Python, the OS and the model import tools' state, the job's
  timings, and the error output: the job's error, the importer's failure fields and the last 40 lines of its log);
- optional, each a checkbox in the window: the import's records (the job record, `workflow/job.json`,
  `rigswap/result.json`, `randall.jsonl`, the newest part of `workflow/job.log`), the newest part of Nucleus's own
  log (`mex_api_<date>.log`), the chat's transcript (as "Report this chat" renders it, without costs), the import's
  preview pictures (at most 8) and the source model file (the job's `source` or the import's `download`; not ticked
  at first; a disc image, a non-model file or a file of the user's game, `chat_report_files.excluded_reason`, is
  never collected).

Every text part is scrubbed with the chat report's scrubber (home-folder user names, tokens, OpenRouter keys,
credential-looking environment values) before it is written, and every part is copied in and hashed when the report
is made, so what the window shows is what goes. Caps: one attachment 24 MB, all of them 40 MB (the worker takes
64 MB); a part past either is listed by name and size and never copied or sent. At most 3 reports wait at once and
6 are made per hour; one nobody sends within 3 days expires, and an ended one is forgotten a day later.

The call answers `{report_id, status: "waiting_for_user", sent: false, note, attachments: [{name, label, kind,
bytes, optional, include, too_large}]}`; the note starts "Waiting for you to confirm in Nucleus". The window hears
`mcp_problem_report` on Socket.IO (and reads the list when it connects) and shows the oldest waiting report
(`McpProblemReports.jsx`): the title, which AI wrote it, the markdown, every attachment with its size and a checkbox
for each optional one, the chat report's consent line, and Send and Discard. Send posts the ticked names to `POST
/api/mcp/window/problem-reports/<id>/review`, which freezes them into one ZIP with a `report.json` summary (what is
in it, what was left out and why) through `chat_report.freeze` (an approval hash over the worker meta and the
manifest, as "Report this chat" does), then posts `{submission_id, approval_hash, consent: true}` to `POST
/api/mex/chat-reports/submit`: the same submit, worker, transport, lease and retry rules. The worker files it as a
chat report (`kind: "chat"`, `chat.surface: "mcp"`, which it shows as unknown; the worker is not changed) with the
description `AI problem report: <title>` and the AI's model. Discard deletes the copies and sends nothing. The
three window routes and the submit route need the window-only key, so the AI client, holding only the backend
token, can neither read the waiting reports nor send or discard one.

`problem_report_status {report_id, wait_seconds?}` [RO] answers `waiting_for_user`, `sent` (with the first 8
characters of the worker's id as `reference`), `discarded` or `expired`; with `wait_seconds` (at most 50) it waits
for the person to decide.

### Images

Images are base64 MCP image blocks after the text block: `vision.tool_images` for the lab tools and import
results, the portrait of `preview_portrait`, and the skin cards of `present_vault_skins`. Paths under `/storage`
and assistant preview URLs are read from the vault; nothing outside it is read.

## Creation toolkit gateway

`native_port` (fighters from other games) and `stage_workbench` (custom stages) live in the developer tools
(`tools/fighterport`, `tools/stages`), which the app does not ship. The app always lists both, with the harness's
own descriptions and input schemas copied as static JSON (`toolkit_schemas.py`; the drift test
`tests/tools/test_app_mcp_toolkit_schemas.py` compares it with `harness_mcp.TOOL_DEFS`), each description
prefixed "Needs the Nucleus creation toolkit (a source checkout); the app asks for it if it is not set up."
Settings > AI > Creation toolkit (`app/frontend/src/settings/CreationToolkitSection.jsx`) says so to the user and
opens the public repo's `tools/creation/SETUP.md` (its `CREATION_TOOLKIT_GUIDE` follows `REPO_URL`, branch main).

- **Not set up:** a call returns `isError` with the steps: clone `REPO_URL` (`toolkit.py`, the one place it is
  written), run `tools/creation/setup.ps1`, call `connect_creation_toolkit`, and "If you have a shell (for example
  Claude Code), first ask the user "Can I clone the Nucleus creation toolkit and set it up?"". Also: the .NET SDK
  for `stage_workbench`, and that the source games are the user's own.
- **`connect_creation_toolkit {path}`** checks `<path>/tools/harness/harness_mcp.py` and a Python at
  `app/venv` or `.venv` without running anything, then asks the person in the app window (`window.confirm`,
  "Connect a creation toolkit?" naming the folder and the Python it will run; the AI client's own prompt is not
  enough, since a prompt-injected AI can talk its user past it). Only after Allow does it run that Python once
  (the package probe), save the folder in `<vault>/assistant/mcp.json` and report what it found (python, harness,
  dotnet). Deny, no answer within 5 minutes (`CONFIRM_SECONDS`; the call becomes a `call-` job after 45 s), a bad
  folder or a network folder are `isError` and save and run nothing.
- **`creation_toolkit_status`** [RO]: the saved folder and the same report, from looking at the folder only: it
  never runs the saved Python (`probe=False`).
- **Forwarding:** the first call starts `<toolkit python> -u tools/harness/harness_mcp.py` in the toolkit folder
  (stdio, no window, stderr to `<logs>/creation_toolkit.log`, owned by the backend so it ends with it, without the
  app's `NUCLEUS_*`, PyInstaller and `PYTHONPATH` variables), initializes it once, keeps it, and restarts it if it
  died or the folder changed. `native_port` and `stage_workbench` are forwarded as themselves; their result
  comes back as the child returned it. Both are job-shaped there (start, then `op: status`).
- **The rest of the harness:** `toolkit_tools {names?}` [RO] lists the harness tools in `toolkit.PASSTHROUGH`
  (summaries, or full descriptions and schemas for `names`, read from the child's own `tools/list`, so a newer
  checkout describes itself) and `toolkit_call {tool, arguments}` runs one. Harness results name their
  pictures as file paths; `toolkit.with_pictures` attaches the first four (scaled to 960 px wide) as images, for
  a client that cannot open files. Offered: the solo in-game session
  (`harness_info`, `dolphin_status`, `boot_match`, `do_move`, `step`, `send_input`, `debug_draw`, `game_state`,
  `screenshot`, `set_player`, `freeze`, `end_session`), `frameshot`, `stage_shot`, `run_ingame_test`, `fps_batch`,
  `netplay_desync` (two Slippi accounts; `op: check` first), `extras_doctor`, `mexcli`, `fsm_patch`, `iso_file`,
  `dat_probe`, `detect_content`, `decomp`, `render_csp`, `render_stock`. Not offered: the dev backend (`api`,
  `backend_*`, `vault_*`, `retake_csp`, `build_modded_iso`: the app's own tools do these), raw RAM pokes
  (`read_ram`, `write_ram`, `ram_search`, `poke_dat`, `effect_probe`), maintenance (`csp_regression`, `mex_codes`,
  `wait_for_file`), `hsdraw` and `rigswap`. A test (`test_every_passthrough_tool_is_in_this_checkouts_harness`)
  keeps the list in step with the harness.
- **Package check:** connect and status run the toolkit Python once and report `missing_packages` from
  `tools/creation/requirements.txt` with a note (it still connects: ports may run in another Python named in
  `app/scratch/creation/settings.json`).
- **Setup:** `tools/creation/setup.ps1` (`-WhatIf` shows the steps) makes `app\venv`, installs
  `app/requirements.txt` and `tools/creation/requirements.txt` (UnityPy, fmod_toolkit, ssbh_data_py, scipy,
  shapely, pyfqmr, PyYAML, opencv-python-headless; not torch, modal or huggingface tooling), runs
  `tools/build/fetch_native.py all`, and checks for the .NET SDK. User steps: `tools/creation/SETUP.md`.

## Not included

- The chat itself: no chat turns, task cards, journal or turn-end autosave. A Skin/Stage Lab result is saved
  only when the AI saves it (the descriptions say how).
- The window's context: the website account sign-in (`set_website_mod_like`),
  and the play card of `test_in_game` (use `action=status`).
- The rest of the developer harness (in-game harness, hsdraw CLI, ISO builds through a headless backend, rigswap
  ops). The toolkit's results stay in its work folders; importing a built fighter or stage ZIP into the installed
  app's vault is done in the app. The toolkit runs on its own checkout's data, not the app's vault.
- Concurrency: Randall tool calls run one at a time (one lock), like chat replies. A call can still run beside a
  reply in the app's own chat.
- Of the build buttons: taking things out of a build (alternates, custom characters and stages, an extra or a
  replaced stage back to vanilla), DAS button assignment and the Stadium transformation freeze, menu mods (CSS,
  SSS, pause, HUD) into a build, the CSS/SSS layout editors (only the automatic re-fit runs), the xdelta and
  texture-pack exports, and custom characters' own costume lists. Patches and bundles are imported but make a
  whole game from the clean ISO in the vault; they are not put into a build.
- Resources, prompts, SSE streams and progress notifications.

## Tests

- `tests/backend/test_app_mcp.py`: token 401, initialize, notifications, bad messages, assistant off, the app
  registers the route, tools/list (valid inputSchemas, annotations), `search_vault` on the test vault, unknown
  tool and bad arguments, images, an approval tool with its undo, choice refusal, `attach_file`, network paths
  refused for every tool before anything is opened, the toolkit status running nothing, connect waiting for the
  window (declined, unanswered, allowed) and the window-only question routes, a slow call as a
  job, `import_model` refusals and a stubbed import job, the ask relay (a stand-in rigswap asking two questions:
  `needs_answers` with the picture, a refused answer handed back, accepted, a stale ask id), a skeleton answer
  with a handless arm refused at once and never written, `cancel_import` (stopped with nothing saved, the chip's
  fields and `stopping` on the record, already stopped, a stop after the save left done), the documented tool
  count, the toolkit unconfigured / bad folder / forwarding to a
  fake harness (with restart), and (slow) a real `stage_workbench {"op":"guide"}` through this checkout.
- `tests/backend/test_relay_answer_checks.py`: `ask_checks` on its own, and against the pinned rigswap's
  `entries` and `_limb_fault` (skipped without a rigswap clone).
- `app/frontend/src/randall/assistant/mcpImport.test.js` (the chip's states on the real job store, Cancel through
  the cancel route, a failed Cancel, the stopped note going, the vault refetch on a saved import only) and
  `McpImportChip.test.js` (the chip as drawn, no inline styles). `tests/backend/test_assistant_import_job.py`
  covers `import_job.next_step`, the step words the chip shows.
- `tests/backend/test_app_mcp_build_tools.py`: the build tools' listing and annotations; `import_to_vault`
  answering the importer's questions (scripted engine) and once through the real importer; the real DAS and
  replace-slot installs on a temp build while the window has another open; custom characters and stages with
  their re-fits, extras routing and music through recording handlers; an export job followed by `job_status` and
  saved for real; `menu_grid` against the window's constants, and (slow) against `cssGridLayout.js` run by node.
- `tests/tools/test_app_mcp_toolkit_schemas.py`: the static schemas match the harness.
- `tests/electron/mcp-relay.test.js`: forwarding, notifications, parse errors, starting the app and waiting, giving
  up, 401 and refused-connection recovery, 404, and the discovery file.
- `app/frontend/src/settings/mcpCommands.test.js`: the commands the card shows.
- `tests/backend/test_mcp_problem_reports.py`: the call assembles a scrubbed report and sends nothing (the network
  recorded); a token-only caller can neither list, freeze, discard nor submit; paths, unknown arguments and ids
  that name nothing are refused and make nothing; the markdown and title caps, the waiting and per-hour limits, and
  attachments over the per-file and total caps listed and never sent; Send through the real chat report submit
  with `requests` mocked (the worker meta, the ZIP's members, the ticked source model, nothing of the home folder);
  Discard; `problem_report_status` waiting for the decision and an old report expiring; a chat by its id.
  `app/frontend/src/randall/assistant/problemReport.test.js`: the review as drawn and the send flow.
- `app/frontend/src/randall/assistant/mcpAccount.test.js`: the window's question watcher (each question once, a
  failed dialog is a no); `app/frontend/src/shared/transport/api.test.js`: only the question routes get the key.
- AI usage: in `test_app_mcp.py`, no sign-in gives the sign-in message and sends nothing, the window's token bills
  the call (provider mocked) and sign-out clears it, each call rechecks the entitlement (used up, paused, not a
  member, offline, invalid token), the machine-key fallback, and the account route's guard and checks;
  `app/frontend/src/randall/assistant/mcpAccount.test.js` for the window's side.
