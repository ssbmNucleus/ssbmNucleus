# Lite deriver: .slp bytes to a Watch Lite bundle in JS

Status: Phase 1 under construction (2026-10-18). The plan and the reasons behind it are in
[raw-slp-vault.md](raw-slp-vault.md).

The lite deriver is one pure-ESM module that turns raw `.slp` bytes into the bundle the Watch Lite
paint layer (`litePaint.js`, `meleeRender.js`, `liteStageInference.js`) already draws. It replaces
`tracker/video/viz_export.build_viz_bundle` as the source of playback data. Desktop Watch Lite, the
phone PWA and the share pages all import the same code:

```
app/frontend/src/tracker/replays/liteDeriver/
  slpParse.js      raw event walk -> ParsedSlp (this contract, part 1)
  deriveBundle.js  ParsedSlp -> Bundle v5    (this contract, part 2)
  window.js        windowBundle(bundle, startFrame, endFrame, pad)
  index.js         deriveFromSlp(bytes, {start, end}) / parseHeaderOnly(bytes)
  *.test.js        node --test (app/frontend: `npm test`), synthetic bytes only
```

Rules for everything in this folder:
- Pure ESM. No DOM, no Node built-ins (`fs`, `Buffer`, `zlib`), no npm dependencies. It runs
  unchanged in node 20+, a browser Web Worker and Electron.
- Input is a `Uint8Array` (or `ArrayBuffer`) of the **uncompressed** `.slp`. Callers inflate gzip
  themselves.
- Never throw on bad data past the header. A truncated or corrupt tail keeps whatever parsed cleanly
  and pushes a string onto `warnings`, the same stance as `stage_items._scan`. A file whose header or
  payload-size table is unusable throws `SlpError`.
- No rounding. Values are the recorded float32s; the parity audit compares with tolerances.
- Committed tests use **synthetic byte arrays built in the test**: no Nintendo data and no user
  replays in git. Real-replay parity lives in `tools/liteaudit/` (Phase 2).

## Part 1: `parseSlp(bytes) -> ParsedSlp`

### Finalization: the core rule

Netplay replays re-emit rolled-back frames. A frame id can appear several times in the stream, and
only its **last emission** is what really happened. The parser builds the finalized timeline:

- **Frame range:** `firstFrame` = the smallest frame id seen (normally -123). `lastFrame` = the
  largest. `n = lastFrame - firstFrame + 1`. Every per-frame array has length `n` and is indexed by
  `frame - firstFrame`.
- **Pre/post frames:** the per (frame, port, isFollower) value is the **last** Pre-Frame /
  Post-Frame event in stream order for that key.
- **Items:** the item set of frame `f` is exactly the Item Update events inside the **last**
  Frame Start (0x3A) ... Frame Bookend (0x3C) block for `f`. For replays without Frame Start events
  (pre-2.2), it is all item events whose frame field is `f`, last emission per spawn id.
- **`rowFids`:** an `Int32Array` holding the frame id of every Frame Start event in stream order (or
  every leader post-frame of the first present port, when there is no Frame Start). It exists ONLY so
  callers can translate legacy row-basis frame numbers (`first + rowIndex`, the old cloud combo basis)
  into true frames: `rowFids[rf - firstFrame]`.

A frame id with no post-frame for a port (a gap, which should not happen) copies the previous
frame's values and sets `present[i] = 0`.

### Shape

