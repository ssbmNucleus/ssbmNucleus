# Luigi — effect color map (MAP-LIVE verified)

Status: **LIVE-POKED 2026-07-02.** Static draft (ptcl_parse inventory + decomp
efSync_Spawn cross-ref + reference-mod diff + marker verification) upgraded by a
MAP-LIVE poke pass judged by eyes. Captures:
`tests/artifacts/datram-probe-luigi/` (probe `backend/probes/luigi_probe.json`,
ckind 0x07, 9 experiments). Per-row verdicts recorded below; the Shippable-now
summary at the bottom is what WIRE fans out.

**Headline answers to STATIC's open questions:**
- **Q2 (fireball green source):** PlLg article colors DO recolor the fireball
  body/aura — poking the PlLg group (0xF42C prim + 0xF430 env + 0xF3BC/0xF3C0 +
  0xF4CC) turned the fireball core/aura MAGENTA while the smoke trail stayed
  green. NOT texture-driven. ✅ VERIFIED.
- **Q1 (scripts 9/10/11):** none of them is the tornado swirl (that's the
  tornado_07/42 EfLgData model blocks, both verified magenta). Scripts 9/10
  (spark_yellow) produced NO visible change on up-B or down-B; script 11
  (spark_blue) produced NO change on taunt, side-B, or up-B. Melee's Luigi
  up-B coin/sweetspot spark is an **on-hit** effect (Super Jump Punch draws its
  coin-spark only on contact), and Luigi's taunt has **no spark GFX** at all.
  → 9/10/11 are on-hit / no-solo-GFX, NOT verifiable solo. Flagged on-hit-pending.
- **Taunt spark colorability:** Luigi's taunt draws no GFX solo → nothing to
  color. spark_blue_s11 is the only candidate and it is on-hit-pending.
- **Side-B misfire:** no misfire occurred (RNG); normal Green Missile draws only
  a white smoke trail (common-bank, not an EfLgData layer). Misfire still pending.

- Effect file: `storage/test-base/files/EfLgData.dat`
  (`effLuigiDataTable`, EffectTable@0x20, ParticleGroup@0x60, version 0x42,
  12 generators, **effect_id_start = 18000 (0x4650)**, tex_bank@0x640).
- Player/article file: `storage/test-base/files/PlLg.dat` (fireball article +
  fireball color live HERE, not in EfLgData — the neutral-B fireball is an
  *item*, `It_Kind_Luigi_Fire`, spawned by `it_802C01AC` in `ftLg_SpecialN.c`).
- Decomp: `src/melee/ft/chara/ftLuigi/` in doldecomp/melee.

## Decomp move → spawn cross-reference

| Move | File | Spawn | gfx_id | Note |
|---|---|---|---|---|
| Neutral-B fireball (hand) | `ftLg_SpecialN.c:155` | `efSync_Spawn(1287,…L1stNb)` | 1287 (0x507) | **common bank** (<18000) — hand GFX in EfCoData, not EfLgData |
| Neutral-B fireball (item) | `ftLg_SpecialN.c` | `it_802C01AC(…It_Kind_Luigi_Fire)` | item | fireball body/aura color lives in **PlLg.dat** article |
| Fireball item impact | `itluigifireball.c:97,99` | `efAsync_Spawn(…1288)` / `…1202` | 1288 (0x508) / 1202 (0x4B2) | **common bank** |
| Side-B green missile | `ftLg_SpecialS.c:466` | `efSync_Spawn(0x50A,…HipN)` | 0x50A (1290) | **common bank** — remove/launch GFX |
| Down-B tornado | `ftLg_SpecialLw.c:65` | `efSync_Spawn(0x509,…)` | 0x509 (1289) | **common bank** |
| Up-B coin | `ftLg_SpecialHi.c` | (no efSync; coin is `itcoin.c` item) | — | coin sparkle/fire has no source anchor |
| Taunt kick spark | (generic appeal anim) | none in decomp | — | animation-embedded GFX if it exists |

