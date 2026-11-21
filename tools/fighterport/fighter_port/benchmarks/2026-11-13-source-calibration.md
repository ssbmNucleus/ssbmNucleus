# Source runtime calibration, 2026-11-13

This is developer investigation, not a new requirement for users or every port. Calibrate the readers and
port implementation with representative mechanics, then keep the correction and focused regression tests
in the normal code. Neither preflight nor the checklist was changed by this work. A clean verifier does
not resolve the runtime discrepancies below.

## Slap City: observed, including another character

The new `fighter_port/harness/source_games/slapcity` adapter uses real controller states, the game's normal
simulation update, and native screenshots. Each case starts a fresh offline Training match on Flatville.
The opponent is Ittle Dew with human neutral input, free to move under knockback. Incoming-hit cases send
Ittle's jab through its controller. Both actors start grounded, idle and at zero damage. Damage resets on
landing are disabled during capture and restored afterward.

26 scenarios were collected: 15 solo special cases and 11 contact cases, including early/full charge,
incoming jab, Flex trade, and interruption after wave creation. Two independent neutral solo runs had
identical initial states and all 60 samples. The harness also checks that wall-clock waiting leaves the
frozen simulation unchanged and that each commanded update produces exactly one game update.

The final session 08 build repeated neutral contact and the interrupted-wave case in Steam Offline Mode
with the same reported timing/damage. A deliberately expired 600-update request stopped after two updates,
returned an explicit incomplete-capture error, and restored control (`frozen=false`). The bridge was
detached and the game closed afterward. These two repeats do not add new scenarios to the count above.

Frame numbers below count submitted simulation updates starting at 1. The game's action frame is recorded
separately and starts at 0 on entry. Hitstop can extend action duration without advancing its action frame.

| Probe | Observed source behavior | Implication for calibration |
|---|---|---|
| Neutral hit, Ittle 1.5 units ahead | Contact on input frame 2, 4 damage; idle on frame 41. Solo idle is frame 36. | Distinguish hitstop from recovery timing. |
| Up hit, Ittle 1.3 units ahead | Contact frame 9, 12 damage; source special fall starts frame 50 on hit versus 41 on whiff. | Compare identical contact conditions. |
| Side run then strike | At 9.5 units, contact frame 36 for 12 damage. At 7 units, the tested strike misses. | Preserve the close-range miss; do not silently reposition a target and call that parity. |
| Down tap, Ittle 3 units ahead | Independent Shockwave00 appears and hits on frame 7 for 10 damage; hitboxes disappear frame 13, object frame 37. | The object lifetime is distinct from its damaging lifetime. |
| Down held 300 updates | Shockwave05 hits on frame 306 for 40 damage; Fish returns idle on frame 366. | Charge and release input duration must be explicit. |
| Incoming jab while charging for 60 updates | Fish takes 2 damage on frame 64, enters hitlag then flinch. | Early charge does not protect against this hit. |
| Incoming jab after 1,200 updates of charge | Fish takes 2 damage on frame 1204, remains in `spd` through hitstop; hurtbox armor is -1. | Positive control: late charge resists interruption while still taking damage. |
| Incoming jab during Flex startup/active transition | Both tested timings interrupt Fish; active timing trades for damage [2, 4]. | The port's claimed initial Flex armor is not confirmed by these observations. Investigate before changing it. |
| Incoming jab after wave creation, Ittle 1.5 units behind | Wave appears frame 7; Fish is interrupted for 2 damage frame 9; wave hits Ittle for 10 on frame 10. It persists until frame 37. | A body-owned hitbox stand-in cannot reproduce this independent article behavior. |

Solo coverage also includes air neutral/down, side reversal/jump/down+B, vertical and both steering choices
for up special, and down holds of 1, 60, 300 and 1,200 updates. Simultaneous down+B during the run selected
the side strike in this test; a pre-held down input still needs checking. Do not infer that the source has
no down-special branch from that one input timing. No claim of complete special coverage or parity.

## Melee smoke captures

