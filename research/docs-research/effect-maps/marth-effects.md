# Marth effect map (MAP-STATIC — 2026-07-02)

Target file: `EfMsData.dat` (23977 B) in `storage/test-base/files/`.
Character `marth` (CSS grid 23, external ckind `0x09`).

Method: structural decode via `python skinlab/ptcl_parse.py
../storage/test-base/files/EfMsData.dat --models` (from `backend/`) + decomp
cross-ref (doldecomp/melee `ft/chara/ftMars/*`, `ef/efasync.c`).
No boots this stage. All rows below are **candidates — LIVE pending**: no layer
here has been eyeballed. Probe spec: `backend/probes/marth_fx_probe.json`.

## Structural parser result

```
FILE: EfMsData.dat   symbol=effMarsDataTable
  EffectTable@0x20  ParticleGroup@0x60  version=0x42  generators=4
  effect_id_start=16000  tex_bank@0x200
script 1  gen@0xC8  bc@0x104..0x140  texGrp=1  kind=0x100
    0x11A  PRIMCOL RGBA  FFFFFFFF   [0xCF]
    0x121  ENVCOL  RGBA  4AA7F800   [0xDF]   (light blue)
script 2  gen@0x140 bc@0x17C..0x1A0  texGrp=2  kind=0x400100
    0x192  PRIMCOL RGBA  00A6FFFF   [0xCF]   (blue)
    0x199  ENVCOL  RGBA  0000C200   [0xDF]   (dark blue)
script 3  gen@0x1A0 bc@0x1DC..0x200  texGrp=0  kind=0x400100
    0x1E0  PRIMCOL RGBA  FFFFFFFF   [0xCF]
    0x1E7  ENVCOL  RGBA  A300E800   [0xDF]   (purple/magenta)
total ptcl color operands: 6   (4 generators, gen 0 blank/shared)
model-region 07/42/98 blocks: 15 (generic material data + one 07 @0x2B9)
```

The ptcl bank is TINY (only 3 generators with color, effstart 16000 → gfx
16001/16002/16003). Decoder terms: `_c1` = PRIMCOL (`0xCF`), `_c2` = the
following ENVCOL (`0xDF`, the "+7 secondary" that dominates the sustained
tint). All three vanilla ENVs are BLUE/purple — consistent with Marth's blue
sword-glow / afterimage family, NOT the sword-trail texture (that lives in
`PlMs.dat 0x3948`, already the shipped Marth sword extra).

## Where Marth's named specials actually live (decomp findings)

**CORRECTION (2026-07-02, per `efcodata.md` §0.3 + `effect-texbank.md`):** an
earlier draft of this section claimed gfx 1265/1266 route to the **EfCoData
common bank**. That is WRONG. The `efsync.c` switch resolves them back into
Marth's OWN file:

- **Shield Breaker** charge glow: `ftMs_SpecialN_801365A8` →
  `efSync_Spawn(1266)` → `efsync.c:442 case 0x4F2` → `efLib_Create*(0x3E80)`.
  `0x3E80 = 16000 = 16000/1000 = bank 16 = EfMsData` script 0 — **this file**,
  not EfCoData. (`ftMs_Init.c:499/502`.)
- **Counter** flash: `ftMs_SpecialLw` → `efSync_Spawn(1265)` →
  `efsync.c:439 case 0x4F1` → `efLib_Create*(0x3E80)` = EfMsData too.
  (`ftMs_SpecialLw.c:349/355`.)

So the three blue-glow ptcl scripts below (16000-16002) ARE Shield-Breaker /
Counter / swing spawns — they live in EfMsData and are editable here. Their
vanilla color is **blue/purple** (`4AA7F8`/`00A6FF`/`A300E8`), i.e. the sword
glow, NOT the orange Flare-Blade fire.

**Marth has NO fire at all — this was previously mislabeled.** `EfMsData`'s
texture bank holds only **3 grayscale groups (I4/I8, zero color)** — see
`effect-texbank.md` — and there is no orange fire texture or orange color operand
in the file. That is not because Marth's fire lives elsewhere; it is because
**Marth has no fire move.** His specials are Shield Breaker, Dancing Blade,
Dolphin Slash, and Counter — all non-fire (blue sword glow only). **Flare Blade
and Blazer are ROY's moves, not Marth's** (Roy is a Marth clone, which is why the
two were conflated here). Roy's Flare Blade + Blazer fire draws its colored cloud
from the **shared EfCoData fire texture group 9** (the one colored CI8 group;
`efcodata.md` §5 / `effect-texbank.md`) via subaction-embedded common-bank fire
GFX — which is why mod 17088 recoloring EfCoData grp9 shifts **Roy's** fire (and
Din's Fire / Bowser Bomb / Charizard breath) cast-wide. That fire recolor belongs
to the shared `common_fire` (EfCoData grp9) extra, listed under **Roy** (+ Bowser
/ Zelda-owner), **not Marth**.
- **Dolphin Slash** (SpecialHi) and **Dancing Blade** (SpecialS): NO
  `efSync_Spawn` in the fighter `.c`. Their visuals are the sword trail
  (`PlMs.dat`, done) plus subaction-embedded effect events in `PlMsAJ.dat`
  that reference this bank's 16001-3 scripts — i.e. the three ptcl scripts
  above are the animation-driven sword-glow spawns, not distinct move colors.

