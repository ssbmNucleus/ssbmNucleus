# Ness effect map (MAP-LIVE — 2026-07-02)

Mission: extras campaign, Ness electric/PSI effects. **LIVE pass complete.**
Offsets parser-/marker-verified against vanilla `storage/test-base/files/`;
semantics now judged by live anti-color pokes (green `00FF00` / magenta
`FF00FF`). Probe spec: `backend/probes/ness_probe.json`. Capture dirs:
`tests/artifacts/datram-probe-ness/` (main sweep) +
`tests/artifacts/datram-probe-ness-batyoyo/` (bat/yo-yo re-boot).

## LIVE VERDICT SUMMARY (2026-07-02)

- **Model[2] = PSI Magnet (down-B) absorb aura** — 🟢 VERIFIED. Poking Model[2]
  turned the whole down-B electric aura green-core + magenta-arcs (dramatic).
  Model[0] and Model[1] did NOT change down-B.
- **PlNs.dat PK Thunder ball + tail** — 🟢 VERIFIED (out of EfNsData scope; hand
  to a PlNs mission). Ball flare → magenta, tail/bolt → green. Confirmed the
  green-poke offsets (tail) + magenta-poke offsets (ball). 0x2D82E poke landed
  on non-color bytes (`F90000`) — WIRE must re-derive that record's colorpos.
- **Model[0] + Model[1] = ⚪ DEAD (NOT the bat/yo-yo on-hit spark)** — RESOLVED
  by the punching-bag pass 2026-07-02 (`ness_batyoyo_bag.py`, captures
  `tests/artifacts/extras-audit/Ness-batyoyo-bag/`). Bat (fsmash CharSpecific
  341) and yo-yo (usmash CharSpecific 342) both landed on a DK bag (confirmed
  DamageN3 / DamageFlyLw / DamageAir3). Poking Model[0] (green c1 / magenta c2)
  and Model[1] (all 9 blocks green/magenta) produced **NO change** to either the
  bat-hit burst OR the yo-yo starburst: the bat on-contact burst stayed
  blue/white + yellow rays (vanilla `vanilla-fsmash-f18.png` == poked
  `efns_model0-fsmash-f18.png`), and the yo-yo starburst stayed green/white +
  blue arcs (unchanged under both pokes at usmash f18). These bright bursts are
  the **common-bank melee-hit spark (EfCoData)**, not Ness EfNsData model
  blocks. Model[0]/[1] are NOT shippable on-hit layers. The faint blue bat
  SPARKLE spray (small particle trail during the swing) also did not recolor →
  also common/article, not these blocks.
- **PK Flash (neutralb)** = vanilla GREEN self-colored explosion; did NOT respond
  to any EfNsData model poke (stayed green, never went magenta) → **NOT an
  EfNsData model block.** It's the PK Flash article's own model / a common
  effect. Out of this file's scope.
- **PK Fire (sideb) cast flash** = yellow-green ring at Ness's hand, IDENTICAL
  across all 3 model pokes → **NOT an EfNsData model block** (article model /
  common). Projectile travels off-screen; its burn pillar is on-hit.

**Net: 1 shippable EfNsData group (PSI Magnet / Model[2]) + PlNs PK Thunder
(separate file). Model[0]/[1] = ⚪ DEAD (bat/yo-yo on-hit sparks are common-bank,
resolved by punching-bag 2026-07-02). PK Flash + PK Fire = not in EfNsData.**

## ITEMS-PASS cross-ref (2026-07-02, see `items.md`)