**Key finding:** every `efSync_Spawn`/`efAsync_Spawn` id in the Luigi source is
< 18000, i.e. resolves into the **common effect bank (EfCoData)**, NOT
EfLgData. The 12 local EfLgData scripts (gfx 18000–18011) and the colored
07/42/98 model blocks are spawned by **article GFX events baked into animation
data**, which the decomp does not spell out as constants. So move→script here
is assigned by (a) the old-cite semantics, (b) primcol hue, and (c) tex-group
clustering — and MUST be confirmed by LIVE poke. Do not trust the naming below
without a capture.

## Reference-mod diff (post 15437 "Luigi Fireball - Trollface", PlLg.dat)

**Same-size + identical md5** (`768c69be269294f9a2c45f0adcc10fd6`, 172308 bytes)
vs our vanilla `PlLg.dat`. The mod is byte-identical to base → it is a
texture-only trollface swap with **zero color-byte edits**. Per lesson 4 this
yields **no offset candidates**. No usable reference-mod corroboration for
Luigi exists in the backup.

---

## Candidate group A — Neutral-B fireball aura (PlLg.dat article)

The fireball body color lives in the article inside `PlLg.dat`, not EfLgData.
PlLg.dat is not a ptcl bank (ParticleGroup version 0x3DCC → parser rejects it),
so offsets are hex-marker-verified by hand, not by ptcl_parse. Base fireball
reads mostly orange in these bytes but the **42_48 PrimCol `00 FF 00` at
0xF42C dominates → the visible green**. Old-doc cites confirmed marker-exact.

| layer_id | format | offsets (marker-verified) | vanilla bytes | (script,opcode,ord) | verified semantic |
|---|---|---|---|---|---|
| fb_aura_07 | 070707 | marker 0xF3B8; col1 0xF3BC=`FF6600`, col2 0xF3C0=`FF3300` | `07 07 07 04 FF 66 00 00 FF 33 00` | model-block (PlLg, no ptcl script) | 🟢 fireball aura inner/outer (part of the recolored core group) |
| fb_aura_42 | 42_48 | block 0xF428; prim 0xF42C=`00FF00`, env 0xF430=`FFFFFF` | `80 80 80 FF 00 FF 00 FF FF FF FF FF 3F …42 48` | model-block (PlLg) | 🟢 fireball aura — the dominant green (PrimCol=00FF00) |
| fb_body_42 | 42_48 | block 0xF4C8; prim 0xF4CC=`FFFFFF`, env 0xF4D0=`FFFFFF` | `00 00 00 FF FF FF FF FF FF FF FF FF 00 …42 48` | model-block (PlLg) | 🟢 fireball core body (in the recolored group) |

**LIVE VERDICT (🟢 VERIFIED as a group):** poking all 5 PlLg offsets to magenta
turned the fireball **body/core aura magenta** (`fb_aura_pllg-neutralb-f24.png`,
`-f34.png`), smoke trail unaffected. Answers Q2 — fireball color IS in the PlLg
article, NOT texture. The 5 offsets were poked together; a follow-up single-poke
boot would isolate which dominates (fb_aura_42 prim @0xF42C is the STATIC lead),
but the whole group is confirmed fireball-aura color. Flag for EYEBALL: confirm
which sub-offset to expose as the primary editor color vs secondary.

AUDIT_HINTS: `neutralb:8-40` — anti-color **magenta `FF00FF`** (fireball body is
green; magenta is opposite). Verified capture: `fb_aura_pllg-neutralb-f24.png`.

## Candidate group B — Neutral-B fireball smoke/particles (EfLgData ptcl scripts)

CF/PrimCol+EnvCol records in the ptcl bank. Old doc labeled these "hand smoke",
"smoke trail", "wall collision", "particles". Green primcols (26FF43, 02FD02,
16FD22, 1ADC24) confirm fireball-family. Per lesson 3, each PrimCol has a
paired EnvCol (the `+7`/next-opcode color) dominating sustained tint — expose
both as `_c1`/`_c2`. Offsets below are the **parser's exact** PRIMCOL/ENVCOL
positions (old CF cites drift ~2 bytes low — do not use them).

