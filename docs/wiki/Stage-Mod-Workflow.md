# Stage Mod Workflow

Exported Stadium variants include their matching four transformation files when
the complete set is available. A partial transformation set is omitted because
the stage loader requires all four files together.

Nucleus handles stage mods two ways. The six competitive stages use **Dynamic Alternate Stages**: several skins per stage, each behind a held button. Every other versus stage is a **single slot**: one installed skin per stage, written over the original, with the original a click away. This page covers both.

## What Makes Up A Stage Mod

At minimum, a stage mod is a stage archive file:

- usually a `.dat`
- Pokemon Stadium's files come as `.usd`, but installed **alt** files must end in `.dat` — the m-ex alt loader only accepts `.dat` inside a stage's alt folder, and a `.usd` alt crashes the stage at load. Nucleus renames Stadium alts to `.dat` for you (and heals older projects that still have `.usd` alts at export/install time).

A screenshot is optional, but useful because Nucleus can use it as the preview image in storage.

## What Importing Does

Importing a stage archive puts it into the **vault** as a stage variant.

Import does this:

1. Detects the stage file in the uploaded archive.
2. Figures out which supported stage bucket it belongs to.
3. Creates a per-stage variant ZIP in storage.
4. Extracts the screenshot separately for preview if one exists.
5. Adds the variant to the stage library.

The stored stage variant is a library item, not yet an active project file.

## Preview Screenshots

A variant with no screenshot shows a placeholder card. **Bulk Render
Screenshots**, above the stages grid in the Vault, fills those in: pick any
number of variants across any stages, and Nucleus draws each one from its own
stage file — roughly a second apiece, with no test build, no Dolphin, and no
vanilla ISO or Slippi path needed. Shots appear as they finish; you can stop
part-way and keep what is already drawn, and nothing is saved until you review
the grid and choose which to keep.

Only the six competitive stages have a camera set up for this so far. Variants
of the other stages are shown dimmed and cannot be selected. A Pokemon Stadium
transformation kept as its own variant is not a whole stage, so it reports that
instead of a picture.

For a live in-game shot of one variant instead, see
[Test In Game](Test-In-Game.md).

Click its card in the stage library to edit it, or focus the card and press
Enter or Space. In custom sort order, drag cards to reorder them.

For the broader import flow, see [Manual Import](Manual-Import.md).

## Current Scope

The Stages panel lists the six competitive stages first. They use Dynamic Alternate Stages, so each can hold several skins at once:

- Battlefield
- Final Destination
- Yoshi's Story
- Dreamland
- Pokemon Stadium
- Fountain of Dreams

Below them and Custom Stages, the list continues with the other 23 versus stages, each shown with its stage-select icon: Princess Peach's Castle, Rainbow Cruise, Kongo Jungle, Jungle Japes, Great Bay, Temple, Brinstar, Brinstar Depths, Yoshi's Island, Green Greens, Corneria, Venom, Poke Floats, Mute City, Big Blue, Onett, Fourside, Icicle Mountain, Mushroom Kingdom, Mushroom Kingdom II, Flat Zone, Yoshi's Island N64, and Kongo Jungle N64.

## The Other Stages

These stages have no alternate-stage loader, so Nucleus treats each one as a single slot: whatever file sits in that slot is what the game loads.

Pick one in the list to see:

- **In ISO** — what is in the slot right now: the original stage, an installed skin from your vault, or a file Nucleus does not recognize (for example one you copied in by hand). **Restore Vanilla** puts the original back from your Melee ISO.
- **Added as Separate Stages** — skins of this stage that you added to the stage select as their own entries. They can be removed from here.
- **Available to Import** — the skins in your vault for this stage. **Install** writes a skin over the original, so the stage looks like the skin everywhere it appears. **Add as new stage** keeps the original and adds the skin as its own stage-select entry instead (see [Custom Stages](Custom-Stages.md)).

Skins for these stages come from the same import you already use: drop in a mod's `GrXx.dat` (Green Greens is `GrGr.dat`, Big Blue is `GrBb.dat`, and so on) and it lands in the vault ready for either action. Corneria, Venom and Onett have two language versions of their file on the disc; Nucleus writes both, so the skin shows regardless of the save's language.

Each row in the list shows the stage's current state, so you can see at a glance which stages carry a skin and how many skins are waiting in the vault.

In the Vault, the Stages tab has a **More Stages** box next to Custom Stages. It opens the same 23 stages with a variant count each, and picking one opens the very same stage page the six competitive stages use: sort, folders, drag to reorder, rename, screenshots, export and delete all work identically, because these skins are stored as stage variants just like the others.

## Dynamic Alternate Stages Setup

Stage mods in Nucleus are installed into the stage folders in the active project.

Nucleus handles the base setup for you, including keeping the original stage as a `vanilla` variant.