The PK Fire burn **PILLAR** IS colorable — but in **`PlNs.dat`**, not EfNsData
(ness.md correctly ruled it out of EfNsData). ITEMS-PASS located + bag-verified
three `070707` blocks in PlNs: bottom ring inside @0x11A8C, main fire aura
@0x11B58, bottom ring outside @0x11DF8 (c1@+4/c2@+8). Blue rings (`007FFF` c2)
turned green/magenta on the PK-Fire connect (DK bag dx=10, f24-f32) — dramatic.
The PK Fire cast lens-flare (PlNs 0x10194) stays ⚪ DEAD (article/self-colored,
no response — confirms this file's "PK Fire cast flash = article/common"). Ships
as extra `ness_pk_fire`. Full table: `research/docs-research/effect-maps/items.md` §2/§7.

## Structural findings (read before trusting any row)

**Ness has NO ptcl (particle) bank.** `EfNsData.dat`'s `SBM_EffectTable` at
0x20 has `Particles=0x00000000` — the parser reports `version=0x0,
generators=0`. Every Ness effect color is therefore a **model-region block**
(070707 / 4248 / 98-matrix) in the `EffectTable.Models[]` JOBJ trees, not a
`CF`/PrimCol record. `python skinlab/ptcl_parse.py EfNsData.dat --models`
returns 0 (its model scan starts at `bank_end`, which for a bankless file =
EOF); scanning from the data-section start (0x20) instead finds **86** model
blocks (18 are `070707`, 20 `4248`, 48 `98-matrix`).

**`EfNsData.Models[]` has exactly 3 populated entries** (indices 0/1/2; slots
3+ are zero / read into raw data). Anim roots: Model[0]@0x13548,
Model[1]@0x14BE8, Model[2]@0x17168. The 18 `070707` blocks partition cleanly by
model:
- **Model[0]**: 2 blocks (0x13270, 0x13330)
- **Model[1]**: 9 blocks (0x13D84 … 0x14390)
- **Model[2]**: 7 blocks (0x163B4 … 0x16834)

**Move→effect cross-ref is INCONCLUSIVE from the fighter code.** Ness's special
moves and PK articles (`ftNess/ftNs_Special*.c`, `it/items/itnesspk*.c`,
`itnessbat.c`, `itnessyoyo.c`) contain **no `efSync_Spawn` into a Ness bank**.
The only fighter spawns are:
- `ftNs_SpecialHi` (PK Thunder): `efSync_Spawn(1262)`, `1263`, `1030` — all
  bank-1 = **common `EfCoData`** (`gfx_id/1000`), NOT `EfNsData`. See quarantine.

So the PK-Fire/PK-Flash/PSI-magnet/bat/yo-yo article visuals are the
**articles' own animated models** (stored in `PlNs.dat`, not `EfNsData`), and
the 3 `EfNsData.Models[]` entries are effect-table geometries whose owning move
could not be pinned statically. LIVE must name Model[0/1/2] by anti-color poke.
This is the Mewtwo-upsmash lesson in advance: the gfx→move map failed, so these
are candidate groups, not named layers.

**15070 "Purple Electric Pack" corroboration is total.** All 3 files diff clean
(same-size, md5 differs — usable per lesson 4). The mod recolored **all 18**
`EfNsData` `070707` c2 (blue-glow) bytes to purple `AE00FF`, and separately
recolored PK Thunder in `PlNs.dat` (below). This proves the 18 blocks are the
electric/PSI-tinted Ness effects — exactly our targets — but does not by itself
say *which* is PK Flash vs PSI magnet vs bat spark.

md5 (vanilla / 15070): `EfNsData` bbe8b358… / 7e155b2c… ; `PlNs`
(same-size, clean 21-byte diff).

---

## `EfNsData.dat` — model-region candidates (symbol `effNessDataTable`)

`070707` layout: marker `07 07 07 04` → color1 RGB @marker+4 (bright core),
color2 RGB @marker+8 (glow — this is the byte 15070 recolored on every block).
Parser tag = (Model index, "070707", ordinal within model).

### Candidate group `ns_efmodel_0` — Model[0], 2 blocks — ⚪ DEAD (punching-bag 2026-07-02: not the bat/yo-yo on-hit spark)

| layer_id | format | offsets (marker → c1 → c2) | vanilla c1 / c2 | parser tag | hypothesized semantic | 15070 |
|---|---|---|---|---|---|---|
| m0_a | 070707 | 0x13270 → **0x13274** / **0x13278** | FFFFFF / 007FFF | (Model0,070707,#0) | electric glow (unnamed) | c2→AE00FF ✓ |
| m0_b | 070707 | 0x13330 → **0x13334** / **0x13338** | FFFFFF / 007FFF | (Model0,070707,#1) | electric glow (unnamed) | c2→AE00FF ✓ |

### Candidate group `ns_efmodel_1` — Model[1], 9 blocks — ⚪ DEAD (punching-bag 2026-07-02: not the bat/yo-yo on-hit spark)

> LIVE (solo): did NOT respond to neutralb/sideb/downb/upb. PUNCHING-BAG
> 2026-07-02: with a DK bag taking the bat + yo-yo hits (confirmed Damage*
> states), poking all 9 Model[1] blocks green/magenta produced NO change to the
> bat-hit burst or the yo-yo starburst — both are common-bank hit sparks
> (EfCoData). ⚪ DEAD as a Ness on-hit layer. The earlier "faint pink yo-yo-disc
> edge" was a rendering artifact, not a response.

| layer_id | format | offsets (marker → c1 → c2) | vanilla c1 / c2 | parser tag | 15070 |
|---|---|---|---|---|---|
| m1_a | 070707 | 0x13D84 → 0x13D88 / **0x13D8C** | FFFFFF / 007FFF | (Model1,070707,#0) | c2→AE00FF ✓ |
| m1_b | 070707 | 0x13E44 → 0x13E48 / **0x13E4C** | FFFFFF / 007FFF | (Model1,070707,#1) | c2→AE00FF ✓ |
| m1_c | 070707 | 0x13F04 → 0x13F08 / **0x13F0C** | FFFFFF / 007FFF | (Model1,070707,#2) | c2→AE00FF ✓ |
| m1_d | 070707 | 0x13FC4 → 0x13FC8 / **0x13FCC** | FFFFFF / 007FFF | (Model1,070707,#3) | c2→AE00FF ✓ |
| m1_e | 070707 | 0x14084 → 0x14088 / **0x1408C** | FFFFFF / 007FFF | (Model1,070707,#4) | c2→AE00FF ✓ |
| m1_f | 070707 | 0x14144 → 0x14148 / **0x1414C** | FFFFFF / 007FFF | (Model1,070707,#5) | c2→AE00FF ✓ |
| m1_g | 070707 | 0x14210 → **0x14214** / **0x14218** | 19FFFF / 0000FF | (Model1,070707,#6) | c1+c2→…AE ✓ |
| m1_h | 070707 | 0x142D0 → 0x142D4 / **0x142D8** | FFFFFF / 00B2FF | (Model1,070707,#7) | c2→AE00FF ✓ |
| m1_i | 070707 | 0x14390 → 0x14394 / **0x14398** | FFFFFF / 004CFF | (Model1,070707,#8) | c2→AE00FF ✓ |

### Candidate group `ns_efmodel_2` — Model[2], 7 blocks — 🟢 VERIFIED = PSI Magnet (down-B) absorb aura

> LIVE: poking these turned the entire down-B PSI-magnet electric aura into a
> green-core + magenta-arc effect (unmistakable). This is the shippable Ness
> EfNsData group. c1 = bright core, c2 = the electric-blue arc glow (what 15070
> recolored). Per-record vanilla bytes byte-verified below (they DIFFER across
> records — do NOT group under one vanilla, lesson 12).

| layer_id | format | offsets (marker → c1 → c2) | vanilla c1 / c2 | parser tag | 15070 |
|---|---|---|---|---|---|
| m2_a | 070707 | 0x163B4 → **0x163B8** / **0x163BC** | 00CCFF / 0000FF | (Model2,070707,#0) | c1+c2 ✓ |
| m2_b | 070707 | 0x16474 → 0x16478 / **0x1647C** | FFFFFF / 0000FF | (Model2,070707,#1) | c2→…AE ✓ |
| m2_c | 070707 | 0x16534 → 0x16538 / **0x1653C** | FFFFFF / 007FFF | (Model2,070707,#2) | c2→AE00FF ✓ |
| m2_d | 070707 | 0x165F4 → 0x165F8 / **0x165FC** | FFFFFF / 007FFF | (Model2,070707,#3) | c2→AE00FF ✓ |
| m2_e | 070707 | 0x166B4 → 0x166B8 / **0x166BC** | FFFFFF / 0066FF | (Model2,070707,#4) | c2→AE00FF ✓ |
| m2_f | 070707 | 0x16774 → 0x16778 / **0x1677C** | FFFFFF / 007FFF | (Model2,070707,#5) | c2→AE00FF ✓ |
| m2_g | 070707 | 0x16834 → 0x16838 / **0x1683C** | FFFFFF / 007FFF | (Model2,070707,#6) | c2→AE00FF ✓ |

> `4248` (20) and `98-matrix` (48) blocks also exist in these models — those are
> material/vertex color for the same geometry. Not primary candidates; poke the
> `070707` c2 first (that is what 15070 chose). If a group changes color on
> LIVE, its adjacent 4248/98 blocks are follow-up layers.

---

## PK Thunder ball + tail — lives in `PlNs.dat`, not EfNsData (reference doc)

The mission lists PK Thunder ball+tail as a Ness target. Static analysis
confirms these are **`PlNs.dat`** article-model colors (the thunder ball/trail
articles carry their own geometry; no EfNsData involvement). These are ALREADY
in `Effect-Offsets-Reference.md` under Ness→PlNs, and 15070's `PlNs.dat` diff
corroborates them exactly:

| offset (doc) | doc semantic | 15070 PlNs diff | note |
|---|---|---|---|
| 0x24030 (c2 @0x2403C) | PK Thunder tip | 0x2403C 004CFF→AE00FF ✓ | |
| 0x2C3F7 (@0x2C3FC) | PK Thunder tail | 0x2C3FC 004C→AE00 ✓ | |
| 0x2C777 (@0x2C77C) | PK Thunder tail | 0x2C77C 004C→AE00 ✓ | |
| 0x2CAF4 (@0x2CAFC) | PK Thunder tail main | 0x2CAFC 004C→AE00 ✓ | |
| 0x2D3C8 (@0x2D3D0) | PK Thunder aura | 0x2D3D0 00→AE ✓ | |
| 0x2D528 (@0x2D530) | PK Thunder aura+ball | 0x2D530 00→AE ✓ | |
| 0x2D5E8 (@0x2D5F0) | PK Thunder lightning | 0x2D5F0 0033→AE00 ✓ | |
| 0x2D6A8 (@0x2D6B0) | PK Thunder lightning | 0x2D6B0 0033→AE00 ✓ | |
| 0x2D768 (@0x2D770) | PK Thunder lightning | 0x2D770 0033→AE00 ✓ | |
| 0x2D828 (@0x2D82E) | PK Thunder lightning | 0x2D82E …0066→…AE00 ✓ | |

These are OUT OF THIS SPEC'S FILE SCOPE (EfNsData) but recorded here because the
mission named them. If PK Thunder ball/tail is to be wired, it targets
`PlNs.dat` at the above offsets — hand off to a PlNs mission. (Probe spec below
still includes a `plns` alias + PK-Thunder pokes so LIVE can confirm in one
boot.)

---

## AUDIT_HINTS (for LIVE / WIRE)

- Ness ckind resolves via `resolve_ckind("ness")`. Anti-colors: effects are
  electric-blue (007FFF / 0000FF), so poke **green `00FF00`** and **magenta
  `FF00FF`** (far from blue — lesson 6).
- Moves + suggested frame windows (LIVE tightens per gamestate, lesson 10):
  - `neutralb` (PK Flash — charge then release): frames [20, 40, 60, 90] with
    a B-hold input to charge; explosion late.
  - `sideb` (PK Fire): frames [8, 16, 26, 40].
  - `downb` (PSI Magnet): frames [6, 14, 24, 40] (hold).
  - `upb` (PK Thunder — ball travels, tail): frames [10, 20, 34, 50] + steer.
  - `fsmash` (bat swing sparkle): frames [8, 14, 20, 28].
  - `dsmash`/`jab`… (yo-yo): yo-yo is up/down-smash — frames [10, 20, 34].
- Because Model[0/1/2] are not statically named, run one experiment PER model
  group across ALL special moves; whichever move lights up green/magenta names
  the model. Flag ambiguous captures for EYEBALL rather than guessing.

## Shippable-now summary (for WIRE)

Only ONE Ness EfNsData group is live-verified and shippable: **PSI Magnet**
(down-B, Model[2]). PK Thunder is verified but lives in `PlNs.dat` (separate
file/mission). Bat/yo-yo (Model[0]/[1]) are on-hit-pending — DO NOT ship yet.

### Extra `ness_psi_magnet` — target `EfNsData.dat` — 🟢 VERIFIED

Format `070707`: marker+4 = c1 (bright core), marker+8 = c2 (arc glow). 7 blocks
in Model[2]. **Per-record vanilla byte-verified 2026-07-02 (they DIFFER — split
per record, lesson 12):**

| layer_id | c1 off | c1 vanilla | c2 off | c2 vanilla | note |
|---|---|---|---|---|---|
| psimag_a | 0x163B8 | `00CCFF` | 0x163BC | `0000FF` | c1 non-white here |
| psimag_b | 0x16478 | `FFFFFF` | 0x1647C | `0000FF` | |
| psimag_c | 0x16538 | `FFFFFF` | 0x1653C | `007FFF` | |
| psimag_d | 0x165F8 | `FFFFFF` | 0x165FC | `007FFF` | |
| psimag_e | 0x166B8 | `FFFFFF` | 0x166BC | `0066FF` | |
| psimag_f | 0x16778 | `FFFFFF` | 0x1677C | `007FFF` | |
| psimag_g | 0x16838 | `FFFFFF` | 0x1683C | `007FFF` | |

Grouping suggestion: one extra, two controls — **c1 (core, mostly white)** and
**c2 (arc glow, electric-blue)** — each writing all 7 records of its column.
15070's visible change was recoloring the c2 set, so c2 is the primary control;
expose c1 too (psimag_a's c1 is `00CCFF` not white). Because vanillas differ,
WIRE keys each record separately (no shared vanilla).

`AUDIT_HINTS`: `ness downb frames [6,14,24,40]` (hold down-B to sustain the
absorb aura). Anti-colors are per-operand (lesson 11): c1 core is white/cyan →
poke green or magenta; c2 glow is blue → poke green or magenta. Both far from
blue/white, verified good.

### PK Thunder (verified, but `PlNs.dat` — hand to a PlNs mission)

Ball flare = magenta-poke offsets, tail/bolt = green-poke offsets (LIVE
confirmed). Working offsets from `ness_probe.json` `plns_pkthunder`: tail/aura
`0x2403C 0x2C3FC 0x2C77C 0x2CAFC` (all vanilla `004CFF`), ball flare `0x2D3D0
0x2D530` (both vanilla `0000FF`), lightning `0x2D5F0 0x2D6B0 0x2D770` (all
vanilla `0033FF`). **CAUTION:** the `0x2D82E` poke landed on `F90000` (not the
lightning color) — that record's colorpos is offset differently; WIRE must
re-derive it from the marker, don't ship 0x2D82E as-is.

## EfCoData quarantine (NEVER a Ness layer)

15070 also recolors `EfCoData.dat` (cast-shared common electric/fire effects).
Ness's PK Thunder fighter code spawns common effects `efSync_Spawn(1030/1262/
1263)` (bank 1 = EfCoData), so some PK-Thunder spark/hit flashes DRAW from
EfCoData — these are **common-effects, out of char scope** and must not be
proposed as Ness offsets. See quarantine section in `pikachu.md` for the shared
EfCoData diff cluster list (one list serves both characters).

## Open leads (post-LIVE)

1. **RESOLVED:** Model[2] = PSI Magnet (verified). Model[0]/[1] = ⚪ DEAD (the
   bat/yo-yo on-hit sparks are common-bank EfCoData, not these blocks — settled
   by the punching-bag pass 2026-07-02). PK Flash + PK Fire cast flash are
   NOT EfNsData model blocks (self-colored / common).
2. **PUNCHING-BAG REFERRAL — DONE (⚪ DEAD).** Ran `ness_batyoyo_bag.py` (bat
   fsmash CharSpecific 341 + yo-yo usmash CharSpecific 342, step-until
   CHAR_SPECIFIC_BASE + DK bag parked dx=8). Both moves landed clean Damage*
   hits; Model[0] and Model[1] pokes did nothing to either burst. Captures:
   `tests/artifacts/extras-audit/Ness-batyoyo-bag/`. Nothing shippable from
   these blocks — they are not the bat sparkle or the yo-yo spark.
3. The `4248`/`98-matrix` blocks inside Model[2] are follow-up material/vertex
   sub-layers for PSI Magnet once the core c1/c2 group ships.
