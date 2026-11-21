# Randall (backend)

One folder per job. The long-form description is `docs/dev/RANDALL.md`; the pipelines each have a README
you can read top to bottom.

A chat is a normal chat or starts from one of five starting points (`assistant/recipes.py` `LAUNCHABLE`, served
by `GET /api/assistant/status` as `tasks`), in two groups. Characters: **Retexture a costume** (`recolor_part`,
`recolor/`), **Import a character model** (`model_import`, `model_import/`) and **Create a character**
(`create_character`, a stub). Stages: **Retexture a stage** (`recolor_stage`, `recolor/`) and **Import a stage
model** (`stage_import`, a stub). A stub is listed with `available: false` and cannot be started
(`create_character/README.md`, `stage_import/README.md`). The user-facing word is "Retexture"; ids, folders and
code keep "recolor".

| Folder | What is in it |
|---|---|
| `assistant/` | The chat itself: the turn loop (`engine.py`), the prompt, the main-model request, live runs and approvals, the tool registry (`tools.py`: every tool's schema) and the tool stage, the chat store, compaction and continuity, app context, capabilities, vision, the task cards (`recipes.py`), turn facts, and `tasks/` (the task journal). Also the pieces every pipeline shares: chat file handles (`mod_files.py`), HSDRaw edits and `save_mod_copy` (`hsdraw.py`, `stage_scene.py`), vault rows as tools show them (`vault_items.py`), and clone a character. |
| `recolor/` | **Retexture a costume**: the recolor workflow (acquire, prepare, create and review), the Skin Lab, materials and generated swatches, stock costumes as working files. **Retexture a stage**: the Stage Lab and how a stage recolor chat starts (`stage_start.py`). [README](recolor/README.md) |
| `model_import/` | **Import a character model**: `chat/` is how a chat starts, runs and reports an `import_model` job, which runs rigswap (its own repo) as a subprocess; `studio/finish.py` saves the costume to the vault. [README](model_import/README.md) |
| `create_character/` | **Create a character**: not built. A README only: what it will be (model import is step one) and the owner's open questions. [README](create_character/README.md) |
| `stage_import/` | **Import a stage model**: not built. A README only: what it will be and the owner's open questions. [README](stage_import/README.md) |
| `website/` | Finding and downloading mods from ssbmnucleus.net into the vault: search, inspect, one approval, quarantine, safety check, import, likes, and which downloads are already in the vault. |
| `delivery/` | Putting a result in the game: project installs (`projects.py`), "My game" (`destination.py`), `deliver_to_game` and its undo (`deliver*.py`), in-game play sessions and checks (`game_tests.py`). |
| `reports/` | What Randall sends to the developer: "Report this chat" (`chat_report*.py`), wishes (confirmed missing capabilities, `wishes.py` over `wish_*.py`) and the transport both use. |
| `coach/` | The Tracker coach (the Analyst tab). |
| `routes/` | The HTTP layer: `/api/assistant`, chat reports, wishes, and the coach's routes. |
| `mcp/` | Randall's tools as an MCP server for the user's own AI (`POST /api/mcp` in `shared/routes/mcp.py`), model import jobs, whose AI usage its calls spend (`credits.py`), the collection and build tools (`build_tools.py`: import to the vault, stage skins, custom characters and stages, extras, music, ISO export), and the creation toolkit gateway. [APP_MCP.md](../../../docs/dev/APP_MCP.md) |

Import direction: `assistant/` registers the tools of the feature folders (`recolor/`, `model_import/chat/`,
`website/`, `delivery/`) and reads `reports/`; the feature folders import `assistant/` helpers (`mod_files`,
`vault_items`, `approvals`, `tasks/`, ...) but never the turn loop (`engine.py`).
