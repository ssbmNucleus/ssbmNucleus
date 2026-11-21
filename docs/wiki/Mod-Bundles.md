# Mod Bundles

Mod bundles are the `.ssbm` files Nucleus produces when you want to ship a whole modded build as a single file someone else can import in one step.

A bundle is the answer to: "I have an `.xdelta` patch AND a Dolphin texture pack and I want to share both at once."

## What A Bundle Contains

A `.ssbm` file is just a ZIP with a fixed layout:

- `patch.xdelta` — the diff between vanilla Melee and the modded ISO
- `textures/` — the Dolphin texture-pack PNGs for this build
- `manifest.json` — name, description, build name, creation date, texture count
- `image.png` — optional cover image shown in the bundle library

The bundle stores the build's name and description inside the manifest, so the receiving Nucleus install gets the same labels the creator used.

## What A Bundle Is For

Bundles exist because patches and texture packs are two halves of the same build:

- the `.xdelta` describes the ISO changes (gameplay code, character DAT swaps, stage edits)
- the texture pack provides the HD CSS portraits Dolphin loads at runtime

Shipping only one half means the recipient is missing something visible. Bundles keep them together so a one-file share recreates the whole build.

## Creating A Bundle

Bundles are created from the **Export** screen as one pipeline. Pick Bundle, give it a name, description, and optional cover image, and Nucleus:

1. builds a texture-pack ISO from the current project (placeholder portraits inside)
2. auto-applies the HD portraits into a texture-pack folder ([Texture Pack Mode](Texture-Pack-Mode.md))
3. runs `xdelta3 -e` against your configured vanilla ISO to produce `patch.xdelta`
4. copies the texture pack PNGs into `textures/`
5. writes `manifest.json` with the metadata you supplied
6. ZIPs it all into `<name>.ssbm`

The output lives in the bundle library and can be downloaded again later. There is no separate "gather the ISO and texture folder yourself" step anymore.

## Importing A Bundle

When you import a `.ssbm`, Nucleus needs your configured vanilla ISO and your Slippi install path. It then:

1. extracts the bundle into a temp folder
2. validates that `manifest.json` and `patch.xdelta` are present
3. applies the patch against vanilla to produce a playable ISO in your Dolphin ISO folder
4. copies the textures into `User/Load/Textures/GALE01/ssbm-nucleus/<build_name>/`
5. enables `HiresTextures=True` in Dolphin's `GFX.ini`

The build name in the manifest is what keeps each imported bundle's textures in its own subfolder, so installing multiple bundles does not cause them to overwrite each other.

## Bundle Vs Patch Vs Texture Pack

It is worth being explicit about how this differs from the other distribution formats:

- a [Patch](Patches.md) is just the `.xdelta` — it rebuilds a modded ISO but the build will be missing HD portraits
- a [Texture Pack](Texture-Pack-Mode.md) is just the Dolphin `Load/` folder — it has portraits but no ISO behind them
- a Bundle is both, packaged together, with a manifest

If the build is portrait-heavy, ship a bundle. If the build does not use HD portraits at all, a plain patch is smaller and simpler.

## Size Considerations

Bundle size is dominated by:

- the `.xdelta` size, which scales with how much you changed vs. vanilla
- the number and resolution of textures in the pack

The xdelta is created with fast compression (`-1`) so encode time stays reasonable. If a build has hundreds of portraits, the texture portion can easily be larger than the patch.

## What Bundles Are Not

Bundles are not:

- a full ISO (you still need the recipient to provide their own vanilla ISO)
- a way to ship individual character or stage mods (use one-click imports or ZIPs for that)
- a Nucleus project file — they are a distribution format, not a save format

If you want to ship a single skin or a single stage rather than a whole build, see [One-Click Imports](One-Click-Imports.md) instead.

## Related Pages

- [Patches](Patches.md)
- [Texture Pack Mode](Texture-Pack-Mode.md)
- [One-Click Imports](One-Click-Imports.md)
- [Vault Backup And Restore](Vault-And-Distribution-Workflow.md)