| layer_id | fmt | prim off / env off | vanilla prim / env | (script,opcode,ord) | verified semantic |
|---|---|---|---|---|---|
| fb_smoke_s0a | CF-multi | 0xFF / 0x106 | `26FF43` / `2ABA4E` | (0, CF/DF, 1) | 🟢 fireball hand/spawn smoke puff |
| fb_smoke_s0b | CF-multi | 0x10C / 0x113 | `149C2D` / `0C5419` | (0, CF/DF, 2) | 🟢 fireball hand/spawn smoke puff (count=7) |
| fb_smoke_s3 | CF-multi | 0x26D / 0x281 | `02FD02` / `052E15` | (3, CF/DF, 0/1) | 🟢 fireball spawn smoke (in the recolored hand puff) |
| fb_smoke_s4 | CF-multi | 0x2DD / 0x2F1 | `16FD22` / `0A4F12` | (4, CF/DF, 0/1) | 🟢 fireball spawn smoke (in the recolored hand puff) |
| fb_dust_s5 | CF-multi | 0x352 / 0x372 | `BDFDBB` / `31F83B` | (5, CF/DF) | 🟢 fireball smoke/dust (in the recolored group) |
| fb_particle_s6 | CF-multi | 0x3FE / 0x40E | `1ADC24` / `7CFF70` | (6, CF/DF) | 🟢 fireball particles (in the recolored group) |
| fb_smoke_s1 | CF-multi | 0x186 / 0x18D (+0x194/0x19B/0x1A7/0x1AE/0x1B4/0x1BB) | `93A394` / `22AB0A` … | (1, CF/DF, 0–3) | 🟢 **STRONG** fireball spawn smoke puff (was flagged "weak grey/olive lead" — it is a dominant fireball smoke layer) |

**LIVE VERDICT (🟢 VERIFIED as a group):** the fb_smoke_particles poke turned the
**hand-spawn smoke puff magenta** (`fb_smoke_particles-neutralb-f24/f34.png`);
the fb_smoke_s1_lead poke turned it a **strong bright magenta**
(`fb_smoke_s1_lead-neutralb-f24.png`) — script 1 is a real, dominant fireball
smoke layer, NOT the "weak grey/olive lead" STATIC guessed. In both cases the
*traveling* fireball trail (further from the hand) stayed green → that trailing
smoke is a separate source (likely common-bank; quarantined). These EfLgData
scripts color the **hand/spawn burst**.

AUDIT_HINTS: `neutralb:8-45` — anti-color **magenta `FF00FF`** (smoke is green).
Verified captures: `fb_smoke_particles-neutralb-f34.png`,
`fb_smoke_s1_lead-neutralb-f24.png`.

## Candidate group C — Down-B tornado (EfLgData 07/42 model blocks)

Old cites named these tornado layers; hues (pale yellow `FFFFB2`/`FFFFCC`,
white finish `FFFFD0`) match a spinning yellow-white tornado. Marker-exact.

| layer_id | fmt | col1 off / col2 off | vanilla col1 / col2 | hypothesized semantic |
|---|---|---|---|---|
| torn_outer | 070707 | 0x11A80 / 0x11A84 | `FFFFB2` / `FFB200` | tornado outer swirl |
| torn_upper | 070707 | 0x11B4C / 0x11B50 | `FFFFB2` / `FFCC00` | tornado upper |
| torn_inner1 | 070707 | 0x11C18 / 0x11C1C | `FFFFE5` / `FFFF00` | tornado inner side 1 |
| torn_inner2 | 070707 | 0x11CE4 / 0x11CE8 | `FFFFCC` / `FFFF00` | tornado inner side 2 |
| torn_under | 070707 | 0x11DB0 / 0x11DB4 | `FFFFCC` / `FFB200` | tornado underneath |
| torn_outer_fin | 42_48 | prim 0x11AF0 / env 0x11AF4 | `FFFFD0` / `FFFFFF` | tornado outer ring finish |
| torn_fin | 42_48 | prim 0x11BBC / env 0x11BC0 | `FFFFD0` / `FFFFFF` | tornado finish |
| torn_fin_s1 | 42_48 | prim 0x11C88 / env 0x11C8C | `FFFFD0` / `FFFFFF` | tornado finish side 1 |
| torn_fin_s2 | 42_48 | prim 0x11D54 / env 0x11D58 | `FFFFD0` / `FFFFFF` | tornado finish side 2 |
| torn_below | 42_48 | prim 0x11E20 / env 0x11E24 | `FFFFE3` / `FFFFFF` | tornado below Luigi |

