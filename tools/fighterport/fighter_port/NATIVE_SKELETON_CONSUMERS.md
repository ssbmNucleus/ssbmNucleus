# Native skeleton: the engine-consumer map

What must be re-pointed when a fighter's skeleton is replaced. Start from
[ULTIMATE_PORT_PIPELINE.md](ULTIMATE_PORT_PIPELINE.md) for the pipeline; this page is the list
that pipeline's stages 3-4 must satisfy.

Measured from the decomp (`~/projects/melee`), HSDRaw, a retail PlCo.dat, and
the delivered Incineroar rig. Reviewed adversarially 2026-09-12. Earlier
revisions of this file were wrong and have been **removed rather than
annotated** — a corrections block does not neutralise executable instructions
sitting below it.

## Melee addresses bones two ways

### 1. Semantic parts — one authorable table

`src/melee/ft/types.h:50`

```c
/// Table in PlCo.dat
struct FighterPartsTable {
    u8* joint_to_part;   // "reverse", length parts_num
    u8* part_to_joint;   // "forward", 54 slots in a 56-byte allocation
    u32 parts_num;
};
```

```c
/* ftparts.c:700 */
Fighter_Part ftParts_GetBoneIndex(Fighter* fp, Fighter_Part part)
{ return ftPartsTable[fp->kind]->part_to_joint[part]; }
```

* **Data, not code** — `ftPartsTable = pData[4]` (`fighter.c:194`) out of
  PlCo.dat. No DOL patch needed to author it.
* **A writer already exists.** `mexLib/Generators/GeneratePlCo.cs:12` loads
  PlCo, calls each fighter's `SetPlCo`, saves; `MexFighterBoneDefinitions.cs:57`
  installs `BoneDefinitions.Lookup`; invoked from `MexWorkspace.cs:469`.
  Do not write another one.
* **Slot order is `bone_lookup.SLOTS` — 54 slots.** HSDRaw iterates `0x36` and
  allocates `0x38` (`SBM_BoneTables.cs:181,215`); bytes 54-55 are alignment.
  Slot 53 (`extra`) is **consumed**, not padding: common init calls
  `ftParts_GetBoneIndex(fp, 0x35)` unguarded (`ftparts.c:695`).
* **Do NOT use the decomp `enum Fighter_Part`** (`forward.h:254`) as the storage
  order. They are competing labels for the same numeric slots and diverge at
  16 (`waistB` vs `BustN`) *and again* at 31 (storage `lHave, lThumb1, lThumb2`
  vs enum `LThumbNa, LThumbNb, LHandNb`). Labelling storage bytes with decomp
  names yields confident, wrong conclusions — it already did once here.
* `FtPart_56` is **not** an exclusive bound: Samus uses joint index 56 directly
  (`ftSs_SpecialN.c:432`). `MAX_FT_PARTS` is 140 (`ftparts.h:51`, enforced
  `ftparts.c:403`); the delivered Incineroar build patches past it.
* `parts_num` is the **runtime indexed domain** — close to, but not strictly,
  a physical joint count (`ftparts.c:409` may insert null/reserved entries).
  Measured: Bowser 76, Popo 49, Marth 90.
* `ftPartsRemap(to, from, joint)` (`ftparts.c:704`) already performs
  cross-skeleton joint → part → joint translation.

#### 0xFF (`FTPART_INVALID`)

| | status | why |
| --- | --- | --- |
| `joint_to_part[j] = 0xFF` | **supported unmapped sentinel** | consumed by `ftPartsRemap`, which tests `!= FTPART_INVALID` first (`ftparts.c:708`). Correct for wings/leaves/vines/flower. Not a free pass — skipping a transferred animation can still be behaviourally wrong. |
| `part_to_joint[p] = 0xFF` | **conditional** | vanilla does it (Mario 3, Bowser 6, Popo 14; range 1-28 across playable kinds). But `ftParts_GetBoneIndex` returns it **raw and unguarded**. Some *callers* guard — `ftanim.c:679-680` tests the `ftPartsRemap` result — but that is per-path, not general. Null a part only with evidence its consumers are **unreachable or safely guarded** for this fighter. |

