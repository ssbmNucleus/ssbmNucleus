# Samus effect map (MAP stage — 2026-07-02)

Target files: `EfSsData.dat` (82986 B) and `PlSs.dat` (319219 B) in
`storage/test-base/files/`. Character `samus` (external ckind `0x10`).

Method: marker scan of both vanilla DATs → live RAM pokes via
`backend/devtools/effect_probe.py` (specs in scratchpad `samus_probe1.json` /
`samus_probe2.json` + this mission's `backend/probes/samus_probe.json`), captures
judged frame-by-frame. Reference mod post 13986 (Vaporwave Samus) is
**same-size** = trustworthy offsets; its diff clusters corroborate the poked
groups. Reference mod post 17088 (Rainbow) is RE-SAVED (EfSsData 82986→92806,
PlSs 319219→391639) → UNUSABLE for offsets (only its `og` files md5-match
vanilla). Powerbeam mod 14701 diffs almost entirely in the PlSs 0x36xxx
texture bank = the beam is a **texture**, not a color record (see open leads).

Captures live in `tests/artifacts/datram-probe-samus/` (boot 1 + this
mission's boot 3, ~270 files) and `tests/artifacts/datram-probe-samus2/`
(boot 2, 30 files). `tests/artifacts` is ONE level ABOVE the repo dir.

CF-record format (this file): marker `CF`, color1 at marker+2 (`_c1`),
secondary at color1+7 (`_c2`, dominates the sustained puff tint). 07-blocks:
marker `07 07 07 04`, bright core at marker+4, glow at marker+8.

### Structural parser cross-reference (relocation-proofing)

`python skinlab/ptcl_parse.py ../storage/test-base/files/EfSsData.dat --models`
decodes EfSsData cleanly: symbol `effSamusDataTable`, `effect_id_start=2000`,
22 generators (ptcl bank ends at 0x960), tex_bank@0x960, + 50 model-region
color blocks past the bank. In the decoder's terms: `_c1` = a **PRIMCOL**
operand (`0xCF`, PrimColor), `_c2` = the following **ENVCOL** operand (`0xDF`,
EnvColor — the "+7 secondary"). Each EfSs CF layer below is tagged
`(script N, opcode-kind, ordinal-within-script)` so WIRE/future missions can
re-derive the offset from the bank grammar if the file is re-saved and shifts.
The **screw-attack 07-quad and warm/late 07-blocks are model-region material
blocks** (past 0x960, among the 50), NOT ptcl scripts — they have no script
index; use their marker+4/+8 anchors. Script→move: `gfx_id − 2000` cross-ref
`efSync_Spawn` in decomp `ft/chara/ftSamus/*` (not run this pass — semantics
here are from live captures).

---

## Proposed extra: `screw_attack` (up-B electric arcs) — EfSsData.dat  ✅ VERIFIED

The screw-attack electric arcs that wrap Samus's body on up-B, plus the
rising spiral spark ring. Four identical 07-blocks (one per arc/quadrant).

| layer_id | format | offsets (marker+4 core / marker+8 glow) | vanilla | semantic | how |
|---|---|---|---|---|---|
| arc1_core | 070707 | 0x11588 (marker 0x11584) | FFFFFF | arc bright core | live-poke |
| arc1_glow | 070707 | 0x1158C | 0000FF | arc glow | live-poke |
| arc2_core | 070707 | 0x11648 (marker 0x11644) | FFFFFF | arc bright core | live-poke |
| arc2_glow | 070707 | 0x1164C | 0000FF | arc glow | live-poke |
| arc3_core | 070707 | 0x11708 (marker 0x11704) | FFFFFF | arc bright core | live-poke |
| arc3_glow | 070707 | 0x1170C | 0000FF | arc glow | live-poke |
| arc4_core | 070707 | 0x117C8 (marker 0x117C4) | FFFFFF | arc bright core | live-poke |
| arc4_glow | 070707 | 0x117CC | 0000FF | arc glow | live-poke |

Verified: `quad07mat-upb-f10.png` — all four arc cores turned green (from
the +4 green pokes) and the rising spiral spark ring below Samus turned green;
the +8 glow (magenta) reads faintly at the arc edges. Confirmed again in this
mission's `blue_quad-upb-*` (same offsets).

Suggested grouping: `_c1` (all four cores) + `_c2` (all four glows) fanned from
a DualColor editor's two pickers — exactly the Mewtwo bolts / Falcon `_c1`/`_c2`
convention. Vanilla is white core + blue glow.

AUDIT_HINTS: `upb:8,12,16` forced anti-colors core=`00FF00` glow=`FF00FF`.

---

## Proposed extra: `charge_shot` (neutral-B charge) — EfSsData.dat  ✅ (charge) / ⚠️ (fired ball is a texture)

Two sub-effects. The CHARGING vortex spark needles are color records (mapped).
The FIRED projectile ball (blue ring / pink inner ring / white core) is NOT
reachable via any tested color record — see open leads (texture bank).

| layer_id | format | offsets (c1 / c2) | vanilla | semantic | script/opcode/ord | how |
|---|---|---|---|---|---|---|
| charge_needles_c1 | CF-multi | 0x2E9 (marker 0x2E7) | FFFFFF | radiating charge spark-needle lines | script 5, PRIMCOL, #0 | live-poke |
| charge_needles_c2 | CF-multi | 0x2F0 | 090087 | needle secondary tint | script 5, ENVCOL, #0 | live-poke |

Verified: `datram-probe-samus2/needles2E7-neutralb-f40.png` — the radiating
spark needle lines around the arm cannon turned magenta (vanilla white/blue).
The blue swirl vortex + white core ball behind Samus were NOT affected by this
poke (they belong to the charge-ball, likely texture/ptcl).

⚠️ FIRED CHARGE-SHOT BALL: unmapped. Poking every candidate left it vanilla
(blue ring / pink inner / white core) — see `cf_group`, `blue_quad`,
`blue_120d0`, `blue_12834_129cc`, `fire_block` neutralb f40/f50 captures, all
show the identical vanilla projectile. Almost certainly a **texture/ptcl**
effect (the same conclusion the Powerbeam mod 14701 texture-bank diff points
to). Flag for a future texture-extra pass, not a color layer.

AUDIT_HINTS: `neutralb:20,40,54` (hold to charge; fire with
`inputs:["50:PRESS B","52:RELEASE B"]`), anti-colors needles c1=`FF00FF`.

---

## Proposed extra: `charge_ball` (fired charge-shot ball) — PlSs.dat TEXTURE  ✅ IN-GAME VERIFIED 2026-07-02

Dolphin verify PASSED: ISO built with `PlSs_ball_green.dat` swapped in, full
charge fired via input_at 50/52 — the flying ball rendered green with
cyan-green inner and preserved white core, matching
`036840_64x64_target_00FF00.png`
(`tests/artifacts/samus-ball-texture/verify/samus-neutralb-f62.png`). No
garble/hang. STRAGGLER FOUND (→ completeness sweep): the thin blue elliptical
ORBIT RINGS around the flying ball are NOT in this texture — they stayed
vanilla blue; separate unmapped element.

WIRE 2026-07-02: shipped as the `charge_ball` extra using the new
`texture_recolor` format (`backend/blueprints/extras/texture_recolor.py`,
promoted from this file's `plss_ball_probe.py` decode/rotate/encode).
Config in both mirrors (`backend/core/extra_types.py` `"Samus"` /
`frontend/src/config/extraTypes.js` `Samus`), single-ColorPicker editor via
`DualColorEditorModal` (one property, no `_c2`), preview added to both
`ExtraPreviews.jsx` mirrors, `extras_audit.py` build-stage mirror +
`AUDIT_HINTS` entry added. Self-test recoloring the vanilla block to
`00FF00` is byte-identical to `PlSs_ball_green.dat`'s ball region. Dolphin
verify-build deferred (no emulator this session) — run
`python devtools/extras_audit.py --char Samus --extra charge_ball` to EYEBALL.

STATIC texture mission 2026-07-02. The fired charge-shot BALL that the MAP pass
proved is not any color record (`charge_shot` ⚠️ note above) is a single
**RGB5A3 texture** in PlSs.dat. Located by diffing the two same-size community
mods against vanilla and tracing the HSD_Image struct.

### Ground truth (both mods are byte-size 319219 = vanilla; diffs trustworthy)
- post 14701 "POWERBEAM": diffs `0x36063-0x36727` (the I4 map, below) + a solid
  `0x36840-0x3883F` block (the RGB5A3 ball).
- post 13986 "Vaporwave": diffs `0x36840-0x3883F` heavily **plus** `0xD414`,
  `0x10600-0x107E2`, `0x11360-0x113DF` — those last three are the
  **missile/body-suit material** already mapped in the `missile` section
  (`plss_mat_10600` / `missile_body`), NOT the ball. **Overlap analysis**: the
  only region BOTH mods touch is `0x36840-0x3883F` → that is the ball, and it
  drives ONLY the ball (no overlap with beam/bomb; "POWERBEAM" = the mod's name
  for the fully-charged shot itself, not a separate beam texture).

### The texture(s)
| id | file offset (data section) | dims | GX format | role | verified |
|---|---|---|---|---|---|
| ball (RGB5A3) | **0x36840** (struct data-off 0x35A6C, dataPtr 0x36820) | 64×64 | **RGB5A3** (fmt 5) | the colored ball: blue outer glow + magenta/pink inner ring + white core, ~half transparent | probe decode → PNG (`tests/artifacts/samus-ball-texture/036840_64x64_vanilla.png`) shows exactly that |
| shape (I4) | 0x36040 (struct data-off 0x35B18) | 64×64 | I4 (fmt 0) grayscale | intensity/shape map; **no hue** — 14701 reshapes it, a recolor MUST NOT touch it | decode |

Single color-bearing texture. Blue (hue ~210–240°), magenta/pink (~300°) and
gray/white texels all live in the ONE RGB5A3 image, so this is **one `ball`
color layer** (not separate ball_outer/ball_inner) — the blue↔pink relationship
is preserved by rotating every texel's hue by the same delta.

**`VANILLA_DOMINANT_HUE = 239°`** (saturation-weighted, computed from the
texture itself — record as the constant; the outer glow dominates).

### CLI-addressable? **NO — raw texel patch required.**
The RGB5A3 image's TObj (data-off 0x35A84) sits in an **effect/particle
texture-graphics block** embedded in the fighter file (the `42 48 …` /
`60 00 00 11` TObj-in-ptcl-bank signatures at data 0x35AF0), NOT on a
JOBJ→DObj→MObj material tree. `HSDRawViewer --texture export ftDataSamus 0`
returns `Expected HSD_JOBJ at end of path, got SBM_FighterData` and no property
path reaches the block. This is the **same limitation the Fox campaign hit**
with effect-table TextureGraphics textures (see Fox `upb_texture` note in
`backend/core/extra_types.py`). So the existing `blueprints/extras/textures.py`
export/import CLI machinery CANNOT be used here.

### Patch recipe (color-picker driven, prototyped & working)
Script: **`backend/skinlab/plss_ball_probe.py`** (pure-Python HSD reader +
GX texel decode/encode; leans on `skinlab.datprobe` for header/pointer/format).
```
python -m skinlab.plss_ball_probe scan    <plss.dat>                     # locate
python -m skinlab.plss_ball_probe export   <plss.dat> <out_dir>          # PNGs
python -m skinlab.plss_ball_probe recolor  <plss.dat> <target_hex> <out.dat> [out_dir]
```
Recolor algorithm (color-picker, NOT hue-slider): given target RGB → target_hue;
`shift = target_hue − VANILLA_DOMINANT_HUE (239°)`; for each texel decode
RGB5A3→RGBA, `hue = (hue + shift) % 1`, keep S/L/alpha, re-encode RGB5A3 in
place. Grays/whites (low S) barely move → white core stays white; alpha
preserved → the transparent half stays transparent. Writes patched DAT at the
identical byte size (verified: 319219 B, changes confined to
`0x36840-0x3883F`). The I4 shape map is deliberately skipped (grayscale).

Demonstrated: `target=00FF00` (green: blue→green, pink→cyan-green, core white)
and `target=FF0000` (red: blue→red, pink→yellow, core white) — PNGs in
`tests/artifacts/samus-ball-texture/036840_64x64_target_{00FF00,FF0000}.png`,
patched DATs `PlSs_ball_{green,red}.dat` alongside.

### Generalizes to a shared `texture_recolor` extra format
This color-picker texel remap (target RGB → hue-rotate about a recorded
dominant-hue constant, preserve S/V/alpha, re-encode in original GX fmt) is the
intended replacement for the current hue-degrees slider used by Fox
`upb_texture` / Falcon `punch_texture`. Those extras route through the CLI
`export/shift_texture_hue/import` path; a future WIRE can wire `charge_ball` as
`type: "texture_recolor"` (raw texel path, non-CLI) and migrate the hue-slider
extras to the same color-picker UX (they stay CLI-addressable, so they keep the
CLI export/import but swap `shift_texture_hue`'s degrees arg for the
target-RGB→dominant-hue delta computed here).

### Open risks
1. **HSDRaw re-import round-trip is bypassed** — the patch is a raw in-place
   byte splice of the RGB5A3 block, so it does NOT go through HSDRaw's
   texture-injection (which is unavailable). Byte-size is identical and the
   only bytes touched are the ball texel block, so structurally safe, but a
   Dolphin verify must confirm the game renders it (no garbled ball / no hang).
2. **RGB5A3 4-bit precision**: hue rotation on a 4-bit-per-channel non-opaque
   region can band slightly; the opaque core uses 5-bit RGB555. Acceptable for
   a recolor but note in EYEBALL.
3. **Dominant-hue for near-gray targets**: a low-saturation target RGB gives an
   unstable target_hue; the effective shift still works (grays rotate to grays)
   but the UI should pass a saturated pick.

### Dolphin verify slot should run
Build a test ISO with the patched `PlSs_ball_green.dat` (and/or red) swapped in,
then screenshot Samus's neutral-B **charge release**: hold neutral-B to full
charge and fire. Frame-window precedent from the `charge_shot` map above:
`neutralb:20,40,54` to charge, fire with `inputs:["50:PRESS B","52:RELEASE B"]`,
then capture ~5–15 frames after release while the ball travels (it's a fast
projectile — grab several frames). Via `effect_probe.py`-style mid-move inputs,
or `extras_audit.py` once a `charge_ball` / `texture_recolor` layer is wired.
Expected: the flying ball's blue glow + pink ring recolor to the target hue,
white core stays white, ball shape/alpha unchanged. Compare against
`tests/artifacts/samus-ball-texture/036840_64x64_target_00FF00.png`.

---

## Proposed extra: `missile` (side-B) — EfSsData.dat + PlSs.dat  ✅ VERIFIED (EfSs) / ⚠️ (PlSs mat)

The contrail smoke behind the missile and the launch back-blast puff at the
cannon. Both are CF-record groups. Verified against vanilla (brown/tan trail).

| layer_id | format | offsets | vanilla (c1) | semantic | script/opcode/ord | how |
|---|---|---|---|---|---|---|
| contrail_c1 | CF-multi | 0x470, 0x47D | C27742 / 867E82 | missile contrail smoke core | script 9, PRIMCOL, #0 & #1 | live-poke |
| contrail_c2 | CF-multi | 0x477, 0x484 | 6E1B1D / 000000 | contrail secondary | script 9, ENVCOL, #0 & #1 | live-poke |
| backblast_c1 | CF-multi | 0x61F + chain 0x62D | D3ABA1 / 443B43 | launch back-blast puff | script 13, PRIMCOL, #1 & #2 | live-poke |
| backblast_c2 | CF-multi | 0x626, 0x634 | 51231F / 000000 | back-blast secondary | script 13, ENVCOL, #1 & #2 | live-poke |

Verified: `smokeBEG-sideb-f32.png` — contrail smoke behind the flying missile
turned GREEN (0x470 group) and the back-blast puff at the cannon turned MAGENTA
(0x612 group). `smokeBEG-sideb-f22.png` shows the green muzzle patch at launch.

The `smokeBEG` experiment also poked a CYAN group `0x752/0x759/0x75F/0x766/
0x76D/0x774` (**script 16** — structurally an exact clone of the script-13
back-blast: same PRIMCOL/ENVCOL ordinals #0/#1/#2, same texGrp 5) — **no
clearly attributable cyan element** appeared in the sideb captures (script 16
is likely the missile's *other* puff — e.g. the on-hit detonation smoke, or a
mirrored back-blast). Flag as pending EYEBALL / punching-bag; the same cluster
is in the 13986 same-size diff (0x752-0x776), so it IS a real recolor target,
just not solo-visible on a whiffed missile.

PlSs missile material (⚠️ uncertain): boot-2 `plssQuad` poked ambient
0x10600/0x106A0/0x10740/0x107E0 (all vanilla 808080) + 0xD414 (E6E6E6) RED and
the prior agent judged the missile body pink-red. This mission's
`plss_mat_10600` / `plss_mat_d414` poked the SAME offsets with distinct
per-slot colors and the pink missile TIP stayed vanilla pink (only a faint
reddish launch-flash tint). **A/B is weak — flag for EYEBALL.** These are HSD
material RGBA blocks (ambient at base, diffuse at base+4); 13986 diffs 0xD414
+ the quad too. If real, group as `missile_body` material layers, but do not
ship until EYEBALL confirms a clean color swap.

AUDIT_HINTS: `sideb:14,22,32` anti-colors contrail=`00FF00` backblast=`FF00FF`.

---

## Punching-bag RE-RUN RESULTS (2026-07-02, clean bag) — read this over the older pass below

The prior bag pass (below) was compromised because Samus's charge shot launched
the bag off-stage. This re-run fixed that: **DK bag dx=5, percent zeroed every
rep, and every rep verifiably CONNECTED** (missile → DamageN3, charge shot →
DamageN2, bag stayed grounded, never launched off-stage). Spec:
`backend/probes/samus_onhit_rerun_probe.json`. Captures:
`tests/artifacts/datram-probe-samus-onhit-rerun/`. Net: **all three leads are
DEAD/null on a confirmed hit.**

- **`flashA` script 8 (0x3FF/0x406/0x418) — 🔴 DEAD on-hit.** Charge shot fired
  into the bag (DamageN2, HIT). The connect burst is a **blue radial flash +
  purple/magenta hitspark + white smoke trail** — IDENTICAL in vanilla_charge
  vs flashA_charge at every frame (f56-f90); the green (0x3FF) + magenta
  (0x406/0x418) pokes produced ZERO visible change. The on-hit visual is the
  **generic common-bank hit-spark** (blue+purple), not the EfSs script-8 flash.
  Confirms the prior "leans common-bank" lean → now a solid negative. CAVEAT:
  the shot fired near-uncharged (execute's B-tap + f52 release ≈ minimal charge,
  only 7-8%); the big FULLY-CHARGED-shot flash (where flashA might truly live)
  was not achievable — the harness can't cleanly hold B for the ~60f charge.
  So this is DEAD *for the small/mid shot*; a fully-charged shot flash remains
  strictly untested (would need a charge-hold input path). Captures:
  `flashA_charge-neutralb-f56/f60` vs `vanilla_charge-*`.
- **`warm` 07-block 0x114C4 (core 0x114C8=FFFF8A / glow 0x114CC=FF4C00) — 🔴 DEAD
  on-hit.** Same charge-shot-into-bag setup. Poking core green + glow magenta
  left the connect burst IDENTICAL to vanilla_charge (blue flash + purple
  hitspark) — no warm/explosion element renders from these offsets on the hit.
  Same fully-charged caveat as flashA. Now DEAD on-hit (was untested — Samus fell
  off in the prior pass). Captures: `warm_block_charge-neutralb-f56/f60`.
- **`missile` script 16 cyan clone (0x752/0x759/0x75F/0x766/0x76D/0x774) — 🔴 DEAD
  on-hit.** Missile detonated ON the bag (DamageN3, HIT). The detonation is a
  yellow/orange fireball + white bloom + orange spark dots at f26, spraying into
  orange fireballs + white/gray smoke puffs at f34 — IDENTICAL in vanilla_missile
  vs script16_cyan (green poke). ZERO green anywhere at any frame. The script-16
  cyan clone does NOT own the missile detonation smoke or any visible on-hit
  element. It is a real 13986-diff target but drives an unrendered/consumed
  layer — **not shippable.** Captures: `script16_cyan-sideb-f26/f34` vs
  `vanilla_missile-sideb-*`.

**Net (clean re-run):** flashA, warm-block, and the script-16 cyan clone are all
DEAD/null on a confirmed hit (small/mid shots). None ships.

### FULLY-CHARGED re-probe — flashA & warm STILL DEAD (STRAGGLER-CLOSEOUT 2026-07-02)

Closed the residual "fully-charged" caveat. Built a charge-hold input schedule
(`samus_fullcharge_probe.json`, pinned DK bag dx20): `execute("neutralb")` starts
the charge, then held B ~f2-f58 to build charge, released, re-pressed B at f62 to
FIRE, capturing f70-106 as the ball travelled the 20-unit gap and connected. The
shot connected as a **large charged-shot burst** (bag → DamageHi2 launch; the
connect flash is the big purple/blue explosion + white lightning arcs + star
sparkles + dark shockwave rays — visibly far more charged than the prior 7-8%
dinky shot). Poked flashA (0x3FF/0x406/0x418) all **RED** and warm
(0x114C8 red / 0x114CC green): **the connect explosion is byte-for-eye IDENTICAL
to vanilla_full at every frame (f70-f74)** — ZERO red/green in the flash; only
ambient background sparkle stars differ (RNG/frame timing, not the poke), and the
aftermath sparkle trail stays vanilla purple/magenta. **flashA and warm are DEAD
across ALL charge levels** — the charged-shot connect flash is a TEXTURE/MODEL
effect, not these EfSs ptcl operands. The narrow "fully-charged" uncertainty is
now CLOSED negative. Captures: `tests/artifacts/datram-probe-samus-fullcharge/`
(`{vanilla_full,flashA_full,warm_full}-neutralb-f70/f74`). Spec:
`backend/probes/samus_fullcharge_probe.json`. (Recipe note: the full-charge fire path is
now a reusable pattern — hold B ~56f via the move's `inputs` schedule, release,
re-press B to fire; the pinned bag at dx20 lets the ball travel + connect.)

## Punching-bag pass RESULTS (2026-07-02) — SUPERSEDED by the clean re-run above

Ran `samus_onhit_probe.json` (DK bag dx=5): sideb missile, neutralb charge-shot
fired into the bag, downb bomb detonation. Captures
`tests/artifacts/extras-audit/Samus-onhit-bag/`. **The run was partly compromised**
— Samus's charge shot launched DK far/high (DamageFlyN), so the missile (script 16)
and warm-block reps ran with a displaced/knocked-down bag and could not connect.
Net verdicts:

- **`bomb` groups (scripts 10/15/17: 0x4DF/0x4ED/0x4FB, 0x6D6/0x6E3, 0x7CF)** —
  ⚪ NO VISIBLE RESPONSE on a REAL detonation. The bomb was laid and detonated on
  the bag (`bomb_groups_s10_15_17-downb-f30.png` shows the orange/yellow fireball
  explosion on DK). Poking the spark-dots magenta/green + the fireball blue/green
  produced ZERO green/magenta/blue in the explosion at any frame (pixel-checked
  f10–f78). The detonation is dominated by the orange fire + white bloom (as the
  prior spec predicted). Either these records are consumed/washed-out or drive an
  unrendered sub-layer. **Not shippable.** Flag for EYEBALL with a tight
  effect-region crop if bombs are ever revisited, but the live evidence is
  a null even WITH a detonation.
- **`flashA` script 8 (0x3FF/0x406/0x418)** — INCONCLUSIVE. The charge shot DID
  hit the bag (DamageFlyN) but there was no vanilla-hit control (vanilla neutralb
  whiffed), and the brief hit flash read blue/purple (standard hit-spark), not
  the poked green. Leans common-bank / not-flashA but NOT settled — flag EYEBALL /
  a re-run with a bag that can't be launched away.
- **`missile` script 16 cyan clone (0x752…0x774)** — STILL UNATTRIBUTED. The bag
  was knocked down before the missile rep, so no on-hit detonation was observed.
  No cyan element appeared on the visible missile. Remains a real 13986-diff
  target with no isolated verdict — EYEBALL / re-run.
- **warm 07-block 0x114C4** — NOT TESTED (Samus fell off after the bomb-jump →
  RebirthWait, the downb rep errored before capturing). Still pending.

**Punching-bag re-run recommendation:** give the bag a high enough percent-cap
that Samus's moves can't launch it clear across the stage between reps, and run
ONE experiment per boot (flashA, then missile, then warm) so a prior launch
doesn't displace the bag for the next. The bomb detonation is the one clean
result here (null).

## Proposed extra: `bomb` (down-B) — EfSsData.dat  ⚪ NO-RESPONSE on-hit (punching-bag 2026-07-02) / was 🟡 PENDING

The morph-ball bomb + its detonation flash. Candidate CF groups were poked but
the detonation frames (f78-90) are dominated by a large white bloom that
washes out the anti-colors, and the laid-bomb frames show only the orange/red
bomb texture. No clean attribution yet.

| layer_id | format | offsets | vanilla (c1) | candidate semantic | script/opcode/ord | how |
|---|---|---|---|---|---|---|
| bomb_grpC | CF-multi | 0x4DF/0x4ED/0x4FB (+env 0x4E6/0x4F4/0x502) | FFFFFF | bomb spark/dots | script 10, 3× PRIMCOL/ENVCOL | poked (inconclusive) |
| bomb_grpF | CF-multi | 0x6D6, 0x6E3 (+env 0x6DD/0x6EA) | FDDB86 | bomb fireball tint | script 15, PRIMCOL #0/#1 | poked (inconclusive) |
| bomb_grpH | CF-multi | 0x7CF (+env 0x7D6) | FF0A0A | bomb ember/red spark | script 17, PRIMCOL #0 | poked (inconclusive) |

`bombF` (0x6D6 blue / 0x6E3 green) and `bombCG` (0x4DF magenta / 0x752 green)
at downb f84 (`datram-probe-samus2/`) both show only orange fire + white flash
— the flash bloom obscures. `sparksCDH-downb-f30` shows the laid bomb (orange
morph-ball) with no visible poke color. These clusters ARE in the 13986
same-size diff (0x4DF-0x4E8, 0x4FC-0x504, 0x6D6-0x6EC, 0x7D0-0x7D8), so they
are real Samus recolor targets — they just need earlier detonation frames
and/or the effect-region crop. Flag for EYEBALL with a tighter frame window
(detonation is ~40-55 frames after the bomb is laid).

AUDIT_HINTS (tentative): `downb:55,60,65` (detonation) — needs frame re-tune;
anti-colors far from orange.

---

## Dead / consumed / no-visible-change (verified null this pass)

Live-poke null ≠ dead offset (may be consumed at effect-system load, or an
on-hit-only layer). Confirm with a build-path run before declaring irrelevant.

- **`rec1DC` EfSsData 0x1DE/0x1E5** (script 2, PRIMCOL/ENVCOL #0; vanilla
  20638F / 060251): green poke on neutralb charge showed no change
  (`datram-probe-samus2/rec1DC-neutralb-*`). Not in the 13986 diff — likely
  genuinely unused for charge.
- **`flashA` EfSsData 0x3FF/0x406/0x418** (script 8, PRIMCOL #0 @0x3FF /
  ENVCOL #0 @0x406 / PRIMCOL #1 @0x418): green+magenta on sideb — the yellow
  missile-launch flash stayed yellow (`flashA-sideb-f22`). BUT 0x3FF-0x408 +
  0x419 ARE in the 13986 same-size diff → likely an on-hit / charge-shot-flash
  layer (script 8 texGrp=4, shared with the charge scripts 6/19) not shown on
  a whiffed missile. PUNCHING-BAG 2026-07-02: charge shot hit the bag but the
  flash read blue/purple (not the poked green) and there was no clean vanilla-hit
  control → INCONCLUSIVE, needs a re-run (bag that can't be launched away).
- **`fire_block` / warm 07-block 0x114C4** (core 0x114C8=FFFF8A glow
  0x114CC=FF4C00): green/magenta poke showed NO change on charge shot
  (`fire_block-neutralb-f40`) OR missile launch flash (`flash114C4-sideb-f22`).
  It IS in the 13986 diff (0x114C9-0x114CE, "warm flash") → strong on-hit /
  explosion candidate. Flag pending punching-bag + one build-path run.
- **late blue 07-blocks 0x120D0 / 0x12834 / 0x129CC** (light-blue cores, blue
  glows): poked green/magenta/orange (`late07`, `blue_120d0`,
  `blue_12834_129cc`) — the flying charge-shot ball stayed vanilla. These are
  probably the CHARGE-SHOT ball's color records BUT the visible ball is
  texture-driven (they may only tint an unrendered/consumed layer). Pending.
- **`sparksCDH` 0x596 / 0x7CF / 0x4DF** (script 12 PRIMCOL#0 @0x596; script 17
  PRIMCOL#0 @0x7CF; script 10 PRIMCOL#0 @0x4DF): no attributable element on
  neutralb/upb/downb. 0x596-0x5AC (script 12) and 0x4DF-0x504 (script 10) and
  0x7D0-0x7D8 (script 17) all appear in the 13986 diff → real targets,
  on-hit/detonation-pending (bomb candidates, see `bomb` section).
- **mat 0x11534 / 0x11538** (EfSsData, vanilla 808080 / D8FFCF): poked in
  `quad07mat` (orange/cyan) with no isolated visible change; 0x11538 (D8FFCF)
  is in the 13986 diff. Untested in isolation — flag pending.
- **PlSs 0x11360-0x113DF** and **0x35B60/0x35C2C**: in the 13986 diff / boot-1
  `plssMisc`; not isolated-verified. Likely body/beam material or texture
  palette. Pending.

---

## QUARANTINE: EfCoData.dat (CAST-SHARED — NEVER ship as a Samus layer)

Rainbow mod 17088 recolors `EfCoData.dat` (the common cast-wide effects file)
as a pure texture-bank recolor (0x8CD77-0x97F3F per prior recon). EfCoData is
shared across the whole cast — any finding there belongs to a common-effects
map, NOT to Samus. Not investigated this pass; listed only so it is never
mistaken for a Samus effect.

---

## Open leads / honest gaps

1. **Fired charge-shot ball color = texture, not a record.** Highest-value
   remaining Samus effect and the one users most want. All color-record
   candidates left it vanilla. Powerbeam mod 14701's texture-bank diff (PlSs
   0x36xxx) + this null result point to a texture extra (like Fox `upb_texture`
   / Falcon `punch_texture`) — needs the HSDRaw texture CLI, out of MAP scope.
2. **On-hit / detonation layers** — RE-RUN 2026-07-02 (clean bag, all connected):
   **flashA 0x3FF, warm 0x114C4, and the script-16 cyan clone are all 🔴 DEAD/null
   on a confirmed hit** (small/mid charge shot + missile detonation). The hit
   visuals are common-bank hitsparks / orange fireball + white bloom (texture),
   NOT these EfSs records. They ARE in the 13986 diff but drive unrendered/consumed
   layers on this hit. ONLY residual: the FULLY-charged-shot flash (flashA/warm)
   is strictly untested — the harness can't hold B for the ~60f charge. Sparks
   0x596 / bomb groups: still null (see bomb section). See the RE-RUN RESULTS block.
3. **PlSs missile material** A/B is weak — needs EYEBALL with the effect region
   cropped.
4. **grapple (Z-air / grab)**: Samus `grab` recipe FAILS in the harness
   (char-specific state) and was dropped. Grapple beam color not investigated;
   it is likely a PlSs material/texture. Open.
5. **cyan missile group 0x752 (script 16) / mat 0x11538 / PlSs 0x11360**: real
   13986 diff targets, no isolated verdict — EYEBALL/punching-bag.

**Parser completeness note:** `ptcl_parse` enumerates 63 color operands in the
ptcl bank (22 scripts) + 50 model-region blocks. Every EfSs CF-record layer
mapped/flagged above corresponds to a real script operand — no ptcl-bank color
record was missed by the marker scan. Scripts NOT referenced above (0, 3, 6,
19, 20, 21) hold charge-glow / hurtbox / generic operands not isolated this
pass; scripts 6/19 (texGrp 4, blue/magenta prim colors) are candidate
charge-vortex layers worth a future targeted poke if the charge glow needs
exposing.

## Shippable-now summary (for WIRE)

- `screw_attack`: 8-offset 070707 quad, `_c1`(4 cores)/`_c2`(4 glows). SOLID.
- `missile`: `contrail_c1/c2` (0x470,0x47D / 0x477,0x484), `backblast_c1/c2`
  (0x61F / 0x626, chain 0x612/0x619/0x62D/0x634). SOLID for EfSs smoke.
- `charge_shot`: `charge_needles_c1/c2` (0x2E9 / 0x2F0) only — the ball is a
  texture (do NOT wire a ball-color layer).
- Everything else: hold for EYEBALL / punching-bag / texture pass.