**LIVE VERDICT (🟢 VERIFIED):**
- `tornado_07` (all 10 offsets) → tornado swirl AND ground ring turned **magenta**
  (`tornado_07-downb-f14.png`). Both the horizontal swirls around Luigi's arms
  and the ground ring recolored.
- `tornado_42_finish` (all 10 offsets) → the tornado **ring/dissipation finish**
  turned magenta — subtle at peak swirl but clear on the trailing/ground ring
  (`tornado_42_finish-downb-f14.png` ground ring pink,
  `tornado_42_finish-downb-f24.png` residual ring purple vs vanilla white
  `vanilla-downb-f24.png`).

AUDIT_HINTS: `downb:1-50` (Luigi Cyclone) — anti-color **magenta `FF00FF`**
(tornado is white/pale-yellow; magenta is far from that). Note torn 07-block
col2 sits at col1+4 (marker+8), separator `00` at marker+7. Verified captures:
`tornado_07-downb-f14.png`, `tornado_42_finish-downb-f24.png`.

## Candidate group D — Neutral-B hand ring (EfLgData 42_48)

| layer_id | fmt | prim off / env off | vanilla prim / env | verified semantic |
|---|---|---|---|---|
| hand_ring_42 | 42_48 | prim 0x11260 / env 0x11264 | `66FF99` / `FFFFFF` | 🟢 ring/portal around hand at fireball spawn |
| hand_ring_07 | 070707 | col1 0x111F0 / col2 0x111F4 | `CCFFE5` / `19B200` | 🟢 neutral-B hand ring (part of the recolored ring) |

**LIVE VERDICT (🟢 VERIFIED):** the fb_hand_ring poke turned the **oval ring/portal
at Luigi's hand** magenta at fireball spawn (`fb_hand_ring-neutralb-f24.png`
shows a bright magenta portal ring); the green fireball flame is a separate
layer and stayed green.

AUDIT_HINTS: `neutralb:1-20` — anti-color **magenta `FF00FF`**. Verified capture:
`fb_hand_ring-neutralb-f24.png`.

## Candidate group E — up-B coin / side-B missile / taunt spark (OPEN, no anchor)

Local ptcl scripts 9/10/11 have **no decomp anchor** (all move efSync ids are
common-bank). Assigned by hue + tex-group. LIVE must poke each while performing
the move and watch.

| layer_id | fmt | prim off / env off | vanilla prim / env | tex/kind | verdict |
|---|---|---|---|---|---|
| spark_yellow_s9 | CF-multi | 0x536 / 0x53D (+0x547 count=4) | `FFCE0A` / `C70505` | grp4 kind 0x420102 | ⚪ DEAD — up-B contact spark unchanged on a bag (not the SJP coin) |
| spark_yellow_s10 | CF-multi | 0x5A6 / 0x5AD (+0x5B3 count=8) | `F7FF0A` / `D73706` | grp4 kind 0x420102 | ⚪ DEAD — same |
| spark_blue_s11 | CF-multi | 0x60A / 0x611 (+0x617 count=4) | `B5F6FF` / `0C17D7` | grp5 kind 0x400100 | 🟢 **VERIFIED = on-hit IMPACT SPARK** (colors the inner burst of any melee-hit contact flash) |

