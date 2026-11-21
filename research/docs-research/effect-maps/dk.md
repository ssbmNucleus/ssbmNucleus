# Donkey Kong effect map (LIVE-JUDGED 2026-07-02)

Mission: extras campaign, DK (`EfDkData.dat`). LIVE pass complete —
`backend/probes/dk_probe.json` + `dk_bag_probe.json` run + judged. Captures:
`tests/artifacts/datram-probe-dk/` and `…-dk-bag/`. Char key = `dk`.

## LIVE VERDICTS (headline) — DK ships NOTHING from this bank

Every DK effect color in `EfDkData.dat` is a **model-region material block**
whose visible effect is a WHITE additive texture (wind wisp / ground dust) that
overrides the material RGB — the Bowser-fire / spin-kong texture-dominance
pattern. All three probe groups are dead as visible color layers:

- 🔴 **spinkong_swirl_blue (0xD108-0xDB18)** — DEAD. Spinning Kong's trail +
  puff clouds render WHITE/grey (textured wisp) across all frames f08-f60;
  magenta poke of the full 14-offset blue series changed nothing. The name
  "blue swirl" is a misnomer — the swirl is white regardless of the blue
  material bytes. (Resolves the STATIC "biggest open question": neither the
  giant-punch charge nor the spin trail is a colorable blue swirl.)
- 🔴 **giantpunch_model_white99 (0xB124/0xB1C4/0xB3A4/0xB444)** — DEAD. DK's
  giant punch has NO visible charge glow (charge is stored silently; the
  fully-charged f160 frame has zero GFX). The only visible GFX is the white
  wind-up ground dust at f20, which stayed white under the magenta poke. The
  charge swirl is not in these blocks (and not visible at all in vanilla).
- 🟡 **downb_slap_blue (0x7D20/0x806C)** — HARNESS-BLOCKED / likely dead. The
  bag confirmed hand-slap CONNECTS (DamageFlyTop), but vanilla hand-slap shows
  only white ground dust + the generic pink EfCoData hitspark — NO blue
  shockwave ring. The poked-with-bag run couldn't complete (DK knocked into
  DownStandD, safe_reset can't recover post-knockback — lesson 9/14 territory).
  No blue ring exists in vanilla to recolor; treat as dead unless a future
  probe isolates a distinct ground-ring GFX.

DK is **bankless** with no ptcl records, so there is no CF-puff path like
Bowser's flame. Nothing here is shippable. STATIC structural notes retained
below.

---

Original STATIC draft. All offsets marker-verified against vanilla
`storage/test-base/files/EfDkData.dat`. Probe spec: `backend/probes/dk_probe.json`.
Char key = `dk` (`ingame/char_select.py`).

## Structural findings (read before trusting any row)

**DK has NO ptcl (particle) bank** (bankless, like Ness). `EfDkData.dat`
(symbol `effDonkeyDataTable`) — the `SBM_EffectTable` root is at data-section
start 0x20, and its `Particles` pointer is `0x00000000`. `ptcl_parse.py
--models` crashes/returns 0 (its model scan starts at `bank_end` = EOF for a
bankless file). Scanning `scan_model_colors(data, 0x20)` from the data-section
start instead finds **99 model-region blocks** (15 `070707`, 31 `4248`,
53 `98-matrix`). Every DK effect color is a **model-region block** in the
`EffectTable.Models[]` JOBJ trees, not a CF/PrimCol record.

