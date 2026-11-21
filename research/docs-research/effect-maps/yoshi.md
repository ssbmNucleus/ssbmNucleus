# Yoshi effect map (MAP-LIVE complete — both ptcl candidates DEAD)

Mission: extras campaign, Yoshi effects. **LIVE done 2026-07-02.** Offsets are
parser-verified vs `storage/test-base/files/EfYsData.dat`. Probe spec:
`backend/probes/yoshi_probe.json`. Captures: `tests/artifacts/datram-probe-yoshi/`.

## LIVE VERDICT (headline): both EfYs colorable candidates are visually DEAD.

Poked `egg_throw_core` (0xAA→green / 0xB1→magenta) and `egg_flash`
(0x112..0x162→green) live via effect_probe; readbacks OK. Across every reachable
capture (sideb / downb, frames 8–54) **neither poke changed anything on screen.**
Root cause matches the STATIC prediction: **Yoshi's visible egg is a per-costume
MODEL** (`PlYs<color>.dat` green-spot texture), not an EfYs ptcl puff — the thrown
egg at `egg_throw_core-sideb-f26` stayed vanilla green-spot-white despite the
poke. No white hatch-flash (`egg_flash` script 1) ever appears in the reachable
moves; it is either a subaction-data spawn tied to the egg-LAY state (which the
solo harness cannot trigger — Yoshi neutral-B egg-lay needs a grabbed-egg
input; the moves driver's neutralb slid Yoshi off → RebirthWait every rep) or is
consumed at load. **Not shippable as a Yoshi color layer.** WIRE: ship NOTHING
for Yoshi from this file.

Harness note: the moves driver's `sideb`/`downb` for Yoshi mostly fire his
double-jump / flutter (egg roll needs a held input; egg lay needs grab), so a
clean egg-lay hatch-puff was never reachable. One `sideb` rep did throw an egg
(seen unrecolored) — confirming the egg is a model, closing the loop.

## Structural findings (read first)

`EfYsData.dat` (symbol `effYoshiDataTable`) parses cleanly:
`python skinlab/ptcl_parse.py EfYsData.dat --models` → version 0x42,
**4 ptcl generators only**, `effect_id_start=9000` (0x2328), tex_bank@0x220,
**16 ptcl color operands** + 6 model-region blocks. Yoshi's char bank is TINY —
almost all of Yoshi's visible effects (egg-lay/roll sparkle, bomb stars, tongue)
route to the **common bank `EfCoData`**, not this file (see quarantine).

**Move→effect cross-ref (decomp `ftYoshi/` + `it/items/` + `ef/efsync.c`).**
The gfx_id a fighter/item passes to `efSync_Spawn` is remapped by the big
`efsync.c` dispatcher to a *global* effect id; `0x2328` (=9000) is Yoshi's bank
base. Grepping the whole decomp, the ONLY spawn that lands in EfYs is:

- `ityoshieggthrow.c:133` `efAsync_Spawn(gobj, …, 1, 0x4CE, jobj)` →
  `efsync.c case 0x4CE: efLib_CreateGenerator(0x2328)` = **EfYs ptcl script 0**.
  → Yoshi's thrown-egg spawn/hatch flash (script 0's tinted puff).
  (`case 0x4CD` also maps to 0x2328 but no caller was found — likely a
  subaction-data spawn or unused.)

Everything else Yoshi is COMMON bank (quarantine section below):
- `ityoshiegglay.c` egg-lay sparkle: `efAsync_Spawn(…, 4, 1231, …)` (gfx 1231,
  the shield-star burst reused from `ftYs_Guard`) — **common**.
- `itegg.c:277` `efSync_Spawn(1232)` — egg shell/roll — **common**.
- `ftYs_SpecialS.c` egg-roll trail: `efSync_Spawn(0x3FF/0x406/0x4CF)` — these
  gfx_ids dispatch to common/low global ids (0x1C–0x1F cluster in `efsync.c`
  case 0x4CF), NOT 0x2328 — **common**.
- `ityoshistar.c` (Yoshi Bomb stars) — check LIVE which bank; no EfYs spawn
  found, so bomb stars are almost certainly **common** (star-burst shared art).
- Rainbow dair trail — no EfYs ptcl spawn; likely a `PlYs*.dat` model/texture
  trail (per-costume), not a colorable Ef operand. **Out of Ef scope**; flag.

**Egg *model* colors (egg-lay/roll shield tint) live in `PlYs<color>.dat`**, one
per costume (reference mod 15750 "Multicolored Egg Shields/Egg Rolls" recolors
`PlYsBu/Aq/Re/Ye/Pi.dat`, NOT any Ef file). That is a per-costume player-file
recolor, a different subsystem from this Ef bank — noted for completeness, not a
shippable single-file Ef layer.

