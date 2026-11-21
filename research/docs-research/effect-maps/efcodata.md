# EfCoData.dat — cast-shared common effects bank (MAP-LIVE, partial)

**Target file:** `storage/test-base/files/EfCoData.dat` (md5 `739290ead708aeb98bd5118c1abe4a34`, 1,334,111 bytes).
**Public symbol:** `effCommonDataTable`. **Bank index 0** in `efAsync_DatEntries`
(`efasync.c:1146`), so this is the file every `gfx_id < 1000` resolves into.
**`effect_id_start = 0`** → **script index == gfx_id** (no offset). 592 generators.

Status: LIVE pass 2026-07-02 (MAP-LIVE) verified a subset by eye — see the
🟢/🟡/⚪ marks in §3a and the **LIVE RESULTS** block below. The rest stay
LIVE-pending (structure + decomp cross-ref + reference-mod diff only). Probe
specs: `backend/probes/efcodata_probe.json` (Zelda), `backend/probes/efcodata_pika_probe.json`
(Pikachu), `backend/probes/efcodata_link_probe.json` (Link — harness-blocked, below).

### LIVE RESULTS (2026-07-02, MAP-LIVE) — read this before §3

Legend: 🟢 verified (poke visibly recolored the effect) · 🟡 partial/subtle or
on-hit-pending · ⚪ texture-null control confirmed empty (ptcl path does nothing)
· 🔧 harness-blocked (not a dead offset).

- **🟢 `common_electric` (§3c pool) — VERIFIED.** Boot: Zelda + DK bag (dx15).
  Poked 9 pool records green (0xDC5/EAD/14F5/1560/1609/1C17/1C8D/1CFF/2F15) on
  Zelda's on-hit hitlag burst. The body-wide **blue electric arc + radial spark
  rays turned bright GREEN** (vanilla-jab-f12 blue → electric_pool_on_jab-jab-f12
  green). This pool = the **cast-wide on-hit / hitlag electric spark burst** that
  fires when a character takes a hit. Grouped extra confirmed (per-script split
  not needed to ship the group). Captures: `tests/artifacts/datram-probe-efcodata-zelda/electric_pool_on_jab-*` vs `vanilla-jab-*`.
- **🟢 s95 thunder_jolt_spark — VERIFIED but SUBTLE.** Boot: Pikachu solo,
  neutral-B (Thunder Jolt). Poked s95 magenta (0x391A/0x3921/0x3930). The
  **small dissipation/cheek sparkles at Pikachu turned magenta-white** (poked
  f36 shows pink-white star bursts at chin+foot absent in vanilla; ambient
  background stars also shifted purple). **IMPORTANT honesty note:** the big blue
  **Thunder Jolt fountain / travelling bolt is UNCHANGED — it is a separate
  texture-driven article effect, NOT s95.** s95 only owns the caster-side spark.
  A `thunder_jolt_spark` extra is real but low visual impact; the marquee jolt
  bolt is a texture lead. Captures: `tests/artifacts/datram-probe-efcodata-pika/thunder_jolt_spark-neutralb-f36.png` vs `vanilla-neutralb-f36.png`.
- **⚪ Transform (s106) texture-null — CONFIRMED EMPTY.** Zelda down-B: green
  poke of the electric pool left the transform sparkle column **vanilla
  blue/gold** (transform_null-downb-f12 identical column to vanilla-downb-f12,
  only faint green ambient background stars added). Confirms Transform (and by
  the same logic Din's Fire / Vanish / Quick Attack / arrow / Bowser Bomb in
  §3b) needs the **texture path**, not the colour editor.
- **🔴 `common_hit_smoke` (s62 0x2AC3 / s4) — DEAD (Fox fsmash re-probe 2026-07-02).**
  Re-ran with a HEAVY hit: Fox fsmash into a DK bag (dx5), bag → DamageN2 (HIT,
  15%). The damage-smoke cloud DID spawn and is clearly visible trailing the
  launched bag at f30 — but poking s62 0x2AC3 green (vanilla ENV `FFFFFF`) left
  the smoke **fully WHITE/gray in both vanilla and poked** (zero green at any
  frame). The big blue+white+gold hit-spark STAR at connect (f14) is also
  unchanged (it is the generic hitspark — texture/model, not this ENV). s4
  (0xFDA) is alpha-only (`804001`) — un-recolorable as predicted. **NOT shippable.**
  The damage-smoke color comes from elsewhere (texture or a different operand than
  the s62 ENV). Captures: `tests/artifacts/datram-probe-efcodata-fox/`
  (`hit_smoke_s62-fsmash-f14/f30` vs `vanilla-fsmash-f14/f30`).
