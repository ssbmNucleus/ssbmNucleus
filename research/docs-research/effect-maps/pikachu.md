# Pikachu effect map (MAP-LIVE — 2026-07-02)

Mission: extras campaign, Pikachu electric effects. **LIVE pass complete.**
Down-B thunder (`PlPk.dat` 0xC350) is **ALREADY SHIPPED/verified** — NOT
remapped here. Offsets parser-/marker-verified vs `storage/test-base/files/`;
semantics now judged by live anti-color pokes (green `00FF00` / magenta
`FF00FF`). Probe spec: `backend/probes/pikachu_probe.json`. Capture dirs:
`tests/artifacts/datram-probe-pikachu/` (main sweep) +
`tests/artifacts/datram-probe-pikachu-airjolt/` (aerial-B re-boot).

## LIVE VERDICT SUMMARY (2026-07-02)

- **Aerial thunder-jolt CF group (0x168/0x1D0/0x238/0x2A0)** — 🟢 VERIFIED via
  AIRBORNE neutral-B (grounded neutral-B only fires the PlPk ground jolt — the
  main sweep's neutralb missed this). PRIM (marker+2, green pokes) = bright
  starburst core; ENV (colorpos+7, magenta pokes) = the outer radial lens glow
  (dominant tint, lesson 3 confirmed).
- **PlPk.dat ground thunder-jolt bolt (0x14E00/0x14ECC/0x14F98/0x15064 c1 +
  …E04/…ED0/…F9C/…068 c2, plus head 0x151F4)** — 🟢 VERIFIED. Grounded
  neutral-B: the traveling jolt bolt went green-arc + magenta, spawn starburst
  teal, cheek spark purple. Different HOME from the EfPk air CF group (separate
  file). Confirms open-lead #1.
- **fsmash electric arc — GROUND cluster 0x148xx (0x148E0/0x14C84/0x14D50/
  0x14E10 c1 + …E4/…88/…54/…14 c2)** — 🟢 VERIFIED. fsmash arc turned
  green+magenta; the AIR clone (0x17Cxx) did NOT change fsmash. Confirms
  0x148xx = GROUND fsmash.
- **fsmash AIR clone 0x17Cxx** — ⚪ DEAD for nair/dsmash (punching-bag 2026-07-02).
  Re-tested on a DK bag (nair + dsmash INTO the bag, dsmash connected DamageN3/
  DamageAir3): poking all 8 air-clone blocks green/magenta produced NO change to
  the dsmash burst (stayed blue/white; zero green, magenta = HUD-icon noise), and
  **Pikachu's nair has no electric arc GFX at all** (it's a plain spinning aerial
  — nothing for these blocks to color). So the air clone does not own nair or
  dsmash. Its true owning context (a different aerial 2nd-hit?) is still unknown,
  but the mission's "nair/dsmash arcs" label is confirmed WRONG. Not shippable as
  a nair/dsmash layer. Captures `tests/artifacts/extras-audit/Pikachu-airclone-bag/`.
- **skull-bash smoke CF group (0x35E/0x36B/0x4A7/0x4B4)** — 🔴 SKIP. Solo side-B
  charge+launch: smoke reads plain white/gray, NO visible change under the poke.
  Matches 15070 leaving it vanilla. NOT worth a purple layer.
- **skull-bash lens-flare sub-records (0x3D8/0x3E5/0x440)** — 🟡 the brief launch
  flash wasn't captured at frames [46,54,64] → EYEBALL if skull-bash is ever
  revisited, but lean skip (whole move reads non-electric).
- **quick attack (up-B)** — COMMON `EfCoData` (quarantine), not tested (not an
  EfPk layer).
