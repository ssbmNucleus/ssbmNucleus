# Patches

Patches in Nucleus are `.xdelta` files that describe how to turn a vanilla Melee ISO into a specific modded ISO.

## What Makes Patches Different

Character mods, stage mods, and effects are modular pieces you import into the vault and install into the current project.

Patches are different. A patch represents a whole build state.

Instead of importing one mod into the current project, you apply a patch against a vanilla ISO to recreate a full modded ISO.

## What Nucleus Stores

The patch library stores:

- the `.xdelta` file
- a name
- a description
- an optional image

So patches still behave like a managed library item even though the result is distribution-focused.

## Main Patch Flows

There are three main directions:

- import an existing `.xdelta` into the patch library
- create a new patch by comparing a modded ISO against your configured vanilla ISO
- build a playable ISO from a stored patch plus your configured vanilla ISO

Nucleus also lets you download a stored patch again after it has been added to the library.

Download is available from both the completed Export screen and the patch library.
If the download check fails, Nucleus shows an error and you can retry. Downloading
does not remove the stored patch; the browser or desktop shell handles saving the file.

If Settings cannot verify your vanilla ISO, retry verification or reselect the
file after reconnecting its drive. A failed verification request does not mean
the disc is invalid. A confirmed mismatch still requires a vanilla Melee 1.02 ISO.

## Creating A Patch

There are two ways to end up with a new patch:

- **From the Export screen** — the Patch pipeline builds an ISO from your current project and diffs it against your configured vanilla ISO in one go. This is the normal path for sharing your own build.
- **From the patch library** — pick any existing modded ISO and Nucleus compares it against your configured vanilla ISO.

Either way, the result is a new `.xdelta` file that can be kept in the patch library and shared with other people.

## Building From A Patch

When you build from a patch, Nucleus takes:

- the stored `.xdelta`
- your configured vanilla ISO

Then it applies the patch and produces a downloadable patched ISO.

That is why the vanilla ISO path matters here even if the patch itself is already in storage.

## What Patches Are For

The main use here is sharing a full build without sharing a full ISO.

Patch size depends on how different the modded ISO is from vanilla, but the output is often much smaller than a full disc image.

## What Patches Are Not

Patches are not the same thing as:

- a costume ZIP
- a stage ZIP
- a one-click Nucleus import link
- texture-pack mode output

If you want to share supported mod ZIPs directly into another user's vault, see [One-Click Imports](One-Click-Imports.md).

If you want Dolphin CSP texture output, see [Texture Pack Mode](Texture-Pack-Mode.md).

## Related Pages

- [Texture Pack Mode](Texture-Pack-Mode.md)
- [One-Click Imports](One-Click-Imports.md)
