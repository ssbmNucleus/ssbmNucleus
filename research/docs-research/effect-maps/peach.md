# Peach effect map (MAP-LIVE done 2026-07-02 — DEAD, no shippable EfPeData extra)

Mission: extras campaign, Peach (`EfPeData.dat`). LIVE pass complete.
Offsets marker-verified against vanilla `storage/test-base/files/EfPeData.dat`.
Probe spec: `backend/probes/peach_probe.json`. Char key = `peach` (ckind 0x0C).
**No reference mods exist.**

## ⚡ LIVE VERDICT (2026-07-02) — 🔴 DEAD, confirmed STATIC hypothesis

Captures: `tests/artifacts/datram-probe-peach/`. Poked the single EfPeData
model material (ambient 0xDC0 + diffuse 0xDC4) magenta (`FF00FF`, vanilla was
ambient `B3B3B3` / diffuse `FFFFFF`) and ran all four specials:

| move / effect | result |
|---|---|
| down-B (turnip pull) | vanilla only (poked rep threw a held turnip → `LightThrowF4`); vanilla turnip pull shows the turnip + dust swirl, NO EfPeData model on screen |
| side-B (bomber) | grey/white dust swirl + white explosion puff — NO magenta tint |
| neutral-B (toad) | Toad summoned with normal red/white cap — NO magenta tint |
| up-B (parasol) | parasol opens WHITE — NO magenta tint |

**The single EfPeData model produces NO visible tint under any special.** This
is exactly the predicted outcome: the model is loaded-but-unused for these
moves. **Peach has no shippable EfPeData char extra** — all her marquee special
visuals (turnip pull sparkle 0x4D2, toad spore 0x4D3, float dust 0x4D4) are
COMMON-bank (`EfCoData.dat`); parasol/turnip/toad/bomber-explosion are ITEMS.
WIRE: **skip Peach entirely for EfPeData.** If turnip/toad/float recolors are
ever wanted, they are an EfCoData common-bank workstream (`efcodata.md`), NOT a
Peach char layer — recoloring them recolors the whole cast's equivalent.

---

## Headline STATIC finding: Peach's marquee effects are NOT in `EfPeData.dat`

`EfPeData.dat` (symbol `effPeachDataTable`, 5094 bytes) has **NO ptcl
(particle) bank** — `SBM_EffectTable` root @0x20 with `Particles = 0x00000000`,
`TexBank = 0`. The table is a SINGLE `SBM_EffectModel`: JOBJ tree @0x1208,
anim @0x1320, plus a scale float `0x41200000` (=10.0) at +0x08. `ptcl_parse.py
--models` finds **10 model-region color blocks** (1 × 42_48, 9 × 98-matrix),
all inside that one model.

**Every Peach special effect the mission targets resolves to the COMMON bank
(`EfCoData.dat`), not `EfPeData`.** Cross-ref of `efSync_Spawn` in
`melee/src/melee/ft/chara/ftPeach/` + `src/melee/it/items/itpeach*.c`:

| source | gfx_id | move / article | resolves to |
|---|---|---|---|
| `ftPe_SpecialLw.c:108` `efSync_Spawn(1234)` | 0x4D2 | Turnip PULL sparkle (down-B) | **EfCoData** (id<592-gen common bank) |
| `itpeachtoadspore.c:85` `efSync_Spawn(0x4D3)` | 1235 | Toad SPORE burst | **EfCoData** |
| `ftPe_Float.c:65` `efAsync_Spawn(…,1236,…)` | 0x4D4 | Float DUST | **EfCoData** |

`EfCoData.dat` = `effCommonDataTable`, `EffectIDStart=0`, **592 generators** —
these small ids (0x4D2/0x4D3/0x4D4 = 1234/1235/1236) index straight into it.
Per the campaign's standing rule, **common-bank effects are quarantined**
(shared across all fighters; never ship as a Peach-specific char layer). They
belong in `efcodata.md`, not here.