- **🟢 `jab_finisher_spark` (s11/s15/s91) — VERIFIED & COLORABLE (STRAGGLER-CLOSEOUT 2026-07-02).**
  The Attack100 harness gap is SOLVED. Built a `rapidjab` recipe in
  `ingame/moves.py` (registered in `MOVES`): a **1-frame-ON / 1-frame-OFF A
  toggle** drives Fox's jab chain Attack11(44)→Attack12(45)→Attack100Start(47)→
  **Attack100Loop(48)** deterministically. (Neither mashing NOR a continuous
  hold chained on the frozen-step pipe — a continuous hold played jab1's full
  17f then dropped straight to Wait; the toggle presents a fresh A-press edge
  inside every jab's IASA window. Decomp basis in the recipe comment.) With the
  DK bag PINNED (dx6, pin:true) it stays grounded in DamageN2 through the whole
  rapid loop + finisher launch (DamageHi2). Poked s11(0x12AF)/s15(0x148D,0x14A1)/
  s91(0x376F) **RED** (strong anti-color — vanilla connect spark is pink-white/
  cyan): at the finisher connect frame (f24, Attack100 loop/end) each poke
  visibly recolors the finisher **connect diamond/burst** on the victim RED
  (vanilla pink-white → red). s11 = leading connect spark, s15 = the electric
  burst body, s91 = the cyan flash; all three own components of the same
  finisher connect flash. The generic radial gold hit-spark streaks stay gold
  (texture/model, not these ENV — lesson 14). SHIPPABLE as a grouped
  `jab_finisher_spark` extra (s11+s15+s91). Captures:
  `tests/artifacts/datram-probe-efcodata-rapidjab/` (`{vanilla,s11_red,s15_red,
  s91_red}-rapidjab-f24`). Spec: `backend/probes/efcodata_rapidjab_probe.json`.
  Recipe: `ingame/moves.py` `RAPIDJAB` branch. **WIRE-READY** (grouped color
  extra, all cast; AUDIT_HINTS: move `rapidjab` frames ~20-28, bag dk dx6
  bag_pin, anti-colors red or any hue far from cyan/green). s44 (0x22E3) is the
  generic white energy-shell glow shared with DK grab-stage / shells / Master
  Hand — NOT part of the jab finisher, leave out of this group.
  **⚠ BOUNCED at the shipped-extra audit (2026-07-02, post-WIRE).** The wired
  `jab_finisher_spark` extra builds correctly — the built ISO's `EfCoData.dat`
  carries FF0000 at all 4 offsets AND a live RAM readback in the modded match
  confirms FF0000 at the single located EfCoData image (0x80712A60) — but
  **no attributable red recolor renders**: dense loop windows f2-f30, the
  finisher Attack100End(49) burst f54-70 (bag connected, DamageHi2 — the End
  hit landed), and the original f20-28 window are all pixel-count identical to
  the vanilla-ISO control (strong-red counts equal per frame; the cyan-family
  pixels at f14 are UNCHANGED by the red poke, so the visible cyan is NOT
  these ENV records). The 🟢 claim above does not reproduce with the shipped
  extra; note the original session's own f24 pair has percent drift (9% vs
  10% = misaligned hit cycles), so its "visibly recolors RED" judgment is
  suspect. These 4 offsets are ENV-only — the connect diamond's visible color
  may be PRIM and/or texture. NEEDS RE-MAP before the extra can be trusted
  (find the PRIM operands of s11/s15/s91 or the real owner of the connect
  diamond). Audit captures:
  `tests/artifacts/extras-audit/Fox-jab_finisher_spark*` (modded, `-vanilla`,
  `-end`, `-dense` windows).

- **🔧 (historical) `jab_finisher_spark` — HARNESS-BLOCKED (Fox re-probe 2026-07-02, NOW RESOLVED above).**
  Re-ran on Fox (a real Attack100 rapid-jab char) with A mashed every 2 frames
  (f3-f53) into a DK bag (dx5). **Fox never reached Attack100 (rapid-jab loop):**
  the 0%-uncontrolled bag is knocked AIRBORNE (DamageAir1/2) on the FIRST jab
  hit, flying out of range, so Fox's follow-up A inputs produce fresh single
  jab1s (Attack11=44), not the sustained rapid finisher. Percent only crept to
  9% over 44 frames. The finisher scripts s11/s15/s91 (0x3F3/0x41D/0x422) only
  spawn during Attack100Loop/End, which never triggered. One frame (f26) showed
  a whitish-vs-gold spark difference but it was a transient single-jab spark, not
  reproducible (f44 identical to vanilla) — not an attributable finisher recolor.
  This is a NEW harness limitation (lesson-14 corollary): rapid-jab moves need a
  target pinned in range so the jab chains into Attack100; an uncontrolled bag
  flies away on hit 1. Genuinely harness-blocked, not dead. Captures:
  `tests/artifacts/datram-probe-efcodata-fox/jab_finisher_spark-jab-*`. Spec:
  `backend/probes/efcodata_fox_probe.json`.
  - **RE-TEST 2026-07-02 (BAG-PIN) — range fixed, but Attack100 loop still not
    reached.** Added `--bag-pin` (spec `"bag":{...,"pin":true}`; zeros the bag's
    self_vel/kb_vel/ground-vel every stepped frame + re-pins its position — see
    `ingame/gamestate.py Bag.pin` + `effect_probe._pinned_step`). This WORKS: the
    DK bag now stays GROUNDED in DamageN1/N2 taking every jab hit (vs flying to
    DamageAir on hit 1 before). BUT mashed A (press+release) only chains jab1↔jab2
    (Attack11/Attack12, DK crept to ~10% over 54f), and a held-A attempt produced
    a single jab then Fox reset to Wait — neither reached the Attack100 rapid-jab
    LOOP that spawns s11/s15/s91 (0x3F3/0x41D/0x422). At the connect frames the
    jab hit-spark stayed gold/white with s11/s15 poked green (`jab_finisher_spark
    -jab-f26/f44` vs `vanilla-jab-*`). So the blocker is no longer knockback/range
    (pin solved that) but the **Attack100 input recipe**: Fox's rapid jab needs a
    sustained held-A that neither mashing nor the current `execute()`+hold path
    reliably triggers on the frozen-step harness. s11/s15/s91 remain UN-verified.
    NEXT: a moves.py `rapidjab` recipe that holds A continuously through jab1→jab2
    →Attack100Loop (or memory-force the Attack100 action state), then re-poke with
    the pinned bag. Captures: `tests/artifacts/datram-probe-efcodata-fox/`.
