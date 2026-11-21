# First-Run Setup

First-run setup builds Nucleus's baseline data from a clean Melee ISO.

## What It Needs

Nucleus expects a vanilla Melee 1.02 ISO. That baseline is important because later workflows depend on known-good vanilla files for comparison, fallback assets, CSP generation, and restoration.

## How Nucleus Verifies The ISO

In the current setup flow, Nucleus tries auto-detect first and still allows manual browse as a fallback.

At a high level, the detection flow is:

1. Nucleus checks the default Slippi Dolphin folders under `AppData/Roaming/Slippi Launcher`
   (macOS: `~/Library/Application Support/Slippi Launcher`)
2. if present, it reads `User/Config/Dolphin.ini` (macOS:
   `~/Library/Application Support/com.project-slippi.dolphin/netplay/User/Config/Dolphin.ini`)
3. it collects configured ISO locations from Dolphin's settings
4. it also checks nearby Slippi folders as a fallback
5. it looks for `.iso` and `.gcm` candidates and gives common vanilla-style names like `GALE01`, `vanilla`, and `Melee` higher priority
6. the backend hashes candidate files and compares them against the known vanilla Melee 1.02 MD5
7. setup only continues if the hash matches

If auto-detect misses, you can still browse to the ISO manually.

So the "is this really a vanilla 1.02 ISO?" check is hash-based, not filename-based.

## When The ISO Is Rejected

Setup, **Settings → Vanilla ISO** and the startup notice all say why a file was
refused, and the log records the same reason (`ISO rejected (<reason>)`):

- **Cannot read this file / folder** (`unreadable`): the operating system refused
  access. On macOS this is the privacy prompt for Downloads, Documents, Desktop,
  iCloud Drive or an external drive: once "Don't Allow" is clicked, macOS does
  not ask again. Allow SSBM Nucleus in **System Settings → Privacy & Security →
  Files and Folders** (or Full Disk Access), or move the ISO to a plain folder in
  your home folder such as `~/Melee`.
- **Compressed RVZ / WIA / GCZ / CISO image** (`compressed`): Dolphin and Slippi
  play these, but Nucleus needs the plain ISO. Dolphin's **Convert File...** (format
  ISO) restores RVZ, WIA and GCZ exactly; CISO cannot be restored to the original.
- **NKit image** (`nkit`): restore the full ISO with NKit's ConvertToISO.
- **Another game, region or revision** (`not_gamecube`, `wrong_game`,
  `wrong_version`): Nucleus needs NTSC Melee 1.02, disc ID `GALE01`.
- **Trimmed** (`trimmed`): the file is smaller than a full 1.02 disc.
- **Melee 1.02, but modified** (`modified`): the disc header and size are right
  but the MD5 is not. It is a modded build or a scrubbed dump. Slippi Launcher
  calls some scrubbed dumps valid; Nucleus needs the unmodified dump.

## What Setup Produces

The first-run process is not importing your mods. It is extracting and seeding the app's own reference data.

At a high level, setup prepares:

- vanilla character assets
- vanilla stage assets
- stock icons and stage icons
- AJ animation archives used by viewers and CSP generation
- the reference files the portrait renderer reads (`storage/test-base/files`)
- the files for built-in custom characters (Giga Bowser). Setup only *prepares*
  them — the slow part, rendering his portraits and recolors, happens the first
  time you click his greyed-out card in
  [Custom Characters](Custom-Characters.md), so it does not hold up setup.
- Watch Lite's 2D character animation geometry (downloaded once if this
  build didn't bundle it; until it exists the replay viewer falls back to
  "dot mode"). The backend also fetches it in the background on startup, so
  installs that finished setup before this feature existed pick it up
  automatically.

## Finding Settings

Settings keeps its existing cards in categories along the left: **General**,
**Files & setup**, **AI**, and **Storage & backups**. Select a category
to see its cards. Switching categories
keeps your unfinished edits and running operations.

**General** includes updates, help and credits. **Files & setup** includes your
account, paths and setup. **AI** includes connecting your own AI (MCP), the
download of the model import tools and the creation toolkit's setup guide (see
[Assistant](Assistant.md)). Tracker has a separate **Cloud** category for Cloud
vault and phone pairing. **Storage & backups** includes data location, backups and
texture-pack storage. In Tracker, **Storage** contains the
data-location card.
On narrow windows, the category menu sits above the cards.

## Keeping Nucleus Up To Date

Nucleus checks for updates about 15 seconds after opening, then every six hours.
If a check fails, it retries after five minutes. Returning to the app or waking
your computer also checks when one is due. You can always use **Settings →
General → Check for Updates** to check immediately.

A newer public release shows a banner and a dot on Settings. Dismissing a banner
hides it for that version; the next release can show it again. A private preview
newer than the public release will not show an update until a newer release is
available.

## Why It Matters Later

A lot of later features silently rely on setup having happened already:

- missing stocks can fall back to vanilla assets
- CSP generation has the vanilla data it needs
- pose thumbnails can be rendered against vanilla costume and animation files
- stage and UI previews have a stable source of baseline assets