```js
ParsedSlp = {
  version: [major, minor, build],          // GameStart 0x1..0x3
  start: {
    stage: int,                            // stage id (GameStart 0x13 + 1)
    seed: uint32|null,                      // payload 0x13C (SPEC command 0x13D), since 0.1.0
    isTeams: bool,
    players: [                             // only ports that are present (type != 3 / empty)
      { port: 0..3,                        // slot index in GameStart
        extChar: int,                      // EXTERNAL (CSS) char id
        costume: int,
        team: int|null,                    // only when isTeams
        type: int,                         // 0 human, 1 cpu, 2 demo
        code: string|null,                 // netplay connect code (v3.9+)
        name: string|null,                 // netplay display name (v3.9+)
      } ],
  },
  firstFrame: int, lastFrame: int, n: int,
  rows: int,                               // count of raw frame events (Frame Start or leader post)
  rowFids: Int32Array,
  frameSeeds: (uint32|null)[],              // finalized Frame Start seed, since 2.2.0
  sceneFrames: (uint32|null)[],             // Frame Start scene counter, since 3.10.0
  ports: [                                 // same order as start.players
    { port: 0..3,
      leader: FrameArrays,
      follower: FrameArrays|null,          // Ice Climbers' Nana; null when the port has none
    } ],
  items: [ ItemTrack, ... ],               // sorted by start frame
  stage: {
    fod:     [[frame, platform(0=right,1=left), height], ...],   // 0x3F, last emission per (frame,plat)
    stadium: [[frame, event, transformationId], ...],            // 0x41, last emission per frame
  },
  end: { method: int|null, lrasInitiator: int|null } | null,     // Game End 0x39 (lras 0-based)
  warnings: [string],
}

FrameArrays = {                            // all length n, index = frame - firstFrame
  present:   Uint8Array,   // 1 if a post-frame exists for this frame (follower: Nana alive/present)
  state:     Uint16Array,  // post action state id
  cid:       Uint8Array,   // post INTERNAL character id (follows Zelda<->Sheik)
  x: Float32Array, y: Float32Array,
  dir:       Int8Array,    // facing: -1 / +1 (post facing float sign; 0 -> +1)
  pct:       Float32Array,
  shield:    Float32Array,
  stocks:    Uint8Array,
  lastAttack:Uint8Array,   // post last attack landed (move id)
  age:       Float32Array, // post action state frame counter (animation frame)
  airborne:  Uint8Array,   // v2.0+; all 0 when absent
  lcancel:   Uint8Array,   // v2.0+; all 0 when absent
  joyX: Float32Array, joyY: Float32Array,      // pre main stick
  cX:   Float32Array, cY:   Float32Array,      // pre c-stick
  trigger:   Float32Array, // pre processed analog trigger (what peppi calls pre.triggers)
  buttons:   Uint16Array,  // pre PHYSICAL buttons bitmask (peppi pre.buttons_physical)
  seed:      Uint32Array,  // pre RNG seed (HSD_Rand state) Slippi recorded at this pre-frame
  seedOrder: Uint32Array,  // raw pre payload offset: actual callback order; 0 = absent/stale
  preState:  Uint16Array,  // action at the pre hook, before the input tail
}

ItemTrack = {                              // one contiguous life of one spawn id, finalized timeline
  spawn: int, type: int,                   // melee ItemKind id (54 Fox laser, 55 Falco laser, ...)
  owner: int,                              // port index, -1 none/unknown (v3.6+, else -1)
  start: int,                              // first frame of this life
  // per-frame arrays, length = life, index = frame - start:
  state: Uint8Array, dir: Int8Array,       // dir -1/0/+1 (NaN facing -> 0)
  x: Float32Array, y: Float32Array,
  vx: Float32Array, vy: Float32Array,      // Item Update velocity (spec 0x0C / 0x10)
}
```

A spawn id is recycled by the game, so a **new life** starts when, on the finalized timeline, the
same spawn id reappears after a gap of one or more frames, or with a different type.

Offsets: use the Slippi replay spec. Payload offsets in this codebase are "spec offset minus 1",
because the spec counts the command byte at 0x0. Existing readers to mirror:
- `app/backend/tracker/store/slp_meta.py`: GameStart fixed offsets, the UBJSON footer, killed-session
  `raw_len == 0` recovery.
- `app/backend/tracker/video/stage_items.py`: Item Update, FoD and Stadium offsets.

Event 0x10 (message splitter) is a normal sized event: skip it. An unknown command id (not in the
payload-size table) ends the walk with a warning.

**Version gates (match Python):**
- slp < 2.0.0 has no airborne / l_cancel. `game_trace._parse` refuses those files, so
  `deriveBundle` throws `SlpError('unsupported: pre-2.0')`. The parser itself still returns them.
- slp < 3.0.0 has no Item Update events, so `items` is `[]`.
- FoD and Stadium events exist from 3.18.0 only, otherwise empty lists.

### Stage RNG ordering (NTSC 1.02)

`stageSim/rng.js` implements HSD's 32-bit LCG and shared cursors. Setup starts at
`meta.start_seed`, before fighter creation. FoD draws left then right timers;
Stadium draws its first dwell timer first. Initializers must consume their own
objects' draws in creation order; reversing a fixed number of steps from the
first pre-frame seed is invalid for multiplayer and online recordings.

The scheduler runs proc priorities ascending, then `p_link`, then object creation
order. Ground animation is priority 1; fighter input is priority 3; ordinary
ground callbacks are priority 4, before fighter physics at the same priority.
The pre-frame seed is recorded **inside** input processing, before its remaining
action callback. `frameCursor(bundle, idx)` selects the last emitted pre seed
across leaders and followers and advances by `inputTailDraws`. Earlier ground
objects share that cursor (for example Stadium's display consumes Randi(200),
and two further draws when it returns zero, before terrain).

The input hook reads the shipped `data/rngInputTails.json` table by internal
character and action, on pre/post action change with post age <= 1. Missing,
null, or unknown entries fall back to zero as a practical prediction, **not a
proof that no draws occurred**. The table's `special` notes describe conditional
native helpers, pending effect queues, and multiple transitions that are not
reconstructed. This model reproduces all 25 tested FoD and 20 Stadium event
games with their events removed; it is not a universal fighter/effect emulator.
Stadium's camera-dependent jumbotron RNG is also not fully modeled. Recorded
stage events always take precedence.

`frameCursor(..., {priority:1, extra})` requires an explicit count of priority-0
draws after the recorded Frame Start. Priority 10 similarly requires the known
intervening physics/item/ground tail as `extra`; an omitted count returns null.
Online Frame Start is `initialOnlineSeed + rotl32(sceneFrame,16)` modulo 2^32.
`onlineFrameSeed` implements that formula; the parser preserves the actual
Frame Start anchor, including offline games. Neither priority 1 nor 10 can be
recovered generally by treating the next pre-frame seed as an ending boundary.

