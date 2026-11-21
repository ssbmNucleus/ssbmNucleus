# Jigglypuff effect map (MAP-LIVE done 2026-07-02)

Mission: extras campaign, Jigglypuff (`EfPrData.dat`). LIVE pass complete.
All offsets marker-verified against vanilla `storage/test-base/files/
EfPrData.dat`; semantics now carry a LIVE verdict. Probe specs:
`backend/probes/jigglypuff_probe.json` (main, 12 experiments) +
`backend/probes/jigglypuff_rest_probe.json` (tight-frame rest re-probe).
Char key = `jigglypuff` (aliases `puff`/`jiggs`; ckind 0x0F).
**No reference mods exist** (Reference-Mods-Index.md: "No usable effect mods
found for … Jigglypuff (sing)").

## ⚡ LIVE VERDICTS (2026-07-02) — read this first

Captures: `tests/artifacts/datram-probe-jigglypuff/` (main) +
`tests/artifacts/datram-probe-jigglypuff-rest/` (tight-frame rest).

| candidate | verdict | evidence |
|---|---|---|
| **Sing red note** (070707 @0x5444/0x5448) | 🟢 **CONFIRMED** | poked red→green; bottom note turned green, blue/green notes unchanged (`sing_notes_red-upb-f40`) |
| **Sing blue note** (070707 @0x5504/0x5508 + 42_48 @0x5574) | 🟢 **CONFIRMED** | poked blue→orange; upper-left note turned orange (`sing_notes_blue-upb-f40`) |
| **Sing green note** (070707 @0x55C4/0x55C8 + 42_48 @0x5634) | 🟢 **CONFIRMED** | poked green→magenta; right note turned magenta (`sing_notes_green-upb-f40`) |
| **ptcl scripts 2/3/4** (note-trail hypothesis) | 🔴 **DEAD** | poked on upb; notes + orange sing rings UNCHANGED, no attributable trail recolor (`ptcl_script2_note_orange-upb-f40`). Background ambient sparkle stars are present in vanilla too. |
| **ptcl script 0** (0xA0/0xA7 etc., rest-burst hypothesis) | 🔴 **DEAD** | poked on upb/sideb/neutralb AND downb (rest tight-probe); no visible change on Sing, Pound, Rollout, or Rest. Not a Jiggly special effect. |
| **Rest flower** (070707 @0x5684/0x5688 petals + 42_48 @0x56F4 center) | 🔴 **DEAD / non-rendering** (bag re-probe 2026-07-02) | Re-ran Rest (downb) WITH a DK bag at dx=4 (point-blank, Rest's hitbox is contact-range). Vanilla Rest **CONNECTED** — bag went `DamageFlyN` (HIT confirmed by sidecar), so this was a successful Rest hit, not a whiff. Swept downb f1-f40. The on-hit burst is a large **golden/orange radial FIRE flash + red spark rays** engulfing both Jiggly and the victim (Rest's signature fire hitspark) — **there is NO pink flower petal burst at ANY frame**, on Jiggly or the victim. The 070707 magenta petals @0x5684 (`A00095`/`820077`) + 42_48 center simply do not render in this vanilla NTSC 1.02 build. Pokes were marker-verified + readback-OK, so the offsets are structurally sound, but the geometry is never drawn. The poked rep itself desynced (vanilla Rest launched the 0%-bag off-stage → Rebirth halo by the poke rep, lesson 14) but the vanilla-hit control is conclusive: a successful Rest shows fire, not a flower. Captures: `tests/artifacts/datram-probe-jigglypuff-rest-bag/` (`vanilla-downb-f02/f04/f07` = fire burst, no petals). The "flower" is likely a Brawl-onward visual mis-attributed to Melee, or the model region carries dormant geometry the game never spawns. **Do NOT ship; do NOT bounce to EYEBALL — it is a confirmed non-render.** |

**Shippable now:** the three Sing notes (red/blue/green), each as its own
per-note-color layer so users can theme the trio individually.

## Structural findings (read before trusting any row)

`EfPrData.dat` (symbol `effPurinDataTable`, 26834 bytes) HAS a real **ptcl
bank**: `ParticleGroup@0x40`, version 0x42, `EffectIDStart = 11000`,
**5 generators** (scripts 0-4 = effect ids 11000-11004). Beyond the bank
(from ~0x5440) is the **model region** with note/flower geometry.

The special-move C code (`melee/src/melee/ft/chara/ftPurin/`) is almost silent
on effect spawns — only `ftPr_SpecialN.c` (Rollout) calls `efSync_Spawn(0x3FF)`
/ `efSync_Spawn(0x406)` and `ftPr_Init.c` calls `efSync_Spawn(1238)`, all
**common-bank** ids (< 11000, so EfCoData — see Quarantine). The Purin-bank
effects (11000-11004) and the note/flower geometry are spawned **data-driven
from subaction event scripts** (in the fighter `.dat`), which is why decomp is
quiet. Jiggly specials: SpecialN=Rollout, SpecialS=Pound, SpecialHi=Sing,
SpecialLw=Rest.

### The Sing notes + Rest flower are MODEL-REGION geometry (not ptcl)

The classic red/blue/green Sing notes and the Rest flower are **070707 vertex
pairs + a matching 42_48 material block** in the model region — each note has
BOTH. Marker-verified bytes:

All offsets below are marker-verified (see "Block format"). The 070707 note
colors and the 42_48 note-material diffuse do NOT sit at the same marker — they
are separate blocks. Verified diffuse offsets: 42_48 marker 0x5580 → block
0x5570 → diffuse `0000FF` @0x5574; marker 0x5640 → block 0x5630 → diffuse
`00FF00` @0x5634; marker 0x5700 → block 0x56F0 → diffuse `FFADFF` @0x56F4
(flower center, light-pink); markers 0x54C0 and 0x57A0 → white diffuse.

| 070707 marker | color1 @+4 | color2 @+8 | reading |
|---|---|---|---|
| 0x5440 | `FFFFFF` | **`FF0000`** | Sing **red** note (070707 pair) |
| 0x5500 | `FFFFFF` | **`0000FF`** | Sing **blue** note (070707 pair) |
| 0x55C0 | `FFFFFF` | **`00FF00`** | Sing **green** note (070707 pair) |
| 0x5680 | **`A00095`** | **`820077`** | **Rest FLOWER petals** (magenta) |

| 42_48 marker | block | diffuse @block+4 | reading |
|---|---|---|---|
| 0x5580 | 0x5570 | **`0000FF`** @0x5574 | blue note material |
| 0x5640 | 0x5630 | **`00FF00`** @0x5634 | green note material |
| 0x5700 | 0x56F0 | **`FFADFF`** @0x56F4 | **Rest flower center** (light-pink) |
| 0x54C0 | 0x54B0 | `FFFFFF` @0x54B4 | white note material (uncolored) |
| 0x57A0 | 0x5790 | `FFFFFF` @0x5794 | white note material (uncolored) |

(The reference doc `Effect-Offsets-Reference.md` already lists the three Sing
notes at 0x5440/0x5500/0x55C0 — my parse matches it exactly. The 4th 070707
(0x5680 magenta) and ALL the 42_48 material blocks are **new** findings not in
that doc.) **⚠️ LIVE must confirm which 42_48 material pairs with which note**
— there is a blue material (0x5574) and green material (0x5634) but no red
material block (red note may take its color only from the 070707 pair). The
flower center diffuse is `FFADFF` (light pink), not a pure yellow.

### Block format
- `070707`: marker `07 07 07 04` → color1 RGB @+4, color2 RGB @+8 (glow).
- `42_48` (HSD material): color block @marker−0x10; ambient RGBA @+0, **diffuse
  RGBA @+4 (diffuse dominates)**. Byte-verified: block 0x5570 =
  `80 80 80 FF 00 00 FF FF FF FF FF FF …` → diffuse `0000FF` @0x5574.
  Per lesson 12, WIRE must byte-recompute diffuse per marker (block = marker−
  0x10, diffuse = block+4) and split grouped keys when vanilla differs.

---

## `EfPrData.dat` — Sing (up-B) candidates

Sing spawns three musical notes (red/blue/green) that circle Jiggly. Solo-
visible (Sing puts nearby foes to sleep but the notes render regardless).

### Note GEOMETRY (070707 + 42_48 material)

| layer_id | fmt | offset | vanilla | hypothesis |
|---|---|---|---|---|
| sing_red_core | 070707 | 0x5444 | `FFFFFF` | red note core |
| sing_red_glow | 070707 | 0x5448 | `FF0000` | red note fill |
| sing_blue_core | 070707 | 0x5504 | `FFFFFF` | blue note core |
| sing_blue_glow | 070707 | 0x5508 | `0000FF` | blue note fill |
| sing_blue_mat | 42_48 | 0x5574 | `0000FF` (diffuse) | blue note material |
| sing_green_core | 070707 | 0x55C4 | `FFFFFF` | green note core |
| sing_green_glow | 070707 | 0x55C8 | `00FF00` | green note fill |
| sing_green_mat | 42_48 | 0x5634 | `00FF00` (diffuse) | green note material |

AUDIT_HINTS (sing): move=upb, note ring appears frames ~8-110 (Sing loops).
Forced anti-colors: red note→green, blue note→orange, green note→magenta
(per-operand, lesson 6/11). Probe pokes each note's core+glow+material.

### Note TRAIL sparkles (ptcl scripts 2/3/4)

Scripts 2/3/4 (texGrp 1) each carry prim `FFF8F5` (near-white) + a distinct
env — **orange `FF3B05`, green `1EC703`, blue `1109F3`** — almost certainly the
three colored note-trail particle puffs that match the red/green/blue note
geometry. CF secondary at colorpos+7 applies (lesson 3): expose `_c1`/`_c2`.

| layer_id | fmt | offset | vanilla | hypothesis |
|---|---|---|---|---|
| sing_trail_a_prim | CF-multi | 0x16D | `FFF8F5FF` | note-trail sparkle prim (orange env) |
| sing_trail_a_env | DF | 0x174 | `FF3B0500` | note-trail sparkle env (orange) |
| sing_trail_b_prim | CF-multi | 0x1FD | `FFF8F5FF` | note-trail sparkle prim (green env) |
| sing_trail_b_env | DF | 0x204 | `1EC70300` | note-trail sparkle env (green) |
| sing_trail_c_prim | CF-multi | 0x28D | `FFF8F5FF` | note-trail sparkle prim (blue env) |
| sing_trail_c_env | DF | 0x294 | `1109F300` | note-trail sparkle env (blue) |

(Parser tags: script2=(2,CF,0)+（2,DF,0); script3=(3,…); script4=(4,…). LIVE
must confirm scripts 2/3/4 belong to Sing vs Rollout/Pound — gfx→move narrows,
doesn't verify.)

---

## `EfPrData.dat` — Rest (down-B) candidates

Rest's on-self **FLOWER** burst is **solo-visible** (blooms on Jiggly's head
regardless of contact) — the best-verifiable candidate here.

