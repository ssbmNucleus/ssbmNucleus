# Extras & Effects Workflow

Extras change a character's in-game effects: colors, effect textures, and
Fox/Falco image shines. Saved extras live in the vault and are applied to the
project when you build or install.

Effects shared across large groups are labeled "Shared with many characters";
small groups still show the character names.

## What you can recolor

Almost every character has extras. A few examples:

- **Fox / Falco** — laser (beam core, band, glow, tip), Firefox/Firebird fire,
  shine (hexagon + startup flash + sparkles), Blaster flash, side-B afterimage.
- **Captain Falcon** — Falcon Punch (fire + the fire-bird texture), Falcon Kick
  foot fire, Raptor Boost (including the on-hit uppercut burst).
- **Mario / Dr. Mario** — fireball, fireball aura, cape sparkles, cape cloth,
  tornado, and the up-B coins.
- **Samus** — Screw Attack arcs and rotating swirl, missiles, charge-shot needles, and the charge
  shot ball itself.
- **Zelda / Sheik** — Farore's Wind burst, transform flash.
- **Pikachu / Pichu** — thunder, thunder jolt (ground and air), forward-smash arc.
- **Ness** — PSI Magnet, PK Thunder, PK Fire pillar.
- **Luigi, Bowser (fire breath), Jigglypuff (sing notes), Ganondorf (Warlock
  Punch, Wizard's Foot, Gerudo dragon), Ice Climbers (ice shot), Link/Young Link
  (spin attack), Kirby (stone), Mewtwo (shadow ball, bolts, up-smash)**, the
  sword characters' trails, and more.

Some character visuals need texture or model support that is not currently
mapped as an extra, such as Yoshi's eggs and several Game & Watch articles.

## Creating and recoloring an extra

Open a character in the vault, click **Extras**, and pick a move. A move is
one mod: Up-B is rings and lines, rising charge flames, the main flame, the
fire puffs with their puff texture, and the travel sparkles, saved together
under one name. Fireballs, Fire Breath and Charge Shot bundle their aura,
smoke, texture or ball the same way. Installing the mod installs every part;
Restore Vanilla restores every part.

Click a saved mod, or **Create New Mod**, and the move opens as a full page:
one row per part, top to bottom, each with its own live pictogram of the move
(that part highlighted), its color pickers, and the in-game reference where
one exists. **Recolor whole effect** at the top pushes one color through every
row, keeping each part's relative brightness; adjust any row after. Name the
mod in the header and Save.

Laser, side-B, shine, sword trails, the blaster flash, gun models and the
shield texture keep their own editors, which open as dialogs from the same
cards.

Every pictogram is live: the move's parts are layered into one simplified
illustration and the colors update as you edit. Clicking a shape in any row's
pictogram scrolls to that part's row. Up-B draws the startup scene (rings,
lines, charge flames) for its charge rows and the flight scene for the rest;
Shine separates the hexagon, flash, and sparkles.

The game image stays visible below the selected part's controls. Selecting a part highlights
its location where a mapped reference is available. Older overview crops can
show several parts together without a highlight. The game image uses example
colors; the pictogram uses your current colors. Use **Test in Game** to check the
final appearance, including textures, timing, and lighting.

Open **Recolor whole effect** for a single color or presets. The shared effects
editor preserves relative brightness when recoloring the whole effect. You can
then adjust individual parts in the color list. Click a current-color swatch to choose any color.
Give the recipe a name below the editor and save it.

