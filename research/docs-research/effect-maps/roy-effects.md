# Roy effect map (MAP-STATIC — 2026-07-02)

Target file: `EfFeData.dat` (26843 B) in `storage/test-base/files/`.
Character `roy` (CSS grid 24, external ckind `0x17`). ftEmblem is a **Marth
clone**: `ftFe_Init.c` reuses `ftMs_SpecialN/Hi/Lw/S` wholesale.

Method: structural decode via `python skinlab/ptcl_parse.py
../storage/test-base/files/EfFeData.dat --models` + decomp cross-ref
(`ft/chara/ftEmblem`, `ft/chara/ftMars`, `ef/efasync.c`). No boots. All rows
are **candidates — LIVE pending**. Probe spec: `backend/probes/roy_fx_probe.json`.

## KEY STRUCTURAL FINDING — EfFeData's ptcl bank ≈ EfMsData (Marth)

```
FILE: EfFeData.dat   symbol=effEmblemDataTable
  EffectTable@0x20  ParticleGroup@0x60  version=0x42  generators=4
  effect_id_start=49000  tex_bank@0x200
script 1  0x11A PRIMCOL FFFFFFFF / 0x121 ENVCOL 4AA7F800   (light blue)
script 2  0x192 PRIMCOL 00A6FFFF / 0x199 ENVCOL 0000C200   (blue)
script 3  0x1E0 PRIMCOL FFFFFFFF / 0x1E7 ENVCOL A300E800   (purple)
```

Roy's ptcl bank is **byte-identical to Marth's EfMsData** — same 3 scripts,
same offsets (0x11A/0x121/0x192/0x199/0x1E0/0x1E7), same BLUE/purple vanilla
colors. The model region (07-block @0x2B9, 42/98 material blocks 0x3E34-0x4473)
is likewise near-identical to Marth's. Both files are the Marth effect template
with only the EffectIDStart differing (16000 vs 49000). **Nothing in EfFeData
is Roy-fire-colored.**

## Where Roy's FIRE actually lives (decomp findings)

**CORRECTION (2026-07-02, per `efcodata.md` §0.3 + `effect-texbank.md`):** an
earlier draft claimed Roy's specials route to the **EfCoData common bank**. That
is WRONG — the `efsync.c` switch sends them back into Roy's OWN file:

- Roy reuses Marth's special-move functions (`ftFe_Init.c` installs
  `ftMs_SpecialN/Hi/Lw/S`), which for the ftEmblem clone spawn the **49xxx**
  ids: `efSync_Spawn(1297)` → `efsync.c:635 case 0x511` → `efLib_Create*(0xBF68)`;
  `0xBF68 = 49000 = 49000/1000 = bank 49 = EfFeData` script 0 — **this file**.
  `efSync_Spawn(1296)` → `case 0x510` → `0xBF68` too. (Marth's 1265/1266 route to
  `0x3E80` = 16000 = EfMsData; Roy's clone remaps to 49xxx.) Neither is EfCoData.
- **Counter flash / Shield-Breaker-style charge glow**: these ARE the three blue
  ptcl scripts below (49000-49002), editable here.
- **Orange Flare Blade / Blazer FIRE**: NOT a color record anywhere in EfFeData.
  EfFeData's texture bank is **3 grayscale groups (I4/I8, zero color)** — see
  `effect-texbank.md`. The visible orange fire comes from the **shared EfCoData
  fire texture group 9** (the one colored CI8 group, `efcodata.md` §5 /
  `effect-texbank.md`), which mod 17088's "rainbow fire whole cast" recolors —
  that shared grp9 is why Roy's fire shifts along with everyone else's.

So EfFeData contributes only the same blue sword-glow ptcl scripts as Marth
(now correctly attributed to EfFeData, not EfCoData), plus the sword trail
(`PlFe.dat 0x3AA0`, already the shipped Roy sword extra, vanilla inner edge
orange `EB7850`). Roy's fire recolor belongs to the shared EfCoData
`common_fire` (grp9) extra.

---

## Proposed extra: `sword_glow` — EfFeData.dat — 🔴 DEAD (LIVE 2026-07-02)

**LIVE PASS 2026-07-02** (`backend/probes/roy_fx_probe.json`, captures
`tests/artifacts/datram-probe-roy/`). Probed all 3 scripts (green on ENV,
magenta on white PRIM) across **neutralb (Flare Blade), upb (Blazer), sideb
(Dancing Blade), downb (Counter), fsmash**.

**Verdict: FULLY DEAD — zero visible color change on every tested move.** This
is exactly the predicted outcome and confirms the correction: EfFeData's blue
scripts do NOT drive any visible Roy effect. Roy's swings show the white PlFe
sword trail (shipped extra); his orange fire is the shared EfCoData grp9 texture
(`common_fire`), not this file. Pixel-diffs vs vanilla were flat (all within
star-twinkle noise); eyeballed Flare Blade (neutralb f30) — no fire, no glow,
identical between poked and vanilla.

| layer_id | format | offset | vanilla | LIVE verdict |
|---|---|---|---|---|
| glow1_c1/c2 | CF-multi | 0x11A/0x121 | FFFFFF / 4AA7F8 | 🔴 DEAD |
| glow2_c1/c2 | CF-multi | 0x192/0x199 | 00A6FF / 0000C2 | 🔴 DEAD |
| glow3_c1/c2 | CF-multi | 0x1E0/0x1E7 | FFFFFF / A300E8 | 🔴 DEAD |

**Note vs Marth:** Roy's downb (Counter) rendered DEAD just like the rest — but
that is the same on-hit limitation as Marth's counter (bag never attacks), so
"dead on downb" here means "not demonstrated," same caveat. All 5 moves flat.

## Shippable-now summary (for WIRE)

**NOTHING to ship from EfFeData.** No `sword_glow` extra — the 3 scripts are
dead/undemonstrated. Roy's only shipped effect extra remains the sword trail
(`PlFe.dat 0x3AA0`). Roy's fire → shared `common_fire` (EfCoData grp9) extra,
a separate common-effects mission.

### Open leads
- Model-region 07/42/98 blocks (0x2B9-0x4473): generic material data mirroring
  Marth's; not poked, not proposed.
- If Roy's Counter flash is ever wanted, it faces the SAME on-hit harness block
  as Marth's (see marth-effects.md "To un-block").

### NOT Roy-file layers
- **Orange Flare Blade / Blazer FIRE** — shared **EfCoData texture group 9** (the
  one colored CI8 fire group), recolored by mod 17088 cast-wide. Belongs to the
  EfCoData `common_fire` texture_recolor extra (`effect-texbank.md`), never a
  per-Roy EfFeData record. (EfFeData's own tex bank is 3 grayscale groups.)
- Counter flash / charge glow — these ARE the blue ptcl scripts above
  (gfx 1296/1297 → 0xBF68 = EfFeData 49000-2, NOT EfCoData; corrected
  2026-07-02). Editable here as `sword_glow`.
