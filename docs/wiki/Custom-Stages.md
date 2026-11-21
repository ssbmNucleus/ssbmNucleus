# Custom Stages

Custom stages are **wholly new stages** added through m-ex's stage system — they get their own slot on the stage select screen.

This is different from the [Stage Mod Workflow](Stage-Mod-Workflow.md), which is about alternate looks (skins) for stages that already exist: button-selected alternates for the six legal stages, and one installed skin per stage for the rest.

## Where They Come From

- **MexManager stage packages** — a stage ZIP exported from MexManager. Import it with the normal Import button.
- **Classic `stage.yml` packages** — the older community stage format. Nucleus converts these automatically on import, including their custom map objects and moving collisions.
- **Add as new stage** on a stage skin — a `GrXx.dat` mod for any stage imports as a [stage skin](Stage-Mod-Workflow.md) (Vault > Stages > More Stages for the non-tournament ones). From that stage's row in Install > Stages, **Add as new stage** turns the skin into a brand-new stage-select entry that keeps the vanilla stage untouched, carrying the vanilla stage's icon, sound bank, music, and stage logic (hazards, moving platforms). The new entry then appears here as a custom stage.
- **Scanning a modded ISO** — Nucleus can extract custom stages out of an existing m-ex build.

## What The Vault Stores

Each custom stage keeps:

- the original stage package (intact, for re-export)
- its SSS icon and banner image
- extracted metadata

Custom stages have their own vault section with the same folder organization as costumes (create folders, rename, drag stages in and out).

## Installing

Installing a custom stage adds it to the open MEX project's stage select via m-ex. From the project side you can:

- see which custom stages are currently in the project
- reorder them
- remove them

The SSS layout itself (icon positions) is edited in the [menus editor](Menus-And-Select-Screen-Mods.md).

## Testing

Custom stages can be smoke-tested with [Test In Game](Test-In-Game.md): Nucleus builds a minimal ISO with the stage, boots it, selects the stage, and reports whether the match loads.

## Related Pages

- [Stage Mod Workflow](Stage-Mod-Workflow.md)
- [Custom Characters](Custom-Characters.md)
- [Menus And Select Screen Mods](Menus-And-Select-Screen-Mods.md)
- [Test In Game](Test-In-Game.md)