Using the existing isolated Dolphin harness and the owner's `All Ports Test 1.iso`, Fishbunjin (external
ID 0x1B) was captured through all four specials. Neutral, up, and down also hit a stationary Marth target.
These prove the tested interactions execute on the disc. They are not a matched source comparison:
the source target was Ittle, canned input holds differ, and a reused Melee target was still recovering
from a prior move. A fresh match per comparison and equivalent explicit input streams are still needed.
No port or ISO was rebuilt during that initial calibration round.

The initial implementation used body-attached down-special hitboxes and omitted independent object/visual
behavior. The interruption trace demonstrated why that approximation changed gameplay, not only appearance.
The correction below replaces it. The Flex
armor assumption needs a separate controlled timing sweep and inspection of the source's effective
defense rules. Do not remove armor just because a pose looks interruptible or assume the existing comment
is the runtime truth.

## Down-special correction and native validation

`own_fishbunjin_wave.py` now makes independent native items. The reader follows the custom call's pointer
arrays through ProxyUpdater to its tweens, preserves each Transform's full parent TRS chain, and associates
motion with its actual track. The old read omitted that motion, nonuniform scale and parent rotations.
The uncharged left/right tracks move by 1/3 source unit per update; the strong tiers include diagonal
tracks that were previously collapsed into the horizontal pair. The look shortcut's prefab scale also
makes the spawn offset **2.3 source units**, not its untransformed local offset of 2.0.

All eight charge tiers carry their attack duration and 30/120/180-update object lifetimes. The seven-box
tiers use two items with a shared native hit-exception ID (SpawnItem+0x40 / ItemData+0xAC4) and hit group.
Melee's `it_8026FAC4`, `it_8026FC00` and `it_8026FCF8` synchronize their target history during collision
resolution; no new collision hook is installed. `items.set_script` now accepts an explicit `group` while
retaining its existing default multihit behavior. Contact clears the wave's own hitstop request, matching
the source's zero self-hitlag, without changing the victim's native hitstop.

The live iterations caught two further timing bugs. Release handling in Anim saw the previous update's
buttons, so it moved to IASA. Release now produces the wave five updates later and recovery 65 updates
later. Item script priming also cleared the hitboxes before the last part of the sampled sweep; the item
callback is now the sole clock for hitbox removal and destruction. Charge uses single-precision seconds
like `spd_charge`, rather than rounded frame thresholds: 1,200 additions of float32 1/60 total about
19.999866, so that boundary still selects the 10-second / 50-damage tier, as observed in Slap City.

Final isolated Melee build: Fish external 0x1A, human-neutral Marth target on Final Destination. This is a
mechanic comparison, not identical fighters, hurtboxes, physics or visual effects across games. Frame
numbers below are the harness's move-frame labels; article age starts at zero on creation.

| Check | Final observed result |
|---|---|
| Fresh tap | Appears and hits for 10 on frame 7; active through frame 12; inactive on 13; object absent on 37; Fish idle on 67. |
| Sweep | Last active centres relative to wave origin are ±8/3 source units, with the previous centres ±7/3. Native radius quantization is under 0.002 Melee unit in this case. |
| Incoming jab, Marth 11 Melee units behind | Fish is in DamageN2 on frame 8 while Marth remains at zero damage. The wave hits Marth on frame 9, with Fish still interrupted. |
| Independence | Another incoming-hit run moves Fish to x=3.625 and flips his facing; the wave stays at x=10.5075, continues its own clock, and clears its hitboxes. |
| Held 1,200 updates | 50 base-damage tier appears on frame 1206; Fish idle on 1266; article alive at age 119 / frame 1325 and absent at age 120 / frame 1326. |
| Strongest tier | Seven live boxes across two items, same native exception ID and hit group; active at ages 0 and 5. One contact, unchanged target damage through the sweep. Both remain at age 179 and are absent at 180. |

Repeated cases retain Melee staling. Examples: the delayed jab/wave deal 3.64/8.30; the 1,200-update wave
has base damage 50 and applies 38; the final strong wave has base damage 150 and applies 105 exactly once.
The jab stimulus is a one-shot call through the target's IASA slot to vanilla `checkAttack11` (0x8008ABC0).
The engine replaces it with normal Attack11 IASA (0x8008ACD8), verified by readback; no CPU was enabled.

