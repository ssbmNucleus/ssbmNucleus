# EfKbData.dat — Kirby effects (MAP-STATIC draft)

**Target file:** `storage/test-base/files/EfKbData.dat`
(`effKirbyDataTable`). Header: `EffectTable@0x20 ParticleGroup@0xE0
version=0x42 tex_bank@0x980`, **19 generators**, **`effect_id_start = 5000`
(0x1388)**. 65 color operands in the ptcl bank + **92 model-region 07/42/98
blocks** (past the ptcl bank — open leads, see §4).

Status: **LIVE pass DONE (2026-07-02, MAP-LIVE).** All offsets/vanilla bytes
below are ptcl_parse-exact (structure trusted) and every base-kit group was
live-poked + eyeballed. **Only ONE shippable extra found: `kirby_stone`**
(down-B transform burst, driven by the dust scripts s8/s9/s14 + s5). Final
Cutter, Hammer, Inhale, and Puff-air are all **DEAD in the EfKbData ptcl bank**
(their visible effects are model/texture or item-article driven — details per
group below). Probe specs: `backend/probes/kirby_probe.json` (base kit),
`backend/probes/kirby_probe_upb.json` (Final Cutter late-window re-boot). Captures:
`tests/artifacts/probe-kirby/` + `tests/artifacts/probe-kirby-upb/`.
ISO used: `output/extras-audit-Ness-ness_pk_thunder-vanilla.iso` (Kirby is base
ckind 0x04, any GALE01 vanilla works).

## 0. Headline findings

1. **Base-kit specials route through `efAlt_Spawn` (efalt.c), not
   efAsync_Dispatch.** Kirby's move code (`ft/chara/ftKirby/`) calls
   `efSync_Spawn(0x479..0x4BA, …)`; efsync.c routes that range to
   `efAlt_Spawn`, which resolves each id to a local generator id via
   `efLib_CreateGenerator(0x138x)` etc. **Local bank base = 0x1388 = 5000 =
   `effect_id_start`.** So **parser script index N (1-based) = generator id
   0x1388 + (N−1)**. This is the authoritative script→move map (§1).

2. **Verified move→script bindings (from decomp efSync/efAlt cross-ref):**
   - **Final Cutter (up-B)** — `ftkirbyspecialhi.c:81/99` `efSync_Spawn(0x494)`
     → efalt.c case 0x494 spawns **0x1388, 0x1389, 0x138A** = **scripts 1,2,3**
     (the rising blade slash + the two descending shockwave-beam halves).
   - **Stone (down-B)** — `ftkirbyspecialn.c` `fn_800F53AC_SpawnEffect`:
     air `ef_id=0x497`, ground `ef_id=0x496` → **0x138D/0x138C = scripts 6,5**;
     `SpecialLw_Enter` `efSync_Spawn(0x49B)` → 0x138F = **script 8** (transform
     dust); `SpecialLw_IASA` `efSync_Spawn(0x49C)` → 0x1395 = **script 14**
     (stone-break dust); 0x49D → 0x1390 = **script 9**.
   - **Hammer (side-B)** — `itkirbyhammer.c` `particle_id = 1176/1177`
     (= 0x498/0x499) → 0x138E/0x138F = **scripts 7,8** (hammer-head glow / dust).

3. **Out-of-bank (shared) ids — DO NOT ship as Kirby layers:** 0x49E →
   `efLib_CreateGenerator(0x206)` (landing/wall dust, common); 0x49F → 0x7D00
   (Mario-copy fireball flourish); 0x4B1 → 0x9088; the copy-flourish ids
   0x4B4–0x4B9 → 0x4E20/0x5208/0xBB80 (donor banks). These belong to other
   files. Quarantined in §3.

4. **The Cutter Beam projectile and Inhale/Swallow star are ITEMS**
   (`It_Kind_Kirby_CBeam`, inhale via `efAsync_Spawn(…0x49A…)`). Scripts
   4,10,11,12,15,16,17,18 are not bound by the decomp ids traced above — they
   are the cutter-beam trail / inhale sparkle / puff-air candidates (open
   leads for LIVE, §4).

## 1. Base-kit candidate tables (LIVE pending)

Format: `CF/DF` ptcl operands. RGB byte is at the parser `file_off` (probe
pokes RGB directly there). PRIMCOL (0xCF) = birth/bright core; ENVCOL (0xDF) =
sustained env tint (dominates fade) — expose as `_c1`/`_c2` per precedent.

### final_cutter (up-B) — scripts 1,2,3 — 🔴 ALL DEAD (no shippable ptcl layer)

**VERDICT: DEAD.** Poked s1 (blade, green), s2 (beam, green), s4 (0x32A flash,
magenta) — NONE recolored any visible Final Cutter element. Re-booted with a late
up-B window (`kirby_probe_upb.json`, frames out to f84) to catch the descending
beam that the base spec's f8-34 window missed entirely.
- The **startup birth-flash** (gold ring + white starburst, ~f8) is IDENTICAL in
  vanilla, s1, s2, and s4 pokes → it is a **model-region block or shared/common
  effect**, not a poked ptcl operand. (Gold ring reads FFC257 = s1's env value but
  poking s1 left it unchanged → duplicate/model color.)
- The **white sword blade + slash trail** (f14-44) = a **MODEL**, unchanged by s1.
- The **descending cyan Cutter-Beam wave** (f52 vertical wall → f68 blue-white
  flying projectile) is the **`It_Kind_Kirby_CBeam` ITEM article** — IDENTICAL under
  s2 pokes. Its color lives in the item DAT, not EfKbData s2.

| layer | fmt | offset | vanilla RGB | verdict | evidence |
|---|---|---|---|---|---|
| fc_blade_* (s1) | CF/DF | 0x1CA–0x206 | FFFFFF/FFC257/D4457D/E61A10/FF1119 | 🔴 DEAD | `fc_blade_s1-upb-f08/f30.png` ≡ `vanilla-upb-*` (blade=model) |
| fc_beam_* (s2) | CF/DF | 0x27C–0x293 | 051AC8/FFFF82/FF6EC8/0C1400 | 🔴 DEAD | `fc_beam_s2-upb-f52/f68.png` ≡ vanilla (beam=CBeam item) |
| fc_flash (s4) | CF | 0x32A | 0400FF | 🔴 DEAD | `fc_flash_s4-upb-f08.png` ≡ vanilla (flash=model/common) |

(Script 3 = 0x138A carries no color operands.) Final Cutter is the Bowser-fortress-
white pattern: the visible effect is not in the character's ptcl bank. Any future
recolor would need the CBeam item DAT (beam) + model-region blocks (blade/flash).