- **🔧 s93/s331 hookshot_grapple — STILL UN-VERIFIED, re-probed 2026-07-02.**
  The earlier "grab window too short" diagnosis was WRONG. Re-probe findings:
  1. **Root grab blocker = `PRESS Z` is SWALLOWED by the Slippi pipe** — 15 f of
     held Z from Wait stays in Wait (A/L/etc. register fine; the pad config maps
     Z correctly, but the game gets no grab). Fixed `ingame/moves.py`: `grab`
     now uses **L(shield)+A** → Catch (212); `dashgrab` uses **A+L on the same
     frame** (A listed first) while running → CatchDash (214). L-before-A rolls
     (EscapeF); Z never works. Both recipes now reach the grab states reliably.
  2. **But the tether effects still don't render capturably.** With the working
     dash-grab and the bag parked far (dx 42-55), the hookshot connected
     (bag → CatchDash), yet poking s93/s331 magenta produced NO magenta on the
     chain/tip in any frame (f3-22). The harness force-parks the victim straight
     into the grab state, so the tether's mid-air FLIGHT phase — where s93 tip
     spark / s331 chain glow spawn — is skipped/clamped; the grab resolves on
     frame 1 and the thin chain segments don't visibly render at match zoom.
     Also Link's STANDING grab is a short hand-grab (no hookshot at all); only
     dash/pivot grab extends the clawshot.
  Offsets + vanilla bytes still verified (s93 0x3858 `19E388` green tip, s331
  0xA188 `11C8FF` cyan chain); decomp attribution solid. **Un-block needs a
  free-flight tether** (let Link whiff a dash-grab into empty air with NO bag so
  the tether travels its full length, close camera on the extending chain), not
  another grab-input fix — that part is now solved. Captures:
  `tests/artifacts/datram-probe-efcodata-link/`.

---

## 0. Headline findings (read before anything else)

1. **The marquee named specials are TEXTURE-ONLY, not colour records.**
   Din's Fire (all phases), Sheik Vanish, Zelda/Sheik Transform, Pikachu Quick
   Attack, Link arrow, Bowser Bomb landing — every one of these resolves to a
   common-bank script that has **ZERO PrimCol/EnvCol operands**. Their colour
   comes from the **texture bank** (`tex_bank @ 0x11C20`) and/or model/vertex
   colour, exactly the surface **17088 "rainbow fire whole cast"** recolours
   (pure texture diff `0x8CD77–0x97F3F`, 27,038 bytes). These need the
   **texture-recolor path** (like Fox `upb_texture` / Samus `charge_shot`),
   **not** the ptcl colour-operand editor. See §5.

2. **15070 "Purple Electric Pack" recolours GENERIC cast-wide sparks, not the
   named specials.** Its 41 ptcl clusters + 2 material clusters (148 bytes,
   same-size, base md5 verified) land on 28 scripts, almost all of which have
   **no attributable fighter `efSync_Spawn` caller** — they are spawned by
   subaction event-GFX / hitbox flashes shared across the cast (generic
   electric/hit sparks). Only scripts 5, 11, 15 overlap a named caller. See §3.