The long strongest-tier run preserves a pre-spawn sample showing a one-update delivery discrepancy in
the pipe-input sequence. Marth also respawned during the hold and was placed grounded and idle at x=14.6
before spawn. That run establishes geometry, one-hit behavior and article lifetime, **not** exact release
timing. Future exact controller comparisons should acknowledge button transitions from sampled inputs.
Its seven-box geometry is source-prefab-derived and native-tested; full-charge source visual parity is not
claimed. Turning fighter debug draw off after creation leaves the copied item overlay visible in that
run's two PNGs; they are diagnostic views, not clean effect previews.

The expanding ring remains a visual stand-in. Source particles/FX audio, charge glints, camera shake and
the source's wall-clipped spawn placement are still incomplete. Other specials, Flex armor and general
knockback/hitstop equivalence need their own calibration. No user harness requirement was added.

Local evidence: `app/scratch/source-calibration/fix-wave/melee-wave-accepted.json`, plus earlier failed
iterations `melee-wave-first-build.json` and `melee-wave-second-build.json`. The test ISO is
`app/scratch/slapcity2-cold/tmp/first.iso`; source/generated-file hashes are recorded alongside the evidence.
The user's Desktop All Ports ISO was not overwritten. All owned Dolphin sessions were closed afterward.

Validation: native item/fighter code compiled, rebuilt ISO, verifier **0 FAULT**. Focused reader, item and
route regressions: **95 passed, 1 skipped**; the last wave-specific run was **26 passed**. An attempted
broader collection including the unrelated experimental `test_source_item_events` failed on a
`shared.modellab.rig.load_visibility` import; no changes were made to that rig work or the Dolphin harness.

## Fishbunjin Flex: armor and aerial motion calibrated

Session 09 repeated neutral Flex and a seven-case Fishbunjin/Ittle Dew timing sweep, each in fresh
offline Flatville Training. Delay means Flex input frame minus jab input frame. Delays -1, 0 and +1
let Flex hit Ittle for 4 before her jab hits. At +2, both hit on update 4 (Fish 2, Ittle 4), and Fish
enters flinch after hitstop. At +3..+5 the jab interrupts before Flex enters. All eleven Fish hurtboxes
show zero armor throughout the opening Flex frames. A repeat through the portable sweep reproduced +2.

The raw `spn` script explains this: its armor action is inside `CTM None`, excluding both
`grounded == 0` and `grounded == 1` (also kneebend/tumble). It is unreachable for normal ground/air
play. The reader already leaves conditional armor out, but the own module had hardcoded it back in.
That override is removed. The reduced conditional fixture and generated callback checks guard the fix.
Deep Breath is a positive control: a fresh held-charge source run takes 2 damage from Ittle's jab,
keeps `spd`, and reports armor -1 on all hurtboxes instead of entering flinch.

Fresh aerial neutral/right/down traces also found two connected errors. Source entry (`moveFrame 0`)
finishes the previous jump movement; frames 1..3 repeatedly reset speed before gravity, producing
`vy = -0.8333334` source units/second. Frame 4 accelerates to `-1.666667`. Right/down holds have the same
positions and velocities as neutral input: `allowMovement 0` blocks drift and fastfall. The old port
reset once on entry, then used ordinary aerial drift/fastfall; holding right moved it 1.04694 Melee
units by port frame 6. Flex now has a dedicated physics callback with the observed reset window and
locked air controls. Ground/air handover still uses the existing collision callback.

Final native checks used Fish external 0x1A and a human-neutral Marth on Final Destination:

