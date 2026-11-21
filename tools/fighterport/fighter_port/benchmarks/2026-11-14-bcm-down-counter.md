# BCM held special and paid counter — 2026-11-14

This implements part of BCM's custom specials and exercises reusable porting requirements.
It is not completion of BCM or the port system. Harnesses remain developer calibration tools.

## Source and implementation

The installed Slap City Assembly-CSharp.dll and the normal reader's retained `source_programs`
are the source, including CTCompareFloat, CTInput, SmashCharacter, BCManCC and combat armor handling.
CTCompareFloat uses Less/EOLess, not Smaller/EOSmaller; the shared expression compiler is corrected.
Optional explicit CTI compilation preserves nested conditions without assuming buffer semantics.
Unbound input predicates still fail. The counter accepts only the supported one-update Attack/Special
Down predicate, with the source SpecialFromFrame blocker, cash comparison and incoming-hit condition.

`spd` registers unlimited armor at update 8, a counter gate at 13, and a repeating 16-update timer
at 21. The first release check is 37. Five held rewinds precede release at 117; recovery lasts 25
updates (end 62 for early release, 142 for full hold). These updates use a separate clock from the
rewound clip and pause naturally with native hitlag. Source cancellation clears the hurt multiplier.
The source's SADeleteAction removes registered listeners, not ordinary move recovery.

Native unlimited armor uses Fighter x2220_b3 (byte +0x2220 mask 0x10). `ftCo_8008EC90` suppresses
reaction without suppressing damage or hitlag. `Fighter_ChangeMotionState` clears it, so same-move
rewinds and ground/air transitions reapply it. The boss-only `no_reaction_always` path is invalid for
ordinary fighters. Native finite armor subtracts knockback and is not claimed equivalent to Slap's
all-or-nothing threshold armor.

The paid down counter consumes the retained ordered payment/clamp only after the full guard passes.
It has separate ground/air states sharing validated neutral hit geometry: 6 damage, angle 55,
active updates 9–12, intangible through 16, normal hurt status at 17, full end at 27. Entry velocity
is multiplied by .3 and air gravity by .6, with no ordinary air drift. Same-move ground/air handover
keeps active hitboxes, hit logs, fastfall and script hurt status. Ordinary neutral uses the same
movement/recovery with its own angle and without counter intangibility.

## Native evidence

MCP solo match, BCM P0 and a human-neutral Marth P1, Final Destination, 14 units, no bag pin or CPU.
For a reproducible incoming jab, temporarily route Marth's StaticPlayer+0x48 and Fighter+0x618 to
pad 0; both are restored afterward. Input takes the normal fighter pipeline, with no forced attack
states, damage events, or counter-hit flag writes.

`bcman-down-v1.iso`: armor byte 00 at 7, 10 at 8 and 36, 00 at 37. Early release stays in the
special through 61 and enters Wait at 62. Holding B rewinds at 37, remains armored, releases at
117, stays in recovery at 141 and enters Wait at 142. Air hold remains armored while airborne.
Marth's actual jab deals 4 damage and 2 remaining hitlag frames, while BCM remains in the down
special with no displacement; cash becomes 37 (5 + 8*4), confirmed in RAM and the native HUD.

`bcman-counter-v1.iso`, SHA256
`df79e770c6dd014f006da554d129c5ce353bff94c00a5d9578e02eff1b16f10c`:
after the same real jab, an Attack press at 37 cash is rejected. Cash alone is then seeded to 237
for the threshold trial. A fresh Attack press enters state 381 at animation 1, spends 200 to 37,
sets script hurt status 2 and clears armor. At counter frame 9, Marth takes 6% and enters DamageN3;
cash becomes 87. Both the attack and victim's damage log have angle 55. Marth is free to react/move.
Script hurt status is 2 at frame 16 and 0 at 17. Recovery remains locked at 26 and enters Wait at 27;
cash stays 87. A separate air-neutral boundary probe sets only position/vertical velocity to land
on active frame 12: ground state 373 retains its hitbox, which clears correctly at 13. No hit or
action state is forced in this landing test.
An air down-special held through update 55 lands in its ground state and keeps armor active,
with the loop clock continuing rather than restarting on landing.

Raw local evidence is in `app/scratch/source-calibration/shared-timing/bcm-down-native-v1.json`
and `bcm-counter-native-v1.json`; screenshots are in `app/scratch/mcp/20261113-170934/`:
`bcm-down-v1-after-armored-jab.png`, `bcm-counter-v1-contact.png`.

## Checks and remaining work

Generated C tests cover the hold/release clocks, armor cleanup, external interruption, both form
handovers, cash/contact/fresh-input guards, ordered payment, ordinary-vs-counter properties,
intangible/end boundaries and all six source comparison operators. Changed buffer/input shapes
are rejected. Required suite: 679 passed, 6 skipped. Normal driver/sounds/build/verify succeeds;
the verifier still reports the uncompleted gameplay/visual checklist rather than marking it done.

Open: source stun and shield-damage multipliers; SELL/BUY and armor/firetrail/spark visuals;
source movement calibration beyond the converted native walking attributes; up/side specials,
up/helpless counter entries, throws/taunt and remaining resource paths. Ranno's victory capacity,
native material curves and custom specials also remain on the active implementation list.