### kirby_stone (down-B) — ✅ SHIPPABLE — the dust scripts drive the burst

**VERDICT: ✅ CONFIRMED.** The Stone transform burst recolors. The DOMINANT
colorable payload is the **dust scripts s8/s9/s14** (`kirby_stone_dust` experiment):
poked magenta, the entire radial transform burst + rock-debris tint + swirl rings
turn **bright magenta** — huge, unambiguous (`kirby_stone_dust-downb-f34.png` vs
`vanilla-downb-f34.png`). Window: **f24-f40** (the mid-transform burst peak).

The **ground-transform script s5** (`kirby_stone_ground`, poked magenta) gives a
subtler-but-real recolor of the early transform starburst (`...-downb-f06.png`:
vanilla dark-gray radial burst → teal/darkened; f14 gains a blue central flash).
s5 is a secondary contributor; s8/s9/s14 carry the visible color.

The **air-transform script s6** (`kirby_stone_air`, `airdownb`, poked magenta) showed
**NO visible change** — the air-stone transform burst is white/cyan in both vanilla
and poked (`kirby_stone_air-airdownb-f20.png` ≡ vanilla). s6 = 🔴 redundant/DEAD
standalone; the air burst reuses s5/dust visuals. Ship ground+dust; s6 not needed.

| layer | fmt | offset | vanilla RGB | verdict | note |
|---|---|---|---|---|---|
| stone_dust_c1 (s8) | CF | 0x51E | FFFFFF14 | ✅ CONFIRMED | dust bright — dominant burst color |
| stone_dust_c1b (s8) | CF | 0x52B | FFFFFF | ✅ CONFIRMED | dust |
| stone_dust_c2 (s8) | CF | 0x532 | FFFFFF00 | ✅ CONFIRMED | dust fade |
| stone_s9_c1 (s9) | CF | 0x58B | CCCCCC14 | ✅ CONFIRMED | grey dust |
| stone_s9_c2 (s9) | DF | 0x592 | 09A9BA | ✅ CONFIRMED | s9 env (teal) |
| stone_s9_c1b (s9) | CF | 0x598 | CACACAFF | ✅ CONFIRMED | grey dust |
| stone_s9_c1c (s9) | CF | 0x59F | BABABA00 | ✅ CONFIRMED | grey dust fade |
| stone_brk_c1 (s14) | CF | 0x796 | FFFFFF14 | ✅ CONFIRMED | break dust |
| stone_brk_c2 (s14) | CF | 0x7A3 | FFFFFF | ✅ CONFIRMED | break puff |
| stone_g_* (s5) | CF/DF | 0x381–0x3B8 | FFFF00/000000/FFFFFF | ✅ CONFIRMED (subtle) | ground transform starburst — secondary |
| stone_a_* (s6) | CF/DF | 0x42E–0x465 | FFFF00/000000/FFFFFF | 🔴 DEAD standalone | air burst unchanged; redundant |

WIRE per lesson-12: these records share FFFFFF14 / FFFFFFFF / FFFFFF00 CF patterns
but have dim-alpha variants — byte-verify each record's exact bytes before grouping
(full per-record vanilla in §2). Anti-color for verify: magenta `FF00FF` (vanilla
white/teal/grey). Suggested group key: **`kirby_stone`** (single extra covering the
s5+s8+s9+s14 records; the burst reads as one visual unit).

### kirby_hammer (side-B) — 🔴 DEAD in EfKbData ptcl bank

**VERDICT: DEAD (not in this file).** side-B hammer does NOT draw the s8 dust
records: poking 0x51E/0x52B/0x532 green left the entire hammer swing IDENTICAL
(`kirby_hammer-sideb-f24.png` ≡ `vanilla-sideb-f24.png`). The visible hammer
effects are:
- the **purple/yellow spin-swirl aura** during the twirl (f17-34) = the **hammer
  ITEM (`ItKbHammer`) effect** or a model block, NOT an EfKbData ptcl script;
- the **wooden hammer head** (f34+) = a **MODEL**.

Script 7 (gen@0x4C8) has no color operand in the ptcl bank (confirming the draft
suspicion). **No shippable EfKbData ptcl layer for Hammer.** A future recolor
needs the hammer item DAT + model-region blocks (out of EfKbData scope).

## 2. Full per-record vanilla (ptcl bank, WIRE reference)

Complete `ptcl_parse` dump (offset = RGB start):

```
s1  0x1CA CF FFFFFF | 0x1D1 DF FFC257 | 0x1D7 CF D4457D | 0x1DE DF E61A10
    0x1FF CF 000000 | 0x206 DF FF1119
s2  0x27C CF 051AC8 | 0x283 DF FFFF82 | 0x28C CF FF6EC8 | 0x293 DF 0C1400
s4  0x32A CF 0400FF
s5  0x381 CF FFFF00 | 0x388 DF 000000 | 0x38E CF FFFFFF | 0x397 DF 000000
    0x3A9 CF FFFFFF | 0x3AF CF FFFF00 | 0x3B8 DF 000000
s6  0x42E CF FFFF00 | 0x435 DF 000000 | 0x43B CF FFFFFF | 0x444 DF 000000
    0x456 CF FFFFFF | 0x45C CF FFFF00 | 0x465 DF 000000
s8  0x51E CF FFFFFF | 0x525 DF 000000 | 0x52B CF FFFFFF | 0x532 CF FFFFFF
s9  0x58B CF CCCCCC | 0x592 DF 09A9BA | 0x598 CF CACACA | 0x59F CF BABABA
s10 0x5F3 CF FFFFFF | 0x5FA DF E1D60B | 0x600 CF FFFFFF | 0x607 CF FFFFFF
s11 0x666 CF FFFFFF | 0x66D DF 000000 | 0x673 CF FFFFFF | 0x67A CF FFFFFF
s12 0x6D6 CF FFFFFF | 0x6DD DF 000000 | 0x6E3 CF FFFFFF | 0x6EA CF FFFFFF
s14 0x796 CF FFFFFF | 0x79D DF 000000 | 0x7A3 CF FFFFFF | 0x7AA CF FFFFFF
s15 0x803 CF CCCCCC | 0x80A DF 09A9BA | 0x810 CF CACACA | 0x817 CF BABABA
s16 0x86B CF FFFFFF | 0x872 DF E1D60B | 0x878 CF FFFFFF | 0x87F CF FFFFFF
s17 0x8DE CF FFFFFF | 0x8E5 DF 000000 | 0x8EB CF FFFFFF | 0x8F2 CF FFFFFF
s18 0x94E CF FFFFFF | 0x955 DF 000000 | 0x95B CF FFFFFF | 0x962 CF FFFFFF
```