Never null across the **ordinary playable fighter kinds (0-26)**, and read by
common code for every fighter: `top`, `trans`, `xRot`, `yRot`, `hip`, slot 53.
`hip` is not merely a common-code read — it is the one part id BOTH measured
donors address semantically from a subaction script (`Create Hitbox` with
`use_common_bone_ids = 1`, in the `DamageFly*` launch hitbox).
**Not** a universal rule -- outside that range vanilla does null them: kind 27
and kind 28 have `hip` (slot 4) = `FF`, and kind 32 has `extra` (slot 53) = `FF`.
Storage slot 52 (`throw`) is populated across all 33 kinds.

### 2. Raw joint indices — rebased per fighter

> **Type-alias trap:** `ftHurtboxInit.bone_idx` is *declared* `Fighter_Part`,
> and `ftParts_GetBoneIndex` is declared as *returning* one, but callers index
> `fp->parts[<value>]`, and `fp->parts` is **joint**-indexed with `parts_num`
> entries (`ftparts.c:403-454`). These are joint indices; the type name is a
> decomp artifact.

## Consumer checklist

"Censused" = covered by `fighter_bone_inventory.direct_bone_inventory`
(ftData `center` 0x34, `ecb` 0x44, `special` 0x54, hurtboxes).

| Consumer | Addressing | Censused | Notes |
| --- | --- | --- | --- |
| Semantic lookup | part id | n/a | author the PlCo table |
| `center` | raw joint | yes (1) | ftData +0x34; `ft_07C1.c:42-46` (thrown-fighter hitbox) |
| ECB | raw joint | yes (6) | `ftData_x44_t`, six `s16`; `ft_081B.c:56-62` |
| `special` head/arms/legs | raw joint | yes (5) | `ftCo_09F7.c:76,112` |
| Hurtboxes | raw joint | yes (15 Bowser / 12 Popo) | `ftcoll.c:3235-3239`. A hurtbox rebase covers hurtboxes ONLY — not center, ECB or special. |
| **IK, `ftData+0x58`** | raw joint | yes (all ten) | **TEN bone bytes** — `SBM_FighterIK.cs`: `RLegJ, LLegJ, RKneeJ, LKneeJ, RFootJ, LFootJ, RShoulderJ, LShoulderJ, RArmJ, LArmJ`. Incineroar's control remaps all ten. `ft_0899.c:101-140` shows only part of the structure. **They are interleaved with LIMB-LENGTH floats the solver also consumes**: `ft_0899.c:95-98` reads `len0 = x58->x4 * scale.y`, `len1 = (x58->xC + x58->x18) * scale.y`. Bowser's are `6.04 / 6.20 / 8.0 / 3.76 / 4.81 / 5.20 / 30.0`. Re-pointing the indices without re-measuring these gives the solver the donor's proportions. |
| **Subaction hitboxes, incl. grabs** | **raw AND semantic** | yes (Bowser 196+1, Popo 377+2) | `ftaction.c:316` — `use_common_bone_ids` selects which mode. Scripts live in **Pl action data**, not "AJ subaction scripts". **You must FOLLOW `Subroutine` (0x05) and `Go To` (0x07)**: `echo.subactions` records those pointers without traversing them, and walking entry blocks only missed 32 blocks / 149 refs on Bowser — including his ONLY semantic reference (`0x35A0`, part 4 = `hip`, shared by `DamageFly*`). Walk the DEMO table (ftData+0x14) too. |
| **Dynamic / physics bones** | raw joint | yes (Bowser: 1 desc on joint 49, 0 bubbles) | `ftdynamics.c:49`. Separately, `FighterActionDynamicBehaviors` (ftData+0x10, 1:1 with the action table) carries a byte often mistaken for a part id: **it indexes `ft_data->x2C->x10[]`, the per-action dynamics FigaTree table** (`ftCo_8009E4A8`, `ftdynamics.c:533`). A third addressing domain, not the parts table. |
| **Shield / reflect / absorb** | raw joint | **NO** | `ftcoll.c:3188 / 3204 / 3214` |
| **Camera zoom target** | raw joint | **NO** | `types.h:769`; lookup chain `ftlib.c:335` → `302` |
| **Script GFX** | **raw, semantic, OR special selector** | **NO** | `ftaction.c:252` reads `useCommonBoneIDs`; `ftCo_09F7.c:91` conditionally calls `ftParts_GetBoneIndex`; special selectors `0x8D/0x8E` at `ftCo_09F7.c:72-112`. Do not assume raw. |
| Per-bone hurt-state / wind | raw joint | **NO** | `ftaction.c:554,1298-1313`; `ftdynamics.c:590` |
| Model-header bone bytes `(ftData+8)+0x10..0x14` | raw joint | **NO** | `ftanim.c:138`, `ftCo_Guard.c:264`, `ftaction.c:248,1175-1179` |
| ItemHoldBone initialization scale | model-header selector 0 | n/a | `ftAnim_8006FA58/FB88` call `ftCommon_8007F6A4` during action initialization: scale becomes `1 / ftData->x0->model_scaling` (attribute +0x8C). Omitted scale tracks retain this value; it is not the player size multiplier. Explicitly choose native or animation ownership. A source weapon below this joint inherits the scale and can shrink even when offline playback passes. |
| Coin collision array `ftData+0x38` | raw joint | **NO** | `ft_07C6.c:24` |
| Dynamics collision descriptors `dyn->x8[]` | raw joint | **NO** | `ftcoll.c:3252` |
| Sword afterimages | raw joint | **NO** | `ftafterimage.c:457` |
| Partial-animation roots / bone lists `ftData+0x1C` | raw joint | yes | `ftanim.c:1326,1351-1356`. **`SBM_ModelPart.Count` is the length of the byte list at `+0x04`, NOT a span from `StartingBone`** — Bowser's part 2 starts at 48 and lists `[53,54,55]`. `ftanim.c:1351` reads that list straight into `fp->parts`. |
| **PlCo's OTHER bone table, `pData[5]`** | — | **NO** | `fighter.c:195`; `ftparts.c:715-730,906-917` |
| Visibility lists | **DObj** indices, a different domain | **NO** | see [[animation-part-visibility]], `ftParts_80074B6C` |
| **Hard-coded character indices** | literal | n/a | Bowser flame `parts[48]` (`ftKp_SpecialN.c:68`), Bowser hurt-states `:410-421`, Popo Blizzard (`ftPp_SpecialLw.c:184,194`), Peach raw 109. **No table repairs these.** |