- **dsmash electric burst** — ⚪ CONFIRMED NOT ANY EfPk COLOR-RECORD (re-confirmed
  bag 2026-07-02). dsmash into a DK bag (dx5): poking BOTH 070707 clusters at once
  — ground fsmash 0x148E0/0x14C84/0x14D50/0x14E10 AND air clone 0x17C60/0x18004/
  0x180D0/0x18190, all 16 offsets green(c1)/magenta(c2) — left the dsmash blue/
  white radial spark star **completely unchanged** (zero green/magenta at any
  frame f4-f20). Since every EfPk CF ptcl script (1-9) is thunder-jolt/skull-bash
  and both 070707 blue clusters are now ruled out, the dsmash burst is definitively
  **not any EfPk color-editable record.** It lives in a **98-matrix block** (the
  unlabeled electric-bolt geometry, 48 of them — NOT an RGB triple, so not
  poke-recolorable as a color layer) OR the **common `EfCoData` bank** (out of
  char scope). NOT shippable as an EfPk color extra. Captures:
  `tests/artifacts/datram-probe-pikachu-dsmash-burst/all_070707_clusters-dsmash-f08`
  vs `vanilla-dsmash-f08`. Spec: `backend/probes/pikachu_dsmash_burst_probe.json`.

**Net: 3 shippable groups (aerial jolt CF, PlPk ground jolt, ground fsmash arc).
Skull-bash smoke = skip. fsmash air clone + dsmash burst = pending.**

## Structural findings (read first)

`EfPkData.dat` (symbol `effPikachuDataTable`) parses cleanly:
`python skinlab/ptcl_parse.py EfPkData.dat --models` → version 0x42,
**10 ptcl generators**, `effect_id_start=7000`, tex_bank@0x4E0, **25 ptcl color
operands** + **83 model-region blocks** (past the ptcl bank). SHARED WITH PICHU.

**Move→effect cross-ref (decomp `ftPikachu/`):**
- `ftPk_SpecialN` (thunder jolt): `efSync_Spawn(1214)` / `1215`
  (`SpawnEffect0/1`). `ftPk_SpecialS` (skull bash) calls the SAME `SpawnEffect0/
  1` via `accessory4_cb` — so the jolt-spawn is reused for skull-bash charge.
- `ftPk_SpecialLw` (down-B thunder): `efSync_Spawn(1219)` — **SHIPPED, skip.**
- `ftPk_SpecialHi` (quick attack): `efSync_Spawn(1012)` — bank 1 =
  **common `EfCoData`**, gated `kind != PICHU`. Quick-attack streaks are a
  COMMON effect → **quarantine, out of char scope** (not an EfPk layer).
