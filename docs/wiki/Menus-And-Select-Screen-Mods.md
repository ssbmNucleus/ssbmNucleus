# Menus And Select Screen Mods

Menu mods change the game's select screens and in-game HUD instead of characters or stages: the Character Select Screen (CSS), the Stage Select Screen (SSS), and the HUD textures shown during a match.

They live in the vault's **Menus** page, and install from the Menus area of the install side of the app.

## The Menus Page

The Menus page is one screen: a sidebar on the left lists every kind of menu mod, grouped by screen, with a count of what you own; the cards on the right are the mods of the selected kind.

- **Character Select**: Icon Grids, Backgrounds, Doors
- **Stage Select**: Backgrounds
- **In-Game HUD**: Pause Screens, Percent Fonts, Ready / Go / Game

Each card shows the mod's preview and name. Hover a card for its actions: rename (the small pencil by the name), replace the preview picture (for doors, this replaces the texture itself), export as a zip, and delete. Kinds with an editor — icon grids, pause screens, and HUD typefaces — open it when you click the card.

Every kind ends with a **+** card:

- **Icon Grids** — a new grid seeded with the vanilla icons, opened in the icon editor so you replace only the ones you want
- **Pause Screens**, **Percent Fonts**, **Ready / Go / Game** — a draft from the vanilla textures, opened in its editor; it only lands in the vault when you save it
- **Doors** and **Backgrounds** — a file picker for that kind (a picture for a door, a `MnSlChr` / `MnSlMap` file for a background), imported with no questions asked because the kind is already known

## The Menu Mod Types

- **CSS icon grids** — replacement sets for the character icons on the CSS
- **Menu backgrounds** — the animated backdrop behind the CSS or SSS
- **CSS doors** — the port panels ("doors") on the CSS
- **Layouts** — where the icons actually sit on the CSS and SSS
- **In-Game HUD** — pause screen textures, the damage percent font, and the Ready / Go / Game graphics

## CSS Icon Grids

An icon-grid mod is a full or partial set of replacement character icons.

Imports accept two flavors:

- **loose PNGs** named after characters — a large alias table maps names like `falc.png`, `gnw.png`, `ics.png` to the right character
- **compiled CSS files** (`MnSlChr.dat`/`.usd`, `mexSelectChr.dat`) — Nucleus extracts the icons out of the file for you

Either way the mod is normalized into one labeled icon per character, so after import you can:

- relabel an icon to a different character
- replace, add, or delete individual icons
- install the whole grid into the open project, or just one icon at a time

## Menu Backgrounds

A background mod is a model/animation bundle extracted from a menu file, plus an optional preview screenshot.

A CSS backdrop and an SSS backdrop are different models, so each screen lists its own. The **Scene settings** switch on a card also installs the background's camera, lighting, and fog; turn it off if a background looks wrong on a different screen.

If a custom CSS background is in your project, the Character Select **Background** page shows **Restore Vanilla Background** under "Currently in MEX". It puts the original Melee background back into that project only (icons, doors, characters, stages and music are not touched). Rebuild the ISO afterwards. It needs your vanilla ISO to be set up.

## CSS Doors

A door mod is a single `door.png` texture for the CSS port panels. Import a picture, preview it, install it into the open project. The picture is stretched onto the in-game 128 × 200 door and the original alpha mask is kept.

## Layout Editors

Both select screens have layout editors that read and write the open project directly:

- the **CSS layout** editor moves the character icons on the grid
- the **SSS layout** editor moves the stage icons

These need an open project, since the layout is project state rather than a vault item.

### Stage Select Pages

The **+** next to the SSS editor's page tabs adds a page laid out like the vanilla grid, with every slot Locked (the **?** icon). To put a stage in a slot, right-click it and pick a **Stage**; that unlocks the slot. A stage already on another page brings its picture along; any other stage shows its picture once you save. Remove the slots you don't need with **- Remove**, since a slot left Locked shows as **?** in game.

