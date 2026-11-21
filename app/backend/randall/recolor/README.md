# Recolor a costume, recolor a stage

This folder holds two starting points (the panel calls both "Retexture"). **Recolor a costume** is the pipeline
below. **Recolor a stage** is the Stage Lab with a one-step start ([Stage retexture](#stage-retexture), at the end).
What the two share (one session lookup, resuming a closed session, greyscale slots, per-texture colour edits, the
cached UV layout) is `lab_common.py`; `skin_material`, `texture_inspection` and `generate_material` serve both.
Colour that lives in no texture (vertex colours, colour animation keys) is edited the same way in both:
`model_colours.py` (the edits, their reset, the renderer reload), with each lab's own side in `stage_colours.py`
and `costume_colours.py`, over the DAT reader `shared/rendering/dat_colours.py`.

## Recolor a costume

The recolor pipeline turns one costume into a new look (colours, materials, generated surface patterns) and
saves the result as a **new** vault costume. It runs in a chat started as **Recolor a costume**
(`recipes.LAUNCHABLE`, task id `recolor_part`). Code does everything that needs no judgement: it opens the
costume the user picked, opens a private live-render session on it and collects the evidence (which texture
is which part). A cheap model is used only when code cannot tell which costume to open. The main model does
the creative work: which parts, which colours, which materials, and checking the rendered result. Nothing is
ever edited in place: every step writes a new working file, and when the turn ends code saves the result to the
vault by itself ([Saved when the turn ends](#saved-when-the-turn-ends), both labs): a new costume the first
time, that same costume updated on later turns of the chat.

The same tools also work in an ordinary chat (any chat can call `skin_lab_open`); there the main model drives
them alone and none of the stages below runs. The **Stage Lab** in this folder (`stage_lab.py`) is the same
live-render editing for stages; it is not a stage of this pipeline ([Stage retexture](#stage-retexture)).

### The stages, in order

The per-turn coordinator is `Workflow` in `workflows.py`. It has three stages (`RECOLOR_STAGES`): `acquire`,
`prepare`, `create_review`. It keeps no state of its own between turns: it advances only from the receipts of
tool calls that actually ran (`Workflow.observe`), and it never runs a tool itself. Its calls go through the
normal tool path (`assistant/tools.py` `prepare` / `execute`), approvals included.

1. **Start (the user, then code).** The user picks the *Recolor a costume* tile and a costume in the picker
   (frontend `vault/picker/CostumePicker.jsx`, `picker: 'costume'`). The first message carries
   `context.task = 'recolor_part'` and `context.selection` with exactly one costume: a vault costume
   `{id, character, name}` (`picked_costume` reads `id` as the skin id) or a stock one `{character, vanilla: true, color?}`
   (`randall/routes/assistant_bp.py` whitelists both). The pick is optional: typing works too.
   - In: the message and its context. Out: a declared recolor chat (`recipes.chat_task` reads the task from the
     first user message).

2. **Enrol the turn (code).** `assistant/engine.py` decides per turn whether the workflow runs
   (`engine._recolor_enrollment`): a declared recolor chat, a turn whose card is the recolor card
   (`recipes.turn_family`: "put it in my game" or "test it in game" are follow-ups, not a new recolor), no 3D
   model attached and waiting to be imported (`../model_import/chat/attached_model.py`; a model-only file attached
   to this very message is answered with one sentence pointing at a new *Import a character model* chat,
   `recipes.task_mismatch`), not a card-button download. `Workflow.__init__` then also requires: the workflow switch on (`NUCLEUS_RECOLOR_WORKFLOW`), a
   message that is one recolor and not a question, refusal or several costumes (`one_recolor`), and no skin
   session open yet. One typed decision per turn (`shared/aiengine/decisions.py`) supplies the acquisition gates
   (`wants_vanilla`, `wants_website`, `variant_named`) and can only lower the main model's reasoning effort.
   - In: the user text, the chat's receipts, the working state (`assistant/continuity.working_context`).
     Out: `Workflow(name='recolor', stage='acquire')`, or no workflow (the turn goes to the main model).

3. **Acquire the source costume (code first, else the cheap acquisition model).**
   - Code opens the source itself when it can (`Workflow._opening_call`, no model round): the picked costume
     (`picked_costume`: `open_vault_file` for a vault costume, `open_vanilla_file` for a stock one), else the stock
     default of the one fighter the words name when they point at no other source (`default_vanilla_source`,
     `named_fighter`, `SOURCE_WORDS`).
   - Otherwise the **acquisition lane**: Gemini Flash Lite through `shared/aiengine/fast_lane.py`
     (`FastLane('mod', policy=ACQUIRE)`), with the instruction `ACQUIRE_INSTRUCTION` and only the read-only
     acquisition tools (`ACQUISITION_TOOLS`). Its schemas are narrowed per round to ids already seen in the chat
     (`_acquisition_schemas`, from `_source_facts`), and every call it makes is checked
     (`_validate_acquisition`). Vault first; the website only after a vault search or when asked; stock costumes
     only when asked. Anything ambiguous, failed or declined hands the turn to the main model.
   - **User approval:** a website download (`download_website_mod`) always shows its approval card first
     (`assistant/approvals.py`, the download itself in `../website/`).
   - When an archive unpacks to several costume files, one more typed question picks among them
     (`Workflow._choose_source`, `SOURCE_PICK`); an unsure answer hands over to the main model.
   - In: the user text, the selection, receipts. Out: one opened costume DAT (a chat file id).

4. **Prepare the evidence (code, no model round).** `Workflow.observe` queues the calls that the engine runs as two
   code rounds (`Workflow.code_round`; a round may carry several calls, run in order): `skin_lab_open(file_id)`,
   then `skin_lab(action='texture_usage')` and `skin_lab(action='texture_sheet', page=0)` together. Then the stage
   is `create_review` with reason `evidence_ready`.
   - The open's part-scope report reads each texture and the UV layout once (the renderer's readback and the
     session's cached layout, shared with `known_parts`), and the DAT half of it (`skin_lab._scope_map`: the
     canonical map with every texture decoded) is built while the renderer starts. Measured on Fox, Mario and
     Samus with the real renderer: everything but the renderer start (~5 s) 1.5-1.9 s -> 1.0-1.2 s, the report
     0.9-1.3 s -> 0.7-0.9 s, byte-identical `part_scope`.
   - Where each colour lives (`costume_colours.py`, read from the DAT by `shared/rendering/dat_colours.py`) rides
     on the open and on `texture_usage`: every texture row and every known part gets `colour_from` (`texture`,
     `material`, `vertex`, `animation` or `mixed`), and a costume that colours anything through vertex colours
     or colour animation also gets `colour_sources` and `colour_note` (below, step 5). Usage carries it because
     the round's two results are the ones the main model gets whole (`compaction.KEEP_WHOLE`); the open's is
     shortened by then.
   - In: the source DAT. Out: a private session (`session_id`) with a rendered preview, the costume's textures,
     `known_parts` (the costume's part map when one is known, `shared/rendering/part_map.py`), `part_scope`
     (which parts share pixels), where each colour lives, texture usage and the first labelled texture sheet.

5. **Create and review (the main model).** The main model (`assistant/main_model.py`, `z-ai/glm-5.3-flash` by
   default) gets the recolor card (`recipes.CARDS['recolor_part']`, attached once with the exact signatures of
   the family's tools) and a *Code workflow state* note (`Workflow.stream`: the source file, the session, the
   surface themes the request names and any swatches saved for them earlier). It chooses the parts, palette,
   masks and materials, and reviews the rendered result. On a workflow turn, once its session is open, the
   roster is cut to `engine.SKIN_TOOLS` for the rest of that turn (so is an ordinary chat's turn that opened its
   first session itself); the user's next message gets the whole roster back.
   - **What an edit reaches (never a refusal, never a question for the user).** The model checks its target from
     the evidence before editing (`known_parts`, `part_scope`, the identify map, `highlight`); every edit is made,
     and its result names what it reached beyond the part (`skin_lab.reach`): `also_changed` lists the parts that
     read the same pixels (a part whose pixels are shared with another part changes both), unless a colour mask by
     part separated them (`analyze_palette` with `parts`: every named part has an available colour mask and every
     shared part is named or protected, `skin_lab._colour_mask_covers`); `unmapped_textures` lists the textures no
     part map covers (a model import, a restructured mod). The model reads that and the render, then separates what
     should not have changed or says so in its reply. `skin_material apply` reports the same. (Until 2026-10-04 such
     an edit was refused until the user's answer was recorded with `choose_scope`; that action is gone, and stored
     chats holding its results still load.)
   - **The identify map** (`skin_lab action=identify`, shared with the Stage Lab: `texture_inspection.identify`,
     described under [Stage retexture](#stage-retexture)) is the reverse lookup, what is drawn where. Without a
     camera a costume's is three views in one picture: front, back (a costume's back is seen in game) and a zoom on
     the head (the top quarter of the figure in the front view), one legend for all three; measured on stock Mario
     (2026-10-05), the zoom numbers the cap emblem, eyes, nose and moustache and the 8x8 textures the full view
     leaves too small. The prepare stage runs it first in its round only for a costume with no known part map or
     with unresolved parts; an ordinary costume's turn carries no extra image.
   - **One batch for the whole change** (`skin_lab action=apply`, `lab_common.apply_batch`, the Stage Lab's
     too): `edits` (up to 64), each `{kind, ...}` with the fields of the single action it stands for: `recolor`
     (one `texture_index` with a texture edit's colour change and mask, `lab_common.adjust`), `recolor_vertex` /
     `recolor_animated` (below), `set_material`, `material` (a generated swatch, below) and `reset_texture`. They
     apply in the order given (texture pixels, then material colours, then the colours stored in the file; three
     stores, so that is the order given) with one render, one checkpoint and one `viewer_update`. An edit that
     fails is listed in `failed` with its reason and the rest apply; a batch where none applies is an error. A
     texture the batch or a material writes keeps its pixels from before its first write
     (`lab_common.keep_originals`, in the workspace under `originals-<token>/`), so `reset_texture` (an action,
     and a kind) returns it there, after a resume too.
   - **Materials apply directly** (`texture_material.compose_material`): a `material` edit of a batch, or
     `skin_material action=apply` with `texture_indices` and `material_file_id`, applies in one step and its render
     is the result; `preview` stays for an uncertain mask. The default `blend` is `replace`: the selected pixels
     take the material's own colours, the alpha is never touched (cut-outs stay), and `keep_shading` (default
     0.25) lays that much of the original's light and dark over it; `blend=mix` is the older look (strength 0.75
     over the texture, the full shading).
   - **Colour in no texture** (`costume_colours.py`). No vanilla fighter colours a surface through vertex colours,
     but mods do (the Paper Mario Game & Watch in the owner's vault: 59 of its 116 objects, the red shirt and blue
     overalls included, RGB8 vertex colours only), and Yoshi's shield egg animates its material colour.
     `colour_sources` lists the objects whose colour is not simply their texture's (material ids `Model:i`, the
     renderer's own) by known part, else under `no known part` (an object belongs to a part when it draws that
     part's textures; one with no texture, as on that Game & Watch, belongs to none); `hidden` names those the
     fighter does not show by default, from its model lookup tables (`shared/rendering/lowpoly.hidden_objects`:
     the low-poly model, and alternate pieces such as other heads that moves swap in); `vertex_colours` which
     objects carry each colour. `skin_lab` `recolor_vertex` and `recolor_animated` take `edits` (up to 64, one
     preview and one checkpoint), each naming a `part` (every object drawing its textures, hidden copies
     included, as a texture edit reaches them), `material_ids` (`Model` for every object) or a `texture_index`,
     with a texture edit's change and colour mask (`model_colours.py`: formats, counts, alpha, frames and
     interpolation kept). One mesh often carries several colours, so the mask is what picks one. The result
     names `hidden_unchanged` objects (a low-poly or alternate piece carrying a colour the edit changed that it
     did not name). `reset_colors` (material ids, or none) restores them from the session's source chat file;
     `color_sources` lists them again.
   - **The same for these edits.** A buffer another object reads is copied and only the named objects move to the
     copy (`dat_colours.isolate`), so a part changes alone. What cannot be separated changes with them and is said
     (`costume_colours._reach`): `also_changed` names objects reading a pointer the named objects share (a vertex
     descriptor list, a POBJ, an AOBJ or a MOBJ two objects read, `dat_colours.entangled`), and
     `also_changed_parts` says, in parts, those objects and any object an edit by part reached that also draws
     another part's textures.
   - Such an edit is made on the renderer's exported DAT and shown by `model_colours.reload`: in place on a
     protocol-2 viewer (`setVertexColors` / `setAnimationColors`, the diff `dat_colours.colour_messages` makes;
     nothing restarts, the checkpoint's `viewer_update` carries the same messages so the workbench swaps them
     too), else the file loaded into the running renderer (`loadDat`), else (an older viewer) a fresh renderer
     started as its own is (`skin_lab._viewer`: the fighter's scene, animations and model tables), in the
     session's private folder; camera kept, the texture list checked. After a reload (not after an in-place
     update) a palette analysis resends its textures on the next recolor (the renderer holds the exported ones).
   - Budget (`assistant/engine.py`): a wrap-up note at 15 rounds (`SKIN_WRAP_UP`), a stop at 20 rounds
     (`SKIN_MAX_ROUNDS`) or 10 cents of text spend (`SKIN_MAX_COST`). Completed edits are kept, and saved to the
     vault as the stopped turn ends. Generated
     images are not in the 10 cents: each user turn has its own allowance of 3 billed images
     (`engine.IMAGE_ALLOWANCE`, `NUCLEUS_IMAGE_ALLOWANCE`; one `generate_material` sheet is one image), and a
     refused one says so plainly (`assistant/refusals.py`; [RANDALL_RECOLOR.md](../../../../docs/dev/RANDALL_RECOLOR.md)).
   - Every edit is checkpointed as a chat file (`assistant/continuity.record_skin_result`). A session that has
     closed (15 idle minutes, `close`, a backend restart) reopens from its last checkpoint on its next call, under
     the same `session_id` and without the model being told (`lab_common.live`); its workspace keeps the palette
     analysis, the scope report and choice, and the material values before the first edit, so `recolor` stays
     absolute and `reset_palette`/`reset_material` still return to the true original (`reset_colors` reads the
     source chat file the record names) and `reset_texture` the pixels kept before the first material or batch
     write. Material previews do not survive (make a new one). `skin_lab_open` on
     the checkpoint file still opens a new session.
   - In: the evidence of stage 4. Out: an edited private session and its previews.

6. **Save (code, when the turn ends).** `autosave.py` saves every session the turn edited
   ([Saved when the turn ends](#saved-when-the-turn-ends)): the first time through `save_mod_copy`
   (`assistant/hsdraw.py`), which imports the exported DAT as a **new** standard costume with fresh CSP and stock
   icon and the normal Slippi check (`vault/importing/unified/characters.py`); later turns through
   `hsdraw.update_mod_copy`, the same import moved over that costume. The source is never changed. The model
   names the result with `name` on its apply and no longer offers to save. On request it can still make a
   separate copy: `skin_lab action=export` writes the edited DAT as a new chat file and
   `save_mod_copy(file_id, name)` adds it (no approval card).
   - In: the session's exported DAT and a name. Out: a vault costume (`items` in the result).
   - The new costume's portrait and stock icon are rendered from the saved DAT, so vertex colour and colour key
     edits are in them, as `preview_portrait`'s are (measured on the Peach mod `plpeae`). Not on Mr. Game &
     Watch: the portrait path paints every G&W costume in his flat runtime slot colour
     (`generate_csp._gw_diffuse_args`, `--override-diffuse`), which also covers a mod's own vertex colours, so
     the Paper Mario Game & Watch's portrait is a black silhouette before and after an edit (its raw render shows
     the edit).

7. **After the save (other packages).** "Put it in my game" is `deliver_to_game` (`../delivery/`), "test it in
   game" is `test_in_game` (`../delivery/game_tests.py`). Both are follow-up cards (`recipes.FOLLOW_UPS`), not
   part of this workflow.

### The tools the model calls here

Every tool's schema (what the model sees) is in `assistant/tools.py` (`SCHEMAS`, `REGISTRY`); the code that runs
it is in the file below.

| Tool | Used in | Runs in |
|---|---|---|
| `open_vault_file` | acquire | `assistant/vault_items.py` |
| `open_vanilla_file` | acquire | `recolor/vanilla.py` |
| `inspect_mod_file`, `unpack_mod_file` | acquire | `shared/mod_files.py` |
| `search_vault`, `inspect_mod`, `preview_portrait` | acquire, any time | `assistant/tools.py` |
| `search_website_mods`, `inspect_website_mod`, `download_website_mod` (approval) | acquire (lane only when allowed) | `website/website_search.py`, `website/website_posts.py`, `website/website.py` |
| `skin_lab_open` | prepare | `recolor/skin_lab.py` |
| `skin_lab` (`texture_usage`, `texture_sheet`, `highlight`) | prepare, create | `recolor/skin_lab.py` over `recolor/texture_inspection.py` |
| `skin_lab` (`identify`) | prepare (no known part map), create | `recolor/skin_lab.py` over `recolor/texture_inspection.py` |
| `skin_lab` (`apply`: one batch of mixed edits) | create | `recolor/lab_common.py` (`apply_batch`) |
| `skin_lab` (`inspect`, `analyze_palette`, `recolor`, `reset_palette`, `reset_texture`, `frame`, `camera`, `texture`, `export`, `close`) | create | `recolor/skin_lab.py` |
| `skin_lab` (`materials`, `set_material`, `reset_material`, `preview_base_colors`) | create | `recolor/materials.py` |
| `skin_lab` (`color_sources`, `recolor_vertex`, `recolor_animated`, `reset_colors`) | create | `recolor/costume_colours.py` over `recolor/model_colours.py` and `shared/rendering/dat_colours.py` |
| `generate_material` (billed image request) | create | `recolor/texture_material.py` over `shared/aiengine/image_api.py`; swatches indexed by `recolor/swatch_library.py` |
| `skin_material` (`coverage`, `preview`, `apply`, `reset`) | create | `recolor/texture_material.py` |
| `save_mod_copy` | a separate copy on request (the turn's own result is saved by code, `autosave.py`) | `assistant/hsdraw.py` |
| `hsdraw` (any HSDRaw operation on a file id) | any chat | `assistant/hsdraw.py` |

The acquisition lane's own `handoff_to_main` is not an app tool: it is the fast lane's way out
(`shared/aiengine/fast_lane.py`).

### Where state lives

- **Per turn:** the `Workflow` object (`workflows.py`): stage, queued code calls, source file, session id. Gone
  after the turn; the next turn rebuilds what it needs from receipts.
- **Live sessions:** `skin_lab._sessions` in memory: at most two at once, closed after 15 idle minutes; an open
  with both in use closes the one used longest ago (`lab_common.make_room`), which reopens on its next call. The
  renderer is HSDRawViewer through `shared/rendering/session.py`, which reads each texture once until it is
  written. A vertex colour or colour key edit replaces it with one started on the edited export
  (`colours-<token>.dat` in the session's private folder); the colour evidence is cached per renderer.
- **Session workspaces:** `<storage>/assistant/skin_lab/<session id>/`: `resume.json` (source, last checkpoint,
  texture list, scope report and choice, palette groups and adjustments, material baseline) and
  `palette-<token>.npz` (the analysis snapshot). A closed session reopens from it; a checkpoint whose texture list
  differs on reload is not resumed. Pruned like stage workspaces (the newest ten and any younger than three days).
- **Files:** every working copy, preview, texture sheet, checkpoint and swatch is an immutable chat file under
  `<storage>/assistant/files/` (`shared/mod_files.py`).
- **Swatch index:** `<storage>/assistant/swatch_library.json` (`swatch_library.py`): which saved swatch was drawn
  for which surface theme, so a repeated theme costs nothing.
- **Chat and journal:** receipts in `<storage>/assistant/chats.db` (`assistant/store.py`); the task journal in
  `<storage>/assistant/tasks/tasks.db` (`assistant/tasks/`).
- **Switches:** `NUCLEUS_RECOLOR_WORKFLOW=0` turns the workflow off; `NUCLEUS_FAST_ROUTING=0` turns the
  acquisition lane off (code still opens a picked costume or a named fighter's stock default);
  `NUCLEUS_JEV_ROUTING=0` turns the per-turn decision off; `NUCLEUS_MATERIAL_MODEL` picks the image model.

### How it ends

A vault costume, saved by code when the turn ends and updated by later turns of the chat
([Saved when the turn ends](#saved-when-the-turn-ends)); a separate copy (`save_mod_copy`) when the user asks for
one. Palette maths and materials are described in `docs/dev/RANDALL_RECOLOR.md`.

## Stage retexture

A chat started as **Retexture a stage** (`recipes.LAUNCHABLE`, task id `recolor_stage`, `picker: 'stage'`) edits a
private live-rendered copy of one stage in the **Stage Lab** (`stage_lab.py`) and saves the result as a **new**
vault stage variant. There is no acquisition lane, and the prepare step is the open itself: `stage_lab_open`
returns everything the costume workflow's prepare stage collects in separate code rounds, so the main model's
first round can already edit. The Stage Lab works in any chat too (any chat can call `stage_lab_open`, and its
first call brings the same card, `recipes.family_for_tool`); there step 2 never runs.

### The steps, in order

1. **Start (the user, then code).** The user picks the *Retexture a stage* tile and, optionally, a stage in the
   picker (frontend `vault/picker/StagePicker.jsx`): first a stage from `/status` `recolor_stages`
   (`stage_lab.supported_stages()`), then one of its vault variants (the Vault's own stage list,
   `GET /api/mex/das/storage/variants`) or the stock stage. The first message carries
   `context.task = 'recolor_stage'` and `context.selection` with exactly that one entry: a vault variant
   `{kind: 'stage', stage: 'GrNBa', id: '<variant id>', name}` or the stock stage
   `{kind: 'stage', stage: 'GrNBa', vanilla: true, name}`. The blueprint checks it
   (`routes/assistant_bp._stage_item`): a stage the Stage Lab supports (its vault folder is read as the code), a
   variant whose archive `<storage>/das/<folder>/<id>.zip` exists, exactly those keys; anything else is dropped.
   - In: the message and its context. Out: a declared stage recolor chat (`recipes.chat_task`).

2. **Open the picked stage, with its evidence (code, no model round).** On a turn `engine._stage_enrollment`
   allows (a declared stage recolor, a turn whose card is the stage card and not a follow-up, no model file
   attached or waiting, not a card-button download) the engine uses `stage_start.StageStart` instead of the
   costume `Workflow`. `StageStart` also requires exactly one picked stage (`stage_start.picked_stage`), no Stage
   Lab session opened in this chat before, and a message that is one recolor now, not a question or a refusal
   (`workflows.one_recolor`). Its code round issues `stage_lab_open(stage_code, variant_id?)` through the normal
   tool path (`assistant/tools.py` `prepare` / `execute`); otherwise the main model opens the stage itself.
   - `stage_lab_open` -> `shared/rendering/stage_editor.open_stage`: a vault variant is the archive member whose
     name starts with the stage code (`.usd` preferred; an archive with several base stage files is refused);
     the stock stage is `<storage>/skinlab_stages/<file>` or is extracted from the recorded vanilla ISO
     (`shared/vanilla_extract/vanilla_refs.ensure_vanilla_ref`; `GrPs` is the `.usd`, every other stage its
     `.dat`). The copy goes to a workspace `<storage>/stage_editor/<id>/` and must have a `map_head` root; then a
     private HSDRawViewer session opens on it (`shared/rendering/session.py`). At most two Stage Lab sessions
     at once; idle ones close after 15 minutes, and an open with both in use closes the one used longest ago.
   - The open reads every texture once (`stage_lab._inventory`): the originals `reset_texture` restores, the
     **greyscale slots** (every pixel R=G=B: an intensity format whose colour comes from the material; the saved
     file keeps the format, so colour written there is lost, as measured on Pokemon Stadium), triangle counts
     from the UV layout, and the base material colours. It returns `files`: the first rendered picture, then
     labelled texture sheets (32 textures a page, up to three pages; `grey` marks greyscale slots), and
     `textures`: one compact row per texture (index, name, size, triangles, `greyscale`, `animates` for an
     animation frame).
   - It also returns the **identify map** (`texture_inspection.identify`, the reverse lookup: what is drawn HERE?),
     second in `files` after the first picture, and its table as `identify`. Three views in one picture
     (`_identify_views`, below); each is a frame with
     every texture painted one flat id colour (alpha kept but made opaque or clear), vertex colours white, and an
     object with no texture painted through its material; for a texture that only vertex-coloured objects draw and
     whose vertex colours carry the hue (Dream Land's canopy and side bushes are one texture, 29, told apart by
     vertex colour) each object is its own id (`Group g:i`). A texture whose slot stores lightness only (I4, I8,
     IA4, IA8, a greyscale palette: `intensity` in `_plan`) cannot hold an id colour, since the renderer encodes a
     painted texture in the slot's format; it is painted white and its id rides on the objects that draw it (their
     vertex colours, else their material). Final Destination's sky (texture 5, I8 over vertex colours) drew its id
     as a grey level and read as nothing (2026-11-18). Before painting, the renderer loads an **id copy** of its
     file (`_id_copy` / `_load_id_copy`, `look-ids-*.dat` in the session folder, at the frame the animation had
     reached): every material's ambient and diffuse white (diffuse the id where a material carries one), specular
     black, alpha opaque from the cut up; every blend the plain alpha blend; every colour map MODULATE with its
     colour TEV off; fog off; lights grey at their brightest channel; colour keys the same. FD's sky diffuse
     #331ea1, its additive nebula (Groups 4:1/4:2) and its fog tinted every id before. A renderer that cannot load
     the copy gets its material colours set instead (`_material_paint`, put back afterwards).
     Everything goes in at once (`updateTextures`,
     `setVertexColors`; an older viewer gets one texture at a time and keeps its vertex colours) and is put back
     exactly: the renderer reloads the file exported just before the look (`_snapshot` / `_take_back`, loadDat
     into the session's own folder, camera kept; no checkpoint, no `viewer_update`). Writing each texture back
     was not exact (2026-10-07): the renderer writes a texture into every slot of its group whose encoded bytes
     match, and flat paints in a palette format match in every slot of a size, so Dream Land saved its side faces
     (11) with the front strip's grass and its platform tops (13) with the platform sides', Fountain of Dreams'
     leaves and pillars came back in one another's colours, Skin Lab costumes changed their texture list, and CMPR
     textures lost detail to the second encode. A renderer that cannot loadDat still gets each thing put back.
     The frame is
     decoded by proportion (a colour over its brightest channel: an unlit material's gain, ~1.5x on Dream Land,
     keeps it), against each id's colour as stored (a vertex colour id through its GX format: Dream Land's are
     RGBA4), then a 5x5 majority, specks dropped and one-pixel gaps filled (leaf holes and JPEG's blurred colour
     at fine detail). The picture is drawn from the decoded ids, 1024 wide (`vision.PREVIEW_MAX_SIDE`): each id
     a colour far from its neighbours', shaded by the real render, outlined, numbered (`29`; `5:16` for
     `Group 5:16`) deep inside each sizeable region, with a legend (size, `colour_from`; ids too small to number;
     ids this camera does not see). The table gives per id its share of the picture, screen box (0..1),
     `colour_from`, format, greyscale and the objects drawing it; `major` lists the ids at 0.5% of the picture or
     2% of what it identified. Measured 2026-10-04: Dream Land's open 3.4 s -> 4.8-5.0 s, `identify` on demand
     1.0-1.2 s; every surface named in the task reads off it (canopy 5:14/5:16/5:18/5:17/5:15, trunk 25,
     platforms 14, side bushes 37, grass band 27, dirt underside 4:25, sky and rainbow 8).
   - **The three views** (since 2026-10-05; `identify` with a `camera` is still one view): (1) the game camera;
     (2) a raised three-quarter view from the front (`RAISED`: rot_x +28, rot_y +30), which shows the ground top
     and the platform tops; (3) a zoom on the busiest part of view 1 (`_busiest`: the 2:1 window, 1/2.5 of the
     frame's width, holding the most distinct small ids, under 0.5% of the frame each), rendered at that zoom so
     what view 1 is too small to number gets a number. The ids are painted once and every view is grabbed while
     they are; the session's state comes back exactly as before. A pan moves the picture the same number of
     pixels at any zoom, but how many depends on how the renderer framed the model (3.75 px a unit on Dream Land,
     55 on Mario), so it is measured once per renderer (`_pan_scale`, one panned frame, phase correlation); a zoom
     pivots on the frame centre only when the pan grows with it, so the zoom camera's pan is
     k x (own pan - window offset / px a unit) (`_zoom_camera`; Mario's own pan put the plain pivot below the
     frame). The panels are cropped to what they show (a backdrop spanning the frame left out) and laid out in
     1024 x 1024 with one legend under them (`_layout`: one row, two over one, one over two or a column,
     whichever shrinks its most shrunk panel least; under 0.45 the zoom becomes a second picture). An id keeps
     one colour and number in every panel (`display_colours` over the panels side by side). The table merges
     the views: per id `views` (its share of each, 0 where unseen), `area` (`view_area`, what the table is
     sorted by: a stage's game-camera share, or its raised-view share for a surface the game camera does not
     show; a costume's larger of front and back. The larger of views 1 and 2 put FD's side walls, 11.5% of the
     game camera but 64.8% of the raised view, above the sky, and they were recoloured as "the background",
     2026-11-18), `box` (0..1 of the whole picture, in the first panel that shows it, where `points` look
     too); `major` comes from views 1 and 2; `not_visible` is what no view shows. Measured on Dream Land with the
     real renderer: the open 3.9-4.3 s -> 5.7-7.3 s, `identify` on demand 2.2 s; the raised view shows the grass
     top (23), path (10), sand (15), pond (36) and platform tops (13), none of which the game camera sees, and
     the zoom numbers the fence (21), roots (26), Whispy's face (34), the flower strips (38) and 6:2, which the
     single view left too small; the stars on the canopy (7, 30, 32) stay too small.
   - It also says where each colour lives (`stage_colours.annotate` / `evidence`, reading the DAT with
     `shared/rendering/dat_colours.py`): every texture row gets `colour_from` (`texture`, `material`, `vertex`,
     `animation` or `mixed`, over the objects that draw it), and `colour_sources` lists per group the objects
     (by material id `Group g:i`) whose colour is not simply their texture's, with each vertex-coloured object's
     colour (`#dark..#light` for a gradient). Many stage looks are in no texture: the VsMewtwo Final
     Destination's whole background is Group 1, whose render flags take vertex colours over greyscale textures;
     Battlefield's swirl, Pokemon Stadium's sky and Dream Land's tree are vertex colours too.
   - `assistant/continuity.record_stage_result` registers the untouched source as the first checkpoint chat file
     (`checkpoint_file`, `stage_target`), so the workbench can show the stage, and writes the workspace's resume
     record. `checkpoint_file`, `revision` and `stage_target` are the workbench's: the model never sees them
     (`compaction.STAGE_UI_ONLY`).
   - In: the pick. Out: `session_id` and the evidence; or a failed receipt, which the main model is told not to
     repeat (`StageStart` reason `open_failed`).

3. **Edit (the main model).** The main model gets the stage card (`recipes.CARDS['recolor_stage']`, with the
   exact signatures of `stage_lab_open` and `stage_lab`) and a *Code workflow state* note (stage code, variant,
   session). Every `stage_lab` action works on the session:
   - look: `frame`, `camera` (rot_x, rot_y, scale, x, y), `texture` (one texture as a PNG), `inspect` (the rows),
     `texture_sheet` (page), `texture_usage` (triangles and world bounds per texture), `identify` (a fresh identify
     map, after scenery edits or with `camera` from another angle; `points` [[x,y]] (0..1 of the picture) return
     the id, texture, layers and objects under each spot), `highlight` (up to 16 `texture_indices` drawn magenta
     on the stage, then restored: where given textures draw),
     `animation` (frame, playing);
   - **the whole change in one call:** `apply` with `edits` (up to 64, `lab_common.apply_batch`), each
     `{kind, ...}`: `recolor`, `recolor_vertex`, `recolor_animated`, `recolor_lights`, `set_material` (one
     `material_id` or several `material_ids`), `material` (`texture_indices` and a swatch `material_file_id`) and
     `reset_texture`, each with the fields of the single action below and run through that action's own code; one
     upload of the textures, one `setMaterialColors`, one export and one reload (in place on a protocol-2 viewer)
     for the colours in the file; one render, one checkpoint, one `viewer_update`, one coverage line, one merged
     `also_changed`. The result says `applied`, `failed` ([{index, kind, reason}]: every other edit still applied;
     none applied is an error) and `changed_textures`, `changed_objects`, `restored_textures`. An edit without a
     `kind` takes it from its fields where they name one (a swatch -> material, field and value ->
     set_material, lights -> recolor_lights, fields -> recolor_animated, texture_index with colour -> recolor,
     material_ids with colour -> recolor_vertex or recolor_animated by what the objects carry). A `material` edit
     greys the vertex colours its textures are multiplied by (objects drawing them whose vertex colours carry hue,
     lightness kept, `vertex_neutralised` in the result) unless another edit of the batch sets them or
     `keep_vertex_colours`: Dream Land's canopy objects multiply the leaf texture by #88ff88..#ffffff, which with
     the old 0.75 blend is what tinted the owner's cotton candy green (a quarter of the old green in every pixel,
     then the green vertex colours over it). Measured with the real renderer: a nine-edit candy theme of Dream Land
     (sky, canopy vertex colours, three materials, platforms, underside, fringe, bushes) in 1.1-1.4 s;
   - colour: `recolor` with `edits` (up to 64 changes in one call, one preview and one checkpoint: each names a
     `texture_index` and an exact colour `set_hue`/`set_saturation` or a shift `hue_shift`/`saturation_shift`,
     or one exact and the other shifted (`set_hue` with `saturation_shift`, `hue_shift` with `set_saturation`;
     one field both set and shifted is refused; `lab_common.colour_change`, every colour path),
     an optional `lightness_scale` and an optional colour `mask` so only matching pixels change; applied in order
     to the texture as it is now, `lab_common.adjust` over `shared/rendering/palette.apply_adjustments`, the Skin
     Lab's own maths); the older form `texture_index` with `hue_shift`/`saturation_shift`/`lightness_scale`, or
     no `texture_index` for every texture plus the base material colours (shapes one step from these, such as
     `texture_indices` with a top-level colour or `edits` as a JSON string, are put in them first, and a refusal
     names the shape with an example: `recolor_args`, `RECOLOR_SHAPE`, `docs/dev/APP_MCP.md`); `reset_texture` (`texture_indices`, or
     none for the whole stage including the base material colours as they opened); `materials`, `set_material`,
     `reset_material`, `preview_base_colors` (`materials.py`); `replace_texture` (a PNG chat file resized to the
     texture);
   - generated materials: `generate_material` (the billed image request, `shared/aiengine/image_api.py`) then a
     `material` edit of an `apply`, or `skin_material` with the Stage Lab `session_id` (`texture_material.py`,
     through `lab_common.session`): applied directly (replace by default, as on a costume), preview optional,
     except that a stage texture keeps its own size (no enlargement: a stage file's textures share one memory
     budget) and `mode` defaults to `tile`;
   - greyscale slots refuse a colour edit, a picture and a material (`lab_common.refuse_greyscale`); lightness
     still works, and the whole-stage shift leaves them grey (`greyscale_kept`). Their colour is the material's;
   - colour in no texture (`stage_colours.py`, its edits the Skin Lab's too: `model_colours.py`): `recolor_vertex`
     changes vertex colours and `recolor_animated`
     the keys of material colour animations (`fields`, default diffuse and ambient; spline tangents follow the new
     curve; R, G and B keyed at different frames are re-keyed on the most detailed channel's frames). Both take
     `edits` like `recolor`, each naming `material_ids` (`Group g` for a whole group) or a `texture_index` (every
     object drawing it), with the same colour change and mask maths. A vertex colour keeps its GX format and
     alpha, a key its frame, interpolation and format; alpha tracks are untouched. `recolor_lights` does the same
     for light colours and their keys (edits name `lights` from `colour_sources`, or none for all: lit surfaces,
     as most of Fountain of Dreams, take their tint from them). `reset_colors` (`material_ids`, or none for the
     whole stage, lights included) restores them from the workspace's `source.dat`; `color_sources` lists the
     sources again. The
     edit is made on the renderer's exported DAT (in place; a buffer other objects also read is copied to the end
     of the data section first) and shown by `model_colours.reload`: on a protocol-2 viewer the changed vertex
     colours, key streams, material and light colours go to the running renderer (`setVertexColors`,
     `setAnimationColors`, `setLightColors`; nothing restarts, the animation keeps playing) and the checkpoint's
     `viewer_update` carries them to the workbench; otherwise the file is loaded into the running renderer
     (`loadDat`) or, on an older viewer, a fresh one (camera kept, animation back to frame 0, the texture list
     checked) and the workbench reloads. An object outside the named ones that reads one of the same
     pointers (one the file shares between them, so no copy can split it) changes with them and is named in
     `also_changed`;
   - scenery (only when asked): `scene`, `preview_objects`, `copy_objects`, `transform_scenery`, `hide_objects`
     (`assistant/stage_scene.py`).

   Each edit (a whole `apply` batch is one) returns a rendered preview and is checkpointed as a chat file (`continuity.STAGE_EDIT_ACTIONS`,
   `skin_material`'s apply and reset included). A checkpoint whose edit changed only textures and material
   values, or colours the renderer took in place (above), also carries `viewer_update`, so the workbench swaps
   them in place (card-only). A scenery edit loads its file into the running renderer (`loadDat`, camera kept)
   on a protocol-2 viewer, else a fresh one. A checkpoint that cannot be written is reported as on a costume
   (`checkpoint_error`, until the next one is).

   A whole-stage recolor reads the textures the session has not written from the renderer's readback cache
   (`shared/rendering/session.py`) and computes the edits on four threads; a protocol-2 renderer takes them as
   one `updateTextures` batch (decoded and encoded in parallel, applied in one render-thread pass;
   `lab_common.write_textures`), an older one one at a time. Measured 2026-10-04 on Pokemon Stadium (29
   textures): sending them 2.4-2.8 s -> 0.4-0.5 s, the whole recolor 3.5 s -> 1.6 s, the same pixels.

   A **theme for the whole stage** ("lava", "marijuana themed", "night": any request naming no surface,
   `stage_lab.whole_stage_request`) gives every surface its part of the theme, the major ones first (the card).
   While one runs, each edit's result carries `coverage` (`engine._stage_coverage`): the major surfaces of the
   identify table not edited yet, then every other surface still vanilla (`texture_inspection.coverage`, from the
   edits `stage_lab.track` records off each checkpointed edit, kept in the resume record), and the wrap-up note
   carries the same line. "Every other" is `units`: every identify id plus the textures no id stands for (second
   layers, animation frames), because the views barely see side and back faces (Dream Land's ends under the
   walkway, 11, were 0.09% of one view and were saved vanilla, 2026-10-07). Slots the renderer writes as one
   (one buffer in two groups, or one group's slots with the same encoded bytes: `_one_texture`) count once.
   A request naming a surface gets none.

   Budget (`assistant/engine.py`): the costume pipeline's, a wrap-up note at 15 rounds (`STAGE_WRAP_UP_NOTE`),
   a stop at 20 rounds (`SKIN_MAX_ROUNDS`) or 10 cents of text spend (`SKIN_MAX_COST`), and the turn's own
   allowance of 3 generated images (`IMAGE_ALLOWANCE`), which the text spend cannot use up; once the session is open the turn
   (also an ordinary chat's turn that opened it) sees only `engine.STAGE_TOOLS` and the latest image
   evidence. No scope refusal: the card tells the model to say in its reply what a change reached beyond the
   surface the user named.
   - In: the session. Out: an edited session and its previews.

4. **Save (code, when the turn ends).** `autosave.py` saves every session the turn edited
   ([Saved when the turn ends](#saved-when-the-turn-ends)). The first time it is `stage_editor.save_copy`, the
   save `stage_lab action=save` makes: the workspace's source hash is checked again, the export must have a
   `map_head` root, and a new archive `<storage>/das/<folder>/<name-slug>-<12 hex>.zip` is written (every other
   member of the source archive kept, the stage file replaced) with `<same>_screenshot.png` (the current frame);
   a variant `{id, name, filename, has_screenshot, screenshot_filename, date_added, slippi_tested: false,
   slippi_safe: null, randall_chat}` is appended to `metadata.stages.<folder>.variants` (the fields an imported
   variant carries, and the chat that made it). Later turns use `stage_editor.update_copy`: the same archive and
   screenshot written beside the variant's and replaced, `date_modified` set, the in-game check reset. The
   source and every other variant are never touched. The model names the result with `name` on its apply;
   `action=save` with a name makes a separate copy on request (no approval card), `action=export` returns the
   DAT as a chat file.
   - In: the session and a name. Out: a vault stage variant (`variantId`, `folder`, `stageCode`). The panel
     shows its stage card (`ModFileCards.jsx`) and, under the reply, "Start another" (`taskModes.TERMINAL_TOOLS`).

5. **After the save (other packages).** Playing it is `test_in_game kind=stage_skin` with the saved variant
   (`../delivery/game_tests.py`; the six tournament stages only), when asked. There is no delivery of a stage
   into the user's game (`deliver_to_game` takes costumes only).

### The tools the model calls here

| Tool | Used in | Runs in |
|---|---|---|
| `stage_lab_open` (`stage_code`, `variant_id?`) | open | `recolor/stage_lab.py` over `shared/rendering/stage_editor.py` |
| `stage_lab` (`apply`: one batch of mixed edits) | edit | `recolor/lab_common.py` (`apply_batch`) |
| `stage_lab` (`frame`, `camera`, `texture`, `texture_sheet`, `texture_usage`, `identify`, `highlight`, `inspect`, `animation`, `recolor`, `reset_texture`, `replace_texture`, `export`, `save`, `close`) | look, edit, save | `recolor/stage_lab.py` (sheets, usage, identify and highlight in `recolor/texture_inspection.py`) |
| `stage_lab` (`materials`, `set_material`, `reset_material`, `preview_base_colors`) | edit | `recolor/materials.py` |
| `stage_lab` (`color_sources`, `recolor_vertex`, `recolor_animated`, `recolor_lights`, `reset_colors`) | edit | `recolor/stage_colours.py` over `shared/rendering/dat_colours.py` |
| `generate_material`, `skin_material` (with the Stage Lab `session_id`) | edit | `recolor/texture_material.py` |
| `stage_lab` (`scene`, `preview_objects`, `copy_objects`, `transform_scenery`, `hide_objects`) | on request | `assistant/stage_scene.py` (the `hsdraw` tool exposes the same operations) |

### Where state lives

- **Per turn:** the `StageStart` object (`stage_start.py`), only on the turn that opens the picked stage.
- **Live sessions:** `stage_lab._sessions` in memory (at most two, closed after 15 idle minutes, the one used
  longest ago closed when an open needs its slot: `lab_common.make_room`), each with its
  open-time textures and material colours (for `reset_texture`), greyscale slots and cached UV layout. A closed
  or expired session reopens from its workspace's last checkpoint on its next call, under the same `session_id`
  (`lab_common.live`): the reset originals, the base material colours, the material values before the first edit
  and the scenery provenance are kept beside it, so `reset_texture` and `reset_material` still return to the
  true original. The reopened copy holds what the checkpoint file holds: a lossy texture format comes back as
  the saved file would have it (up to 7/255 a channel on Pokemon Stadium; Fountain of Dreams came back exact).
  A checkpoint whose texture list differs on reload is not resumed (that call gets the old "expired or closed"
  error).
- **Workspaces:** `<storage>/stage_editor/<session id>/` (`source.dat`, `source.zip` for a variant,
  `workspace.json`; for Randall also `resume.json`, `originals-<token>/` and the reopened copy
  `resumed-<file id>.dat`), the same layout the human Stage Creator uses (`vault/routes/stage_editor.py`). Each
  open prunes old ones (`stage_editor.prune_workspaces`): the newest ten and any younger than three days stay.
- **Saved variants:** `<storage>/das/<folder>/` and `metadata.stages.<folder>.variants`, like every vault stage.

## Saved when the turn ends

Both labs, in every chat (a declared retexture chat or an ordinary one that opened a lab session): the user never
has to ask for a save. `autosave.py`, run by `assistant/engine._autosave` as the turn's last step (code, no model
round, no approval).

- **When.** A reply turn ends: the model's final reply, a stop at the round or cost budget, the user's stop, a
  newer message steering in. Every session the turn edited successfully (`autosave.plan`: a checkpointed edit
  of `skin_lab`, `stage_lab` or `skin_material`, `continuity.EDIT_ACTIONS` / `STAGE_EDIT_ACTIONS`) is saved,
  plus a session whose last auto-save failed and may be retried. A turn with no edit, or whose edits all failed,
  saves nothing; so does a session whose exported bytes are those last saved (or, before any save, the source's),
  and one the model itself saved after its last edit.
- **One item per chat session.** The first save makes a NEW costume (`hsdraw.save_mod_copy`) or stage variant
  (`stage_editor.save_copy`); later turns update that item in place (`hsdraw.update_mod_copy`,
  `stage_editor.update_copy`: id, name and folder kept, files replaced atomically, portrait and stock icon or
  screenshot made again from the final state). A separate copy the user asks for ("save this as a new one",
  "keep both") is the model's own save, and the auto-save updates that newest item from then on.
- **Ownership.** Read from the chat's receipts (server-owned, in chats.db: it survives a session resume and an
  app restart): the newest successful save of the session (`autosave.owned`; a manual `save_mod_copy` belongs to
  the session whose export or checkpoint it saved). The vault item must also say it was made in this chat
  (`randall_chat`, written by both saves from the chat id the engine passes; the model cannot set it). An item
  that is gone, or made elsewhere, is never touched: a new one is made instead.
- **Name.** `name` on the model's apply (the cards ask for it: "Fox - Lava", "Dreamland - Candy"), else the name
  a failed auto-save of the session tried, else `<fighter or stage> - <a few words of the request>`
  (`fallback_name`). An update keeps the item's own name. Each successful edit's result carries `vault`, one
  line saying what code will save and under which name, so the reply says where the result is instead of
  offering to save it.
- **What the user sees.** The save is the receipt a manual save makes (`save_mod_copy` with `file_id` and
  `name`; `stage_lab` with `action: save`), placed after the reply's words: running with its progress line
  ("Saving the costume to your vault") while the portrait renders, then the saved card marked `autosave`
  `saved` or `updated` (`ModFileCards.jsx`). "Put it in my game" and "Start another" read it as any save
  (`taskModes.js`). The bookkeeping (`auto_save`: session, kind, mode, sha256 of the bytes saved, retry,
  seconds) is on the receipt, never in what the model reads.
- **Failure.** A save that fails (paired Ice Climbers, a file with no costume code, a disk error, a working copy
  that cannot be reopened) is a failed receipt with one plain sentence (`refusals.not_saved`), also appended to
  the reply. The session and its edits stay; the next turn tries again (a refusal no retry gets past waits for
  the next edit). The costume's edited file stays downloadable from that card.
- **Timing** (real renderer, scratch data root, `app/scratch/autosave/prove.py`, 2026-10-05): a new Dreamland
  variant 0.26 s, its update 0.23 s; a new stock-Fox costume 6.3 s, its update 6.1 s (portrait render and Slippi
  check), both after the reply's words were on screen. An update within a few seconds of the save before it
  waits for Windows' scanner to release the new archive (`file_retry`, measured 4.4 s).

## Files

| File | What it does |
|---|---|
| `workflows.py` | The costume recolor workflow: stages and ownership, the acquisition lane's policy, the picked costume and the named fighter's default, the code rounds |
| `skin_lab.py` | Private costume sessions in the live renderer: open, palette analysis and recolour, scope (which parts may change), export |
| `texture_inspection.py` | Texture usage, labelled texture sheets and highlights (where is texture N?), the identify map (what is drawn here?) and the coverage line, in the renderer's own index space, for both labs |
| `materials.py` | Material colour controls shared by the Skin Lab and the Stage Lab |
| `texture_material.py` | `generate_material` (image model) and `skin_material` (masked material edits with reviewable previews) |
| `swatch_library.py` | The swatch index by surface theme |
| `vanilla.py` | `open_vanilla_file`: a stock costume from the user's extracted assets as a working file |
| `stage_lab.py` | The Stage Lab: private stage sessions, their actions, and its stage list (`supported_stages`) |
| `stage_start.py` | How a stage recolor chat starts: the picked stage (`picked_stage`) and code opening it (`StageStart`) |
| `model_colours.py` | What both labs share for colour in no texture: validating a batch of edits, the vertex colour and colour key edits and their maths, the reset to the file as opened, the renderer reload (the DAT side is `shared/rendering/dat_colours.py`) |
| `stage_colours.py` | The Stage Lab's side of it: where a stage's colours live (`colour_from`, `colour_sources`), how an edit names its objects, light colour edits |
| `costume_colours.py` | The Skin Lab's side of it: where a costume's colours live (per texture row and known part, `colour_sources` with the hidden low-poly and alternate objects), edits by part, material id or texture, the scope gate for a store that cannot be separated, reset from the source file, the reload in the fighter's own renderer |
| `autosave.py` | Saving a turn's lab result to the vault when the turn ends: which sessions, the one item a chat session owns, its name, the save or update, the failure sentence |
| `lab_common.py` | What both labs share: one session lookup over both, resuming a closed session from its workspace (`live`), the material baseline, greyscale slots, per-texture colour edits through a mask, the cached UV layout, the `apply` batch (`apply_batch`) and a costume's reset_texture originals |

## Tests

From the repo root:

```
app\venv\Scripts\python -m pytest -q -p no:cacheprovider tests/backend/test_assistant_workflows.py tests/backend/test_decisions.py tests/backend/test_assistant_skin_lab.py tests/backend/test_skin_lab_scope.py tests/backend/test_assistant_texture_material.py tests/backend/test_assistant_texture_inspection.py tests/backend/test_assistant_materials.py tests/backend/test_swatch_library.py tests/backend/test_assistant_vanilla.py tests/backend/test_assistant_continuity.py tests/backend/test_stage_editor.py tests/backend/test_assistant_stage_scene.py tests/backend/test_assistant_stage_recolor.py tests/backend/test_stage_retexture.py tests/backend/test_lab_speed.py tests/backend/test_lab_resume.py tests/backend/test_stage_colours.py tests/backend/test_costume_colours.py tests/backend/test_lab_batch.py tests/backend/test_lab_autosave.py
```

A lab call without `action` runs the one its arguments name (`assistant/tools.infer_action`, `INFER_ACTIONS`:
`edits` alone -> apply, `points` -> identify, `material_id` + `field` + `value` -> set_material, a Stage Lab
`texture_index` with hue/saturation/lightness -> recolor, `texture_index` alone -> texture, `page` ->
texture_sheet, `camera` alone -> camera, ...) and its result says `action_inferred`; arguments that name none or
several still get the short "use one of" error. The real-renderer check of the batch, the materials and the three
views is `app/scratch/batch/prove.py` (scratch data root, stubbed image generator).

`tests/backend/test_fast_lane.py` covers the acquisition lane's runtime; `eval/randall/workflow_check.py` is the
live acquisition benchmark (paid, not a test). The stage picker's frontend tests are
`frontend/src/vault/picker/StagePicker.test.js` and `stagePicks.test.js`.
