# Changelog

All notable changes to SSBM Nucleus are documented here.

## 0.6.2

- **Mr. Game & Watch color creator** — G&W can finally have custom colors:
  "Create New Color" on his character page makes fill/outline color mods, and
  added color slots stay correct through add, remove, and reorder.
- **Duplicate-detection fix** — vault entries whose stored zip was deleted no
  longer "ghost-block" re-importing the same mod.
- **Giga Bowser stock icon** — the generated stock icon now crops around the
  face correctly.
- **Upload page polish** — the review step previews the post exactly as the
  website will show it, and "Upload another mod" resets the form cleanly.

## 0.6.1

- **Uploading fix** — publishing from the Upload tab to ssbmnucleus.net now
  works.
- **Stage music improvements** — stage and menu music are edited as weighted
  playlists.

## 0.6.0

### ✨ New
- **Classic mexTool character packages import directly as custom characters.**
  The `fighter.yml` package format most community fighters ship in — Shadow,
  Deoxys, Slippy, and hundreds of others — can now be dropped straight into
  the import button. The package is converted on the fly: costumes, CSS icon,
  sound bank, announcer call, victory theme, and the character's embedded
  move-logic tables (specials, taunts) all carry over. Packages nested inside
  a post's outer zip are found automatically, the best icon art shipped
  alongside the package is harvested (or one is generated from the first
  costume's portrait so the roster never shows a blank slot), and team-battle
  costume slots authored against a dev build are clamped so team mode can't
  break.
- **Vanilla-stage mods import as new custom stages.** A raw stage file for any
  non-tournament stage — Green Greens, Peach's Castle, Big Blue, Temple,
  Onett, and the rest — can now be dropped straight into the import button (or
  added from the website). Instead of replacing the original stage, the mod is
  added as a brand-new stage with its own stage-select entry, carrying the
  real stage's icon, music, sound effects, and stage logic (hazards, moving
  platforms, Banzai Bills...). The six tournament-legal stages still import as
  stage skins, exactly as before.
- **Sign in with your ssbmnucleus.net account.** The new Settings › Account
  card signs into the same community account used on the website (username or
  email), shows your avatar, and keeps you signed in between sessions. One
  account now works in both places.
- **Upload tab: build a website post from your vault.** A three-step flow for
  packaging mods for ssbmnucleus.net: pick mods straight from your vault (or
  drag in any files), fill in post details with category options derived from
  what you selected, and review the finished post. Actually publishing to the
  site goes live in an upcoming update — for now the flow is a full offline
  preview.
- **Menu music playlist editor.** The music button on the Fighters, Stages,
  and Menus screens now also edits the project-wide menu playlist — add any
  songs you like and weight how often each plays (vanilla is two songs at
  75%/25%).
- **Shield texture extras.** A new kind of effect mod that replaces the
  shield-bubble texture itself. Shield color still comes from the engine, so
  one texture mod restyles every player's shield without touching the tints.
- **Model Studio: real skin weights and a rig check.** AI-generated models are
  now rigged with Blender's bone-heat solver for much better deformation, and
  a rig-quality gate flags bad rigs before you waste time exporting them.

### 🚀 Improvements
- **The app now scales to your display.** The UI was designed on a 1440p
  monitor and looked off elsewhere; the window now picks a zoom factor from
  your display's resolution, and re-adapts when you drag it to another
  monitor. The embedded 3D viewers and the in-app Dolphin window stay
  pixel-aligned at every zoom level.
- **Vault layout polish.** The Stages home is a honeycomb of hexagons instead
  of a plain grid, all four mode homes line up at the same height, the
  character grid fills the page with bigger icons, and Upload-page costume
  rows show each costume's slot color as a named dot.
- **Settings page stability.** Sections live in fixed columns so expanding one
  card no longer reshuffles the whole page, and the danger zone is clearly
  marked.

