# CSP And Pose Workflow

Nucleus has extra CSP tools on top of normal costume import.

## What The App Can Do

- generate a missing CSP on import from the default vanilla pose
- let you make and save custom poses in the app
- batch-generate CSPs for many costumes with a saved pose
- retake a single costume's CSP with the active pose from its edit modal
- generate a matching stock icon from a recolored costume
- capture HD CSPs from either the default pose or a saved pose for [Texture Pack Mode](Texture-Pack-Mode.md)

## Missing CSPs On Import

When you import a costume ZIP:

- an included CSP can be reused
- if the ZIP is missing a CSP, Nucleus can generate one from the DAT
- that generated CSP uses the character's normal default pose workflow rather than requiring you to pose it first

This gives the costume a usable portrait immediately, even if the original mod archive did not include one.

## Custom Poses

A pose is a reusable scene setup for one character.

In practice, that means you can use the app to make your own CSP poses instead of being locked to the default one.

Saved poses are useful because:

- they can be reused across multiple costumes of the same character
- they give you a consistent portrait style across a whole costume set
- they can be used later for both normal CSP generation and HD CSP capture

When possible, Nucleus also generates a thumbnail for the saved pose so it is easy to pick again later.

The 3D viewer's animation list groups moves by kind. Every special move is under Specials, including the
air versions and their start, loop and end parts, named like "Side B (Air)" or "Neutral B Start (Air)".
The Pose Manager and the 3D viewer use the same names. Samus's Super Missile is "Side B Smash", and
Kirby's copied specials carry the fighter he copied ("Fox Neutral B Start (Air)"). The fall after an up
special is under Movement, as "Fall (Special)" with its forward and back versions.
Search matches these names as well as the raw animation name.

**Create New Pose** starts from the character's default portrait framing. The viewer pane keeps at most a
2:1 shape, so the whole portrait frame stays in view on a short or narrow window.

Escape closes the innermost layer: Generate CSPs (not while it is rendering), the model menu, then
Create Pose back to the pose list, then Poses. While you type a pose name, Escape stays in the field.
Poses and Generate CSPs hide while you are on another tab and are still open when you come back.

## Retaking A Single CSP

A costume's edit modal has a **Retake CSP** button. It re-renders that one costume's portrait with the currently active pose and shows a preview before you confirm, so you can refresh a single skin without running a batch.

Next to it, **Pose** lists the default pose and every pose saved for that character. Pick one to preview the portrait in that pose; keep it and it becomes the portrait the costume shows. **New pose with this model** at the foot of the list opens the pose maker with that costume's own model loaded instead of the vanilla one, which helps when a pose made on the vanilla model sits badly on a model of another shape.

## Bulk Retake

**Bulk Retake CSPs** sits above the character grid, in the same spot as the stages' Bulk Capture Screenshots. It lists every costume in the vault grouped by character, with presets to select all costumes missing a portrait or missing an HD portrait. Each selected costume is re-rendered with its own active pose; you review the before/after pairs and apply only the ones you keep. Every applied retake saves both the normal portrait and the 4x HD one.

## Stock Icons

Recolored costumes can get a matching stock icon generated automatically. Nucleus measures how the costume's colors moved relative to the vanilla costume and applies the same movement to the vanilla stock icon's palette — so the icon follows the skin without anyone drawing pixel art. This runs at import for recolors, and the vault has a button to generate or regenerate a stock on demand.

## Batch Generation

Once you have a saved pose, you can use it to mass-generate CSPs for your costumes.

This is one of the strongest portrait workflows in the app:

- pick a saved pose
- select multiple skins for that character
- generate matching CSPs for the whole set

That is the easiest way to give a full costume library a consistent look without posing every skin from scratch.

Each selected skin shows the new pose straight away. A skin keeps one portrait per pose, so generating the same pose again replaces its picture, and the original portrait stays available under **Portraits**. The skin cards in Generate CSPs update after each run, and a pose saved again under the same name shows its new thumbnail.

## HD CSPs

Nucleus can also capture HD CSPs at a higher resolution.

The important distinction is:

- normal CSPs are the regular portrait assets the skin uses in the app
- HD CSPs are higher-resolution portrait images stored separately for HD-oriented workflows

You can generate HD CSPs from:

- the default vanilla pose
- a saved custom pose
- **Bulk Retake CSPs** above the character grid, whose **Select all missing HD** preset fills in every costume that has a portrait but no HD one

HD CSPs are always rendered at 4x resolution, and they never go inside the ISO — they exist purely for Dolphin texture-pack output. The **Manage CSPs** view on a costume shows the original and every alternate in one grid, with an HD tag on portraits that have a 4x copy; click a portrait to make it active, add one from an image, remove one, or replace the original.

That makes HD capture useful whether you want a cleaner version of the normal portrait or a full custom posed set.

## Texture Pack Mode

HD CSPs can also be generated for use with [Texture Pack Mode](Texture-Pack-Mode.md).

That workflow can use the HD portrait files instead of only relying on the normal in-project CSPs, which is what makes it useful for Dolphin texture-pack output.

## Poses On The Install Page

Applying a pose from the install page regenerates **all** of that character's in-ISO portraits with the pose — including vanilla costumes and costumes that came from a patch — so the whole select-screen column ends up in a consistent style, not just your vault skins.

## Ice Climbers Note

Ice Climbers are still the main exception.

Their portrait workflow is treated as a paired Popo/Nana portrait problem rather than two totally separate single-character portraits.

In practice, Nucleus handles the pairing automatically. You select Popo, and the app fills in the rest of the pair behavior for you.

The main current limitation is custom poses: they do not work properly for Ice Climbers yet, because their portrait setup is more complicated than a normal one-character pose workflow.

For that special case, see [Ice Climbers Pairing](Ice-Climbers-Pairing.md).

## Summary

A normal CSP is your skin's standard portrait.

A pose is a reusable recipe for making portraits.

An HD CSP is a higher-resolution version of that portrait workflow, mainly useful for HD presentation and texture-pack export.


### Ice Climbers previews

Popo and Nana appear together whenever you open an Ice Climbers 3D preview,
including the pose manager. Opening a Nana costume keeps that costume selected
and shows its Popo partner alongside it. Linked custom partners take priority;
if a linked costume is missing, restore it before reopening the preview.
Unpaired costumes use the matching vanilla partner.

The animation list includes their shared attacks, movement, and other motions
as well as specials. Playback and frame controls move both climbers together;
Nana uses her own version of a special when she has one. Saving a pose keeps the selected climber's
pose settings; the side-by-side preview spacing is not baked into your costume
or saved camera scale. Paint and save textures for either climber in Skin Creator.
