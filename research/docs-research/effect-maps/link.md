# Link effect map (MAP-STATIC — 2026-07-02)

Target file: `EfLkData.dat` (34809 B) in `storage/test-base/files/`.
Character `link` (CSS grid 16, external ckind `0x06`). Also covers the Young
Link sharing question.

Method: structural decode via `python skinlab/ptcl_parse.py
../storage/test-base/files/EfLkData.dat --models` + decomp cross-ref
(`ft/chara/ftLink`, `ft/chara/ftCLink`, `it/items/itlink*`, `ef/efasync.c`) +
reference-mod survey (ssbm-backup posts 15262/15263, 12904).

**LIVE PASS 2026-07-02** (MAP-LIVE, `backend/probes/link_probe.json`, 6 experiments ×
neutralb/sideb/downb/upb, captures `tests/artifacts/datram-probe-link/`):
one block is LIVE-confirmed, the rest are DEAD. See the verdict table below.

## ITEMS-PASS cross-ref (2026-07-02, see `items.md`)

ITEMS-PASS confirmed the item architecture: `itlinkbomb.c` / `itlinkboomerang.c`
have NO `efSync_Spawn`, so the bomb explosion + boomerang trail are the **article
DAT model / `PlLk.dat` / EfCoData**, never EfLkData (this file's spin-attack
trail 0x5510/0x5514 is the only live EfLkData color). The bomb explosion was NOT
re-mapped — the harness still lacks a throw-item + detonate recipe (Z swallowed
per lesson 15; only grab=L+A exists). Bomb stays an OPEN LEAD needing (a) a
pull→throw→detonate input recipe and (b) a PlLk.dat mapping pass. See
`research/docs-research/effect-maps/items.md` §5.

## KEY STRUCTURAL FINDING — EfLkData has NO ptcl bank

```
FILE: EfLkData.dat   symbol=effLinkDataTable
  EffectTable@0x20  ParticleGroup@none (no ptcl bank)  version=n/a  generators=0
  effect_id_start=n/a  tex_bank@none
total ptcl color operands: 0
model-region 07/42/98 blocks: 29
```

The `SBM_EffectTable` at data-offset 0 has **Particles ptr = 0 and
TextureGraphics ptr = 0** — Link's effect file carries NO `HSD_ParticleGroup`
(unlike Fox/Falcon/Marth/Roy). Its entire payload is the `Models[]` array
(4 `SBM_EffectModel` entries, 0x14 each, starting at data-off 0x08):

| model | FrameCount | RootJoint | JointAnim | MatAnim | ShapeAnim |
|---|---|---|---|---|---|
| [0] | 80.0 (0x42A00000) | 0x5A68 | 0x6504 | 0x6800 | 0x68A4 |
| [1] | 80.0 | 0x5A68 (shared) | 0x718C | 0x7488 | 0x752C |
| [2] | 80.0 | 0x7A08 | 0x7B6C | 0x7CD8 | 0x7D18 |
| [3] | 80.0 | 0x7A08 (shared) | 0x7E30 | 0x7FCC | 0x800C |

Two distinct model roots (0x5A68 ×2, 0x7A08 ×2), each with two animation
variants — i.e. two effect models, likely the bomb-explosion and/or
spin-attack disc geometry drawn as animated JOBJ trees. **All Link "effect"
colors in this file are HSD material / TEV / vertex colors inside those model
trees, decoded ONLY by the `--models` signature scan (locator, not verifier).**

> Parser note: `parse_bank()` was extended this mission to tolerate a null
> Particles pointer (was crashing on the OOB gcount read); it now returns an
> empty script list + `no_ptcl_bank: True` and lets `--models` scan the whole
> file. Ground-truth `--verify` still PASSES (unaffected — those files have
> ptcl banks).

## Where Link's named effects actually live (decomp + mod findings — quarantine)

None of Link's targeted effects are ptcl color records in EfLkData:

- **Bomb explosion, boomerang trail/sparkle, arrow, hookshot chain**: spawned
  from the **article item files** (`it/items/itlinkbomb.c`,
  `itlinkboomerang.c`, `itlinkarrow.c`, `itlinkhookshot.c`). The item .c files
  spawn a few effects but only with **common-bank (EfCoData) gfx ids in the
  1000-range**: arrow `efSync_Spawn(0x448=1096)`, hookshot
  `efSync_Spawn(0x41C=1052 / 0x3F1=1009)`. Bomb/boomerang have **no**
  `efSync_Spawn` at all — their visuals are the article DAT model + subaction
  events. **Quarantine (common bank).**
