# Ultimate port pipeline — source-native skeletons

How to put a Smash Ultimate character onto its OWN skeleton in Melee, instead of
deforming it onto a donor fighter's bones.

**Named for its scope.** Stages 0-6 are character-agnostic but Ultimate-specific
(see Scope below). If a second source game is ever ported, either generalise
this page or fork it — do not silently widen its claims.

Established 2026-09-12 from the decomp, the shipped Incineroar build, and an
adversarial second opinion. Companion pages:
[PORT_CHECKLIST.md](PORT_CHECKLIST.md) (the operator sequence) and
[NATIVE_SKELETON_CONSUMERS.md](NATIVE_SKELETON_CONSUMERS.md) (the engine-consumer
map).

## Trainer regression rules, 2026-09-14

The Trainer campaign added reusable checks exposed through Randall's
`native_port` operations. These checks complement native testing:

- **Movement:** `movement_audit/repair` tracks both the source translation joint
  and the outer engine root. A special needs an explicit physics owner; clearing
  only one translation can leave the mesh moving away from its collision actor.
  Waterfall demonstrated this failure on both facings. Do not blanket-clear an
  unknown special's travel.
- **Combat:** use `source_combat_audit/install` to bind source bone names and
  event clocks to the converted animation. Swapping donor animation does not
  replace donor hitboxes. Encoded editor `x_offset` is bone-local Z and
  `z_offset` is bone-local X; `hitbox_rebase` requires a measured transform when
  changing attachments. Validate both facings and real victim contacts, not only
  script readback or a plausible debug overlay.
- **Compression:** `compress` protects combat joints and their ancestors,
  measures pose/skin error, and checks archive spans. Stock clip capacity and
  total preload memory are separate limits; a small costume does not make an
  oversized animation bank safe.
- **Special effects:** `special_physics_hooks.compose` uses live fighter state
  IDs, preserves the original callback, and rejects duplicate composition.
  Common-state wrappers do not cover private special callbacks. Attach moving
  particle generators with an updated rendered AppSRT matrix; changing a cached
  translation alone is insufficient. Test hitlag, interruption, death, respawn
  and transformations with owner identity and generation checks.
- **Menus and exports:** verify portraits inside the actual player-card crop,
  not just their source PNGs. Confirm the actual hovered CSS index before
  capture: reaching a cursor coordinate within tolerance can still select the
  neighboring cell, so a screenshot alone cannot establish an exporter defect.
  Admit every FST file's 32-byte rounded DVD read
  through `core.iso_reads.ensure_padding` before recording the final ISO hash;
  whole-image 32-byte alignment alone can still leave the last file's read past
  EOF. This guard is shared by Trainer builds and Randall's MexCLI export.

Character-specific move timing, effects and recovery behavior still require
authored contracts. The Trainer roster-aware bank hook binds the final project
IDs and archives, keeps normal heaps, and has native evidence for the tested
heavy lineups; it is not a guarantee for arbitrary imported rosters or slots.

## Scope — what this generalises to

**This is a general pipeline, not a Charizard recipe.** Stages 0-6 are
character-agnostic; every character named below is an example or a measurement,
never an assumption baked into a step. Three real limits, though:

1. **Source must be Smash Ultimate.** The conversion assumes `nusktb`/`nuanmb`
   via `ultimate.decode`, Ultimate's bone-naming lineage (`Hip`, `KneeL`,
   `FootL`, `Throw`), and its digit numbering (digit 5 = thumb, measured on
   Charizard and K. Rool). A Models-Resource rip or a different game needs its
   own decoder and its own naming survey before stage 1 — the SLOT bindings in
   stage 3 are where that assumption is concentrated.
2. **Per-donor work is irreducible.** Hard-coded bone literals differ by donor:
   Bowser's flame `parts[48]`, Popo's Blizzard, Peach's raw 109. No table fixes
   these, and the set is different for every fighter slot you land in. That is
   precisely why stage 0 inventories consumers *for this donor* before anything
   is frozen.
3. **Validated end-to-end on exactly ONE delivered character** — Incineroar,
   into a Bowser slot, over a long campaign. Everything else here is measured
   from the decomp and from retail data, which is strong evidence but not the
   same as a second character having shipped through it.

Coverage check for the alias/name assumptions: the root chain
(`Trans -> Rot -> Hip`) mapped identically across five Ultimate skeletons
spanning 44-104 joints (Squirtle 44, Ivysaur 54, Charizard 73, Greninja 91,
K. Rool 104).

**But "resolved with no hand edits" was too strong, and authoring the bindings
for real disproved it.** Slot resolution needs per-fighter judgement:

* **Digit numbering is not a shared convention.** Squirtle's thumb is digit 1,
  Charizard's is digit 5 — measured, same source game (see stage 1).
* **Anatomy genuinely differs.** Of 54 slots: Charizard binds 39 and nulls 15
  (three-fingered hands: no ring, no pinky), Squirtle binds 33, Ivysaur binds
  **28** and nulls 26 — one digit per hand and a single `Have` bone rather
  than a left/right pair.

