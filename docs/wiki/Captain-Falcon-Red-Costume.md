# Captain Falcon Red Costume

Captain Falcon has one notable file-format exception: the red costume is commonly encountered as a `.usd` file instead of the normal costume `.dat`.

That does **not** mean it is a fundamentally different kind of mod file. It is still the actual costume archive for that skin.

## The Core Rule

Most character costumes follow the usual pattern:

- `PlXxYy.dat`

Captain Falcon's red slot is the exception:

- in this repo's existing metadata, it shows up as `PlCaRe`
- in modding notes, you may also see people write `PlCaRd`
- the important part is that this red Falcon costume is the one special slot that may use `.usd`

## What `.usd` Means Here

As noted in the Melee file reference, `.usd` is basically `.dat` with extra localization data.

So for Captain Falcon red, the safe mental model is:

- it is still a normal costume archive
- it still belongs to Falcon's red costume slot
- the unusual part is the container or extension, not the basic role of the file

## Why This Matters

Red Falcon is available as a starting costume in Skin Creator. Setup resolves
his regional filename to the actual costume archive. If an older setup saved
only his portrait, opening the costume list recovers the model from your saved
vanilla ISO or its extracted reference files.

This is easy to miss if you only scan character archives for `.dat` files.

In practice, the important takeaway is:

- do not assume every valid character costume must end in `.dat`
- do not dismiss Falcon red just because it appears as `.usd`
- treat this as a file-naming and container exception, not a separate mod category

## Scope Note

This page only covers the red-costume file-format exception.

Captain Falcon also has ECB differences, but that is a separate topic and is not documented here yet.

## Related Pages

- [Character Mod Workflow](Character-Mod-Workflow.md)
- [Melee Files Reference](reference/new-414/Melee-Files.md)
