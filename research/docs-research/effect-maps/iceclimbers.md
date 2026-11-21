# EfIcData.dat — Ice Climbers effects (MAP-STATIC draft)

**Target file:** `storage/test-base/files/EfIcData.dat`
(`effIceclimberDataTable`, bank index **14** in `efAsync_DatEntries`, `efasync.c:1160`).
**`effect_id_start = 14000` (0x36B0)** → **script index = gfx_id − 14000**.
17 generators (indices 0–16, gaps at 1,7,14 which are texture-only / no colour).
Header: `EffectTable@0x20 ParticleGroup@0x40 version=0x42 tex_bank@0x6C0`.

Status: **LIVE pass DONE (2026-07-02, MAP-LIVE final batch).** Parser confirmed every
draft offset byte-exact. **Ice Shot recolors broadly** — birth swirl (script 0), block-glow
variants (scripts 3/4), and sparkle (Family A scripts 2/6/8/12) all 🟢 CONFIRMED. **Freeze
crystals (Family B scripts 9/11/13/15) = DEAD at ptcl offsets** — the visible freeze
snowflake/crystal is the item's freeze TEXTURE/model, not these operands. See §LIVE.
Probe specs: `backend/probes/iceclimbers_probe.json` (bag), `iceclimbers_probe_solo.json`
(no-bag, projectile-visible — the clean Ice Shot A/B), `iceclimbers_probe_freeze.json`
(bag freeze A/B).

## LIVE results (verdicts + capture dirs)

**Ice Shot is a forward-firing PROJECTILE → fully solo-visible; run NO-BAG** so the
climbers stay planted and frames align (the `_solo` spec). The freeze family needs the
victim hit, so it used the bag (`_freeze`, poked-first-then-vanilla to avoid carryover).

| Group | scripts | offsets | verdict | evidence |
|---|---|---|---|---|
| **ice_shot_birth** | 0 | 0xE2–0x103 | **🟢 CONFIRMED** | spawn swirl vortex turns red — `probe-iceclimbers-solo/ice_shot_birth-neutralb-f10.png` vs `vanilla-neutralb-f10.png` (vanilla blue swirl → red). |
| **ice_shot_sparkle** (Family A) | 2,6,8,12 | see §2 | **🟢 CONFIRMED (subtle)** | the birth/impact sparkle burst at the block base goes red — `probe-iceclimbers-solo/ice_shot_sparkle-neutralb-f22.png` vs `vanilla-neutralb-f22.png` (red streak at block base). Subtle; **flag frame f22 for EYEBALL double-check.** |
| **ice_shot_variants** | 3,4 | 0x20E–0x283 | **🟢 CONFIRMED** | one ice block's internal glow turns red — `probe-iceclimbers-solo/ice_shot_variants-neutralb-f22.png` (left block glows red inside). |
| **freeze_crystals** (Family B) | 9,11,13,15 | see §2 | **🔴 DEAD at ptcl offsets** | victim (DK) FROZE and shattered but the blue snowflake glyph + crystal shards stayed BLUE with pokes active+readback-OK — `probe-iceclimbers-freeze/freeze_crystals-neutralb-f22.png` & `-f30.png` vs `vanilla-neutralb-*`. Freeze visual = item texture/model, not these operands. (The green radial hit-spark is a shared/common-bank effect present in vanilla too — NOT ours.) |

Draft §2 vanilla bytes all byte-verified; only the Ice-Shot rows are LIVE-green.

## 0. Headline findings

1. **Popo and Nana SHARE this file** — `efAsync_DatEntries` has exactly one
   `EfIcData.dat` entry; both fighters resolve the same bank. There is no per-climber
   split at the effect-file level (their fighter DATs differ, the effect table is one).
   For the probe, boot ICs normally (char key `ics`/`popo`, external id 0x0E,
   `char_select.py`).

2. **Almost everything is icy-blue** — no purple/warm operands anywhere. Every ptcl
   colour is a shade of blue/white (`79B8F7`, `2E66FF`, `515DFF`, `1994FF`,
   `0F3BFF`, `1303BD`). Anti-color for LIVE = **red/orange/green** (far from blue).

