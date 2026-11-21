# Ice Climbers Pairing

Ice Climbers are a special case in both Melee modding and Nucleus.

They are not treated like two fully independent costumes. In practice, one playable Ice Climbers mod is a **paired Popo and Nana set**.

Costume previews show both climbers together on Windows, Mac and Linux, even
when you open Nana. Linked custom partners stay together; an unpaired costume
uses its matching vanilla partner. If a linked costume is missing, the preview
reports the problem. Shared animations play and seek together. Saved poses
retain the selected climber's settings without saving the preview's side-by-side
placement.

## The Core Rule

For a complete Ice Climbers costume pair:

- you still need both DAT files
- Nana should **not** have separate CSP and stock assets

That is the most important distinction to keep in mind.

## What Files Make Up The Pair

The pair is built around two costume DATs:

- `PlPp__.dat` for Popo
- `PlNn__.dat` for Nana

Those two DATs are the real gameplay and model assets for the pair.

So when people say Ice Climbers are "one mod," that usually means:

- two DAT files
- one shared set of menu-facing portrait assets

## Color Pairing

Nucleus currently assumes the standard Popo/Nana color pairing:

- Popo Default <-> Nana Default
- Popo Red <-> Nana White
- Popo Orange <-> Nana Aqua/Light Blue
- Popo Green <-> Nana Yellow

That pairing is used when the importer tries to match Popo and Nana files from the same archive.

## CSP Behavior

Ice Climbers CSPs are treated as a **composite portrait**, not two unrelated portraits.

The current CSP generator:

1. renders Nana with Nana's scene file
2. renders Popo with Popo's scene file
3. composites Popo over Nana with alpha blending

So the final portrait is effectively:

- Nana as the background layer
- Popo as the foreground layer

This matches the current implementation in the generator, not just a hand-wavy workflow description.

## About Shadows

The generator does not apply a special "shadow-only" post-process for Ice Climbers.

It composites the full Nana render behind the full Popo render. That means any shadow look you see is coming from the underlying rendered layers and scene setup, not from a separate documented shadow pass.

So the safe way to describe it is:

- Nana provides the background render
- Popo is composited on top
- exact shadow appearance is scene/render dependent

## Stock And Other UI Assets

In the intended Nucleus workflow, Nana should not have her own separate stock or CSP asset.

Those assets are not displayed separately for Nana, so keeping a second Nana CSP or stock just wastes memory.

The pair should be treated as having:

- one Popo-centered composite CSP for the pair
- one stock set for the pair

## How Nucleus Stores The Pair

In Nucleus, the pair is usually represented as one Popo-facing skin entry with Nana attached as the partner.

This is why Ice Climbers can feel like one character mod even though there are still two costume DATs underneath.

## Import Behavior

During character import, Nucleus looks for both DATs and matches them by the expected color pairing.

Once the pair is recognized, it is handled as one shared menu-asset problem rather than two separate skins.

## Install And Removal Behavior

In the active M-EX project, Nucleus also treats the pair as linked:

- installing Popo auto-installs the paired Nana
- removing Popo also removes the paired Nana at the same costume index

So project behavior follows the same rule as storage behavior: Popo is the primary entry point for the pair.

## Export Behavior

When a stored Ice Climbers Popo skin is exported, Nucleus also tries to include the paired Nana DAT.

That means an exported Ice Climbers costume ZIP is expected to look more like:

- Popo DAT
- Nana DAT
- one CSP
- one stock

That is a better mental model than expecting two totally separate costume packages.

## Summary

For Ice Climbers:

- gameplay/model side: think **two DATs**
- menu/UI side: think **one paired portrait set**
- workflow side: think **one paired skin entry**

If you keep those three rules straight, the rest of the behavior makes much more sense.

## Related Pages

- [Character Mod Workflow](Character-Mod-Workflow.md)
- [CSP And Pose Workflow](CSP-And-Pose-Workflow.md)
- [Melee Files Reference](reference/new-414/Melee-Files.md)