## 3. Quarantined (shared / out-of-bank — never ship as Kirby layers)

- 0x49E → common 0x206 (landing/wall dust).
- 0x49F → 0x7D00 (Mario-copy fireball).
- 0x4B1 → 0x9088; 0x4B4–0x4B9 → donor banks (0x4E20 Emblem, 0x5208 Zelda,
  0xBB80). These are the copy-ability visual flourishes; the donor content
  lives in the EfKbXx.dat copy files (§5), not here.

## 4. Open leads — LIVE RESULTS (2026-07-02)

- **Inhale (neutral-B)** — 🔴 DEAD in ptcl bank. Poked s4/s10/s11 (0x32A +
  0x5F3–0x67A) cyan during neutral-B; the white suction dots + wind puff stayed
  white/gray (`inhale_sweep-neutralb-f22.png` ≡ vanilla). The inhale suction is
  model/texture/white-particle driven, not a colorable EfKbData ptcl operand
  (matches the §4 caution — the inhale star is an `efAsync` article).
- **Puff-air (aerials, multi-jump)** — 🔴 NO EFFECT. nair/fair spawn no aerial
  ptcl at all — poked s17/s18 (0x8DE–0x962) cyan, no visible effect present in
  either vanilla or poked (`puff_air_sweep-nair-f08.png` ≡ vanilla). Kirby's
  aerials/multi-jump have no colorable EfKbData ptcl payload on FD.
- **Cutter Beam (s2)** — 🔴 DEAD (see final_cutter §1): the descending beam is
  the `It_Kind_Kirby_CBeam` item article, unaffected by s2 pokes.
- **92 model-region 07/42/98 color blocks** past the ptcl bank — STILL UN-ENUMERATED
  (the parser only prints a count, even with `--models --all-ops`). These are the
  top suspects for the DEAD ptcl-bank effects: cutter-blade model tint + startup
  flash, hammer-head, stone model. A model-recolor path (out of ptcl scope). NOT
  probed this pass (would need a signature-scan enumerator + per-block pokes).
- **Scripts 10,11,12,15,16 remaining** — poked in leads/inhale/puff sweeps with no
  attributable visible change on the moves tested; likely on-hit or copy-ability
  variants. Not shippable from this pass.

## 5. Copy-ability file inventory (13 EfKbXx.dat) — future "Kirby copies" extra

Kirby's copy abilities load a per-donor `EfKbXx.dat` whose ptcl bank uses the
**DONOR character's `effect_id_start`** and holds a **byte-identical subset of
the donor's own effect records** (the Roy≡Marth pattern, verified: EfKbPk
scripts 1-3 ≡ EfPkData scripts 1-3 exactly; EfKbCa records ≡ EfCaData script-2+
exactly). **These inherit the donor's semantics for free** — a future copies
extra would just remap the donor's already-mapped offsets onto the copy file.

| file | symbol / donor | eid_start | gens | color ops | verdict |
|---|---|---|---|---|---|
| **EfKbDk** | Donkey (DK) | n/a | 0 | 0 | **NO ptcl bank — texture/model-only** |
| **EfKbFe** | Emblem (Marth FE fire) | n/a | 0 | 0 | **NO ptcl bank — texture/model-only** |
| **EfKbFx** | Fox | n/a | 0 | 0 | **NO ptcl bank — texture/model-only** |
| **EfKbMs** | Mars (Marth) | n/a | 0 | 0 | **NO ptcl bank — texture/model-only** |
| **EfKbZd** | Zelda | n/a | 0 | 0 | **NO ptcl bank — texture/model-only** |
| **EfKbPc** | Pichu (48000) | 48000 | 4 | 6 | colorable; clone of EfPcData Thunder subset |
| **EfKbPk** | Pikachu (36000) | 36000 | 4 | 6 | **FREE WIN — byte-identical to EfPkData s1-3** (Thunder blue) |
| **EfKbCa** | Falcon (38000) | 38000 | 4 | 16 | **FREE WIN — byte-identical to EfCaData** (Falcon Punch fire) |
| **EfKbGn** | Ganon (47000) | 47000 | 4 | 16 | colorable; clone of EfGnData Warlock subset (purple) |
| **EfKbIc** | Ice Climbers (46000) | 46000 | 7 | 19 | colorable; clone of EfIcData (Blizzard/ice) |
| **EfKbKp** | Koopa/Bowser (41000) | 41000 | 4 | 32 | colorable; clone of EfKpData (fire breath) |
| **EfKbLg** | Luigi (37000) | 37000 | 7 | 32 | colorable; clone of EfLgData (fireball/green) |
| **EfKbMr** | Mario (32000) | 32000 | 7 | 32 | colorable; clone of EfMrData (fireball/red) |
| **EfKbSs** | Samus (34000) | 34000 | 11 | 28 | colorable; clone of EfSsData (charge shot/blue) |

**Highlights:**
- **5 copies are model/texture-only** (Dk/Fe/Fx/Ms/Zd) — nothing colorable in
  the ptcl framework; skip in any copies extra (their copy visuals are the
  donor-bank flourishes 0x4B4–0x4B9 that live in EfKbData/shared banks + model
  swaps).
- **9 copies have ptcl banks** with 6–32 color operands each, all appearing to
  be byte-identical subsets of the donor's own `EfXxData.dat` bank (2 spot-
  verified byte-exact: **EfKbPk, EfKbCa**). Per-file cheap: a copies extra can
  reuse the donor char's existing offset map, translated by the header size
  delta (donor gen@0x128 → copy gen@0xB0 for Pikachu). **WIRE would byte-verify
  each copy record against the donor before shipping (the offsets shift by the
  header delta, the operand VALUES match).**
- Recommended future scope: ship the 9 ptcl copies as a single "Kirby Copy
  Abilities" extra that mirrors each donor's mapped layers; the 5 texture-only
  copies get a texture-pack path instead.

## Shippable-now summary (for WIRE)

**ONE extra ships: `kirby_stone`.** Everything else (Final Cutter, Hammer, Inhale,
Puff-air) is DEAD in EfKbData's ptcl bank — the visible effects are model/texture or
item-article driven. Do NOT wire those; they'd pass py_compile but silently no-op.

### `kirby_stone` (owner menu: Kirby)
- **Target file:** `EfKbData.dat`  •  **Move:** `downb`  •  **Frame window:** `24-40`
  (transform-burst peak; ground down-B on a flat stage).