3. **ICs specials spawn effects via ITEMS, not fighter `efSync_Spawn`.** The decomp
   `ftPopo/ftPp_Special*.c` spawn item objects; the items
   (`it/items/itclimbers*.c`) carry the EfIc particles:
   - **neutral-B Ice Shot** → `itClimbersice.c` (`It_Kind_IceClimber_Ice`), which
     `efAsync_Spawn`s symbolic ids **0x4E9 / 0x4EA / 0x4EB** across its lifecycle
     (spawn / travel / destroy). Those resolve in `efsync.c:406–420` via
     `hsd_8039EFAC(0, 0xE, …)` (0xE = bank 14 = EfIc) to gfx **0x36B0 / 0x36B1 /
     0x36B6** = **scripts 0 / 1 / 6**. (It also emits 0x4AE/0x4AF/0x4B0 → gfx
     0xB3B0… which is a *different, higher bank*, NOT EfIc — quarantined below.)
   - **down-B Blizzard** → `ftPp_SpecialLw.c:187 itClimbersBlizzard_Spawn` +
     `efSync_Spawn(0x4EC…)` → gfx 0x36B7 = **script 7** (texture-only, 0 operands —
     the snow model is the item's own geometry/texture).
   - **up-B Belay** → `ftPp_SpecialHi.c` `itClimbersString` (rope/sparkle) — no EfIc
     ptcl operand found in the string item; the rope glimmer is likely model/texture.
   - **side-B Squall Hammer** = SpecialS — no EfIc ptcl spawn found; the swirl is
     likely the hammer swing model + a shared common-bank spark.

4. **Mission-target reconciliation:** the mission listed "ice breath (neutral-B
   blizzard)" but in retail Melee **neutral-B = Ice Shot** and **down-B = Blizzard**.
   The ptcl colour records live on **Ice Shot (scripts 0,1,6 and siblings)** — that
   is the recolorable target. Blizzard (script 7) and Belay are texture/model, no
   ptcl colours. Squall Hammer swirl has no dedicated EfIc ptcl record found.

5. **Colour layout** = CF/DF ptcl operands, RGB byte at the parser's `file_off`
   (probe pokes RGB there directly). PRIM (0xCF) = birth, ENV (0xDF) = sustained tint.

## 1. Script → move map

| Script | gfx_id | Spawned by | Move | ptcl colours |
|---|---|---|---|---|
| **0** | 0x36B0 | 0x4E9 (itClimbersice spawn) | **Ice Shot** birth flash | 5 |
| **1** | 0x36B1 | 0x4EA (itClimbersice travel) | **Ice Shot** — TEXTURE-ONLY (0 operands) | 0 |
| **6** | 0x36B6 | 0x4EB (itClimbersice) | **Ice Shot** sparkle burst | 3 |
| **7** | 0x36B7 | 0x4EC (SpecialLw / Blizzard) | **Blizzard** — TEXTURE-ONLY (0 operands) | 0 |
| 2,3,4,5,8,9,10,11,12,13,15 | 0x36B2… | item lifecycle (unattributed per-state) | Ice Shot / freeze sparkle family | see §2 |

