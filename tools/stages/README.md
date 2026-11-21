# Stage workbench

Agent tools for freeform Melee stage work, exposed as **`stage_workbench`** in
the Nucleus developer MCP (`melee-harness`). The agent still designs the stage,
writes custom scripts, chooses source assets and iterates with the user. There
is no required sequence, project manifest, end-user harness, or one-click claim
that an arbitrary model has become a good stage.

These are the useful shared parts of the Pokémon Colosseum and CS2 builds.
The native graft code preserves their animated donor import, mesh construction,
texture sharing, material animation, particle cleanup, skin baking and optional
stage-specific helpers. It is source-only: no game assets or machine paths ship.
This developer tool is separate from Randall's unimplemented stage-import tile.

## Calls

All tool paths are absolute. Paths *inside* a spec resolve relative to that spec.
Outputs must be new filenames; input assets and earlier revisions are never
overwritten. Call `guide` again whenever orientation helps.

| Operation | Inputs | Result |
|---|---|---|
| `guide` | none | This guide and the tools directory |
| `inspect` | `file`, optional `stage` | Archive roots, model groups / scene descriptors, mesh and animation counts, collision-data digest, file size and optional reference budget |
| `mesh` | `spec`, `out` filename prefix | `.mesh` + `.img`, and an entry ready for `cs.meshes` |
| `graft` | `spec`, `out` DAT, optional `stage` | New stage, inspection, collision comparison; defaults leave existing meshes intact |
| `cameras` | `stage`, optional `camera`, `views`, `out` | Ten settled match-camera views, or your own views; optional sweep JSON |
| `package` | `files` mapping archive names to source paths, `out` ZIP | Verified ZIP, CRCs and SHA-256; no install |

Before the MCP client reconnects, the identical interface is available through
`python -m tools.stages.workbench request.json` from the repo root, using the
app's Python environment. Inspect/graft compiles .NET 8 source on first use
against `core.config.HSDRAW_EXE`'s HSDRaw.dll; binaries go under app scratch,
cached by source and DLL content. It requires the .NET SDK, not a separate
hardcoded builder installation. Other operations do not compile anything.

## Choose the approach for this stage

- **Animated 3D scenery:** keep source depth, models and material animations.
  Colosseum is the reference. Its water should move; flattening the village
  into a picture changes the requested design. `flatten` in a *donor spec*
  expands HSD instance joints; it does **not** flatten a model into an image.
- **Baked or hybrid scenery:** render selected source geometry in Blender,
  then use a background board plus real stage-body/prop meshes if appropriate.
  CS2 used this intentionally. Plan overscan against match cameras before
  spending time on a high-resolution bake.
- **New layout, collision or hazards:** author those separately using the
  existing HSDRaw/MexCLI tools or custom code. Grafting visual meshes does not
  create floors, ledges, blast zones, spawn points or stage logic. A legal-stage
  skin normally inherits those from its chosen base; a new stage need not.

The source reader is also freeform: `iso_file` for local GameCube extraction,
`hsdraw` for HSD model export/texture work, Blender/glTF or source-specific
extractors for other games. No source-specific extractor is silently run by
this tool. Use the user's local assets and keep them out of source control.

## Minimal graft spec

```json
{
  "target": "base/GrNBa.dat",
  "receive_group": 0,
  "clear_groups": [],
  "donors": [],
  "cs": {
    "meshes": [{
      "name": "my_geometry", "mesh": "body.mesh", "tex": "body.img",
      "mips": false, "wrap": "clamp", "colors": false, "cutout": false
    }]
  }
}
```

This is a format example, **not a stage-specific group recommendation**. Inspect
the target and choose its receiver deliberately. Append geometry to preserve
joints the game's stage code indexes. `clear_groups` removes meshes, not joints.
`joint: [group,index]` on a mesh attaches it to an existing moving joint;
`minus_joint: true` subtracts that joint's translation from stage-space input.
The complete optional operations remain in `native/Program.cs`, `Cs.cs`,
`Colo.cs`, `Path.cs`, `Bf.cs`, `Fod.cs`, `Stage.cs`, `Props.cs`, `Downscale.cs`.
Unknown creative fields are not filtered by the Python wrapper; the native
builder reads the supported fields (it does not validate unknown spellings).

A Colosseum donor can be added to the same spec:

```json
{
  "wrappers": [{"t": [0, -100, -120], "s": 1.0}],
  "donors": [{
    "file": "source/scene.rdat", "desc": 0, "wrapper": 0,
    "flatten": true, "bake_envelopes": true, "strip_ptcl": true,
    "anim": true, "joint_anim": false, "mat_anim": true, "loop": true
  }]
}
```

Merge these fields into your target spec; choose descriptor, scale and placement
from inspected source data. Baking envelopes makes the selected skinned mesh
rigid; use it deliberately. Optional `path` control points provide authored
looping flight animation. Don't assume every stage group runs animations: FoD's
working animation receiver was group 1, with fog in group 3.

