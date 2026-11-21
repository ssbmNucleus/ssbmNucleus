# Rivals numeric material opacity

This implements a reader-to-native rendering path. It does not complete Ranno's port, its independent articles,
or the oversized victory animation. Developer observation is optional and is not a prerequisite for a user port.

## Source evidence

Rivals 2 1.7.5 (30985), executable SHA256
`5fa30a728fb75aa1e703c4b3f7447154b7bd8e7cf449b3222ce291ec711a57c1`, offline training, Ranno versus Olympia DUMMY.
The retained renderer ReceiveTick binds SashVisible to Visible on the Sash material group, excluding the shield.
The default Sash material inherits MI_Ran_Sash_Standard and MAT_Cha_Standard. The body mesh and outline each
have their own dynamic Sash material. Palettes change colors on the same default model/material lineage.

A session-local renderer experiment froze the simulation and disabled only the renderer actor's tick while
setting Visible on those two materials. It did not force attacks or claim gameplay parity:

- Frame 5814, RannoFidget2 frame 32: Visible 0 removed the sash and its outline; 1 restored both.
- Frame 15352, RannoIdle frame 6: .32 produced sparse screen-door dithering; .75 produced denser dithering.
  The source material's .3333 mask cutoff is therefore not a threshold for the Visible parameter.
- Each session restored both material values, the renderer tick flag, pause/advance flags and normal input.

Local evidence is under `app/scratch/source-calibration/shared-timing/`: `ranno-live-materials.json`,
`ranno-visible-zero.png`, `ranno-visible-one.png`, `ranno-visible-032.png`, `ranno-visible-075.png`.
The controller manifests/history are in `ranno-visual-session-02` and `ranno-visual-session-03`.
No DLL, game assets, SDK dump or screenshot is included in this repository.

The retained body victory curve is zero through 4.9 seconds, rises to one at 5.0 seconds, then holds.
The separately loaded AN_Ran_RopeSash_Victory is an independent article, not proof that the hidden body's
sash motion should be visible. Its native article remains unimplemented.

## Implementation

`echo_rivals2.opacity` accepts the calibrated material lineage and binding, never arbitrary shader parameters
with similar names. It evaluates unweighted constant/linear/Hermite curves on the sequence's time base,
preserves numeric values, and carries each attack part's actual source frame map. Frames beyond a sequence
hold its endpoint, matching the skeletal resampler. Replacing a raw clip also replaces its diagnostic entries.
Unsupported curves/bindings remain in `material_opacity.unresolved` with their source references.

Normal Ranno export carries 217 opacity timelines. Twenty-two missing/ambiguous curve records and five
out-of-range curves remain unresolved, including article clips. Those use the explicit default, not a claim
of equivalent source behavior. Zetterburn's unresolved renderer tick is not guessed into this adapter.

`own_opacity` maps these timelines through the same part maps as the animation bank, including holds, split
clips, fractional clocks and demo actions. Unmapped/interrupted actions restore the declared default. Each
fighter evaluates its own clock and materials; there is no shared player-slot timer or material pointer cache.
The owned GOBJ process runs at priority 23, after animation/input/collision/state updates, including in demos.
Both ordinary Fighter_Create and ftDemo_CreateFighter call the donor OnLoad entry where it is registered.

Before native material creation, the normal prepare/costumes stages enable material alpha and blending on
the bound pieces. Vertex alpha is retained when present. Shared color descriptors with differently controlled
pieces are refused. Every palette follows the same model-group and material checks.

The native shadow pass can bypass materials, so alpha alone is insufficient at zero. Opacity-only meshes get
independent native model groups. Their low-detail copies belong to the same groups, removed from the always
drawn shadow list. Zero selects -1; positive values select the visible choice. Existing discrete visibility on
the same mesh is explicitly unsupported until the predicates can be combined. The native eleven-group limit
is checked; the builder never merges opacity groups into unrelated facial choices.

Source screen-door dithering is adapted to native material alpha. Partial-opacity shadows remain full
silhouettes; zero-opacity pieces disappear from every model-list pass. Translucent depth writes are disabled.
These differences are explicit rendering adaptations, not claims of pixel-identical shaders.

## Checks and remaining work

Synthetic curve/descriptor tests and host-compiled generated C cover fractional fades, held clocks, interrupted
actions, independent fighters, main/demo/unknown tables, material-sharing rejection and shadow-list ownership.
The actual Ranno descriptors and generic callback compile with MexTK. Normal preparation passes its independent
fighter-data census with two model groups and low-detail sash piece 5 assigned only to opacity group 1.
All six normal costumes build (1,346,460 bytes each); each preserves the same controlled body/low-detail
piece mapping. Required regressions: **688 passed, 6 skipped**. Cache regressions verify that changing opacity
bindings invalidates the body without invalidating the rig; unrelated game reports do neither.

The full normal driver still stops on Win1: 54,208 bytes versus the 45,056-byte demo buffer. No animation was
truncated, no buffer widened and no hidden-motion compression was applied. Experiments fitting only visible
sash motion either remained oversized or distorted the visible body; they were rejected. The reader/runtime
path must not be reported as full Ranno gameplay or results-screen acceptance.

Next acceptance: built-disc fade/shadow checks after resolving the demo capacity blocker, independent article
rendering, unresolved curves and Ranno's actual specials/status effects. Required regression results are recorded
with the change; a passing suite is not a completed character port.
