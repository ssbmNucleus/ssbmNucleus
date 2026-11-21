# Ranno neutral and shared Rivals reader corrections

Source: installed Rivals 2 1.7.5 (30985), executable SHA-256
`5fa30a728fb75aa1e703c4b3f7447154b7bd8e7cf449b3222ce291ec711a57c1`.
Offline Training, Ranno P0 and Olympia DUMMY P1, Hodojo. All attacks were entered through
normal P0 input; no attack states, projectiles, damage or poison were seeded. Native results below distinguish observed gameplay from compiler checks and remaining gaps.

## Source observations

The optional finite capture tools restored inputs and pause on every completed case. Evidence
is under the local `source-calibration/shared-timing` folder. A failed initial inventory in
`ranno-neutral-darts-source.json` produced no input updates and detached; it is not accepted evidence.

* `ranno-neutral-release10-source.json`: hold 1..10, release 11. Throw startup 11, active 13,
  recovery 20, idle 51. Real needle contact at 23 adds 1% and PoisonStack1 to Olympia.
* `ranno-neutral-release90-source.json`: charge stages at 9,33,57,81; release 91. Active93,
  recovery100, idle131. Contacts103/105 add two separate poison stacks and 2% total.
* `ranno-neutral-ammo-source.json`: hold130, release131. DartsStored advances1/2/3/4 at
  stages9/33/57/81 and remains4 after a complete full-charge loop. Emission decrements at
  133,135,137; counter clamps at1. Three real contacts raise damage3->6 and cap visible poison
  at four separate stack entries. Poison does not passively tick during the observed idle tail.
* `ranno-neutral-darts-native-source.json`: four actual server-owned articles first appear
  at93/95/97/99, each NumDartsThrown4. Velocity magnitude45cm/update, directions0/7/14/21deg.
  Spawn position is the attack's offset plus100cm along the dart's direction. Hit count is
  not used to infer projectile count.
* `ranno-air-neutral-darts-source.json`: full hop, charge on7; lands on Hodojo's platform
  at42 while releasing. The subsequent volley is GROUNDED. This demonstrates a preserved
  charge across landing; it does not establish aerial projectile directions.
* `ranno-double-air-neutral-darts-source.json`: full hop then a real double jump, charge
  21..55, release56. Two airborne darts appear58/60, velocities(31.8194,-31.8194) and
  (35.4605,-27.7052): -45deg and -38deg. The extra spawn offset is again100cm along flight.

The article observer is a session-local read-only extension of native status. It enumerates
live authoritative-world RivalsArticleEntity objects on the game thread, reads SDK-pinned
velocity/window/NumDartsThrown fields, and uses Actor.K2_GetActorLocation. Each input update
still requires exactly one simulation frame and one P0 input-hook call. Installed game files
and Steam settings are unchanged; Steam remains offline.

## Corrections carried by ordinary ports

`made_articles` no longer invents a frame-one spawn for an empty CreationWindowStringTableKey.
It retains the declaration with `trigger: compiled`, `real: null`, and its complete source row.
Named windows retain their actual scheduled frame. This applies to every Rivals fighter.

The reader discovers separate NspecialAir/FspecialAir/UspecialAir assets before exporting
fallback air clips. Separate attacks own their timing, cancels and articles. Shared attacks
use the actual declared AerialAnimation, including their conditional branches, and recompute
hit geometry against that animation. Ranno's real aerial neutral recovery is24 frames rather
than the ground's31; its air acceleration and projectile offset also differ. Normal export
now produces55 move paths (previously47).

`own_windows.release_loop` validates a contiguous held path, an explicit final loop, complete
unguarded SpecialReleased windows, and a finite separate release branch. It refuses unsupported
guards or timer preservation. `own_template.build_plain` allows custom modules to retain only
the still-plain specials without substituting text in generated C.

Ranno's first native adapter consumes that plan plus exported compiled emission rules. It loops
full charge, releases in current-input IASA, emits one to four native items two updates apart,
and has separate ground/air recovery. Its aerial drift uses the source override; charge landing
preserves its phase. Needle damage/knockback/size/lifetime come from the article asset. Its simple
needle picture is an explicit geometric stand-in for Niagara rendering.

## Native checks on the normal rebuilt disc

Ranno against a human-neutral Marth on Final Destination, using normal input. Hold10/release11
enters throw on11, emits on13, remains in recovery on50 and returns to Wait on51, matching
the source release case. Real needle contact gives Marth1% and DamageLw1. The first native
needle originally appeared4.5 units ahead: Melee integrates a newly created item on that
same update. Compensating only that first integration gives an observed initial relative
position(19.999996,5.0001), velocity(4.5,0), matching the source(200cm,50cm) at0.1 units/cm.

Hold130/release131 emits four actual items; velocities match0/7/14/21deg and recovery ends
on171. A full-hop release emits an airborne item at-45deg. Landing during aerial throw enters
LandingFallSpecial. These observations establish count, direction, contact and the measured
ground recovery; they do not establish poison, stored charge, isolated full aerial recovery,
or all ground/air transitions. The aerial birth-position correction still needs a live check.

The normal driver, sounds, firstdisc and verifier pass (0 FAULT). The tested disc's sound bank
matches the refreshed package byte-for-byte except its installed sound-ID base at bytes12..15
(0x5ff versus package0), which m-ex assigns during installation. Required suite:712 passed,
6 skipped; focused Ranno/continuation tests:11 passed, including real MexTK compilation.

## Complete source victories in bounded demo clips

The shared demo builder now preserves the whole389-frame source victory using six clips,
without widening the retail45,056-byte buffer. The largest is44,640 bytes; each sampled
game-frame error is below0.005 rig heights. All three Ranno victory entries have identical
source animation, material opacity and emitted sound scripts, so they share the five-row tail.
Sharing requires identical playback data; different sounds or opacity must retain separate tails.
The route also retimes faces, opacity and sounds to the actual segment, with boundary sounds
emitted only once. Donor wait-row loop flags are removed and a demo-only callback advances
at the segment boundary, preserving residual time.

An owned Dolphin results-screen check entered demo row2 and reached row8/frame69, the end of
source frame389; it held there while the emulator advanced59 more frames. Slippi's Salty Runback
skip was adjusted only in that owned session's RAM using the existing results_probe procedure.
The session was closed afterward. This accepts continuation control, not visual presentation:
the final fighter is partly above the camera. The source animation's retained body motion and
results framing need further work. Segment128..192 also has a reported between-frame error
of0.06906 rig heights, which is not covered by the sampled game-frame bound.

## Open work

Poison's active behavior, storing/canceling charge, source visuals and the other three specials
are incomplete. Victory framing and between-frame interpolation are open. The shared material reader now resolves cooked master defaults and elemental color parameters;
packed RGB masks retain color when their unused alpha is zero. The normal rebuilt disc shows a
green sash in `app/scratch/mcp/20261113-170934/ranno-rgb-mask-fixed-native.png`. The flat bake is
an explicit approximation of the source shader. Zetterburn's five materials exercise the same
reader. A separate source-camera trial follows the timeline but has incorrect framing at source
frames 152, 192 and 389; those screenshots do not accept camera parity.
Neither a passing compiler nor this limited native acceptance establishes complete gameplay parity.
