# Setting up the Nucleus creation toolkit

SSBM Nucleus lists two creation tools to your own AI (Claude Code, Claude Desktop, Codex): `native_port`
(fighters from other games) and `stage_workbench` (custom stages). They run from a source checkout, the
creation toolkit, not from the installed app. Until one is connected the app answers either tool with these steps.

1. Clone the toolkit: `git clone https://github.com/ssbmNucleus/ssbmNucleus nucleus-toolkit`
2. Set it up (Windows, Python 3.13):
   `powershell -NoProfile -ExecutionPolicy Bypass -File nucleus-toolkit\tools\creation\setup.ps1`
   It makes `app\venv`, installs `app\requirements.txt` and `tools\creation\requirements.txt`, and fetches the
   pinned MexCLI and HSDRawViewer (`tools\build\fetch_native.py all`, from the public releases; no GitHub
   account needed). Add `-WhatIf` to see the steps without changing anything.
3. Ask your AI to call `connect_creation_toolkit` with `{"path": "<the nucleus-toolkit folder>"}`. The app checks
   the folder (`tools/harness/harness_mcp.py` and a working `app/venv` Python), saves it, and from then on
   forwards `native_port` and `stage_workbench` there. `creation_toolkit_status` shows what it found.

Needs:

- The .NET SDK (https://dotnet.microsoft.com/download) for `stage_workbench`, which builds its stage tool on first
  use. `native_port` works without it.
- Blender only for shaded port renders: Blender 4.3.2 comes with the model import tools (Settings > AI > Model import
  tools; or from `app\backend`: `..\venv\Scripts\python.exe -m randall.model_import.tools.assemble --root <dir>`).
- The source games are your own. The toolkit reads the games you installed and never downloads one.
- Where the readers find things is set in `app\scratch\creation\settings.json` (ignored by git) or the same
  names as environment variables: `python` (a Python for the port jobs, if not `app\venv`), and under
  `fighterport`: `RIVALS2_USMAP` (Rivals 2 needs a `.usmap` dumped from your own install) and `OODLE_DLL`
  (`oo2core_9_win64.dll`, shipped with many Unreal games), `ULTIMATE_DUMP`, `BRAWL_DUMP`, `SSBH_DATA_PY`,
  `UNITY_PYDEPS`, `MEXTK_DIR`, `PORT_DONOR_ZIP`. `native_port {"op":"info"}` shows which are set.
- `connect_creation_toolkit` also reports which toolkit packages its Python lacks (`missing_packages`).

Once connected, the toolkit also offers the dev harness's useful tools through `toolkit_tools` (list) and `toolkit_call` (run): frame-exact move screenshots, stage screenshots, a solo match driven frame by frame with hitboxes, ISO crash and FPS checks, extras triage, the m-ex CLI, Crazy Hand FSM patches, ISO/DAT readers and the Melee decompilation (`decomp` needs a local doldecomp/melee checkout, `MELEE_DECOMP`).

The netplay desync test (`netplay_desync`) needs two Slippi accounts: copy Slippi Launcher's `netplay` folder to `slippi-desync-rig\instance-a` in your home folder (or set `NETRIG_ROOT` to the folder that holds `instance-a`), run that copy's `Slippi Dolphin.exe` once and log in with your second account; keep the launcher on your main one. It drives two virtual controllers with `vgamepad` (`pip install vgamepad`, which installs the ViGEmBus driver) in the Python named as `python` in `app\scratch\creation\settings.json`. `toolkit_call {"tool": "netplay_desync"}` checks all of this before it boots anything.

How the app forwards the calls, and everything else about the MCP server: `docs/dev/APP_MCP.md`.