| layer_id | fmt | offset | vanilla | hypothesis |
|---|---|---|---|---|
| rest_flower_petal1 | 070707 | 0x5684 | `A00095` | flower petals (magenta) |
| rest_flower_petal2 | 070707 | 0x5688 | `820077` | flower petals darker |
| rest_flower_center | 42_48 | 0x56F4 | `FFADFF` (diffuse) | flower center (light-pink) |

AUDIT_HINTS (rest): move=downb, flower blooms frames ~4-70 (on-self, no contact
needed). Forced anti-colors: petals→green, center→magenta. Probe pokes petals
on downb and center on downb.

**Rest BURST (the damaging ring):** the ptcl **script 0** (kind 0x1, texGrp 0)
carries prim `E3FFFFFF` + env `4E26FF` (blue-purple) with count-40 keyframes —
plausibly the rest damage ring / burst puff. But this could equally be a
Rollout or Pound effect. Probe pokes script 0 on BOTH downb and upb to
attribute. The rest burst hurtbox is on-self AoE (no bag needed).

| layer_id | fmt | offset | vanilla | hypothesis |
|---|---|---|---|---|
| ptcl0_prim | CF-multi | 0xA0 | `E3FFFFFF` | script-0 prim (rest burst? / rollout?) |
| ptcl0_env | DF | 0xA7 | `4E26FF00` | script-0 env (blue-purple) |
| ptcl0_prim2 | CF-multi | 0xB9 | `E3FFFFFF` | script-0 sustained prim |
| ptcl0_env2 | DF | 0xC0 | `4E26FF00` | script-0 sustained env |
| ptcl0_prim3 | CF-multi | 0xC8 | `E3FFFF00` | script-0 late prim |