**LIVE VERDICT — resolved by the punching-bag pass 2026-07-02**
(`luigi_onhit_probe.json`, captures `tests/artifacts/extras-audit/Luigi-sparks-bag/`,
DK bag dx=6). up-B/fair/nair all landed clean Damage* hits (DamageN1 / DamageAir3):
- **spark_blue_s11 (0x60A/0x611/0x617) = 🟢 VERIFIED on-hit impact spark.** Poked
  RED (prim FF0000 / env FFFF00). On fair AND nair contact, the inner jagged
  burst of the melee-hit flash turned **RED** — a burst that is ABSENT in vanilla
  (pixel-diff at the impact frame: `vanilla-fair-f08` red≈0 vs `spark_blue_s11-fair-f08`
  red≈1400; `vanilla-nair-f04` red=0 vs poked=3022). The surrounding white/yellow
  rays + glow (common-bank) stay unchanged; s11 colors ONLY the small inner
  contact burst. **SHIPPABLE** as `luigi_hitspark`. This is a real Luigi on-hit
  layer (grp5, not common-bank).
- **spark_yellow_s9 / s10 = ⚪ DEAD.** Poked blue/cyan; the up-B (Super Jump Punch)
  on-contact spark was UNCHANGED (vanilla already has a blue-white contact spark +
  green fire; the poke added no cyan — pixel counts identical vanilla vs poked at
  every up-B frame). The SJP coin/contact spark is common-bank, not s9/s10. Do
  NOT ship these as `luigi_upb_coin`.

AUDIT_HINTS (deferred until on-hit verified):
- spark_yellow_s9/s10 (up-B coin, on-hit): anti-color **blue `0000FF`**.
- spark_blue_s11 (impact spark, on-hit): anti-color **red `FF0000`**.
- side-B misfire (random RNG; no misfire occurred this pass): the larger misfire
  flame may add layers — still **LIVE-pending-multiple-attempts**. Normal missile
  flame/trail is common-bank (gfx 0x50A), not an EfLgData layer.

## 98-matrix / texanim blocks (quarantine — NOT color layers)

Parser reports 9 `98matrix` blocks (texanim/matrix data at 0xD4F7, 0x1131C,
0x1147B, 0x11EE0, 0x11FC0, 0x12060, 0x120C0, 0x120E0, 0x12893). These are
matrix/texanim tables, not RGB triples — do **not** ship as color layers.

## Open leads (post-LIVE)

