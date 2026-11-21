# Screenshots that need a human

Everything else in `../img/` comes from `capture.mjs` / `capture-web.mjs`. These are OS or browser dialogs, or need Dolphin with a controller, so they are taken by hand. Save them as `../img/<id>.png` at roughly 1600 px wide; `build.py` will pick them up like any other image.

| id | What to show | How |
|---|---|---|
| `01-smartscreen.png` | Windows "Windows protected your PC" dialog with **More info** expanded and **Run anyway** visible | Run the installer on a machine that hasn't seen it. |
| `03-web-protocol-prompt.png` | The browser's "Open SSBM Nucleus?" prompt after clicking **Add to Nucleus** | Firefox and Chrome both work; ring the **Open** button. |
| `03-slippi-prompt.png` | The import dialog offering **Fix and import** / **Import as is** | Import a skin that fails validation, for example a model swap. |
| `05-test-in-game.png` | Dolphin embedded in the app during a **Test in game** run, with the progress text | Click Test in Game on any skin's edit dialog with Slippi installed. |
| `06-in-game.png` | An in-match screenshot of a Nucleus build showing a modded skin and a stage variant | Boot the exported ISO in Slippi Dolphin. Use `tools/harness/harness_mcp.py`'s `frameshot` if you want this scripted too. |
| `08-share.png` | The share menu on a replay, with the public link | Needs a signed-in account; click **Share** on any replay. |

Images the scripts *can* take but only with `--slow` (minutes each): `03-iso-scan-results` (set `GUIDE_SCAN_ISO` to a modded ISO), `06-export-done`, `08-watch-lite`, and populated versions of `08-replays` / `08-combos` / `08-stats` (indexes the replay folder in `GUIDE_REPLAY_DIR`, default `Documents\Slippi`).
