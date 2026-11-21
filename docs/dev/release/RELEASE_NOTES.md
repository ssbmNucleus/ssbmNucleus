# SSBM Nucleus 0.9.0

Randall, the AI assistant, comes with SSBM Nucleus now, and you can connect your
own AI to Nucleus too.

- **Randall** is part of Nucleus. Open **AI** to ask him about your vault, your
  builds and mods on ssbmnucleus.net: he finds and downloads mods, recolors
  costumes and stages, takes portraits, makes builds and installs mods into
  them, and tests things in the game right in the chat. Anything that changes
  your files asks you first. His AI runs on your Patreon sign-in; Randall
  settings shows the usage left this month.
- **Connect your own AI (MCP).** Settings > AI gives you the command
  to add Nucleus to Claude Code, Claude Desktop or Codex. That AI gets
  Randall's tools: your vault, website downloads, model imports, builds,
  in-game tests and ISO export.
- **Model import** (Windows): give Randall a model (ZIP, GLB, glTF, OBJ, FBX,
  SMD or DAE) and he fits it to a Melee fighter and saves the costume. Then
  say what looks wrong ("the legs look wrong") and he fixes that one thing.
  The Windows installer is bigger because it carries Blender and the importer.
- **Art from your own game**: the select-screen layout editors, stage select
  icons and banners, HUD, pause and series pictures, and the Dynamic Alternate
  Stages loaders are all made from your own copy of the game.
- **Tracker**: shared and synced replays upload as the original replay file,
  so share links and the phone get every viewer fix.
- **Fixes**: L and R on a one-page stage select screen, recordings from an
  odd-sized Dolphin window, Falcon Punch fire colours, blue Jigglypuff's bow in
  posed portraits, and the "Drop to import" screen sticking.
- **Security**: replay text can't run code in Watch Lite; the MCP refuses
  network paths and asks before connecting a toolkit; backups leave out your
  sign-in, AI-client settings and this PC's folders, and a restore never takes
  a network path from one; Patreon linking only accepts a link Nucleus
  started; private keys are off the command line; website imports ask first;
  and the app window has a Content-Security-Policy. Electron 44.11.5.
- **Removed**: the older separate custom character and stage imports (ZIP and
  ISO scan). The Import page does both.

Full changelog: https://github.com/ssbmNucleus/ssbmNucleus/blob/main/CHANGELOG.md
