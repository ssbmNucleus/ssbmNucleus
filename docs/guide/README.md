# SSBM Nucleus user guide

The user-facing guide, written for people who want to *use* Nucleus, not understand it. Feature-first, no internals. It replaces the 1.0-era PDF guide and sits beside the more technical `../wiki/`.

- `sections/*.md` — the text, one file per chapter, in reading order. Start with `sections/00-intro.md`.
- `img/` — screenshots. **Generated, not hand-taken.** Every image is reproduced by a script, so a UI change means re-running, not re-cropping.
- `scripts/` — the tooling below.
- `dist/` — build output (ignored).

## Rebuilding the guide

For the current review copy:

```
python docs/guide/scripts/build.py --strict
```

This writes the self-contained `dist/guide.html`, a combined Markdown file, and a split static-host build in `dist/site/` whose images are separate files. `--strict` rejects missing images and broken chapter links. The HTML is the review artifact; nothing is published by this command.

The September 13, 2026 pass updated the text for 0.8.3 through 0.8.6 (Stage Creator, More Stages, Any Climbers, Skin Creator layers and tools, the effects editor, music controls, stock icon styles) and reshot the Skin Creator, Custom Characters, effects editor, Portraits, DAS prompt and Stage Music images with `capture.mjs --only`. `capture.mjs` seeds the renderer's ISO path from `GUIDE_VANILLA_ISO` (no default), so set it to a real vanilla 1.02 ISO or every shot carries a setup banner. Any Climbers pairs in the scratch vault were created through `/api/mex/climbers/create` (see `.capture/seed_pairs.py`).

Scratch vault = a copy of the demo vault (`seed.py --vault <demo vault>`, 598 skins) plus two Any Climbers pairs (`.capture/seed_pairs.py`). Tracker shots need games: `.capture/pick_replays.py 60` copies the newest 60 *parseable* games from the Slippi folder (unfinished harness recordings are skipped), `.capture/seed_replays.py` indexes them and `.capture/seed_combos.py` runs the combo pass, all through a private backend. Do this before `capture.mjs` or every Tracker page is empty. Stage and menu content: `.capture/seed_stage_shots.py` renders a screenshot for every stage variant that lacks one (the Bulk Render path, offline), `.capture/seed_menus.py` pulls CSS/SSS backgrounds and pause screens from the website into the vault, and `.capture/seed_menu_ingame.py` installs one of each into Guide_Build, exports `guide-menus.iso`, boots it and grabs `04-menu-css-in-game` / `04-menu-sss-in-game` from Dolphin (these two are not in `shots.mjs`; run the script, then `annotate.py`). Poses: `.capture/seed_pose.py` saves a Fox "Taunt" pose (AppealSL, frame 28) and batch-renders every Fox portrait with it, which `04-pose-grid` and `04-character-detail` show; `04-pose-editor` is a desktop grab of the native viewer. Chapter 8 sign-in: `.capture/seed_signin.py` copies this machine's Discord session into the scratch vault (names are masked in the shot); set `GUIDE_STARTGG_SLUG=076502c1` for Hungrybox's linked Tournaments page; Share and Cloud vault need a Patreon-linked `vault_app_token`, which this laptop's app does not have, so `08-share` stays unshot and the share page comes from the website instead (`capture-web.mjs`, which also takes the phone shell at 390x844).

The **phone app** shots (`08-mobile-games` / `-combos` / `-stats` / `-tourney`) come from `scripts/capture-phone.mjs`: it drives the live app at tracker.ssbmnucleus.net at 390x844, but answers every `vault-read` call locally from `scripts/phone_payload.py`, which rebuilds the vault's `list`/`combos` response shapes out of the same `.capture/storage/nucleome.db` the desktop Tracker shots use. So the phone shows the same 60 games as the desktop pages, and no device token is needed — which matters, because this laptop has no `vault_app_token` to mint one with. Tourney is the exception: it is public (`startgg-proxy` takes no token) and is crawled live, so pass `GUIDE_STARTGG_SLUG` for it and expect the first sync to take a minute. A pose-camera sweep helper lives next to it: `.capture/pose_sweep.py x,.. y,.. z,.. out.png` renders a contact sheet of camera variants on the vanilla costume, which is how `04-pose-grid`'s framing was picked.