`mesh` accepts `{ "texture": "material.png", "vertices": [[x,y,z,u,v,r,g,b,a], ...] }`.
Supply triangle lists (3 vertices per triangle), stage **file units**, RGBA in
0..1 and UVs using your mesh convention. Optional `name`, `colors`, `cutout`.
The returned entry defaults to no mipmaps. Textures must be at most 1024 per
axis; non-power-of-two mipmapped inputs receive a hardware-compatibility note
(existing Dolphin-only designs remain buildable). The neutral binary
format is little-endian: `.mesh` = int32 count + 9 float32 per vertex; `.img` =
int32 width/height + BGRA8. Blender or any custom script may write it directly.

## Checks that help during design

- The collision digest compares **`coll_data` only**, ignoring relocation layout.
  It does not prove that moved joints, hazards, stage code, camera or spawns are
  unchanged. The builder refuses a partially exposed model-group table (the
  original Stadium files have split symbols); use a resolved base instead of
  silently losing groups.
- Budget presets are advisory references measured with four heavy vanilla
  fighters, not guarantees for every custom-fighter pack. Stadium's transforms
  consume additional memory. Inspect all language variants/forms you distribute.
- `cameras` uses measured legal-stage constants and the settled camera formula
  from Melee's `cm/camera.c`. Results are **world units**; the response includes
  the base stage's file-to-world scale. Yoshi's uses a 20-degree lens, the other
  presets 30. These are estimates, not screenshots or coverage certification.
  Override `camera` with the full constants object shaped like
  `camera_presets.json`, and `views` with `{name, box:[xmin,ymin,xmax,ymax]}` for
  new layouts. The `gamecam.Board` helper computes a background board's visible
  window and envelope; no flat background is required.
  Pass the returned `views` directly to `stage_shot.framing_sweep` to capture
  those views in one boot. Each view has its own success/error and file path;
  the batch succeeds only if all requested views were captured. These are
  posed cameras using estimated match framing, not actual camera motion.
- Real framing matters: look at center play, both ledges/recovery and extreme
  bounds. Put landmarks/screens where play sees them. Check contrast behind
  fighters, seams, culling, texture sharpness and moving scenery.
- `hsdraw --stage-render` is useful for previews; `stage_shot` is a debug-camera
  beauty shot, **not** a match-camera test. Live checks through the existing
  harness are optional developer tools. Hiding all models can also hide stage
  items (e.g. Office's Shy Guy stickers), so review those in an ordinary match.

## Packaging and delivery

For a skin, pass canonical game filenames (e.g. `{"GrNBa.dat":"..."}`) to
`package`. Stadium may need both `GrPs.usd` and `GrPs.dat` plus its forms. Don't
rename a file to a different stage's filename and assume its logic is compatible.
For custom slots, use MexCLI's stage export metadata and include the resulting
`stage.json` and referenced assets; package does not invent stage IDs or code.
Use `detect_content` to check routing, then `vault_import` and
`build_modded_iso` when delivery is requested. Neither ZIP validation nor a
successful export claims the visuals or gameplay were tested.

Use new filenames and isolated build projects. Do not borrow space from a
disc's bonus movie: the old experiments did, and later bases could carry broken
movies. Use Nucleus/MexCLI's exporter. Preserve the user's requested base and
its unrelated assets. No user-facing harness step is required.

## Proven examples on the original workstation

These are optional local references, never runtime dependencies:

- `colo_tmp/build/ps2/make.py` and `stage/v7/spec.json`: Phenac City's real
  3D models, moving water, and repositioned Stadium screen.
- `colo_tmp/build/ys2/make.py`: Mt. Battle exterior, source models/props.
- `colo_tmp/cs2/build/nuke/make.py`, `stage/v16/spec.json`: Nuke's baked
  background, custom plant body, screen and both language files.
- `colo_tmp/cs2/tools/scene.py`, `bake_bg.py`, `sheet.py`, `body.py`,
  `model.py`: source-specific scene preparation and geometry examples. Adapt
  their creative logic; do not inherit their hardcoded paths or fixed pack list.

The native implementation was promoted from `colo_tmp/cs2/colograft_cs`
(2026-11-14); camera math/presets from that project's `gamecam.py/json`.
Historical probe executables and per-stage artistic decisions were left out.

## Verification of this integration (2026-11-14)

The workbench rebuilt Phenac v7 and Nuke v16 from their retained specs through
real MCP stdio calls. Both DATs matched the accepted files byte-for-byte;
declared collision tables matched the bases, and an intentional coordinate
edit changed the collision digest. All six camera presets returned their ten
views. Both generated ZIPs were classified as Pokemon Stadium stages by the
existing Nucleus importer. Focused tests cover input preservation, failed-build
preflight, mesh encoding, archive safety and partial camera-capture reporting.
No new gameplay or live camera-sweep run was needed for this tool integration.