---

## `EfPrData.dat` — Rollout (neutral-B) & Pound (side-B) — open leads

Rollout's charge swirl and Pound's forward streak have **no dedicated
Purin-bank script clearly attributable from bytes** — Rollout's C code spawns
common-bank `0x3FF`/`0x406` (EfCoData, quarantined). The Purin-bank scripts
2/3/4 are hypothesized as Sing trails above, but LIVE should also poke them on
`sideb`/`neutralb` to rule out Pound/Rollout ownership. If nothing in
`EfPrData` changes on Rollout/Pound, both are **common-bank/EfCoData** or use
the fighter model's own trail — route accordingly. Rollout charge swirl and
Pound streak are on-self / self-motion (solo-visible), NOT on-hit.

---

## Quarantine / shared-file findings (NEVER ship as Jiggly layers)

- **Common-bank (EfCoData) spawns from `ftPurin/`**: `efSync_Spawn(0x3FF)` and
  `efSync_Spawn(0x406)` (Rollout, `ftPr_SpecialN.c`), `efSync_Spawn(1238)`
  (`ftPr_Init.c`). All ids < 11000 → resolve to `EfCoData.dat`
  (`effCommonDataTable`, EffectIDStart=0, 592 generators). Route any
  Rollout/Init smoke/dust findings to `efcodata.md`, not here.