- fsmash / nair / dsmash electric arcs: **no fighter-code spawn** → they are
  EfPk **model-region** `070707` blocks (0x148E0…, reference-doc "Forward
  Smash" cluster). The move that owns each block is a hypothesis for LIVE.

**Bank-index caveat (do not over-trust the gfx map).** The fighter spawns use
`gfx_id 1214/1215/1219` = `gfx_id/1000 = 1` (fighter-relative bank slot), while
EfPk's on-disk `effect_id_start` is 7000. Index math (214/215/219) exceeds the
10 ptcl generators, so those spawns resolve into the **Models[]** array, not the
ptcl scripts. Which specific EfPk ptcl records vs model blocks each move draws
was NOT fully pinned statically — the reference-doc move labels below (authored
from prior in-game work) are the working hypothesis; LIVE confirms.

**15070 corroboration (all same-size, clean diff — lesson 4):** the "Purple
Electric Pack" recolored EfPk ptcl records 0x16F/0x1D0/0x238/0x2A0 and model
blocks 0x148E0/0x14C84/0x14D50/0x14E14 (+ air-variant clones 0x17C60…),
plus `PlPk.dat` ground neutral-B (0x14E00…) and 0x1519C. md5 EfPk: 14e631b4… /
e7c3a9f7….

---

## `EfPkData.dat` — ptcl records (symbol `effPikachuDataTable`, id_start 7000)

`CF` (PrimCol 0xCF, all-channel): primary color @marker+2, secondary (EnvCol
0xDF) @colorpos+7. Parser tag = (ptcl script index, opcode, ordinal). Reference-
doc semantics carried as hypotheses.

| layer_id | fmt | offsets (prim @ / env @) | vanilla prim / env | parser tag | hypothesized semantic (ref doc) | 15070 |
|---|---|---|---|---|---|---|
| jolt_air_mid | CF | 0x168 / 0x16F | FFFFFF / 6681FA | (s1,PRIMCOL,#0)/(s1,ENVCOL,#0) | Aerial neutral-B (thunder jolt, air) middle | env→AE00FF ✓ |
| jolt_air_outerflare | CF | 0x1D0 / 0x1D7 | 0B0BE6 / 07078F | (s2,PRIMCOL,#0)/(s2,ENVCOL) | Aerial N-B outer lens flare | prim+env ✓ |
| jolt_air_midflare | CF | 0x238 / 0x23F | 8FD6FF / 0C0CFF | (s3,PRIMCOL,#0)/(s3,ENVCOL) | Aerial N-B middle lens flare | prim+env ✓ |
| jolt_air_innerborder | CF | 0x2A0 / 0x2A7 | FE061B / FB9E14 | (s4,PRIMCOL,#0)/(s4,ENVCOL) | Aerial N-B inner border | prim+env ✓ |
| jolt_air_innertri | CF | 0x2AD (prim only, count=4) | FFFFFF | (s4,PRIMCOL,#1) | Aerial N-B inner triangles | (near 0x2B4 diff) |

> **🟢 `pikachu_thunder_jolt_air` VERIFY-BUILD CONFIRMED (2026-07-02, BAG-FIXED RE-TEST).**
> This extra was WIRED 2026-07-02 but previously UNVERIFIABLE — the frameshot
> driver had no jump-then-B recipe, so the air jolt never spawned in a verify
> build. The new `airneutralb` move in `ingame/moves.py` (jump to apex → B in
> the air) fixed that. `python devtools/extras_audit.py --char Pikachu --extra
> pikachu_thunder_jolt_air` (AUDIT_HINTS now `airneutralb:20,30,44,58`) builds
> the ISO and Pikachu enters CharSpecific_342 (aerial N-B); the spawn burst
> renders **vivid GREEN core + MAGENTA outer flare** = the forced
> `jolt_air_*_c1=00FF00` / `_c2=FF00FF` colors, exactly on the jolt lens-flare
> layers. Captures: `tests/artifacts/extras-audit/Pikachu-pikachu_thunder_jolt_air/`
> (`pikachu-airneutralb-f30.png`, `-f44.png`). Extra is SHIPPED & verified.

| skullbash_smoke1 | CF | 0x35E / 0x365 | FFFFFF / F96801 | (s6,PRIMCOL,#0)/(s6,ENVCOL,#0) | Over-B (skull bash) smoke majority | — |
| skullbash_smoke2 | CF | 0x36B / 0x372 | FC8A55 / 840000 | (s6,PRIMCOL,#1)/(s6,ENVCOL,#1) | Over-B outline/ending smoke | — |
| skullbash_midflare | CF | 0x3D8 / 0x3DF | FCF88D / F8CF02 | (s7,PRIMCOL,#0)/(s7,ENVCOL,#0) | Over-B middle lens flare | — |
| skullbash_endflare | CF | 0x3E5 / 0x3EC | F7030B / 840000 | (s7,PRIMCOL,#1)/(s7,ENVCOL,#1) | Over-B ending lens flare | — |
| skullbash_startflare | CF | 0x440 / 0x447 | FFFFFF / F8CF02 | (s8,PRIMCOL,#0)/(s8,ENVCOL,#0) | Over-B starting lens flare | — |
| skullbash_lines1 | CF | 0x44D / 0x454 | FD6368 / 840000 | (s8,PRIMCOL,#1)/(s8,ENVCOL,#1) | Over-B lines | — |
| skullbash_lines2 | CF | 0x4A7 / 0x4AE | FFFFFF / F96801 | (s9,PRIMCOL,#0)/(s9,ENVCOL,#0) | Over-B lines | — |
| skullbash_lines3 | CF | 0x4B4 / 0x4BB | FC8A55 / 840000 | (s9,PRIMCOL,#1)/(s9,ENVCOL,#1) | Over-B lines | — |

> The `_air` prefix (scripts 1-4) = **aerial thunder jolt** = one of the mission
> targets (thunder jolt ground+air). 15070 recolored exactly these 4, strong
> signal. `skullbash_*` (scripts 6-9) = **skull bash charge/launch** (over-B) —
> mission target; 15070 left these vanilla (they read as white/orange smoke, not
> electric), consistent with "purple ELECTRIC" only touching electric bits, so
> skull-bash smoke is a real candidate but unconfirmed by the mod diff.

## `EfPkData.dat` — model-region candidates (`070707`; c1@marker+4, c2@marker+8)

| layer_id | fmt | offsets (marker → c1 → c2) | vanilla c1 / c2 | hypothesized (ref doc) | 15070 |
|---|---|---|---|---|---|
| fsmash_pre | 070707 | 0x148DC → 0x148E0 / 0x148E4 | CCE5FF / 0000FF | Pre-fsmash lightning | c1→FFFFFF,c2→…AE ✓ |
| fsmash_aura1 | 070707 | 0x14C80 → 0x14C84 / 0x14C88 | CCE5FF / 0000FF | Fsmash aura half 1 | ✓ |
| fsmash_aura2 | 070707 | 0x14D4C → 0x14D50 / 0x14D54 | CCE5FF / 0000FF | Fsmash aura half 2 | ✓ |
| fsmash_ball | 070707 | 0x14E0C → 0x14E10 / 0x14E14 | FFFFFF / 004CFF | Fsmash ball/head | c2→AE00 ✓ |
| (air clone) fsmash_pre_air | 070707 | 0x17C5C → 0x17C60 / 0x17C64 | CCE5FF / 0000FF | AIR clone — 🟡 unverified (did NOT drive fsmash/nair/dsmash solo) | ✓ |
| (air clone) fsmash_aura1_air | 070707 | 0x18000 → 0x18004 / 0x18008 | CCE5FF / 0000FF | air variant | ✓ |
| (air clone) fsmash_aura2_air | 070707 | 0x180CC → 0x180D0 / 0x180D4 | CCE5FF / 0000FF | air variant | ✓ |
| (air clone) fsmash_ball_air | 070707 | 0x1818C → 0x18190 / 0x18194 | FFFFFF / 004CFF | air variant | c2→AE00 ✓ |

> The 0x148xx and 0x17Cxx clusters are byte-identical structurally — a
> ground/air (or two-hit) duplication of the same electric-arc model. The
> mission's "nair/dsmash electric arcs" target is a hypothesis for one of these
> model blocks OR the 98-matrix bolt geometry between 0x14EC0-0x15DE0 /
> 0x180xx-0x1B0xx (48 total 98-matrix blocks, unlabeled). LIVE: poke fsmash
> first (best-labeled), then nair/dsmash to see which clones respond.
>
> There are additional lone `4248` (0x13F14 — near the very first model) and
> `98-matrix` blocks; not primary candidates. The 15070 diff at 0x13F14
> (`808080FFFFFF`→`FFFFFFFFAE00`) is a material recolor adjacent to the fsmash
> group — follow-up sub-layer.

---

## AUDIT_HINTS (for LIVE / WIRE)

- Pikachu ckind via `resolve_ckind("pikachu")`. Effects are electric-blue
  (0000FF/004CFF/6681FA), so anti-color **green `00FF00`** + **magenta
  `FF00FF`** (lesson 6).
- Moves + suggested frames (LIVE tightens, lesson 10):
  - `neutralb` (thunder jolt): ground [8, 16, 26, 40]; **also test airborne**
    (jump then B) for the `_air` scripts / PlPk ground blocks.
  - `sideb` (skull bash — hold to charge, release): [charge 20, 40; launch 6,
    14, 24 after release] with a B-hold+release input.
  - `fsmash`: [6, 12, 18, 26] (electric arc + ball).
  - `nair`, `dsmash`: [6, 12, 20, 30] — to attribute the electric-arc clones.
  - `upb` (quick attack): streaks are COMMON `EfCoData` (quarantine) — poke
    only to CONFIRM they don't respond to EfPk edits.
  - **DO NOT test down-B** as a mapping target (shipped).
- One experiment per candidate group; whichever move lights green/magenta names
  the block. Flag ambiguous captures for EYEBALL.

## Shippable-now summary (for WIRE)

Three live-verified groups. All per-record vanilla bytes byte-verified from disk
2026-07-02 (they DIFFER across records — split per record, lesson 12).

### Extra `pikachu_thunder_jolt` — target `EfPkData.dat` + `PlPk.dat` — 🟢 VERIFIED

Two homes for the same conceptual move (thunder jolt): the AERIAL variant lives
in EfPk CF records, the GROUND bolt in PlPk. Suggest ONE extra with a shared
color that writes BOTH homes so ground+air stay consistent, OR two sub-controls.

**EfPk aerial-jolt CF (fmt `CF`: prim @marker+2 = core, env @colorpos+7 = glow;
env dominates the sustained tint):**

| layer_id | prim off | prim vanilla | env off | env vanilla | tag |
|---|---|---|---|---|---|
| jolt_air_mid | 0x168 | `FFFFFF` | 0x16F | `6681FA` | (s1) |
| jolt_air_outerflare | 0x1D0 | `0B0BE6` | 0x1D7 | `07078F` | (s2) |
| jolt_air_midflare | 0x238 | `8FD6FF` | 0x23F | `0C0CFF` | (s3) |
| jolt_air_innerborder | 0x2A0 | `FE061B` | 0x2A7 | `FB9E14` | (s4) |
| jolt_air_innertri | 0x2AD (prim only) | `FFFFFF` | — | — | (s4 #1) |

**PlPk ground-jolt bolt (fmt `070707`: c1 @marker+4, c2 @marker+8):**

| layer_id | c1 off | c1 vanilla | c2 off | c2 vanilla |
|---|---|---|---|---|
| jolt_gnd_a | 0x14E00 | `B2E5FF` | 0x14E04 | `0000FF` |
| jolt_gnd_b | 0x14ECC | `B2E5FF` | 0x14ED0 | `0000FF` |
| jolt_gnd_c | 0x14F98 | `B2E5FF` | 0x14F9C | `0000FF` |
| jolt_gnd_d | 0x15064 | `B2E5FF` | 0x15068 | `0000FF` |
| jolt_gnd_head | 0x151F4 | `004CFF` (single, cyan-poked) | — | — |

`AUDIT_HINTS`: `pikachu neutralb ground frames [26,40]` (bolt visible), AND
`airborne (jump then B) frames [24,34]` for the EfPk CF core+glow. Anti-colors
per-operand (lesson 11): CF prim is white/blue → green/magenta OK; CF env is
blue/orange (jolt_air_innerborder env is ORANGE `FB9E14` — magenta is a good
anti-color, green would be too close-ish, prefer magenta); 070707 c1 is pale-cyan
`B2E5FF`, c2 is `0000FF` → green/magenta both far.

### Extra `pikachu_fsmash` (electric_arc) — target `EfPkData.dat` — 🟢 VERIFIED

Ground fsmash arc, `070707` cluster (fmt: c1 @marker+4, c2 @marker+8):

| layer_id | c1 off | c1 vanilla | c2 off | c2 vanilla |
|---|---|---|---|---|
| fsmash_pre | 0x148E0 | `CCE5FF` | 0x148E4 | `0000FF` |
| fsmash_aura1 | 0x14C84 | `CCE5FF` | 0x14C88 | `0000FF` |
| fsmash_aura2 | 0x14D50 | `CCE5FF` | 0x14D54 | `0000FF` |
| fsmash_ball | 0x14E10 | `FFFFFF` | 0x14E14 | `004CFF` |

Grouping: c1 (pale-cyan core) + c2 (blue arc glow) columns, each writing all 4
records. `AUDIT_HINTS`: `pikachu fsmash frames [12,18]`. Anti-colors green/magenta
(far from blue/pale-cyan). **Do NOT** bundle the air clone 0x17Cxx (byte-identical
vanilla but unverified — see pending section); ship ground-only for now.

### Extra `pikachu_skull_bash` — 🔴 SKIP

Solo LIVE: smoke reads plain white, no electric response. 15070 left it vanilla.
Do not wire unless a punching-bag/lens-flare EYEBALL pass reverses this.

## EfCoData quarantine — NEVER a Pikachu (or Ness) layer

15070 recolors `EfCoData.dat` (cast-shared common electric/fire effects). Both
Pikachu **quick attack** (`efSync_Spawn(1012)`) and Ness **PK Thunder** hit
sparks (`1030/1262/1263`) draw from EfCoData. These are **common-effects, out
of char scope** — flag any move whose spark comes from here, never propose the
offsets as char layers. Diff clusters (vanilla `EfCoData` md5 739290ea… vs
15070 d1dd8ecd…, same-size, 148 bytes / 43 clusters), for reference only:

```
ptcl bank:  0xDC5 0xDDB 0xDF1 0xE0F 0xE1D 0xEAD 0x1033 0x12AF
            0x1384 0x13AB 0x13BA 0x13D7 0x1425 0x148D 0x14A1 0x14F5
            0x1560 0x15BA 0x1609 0x1C17 0x1C24 0x1C8D 0x1C9A 0x1CFF
            0x2F15 0x5550 0x55B1 0x854E 0x855B 0x85B6 0x860E 0x9779
            0xA1DD 0xCDB7 0xCE18 0xCE84 0xCEEF 0xCFEC 0xD87D 0xD897 0x10019
material:   0x115AA8 0x115B74  (808080/B3B3B3 → FFFFFF/AE00FF)
```
All are `AD DF`-ENVCOL-pattern electric/spark records in the common bank. This
list is shared reference for the Ness quarantine too.

## Open leads (post-LIVE)

1. **RESOLVED:** aerial jolt CF = EfPk (air B), ground jolt bolt = PlPk (ground
   B) — different homes, both verified.
2. **RESOLVED:** 0x148xx = GROUND fsmash (verified). 0x17Cxx air clone = ⚪ DEAD
   for nair/dsmash (punching-bag 2026-07-02 — dsmash burst unchanged on a
   confirmed hit; Pikachu nair has no electric arc to color). Its true owning
   context (a different move / aerial 2nd-hit) remains unknown — do NOT ship it.
   dsmash burst = separate unattributed effect. RE-CONFIRMED 2026-07-02: NOT any
   EfPk color-record (both 070707 clusters poked together = no change; all CF
   scripts are jolt/skull-bash). It is a 98-matrix block (non-RGB-triple, not a
   color layer) or common-bank. Closed as "not an EfPk color extra"; if ever
   wanted, needs a 98-matrix/texanim path or an EfCoData probe, not a color poke.
3. **RESOLVED:** skull-bash smoke reads plain white solo → SKIP. Lens-flare
   sub-records (0x3D8/0x3E5/0x440) EYEBALL-pending (brief flash not captured).
4. 48 unlabeled `98-matrix` blocks — follow-up sub-layers + candidate home for
   the unattributed dsmash electric burst.