Every null is `FTPART_INVALID` in `part_to_joint`, which is **conditional**,
not free: `ftParts_GetBoneIndex` returns it raw and unguarded. A null needs its
consumers shown unreachable or guarded before stage 4 installs the table.

## Why bother

**This retargeter** only animates joints it can find by anatomical landmark --
a limitation of the implementation, not of fitted-donor architecture in general.
Measured on Charizard-on-Bowser: **21 of 76 joints carry rotation keys**,
including none of the wing set. (No rotation keys does not strictly mean "frozen
forever": translation, scale, inherited parent motion and procedural updates can
still move a joint. What it does mean is
that this clip supplies no keyed rotation to those joints.) Two independent blind judges failed that build, one on a stiffness
veto ("wings identical across 40 frames where the source flaps"). No IK or
weighting fix reaches it — the bones aren't there. See
[[retarget-drives-only-landmark-joints]].

Source-native removes the retarget entirely: the clip is already authored on
these exact bones.

## The precedent — read this before designing anything

**The delivered Incineroar (v58) is source-native and shipped.** Verified:

```
incineroar-source-rig-integration-v1/engine-control-203-v1/compiled-lookup.json
  joint_order  203        forward  54 slots
  hip   -> 6   = Hip      throw -> 201 = Throw
  headN -> 92  = Head     extra -> 202 = __engine_ExtraMotion
```

**203 joints = 143 source + 18 scale + 38 orientation + 4 engine helpers.**
37 of the first 76 parent indices differ from vanilla Bowser, so the donor index
space is *not* preserved.

### The hard rule: EVERY owned row needs a native-domain clip

`ftAnim` binds a figatree's node array **positionally** to `fp->parts[i]`
(`ftanim.c:607-636`: `while (*cur_node != -1) { ... i++; }`). There is no name
binding. So a donor figatree left in place on a native rig drives *the first N
parts of a different skeleton*.

On the donor route an unported action harmlessly keeps the donor's animation.
**Here it is garbage, not a fallback.** Reasoning inherited from a donor-route
port ("specials are the donor's own move logic", "Escape drives the transform")
is about whether to *convert* a row -- it does not license leaving one behind.

Give every owned row one of four dispositions (`native_port.build_catalog`):

| | |
| --- | --- |
| `CONVERT` | a genuine source counterpart exists |
| `RETIME` | same, but the engine depends on the donor's exact duration |
| `SYNTHESIZE` | no counterpart -- emit a native-domain clip holding a chosen pose for the donor's frame count |
| `RESERVED` | owned by another system; still synthesized, but flagged |

The denominator is the donor's own bank, not your map. Measured: Bowser owns
**199** `PlyKoopa5K_Share` action motions (plus 11 `PlyTaro` Giga rows); Popo
owns **195**. A catalog inherited from the donor route covered 136 of Bowser's
199 and read as complete because it never stated the denominator.

### Retime to the donor's duration

Melee's script frame numbers, IASA windows, hitbox windows and loop points are
all written against the **donor's** figatree length. Shipping the source length
silently rewrites the move. Measured on Charizard: `Run` is 81 source frames
against Bowser's 20-frame cycle, `Entry` 121 against 10, `Guard` 361 against
370. Resample the motion into the donor frame count -- target time `t` samples
source time `t * source_end / native_end`, which handles compression and
expansion alike (`RetimedClock` only expands).

The cost is that motion plays at a different speed than Ultimate, and
compression makes sub-frame error worse. That is the right trade: Melee's
timings are the contract, Ultimate's are not.

**Locomotion rows hold ONE gait cycle — detect it on the LEG CHAIN.** Melee
loops walk/run/dash against ground speed, so the row is one cycle. Ultimate's
clip may hold several: Charizard's `a02run` is 81 frames and recurs *exactly*
at frame 40. Resampling all 81 into Melee's 20 both merges the cycles and
doubles the angular rate.

Measuring whole-body similarity finds nothing — his wings and tail do not share
the gait period. Restrict the similarity test to `Leg*`/`Knee*`/`Foot*`/`Toe*`
(`native_port.detect_cycle`). Measured effect on Charizard's `Run`:

```
ratio 4.00 (whole clip)   sub-frame pivot 13.1434   FAIL
ratio 1.80 (one cycle)    sub-frame pivot  0.0663   PASS
```

That one change removed the largest error in the bank and took every walk/run
row from FAIL to PASS.

**Cap the retime ratio; past the cap, TRIM rather than compress.** Resampling a
74-frame Ultimate wind-up into Melee's 17-frame `SpecialHiStart` plays the whole
motion at 4.3x speed — which looks wrong *and* is the dominant remaining source
of sub-frame error, because compression multiplies the angular rate. Past a cap
(1.5 works), take the **tail** of the source window instead: the terminal pose
is what the next Melee state inherits, and the motion keeps its real speed.

```
Ivysaur SpecialHiStart    ratio 4.29 resampled   sub-frame pivot 13.9474  FAIL
                          ratio 1.50 tail-trim   sub-frame pivot  0.0483  PASS
        SpecialAirHiStart  9.0085 -> 0.0851      CliffCatch  5.3055 -> 0.0893
```

This is a CONTENT choice — you are showing part of the motion rather than all of
it — so it belongs in the catalog next to the tier, not buried in the encoder.

