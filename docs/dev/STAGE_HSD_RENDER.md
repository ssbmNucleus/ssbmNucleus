# Headless HSD Stage Rendering (`--stage-render`)

**Status (2026-09-10):** used for ISO-imported stage variants and for the
vault's bulk stage-screenshot flow. Stage DATs render on the same offscreen host
as CSPs, without building an ISO or launching Dolphin.
A measured eight-image Windows batch took 7.4 seconds for the first preview
(including startup), then 1.2–2.0 seconds per image on a warm worker.

## Usage

```
HSDRawViewer.exe --stage-render <Gr.dat> <out.png>
    [--eye x,y,z] [--interest x,y,z] [--fov deg]
    [--groups 0,1,3,6] [--anim N] [--frame F] [--size WxH]
```

- Implemented in `<ssbmNucleus-hsdlib>/HSDRawViewer/Program.cs` (`RenderStageCore`) and the cross-platform headless program. Both use `StageScene`.
- Shipped through the normal HSDRawViewer publish step. `--csp-server` accepts
  both `--csp` and `--stage-render` jobs and clears scene resources between jobs.
- Works directly on the dat inside a DAS variant zip — no ISO build, no Dolphin,
  no "close Slippi first" issue. Deterministic output (verified: two runs differ
  only by ±1 LSB rasterization noise).

## How it works

- Finds the `map_head` root (`SBM_Map_Head`), builds one `RenderJObj` per
  `SBM_Map_GOBJ` model group on the CSP pipeline's offscreen `CspRenderHost`.
- Applies joint + material animation `--anim N` (default 0) at `--frame F`.
- Lights: per-group `gobj.Lights` (falling back to `map_head.Lights`) via
  `RenderLObj.LoadLight` + `LightRenderMode.Custom`. **Light anims are stripped**
  (bare `HSD_Light{LightObject=lobj}` wrapper) — see gotchas.
- Applies `grGroundParam.StageScale` as `RenderJObj.ModelScale`.

## Camera calibration (matches in-game `STAGE_FRAMING`)

`backend/shared/ingame/capture.py` `STAGE_FRAMING` coords carry over with one empirical
correction (calibrated on Battlefield, holds on all 6 stages):

> **fov 40 → 46.5, eye/interest y − 4** (x/z unchanged)

Verified on a 13-variant comparison sheet against vault in-game screenshots
(framing, textures and lighting near-identical).

## Hard-won gotchas (do not re-derive)

1. **`grGroundParam.StageScale`** — the game scales ALL map models by it
   (Battlefield = 0.8). Skipping it makes renders look zoomed-in.
2. **Viewer `Camera.Translation` Y is negated** — `UpdateTranslationMatrix` builds
   `CreateTranslation(x, -y, z)`. Pose as: solve `R = RotY(ry)·RotX(rx)` so the
   look direction maps to (0,0,−1) (row-vector), `t = −(eye·R)`, then assign
   `Translation = (t.x, −t.y, t.z)`.
3. **Viewport chrome** — the docked glControl is smaller than the form client
   area (playback bar ≈ 29 px). `RunStageRender` measures `cam.RenderWidth/Height`
   and re-sizes by the delta until the requested dimensions are reached.
4. **Light-anim nondeterminism** — `RenderLObj.Bind` advances its anim frame on
   every render pass, and the paint-event count varies per run, so animated map
   lights land on random frames (Battlefield's bg dome flipped white/black
   between runs). Fixed by loading bare LOBJs without `AnimPointer`.
5. **Use `--frame 60` (or later) for steady state.** Frame 0 is the stage's
   *intro* state — Battlefield's wireframe bg dome is bright white at frame 0 and
   fades to its familiar near-invisible state by ~frame 60. In-game captures are
   taken seconds into the match, i.e. steady state.

## Mode-specific model groups (why `--groups` exists)

Stage DATs contain model groups for ALL game modes; the stage's C code picks at
init. Rendering everything shows the wrong background. Ground truth is each
stage's `OnInit` in the decomp (`projects/melee/src/melee/gr/`):

| Stage | decomp | VS-mode groups | Notes |
|---|---|---|---|
| Battlefield (GrNBa) | `grbattle.c` | `0,1,3,6` | special modes (`gm_8016B3D8()`/0x111/0xF5): `0,5,6` — group 5 is the rainbow swirl, 2/4 other modes; group 6 = stage |
| Final Destination (GrNLa) | `grlast.c` | `0,1,2,3` (all) | no filtering needed |
| Pokémon Stadium (GrPs) | `grpstadium.c` | `0,1,2,5` | group 5 is the normal floor/platforms; transformations are separate |
| Dream Land (GrOp) / Yoshi's Story (GrSt) / Fountain (GrIz) | not yet read | rendered fine with all groups | check `OnInit` when resuming |

## Known gaps (cosmetic)

- No EFB effects: Stadium jumbotron shows its static texture (not the live
  "Current Stage" screen); FoD floor reflection missing.
- No map fog (`SBM_Map_GOBJ.Fog` unused) — a few background tints differ.
- No particles (Shy Guys, sparkles, snow).

## ISO import integration

`backend/vault/importing/stage_previews.py` applies the six stage framing
profiles at frame 60 and writes uniform 768×432 PNGs. A single persistent worker
renders the batch; per-job deadlines prevent a broken DAT from holding it forever.
`POST /api/mex/das/scan-iso` renders after committing the stage ZIPs, outside the
vault metadata transaction, then returns `screenshotUrl` for result cards and saves
screenshot metadata. PNGs are validated and installed atomically. Preview errors
are logged and keep the imported stage. Rescans backfill missing previews for
older ISO imports, preserve existing images, and return those entries as `skipped`.
Custom stages continue to use their imported stage icons.

### Stadium's split model table

Interior exported symbols split `map_head`'s logical model-group array into
multiple parser structs. Reading `ModelGroups.Array` stops after group 2 in
retail Stadium, even though its declared count is ten. `ReadModelGroups(file)`
reconstructs all descriptors using original offsets, retaining references to the
original models, materials and animations. This fixes the missing group 5 floor
and platforms in both captures and the shared live StageScene.

The normal Stadium group filter also prevents transformation geometry from being
stacked when it is present in a modded archive. Explicit `--groups` overrides it.

### Verification

- `tests/backend/test_iso_stage_previews.py`: imports, image URLs, failed-preview
  isolation, old-import backfill, existing-image preservation, and lock scope.
- `tools/ingame/stage-groups-smoke`: synthetic DAT with symbols splitting the table at
  group 3 and inside group 5. Checks all ten groups, pointers, scalar values and
  malformed counts. Windows `build.bat` runs this against the published HSDRaw.dll
  before packaging; no game assets are required for that gate.
- Local real-data verification: six vanilla stages plus a Stadium skin, followed
  by an invalid DAT and another Stadium render. The repeated Stadium images were
  pixel-identical. Both Windows and cross-platform helper builds compile.

In-game capture remains available separately for testing game-scripted effects
and boot behavior that an offline renderer cannot reproduce.