| Check | Observed result |
|---|---|
| Incoming jab | Fish at x=0, Marth at x=16. Jab input update 1, Flex update 2; on update 4 Fish takes 4 and enters DamageN2, with no Flex armor. |
| Air reset | Port frame 1 retains upward speed. Frames 2..4 each have vy=-0.0634511; frame 5=-0.1269021, frame 6=-0.1903532. These correspond to source moveFrames 1..3 and subsequent gravity acceleration. |
| Right/down holds | At sampled port frames 1, 2, 4, 5 and 11, both exactly match the neutral native positions and velocities. |
| Charge protection | After 1,200 additional held updates, Deep Breath has armor 4322. A jab on release update 4 deals 3.64 with staling, but Fish stays in Deep Breath through hitstop and emits the wave. |

The native jab uses ordinary A input, briefly routing the harness controller to the target via
`Fighter.pad_index`, then restoring both mappings. No CPU, forced attack state or position pin is used.
The native charge check covers early release armor; the source positive control covers held charge.
Different opponents, jump setup, spacing, damage and hitstop prevent a claim of complete cross-engine
parity. Native raw-input `move_frame` is the previous recipe's running counter; action/animation frame
and case labels identify timing. An earlier native contact produced a zero-damage hitbox clash, and
another began with Marth in a get-up attack; neither is accepted armor evidence.

Local evidence: `evidence/flex-contact-09/`, `flex-portable-09/`, `flex-air-09/`,
`flex-air-controls-09/`, `flex-charge-control-09/`; native observations and executable assertions in
`fix-flex/melee-flex-accepted.json` and `fix-flex/verify_evidence.py`, with fingerprints alongside.
Final ISO SHA256: `a1b97ba41f9a5ccbac326386c71a30c7167165c717cea4cfad9d28891614c773`.
The intermediate armor-only ISO and failed setups remain identified in the evidence. The final
generated native code compiled, the rebuilt disc passed the file verifier with **0 FAULT**, and
focused own-Fish/wave/source-calibration/checklist tests passed **56 tests**.

The optional `slapcity.flex_cases` timing sweep and two air-direction scenarios retain this calibration.
They add no user requirement. Flex jump/up-special cancels and reversal, side-special follow-up choices,
clank behavior, remaining FX and general hitstop/knockback equivalence still need calibration.

## Bunjin Bull calibration checkpoint

This closes the current Fishbunjin investigation. Remaining work is a backlog, not a prerequisite for
moving on to another game's reader. No user harness requirement was added.

Source probes found that current follow-up input must be handled in Melee's IASA callback; Anim sees
the preceding input. Ground up-special now enters Bell Ringer on input update 31 instead of staying
in the run and incorrectly slapping on update 32. Air up-special consumes an available jump for one
update before Bell Ringer; with the jump spent, it slaps. Ordinary ground and air jumps remain available.
The special-plus-down prose was incorrect: down selects slap. A separate buffered neutral/up-flick
Flex branch remains unimplemented.

Run entry applies dash speed before later acceleration. Source braking is applied once after script
acceleration. Opposite horizontal input requires the default Far threshold (0.8): facing turns immediately,
while momentum continues forward, brakes to zero, then reverses. The old implementation reversed velocity
immediately and accelerated on entry. Native ground run x at update 30 is 19.238071, matching the scaled
source trajectory; the old build reached 21.69992. Startup/slap braking now uses the source values too.

Final native checks: ground up enters state 380 on input update 31; air up enters 385 with jumps used 2,
then 381 next update with zero velocity; a spent air jump selects 379. Reversal retains forward movement
on the turn update, reaches zero, then moves backward. A normal B follow-up hits human-neutral Marth at
x=40 for 12 damage on slap animation frame 6; damage stays 12 after twelve more updates and Marth moves
under knockback. No CPU or forced special action was used.

Local accepted evidence is `fix-side/melee-side-accepted.json`, source `evidence/side-final-10/`, and earlier
direction/threshold cases in `side-controls-09/`, `side-controls-more-09/`, `side-steering-09/`.
Session 10 records raw jumpsSpent 1 -> 2 for the hop and 2 -> 2 for the no-jump slap. Native reversal
includes an extra light-tilt update before full reversal; compare relative turn onset. Native no-jump setup
consumes a jump from a preceding run, so the full source/native input streams differ. Marth and Ittle Dew
also differ. These are targeted mechanic checks, not complete cross-engine parity.