### 🐛 Fixes
- **Big zip imports no longer silently drop most of their files.** A zip
  containing other archives (a whole character pack, an overnight batch)
  used to import only the loose files at the top level and ignore everything
  nested — now inner archives are unpacked two levels deep, with a summary of
  what was imported, auto-fixed, and skipped. Also fixed in the same pass:
  `.7z` archives import instead of erroring, "skip duplicates" actually skips
  for stages/patches/effects, and a file that tripped two confirmation
  dialogs at once (e.g. Slippi fix + duplicate) imported instead of silently
  failing.
- **Ice Climbers costumes from the website import correctly.** Website
  exports pair Popo and Nana in non-vanilla color combinations (say, Green
  Popo with Aqua Nana), which the importer refused to match up — a zip with
  exactly one of each now pairs them regardless of color.
- **Character detection works on more files.** The DAT parser misread any
  file that contains reference nodes, which silently defeated content-based
  character and color detection for those imports.
- **Patch files no longer balloon on rebuilt ISOs.** Creating an xdelta patch
  against a rebuilt ISO could degenerate to nearly the size of the full
  image; patches are now created with a full-image search window.
- **Hand-edited recolors render clean portraits again.** A re-exported skin
  that dropped a couple of model parts could defeat low-poly hiding, drawing
  the low-detail mesh on top of its CSP.

## 0.5.2

### 🐛 Fixes
- **m-ex builds no longer crash on the stage-select screen with current
  Slippi.** Slippi's October 2025 update made m-ex ISOs require the "Skip
  Slippi SSS" gecko code — without it, the game crashed the moment you opened
  the stage-select screen. Every exported ISO now bakes this code in
  automatically, so there's nothing to set up by hand.
- **Pokemon Stadium alternate stages no longer crash on load.** Dynamic
  Alternate Stage variants for Pokemon Stadium could crash the game the instant
  the stage loaded, depending on your Melee save's language — Pokemon Stadium
  is the one stage whose file the disc loads differently for English vs.
  Japanese saves, and a variant was only ever packed for one of them. Exported
  ISOs now include every Stadium alternate for both, so they load no matter
  which language your save uses. Existing projects fix themselves on the next
  export.
- **Effect recolors (Extras) now work reliably on any install.** Extras that
  recolor a texture — Mario's coins, Fox/Falco's Firefox charge fire, Bowser's
  fire breath, and others — could fail with a "no vanilla reference" error, and
  installing one effect mod on top of another could silently keep the old
  colors for some layers ("N layers could not be safely written"). The app now
  pulls the small reference files it needs straight from your saved vanilla
  ISO, so these installs apply cleanly everywhere.

### ✨ New
- **Bowser "Fire Breath Texture" extra.** With a recolored fire breath, the
  flames landing on the stage stayed orange, because sustained ground fire is
  drawn from a texture the color mod didn't touch. The new texture recolor
  brings the flame body itself in line with your color, so Bowser's fire is one
  consistent color from breath to ground.

### 🚀 Improvements
- **Settings › Updates polish.** The update indicator is now the same hexagon
  loader used throughout the rest of the app, and it holds its position instead
  of shifting when an update is found or while one downloads.

## 0.5.1

### 🐛 Fixes
- **Extras install no longer fails with "No module named 'ptcl_parse'"** in the
  installed app — the offset-relocation module was imported dynamically and
  never got bundled into the packaged backend, so any extra whose install hit
  the relocation guard (e.g. Bowser's Fire Breath on an already-modified
  effect file) errored out.
- **Installing an extra on top of another one now works.** The offset-safety
  guard only accepted untouched vanilla bytes, so a second install over a
  previous mod (or re-installing an edited mod, or restore-vanilla) silently
  skipped most layers. The guard now proves the write location structurally
  (neighborhood context + particle-bank identity) instead of by vanilla color
  value.