In game, **L** and **R** switch stage select pages when there are two or more. With one page they do nothing.

### L Alternates

A fighter on the CSS can carry a list of **L alternates**. In game, place your coin on that fighter and tap **L** to scroll through the list: Luigi, then Luigi & Boo, then Dr. Luigi, then back to Luigi. The portrait and name switch right away, and the match loads whichever fighter you land on.

Set them in the CSS layout editor's icon list: every fighter's row has a **+ L** picker. Pick a fighter there and it appears under that row as L1, then L2 and so on in the order L scrolls through them; use the arrows to reorder and × to remove. Keep using **+ L** to add more. An alternate gets no icon of its own on the grid, so each list saves grid space; the grid re-fits when a fighter becomes an alternate or stops being one. A fighter can be in only one list. The alternates must already be in the project.

## In-Game HUD

The HUD kinds cover match-time textures:

- **Pause Screen** — the texture set shown on the pause camera overlay. A plain picture works too: it replaces the central pause graphic.
- **Percent Font** — the damage number glyphs
- **Ready / Go / Game** — the match start/end word graphics

These come as texture packs in the vault and install into the open project like other menu mods. Pause-screen mods can be previewed with a live in-game capture (the **Capture** action on the card; see [Test In Game](Test-In-Game.md)).

A typeface that changes both the digits and the word banners shows under both **Percent Font** and **Ready / Go / Game** once installed.

Installing a Percent Font or Ready / Go / Game mod first puts those HUD textures back to vanilla, so nothing from the previously installed one is left over (for example its damage emblem, or a READY banner the new pack doesn't have). **Restore Vanilla** on those two pages puts the original Melee graphics back for that page only. Both need your vanilla ISO to be set up; without it a mod still installs, but pieces of the previous one may stay.

## What "Currently in MEX" Shows

Each menu page shows what is in the open project. Besides remembering what you installed, Nucleus reads the project's own files for the HUD pages (pause screen, percent font, Ready / Go / Game), the Character Select icon grid, doors and background, and the Stage Select background. This can take a few seconds the first time a page opens ("Checking the project file...").

- A project made from an already-modded ISO shows **Custom (unknown)** instead of Vanilla.
- If a file was changed outside Nucleus after an install, the page says it no longer matches that mod.
- The picture shown is saved when you install, so editing or deleting the mod in the vault doesn't change it.

## Importing Menu Mods

Menu mods go through the same floating Import button as everything else ([Manual Import](Manual-Import.md)). Nucleus detects what a file is and files it under the right kind:

- a `MnSlChr` / `MexSelectChr` file, or a zip of `=Name.png` icons → Icon Grids
- a `MnSlMap` file → Stage Select Backgrounds
- a `GmPause` file → Pause Screens
- an `IfAll` file → Percent Fonts and/or Ready / Go / Game (a full typeface mod appears under both)
- ten digit pictures (`0.png` … `9.png`) selected together → a Percent Font; three or more word banners (`ready.png`, `go.png`, `game.png`, …) → a Ready / Go / Game pack
- any other picture → Nucleus asks **What is this?** (door texture, pause picture, shield or shine image), with its best reading preselected from the name and size. A picture is never filed on a guess; use the kind's **+** card when you already know what it is.

A compiled `MnSlChr` holds both the icons and the backdrop, so it asks too: icon grid or CSS background. Batch imports take the first option instead of asking.

## Vault Vs Project, Again

The usual split applies:

- importing, editing, and deleting menu mods works on the vault and needs no open project
- **installing** any menu mod writes into the open MEX project and requires one

## A Note On Patch Builds

Some patch builds (like Animelee) paint their own CSS/SSS over the scene. When you create a project from such a patch, Nucleus resets the menu scenes to vanilla first so installed menu mods and grids behave predictably.

## Related Pages

- [Vault Vs Project](Vault-Vs-Project.md)
- [Manual Import](Manual-Import.md)
- [Test In Game](Test-In-Game.md)