1. ~~Which of scripts 9/10/11 is up-B coin / tornado spark / side-B / taunt~~ →
   RESOLVED: none is the tornado (that's the model blocks). 9/10/11 are on-hit
   sparks with no solo GFX → punching-bag pass.
2. ~~Fireball green: PlLg article vs texture~~ → RESOLVED: PlLg article recolors
   it (verified). Remaining EYEBALL micro-question: which PlLg sub-offset to
   expose as the editor's primary color (fb_aura_42 prim @0xF42C is the lead).
3. Side-B misfire (random) still pending — no misfire rolled this pass.
   LIVE-pending-multiple-attempts.
4. ~~Taunt kick spark existence~~ → RESOLVED: no taunt spark GFX drawn solo;
   spark_blue_s11 is on-hit-pending.
5. Common-bank (EfCoData) shared GFX — quarantined below.

## Common-bank / shared-file quarantine (do NOT ship as Luigi layers)

- Fireball hand-cast GFX + fireball impact (gfx 1287 / 1288 / 1202), tornado
  (0x509), Green Missile (0x50A) — every `efSync/efAsync` id in Luigi source is
  <18000 → resolves into **EfCoData** (common bank). The visible fireball
  *traveling trail* and the *normal missile smoke trail* both stayed green/white
  under all EfLgData pokes → they live in the common bank, not EfLgData.
  Route to any EfCoData mapping mission.
- 98-matrix/texanim blocks (0xD4F7, 0x1131C, 0x1147B, 0x11EE0, 0x11FC0, 0x12060,
  0x120C0, 0x120E0, 0x12893) — matrix/texanim tables, not RGB. Never ship.

---

# Shippable-now summary (for WIRE)

Five verified color groups, all EfLgData/PlLg, all confirmed by live magenta
poke. Spark groups (9/10/11) are held for the punching-bag pass — do NOT wire.
Anti-colors are per-operand (lesson 11): fireball/tornado effects are green /
pale-yellow-white respectively, so **magenta `FF00FF`** is a valid far anti-color
for every shippable group (PrimCol and EnvCol operands alike here are green- or
white-family, never magenta-family).

## Proposed extra 1 — `luigi_fireball` (neutral-B fireball color)

Groups the fireball body/aura + hand-spawn smoke + hand ring into ONE extra
(they all recolor together as "the green fireball"). Two logical colors for a
`_c1`/`_c2` dual-color editor: **c1 = fireball body/aura**, **c2 = smoke/glow**.

**Target file: `PlLg.dat` (article — body/aura):**

| layer | fmt | prim/col1 off | env/col2 off | vanilla prim/col1 | vanilla env/col2 | tag | → editor |
|---|---|---|---|---|---|---|---|
| fb_aura_42 | 42_48 | 0xF42C | 0xF430 | `00FF00` | `FFFFFF` | (PlLg model-block, 42/48) | c1 (dominant green) |
| fb_aura_07 | 070707 | 0xF3BC | 0xF3C0 | `FF6600` | `FF3300` | (PlLg model-block, 07) | c1 |
| fb_body_42 | 42_48 | 0xF4CC | 0xF4D0 | `FFFFFF` | `FFFFFF` | (PlLg model-block, 42/48) | c1 |

**Target file: `EfLgData.dat` (hand-spawn smoke + hand ring):**

| layer | fmt | prim off | env off | vanilla prim | vanilla env | (script,opcode,ord) | → editor |
|---|---|---|---|---|---|---|---|
| fb_smoke_s1 | CF-multi | 0x186 | 0x18D | `93A394` | `22AB0A` | (1,CF/DF,0) | c2 (strong smoke) |
| fb_smoke_s1 (cont) | CF-multi | 0x194 | 0x19B | … | … | (1,CF/DF,1) | c2 |
| fb_smoke_s1 (cont) | CF-multi | 0x1A7 | 0x1AE | … | … | (1,CF/DF,2) | c2 |
| fb_smoke_s1 (cont) | CF-multi | 0x1B4 | 0x1BB | … | … | (1,CF/DF,3) | c2 |
| fb_smoke_s0a | CF-multi | 0xFF | 0x106 | `26FF43` | `2ABA4E` | (0,CF/DF,1) | c2 |
| fb_smoke_s0b | CF-multi | 0x10C | 0x113 | `149C2D` | `0C5419` | (0,CF/DF,2) | c2 |
| fb_smoke_s3 | CF-multi | 0x26D | 0x281 | `02FD02` | `052E15` | (3,CF/DF) | c2 |
| fb_smoke_s4 | CF-multi | 0x2DD | 0x2F1 | `16FD22` | `0A4F12` | (4,CF/DF) | c2 |
| fb_dust_s5 | CF-multi | 0x352 | 0x372 | `BDFDBB` | `31F83B` | (5,CF/DF) | c2 |
| fb_particle_s6 | CF-multi | 0x3FE | 0x40E | `1ADC24` | `7CFF70` | (6,CF/DF) | c2 |
| hand_ring_42 | 42_48 | 0x11260 | 0x11264 | `66FF99` | `FFFFFF` | (EfLgData model-block) | c1 or c2 (ring) |
| hand_ring_07 | 070707 | 0x111F0 | 0x111F4 | `CCFFE5` | `19B200` | (EfLgData model-block) | c1 or c2 (ring) |

`AUDIT_HINTS`: `luigi:neutralb:8-40 anti FF00FF`
(fireball body — capture `fb_aura_pllg-neutralb-f24.png`)

## Proposed extra 2 — `luigi_cyclone` (down-B tornado color)

Single-color extra (all pale-yellow/white → one editor color). Target file:
`EfLgData.dat`.

| layer | fmt | col1/prim off | col2/env off | vanilla col1/prim | vanilla col2/env |
|---|---|---|---|---|---|
| torn_outer | 070707 | 0x11A80 | 0x11A84 | `FFFFB2` | `FFB200` |
| torn_upper | 070707 | 0x11B4C | 0x11B50 | `FFFFB2` | `FFCC00` |
| torn_inner1 | 070707 | 0x11C18 | 0x11C1C | `FFFFE5` | `FFFF00` |
| torn_inner2 | 070707 | 0x11CE4 | 0x11CE8 | `FFFFCC` | `FFFF00` |
| torn_under | 070707 | 0x11DB0 | 0x11DB4 | `FFFFCC` | `FFB200` |
| torn_outer_fin | 42_48 | 0x11AF0 | 0x11AF4 | `FFFFD0` | `FFFFFF` |
| torn_fin | 42_48 | 0x11BBC | 0x11BC0 | `FFFFD0` | `FFFFFF` |
| torn_fin_s1 | 42_48 | 0x11C88 | 0x11C8C | `FFFFD0` | `FFFFFF` |
| torn_fin_s2 | 42_48 | 0x11D54 | 0x11D58 | `FFFFD0` | `FFFFFF` |
| torn_below | 42_48 | 0x11E20 | 0x11E24 | `FFFFE3` | `FFFFFF` |

07-block note: col2 sits at col1+4 (marker+8), separator `00` at marker+7.

`AUDIT_HINTS`: `luigi:downb:1-50 anti FF00FF`
(tornado swirl+ring — captures `tornado_07-downb-f14.png`,
`tornado_42_finish-downb-f24.png`)

## Punching-bag pass RESULTS (2026-07-02)

### Proposed extra 3 — `luigi_hitspark` (on-hit impact spark) — 🟢 VERIFIED, SHIPPABLE

spark_blue_s11 colors the inner burst of Luigi's melee-hit contact flash (verified
on fair + nair with a DK bag). Single conceptual color; fmt `CF-multi` (prim @marker,
env @+7 per lesson 3). Target `EfLgData.dat`.

