# Vault Vs Project

Vault vs project is the core split in the app.

## The Vault

The vault is your library. It stores imported costumes, stage variants, preview images, pose files, effect presets, patch metadata, and the main `metadata.json` that ties everything together.

The vault is meant to be stable and reusable. Importing something into the vault usually means "save this for later and make it manageable."

## The Current MEX Project

The current MEX project is the active build you are editing. This is the set of files that the game or ISO export actually uses.

Installing or applying something to the project means "write this into the current build."

## The Difference In Practice

- importing a costume ZIP puts it in the vault
- installing that costume from the character panel writes it into the active MEX project
- importing a stage ZIP puts a stage variant in the vault
- importing a stage variant into a stage slot writes a stage file into the active MEX project
- creating or installing an effect patches a project DAT directly
- exporting an ISO reads the current MEX project, not the whole vault
- backing up the vault preserves your library, not a full game build

## Basic Loop

Most actions in Nucleus fall into this pattern:

1. import something into the vault
2. install or apply it to the current MEX project
3. export the current project or back up the vault

## Why This Split Is Good

Without this split, it would be hard to reuse the same library across multiple project setups.

The vault gives you:

- a permanent collection
- previews and metadata
- import, rename, reorder, and folder organization
- sorting (A–Z, date added, costume color) — your drag-arranged order is the
  "Custom" sort and is never lost; the other sorts are view-only, and
  drag-reorder is available only while Custom is active
- backup and restore

The project gives you:

- the currently playable build
- costume order and stage files that match the open project
- the exact files used by ISO export and patch creation

## Choosing A Data Drive

In an installed app, open **Settings → Data location** to choose the drive for
your Vault, app-owned projects, build output, extracted assets and local history.
Temporary import and build files use the selected drive too. Choose a parent
folder, review the new data folder shown, then select **Schedule move for next
launch**. The destination must be new or empty and have room for a full copy.
The **Current folder** and **Temporary files** paths can be selected and copied;
long paths wrap so you can read the complete location.

Finish active work and close Nucleus when convenient. On the next normal launch, Nucleus copies and verifies
your data before opening. The original folder remains available for recovery.
You can cancel a scheduled move in Settings before quitting.

Reconnect a missing selected drive before launching. Nucleus shows an error
instead of opening an empty library elsewhere. An interrupted move retains the
original data and partial copy; use the startup recovery choices to return to
the original library or retry with a new empty destination.

The model import tools (Settings > AI > Model import tools) are not
copied: they are a download Nucleus can repeat, so after the move the card
offers **Download** again. The original folder keeps its copy until you delete it.

External replay folders and ISO files remain where you chose them. Browser
caches and the application profile stay in their normal location. Development
checkouts and launches using developer storage overrides disable this setting.

## Typical Loop

1. Import mods into the vault.
2. Choose which ones to install into the current MEX project.
3. Reorder or tweak the project build.
4. Export an ISO or create a patch.

If something feels confusing, ask: "am I saving this in the vault, or am I changing the active project?"