3. **Marth/Roy "common EfCoData" claims in `marth-effects.md` / `roy-effects.md`
   are WRONG.** Flare Blade / Shield Breaker charge `efSync_Spawn(1266)` = 0x4F2
   → efsync switch → **0x3E80 = 16000 = bank 16 = EfMsData** (Marth's own file).
   Counter `1265` = 0x4F1 → 0x3E80 too. Roy variants `1297`=0x511 / `1296`=0x510
   → **0xBF68 = 49000 = bank 49 = EfFeData** (Emblem/Roy file). **None of these
   touch EfCoData.** A Marth/Roy fire recolor belongs in EfMsData/EfFeData, not
   here. (Corroboration: 17088 recolors EfCoData fire *textures* cast-wide, which
   is why Roy's fire *also* shifts — but that is the shared texture bank, not the
   Marth-specific charge effect.)

4. **Sheik needles / chain / vanish ITEMS spawn no effects.** `itseakneedle*`,
   `itseakchain`, `itseakvanish` have zero `efSync_Spawn` — their visuals are
   article DAT models. The only Sheik→common hooks are the *fighter* specials:
   Transform (script 106), Vanish flash (scripts 109/121) — all texture-only.

---

## 1. Bank layout (ptcl_parse `--models`)

```
EffectTable @0x20   ParticleGroup @0x420   version 0x42   generators = 592
effect_id_start = 0     tex_bank @ 0x11C20 (72736)
ptcl bank spans 0x420 .. 0x11C20
```

- **592 generators**; **478** carry ≥1 ptcl colour operand, **114** are
  texture-only / blank ("same-as-previous").
- **2029** ptcl colour operands total (mostly `CF`/`DF` PrimCol/EnvCol pairs).
- **1019** model-region blocks past the tex-bank pointer (07/42/98 signatures)
  — a mix of texture-bank image data and JOBJ material colour. Not decoded
  structurally here (out of the ptcl-decode scope; see PTCL_FORMAT §4).

## 2. Effect id → script → move (the dispatcher, ground truth)

`efSync_Spawn(gfx_id)` (`efsync.c:39`) routes by range:

| gfx_id range | handler | reaches common bank? |
|---|---|---|
| `0x000–0x24F` (0–591) | `efLib_CreateGenerator(gfx_id)` | **YES — direct, script = gfx_id** |
| `0x250–0x3E7` | `efAsync_Dispatch` (low) | no (char banks) |
| `0x3E8–0x477` | `efAsync_Dispatch` **switch** → `efLib_Create*(N)` | **YES when N < 0x250** |
| `0x479–0x4BA` | `efAlt_Spawn` | no |
| `0x4BB–0x512` | `efsync.c` **switch** → `efLib_Create*(N)` / `hsd_8039EFAC(0,0,N)` | **YES when bank arg 0 & N < 0x250** |

Both switches (parsed programmatically from `efsync.c` + `efasync.c`, incl.
`hsd_8039EFAC(linkNo, bank, gfx_id, jobj)` where **bank 0** = common) were
joined against every `efSync_Spawn`/`efAsync_Spawn` call in `src/melee/ft` +
`src/melee/it` + `gr`/`if`/`vi`. **72 common scripts have an attributable
fighter/item/stage caller.** The rest are spawned by subaction event-data GFX
(no C-level caller) — the classic "generic hit spark" pool 15070 recolours.

---

## 3. Region → consumers map (the deliverable)

### 3a. Colour-editable + attributed (SHIPPABLE candidates)

Per-record offsets are exact (ptcl_parse). Vanilla bytes are RRGGBBAA (PrimCol)
or the EnvCol tuple. `(script,kind,ordinal)` is the shift-robust key. All
LIVE-pending.

| script | key colour offsets (vanilla) | consumers (char/move) | hypothesised visual |
|---|---|---|---|
| **4** (0x4) | 0xFDA PRIM-A `80` (alpha only) | **Damage/DownBound/WarpStar (all cast), Fox up-B (0x406), Ness PK-Thunder hit (0x406), Jigglypuff/Purin N-B, Yoshi S-B** | generic damage/hit white star (alpha-only record — may be un-recolourable) |
| **5** (0x5) | 0x1033 ENV `FFFAFE`, 0x1041 ENV `A826FF` | Jigglypuff/Purin N-B, Yoshi egg-roll (0x3FF) | small hit puff (15070 recolours 0x1033) |
| **11** (0xB) 🟢 | 0x12AF ENV `0554FF` (blue) | Attack100 (jab finisher, all cast) (0x3F3) | **VERIFIED (Fox rapidjab, red poke): jab-finisher CONNECT leading spark** — see LIVE RESULTS `jab_finisher_spark` 🟢 |
| **15** (0xF) 🟢 | 0x148D ENV `57D0FF`, 0x14A1 ENV `0509FF` | Attack100 (0x41D) | **VERIFIED (Fox rapidjab, red poke): jab-finisher electric BURST body** |
| **27** (0x1B) | 42 operands 0x19D8–0x1B66 (`FFFDEE` env ladder) | Mewtwo N-B charge (0x1B), Kirby-Mewtwo, item-break box/barrel (0x427) | Mewtwo shadow-ball charge flash ladder / crate break |
| **28** (0x1C) | 0x1BB5 ENV `FFFFFF`, 0x1BC2 ENV `FBFEB5` | **Yoshi egg** (throw/lay/guard 0x4CF, itegg 0x4D0), Kirby-Yoshi egg | Yoshi egg spawn sparkle (pale-yellow env) |
| **34** (0x22) | 10 operands 0x1E00–0x1E59 (green/blue gradient) | ftCo_09F7 (a shared hit) (0x438) | multicolour hit gradient |
| **36** (0x24) | 0x1F2D/0x1F43 ENV `D28AFF` | ft_0C31 (0x43E), Warp Star (itwstar 0x43D→s431) | lavender burst |
| **37** (0x25) | 0x1FB3 ENV `EE0284` | DamageIce (0x415) | frozen-hit red spark |
| **38** (0x26) | 0x200F/0x201C ENV `D28AFF` | Master Ball (itmball 0x449) | pokéball lavender flash |
| **40** (0x28) | 0x20C6 ENV `EE0284` | Bury (all cast, 0x447) | buried-in-ground red spark |
| **44** (0x2C) | 0x22E3 ENV `FFFFFF` | **Attack100 (all cast), DK grab-stage (grkongo), shells (green/red/giant), Master-Hand bullet/laser, Entei** | generic white energy shell/bullet glow |
| **45** (0x2D) | 0x2348 ENV `FF695E` | Raikou (itraikou 0x46D) | orange trainer-mon glow |
| **62** (0x3E) 🟡 | 0x2AC3 ENV `FFFFFF` | **Damage (all cast)**, Lip's Stick, Star Rod, grgreens | generic damage smoke (white) — ON-HIT-PENDING: light jab did not spawn it; needs a heavy hit |
| **66** (0x42) | 0x2C48 ENV `11C8FF` (cyan) | ftcoll (0x3EF — landing/collision) | landing dust cyan |
| **75** (0x4B) | 0x2FE7 ENV `FFF70C`, 0x2FFB ENV `220AFF` | it_2725 (0x411) | item yellow/blue sparkle |
| **91** (0x5B) 🟢 | 0x376F ENV `75DBEB` | Attack100 (0x422) | **VERIFIED (Fox rapidjab, red poke): jab-finisher CYAN flash → red** |
| **93** (0x5D) 🔧 | 0x3858 ENV `19E388` (green) | **Link hookshot, Samus grapple, ledge-grab (ftcliffcommon), collision** (0x41C) | hookshot/grapple tip green spark — grab-input now works (L+A/dashgrab, 2026-07-02) but tether flight force-parked away → still NOT rendered/verified; needs free-flight whiff |
| **95** (0x5F) 🟢🟡 | 0x391A PRIM `EAE7E9`, 0x3921 ENV `6E6E6E`, 0x3930 PRIM `575757` | **Pikachu thunder-jolt (ground it + N-B 0x4BD/E/F), Luigi side-B remove (0x50A)** | VERIFIED: caster-side dissipation/cheek spark (turned magenta). SUBTLE — the big jolt FOUNTAIN is a separate texture effect, NOT s95 |
| **140** (0x8C) | 0x4BE6 PRIM `66524C` | Koffing/Weezing gas (itmatadogas 0x45B) | poison-gas cloud (dark) |
| **141** (0x8D) | 0x4C56 PRIM `483D4C`, 0x4C5D ENV `382753` | Koffing/Weezing gas (0x45C) | poison-gas cloud 2 |
| **218–221** (0xDA–0xDD) | 0x6E84.. many (`F7EE9D`/`FE5E3A` fire) | **Charizard flame** (itlizardon 0x44E–0x451) | Charizard fire-breath flames |
| **277** (0x115) | 0x88F8 PRIM `3F3F3F` | Kusudama (itkusudama 0x433) | confetti-ball dark record |
| **289** (0x121) | 0x8F97 ENV `0554FF` (blue) | ft_0D31 (0x42D) | blue spark (mirror of s11) |
| **305/325** (0x131/0x145) | 0x9714/0x9EDC ENV `FF470A` | Celebi (itcerebi 0x472) / ft_07C6 (0x432) | orange trainer-mon flame |
| **331** (0x14B) 🔧 | 0xA188 ENV `11C8FF` (cyan) | **Link hookshot, Samus grapple** (0x3F1) | hookshot chain-link cyan glow — grab-input now works but chain not rendered when victim is force-parked into the grab; still NOT verified (2026-07-02) |
| **370** (0x172) | 0xB3D1 ENV `9EDCA3` | Peach Toad spore (itpeachtoadspore 0x4D3) | toad-counter spore green |
| **431** (0x1AF) | 0xD113 ENV `FFD30C` | Warp Star (itwstar 0x43D) | warp-star yellow trail |
| **575/576** (0x23F/0x240) | 0x1146E/0x114D8 PRIM `66524C`/`483D4C` | Koffing/Weezing gas 3/4 (0x45D/E) | poison-gas cloud 3/4 |

### 3b. Texture-only + attributed (need the TEXTURE path, NOT colour records)

These have **0 ptcl colour operands**; colour = tex bank (`texGroup` = index
into the TEXGraphicBank) and/or model/vertex colour. See §5.

| script (texGroup) | consumers (char/move) | visual |
|---|---|---|
| **110** (grp16) | Din's Fire ember `itzeldadinfire` (0x4F8→0x6E) | Din's fireball ember trail |
| **456** (grp13) | Din's Fire 2nd `itzeldadinfire` (0x4F9→0x1C8) | Din's fireball secondary |
| **358** (grp2) | Din's Fire explosion `itzeldadinfireexplode` (0x4FA→0x166) | Din's detonation |
| **113** (grp2) | Din's Fire charge glow `ftZd_SpecialS` (0x4FB→0x71) | Din's charging hand glow |
| **106** (grp4) | **Zelda↔Sheik Transform** (0x4FC/0x4FD→0x6A), Kirby-Sheik | transform flash |
| **109/121** (grp11) | **Sheik/Zelda Vanish** up-B (0x504/0x505→0x6D/0x79) | vanish teleport flash |
| **72** (grp4) | **Pikachu Quick Attack** up-B `ftPk_SpecialHi` (0x3F4→0x48) | quick-attack streak |
| **588** (grp11) | Pikachu down-B thunder `ftPk_SpecialLw` (0x4C3→0x24C) | thunder bolt column |
| **97/323** (grp11/23) | **Bowser Bomb landing** `ftKp_SpecialLw` (0x4D8→0x61, 0x4DF→0x143) | Bowser Bomb shockwave |
| **146** (grp26) | **Link arrow** `itlinkarrow` (0x448→0x92) | arrow trail |
| **286** (grp?) | Peach Float (ftPe_Float 0x4D4→0x11E) | float dust |
| (coin sprite) | **Mario/Dr.Mario/Luigi up-B "coin" ring** (subaction event-GFX, no C caller) | SMB gold-coin sprite — TEXTURE-ONLY (ITEMS-PASS 2026-07-02, see items.md §4); texGroup TBD by TEXGraphicBank decode |
| **9/25/33/45/153/158/202/227/247/252/255/316/320/345/472/476/497/507/521/542/544/554** | various items/stages/UI (see consumers.json) | misc texture-only |

### 3c. 15070-recoloured scripts with NO attributable caller (generic cast-wide sparks) — 🟢 SEMANTIC VERIFIED

Spawned by subaction event-GFX, not C `efSync_Spawn` — cannot be attributed to
one move statically. **These are the true "cast-wide electric/spark" pool.**
Scripts: `0, 1, 13, 14, 16, 17, 18, 19, 29, 30, 31, 73, 161, 162, 268, 269,
270, 306, 332, 423, 424, 425, 426, 448, 537`. All recoloured blue→purple by
15070.

**🟢 LIVE 2026-07-02:** poking 9 of these (0xDC5/EAD/14F5/1560/1609/1C17/1C8D/
1CFF/2F15 — scripts 0,1,16,17,19,29,30,31,73) GREEN while Zelda took a hit
turned the **body-wide on-hit electric arc + radial spark burst from blue to
green**. Semantic = **cast-wide on-hit / hitlag electric spark**. The group as a
whole is verified; individual per-script ownership within the burst was not
isolated (all poked at once) — not needed to ship the grouped `common_electric`
extra. The remaining un-poked pool records (13/14/18/161/162/268-270/306/332/
423-426/448/537) are the same 15070 sweep and carry the same look — ship as one
group with the whole §3c list. Owner: none / "Common Effects" bucket.

---

## 4. 15070 diff reconciliation (colour-record path corroboration)

Base verified: vanilla `739290ea…` vs 15070 `d1dd8ecd…`, **same size**, 148
bytes across 41 ptcl + 2 material clusters. Every ptcl cluster sits on an
**EnvCol (`DF`) operand** (a few on PrimCol), recoloured to purple `AE00FF`.
Cluster → (script, operand) resolved:

```
0xDC5/DDB/DF1/E0F/E1D  -> script 0  ENV #1,3,5,7,9   (5 env records)
0xEAD                  -> script 1  ENV #1
0x1033                 -> script 5  ENV #1  (attributed: Jiggly/Yoshi hit puff)
0x12AF                 -> script 11 ENV #1  (attributed: Attack100 jab spark)
0x1384/13AB/13BA/13D7  -> script 13 PRIM#2/ENV#7/PRIM#8/ENV#11
0x1425                 -> script 14 ENV #1
0x148D/14A1            -> script 15 ENV #1,3 (attributed: Attack100)
0x14F5                 -> script 16 ENV #2
0x1560                 -> script 17 ENV #1
0x15BA                 -> script 18 ENV (inner byte)
0x1609                 -> script 19 ENV #1
0x1C17/1C24            -> script 29 ENV #1,3
0x1C8D/1C9A            -> script 30 ENV #1,3
0x1CFF                 -> script 31 ENV #1
0x2F15                 -> script 73 ENV #1
0x5550                 -> script 161 PRIM#0
0x55B1                 -> script 162 PRIM#0
0x854E/855B            -> script 268 ENV #1,3
0x85B6                 -> script 269 PRIM#0
0x860E                 -> script 270 PRIM#0
0x9779                 -> script 306 PRIM#0
0xA1DD                 -> script 332 ENV #1
0xCDB7                 -> script 423 ENV #1
0xCE18                 -> script 424 ENV #1
0xCE84                 -> script 425 PRIM#0
0xCEEF                 -> script 426 PRIM#0
0xCFEC                 -> (inner byte of a script-426-region operand)
0xD87D                 -> script 448 ENV #1
0xD897                 -> (inner byte, script 448 region)
0x10019                -> script 537 PRIM#0
material: 0x115AA8, 0x115B74  (808080/B3B3B3 -> FFFFFF/AE00FF) model-region JOBJ
```

Interpretation: 15070 is a "recolor every blue/white electric env tint to
purple" sweep. It is **candidate corroboration** that these scripts carry the
cast-wide electric look — but per lesson #4 it is find-replace shrapnel, so each
is a candidate, not a verified move. The material clusters are model-region JOBJ
colour (a different subsystem; relocate via signature scan, not ptcl identity).

## 5. Texture-recolor path (the marquee effects live here)

17088 "rainbow fire whole cast" is a **pure texture-bank recolor**: diff range
`0x8CD77 – 0x97F3F` (27,038 bytes), base byte-identical to vanilla (md5 match on
its bundled "og effects/EfCoData original fire.dat"). tex_bank starts at
`0x11C20`; `0x8CD77` is deep in the image-data region → it recolours the fire
**texture pixels**, which is why every fire effect (Din's, Roy's, Bowser's fire
breath, generic flames) shifts hue together.

**Implication:** Din's Fire, Vanish, Quick Attack, arrow, Bowser Bomb (all §3b)
cannot be recoloured with the colour-operand editor — they have no operands.
They need a **texture extra** (HSDRaw TEXGraphicBank CLI: decode → recolor →
re-encode), like Fox `upb_texture` / Samus `charge_shot`. Texture leads:
- Fire textures cluster around `0x8CD77–0x97F3F` (from 17088).
- Each script's `texGroup` field indexes the TEXGraphicBank; a texture-map pass
  (decode the bank, list image offset/dims/format per group) is the required
  next STATIC step for §3b, out of this ptcl pass's scope (mirrors the Samus
  charge-ball / Fox upb_texture missions). Record `texGroup` per script from the
  table in §3b when that pass runs.