Two Windows file-sharing faults were reproduced during source collection. The client now retries reading
the same UUID response within its deadline; the bridge retries only before a request has been consumed.
Session 10's request-lock check retained freeze while the request file was locked and executed exactly
one update after unlocking. Failed/incomplete session 09 batches are retained and superseded by session 10.

Final side-patch ISO SHA256: `d340f90982874563b78f3ff84b92be581780f7afe6cfadf1d91c8c7c1e4aa1be`.
Native compilation and disc verification passed (0 FAULT). The Desktop All Ports disc was not overwritten.
Remaining Fishbunjin work: Flex cancels/reversal, buffered run-to-Flex input, honk, clank, wall-clipped wave
spawning and visual/audio fidelity. Next calibration target is Rivals 2 input and combat observations.

## Rivals 2: idle snapshots and native frame advance checked

Rivals 2 ran in Steam Offline Mode as a guest, version `1.7.5 - 11-06-2026 - 30985 - [release]`.
Executable SHA256: `5fa30a728fb75aa1e703c4b3f7447154b7bd8e7cf449b3222ce291ec711a57c1`.
The accepted setup is visible local Training Room gameplay, human Zetterburn versus Ranno CPU DUMMY.
The dummy supplies a neutral target; no attack, hit, or input replay is yet accepted.

The initial observer incorrectly expected a single simulation world and dereferenced
`CachedCharacterDefinition`. Actual Training contains client and server worlds with the same name;
the cached character pointer is null. Native `TrainingSubsystem.GetGameState` follows the local
SnapNet server, so the observer now follows that exact pointer chain and filters actors by world identity.
It reads `LastAppliedCharacterName` for character identity. Class/ownership/uniqueness checks remain.

Live evidence in `rivals-control/session-07/observer-frame-check.json` records frames **1388..1393**.
The initial read agrees with native `GetGameplayFrame` and `GetGameState`. Five advance requests each
produced exactly one new gameplay frame; each pre-step frame stayed unchanged over a 0.5-second interval.
At frame 1393 the visible HUD matched Zetterburn **Idle 256 / window 0 timer 256** and Ranno
**Fidget1 21 / window 0 timer 21**. Both were grounded with zero damage, hitpause and velocity.
This validates the idle/fidget identifiers and timers; zero values do not establish combat field scales.

A local, build-pinned C++ probe calls native Training controls on the selected game's message thread.
`SetAllowFrameAdvance(true)`, `ToggleFrameAdvance(true)` and `AdvanceFrame(true)` reach a settled
single-step state; UI flags alone did not. The observer now requires SnapNet active/enabled flags and
no pending step, and rechecks the frame, controls and complete server-world chain after sampling.
The step call returns before simulation advances, so its response alone is not completion evidence.
Release was checked to resume gameplay; the prototype later released and unhooked on inactivity.
Its manifest records bridge SHA256 `88f2fd3b499ab35c4156afc3b757631777c0a43701f93425116379f772ba09f0`
and source SHA256 `e0d9a4b0698b87ad0a6cb0cbd579dc66bc610621d377c394cfcfe2e81e1eadf3`.

Setup failures are retained separately. Calling `SendReadyToStartMatchMessage` directly bypassed the
normal selection transition and produced black gameplay; those captures are rejected. Native
`CharacterSelectScreen.OnMidButtonClicked(0)` followed by normal stage selection produced visible
gameplay. The raw `assetsLoaded` flag was zero in that working match, so it is not a readiness test.
Session 04's black-world frame checks and session 07's earlier client-world snapshot are exploratory,
not accepted gameplay baselines. No live `RivalsAIController` was present in the dummy setup, so that
class's input setter is not yet a usable input path.

Only the corrected read-only observer is committed. The local control probe is not ready to ship:
controlled inputs and abnormal server-exit cleanup need work. The observer still uses query/read rights,
requires `--experimental`, and labels output `experimental-partial-training-calibration`. Nonzero damage,
armor, hitstop, charge, velocity units, attack windows, projectiles and incoming hits remain unvalidated.
No Rivals port behavior or full parity claim follows from these idle checks. Steam remains offline.