There is therefore **no Marth-unique shield-breaker / counter color record in
`EfMsData`** to ship as a Marth extra. The only shippable candidates in this
file are the three blue-glow ptcl scripts, whose in-game role must be
identified by LIVE poke.

---

## Proposed extra: `sword_glow` — EfMsData.dat — 🔧 HARNESS-BLOCKED (LIVE 2026-07-02)

**LIVE PASS 2026-07-02** (`backend/probes/marth_fx_probe.json`, captures
`tests/artifacts/datram-probe-marth/`). Probed all 3 scripts (green on ENV,
magenta on white PRIM) across **upb (Dolphin Slash), sideb (Dancing Blade),
fsmash, fair** (run 1), then **neutralb (Shield Breaker) + downb (Counter)**
(run 2), then a **CHARGED Shield Breaker** (B held f1-44, run 3).

**Verdict: none of the 3 scripts rendered a visible color change on ANY tested
move.** Every Marth swing/special shows its blade effect as the **white PlMs
sword trail** (the already-shipped sword extra) or the naturally-magenta Shield-
Breaker charge beam (present identically in vanilla + poked = NOT ours). All
apparent green/magenta pixel-diffs were background stage star-twinkles (verified
by eyeballing — the "green" pixels were scattered sparkle dots off Marth's body,
not on the blade). The scripts are structurally real but did not demonstrate on
a capturable move.

**Why (decomp-consistent):** the two decomp-cited spawners are hard to trigger
solo:
- **Counter flash** (gfx 1265 → EfMsData) is **on-HIT only** — it fires when
  Marth is STRUCK inside the counter window. The punching-bag harness gives a
  2nd *uncontrolled* human port that NEVER attacks (lesson #7/#14), so Marth is
  never hit → the counter flash never spawns. **Genuinely harness-blocked.**
- **Shield Breaker charge glow** (gfx 1266 → EfMsData): even a full charged
  release showed only the white PlMs slash burst; the EfMsData sub-glow, if it
  renders at all, is masked by / coincident with the sword trail at this zoom.

| layer_id | format | offset | vanilla | (script,opcode,ord) | LIVE verdict |
|---|---|---|---|---|---|
| glow1_c1 | CF-multi | 0x11A prim | FFFFFF | (1, PRIMCOL, 0) | 🔧 no visible demo |
| glow1_c2 | CF-multi | 0x121 env  | 4AA7F8 | (1, ENVCOL, 0)  | 🔧 no visible demo |
| glow2_c1 | CF-multi | 0x192 prim | 00A6FF | (2, PRIMCOL, 0) | 🔧 no visible demo |
| glow2_c2 | CF-multi | 0x199 env  | 0000C2 | (2, ENVCOL, 0)  | 🔧 no visible demo |
| glow3_c1 | CF-multi | 0x1E0 prim | FFFFFF | (3, PRIMCOL, 0) | 🔧 no visible demo |
| glow3_c2 | CF-multi | 0x1E7 env  | A300E8 | (3, ENVCOL, 0)  | 🔧 no visible demo |

**NOT shippable yet.** The offsets/vanilla bytes are byte-verified and the
scripts exist, but without a live demonstration these must not ship as a
`sword_glow` extra (mission rule: no layer ships 🟢 without an eyeballed change).

### To un-block (future mission)
- **Counter flash:** needs a bag that ATTACKS Marth during the counter window.
  The current uncontrolled-human bag can't. Candidate harness upgrade: a scripted
  CPU that throws ONE weak hit on a fixed frame (contradicts the no-CPU rule for
  crash tests, but for an on-hit-effect probe a single-jab CPU may be acceptable),
  or memory-force Marth's counter into its "success" branch.
- **Shield Breaker:** try a much closer camera / crop to the blade tip, or force
  the max-charge tier, to see whether the EfMsData glow is a thin blade sheen
  distinct from the PlMs trail.

### Open leads
- 07-block @0x2B9 (c1=080807 c2=040304, near-black) + 42/98 material blocks
  (0x3E34-0x4473, incl. red-ish `FF3B4A` @0x4208) = model-region JOBJ material
  data. Not poked; almost certainly sword-glow model geometry, not movable.

### NOT Marth moves / NOT Marth-file layers
- **Orange Flare-Blade / Blazer FIRE — this is ROY, not Marth.** Marth has no
  fire move; Flare Blade + Blazer are Roy-exclusive. Roy's fire draws from the
  shared **EfCoData texture group 9** (the one colored CI8 fire group), recolored
  by mod 17088 cast-wide, and belongs to the EfCoData `common_fire`
  texture_recolor extra (`effect-texbank.md`) listed under **Roy** — never a
  per-Marth EfMsData record. (EfMsData's own tex bank is 3 grayscale groups.)
- Shield Breaker charge glow / Counter flash — these ARE the blue ptcl scripts
  above (gfx 1266/1265 → 0x3E80 = EfMsData 16000-2, NOT EfCoData; corrected
  2026-07-02). Editable here as `sword_glow`.