- **Fox/Falco Firefox tip and body colors no longer get stuck** — their
  matrix-format layers matched only the vanilla color, so they could be
  recolored exactly once and never restored.
- **The install page's "Currently in MEX" preview shows the actually-installed
  colors** — it previously fell back to a hardcoded white/blue pictogram for
  the fan-out effect extras.
- **Extras installs are atomic** — patches are applied to an isolated copy and
  swapped in only after every layer succeeded, so a mid-install failure can't
  leave a half-patched effect file.
- Skipped layers (unrecognizable file layout) are now reported to the user
  instead of the install silently claiming success.

## 0.5.0

### ✨ New
- **Recolor nearly every character's in-game effects.** The Extras system now
  covers the whole cast with 55 effect mods: lasers, Shine, and Firefox
  (Fox/Falco — including the charge-phase fire), Falcon Punch/Kick/Raptor
  Boost, Mario & Doc fireballs/cape/tornado/coins, Luigi, Samus screw
  attack/missiles/charge shot, Ness PSI/PK Thunder/PK Fire, Pikachu & Pichu
  thunder and jolts, Mewtwo, Zelda & Sheik, Bowser's fire breath, Jigglypuff's
  sing notes, Ganondorf's warlock/wizard's foot/gerudo, Ice Climbers,
  Link & Young Link spin attacks, Kirby stone + five copy-ability recolors,
  Marth/Roy/Link sword trails, and cast-shared common fire/flash/electric.
  Every mod was verified in-game frame-by-frame.
- **Redesigned extras editor.** Simple mode recolors the whole effect with one
  picker while preserving each layer's brightness; Advanced mode shows a card
  per effect element (Main Colors, Trail, Dots, ...) with in-game-cropped
  pictograms — no more cryptic offset names. One preset row, clickable color
  swatches, and live previews that match what actually renders in game.
- **Fox and Falco laser mods can now recolor the beam's white center line.**
  The laser editor gained "Center Line" and "Center Tip" pickers (the preview's
  center line — previously always white — now follows your color). Existing
  saved laser mods keep their behavior: the line stays vanilla white unless
  you set it.
- **Bulk CSP generation** — regenerate portraits for every costume of a
  character in one click.
- **Wiki overhaul: 7 new pages** covering previously undocumented features
  (Custom Characters, Custom Stages, Menus & Select Screen Mods, Sound Mods,
  Skin Creator, Test In Game, ISO Scanning), plus stale pages brought up to
  date with current behavior.
- **Boot-time setup health check.** The app now validates your saved vanilla
  ISO path on startup (exists, right size, GALE01 header) and shows a
  dismissable "re-run setup" notice if something's off.

### 🚀 Improvements
- **The vault now runs on a real database.** The vault index (costumes, stages,
  custom content, bundles) moved from the single `storage/metadata.json` blob
  to SQLite (`storage/vault.db`) — concurrent writes are safe across processes,
  and it lays the groundwork to eliminate list-position ordering bugs. Migrated
  automatically on first launch with a backup and a round-trip-validation check
  (falling back to JSON if anything looks wrong); `metadata.json` is kept in
  sync as a live backup and remains the portable format for vault
  backups/exports. Set `NUCLEUS_VAULT_DB=0` to stay on JSON. See
  `docs/VAULT_SQLITE_MIGRATION.md`.
- **Much faster portrait generation.** Headless CSP renders go through a
  persistent worker pool instead of spawning a fresh renderer per portrait —
  around 9.5x faster on batch renders, byte-identical output.
- The skin creator's costume-select step now renders as a normal in-app page
  under the header instead of a fullscreen takeover.

### 🐛 Fixes
- **Custom Firefox/Firebird mods now apply ALL their layers when installed.**
  Newer up-B color layers (small trail, dots, charge lines, flare) were
  silently skipped during install/export when the app's dynamic offset
  detection was active — mods saved with those colors only partially applied.