Focused source-calibration regressions: **36 passed**. Added cases distinguish same-named client/server
worlds, reject missing/ambiguous/foreign server contexts, reject unsettled single-step flags, preserve
character identity without the cached definition pointer, and discard a world change during sampling.

## Local evidence and provenance

Scratch root on the development machine: `app/scratch/source-calibration/` in the checkout.

- `evidence/fishbunjin/`: 15 solo traces and screenshots from session 04. These predate manifest support
  and are explicitly marked `unfingerprinted`; exploratory observations, not a versioned baseline.
- `evidence/contact-grounded/`: 10 contact cases from session 06 and the interrupted-wave case from
  session 07, with full game/bridge/bootstrap hashes in each JSON's `provenance`.
- `evidence/side-close-whiff/`: the preserved 7-unit side-strike miss.
- `evidence/final-smoke/`: session 08 repeat of neutral contact and interrupted wave; timeout recovery
  result in `session-08/timeout-check.json`. Final bridge source SHA256:
  `caeb7d1a6780c868997de13fdddbb0dbfb1385797fe438d9ab864474274f62ce`.
- Older `evidence/contact/` contains the rejected airborne-target setup; do not treat it as an accepted run.
- Melee solo captures: `app/scratch/frameshot/mcp/20261113-174959` (19 PNGs/JSON sidecars).
- Melee target smoke: `app/scratch/frameshot/mcp/20261113-175453` (13 PNGs/JSON sidecars).

Slap City executable SHA256: `092cd828a0d168eb286f9a86feeeb4a853c2a6269a51248be81a225fafea0c77`.
Assembly-CSharp SHA256: `b70308cd719bf036158c8617c90ac8bbf5eec36f57a511c9d740c035d643c324`.
Session 07 bridge source SHA256: `c678a5f239e112a55f724348cf88497333b2888a125890a37eca6985df08484e`.
Session 06 differed in target placement: only positive distances were accepted. Session 07 added signed
distance/facing so the jab could interrupt from behind. Both settle the target before freezing; session 05
did not and its incoming-jab case correctly failed.

Game data, SDK/decompiler output, images, and complete recordings stay local. The repository contains only
authored harness code, protocol tests, and these observations. No user-facing harness gate was added.

Validation: `python -m pytest tests/test_source_calibration.py tests/test_checklist_counts.py -q`:
**27 passed**. Checks cover incomplete/nonconsecutive captures (including resets between input segments),
request ownership/deadlines, output preservation, completed PNG writes, unsupported Rivals builds and
invalid/ambiguous Rivals capture contexts. Slap City C# and native bridges compiled with the installed
toolchains; session 08 supplies the final live smoke and timeout-recovery checks described above.


## Rivals 2 controlled calibration completed later on November 13

This section supersedes the earlier idle-only status for the specific cases below. It does not claim
complete character parity. The game remained offline, human Zetterburn P0 versus Absa CPU DUMMY on
Hodojo, executable SHA256 `5fa30a728fb75aa1e703c4b3f7447154b7bd8e7cf449b3222ce291ec711a57c1`.

The optional controller now supplies finite inputs through the original native input-reading function.
A one-shot actor vtable override is removed before calling that function; current/previous SnapNet buffers
are temporarily supplied and then restored. Native single-step and an authoritative settled snapshot must
agree on exactly one update and one reader callback. It does not write attack states. The source game
install is unchanged. This works independently of the nonresponsive keyboard-synthesis attempts.

Accepted source observations:

- A 26-update movement/jab trace and 45 neutral updates verified ordinary control and frame accounting.
- Fireball contact at update 34: Absa takes +2 damage, hitstop reads 6..1 with state timer held at zero,
  then knockback and landing. Initial spacing was 660.36 cm. **This trace was interrupted after 80 of
  91 requested updates by a Windows sharing error.** The recorded contact is usable partial evidence;
  the case is not marked a completed 91-update replay.