- **Reference mods 15262 (Trans boomerang/bow/hookshot) & 15263 (Watermelon
  Bombs) diff `PlLk.dat`, NOT EfLkData** (confirmed via
  Reference-Mods-Index + backup: both ship `PlLk*.dat`). So the community-known
  editable boomerang/arrow/bomb colors are in **`PlLk.dat`** (the player/item
  file, out of this mission's Ef* scope). NOTE: post 15262's `PlLk.dat` is
  239075 B vs vanilla 239099 B (−24) = RE-SAVED → unusable for exact offsets
  (lesson #4); it corroborates *which file*, not *which offset*.
- **Spin-attack trail (beyond the sword extra)**: no EfLkData ptcl record; the
  extra sword-swing trail is `PlLk.dat` (the shipped Link sword extra). Any
  additional spin glow would be common-bank or PlLk model data.

So **EfLkData ships only model-region geometry colors** (the 4 effect models),
which need LIVE poking to attribute to bomb/spin visuals — and even then they
are JOBJ material colors, not ptcl `_c1`/`_c2` couples.

## Young Link sharing — ANSWERED

**Young Link (ftCLink / "Child Link") has NO separate effect DAT file.** The
`efAsync_DatEntries[51]` table (`efasync.c:1145-1197`) lists `EfLkData.dat`
(index 6, `effLinkDataTable`) but there is **no `EfClData.dat` / Child-Link
entry** anywhere in the table (the only Kirby-copy banks are `EfKbXx`; no
`EfKb`-analog for YLink either). `ftCLink` has no `efSync_Spawn` calls of its
own. Therefore Young Link **loads and shares Link's `EfLkData` effect table**
(and the common EfCoData bank) — a per-character effect edit to EfLkData will
affect BOTH Link and Young Link. YLink's own visual differences live in
**`PlCl.dat`** (confirmed: the "Young Link to the Past" mod, post 12904, ships
its effect changes in `Effects/PlCl.dat`, not any EfCl file). YLink's sword
extra already exists (PlCl-based).

---

## Model-region color inventory (EfLkData.dat) — CANDIDATES, LIVE pending

Signature scan of the `Models[]` region. These are HSD material/TEV/vertex
colors, NOT ptcl operands — the scan LOCATES them; semantics require LIVE.
The `42`-signature blocks with `808080 FFFFFF FFFFFF FFFFFF 00000000` are
generic material defaults (ambient grey / white diffuse-specular) and are
probably not visually meaningful; listed for completeness. The 07-blocks and
the colored 42-block are the more promising candidates.

| off | type | vanilla (c1 / c2 or block) | VERDICT (LIVE 2026-07-02) | notes |
|---|---|---|---|---|
| 0x4A1 | 070707 | c1=040206 c2=1C0E0E (near-black) | 🔴 **DEAD** (no change on any move) | near-black; not visible |
| **0x550C** | 070707 | **c1=FFFFFF (0x5510) c2=0000FF (0x5514)** | 🟢 **LIVE = SPIN ATTACK (up-B) blade/disc TRAIL** | poke→trail turns magenta/red on up-B f6-30 |
| 0x558C | 4248 | 808080 FFFFFF FFFFFF FFFFFF 3F7FBE77 | 🔴 **DEAD** | generic material |
| 0x56A0 | 98matrix | 2-byte vertex colors (0x34xx first) | 🔴 **DEAD** | model 0 vertex colors, invisible |
| 0x7860 | 98matrix | 2-byte vertex colors (0x37xx first) | 🔴 **DEAD** | model 1 vertex colors, invisible |
| 0x7758–0x7808 | 4248 | 808080 FFFFFF FFFFFF FFFFFF 3F80.. | (not poked) | generic LOD materials |

(Generic `...00000000`-tail 42-blocks at 0x5224/0x52C4/0x5364/0x5410/0x54B0/
0x561C omitted — pure material defaults.)

**LIVE result:** Only the **0x550C 07-block is a real, editable Link effect
color: the spin-attack (up-B) blade/disc TRAIL.** Vanilla is white core
(0x5510) → blue tint (0x5514); poking core→MAGENTA + tint→RED turned the
swirling up-B disc trail magenta/red across the whole up-B active period
(confirmed f6, f10, f16, f24 — captures
`tests/artifacts/datram-probe-link/block_550c_white_blue-upb-*.png` vs
`vanilla-upb-*.png`). All other model-region candidates (near-black material,
the 42/98 vertex blocks) produced **no visible change on any move** = DEAD.

⚠️ **downb (bomb) — NOW TESTED via a `bombthrow` recipe (STRAGGLER-CLOSEOUT 2026-07-02): EfLkData is DEAD for the bomb explosion.**
Built a `bombthrow` recipe in `ingame/moves.py` (registered in `MOVES`): down-B
(stick-down + B) pulls the bomb, ride out the pull, then toss it FORWARD (stick
forward + PRESS A = item LightThrow, since Z is swallowed and item-toss is A not
grab). Verified LIVE: Link reaches **LightThrowF4** and the bomb flies ~34 units
and **DETONATES on the pinned DK bag** (bag → DamageHi3; the explosion — orange
fireball + gold radial rays + white star bursts + gray shockwave ring — is fully
captured at f14). Poked EfLkData 0x7758/0x7808 RED + a 0x7A08-0x8010 color table
(green, all common bases): the two exact material pokes changed NOTHING and the
0x7A08 table matched **0 records** — the bomb explosion is **byte-for-eye
IDENTICAL** vanilla vs poked at every frame. **CONFIRMS the ITEMS-PASS: the bomb
explosion is NOT in EfLkData** — it renders from the article item file
(`itlinkbomb.c`, no efSync_Spawn) / `PlLk.dat` / EfCoData, exactly as predicted.
EfLkData's 0x7A08 model is NOT the bomb-explosion color source. **Bomb explosion
is NOT a shippable EfLkData color extra.** If ever wanted, it's a PlLk.dat /
EfCoData mapping task, not this file. Captures:
`tests/artifacts/datram-probe-link-bombthrow/` (`{vanilla,bomb_model_7a08}
-bombthrow-f14`). Spec: `backend/probes/link_bombthrow_probe.json`. Recipe:
`ingame/moves.py` `BOMBTHROW` branch (reusable for any pull-item + throw +
detonate probe).

AUDIT_HINTS: `upb:6-30` forced anti-colors core `FF00FF` / tint `FF0000`
(vanilla white/blue). Movement note: up-B rises off the top of frame after
~f24; the trail is best framed f6-16.

## Shippable-now summary (for WIRE)

**Extra: `spin_attack_trail` (Link up-B blade/disc trail) — EfLkData.dat.**
One 07-block, two color operands (marker+4 core / marker+8 tint per lesson #2).
LIVE-verified 2026-07-02. Shared by Young Link (loads EfLkData).

| layer_id | format | offset | vanilla | semantic | anti-color used |
|---|---|---|---|---|---|
| spin_trail_c1 | 070707 core | 0x5510 | `FFFFFF` | up-B trail bright core | `FF00FF` |
| spin_trail_c2 | 070707 glow | 0x5514 | `0000FF` | up-B trail tint/glow | `FF0000` |

- Marker: the 07-block header is at 0x550C (`07 07 07 04`); c1 at +4 (0x5510),
  c2 at +8 (0x5514). Byte-verified vanilla: `...07070704 FFFFFF00 0000FF00...`.
- AUDIT_HINTS: `upb:6-30` (up-B active/rise frames), forced anti-colors
  `spin_trail_c1=FF00FF`, `spin_trail_c2=FF0000` (far from vanilla white/blue).
- Editor grouping: single extra, `_c1`/`_c2` = core/glow (like Fox laser_ring's
  07-block pair). Not a CF-multi (no `_c1`/`_c2` secondary-at-+7 subtlety — it's
  a plain 070707 with the two-color core/glow pattern).
- On-hit/pending: none — the trail is a pure animation-driven model effect,
  visible every up-B.

### Open leads
- **Bomb explosion disc — CLOSED (STRAGGLER-CLOSEOUT 2026-07-02): DEAD in EfLkData.**
  The `bombthrow` recipe now exists and lands a real bomb detonation on the bag;
  poking 0x7758/0x7808 + the whole 0x7A08-0x8010 model color region changed the
  explosion by NOTHING. The bomb explosion is architecturally in the article item
  file / PlLk.dat / EfCoData (ITEMS-PASS), not EfLkData. Not a lead in this file
  anymore — see the ⚠️ downb block above + the Quarantine section below.
- 98-matrix 2-byte colors: all DEAD; the bomb-recipe test (above) confirms no
  further EfLkData work is warranted.

### Quarantine (NOT EfLkData layers)
- Bomb explosion / boomerang trail / arrow / hookshot colors → **PlLk.dat**
  (mods 15262/15263) and/or **EfCoData common bank** (arrow gfx 1096, hookshot
  gfx 1052/1009). A separate PlLk-focused or common-effects mission owns these.
- Young Link visual tweaks → **PlCl.dat** (mod 12904), never an EfCl file.
