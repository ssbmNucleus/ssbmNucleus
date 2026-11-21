# Mario & Dr. Mario — effect-color mapping spec (MAP-LIVE complete)

Status: **LIVE-VERIFIED.** MAP-LIVE ran `backend/probes/mario_probe.json` (Mario boot),
`backend/probes/docmario_probe.json` (Doc boot), and `backend/probes/mario_probe_extra.json`
(disambiguation boot) 2026-07-02. Every candidate judged against captures.
Captures:
- Mario: `tests/artifacts/datram-probe-mario/`
- Doc: `tests/artifacts/datram-probe-docmario/`
- Extra (0x567 isolation + 42 diffuse/ambient split): `tests/artifacts/datram-probe-mario-extra/`

**Verdict legend:** 🟢 verified · ⏳ on-hit pending (punching-bag) · ⚪ dead/no-op.

**Headline results:** fireball hand-smoke / trailing-fire / ball-particles /
landing-dust / square-particles all 🟢; fireball AURA material in PlMr (0xFA40/
0xFAB0) 🟢 (recolors the fireball glow — the un-corroborated blocks are real);
cape sparkles 🟢 (subtle, warm-shift); cape 0x567 black-RGB record 🟢 (drives a
real trailing cape sparkle — NOT dead alpha); Mario cape material 0x14EAC 🟢
(green cloth); **Doc cape material PlDr 0x19CAC 🟢 (green cloth — the ref-mod
candidate confirmed)**; tornado 07 (6 blocks) 🟢 (full red swirl); tornado 42
DIFFUSE(+4) 🟢 (ground ripple + spin haze), AMBIENT(+0) ⚪ no-op; up-B coin-punch
⚪ DEAD (punching-bag 2026-07-02: coin ring is common-bank EfCoData, not the
s11/s12/s13 records — do NOT ship). All Doc shared-EfMrData rows
fire identically to Mario.

## ITEMS-PASS cross-ref (2026-07-02, see `items.md`)

The up-B **"coin" ring is a TEXTURE-ONLY common effect** (the SMB gold-coin
sprite, a subaction event-GFX resolving into EfCoData, no C-level `efSync_Spawn`
in `ftMr_SpecialHi.c`) — which is exactly *why* the EfMrData `upb_coin` CF
records (s11/s12/s13) were ⚪ DEAD under the bag: the color isn't in any ptcl/
model operand, it's a texture. To recolor the coin, use the **EfCoData texture
pass** (decode TEXGraphicBank, hue-shift the coin texGroup), not the color
editor. No change to this file's ⚪ verdicts. Details:
`research/docs-research/effect-maps/items.md` §4. (`itcoin.c`/`It_Kind_Coin`/`ItCo.dat`
is the unrelated money-coin ITEM, NOT the up-B coin visual.)

## File topology (verified)

- Mario particle effects (fireball, cape sparkles, coin-punch up-B) live in the
  **shared** `EfMrData.dat` (`effMarioDataTable`, `efAsync_DatEntries[1]`,
  `EffectIDStart = 1000`). Parser: 14 generators, 48 ptcl color operands, 28
  model-region blocks.
- **There is no `EfDrData.dat`.** The effect table has no Doc entry and no
  EfDr* file exists in `storage/test-base/files`. **Doc reuses Mario's moveset
  and shares `EfMrData.dat` outright** (decomp: `ftDrMario/` has only Init +
  AppealS; the whole `ftMr_Special*` moveset is Mario's, keyed on
  `fp->kind == FTKIND_MARIO` for fireball vs `itDrMarioPill_Spawn` for Doc's
  pill). So every EfMrData row below applies to **both** characters, EXCEPT the
  fireball ptcls, which Doc does not spawn (Doc's neutral-B is the vitamin pill
  item — no `efSync_Spawn(1146)`). Doc's coin-punch up-B and cape sparkles DO
  fire from EfMrData.
- Player-file (per-costume) material colors: Mario fireball aura + cape in
  `PlMr.dat`; **Doc cape in `PlDr.dat`** (his own file, different offset).