Textures work the same way. Effects whose color lives in a texture rather than a
color value (Firefox fire, Samus's charge-shot ball, Bowser's fire breath,
Mario's coins, and the cast-shared fire/electric flashes) still present as a
normal color picker — the app hue-shifts the texture to match, preserving its
shading.

Saved extras live in the vault. Installing one patches the effect's DAT file in
the active project, so the recolor is part of the next build you make.

Editing a saved extra updates that recipe and keeps its active selection.
Changing Side-B colors preserves the saved transparency of each layer.
**Restore Vanilla** restores the original color variation across the effect's
records. If part cannot be safely restored, the app reports an incomplete
restore with details instead of claiming success.

## Importing effect files and image shines

Nucleus's import flow accepts supported color DATs as well as
image-shine DATs. Color files are read into editable color recipes; image shines
retain their image. Malformed files and unsupported replacement geometry report
an error instead of creating an effect with no applicable changes.

Fox and Falco also accept a PNG or other supported image through the shine image
editor. The image is normalized to the shine texture size. Shield textures use
their own texture import flow. Changing between an image shine and a gradient
restores the selected model shape; fire texture edits preserve an installed
image shine.

Website **Add to Nucleus** links carry the effect type and character. Image-only
shine downloads are imported as images, including files listed only in the
upload manifest. Import one image variant at a time; an archive containing
several candidate images needs an explicit choice. Duplicate detection uses the
same selected payload as the importer.

**Unreleased — Falco afterimage models:** Spooky Phantasm DATs import through
the normal file import or website download flow. They retain the skeleton shape
and transparency while preserving your project's other Falco edits. Support is
limited to compatible static, untextured Falco afterimage models; side-B does
not accept an image in place of a model.

An imported afterimage model can be renamed or deleted. To use editable colors,
create a separate side-B color extra; installing it restores the original
afterimage shape before applying your colors. **Restore Vanilla** restores the
original shape and colors. If the required original game data is unavailable,
the app reports the problem without replacing the fighter file.

**Unreleased — gun models:** a gun can come from a `.dae` model or from the
fighter file that carries it (`PlFc.dat` for Falco, `PlFx.dat` for Fox). A costume file such as `PlFcNr.dat` has no gun in it; the
app now says so instead of failing silently. Guns built from skinned meshes no
longer stop the game when the fighter loads. **Restore Vanilla** (the × on the
Currently in MEX card) puts the original blaster back from your vanilla ISO.

## Shared effects

Some effects are shared across characters and surface in the menu **under the
character you'd expect**, with an honest note about what else they change:

- **Fox and Falco** share shine and flight-effect components. Their laser and
  afterimage colors are separate, and Fox's charging flames are Fox-only.
  See [Fox And Falco Shared Effects](Fox-And-Falco-Shared-Extras.md).
- **Mario and Dr. Mario** share cape sparkles and the tornado; **Link and Young
  Link** share the spin-attack trail.
- **Cast-wide common effects** live in a shared file and are edited under a
  representative character: *common fire* (Din's Fire, Bowser Bomb, Roy's Flare
  Blade, and other flames), *common flash* (Vanish, Transform, thunder bursts),
  and the *electric hit-spark* (the flash when an electric-element attack
  connects — Pikachu's shocks, Zelda's lightning kicks, Falcon's knee, the
  shine, and so on). Because these are shared, recoloring one changes that effect
  for **every** character that uses it — the editor's description lists which.

## Game & Watch colors

Game & Watch's costume colors are engine-side: every costume DAT is a vanilla
copy with white materials, and the game recolors him at load from the build's
m-ex "GaW Colors" table (one fill and one outline color per costume slot). A
G&W color mod is therefore a vault skin whose zip carries a `gaw.json` sidecar
(`{"fill": "#AARRGGBB", "outline": "#AARRGGBB"}`; vanilla is black fill and a
half-transparent white outline). Installing, removing or reordering a slot keeps
the table row in step with the costume. Create one with **Create New Color** on
his character page (see [Skin Creator](Skin-Creator.md)).

## Robustness

Extras locate the effect data in the current file rather than trusting a fixed
byte position, so they keep working even after other edits shift a file's
layout. If an extra can't safely find its target, it skips that layer and warns
rather than corrupting the file.

## What "Currently in MEX" shows

On the Install page, picking an effect shows what your project's file holds
right now, found the same way an install finds it:

- **Vanilla** means every color matches the original game.
- **Custom** shows the installed colors. When they exactly match one saved
  extra in your vault, the card names it. A move with parts (Up-B's charge
  flames, a fireball's aura...) gets one extra card per part, each with its
  own Vanilla/Custom.
- **Image effect** means an image shine is installed; the card shows the image.
- **Afterimage model** (Unreleased) means a supported Falco side-B model is
  installed. The card names a matching saved extra when one can be identified.
- **Unknown** means Nucleus couldn't find the colors in this project's file
  (for example after another tool rebuilt it). It won't guess. You can still
  install over it or restore vanilla.
- Effects colored by a texture (coins, the charge ball, Firefox's flight
  puffs...) say Vanilla or Custom from the texture itself; the swatch is the
  texture's main hue, so it is marked approximate.
- Model swaps (Fox/Falco's blaster) say **Can't detect**: which model is in
  the file can't be read back, so pick one below to replace it, or (Unreleased)
  click × to put the vanilla blaster back.
- **Couldn't read** means the file itself couldn't be opened; nothing is
  assumed.
