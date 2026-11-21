# Zelda + Sheik effect map (MAP-LIVE complete 2026-07-02)

Mission: extras campaign, Zelda + Sheik. **ONE shared file `EfZdData.dat`
(symbol `effZeldaDataTable`) holds BOTH forms' effects.** Offsets parser-verified
vs `storage/test-base/files/EfZdData.dat` (all vanilla bytes byte-confirmed
below). Probe specs: `backend/probes/zelda_probe2.json` (corrected — see harness note)
+ `backend/probes/sheik_probe2.json`. Captures:
`tests/artifacts/datram-probe-zelda2/` + `tests/artifacts/datram-probe-sheik2/`
(the original `zelda_probe.json`/`sheik_probe.json` runs are POISONED — see note).

## LIVE HEADLINE (2 of 5 candidate groups LIVE):
- **farore_burst (s2/s3)** — 🟢 LIVE. Magenta poke recolored the entire Farore's
  Wind teleport-burst CORE (the yellow/orange ribbon spirals stayed yellow =
  model region, not ours). `datram-probe-zelda2/farore_burst-upb-f10.png`.
- **transform_flash (s6/s9)** — 🟢 LIVE, confirmed on BOTH forms. Green poke
  recolored the transform chest-flash core orb/ring on Zelda (downb) AND on Sheik
  (downb). The surrounding pink+blue sparkle STARS stayed put (separate element).
  `datram-probe-zelda2/transform_flash-downb-f04..18.png` +
  `datram-probe-sheik2/sheik_transform_shared-downb-f10,f18.png`.
- **nayru_crystal (s0/s1)** — ❌ DEAD. Magenta poke; the blue crystal + blue rim
  glow stayed fully BLUE. The crystal color lives in a MODEL-region block, not
  these ptcl operands. `datram-probe-zelda2/nayru_crystal-neutralb-f12,f20.png`.
- **ring_s7_blue (s7)** — ❌ DEAD (no attribution). Magenta poke; no change on
  neutralb (Nayru) or upb (Farore). Not the blue crystal rim; likely a
  model/subaction element or load-consumed.
- **ring_s8_pink (s8)** — ❌ DEAD on neutralb/upb (green poke, no change). OPEN
  LEAD: the pink sparkle STARS visible on the *transform* (both forms) are the
  most likely owner of s8 — but s8 was never poked on the transform move (out of
  boot budget). See open leads.

### Harness note (IMPORTANT for any re-probe)
Running Zelda's `downb` (Transform) morphs her into Sheik and **poisons every
subsequent experiment** — the fighter lands in `Sleep` and `safe_reset` (which
only recovers REBIRTH/REBIRTH_WAIT) can't recover it, so all later moves report
`MOVE FAILED (... state = Sleep)` with zero captures. Same on Sheik (her
`neutralb` needles / `upb` vanish leave Sleep). The FIX used here: `zelda_probe2`
orders the transform experiment LAST and restricts the ring experiments to
neutralb+upb only (never downb mid-sequence); `sheik_probe2` runs ONLY the
transform experiment (one move, no vanilla, nothing after). If effect_probe's
`safe_reset` ever learns to recover from Sleep (dizzy state), the original
combined specs become usable again.

## Sheik reachability for LIVE (important)

`ingame/char_select.py` gives Sheik her own external c_kind **0x13**
(`CKIND_NO_CELL = {"sheik": 0x13}`), and `effect_probe.py` resolves char via
`ckind()`. So **`sheik_probe.json` with `"char": "sheik"` should boot Sheik
directly** (memory-select 0x13), no down-B transform needed. If the solo-boot
engine rejects 0x13 (falls through to the cursor, which only reaches Zelda's
cell → then transforms via down-B post-match), LIVE must transform first. Try
direct 0x13 first; the moves driver's `downb` = Transform if fallback is needed.

## Structural findings (read first)

`python skinlab/ptcl_parse.py EfZdData.dat --models` → version 0x42,
**10 ptcl generators** (scripts 0,1,2,3,4[blank],5[blank],6,7,8,9 — 5 is
"same-as-previous"), `effect_id_start=17000` (0x4268), tex_bank@0x6A0,
**90 ptcl color operands** + 86 model-region blocks.

