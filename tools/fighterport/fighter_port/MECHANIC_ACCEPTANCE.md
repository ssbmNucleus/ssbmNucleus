# Rivals mechanic acceptance — 2026-11-14

This pass completes the identified Ranno and Loxodont mechanic adapters and the
shared support needed to build them through the ordinary port command. It does
not claim exact source-game parity or exhaustive roster certification.

## System changes

- Attack-scoped custom source conditions retain their source prerequisites.
  The same state plan drives clip allocation and native code generation.
- Explicit adapter animation slots take priority over donor placeholders;
  conflicting explicit owners fail instead of silently replacing a phase.
- Shared native helpers cover bounded resources, projectile fans, swept
  tongue/bubble contact and damage-driven item batting.
- Ordinary packages carry a mechanic inventory in `port-implementation.json`
  and `PORT_NOTES.txt`. Compiled source branches, article triggers and custom
  conditions add obligations. Unknown obligations remain unfinished; declared
  handlers must actually be built. This is implementation coverage, separate
  from gameplay evidence.
- Calibration remains a developer activity. Users import the ordinary package
  without running a source-game or Dolphin harness.

## Native checks

Both characters were tested against Marth on Final Destination in owned,
isolated offline Dolphin sessions. Trial setup moved fighters and routed the
controller; attacks, damage, capture, article collisions and recovery ran in
the native engine. Resource values, damage and hit callbacks were not forged.

Ranno's final package has 26 custom states and five article types:

- The spin fan hit Marth with actual projectile damage, then expired cleanly.
- The travelling strong-attack palm hit Marth for 5% beyond the body-hit range.
- Jab three entered rapid jab. Holding A sustained the loop and further hits;
  releasing A played recovery and returned to Wait.
- A tongue cast from outside the left ledge caught the stage, entered sling,
  launched upward and landed safely onstage. A floor-anchor trial also returned
  control without throwing Ranno offstage.
- Tongue contact with his own bubble consumed it and launched Ranno upward;
  the move recovered and left no article behind.
- Tongue contact with Marth dealt 1%, created the capture bubble, and eventually
  released Marth. Both fighters returned to Wait and the bubble was removed.

Loxodont's package has 26 custom states and six article types:

- Side special captured and released Marth for 12% on the unstaled trial.
  The slam created a pool and supplied a molten charge.
- An uncharged boulder bounced and became a pool. Owner pickup supplied a
  charge; a powered forward strong then hit Marth with both the body attack
  and its separate aftershock. The aftershock expired.
- Holding neutral B produced charge 1.0 and a faster projectile than the
  uncharged cast. Marth standing on an unprotected pool extinguished it.
- Three slam pickups followed by down B with shield held selected the base
  branch and spent one charge. The following ordinary down B selected the
  two-charge branch; another down B selected the empty branch. Each recovered.
- In the final build, Marth's forward smash hit an incoming uncharged boulder.
  The projectile reversed from leftward travel to rightward travel, charge
  increased from 0 to approximately 0.679, and horizontal speed increased from
  1.5 to approximately 5.253. Marth remained at 0%. The subsequent cleanup
  trial left no article behind and both fighters returned to Wait.

## Verification and evidence

The full regression run passed 842 tests with six skips. The final focused run
passed 24 tests. Native-module and helper tests cover the final hurtbox registration correction,
resource cap/spend/reset, interruption, one aftershock per attack, source
conditions, slot allocation, coverage reporting, fan scheduling and geometry.
Ranno's fighter plus five items and Loxodont's fighter plus six items link
against the actual MexTK headers/toolchain.

Ordinary package generation and generated-file verification were used, including
memory admission for mirror matchups on Pokemon Stadium. Resident effect images
were reduced after that check exposed a heap-budget overrun.

Local evidence is under the app's `app/scratch/source-calibration/shared-timing/`:
`ranno-mechanics-trace-v2/history.json`, `lox-mechanics-trace-v3/history.json`,
`lox-mechanics-trace-v5/history.json`, and `lox-mechanics-trace-v6/history.json`.
The final ISOs were `ranno-complete-specials-v2.iso` and
`loxodont-complete-specials-v6.iso`. The histories retain failed setup
attempts as well as successful trials. Intermediate ISOs may be removed;
the final importable packages are under `app/scratch/rivals2-ranno/package/`
and `app/scratch/rivals2-loxodont-system/package/`.

## Explicit limits

Fan pattern, sling launch/drift, boulder strength scaling and several compiled
triggers are documented Melee adaptations. Article art is geometric where the
source effect is unavailable. Source timing and cosmetic fidelity remain
separate polish work.

Ranno's pre-existing poison limits remain explicit in his package: source
status visuals, shield/parry contacts, projectile cleansing and persistence
after the source owner's death. Those behaviors are not certified by this pass.
Both packages have no unclaimed obligations in the currently reviewed mechanic
inventory; that does not prove that every source mechanic has been discovered.