**Reference-mod corroboration: NONE for the ptcl bank.** 17025 EfYs is
byte-identical to vanilla in the ptcl bank (<0x220); 14328/15667 EfYs diffs are
all texture/model region. So these rows rest on parser structure + decomp
cross-ref, verified LIVE by poke.

---

## `EfYsData.dat` — ptcl records (symbol `effYoshiDataTable`, id_start 9000)

`CF` = PrimCol 0xCF all-channel; the parser reports the **color-byte offset**
(RGBA), verified: opcode `CF <count>` sits 2 bytes before. EnvCol (0xDF) color
sits at prim+7. Poke the listed offset directly (3-byte RGB write).

| layer_id | fmt | offsets (prim @ / env @) | vanilla prim / env | parser tag | LIVE verdict |
|---|---|---|---|---|---|
| egg_throw_core | CF | 0xAA / 0xB1 | FEF777 / FB0F1E | (s0,PRIMCOL,#0)/(s0,ENVCOL,#0) | **DEAD** — poked green/magenta, no visible change; thrown egg is a PlYs model, not this puff. Capture: `datram-probe-yoshi/egg_throw_core-sideb-f*.png` |
| egg_flash | CF | 0x112, 0x11B, 0x126, 0x12F, 0x13A, 0x143, 0x14E, 0x157, 0x162, 0x16B (all prim, alt FFFFFF/FFFFFF-A00) | FFFFFF | (s1,PRIMCOL,#0..#9) | **DEAD (unreached)** — poked 5 steps green, no flash ever appeared in sideb/downb. Owner is the egg-LAY hatch (subaction spawn) which the solo harness can't trigger. Capture: `datram-probe-yoshi/egg_flash-*.png` |
| egg_alpha2 | BYTE(A) | 0x1B9 (FF) / 0x1BD (00) | alpha-only | (s2,PRIMCOL A) | script 2 alpha-only PrimCol (no RGB) — a fade envelope, NOT a color. Skip for recolor. |
| egg_alpha3 | BYTE(A) | 0x201 (FF) / 0x205 (00) | alpha-only | (s3,PRIMCOL A) | script 3 alpha-only, same as s2. Skip. |

Only **egg_throw_core** and **egg_flash** are colorable. Scripts 2/3 are
alpha-only fade envelopes.

**AUDIT_HINTS (LIVE):** egg throw = `sideb` (Yoshi's egg lay is down-B in some
control schemes; egg *throw* is the follow-up. In `moves.py` the harness fires
`sideb`/`downb` — try both). Egg-lay/roll = `downb`/`sideb`. Anti-colors: prim
vanilla is yellow-white (FEF777) → poke deep green 00FF00 / magenta env.

## Model-region blocks (past ptcl bank, <0x2378..>)

6 blocks reported by `--models`; all in the tiny model region. Not chased
statically (Yoshi bank has almost no drawn-geometry effects). Open lead if a
LIVE poke of the ptcl scripts comes up short.

## Quarantine — Yoshi effects that are COMMON bank (`EfCoData.dat`), NOT EfYs

These must NOT ship as Yoshi layers (they'd recolor the whole cast):
- egg-lay sparkle (gfx 1231, shield-star), egg shell/roll (gfx 1232),
  egg-roll trail (gfx 0x3FF/0x406/0x4CF), Yoshi Bomb stars (star-burst art).
All resolve into `EfCoData` (`effect_id_start=0`, 592 generators). A future
common-bank mission owns these; a Yoshi-only recolor of them is impossible
without a per-fighter effect-table override.

## Shippable-now summary (for WIRE)

**NOTHING is WIRE-ready for Yoshi.** Both EfYs ptcl candidates are visually DEAD
(model, not Ef / unreachable subaction spawn). Do not add any Yoshi extra_type
from `EfYsData.dat`. Yoshi's egg color is a per-costume `PlYs<color>.dat` model
recolor (different subsystem, out of the Ef-extras scope) — flag to whoever owns
player-file recolors, not this campaign.

## Open leads (not blocking WIRE — nothing ships)
- egg_flash (script 1) may be the egg-LAY hatch flash; only reachable if the
  harness gains a grabbed-egg / egg-lay trigger. Low priority (single brief
  flash, likely subtle even if colorable).
- Rainbow dair trail: inspect `PlYs.dat` for a colorable trail material
  (separate mission — player file, not Ef).
