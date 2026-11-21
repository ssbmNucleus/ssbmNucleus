# Reusing solved port problems

Use `native_port` `info` to discover the operations below. They compose the
existing source readers, dependency closure, chart/wrapper handling, DAT
inventory, encoder audit and geometry evaluation. Character selection, engine
consumers, source initialization and tolerances remain explicit inputs.

Historical checkpoint scripts are evidence, not templates to copy wholesale.
Before investigating a failure, run the matching operation and identify which
assumption the previous solution does not cover.

## Mesh dependencies and frozen rigs

```json
{
  "op": "plan_rig",
  "source_rig": "work/full-source-rig.json",
  "source_mesh": "work/source/model.numshb",
  "selection": "work/selection.json",
  "consumers": {"effects": ["HandL_eff"], "throw": ["Throw"]},
  "animated_joints": [],
  "unresolved_consumers": ["special articles"]
}
```

Selection is `{"meshes":[{"name":"mesh name","subindex":0}]}`, the same
identity contract as `source_mesh_handoff.prepare`. Names in the example are
illustrative: derive consumers from the actual engine/action scope.

The planner reads positive skin influences and rigid parents from the raw
mesh, retains their ancestors and named consumers, and lists excluded meshes
that would invalidate pruning. Animation presence is diagnostic, not a reason
to retain an unused physical joint. This is a plan, never engine acceptance.

Charts come from `rotation_charts.choose` or an explicitly frozen prior
selection. Resolve named pending consumers before freezing. The predicted count
is the skeleton count; repeat `costume_budget` on the actual imported DAT to catch
extra importer nodes, and use `engine_capacity.assess` against the target DOL.

## Visibility and costume size

```json
{
  "op": "source_visibility",
  "selection": "work/selection-with-visibility-nodes.json",
  "source_motion": "work/source/idle.nuanmb",
  "frame": 0,
  "fallback_motion": "work/source/initialization.nuanmb",
  "fallback_frame": 0
}
```

Each selection row may include `visibility_node`; null means uncontrolled.
Current tracks win over the explicitly pinned fallback frame, which wins over
an explicit `visibility_defaults` map. Missing values remain unresolved,
never implicitly false. The result records which source supplied each value.

For a preflight manifest, also provide `costume` and `dobj_map`, a reviewed
mapping from each selection row to its actual serialized DObj index. The
operation bounds-checks that declared mapping and binds the manifest to the
costume hash. It does not infer mesh identity from descriptor count. Supply
correspondence evidence that also checks ambiguity: a passing triangle
comparison for each proposed pair does not establish that the pairing is
unique. Challenge other groups with equal triangle counts at the same
tolerances. Geometrically indistinguishable groups require separately pinned
import-order or material evidence; record that dependency explicitly instead
of claiming geometry alone proves identity.

Supply
the result as `visibility_manifest` to `preflight`: hidden drawables must be
covered by fighter alternatives in modes 0, 1 and 3. Coverage still does not
prove the chosen initialization or runtime expression switching.

The declared costume count must match the table extent. After an HSDRaw/Mex
re-save, supply `table_padding_bytes` only from independently known costume
count/serialization evidence. It accepts explicit zero padding of0..28 bytes
without pointers; it never automatically treats a NULL costume row as padding.
The current append-only writer preserves the table extent, but a later external
re-save must be inventoried again. Retain reviewed DObj correspondence separately.

This writes layout only. Default states, timed cues and callback ownership remain
caller responsibilities. In particular, the native model-state setter refreshes
only mode0: when DObjs are shared across modes, integration must refresh modes1/3
as well or expression changes can leave them hidden. Test active-mode switches
and interruptions; a coverage receipt is not runtime-selection acceptance.

```json
{"op":"costume_budget","costume":"work/imported-costume.dat"}
```

This measures unique encoded tiled image payloads, display lists, the remaining
archive structures, and actual JObj/DObj counts. When textures exceed half the
file, it directs texture reduction first. Shared images count once; unsupported
mip chains fail explicitly. This is file allocation accounting, not MEM1/ARAM
or roster admission.

The existing `materials` operation now accepts `max_texture_dimension` and
`preserve_materials` (source material labels). It applies the explicit size
policy after color-layer baking and before encoding, preserving aspect ratio
and RGBA. Defaults keep existing dimensions. Small eye/expression sheets can
be exempted. Re-import, remeasure the encoded DAT and inspect the actual face,
silhouette and alpha behavior; PNG savings alone do not establish acceptance.

## Animation diagnosis before repair

```json
{"op":"animation_diagnose","recipe":"work/diagnosis.json","out":"work/new-diagnosis"}
```

