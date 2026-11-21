# Slap conditional hitboxes and resource contacts — 2026-11-14

This is an implementation milestone, not a completed BCM port or completed port system.

## Shared corrections

- The reader no longer applies conditional SASATP, SARA, SAEA or SASHC to the unconditional hitboxes.
  Conditional SACH replacements of existing boxes also retain a separate branch. BCM forward air previously
  truncated the ordinary boxes when its cash branch was read, producing a spurious phase boundary.
- Ordered `source_terms` preserves assignments, expressions, custom calls and raw guards. `source_programs`
  remains authoritative for execution phases, callback lifetimes and loops.
- `own_slap_expr` compiles only explicitly bound scalar expressions and predicates. Unsupported input or
  resource terms fail; consecutive operations share one lexical guard so spending cannot disable its clamp.
- `own_contacts` observes pending collision records at priority 14, p_link 0, before fighter damage at
  priority 14, p_link 8. Native OnGiveDamage alone misses trades because incoming damage takes precedence.
  The observer includes primary/secondary targets, body and shield contacts, and a scene teardown reset.
  Callbacks may update resources, not damage fields or action state in this phase.
- Source sound existence is checked against actual bank ids. BCM `straircharge` has no id in its bank;
  SAPlaySFX/SmashSFXBank make that call silent in the source game. This is distinct from a decode/export
  failure of an existing sound. The original verification failure was preserved before this correction.

## BCM implementation and native trial

`own_bcman_resources` consumes source transactions for ordinary buying attacks, forward/up strong,
forward air, pummel, down throw and the plain neutral special. Resources persist across moves, clamp at
1000, and halve on the native death edge. Bindings reset with the action. Sell costs occur once per binding
on body or shield contact; buy events exclude shields. Damage is regenerated from immutable base values.
Z currently substitutes for the source dash/clutch spending modifier; native smash-charge frames supply
the charge fraction. These are port adaptations, not demonstrated input/charge equivalence.

Native ISO: `app/scratch/slapcity-bcman/bcman-resources.iso`.
SHA-256: `ab88dd09a4d66649762a60a886c6c8a2b28b7c123bddbdd68d61395b4202f016`.
Normal reader → driver → sounds → costumes → build, with a separate owned MCP session and human-neutral
Marth on Final Destination. No CPU, no continuous target pinning. The first build exposed the missing
costume stage; the next produced the disc and caught the original-game silent sound reference twice in
verification. Refreshed reader/driver/sound receipts subsequently distinguish that source no-op.

| Case | Observation |
| --- | --- |
| Jab, starting cash 0 | Real body contact gives 30 cash; recovery leaves 30, no repeat credit. |
| Forward strong, seeded cash 399 | 12% damage, cash remains 399. |
| Forward strong, seeded cash 400 | Source damage multiplier 2; staled hit gives 21.84000015%; cash becomes 0 and stays 0. |
| Forward strong whiff, seeded cash 400 | Cash remains 400 through recovery. Target is out of range in CliffWait. |

The threshold cases seed only the cash scalar, explicitly, to isolate the boundary. Jab cash is earned
by normal contact. Marth takes real damage and moves freely; the second strong eventually puts him on the
ledge. Screenshot/evidence: `app/scratch/source-calibration/shared-timing/bcman-native-resources.json` and
`app/scratch/mcp/20261113-170934/bcman-resource-calibration.png`. Session is closed.

## Validation and open work

Generated-C execution covers trades, shields, zero-knockback armor, secondary opponents, stale records,
sleeping targets, ownership changes, scene cleanup, clamps, one-time costs and move-binding lifetime.
The observer and resource adapter also compile against MexTK. Those trade/shield/armor cases still need
native input trials; this native run verifies body contacts and spending/whiff behavior only.
All 11 Slap fighters pass the reader's rig/hit/hurt/collision audit after the conditional correction;
known conditional/dynamic clip gaps remain explicit. No user needs to run a harness.

Open: BCM custom up/down/side specials and counter state, visible cash/BUY/SELL effects, forward-throw
branch, taunt/grab losses, air-finisher/cards, exact charge and input mapping, multibox aggregation limits,
and final visual/audio/package acceptance. Plain special states remain labeled plain in the build.
Ranno's demo-bank capacity and custom specials remain independent open work. Passing these cases is not
evidence that either game reader has complete runtime coverage.

Required regression suite: **661 passed, 6 skipped** (127.54 s). The refreshed normal package verifier
has **0 FAULT**; unanswered checklist items and the explicit runtime/visual limitations above remain open.