**A complete engine-wide census is UNVERIFIED.** `bone_lookup.remap_references`
resolves only what you hand it; it does not discover a consumer you missed.

**Measured totals** (`artifacts/charizard-native-20260912/stage0_*.py`):

| donor | distinct joints read | raw refs | semantic refs |
| --- | ---: | ---: | ---: |
| Bowser `ftDataKoopa` | 46 | 548 | 1 |
| Popo `ftDataPopo` | 37 | 437 | 2 |

`direct_bone_inventory` sees 27 of Bowser's. Consumer classes each donor
actually exercises differ: Popo uses `Animate Model` (6 refs, body part 2),
Bowser uses none; Bowser uses `Sword Trail` (4) and `Set All Bone Collision
States` (3). Do not carry one donor's "not exercised" to another.

`ftdynamics.c:78` advances `GetChild()` and `bone_id++` together, so re-pointing
a chain's first index does not establish chain topology.

## Measured donor facts

| donor | root | parts_num | hurtboxes |
| --- | --- | ---: | ---: |
| Bowser | `ftDataKoopa` | 76 | 15 |
| Popo | `ftDataPopo` | 49 | 12 |

Bowser's 27 direct refs: `center`=4; `ecb`=48,60,33,16,7,4; `special`
head/r_arm/l_leg/r_leg/l_arm=48,61,7,16,34; hurtboxes
30,4,55,48,60,33,61,34,15,6,16,7,19,10,29.

Pointed naively at the Ultimate rigs those indices land on: **Charizard** —
`WingL2`, `WingR1/2/5`, three finger bones, and `S_Fire2_null` (an effect null);
**Ivysaur** — `LeafR1/2`, `FlowerF/R/C`; **Squirtle** — bones 44 and 46 **do
not exist** on his 44-bone rig, and `direct_bone_inventory` raises
`Out-of-range direct joint index: hurtbox[7]=46`.