- **98-matrix blocks** (0x5820+): texanim/matrix tables, not RGB triples. The
  parser lists 3 (0x5820, 0x5909, 0x591E) plus more; never ship.
- The three white 42_48 blocks (0x54A0, 0x5780) with no color = uncolored note
  material (white); poke only if a note core needs it.

---

## Shippable-now summary (for WIRE)

ONE extra to ship: **`sing_notes`** (up-B) — three musical notes that circle
Jiggly during Sing. Keep the red/blue/green notes as **separate per-note-color
layers** so users can theme the trio individually (do NOT collapse into one
color). All 070707: `07 07 07 04` marker → color1 RGB @marker+4 (bright core),
color2 RGB @marker+8 (fill/glow). Byte-verified per-record vanilla:

| layer_id | fmt | offset | vanilla | verified semantic | LIVE anti-color used |
|---|---|---|---|---|---|
| sing_red_core  | 070707 | 0x5444 | `FFFFFF` | red note bright core | (paired w/ glow, note→green) |
| sing_red_glow  | 070707 | 0x5448 | `FF0000` | red note fill/glow | 🟢 poked green → red note went green |
| sing_blue_core | 070707 | 0x5504 | `FFFFFF` | blue note bright core | (paired) |
| sing_blue_glow | 070707 | 0x5508 | `0000FF` | blue note fill/glow | 🟢 poked orange → blue note went orange |
| sing_green_core| 070707 | 0x55C4 | `FFFFFF` | green note bright core | (paired) |
| sing_green_glow| 070707 | 0x55C8 | `00FF00` | green note fill/glow | 🟢 poked magenta → green note went magenta |

**42_48 note materials (optional, keep OFF the default ship):** blue material
diffuse `0000FF` @0x5574 (block 0x5570) and green material diffuse `00FF00`
@0x5634 (block 0x5630). These were poked TOGETHER with the 070707 pairs, so I
could NOT isolate their contribution — the note body recolored fully from the
070707 pair alone in every case, and there is **no red material block** (the red
note has only the 070707 pair). RECOMMENDATION: ship the 6 070707 records only
(core+glow per note). If the built preview shows the note's inner disk keeping
its vanilla hue, add the two material diffuses as `_mat` sub-layers per lesson
12 (byte-recompute diffuse = block+4 per record; they DIFFER: blue `0000FF` vs
green `00FF00`, so they are per-record keys, not a shared group).

**Editor grouping (`_c1`/`_c2` fan-out):** each note = a 2-record color pair
(core=`_c1`/white, glow=`_c2`/hue). Simplest UX: one color swatch per note that
drives the glow (`_c2`), with the core (`_c1`) staying white; or expose both.
Precedent: this is a 070707 pair like Fox laser center-line, not a CF-multi.

**AUDIT_HINTS (sing):** `move=upb`. Notes visible frames **~20-110** (Sing
loops; the notes are best-framed f40-70 — f8 is too early, notes still
spawning). Forced anti-colors (per-operand, lesson 6/11): red note→green,
blue note→orange, green note→magenta.

## Dead / not-shippable (do NOT wire)

- **ptcl scripts 0/2/3/4** — all DEAD (no attributable visible effect on any
  Jiggly special). Route nothing here.
- **Rollout / Pound** — no EfPrData ptcl changed on neutralb/sideb; their
  visuals are common-bank (EfCoData `0x3FF`/`0x406`) or the fighter model's
  own motion trail. Quarantine (see below); not a Jiggly char extra.
- **Rest flower** — 🔴 DEAD / non-rendering (bag re-probe 2026-07-02, see LIVE
  VERDICTS). A successful point-blank Rest (DK bag dx=4, bag → DamageFlyN) shows
  a golden/orange FIRE burst + red spark rays, NOT a pink flower — no petals at
  any frame on Jiggly OR the victim. The 070707 petal geometry @0x5684 is never
  drawn in this NTSC 1.02 build. Do NOT ship, do NOT bounce to EYEBALL.

## Open leads (deferred, not blocking the Sing ship)

1. ~~Rest flower~~ — 🔴 RESOLVED DEAD (bag re-probe 2026-07-02): a successful
   point-blank Rest shows a golden fire burst, not a flower; petal geometry
   never renders. Closed.
2. **Sing 42_48 material isolation** — poke ONLY 0x5574 / 0x5634 (not the
   070707 pair) to learn whether the material contributes to the note body.