**Normalise error against rig stature.** An absolute threshold is not
comparable across characters: Charizard is 20.58 units tall, Ivysaur 9.44,
Squirtle 8.25. The same 0.05 is 0.24% of Charizard and 0.61% of Squirtle.
Report both, and set the threshold as a fraction of height.

### The central trick: helper joints, not approximate targets

Melee needs slots Ultimate has no bone for (`top`, `xRot`, `yRot`, `extra`).
Do **not** aim them at the nearest plausible bone — *insert real helper joints*:

| prefix | count (Incineroar) | purpose |
| --- | ---: | --- |
| `__engine_*` | 4 | `Top`, `XRot`, `YRot`, `ExtraMotion` — the engine-only slots |
| `__scale_before_*` | 18 | scale compensation |
| `__chart_before_*` | 38 | Euler orientation correction |

Source bones keep their own names (`Hip`, `Waist`, `Bust`, `ClavicleC`, ...).
`rig_wrappers.insert_identity_parents` adds the engine controls -- but note
`prepare_engine_rig.py` inserts only **three** engine parents;
`__engine_ExtraMotion` is appended as a SEPARATE step. Follow the example
literally and you stop at 202 nodes.

### Limits are patched, not vanilla

The delivered DOL supports **203 joints** and **131,072-byte animation
allocations** (usable budget 131,040). So `MAX_FT_PARTS` 140 (`ftparts.h:51`) and
the 32,768-byte figatree pool are **not hard walls** — see
`engine_capacity.extend_rig_capacity` (covers the animation-binding guard, unlike
the older allocation-only experiment) and `animation_capacity.py`.

> Do not quote "Charizard is at 99% of the pool" as a blocker: that is **one
> clip's** buffer occupancy (`WaitItem`, 32,446 bytes), not the whole AJ bank.

## Pipeline

Reuse `pilots/incineroar_campaign/`; those scripts work but carry
Incineroar-specific IDs, names and counts, so parameterize rather than copy.

### 0. Establish requirements BEFORE freezing anything

> **Three ways a census silently under-reports, all found the hard way:**
> 1. **Follow `Subroutine` (0x05) and `Go To` (0x07).** `echo.subactions`
>    records those pointers and does not traverse them. Walking only the action
>    entry blocks missed 32 reachable blocks and 149 references on Bowser --
>    including the ONE command in his whole bank with
>    `use_common_bone_ids = 1` (`0x35A0`, a `Create Hitbox` on part 4 = `hip`,
>    shared by `DamageFly*`). A single missed block inverted the conclusion
>    "this donor never addresses semantically". Walk the DEMO table too.
> 2. **`SBM_ModelPart.Count` is an entry-list length, not a span.** The list at
>    `+0x04` is read straight into `fp->parts` (`ftanim.c:1351`). Bowser's part
>    2 has `StartingBone=48` and lists `[53,54,55]` -- recording the start alone
>    both missed 22 references and named a joint the part never touches.
> 3. **`FighterActionDynamicBehaviors.boneTableIndex` is NOT a Fighter_Part.**
>    `ftCo_8009E4A8` (`ftdynamics.c:533`) uses it as `ft_data->x2C->x10[<byte>]`,
>    the per-action dynamics FigaTree table. Sending it to a parts-table
>    remapper corrupts dynamics selection.
>
> Also: **IK is ten bone bytes AND limb-length floats.** `ft_0899.c:95-98` reads
> `len0 = x58->x4 * scale.y`, `len1 = (x58->xC + x58->x18) * scale.y`. Those are
> the DONOR's segment lengths; re-pointing the indices without re-measuring
> them hands the solver geometry that does not match the bones it drives.

Inventory the engine consumers this fighter actually uses
(NATIVE_SKELETON_CONSUMERS.md) and check capacity feasibility for the intended
clip catalog. Both constrain the rig you are about to freeze, so doing them
after is a rework. DOL patching itself need not precede offline costume
construction, but **must** precede loading an oversized rig.
Decide **movement ownership** here too -- but run
`movement_ownership.adapt_common_bank` in stage 6, *after* encoding, because it
edits packed animation bytes.

### 1. Freeze the rig, convention and clip catalog

