# Custom Characters

Custom characters are **wholly new fighters** added to the roster through m-ex — Sonic, Shadow, Mewtwo clones, and so on. They are not costume swaps on an existing fighter; they get their own CSS slot.

## Where They Come From

Sources:

- **MexManager character packages** — a fighter ZIP exported from MexManager. Import it with the normal Import button; Nucleus detects it as a custom character.
- **Randall clones** — in assistant-enabled builds, ask Randall to turn an imported model into a separate character. It inherits the fighter it was fitted to and creates the original plus four recolors, matching portraits and stock icons, a CSS icon, and name banners. The result is saved to the vault as a new custom character and appears in Custom Characters; Randall does not install it into a project. It needs a prepared donor or an open project; moves, animations and audio remain the donor's, and the new character still needs an in-game test. Paired/transforming fighters and Game & Watch are not supported by this simple clone workflow.
- **Scanning a modded ISO** — Nucleus can extract non-vanilla fighters out of an existing m-ex build, so you can rip a character from a modpack you already have.

## Built-In Characters

Giga Bowser ships as a built-in custom character — he exists in Melee but is
normally unplayable, so Nucleus packages him like any other m-ex fighter.

He starts out **greyed out** in the Custom Characters grid. First-run setup only
prepares his files; building his portraits, recolored costumes and stock icons
takes a couple of minutes, and there is no reason to spend that on every install.
Click the greyed-out card and Nucleus builds him right there, showing progress on
the card. When it finishes he becomes a normal custom character with an icon
and four costumes: Normal, Red, Blue, and Green. Reopening an already prepared
Giga Bowser does not rebuild his assets.

## What The Vault Stores

Each custom character is a vault entry with:

- the original fighter package (kept intact so it can be re-exported)
- its CSS icon and per-costume portraits
- extracted metadata (name, costumes, sounds)

Custom characters appear in their own vault section, separate from vanilla-character costumes.

## The Detail View

Opening a custom character shows its costumes and support assets. From there you can:

- rename or delete the character
- browse its costume slots
- add **custom skins** to the character — drag a costume from a vanilla character onto a custom character's skin area, or import skins made for it
- assign the character to a **custom series** (the franchise symbol shown behind its portraits)
- browse and edit its **sound bank** (see [Sound Mods](Sound-Mods.md))

## Installing

Installing a custom character adds it to the open MEX project's roster via m-ex: CSS slot, fighter data, sounds, and all. Removing it takes it back out.

Sound banks and announcer calls are handled automatically on install — imported characters reuse vanilla banks where possible and get a generic announcer call, so a reskin-type character does not bloat the build with duplicate audio.

### Large rosters and Slippi

Intermittent grab and command-grab desyncs have been reported with rosters above
63 fighter entries, even when the build exports and launches successfully. This
count includes partners, hidden fighters and reserved slots, so it is higher
than the number of character-select cards. The reported threshold is not a
universal engine limit, and smaller rosters are not guaranteed safe.

**Unreleased:** Nucleus shows an advisory for oversized projects, while selecting
characters to add, and before exporting. Batch selections show a projected count;
the actual count refreshes after installation or removal. The advisory does not
block large rosters. Character-select memory and effect-table capacity are
separate constraints. See [Slippi Safety](Slippi-Safety.md).

## Testing

A custom character (or one specific skin of it) can be smoke-tested with [Test In Game](Test-In-Game.md): Nucleus builds a minimal ISO with just that character, boots it in an isolated Dolphin, picks the character on the CSS, and reports whether the match loads.

## Any Climbers: Switching and Stocks

Press **D-pad down** to switch which member of a pair you control. Both fighters
must be alive and off the respawn platform before you can switch. The stock icon
shows the character you control.

The character you control is the leader: losing that character costs a stock
and respawns the pair together. Losing only the follower does not cost a stock;
the follower returns when the leader loses a stock. These rules also apply
after switching. Rebuild the project to get the stock and respawn fix.

## Compatibility Notes

**Unreleased:** ISO scans preserve a character's separate Classic intro and
ending animations when the source build provides them. Losing those animations
could crash an imported fighter such as ACE Wolf. Rescanning the source build
fills missing animation files in an older vault package without replacing
existing packaged files. The rescan does not change project copies that were
already installed; those need the repaired package installed again. A package
missing animations cannot be repaired without the source files. This does not
resolve every Direct or Classic compatibility report.

- Characters authored in special modified builds can depend on that build's custom m-ex core. If a character crashes on a vanilla-based project with an m-ex assertion, it likely needs its original base build.
- Custom characters based on Kirby or Ice Climbers inherit those characters' special-case behavior.

## Related Pages

- [Character Mod Workflow](Character-Mod-Workflow.md)
- [Custom Stages](Custom-Stages.md)
- [Sound Mods](Sound-Mods.md)
- [Test In Game](Test-In-Game.md)