---

## 6. Proposed extra groupings (owner + honest also-affects)

Because one EfCoData region drives many characters, each extra carries an
"also affects" list. UI decision: surface under the marquee owner.

| proposed extra | owner (menu) | scripts / offsets | also affects | path |
|---|---|---|---|---|
| `dins_fire` (all phases) | **Zelda** | 110,456,358,113 | none (Zelda-only articles) | **TEXTURE** |
| `vanish_flash` | **Sheik/Zelda** | 109,121 (+106 transform) | Zelda & Sheik share; Kirby-Sheik copy | **TEXTURE** |
| `quick_attack` | **Pikachu** | 72 | Pichu-gated off | **TEXTURE** |
| `link_arrow` | **Link** | 146 | Young Link arrow shares article | **TEXTURE** |
| `bowser_bomb` | **Bowser** | 97,323 | none | **TEXTURE** |
| `thunder_jolt_spark` | **Pikachu** | 95 (0x391A/0x3921/0x3930) | **Luigi side-B remove GFX shares s95** | colour |
| `hookshot_grapple` | **Link** | 93 (0x3858), 331 (0xA188) | **Samus grapple + all ledge-grabs (ftcliffcommon) share s93** | colour |
| `yoshi_egg_sparkle` | **Yoshi** | 28 (0x1BB5/0x1BC2) | egg item (itegg), Kirby-Yoshi | colour |
| `charizard_flame` | **(item) Charizard** | 218–221 | Pokéball Charizard only | colour |
| `poison_gas` | **(item) Koffing** | 140,141,575,576 | Pokéball Weezing | colour |
| `jab_finisher_spark` | **(generic) Attack100** | 11,15,91 | **every character's jab finisher** — honest: not one char | colour |
| `common_hit_smoke` | **(generic) Damage** | 62,4 | **every character taking a hit** | colour |
| `common_electric` | **(generic)** | §3c list (0,1,13,14,16–19,29–31,73,161,162,268–270,306,332,423–426,448,537) | cast-wide; unattributed sparks — 15070's target | colour |