- **CSP/portrait generation no longer steals your keyboard focus.** Every
  headless render (generating CSPs, stock icons, HD portraits, the skin-lab
  viewer) used to yank the foreground away from whatever you were typing in —
  making the app unusable for writing AI prompts while portraits generated.
  The renderer's internal OpenGL window force-focused itself on creation; it
  is now blocked from activating at all (with an instant hand-back safety net),
  and the full CSP regression suite confirms renders are pixel-identical.
- **Sword trail extras (Marth, Roy, Link, Young Link) now recolor the trail
  correctly.** The editor previously offered three colors (Main / Secondary /
  Edge), but the game's trail is actually a two-color ribbon — one color along
  each edge of the arc, fading out toward the tail — and two of the old
  "color" bytes were really the trail's transparency settings, so custom
  trails could come out with a reversed fade and mostly-wrong colors
  (vanilla Marth's trail is cyan-to-white, not red/yellow/white). The editor
  now has Inner Edge / Outer Edge pickers and the preview matches what
  actually renders in game. Verified frame-by-frame in-game on Marth.
- **The character page's "Available to Import" list now matches the vault's
  order.** Costumes you filed into a folder (e.g. an "Animelee" folder) were
  grouped together in the vault but showed up scattered in raw import-order on
  the character page, so the two screens disagreed. The import list now orders
  costumes exactly like the vault — folder members grouped where the folder
  sits — just as a flat list, without the folder headers. Ordering only; no
  costumes are added, removed, or changed on disk.
- **Mr. Game & Watch portraits and stock icons recolor correctly.** Team-color
  and custom G&W costumes get his signature outline rebuilt in the portrait
  pipeline (it used to project as a gray blob), and his stock icons are
  recolored from the vanilla icon instead of rendered.
- **Some imported costumes no longer render with flat-grey armor or
  near-black bodies in portraits.** A color-mixing operation (RGB_MASK) in the
  CSP shader was implemented wrong; costumes using it (e.g. Marth "Lyn",
  some Mario imports) now match the game. Re-render CSPs to refresh existing
  portraits.
- **Reordering Ice Climbers costumes no longer desyncs Popo and Nana** — and
  reordering Peach no longer silently corrupts Nana's costume order (the
  pairing logic pointed at the wrong character slot).
- **Exported ISOs are always valid even if a Stadium stage folder still has
  legacy `.usd` alt files** — they're healed to `.dat` names at ISO pack time
  so the in-game alt loader accepts them.
- **Bundle/patch export fixes** for modded-vanilla content: Red Falcon,
  Fox's blaster, Pichu multi-slot costumes, and Ice Climbers costumes with a
  modded Nana.
- Fixed a race that could briefly leave the vault index partially written
  during imports.

### ⚙️ Internal
- Added a backend pytest suite + GitHub Actions CI that runs it.
- Docs audit (ARCHITECTURE/API_REFERENCE now cover all blueprints and hooks;
  stale claims removed; `docs/DOCUMENTATION.md` defines the doc tiers and ship
  checklist) and a dead-code sweep (17 finished one-off probe scripts, orphan
  component, 93 tracked debug PNGs).
- One-shot release script (`scripts/build/release.bat`): tests → build → CSP
  regression → tag → publish to R2 + GitHub.

## 0.4.3

### 🐛 Fixes
- **Character-select portraits render imported costumes correctly.** Costumes whose
  eyes were drawn black/empty (Sonic, Wario and similar imports) now composite their
  eye textures properly, and replaced-model costumes no longer show low-poly geometry
  poking through. Regenerate CSPs to refresh existing portraits.
- **Costume accessories show up in portraits.** Attached hats and hair now sit on the
  model — e.g. Jigglypuff's nurse hat and the Falco-slot's long hair.
- **Pokémon Stadium custom stages no longer crash on boot** (caused by legacy
  alt-file extensions).
