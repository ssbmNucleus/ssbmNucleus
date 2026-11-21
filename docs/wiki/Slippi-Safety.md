# Slippi Safety

Nucleus uses two different Slippi-safety models: automated checks for costumes, manual status for stages.

## The Big Distinction

For character costumes, Nucleus has an **automated validation and fix flow**.

For stage variants, Nucleus currently only stores a **manual Slippi status flag**.

So "Slippi safe" does not mean the same thing everywhere in the app.

## Character Costumes

When you import a character archive into the vault, Nucleus validates each detected costume DAT for Slippi safety before finishing the import.

If any costume fails the check, the app does not silently continue. It returns a dialog flow so the user can decide whether to:

- fix the costume
- import it as-is

## What "Fix" Means In Practice

If you choose to auto-fix during import:

- the fixed DAT becomes the one written into the stored costume ZIP
- the costume is treated as tested and safe

If you import as-is:

- the original DAT is stored
- the app records that the costume was tested and not considered safe

## Captain Falcon Is Special

Falcon is the one character whose vanilla skeleton genuinely differs between
color slots (up to 33 of his 63 bones), so a skin built on a non-neutral color
can desync online even when the validator passes it — the validator can only
compare against the color the skin *says* it is.

Nucleus sidesteps this at **install time**: every Falcon costume is converted
to the neutral color as it enters a build (its skeleton is retargeted to the
neutral one and its internal symbols renamed to match). The skin looks
identical — the base color under a mod doesn't matter — but the skeleton is
now the netplay-safe neutral one.

This conversion never touches the vault. It applies only to the copy installed
into the build, so exporting or re-sharing a vault costume gives you the
original bytes.

## Retesting Stored Costumes

Vault costumes can be retested later.

Retest is not just a label refresh. If you choose the fix path, Nucleus can update the stored costume package with the fixed DAT.

## Manual Override

Nucleus also supports a manual override for costume safety.

That does **not** change the DAT. It only changes the app's stored status.

## Stage Slippi Status

Stage variants do not currently go through the same automatic validator path.

Instead, stage Slippi state is a manual status flag.

## What The App Actually Knows

Today, Nucleus can say these things with confidence:

- whether the costume validator reported the DAT as safe
- whether a fix was applied
- whether the user manually overrode the result
- whether a stage status was set manually

What it does **not** document in this repo is the full low-level rule set used by the external Slippi validator.

So the app knows the outcome of validation, but not necessarily every internal rule behind that outcome.

## Practical Warning

Large rosters have a separate reported online risk: above 63 fighter entries,
grabs and command grabs can intermittently desync even when the game builds and
launches. The count includes partners, hidden fighters and reserved slots, rather
than just visible character-select cards. This is a reported threshold, not a
proven universal limit or a guarantee that smaller rosters are safe.

**Unreleased:** the project, Add Characters and export views show a nonblocking
roster advisory. It is independent of costume validation and the game's
character-select memory and effect-table limits. See
[Custom Characters](Custom-Characters.md#large-rosters-and-slippi).

The older color/effect notes in the repo also mention desync risk for some gameplay-adjacent edits, such as hitbox-element changes.

That means "visual modding" and "Slippi safety" are related but not identical topics. Some visual-looking changes still touch gameplay-relevant data.

## How the check works

Nucleus wraps an external validator rather than implementing its own rule set.
`validate_for_slippi()` (`app/utility/tools/services/dat_processor.py`) is used by
the import and retest flows.

- **Filename reconstruction.** The validator expects a real Melee costume name
  such as `PlFxGr.dat`. Uploads and stored ZIP entries do not always use one, so
  Nucleus parses the DAT and rebuilds the name from the detected character and
  color. If it cannot, validation cannot run.
- **Copy, validate, replace.** The original DAT is hashed and copied into a
  scratch folder under the reconstructed name (the validator skips names that are
  not a plain `Pl...` stem, so the copy cannot carry a prefix). The validator runs
  on the copy with the caller's auto-fix choice, the original's hash is checked
  unchanged, and the fixed copy replaces the original only if the validator
  reports it actually wrote a fix. It declines to when a skeleton diverges too far
  to correct bone for bone.
- **When it cannot run.** An unreadable DAT, an unreconstructable filename or a
  crashed helper gives neither "safe" nor "needs a fix". The result carries an
  `error`, and a retest returns that error and leaves the stored status alone
  instead of recording a guess.
- **Import.** The upload route first checks without importing. `slippi_action`
  of `fix` imports with auto-fix, `import_as_is` imports unchanged, and none
  means "check first and decide whether a dialog is needed". The stored costume
  records `slippi_safe`, `slippi_tested`, `slippi_test_date` and
  `slippi_manual_override`.
- **Retest** (`/api/mex/storage/costumes/retest-slippi`) re-extracts the DAT from
  the stored ZIP, validates again, rewrites the DAT in the ZIP if auto-fix was
  chosen, updates the stored fields and clears any manual override.
- **Manual override** (`/api/mex/storage/costumes/override-slippi`) only updates
  the stored status; it does not run the validator or touch the DAT. Stages use
  `/api/mex/storage/stages/set-slippi`, which stores a status and date only.

## Summary

For costumes, Slippi safety in Nucleus is:

- validator result first
- auto-fix support second
- manual override as metadata only

For stages, Slippi safety is currently:

- a manually maintained status flag

## Related Pages

- [Character Mod Workflow](Character-Mod-Workflow.md)
- [Stage Mod Workflow](Stage-Mod-Workflow.md)