- A separate completed 60-update fireball trace starts at greater spacing after the first knockback.
  Contact is update 40, +2 damage and six observed hitstop updates. Prior burn was already active;
  damage rises independently before/after contact, so this is not an isolated burn-tick measurement.
- Holding neutral special on updates 1..10 then releasing on 11 switches to Uncharged Active on 11,
  recovery on 13, idle on 34. Holding for 45 updates reaches Charged Active on 37, recovery on 40,
  idle on 64. Both traces complete (50 and 90 updates). The generic `charge` memory field remains zero;
  it is explicitly unvalidated, as is the velocity field that stayed zero during positional movement.
- Later readback and the visible HUD agree on Zetterburn 0 / Absa 11. Damage-unit support is limited to
  these integer examples, not fractional damage, every character, armor, or arbitrary status effects.

Melee comparison used the owned MCP harness, Zetterburn external 0x1A and **human-neutral Marth**.
At the source-equivalent spacing (0.103 units/cm times drawn scale 0.969807505607605), the existing port
has registered a 2% projectile hit by update 34; RAM and screenshot agree. Exact first-contact timing is
bounded between the sampled updates 27 and 34, not proven equal to source update 34. Opponent hurtboxes,
stage and knockback differ between engines. Source side-special idle begins at 47; the port's forced
IASA exit begins at 36. The reader already preserves both numbers; natural follow-through is an explicit
remaining custom-state requirement, not fixed in this bounded pass. Burn timing/refresh/consume remain
documented estimates rather than being guessed from these overlapping burn applications.

The controlled neutral release exposed a concrete implementation defect: old port still charged on
update 11 and entered its small burst on 12. `N_IASA` now reads refreshed input, with `N_Anim` retaining
timekeeping. A rebuilt-disc test enters ground state 375 or air state 376 at animation frame 1 on update
11 after ten held updates. This independently confirms the shared Melee callback-order rule previously
found with Fishbunjin. The air check verifies the corrected port callback; the source comparison was grounded.

Controller lifecycle acceptance:

- Normal detach, 1.5-second idle-timeout test, and terminating the exact owned controller child each
  restored all three pause/advance flags to their original zeros and both actor vtable/input-reader
  pointers to their originals. Gameplay frame counters resumed advancing afterward.
- Published API smoke also verified current/previous input buffers restored byte-for-byte after an
  attack+direction update, duplicate PID-controller exclusion, a complete two-update generic trace,
  and detach. Watchdog default remains 120 seconds. The retained DLL reference ends when the game exits.
- Client tests cover same-UUID sharing retries without re-executing a frame, client lock ownership,
  rejected malformed inputs, partial evidence preservation, and failed-cleanup exit status.

Local evidence under `source-calibration/rivals-control/`: `session-13/{movement,neutral,fireball,
fireball-repeat}.json`, `session-14/{neutral-release11,neutral-hold}.json`, `cleanup-results.json`,
`session-{15-normal,16-timeout,17-controller-exit}/readback.json`, `session-18-published/`,
`melee-side-baseline.json`, `melee-charge-accepted.json`, and `source-summary.json`.
Each native session has executable/bridge/source hashes. Melee contact image:
`app/scratch/mcp/20261113-170934/zetter-side-hit-update34.png`.

Calibrated disc: `app/scratch/rivals2-cold/zet-calibrated.iso`, SHA256
`de064c8df460162796f67bad149ab124fae9e8916949adcbeb96300040de4529`.
Rebuilt driver and sound bank; verifier **0 FAULT** (33 ok / 19 informational).
The handoff's full regression list passed **581 tests, 6 skipped**. Focused source/calibration results
are recorded in the commit handoff. No source game data, recordings, SDK dump, or disc is committed.

Owned Dolphin and Rivals sessions were closed after restoration; the user's Slippi session was untouched.
Steam's offline setting was left unchanged. Both adapters remain optional developer tools, with no new
normal-port requirement. Slap City's earlier roster-wide fix remains the shared-reader improvement from
this pass; Rivals adds reusable input/lifecycle calibration and a measured callback-order correction.