- **Anti-color for verify build:** magenta `FF00FF` (vanilla is white/teal/grey).
- **Records (all ✅ live-confirmed; WIRE must byte-verify each per lesson-12 — the
  FFFFFF14/FFFFFFFF/FFFFFF00 group has dim-alpha variants that differ per record):**

  | offset | fmt | vanilla bytes (RGBA, from ptcl_parse §2) | semantic |
  |---|---|---|---|
  | 0x51E | CF (PRIM) | `FFFFFF14` | s8 transform dust bright |
  | 0x52B | CF (PRIM) | `FFFFFFFF` | s8 dust |
  | 0x532 | CF (PRIM) | `FFFFFF00` | s8 dust fade |
  | 0x58B | CF (PRIM) | `CCCCCC14` | s9 grey dust |
  | 0x592 | DF (ENV)  | `09A9BA00` | s9 env (teal) |
  | 0x598 | CF (PRIM) | `CACACAFF` | s9 grey dust |
  | 0x59F | CF (PRIM) | `BABABA00` | s9 grey dust fade |
  | 0x796 | CF (PRIM) | `FFFFFF14` | s14 break dust |
  | 0x7A3 | CF (PRIM) | `FFFFFFFF` | s14 break puff |
  | 0x381 | CF (PRIM) | `FFFF0000` | s5 ground starburst (secondary) |
  | 0x38E | CF (PRIM) | `FFFFFFFF` | s5 ground flash (secondary) |
  | 0x3A9 | CF (PRIM) | `FFFFFFFF` | s5 (secondary) |
  | 0x3AF | CF (PRIM) | `FFFF0000` | s5 puff (secondary) |

  (s5 rows are the subtler early-transform starburst; s8/s9/s14 carry the dominant
  visible color. Ship them together as one `kirby_stone` group — the burst reads as a
  single visual unit. s6 air-stone 0x42E–0x465 is DEAD standalone — DO NOT include.)
- **Grouping / fan-out:** single-color extra is cleanest. If a `_c1`/`_c2` split is
  wanted, `_c2` = the ENV records (only 0x592 here); everything else is PRIM `_c1`.
- **Suggested id:** `kirby_stone`  •  **AUDIT_HINTS:** `kirby_stone: downb, frames 24-40, anti-color magenta`.
- **Verify capture to expect:** the radial transform burst + rock debris go magenta at
  f24-f40 (cf. `kirby_stone_dust-downb-f34.png`).

### Bonus (already mapped, separate future extra)
- **Kirby Copy Abilities** (9 EfKbXx.dat ptcl copies) — see §5; each mirrors a donor's
  already-mapped offsets. Not part of this base-kit pass.

## DEAD / not-shippable (for the audit row status)
- `final_cutter` — 🔴 blade=model, beam=CBeam item, flash=model/common. No ptcl layer.
- `kirby_hammer` — 🔴 swirl=hammer item DAT, head=model. No ptcl layer.
- `inhale` — 🔴 suction=white-particle/model. No colorable ptcl operand.
- `puff_air` — 🔴 no aerial ptcl spawns at all.

## AUDIT_HINTS (LIVE-refined)

```
kirby_stone:  downb, frames 24-40 (transform dust burst), anti-color magenta
# DEAD — do not wire: final_cutter (upb), kirby_hammer (sideb), inhale (neutralb), puff_air (aerials)
```

---

# Copy Abilities (§6) — STATIC pass, 2026-07-02