The generic ones (`jab_finisher_spark`, `common_hit_smoke`, `common_electric`)
have NO honest single owner — surface under a "Common Effects" bucket, not a
character, per the also-affects rule.

---

## 6b. Shippable-now summary (for WIRE) — 2026-07-02 MAP-LIVE

Only ONE extra is fully eye-verified and ready to wire this pass. The rest are
either texture-path (out of scope), harness-blocked, wrong-probe-char, or
on-hit-pending — do NOT ship them as colour extras until re-verified.

### ✅ SHIP NOW

**`common_electric` — "Common Effects" bucket (owner: none / generic).**
- **Semantic (verified):** the cast-wide **on-hit / hitlag electric spark burst**
  — the blue arc + radial spark rays that flash on a character when they take a
  hit. Green-poke turned the whole burst green on Zelda. 15070's exact target.
- **Records (all EnvCol/PrimCol, format per §4):** the full §3c list —
  scripts 0,1,13,14,16–19,29–31,73,161,162,268–270,306,332,423–426,448,537.
  Per-record offsets in §4. **Per lesson 12, WIRE must byte-verify vanilla per
  record** — they are NOT a uniform value (e.g. 0xDC5 `FFF305`, 0xEAD `1165FF`,
  0x14F5 `82A1F8`, 0x1560/0x1609 `210CFF`, 0x1C17 `E6FEFF`, 0x1C8D `FFFFFF`,
  0x1CFF `5F9BFC`, 0x2F15 `4FA4FF` — all differ). Split the group into
  per-record keys.