| layer | fmt | prim off | env off | vanilla prim | vanilla env | note |
|---|---|---|---|---|---|---|
| hitspark_s11 | CF-multi | 0x60A | 0x611 | `B5F6FF` | `0C17D7` | + count-record @0x617 (prim only, cnt=4) |

`AUDIT_HINTS`: `luigi:fair:8 anti FF0000` (or nair:4 — impact frame). Anti-color
**red `FF0000`** (vanilla is pale-blue/blue). Grouping: one `_c1`/`_c2` (prim=core,
env=glow). Verified captures: `spark_blue_s11-fair-f08.png`, `spark_blue_s11-nair-f04.png`.
This is a generic on-hit spark — it appears on ANY connecting attack, so the
"Luigi impact spark color" reads as a subtle Luigi flavor on every hit.

### ⚪ DEAD — do NOT wire

- `luigi_upb_coin` — spark_yellow_s9 (0x536/0x53D/0x547) + s10 (0x5A6/0x5AD/0x5B3):
  the SJP on-contact spark is common-bank; s9/s10 produced no change on a bag. DEAD.
- Side-B misfire flame — LIVE-pending-multiple-attempts (no misfire rolled). Still open.

## Counts

- **Verified 🟢:** 6 groups (fireball aura/PlLg, fireball smoke, hand ring,
  tornado swirl, tornado finish, **on-hit impact spark s11**) → 3 shippable extras
  (`luigi_fireball`, `luigi_cyclone`, `luigi_hitspark`).
- **⚪ DEAD (punching-bag 2026-07-02):** spark_yellow_s9/s10 (up-B coin candidate)
  — SJP contact spark is common-bank, not these records.
- **Pending (RNG):** side-B misfire.
- **Quarantined:** common-bank fireball trail/hand-cast/impact + missile trail +
  tornado GFX; 9 texanim blocks.
