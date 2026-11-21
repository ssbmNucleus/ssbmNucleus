# Skin Creator

The Skin Creator is the in-app editor for making your own costume: open a skin, paint on it, recolor it, watch the changes on the live 3D model, and save the result as a new vault skin.

## Opening A Costume

The Skin Creator opens from the vault. You can start from:

- any vault skin (there is also an "edit this skin" path from a costume's detail view)
- a vanilla costume, as a clean base

The costume loads into a live 3D viewport with its full texture list alongside.

## Arrange Your Workspace

Drag the dividers to resize the texture canvas, 3D preview, color palette, and
texture browser. Your panel sizes are remembered. Double-click a divider to
reset it, or use **Reset editor layout** beside the zoom controls to restore all
panels. You can also focus a divider and use the arrow keys.

The color tools keep a minimum working area so the palette sliders stay visible.
Color swatches scroll sideways instead of adding rows above the controls, and
you can select them with the keyboard. **Expand** gives the color tools the full
sidebar height; **Restore** brings back the 3D preview with your selection intact.
This layout is shared by Skin Creator and Stage Creator.

A fighter costume holds two models: the one you see in a match and a low-poly copy
the game draws in a few places. The texture browser sorts a character's textures
into **Model**, **Low-poly model** and **Animated** (eye blinks and other swap frames).
Most low-poly parts reuse the model's own images; those stay under **Model** with an
*also low-poly* mark, since one edit paints both. When the game files can't tell,
the browser shows one list as before.

Use **Find a texture** to filter the texture browser by name, index, or dimensions.
The selected texture's name and pixel dimensions appear below the canvas.

## Texture Zoom And Pan

- Scroll over the texture to zoom around your pointer, or use **− / +**.
- Hold **Space** and drag, middle-drag, or select the **hand** button to pan.
- **Fit** centers the whole texture; clicking the zoom percentage restores **100%**.
- With the canvas focused, **+ / −** zoom, **0** fits, and **1** restores actual size.

Zoom and pan only change your view. Painting still targets the original pixels,
and exports keep the texture's native resolution. Resizing panels preserves a
manual zoom; Fit continues fitting the texture as the workspace changes.

## The 3D Preview

The viewport is a real render of the actual DAT:

- drag to rotate, scroll to zoom, and right-drag to pan (the model stays under your cursor)
- changes you make to textures show up on the model immediately
- load the character's real animations and scrub frames to see the skin in motion

The native renderer presents the preview inside the app's canvas on Windows,
Linux, and macOS. Resizing a panel updates its render dimensions, including
display scaling. A hidden or collapsed preview pauses rendering and resumes
when shown. Camera dragging captures the pointer and stops on focus loss;
scrolling over the preview zooms without scrolling the editor.

Preview frames are separate from the full-resolution textures used for painting,
PNG export, and DAT saves. A preview connection or capability error is displayed
in the editor; reconnecting retains your paint edits. Unsupported CSP camera
mode or live animation updates are reported by the viewer instead of silently
switching transports.

For troubleshooting, Windows still supports the explicit launch environment
setting `NUCLEUS_VIEWER_TRANSPORT=embedded` for the legacy native window.
Canvas streaming is the default; a startup failure does not automatically use
the legacy window.

## Painting And Textures

Each texture in the DAT can be edited directly:

- paint on the texture canvas with the built-in tools (with undo/redo)
- **export** any texture as PNG to edit in an external editor
- **import** a PNG back onto a texture — it is resized to the texture's native size automatically

Painting and PNG export wait for the selected texture's original pixels to load.
The small images in the texture list are previews only. If reading the full image
fails, reconnect the viewer to retry; the editor does not substitute a thumbnail.

Costume DATs hide some textures in animation swaps (eye blink frames, for example); the Skin Creator exposes those too, so recolors do not miss the closed-eye frames.

## Selecting An Area

Pick the **select** tool and drag a box; every other tool then paints only
inside it, so a bucket fill or a color replace cannot escape the region.

- Drag **inside** the box to move it, or grab an **edge or corner** to resize it.
  The pointer shows which one you are about to do.
- Hold **Shift** while dragging out a new box to keep it square.
- **Ctrl+A** selects the whole texture, **Ctrl+D** or **Escape** clears the
  selection, and the toolbar shows the selection's size in pixels.

The box always snaps to whole texture pixels, but its outline is drawn a couple
of pixels thick on screen whatever your zoom is — it does not grow with the
pixel grid.

## Layers

The **Layers** tab beside the color palette stacks edits the way paint.net does,
so you can try something on top of a costume without touching the pixels
underneath.

- Every texture starts as a single **Background** layer and keeps its own stack
  while the editor is open, so switching textures and coming back is safe.
- Add, duplicate, reorder, hide, merge down and delete layers from the buttons
  at the top of the panel. Painting always goes to the **selected** layer.
- Each layer has an **opacity** and a **blend mode** (Multiply, Screen, Overlay,
  Additive and the rest). The 3D preview shows the flattened result as you work.
- Erasing on an upper layer reveals the layer below rather than punching a hole
  in the texture, and the eyedropper picks the color you can actually see.
- A PNG import replaces the selected layer, so an imported or AI-generated pass
  can be dialled back with opacity instead of overwriting everything.

Undo and redo cover layer operations as well as brush strokes, in the order you
did them.

**Layers only exist while you are editing.** A Melee texture is a single flat
image, so there is nowhere in a costume file to keep a stack: saving to the
Vault writes the flattened texture, and reopening the costume starts from one
Background layer again. Recoloring with the Color Palette tool also reflattens
the stack, because it rewrites the whole texture.

## The Color Palette Tool

The recolor tool clusters every texture's pixels into color groups, then lets you shift each group's hue and saturation as one unit.

Lightness is left untouched, so shading, folds, and seams survive the recolor. This is the fast path from "red Falcon" to "green Falcon" without repainting anything.

One caveat: details that share a hue with the thing you are shifting (eyes matching a jacket, say) move together. For surgical edits, export the texture and edit the pixels directly.

The palette defaults to **Textures + materials**, including colors stored directly
in the model. Choose **Textures only** or **Materials only** before Analyze to
limit the changes. Matching colors share the same hue and saturation sliders.
Material alpha, opacity and shininess stay unchanged. Reset restores the colors
captured by that analysis, including material colors. Animation can still override
these base values; use **Preview base colors** in Materials to inspect them.

## Material Colors

Switch from **Color palette** to **Materials** to edit colors stored in the
model itself. Choose a mesh, then adjust diffuse, ambient or specular color,
opacity, shininess, or its available texture-blending colors. Color values use
eight-digit RGBA: the final two digits control alpha. Click **Apply** to update
the live preview; **Reset** restores that field to its value before your first
edit in this session. Shared materials affect every mesh using them.

Animated materials are marked. **Preview base colors** temporarily hides color
animation so you can inspect the underlying values; saved animations stay intact.
Lighting and material settings still determine which colors affect the model.
Animation curves, vertex colors and scripted stage effects are not editable here.

These controls work in both Skin Creator and Stage Creator. Paired Ice Climbers
editing currently supports textures only. Save creates a new vault copy as usual.

## Saving

Saving exports the edited DAT and sends it through the normal import intake as a **new** vault skin:

- CSP and stock previews are generated automatically
- Slippi validation runs, exactly like a hand-imported skin
- the original costume you started from is untouched

Skins made for a custom character save into that character's skin list instead.

## Ice Climbers

Popo and Nana appear together in every Ice Climbers 3D preview, including
costume previews and the pose manager. In Skin Creator, they share one preview. The texture strip shows labeled
**Popo** and **Nana** sections side by side. Select a texture in either section
to paint its owner; each texture keeps its own undo history. PNG imports apply
to the selected texture and are cancelled if you select another texture before
loading finishes.

The Color Palette's **Adjust textures for** setting defaults to **Popo only**.
Choose **Nana only** or **Both Popo and Nana** before analyzing colors to change
the batch scope. Changing scope finishes pending adjustments and starts a new
analysis.

Saving creates a paired vault costume, including the climber you did not edit.
**Download** gives you a ZIP containing both costume files. Both files export
from the same preview state. If either export fails, the editor keeps your edits
and reports the error without saving a partial pair. Reconnect restores both
climbers' texture edits after a lost viewer connection.

Existing skins use their linked Nana costume. If that linked costume is missing,
restore it before editing. A standalone Popo skin uses the matching vanilla Nana
when that color is available.

## Mr. Game & Watch: The Color Creator

Game & Watch is special: his model carries no textures — the game paints him a
single flat color at load, so there is nothing for the Skin Creator to edit.
His character page replaces "Create New Mod" with **"Create New Color"**:

- pick a **fill** color (his whole body) and an **outline** color (the thin
  edge around him; vanilla is white)
- a live preview shows the recolored portrait as you pick
- saving creates a normal vault skin with a matching portrait and stock icon

Install it like any other skin. The color rides with the costume: installing
sets the slot's in-game color, and removing or reordering slots keeps every
color on its costume automatically.

## Stage Creator

In **Vault > Stages**, click a variant to open its edit menu, then choose
**Edit Textures**, just like character skins. **Create New Mod** starts from vanilla.
These open the standalone editor, without Randall or an AI account requirement.
Stage Creator uses the same painting,
color palette, texture search, zoom, undo, and resizable panels as Skin Creator.
The live 3D view supports rotating, panning, zooming, and animation playback.

Stage Creator works on Windows, Linux and macOS.
Opening a stage does not change its file.

Stage textures include model groups, material animation frames, and supported
standalone image symbols. **Save** creates a new named vault variant with a
preview; companion files stay in the archive and the source is untouched.
Saved variants have an untested Slippi status until checked. **Download** exports
the edited DAT. This editor makes stage reskins; collision and geometry authoring
are separate work.

Stage cards in Randall's download and save receipts have an **Edit** button that
opens Stage Creator with the conversation beside it. Clicking the card itself
opens that variant's vault edit menu. The sidebar can be closed and reopened with
**Randall** in the editor header. PNG files in chat can be applied to the
selected texture and undone. Randall's Stage Lab tools use a separate working
copy, so a tool operation does not silently change a human's unfinished edit.

## Related Pages

- [Character Mod Workflow](Character-Mod-Workflow.md)
- [CSP And Pose Workflow](CSP-And-Pose-Workflow.md)
- [Slippi Safety](Slippi-Safety.md)
