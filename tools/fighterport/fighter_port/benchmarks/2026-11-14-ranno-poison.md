# Ranno poison calibration — 2026-11-14

Optional developer evidence for Rivals 2 1.7.5 (30985), executable SHA-256
`5fa30a728fb75aa1e703c4b3f7447154b7bd8e7cf449b3222ce291ec711a57c1`.
Normal users import through the reader and recipe; they do not run these probes.

## Source observations

Offline Hodojo Training, Ranno vs Olympia. Poison was applied by real dart hits in the
earlier neutral-special traces. These trials changed input only; no damage, status,
position or action-state seeding. Steam remained offline.

- Four stacks: a full hop caused no poison damage; aerial attack startup changed 9% to 10%.
- Ground jab, strong and special startup each added exactly 1%; no further damage during recovery/idle.
- Shield startup/release, walking and dropping through a platform caused no poison damage.
- A poisoned Olympia jab hit Ranno and removed one stack on contact (4 to 3).
- Subsequent real jab contacts reduced 3 to 2 to 1 to 0. Each poisoned attack start added 1%,
  including the one-stack case. The following attack with zero stacks added no poison damage.
- Ranno took ordinary hit damage/reaction on these contacts. The target was not pinned.

The pinned PoisonStackStatusEffect implementation corroborates attack-event behavior:
override RVA 0x67BC8F0 selects the highest active stack, checks source Attack state 2,
and invokes a one-point damage callback. The other stack instances do not multiply the tick.
BP_PoisonStackStatusEffect declares PoisonStack1 plus keys 2/3/4. Source hit assets retain
Poison and DoublePoison separately.

## Reusable calibration correction

RivalsCharacterEntity::ReadInputs (0x66CE3E0) calls IsCpu (0x66B3720), which resolves
the owning RivalsPlayerEntity through PlayerOwner +0x138 (0x66AB3A0). The CPU flag is
on that player (+0x838), not on the character. Earlier idle/failed-control trials 08–14
are not active-poison evidence. The working probe selects the normal input reader for
one call and immediately restores the player's flag. The production optional harness now
supports `--player 1`; its independent 40-update capture completed and detached cleanly.
Sessions 16/17/19 also record ownerCpu=1 after every opponent update and after cleanup.

## Native implementation

The normal reader exports the calibrated rules. The shared contact observer has an optional
raw-contact callback, so item and non-owner fighter contacts are visible before damage reset.
Ranno's source hit-effect intervals and dart item type add capped stacks. A direct body hit
by a poisoned fighter removes one. Native attack-instance changes trigger the single damage
tick; ordinary charge/release and ground/air continuation phases retain their attack identity.
The observer covers both subcharacters in each player slot and clears stale identities/KO state.
Generated C tests exercise the actual contact/status code, including idle, continuations,
projectiles, followers, shields, unrelated items and scene teardown. The real MexTK ABI compiles.

The normal rebuilt disc passed a live Ranno-vs-Marth check: one needle caused 1% and a real
DamageLw1 reaction. After recovery, Shield Breaker startup changed Marth to 2%; charge state 342
and release state 343 retained native attack instance 19 and caused no extra tick. Jump/landing
and idle retained 2%. A jab whiff changed it to 3%; a later jab changed it to 4% and dealt 4% plus
DamageN2 to Ranno, removing the stack. The next jab and 80 more idle updates retained 4%.
Input routing was swapped only in the owned test session to drive the opponent. Positions were
set between cases; no damage/status/move state was seeded, and contacts were not pinned.
Owned Dolphin closed cleanly. The summarized MCP observations and disc/data hashes are in
`ranno-poison-native-acceptance.json`; screenshot `ranno-poison-marth-cleansing-contact.png`.

Required working-tree regression suite: 728 passed, 6 skipped (includes separate unaccepted
camera work); control/observer suite: 47 passed. The source camera remains unaccepted and is
not part of this gameplay change. Source status visuals, shield/parry contact cleansing,
projectile cleansing, bubble consumption, owner-death persistence and unusual native attack
categories remain open.

## Retained evidence

Files are under the development workspace `app/scratch/source-calibration/shared-timing`.
Each capture ended with paused/advance/allowAdvance/pendingInput/ownsPause all zero.

| Trace | Updates | SHA-256 |
|---|---:|---|
| `session15-opponent-owner-input-source-capture.json` | 72 | `ef087d8a517227a279b13f506f30d44a8d208b4e5fe0244a0a073f88d5b32c66` |
| `session16-poison-action-classes-source-capture.json` | 209 | `9eb9db9da2fcc8fa01a189224ff5a11b26774adda9f45d021a23866192be635a` |
| `session17-poison-contact-source-capture.json` | 164 | `8fc3a7353aad6e74115d01fe0ce2aab9a0d6c74bcc3aeb540bf90de01f35622d` |
| `poison-production-p1-source.json` | 40 | `9352a76897d551858c30a9f4b8ab5778f6484f574f496533b8841204f1de1e25` |
| `session19-poison-stack-cleansing-source-capture.json` | 237 | `8c9e8e3a9e6d38b58d5499f8ad8543226549e2aa58fe7913de974eb47c2fff45` |
