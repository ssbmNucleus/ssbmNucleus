# Mr. Game & Watch — effects (MAP-STATIC)

**Verdict: NOTHING colorable in the ptcl-operand extras framework.**
G&W ships **no `Ef*.dat` effect file at all**, and none of his moves spawn
particle effects. There is no `kirby_probe.json`-style probe because there are
no ptcl color operands to poke.

## Why there is no Ef file

1. **No `EfGw*.dat` exists** in `storage/test-base/files/` (verified: the only
   `*Gw*` files are `PlGw*.dat` fighter data, `GrTGw.dat`/`GrOp` stage,
   `GmRstMGw.dat`, `TyGW*` trophies, and the two Kirby-copy files
   `PlKbCpGw.dat`/`PlKbNrCpGw.dat`). `PlGw.dat` has **no effect table** (fails
   the `ptcl_parse` header check — it is pure fighter data, not an Ef file).

2. **No `efSync_Spawn` / `efAsync_Spawn` / `efLib_Create*` anywhere in
   `ft/chara/ftGameWatch/`.** All 5 specials (`ftGw_SpecialN/S/Hi/Lw`) and his
   normals (`ftGw_Attack100/11/AirLw3/S4`) drive **item articles**, not
   particles. The only effect-ish flags found are `Ft_MF_KeepGfx` motion flags
   in `ftGw_SpecialLw.c` (state bookkeeping, not a spawn).

3. **His "effects" are physical ITEM models,** each its own item DAT with a
   flat-shaded model + texture — verified zero `efSync/efAsync/PrimitiveColor`
   calls across every `it/items/itgamewatch*.c`:
   - `itgamewatchchef.c` / `itkirbygamewatchchefpan.c` — Chef food (side-B)
   - `itgamewatchjudge.c` — Judge number/hammer (down-B "Judgement")
   - `itgamewatchturtle.c` — turtle (up-B rescue)
   - `itgamewatchparachute.c` — parachute (up-B)
   - `itgamewatchfire.c` / `itgamewatchbreath.c` — Oil Panic fire / breath
   - `itgamewatchmanhole.c`, `itgamewatchgreenhouse.c`, `itgamewatchrescue.c`,
     `itgamewatchpanic.c` — misc articles

## Consequence for the extras system

The color-effects extras system recolors **ptcl `CF/DF` operands** in `Ef*.dat`
banks. G&W has **none** — his visuals are item-DAT model/texture assets
(famously flat 2D-shaded). There is nothing for `effect_probe.py` /
`extra_types.py` to target. **Honest verdict: G&W is texture/model-only; no
effect-color extra is shippable for him.**

If a future non-ptcl path is built (item-DAT material/texture recolor, like the
texture-pack path), G&W's articles (turtle, fish, parachute, judge number,
chef food, fire) would be the targets there — but that is out of scope for the
ptcl-operand extras campaign and does not belong as an Ef layer.

## Open leads (out of this campaign's scope)

- Generic engine hit-sparks on G&W's attacks come from the **common effect
  bank** (grp9/grp3 composites), not from G&W — those are the shared
  `EfCoData` territory already quarantined in `efcodata.md`, and recoloring
  them would affect every character, not G&W specifically.
- The Judge "9" flash and Oil Panic fire are the most visually distinct
  candidates for a hypothetical item-texture recolor path.
