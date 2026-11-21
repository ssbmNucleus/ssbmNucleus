# Original-game (Smash Ultimate) source assets

**This is the import path Shulk actually ships on.** 237 of its 244 moveset
clips come from Ultimate's own `motion/body/...` files against the real
`model/body/c00/model.nusktb` skeleton. This is not motion capture. Decoded
clips from here feed the retarget/bake toolchain under `fighter_port`.

Original motion is an input adapter and a reference for validating the authoring
tools. It is not a requirement that every authored move have an original clip.
Prompted key poses, contact constraints, hand/weapon paths and imported motion
should ultimately feed the same rig evaluation and game-installation path.

## Extract a selected set of assets

`extract_arc.ps1` reads a **decrypted** Ultimate `data.arc` with the native
`smash_arc.dll` distributed by [ArcExplorer](https://github.com/ScanMountGoat/ArcExplorer).
Its bindings follow [SmashArcNet](https://github.com/ScanMountGoat/SmashArcNet).
It does not handle console encryption keys or unpack NSP/NCA containers.

Supply a UTF-8 text file with one archive-relative path per line. Known paths
can be selected from the upstream [archive-hashes](https://github.com/ultimate-research/archive-hashes)
`Hashes_FullPath` list. For the first Shulk calibration, the selection was
`fighter/shulk/model/body/c00/` plus `fighter/shulk/motion/body/c00/`.

```powershell
./echo/ultimate/extract_arc.ps1 -ArcPath data.arc -FileList selected-paths.txt `
  -NativeLibrary tools/smash_arc.dll -OutputDirectory work/shulk-source
```

The extractor rejects paths outside the output directory and refuses to
overwrite existing outputs. It records missing paths explicitly, hashes each
extracted file, and hashes the archive, native library and path list. Output is
`extraction.json` plus the selected files. Archive hashing can take several
minutes. Keep all game assets, containers and keys out of source control.

## Decode a native skeleton and animation

The optional reader used in this experiment is `ssbh-data-py==0.9.1`, from
[ssbh_data_py](https://github.com/ScanMountGoat/ssbh_data_py). It can be installed
in a separate environment or an isolated `--target` directory on `PYTHONPATH`.

```text
python -m echo_ultimate.decode model.nusktb c01attacks3s.nuanmb --out work/source-ftilt --landmarks echo/tier2/shulk/ultimate_landmarks.json --allow-unbound S_Hip_hit
```

The output directory must be empty. Outputs are a source `.joints.json`, a
source `.anim` and `decode.json`. This is the **original skeleton**, not a
Marth retarget. The decoder handles row-vector skeleton matrices, XYZW
quaternions, constant/full-length tracks, translation and scale. It sorts the
hierarchy topologically, because helper bones can precede their parents in
the source file. Invalid matrices, cycles, partial tracks and unsupported
transform inheritance flags fail explicitly.

Animation nodes absent from the model skeleton fail unless individually named
by `--allow-unbound`; those exceptions appear in the report. Shulk's tested
forward tilt has one such track, `S_Hip_hit`.

### Explicit landmark maps

Rig JSON can contain a `landmarks` map from semantic names to actual joint
names. These override the geometric heuristic and are validated against the
joint list. Use this for known source rigs with named anatomy.

On Ultimate Shulk, the old heuristic called `LegC` the pelvis, identified
`SwordR` as a wrist, and misidentified the torso/head chain. The provided Shulk
map uses `Hip`, `Waist`, `Bust`, `HandR`, etc. The mapped right-arm chain is
`ClavicleR -> ShoulderR -> ArmR -> HandR`; weapon bones hang below `HaveR`.

### What is not yet evaluated

* Game-script motion rates, cancellation and state transitions. Shulk's forward
  tilt file contains 68 samples (0..67); that is not a claim of 68 gameplay frames
  or a reason to stretch it automatically onto the footage's 43 frames.
* Material and visibility tracks, including switches between back-mounted and
  hand-held weapon meshes.
* Helper-bone constraints and physics. Shulk's model has two elbow-orientation
  constraints, which are not applied by this decoder.
* Exact fractional-frame quaternion interpolation after Euler baking. Integer
  samples preserve the source SRT transforms within floating-point precision.

These limitations remain in the decode report so the source can be used as
skeletal calibration evidence without claiming complete engine reproduction.

## 2026-09-04 local experiment

The media PC contained Ultimate's base NSP and update NSP, and Smash for Wii U
as WUX. Ultimate was selected. Its existing tools and key files opened the base
and update; the combined RomFS yielded `data.arc`. No ROM library files were
modified. Work on that PC lives in `~/shulk-calibration-20260904/` (the `ULTIMATE_DUMP` default).

Local private artifacts are under
`app/tests/artifacts/mocap/20260904-ultimate/`. The selected model/motion
files total about 28.7 MB. The decoded forward tilt has 116 skeleton bones and
97 animated bones. Over 68 integer samples, comparison against direct source
quaternion/SRT FK gives maximum world-position error **0.00004117 source units**.
This measures decoding precision, not retargeting quality.

`original-ftilt-sheet.png` shows the mapped source skeleton and weapon-bone
origins. It is a source inspection sheet; it does not depict the rendered
Monado mesh or assert an artistic quality grade. `decode-validation.json`
records the numerical check. The full Shulk character and prompt-driven
animation authoring are still unfinished.

## Independent-source preflight gate (`randall/fighter_port/source_preflight.py`)

Any sampler that turns raw `.nuanmb` tracks into poses for authoring must be
checked against a second implementation that shares none of its code, **by the
build, before it authors**. The mobility slice shipped a wrong quaternion order
and every fidelity gate passed because the author and the verifier drew their
poses from the same sampler; the tests that would have caught it existed but the
build never ran them.

`source_preflight.RawSource` is that second implementation: it reads the
`.nusktb` bind and the raw transform tracks into arrays, slerps with SciPy
between the two bounding samples, interpolates translation/scale linearly,
applies `compensate_scale` in the MAYA_JOINT order (`T·diag(1/s_parent)·R·S`,
parent scale from the raw parent track, `1` when unanimated), computes the
retime `source_time = authored_frame · source_end / authored_end` itself, and
**refuses** any `override_*` flag instead of ignoring it. That placement is the
sourced third-party semantics from `pilots/incineroar_decoder/reference_v2`
(ssbh_wgpu, smash-ultimate-blender, Maya joint node) and is recorded in every
receipt as an explicit policy; it is not a claim about the Ultimate runtime.

`compare(candidate, reference, frames, joints, tolerance)` takes two
`frame -> {joint: 4x4}` callbacks and checks the exact joint domain, finiteness
and affine bottom row of every matrix on both sides, and the largest absolute
entry difference, at every integer authored frame plus explicit fractional offsets inside
a bounded, deterministic set of intervals (`frame_plan`: every interval when the
clip has no more than the cap, otherwise exactly the cap, evenly spread and
always including the first and last interval). Empty, duplicate or non-finite
frames, empty specs and duplicate spec keys are rejected rather than passed. The fractional frames
are the point: a baked-Euler interpolation matches slerp exactly at the keys and
is wrong between them. `run(specs, ...)` gates several clips and `evidence()`
hashes the reference module, the files each side is built from, the inputs, the
library versions, the policy and the tolerance into the receipt. Passing two
different callables does not prove independence; the receipt lists the files by
hash and says that independence is a claim about those files, not a
measurement.

Production use: `pilots/incineroar_mobility/preflight.py` builds the specs for
that package (its `MobilityNative` as candidate, its declared retime, its rig's
joint list, tolerance `1e-4`) and `build.py` calls `preflight_or_fail` before
authoring. There is no switch to skip it and no stored pass is reused; a failure — or a
gate that could not run at all (reference load error, bad spec), recorded as a
`gate_error` receipt — writes `preflight.json` and `PREFLIGHT-FAILED` into the
requested output directory and nothing is authored. On a pass the receipt is
written the moment the output directory is created, before authoring, so it is
retained even if authoring fails later. Tests: `tests/test_mocap_source_preflight.py`
(planted wrong XYZW, baked-Euler fractional mismatch, non-finite and missing
joints, refused override flags, the six real clips). It is a per-build check on
the clips about to be authored, not a corpus sweep.

## Reusable transfer and authored edits

The skeletal transfer entry point accepts any explicit landmark-mapped source,
including a clip authored from rest. It is separate from the Ultimate decoder:

```text
python -m fighter_port.retarget source.anim source.joints.json Marth.joints.json --out work/ftilt.anim --source-times times.json --attachments attachments.json
```

`times.json` is a JSON array of source animation times; each becomes one output
frame, starting at zero. Omit it to sample the entire source at integer frames
plus endpoints. The transfer does not infer gameplay time from clip length.
`attachments.json` for the held weapon in this experiment is:

```json
[{"source":"SwordR","source_anchor":"HandR","target":"JOBJ_75","target_anchor":"JOBJ_73"}]
```

The default basis comes from rest body axes; displacement scale comes from rest
leg lengths. Optional `--basis` (3x3 rotation JSON) and `--scale` make overrides
explicit. Body rotations preserve target bone lengths; hand and weapon joint
rotations plus animated attachment offsets transfer separately. Target rest
grips are preserved. This does not transfer the Monado's articulated blade or
visibility changes. A frozen run manifest is emitted for installation/review.

Native forward tilt has now been installed into a separate test ISO and captured
in Melee on the Marth donor. Its extracted ISO bank matches the installed bank.
Eight sampled frames stayed in AttackS3S and frame 43 returned to Wait. The
maximum native blade-tip position difference after import was 0.003175 rig
units. This is an import precision measurement, not an artistic quality grade.

[Editable recipes](AUTHORING.md) now support additive poses, explicit timing,
and two-bone contact constraints using this same animation/install/review path.
A Shulk trial lengthens anticipation, speeds recovery, and anchors both ankles
during part of the strike. Full character visuals and special mechanics are
still unfinished. `benchmarks/native-authoring-20260904.json` records the
native and corrected authored candidate measurements and private artifact hashes.
The corrected authored candidate's maximum blade-tip import error is 0.002474
rig units; planted ankle errors after import are 0.000809 and 0.000768 units.
The full-frame capture confirms action frames 1..41, then Wait on frames 42..43.
The motion review GIF retains all 43 captures, labelled at 3x slow speed with
a final idle pause. The current targeted regression suite has 72 passing tests.

All **410 selected files** were extracted with zero missing paths, and every
local file's size and SHA-256 matches the remote extraction manifest. Native
neutral air, up smash and run references also decode successfully. Their raw
sample counts are 80, 85 and 37 respectively; forward tilt has 68. All 64
targeted mocap, animation and source-adapter tests pass. The asset-free
`benchmarks/ultimate-source-20260904.json` preserves this verification summary.
# Current bank metadata before authoring

Use `fighter_port.motion_contract.require_motion_contract` to check a common
motion's action index, state name and expected archive end against the actual
input Pl/AJ. It records payload, input and implementation hashes. This catches
copied metadata such as DamageN1 state 75 (actually DamageHi1), or an 11-frame
DamageAir1 donor claim when the current archive says 12. It does not prove
state lifetime: hitstun countdowns, interrupts, rate changes and animation
exhaustion must be reviewed separately. Source duration and archive duration
are separate declarations even when a prior recipe happened to make them equal.

## Gameplay data from the game's own files (`gamedata/`, 2026-11-10)

Attributes, move timing and hitboxes can be read from the game instead of a
wiki. Pure Python; the only native piece is ArcExplorer's `smash_arc.dll`, used
to pull files out of `data.arc`.

```text
python -m echo_ultimate.gamedata shulk --root <dump folder> [--out moves.json] [--move game_attack11]
```

`<dump folder>` holds `romfs/data.arc`, `ArcExplorer/smash_arc.dll` and, for
names, `Hashes_FullPath` (or set `ULTIMATE_DUMP`). Needed files are extracted on
first use into `<dump folder>/gamedata/`. `--out` writes game-derived data: keep
it out of this repository.

| file in the archive | what it gives | reader |
|---|---|---|
| `fighter/common/param/fighter_param.prc` | one row of 369 attributes per fighter | `prc.py` |
| `fighter/<name>/motion/body/c00/motion_list.bin` | per motion: script names, animation file, intangibility, cancel frame | `motion_list.py` |
| `prebuilt:/nro/release/lua2cpp_<name>.nro` | the compiled move scripts: hitboxes, grabs, throws, timing | `nro.py`, `acmd.py` |

How the scripts are read. The module registers each script with
`sv_set_function_hash(function, hash40("game_attack11"))`. The registered
function is a small wrapper; the script is the local function it calls. Inside
it, each `ATTACK` goes through a local wrapper that pushes its arguments and
tail-jumps to `app::sv_animcmd::ATTACK`, so the arguments are the `L2CValue`s
constructed just before that call, in order (33 of them when the hitbox has no
second point). `acmd.py` walks the code linearly and tracks the constants it
loads; it runs nothing and follows no branches.

Timing. Script frames are animation frames. The animation position starts at
1 on game frame 1 and moves `1/rate` per game frame, `rate` being the last
`FT_MOTION_RATE`; `frame(n)` fires when the position reaches n (`moves.py`).

Checked on Shulk: all 36 saved wiki rows for his 15 normal attacks match in
frame window, damage, angle and knockback, and 90 of 90 named attributes match.
Mario and Marth were run once and gave plausible tables; no row-by-row check.

Limits:

* Names are hashes. Script names are guessed from animation file names (67 of
  Shulk's 162 game scripts); most attribute fields and all of `vl.prc` are
  unnamed. The community label lists would name them; they are not vendored.
* Values the game looks up at run time by constant name (sound levels, some
  flags) show as `<const 0x...>` or `None`. A value a script computes or
  chooses in a branch is not followed.
* The archive path uses a colon (`prebuilt:/...`); `extract_arc.ps1` refuses
  colons, so use `gamedata/arc.py` for the script modules.
* Cancel frames after rate conversion were off by one on 2 of 18 Shulk moves
  (up tilt, back throw); cause not found.
* On Marth the expression scripts were not attributed to their agent (counted
  under `?`); game scripts were unaffected.
* Status scripts (the move logic itself) and effect/sound scripts are
  registered and listed but not interpreted.

Tests: `tests/test_ultimate_gamedata.py`; its last test needs `ULTIMATE_DUMP`.
