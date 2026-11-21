# Rivals status calibration — 2026-11-14

Developer calibration of compiled source behavior, used by the normal reader and port generator.
Running a harness is not a user prerequisite. This does not complete the porting system or the trial checklist.

## Source fixture and accepted observations

Rivals 2 1.7.5 (30985), Steam Offline Mode, local Training/Hodojo, human P0 Zetterburn against Absa DUMMY.
Executable SHA256: `5fa30a728fb75aa1e703c4b3f7447154b7bd8e7cf449b3222ce291ec711a57c1`.
Only ordinary P0 movement/special/strong inputs were supplied; attack states and target positions were not forced.
Every accepted row has one authoritative simulation-frame increment and one P0 input-reader call.

- Expiry, 400 updates: fireball contact at update 41 applied 2% and Burn value 150. The counter stayed 150
  during hitstop/initial stun, first decremented at update 74, and produced five 1% ticks at updates
  103, 133, 163, 193 and 223. It disappeared on the last tick. Target started at 7%, finished at 14%.
- Refresh, 360 updates from a restarted 0% fixture: contacts at updates 35 and 138; the second changed
  the same Burn effect from 77 to 150. After recovery, five new ticks occurred at updates 182, 212,
  242, 272 and 302, then the effect disappeared. No overlapping Burn entries were observed.
  Damage also rose by 1 at update 144 during a ground-impact transition, while Burn remained 150;
  that event is not counted as a periodic burn tick.
- Consume, 323 updates from a restarted 0% fixture: walk 40, neutral 1, side special 1, neutral 59,
  walk 40, neutral 1, forward strong 1, neutral 180. Fireball contact at 64 applied Burn. Two periodic
  ticks preceded the strong. The strong hit for 2 at 160, 8 at 164, then a separate 6 at 174, when
  Burn disappeared and target hitstop became 24. Target ended at 20%. The attack assets identify
  the final sequence as Active 1 -> Active 2 -> CharacterSpecific1 -> Consume Active/Recovery.
  Its final hit has separate knockback, hitpause, hitboxes and animation frames; a percent bonus is
  not equivalent. This remains open implementation work beyond the clock fix.

`hitstunDuration` is the last-hit duration, not remaining time. It stayed 24 after projectile recovery
and changed to 16 on the refresh case's ground impact. Burn can resume while the landing/bounce animation
state is still active: state names alone are not a valid remaining-stun test. Source/native engine hitstun
lengths and opponents differ; the measured clock rule is carried through Melee's stun/hitlag flags.

## Changes carried into ordinary ports

- `echo_rivals2.rules.BURN` records the observed duration (150), interval (30), damage (1), refresh
  policy and build/evidence provenance. `game.json.status_effect_rules` carries those rules separately
  from attack-asset properties. The generator uses exported rules, with the same calibrated default
  for previously exported work folders.
- Zetterburn uses five ticks and pauses the clock during target hitstun/hitlag. The old six-tick,
  unconditional clock was an explicitly uncalibrated stand-in.
- A projectile arriving while its owner is in a strong no longer falsely qualifies as a direct
  consuming strike: the damage log must identify the fighter object. The existing consume shortcut
  still applies damage too early and lacks the source follow-up; it is not accepted as parity.
- The observer retains bounded status arrays (name, integer value, inflictor), caches a fixed roster
  during finite traces, and revalidates identities. RestartMatch revealed old destroyed actors still
  present in the UObject table; both native control and observation now exclude destruction/garbage
  flags and Actor's destruction bit. Identity/destruction changes during capture fail explicitly.
- Optional `training-ready` and `restart` call the local Training UI/native methods. Restart is
  restricted to unpaused gameplay without an owned pause/input operation. Restart is asynchronous.

## Rebuilt-disc acceptance

Normal `port --own` driver, sounds and build stages completed. Disc verifier: 33 ok, 19 informational,
zero faults; these file checks do not cover every open trial checklist line.
ISO `app/scratch/rivals2-cold/zet-burn.iso`, SHA256
`5e4ed249f58edbe6dd36d1d32cfffb1e0561020cd80fced953d41b34cb01bd1f`.

MCP harness: Zetterburn external 0x1A/internal 27 vs human-neutral Marth, Final Destination, initial
60-unit spacing; target free to react, no position pinning. Fireball first contact was update 30 for 2%.
At 54 damage was still 2 and Marth in DamageN2; at 74 he was idle and still at 2. Samples at
94/124/154/184/214 had 3/4/5/6/7%, with 7% unchanged at 274. This bounds native clock behavior;
it does not claim exact cross-engine contact/stun parity. Generated-C execution tests separately
cover the 29/30 boundary, all five ticks, hitlag/stun pause, refresh and direct/projectile distinction.

Focused checks: 66 passed, 2 skipped. Required port suite: 628 passed, 6 skipped.
All source captures detached with input/pause restored; the owned Rivals and Dolphin sessions closed.
Steam remained offline; the user's separate Slippi session was untouched.

## Local evidence

Under `app/scratch/source-calibration/shared-timing/`: `rivals-burn-expiry-b.json`,
`rivals-burn-refresh-clean.json`, `rivals-burn-consume-b.json`, `zet-consume-details.txt`,
`zet-native-burn-clock.json`, `zet-burn-build.log`. Full traces preserve inputs, bridge/source hashes,
initial conditions, observations and cleanup. The earlier expiry trace was interrupted by unrelated
object collection; the first refresh plan missed its second shot; the first consume attempt rejected
stale actors after restart. Those attempts are retained, not substituted for accepted captures.
Game assets, SDK dumps, binaries and raw recordings remain local and are not committed.
