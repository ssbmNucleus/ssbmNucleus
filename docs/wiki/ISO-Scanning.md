# ISO Scanning

ISO scanning rips mod content **out of** existing ISOs and into your vault. If you have old modded builds lying around, this is how you recover their skins without the original ZIPs.

## Character Skin Scanning

The main scan takes one or more ISOs (`.iso` / `.gcm`; NKit images are not supported) and finds costume skins:

1. choose ISOs with **Import**, or drop them anywhere in the vault; choose your targets and click **Start scan**
2. Nucleus extracts each ISO and hashes every character costume file
3. anything that matches vanilla Melee or a skin already in your vault is skipped — only **new** skins surface
4. each candidate gets Slippi validation and a rendered CSP preview
5. you pick which candidates to keep from a per-character selection grid
6. selected skins import into the vault like any other costume

The square scan panel keeps the shine animation, current step, progress and elapsed
time. Preview preparation starts rendering as soon as the first renderer is ready,
without waiting for the whole batch to initialize. Scans with no new skins finish
without preparing previews. You can cancel
mid-scan; during a custom import, the current ISO finishes and its additions are
kept before the remaining work stops. Progress and results recover automatically after a connection interruption. Unreadable ISOs are
listed separately; if none can be read, the scan reports an error.

If a selected file cannot be opened, the scan window offers **Add ISOs** to
choose it again.

## Reading Results

Stage variants get a 16:9 preview rendered directly from their stage file,
without launching Dolphin. The renderer is reused across the batch. Rescanning
fills in missing previews for older ISO imports without adding duplicate stages;
existing screenshots are kept. A failed preview does not discard the stage.

Switch between
**Character skins**, **Stage variants**, **Custom characters**, and **Custom stages**
using the compact tabs, in that order. The target picker and loading steps use
the same names.
The active tab is yellow; counts appear when content is new or has been added.
Characters and stages shown here are already saved in your vault. Each result
has one bordered card containing its image and name, without a repeated status badge.
Card columns expand evenly to fill the available width. Portraits and icons use
consistent frames and fit without cropping or stretching. On narrow windows,
the category tabs wrap into two rows so their full names remain visible.

Skin previews stay grouped by character. Select individual cards, whole groups,
or all skins, then choose **Import & finish**. The footer shows your selection count.
Successful imports play the confirmation sound and return directly to the refreshed
vault, with no second Done screen. **Close without importing** skips the character
skin selection; other content already saved to the vault stays saved.
Already-imported content appears under **Already in vault** with its saved portraits
or icons. Vanilla files stay hidden. Other skipped files have a compact breakdown.
If part of a scan fails, successful additions remain visible alongside the error.
Import errors keep the result cards and failed skin names visible. A lost import
response is shown as unconfirmed; check the vault before scanning again. If the
vault refresh fails after saving, **Refresh vault** retries just the refresh.
Results with no pending skins use **Done** for successful additions or **Close**
for empty results and errors. Done plays the menu confirmation sound. Results
close immediately; temporary-file cleanup runs in the background. Clicking outside
the results does not discard the selection.

## Deduplication Is Live

The "is this new?" check is recomputed against your current vault every scan. If you delete a skin from the vault, a later scan of the same ISO will offer it again — nothing is permanently remembered as "already imported."

## Diet Melee Builds

Skins from **Diet Melee**-family builds (including Diet Melee 64) are authored
for the low-poly models that those packs' patched game engine displays. Ripped
raw, they would look near-vanilla on a normal build — and some can hang the
game at match load. Nucleus detects these ISOs during the scan and repairs
each skin automatically: the low-poly art is promoted into the normally
visible model slots and the file is made engine-safe, so the skin looks and
plays the way the pack intended on any build. The same repair applies when
you import an individual skin file that carries the Diet fingerprint.

## Stage Variant Scanning

The stage side has its own scan: Nucleus can pull **stage variants** out of a modded ISO — both m-ex DAS folders and 20XX-style alternate stage files — and offer them as importable variants for the six DAS stages.

## Custom Content Scanning

Custom characters and custom stages have separate scan flows in their own vault sections, for extracting m-ex fighters and stages out of a modded build. See [Custom Characters](Custom-Characters.md) and [Custom Stages](Custom-Stages.md).

## Requirements

Nucleus reads ISO files directly on Windows, macOS and Linux. No separate tool
install is needed.

## Related Pages

- [Manual Import](Manual-Import.md)
- [Custom Characters](Custom-Characters.md)
- [Custom Stages](Custom-Stages.md)
- [Stage Mod Workflow](Stage-Mod-Workflow.md)