**gfx→script cross-ref (decomp `ftZelda/`, `ftSeak/`, `it/items/`, `ef/efsync.c`).**
The fighter/item passes a gfx_id to `efSync_Spawn`; the `efsync.c` dispatcher
remaps it to a global effect id. `0x4268`(=17000) is this bank's base, so
global `0x4268+N` = **EfZd ptcl script N**. Confirmed mappings:

| move (source) | fighter gfx | efsync case → global | EfZd script | notes |
|---|---|---|---|---|
| **Nayru's Love** (`ftZd_SpecialN` 1268 grnd / 1269 air) | 0x4F4 / 0x4F5 | →0x4268 / 0x4269 | **s0 / s1** | the reflect crystal (grounded/aerial variants) |
| **Farore's Wind** (`ftZd_SpecialHi` 1270 grnd / 1271 air) | 0x4F6 / 0x4F7 | →0x426A / 0x426B | **s2 / s3** | teleport burst (grnd/air) |
| **Transform** (`ftZd_SpecialLw` 1276 / 1277) | 0x4FC / 0x4FD | →0x426D(s5=blank→s4) / 0x4271(s9) | **s5→s4 / s9** | Zelda↔Sheik transform flash |
| **Sheik chain** (`ftSk_SpecialLw` 0x4FC / 0x4FD) | 0x4FC / 0x4FD | →0x426D / 0x4271 | **s5→s4 / s9** | SHARES transform's records |
| scripts 4, 6, 7, 8 (globals 0x426C/E/F/0x4270) | — | — | **s4,s6,s7,s8** | NO direct gfx caller → spawned by subaction event-data / lifetime-end chains (case 0x501→0x426E chains). The rich gradient rings. LIVE-attribute to Nayru/Farore/Transform. |

**Quarantine — routes to COMMON bank `EfCoData`, NOT EfZd (do NOT ship as
Zelda/Sheik layers):**
- Din's Fire ember (`itzeldadinfire.c` 1272/1273 → efsync 0x4F8/0x4F9 →
  common 0x6E / 0x1C8) — **common**.
- Din's Fire explosion (`itzeldadinfireexplode.c` 0x4FA → common 0x166) —
  **common**.
- Din's Fire charge glow (`ftZd_SpecialS` 1275=0x4FB → common 0x71) — **common**.
- Sheik needles (`ftSk_SpecialN` 1283=0x503 → common 0x6A) — **common**.
- Sheik/Zelda Farore-air companion (1285=0x505 → common 0x79) — **common**.
- Sheik Vanish (`ftSk_SpecialHi` 1284=0x504 → common 0x6D; 1285=0x505 →
  common 0x79) — **the vanish burst is COMMON, not EfZd** ⚠. So a Sheik-only
  vanish recolor is impossible via this file; flag for the EfCoData mission.

So the mission's headline targets split: **Nayru's crystals, Farore's teleport
burst, and the Transform flash ARE in EfZd** (mappable here); **Din's Fire (all
phases), Sheik needles, and Sheik Vanish are COMMON bank** (out of char scope).

**Reference-mod corroboration: NONE for the ptcl bank.** 15667 EfZd (same size,
clean diff) has 465 diff bytes but **0 in the ptcl bank (<0x6A0)** — all
texture/model. 14328 same. Rows rest on parser + decomp; LIVE confirms.

---

## `EfZdData.dat` — ptcl records (symbol `effZeldaDataTable`, id_start 17000)

Parser reports the **color-byte offset** (RGBA); opcode `CF <count>` is 2 bytes
before, EnvCol color at prim+7. Poke the listed offset directly.