Sections can lay screenshots out side by side with a `:::phones` ... `:::` fence around the image lines — full width each, a 390x844 capture is a wall of pixels.

Obsidian copy: `app\venv\Scripts\python docs\guide\scripts\export-obsidian.py` rewrites `Projects/Nucleus/SSBM Nucleus Guide.md` in the Nucleus Notes vault and syncs `Attachments/guide/`. One-way; run it after any section or image change.

The September 8, 2026 refresh covers the 0.8.2 feature surface. Refreshed tabs, project selector, Settings, bug report, and mobile-instructions images come from `capture-settings.mjs`, which runs the real app with a separate profile, Vault, runtime directory, and Vite handoff. It does not overwrite the normal frontend's `.vite-port` file. Download and Add to Nucleus images were refreshed with `capture-web.mjs`. Capture sources and dates are recorded in image sidecars. Other images are retained earlier captures of the corresponding features.

```
node docs/guide/scripts/capture-settings.mjs
node docs/guide/scripts/check-render.mjs
```

The six previously missing images (SmartScreen, protocol prompt, ISO scan results, completed export, Watch, and Share) are no longer referenced. Feature instructions stand on their own without them; the SmartScreen detour was removed. The obsolete automated Test in Game result screenshot, old Cloud vault image, empty Tracker pages, and outdated Friends screenshot are also omitted. Do not substitute a fabricated dialog, an unsigned installer warning, or a development-only screen for a release screenshot.

The original full capture pipeline is below. Its selectors and environment assumptions predate the current Settings layout and need checking before a full recapture.

```
# 1. build the scratch vault the screenshots use (once; safe to re-run)
app\venv\Scripts\python docs\guide\scripts\seed.py

# 2. take the screenshots (about 5 minutes; add --slow for the ones that take longer)
node docs\guide\scripts\capture.mjs

# 3. website screenshots (download page, Add to Nucleus button)
node docs\guide\scripts\capture-web.mjs

# 4. assemble sections + images into dist/guide.html (and --pdf)
app\venv\Scripts\python docs\guide\scripts\build.py --pdf
```

`capture.mjs` drives the real Electron app with Playwright (`playwright-core` is a devDependency in `app/package.json`; run every command below from the repo root) against an isolated profile and vault under `docs/guide/.capture/`, with the same release gates as the packaged build, so nothing unreleased can end up in an image. Red rings are not drawn by hand: each shot records the bounding boxes of the elements to highlight in `img/<id>.json`, and `annotate.py` paints them onto the raw capture.

`--only <substr>` re-takes a subset (`--only 05-` for the Install chapter). Failed shots leave `img/_raw/_failed-<id>.png` for diagnosis.

Shots marked `slow` in `shots.mjs` need `--slow` and take minutes: the ISO scan of a modded ISO, an ISO export, Test in Game (Dolphin embedded, grabbed from the desktop), and indexing the replay sample in `.capture/replays`.

**Privacy.** Every shot first swaps the strings in `docs/guide/.capture/redact.json` (gitignored) out of the DOM: your Windows username in paths, your connect code and display name. Tracker pages also pixelate player names and codes through the `mask` option, so opponents in the replay sample never appear. Check new screenshots for anything personal before committing them.

Anything still unscriptable is listed in `scripts/MANUAL_SHOTS.md`.

## Editing the text

Plain Markdown. Image references are `../img/<id>.png` and cross-links are `NN-name.md`; `build.py` rewrites both when it stitches the single-file HTML. Keep the tone: what the user can do and how, not how it works underneath. If a sentence is about the code, it belongs in `../wiki/`.

Use feature names, locations, and actions. Avoid promotional claims, invented use cases, generic advice, and unreleased features. Check `app/frontend/src/shared/config/features.js` and the packaged gates in `app/electron/main.js` before adding a feature. A changed screenshot or passage does not authorize production publication.