**Turnip, Parasol, Toad, Bomber-explosion are ITEMS**, not EfPeData effects.
`ftPe_SpecialHi.c` uses `It_Kind_Peach_Parasol` / `It_Kind_Parasol`;
`ftPe_SpecialLw.c` uses `It_Kind_Peach_Turnip`; SpecialS bomber →
`itpeachexplode.c` (no `efSync` — its explosion visual is a common explosion
effect or the item model). Item visuals live in the item's own `.dat`
(`PlPe.dat` / item files), NOT in `EfPeData.dat`. Peach hearts (`itheart.c`)
are likewise an item model. → **None of these are EfPeData char layers.**

## What IS in `EfPeData.dat` (the single effect model)

The one model's color blocks — semantic UNKNOWN from C code (no move spawns id
≥ 11000 into this bank; the model is loaded but not attributable to a named
move without live poke). Marker-verified:

| off | fmt | vanilla | note |
|---|---|---|---|
| 0xDC0 (block) | 42_48 | `B3B3B3FF FFFFFFFF FFFFFFFF 3F800000` → diffuse `FFFFFF` @0xDC4, ambient `B3B3B3` @0xDC0 | only 42_48 material; a grey-ambient white-diffuse surface |
| 0xE6C, 0xF2C, 0xF44, 0xFB6, 0x1079, 0x1145, 0x1166, 0x1190, 0x11A8 | 98-matrix | (vertex/texanim tables) | **9 × 98-matrix — NOT RGB triples; quarantine** |

The 42_48 at 0xDC0 has ambient `B3B3B3` (@0xDC0, RGB) + diffuse `FFFFFF`
(@0xDC4). What this model IS (a shared crown/heart/toad glow? a float sparkle
model? Peach's parasol tip?) is the single open question for LIVE — probe it
across all four specials and see if any move tints.

---

## `EfPeData.dat` — single-model candidate (semantic unknown)

| layer_id | fmt | offset | vanilla | hypothesis |
|---|---|---|---|---|
| pe_model_ambient | 42_48 | 0xDC0 | `B3B3B3` (ambient) | effect-model ambient tint |
| pe_model_diffuse | 42_48 | 0xDC4 | `FFFFFF` (diffuse) | effect-model diffuse (dominant) |

AUDIT_HINTS (unknown-model): probe pokes 0xDC0+0xDC4 magenta across
downb (turnip pull), sideb (bomber), neutralb (toad), upb (parasol) to find
which — if any — move shows a magenta tint. Forced anti-color magenta (vanilla
white). **If NOTHING tints under any move, this model is loaded-but-unused for
these moves (or its visual is the item/common effect) → dead, route to
quarantine.**

---

## Quarantine / shared-file findings (NEVER ship as Peach layers)

- **Turnip pull sparkle (0x4D2/1234)**, **Toad spore burst (0x4D3/1235)**,
  **Float dust (0x4D4/1236)** — all `EfCoData.dat` common-bank generators.
  These are the mission's headline Peach targets but they are NOT Peach-owned;
  document any recolor in `efcodata.md`. (Toad spore is a counter on-hit burst;
  if a common-bank spore generator is later wanted, it needs the punching-bag
  harness — lesson 7 — but it is still a SHARED effect, not a Peach layer.)
- **Peach Bomber explosion + hearts** — `itpeachexplode.c` / `itheart.c` item
  visuals (item model / common explosion), not `EfPeData`. Out of scope for an
  EfPeData char extra.
- **Parasol** — `It_Kind_Peach_Parasol` item; its model/colors are in the item
  `.dat`, not `EfPeData`.
- **Heart/crown visuals** — item/character-model geometry, not `EfPeData`.
- **9 × 98-matrix blocks** in EfPeData model — texanim/matrix tables, not RGB.

## Open leads for LIVE

1. **Probe the single EfPeData model (0xDC0/0xDC4)** across all four specials.
   Most likely outcome: no visible tint (the model is a loaded-but-secondary
   asset and the real visuals are common-bank/item). If so, mark dead and note
   Peach has **no shippable EfPeData char extra** — its effects are all
   EfCoData/item.
2. If a move DOES tint the model, identify which (likely float sparkle or a
   toad/heart glow) and promote to a real layer.
3. Turnip-pull / toad-spore / float-dust recolors, if desired, must be pursued
   as **EfCoData common-bank** extras (separate workstream / `efcodata.md`),
   NOT as Peach layers — flag to the campaign owner. Peach shares those
   generators with the whole cast, so recoloring them recolors everyone's
   equivalent.