### Nayru's Love (scripts 0/1) — ❌ DEAD
| layer_id | fmt | prim @ / env @ | vanilla prim / env | parser tag | LIVE verdict |
|---|---|---|---|---|---|
| nayru_ground | CF | 0x186 / 0x18D | FFFFFF / 06F406 | (s0,PRIMCOL,#0)/(s0,ENVCOL,#0) | **DEAD** — magenta poke, crystal stayed blue (model-region color). `nayru_crystal-neutralb-f12.png` |
| nayru_air | CF | 0x1EE / 0x1F5 | FFFFFF / 06F406 | (s1,PRIMCOL,#0)/(s1,ENVCOL,#0) | **DEAD** — same, no change |

### Farore's Wind (scripts 2/3) — 🟢 LIVE
| layer_id | fmt | prim @ / env @ | vanilla prim / env | parser tag | LIVE verdict |
|---|---|---|---|---|---|
| farore_ground_a | CF | 0x257 / 0x25E | 03860E / 035814 | (s2,PRIMCOL,#0)/(s2,ENVCOL,#0) | 🟢 LIVE (poked as a group w/ air; grnd not separately isolated — same script family, ship together) |
| farore_air_a | CF | 0x2B8 / 0x2BF | 0A7D3D / 001C8C | (s3,PRIMCOL,#0)/(s3,ENVCOL,#0) | 🟢 LIVE — upb burst core turned magenta. `farore_burst-upb-f10.png` |
| farore_air_b | CF | 0x2C5 (count5) | 0BC52D | (s3,PRIMCOL,#1) | 🟢 LIVE (part of the recolored burst core) |
| farore_air_c | CF | 0x2CC (count5) | 01757E | (s3,PRIMCOL,#2) | 🟢 LIVE (part of the recolored burst core) |

### Transform / burst family (scripts 6 & 9 — shared by Transform + Sheik chain) — 🟢 LIVE, both forms
| layer_id | fmt | prim @ / env @ | vanilla prim / env | parser tag | LIVE verdict |
|---|---|---|---|---|---|
| transform_s6_a | CF | 0x371 / 0x378 | 6D68FF / 000082 | (s6,PRIMCOL,#0)/(s6,ENVCOL,#0) | 🟢 LIVE — green poke recolored transform chest-flash core (Zelda + Sheik) |
| transform_s6_b | CF | 0x37E / 0x385 | FD676A / 8F0000 | (s6,PRIMCOL,#1)/(s6,ENVCOL,#1) | 🟢 LIVE (secondary of the same flash) |
| transform_s9_a | CF | 0x67B / 0x682 | 6D68FF / 000082 | (s9,PRIMCOL,#0)/(s9,ENVCOL,#0) | 🟢 LIVE — **byte-identical to s6_a** (6D68FF/000082); group per lesson 12 (verified equal) |
| transform_s9_b | CF | 0x688 / 0x68F | FD676A / 8F0000 | (s9,PRIMCOL,#1)/(s9,ENVCOL,#1) | 🟢 LIVE — **byte-identical to s6_b** (FD676A/8F0000); group |

### Gradient rings — scripts 7 & 8 (no direct gfx caller; subaction/chain spawn)
Long CF/EnvCol gradient ladders (12 fading steps each). These are the big
sparkle rings; owner move (Nayru vs Transform) is LIVE-pending. Recolor the
first non-zero prim of each and the env to attribute.
| layer_id | fmt | prim @ / env @ | vanilla prim / env | parser tag | LIVE verdict |
|---|---|---|---|---|---|
| ring_s7_head | CF | 0x3D4 / 0x3DB | FFFFFF / 0000FF | (s7,PRIMCOL,#0)/(s7,ENVCOL,#0) | ❌ DEAD (no attribution) — magenta poke, no change on Nayru(neutralb) or Farore(upb). NOT the blue crystal rim. |
| ring_s7_grad | CF | 0x3F3 / 0x3FA | 54DAFF / 0000FF | (s7,PRIMCOL,#2)/(s7,ENVCOL,#2) | ❌ DEAD (same) |
| ring_s8_head | CF | 0x525 / 0x52C | FFFFFF / FF0CBB | (s8,PRIMCOL,#0)/(s8,ENVCOL,#0) | ❌ DEAD on neutralb/upb (green poke). OPEN: likely the transform pink STARS — never poked on downb. |
| ring_s8_grad | CF | 0x544 / 0x54B | FFBFFF / 7F007F | (s8,PRIMCOL,#2)/(s8,ENVCOL,#2) | ❌ DEAD on neutralb/upb (same open lead) |

(Full 12-step ladders continue to 0x4CC (s7) and 0x61D (s8); the probe pokes the
heads + a couple gradient steps to attribute the ring, then WIRE can fan out the
whole ladder if it lands.)

## Shippable-now summary (for WIRE)

**Two LIVE extras to ship, both from `EfZdData.dat`. Nayru + both rings are DEAD
— do NOT wire them.**

### 1. `zelda_farore` (Farore's Wind teleport burst) — 🟢 ship
Semantic: the green teleport-burst CORE flash of Zelda's up-B (the yellow/orange
ribbon spirals are model region — NOT recolored). One script family (grnd s2 +
air s3); ship all 6 operands as one dual-color extra.
Per-record vanilla bytes (byte-verified):
| operand | offset | vanilla | anti-color used (verified) |
|---|---|---|---|
| s2 prim | 0x257 | 03860E | FF00FF |
| s2 env  | 0x25E | 035814 | FF00FF |
| s3 prim | 0x2B8 | 0A7D3D | FF00FF |
| s3 env  | 0x2BF | 001C8C | FF00FF |
| s3 prim1| 0x2C5 | 0BC52D | FF00FF |
| s3 prim2| 0x2CC | 01757E | FF00FF |
Grouping: `farore_c1` = the 4 prims (0x257,0x2B8,0x2C5,0x2CC) as a multi-RGB
list; `farore_c2` = the 2 envs (0x25E,0x2BF). Per lesson 12 the 6 vanilla bytes
all DIFFER, so wire each offset with its own vanilla string (no shared vanilla).
Anti-color for BOTH operands: vanilla is green/teal → magenta far.
AUDIT_HINTS: `zelda` move `upb` frames `4-18` (burst core is a brief bloom;
capture a WINDOW f4–f18, not a single frame).

### 2. `zelda_transform` (Transform flash, SHARED Zelda↔Sheik) — 🟢 ship
Semantic: the chest-flash core orb/ring of the Zelda↔Sheik transform. Fires on
BOTH forms' down-B transform (verified on Zelda downb AND Sheik downb). The pink
+ blue sparkle STARS around it are a separate element (NOT recolored). s6 and s9
are BYTE-IDENTICAL (verified) → one grouped layer is safe (lesson 12 satisfied).
Per-record vanilla bytes (byte-verified; s6 == s9):
| operand | offsets (s6 / s9) | vanilla | anti-color used (verified) |
|---|---|---|---|
| prim0 (core) | 0x371 / 0x67B | 6D68FF | 00FF00 |
| env0  (core) | 0x378 / 0x682 | 000082 | 00FF00 |
| prim1 (2ndary)| 0x37E / 0x688 | FD676A | 00FF00 |
| env1  (2ndary)| 0x385 / 0x68F | 8F0000 | 00FF00 |
Grouping: `transform_c1` = prim0+prim1 across s6 AND s9 (4 offsets, multi-RGB);
`transform_c2` = env0+env1 across s6 AND s9 (4 offsets). Because s6==s9, one
vanilla string per operand covers both records. Anti-color: prim0 vanilla is
periwinkle-blue → green far; env0 deep-blue → green far. (Ship a green-far reset
NOT blue.)
AUDIT_HINTS: `zelda` move `downb` frames `4-18` (transform flash window; brief).
The extra applies to both forms since they share the file — one extra_type,
label it as the transform flash (affects Zelda→Sheik and Sheik→Zelda).

### DEAD — do NOT wire
- `nayru_*` (s0/s1) — crystal color is model-region, not these operands.
- `ring_s7_*` (s7) — no visible attribution.
- `ring_s8_*` (s8) — dead on Nayru/Farore; possible transform-star owner but
  unconfirmed (open lead).

## Open leads
- **s8 pink stars on the transform**: the pink sparkle STARS visible during BOTH
  forms' transform are the strongest remaining candidate for s8 — but s8 was only
  poked on neutralb/upb (dead there), never on downb. A single targeted boot
  (poke 0x525/0x52C/0x544 + the rest of the s8 ladder on Zelda downb) would
  attribute it. Likewise s7 blue stars on the transform. Low priority — the
  stars are a secondary sparkle, not the headline flash.
- Attribute scripts 4/6/7/8 fully: s6/s9 done (transform). s4 unpoked.
- Sheik Vanish + needles are COMMON (EfCoData) — out of char scope, confirmed.
- Nayru crystal / s7 blue rim: colorable only via a MODEL-region block
  (86 blocks in this file) — a future model-block poke pass could reach it.