The recipe uses schema `animation-diagnosis-input-v1`. Paths are relative to
the recipe and all nine must have matching SHA-256 values in `input_sha256`:

| Field | Input |
|---|---|
| `source_rig` | Ancestor-closed source subset, with order/parent/rest |
| `target_rig` | Frozen rig, including provenance scale/chart helper names |
| `source_skeleton`, `source_motion` | Raw Ultimate skeleton and one motion |
| `costume` | Actual DAT on the frozen rig |
| `skin_smd` | Reviewed geometry readback from that costume |
| `authored` | FigaCodec key-spec JSON, one clip |
| `packed` | Actual encoded FigaTree DAT |
| `codec` | Existing built FigaCodec executable |

Also supply `wrappers`, the exact identity engine-node list, and `limits` with
positive `integer_pivot`, `fine_pivot`, `integer_skin`, `fine_skin`, and `basis`.
Optional `bytes` must be 32768, 65504 or 131040. Python builders should obtain
these through `native_port.source_acceptance(height, capacity=...,
skin_fraction=...)`; the legacy `relative_acceptance` retains its historical
Trainer default and must not supply a new character's capacity.

The op audits the actual encoded bytes and compares source→authored,
authored→packed and source→packed on the same complete 1/16-frame grid, including
integer gates and all supplied skin vertices. It returns the worst frame,
vertex/joint, its weighted joints and ancestors, and an immediate stage-error
diagnosis. Retimed or movement-repaired clips need a different explicit source
clock/movement contract; this adapter refuses them.

`authored_stage` is `exact` (default) or `reduced`. Optional `predecessors`
contains previously reviewed PASS/FAIL/UNMEASURED verdicts before that stage.
`first_failure` preserves missing predecessor evidence; it is distinct from
the numerical `diagnosis` of these three measured inputs. Caller verdicts do
not replace independent source-semantics review. Source pose acceptance is
separate from byte capacity, movement integration and live gameplay.

## Encode, repair, pack

`native_port.author_dense(..., reducer=...)` accepts the existing scalar or C1
reducer without another authoring loop. Its default preserves old behavior.

Use `workbench.run_candidates`, not a campaign-specific search framework.
Declare a byte budget, attempt budget, elapsed budget and fixed comparison
domain (bind source, rig, clock, movement policy, geometry and limits).
For repairs supply an evaluated `baseline` containing actual `blob` bytes,
`metrics`, `domain`, optional `spec`, and `protected_state`. It is incumbent -1
and does not consume a candidate attempt. `monotonic=True`/`"gates"` prevents
any passing metric from failing; `"metrics"` forbids any increase. Both modes
require that baseline. An optional `generator(incumbent, attempt)` can propose
from its witness instead of a static list. Generators/evaluators receive copies.

The default `tie_break="bytes"` preserves the original selection rule. For
repairs where an unrelated worst error is tied, opt into
`tie_break="violations"`: after capacity and the worst normalized error, compare
remaining failed-gate ratios from largest to smallest, then bytes. Passing
metrics do not influence that secondary vector. This retains improvements like
Pit frame54's pivot repair while its skin maximum is unchanged; it does not
waive monotonic, protected-interval, capacity or full-pass gates. The policy is
recorded in each search receipt. Saved-byte replay:
`artifacts/pit-resume-sol-20260914/coordinator/tie-break-replay.json`.

When combining newly admitted clips through `pack`, provide `target_rig` and
`clip_receipts` mapping every public symbol to its codec/diagnosis receipt path.
The operation refuses missing pins, changed bytes, node mismatch and mixed rig
fingerprints, including same-node-count changes to rests. Raw lossless packing
without these optional arguments remains available for legacy bank operations;
it makes no rig or source-admission claim. Codec receipts alone never establish
source fidelity.

New receipts also pin `track_sha256`, the lossless clock/count/descriptor/stream
identity already used for alias grouping. Assembly may rename public symbols
or combine aliases without invalidating that identity; changed animation
streams still fail. Old receipts without it require exact file bytes. Check
the final packed span size again, since symbol tables can change its size.

## Regression entry points

The Pit known-failure replay lives in the outer workspace at
`artifacts/pipeline-reuse-20260914/replay_pit.py`. It calls shared operations
without importing worker scripts. It covers unused animation branches, frozen
115-joint serialization, open-eyelid fallback, 4.62 MB→1.08 MB accounting, and
raw-source fitting-vs-packing diagnosis on the saved run/tilt failures. Historic
artifacts remain immutable. New character problems require new evidence;
the old failed Pit tilt search is not promoted into a universal fitter.
