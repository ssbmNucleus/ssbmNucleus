# Texture Pack Mode

Texture-pack mode is how a build gets **HD character portraits in Dolphin**, beyond what fits inside the ISO itself.

The important practical detail is that this is mainly a **CSP pipeline**. It is not a general-purpose "turn the whole build into a texture pack" system.

## What It Is For

Melee has limited memory for menu portraits, so portraits stored inside the ISO have to stay small. Dolphin's custom-texture loading sidesteps that: the ISO ships tiny placeholder portraits, and Dolphin swaps in full-resolution images from a texture-pack folder at runtime.

Use it when you want the build to keep normal in-game behavior but show high-resolution CSS portraits through Dolphin's texture loading.

## How It Works Now (Automatic)

Texture packs are generated as part of the **Bundle** export pipeline. When you export a bundle:

1. Nucleus builds the ISO with small placeholder portraits in place of the real CSPs
2. it **auto-applies** the real HD portrait images into a Dolphin texture-pack folder, naming each file correctly for Dolphin — instantly, with no Dolphin running
3. the ISO and the texture pack are packaged together as a `.ssbm` [Mod Bundle](Mod-Bundles.md)

The auto-apply step works because the placeholder image for each costume slot is deterministic, so the Dolphin load filename it produces can be precomputed once and reused for every build. Older versions of Nucleus required you to boot the exported ISO and manually scroll through every costume on the character select screen so Dolphin would reveal the filenames — that step is gone.

## Where The Real Portraits Come From

Texture-pack mode uses the portrait files Nucleus already knows about:

- if a costume has an HD CSP, Nucleus uses that
- otherwise it renders one at export time (rendered at 4x and cached, so later exports of the same costume are instant)

That is why this mode pairs naturally with the portrait tools on [CSP And Pose Workflow](CSP-And-Pose-Workflow.md).

## Quick Exports Vs Finished Builds

If you just want to test a few skins or check whether something basically works, a plain ISO export is simpler — there is no texture pack to carry around.

In that case, [CSP Compression](CSP-Compression.md) is the relevant knob: it downsizes the in-ISO portraits so the build stays within Melee's portrait memory limits.

Texture-pack output is the nicer-looking option and is the right choice for finished builds you want to share, since the [Mod Bundle](Mod-Bundles.md) format carries both halves in one file.

## What You Get At The End

- the exported ISO (with placeholder portraits inside)
- a build-specific portrait texture-pack folder under Dolphin's `Load/Textures/GALE01` path
- if you exported a bundle, a `.ssbm` file containing both

Dolphin needs `HiresTextures` enabled to load the pack; importing a bundle sets that automatically.

## Related Pages

- [Mod Bundles](Mod-Bundles.md)
- [CSP And Pose Workflow](CSP-And-Pose-Workflow.md)
- [CSP Compression](CSP-Compression.md)
- [Character Mod Workflow](Character-Mod-Workflow.md)
