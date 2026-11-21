# EfGnData.dat — Ganondorf effects (MAP-STATIC draft)

**Target file:** `storage/test-base/files/EfGnData.dat`
(`effGanonDataTable`, bank index **19** in `efAsync_DatEntries`, `efasync.c:1165`).
**`effect_id_start = 19000` (0x4A38)** → **script index = gfx_id − 19000**.
17 generators (script indices 0–16). Header: `EffectTable@0x20 ParticleGroup@0xA0
version=0x42 tex_bank@0x9E0`.

Status: **LIVE pass DONE (2026-07-02, MAP-LIVE final batch).** Parser confirmed every
draft offset byte-exact (ptcl_parse cross-check clean). Marquee **warlock_punch =
🟢 CONFIRMED**; the two secondary specials (Wizard's Foot, Gerudo dragon) do NOT recolor
at the draft's script-2/4 offsets — the visible dash-trail + grab-burst live on OTHER
scripts (one lead found: **script 6 = Wizard's Foot foot-fire, recolors**). See §LIVE.
Probe specs: `backend/probes/ganondorf_probe.json` (bag, all groups), `ganondorf_probe_solo.json`
(no-bag clean-timing, warlock+wizfoot), `ganondorf_probe_gerudo.json`,
`ganondorf_probe_leads.json` (open-lead sweep).

## LIVE results (verdicts + capture dirs)

**Harness note (important for reproducing / for WIRE verify builds):** the punching-bag
carries knockback percent across reps, which *desyncs frame timing* between the vanilla
control and a poked experiment in the same boot (lesson-14 corollary). For SOLO-visible
moves (Warlock Punch charge, Wizard's Foot dash) run **no-bag** so frames align; the
`_solo` specs do this. For on-connect bursts run the poked experiment FIRST (before any
off-stage carryover) — see `_gerudo`/`_freeze`.

| Group | scripts | offsets | verdict | evidence |
|---|---|---|---|---|
| **warlock_punch** (fist explosion) | 0+1 | 0x154–0x269 | **🟢 CONFIRMED** | poked green burst replaces vanilla purple on the punch's connect burst — `probe-ganondorf/warlock_punch-neutralb-f50.png` vs `vanilla-neutralb-f70.png`. NOTE: the fist-explosion fires on the *victim at connect* (needs the bag OR a target); the f30 solo *charge starburst* is a DIFFERENT unpoked script and stayed purple. |
| **wizards_foot** (draft script 2) | 2 | 0x306–0x31D | **🔴 DEAD at these offsets** | solo dash-trail stayed purple with pokes active+readback-OK — `probe-ganondorf-solo/wizards_foot-downb-f26.png` vs `vanilla-downb-f26.png`. The visible purple foot-trail is NOT script 2. |
| **wizards_foot foot-fire** (NEW lead) | 6 | 0x4CF/0x4D6 | **🟢 CONFIRMED (partial)** | poking script 6 green → green foot-fire streaks appear under Ganon during the dash — `probe-ganondorf-leads/leads_downb-downb-f24.png` & `-f30.png`. (The big purple impact starburst is still another unpoked script.) |
| **gerudo_dragon** (draft script 4) | 4 | 0x3CC–0x3E3 | **🔴 DEAD at these offsets** | the grab-connect burst stayed purple with pokes active — `probe-ganondorf-gerudo/gerudo_dragon-sideb-f22.png` & `-f28.png`. Visible Gerudo burst is on an unidentified script (open lead; leads sweep didn't reconnect the grab to attribute it). **SUPERSEDED — real owner found: s12/14/15/16 (0x76C–0x9BC), ✅ WIRE-READY, see §5b NARROW CONFIRM.** |

Draft (pre-LIVE) note below retained for reference; the tables in §2 keep their vanilla
bytes (all byte-verified) but only the **warlock_punch** and **script-6** rows are LIVE-green.

## 0. Headline findings

1. **Ganondorf is a Falcon clone that reuses ftCaptain code entirely.** `ftGanon/`
   in the decomp has only `ftGn_Init.c` (motion-state table); every special runs
   the `ftCaptain/ftCa_Special*.c` functions, which branch on `ftLib_800872A4`
   (`FTKIND_CAPTAIN` vs `FTKIND_GANON`) and spawn a **different symbolic effect id
   per fighter, offset by exactly +124 (0x7C)**: Falcon `1167/1169/1170/1171/0x490`
   → Ganon `1291/1293/1294/1295/0x50C`. Those symbolic ids resolve (in
   `ef/efsync.c`, the Ganon block, and `ef/efalt.c` for the Falcon block) to
   **EfGn gfx 0x4A38–0x4A3D = scripts 0–5**. This is the authoritative script→move
   map below (Falcon's own map lives in `extra_types.py` "C. Falcon").

2. **NOT byte-identical to Falcon** — the operands are genuine dark/purple recolours
   at the parallel script indices (Falcon orange `FF7F00` → Ganon purple `280021`,
   `47004F`, `A200AB`, `9406CC`, magenta `CA07FF`/`FF80FB`). So each script has real
   vanilla purple bytes to map; treat like Falcon's ptcl layers, not a texture clone.

3. **Colour layout = CF/DF ptcl operands** (`CF <interp> RRGGBB AA AD DF …` /
   `DF …`). The **RGB byte is at the parser's `file_off`** (the config-CF form would
   use `file_off−2`, but the LIVE probe pokes RGB directly at `file_off`, so the
   offsets in the probe/table below ARE the RGB starts). PRIMCOL (0xCF) = birth/bright,
   ENVCOL (0xDF) = sustained env tint (dominates the fade), mirroring Falcon's
   `_c1`/`_c2` split.

## 1. Script → move map (decomp-verified spawns)

| Script | gfx_id | Symbolic (Ganon) | Falcon twin | Move / caller | ptcl colours |
|---|---|---|---|---|---|
| **0** | 0x4A38 | 0x50B (`efSync_Spawn(1291)`) | 0x48F→0xFA0 | **Warlock/Falcon Punch** dark aura (SpecialN, TopN joint) — paired w/ 1 | 6 |
| **1** | 0x4A39 | 0x50B (2nd of pair) | 0x48F→0xFA1 | **Warlock Punch** 2nd cluster (fist explosion) | 6 |
| **2** | 0x4A3A | 0x50C (`efAsync_Spawn 0x50C`) | 0x490→EfCa | **Wizard's Foot** (SpecialLw, down-B) dark trail | 4 |
| **3** | 0x4A3B | 0x50D (`efSync_Spawn(1293)`) | 0x491→0xFA4 | **Gerudo/Flame Choke startup** (SpecialS start, L2ndNb) — **0 colour operands = TEXTURE-ONLY** | 0 |
| **4** | 0x4A3C | 0x50E (`efSync_Spawn(1294)`) | 0x492→0xFA3 | **Gerudo dragon, grounded** (SpecialS_Anim, TransN + facing_dir) | 4 |
| **5** | 0x4A3D | 0x50F (`efSync_Spawn(1295)`) | 0x493→0xFA5 | **Gerudo dragon, aerial** (SpecialAirS_Anim, TransN) | 10 |

Scripts **6–16** have NO attributable ftCaptain-special caller — they are spawned by
generic/shared paths (aerial-attack sparks, up-B, on-hit fire shared with the
`hsd_8039EFAC` generic dispatcher). Left as **open leads**, not layers, pending LIVE.

## 2. Candidate colour tables (per-record vanilla bytes; RGB = probe offset)

### neutralb — Warlock/Falcon Punch (scripts 0 + 1) — dark aura
Solo-visible (no bag needed). This is the marquee dark aura.

| Layer | offset | op | vanilla RGB | note |
|---|---|---|---|---|
| punch_c1 | 0x154 | PRIM | `280021` | dark-purple core (birth) |
| punch_c2 | 0x15B | ENV  | `11002E` | purple env tint |
| punch_c1b| 0x161 | PRIM | `47004F` | purple mid |
| punch_c2b| 0x168 | ENV  | `130245` | deep purple env |
| punch_c1c| 0x192 | PRIM | `000000` | black fade |
| punch_c2c| 0x199 | ENV  | `1B0245` | purple fade env |
| fist_c1  | 0x224 | PRIM | `A200AB` | magenta-purple fist explosion |
| fist_c2  | 0x22B | ENV  | `400591` | purple env |
| fist_c1b | 0x231 | PRIM | `75039C` | purple |
| fist_c2b | 0x238 | ENV  | `280587` | purple env |
| fist_c1c | 0x262 | PRIM | `000000` | black fade |
| fist_c2c | 0x269 | ENV  | `540775` | purple fade env |

### downb — Wizard's Foot (script 2) — dark kick trail
Solo-visible.

| Layer | offset | op | vanilla RGB | note |
|---|---|---|---|---|
| wizkick_c1 | 0x306 | PRIM | `FF80FB` | pink-magenta core |
| wizkick_c2 | 0x30D | ENV  | `A20CFF` | purple env |
| wizkick_c1b| 0x316 | PRIM | `FF70DC` | magenta |
| wizkick_c2b| 0x31D | ENV  | `B005FF` | purple env |

### sideb — Gerudo / Flame Choke (scripts 3 tex-only, 4 grounded, 5 aerial)
Script 3 = texture-only (no operands) → flag for texGroup recolor, not ptcl.
Scripts 4/5 are the dragon burst — largely on the move but the *bite* connects, so
**bag-recommended** to confirm the on-hit dragon visual against a `--vanilla` control.

Script 4 (grounded dragon):
| Layer | offset | op | vanilla RGB | note |
|---|---|---|---|---|
| dragon_c1 | 0x3CC | PRIM | `CA07FF` | magenta dragon body |
| dragon_c2 | 0x3D3 | ENV  | `E9C0FF` | pale-lilac env |
| dragon_c1b| 0x3DC | PRIM | `ECD1FF` | near-white lilac |
| dragon_c2b| 0x3E3 | ENV  | `A007FF` | purple env |

Script 5 (aerial dragon) — 10 operands, but note the PRIMs are grayscale
(`FFFFFF`/`7A7D7A`/`7D7D7D`/`5E5E5E`/`404040`) tinted by the tan/purple ENVs; this
looks like the **smoke/dust cloud** of the dragon (env-driven), analogous to Falcon
script 0. Probe the ENVs, not just PRIMs:
| Layer | offset | op | vanilla RGB | note |
|---|---|---|---|---|
| dragon_smoke_c1 | 0x42F | PRIM | `FFFFFF` | white smoke (env-tinted) |
| dragon_smoke_c2 | 0x436 | ENV  | `D2CE9E` | tan env (shared w/ Falcon smoke) |
| dragon_smoke_c1b| 0x449 | PRIM | `7A7D7A` | gray |
| dragon_smoke_c2b| 0x450 | ENV  | `6F6639` | olive env |
| (further PRIM/ENV at 0x459/0x460/0x46C/0x473/0x47C/0x483 — mostly black ENV, gray PRIM) |

## 3. AUDIT_HINTS (frame windows from LIVE session)
- `neutralb`: Warlock Punch connects ~f70; the fist-explosion burst fires on the victim.
  **Bag needed** (`bag dk, dx 11`) to demonstrate — capture `[50,70,80,90]`. Anti-color: green
  (vanilla magenta/purple). (Solo charge starburst at ~f30 is a different unpoked script.)
- `downb`: Wizard's Foot foot-fire (script 6) shows during the dash; capture `[12,18,24,30]`.
  Anti-color: green (vanilla white/purple).

## 4. Editor grouping (WIRE) — SHIP ONLY THE LIVE-GREEN GROUPS

**`warlock_punch`** (DualColor, 🟢) — scripts 0+1 fist-explosion.
- `_c1` (PRIM birth/bright, 6 records): 0x154 `280021`, 0x161 `47004F`, 0x192 `000000`,
  0x224 `A200AB`, 0x231 `75039C`, 0x262 `000000`.
- `_c2` (ENV sustained, 6 records): 0x15B `11002E`, 0x168 `130245`, 0x199 `1B0245`,
  0x22B `400591`, 0x238 `280587`, 0x269 `540775`.
- Anti-colors: `_c1`→green `00FF00`, `_c2`→green `00FF00` (any far-from-purple works).
- NOTE per-record vanilla bytes DIFFER (two `000000` blacks + several distinct purples) —
  WIRE must key each record separately, NOT one grouped vanilla (lesson 12).

**`wizards_foot`** (DualColor, 🟢 partial — script 6 only) — Wizard's Foot foot-fire.
- `_c1` (PRIM): 0x4CF `FFDEFF`. `_c2` (ENV): 0x4D6 `3D0261`. Anti-color: green.
- This covers the green-confirmed foot-fire streaks only; the larger purple impact
  starburst is a still-unattributed script (open lead — leave out of the shipped group).

## 4b. DO NOT SHIP (LIVE-dead / harness-blocked)
- **wizards_foot draft script 2** (0x306–0x31D): DEAD — poke had no visible effect. Drop.
- **gerudo_dragon draft script 4** (0x3CC–0x3E3): DEAD — grab-burst unchanged. Drop. The
  visible Gerudo burst is on an unidentified script; needs a follow-up MAP pass that
  reliably reconnects the grab (bag DownAttack-recovery interfered with attribution here).
- Script 3 = texture-only (0 operands) — texGroup recolor only, not a ptcl layer.
- 190 model-region blocks (Gerudo dragon-head + wizard's-foot geometry) = model recolor,
  out of scope.

## 5. Nana/Popo note (shared file)
Ganondorf is single-fighter — no Nana/Popo split concern. (That note applies to Ice
Climbers; see iceclimbers.md.)

## 5b. Gerudo burst owner sweep (2026-07-02) — 🔧 HARNESS-BLOCKED (grab-reconnect)

Attempted to attribute the visible Gerudo dragon burst (magenta/purple flame that
engulfs the victim on the command grab) by sweeping all remaining unattributed
scripts in 2 grouped green pokes: **sweep_A = s7/s9/s10/s11** (0x52F–0x708),
**sweep_B = s12/s14/s15/s16** (0x76C–0x9BC). Spec:
`backend/probes/ganondorf_gerudo_burst_probe.json`. Captures:
`tests/artifacts/datram-probe-ganondorf-gerudo-burst/`.

**Result: BLOCKED — same grab-reconnect failure as the earlier `_gerudo` pass.**
The VANILLA rep connected cleanly (DK → 17%, and the purple/magenta Gerudo dragon
flame aura renders around the grabbed victim — `vanilla-sideb-f20/f26`, confirming
the burst is real). But the Gerudo is a COMMAND GRAB: the first slam knocks DK
into `DownAttackU` (getting up from a knockdown), and neither sweep rep could
re-grab a downed bag — sweep_A caught only throw/tumble states (DK as the standard
darkened-shadow grabbed silhouette + white smoke, NOT the ptcl dragon), and
sweep_B whiffed entirely (Ganon slid off → RebirthWait, move errored). So there is
**no clean poked-Gerudo-connect to compare against the vanilla burst** — the sweep
is inconclusive, NOT a dead-offset result. The purple silhouette that persists in
sweep_A is the grabbed-victim shadow/darkening (a fighter render state), not any
EfGn ptcl script, so it does not attribute the burst either.

**Un-block needs:** one experiment per boot with a guaranteed fresh grab (bag reset
to Wait + repositioned in front each boot, not carried across reps within a boot),
OR a scripted target that stays grabbable. The current bag harness force-parks the
victim but a command-grab still requires the grab to LAND, and a knocked-down bag
can't be re-grabbed. This is a genuine harness limitation for command-grab bursts
(distinct from the on-connect-hit bursts the bag handles fine). The Gerudo burst
owner among s7/9/10/11/12/14/15/16 remains UNIDENTIFIED.

### RE-SWEPT 2026-07-02 (BAG-PIN) — 🟡 GERUDO FLAME AURA = s12/14/15/16; smoke = s7/9/10/11

The new `--bag-pin` harness option (`"bag":{...,"pin":true}` in the probe spec;
zeros the bag's knockback velocity + re-pins its position every frame — see
efcodata.md and `ingame/gamestate.py Bag.pin`) UNBLOCKED the command grab: with
pin on, the DK bag now goes **DamageFlyTop** (the Gerudo dragon slam-throw) on
BOTH sweep reps — a clean poked-connect that the earlier pass could never get
(the bag no longer knocks down out of re-grab range). Re-ran
`ganondorf_gerudo_burst_probe.json` (`"pin":true`, iso=Ness-vanilla) —
captures `tests/artifacts/datram-probe-ganondorf-gerudo-burst/`
(`sweep_A_*` / `sweep_B_*` / `vanilla-sideb-f20/f26`).

Verdict (eyeballed f20/f26 poked vs vanilla):
- **`sweep_B` = s12/14/15/16 (0x76C–0x9BC, the purple `7C40D7`/`BEA7CA`/`7605B3`/
  `E36DF3` records) → the Gerudo dragon FLAME AURA.** Poked green, DK's upper
  body + the flame engulfing the victim at connect picks up a clear GREEN tint
  absent in vanilla (`sweep_B-sideb-f20` green glint on DK's shoulder vs
  `vanilla-sideb-f20`). This is the magenta/purple flame that engulfs the grabbed
  victim = **the visible Gerudo burst owner** (partial — the impact green-ray
  starburst + white flash are a SEPARATE unpoked script, still vanilla in the
  poked rep).
- **`sweep_A` = s7/9/10/11 (0x52F–0x708) → the gray/white SMOKE puffs**, not the
  flame. Poked green, the smoke clouds grew larger/whiter with no hue change
  (`sweep_A-sideb-f20`) — confirms the §6 "grayscale/tan smoke" reading; these are
  the dust/smoke records, not the colored flame.

**Shippable lead (needs a split-verify pass to isolate s12/14/15/16 from the
smoke):** a `gerudo_dragon` colour extra owning s12/14/15/16 is now attributable.
Recommend a follow-up narrow poke (s12/14/15/16 only, anti-color magenta→cyan
`00FFFF` per lesson-11 since the operands are purple/magenta) to confirm the aura
independently before WIRE. Owner menu = Ganondorf.

### NARROW CONFIRM 2026-07-02 (Kirby-mission rider) — ✅ WIRE-READY

Ran the recommended narrow poke: **s12/14/15/16 ONLY (0x76C–0x9BC) → cyan `00FFFF`**,
bag `dk dx5 pin:true`, sideb `[14,20,26,32,40]`. Spec:
`backend/probes/ganondorf_gerudo_narrow_probe.json`; captures
`tests/artifacts/probe-ganondorf-gerudo-narrow/` (`gerudo_aura_s12_14_15_16-sideb-*`
vs `vanilla-sideb-*`). Bag connected cleanly (DamageFlyTop slam-throw on both f20/f26).

**Verdict: ✅ CONFIRMED, ISOLATED.** At f20 the purple/magenta flame aura engulfing DK
at the grab-connect turns unmistakably **CYAN/teal** (`gerudo_aura...-sideb-f20.png` vs
`vanilla-sideb-f20.png`); f26 corroborates. The recolor is isolated to these four
scripts — the white smoke puffs (s7/9/10/11, unpoked here) stayed white, DK's darkened
grabbed-victim silhouette (a common effect) stayed purple, and the separate impact
green-ray starburst + white flash (a DIFFERENT unpoked script) is unaffected.

**WIRE recipe:** extra id `gerudo_dragon`, owner menu **Ganondorf**, target `EfGnData.dat`,
move `sideb`, frames `18-28`, anti-color cyan `00FFFF`. Per-record vanilla bytes
(byte-verified via §5b sweep_B / ptcl_parse):

| layer | offset | fmt | vanilla RGB | semantic |
|---|---|---|---|---|
| gerudo_s12_c1 | 0x76C | PRIM | `7C40D7` | dragon flame aura (purple) |
| gerudo_s12_c1b| 0x773 | ... | (byte-verify) | |
| gerudo_s12_*  | 0x779 / 0x780 | ... | (byte-verify) | |
| gerudo_s14_*  | 0x875 / 0x87C / 0x885 / 0x88C / 0x895 / 0x8A5 | ... | `BEA7CA`/`C607FF` | dragon flame (s14) |
| gerudo_s15_*  | 0x92C / 0x933 / 0x93C | ... | `7605B3`/`D873FF` | dragon flame (s15, magenta) |
| gerudo_s16_*  | 0x9A0 / 0x9A7 / 0x9AE / 0x9BC | ... | `E36DF3` | dragon flame (s16) |

WIRE must byte-verify each record's vanilla + PRIM/ENV format per lesson-12 (grouped
vanilla strings differ per record); the offset list is exact (marker/ptcl_parse-verified).

## 6. Open leads (unpoked / partially poked — future MAP)
Scripts 6 (2 col), 7 (10 col grayscale/tan — likely shared smoke like 5), 9 (6),
10 (4), 11 (2), 12 (6, purple `7C40D7`), 14 (10, purple `BEA7CA`/`C607FF`),
15 (4, magenta `7605B3`/`D873FF`), 16 (6, `E36DF3`). No decomp caller found in
ftCaptain specials — probe generically (all four specials + aerials) if scripts 0–5
don't cover a target. 190 model-region colour blocks past the ptcl bank (07/42/98)
= the Gerudo dragon-head geometry + wizard's-foot model; a model-recolor path, not
ptcl (out of scope for this draft).