- **Reordering DAS stage variants no longer fails** with "Invalid fromIndex or
  toIndex" when an on-disk variant wasn't in the vault metadata.

### 🚀 Improvements
- **Fox and Falco's blaster renders as the real 3D model in portraits.**
- **Faster texture-pack exports.** HD portraits now render in parallel, sized to your
  machine's CPU, instead of one at a time.
- **Automatic Animelee detection** when organizing the vault.
- HD portraits are cached for bundle/patch exports, so repeat exports are instant.

### 🔧 Changes
- Stage and character names are hidden in the grids for a cleaner look.
- Bug-report zips no longer count Dolphin distribution files as Slippi logs.
- More robust Dolphin controller-pipe connection during in-game tests.

## 0.4.2

### 🐛 Fixes
- **Character select portraits render alt costumes correctly.** Recolor/alt
  costumes were drawn with the default costume's low-poly mask, so accessories
  vanished or low-poly geometry poked through — Pikachu's blue/green hats were
  missing and the red cap showed an artifact, Pichu's backpack/cheeks were wrong,
  and Peach's Daisy sleeves were blocky. Each costume now uses its own visibility
  data. Regenerate CSPs to refresh existing portraits.
- **Jigglypuff's costume hats now show up in portraits.** Hats that ship as a
  separate model are spliced into the render and follow the posed head.
- **Merging a vault backup no longer corrupts custom characters you already have.**
  A conflicting item is now kept entirely as-is — the backup's copy of it (and any
  stray extra files) is skipped — instead of leaking files into your version. The
  merge also shows a report of what was added vs. kept.

### 🚀 Improvements
- **Vault restore now shows live progress.** Importing a vault backup displays an
  upload bar and then a per-file extract/merge status instead of an indefinite
  wait with no feedback.
- CSP rendering uses two-sided lighting so back-facing surfaces no longer go dark.

### 🔧 Changes
- Stages imported without a bundled screenshot no longer boot Dolphin to capture
  one during import. Use the bulk DAS "capture screenshots" flow instead.

## 0.4.1

### 🐛 Fixes
- **Ice Climbers no longer crash in Classic mode and online.** Nana's intro/result
  demo animations were exported empty, which made her T-pose on the VS banner and
  crash the game when starting a 1P or netplay match. Existing projects are repaired
  automatically on the next export.
- **Imported Jigglypuff costumes no longer crash the game.** The importer grabbed
  Jigglypuff's hat model (1 joint) instead of the body (50 joints), which crashed on
  load. Re-import affected Puff skins to fix existing ones.

## 0.4.0

The big update is finally here.

### ✨ New features
- **In-app updater** — future versions update from inside the app (Settings → Updates)
- **In-game testing** — test skins in game directly from the app
- **Stage screenshots** — capture clean in-game previews for stages
- **Custom characters & stages** — import, manage, and install them
- **Menu mods** — CSS + grid editor, SSS + grid editor, and HUD
- **Game banner editing**
- **Sound mods & stage music**
- **ISO scan** — pull every skin / stage / custom character / custom stage from any
  ISO into your vault (skips what you already have)
- **Start a project from a vanilla Melee patch** in your vault (Animelee, etc.)
- **Pose manager** improvements
- **Experimental stock-icon generator** (still janky)

### 🚀 Improvements
- Better loading screens and feedback
- Faster batch skin installation
- Better mod importing & project management
- **Exporting**: improved CSP compression, automated texture-pack scanning, and
  create/launch xdelta patches inside the app

### 🐛 Bug fixes
- Pokémon Stadium should finally be fixed
- Ice Climbers fixes
- Red Falcon fixes
- Kirby and Game & Watch actually work now

### ⚠️ Known issues
- Non-default Captain Falcon skins desync
- Extras still need work

### 🔜 Coming next
Trailer · guide · more bug fixes · better console support · website improvements ·
more mod-creation tools · and more :)

**Download:** https://ssbmnucleus.net/download
