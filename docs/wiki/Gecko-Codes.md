# Gecko Codes

Gecko codes are small hex patches (widescreen, UCF, unlock everything, camera
tweaks…) that get compiled into your build's `codes.gct` and loaded by the
game at boot. Everything lives in one place: the **Codes** button on the
Install tab.

## Your Code Library

The manager's Vault column starts pre-loaded with the community code library
that ships with MexManager (49 codes across QOL, MENU, GAMEPLAY, DEBUG, and
ADDITIONAL categories — Better Camera, UCF, Skip Result Screen, Unlock
Everything, and friends), grouped into collapsible categories. Nothing is
applied to any build until you say so. The ✕ on a vault row deletes a code
from your library.

### Adding Your Own Codes

Hit **+ Paste codes** and paste anything:

- raw hex lines (`04452C68 C0A00000`)
- a full INI block (`$Widescreen 16:9 [dan]` followed by hex)
- several codes at once — INI entries or title-plus-hex blocks
- a loose copy-paste from a SmashBoards thread (title, description, and hex
  are picked apart automatically)

You get a preview of every code found, can fix up names/creators/categories,
and only the ones you check get saved. Codes that can't compile are flagged
with the reason instead of silently breaking your build.

**Note:** the m-ex code loader supports gecko opcodes `00`, `02`, `04`, and
`C2` (memory writes and code injections). Codes using other opcodes (e.g.
`06` string writes) are rejected at paste time — this is a loader limit, not
a Nucleus one.

## Applying Codes To A Build

On the Install tab, the **Codes** button opens the manager for the open
project:

- **In this build** lists what's already applied. The checkbox toggles a code
  on/off (disabled codes stay listed but are left out of the compiled gct);
  the ✕ (shown when you point at a row) removes it entirely.
- **Add codes** has a search box, then your library by category. Codes
  Nucleus makes itself, such as Now Playing, are listed first in theirs.
  **Add** stages a code into the build. **Paste codes** adds new codes to your
  library.

### Matching Stock m-ex Defaults

Builds made in the standalone MexManager app start with the whole 49-code
library applied. Nucleus-created projects start lean — just the m-ex engine
core and the default Slippi fix. If you want the stock m-ex experience
(Skip Memcard Prompt, Unlock Everything, Neutral Spawn, Salty Runback…),
hit **Add all m-ex defaults** at the top of the Add codes column: it stages every
missing library code so you can review the list, uncheck what you don't
want, and Apply.

Nothing touches the project until you hit **Apply**, which rewrites the
project's `codes.ini` and recompiles `codes.gct`. Export the ISO afterwards to
play with the new codes.

### The Default Slippi Code

Every project starts with **Skip Slippi SSS [KELLZ]** turned on, marked
"Needed for Slippi Dolphin" in the manager. Since the October 2025 Slippi update, an m-ex
build's stage select screen crashes on **Slippi Dolphin** without it:
**turning it off breaks the ISO for Slippi Dolphin.** Only turn it off for a
build you play on **Slippi Nintendont** (console), where it can instead crash
at stage select — untick it (a warning shows while it's off) and hit **Apply**. The choice is
saved with the project and later exports respect it.

### Now Playing

A project you create also starts with **QOL | Now Playing (Song Name at Match
Start)** turned on: when a match starts, a banner with the song's name slides
in at the top left for a few seconds. The name is the one the song has in your build's
music list. It is an ordinary code — untick or remove it and hit **Apply** if
you don't want it. Projects made before it existed don't get it automatically:
add it from **Quality of life** in the codes manager and hit **Apply**. A build
made from the ACE Build already shows the song its own way, so it doesn't get
this code, and the manager says so instead of offering it.

### Codes From Other Sources

Codes that arrived in your project some other way (fighter packs bundle their
own codes, some installs inject helper codes) show up in "In this build" like
any other. They survive Apply untouched unless you explicitly remove them.

### Applied By Slippi Dolphin

Below "In this build", one line counts the codes your **Slippi Dolphin
injects at launch** (its required netplay codes plus anything enabled in
your Dolphin GameSettings); click it to see them. These run on top of whatever
ISO you play and are **not part of the exported ISO**; they're shown so the
full picture of what actually runs in-game is in one place. When the list
can't be read (no Slippi configured), a note explains that Slippi adds its
own codes at launch.