Scripts 2,3,4,5,8,9–15 carry blue operands but no clean per-move decomp attribution
(they fire across the ice item's states + freeze-shatter). Grouped by vanilla
signature into two families below; the LIVE pass sorts which fire on neutral-B vs on
a frozen opponent's shatter (**freeze crystals** — capture with a bag that gets frozen).

## 2. Candidate colour tables (grouped by vanilla signature; offset = RGB start)

### Family A — Ice Shot sparkle (`FAFCFF`/`515DFF`/`BAEEFF`), scripts 2,6,8,12
Identical vanilla bytes across all four — one visual, four generators.
| Layer | offsets | op | vanilla RGB |
|---|---|---|---|
| iceshot_c1 (PRIM) | 0x1A5, 0x335, 0x3EC, 0x58C | PRIM | `FAFCFF` (near-white) |
| iceshot_c2 (ENV)  | 0x1AC, 0x33C, 0x3F3, 0x593 | ENV  | `515DFF` (blue) |
| iceshot_c1b (PRIM)| 0x1B2, 0x342, 0x3F9, 0x599 | PRIM | `BAEEFF` (pale cyan) |

### Family B — freeze crystals / blizzard snow (`1994FF`/`1303BD`/`0F3BFF`), scripts 9,11,13,15
Identical vanilla bytes across four generators — the deep-blue crystal shards.
| Layer | offsets | op | vanilla RGB |
|---|---|---|---|
| crystal_c1 (PRIM) | 0x44A, 0x527, 0x5EA, 0x656 | PRIM | `1994FF` (blue) |
| crystal_c2 (ENV)  | 0x451, 0x52E, 0x5F1, 0x65D | ENV  | `1303BD` (deep blue) |
| crystal_c1b (PRIM)| 0x458, 0x535, 0x5F8, 0x664 | PRIM | `0F3BFF` (blue) |

### Script 0 — Ice Shot birth flash
| Layer | offset | op | vanilla RGB |
|---|---|---|---|
| birth_c1 | 0xE2  | PRIM | `79B8F7` (light blue) |
| birth_c2 | 0xE9  | ENV  | `0101F9` (pure blue) |
| birth_c1b| 0xEF  | PRIM | `2E66FF` (blue) |
| birth_c2b| 0xF6  | ENV  | `0B07EE` (blue) |
| birth_c1c| 0x103 | PRIM | `679CFE` (blue) |

### Scripts 3,4 — Ice Shot variants (`2E17FF` env)
| Layer | offset | op | vanilla RGB | script |
|---|---|---|---|---|
| var_c1 | 0x20E | PRIM | `FAFCFF` | 3 |
| var_c2 | 0x215 | ENV  | `2E17FF` | 3 |
| var_c1b| 0x21B | PRIM | `1AB4DE` | 3 |
| var2_c1b| 0x283 | PRIM | `82EBFF` | 4 |

### Scripts 5,10 — misc
5: 0x2DC `FFFFFF`(PRIM) / 0x2E3 `0101F9`(ENV).
10: 0x4BC `CEE5FE`(PRIM) / 0x4C3 `0B05BC`(ENV) / 0x4CA `E2F5FE`(PRIM).

## 3. AUDIT_HINTS (frame windows from LIVE session)
- `neutralb` (Ice Shot): the projectile spawns ~f10 and the sparkle burst peaks ~f16–22.
  **No bag** (solo-visible projectile) — capture `[10,16,22,30]`. Anti-color: red `FF0000`
  (vanilla blue). Watch the block-base sparkle + the birth swirl.
- `downb`/`upb`: texture/model, no shippable ptcl colour.

## 4. Editor grouping (WIRE) — SHIP THE ICE-SHOT GROUP; DROP FREEZE

**`ice_shot`** (DualColor, 🟢) — one group covering birth swirl + block-glow variants +
Family-A sparkle. All are near-white/blue and read as one recolorable Ice Shot look.
- **`_c1` (PRIM, near-white/blue birth+sparkle):**
  - script 0 (birth): 0xE2 `79B8F7`, 0xEF `2E66FF`, 0x103 `679CFE`
  - Family A sparkle PRIMs: 0x1A5/0x335/0x3EC/0x58C `FAFCFF`; 0x1B2/0x342/0x3F9/0x599 `BAEEFF`
  - variants PRIMs: 0x20E `FAFCFF`, 0x21B `1AB4DE`, 0x276 `FAFCFF`, 0x283 `82EBFF`
- **`_c2` (ENV, blue tint):**
  - script 0: 0xE9 `0101F9`, 0xF6 `0B07EE`
  - Family A: 0x1AC/0x33C/0x3F3/0x593 `515DFF`
  - variants: 0x215 `2E17FF`, 0x27D `2E17FF`
- Anti-colors: `_c1`→red `FF0000`, `_c2`→red `FF0000`.
- **lesson-12 warning:** per-record vanilla bytes DIFFER within each operand list
  (`FAFCFF` vs `BAEEFF` vs `82EBFF` vs `1AB4DE` on PRIM; `515DFF` vs `2E17FF` vs `0101F9`
  vs `0B07EE` on ENV) — WIRE MUST key each record by its own vanilla bytes, not a single
  grouped vanilla, or reset/preview ships wrong.

## 4b. DO NOT SHIP (LIVE-dead)
- **freeze_crystals Family B** (scripts 9/11/13/15, 0x44A/0x451/0x458, 0x527/0x52E/0x535,
  0x5EA/0x5F1/0x5F8, 0x656/0x65D/0x664): DEAD — freeze snowflake/crystal is item texture,
  not these ptcl operands. Poking them red left the freeze visual blue. Candidate for a
  future `type:"texture"` recolor on the item's freeze texture, NOT a ptcl layer.
- Scripts 1,7 = texture-only (0 operands). Blizzard/Belay = texture/model.

## 5. Nana/Popo shared-file note (IMPORTANT for WIRE)
`efAsync_DatEntries` has exactly ONE `EfIcData.dat` entry — **both Popo and Nana resolve
this same bank**. So a single recolor of these offsets applies to BOTH climbers'
Ice Shots automatically; there is NO separate Nana copy to also patch (unlike a
fighter-DAT edit where Nana must be paired). Nana echoes Popo's neutral-B, so her Ice
Shot draws the SAME EfIc scripts and recolors identically — verified implicitly (the
probe boots ICs normally; both climbers on stage share the file). WIRE: patch once, done.

## 6. Quarantine / open leads
- **0x4AE/0x4AF/0x4B0 → gfx 0xB3B0/0xB3B1/0xB3B6** (`efalt.c:453`, bank `0x2E`) are
  spawned by `itClimbersice` but land in a **different, higher effect bank, NOT
  EfIcData** — do NOT ship as EfIc layers.
- Only 2 stray model-region colour blocks past the ptcl bank (vs Ganon's 190) → ICs
  effects are ptcl + item-texture, essentially no effect-model geometry to recolor.
- Belay rope sparkle + Squall Hammer swirl: no EfIc ptcl record located; likely
  fighter/item model + common-bank (EfCoData) sparks. Confirm in LIVE by probing
  those specials and checking for any EfIc diff before declaring dead.