That means the active project ends up with:

- the stage root file replaced with the stage-variant setup
- a per-stage alt folder such as `GrSt`, `GrOp`, or `GrPs`
- the original stage copied into that folder as `vanilla.dat`

Each stage's alternate-stage loader is made from that stage's file in your own Melee 1.02 ISO. If Nucleus cannot find a vanilla copy of a stage's file, it sets up the other stages and tells you which one it skipped, both when you create a project and when you install from the Stages tab. That stage's page then says it has no alternate-stage loader, since the game ignores its alternates until it has one, and offers **Install Again**. Set your vanilla ISO in Settings first.

## Variant Names

Nucleus removes unsupported characters from installed variant names. Pokemon Stadium names are also kept short so its transformations can load reliably. Any transformation skins stay attached when a variant is renamed.

Existing safe Stadium names, including the original vanilla variant, keep their spelling when you open the variant list. If shortening or cleaning up a name would clash with another variant, Nucleus chooses a distinct name and preserves both variants.

## Folder Layout

In the active project, alts live in folders named after the stage code.

Examples:

- `GrSt` for Yoshi's Story
- `GrOp` for Dreamland
- `GrPs` for Pokemon Stadium

The alt files themselves can be named freely, but they must use the `.dat` extension — including Pokemon Stadium alts, which Nucleus converts from `.usd` automatically. (Only the stage's root file, like `GrPs.usd`, keeps its original extension.)

## What Importing A Stage Variant To The Project Does

Once a stage variant is in the vault, you can import it into the active MEX project.

That workflow:

- reads the stored ZIP from the vault
- extracts the stage file
- writes it into the stage's project folder under the current stage code
- leaves the vault copy alone

So, just like character mods, the vault copy is your source item and the project copy is the active installed result.

## Button Tokens

Inside the project, stage variants can use button-token suffixes like `(B)`, `(X)`, `(Y)`, `(L)`, `(R)`, and `(Z)`.

When Nucleus copies a stage into the active project, it normalizes the installed filename to a no-space PascalCase form. Those tokens are part of that installed filename and represent button-selected stage variants.

Examples:

- `MyYoshiAlt(L).dat`
- `FrozenStadium(X).usd`

## Slippi Status

Stage variants do not currently follow the same automatic Slippi validation flow as costumes.

Right now, stage Slippi status is a manual flag rather than an automated validator result.

For the full distinction, see [Slippi Safety](Slippi-Safety.md).

## Stage Music

Each legal stage can also carry a custom music playlist — see [Stage Music](Sound-Mods.md). Playlists are edited directly in the open project, independently of the stage skins; clearing a playlist restores the stage's vanilla music.

## Pokemon Stadium Notes

**Transformation visibility.** Stadium's model has ten groups; during a transformation the engine hides only group 5 (the normal-form floor and two platforms) and keeps groups 1 and 2 (background, permanent shell) visible. A skin that puts floor or platform geometry in group 1 or 2 leaves it hanging through the water, fire, grass and rock forms (a visual ghost only; collision transforms correctly). The importer repairs this in `vault/importing/stadium_transform_fix.py` by changing model grouping only. For skins with separable duplicates (Bell Tower) it moves the permanent copy into group 5 and never deletes it, since the stacked pieces are material layers. For welded display lists it carves only broad shallow top-surface components, thin raised side platforms and, where no mesh-relative deck exists, a collision-space side-pad fallback into group 5, leaving walls, rims, skirts, stairs, supports, facades and group-1 skyline permanent. Repaired files are fixed points (a second pass reports `clean`), and clean archives stay byte-identical.

**Language-dual root file.** On the (En, Ja) US disc, Melee resolves extension-less filenames by the saved language: `.usd` for English (or no memory card), `.dat` for Japanese. The DAS loader checks `GrPs` alts against that runtime extension, and Stadium is the only stage with a language-dual root file, so an alt shipped under one extension asserts "no valid alts found in GrPs folder" (`dynamicAlts.c`) for players with the other language. The fix is in mexLib's `ExportISO`: every `GrPs` alt is packed under both extensions. Projects stay `.dat` on disk and the twin is made at export, so existing projects are fixed by their next export. Other stages (Yoshi's Story checked) are not language-sensitive.

## Custom Stages Are Different

This page is about **stage skins** — alternate looks for stages that already exist. Wholly new stages added to the stage select screen are a separate system: see [Custom Stages](Custom-Stages.md). The **Add as new stage** action on a non-tournament stage is the bridge between the two: it turns a skin into a custom stage entry.

## Summary

A stage mod in Nucleus is a vault item. For the six competitive stages it is copied into the stage's alt folder in the current project and picked with a held button; for every other stage it is written over the original stage file, with Restore Vanilla to undo.