- Move → script (decomp `efSync_Spawn`): fireball `gfx_id 1146` → EfMrData
  script index 146; tornado/down-B `gfx_id 0x47C = 1148` → script index 148.
  (These index the sparse `psCmdListArray`; the parser's 0-based generator
  ordinals 1-13 are the on-disk generators, not the gfx_id indices — but the CF
  offsets below are all exact marker-verified file offsets regardless.)

---

## EfMrData.dat — ptcl CF records (`CF_##` / PrimCol 0xCF)

Layout per record: `CF <count> RR GG BB AA` then `AD DF <count> rr gg bb aa`
(EnvCol secondary). **color1** = PrimCol RGB at marker+2 (particle/texture
tint); **color2 (_c2)** = EnvCol RGB at marker+9 (env/sustained tint,
dominates the lingering puff — lesson 3). All markers verified against raw
bytes; old reference cites point at the `CF` opcode byte and are correct
**except two off-by cites flagged below**.

### Fireball (neutral-B, Mario only — script tags from parser ordinals 1,2,4,5,6,7)

Poked cyan/green/magenta (per anti-color rules). Verdicts from
`datram-probe-mario/fb_*-neutralb-f{16,24,46}.png`.

| marker | color1 off | color1 | color2(env) off | color2 | (script,op) | verified semantic | verdict |
|--------|-----------|--------|-----------------|--------|-------------|-------------------|---------|
| 0x160 | 0x162 | FFFFFF | 0x169 | FFCC4A | (s1,CF#1) | hand/muzzle smoke burst at spawn | 🟢 fb_hand_smoke |
| 0x175 | 0x177 | FFA217 | 0x17E | BA120D | (s1,CF#2) | hand/muzzle smoke burst | 🟢 fb_hand_smoke |
| 0x182 | 0x184 | 9C060B | 0x18B | 540405 | (s1,CF#3) | hand/muzzle smoke (interp cnt=7) | 🟢 fb_hand_smoke |
| 0x20A | 0x20C | C7BB0D | 0x213 | D43B08 | (s2,CF) | trailing fire plume behind fireball | 🟢 fb_trailing_fire |
| 0x21D | 0x21F | FFA800 | 0x226 | FF5900 | (s2,CF) | trailing fire plume | 🟢 fb_trailing_fire |
| 0x22A | 0x22C | FF070F | 0x233 | 510A00 | (s2,CF) | trailing fire plume (cnt=8) | 🟢 fb_trailing_fire |
| 0x2E3 | 0x2E5 | FDEB74 | 0x2EC | E33C09 | (s4,CF) | scattered ball particles / end-burst sparks | 🟢 fb_ball_particles |
| 0x2F0 | 0x2F2 | B90303 | 0x2F9 | 610101 | (s4,CF) | ball particles (cnt=12) | 🟢 fb_ball_particles |
| 0x353 | 0x355 | FDE467 | 0x35C | D42304 | (s5,CF) | ball particles | 🟢 fb_ball_particles |
| 0x360 | 0x362 | 7D4202 | 0x369 | 2E0000 | (s5,CF) | particles around fireball (cnt=12) | 🟢 fb_ball_particles |
| **0x3C8** | 0x3CA | FEFCE2 | 0x3D1 | FFF75C | (s6,CF) | fireball landing/expiry dust — **old cite 0x3C9 off by 1** | 🟢 fb_landing_dust |
| 0x3DB | 0x3DD | FCE669 | 0x3E4 | D60B0E | (s6,CF) | landing dust | 🟢 fb_landing_dust |
| 0x3E8 | 0x3EA | F9AC06 | 0x3F1 | 6B0507 | (s6,CF) | landing dust (cnt=7) | 🟢 fb_landing_dust |
| 0x474 | 0x476 | FF290C | 0x47D | FFFF82 | (s7,CF) | square particles at fireball endpoint | 🟢 fb_square_particles |
| 0x484 | 0x486 | FFFF6E | 0x48D | FF0C14 | (s7,CF) | square particles | 🟢 fb_square_particles |

### Cape (side-B — script tags 8,9; Mario + Doc)

Poked FF0000 (all 5) in the combined `cape_sparkles` group; 0x567 isolated with
00FF00 in `mario_probe_extra`. Verdicts from `cape_sparkles-sideb-f{12,20}.png`
+ `datram-probe-mario-extra/cape_567_black_only-sideb-f12.png`. NOTE: vanilla
cape sparkles are inherently multi-hue (blue/cyan/magenta/pink stars), so the
shift is real but SUBTLE — flagged for EYEBALL confirmation.

| marker | color1 off | color1 | color2(env) off | color2 | (script,op) | verified semantic | verdict |
|--------|-----------|--------|-----------------|--------|-------------|-------------------|---------|
| 0x4DE | 0x4E0 | 6BFDFF | 0x4E7 | 1105FF | (s8,CF#1) | cape swing sparkle star | 🟢 cape_sparkles (subtle) |
| **0x4EB** | 0x4ED | D1A3FF | — (no AD DF) | — | (s8,CF#2) | cape swing sparkle — **old cite 0x4EC bogus; real marker 0x4EB (cnt=8)** | 🟢 cape_sparkles (subtle) |
| 0x503 | 0x505 | BF09A1 | — | — | (s8,CF#3) | cape sparkle faint (cnt=4) | 🟢 cape_sparkles (subtle) |
| 0x567 | 0x569 | 000000 | — | — | (s9,CF) | smaller trailing cape sparkle — **NOT dead**: green poke produced a visible cyan/teal sparkle at the cape's bottom edge (isolated `cape_567_black_only`). Black base is alpha-mask, but color IS expressed. Was low-confidence — now confirmed. | 🟢 cape_sparkles |

### Up-B "coin punch" contact (script tags 11,12,13; Mario + Doc) — ⚪ DEAD (punching-bag 2026-07-02)

Poked FF00FF (solo) then re-tested ON A DK BAG 2026-07-02 (`mario_onhit_probe.json`,
captures `tests/artifacts/extras-audit/Mario-upb_coin-bag/`). **Result: ⚪ DEAD.**
Mario's up-B connected on the bag (first hitbox → Rebound; contact confirmed),
and the on-contact coin/ring effect was clearly visible — a **cyan-teal ring
with a dark starburst center**. Poking all 9 s11/s12/s13 records to green/magenta
(rep 1) then all to far RED (rep 2, `upb_coin_red`) produced **NO measurable
change** to the ring at ANY frame (pixel-diff of the ring region: vanilla ==
poked, cyan/green counts identical, no red injected). → the up-B coin/contact
ring is a **common-bank effect (EfCoData)**, NOT these EfMrData records. Same
class of finding as Ness Model[0]/[1] and Luigi s9/s10. **Do NOT ship `upb_coin`.**

| marker | color1 off | color1 | color2(env) off | color2 | (script,op) | hypothesized semantic | verdict |
|--------|-----------|--------|-----------------|--------|-------------|-----------------------|---------|
| 0x62C | 0x62E | FFCE0A | 0x635 | C70505 | (s11,CF) | up-B contact (NOT the coin ring) | ⚪ dead |
| 0x63D | 0x63F | FF3705 | — | — | (s11,CF) | up-B contact faint (cnt=4) | ⚪ dead |
| 0x69C | 0x69E | F7FF0A | 0x6A5 | D73706 | (s12,CF) | up-B contact | ⚪ dead |
| 0x6A9 | 0x6AB | FBFF0A | — | — | (s12,CF) | up-B faint (cnt=8) | ⚪ dead |
| 0x700 | 0x702 | B5F6FF | 0x709 | 0C17D7 | (s13,CF) | up-B fist | ⚪ dead |
| 0x70D | 0x70F | 056AC7 | — | — | (s13,CF) | up-B fist faint (cnt=4) | ⚪ dead |

> NOTE: contact registered as **Rebound** (up-B's first hitbox is a weak
> multi-hit — the bag rebounds rather than entering Damage*). Rebound IS a
> hit-contact state and the coin ring rendered on-screen in both reps, so the
> null is a real "these records don't drive the ring", not a whiff. Two reps
> (green/magenta and far-red anti-colors) agree.

---

## EfMrData.dat — model-region blocks

### `07_07_07` blocks (marker `07 07 07 04`; color1 = core @marker+4, color2 = glow @marker+8)

Poked FF6600 (hand circle) + FF0000 (5 tornado). Verdict from `tornado_07-downb-f{14,24}.png`
(Mario) + `datram-probe-docmario/doc_tornado_07-downb-f24.png` (Doc). 🟢 STRONG:
the whole tornado vortex + horizontal spin arcs + ground ripple went full red;
identical on Doc.

| marker | color1 off | color1 | color2 off | color2 | verified semantic | verdict |
|--------|-----------|--------|-----------|--------|-------------------|---------|
| 0x11AF4 | 0x11AF8 | FFFFB2 | 0x11AFC | FF6600 | fireball hand circle (Mario only) | 🟢 (bundled in fireball 07 poke; see PlMr note) |
| 0x1237C | 0x12380 | B2FFFF | 0x12384 | 0000FF | tornado outer swirl (down-B) | 🟢 tornado_07 (Mario+Doc) |
| 0x12448 | 0x1244C | B2FFFF | 0x12450 | 0000FF | tornado outer swirl | 🟢 tornado_07 (Mario+Doc) |
| 0x12514 | 0x12518 | 99CCFF | 0x1251C | 0000FF | tornado inner side 1 | 🟢 tornado_07 (Mario+Doc) |
| 0x125E0 | 0x125E4 | 99CCFF | 0x125E8 | 0000FF | tornado inner side 2 | 🟢 tornado_07 (Mario+Doc) |
| 0x126AC | 0x126B0 | CCFFFF | 0x126B4 | 0033FF | tornado underneath | 🟢 tornado_07 (Mario+Doc) |

All six markers verified at the exact old-cited offsets (no drift). color1
(core @+4) and color2 (glow @+8) both contribute; poking both = full red swirl.

### `42_48` blocks (HSD material; marker `42 48` sits at block_start+16; color RGBA at block_start)

**DIFFUSE (block+4) dominates; AMBIENT (block+0) is a visual NO-OP.** Split-tested
in `mario_probe_extra`: `tornado_42_diffuse_only` (block+4 = 00FF00) turned the
ground ripple + horizontal spin haze GREEN (visible); `tornado_42_ambient_only`
(block+0 = FF00FF) produced NO change vs vanilla. Confirms Fox/Falco precedent.
The 42 layer drives the tornado's ground ripple / finish haze — a real but minor
SECONDARY tint (the bright vortex is 07-driven). Ship block+4 only; drop block+0.

| block off | diffuse off (SHIP) | ambient off (no-op) | marker off | verified semantic | verdict |
|-----------|-------------------|--------------------|-----------|-------------------|---------|
| 0x11B64 | 0x11B68 | 0x11B64 | 0x11B74 | ring around hand after fireball | 🟢 diffuse (bundled) |
| 0x123EC | 0x123F0 | 0x123EC | 0x123FC | tornado ground ripple / outer ending | 🟢 tornado_42 diffuse |
| 0x124B8 | 0x124BC | 0x124B8 | 0x124C8 | tornado ground ripple / outer ending | 🟢 tornado_42 diffuse |
| 0x12584 | 0x12588 | 0x12584 | 0x12594 | tornado spin haze side 1 | 🟢 tornado_42 diffuse |
| 0x12650 | 0x12654 | 0x12650 | 0x12660 | tornado spin haze side 2 | 🟢 tornado_42 diffuse |
| **0x1271C** | 0x12720 | 0x1271C | 0x1272C | tornado ground haze below Mario — **old cite 0x1271B off by 1** | 🟢 tornado_42 diffuse |

---

## PlMr.dat — player-file material colors (Mario)

Poked cyan (fireball group) / green (cape). Verdicts from
`fb_aura_material_plmr-neutralb-f{16,24,46}.png` + `cape_material_plmr-sideb-f{12,20}.png`.

| off | format | bytes | marker | verified semantic | verdict |
|-----|--------|-------|--------|-------------------|---------|
| 0xFA40 | 07_07_07 | 07070704 FF6600 00 FF3300 | @0xFA40 | **fireball aura/glow halo** — inner(@0xFA44)/outer(@0xFA48). The soft round glow surrounding the fireball orb turned cyan. **Un-corroborated by ref mod 15777, but LIVE-confirmed.** | 🟢 fb_aura (Mario only) |
| 0xFAB0 | 42_48 | 808080FF FF4C00 FF... marker@0xFAC0 | @0xFAC0 | fireball aura material (diffuse @0xFAB4 dominant) | 🟢 fb_aura (Mario only) |
| 0xFB50 | 42_48 | 000000FF FFFFFF FF... marker@0xFB60 | @0xFB60 | fireball color material — bundled in the cyan aura poke; contributes to the fireball body glow (the white core orb itself stayed white — separate texture) | 🟢 fb_aura (Mario only) |
| 0x14EAC | 42_48 | FFFFFFFF FFFFFFFF 333333FF 3F800000 marker@0x14EBC | @0x14EBC | **Mario cape cloth color** (color1@0x14EAC, color2@0x14EB0, specular 333333). Cape cloth turned bright green — STRONG, clean. | 🟢 cape_material (Mario) |

## PlDr.dat — player-file material colors (Dr. Mario)

Verdict from `datram-probe-docmario/doc_cape_material_pldr-sideb-f{12,20}.png`.

| off | format | bytes | marker | verified semantic | verdict |
|-----|--------|-------|--------|-------------------|---------|
| **0x19CAC** | 42_48 | FFFFFFFF FFFFFFFF 333333FF 3F800000 marker@0x19CBC | @0x19CBC | **Doc cape cloth color** (color1@0x19CAC, color2@0x19CB0). Cape turned bright green — STRONG, clean. Ref mod 13332 + LIVE both confirm. **old cite 0x19CA0 off by 12 (0xC)** | 🟢 doc_cape_material (strongest ship candidate) |

Doc has NO fireball aura block (throws pills). Doc's tornado/coin-punch reuse
the EfMrData blocks above.

---

## Reference-mod diff results (base-md5 / same-size rule — lesson 4)

| post | mod | base | same size? | verdict |
|------|-----|------|-----------|---------|
| **13332** Blue Cape Dr. Mario | `PlDr Blue cape for doc .dat` (251170) | PlDr.dat (251170) | YES | **CLEAN — 5 bytes @0x19CAC-0x19CB2.** color1 `FFFFFF`→`00D0FF` (blue), color2 `FFFF`(partial)→`80BAD1`. Confirms Doc cape block @0x19CAC exactly; corrects old 0x19CA0 cite. |
| 15777 Better Fire Ball | PlMr.dat (194992) | PlMr.dat (194992) | YES | **NON-CORROBORATING.** 12017 diff bytes, ALL in the 0xFDB6-0x13EDF padding region (adds a new fireball model/effect). Does NOT touch the vanilla fireball color blocks 0xFA40/0xFAB0/0xFB50 or cape 0x14EAC. So the fireball color offsets remain UN-corroborated by this mod. |
| 14851 Unmirrored Mario Cape | PlMr.dat (197656) | PlMr.dat (194992) | **NO (re-saved)** | **UNUSABLE for offsets** (size changed → HSDRaw re-save → offsets shifted). Skipped per lesson 4. |

Note: `storage/test-base/files/PlDrYeMod.dat` (483018) is a full Doc yellow
costume **texture** recolor (~74K diff bytes vs every Doc costume base) — not an
effect mod; irrelevant to this map.

---

## Candidate summary (post-LIVE)

- **CF ptcl records: 25** — fireball 15 🟢, cape 4 🟢, up-B coin-punch 6 ⏳(on-hit).
- **07_07_07 blocks: 7** — 5 tornado 🟢 + 1 fireball-hand-circle 🟢 (EfMrData) +
  1 fireball-aura 🟢 (PlMr 0xFA40).
- **42_48 blocks: 10** — 6 EfMrData (1 fireball-ring + 5 tornado) 🟢 DIFFUSE
  (ambient ⚪ no-op) + 2 PlMr fireball aura/color 🟢 + 1 PlMr cape 🟢 + 1 PlDr
  cape 🟢.
- **Verdict tally: 🟢 42 verified sites · ⏳ 6 on-hit-pending (up-B) · ⚪ ambient
  bytes no-op (not counted as sites).**
- Total distinct candidate color sites judged: **48** (42 verified, 6 pending).

## AUDIT_HINTS (frame windows from the LIVE session; anti-colors per lesson 11)

Best capture frames observed per group (use for `extras_audit.py` final verify):

- `neutralb` (fireball, Mario only): effect visible ~f16-46. Fireball body/trail
  vanilla hue = **orange/red** → poke **cyan `00FFFF`** (hand-smoke, trailing,
  aura) or **green `00FF00`** (ball particles). Landing/square use **magenta
  `FF00FF`** / **cyan**. Best frames: f24, f46.
- `sideb` (cape): cape swing sparkles + cloth visible ~f12-30. Cape CLOTH vanilla
  = yellow (Mario) / white (Doc) → poke **green `00FF00`**. Cape SPARKLE stars
  vanilla = multi-hue blue/cyan/magenta (EnvCol-heavy) → poke **red `FF0000`** or
  green (subtle result — flag EYEBALL). Best frames: f12, f20.
- `downb` (tornado): tornado visible ~f6-24 (ends ~f30, then landing dust). 07
  vortex + 42 ground-haze vanilla = **blue/cyan** → poke **red/orange `FF0000`/
  `FF6600`**. Best frames: f14, f24. **Mashed-rise NOT tested — see open lead 5.**
- `upb` (coin punch): **ON-HIT ONLY, no solo verify.** Coin/contact vanilla =
  yellow/gold/cyan → poke **magenta `FF00FF`**. Needs punching-bag harness.

## Suggested editor grouping (for WIRE)

**SUPERSEDED — see the "Shippable-now summary (for WIRE)" section below** for the
LIVE-verified per-extra layer tables with exact offsets, vanilla bytes, tags, and
AUDIT_HINTS. Groupings: `mario_fireball` (Mario only), `mario_cape`/`doc_cape`
(shared sparkles + per-char cloth), `mario_tornado` (Mario+Doc), `upb_coin`
(defer — on-hit).

## Open leads / flags — RESOLVED by LIVE session (2026-07-02)

1. ✅ RESOLVED. Fireball PlMr blocks (0xFA40/0xFAB0/0xFB50) DO recolor the fireball
   aura/glow halo (cyan poke visible). Un-corroborated by mod 15777, but live-
   confirmed. Ship as Mario-only fireball aura.
2. ✅ RESOLVED. Cape 0x567 (black RGB) is NOT dead — isolated green poke produced
   a visible cyan/teal cape sparkle. Black base = alpha mask; color IS expressed.
3. ✅ RESOLVED. 42_48 diffuse (block+4) DOMINATES; ambient (block+0) is a no-op.
   Ship block+4 only.
4. ✅ RESOLVED. docmario_probe ran — all shared EfMrData rows (cape sparkles,
   tornado 07/42, up-B) fire identically on Doc; Doc cape material 0x19CAC 🟢.
5. ⚠️ NOT TESTED — probe limitation. The `downb` handler in `ingame/moves.py`
   fires B **once** (single press, no mash loop). Mario's down-B mashed-rise
   (repeated B to gain height) is NOT expressible in effect_probe.py, so any
   extra scripts spawned by mashing were not observed. If mashed-rise has its own
   effect scripts they remain an OPEN LEAD (would need a mash-capable driver).
   None of the base-tornado scripts appear to need it (full tornado captured
   from a single press).
6. ✅ RESOLVED. Doc's up-B coin-punch reads the same EfMrData rows (shared file);
   both chars show NO solo effect (on-hit only) → ⏳ punching-bag for both.

---

## Shippable-now summary (for WIRE)

Five extras. All offsets below are exact, marker-verified, LIVE-judged. CF
records: color1 = PrimCol RGB @marker+2, color2(_c2) = EnvCol RGB @marker+9
(EnvCol dominates sustained tint — expose as `_c1`/`_c2` multi-RGB per lesson 3).
07 blocks: color1(core)@+4, color2(glow)@+8. 42 blocks: **ship diffuse@+4 ONLY**
(ambient@+0 no-op).

### Extra `mario_fireball` (Mario only — Doc throws pills, gate Doc out)

Target `EfMrData.dat` (CF ptcls) + `PlMr.dat` (aura material).

| layer | format | offsets (c1 / c2) | vanilla c1 | vanilla c2 | tag |
|-------|--------|-------------------|-----------|-----------|-----|
| hand smoke A | CF | 0x162 / 0x169 | FFFFFF | FFCC4A | s1 CF#1 |
| hand smoke B | CF | 0x177 / 0x17E | FFA217 | BA120D | s1 CF#2 |
| hand smoke C | CF | 0x184 / 0x18B | 9C060B | 540405 | s1 CF#3 (cnt7) |
| trailing fire A | CF | 0x20C / 0x213 | C7BB0D | D43B08 | s2 |
| trailing fire B | CF | 0x21F / 0x226 | FFA800 | FF5900 | s2 |
| trailing fire C | CF | 0x22C / 0x233 | FF070F | 510A00 | s2 (cnt8) |
| ball particles A | CF | 0x2E5 / 0x2EC | FDEB74 | E33C09 | s4 |
| ball particles B | CF | 0x2F2 / 0x2F9 | B90303 | 610101 | s4 (cnt12) |
| ball particles C | CF | 0x355 / 0x35C | FDE467 | D42304 | s5 |
| ball particles D | CF | 0x362 / 0x369 | 7D4202 | 2E0000 | s5 (cnt12) |
| landing dust A | CF | 0x3CA / 0x3D1 | FEFCE2 | FFF75C | s6 |
| landing dust B | CF | 0x3DD / 0x3E4 | FCE669 | D60B0E | s6 |
| landing dust C | CF | 0x3EA / 0x3F1 | F9AC06 | 6B0507 | s6 (cnt7) |
| square particles A | CF | 0x476 / 0x47D | FF290C | FFFF82 | s7 |
| square particles B | CF | 0x486 / 0x48D | FFFF6E | FF0C14 | s7 |
| aura 07 (PlMr) | 07 | 0xFA44 / 0xFA48 | FF6600 | FF3300 | glow halo |
| aura 42 (PlMr) | 42 | 0xFAB4 (diffuse) | FF4C00 | — | aura material |
| color 42 (PlMr) | 42 | 0xFB54 (diffuse) | FFFFFF | — | body glow |

AUDIT_HINTS: `neutralb` frames 16-46; anti-color **cyan `00FFFF`** (vanilla
orange/red). Grouping: five `_c1`/`_c2` CF sub-groups (hand_smoke, trailing_fire,
ball_particles, landing_dust, square_particles) + PlMr aura block.

### Extra `mario_cape` (Mario) / `doc_cape` (Dr. Mario)

Cape sparkles are SHARED `EfMrData.dat`; cape CLOTH is per-char player file.

| layer | format | offsets (c1 / c2) | vanilla c1 | vanilla c2 | tag | applies |
|-------|--------|-------------------|-----------|-----------|-----|---------|
| sparkle A | CF | 0x4E0 / 0x4E7 | 6BFDFF | 1105FF | s8 CF#1 | Mario+Doc |
| sparkle B | CF | 0x4ED / — | D1A3FF | — | s8 CF#2 (cnt8) | Mario+Doc |
| sparkle C | CF | 0x505 / — | BF09A1 | — | s8 CF#3 (cnt4) | Mario+Doc |
| sparkle D (trail) | CF | 0x569 / — | 000000 | — | s9 (alpha-mask base) | Mario+Doc |
| cape cloth (Mario) | 42 | 0x14EAC / 0x14EB0 | FFFFFF | FFFFFF | PlMr | Mario |
| cape cloth (Doc) | 42 | 0x19CAC / 0x19CB0 | FFFFFF | FFFFFF | PlDr | Doc |

AUDIT_HINTS: `sideb` frames 12-20; anti-color **green `00FF00`** for cloth
(vanilla yellow/white); sparkles vanilla multi-hue → **red `FF0000`** (SUBTLE —
EYEBALL). Grouping: cloth = the ship headline (clean/strong); sparkles = a `_c1`
CF list (subtle). Doc cape material 0x19CAC is the STRONGEST candidate (ref-mod
13332 + live). Since sparkles are shared, `mario_cape` and `doc_cape` share the
4 EfMrData sparkle offsets and differ only in the cloth PlMr/PlDr row.

### Extra `mario_tornado` (Mario + Dr. Mario — shared EfMrData)

| layer | format | offsets (c1 / c2 or diffuse) | vanilla | tag |
|-------|--------|------------------------------|---------|-----|
| hand circle 07 | 07 | 0x11AF8 / 0x11AFC | FFFFB2 / FF6600 | fireball-hand (Mario) |
| outer swirl 1 | 07 | 0x12380 / 0x12384 | B2FFFF / 0000FF | tornado |
| outer swirl 2 | 07 | 0x1244C / 0x12450 | B2FFFF / 0000FF | tornado |
| inner side 1 | 07 | 0x12518 / 0x1251C | 99CCFF / 0000FF | tornado |
| inner side 2 | 07 | 0x125E4 / 0x125E8 | 99CCFF / 0000FF | tornado |
| underneath | 07 | 0x126B0 / 0x126B4 | CCFFFF / 0033FF | tornado |
| hand ring 42 | 42 | 0x11B68 (diffuse) | FFFFFF | ground/finish |
| ground ripple 1 | 42 | 0x123F0 (diffuse) | FFFFFF | ground/finish |
| ground ripple 2 | 42 | 0x124BC (diffuse) | FFFFFF | ground/finish |
| spin haze 1 | 42 | 0x12588 (diffuse) | FFFFFF | ground/finish |
| spin haze 2 | 42 | 0x12654 (diffuse) | FFFFFF | ground/finish |
| ground haze | 42 | 0x12720 (diffuse) | FFFFFF | ground/finish |

AUDIT_HINTS: `downb` frames 14-24; anti-color **red/orange `FF0000`/`FF6600`**
(vanilla blue). Grouping: 07 (vortex, `_c1`/`_c2` core/glow) = primary; 42
diffuse (ground haze) = secondary. **DO NOT ship 42 ambient@+0 (no-op).** Fires
identically on Doc.

### Extra `upb_coin` (Mario + Dr. Mario — shared EfMrData) — ⚪ DEAD — DO NOT SHIP

6 CF offsets: 0x62E/0x635, 0x63F, 0x69E/0x6A5, 0x6AB, 0x702/0x709, 0x70F.
**Punching-bag pass 2026-07-02 killed this.** With a DK bag taking the up-B
coin punch, poking all 6 (green/magenta AND far-red) produced NO change to the
on-contact cyan-teal coin ring. The ring is a **common-bank (EfCoData)** effect,
not these records. Do NOT wire `upb_coin`. (Captures
`tests/artifacts/extras-audit/Mario-upb_coin-bag/`; details in the "Up-B coin
punch" section above.)

### Quarantined / kept OUT of char layers

- `EfMrData.dat` is the **shared Mario/Doc effect table** (not a common bank like
  EfCoData) — so its rows ARE char layers for BOTH Mario and Doc; nothing to
  quarantine there. Fireball ptcls apply to Mario only (Doc has no fireball).
- **42 ambient bytes (block+0: 0x11B64, 0x123EC, 0x124B8, 0x12584, 0x12650,
  0x1271C and PlMr 0xFAB0/0xFB50 ambient, PlDr 0x19C** ambient) — verified no-op;
  do not expose (would be a dead editor control).
- The fireball's **white core orb** is a separate texture (stayed white under the
  aura poke) — not in any color block; note for texture-pack work, not a layer.

### Downstream referrals

- **Punching-bag harness:** up-B coin-punch (6 CF offsets above) for both Mario
  and Doc. Also worth re-checking the fireball ball/square particles ON a target
  (their end-burst may differ on contact) — low priority, they verified solo.
- **Texture:** fireball white core orb; cape sparkle sprite shapes.
- **EfCoData:** none found — Mario/Doc effects are self-contained in EfMrData +
  player files. No common-bank spillover observed.
