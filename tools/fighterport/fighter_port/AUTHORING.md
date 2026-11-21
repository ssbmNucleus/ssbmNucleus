# Editable motion recipes

`author.py` compiles JSON pose/timing recipes to ordinary Melee `.anim` files.
An agent can write or revise the recipe from a motion description, inspect the
frozen preview, and install the result through the existing paired AJ/Pl path.
This is a scripting foundation, not an automatic artistic quality judge.

Run from `app/backend`:

```text
python -m fighter_port.author recipe.json Marth.joints.json --out work/strike.anim
```

The compiler prints the frozen manifest path. An install specification can use
`{"move":"ftilt","file":"work/strike.anim","manifest":".../manifest.json"}`.
Keep target rigs and game assets outside source control. Output files must be
new; unsuccessful constraint checks do not write an animation.

## Recipe format

```json
{
  "schema": 1,
  "name": "Deliberate windup and quick recovery",
  "frames": 43,
  "base": "reference-full.anim",
  "time_keys": [[0,0],[6,4],[12,12],[25,32],[42,67]],
  "controls": [
    {
      "joint": "chest",
      "rotation_delta_deg": [[0,0,0,0],[6,0,-10,0],[12,0,0,0],[42,0,0,0]]
    }
  ]
}
```

`base` is optional and resolves relative to the recipe file. Without it, the
rig rest pose is the starting pose; no original motion or video is needed.
Without `time_keys`, output frame N samples base frame N. A different duration
must be expressed explicitly when it would run beyond the base interval.
Time keys are `[output_frame, base_frame]`, interpolate linearly, and may hold
time constant. They cannot run backwards. Their meaning is animation time,
not an assertion about another game's script-controlled gameplay timing.

Joint names resolve through the rig's semantic landmarks, such as `pelvis`,
`chest`, `r_wrist`. `joint:JOBJ_75` explicitly selects a bone. A control can
contain `rotation_delta_deg` and/or `translation_delta`. Vector keys are
`[frame,x,y,z]`. A single key is constant; multiple keys must include both
output endpoints. Unknown fields fail instead of silently dropping a typo.

Rotations are local XYZ Euler inputs in degrees, composed after the base local
rotation, interpolated along the shortest quaternion arc. Include intermediate
poses for deliberate full spins. Translation deltas are in the parent's axes
and rig units. `interpolation` is `smooth` by default (smoothstep within each
segment), or `linear`. These controls do not automatically avoid collisions.

## Planted feet and other two-bone contacts

```json
{
  "chain": ["l_hip","l_knee","l_ankle"],
  "frames": [12,20],
  "anchor_frame": 12
}
```

Put entries like this in the recipe's `contacts` list. The frame interval is
inclusive. The endpoint stays at its authored position on `anchor_frame`,
after pose controls. Alternatively, supply a `target: [x,y,z]` point in rig
world coordinates. A `pole` point selects the knee/elbow bend plane; otherwise
the current plane is retained. The endpoint keeps its orientation.

The solver preserves both segment lengths, supports intermediate helper bones,
and requires an unscaled rigid hierarchy. Multiple constraints must occupy
independent branches. Constraint onset/release is explicit and can cause a pop
if the surrounding poses do not meet the anchor; there is no hidden blending.
An ankle anchor is not automatically a ground-plane sole contact.
Contacts apply to the rig passed to the compiler. Retargeting afterward changes
limb lengths; reapply or remeasure contacts on the final target rig.

Unreachable contacts fail with a distance error. `allow_unreachable: true` is a
diagnostic option that retains per-frame residuals; it does not declare success
at reaching the target. Adjust the pose/anchor deliberately instead of stretching
a limb. In the Shulk trial, lowering the recovery stance made both anchors
reachable; the first two rejected recipes remain with the experiment artifacts.

## Export and review contract

Only base-keyed or authored channels are exported. Unkeyed rest translations
and runtime-controlled engine roots stay unkeyed. Writing the complete rest
hierarchy caused measurable import error and overwrote Melee's facing behavior;
the regression suite now checks that those channels remain absent.

The run bundle freezes recipe, base animation when present, rig, compiled clip,
contact residuals and compiler dependencies. A base-free review is explicitly
labelled a self-preview, not an independent reference. Base time holds and
fractional sampling remain visible in review metadata. Existing Maya `.anim`
base curves are sampled as encoded; this does not recover original quaternion
interpolation from an already Euler-baked source.

Recipes do not author hitboxes, action-state transitions, effects, collision,
weapon visibility or specials. Those require their own runtime checks. Frozen
game-bank readback and solo in-game captures remain necessary before judging
the installed result.

## Runtime import checks

Shulk's September 5 playtest exposed failures that pose screenshots missed:

- Assign movement ownership per state. Walk/dash/run physics already move the
  fighter, so imported body motion must be in place. Animation-driven rolls
  and dash attacks need displacement on the engine root, separate from body
  FK. Compare fighter position and world-space hips through loops and turns.
- A longer animation can strand a donor script's final absolute waits in the
  past, causing a self-goto to hang the interpreter. `pipeline.install` runs
  `moveset.guard_animation_loops` on imported actions and records inserted
  animation-wrap waits. It handles self-loops; it is not a general control-flow
  proof for arbitrary branches or subroutine cycles.
- Judge actual hitboxes. `frameshot --debug-draw overlay` shows model plus
  collision; `collision` hides the model and `off` restores normal drawing.
  The harness MCP exposes the same toggle. Reapply after creating new fighters.
  Melee's command decoder assigns the packed editor `z_offset` to local X
  and `x_offset` to local Z; `combat.py` performs that conversion.
- Test positive contact and intentional misses with an opponent in the right
  physics state. Setting a grounded opponent's Y does not make it airborne;
  ground collision can snap it back before the hitbox reaches it.
- Measure aerial recovery from the first landing-state frame, not from a
  test teleport. Test L-cancel and autocancel separately. A normal landing
  animation may be interruptible before it reaches Wait; measure input
  acceptance rather than treating visual animation duration as recovery.

The native-source calibration is evidence for the reusable pipeline, not a
quality guarantee for untested characters or an independent evaluation of
image-only animation generation.