> **Sample chart clearance BETWEEN frames.** `rotation_charts.choose` at
> integer frames only accepted six Charizard charts that fall under their own
> threshold sub-frame, and missed one it should have taken (104 nodes became
> 105 on a 1/4 grid). "Every clip sampled" is not "sampled densely enough".
>
> **Sanitize source scale first** (`native_port.sanitize_scale`). Ivysaur's
> `c01attacks3s` squashes `LeafL1/R1` on Y through zero to -0.019 -- ease
> overshoot on a flattening leaf. A negative scale makes the local rotation a
> REFLECTION, and `choose` refuses those outright, so one clip blocked the
> whole freeze. HSD cannot draw |scale| < 1e-3 anyway, so clamping is free
> there. Distinguish overshoot from an authored mirror by SHAPE (dips through
> zero on an otherwise-positive track), **not** by magnitude against the floor
> -- -0.019 is well above 1e-3 and is still overshoot.
>
> **Non-uniform parent scale produces real shear.** Squirtle compensates scale
> on `Tail1`/`Tail2`; `T*C*R*S` with a non-uniform `C` and a rotated child
> cannot be represented by two SRT nodes, and `scale_helpers` surfaces that
> rather than hiding it (deviation up to 0.26 across 24 clip/joint pairs).
> Exclude those joints from chart selection, author them with
> `project_shear=True`, and let the gate measure what the projection costs.
>
> **Digit numbering is per-fighter. Measure it.** "Digit 5 is the thumb" holds
> for Charizard (33.9 deg min separation vs 29.9) and K. Rool -- and is FALSE
> for Squirtle, whose digits are 1/2/3 with **digit 1** the thumb (49.2 vs
> 39.5). Same source game. `digits.py` measures each digit's root direction in
> the parent hand's frame and picks the largest minimum separation.
`ultimate.skeleton_metadata`; inspect raw clips with
`source_preflight.RawSource.from_files`. Choose `scale_helpers` and
`rotation_charts`, add engine controls with `rig_wrappers.insert_identity_parents`,
then freeze `canonical_jobj_order`. **Every later numeric reference uses this
serialized order.** Pattern: `prepare_engine_rig.py:39`.

### 1b. GATE the freeze against stage 0 before skinning anything

Stage 0 says the census and capacity "constrain the rig you are about to
freeze". That only happens if something checks. Run `gate.py`:

* **Engine writes.** Common code does not only read bones, it ROTATES
  `FtPart_TopN`, `FtPart_TransN`, `FtPart_XRotN` (`ftCo_0C35.c:67,79`,
  `ftCo_Lift.c:147,160`, `ftCo_HammerTurn.c:45`, `ftCo_Damage.c:262,1190`).
  None may sit under a `__chart_before_*` helper, or the engine rotates inside
  a re-oriented frame. This is the same argument used to leave `Rot` uncharted,
  so it must be enforced rather than assumed.
* **All 54 slots resolve on the FROZEN order** -- not on the bare source rig.
* **Arrangement matches the shipped precedent.** The delivered Incineroar v58
  rig is on disk; compare rather than infer. (Root chain, `__engine_ExtraMotion`
  as a childless identity leaf under `__engine_Top` at the END of the order,
  `Rot` uncharted, `__chart_before_Hip` present -- all five match on all three
  Pokemon.)
* **Node count** against `MAX_FT_PARTS` 140 and the patched 203. Measured:
  Charizard 105, Ivysaur 74, Squirtle 63 -- **all three fit vanilla 140**, so
  only the ANIMATION-pool patch is required, not the parts-capacity one.

### 2. Build the costume with SOURCE skinning
`rig_archive.build_skeleton` + `source_mesh_handoff.prepare`, then the existing
model import.
* **Do not carry donor-fitted mesh weights onto the native rig.**
* Preserve DAT rest scales and inverse binds — **SMD does not carry scale**.
* **Fix the render flags, or nothing draws.** `build_skeleton` writes `0x09`
  (SKELETON|CLASSICAL_SCALING) and `--model import` does NOT upgrade them, so a
  costume that demonstrably contains four DObjs reports *"DOBJs loaded: 0"*.
  Copy the donor root's flag pattern.
* Because the importer puts **every DObj on ONE joint**, that joint must
  advertise `XLU|ROOT_XLU` (`1<<19` / `1<<29`) as well as OPA — otherwise every
  translucent material is silently skipped. Squirtle rendered as a floating
  plastron and two eyes with a bijective mesh readback and 3e-8 weight error.
  **No numeric check catches this. Render before believing it.**
