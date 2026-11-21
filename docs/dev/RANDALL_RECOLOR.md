# Randall recolor

How Randall's recolor works: skinlab palette math, materials, `texture_material`, the swatch library and the stage lab. (The REST skin-lab and the AI Skin/Stage Studios were removed 2026-10-04; see the History table in RANDALL.md.)

## Randall palette tools

### Generated materials and masked application

Randall's `generate_material(prompts)` returns one fresh registered PNG swatch per
prompt (up to four, drawn as one sheet and cut apart, for the price of one image),
provider/model and `cost_usd` when OpenRouter reports it. It uses the active
Randall request's OpenRouter key, falling back to the existing encrypted key
store/environment for standalone calls. Keys never enter schemas or receipts.
The default model is `meta/muse-image` (`image_api.DEFAULT_MATERIAL_MODEL`),
configurable through `NUCLEUS_MATERIAL_MODEL`. A transient provider error is
retried once; a timeout never is (it may have been billed). There is no provider
escalation; `swatch_library.py` lets a repeated surface theme reuse a saved swatch.
Cloudflare is not required or configured. The same swatches apply to a Stage Lab
session through `skin_material` (the recolor README's "Stage retexture").

Generated images have their own allowance per user turn, counted in billed images, not
dollars: `engine.IMAGE_ALLOWANCE` (3; `NUCLEUS_IMAGE_ALLOWANCE`), in a retexture (costume
or stage) and in an ordinary chat alike. A swatch sheet is one image (up to four
materials); `style=artwork` is one image per prompt, and a call needing more images
than the turn has left is refused before any is requested. The retexture's 10-cent cap
(`SKIN_MAX_COST`) reads text spend only, so recolour rounds can no longer starve a
material (until 2026-10-04 the image's 5-cent reservation had to fit under that cap and
a Dream Land retexture had all three materials refused unsent); the image's real charge
still counts in the chat's cost (`cost_parts.images`), the task's accounting and the
OpenRouter key's limit. A transient status the provider answered with bills nothing and
gives its image back. The fourth image is refused with "This request already generated
its three images; ask again in a new message to make more." and every later
`generate_material` of that turn gets the same answer without running
(`assistant/refusals.py`).

Identify parts with `skin_lab(identify)` (every surface painted one flat colour
and numbered with its texture index, with a table of each id's share of the
picture and screen box; `points` look spots up; both labs share it,
`recolor/texture_inspection.identify`), `texture_usage` (live geometry
counts/bounds and animation links), `texture_sheet` (32 labelled textures per
zero-based `page`), and `highlight(texture_indices=[...])` (temporary magenta
marking on the model, including linked animation frames, restored before
returning). These tools use the renderer's own indices; no part names are
inferred from colors. The model does this itself: nothing about parts or
textures is asked of the user, and no edit waits for an answer. Each edit's
result names what it reached beyond its part (`also_changed`,
`unmapped_textures`, `also_changed_parts`).

For a whole surface, run `skin_material(action="coverage", mask={...})` with
explicit color bounds before selecting textures. It scans up to 128 textures
and 4 megapixels, reports matching pixel counts and animation links, and
returns original/mask/highlight sheets for the first 32 matches. Any unscanned
indices are explicit; narrow with `texture_indices` to inspect more. A texture
containing an eye or ear can also contain a large skin background: select that
background while protecting iris, whites and other details. Color matches are
candidates to inspect, not automatic permission to change every matching part.

A material applies in ONE step (since 2026-10-05): a `material` edit of a
`skin_lab`/`stage_lab` `apply` batch (with the colour edits of the same request,
`recolor/lab_common.apply_batch`), or `skin_material(session_id,
action="apply", texture_indices=[...], material_file_id=...)`; the reply's
render is the result and `reset` / `reset_texture` undo it. How it lands is
`texture_material.compose_material`: `blend="replace"` (default) gives the
selected pixels the material's own colours, never touches alpha (cut-outs stay;
with no colour mask the colour under a cut-out takes the material too, so the
old colour cannot ring the holes), and lays `keep_shading` (0..1, default 0.25,
chosen by looking at Dream Land's canopy and trunk at 0, 0.25 and 0.5) of
the original's light and dark over it; `blend="mix"` is the older look, the
shaded material at `strength` 0.75 over the texture with full shading. The
batch's material edit also greys the vertex colours its textures are multiplied
by (lightness kept), unless the batch sets them or `keep_vertex_colours`: the
old blend plus Dream Land's #88ff88 canopy vertex colours is what turned a
cotton-candy canopy green.

The preview stays as an option for an uncertain mask:
`skin_material(session_id, action="preview", texture_indices=[...],
material_file_id=...)`. Indices from headless HSDRaw
are not assumed interchangeable. Preview supports
1..32 textures, at most 4 megapixels combined, and returns labelled
original/mask/candidate sheets (eight rows each) plus a `preview_id`. This lets
the body, face backgrounds and expression variants share one projection and
shading reference. It reports unselected matches from the last coverage scan
using the same mask, plus unselected linked animation frames. It does not write textures.
`mask` accepts `hue_min/max` (0..360, wrapping allowed), `sat_min/max` and
`lum_min/max` (0..100). Without bounds it selects pixels with alpha >=128.
Optional `mask_files` entries (`texture_index`, PNG `file_id`) intersect the
color mask: white selects, black/transparent protects, grey blends. PNG masks
must match original target dimensions. Color masks have no semantic understanding of
logos, stitching or other details.

`mode="project"` (default on a costume; a stage defaults to tile) samples the swatch in shared model space using
`getUVLayout`, including linked animation frames. `world_scale` controls the
distance per repeat; omission derives it from model bounds. Missing geometry
is an error; callers may explicitly choose `mode="tile"`, where `tile_size`
sets pixels per pattern repeat (default 32). In project mode tile_size sets
the swatch sampling resolution. `strength` (default 1 with replace, .75 with
mix) blends against the snapshot; `keep_shading` (older name `shading`;
default 0.25 with replace, 1 with mix) is the retained lightness modulation.
`minimum_size` defaults to 128 for the canvas's longest side. Smaller canvases
grow by powers of two with nearest-neighbor sampling, preserving aspect ratio,
protected pixel footprints and alpha; masks grow with them. Choose 1 to retain
original dimensions, or 32/64/128/256/512. Preview reports original and proposed
dimensions; selected pixel counts measure masks, not visual quality.
Native encoding may quantize RGB. The live viewer retains unquantized pixels,
so previews can differ from the exported DAT. Its cached dimensions and
thumbnail must update on resize; Python rejects stale-size readback and rolls
back rather than reporting success with an older native viewer.

After a preview, call `skin_material` with only `session_id`,
`action="apply"`, and `preview_id`. Apply returns a live 3D preview. Refine
with `action="preview"`, that ID and changed controls: omitted controls retain
their values and all refinements use the original baseline, even after apply.
Repeating the same target/swatch while refining is accepted; actually changing
either requires a new preview. Use the new returned preview ID.
`action="reset"` restores the baseline pixels and original dimensions.
Every apply/reset/refinement checks actual pixels against the last native
readback and rejects stale plans. Apply clears any older palette analysis.
Up to four plans live in each session and expire with it. Native write failures
attempt to restore the prior working textures and report incomplete rollback.
The result is saved to the vault by code when the turn ends (see *Saved when the turn ends* below);
`skin_lab(export)` and `save_mod_copy` remain for a separate copy the user asks for.
Only explicitly selected texture indices change; inspect other variants before
claiming complete coverage. Swatches and mask sheets collapse into tool rows
but remain visible to Randall; applied 3D previews appear in the thread.

### Continuation and palette brightness

Validated tool arguments are saved in receipts without request credentials.
`randall/assistant/continuity.py` reconstructs sources, generated swatches, session
status and preview controls independently of the last eight tool receipts.
Successful costume edits made through Randall tools return an immutable
`checkpoint_file`. A session that expires, is closed or is lost to a backend
restart reopens from its last checkpoint on its next call, under the same
session id (`recolor/lab_common.live`): its workspace keeps the palette
analysis, the part scope and the material values
before the first edit, so recolors stay absolute and resets return to the true
original. Stage Lab sessions reopen the same way, with the textures and base
material colours `reset_texture` restores. Material previews do not survive a
reopen (make a new one); `skin_lab_open` on a checkpoint still opens a new
session. Swatches persist independently of sessions. A checkpoint failure is
reported separately from the successful live edit (`checkpoint_error`, on
costume and stage edits alike); explicit export remains available.

Vision rehydrates the latest 16 images plus the latest swatch and 3D render
when outside that window. Every image has file/session/action labels; older
images are identified as historical, and omissions are explicit. A seven-call
texture batch is delivered in full. Pixels remain outside the chat database.
`inspect_mod_file` can reattach a stored PNG's visual evidence.

Skin palette adjustments accept `lightness_scale` (0..2, default 1), applied
to original lightness alongside hue/saturation controls. Values below 1 darken
without flattening relative shading. Alpha and unselected groups are unchanged;
repeated edits are absolute from the analysis snapshot, and reset restores it.

### Material colors (costume and stage sessions)

Both `skin_lab` and `stage_lab` accept `materials`, `set_material`,
`reset_material`, and `preview_base_colors`. Inspect `materials` to discover
session-local `material_id` and `field`; setters take a `value` (eight-digit
RGBA for colors, also `#rrggbb` or `[r, g, b]`, which keep the field's own alpha,
or `[r, g, b, a]`; 0..1 for `alpha`, 0..128 for `shininess`). The preview action
takes boolean `enabled` and never changes exported descriptors. Edits mark the
private working copy dirty and return a rendered preview; saves retain the
existing copy-only policy. Reset restores the field's first-edit original, even
through another mesh sharing the same descriptor. Pair-mode material editing
is not supported.

`randall/recolor/materials.py` performs discovery-based validation;
`ViewerSession.material_command` waits for typed native acknowledgements and
raises native errors. HSDRawViewer `MaterialColors` edits actual HSD material
and existing TOBJ TEV descriptors, including separate TEV alpha bytes. It does
not enable render flags, create missing TEV blocks, edit animation curves or
vertex colors. Material and texture AOBJs sample their own duration and loop
flag; live shader state resets before sampling to avoid stale animation values.

### Vertex colors and animated colors (stage and costume sessions)

HSD colours a DOBJ from its textures (combined by each TOBJ's colour map), its
material descriptor, its POBJ vertex colours (GX_VA_CLR0/CLR1) and material
animations (MatAnimJoint -> MatAnim -> AOBJ -> FOBJ diffuse/ambient/specular
R, G, B tracks, which replace the descriptor colour every frame). Bits 0-1 of
the MOBJ render flags pick the colour channel's source: 1 material, 2 vertex,
3 both. `shared/rendering/dat_colours.py` reads all of it from the DAT (and
lights and fog), keyed by the renderer's own material ids (`Group g:i`), and
classifies each object (`colour_from`: texture, material, vertex, animation or
mixed: the store that carries hue, or, for a grey object, the store an edit
would have to change).

Measured (2026-10-04, vanilla files and the VsMewtwo Final Destination variant):
every vertex colour in the stages checked is stored DIRECT in the display list
(RGB8, RGBA6, RGBA4, RGB565, RGBA8). The VsMewtwo background is Group 1: six
DOBJs with render flags 0x40000012/0x60000012 (vertex source, lighting off,
TEX0 modulate) over greyscale CI8/I4 textures, so its colour is 234 RGB8
vertex colours (#a3d9e7, #e7f5f5, #a331ef purple, #7e6cd9..#9597e5, and a
154-vertex #000000..#d1fcf4 gradient); not animated (its MatAnim only
scrolls UVs). Vanilla Final Destination's nebula (Group 4, RGBA6 over I8),
Battlefield's swirl (Group 5, 3037 RGBA6), Pokemon Stadium's sky (Group 1,
RGB565), Yoshi's Story's sky and ground and Dream Land's tree (RGBA4) are
vertex colours too. Animated material colours: Final Destination, Battlefield
(Group 3) and Pokemon Stadium (the red lamps, Groups 2 and 5); a fighter only
on Yoshi (two DOBJs on joint 3).

`randall/recolor/stage_colours.py` puts `colour_from` on every texture row and
`colour_sources` in the open, and adds `stage_lab` actions: `recolor_vertex`,
`recolor_animated` (fields default diffuse and ambient), `recolor_lights`,
`reset_colors` and `color_sources`. The edits, their reset and the reload are
`randall/recolor/model_colours.py`, which the Skin Lab uses too (below).
Edits use the texture recolor's change and mask (`lab_common`);
a key's value is computed unrounded with the same formula, a spline tangent is
the new curve's slope, and R, G and B keyed at different frames are re-keyed on
the most detailed channel's frames (a red pulse over constant green can only
become a green pulse that way). Formats, counts, alpha, frames and
interpolation are kept. The edit is applied to the renderer's exported DAT in
Python; a buffer that other objects also read (HSDRaw merges identical buffers
on save) is appended as a copy first and only the chosen pointer fields move
(`dat_colours.isolate`). One pointer field that two objects read (a vertex
descriptor list, a POBJ, an AOBJ or a MOBJ they share) cannot be split that
way: `dat_colours.entangled` names those objects and both labs report them as
`also_changed` (the Skin Lab adds `also_changed_parts`, in parts).

How the edited bytes reach the renderer (`model_colours.reload`), first that
works: (1) in place, on a viewer that announces stream protocol 2
(docs/dev/VIEWER_STREAMING.md): `dat_colours.colour_messages` diffs the export
before and after the edit into `setVertexColors` / `setAnimationColors` /
`setLightColors` (the changed vertex colours as decoded RGBA, whole key
streams by structural key, material and light colours), which the viewer
writes into its loaded structures with the same isolation rule, so the picture
and its next export match a fresh renderer on the edited file (measured
2026-10-04: identical frames on VsMewtwo FD vertex colours, Pokemon Stadium
lamp keys at frames 0/30/90/150, the Paper Mario Game & Watch shirt; 0.6-0.8 s
per edit instead of 5-6 s); the messages ride on the checkpoint's
`viewer_update` (`colours`, stored by `continuity.keep_colours`, fetched from
`/api/assistant/viewer-updates/<id>`) so the workbench's 3D view swaps them in
place too; (2) the edited file loaded into the running renderer (`loadDat`);
(3) with an older viewer (the pre-protocol-2 release, the Linux/Mac headless
builds), a fresh renderer on the edited file, as before. Each path checks that
the renderer lists the same textures; a failure falls through to the next.

**Costumes** (`randall/recolor/costume_colours.py`, the Skin Lab's side). The
reader names a costume's objects and textures as the renderer does: `Model:i`
(every DOBJ of the first `_joint` root in joint pre-order, HSDRawViewer
MaterialColors' ids, so `set_material` and these edits share them) and
`Texture_n` (the renderer's texture index). Vanilla fighters do not colour
through vertex colours; modded ones do. Measured 2026-10-04 on the owner's vault
(copies in a scratch data root):

- Paper Mario Game & Watch (`pap-mario-plgwnr`): 59 of 116 objects take RGB8
  vertex colours (render flags 0x2, no texture), 14 material, 2 texture+vertex.
  One mesh carries several colours: Model:0, the body, holds the overalls
  `#1c4784`, the shirt `#c02929`, the buttons `#dec542` and skin `#e1bd7e`;
  the sleeves are Models 18 and 37; the low-poly body and sleeves 23, 26, 31;
  the head 17 and its alternates 16, 42, 108 carry the cap's `#c02929` too. A
  red colour mask over 0, 18, 37, 23, 26, 31 turns the shirt green and leaves
  the overalls, buttons and cap as they were; the result names the low-poly and
  alternate heads (`hidden_unchanged`) that carry the same red.
- Peach mod `plpeae` (Aerith): 11 objects multiply its texture atlas by RGBA8
  vertex colours (texture+vertex); 48 draw an I4 texture coloured by the
  material. Its magenta vertex colours are the waistband, the hair ribbon and
  the lips.
- Yoshi (vanilla): the only fighter colour animation is his shield egg (joint 3:
  Model:35, an alternate piece, and its low-poly copy Model:34), whose diffuse
  and ambient fade from white to dark red over 100 frames. Both are hidden by
  default, so the Skin Lab's render does not show an edit to them.

Evidence: `colour_from` on every texture row and every known part (its objects
are those drawing its textures); with any vertex or animated colour,
`colour_sources` (`by_part`, else `no known part`; `hidden`: low-poly and
alternate objects from the fighter's model lookup tables,
`shared/rendering/lowpoly.hidden_objects`; `vertex_colours`: which objects carry
each colour, an object's two to four flat colours or `#dark..#light`). It rides
on the open and on `texture_usage`, the result the recolor workflow's prepare
stage leaves whole for the main model. Edits (`skin_lab` `recolor_vertex`,
`recolor_animated`, `reset_colors`, `color_sources`) name a `part`, `material_ids`
or a `texture_index`; a part reaches every object drawing its textures, hidden
copies included. Scope: a shared buffer is copied, so a part changes alone; a
shared pointer, or an object drawing another part's textures too (an edit by
part), changes with them and the result says so (`also_changed_parts`). The session
reopens the edited export in a renderer started like its own (the fighter's
scene, animations and model tables); reset reads the session's source chat
file, so it survives a resume. The saved costume carries the edit (re-read from
the saved archive), and so do its regenerated portrait and `preview_portrait`
(Peach). Mr. Game & Watch's portrait path paints every G&W costume in his flat
runtime colour (`generate_csp --override-diffuse`), which also hides a mod's
own vertex colours: the Paper Mario G&W renders as a black silhouette, edited
or not, while a render without that override shows the green shirt.

Lights: a lit DOBJ (render flag DIFFUSE) is tinted by its group's LOBJ colours.
Fountain of Dreams lights 120 of its 197 DOBJs with purple lights (#4b259d,
#856fa6; one animated through LITC R/G/B tracks), so `recolor_lights` changes
LOBJ colours and their keys with the same maths (`colour_sources` lists hued or
animated lights; a LOBJ holds pointers, so one shared by two light entries
changes for both). Fog is read, not edited: the renderer does not draw it and
every stage checked has black fog (Final Destination, Battlefield) or none.

### Combined material and texture palette

`skin_lab(analyze_palette)` includes base material colors by default when
`texture_indices` is omitted. `include_materials` overrides that choice; an
empty texture list with `include_materials=true` supports material-only analysis.
Selected texture indices default to excluding materials to preserve scope.
Material RGB samples have weight 100 (the palette's minimum group size), with
synthetic opaque alpha; actual descriptor alpha is retained separately. They
join texture hue groups, including hues absent from textures. Recolor and Reset
use the same analysis snapshot, so shifts stay absolute and restore correctly.
Numeric material fields and animation curves are untouched. `stage_lab(recolor)`
includes base materials for whole-stage recolors by default, with the same
`include_materials` override; its shifts remain relative to the current stage.

### Texture palette

Randall exposes `skin_lab_open(file_id)` and `skin_lab(session_id, action, ...)`
through `backend/randall/recolor/skin_lab.py`. This creates a private `ViewerSession`
from an opaque registered costume DAT, separate from both the REST singleton and
the human editor. Vault inputs use `open_vault_file` and, when needed,
`unpack_mod_file`. No model-supplied filesystem paths are accepted.

Actions: `inspect`, `frame`, `camera`, `texture`, `analyze_palette`, `recolor`,
`reset_palette`, `export`, `close`. Analysis uses full-resolution viewer textures
and `shared.rendering.palette`, with optional texture indices and 1–16 groups. Adjustments
use `index`, `hue_shift` (±180°), `saturation_shift` (±100 percentage points).
Values are absolute from the latest analysis; omitted groups retain their values,
zero resets a group, and reset restores the whole snapshot. Alpha and lightness
are preserved. Limits: two live sessions per lab (an open with both in use
closes the one used longest ago, `lab_common.make_room`), 15-minute idle
expiry (either way the next call reopens the session from its last checkpoint), 512 textures and 16 megapixels
per analysis. The viewer texture inventory defines coverage;
palette editing is not a gameplay or Slippi test.

Export registers a fresh immutable DAT retaining its vault origin. Existing
`save_mod_copy` performs a new-copy vault import, artwork and Slippi checking.
Dropped originals remain downloadable copies; paired climber saves require the
Texture Lab.

### Saved when the turn ends

A retexture is saved to the vault by code, never by the model deciding
(`randall/recolor/autosave.py`, called by `assistant/engine._autosave` as the
turn's last step). When a reply turn ends (the final reply, a stop at the round
or cost budget, the user's stop, a newer message steering in), every Skin Lab or
Stage Lab session the turn edited successfully is saved; a turn with no edit, or
whose edits all failed, saves nothing, and neither does a session whose exported
bytes are what was last saved (or, before any save, the source's). It applies in
every chat, declared retexture or not.

- **One item per chat session.** The first save is a NEW costume
  (`hsdraw.save_mod_copy`) or stage variant (`stage_editor.save_copy`): the same
  save a request makes. Later turns on the same session update that item in place:
  `hsdraw.update_mod_copy` imports the new file through the same importer under a
  throwaway name, moves its archive, portrait and stock icon over the costume's
  (each `file_retry.replace`) and drops the throwaway entry in one metadata
  transaction; `stage_editor.update_copy` replaces the variant's archive and
  screenshot (each written beside it, then replaced). Id, name and folder stay.
- **Ownership** is read from the chat's receipts (chats.db: it survives a session
  resume and an app restart): the newest successful save of that session, the
  model's own `save_mod_copy` / `stage_lab save` ("keep both") included, so the
  newest item is the one updated. The item must carry `randall_chat` equal to
  this chat (both saves write it; the engine passes the chat id, the model never
  can); anything else, or an item that is gone, is never touched: a new one is made.
- **Name:** `name` on the model's apply call, else the name a failed auto-save of
  the session tried, else "<fighter or stage> - <a few words of the request>"
  (`autosave.fallback_name`). An update keeps the item's own name. Each successful
  edit's result carries `vault`, the line telling the model what will be saved and
  under which name.
- **What the user sees:** the save is the receipt a manual save makes
  (`save_mod_copy`; `stage_lab` with `action: save`), shown running with its
  progress line while the portrait or screenshot is made (the reply's words are
  already on screen), then the saved card with `autosave: saved|updated`;
  "Put it in my game" follows a costume as after a manual save.
- **Failure:** one plain sentence (`refusals.not_saved`) on the receipt and at the
  end of the reply; the edits stay; the next turn tries again (a refusal no retry
  gets past, such as paired climbers, waits for the next edit).
- **Timing** (real renderer, scratch data root, 2026-10-05): a new Dreamland
  variant 0.26 s, its update 0.23 s; a new stock-Fox costume 6.3 s and its update
  6.1 s (portrait render and Slippi check). An update within a few seconds of the
  previous save waits for Windows' scanner to let go of the new archive (measured
  4.4 s). Owned viewers and private temporary sources are cleaned on close,
idle expiry or backend shutdown; the session's resume record
(`<storage>/assistant/skin_lab/<session id>/`) stays, pruned like stage
workspaces.

`randall/assistant/vision.py` resolves only PNG handles returned by lab tools and attaches
bounded 1024px JPEGs to the next provider request, after all pending tool replies.
Only the latest round of image bytes remains in request context; bytes are not
persisted in the transcript. Chat continues displaying the original PNG cards.
The configured OpenRouter model must support image input. No image generation
API is used.

## Live Stage Creator and Randall Stage Lab

Stages now render in `StreamingServer` via the shared `StageScene`, including
map groups, lights and animations. Stage Creator reuses the human Skin Creator
controls; its source/copy-save API is `/stage-editor/open|save` (see API_REFERENCE).
Randall's `stage_lab_open`/`stage_lab` use owned `ViewerSession` instances and
that same renderer, with separate workspaces. PNGs can move between chat and the
human editor. The open (and `stage_lab action=identify`) returns the identify
map: one render with every texture and vertex-told object painted a flat id
colour, put back exactly afterwards, decoded into a numbered picture and a table
(share of the picture, screen box, `colour_from`, objects) so a surface's id is
read off it rather than guessed; without a camera it is three views in one
picture (the game camera, a raised three-quarter view of the ground and platform
tops, a zoom on the busiest small scenery; a costume: front, back, head zoom)
with one legend. A whole-stage theme's edits carry `coverage`, the major
surfaces not edited yet, and the whole theme goes in as few `apply` batches as
it can (`app/backend/randall/recolor/README.md`, Stage retexture).

### Randall scenery transfer

`stage_lab` adds `scene`, `preview_objects`, `copy_objects`, `transform_scenery`,
`hide_objects` and `export`. Open the source and destination in the two private
sessions. Inspect both scenes, then preview exact `group:joint:mesh` object IDs;
IDs and `collision_linked:false` do not identify background meshes semantically.
`copy_objects` takes `source_session_id`, `object_ids` from one donor group,
and a destination `target_group` whose inspection says `can_receive:true`.
The result includes a rendered PNG, immutable DAT and opaque `instance_id`.
`transform_scenery` moves only an instance created in that working file's
lineage. Transforms are absolute: x/y/z in stage world units, rx/ry/rz in
degrees, and uniform scale; omitted components reset to zero/one. `hide_objects`
removes drawable geometry for exact IDs while keeping joints and DOBJ slots.
The result is saved as a vault variant when the turn ends (*Saved when the turn
ends*, above); `save` creates a separate new variant on request, preserving
companion archive members.

`randall/assistant/stage_scene.py` provides the same operations for immutable file IDs
through `hsdraw`. It validates IDs, transforms and provenance, copies inputs to
scratch, and invokes fixed `--stage-scene inspect|edit` commands. There are no
caller paths or CLI arguments. Selection is capped at 256 objects, combined
groups at 4096 joints, and output at 128 MB. Live edits launch a replacement
owned viewer and obtain its preview before replacing the current session; a
failed replacement leaves the current viewer usable.

Native `StageScenery.cs` copies a donor skeleton and selected drawable meshes,
retains materials/textures, appends under an identity destination root, and
grafts supported joint/material animation trees without shifting existing
indices. Each destination animation slot receives the selected donor clip
(`animation_index`, default zero). Donor external symbols, constrained or
instanced joints and shape animations are rejected. Particle/spline attachments
are omitted. Hiding collision-linked groups is rejected. Destination collision,
spawns and stage parameters are retained; donor game scripts and lighting are
not transferred. Stage code may control animation playback differently, so a
rendered preview is not gameplay or Slippi validation. No ISO export is exposed.

Material preview handles are not silently evicted after four entries. A session
retains up to 32 previews within a 256 MiB array budget; hitting the budget rejects
the new preview and preserves existing ones. Refinement replaces its prior handle.
`overlapping_previews` identifies shared texture indices; applying one makes the
others stale even when their masks target different colors. Tool calls execute
sequentially. `save_mod_copy` accepts edited vanilla-derived costumes with recorded
character/color provenance as well as edited vault costumes, always importing a
new item with fresh artwork and the normal Slippi check. Paired climbers still
require the Texture Lab.