**The free win the §5 inventory flagged, now fully mapped.** All 8 comparable
copy files parse as **pure byte-identical subsets** of their donor's own ptcl
bank (Roy≡Marth pattern, universal): running `ptcl_parse` on each `EfKb<XX>.dat`
and matching every color record against the donor `EfXxData.dat` by
**(script ordinal, in-script operand ordinal, kind, bytes)** — NOT by absolute
offset (the copy's smaller header shifts every offset by a per-file delta) —
gives **0 records that DIFFER and 0 with no donor match** across all 8 files.
There are **no Kirby-specific color tweaks** in any copy bank; each copy is
literally a slice of the donor's records at shifted offsets.

## 6.0 Why recoloring a copy file is INDEPENDENT of the donor (decomp)

Each copy bank's `effect_id_start` is the **donor's copy-range id**, NOT the
donor's own base id — e.g. `EfKbCa` eid_start = **38000**, while `EfCaData`
eid_start = 4000. Kirby's copied specials call `efSync_Spawn(0x479..0x4BA)` from
`ftKirby/ftkirbyspecial<donor>.c`; `efalt.c` resolves those ids to generator ids
that land in the **copy** range, confirmed byte-for-byte against the parsed
eid_start values:

| efalt case | `efLib_CreateGenerator` id | = decimal | copy bank |
|---|---|---|---|
| 0x4AC (Mario) | 0x80E8 | 33000 | **EfKbMr** (base 32000) |
| 0x4A4 (Samus) | 0x84D0 | 34000 | **EfKbSs** |
| (Pika) | 0x8CA0 | 36000 | **EfKbPk** |
| 0x4B1 (Luigi) | 0x9088 | 37000 | **EfKbLg** |
| 0x494-family (Falcon) | 0x9470/0x9471 | 38000/1 | **EfKbCa** |
| 0x4AD/0x4AE (Ice) | 0xB3B0/0xB3B6 | 46000/6 | **EfKbIc** |
| 0x4B3 (Ganon) | 0xB799 | 47001 | **EfKbGn** |

(0x9858/9=39000 → EfKbGw G&W; 0x4B4-0x4B9 → 0x4E20/0x5208/0xBB80 = the
Mars/Zelda/DK model-swap flourishes §3 already quarantined.) **Conclusion: a
copied move draws EXCLUSIVELY from the EfKb copy bank.** Recoloring `EfKbCa`
recolors Kirby's copied Falcon Punch and leaves Falcon's own Falcon Punch
(`EfCaData`) untouched, and vice-versa — they are separate files in separate id
ranges. This is exactly what makes a per-copy extra clean and non-colliding.

## 6.1 Copy → donor identity + which SHIPPED donor extra it twins

For each copy, how many of that donor's **already-shipped** extra color-records
have a byte-identical twin somewhere in the copy bank (matched by bytes, so the
header-delta shift is irrelevant). This is the "reuse the donor's mapped layers"
budget:

| copy | donor / EfKbXX eid | copy color-ops | shipped donor extra → twins in copy | ship confidence |
|---|---|---|---|---|
| **EfKbGn** | Ganon 47000 | 16 | `warlock_punch` **12/12 (FULL)** | ✅ LIVE-VERIFIED (§6.4b) |
| **EfKbIc** | Ice Climbers 46000 | 19 | `ice_shot` **23/23 (FULL)** | ✅ LIVE-VERIFIED (§6.4b) |
| **EfKbKp** | Bowser 41000 | 32 | `bowser_fire_breath` **17/17 (FULL)** | ✅ LIVE-VERIFIED (§6.4b) |
| **EfKbLg** | Luigi 37000 | 32 | `luigi_fireball_smoke` **20/24** (4 = model-region 0x111xx offs, not in ptcl copy) | ✅ LIVE-VERIFIED (§6.4b) |
| **EfKbMr** | Mario 32000 | 32 | `mario_fireball` **30/33** (3 = model-region 0x11Axx offs) | ✅ LIVE-VERIFIED (§6.4b) |
| **EfKbCa** | Falcon 38000 | 16 | `falcon_kick` **11/40** + `raptor_boost` **4/21** (dots); `falcon_punch` **0/25** | ✅ LIVE-VERIFIED (§6.4b; punch fire = these ptcl records) |
| **EfKbPk** | Pikachu 36000 | 6 | `pikachu_thunder_jolt_air` **6/9** | ✅ live: records bind the copied jolt (§6.4b) |
| **EfKbSs** | Samus 34000 | 28 | `charge_shot` **2/2 (FULL)** + `missile` 2/8 | ✅ live: records bind the copied shot (§6.4b) |
| **EfKbPc** | Pichu 48000 | 6 | *(no `EfPcData` Ef donor exists — Pichu thunder lives in `PlPc.dat`; the 6 copy records structurally clone Pikachu's jolt pattern)* | ❌ LIVE-MAPPED DEAD (§6.5) — records do NOT drive the visible copied jolt; NOT SHIPPABLE |
| EfKbDk/Fe/Fx/Ms/Zd | — | **0** | none — texture/model-only (§5) | n/a — texture-pack path |

**Reading the "twins" column:** a low fraction (Falcon, Pikachu, Samus) does NOT
mean the copy is wrong — it means the copy bank keeps donor records we never
surfaced as an extra (or model-region offsets a ptcl copy structurally can't
hold). Every copy record is still byte-identical to *some* donor record; the
fraction only measures overlap with our **shipped** offset maps, i.e. how much
label/structure we can reuse for free vs. author fresh.

### Per-copy record offsets (copy-file-local, ptcl_parse-exact)

Match key `sN.oM` = donor script N, operand M; `→ donor 0x…` = the donor offset
whose exact bytes this copy record clones. Full per-record vanilla is the
`bytes` column (RGBA). All verified against the live copy DATs in `test-base`.

**EfKbGn** (Ganon, all 16 = clone of donor s0/s1/s2, the Warlock/Wizard fire):

```
0xE4  prim 280021C8 → EfGnData 0x154 (warlock_punch color1)   0xEB env 11002E → 0x15B
0xF1  prim 47004F → 0x161   0xF8 env 130245 → 0x168   0x122 prim 000000 → 0x192
0x129 env 1B0245 → 0x199   0x1B4 prim A200AB → 0x224   0x1BB env 400591 → 0x22B
0x1C1 prim 75039C → 0x231   0x1C8 env 280587 → 0x238   0x1F2 prim 000000 → 0x262
0x1F9 env 540775 → 0x269   0x296 prim FF80FB   0x29D env A20CFF
0x2A6 prim FF70DC   0x2AD env B005FF   (s2 = donor 0x306.. — NOT in a shipped extra)
```

**EfKbIc** (Ice Climbers, 19 = clone of donor s0/s2/s3/s4/s5/s6 = `ice_shot` blizzard):

```
0xBA prim 79B8F7→0xE2  0xC1 env 0101F9→0xE9  0xC7 prim 2E66FF→0xEF  0xCE env 0B07EE→0xF6
0xDB prim 679CFE→0x103  0x17D prim FAFCFF→0x1A5  0x184 env 515DFF→0x1AC  0x18A prim BAEEFF→0x1B2
0x1E6 prim FAFCFF→0x20E  0x1ED env 2E17FF→0x215  0x1F3 prim 1AB4DE→0x21B
0x24E prim FAFCFF→0x276  0x255 env 2E17FF→0x27D  0x25B prim 82EBFF→0x283
0x2B4 prim FFFFFF→0x2DC  0x2BB env 0101F9→0x2E3  0x30D prim FAFCFF→0x335
0x314 env 515DFF→0x33C  0x31A prim BAEEFF→0x342   (all 19 twin ice_shot)
```

**EfKbKp** (Bowser, 32 = clone of donor s0/s1/s2 + a repeated s3; `bowser_fire_breath` twins all 17 shipped):

```
0xA2 prim FFFFFF→0xF2  0xA9 env FFE851→0xF9  0xBB prim FFFFFF→0x10B  0xC2 env 000000→0x112
0xCF prim FFD9B8→0x11F  ...  0x226 prim FFC607→0x276  0x22D env FF0206→0x27D  ...
(s3 0x2AE.. = duplicated s0/s2 records, byte-identical; shifted-match, 4-18 donor candidates)
```

**EfKbLg** (Luigi, 32; `luigi_fireball_smoke` twins 20 — the ptcl records; the 4
misses 0x111xx are Luigi's model-region green-fire blocks a ptcl copy omits):

```
0xB2 prim FFFFFF→0xEA  0xB9 env 83FF7D→0xF1  0xC7 prim 26FF43→0xFF  0xCE env 2ABA4E→0x106
0xD4 prim 149C2D→0x10C  ...  full s0/s1/s3/s4/s5/s6 clone, all 32 twin some donor record
```

**EfKbMr** (Mario, 32; `mario_fireball` twins 30 — misses = 0x11Axx model-region;
NOTE copy s0 = donor **s1**, i.e. the copy drops Mario's donor-s0 script):

```
0xB2 prim FFFFFF→ donor s1.o0 0x162  0xB9 env FFCC4A→0x169  0xC7 prim FFA217→0x177 ...
0x3C6 prim FF290C→ donor s7 0x476  0x3CD env FFFF82→0x47D  (s7 = the ember dots)
```

**EfKbCa** (Falcon, 16; the LOW-overlap case worth understanding):

```
0xCA  prim FFFFFF → EfCaData s0 0x12F   (falcon_kick trail_c1)
0xD1  env  FFC257 → s1 0x1E1            0xD7 prim FF5A07 → s1 0x1E7   0xDE env CA000D → 0x1EE
0x108 prim 000000 → s1 0x218            0x10F env FF1119 → s1 0x21F
0x17A prim DE8E2B → s16 0x91A  (= falcon_punch 'smoke' 0x918-family, the trail puff)
0x181 env FF0707 → 0x921   0x187 prim FD5126 → 0x927   0x18E env A40409 → 0x92E
0x1B8 prim 000000 → s1 0x218   0x1BF env 750003 → s16 0x95F
0x23C prim FF051A → s2 0x29C  (= falcon_kick dots_c1 family)   0x243 env FFFF82 → 0x2A3
0x24C prim FFFF6E → 0x2AC   0x253 env FF0C14 → 0x2B3
```

So the copied Falcon **Punch** actually reuses Falcon **Kick/Punch-trail/dots**
records (the fire tip 0x202F0 and lens flares 0x22Dxx that `falcon_punch`/
`punch_texture` recolor are model-region + tex, which the ptcl copy does NOT
carry). This is why `falcon_punch` twins 0/25 but the copy is still fully
faithful — the copied punch just draws a different (ptcl) subset than Falcon's
marquee punch fire. **Recolor target for a copied-punch extra = these 16 EfKbCa
ptcl records, NOT falcon_punch's offsets.**

**EfKbPk** (Pikachu, 6 = the jolt starburst core+glow, s1/s2/s3):

```
0xF0 prim FFFFFFC8 → EfPkData 0x168  0xF7 env 6681FA → 0x16F  (jolt_air_mid c1/c2)
0x158 prim 0B0BE6 → 0x1D0  0x15F env 07078F → 0x1D7  (outerflare c1/c2)
0x1C0 prim 8FD6FF → 0x238  0x1C7 env 0C0CFF → 0x23F  (midflare c1/c2)
```

**EfKbSs** (Samus, 28; only `charge_shot` 0x2E9/0x2F0 + 2 missile records are
shipped-twins — the rest are Samus scripts we never surfaced):

```
0xBF prim CACACA→0x12F  ...  0x279 prim FFFFFF→0x2E9 (charge_shot color1)
0x280 env 090087→0x2F0 (charge_shot color2)  ... 28 records, all twin a donor record
```

**EfKbPc** (Pichu, 6): no `EfPcData` donor Ef file exists (Pichu's thunder is in
`PlPc.dat`). The 6 records structurally mirror EfKbPk's jolt layout
(prim/env pairs across 3 scripts). Ship on parser confidence alongside EfKbPk or
hold — cannot cross-diff a donor Ef bank.

## 6.2 Recommended extra shape

**Per-donor extras, one `kirby_copy_<donor>` per copy file** (NOT a single
mega-extra, NOT a set of sub-layers under one). Rationale:
- **Independent recolor** (§6.0): a user who recolored their Kirby's copied fire
  wants it separate from any donor recolor; separate `target_file` = separate
  file = no collision, and matches the config's one-`target_file`-per-extra rule.
- **Reuse the donor's labels/structure for free:** each `kirby_copy_<donor>`
  mirrors the donor extra's `_c1`/`_c2` PRIM/ENV split and property names (the
  DualColorEditorModal fan-out), just at the copy's shifted offsets. Owner menu:
  **Kirby**. `target_file`: `EfKb<XX>.dat`. Per template lesson 12 every record
  keeps its **own** byte-verified vanilla (the copies have dim-alpha/zero-alpha
  variants — do NOT ship a shared vanilla string).
- Group the whole set under a **"Copy Abilities"** heading in Kirby's extra list
  (like Falcon's punch/kick/raptor grouping) so the UI reads as one feature.
- The **5 texture-only copies (Dk/Fe/Fx/Ms/Zd)** get a texture-pack path, not a
  color extra — no ptcl records to bind.

## 6.3 Free (parser-confident) vs need-LIVE

**6 ship on parser+decomp confidence** — byte-identical to a VERIFIED-and-SHIPPED
donor extra record, and the copied move is a straightforward projectile/burst
that unambiguously renders those records:
- **EfKbGn** (warlock_punch 12/12), **EfKbIc** (ice_shot 23/23),
  **EfKbKp** (bowser_fire_breath 17/17), **EfKbLg** (luigi 20/24),
  **EfKbMr** (mario 30/33) — all high/full overlap with a live-verified donor.

**3 hold for a LIVE spot-verify** — either low shipped-overlap or the copied
move draws a non-obvious subset:
- **EfKbCa** (copied punch reuses kick/trail/dots ptcl, not falcon_punch offsets —
  confirm what the copied punch actually tints),
- **EfKbSs** (only 2 records twin a shipped extra; the copied charge shot's
  visible payload is mostly un-surfaced Samus scripts),
- **EfKbPk / EfKbPc** (6 records each; jolt starburst — confirm the copied jolt
  renders them; Pc additionally has no donor Ef to diff).

Byte-identity to a verified donor record is **strong** evidence, so even the
"hold" set is likely correct; the LIVE is a cheap confirm, not a discovery.

## 6.4 LIVE-confirm probe + harness gap (CLOSED — see §6.4b)

Probe specs: **`backend/probes/kirby_copy/<donor>.json`** — one per donor
(the donor must be IN the match, see §6.4b #3), each with a vanilla control +
anti-color recolor experiment firing the copied neutral-B. Run:
`python devtools/effect_probe.py probes/kirby_copy/ganon.json`.

**⚠ HARNESS GAP (historical — CLOSED by §6.4b's primitive, option 2 below):** the
`backend/devtools/effect_probe.py` / `ingame/` harness drives a **solo Kirby** (no CPU,
by CLAUDE.md design — a CPU attacks and moves the camera). `ingame/moves.py`
exposes `neutralb`/`airneutralb` (inhale) but **no primitive to inhale + swallow
an opponent and thereby gain a copy ability.** A solo Kirby's neutral-B inhales
empty air, never swallows, and **never loads/spawns the EfKb copy banks** — so
the copy pokes would render nothing. To LIVE-confirm, the harness needs a
copy-inhale primitive, e.g.:
1. spawn a throwaway target and script (via pipe) an inhale→swallow sequence, or
2. memory-poke Kirby's copy-ability state directly (`ftKirby` copy_kind /
   copied-fighter id in the player block) so he starts the boot already holding
   the donor's ability, then fire the copied special.

(The single-file `kirby_copy_probe.json` this section originally parked was
superseded by the per-donor `probes/kirby_copy/` specs and deleted — a single
boot cannot switch donors, §6.4b #3.)

### 6.4a RECOVERED MECHANISM (decomp + partial live, HARNESS-BUILD mission 2026-07-02)

Handed off mid-live to a Fable agent for the execution loop; recording the
mechanism + what the live pokes proved so the next agent doesn't re-derive it.

**The copied-fighter id field.** `fp->fv.kb.hat.kind` — a `FighterKind`
(INTERNAL id, not external ckind) at **fp + 0x2238** (`ftKb_FighterVars` starts
fp+0x222C, `hat.kind` = hat+0xC). This is the value the copy-special dispatch
reads (`ftKb_SpecialN_800F19AC`/`800F1A8C`/`800F1CD8` switch on it). Live
baseline read: fresh in-match Kirby has `hat.kind = 0` (no copy; his own
neutral-B inhale = motion state **353** = `ftKb_MS_SpecialN`, base
CHAR_SPECIFIC 0x155=341 + enum offset 12). The death-init default is 4
(FTKIND_KIRBY) per `ftKb_Init_OnDeath`; in-match it reads 0.

**How Kirby acquires it + WHY a bare hat.kind poke is NOT enough (live-proven).**
The install is `ftKb_SpecialN_800F1BAC(gobj, kind, arg2)` (ftkirby.c:4666): it
sets `hat.kind`, calls `800F190C` (reset fighter vars) + a per-kind init callback
`ftKb_Init_803C9CC8[kind*2]`, and `800F16D0` (preloads the copy hat/ability
article from the global `ft_80459B88.hats[]` — Kirby preloads ALL copy files, so
the donor need NOT be in the match for the DATA to exist). The copy special's
Enter is a STORED CALLBACK that 800F1BAC installs; **poking `hat.kind` alone on
the live fighter does NOT re-install that callback** — LIVE CONFIRMED: poked
Kirby's live `hat.kind` = 0x19 (Ganon), fired neutral-B, still got state 353
(his own inhale), NOT `ftKb_MS_GnSpecialN` (528). So the poke must go through
800F1BAC, which we cannot call directly via RPM.

**The lever that CAN trigger 800F1BAC without scripting a swallow: respawn.**
`ftKb_Init_OnDeath` (ftkirby.c:3039-3043) runs on rebirth and, if the
StaticPlayer copy flag+kind are set, calls `800F1BAC(gobj, unk4D, 0)`:
```c
if (Player_GetFlagsBit1(fp->player_id) && Player_GetUnk4D(fp->player_id) != 4)
    ftKb_SpecialN_800F1BAC(gobj, Player_GetUnk4D(fp->player_id), 0);
```
- **`unk4D`** (persisted copy kind, INTERNAL FighterKind) = **StaticPlayer + 0x4D**.
- **`flags.b1`** (the "has copy ability" bit `Player_GetFlagsBit1` reads) =
  **StaticPlayer + 0xAC, mask 0x40** (MWCC MSB-first bitfield: b0=0x80, b1=0x40).
  Live read after poking b1: the 0xAC byte read back `0x40`.
- StaticPlayer base **0x80453080**, stride **0xE90** (per match_setup.py).

**Donor INTERNAL FTKIND ids** (src/melee/ft/forward.h) for the 5 shipped copies:
Mario=0x00 → EfKbMr, Bowser(Koopa)=0x05 → EfKbKp, Luigi=0x11 → EfKbLg,
Ganon=0x19 → EfKbGn, Ice Climbers(Popo)=0x0A → EfKbIc.
(Others: Falcon=0x02→EfKbCa, Samus=0x0D→EfKbSs, Pikachu=0x0C→EfKbPk,
Pichu=0x17→EfKbPc.)

**Copy neutral-B START motion-state ids** (confirmation that a copy installed;
base `ftKb_MS_SpecialN`=353): Mario `MrSpecialN`=**399**, Samus
`SsSpecialNStart`=**407**, Pika `PkSpecialN`=**429**, Luigi `LgSpecialN`=**431**,
Falcon `CaSpecialN`=**433**, Bowser `KpSpecialNStart`=**443**, Ice
`PpSpecialN`=**453**, Pichu `PcSpecialN`=**526**, Ganon `GnSpecialN`=**528**.
A successful copy → neutral-B enters the donor's state, NOT 353.

**What still needed solving (RESOLVED in §6.4b).** Two levers tried by the
first agent, both stuck: the pre-spawn poke (cleared by match load) and the
death→rebirth poke (fighter gobj read NULL forever after the KO). Both dead
ends are explained by the flags.b1 discovery below.

Exploration probe (kept): **`backend/kirby_copy_explore.py`** (now runs the
final primitive end-to-end and prints the copied neutral-B states); stall
diagnostic: `backend/kirby_copy_diag.py`. Vanilla ISO used:
`output/straggler-vanilla.iso`.

### 6.4b PRIMITIVE BUILT + ALL 8 COPIES LIVE-VERIFIED (2026-07-02)

The harness gap is CLOSED. `ingame/match_setup.py` now has the primitive:
`arm_kirby_copy_ondeath(d)` (boot-phase code patch) + `set_kirby_copy(d,
donor_ftkind, port)` (poke) + `install_kirby_copy_via_rebirth(d, donor_ftkind,
port)` (the whole KO→rebirth sequence). Plumbed as `--kirby-copy <donor>` in
`frameshot.py` and the `"kirby_copy"` spec key in `effect_probe.py`
(per-donor specs: `backend/probes/kirby_copy/<donor>.json`). Three discoveries
corrected the §6.4a plan:

1. **flags.b1 is NOT a "has copy" flag — do not set it.** `Player_GetFlagsBit1`
   (StaticPlayer +0xAC mask 0x40) is the SINGLE-PLAYER TEAM-FIGHTER flag
   (Classic Kirby Team, set by gm_1601.c:5105/vi0501.c). It doubles as
   "remove on death": `gm_80167320` (gm_1601.c:3398) skips the respawn and
   `Player_SetSlottype(slot, NA)`s a b1-flagged player — one life per team
   member. THAT was the NULL-gobj dead end. And the death→respawn→OnDeath
   chain is ONE synchronous call stack (`ftCo_800BFD9C → gm_80167320 →
   fn_8016719C → Player_80032768 → Fighter_UnkProcessDeath_80068354 →
   ftData_OnDeath[kind]`), so the two b1 reads can never be split by RPM.
   Instead the primitive NOPs the b1 check INSIDE `ftKb_Init_OnDeath`
   (0x800EE638: `beq +0x2C` 0x4182002C → 0x60000000), so `unk4D != 4` alone
   installs the copy on every rebirth. unk4D's vanilla in-match value is 4
   (FTKIND_KIRBY = no copy), so the patch is side-effect-free until poked.
2. **Dolphin-JIT gotcha: the code patch must be armed at BOOT, before Kirby's
   first spawn.** ftKb_Init_OnDeath runs at the initial spawn too (it's what
   sets hat.kind=4 — reads as 0 only if you read a u8 at +0x2238: `hat.kind`
   is a u32, read all 4 bytes). A mid-match patch hits an already-JIT-compiled
   block and does nothing (live-proven).
3. **The donor MUST be in the match (bag=donor), one boot per donor.** Melee
   loads a donor's copy data (PlKbCp hat + EfKb bank) at match load only for
   PRESENT fighters — the EfKb banks are NOT all preloaded (solo boot: no
   EfKb images in RAM). Installing a copy of an absent donor dereferences
   never-loaded data and HANGS the game (frame counter freezes permanently,
   fighter stuck in Sleep(11), unrecoverable). Also: the harness StaticPlayer
   never got stocks (warp path skips the PlayerInitData copy), so the
   primitive seeds stocks=5 before the KO or the death destroys the fighter.

**LIVE VERIFY (captures: `tests/artifacts/probe-kirby-copy/<donor>/`,
vanilla + poked pairs, 5 frames each, plus a pixel-count anti-color judge):**

| copy | verdict | evidence |
|---|---|---|
| **EfKbGn** ganon | ✅ VERIFIED | neutral-B enters 528; poked f32/f44: purple core/ring visibly altered (magenta-family px 101→62) |
| **EfKbIc** iceclimbers | ✅ VERIFIED | 453; full-bank 19-record FF00FF re-run: forming crystal magenta f14 418 px vs 2 vanilla (3-record poke was too subtle) |
| **EfKbKp** bowser | ✅ VERIFIED | 443; magenta flames f32/f44 442/185 px vs 0 |
| **EfKbLg** luigi | ✅ VERIFIED | 431; green fire drops 10751→3728 px + magenta 277 appears |
| **EfKbMr** mario | ✅ VERIFIED | 399; magenta fireball f44 537 px vs 0 |
| **EfKbCa** falcon | ✅ VERIFIED | 433; punch connects ~f52 (f8-44 shows NOTHING — frame window 40-68): f60 magenta 4697 px vs 0. Confirms §6.1: the copied punch draws the EfKbCa ptcl records, not falcon_punch's model-region offsets |
| **EfKbPk** pikachu | ✅ verified (binding) | 429; the jolt burst's violet component (110/67 px f22/f32) vanishes when poked + burst structure changes; green reads as blue/white shift (additive blend), rep compositions differ |
| **EfKbSs** samus | ✅ verified (binding) | 407; copied shot loses ALL green (548→0) and gains magenta (485→5081) with only 3 records poked — the copy bank IS the copied shot's visible payload |
| **EfKbPc** pichu | ❌ DEAD for the copied jolt (LIVE-MAPPED §6.5) | 526; all 6 records anti-color-poked, zero visual delta (flight ball + connect burst). NOT SHIPPABLE as a color extra |

All 9 donors' installs were state-confirmed (hat.kind == donor FTKIND after
rebirth). The 5 shipped `kirby_copy_*` extras are LIVE-VERIFIED; the Ca/Ss/Pk
trio's copy banks verifiably bind the copied specials, so per-donor extras for
them can ship once offsets are authored (Ca's are already in §6.1).

## AUDIT_HINTS (Copy Abilities)

```
# Copy Abilities: per-donor extras kirby_copy_<donor>, owner Kirby, target EfKb<XX>.dat.
# LIVE-VERIFIED (2026-07-02, §6.4b): EfKbGn/Ic/Kp/Lg/Mr shipped extras recolor in-game;
#   EfKbCa/Ss/Pk copy banks verifiably bind the copied specials (extras can be authored).
# HARNESS: --kirby-copy <donor> (frameshot) / "kirby_copy" spec key (effect_probe);
#   donor MUST be the bag (one boot per donor) or the install HANGS the game.
# EfKbPc (Pichu): LIVE-MAPPED DEAD (§6.5) -- do NOT author kirby_copy_pichu; the
#   copied jolt's visuals are item/PlPc-side, not in the EfKbPc ptcl bank.
# Texture-only (no color extra): EfKbDk/Fe/Fx/Ms/Zd.
```

## 6.5 Pichu copy — MAP-LIVE verdict (FINAL DOLPHIN SWEEP, 2026-07-02)

**Verdict: ❌ NOT SHIPPABLE.** `EfKbPc.dat`'s 6 ptcl color records do NOT drive
any visible element of Kirby's copied Pichu thunder jolt. Do not author a
`kirby_copy_pichu` color extra; there is nothing recolorable in the bank for
the move the copy performs.

**Probe:** `backend/probes/kirby_copy/pichu.json` (two boots, 2026-07-02):
run 1 bag pichu dx=14 (close, connect-burst focus, frames 8/14/22/32/44);
run 2 bag pichu dx=40 `pin:true` (flight-ball focus, frames 8/12/16/20/26/34/44).
Copy install state-confirmed both boots (`hat.kind=0x17`, copied neutral-B =
PcSpecialN 526, Kirby takes the 1% jolt self-damage). Captures:
`tests/artifacts/probe-kirby-copy/pichu/` (both runs' frames share the dir;
run 2 = the f12/f16/f20/f26/f34 names).

**Per-record table (all live-poked together, per-script anti-colors, readback
OK on BOTH window-vote RAM copies 0x8121EE60/0x8125FF20):**

| script | offsets (file) | format | vanilla | anti-color poked | observed |
|---|---|---|---|---|---|
| s1 jolt mid | 0xF0 prim / 0xF7 env | CF/DF RGBA | `FFFFFFC8` / `6681FA` | green 00FF00 both | no delta |
| s2 outerflare | 0x158 prim / 0x15F env | CF/DF RGBA | `0B0BE6C8` / `07078F` | orange FF8000 both | no delta |
| s3 midflare | 0x1C0 prim / 0x1C7 env | CF/DF RGBA | `8FD6FFC8` / `0C0CFF` | red FF0000 both | no delta |

**Evidence of the null:** flight ball f26 vanilla-vs-poked statistically
identical (bright-pixel mean_s 0.350→0.344, mean_v 0.579→0.569, same top
color-histogram bins); connect burst f22(van)/f34+f44(poked) both pure vanilla
violet lightning + white sparkles + black radial spikes; zero green/orange/red
pixels attributable to the pokes in any frame.

**Mechanism (decomp, why it's dead):** the copied jolt is an ITEM spawn —
`ftKb_PkSpecialN_Anim` (ftkirbyspecialpikachu.c) case `FTKIND_PICHU` calls
`it_802B338C(gobj, &pos, dir, da->specialn_pc_grounded_item_id)` (air variant
likewise). The jolt's ball/burst visuals belong to the Pichu jolt item article
(item file / PlPc-side — consistent with Pichu's own thunder living in
`PlPc.dat`, not an Ef bank). This differs from EfKbPk only in degree: Pikachu's
copy bank showed a small binding signal (a ~110 px violet burst component);
Pichu's shows none at all.

**Residual (open lead, NOT needed for the verdict):** per template lesson 5 a
build-path check (patch `EfKbPc.dat` in an ISO) was not run — if some future
mission finds a Kirby-Pichu-copy visual these records DO drive (e.g. a rare
on-hit variant), re-open; until then treat the bank as dead.
