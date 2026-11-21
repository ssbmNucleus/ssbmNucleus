# Vanilla Asset Policy

**The rule: SSBM Nucleus does not ship Nintendo game data. Every vanilla asset
comes from the user's own Melee ISO, extracted on their machine at first run.**

The owner's rule since 2026-11-19, in his words: "NO ASSETS THAT CAN BE
EXTRACTED FROM THE GAME SHOULD SHIP IN THIS." It is about the desktop app.
The phone app and the website are separate builds and are no reason to bundle
anything here. What still ships is listed in §2.

This document records how that works, what is deliberately bundled anyway, and
where the enforcement currently has holes. Written 2026-08-18 during 0.7.0
release prep, after an audit found retail data still shipping in the 0.7.0
installer despite the July cleanup.

---

## 1. Architecture: bring your own ISO

`backend/shared/vanilla_extract/first_run_setup.py` runs once, against the ISO the user supplies. It
shells out to `mexcli create` to extract the ISO into a temp project, then
populates the user's writable directory from it.

The phases, in order:

| Phase | What it does |
|---|---|
| 0 | Copy bundled assets (Sheik PNGs only — see §2) — production builds only |
| 1 | Extract the ISO via `mexcli create` into a temp dir |
| 2 | Copy per-costume assets: the costume `.dat`, `csp.png`, `stock.png` |
| 2a | Copy the CSP reference bank (28 fighter-data and 124 costume DATs, flat) into `<storage>/test-base/files`, listed in `<storage>/test-base/csp-references.json`. `generate_csp` reads every vanilla DAT it needs from here |
| 2b | Stage built-in custom fighters from the extracted game |
| 3 | Copy stage images |
| 4 | *Removed in 0.9.0.* It copied 27 `Pl*Nr.dat` into the install's `processor/csp_data/`. Nothing read them, and the write broke the macOS code signature and failed on the read-only AppImage. Setup writes nothing inside the install |
| 4b | Derive the Slippi bone-reference tables straight off the disc |
| 4c | Derive the menu reference art from the temp project: HUD glyphs and slot manifests, pause textures, series emblems, and every versus stage's select-screen icon and banner (`menu_refs.py`) |
| 5 | Extract menu sounds from `main.ssm` via HSDRawViewer |
| 5b | Seed each character's pristine voice/SFX bank into the vault |

**Portraits, stock icons, costume DATs, stage images and menu sounds are all
produced here, from the user's own copy of the game.** They are not shipped.
This is the part of the design that works, and it should be the destination for
anything currently bundled that doesn't have to be.

Two later steps follow the same idea outside setup:

- **Project open** derives whichever menu-reference sets are still missing
  (`core.state.set_project_path` → `menu_refs.missing_sets()`), so an install
  made before a set existed heals itself. It never re-derives a set that
  exists, because the opened project may be modded.
- **App start** does the same from the known vanilla ISO
  (`menu_refs.derive_missing_at_start`, a background thread 20 s after start;
  not in worker children): from the pristine test base when one is already
  built for that ISO, else from a temporary `mexcli create` project (about
  1.4 GB in the temp folder, deleted afterwards; skipped below 3 GB free).
  A pass that cannot finish records the ISO and the sets it still lacks in
  `menu_refs/.iso_attempt.json` and is not repeated for that pair; a project
  open still tries. A pass takes only the sets still missing once it holds the
  derivation lock, so a project open and the start pass never overwrite each
  other's set.
- **DAS install** rebuilds each alternate-stage loader from the user's own
  vanilla stage root with a shipped xdelta patch
  (`projects/install/das_loaders.py`).

## 2. What is deliberately bundled, and why

