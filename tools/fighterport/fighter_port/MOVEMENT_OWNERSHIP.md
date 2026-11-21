# Animation movement ownership

Do not infer travel from a moving source root or from a Melee action flag alone.
The state physics callback must consume the extracted axis. This applies equally
to a donor-compatible rig and a source-native rig.

`movement_ownership.audit_bank` checks an explicit list of motions and the actual
engine translation joint. `adapt_common_bank` repairs only the known common-state
contracts; custom states require a separately reviewed contract.

| Owner | Treatment | Examples |
| --- | --- | --- |
| Gameplay physics | Remove the source trajectory from the engine translation joint; preserve body curves. | Walk, run, dash, brake, turns |
| Animation delta | Extract the supported axis into fighter position, once, through the state physics callback. | Rolls, dash attack, dash grab, moving techs |
| Local body pose | Retain the movement within the pose. Do not enable extraction simply because a root moves. | A planted tilt leaning forward |
| Custom / unknown | Review the actual callback and source trajectory. No automatic deletion. | Character specials, unusual movement states |

Evidence already present in this workspace:

- Shulk's `echo_tier2_shulk/movement_moveset.json`
  separates eight locomotion clips from root-driven rolls and dash attacks.
- Little Mac's `pilots/littlemac/common.py` uses the same locomotion split.
  Its `defense.py` preserves unsupported X/Y travel as body residuals instead of
  losing it when the engine consumes Z.
- Melee `ftanim.c` extracts Trans only with action flag `0x80000000`; the
  `0x40000000` loop flag does not enable extraction. `ft_084E.c:ft_80085030`
  consumes Z using the appropriate current/saved facing. Walk and run apply
  their own velocity. `ftCo_AttackS3_Phys` applies friction and does not consume
  animation travel.

Root extraction starts from the entry-frame value. Do not turn a nonzero source
entry into an initial teleport. Preserve unsupported axes in body motion before
enabling a consumer that uses only Z. Rolls use saved facing; moving techs and
dash attacks use current facing.

The bank repair isolates shared root buffers before zeroing their numeric
translation payloads, then repacks the archive and updates action spans. Body
curve bytes, timing opcodes and durations are preserved. It rejects conflicting
movement policies on shared action symbols. The low-level in-place patch refuses
root buffers shared with body channels. The audit samples quarter frames to find
movement-policy errors; it does not replace full curve fidelity evaluation.

Randall and the harness expose `native_port` operations `movement_audit` and
`movement_repair`, taking `fighter`, `animation`, explicit `root_joint` and
`motions`; repair also requires a new `out` directory. Common rules apply only
to reviewed state consumers. Unknown specials remain review-required. The
Trainer builder runs this admission check on the final supplied banks.

The extraction joint and the outer engine root are different consumers. Pass
`engine_root_joint` when its translation is overwritten by the engine. A source
conversion that shifts every expanded world matrix to cancel travel can put
the inverse trajectory on this outer root and leave the original trajectory
on Trans. Those curves cancel in offline FK, but the outer curve is overwritten
in the game. Never use an animated engine root as a compensation parent.
For physics-owned clips, repair neutralizes both translation writers while
retaining body channels; for animation-delta clips, it neutralizes the outer
writer and keeps the supported extraction curve. Test the actual runtime pose.

Custom states can provide `movement_contracts`, mapping motion names to
`owner`, `axes`, `physics` (the reviewed callback path), and optional `facing`.
Physics repair requires XYZ ownership; animation-delta repair supports the
reviewed Z consumer. Common contracts cannot be overridden. This makes a new
special's ownership explicit instead of treating every Ultimate root as zero.

Run the audit during authoring preflight and again on the assembled bank before
export. Native checks can then batch representative locomotion loops, release to
idle, and each distinct movement consumer in both facings. There is no need to
repeat unrelated hitbox-placement tests for a root-only repair.
# Normal attacks and outer-root cancellation

Do not assume a normal attack inherits correct root handling merely because
walk/run passed. Historical conversion put inverse Trans movement on the
outer engine Top joint. Offline worlds canceled, but Melee overwrites Top and
the model then slides. Validate both joints on each owned motion.

Trainer's `normal_movement.contracts` (archived under the tag
`archive/fighterport-character-specific-2026-11`) explicitly selected native physics for
its normals except dash attack. The repair neutralizes both translation
writers and disables optional extraction for those selected attacks. Dash
attack retains its reviewed delta consumer. This is a Trainer authoring policy:
Melee's jab/forward-smash callbacks can optionally consume root movement, so
it must not become a blanket rule to zero every future character's attacks.
Source hitbox attachment points and their ancestor tracks need independent
pose checks after movement adaptation and compression.