That last one is an offline proof of an **invalid candidate**. It is *not*
established as the cause of any particular observed in-game freeze.

## Hard capacities, measured

| thing | limit | where | what happens past it |
| --- | ---: | --- | --- |
| hurtboxes | **15** | `ftcoll.c:3227`, `types.h:1333` | asserts, then writes `fp->hurt_capsules[i]` anyway — **corrupts the Fighter struct** |
| fighter parts | 140 | `ftparts.h:51`, `ftparts.c:403` | 105 / 74 / 63 all fit; no patch needed |
| animation row | 32768 vanilla | `animation_capacity.SITES` | row REFUSED; `extend(..., WIDE)` raises it to 131040 |

Bowser ships **15** hurtboxes and Popo **13**. A Bowser-donor port therefore has
no room at all to cover body regions Bowser lacks — Charizard's wings and tail
cannot get hurtboxes without a DOL patch enlarging `hurt_capsules`.

Hurtbox struct: stride `0x28`, `+0x00` joint u32, `+0x04` height, `+0x08`
grabbable, `+0x0C..0x20` capsule a/b, `+0x24` radius.

## Which consumers may be RE-POINTED, and which must be RE-DERIVED

| class | operation | why |
| --- | --- | --- |
| ECB (six s16), `special` (five i32), IK bone bytes, `modelLookup.*`, script bone fields | **re-point** | bare indices; the ECB diamond and IK chain are evaluated from the bones' runtime positions |
| hurtboxes, centre, coin spheres | **re-derive** | capsule/sphere geometry — swapping the bone while keeping the donor's radii puts a correctly-named volume in the wrong place |
| IK floats `ftData+0x58` | **re-measure** | lengths scaled by fighter Y scale (`ft_0899.c:95-98`) |
| `modelPart` lists `ftData+0x1C` | **rebuild the region** | on BOTH donors these are the left-hand chain, the right-hand chain and the jaw/head sub-chain |
| dynamics `ftData+0x2C` | **disable** | `ftdynamics.c:78` walks `GetChild()` and `bone_id++` together; a chain is a walk, not an index |

**IK float identification** (measured against both donors' own skeletons, each
to ~0.5%): `0x04` thigh, `0x0C` shin, `0x20` upper arm, `0x28` forearm. `0x18`
matches no bone pair — an ankle drop, added to the shin by
`len1 = (x58->xC + x58->x18) * scale.y`. `0x2C`=50.0 and `0x30`=30.0 are
**identical on Bowser and Popo**, so they are angle limits, not lengths.

## Bridging donor joints to a native rig

Two tiers, recorded per joint: the **parts table** (`ftPartsRemap` offline),
then the **donor's own parent chain** for joints with no semantic slot — walk up
to the nearest bridged ancestor and read the offset. That identifies a bone
using the donor alone.

**Cross-species nearest-neighbour matching is invalid.** Validated against the
pairs the parts table already answers, pivot-position matching missed by a
median 0.29 / 0.44 / 0.21 of body height and put `headN → Head` 0.45 h apart.
Skin-centroid matching was no better. Validate any matcher on known pairs first.

`HSDRawViewer --model export` SMD node counts are **not** JObj joint counts
(Bowser: 191 nodes for a 76-joint rig). Do not join on them.

## Arrays have no slack

Every array measured here is allocated to exactly its current size — Bowser's
hurtbox bank 600 bytes for 15, Popo's 520 for 13, every modelPart list exact. A
longer array must MOVE, and an offset nothing points at stops being a block
boundary, which is how the archive derives array extents. Moving the hurtbox
bank made the consumer census read 161 rows instead of 60 and
`modelPart[0].entry[2]` come back as joint 153. Write in place; truncate or pad.

## Reading a real table

Use `bone_lookup.from_plco(payload, fighter_kind)` — it resolves DAT
relocations. Do **not** use `echo/ft_parts_table.load_tables`, which
treats data-relative offset 0 as null and therefore silently drops Bowser.
