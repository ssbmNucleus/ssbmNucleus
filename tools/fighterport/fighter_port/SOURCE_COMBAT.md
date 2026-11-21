# Source combat contracts

Replacing an animation does not replace its combat script. A donor script may
decode and run correctly while using the wrong attack bones, offsets, active
frames, or hit-history groups. Bind-pose rebasing alone cannot repair that.

Randall and the harness share two `native_port` operations:

- `source_combat_audit`: compile a pinned source contract and compare selected
  installed action scripts. Read only. Reports differing action indices.
- `source_combat_install`: perform the same validation, install pointer-free
  scripts into a fresh output directory, and verify their encoded readback.
  Reuses old script spans only when no unselected pointer/root refers to them.

Both take `fighter`, `animation`, and `combat_contract` paths. Installation also
takes `out`. A contract has this structure (hashes and matrices must be measured):

```json
{
  "schema": "source-combat-contract-v1",
  "fighter_sha256": "...",
  "animation_sha256": "...",
  "actions": [{
    "action": 69,
    "motion": "AttackAirF",
    "source": "source-AttackAirF.txt",
    "source_sha256": "...",
    "game": "game_attackairf",
    "animation_sha256": "...",
    "clock": {"source_start": 0, "source_end": 39, "target_end": 60},
    "bindings": {"top": {"bone": 0, "matrix": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]}},
    "policy": {
      "engine_differences": "Explicitly authored Melee adaptation; no Ultimate hitlag/SDI multipliers",
      "capsules": "enclosing_sphere",
      "fractional_damage": "ceil",
      "motion_rates": "animation_pose_clock",
      "rehits": "explicit_refresh",
      "groups": "source_part",
      "elements": {"collision_attr_water": 0}
    }
  }]
}
```

Source paths resolve relative to the contract. The reader accepts a bounded
converted ACMD `game_` function, unconditional execution guards, and finite
loops. It never executes source text. Unknown control flow fails. Unhandled
statements and omitted hit IDs need individual reasons in `omit_statements`
and `omit_hit_ids`; unsupported angles need explicit `angles` mappings.

The binding matrix maps source bone-local XYZ into the measured target bone
space. The example root identity is not a universal preset. Reflections and
scale require separate authoring and are rejected. Melee's packed editor names
use `z_offset` for local X and `x_offset` for local Z. Named source bones must
also retain their animated ancestor chains during compression.

Clock mapping uses the first target integer animation pose reaching a source
event. For a full source 0..39 mapped to target 0..60, frames 5, 7, 15 map to
8, 11, 24. The importer checks the actual archive end and refuses trimmed
source windows. Motion-rate commands are recorded; choosing the converted
pose clock does not preserve Ultimate wall-clock speed. Entry-anchored clocks
require an explicit separately implemented playback contract.

There are only four native hitbox slots. Source ID updates retain slots until
clear; source parts map to native hit groups. Explicit repeat hits refresh only
their own slot. Capsules become enclosing spheres only under the named policy;
this expands coverage and requires gameplay review. Category rules, autolinks,
hitlag, shields, and physics differ between engines and cannot be inferred from
an animation replacement.

`SOURCE_SCRIPTS_MATCH` means only that selected installed scripts match the
declared source adaptation. It does **not** establish source pose fidelity,
collision timing in the live engine, actual victim contacts, safe callbacks,
or full-moveset readiness. Validate both facings with source-based expectations
and model-plus-hitbox overlays; comparing live capsules only to installed
scripts would miss the original donor-script failure.

`compress` optionally takes the same `combat_contract`. It verifies that the
declared scripts are installed, and bounded compression preserves the named
hitbox bones and their ancestor streams verbatim. The output includes a contract
with updated fighter/archive hashes. This protects existing animation data;
it cannot restore tracks removed by an earlier converter. Source pose checks
must establish those tracks first.