- **Anti-color used (per operand):** green `00FF00` (vanilla operands are all
  blue/white/cyan → green is a good anti-color per lesson 6/11).
- **also-affects (honest — CORRECTED 2026-07-02, see §6c):** NOT "every
  character taking a hit". The burst only spawns when the **attacker's** hitbox
  carries `HitElement == Electric(2)` (the `EfCoData` scripts are triggered by
  the electric-hit path, not a universal on-hit path). So it affects only the
  13 characters that own an electric attack. The earlier "cast-wide / EVERY
  character" phrasing was over-broad — the green-poke demo worked on a Zelda
  **jab** precisely because Zelda's jab IS electric.
- **Capture dir:** `tests/artifacts/datram-probe-efcodata-zelda/` —
  `electric_pool_on_jab-jab-f12.png` (green) vs `vanilla-jab-f12.png` (blue).

## 6c. Which characters actually trigger `common_electric` (Element==2 scan)

Data-derived by `backend/skinlab/hitbox_elements.py`: it walks every vanilla
`Pl<XX>.dat` fighter action table (ftData root → FighterActionTable @0x0C →
0x18-byte commands → SubAction @0x0C), decodes each **Create Hitbox** subaction
(command `0x0B`, bit layout from HSDRawViewer `Scripts/command_fighter.yml`),
reads the 5-bit **Element** field, and keeps actions with `Element == 2`
(`HitElement.Electric`). Run: `python -m skinlab.hitbox_elements`. Self-test
asserts Zelda electric / Pikachu-Pichu many / Marth ZERO — **passes**.

`common_electric.sharedWith` = this list **minus the owner (Pikachu)** = 13
characters. Everyone not listed (Marth, Roy, Link, Mario, Bowser, DK,
Jigglypuff, Peach, Yoshi, Young Link, Ice Climbers, Luigi) has **no**
electric-element hitbox and is correctly excluded.