**The EffectTable is an array of `SBM_EffectModel` (0x14 stride) starting at
0x20.** Fields per entry: `+0 particles(0)`, `+8 float scale`, `+0xC JOBJ ptr`,
`+0x10 anim`, matanim. `EffectIDStart = 0x1F40 = 8000` (from the `efsync.c`
switch mapping DK's small gfx_ids to real ids). Model index = id − 8000.

**Move → model cross-ref (from `efSync_Spawn` in
`melee/src/melee/ft/chara/ftDonkey/` + the `efsync.c` switch remap):**

| fighter call | gfx_id | efsync case → real id | model idx | move |
|---|---|---|---|---|
| `ftDk_SpecialLw` ground slap | 1222 (0x4C6) / 1223 (0x4C7) | → 0x1F40 / 0x1F41 | **0 / 1** | Hand Slap (down-B) |
| `ftDk_SpecialN` giant punch | 1224 (0x4C8) / 1225 (0x4C9) | → 0x1F42 / 0x1F43 | **2 / 3** | Giant Punch (neutral-B) |
| `ftDk_SpecialHi` spinning kong | 1226 (0x4CA) | → 0x1F44 | **4** | Spinning Kong (up-B) |
| `ftDk_SpecialLw` (efAsync) | 1228 (0x4CC) | → 0x1F46 | **6** | down-B secondary |

Model table (JOBJ / anim / matanim), 0x14-stride from 0x20:
- Model 0/1 (Hand Slap, down-B): jobj @0x70E8, extent ~0x70E8-0x8C68
- Model 2/3 (Giant Punch, neutral-B): jobj @0x8C68, extent ~0x8C68-0xBA28
- Model 4/5 (Spinning Kong, up-B): jobj @0xBA28, extent ~0xBA28-0xE1C8
- Model 6 (down-B efAsync): jobj @0xE1C8

Color blocks partition by these extents (verified by bucketing):

| move / model range | 070707 | 4248 | 98mtx | notable colors |
|---|---|---|---|---|
| header <0x70E8 | 0 | 1 | 9 | — |
| Hand Slap (0x70E8-0x8C68) | 2 (blue) | 11 | 10 | 00B2FF, 007FFF blue |
| **Giant Punch (0x8C68-0xBA28)** | 0 | 6 | 21 | white + `FFFFFF99` diffuse (no 070707) |
| **Spinning Kong (0xBA28-0xE1C8)** | 13 (blue) | 13 | 13 | **big 0000FF / FF0080FF blue-swirl series** |

**⚠️ Move-attribution ambiguity for LIVE.** DK's *giant-punch charge swirl* is
famously a blue/white electric spiral — but the big **blue 070707 series
(FFFFFF/0000FF) + blue diffuse (FF0080FF) at 0x0D108-0x0DB18 falls in the
Spinning-Kong model extent** (0xBA28-0xE1C8), while the Giant-Punch model
(0x8C68-0xBA28) has only white/`FFFFFF99` 4248 blocks, no blue 070707. Two
readings: (a) the blue swirl really is Spinning Kong's wind trail and the
giant-punch charge swirl is one of the white 4248 blocks / a ptcl in EfCoData;
(b) my model-extent boundary is slightly off and the swirl belongs to giant
punch. **LIVE must poke both moves and judge** (Mewtwo-usmash lesson: gfx→move
narrows, does not verify). The probe pokes the blue series on `upb` and the
white-99 blocks on `neutralb` to disambiguate.

## Block layout (all model-region, DK has no ptcl bank)

`070707`: marker `07 07 07 04` → color1 RGB @+4 (bright core), color2 RGB @+8
(glow). Byte-verified (0xD108 = `07 07 07 04 FF FF FF 00 00 00 FF`).
`4248` (HSD material): color block @marker−0x10; ambient RGBA @+0, diffuse
RGBA @+4 (diffuse dominates). Byte-verified (0xD178 = `80 80 80 FF 00 80 FF
FF FF FF FF FF` → diffuse `0080FF` blue @0xD17C).

---

## `EfDkData.dat` — Giant Punch (neutral-B) candidates

Parser tag = (Model 2/3, fmt, ordinal). The giant-punch model region has only
white/`FFFFFF99` 4248 materials (no 070707). Poke the `FFFFFF99` diffuse blocks
(diffuse @block+4; the `99` alpha-tinted ones are the likely charge glow).

| layer_id | fmt | diffuse offset | vanilla block | hypothesis |
|---|---|---|---|---|
| gp_a | 4248 | 0xB124 | `808080FF FFFF99FF FFFFFFFF` | charge swirl / fist glow (diffuse @0xB124) |
| gp_b | 4248 | 0xB1C4 | `808080FF FFFF99FF …` | charge glow |
| gp_c | 4248 | 0xB3A4 | `808080FF FFFF99FF …` | charge glow |
| gp_d | 4248 | 0xB444 | `808080FF FFFF99FF …` | fully-charged spark flash |

AUDIT_HINTS (giant punch): move=neutralb, HOLD B to charge (frames ~20-160);
the charge swirl builds over the charge, fully-charged sparks appear at the
cap. Forced anti-color magenta (vanilla white/pale). Probe holds B at frames
1/30/60/100, releases at 140.

---

## `EfDkData.dat` — Spinning Kong (up-B) candidates

### Candidate group `spinkong_swirl_blue` — Model 4/5 blue trail (070707 + 4248)

The 0x0D108-0x0DB18 region is a dense repeated series of `FFFFFF / 0000FF`
070707 pairs + `FF0080FF` diffuse 4248 materials — the white/blue spinning
wind trail (SEE the giant-punch ambiguity note above; poke on up-B).

| layer_id | fmt | offset | vanilla | hypothesis |
|---|---|---|---|---|
| sk_c1_a | 070707 | 0xD10C | FFFFFF | trail core |
| sk_c2_a | 070707 | 0xD110 | 0000FF | trail blue glow |
| sk_diff_a | 4248 | 0xD17C | 0080FF | trail material diffuse |
| sk_c1_b | 070707 | 0xD1D8 | FFFFFF | trail core |
| sk_c2_b | 070707 | 0xD1DC | 0000FF | trail blue glow |
| sk_diff_b | 4248 | 0xD248 | 0080FF | trail diffuse |
| sk_c1_c | 070707 | 0xD2A4 | FFFFFF | trail core |
| sk_c2_c | 070707 | 0xD2A8 | 0000FF | trail blue glow |
| sk_c1_d | 070707 | 0xD508 | FFFFFF | trail core |
| sk_c2_d | 070707 | 0xD50C | 0000FF | trail blue glow |
| sk_c1_e | 070707 | 0xD904 | FFFFFF | trail core |
| sk_c2_e | 070707 | 0xD908 | 0000FF | trail blue glow |
| sk_c1_f | 070707 | 0xDA9C | FFFFFF | trail core |
| sk_c2_f | 070707 | 0xDAA0 | 0000FF | trail blue glow |

(The full series is ~13 repeated `FFFFFF/0000FF` 070707 blocks 0xD108-0xDA98
each paired with a `FF0080FF` 4248 diffuse; the probe pokes a representative
subset. If it lights up, LIVE fans out to all of them.)

AUDIT_HINTS (spinning kong): move=upb frames ~8-60; forced anti-color magenta
(vanilla blue). Probe pokes 14 blue offsets on up-B.

---

## `EfDkData.dat` — Hand Slap (down-B) candidates

Model 0/1 (0x70E8-0x8C68) has two blue 070707 blocks — the ground shockwave
ring / hand-slap impact.

| layer_id | fmt | offset | vanilla | hypothesis |
|---|---|---|---|---|
| hs_c1_a | 070707 | 0x7D20 | FFFFFF | shockwave core |
| hs_c2_a | 070707 | 0x7D24 | 00B2FF | shockwave blue glow |
| hs_c1_b | 070707 | 0x806C | FFFFFF | shockwave ring core |
| hs_c2_b | 070707 | 0x8070 | 007FFF | shockwave ring blue |

AUDIT_HINTS (hand slap): move=downb frames ~8-40; forced anti-color magenta
(vanilla blue). ⚠️ The Hand Slap shockwave may be ON-HIT / ground-contact only
— if the down-B poke shows nothing solo, flag pending punching-bag (lesson 7),
NOT dead.

---

## Quarantine / open leads

- **53 `98-matrix` blocks**: texanim/matrix tables, not RGB triples. Never ship.
- **Giant-punch charge swirl vs Spinning-Kong trail**: the single biggest open
  question — the blue-swirl series may belong to either move; LIVE poke of both
  disambiguates (see the ambiguity note). If the charge swirl is invisible
  under both `neutralb` (white-99) and `upb` (blue) pokes, it is likely a ptcl
  in the **common `EfCoData`** bank (DK's SpecialN spawns no small-id
  common-bank effect, but articles could) — route there.
- **Model 6 (0xE1C8, down-B efAsync 0x4CC→0x1F46)**: not covered by the probe
  yet; open lead if the down-B poke of Models 0/1 under-covers.
- No DK effect mods exist in `ssbm-backup` — post 16451 "Fire Donkey Kong"
  ships only a costume `PlDkRe.dat`, not `EfDkData`. Zero mod corroboration;
  all rows rest on marker-verification + decomp cross-ref alone.

## Open leads (post-LIVE)

1. ~~Blue swirl attribution~~ RESOLVED: swirl renders white (texture) on both
   moves; not a colorable layer.
2. ~~Giant-punch charge swirl in white-99 blocks~~ RESOLVED: no visible charge
   GFX at all; blocks are white dust material, texture-dominated.
3. ~~Fully-charged spark flash~~ RESOLVED: no spark GFX at charge cap (f160).
4. ~~Hand slap shockwave solo vs on-hit~~ RESOLVED: no blue ring in either
   case; visible slap effect is white dust + generic pink hitspark.
5. (residual) Model 6 (0xE1C8, down-B efAsync 0x4CC→0x1F46) was never probed —
   but given every other DK block is texture-dominated white, low priority.

---

## Shippable-now summary (for WIRE)

**NOTHING to ship from `EfDkData.dat`.** All three candidate groups are dead
or harness-blocked (see LIVE VERDICTS). No config/preview/editor wiring should
be added for DK effects. If DK gets an effect extra later it would need the
TEXTURE path (recolor the white wisp/dust textures) — but no DK effect texture
mod exists in `ssbm-backup` (post 16451 ships only a costume, not
`EfDkData`), so there is zero corroboration and no texture-region lead either.
Mark DK's effect rows in `EXTRAS_AUDIT.md` as investigated → no-ship.
