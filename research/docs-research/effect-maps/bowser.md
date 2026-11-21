# Bowser effect map (LIVE-JUDGED 2026-07-02)

Mission: extras campaign, Bowser (`EfKpData.dat`). LIVE pass complete —
`backend/probes/bowser_probe.json` run + judged. Captures:
`tests/artifacts/datram-probe-bowser/`. Char key = `bowser`.

## LIVE VERDICTS (headline)

- 🟢 **fire_breath (scripts 5-8 CF puff ptcl)** — SHIPPABLE. Magenta poke turns
  the WHOLE near-field flame body vivid pink (NOT subtle; the STATIC "expect
  subtle / all texture" fear was wrong). The CF puff records ARE the dominant
  flame color; texture provides only detail/highlights. See f40/f60 captures.
- 🔴 **firebreath_model_orange (070707 @0x170D8)** — DEAD. Flame stayed fully
  orange with all 3 orange-model offsets poked magenta (0 magenta px). The
  single orange block does NOT tint the flame.
- 🔴/🟡 **fortress (up-B, both `fortress_ptcl` s0-2 AND `fortress_model_blue`
  0x14D54+)** — DEAD on the GROUNDED spin. The visible grounded Whirling
  Fortress is GOLD radial sparks + white smoke ring — no blue anywhere in
  vanilla. Neither poke changed it. The blue model trail is the AERIAL fortress
  (flight variant), which the standing up-B never triggers → HARNESS-BLOCKED,
  not proven-dead, but nothing ships from the grounded probe.
- 🔴 **fortress AERIAL RE-PROBE (2026-07-02, `airupb` harness recipe)** — the new
  `airupb` move in `ingame/moves.py` (jump to apex → up-B in the air) now triggers
  the aerial/flight fortress. Boot: bowser solo, `bowser_fortress_air_probe.json`
  (iso=Ness-vanilla). Bowser DOES render airborne in the shell spin with a trailing
  effect — but the aerial trail is a **WHITE/pale spin ring + gray smoke puffs**,
  NOT blue. The STATIC draft's "blue spinning wind trail" was WRONG. Poking
  `fortress_model_blue` (0x14D58–0x16220) magenta = NO magenta anywhere (white ring
  unchanged f16/f26/f55); poking `fortress_ptcl` (s0-2, 0xF2–0x283) green = smoke
  puffs stay gray (no green). BOTH DEAD for the aerial fortress too. The visible
  aerial trail is texture/other-model, not these offsets. **Not shippable as a
  colour extra.** Captures: `tests/artifacts/datram-probe-bowser-fortress-air/`
  (`fortress_model_blue-airupb-*` / `fortress_ptcl-airupb-*` vs `vanilla-airupb-*`).

STATIC structural notes below are retained for reference.

---

Original STATIC draft (offsets parser-/marker-verified against vanilla
`storage/test-base/files/EfKpData.dat`). Probe spec: `backend/probes/bowser_probe.json`.
Char key = `bowser` (`ingame/char_select.py`).

## Structural findings (read before trusting any row)

`EfKpData.dat` (symbol `effKoopaDataTable`) is a normal ptcl bank:
`ParticleGroup@0x80`, `version=0x42`, `EffectIDStart=12000`, **9 generators
(scripts 0-8)**, tex bank @0x640. `python skinlab/ptcl_parse.py
EfKpData.dat --models` = **64 ptcl color operands + 59 model-region blocks**
(14 `070707`, 13 `4248`, 32 `98-matrix`).

**Move → script cross-ref (from `efSync_Spawn` in decomp
`melee/src/melee/ft/chara/ftKoopa/` + the `efsync.c` switch, which remaps the
fighter's small gfx_id to a real effect id):**

| fighter call | gfx_id | efsync case → real id | id−12000 = script |
|---|---|---|---|
| `ftKp_SpecialHi` (Whirling Fortress, up-B) | 0x4DA | → 0x2EE1 **and** 0x2EE2 | **scripts 1 + 2** |
| `ftKp_SpecialN` fire breath (neutral-B), via `itKoopaFlame_Spawn` gfx 0..3 → `efSync_Spawn(1243+gfx)` = 0x4DB..0x4DE | → 0x2EE5..0x2EE8 | **scripts 5,6,7,8** |
| `ftKp_SpecialLw` (Bowser Bomb landing, down-B) | 0x4D8 → 0x61 (97) ; 0x4DF → 0x143 (323) | **< 0x250 → common `EfCoData` bank** | — (quarantined) |

So the bank splits into two near-duplicate clusters:
- **scripts 0-4 = Whirling Fortress cluster** (up-B). Scripts 1+2 are the
  live-spawned pair; scripts 0/3/4 are unreferenced by ftKoopa's own up-B
  calls (0/4 may be landing/Giga variants, script 3 has **no color operands**).
- **scripts 5-8 = Fire Breath cluster** (neutral-B). script 5≈0, 6≈1, 7≈2,
  8≈4 (byte-near-identical pairs) — Nintendo cloned the fortress scripts for
  the flame.

**Fire breath's dominant color is TEXTURE, not these color bytes** — see mod
corroboration below. The ptcl CF records here tint the flame *puffs*/secondary
particles; the flame body itself is a textured cone in the effect Models[]
(the orange `070707` at 0x170D4 = `FFFF00`/`FF4C00`, only orange block in the
whole file — strong flame-tint candidate, but a hue-shift texture extra à la
Falcon `punch_texture` would be the real fix and is out of STATIC scope).

**Koopa Klaw (side-B, `ftKp_SpecialS`) draws NO effect spawn** — it is an
on-hit grab move (like Falcon raptor on-whiff). No solo GFX; not mappable
without the punching-bag harness. Not wired.

## CF-record layout (ptcl bank)

Parser reports the **color offset** (marker+2 = the RGB right after the
`CF`/`DF` opcode+count). Layout: `RRGGBB AA AD DF flag rrggbb` → primary RGB at
the parse offset, secondary RGB at **parse-offset+7** (lesson 3, dominates
sustained puff tint). Both should be poked per record. Byte-verified in file
(e.g. 0x3E2 = `FF FF FF FF AD DF 00 FF E8 51`, 0x573 = `FF EF 40 1E AD DF 0C
FF 0A 0E`).

`070707` (model): marker `07 07 07 04` → color1 RGB @+4, color2 RGB @+8.
`4248` (model HSD material): color block @marker−0x10; ambient RGBA @+0,
diffuse RGBA @+4 (diffuse dominates, Fox/Mario precedent).

---

## `EfKpData.dat` — Fire Breath (neutral-B) candidates

### Candidate group `firebreath_ptcl` — scripts 5-8 CF puff records

Parser tag = (script, PRIMCOL/ENVCOL opcode, ordinal). All LIVE pending; poke
each primary + its +7 secondary. Anti-color magenta (vanilla = orange).

| layer_id | fmt | offset (color) | +7 sec | vanilla RGB / sec | hypothesis |
|---|---|---|---|---|---|
| fb_s5_a  | CF | 0x3E2 | 0x3E9 | FFFFFF / FFE851 | flame core puff (s5, near-dup of s0) |
| fb_s5_b  | CF | 0x40F | — | FFD9B8 | flame ember puff (s5) |
| fb_s6_a  | CF | 0x490 | 0x497 | FFFFFF / C06401 | flame smoke (s6, dup of s1) |
| fb_s6_b  | CF | 0x49D | 0x4A4 | FF804A / 942514 | orange flame puff (s6) |
| fb_s6_c  | CF | 0x4BB | — | FFA973 | flame wisp (s6) |
| fb_s7_a  | CF | 0x566 | 0x56D | FFC607 / FF0206 | **orange flame** (s7, dup of s2) |
| fb_s7_b  | CF | 0x573 | 0x57A | FFEF40 / FF0A0E | **bright orange flame** (s7) |
| fb_s7_c  | CF | 0x587 | — | FFFFFF | flame tip (s7) |
| fb_s8_a  | CF | 0x5EE | 0x5F5 | FFFFFF / FFE851 | flame burst (s8, dup of s4) |
| fb_s8_b  | CF | 0x609 | — | FFFFFF | flame (s8) |
| fb_s8_c  | CF | 0x628 | — | FFD9B8 | ember (s8) |

### Candidate `firebreath_model_orange` — the flame model tint (070707)

| layer_id | fmt | offset | vanilla | hypothesis |
|---|---|---|---|---|
| fb_model_c1 | 070707 | 0x170D8 | FFFF00 | flame model bright core (only orange block in file) |
| fb_model_c2 | 070707 | 0x170DC | FF4C00 | flame model glow |
| fb_model_diff | 4248 | 0x17148 | (diffuse) | flame model material @marker 0x17154−0x10+4 |

AUDIT_HINTS (fire breath): move=neutralb, hold B (charge/sustain flame) frames
~12-90; forced anti-color magenta (vanilla orange/white). Probe holds B at
frames 1/20/45 then releases at 70.

---

## `EfKpData.dat` — Whirling Fortress (up-B) candidates

### Candidate group `fortress_ptcl` — scripts 0-2 CF records

| layer_id | fmt | offset | +7 sec | vanilla / sec | hypothesis |
|---|---|---|---|---|---|
| wf_s0_a | CF | 0xF2  | 0xF9  | FFFFFF / FFE851 | spin puff core (s0) |
| wf_s0_b | CF | 0x10B | —     | FFFFFF | spin puff (s0) |
| wf_s0_c | CF | 0x11F | —     | FFD9B8 | spin ember (s0) |
| wf_s1_a | CF | 0x1A0 | 0x1A7 | FFFFFF / C06401 | spin smoke (s1) |
| wf_s1_b | CF | 0x1AD | —     | FF804A | spin orange puff (s1) |
| wf_s1_c | CF | 0x1CB | —     | FFA973 | spin wisp (s1) |
| wf_s2_a | CF | 0x276 | 0x27D | FFC607 / FF0206 | spin orange (s2) |
| wf_s2_b | CF | 0x283 | —     | FFEF40 | spin bright orange (s2) |

### Candidate group `fortress_model_blue` — the spin-trail models (070707/4248)

The 0x14D54-0x1629C region is a dense series of **blue** `FFFFFF/007FFF`,
`B2E5FF/0000FF`, `FFFFFF/004CFF` 070707 blocks + `808080FF…` 4248 materials —
Whirling Fortress's white/blue spinning wind trails.

| layer_id | fmt | offset | vanilla | hypothesis |
|---|---|---|---|---|
| wf_m1_c1 | 070707 | 0x14D58 | FFFFFF | spin trail core |
| wf_m1_c2 | 070707 | 0x14D5C | 007FFF | spin trail blue glow |
| wf_m2_c1 | 070707 | 0x14E24 | B2E5FF | trail light-blue core |
| wf_m2_c2 | 070707 | 0x14E28 | 0000FF | trail deep-blue glow |
| wf_m3_c1 | 070707 | 0x14EE4 | FFFFFF | trail core |
| wf_m4_c1 | 070707 | 0x15E54 | FFFFFF | trail core |
| wf_m4_c2 | 070707 | 0x15E58 | 004CFF | trail blue glow |
| wf_m5_c1 | 070707 | 0x15F14 | FFFFFF | trail core |
| wf_m6_c1 | 070707 | 0x15FE0 | CCE5FF | trail pale-blue |
| wf_m7_c2 | 070707 | 0x160A0 | 66B2FF | trail mid-blue |
| wf_m8_c2 | 070707 | 0x16160 | 0099FF | trail blue |
| wf_m9_c2 | 070707 | 0x16220 | 007FFF | trail blue |

(Additional 4248 blue diffuse blocks at 0x14DD4/0x14EA0/0x14F60/0x15020/
0x15ED0/0x15F90/0x1605C/0x1611C/0x161DC/0x1629C are open leads — poke if the
070707 pass under-covers.)

AUDIT_HINTS (fortress): move=upb frames ~8-60; forced anti-color magenta
(vanilla blue for models, orange/white for ptcl).

---

## Quarantine (NOT Bowser layers — do not ship)

- **Bowser Bomb (down-B) landing shockwave**: `efSync_Spawn(0x4D8→0x61=97)`
  and `(0x4DF→0x143=323)` both resolve to the **common `EfCoData`** bank
  (`gfx_id < 0x250`). Route to any EfCoData mapping mission.
- **Koopa Klaw (side-B)**: no effect spawn (on-hit grab). Pending punching-bag
  harness; not wired.
- **32 `98-matrix` blocks** (0x150A0, 0x16300-0x167FF cluster, 0x171C0-0x17957
  cluster): texanim/matrix tables, not RGB triples. Never ship as color layers.
- Scripts 0/3/4 of the fortress cluster: not spawned by ftKoopa's own up-B
  (0x4DA only spawns scripts 1+2). Likely landing/Giga; script 3 has no colors.
  LIVE may confirm via up-B poke whether scripts 0/4 contribute.

## Mod corroboration

- **Post 14698 "Blue Fire Bowser"** (`EfKpData.dat`, `ssbm-backup/uploads/
  posts/2021/02/post_14698/`) — same size (96650), md5
  `ab291c8e4cbe211113237a2f5d68349f`. **Diff is 41276 bytes but ALL in the
  texture-graphics region (0x6C0+); the ptcl bank (0x60-0x640) and the model
  color region (0x14000-0x17800) are BYTE-IDENTICAL to vanilla.** The mod
  recolors fire breath by swapping the flame **texture**, not any color byte.
  → Confirms the fire-breath dominant appearance is texture-driven (Falcon
  punch-fire precedent); the color offsets above only tint particles/model.
  Negative corroboration for the color rows, but a strong structural lesson.

## Open leads / follow-ups (post-LIVE)

1. ~~Fire breath ptcl vs texture~~ RESOLVED: ptcl CF puffs win, ship them.
2. ~~orange model 0x170D8~~ RESOLVED: dead.
3. **Aerial Whirling Fortress**: the blue model trail 0x14D54+ is likely the
   FLIGHT-phase (aerial up-B) trail, never triggered by the grounded probe.
   🔧 **HARNESS-BLOCKED (confirmed 2026-07-02).** An airborne up-B is NOT
   expressible in the current harness: `ingame/moves.py execute()` for SPECIALS
   does a GROUNDED special only (it never jumps first); the `_to_air()` helper is
   wired ONLY for AERIALS (A-attacks), and `effect_probe.py` calls
   `runner.execute(move)` with no air variant. So "jump then up-B" cannot be
   driven without a moves.py code change (out of scope for a MAP probe — no
   harness edits). To un-block, a future harness fix must teach `execute()` a
   `--air`/rise option for SPECIALS (jump via `_to_air`, then send B+up), or add
   a dedicated aerial-special recipe. Until then the blue flight-trail models
   stay UNVERIFIED — do NOT ship them on the guess.
4. Fortress scripts 0/4: still unconfirmed (grounded spin shows gold/white, not
   these). Aerial re-probe needed.

---

## Shippable-now summary (for WIRE)

### 🟢 `bowser_fire_breath` — fire breath flame tint (STRONG live positive)

Target file: `EfKpData.dat`. Move: **neutralb**, HOLD B to sustain the flame.
Frame WINDOW: flame visible ~f24-f90; best judged f40-f60 (full stream).
AUDIT_HINTS: `move=neutralb`, inputs hold B (spec used PRESS B @1/20/45, RELEASE
@70), forced anti-color **magenta** (vanilla orange/white). Bag: not needed
(flame is solo-visible, no contact required).

Format = **CF** (ptcl PrimCol/EnvCol operand; RGB at the parser color offset;
some records have a secondary at +7 per lesson 3). Fan-out grouping: this is a
single multi-record flame layer. Recommend one editor entry `_c1`/`_c2`-style
that recolors the primary set (the whole flame goes one hue); the +7 secondaries
are the puff-fringe tint — expose as an optional 2nd swatch if fine control is
wanted, else fold into the primary.

Per-record vanilla bytes (byte-verified in vanilla, 3-byte RGB at offset):

| record | script | offset | vanilla RGB | role |
|---|---|---|---|---|
| fb_s5_a  | 5 | 0x3E2 | FFFFFF | flame core puff (primary) |
| fb_s5_a2 | 5 | 0x3E9 | FFE851 | └ +7 secondary (warm fringe) |
| fb_s5_x  | 5 | 0x3FB | FFFFFF | flame puff |
| fb_s5_b  | 5 | 0x40F | FFD9B8 | flame ember puff |
| fb_s6_a  | 6 | 0x490 | FFFFFF | flame smoke (primary) |
| fb_s6_a2 | 6 | 0x497 | C06401 | └ +7 secondary (deep orange) |
| fb_s6_b  | 6 | 0x49D | FF804A | orange flame puff |
| fb_s6_b2 | 6 | 0x4A4 | 942514 | └ +7 secondary (dark red) |
| fb_s6_c  | 6 | 0x4BB | FFA973 | flame wisp |
| fb_s7_a  | 7 | 0x566 | FFC607 | orange flame (primary) |
| fb_s7_a2 | 7 | 0x56D | FF0206 | └ +7 secondary (red) |
| fb_s7_b  | 7 | 0x573 | FFEF40 | bright orange flame |
| fb_s7_b2 | 7 | 0x57A | FF0A0E | └ +7 secondary (red) |
| fb_s7_c  | 7 | 0x587 | FFFFFF | flame tip |
| fb_s8_a  | 8 | 0x5EE | FFFFFF | flame burst |
| fb_s8_b  | 8 | 0x609 | FFFFFF | flame |
| fb_s8_c  | 8 | 0x628 | FFD9B8 | ember |

WIRE notes: byte-verify each vanilla RGB per record (all confirmed above). The
`FFFFFF` primaries are "white intensity" nodes — recoloring them is what turned
the whole flame magenta, so they MUST be in the shipped set (not just the
already-orange ones). Anti-colors are per-operand but all vanilla hues here are
warm (orange/white), so a single magenta anti-color is safe far-hue for all.

### Texture lead — ✅ SHIPPED 2026-07-03 as `breath_texture`

Fire breath ALSO has a texture path (mod 14698 "Blue Fire Bowser" recolors ONLY
the texture region 0x6C0+, ptcl+model bytes byte-identical to vanilla). The
`EfKpData.dat` tex bank is @0x640; the 14698 diff spans the graphics region
0x6C0+ (41276 diff bytes, all >0x6C0).

**Shipped** as the `breath_texture` extra (`texture_recolor`, upb_charge_fire
precedent): tex bank group 0 = 9x 64x64 CI8 flame frames, images
0x6C0+i*0x1000, palettes 0x96C0+i*0x200 (RGB5A3), vanilla dominant hue 28.2.
Recolor = palette hue-rotate; self-test: 21FF00 apply changed 4395 bytes, ALL
in the palette tail, 0 image-index/out-of-extent bytes; restore byte-identical.

WHY it was needed (user report 2026-07-03): the CF puffs tint the flame, but
the texture's own orange modulates through — most visibly on LANDED ground
flames. `itkoopaflame.c` spawns the scripts 5-8 ptcl effect ONCE per flame item
(`x44_spawned`); the fire burning on the stage afterwards is dominated by the
item's textured quads, which only this texture extra recolors. The MAP/EYEBALL
captures never caught this because the solo probe's flames dissipated mid-air
(f90 capture: no landed fire). Lesson: probe moves on a surface the projectile
can LAND on before calling coverage complete.

### 🔴 Dead — do not ship
- `firebreath_model_orange` (070707 0x170D8/0x170DC + 4248 0x17148): flame
  stayed orange, 0 change. The one orange block is not the flame color.
- `fortress_ptcl_s0s2` + `fortress_model_blue` (0x14D54+): grounded up-B shows
  gold sparks + white smoke, unchanged. Blue models = untriggered aerial trail.