The C16 calibration establishes `slippi_frame = match_frame`: a dump row is
state AFTER that replay frame. Boundary RAM seeds match raw replay pre seeds
at `match_frame + 1`, independently supported by FoD events and grounded
platform heights. Countdown rows are indexed backwards from counter 1; the
last zero row is Slippi 0, verified on every countdown row in five captures.
The old minus-one alignment made animated bakes draw one frame ahead and
incorrectly rejected several source-anchored simulators. Randall's analytic
fallback applies the one-frame correction internally; callers pass true frames.
The audit compares all active line IDs/kinds/drop flags and reports both strict
numeric equality and the existing 0.05 world-unit endpoint tolerance, including
unsupported rows as failures and missing replay tails separately.
Registration uses complete paired frames (a fully recorded raw Frame Bookend);
truncated final frames are listed separately, never counted as successes.
Drawn simulators are 2, 3, 9, 10, 13, 15, 16, 17, 18, 25, 27 and 29.
Every drawn port passes the geometry gate on all its captures; that is not a
bit-equality claim or validation of every interaction. In particular, stage
29's idle and two wander captures do not exercise cloud loading/vanishing.
`stageSim/ported.js` lists each remaining exclusion. Onett
only emits its bit-exact no-contact prefix and returns null after a possible
roof/awning interaction; Mute City's emitted collision is RNG-independent.

**`parseHeaderOnly(bytes)`** returns `{version, start, rawLength}` without walking frames. List and
metadata views use it.

## Part 2: `deriveBundle(parsed, {lo, hi} = {}) -> Bundle` (v5)

The same JSON shape as `build_viz_bundle` (see `tracker/video/viz_export.py`), so the paint layer
needs no changes, plus these differences:

- `meta.v = 5`, `meta.finalized = true` (rows ARE true frames: `idx = frame - meta.start_frame`),
  `meta.deriver = "lite-js-1"`, `meta.slp_version = "3.16.0"`.
- `meta.start_frame = firstFrame + lo`, `meta.n = hi - lo + 1`. `lo`/`hi` are frame INDICES into the
  finalized arrays; `window.js` converts frames to indices.
- Per-frame arrays are plain JS arrays (JSON-safe) or typed arrays; consumers only index them. The
  values are unrounded.
- `frames.cat`: port of `viz_export._category` together with the analyzer state sets it uses
  (`DAMAGE_STATES`, `GRABBED`, `THROWN`, `DOWN_STATES`, `TUMBLE`, `GUARD`, `SHIELDSTUN`, `_CLIFF`,
  `CHAR_STATE_MIN`). Copy them from `tracker/stats/analyzer.py` into one constants file.
- `frames.form`: `"Z"/"S"/"."` string for a port whose per-frame internal cid contains BOTH Sheik(7)
  and Zelda(19), else `null`. Same rule as `GameTrace.form_series`.
- `frames.lt`: port of `viz_export._lightshield`, computed over the FULL history before slicing.
- `meta.start_seed`: unsigned GameStart seed, or null if unavailable. This is the setup anchor,
  including for clips; it does not describe the start of a clipped window.
- `frames.seed`, `pre_state`, `seed_order`: port-major pre-frame seed/action/emission-order channels.
  The same channels on `frames.fol[]` preserve Nana's pre records independently of post presence.
  A seed is usable only when its order is nonzero; missing pre records never carry the preceding
  frame's RNG. The greatest order across leaders and followers identifies the last emitted pre
  record of the final frame version. Dense `port_index` is not scheduler order.
- `frames.frame_seed` and `scene_frame`: single-row channels (`[[value|null, ...]]`), so existing
  generic port-major clip windowing slices them correctly. Frame Start is before fighter input.
- `frames.cid` = per-frame internal cid. `players[i].char` = EXTERNAL cid (as today).
  `players[i].char_name` and `css_char` come from a small name table. `meleeNames.js` already has
  external names.
- `frames.fol`: Nana rows, `null` where `present == 0`, same keys as today
  (`of,x,y,state,cid,age,dir,air,shield`).
- `items[i] = {t, o, f, x, y, d, s, vx, vy}`. `f` is the window-relative index of the track's first
  frame inside the window, and the arrays are clipped to the window. **No resampling is needed**: rows
  are true frames now.
- `stage_state`: the same carry-in rule as `_viz_items`. The last FoD event per platform before the
  window, and the last Stadium event before the window, are moved to index 0.
- `conversions: {}`. These come from a sidecar (`{hash}.conv.json.gz`, see raw-slp-vault.md) and are
  merged by the caller. Players whose count is not 2 never get conversions (as today).
- `meta.attack_names`, `stage_name`, `stage_edge`: from small constant tables copied from
  `analyzer.py`.

## Parity target

Python's `build_viz_bundle` on the same file, **restricted to last-occurrence rows**, must match
`deriveBundle`:
- floats within ±0.05 (Python rounds to 1–2 decimals);
- ints, states, strings exact;
- items: same tracks, positions and states.

The only accepted differences: JS returns files that peppi panics on, and JS adds `vx/vy` and
removes rollback rows.
