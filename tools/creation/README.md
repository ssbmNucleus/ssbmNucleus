# Nucleus creation tools

The developer MCP exposes three complementary tools:

- `native_port`: source-game fighters, animations, movesets and custom mechanics.
- `rigswap`: a model made into a costume for an existing Melee fighter, through
  Randall's existing importer; successful imports are saved to the vault.
- `stage_workbench`: freeform stage geometry, animated scenery, cameras and ZIPs.
  Its [guide](../stages/README.md) describes the Colosseum/CS2 building tools.

These are agent tools. End users do not need to run a harness. The installed app lists `native_port` and
`stage_workbench` to a user's own AI and forwards them to a checkout set up with `setup.ps1`
([SETUP.md](SETUP.md), `docs/dev/APP_MCP.md`). Custom special
mechanics and visual polish still require creative/engineering work; a completed
build is not a claim that every source mechanic or graphic is finished.

## Native ports

Start with `native_port {"op":"info"}`. The engine and readers are maintained
in this repository at `tools/fighterport`, not in a separate checkout. Source
packages retain their Python names (`fighter_port`, `echo_slapcity`, etc.).

`read_source` runs the existing Slap City or Rivals 2 reader against local game
files, writing a new source root. Rivals names use source capitalization:

```json
{"op":"read_source","game":"rivals2","game_dir":"C:/Program Files (x86)/Steam/steamapps/common/Rivals 2","fighter":"Ranno","root":"<ports>/ranno-source-v2"}
```

Slap City also supports `list:true` with its `Slap City_Data` folder. Ultimate
and Brawl use their existing extracted-source/preflight path; see
`tools/fighterport/fighter_port/READERS.md` for source requirements. No game is
launched and no mapping dumper or injector is run by `read_source`.

Then build with the actual current `fighter_port.port` CLI. The MCP forwards
own-skeleton, stage selection, form, size and optional calibration arguments:

```json
{"op":"port","game":"rivals2","fighter":"ranno","name":"Ranno","root":"<ports>/ranno-source-v2","work":"<ports>/ranno-v2","only":"preflight"}
```

Omit `only` for the build; omit `iso` for a fighter ZIP. Slap City and Rivals 2
default to `own:true`. `from`, `to`, `only` and `forms_from` select rebuild
stages in an existing dedicated work folder. The engine may recreate that
folder's build project and the explicitly requested ISO; use new revisions to
keep earlier results. `inspect` with `work` reads build status, implementation
limits, package paths and notes without launching anything.

`checklist` reads the optional fidelity backlog. With `work`, `line`, `answer`
and `how`, it records an observation. `adapter` exposes existing focused
inspection/repair operations, using `operation` and an `options` object; `info`
lists them. Their implementation is `fighter_port/port_mcp.py`.

## Model costumes

`rigswap {"op":"info"}` reports setup and supported fighters.
`{"op":"import","source":"C:/models/character.glb","fighter":"Marth","name":"My costume"}`
uses the same import and vault-save path as Randall. Omit `fighter` for automatic
selection. `fix` takes the returned `project` id and `change`; `said` preserves
the user's exact words when `change` is an interpretation. Each successful fix
keeps the earlier costume. The engine uses existing configured AI credentials;
keys are never accepted as MCP arguments or saved in job requests.

## Jobs and dependencies

Port/read_source/checklist/adapter and rigswap import/fix return immediately with
a `job` id. Follow it with the same tool's `{"op":"status","job":"..."}` for state,
log tail and result. Status waits up to `wait_seconds` (default 30, at most 40) for an
active job to end, so a caller needs no sleeping between calls. `cancel` asks the owning worker to stop its subprocess
tree. Jobs survive MCP reconnects, persist under `app/scratch/creation/jobs`,
and serialize writes to the same work destination. The MCP never kills an
unrelated process or starts a second writer for the same destination. A stopped
heartbeat is reported as interrupted, not successful. Keep polling until a
terminal state; queueing a job is not completion.

The default port Python is the MCP's interpreter; `FIGHTERPORT_PYTHON` overrides
it. Existing dependencies use `SSBH_DATA_PY`, `UNITY_PYDEPS`, `RIVALS2_USMAP`,
`OODLE_DLL`, `MEXTK_DIR`, `PORT_DONOR_ZIP`, `ULTIMATE_DUMP`, `BRAWL_DUMP`.
An optional ignored `app/scratch/creation/settings.json` can hold `python` and
a `fighterport` object with those dependency paths. Environment values win.
Only local paths belong there; never credentials or assets. `NUCLEUS_REPO` is
set to the repository hosting this MCP so builds use the same app/tool config.
Rigswap continues using its existing `RIGSWAP_*` configuration and runtime.
The port interpreter also needs its existing Python dependencies, including
NumPy, Pillow, OpenCV, Shapely and pyfqmr; the app venv and the port interpreter
may have different packages. Run port tests with that interpreter from the
repository root: `python -m pytest tests/fighterport -o addopts=''`. The test
configuration reads the same optional local dependency paths as MCP.

Stage workbench calls remain synchronous, composable operations. Use existing
`detect_content`, `vault_import`, `build_modded_iso` and optional capture tools
for stage delivery. The creation MCP does not implement Randall's unfinished
stage/native-character UI tiles. Reconnect the MCP client after updating the
server to discover the 44 registered tools.