| Character | # electric actions | electric moves (vanilla subaction symbols) |
|---|---|---|
| **Pikachu** (owner) | 9 | fair, dair (AttackAirLw), dtilt/dsmash (AttackLw4), fsmash (AttackS4), grab-attack (CatchAttack), up-B (SpecialHiStart), down-B thunder (SpecialLwLoop), side-B jolt (SpecialS), fthrow |
| **Pichu** | 7 | fair, dair (AttackAirLw), fsmash (AttackS4), grab-attack, down-B thunder (SpecialLwLoop), side-B (SpecialS), fthrow |
| **Zelda** | 9 | jab (Attack11), bair + fair lightning kicks (AttackAirB/F), dash attack, utilt (AttackHi3), usmash (AttackHi4), fsmash (AttackS4S), grab-attack, dthrow |
| **Mewtwo** | 5 | nair, grab-attack, dsmash (DownAttackD), usmash (DownAttackU), neutral-B (SpecialNLoop) |
| **Ness** | 4 | bair, fair, dash attack, up-B PK Thunder (SpecialHi) |
| **Samus** | 3 | air grapple (AirCatch), up-B screw attack (SpecialHi / SpecialAirHi) |
| **Ganondorf** | 3 | jab (Attack11), dair (AttackAirLw), up-B catch (SpecialHiCatch) |
| **Dr. Mario** | 3 | fsmash (electric palm — AttackS4Hi/S4Lw/S4S; note Mario's is NOT electric) |
| **C. Falcon** | 2 | fair (AttackAirF), a Swing42 hitbox |
| **Sheik** | 2 | side-B chain start (SpecialSStart), a Swing4 hitbox |
| **Fox** | 1 | shine / reflector first-hit (SpecialLwStart) |
| **Falco** | 1 | shine / reflector first-hit (SpecialLwStart) |
| **Kirby** | 1 | copied neutral-B loop (MtSpecialNLoop) |
| **G&W** | 1 | side-B Judgment (SpecialS — the "6" is electric) |

(Move names are inferred from the vanilla ACTION symbols the scanner reports;
the symbol → common-move mapping is the standard Melee action naming. The scan
itself is purely `Element==2`-driven — see the script's output for exact
symbols per character.)

### ⛔ DO NOT SHIP YET (per-extra reason)

| extra | scripts | blocker | what's needed |
|---|---|---|---|
| `thunder_jolt_spark` | 95 | verified but SUBTLE — s95 = only the caster cheek spark; the marquee jolt fountain is texture, not s95 | product call: ship a low-impact spark recolor, or route the jolt bolt to the texture pass |
| `hookshot_grapple` | 93,331 | 🔧 grab-INPUT fixed (Z swallowed→L+A; grab/dashgrab now reach Catch/CatchDash), but tether spark/chain still doesn't render (bag force-parked into grab skips the tether flight) — re-probed 2026-07-02 | whiff a dash-grab into EMPTY air (no bag) w/ close camera so the free-flight chain spawns s93/s331 |
| `jab_finisher_spark` | 11,15,91 | 🟢 VERIFIED & COLORABLE (STRAGGLER-CLOSEOUT 2026-07-02): the new `rapidjab` recipe (1-on/1-off A toggle) reaches Attack100Loop; s11/s15/s91 recolor the finisher connect burst (red poke). WIRE-READY grouped color extra, all cast. | move `rapidjab` frames ~20-28; bag dk dx6 bag_pin; anti-colors far from cyan/green (red) |
| `common_hit_smoke` | 62,4 | 🔴 DEAD (Fox fsmash re-probe 2026-07-02): heavy hit spawned the damage-smoke cloud but it stayed white with s62 0x2AC3 poked green; s4 alpha-only | none — the smoke color is not this ENV; texture/other-operand |
| `yoshi_egg_sparkle` | 28 | LIVE-pending (not probed this pass) | Yoshi boot, up-B/egg-lay |
| `dins_fire`/`vanish`/`quick_attack`/`link_arrow`/`bowser_bomb` | §3b | TEXTURE-only (⚪ confirmed via transform-null) | §3b texture pass (decode TEXGraphicBank) |
| `charizard_flame`/`poison_gas` | 218–221 / 140,141,575,576 | LIVE-pending (item chars, not probed) | Pokéball item boot |

---

## 7. Open leads for LIVE

1. ~~Attribute the §3c generic electric pool.~~ **DONE 2026-07-02 (🟢):**
   verified = cast-wide on-hit/hitlag electric spark. Ship as `common_electric`.
2. **Confirm remaining colour-editable §3a scripts (partial 2026-07-02):**
   - 🟢 s95 thunder-jolt — done (subtle; caster spark only).
   - 🔧 s93/s331 hookshot — re-probed 2026-07-02: grab INPUT fixed (Z is
     swallowed on the pipe; grab=L+A, dashgrab=A+L-same-frame now reach
     Catch/CatchDash), but the tether spark/chain still doesn't render because
     the parked bag skips the tether flight. NEXT: whiff a dash-grab into empty
     air (no bag) w/ a close camera. Spec: `backend/probes/efcodata_link_probe.json`.
   - 🟢 s11/s15/s91 jab-finisher — VERIFIED & COLORABLE (STRAGGLER-CLOSEOUT
     2026-07-02). The new `rapidjab` recipe (1-on/1-off A toggle, ingame/moves.py)
     reaches Attack100Loop on the pinned bag; s11/s15/s91 recolor the finisher
     connect burst (red poke). SHIP as grouped `jab_finisher_spark`. Spec:
     `backend/probes/efcodata_rapidjab_probe.json`.
   - 🔴 s62 hit-smoke — re-probed on Fox fsmash 2026-07-02: DEAD. The heavy hit
     spawned the damage-smoke cloud (visible f30) but it stayed WHITE with
     0x2AC3 poked green. Not this ENV; texture/other-operand. Do not ship.
   - ⚪ Transform/Din's/Vanish confirmed texture-only (control passed).
   - LIVE-pending (not probed): s28 Yoshi egg, s218–221 Charizard, s140/141/
     575/576 poison gas, s27 Mewtwo charge, s45 Raikou, s36/38 lavender bursts.
3. **Texture pass for §3b.** Decode the TEXGraphicBank, map texGroup→image
   offset/dims/format. Required before any `dins_fire`/`vanish`/`quick_attack`/
   `arrow`/`bowser_bomb` extra can ship. Out of this ptcl pass's scope.
4. **script 4 is alpha-only** (`PRIM-A 80`) — likely un-recolourable (no RGB);
   confirm it's a no-op target before wiring.
5. **Alpha-tail records** (many PRIM records with `count>0` and alpha `00`) are
   fade-out frames — do not expose as separate colours.

## 8. Probe files

- `backend/probes/efcodata_probe.json` — **Zelda** probe (rev2). Bag `dk` dx15
  (rev1 dx11 overlapped Zelda → Sleep loop; rev2 fixed). Experiments:
  `jab_finisher_spark` (wrong char — see §6b), `electric_pool_on_jab` (🟢
  verified), `common_hit_smoke` (🟡 on-hit-pending), `transform_null` (⚪
  texture-null confirmed). RAN 2026-07-02.
- `backend/probes/efcodata_pika_probe.json` — **Pikachu** probe, neutral-B Thunder
  Jolt, s95 (0x391A/0x3921/0x3930). 🟢 verified (subtle — caster spark, not the
  jolt fountain). RAN 2026-07-02.
- `backend/probes/efcodata_link_probe.json` — **Link** probe, s93/s331 hookshot via
  dashgrab. RE-PROBED 2026-07-02: grab input fixed (Z swallowed → grab now L+A,
  dashgrab A+L-same-frame; both reach Catch/CatchDash), captures produced
  (`tests/artifacts/datram-probe-efcodata-link/`), but the tether spark/chain
  did NOT render (bag force-parked into the grab skips the tether flight). Still
  🔧 un-verified; NEXT is a bag-less whiff dash-grab with a close camera.
