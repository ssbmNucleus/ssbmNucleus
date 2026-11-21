# Menus System (CSS / SSS Customization)

Menu mod management for the Character Select Screen (CSS) and Stage Select
Screen (SSS). The backend is two route packages, the vault's menu mod library and
the routes that install into the open project, over one engine package
(`vault/menus/`) that both import (route modules never import each other); all
routes register on the single `menus_bp` blueprint defined in the vault route
package (see [API_REFERENCE.md](API_REFERENCE.md#menus-blueprint) for the
endpoint list).

```
backend/vault/routes/menus/
├── __init__.py      # menus_bp definition, imports submodules (and the project side)
├── icons.py         # CSS icon grid mods (import / edit)
├── backgrounds.py   # menu background mods (shared CSS/SSS pool)
├── doors.py         # CSS door textures
├── pause.py         # pause screen (GmPause) texture mods + pause pictures
├── percent.py       # percent font / HUD (IfAll) texture mods + glyph/word packs
└── summary.py       # GET /api/mex/menus/summary (vault sidebar counts)

backend/vault/menus/            (the engine: no routes)
├── store.py         # storage paths, catalog and mod.json persistence
├── files.py         # zip extraction and export, preview pictures, MnSlChr / MnSlMap discovery
├── hsd.py           # the HSDRawViewer CLI, retried when the file is in use
├── installed.py     # the "Currently in MEX" record and its preview snapshots
├── icons.py         # icon grid catalog, character labelling, import
├── backgrounds.py   # background catalog, import
├── doors.py         # door catalog, import
├── pause.py         # pause catalog, vanilla manifest, import, texture set
├── pause_install.py # write a pause mod into GmPause.usd (the in-game capture build uses it too)
├── percent.py       # HUD catalog, categories, vanilla manifest, import, glyph state
├── percent_install.py # write a HUD typeface into IfAll.usd, HUD install bookkeeping
├── hud_verify.py    # checks the HUD typeface slots of "Currently in MEX" against IfAll.usd
├── menu_checks.py   # the same for pause, doors, icon grid, CSS/SSS background
├── menu_pixels.py   # tolerant decoded-picture comparison shared by every check
└── menu_exports.py  # cached HSDRawViewer exports for the checks

backend/projects/routes/menus/
├── __init__.py      # imports the submodules; they add routes to menus_bp
├── icons.py         # install an icon grid (plan + one icon per fighter)
├── backgrounds.py   # install a background into the CSS or SSS, CSS status, restore vanilla
├── doors.py         # install CSS door textures
├── pause.py         # install a pause screen mod
├── percent.py       # install a HUD typeface, restore vanilla Percent Font / Ready-Go
├── installed.py     # GET /api/mex/menus/installed (+ ?verify=), preview snapshots
├── layout.py        # CSS layout editor + fighter icons
├── sss.py           # SSS layout editor + stage icons
└── build_changes.py # the build-change approval card
```

Storage for all menu mods lives under `storage/menus/`.

## The Vault UI

The vault's Menus page (`frontend/src/vault/menus/VaultMenusView.jsx`)
is a sidebar of the seven kinds — grouped Character Select / Stage Select /
In-Game HUD, each with a count from `/menus/summary` — beside a card grid of
the selected kind (`MenuKindPane.jsx` + `MenuModCards.jsx`). The registry in
`menuKinds.js` is the one place that names each kind's list / rename /
preview / export / delete endpoints; a new kind is one entry there (plus an
editor branch in the pane if it has one). Card actions replace the old
pencil-then-modal flow: inline rename, preview replacement (for doors the
preview IS the texture), export, delete, the pause capture, and the
backgrounds' scene-settings switch. Kinds with editors open them in place of
the grid. Every kind ends with a "+" card: pause screens and HUD typefaces
create a draft and open the editor; icon grids create a vanilla-seeded grid
(`POST /api/mex/menus/css/icon_grid/create` → `create_icon_grid_from_vanilla`,
which zips the vanilla `MnSlChr.usd` reference through `install_icon_grid_mod`)
and open the per-icon editor; doors and backgrounds (no editor) open a file
picker and post to `/import/file` with the kind's `mod_type` hint.

There is no import UI on the page: menu mods (compiled files or loose
pictures) arrive through the vault's floating Import button, whose
`/import/file` pipeline detects the kind and refreshes the page
(`refreshers.menuMods`). Importers that the unified route calls directly:
`install_icon_grid_mod`, `import_bg_archive(menu_type=...)`,
`import_door_image`, `install_pause_mods_from_zip`, `import_pause_picture`,
`install_percent_mods_from_zip`.

## CSS Icon Grid Mods

Replacement sets for the character icons on the CSS. A mod can arrive in two
flavors:

1. **Loose PNGs** named after characters (a large alias table maps filenames
   like `falc.png`, `gnw.png`, `ics.png` to canonical character names)
2. **Compiled CSS dat files** (`MnSlChr.dat/.usd`, `mexSelectChr.dat`,
   optional `MxDt.dat`) — icons are extracted via HSDRawViewer

Either way, imports are normalized to a tiny per-mod payload:

```
storage/menus/css/icon_grid/
    metadata.json                 # catalog of installed mods
    <mod_id>/
        mod.json                  # per-mod manifest (icons + names + screenshot)
        screenshot.png            # optional preview
        icons/<Character>.png     # one labeled icon per character
```

Per-icon editing is supported (relabel to a different character, replace,
add, delete), and installation into the open MEX project can be done for the
whole grid or one icon at a time. The icon-grid installer is also reused by
`import_unified/` when a unified import detects a CSS mod.

## Menu Backgrounds

A background mod is a normalized `background.dat` bundle (a model/animation
bundle extracted from a `MnSlChr` or `MnSlMap` dat via HSDRawViewer) plus an
optional screenshot, stored under `storage/menus/css/background/<mod_id>/`.

The same pool of backgrounds installs into **either** screen of the loaded
MEX project:

- CSS: `POST /api/mex/menus/css/background/install/{mod_id}` (patches `MnSlChr.usd`)
- SSS: `POST /api/mex/menus/sss/background/install/{mod_id}` (patches `MnSlMap.usd`)

(`/api/mex/menus/background/...` aliases exist for list/import/delete in
addition to the `css/background` paths.)

A CSS install overwrites the background in place (no backup) and adds the
"Disable Hardcoded CSS BG Anim" Gecko code. `POST
/api/mex/menus/css/background/restore-vanilla` undoes it: it exports the
background from the vanilla `MnSlChr.usd` (`vanilla_refs.ensure_vanilla_ref`)
and imports it back with `--include-scene`, then removes that code via
`mexcli sync-codes`. Icons, doors and fighter slots in `MnSlChr.usd` are left
alone. `GET .../css/background/status` drives the button's visibility.

## CSS Doors

A door mod is a single `door.png` texture (the CSS "door"/port panels),
stored under `storage/menus/css/doors/<mod_id>/` and installed into
`MnSlChr.usd` via HSDRawViewer's `--css-doors` import.

## Layout Editors

Both select screens have layout editors backed by the loaded MEX project's
manager (MexCLI):

- **CSS layout** — `GET|POST /api/mex/menus/css/layout` reads/writes the
  character grid layout; `GET /api/mex/menus/css/fighter-icon` serves fighter
  icon images straight from the project assets.
- **SSS layout** — `GET|POST /api/mex/menus/sss/layout` reads/writes the
  stage select layout; `GET /api/mex/menus/sss/stage-icon` serves stage icon
  images.

All install/layout operations require an open MEX project; vault-side
operations (import, edit, delete) work without one.

## "Currently in MEX" (per-project install record)

The ISO editor's Menus tab shows what each slot of the open project holds.
Install routes record it in `<project_dir>/nucleus_menus.json` under
`installed[<menu>:<submod>]` (`vault/menus/installed.py: record_installed_menu_mod`), and
`GET /api/mex/menus/installed` returns the map.

HUD typeface mods (`percent.py`) can cover the damage digits
(`hud:percent_font`), the READY/GO word banners (`hud:ready_go`), or both.
An install writes every stored slot of the mod, so it is recorded under the
tab it was installed from (`{"slot": "percent_font"|"ready_go"}` in the
install body) plus every category the mod covers (`_mod_categories`).
Records written before this (every install filed under `hud:percent_font`)
are repaired on read by `percent.repair_hud_install_records`: a Ready/Go-only
mod moves to `hud:ready_go`, and a legacy full typeface fills an empty
`hud:ready_go`. Entries carry `categories` once repaired, so it runs once.

The CSS icon grid installs icon by icon (`install/<id>` returns a plan, then
`install/<id>/icon` per fighter). The record is written by the per-icon step
only when MexCLI succeeds, and counts the icons of that plan that landed, so
a failed install records nothing and a partial one reads "12 of 26 icons".

`MenuMode` re-reads `/menus/installed` whenever the open project changes
(`projectPath` from `MexPanel`) or `nucleus:project-changed` fires; it stays
mounted across project switches.

Each install also copies the mod's preview (downscaled PNG) into
`<project_dir>/nucleus_menus_previews/<menu>_<submod>.png` and records
`snapshot`/`snapshotUrl`; `GET /api/mex/menus/installed/preview/<menu>/<submod>`
serves it. The stored `imageUrl`/`screenshotUrl` still point at the live vault
item, so the panel tries the snapshot first, then those, then shows the name
placeholder (older records, or a deleted vault mod).

### HUD typeface slots vs the project file

`hud_verify.py` backs `GET /api/mex/menus/installed?verify=hud`. It decodes
the project's `IfAll.usd` with `--hud-textures export` (slots keyed
`root|kind|ordinal`, so the m-ex-only roots don't shift anything) and
compares the category's slots (percent = `DmgNum`/`DmgMrk`; Ready/Go = the
`ScInfCnt` word-banner mats in `WORD_MAT_ORDINALS`) picture by picture:

- with vanilla, decoded from the user's vanilla disc `IfAll.usd`
  (`ensure_vanilla_ref`); without one, only md5-identical slots (HUD
  manifest) count as vanilla;
- with the recorded mod: its stored slot pictures on its slots and vanilla
  on the rest of the category (so another mod's leftovers don't match).

Results: mod matches -> `installed`; every slot vanilla -> `vanilla`;
otherwise `custom`. Installs store `file_stat` (mtime_ns, size); the first
check that sees the file unchanged since then stores `hud_fingerprint` (the
category's non-vanilla md5s), which still recognizes the install if the vault
mod is edited later. A record whose vault mod is gone, or was edited after
the install and has no fingerprint, is trusted (`unverified`) unless the file
is vanilla. A failed export leaves the slot out and the panel shows the
record. `MenuMode` asks for it only on the HUD page, without blocking.

### Tolerant picture comparison (`menu_pixels.py`, `menu_exports.py`)

The tools re-encode pictures when writing (GX formats and palettes), so two
encodings of the same picture differ in bytes. Every file check compares
decoded pixels with `menu_pixels.same_picture`: colors premultiplied by
alpha; a match needs at most 1% of visible pixels more than 40/255 off and a
mean error within the re-encoding noise of the comparison (`reencode` 8,
`source` 16). The numbers come from real `IfAll.usd` round trips (table in
the module docstring): re-encoding stays under a mean of 5.4 (13.6 for
resized source pictures) with no far-off pixels, while another glyph, a
1px shift or a thicker outline puts 8-80% of pixels far off, and a recolor
of the category shows on its worst slot. `menu_exports.cached_export`
keeps each export under the temp folder keyed by path + mtime + size.

### Vanilla reset before a typeface install, and "Restore Vanilla"

Installing a Percent Font / Ready-Go mod first puts the categories it covers
back to vanilla, in the same `--hud-textures import` call
(`percent.hud_reset_keys` + `_vanilla_reset_replacements`): every slot of
the category plus whatever the previously recorded mod of that category
wrote elsewhere (a timer glyph), never `Stc_scemdls` stock icons or m-ex
`Eblm_matanim_joint` emblems. So typeface B over A leaves none of A (an
emblem, a READY banner B doesn't have). The vanilla pictures come from the
user's vanilla disc `IfAll.usd`; without one the mod still installs as
before and the message says the old textures weren't cleared.

`POST /api/mex/menus/percent/restore-vanilla {slot}` runs the same reset
alone for one category and clears its record (the CSS background restore
pattern). The import re-encodes into the slot's current format, so a slot a
mod moved to RGB5A3 comes back as the vanilla picture in RGB5A3, not
byte-identical: the file check above reads it as vanilla (verified on a
real m-ex project: vanilla -> A -> B -> W -> restore, stock icons and
emblems byte-identical throughout).

### The other slots vs the project files (`menu_checks.py`)

`?verify=css` / `?verify=sss` (and `hud` for the pause screen) read the
other slots the same way: the file's picture(s) compared with the vanilla
disc file (`ensure_vanilla_ref`) and with the recorded mod, verdict shared
through `menu_checks.classify` (record matches -> `installed`; vanilla ->
`vanilla`, `stale` if a record exists; otherwise `custom`; a vault mod
edited after the install or gone -> trust the record as `unverified`).

| Slot | Read from | Compared |
|---|---|---|
| `hud:pause_screen` | `GmPause.usd`, `--pause-screen export` | all 11 textures; a picture mod = the two 88x72 main slots |
| `css:doors` | `MnSlChr.usd`, `--css-doors export` | the 128x200 door textures; the mod's `door.png` stretched under the file's alpha mask, pixels where the mod picture is transparent left out |
| `css:icon_grid` | the project's `assets/` icon PNGs (`data/fighters/*.json` `cssIcon`) | vanilla: every vanilla fighter vs the vanilla `MnSlChr` `--css-icons export`; mod: only the icons that grid installed (other fighters keep whatever they had) |
| `css:background`, `sss:background` | `MnSlChr.usd` / `MnSlMap.usd`, `--bg-textures export` | geometry fingerprint (`model_md5`: joint flags + polygon display lists) and the background's textures; installs copy the model verbatim, so the same background gives the same hash |

`--bg-textures export <file> <dir>` is an additive, read-only HSDRawViewer
mode (`HSDRawViewer/Tools/Melee/BackgroundTextures.cs`, dispatched from both
`HSDRawViewer` and `HSDRawHeadless`): it accepts a MnSlChr / MnSlMap or a
`background.dat` bundle. With an older HSDRawViewer the export fails and the
background slots fall back to the record. The vanilla CSS background has no
textures (22 joints, 97 polygons), which is why the geometry fingerprint is
needed.

Verified on a copy of a real m-ex project (2026-09-27): pause picture
install -> installed; door A -> installed, a record naming A while the file
has B -> custom; icon grid via MexCLI -> installed; CSS background install
-> installed, Restore Vanilla Background -> vanilla; SSS background install
-> installed. On 13 real projects every untouched slot read vanilla and the
two projects with a custom CSS background read custom.