**What still ships that came from the game** (owner's call, 2026-11-19). These
are small, and none of them is a file you could extract from the disc:

| Item | What it is |
|---|---|
| `frontend/public/extras/pictograms/*`, `extras/references/*` | Extras effect pictograms and reference screenshots: captures of gameplay |
| Watch Lite's data tables (`tracker/tools/charmaps.json` and friends) | Numbers, partly read from RAM, which no extraction can reach |
| `backend/assets/hud_vanilla/manifest_{usd,dat}.json` | IfAll slot fingerprints (dimensions, formats, md5s), not pictures |
| `utility/DynamicAlternateStages/*.xdelta` | Six patches, one per DAS loader: only what DAS changed, applied to the user's own vanilla stage root |

Beside these, Sheik's portraits ship and are not game data at all (below), and
neither is `backend/data/clone_engine.dat` (m-ex code). Both are load-bearing;
don't "clean them up".

**Sheik portraits** — `utility/assets/vanilla/Sheik/**/*.png`

Vanilla Melee has no separate Sheik portraits, so there is nothing in the ISO
to extract. These are custom-authored artwork. `PRESERVE_CSP_CHARACTERS =
["Sheik"]` makes Phase 2 skip Sheik so extraction can't overwrite them, and
`_copy_bundled_sheik_assets()` stages them in Phase 0.

Note `.gitignore:61` excludes `utility/assets/vanilla/Sheik/**/*.dat` — the PNGs
are ours, any `.dat` in there would not be.

**Menu sounds are NOT an exception** — corrected 2026-08-19

An earlier revision of this document claimed bundled `.wav` copies under
`utility/assets/vanilla/sounds/` shipped as a reliability net beside Phase 5's
extraction, citing `_copy_bundled_sounds()`'s own docstring.

That is not what happens. `retail-audio` scans clean on all three platforms: no
stage manifest copies `utility/assets/vanilla/sounds`, only
`utility/assets/vanilla/Sheik`. The bundled sounds are a **dev-tree artifact**,
and `_copy_bundled_sounds()` is a no-op in packaged builds. Phase 5 extraction
from the user's `main.ssm` is the only path that runs for real users, and the
owner has confirmed (2026-08-19) that it is reliable and no fallback is wanted.

So Sheik's portraits are the *only* deliberate bundling exception. Do not
"restore" the sound fallback on the strength of that docstring — the docstring
describes an intent the build never carried out.

## 3. Enforcement

As of `8c218db` (2026-08-18) the rules live in **one** place and all three
platforms run them.

- `tools/build/ship_rules.json` — declarative rules. `stage[]` (per-platform
  copy manifest), `scrub[]` (what is deleted *from the stage*), `verify[]`
  (critical artifacts that must survive), `embedded_roots[]` (trees PyInstaller
  folds into the exe), `detect[]` (categories and severities). Every rule
  carries a `why`.
- `tools/build/ship_guard.py` — stdlib-only engine, subcommands
  `stage` / `scrub` / `scan`.

`build.bat`, `build-linux.sh` and `build-macos.sh` all now stage → scrub →
verify → scan → `electron-builder --projectDir <stage>`. `mex_backend.spec`
imports its exclusions from the same rules instead of keeping a second copy.

`scan` reads `.asar` archives and the backend exe's embedded trees, so it works
on shipped artifacts and not just on stages. `stage --rehearse` validates rule
edits in seconds without a full build. `scrub` refuses to touch any directory
lacking the `.nucleus-package-stage` marker.

### Severities

- **BLOCK** — no override exists. Retail game data and unreleased content.
- **REVIEW** — assets awaiting a disposition decision (§4). Fails the build by
  default. `NUCLEUS_ALLOW_UNRESOLVED_ASSETS=1` downgrades REVIEW for a local
  build and stamps it *"FOR LOCAL USE ONLY. DO NOT PUBLISH."* A release build
  must be green **without** the override.
- **NOTE** — reported, non-blocking. Currently the shipped HSDLib source tree.

### How this was allowed to happen

Worth recording, because the failure was in the *check on the check*.
`preflight.py` verified only that `build.bat` mentioned the guard. It never
looked at `build-linux.sh` or `build-macos.sh`, so those two shipped unguarded
from the day they were written until `8c218db`. Preflight now asserts that all
three scripts both stage and scan.

Until that fix, any audit of the Windows installer was a floor rather than a
ceiling for Linux and macOS — the AppImage was confirmed to carry 6.1 MB of
`csp_regression/cases/*.dat` and `promo/randall.mp4` (inside `app.asar`) that
Windows scrubbed away.

## 4. Known gaps (as of 2026-08-18)

Found by audit against the real shipped 0.7.0 Windows installer and an
extracted AppImage. Ships on all three platforms unless noted.

| Asset | Size | Assessment |
|---|---|---|
| `frontend/dist/css_template.png` | 91 KB | Melee Character Select Screen artwork — a **screenshot**. **Resolved 2026-11-19** — rendered from the user's own `MnSlChr`, see below |
| `frontend/dist/sss_template.png` | 176 KB | Stage Select Screen artwork — a **screenshot**. **Resolved 2026-11-19** — rendered from the user's own `MnSlMap` |
| `csp_data/Sheik/{IntroL,IntroR,NeutralB}.dat` | ~10 KB | Byte-exact retail. `NeutralB.dat` is a contiguous slice of `PlSkAJ.dat` at offset 394,144 |
| `csp_data/Young Link/Wait.dat` | 11.8 KB | 100% of sampled blocks verbatim in the retail ISO |
| `frontend/dist/extras/pictograms/*.png` | 1.1 MB | 84 cropped in-game effect frames |
| `CostumeValidator/bin/*.bin` | 1.3 MB | 159 per-bone transform tables extracted from retail `Pl*.dat`. **Resolved** — derived at first run |
| `utility/DynamicAlternateStages/` | 233 KB | Community loader stages, but built by modifying vanilla files — `GrPs.usd` is 84% verbatim retail blocks. The old "custom MOD stages, not vanilla rips" allowlist asserted otherwise and has been retracted. **`GrPs.usd` resolved 2026-11-19** — ships as an xdelta patch; the five hooks stay (owner's call) |
| bundled menu-sound `.wav`s | — | Corrected: never shipped. See §2 |
| `backend/assets/series/*.png` | — | `custom_characters.py` describes them as "icons exported from a vanilla project". **Resolved** — copied from the user's own project at first run; tracked copies deleted 2026-11-19 |
| `backend/assets/hud_vanilla`, `pause_vanilla` | — | Vanilla HUD and pause-screen imagery. **Resolved** — derived at first run; tracked copies deleted 2026-11-19 |
| `csp_data/Wolf/Wolfen/` | 5.4 MB | Star Fox model, not Melee. Provenance unknown; dev scratch either way |

The last three were found only after `ship_guard.py` learned to read the
backend exe's embedded trees — they are folded into `mex_backend` by
PyInstaller, so no filesystem scan of the stage could ever have seen them.
Note `texture_regions` is deliberately *not* flagged: it is coordinate JSON,
not imagery.

The per-platform asymmetry in `utility/assets/stages/*.png` — shipped on Linux
and macOS, never staged on Windows — is settled: Windows won. See *Resolved*
below.

### Why the Sheik and Young Link DATs exist

They are dev scratch from CSP pose work, not a design decision.

Every character directory under `csp_data/` holds exactly one `.dat` — their
`Pl<XX>Nr.dat`, which `.gitignore:66` keeps out of a clean clone. Only two
characters have more, and both sit next to leftover scratch files:

```
Sheik/        IntroL.dat  IntroR.dat  NeutralB.dat   + test.anim    + CSP2.yml
Young Link/   Wait.dat                               + test1-3.anim
```

Someone hand-tuned poses on these two characters (Sheik's `NeutralB` is the
needle-charge pose, `IntroL/R` the intros, Young Link's `Wait` the idle) and
left the source animations behind. **No code references any of them by name.**

They survived the July cleanup because of the exclusion rule's own wording:

```gitignore
# Keep animation files (.anim), scene files (.yml), and images - only exclude vanilla Pl*.dat
utility/tools/processor/csp_data/**/Pl*.dat
```

The intent was to keep `.anim`, `.yml` and images. A retail `.dat` that isn't
named `Pl*` was never considered. Same root cause as the `Wolfen` model: the
filter describes what to drop, not what is allowed.

### Disposition

Each gap needs one of four answers. Extraction is the default; reach for the
others only when it genuinely can't work.

- **Extract at first run** — the ISO contains it, so Phase 1-5 machinery
  applies. Fits the animation DATs and the `CostumeValidator` tables, both now
  done. It does **not** fit the CSS/SSS templates: the guess that they were
  `MnSlChr`/`MnSlMap` textures was wrong. They are rendered from those files
  instead (§4, *Rendered since 2026-11-19*).
- **Ship as a patch** — for files derived from vanilla by modification rather
  than extraction. `DynamicAlternateStages` fits; the app already ships xdelta
  and uses patching elsewhere.
- **Delete** — for anything nothing reads. The Sheik/Young Link DATs, the
  `test*.anim` scratch, and `Wolfen` are all in this bucket.
- **Replace** — for anything that isn't in the ISO at all. The pictograms are
  captures of running gameplay, not files; there is nothing to extract, so they
  must be redrawn or dropped.

### Accepted exceptions (owner decision, 2026-08-18)

These ship knowingly. Recorded so the decision isn't re-argued every audit.

| Asset | Why it stays |
|---|---|
| `retail-effect-pictograms` | Captures of running gameplay, not ISO files. No extraction path exists at any price |
| `dynamic-alternate-stages` | Load-bearing for the DAS feature. Since 2026-11-19 (late) only the six patches; no loader ships as a file |
| ~~`backend/assets/vanilla_stages/Gr*_{banner,icon}.png`~~ | **No longer an exception** (2026-11-19): extracted from the user's own game, see *Resolved*. The mobile argument does not apply to the desktop build |
| `utility/assets/vanilla/Sheik/**/*.png` | Custom-authored — vanilla Melee has no Sheik portraits. See §2 |
| ~~bundled menu-sound `.wav`s~~ | **Not an exception** — they never shipped. See §2 |

The 2026-08 reasoning for these was that extraction only helps where a user's
ISO is reachable, and the phone and website render without one. The owner
overruled that for the desktop app on 2026-11-19: those are separate builds,
and the desktop installer bundles nothing on their behalf.

### Deferred to a later release (owner decision, 2026-08-19)

Three categories were deferred past 0.7.0 at NOTE severity. Two turned out to be
a few seconds of work each and were fixed on 08-19 (see *Resolved*); the third
could not be extracted at all and waited for a renderer, added on 11-19.

| Asset | Status |
|---|---|
| `retail-bone-tables` | **Fixed** 2026-08-19 — derived from the user's disc, byte-exact. Back to REVIEW |
| `retail-hud-and-pause` | **Fixed** 2026-08-19 — derived from the user's project, byte-exact. Back to REVIEW |
| `retail-menu-artwork` (css/sss templates) | **Fixed** 2026-11-19 — not extractable, but rendered from the user's own `MnSlChr`/`MnSlMap` (HSDLib `--menu-render`). The screenshots are deleted and BLOCKed as `retail-menu-backdrops`; `retail-menu-artwork` keeps only `MnSlChr*` at NOTE |

The lesson worth keeping: the deferral note said the bone tables "need deriving
from the user's own `Pl*.dat` at first run" as though that were the hard part. It
was ninety lines and one second of runtime. What was actually hard was the one
category nobody had a concrete theory about: it took a new render mode in the
HSDLib fork.

### Resolved

`csp_data/Sheik/{IntroL,IntroR,NeutralB}.dat`, `csp_data/Young Link/Wait.dat`
and `csp_data/Wolf/Wolfen/` were deleted in `31fdbd2` — dev scratch from CSP
pose work, verified unreferenced. The first four were byte-exact retail
animation data and the most legally unambiguous items in §4.

**`retail-stage-art`, the `utility/assets/stages/*.png` half** (`4fdc196`). The
six tourney-stage SSS icons no longer ship anywhere. The Linux and macOS stage
entries are gone and the `extraResources` block in `package.json` with them, so
the asymmetry resolved toward what Windows has always done. Phase 3
(`_copy_stage_images`, driven by `STAGE_ICONS`) writes the identical
`icon_0NN.png` into `PROJECT_ROOT` from the user's own ISO, and every consumer
already reads `PROJECT_ROOT` first — `assets.py serve_vanilla`, `das.py`'s
default screenshot, and `stage_icon` (now `tracker/routes/icons.py`), which never had a
bundled fallback at all. The `BASE_PATH` fallbacks in the first two are now dead
guards; their comments say so. Evidence the fallback was never load-bearing: the
shipped 0.7.0 AppImage carries exactly *one* of the six (`final destination.png`,
the only one tracked in git — the other five are `.gitignore`d extraction
output), so five of six have been falling through to `PROJECT_ROOT` in
production all along. That last tracked file is now untracked as well. The
detect glob still covers `utility/assets/stages` so a re-added copy trips.
`backend/assets/vanilla_stages/*` remains in this category at REVIEW — a
separate, owner-accepted item.

**`retail-portraits-and-stocks`** (`8bcb5b5`) — the category now scans **clean**.
The 63 `csp_data/*/{DEFAULT,stock,csp_Pl*,css_icon}.png` retail rips are deleted
by a new `csp-data-portraits` scrub rule, and `csp_data_excluded()` was
generalised from "the `csp-data-roster` rule" to "every scrub rule targeting
`csp_data`" so `mex_backend.spec` drops them from the PyInstaller embed by the
same rule — the stage copy and the embedded copy cannot diverge. Nothing in the
app read them: the live path is `backend/shared/rendering/costume_assets.py` over
`VANILLA_ASSETS_DIR` (a `PROJECT_ROOT` dir, filled by Phase 2 from the user's
ISO), and `generate_csp` only reads `.anim`/`.yml` from those folders. The one
reader is `app/utility/tools/processor/generate_stock_icon.py`'s `find_stock_template` /
`find_default_csp`, reachable only from that script's own command line — dev
tooling the backend never imports and the installer never ships. The files stay
in the private repo for that tooling.
Sheik's `utility/assets/vanilla/Sheik/**` PNGs are untouched and now carry an
`except_paths` exemption naming them specifically; any *other* character folder
appearing in that tree still trips the category.

**`retail-bone-tables`** (`93795c6`) — the category now scans **clean**.
`utility/tools/processor/bone_tables.py` is the exact inverse of
`costume_validator._walk`: same depth-first order, same record layout, so it
*writes* the tables the validator reads. `backend/shared/vanilla_extract/bone_refs.py` drives it
straight off the disc — `vanilla_refs.list_files_in_iso` returns an FST offset
and size per file, so each of the 181 costume DATs is one seek and one bounded
read, nothing is extracted to disk, and the whole 59 MB pass takes **~1 second**.
The output lands in `<storage>/test-base/bone-refs`.

Generating from a retail 1.02 disc reproduces **all 159 shipped `.bin` files
byte-for-byte** — `tests/backend/test_bone_tables.py` asserts exactly that.
Byte-exactness is the property that matters here: the validator copies these
transforms verbatim into people's costumes, and a wrong one desyncs them online.
The disc is also a *better* source than the CSP reference bank, which covers only
the 124 roster costumes: it reaches the 35 symbols no fighter's costume list
mentions — Kirby's 25 copy-hats, the two wireframes, Master and Crazy Hand,
Sandbag, Giga Bowser.

First-run setup derives them in Phase 4b. Installs made before that have none, so
`core.config` registers a provider with `costume_validator.set_ref_dir_provider`
that generates them the first time a costume is validated. That fallback is not
optional politeness: a validator with *no* references does not error, it reports
every costume netplay-safe — precisely the silent failure 0.6.4 shipped. The spec
no longer embeds `bin/`, and the new `bone-reference-tables` scrub rule strips it
from the electron stage; the in-tree copies stay in the private repo as the
test's oracle.

**`retail-hud-and-pause`** (`02b2ece`, `2f06503`) — the imagery now scans
**clean**. All of it was an export of something the user already owns, made by a
tool the app already ships. `backend/shared/vanilla_extract/menu_refs.py` runs `HSDRawViewer
--pause-screen export` on `GmPause.usd`, `--hud-textures export` on both `IfAll`
regions, and copies the series emblems out of the project's own
`assets/series/`, into `utility/assets/menu_refs`. **3.8 seconds**, and every
file comes out byte-identical to the copy that used to ship: 11 pause textures,
21 glyph previews, 16 emblems and both slot manifests
(`tests/backend/test_menu_refs.py`).

The source must be a **`mexcli` project, not the raw disc**. m-ex adds an
`Eblm_matanim_joint` root to `IfAll`, so a project's export has 1349 slots where
the disc's has 1333 — and `percent._build_replacement_spec` maps a mod's stored
slots onto *global* texture indices in the project's `IfAll`. A disc-derived
manifest would describe a file the app never writes to. So Phase 4c derives from
the temp project, and `core.state.set_project_path` derives on project open,
which is how existing installs self-heal: the pause and HUD editors refuse to run
without a project loaded anyway, so that hook fires exactly when the art is about
to be wanted.

The three consumers resolve derived-first, bundled-fallback, **per call** rather
than at import — a module-level `Path` constant would pin the pause editor to a
read-only `_MEIPASS` path forever, even after derivation landed.

One deliberate exception: `hud_vanilla/manifest_{usd,dat}.json` and
`assets/pause_vanilla/manifest.json` still ship. They are dimensions, formats and a
raw-buffer md5 per slot — fingerprints and coordinates, not imagery, the same
call already made for `texture_regions` — and keeping them means the *install*
path, the one that can mis-map a mod into the wrong `IfAll` slots, never depends
on runtime derivation. The detect globs were narrowed to `*.png` to say so, and
`embedded_roots` grew an `exclude` list because `backend/assets` reaches an
installer only through the PyInstaller embed, where there is nothing for `scrub`
to delete. That `exclude` is the one place the guard trusts the spec instead of
looking; both sides read the same category, and the comment says not to use it
for a tree that really ships.

**2026-11-19: the owner's rule, applied.** "No assets that can be extracted
from the game should ship in this" (desktop app; the phone and website are
separate builds and no reason to bundle). What changed:

- **`retail-stage-art`, the `backend/assets/vanilla_stages` half** (`c78801b`).
  The 46 stage-select icons and banners rode inside the backend exe for
  Tracker's stage icons. `menu_refs` gained a fourth set, `vanilla_stages`: for
  each versus stage it reads the project's `data/stages/<internal id>.json`,
  checks the slot's root file is still that stage's, and copies its
  `assets/sss` icon and banner. From the pristine-base project all 46 come out
  byte-identical (plus the four legal stages' pictures). Tracker's
  `/stage-icon`, the stage-slot art route and the vanilla stage importer read
  only the derived copy; before it exists they answer 404 or leave the icon
  out. The mobile Tracker argument from 08-19 no longer applies: the phone is
  its own build.
- **Self-healing.** Opening a project derives the sets that are still missing
  (`missing_sets()`, `derive_menu_refs(..., only=...)`), and only those: a set
  taken from setup's fresh project is never overwritten from a modded one. An
  install that ran setup before this change gets its stage pictures at the next
  app start, from the known vanilla ISO (11-19; before that, only once it opened
  a project).
- **The tracked HUD, pause and series copies** (`554037a`). The 48 pictures
  and the pause manifest that stayed in the tree as a dev fallback are gone, and
  so is the fallback: `pause_dir()` and `series_dir()` answer from the derived
  copy only, and `hud_dir()` falls back to the two IfAll slot manifests, which
  still ship. Derived from a copy of the pristine-base project, all 97 tracked
  files these two changes deleted come out identical.
- **Stadium's DAS loader** (`2801d52`). `GrPs.usd` carried the transformation
  models (81% of its 32-byte blocks verbatim retail). It ships as
  `GrPs.usd.xdelta` (7.6 KB, made with the bundled xdelta3: `-e -9 -S none
  -A=`). `projects/install/das_loaders.py` rebuilds it from the user's own
  vanilla `GrPs.usd` (the project's root, `GrPs/vanilla.dat` after DAS, or the
  recorded ISO), checks SHA-256 on the source and the result, and caches it in
  `utility/assets/das_loaders`. A modded source is skipped by its checksum.
  The new `das-stadium-loader` rule BLOCKs a plain `GrPs.usd` beside the
  patch.
- **The other five DAS loaders** (later on 11-19). GrIz, GrNBa, GrNLa, GrOp
  and GrSt kept 13-73% of their vanilla roots. They ship as
  `<code>.dat.xdelta` the same way (6-8 KB each; no 32-byte block of any patch
  occurs in its vanilla root), each with its pair of SHA-256s in
  `das_loaders.PATCHED_LOADERS`. `das-stadium-loader` now BLOCKs every plain
  `.dat`/`.usd` in `DynamicAlternateStages`.

### Rendered since 2026-11-19: the CSS and SSS backdrops

`frontend/public/{css,sss}_template.png`, the backdrops the CSS and SSS layout
editors draw icons on, were 640x527 captures of the **running game** at
Dolphin's native NTSC framebuffer size (`css_template.png` carried the live
"4-man survival test!" banner). They were never textures: `MnSlChr` and
`MnSlMap` hold a *scene* (background and menu models, camera, two lights, fog),
and neither file has a texture near 640x527. So they could not be extracted,
only rendered.

HSDLib `v2026.11.19.1` added that render: `HSDRawViewer --menu-render <dat>
<out.png>` builds the select table's models, poses them at the screen's idle
state as the game's own setup code does (CSS: four closed `N/A` doors, no
character icons; SSS: background plus the frame model after its intro, no
icons, preview or stage name) and draws them through the file's camera, lights
and fog. Two renderer details made it match: per-node hidden joints (HSD hides
a joint's own meshes, not its children) and fog computed per pixel on eye depth
as GX does (the viewer's per-vertex fog turned the SSS backdrop plane solid
navy). Against the old screenshots the mean pixel difference is about 5 of 255;
what differs is run-time text the game's text engine draws (the rules banner)
and slight shading on the BACK corner and the door stripes.

`backend/shared/vanilla_extract/menu_backdrops.py` renders both from the
vanilla `MnSlChr.usd` / `MnSlMap.usd` (taken out of the recorded ISO by
`vanilla_refs.ensure_vanilla_ref`) into `utility/assets/menu_refs/menu_backdrops`,
stamped with the source's SHA-256 and a `RENDER_VERSION`, on demand at
`/api/mex/menus/{css,sss}/backdrop` and warmed at app start. Without an ISO or
a renderer, or after a failed render, the route answers 404 and the editors
draw a plain panel. The screenshots were deleted, and rule
`retail-menu-backdrops` BLOCKs them.

## 5. History

| Commit | Date | What |
|---|---|---|
| `079f215` | 2026-07-15 | Stop shipping Nintendo game data; extract from the user's ISO at first run. **Windows only** |
| `6358647` | — | Keep unreleased and developer-only content out of the installer |
| `0676aa5` | 2026-08-16 | `build.bat` strips `promo/randall.mp4` (Windows only) |
| `8c218db` | 2026-08-18 | Single-source `ship_rules.json` + `ship_guard.py`; all three platforms stage, scrub and scan; preflight checks all three scripts |
| `93795c6` | 2026-08-19 | Bone tables derived from the user's disc; `CostumeValidator/bin` stops shipping |
| `02b2ece` | 2026-08-19 | HUD, pause and series art derived from the user's project; only the slot manifests still ship |
| `31fdbd2` | 2026-08-19 | Delete the retail animation slices and the `Wolfen` dev scratch |
| `4fdc196` | 2026-08-19 | Stop shipping the six tourney SSS icons; first-run extraction is the only source |
| `8bcb5b5` | 2026-08-19 | Scrub the `csp_data` portrait/stock/CSS-icon rips from the stage **and** the `mex_backend` embed |
| `58a9791` | 2026-08-19 | Bone tables, menu artwork and HUD/pause deferred past 0.7.0 → NOTE |
| `2801d52` | 2026-11-19 | Stadium's DAS loader ships as an xdelta patch against the user's own `GrPs.usd` |
| `c78801b` | 2026-11-19 | Stage-select icons and banners derived from the user's project; `vanilla_stages` deleted; project open heals missing sets |
| `554037a` | 2026-11-19 | Tracked HUD, pause and series pictures and their fallback deleted |
| `606c857` | 2026-11-19 | `retail-stage-art`, `retail-hud-and-pause` and the new `das-stadium-loader` → BLOCK; CSS/SSS templates rechecked against the headless viewer: still not renderable, still NOTE |
| `674f11061` | 2026-11-19 | CSS/SSS backdrops rendered from the user's own `MnSlChr`/`MnSlMap` (HSDLib `v2026.11.19.1` `--menu-render`); the screenshots deleted; new `retail-menu-backdrops` → BLOCK |

The July work established the architecture and it is sound. `8c218db` closed
the two enforcement gaps — one platform out of three, and a pattern vocabulary
too narrow to see anything it wasn't told to look for. What remains is not an
enforcement problem but a set of product decisions: the REVIEW assets in §4
still ship, and each needs a disposition.

### Side effect worth knowing

Excluding retail data from the repo made the CSP regression suite less capable.
Its `vanilla_fox` and `vanilla_marth` cases skip because their fixtures are
gitignored Nintendo data, so two baselines silently stop running on any clean
clone. If those baselines matter, they need to come from first-run extraction
like everything else — otherwise the suite quietly shrinks.

## 6. Re-auditing

The audit that produced §4 worked by byte-matching candidate files against a
retail ISO — sampling non-uniform 128-byte blocks and checking what fraction
appear verbatim. That is the reliable test; filename inspection is not, as the
Sheik DATs demonstrate.

Audit the **built artifact**, not the source tree — unpack the NSIS
`app-64.7z` and parse `app.asar`, and extract the AppImage. The working tree
and the shipped payload differ per platform, which is the whole problem.

---

*Standing rule: when adding an exclusion, write down what is allowed, not just
what is dropped. Every gap in §4 came from a filter that enumerated the bad
and let everything else through.*