* `HSDRawViewer --csp` renders **blank whenever any animation is supplied**
  (verified with vanilla Bowser's own costume and his own `Wait1`) and ignores
  camera position. Use Blender for posed verification.

### 3. Author the engine bone contract
All **54** bindings to `bone_lookup.compile_lookup`, including explicit alias
winners. Use the helper joints for engine slots with no anatomical equivalent.
Then feed the inventoried direct references to `bone_lookup.remap_references`.
> **Neither function discovers missing consumers.** Expand the inventory first —
> NATIVE_SKELETON_CONSUMERS.md lists ~15 classes, several uncensused.

Use `bone_lookup.SLOTS` (54 storage slots). **Never** the decomp
`enum Fighter_Part`; they diverge at slots 16 and 31.

### 4. Rebase and write the data consumers

**Bridge donor joints to native ones in two tiers, and record which applied.**

1. **Parts table** — donor joint → semantic slot → your bound joint. This is
   the engine's own `ftPartsRemap` (`ftparts.c:704`) done offline. Covers 34 of
   Bowser's 46 read joints, 23–24 of Popo's 37.
2. **The DONOR's own parent chain** — for the rest, walk up the donor tree to
   the nearest bridged ancestor and read the offset. That identifies the bone
   using the donor alone: Bowser joint 55 is the snout (`-1.32` below, `+4.17`
   forward of Head, carrying bite hitboxes and breath GFX), 29 the shell, 51
   the crown, 10/19 toe claws; Popo joint 15 is the hammer attach, coincident
   with the `lHave` bone, and carries 31 of 32 otherwise-blocked references.

> **Cross-species nearest-neighbour matching is INVALID.** Validate any matcher
> on the pairs the parts table already answers. Matching by joint pivot in
> stature-normalised space missed by a median 0.29 / 0.44 / 0.21 of body height
> and put `headN → Head` 0.45 h apart; skin-centroid matching was no better.
> Two creatures with different morphology do not have bones in the same
> normalised place, so the residual is not a similarity score.
> Also: `HSDRawViewer --model export` SMD node counts are NOT JObj joint counts
> (Bowser exports 191 nodes for a 76-joint rig) — do not join on them.

Classify consumers by whether re-pointing is even the right operation:

* **Pure indices — re-point.** ECB (six s16), `special` (five i32), the ten IK
  bone bytes, `modelLookup.*`, and the 479/437 script bone fields (bit-packed;
  write at `(HEADER_SIZE + cmd.offset)*8 + param.bit_offset`).
* **Geometry — re-derive, never re-point.** A hurtbox is a capsule; swapping
  the bone while keeping the donor's offsets and radii puts a correctly-named
  capsule in the wrong place. `collision_coordinates.rebase_capsule` preserves
  world position and takes a `model_transform` for the stature change — but
  **that alone is not enough**: measured skin coverage was 20.9 / 24.3 / 34.6 %
  against a vanilla control of 85.0 / 70.4 / 70.4. Fit each capsule to its own
  bone's flesh instead (58.5 / 30.0 / 62.4 %).
* **Lengths — re-measure.** The IK floats at `ftData+0x58` were identified by
  measuring both donors against their own skeletons: `0x04` thigh, `0x0C` shin,
  `0x20` upper arm, `0x28` forearm, each matching to ~0.5%. `0x18` matches no
  bone pair (it is an ankle drop; scale by stature). `0x2C`=50.0 and `0x30`=30.0
  are **identical on Bowser and Popo**, so they are angle limits, not lengths.
* **Regions — rebuild.** The `ftData+0x1C` modelPart lists are, on both donors,
  the left-hand chain, the right-hand chain, and the jaw/head sub-chain. Rebuild
  the equivalent native region rather than mapping entries.

**`MAX_HURTBOXES` is 15 and exceeding it corrupts memory.** `ftcoll.c:3227`
asserts on `count > 0xF` and then writes `fp->hurt_capsules[i]` anyway into a
`FighterHurtCapsule[15]` (`types.h:1333`). Bowser already uses all 15 — so a
Bowser-donor port can never cover body regions Bowser lacks without a DOL patch.

**Measure hurtbox quality as skin coverage, with the donor as the control.**
"What fraction of the character's own skin lies inside its hurt volume", and the
same measurement on the donor against its own mesh. A number with no control
beside it says nothing.

**Arrays are allocated to exactly their current size.** Both donors' hurtbox
banks and every modelPart list have zero slack, so growing one moves it — and
moving it orphans a block boundary (see stage 3). Write in place, truncate
nearest-first where the native region is larger, and **pad surplus slots** where
it is smaller: a repeated bone is inert, a stale donor index is not.

**Verify by re-reading the census from the OUTPUT**, re-deriving every expected
value independently of what the writer recorded, and match consumer rows by
NAME — positional zipping silently compared `hurtbox[4]` against `hurtbox[5]`
once stage 5 removed the `dynamicDesc` row.

Install the lookup: `MexFighterBoneDefinitions.Lookup` → `GeneratePlCo.Compile`
→ `SetPlCo`, then read the exported table back with `bone_lookup.from_plco` and
compare. (Use `from_plco`, not `echo/ft_parts_table.load_tables`, which
treats data-relative offset 0 as null and silently drops Bowser.)

Installing it directly is also fine and is what `artifacts/native-port-*/stage3.py`
does: the reverse array is `parts_num` bytes and native rigs are BIGGER than the
donors they displace (105 vs Bowser's 76), so append the new arrays and **rewrite
the fighter's 12-byte row IN PLACE**, reusing the two relocations already at
`row+0` and `row+4`.

> **Never orphan a block to move it.** An offset that nothing points at stops
> being a block boundary, and the archive derives array extents from those
> boundaries. Orphaning Bowser's row at `0x23450` made Kirby's neighbouring
> reverse array look 12 bytes longer and the preservation walk reported a
> difference where not one byte had changed. The same trap bites the hurtbox
> bank and the modelPart lists in stage 4.

**Argue the null slots, do not assume them.** A slot left `0xFF` needs evidence
its consumers cannot reach it. Three admissible arguments, in order:
a fully-playable vanilla fighter ships `0xFF` in the same slot; no decomp call
site names it; or every call site lives under another character's
`ft/chara/ftXxx/` and so cannot execute for this fighter. Two traps: the
Wireframes (kinds 27/28) null 48 of 54 slots, so counting them as precedent
makes every slot vacuously safe — restrict precedent to the 27 playable kinds;
and the decomp spells these `FtPart_TopN`, not `TopN`, so a bare-name lookup
scores every slot zero and "no call site" silently means "my key never matched".

### 5. Replace incompatible procedural ownership
**Disable donor dynamics initially** — Incineroar shipped that way and never made
Bowser's dynamics source-native. Reintroducing physics needs authored topology:
`ftdynamics.c:78` advances `GetChild()` and `bone_id++` together, so remapping a
chain's first index is not enough.

Audit retained donor callbacks. **A lookup cannot repair hard-coded literals.**
Measured across both donors, there are only four, and they are not equal:

| site | spelling | raw | verdict |
| --- | --- | ---: | --- |
| `ftKp_SpecialN.c:68` | `48` | 48 | **LIVE, WRONG BONE** — flame origin; wants Head |
| `ftPp_SpecialN.c:165` | `0` | 0 | LIVE, still correct — index 0 is the root on both rigs |
| `ftPp_SpecialLw.c:184` | `FtPart_L3rdNa` | 26 | neutralised — `SpecialLw` is PT-reserved |
| `ftPp_SpecialLw.c:194` | `FtPart_L4thNb` | 29 | neutralised — same |

Two traps here. **`fp->parts[FtPart_L3rdNa]` is not a semantic lookup** — it
indexes the raw parts array with the enum's numeric value (26), so the stage-3
table has no effect on it despite reading as if it would. And a literal is only
*wrong* if the bone now at that index differs from the one you bound to the slot
the donor's bone occupied; check before reporting, or you flag correct code.

A literal inside an action another system owns outright never executes — the PT
transform replaces the `SpecialLw` ftFunction slot, which is why two of the four
are inert.

### 6. Encode, adapt movement, then verify

**Apply movement ownership PRE-encode, on world matrices.** Cancelling the
root's per-frame travel on the owned axes and shifting every joint by the same
vector leaves every local transform untouched, so the pose survives exactly and
only the travel goes. This is strictly better than
`movement_ownership.adapt_common_bank`, which edits packed bytes afterwards.

> **Cancel the travel on BOTH sides when measuring.** Comparing a de-travelled
> clip against a source that still travels charges the intended change as error:
> it read **234.12 units** of worst integer pivot on Charizard while `basis`
> stayed bit-identical at 0.00554. Rotations untouched and translations off is
> the signature of this mistake, not of a bad encode. `bank.py`, `recheck.py`
> and `skincheck.py` all need the same correction.
> Corollary: put the movement decision in the encoder's **cache key**. Added
> afterwards, `--movement` silently reused every cached row and changed nothing.

**Assembling the AJ.** Concatenated FigaTree DATs, 0x20-aligned; the action
table holds `anim_offset` at +0x04 and `anim_size` at +0x08. Key the blob by
SYMBOL — several actions share one (Bowser: 269 actions, 210 symbols).

* **Not every clip in a fighter's AJ is that fighter's.** Bowser's bank carries
  11 under `PlyTaro_Share` and Popo's 4 — Giga Bowser's throw-victim animations,
  which play on HIS skeleton. Copy them byte-for-byte; re-authoring one against
  your rig drives the wrong bones on a character you never touched. This is why
  `owned_motions` filters on the symbol prefix.
* Read passthrough spans from the **vanilla** Pl, not the working one. Once this
  stage repoints the action table, a second run slices the vanilla AJ at your
  offsets and copies garbage.
* `struct FigaTree` (`lb/lbanim.h:18`) is `{int type; u32 flags; f32 frames;
  s8* nodes; FigaTrack* tracks}` — the node array is at **+0x0C** and its
  entries are signed bytes terminated by -1, exactly as `ftanim.c:607` walks
  them. Reading +0x08 lands on the `frames` float and returns nothing for every
  clip, vanilla included.

**Verify by slicing the written AJ with the written Pl's own action table** and
requiring each span's root symbol to equal the symbol the action names. That is
the check that catches an off-by-one: a shifted span lands on a different but
perfectly valid clip. Also confirm native clips declare exactly as many nodes as
the rig has parts, and that foreign clips are byte-identical to vanilla.

Then verify contracts: `rig_preflight.prepare`, `costume_binding`,
measured DOL-capacity checks.
`rig_preflight` states plainly that passing its layout gates proves **neither
callback ownership nor collision semantics**.

**Require coverage of every OWNED animation row**, with separate
explicit contracts for genuinely foreign victim animations. A converted idle is
not sufficient evidence of a complete bank.

#### Declare thresholds in code, and evaluate off the fitting grid

A sweep that records `status: ENCODED` for every row and picks a cut-off after
looking at the results is a measurement, not a gate. Put the numbers in the
module (`native_port.ACCEPTANCE`) before the run.

**Measure on a grid the rows were NOT fitted on.** Fitting and measuring on the
same grid cannot see error introduced between samples. Measured on Charizard's
bank: worst pivot **0.041 at integer frames** (0 rows over 0.2) versus **2.76
at 1/16** (10 rows over 0.2). Same files, same day, 67x apart.

#### Fractional evaluation and packed key timing

Measure between frames even though this encoder uses integer key positions.
The old claim that floating point editor frames prove fractional packed keys
was incorrect: HSDRaw writes packed integer delta times. Changing slope-key
ordering alone cannot add fractional timing. The preserved FigaCodec rejects
fractional key locations. A different playback clock would need separate
engine and timing validation; tighter scalar tolerances cannot remove this
representation limit.


### Stage 9 — the render scale (do NOT inherit the donor's)

Melee **does** have a per-fighter model scale in data. It is
`ftCo_DatAttrs.model_scaling`, an `f32` at **attributes + 0x8C**
(`types.h:726`), reached as `ptr@(ftData+0x00)` then `+0x8C`:

```c
float ftCommon_GetModelScale(Fighter* fp)            // ftcommon.c:1412
{
    return fp->x34_scale.y * fp->co_attrs.model_scaling;
}
```

`Fighter_UpdateModelScale` (`fighter.c:215`, from the creation path at
`fighter.c:545`) pushes the product onto the fighter's root JObj.
`x34_scale.y` is the per-PLAYER runtime factor (Giant Melee, Yoshi egg) and is
1.0 in a normal match — do not mistake `Player_GetModelScale` for the whole
story, which is how an earlier pass concluded there was no data attribute and
shipped Charizard at two thirds size.

The value **corrects for how the donor's own rig was authored**, so copying the
donor's ftData copies a number that means nothing on your rig. Rig extent below
is the Y span of bind-pose joint worlds from `PlXxNr.dat`:

    Bowser  42.63 x 0.69 = 29.42     Popo   8.63 x 1.15 =  9.93
    DK      24.50 x 1.00 = 24.50     Kirby 10.60 x 0.92 =  9.75

Bowser's model is authored ~1.45x oversized; that is the entire reason he is
0.69. Pick the port's value by MEASURING its frozen rig against the roster
table, not by keeping the donor's. Charizard: rig 20.58, 0.69 -> 14.20 (Fox
class) became 1.30 -> 26.75 (between DK and Bowser, head level with Bowser's).

**Separate hitbox offsets from radii (audit correction, 2026-09-13).** Offsets
pass through the bone world matrix (`lb_8000B1CC`); model scale affects them.
Hitbox Size is loaded directly by `ftaction.c:326` and multiplied by the
runtime player scale `x34_scale.y` at collision time, not by `model_scaling`
(`ftcoll.c` -> `lbColl_8000805C`). The previous median comparison did not prove
radius scaling; the original stage9 writer and verifier shared that mistake.
Do not rescale Size to compensate for a model-scale change.

`fighter_scale.apply` separates radius and offset policies and traverses shared
subroutines, jumps and demo scripts. An immutable baseline allows repeatable
edits and repair of the original stage9 output. `ignore_fighter_scale` affects
the radius's runtime player scale; it does not bypass the bone matrix for
offsets. Preserving local offset products cannot establish contact geometry
after moving a hitbox to a different bone on a different skeleton.

Also scaled by this value: animation-driven TransN travel (`ftanim.c:179`).
Other consumers, including IK and hurt capsules, need their own coordinate-space
checks; do not infer their behavior from script hitbox radius handling.

The `native_port` MCP exposes the reusable scale repair, material bake, static
costume shims and reachable-script inventory. The Pokémon Trainer campaign
that produced these rules (its artifacts, UV conventions and acceptance notes)
is kept under the git tag `archive/fighterport-character-specific-2026-11`.

## Animation: no retarget, but still a conversion

The clips are already on these bones, so there is **no anatomical retargeting**.
`ultimate.decode` converts quaternions to HSD Euler and writes Maya `.anim`.
Still unsolved / to check:

* integer samples do not guarantee correct **fractional-frame** interpolation
* it rejects compensation/override flags; `RawSource` + `source_rig_worlds.expand`
  covers the supported compensation case, overrides need investigation
* engine translation, facing, damage/landing clocks and script timing need
  explicit adaptation
* packed values, tangents, key times and reduction error must be checked **after
  encoding**, preferably on skinned vertices
* material/constraint/physics behaviour absent from skeletal clips will not appear

> **Do not feed these `.anim` into the donor AJ.** `--anim import` derives node
> count from the existing clip, needs `--map` for named bones, and **doubles
> reduction tolerance until it fits a hard-coded 32 KB limit**, automatically
> relaxing tolerance with no geometry acceptance gate. It does report the
> increased tolerance; damage is possible, not guaranteed. Seed the native node domain first; use the packed-codec
> path for larger profiles.

## Where Blender fits (and where it does NOT)

Blender 4.2 is installed at `<MOCAP_ROOT>/blender/blender.exe` (portable unpack;
`shared.modellab.heat_weights.find_blender` resolves it via `MOCAP_ROOT`).

**Use it for verification renders** -- matched-camera CPU renders of the SOURCE
scene against the DAT scene at full skin, same cameras, same scale. That is the
clearest place it earns its keep here. (It is not Blender's only appearance in
that work: `prepare_donors.py:66` calls `rigkit`, which invokes Blender via
`pipeline.py:667`.)

* `pilots/incineroar/blender_fitted_compare.py` — "measured source/DAT scenes,
  fixed full-body cameras"
* `pilots/incineroar/blender_hand_compare.py` — full-body + hand detail
* `pilots/incineroar/blender_crouch.py` — native full-skin vs DAT frames

**Do NOT reach for these on a source-native port:**

* **Bone-heat weights** (`shared/modellab/heat_weights.py`, `blender_boneheat.py`).
  Bone-heat exists to invent weights when draping a mesh over a FOREIGN
  skeleton. Here the source mesh already carries correct weights for its own
  bones — stage 2 says explicitly not to carry donor-fitted weights across.
  Using bone-heat would replace good data with a guess.
* **A Blender IK retarget for anatomical retargeting.** There is none to do on a
  native rig. Narrower caveat: grounding and contact corrections can still be
  needed *after* movement and timing adaptation, so do not delete the idea
  outright -- just do not run a landmark retarget. (`foot_plant.py` /
  `ground_anims.py` in `artifacts/pt-anim-20260911` are donor-route repairs.)

**What Blender cannot do.** It cannot repair engine consumers. The Incineroar
campaign reached v58 and much of that was engine integration -- physics-owned
walk/run `Trans` channels, dash-grab Z extraction, damage/appeal clocks, aerial
landings, audio banks, color/portrait mapping. But **not all of it was**: v55
explicitly changed geometry and skin weights for performance
(`PERFORMANCE-OPTIMIZED-v55.json:79`). So "the 58 iterations happened because
Blender wasn't used" is not established -- and neither is the reverse. What IS
true: only the consumer census and the gates in this document address the
engine-integration class of failure.

## Risk and the cheapest falsifier

**Highest risk: procedural writes that stay in range but hit the wrong bone.**
A valid lookup and a good-looking render do not detect it.

**First end-to-end offline test** (not proven to be the *cheapest* -- cheaper
gates come first: source-flag / strict-transform checks on the raw clip, and
serialized bind / inverse-bind readback). Then a native-rig `Wait1` control — for Charizard it already exercises wings and tail.
Serialize skeleton and skin, encode the clip, independently decode it, and
compare full-skin positions against `RawSource` at integer **and** fractional
times with `rig_benchmark.measure`. Set **explicit error thresholds** up front,
and include an **unreduced control** so a conversion failure is distinguishable
from a reduction failure. Reject on geometry error, unsupported transforms,
wrong node order, or exceeded measured capacity. Reuse
`sweep_source_native.py:48` -- which itself warns that a failed precision
candidate does **not** establish architectural impossibility.

A passing `Wait1` also says nothing about **worst-case clip capacity**; size the
largest clips separately.

This tests fidelity and budget. It does **not** clear the engine-integration
risk: before booting, additionally require every known consumer to be explicitly
remapped, replaced, or disabled.

## Scope honesty

Incineroar reached this over a long campaign (the delivered receipt is **v58**,
after playtest repairs). What it did *not* solve generally: automatic migration
of arbitrary donor callbacks, generic secondary physics, exhaustive
compatibility. Delivered scope is representative two-player play; Kirby copy and
single-player donor metadata retain limitations. **This pipeline is a sequence of
gated stages requiring judgement at several, not a one-shot conversion.**

## Per-character measured facts

| | source joints | frozen rig | donor | owned rows | source coverage |
| --- | ---: | ---: | --- | ---: | ---: |
| Squirtle | 44 | **63** | Popo (`ftDataPopo`, 49 parts) | 195 | 189 (97%) |
| Ivysaur | 54 | **74** | Popo | 195 | 189 (97%) |
| Charizard | 73 | **105** | Bowser (`ftDataKoopa`, 76 parts) | 199 | 192 (96%) |

Frozen rig = source + scale helpers + Euler charts + 4 engine controls.
Only Squirtle needs scale helpers (2, on the tail). All three fit vanilla
`MAX_FT_PARTS` 140.

Consumer census, corrected (following pointers, reading model-part lists):

| donor | distinct joints read | raw refs | semantic refs |
| --- | ---: | ---: | ---: |
| Bowser | 46 | 548 | 1 (`hip`, from `DamageFly*`) |
| Popo | 37 | 437 | 2 (`hip`, from `DamageFlyHi` and `TPopoThrowB`) |

Popo additionally exercises `Animate Model` (6 refs on body part 2), which
Bowser never does -- a consumer class one donor can retire and another cannot.

Source idles already contain the articulation the donor build lacks: Charizard's
wings and all four tail tracks vary in `a00wait1`; so do Ivysaur's leaf/vine
tracks and Squirtle's tail.

Digit numbering: **measure it per fighter, the number does not tell you.**
`digits.py` expresses each digit's root direction in the parent hand's frame
and picks the digit whose MINIMUM separation from the others is largest.

| | digits | thumb | min separation |
| --- | --- | --- | --- |
| Charizard | 1, 2, 5 | **5** | 33.9° vs 29.9° |
| K. Rool | — | 5 | 34.5° (earlier measurement) |
| Squirtle | 1, 2, 3 | **1** | 49.2° vs 39.5° |
| Ivysaur | one per hand (`Finger?51`) | n/a | nothing to compare |

Charizard's digits hang off a short hub (`HandL -> FingerL10 -> ...`), so a
"direct children of the hand" probe reports his hands as fingerless. A digit
root is the first `Finger*` bone below the hand that does not FAN OUT.
