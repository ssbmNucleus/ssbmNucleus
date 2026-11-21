# Manual Import

Manual import adds mod files to the vault.

It does **not** install them into the current MEX project yet.

## The Import Button

There is one import affordance for the whole vault: the floating **Import** button in the bottom-right corner, which is always visible across every vault view. Dragging files anywhere onto the window does the same thing.

You do not choose a mod type first. Nucleus scans each file, detects what it is, and routes it to the right importer.

## Supported Files

- `.zip` / `.7z` / `.rar` — mod archives (costumes, stages, custom characters, custom stages, menu mods, effects)
- `.dat` / `.usd` — a loose costume or stage file, even renamed (Nucleus identifies it by content); a menu file (`MnSlChr`, `MnSlMap`, `GmPause`, `IfAll`); or an effect file (`EfFxData.dat`, `EfCoData.dat`, `PlFx.dat`, …), which lands in that character's Extras
- `.png` / `.jpg` / `.webp` — a picture: a CSS door texture, a pause-screen picture, a shine image or shield texture, or (selected together) a pack of digit or word-banner glyphs — see [Menus And Select Screen Mods](Menus-And-Select-Screen-Mods.md)
- `.xdelta` — a build patch, added to the patch library
- `.ssbm` — a [Mod Bundle](Mod-Bundles.md)
- `.iso` / `.gcm` — starts an [ISO scan](ISO-Scanning.md) to rip skins out of the disc

Multi-select works; batch imports auto-fix Slippi issues and auto-skip already-owned duplicates instead of stopping on every dialog. The summary says how many were imported, auto-fixed, skipped, or couldn't be imported (with per-file reasons in the developer console). Pictures selected together are imported as one set, so the ten digits of a percent font can be picked in one go.

When a file could be more than one thing — a lone picture with no telling name or size, a whole `MnSlChr` (icons or backdrop?), an effect file when no vanilla ISO is recorded to compare against — Nucleus asks **What is this?** with the plausible kinds and imports it as whatever you pick. Batch imports take the first option.

**Zips of zips work too.** If you zip up a whole folder of skin zips and import it, Nucleus opens each inner archive and imports it the same way — two levels deep, with the same auto-fix/auto-skip behavior as a batch. `.zip`, `.7z` and `.rar` members are all opened; anything that can't be read is listed in the summary rather than silently dropped.

## Character Mod Archives

For character mods, the usual bundle is:

- the costume DAT
- a CSP image
- a stock icon

Nucleus will try to match included assets automatically.

If assets are missing:

- it can generate a CSP for you
- it can generate or fall back to a vanilla stock icon

Character imports also go through [Slippi safety validation](Slippi-Safety.md).

Character mods exported as ZIPs from **mexTool** work well here. That format already matches what Nucleus expects to scan.

## Stage Mod Archives

For stage mods, the usual bundle is:

- the stage file
- an optional screenshot

The screenshot is not required, but it is useful because Nucleus can use it as the preview image in the vault.

What happens depends on which stage the file is for:

- the **six tournament-legal stages** (`GrNBa`, `GrNLa`, `GrSt`, `GrOp`, `GrPs`, `GrIz`) import as stage **skins** — alternate looks selectable on the vanilla stage
- any other vanilla stage (`GrGr` Green Greens, `GrCs` Peach's Castle, `GrBb` Big Blue, ...) imports as an **added custom stage** with its own stage-select entry — see [Custom Stages](Custom-Stages.md)

## Other Archive Types

The same import button also accepts:

- **custom character packages** (MexManager fighter ZIPs) — see [Custom Characters](Custom-Characters.md)
- **custom stage packages**, including classic `stage.yml` packages, which are converted automatically — see [Custom Stages](Custom-Stages.md)
- **menu mods** (CSS icon grids, backgrounds, doors, pause screens, HUD typefaces) — see [Menus And Select Screen Mods](Menus-And-Select-Screen-Mods.md)
- **effect files** — an `Ef…Data.dat` (or a character's `Pl…dat` with editable effects) is read through the same offset system as the Extras editors; every effect it changes from vanilla becomes a mod in that character's Extras (one file recoloring both laser and shine yields two). A file that matches vanilla everywhere is refused rather than filed as an empty mod.

## Good Packaging

The simplest packaging rules are:

- character mod: DAT + CSP + stock
- stage mod: stage file + screenshot
