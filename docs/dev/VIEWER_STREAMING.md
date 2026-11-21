# Native viewer streaming protocol

The Windows `HSDRawViewer/StreamingServer.cs` and headless
`HSDRawHeadless/StreamingServer.cs` send JPEG binary WebSocket messages for the
Electron canvas. JSON text messages carry commands and responses. Electron
launch, default-mode selection, forwarding and frontend canvas lifecycle belong
to their respective owners. These server changes do not activate a new binary.

## Root manager integration

Set a fresh `NUCLEUS_VIEWER_SESSION_TOKEN` in the child process environment and
send its exact value as `X-Nucleus-Viewer-Token` on **both HTTP health requests
and the WebSocket upgrade**. This is a header, never a URL parameter. Unset/empty
environment preserves legacy local tooling. Missing/wrong headers with a token
configured receive HTTP 401 before health output or upgrade. Non-loopback peers
receive 403. One WebSocket session is accepted at a time; another receives 409.
Health requests remain serviceable while a session is connected.

Before `info` or any JPEG, each connection receives this additive message:

```json
{
  "type": "capabilities", "protocolVersion": 1,
  "animationTicks": true, "cspMode": true,
  "grid": true, "background": true, "exportScene": true,
  "visibility": true, "paintPair": true, "previewPair": true, "maxMessageBytes": 33554432,
  "minWidth": 2, "maxWidth": 2048, "minHeight": 2, "maxHeight": 2048
}
```

Windows reports `cspMode: true`; headless reports `false`. Root must stop its
synthetic animation ticker when `animationTicks` is true, retain legacy fallback
for servers without capabilities, and honor failure responses without claiming
that an animation loaded. Both servers emit authoritative single-model and paired-preview state:

```json
{"type":"animFrame","frame":12.5,"frameCount":120,"playing":true,"speed":1}
```

An event follows each streamed frame and each play/pause/toggle/
seek/speed command. Frame advancement uses monotonic elapsed seconds × 60 ×
speed, with wrap in either direction. Hidden previews freeze advancement while
retaining the requested play state; no catch-up of hidden time is intended.
Paired previews synchronize common animations across both members. Skin Creator
keeps independent member poses; preview playback does not change its editing contract.

Forward `hide`/`show` to native; hiding just the canvas leaves a renderer running
on older servers. Keep the last decoded canvas image during hide/export and
until a replacement JPEG arrives. Responses are additive:

| Command | Response / behavior |
| --- | --- |
| `{"type":"hide"}` / `{"type":"show"}` | `{"type":"visibilitySet","visible":false/true}`; pause/resume rendering and encoding; continue processing commands |
| `resize`, integer `width`, `height` | `{"type":"resized","width":W,"height":H}` after uniform maximum-edge scaling to 2048 with a two-pixel minimum; framebuffer and camera aspect use that size |
| `fps`, integer `value` | Clamp cadence to 1–60; Windows now reevaluates cadence during the connection |
| `setGrid`, boolean `enabled` | `{"type":"gridSet","enabled":...}` |
| `setBackground`, boolean `enabled` | `{"type":"backgroundSet","enabled":...}` |
| `setCspMode`, boolean `enabled` | Windows: `{"type":"cspModeSet","enabled":...,"supported":true}`; headless: `enabled:false,supported:false,reason` |
| `exportScene` | `{"type":"sceneExported","success":true,"scene":...}` or `success:false,error` |
| `ping` | `{"type":"pong"}` |

Resize uses the same single scale as Electron: `min(1, 2048 / max(width, height))`.
Normal integer dimensions from 2 through 2048 are preserved exactly, including
small, portrait and ultrawide frames. Oversized frames preserve aspect subject
only to integer rounding; an extreme aspect ratio whose short edge rounds below
2 necessarily hits the two-pixel minimum. Nonpositive input is floored to 2;
it is not a request to render a zero-sized framebuffer. The managed command
harness covers these shapes, oversized inputs, half-pixel rounding and matching
capability/ACK bounds in both hosts.

`scene` retains the embedded shape: `frame`, `cspMode`, `showGrid`,
`showBackdrop`, `animSymbol`, `hiddenNodes`, and `camera` containing `x`, `y`,
`z`, `scale`, `fovRadians`, `rotationXRadians`, `rotationYRadians`.
Windows CSP mode is the **embedded framing guide**, not final CSP image
post-processing. Final CSP output still uses the existing export pipeline.
Headless does not draw that guide and explicitly reports it unsupported.
Headless reports `grid:false` on Core-profile GL, where the existing renderer
does not draw the grid; compatibility GL reports `grid:true`.

Existing `camera` deltas, texture listing/readback/UV/edit/export and animation
archive/list/load commands remain supported. Speed is finite and bounded to
−16…16; seek is finite and clamped to the animation range. `animLoaded` success
adds `success:true`; failures now return `success:false,error`. Generic parse,
invalid-command and queue failures return `commandError` with `success:false`,
`error`, and `command`/string `requestId` when available. Root should surface
those failures and preserve dirty edits until a successful applied/export ACK.
Root response deadlines should allow the ten-second pending-command deadline
plus transport time. A started edit/export can take longer; a client timeout
does not establish that it was canceled or safe to repeat.

## Protocol 2: in-place colour edits, texture batch, model swap

Since fork tag v2026.10.04 the Windows viewer announces `"protocolVersion": 2` and
`"messages": [...]`, every command type it handles, in its `capabilities` message
(also the answer to `{"type":"hello"}` / `{"type":"getCapabilities"}`, with the
request id). **The capability rule:** a client sends a protocol-2 message only when
the connected viewer announced protocol 2 or later AND lists that type
(`session.ViewerSession.supports`, frontend `viewerSupports`). A viewer that announces
`protocolVersion: 1` and no list (the v2026.10.03 release, any build before) gets
exactly what it always got, and every caller keeps its old path as the fallback:
lab colour edits and model changes restart the renderer, textures go one
`updateTexture` at a time. Headless (Linux/Mac) builds load stages too (since hsdlib
v2026.11.09.1, `capabilities.stage`) and list everything the Windows viewer does
except `loadDat` and `focusTextures`.

Each protocol-2 request carries a string `requestId`; its reply carries it back with
`success` (and `error` when false). Work is applied on the render thread like
`updateTexture`, and everything is validated before anything changes:

| Request | Reply |
| --- | --- |
| `{"type":"setVertexColors","objects":[{"id":"Group 1:3","colors":[{"pobj":0,"attr":11,"rgba":"<base64 RGBA>"}]}]}` | `vertexColorsSet` (`objects`, `values`) |
| `{"type":"setAnimationColors","tracks":[{"key":["material",1,0,4,0,2],"data":"<base64 key stream>","valueFlag":135,"tanFlag":0}],"materials":[{"id":"Group 1:3","ambient":"#rrggbbaa","diffuse":"#rrggbbaa","specular":"#rrggbbaa"}]}` | `animationColorsSet` (`tracks`, `materials`) |
| `{"type":"setLightColors","lights":[{"name":"Group 1 light 0","rgba":"#rrggbbaa"}],"tracks":[{"key":["light",1,0,0,0,1],...}]}` | `lightColorsSet` (`lights`, `tracks`) |
| `{"type":"updateTextures","textures":[{"index":3,"data":"<base64 PNG>"}, ...]}` | `texturesUpdated` (`indices` applied) |
| `{"type":"loadDat","datFile":"...","sceneFile":"","ajFile":"","dataFile":"","reframe":false}` | `datLoaded` (`textures` as `textureList`, `camera` as `info`, `animation`, `animSymbol`, `stage`, `reframed`, `dobjCount`) |

* **Names** are the app's (`shared/rendering/dat_colours.py`): an object is
  `<prefix>:<i>`, the i-th DOBJ of a renderer in joint pre-order (a stage's
  `Group <g>`, a costume's `Model`; MaterialColors' ids). A vertex colour attribute
  is (POBJ index in its DOBJ, GX attribute 11 CLR0 / 12 CLR1); its values are listed
  where the display list reads them (inline colours: every vertex in list order;
  indexed: the sorted distinct indices) and the count must match. A track is its
  structural key (`dat_colours.Track.key`: `material|texture, unit, animation,
  joint, matanim[, texanim], fobj` or `light, group, light, animation, node, fobj`).
* **Values are the result**, not the change: the app makes the edit on the DAT the
  viewer exported and sends what changed (`dat_colours.colour_messages`). The viewer
  writes them into its loaded structures with the same rules (formats and layouts
  kept; an RGBX8 pad byte kept; a buffer another pointer field also reads is copied
  and only the edited fields move to the copy), re-uploads the changed objects'
  vertex buffers on the next frame, rebuilds the material animation players at the
  current frame and reloads the lights. The picture and the next `exportDat` then
  match a fresh viewer on the edited file (measured: identical frames).
* **`updateTextures`** = consecutive `updateTexture` commands (same matching, same
  encoding), with the PNG decode and GX encode done in parallel off the render thread
  and one reply. Keep one message under the 32 MiB limit (the app splits at 16 MiB).
* **`loadDat`** reads the new file off the render thread (a file that fails to parse
  changes nothing), then frees the old model's GPU resources and builds the new one
  in the same process, window and GL context. The camera and view toggles stay
  unless `reframe` is true (default: reframe when a stage replaces a costume or back);
  the animation being watched stays when the new AJ has it (a stage keeps its frame).
  Not available while a paired preview is shown. A failure after the swap began
  leaves no model: restart the viewer.

Start-up (protocol 2 builds): the fixed 500 ms "Waiting for file to load" sleep is gone
(`MainForm.OpenFile` is synchronous), the 1-1.6 s fixed message pump waits for the GL
control's Load instead (about 30 ms), and `debug_frame.png` is written only with
`NUCLEUS_VIEWER_DEBUG_FRAME=1`: a viewer starts in about 2.2 s instead of 4.3-4.9 s.

## Rendering, ordering and bounds

Windows owns one explicit stream render schedule. Its streaming-only adapter
detaches the desktop viewport's exact private `panel1_Load` and `panel1_Paint`
handlers before GL initialization; it performs camera and startup drawable
initialization without the desktop's autonomous timers. It also avoids opening
an unused JObj editor with another render timer. The native window remains
offscreen with its GL context alive. This adapter fails startup if the private
method names change; static tests check the current handler wiring. A future
public viewport scheduling API can replace the adapter when that file is owned.

Windows streaming reads the current back buffer without swapping an offscreen
window onto the desktop. Its normal message pump dispatches render commands;
unchanged dimensions skip layout work, and completed frames wait only for their
remaining frame budget. Normal desktop rendering still presents as before.

Headless uses a reusable offscreen framebuffer. Its render loop waits for the
next frame deadline instead of polling every two milliseconds; queued commands
wake it immediately. Idle waits are bounded to 100 ms, and an over-budget frame
has no added sleep. Headless continues draining its render queue while hidden.
Both hosts aggregate capture/dispatch, JPEG encoding and send timings once every
five seconds; Electron suppresses per-frame animation logging. Both hosts skip frame
generation while `PaintPairSession.IsExporting` is true, preserving the client's
last complete image. Pair dispatch remains ahead of preview and legacy command
handling; its session/request/member identifiers and two-file export contract
are unchanged. Single-DAT serialization now runs between renders and cleans its
temporary file in `finally`. Windows texture upload failures propagate into a
failure response instead of a false success ACK; invalid cached texture slots
are rejected explicitly.

Each connection receives and awaits one command at a time, including its actual
mutation/export result and response. There is no fire-and-forget edit queue and
no dropped/coalesced camera delta. Each host allows at most 16 **pending** render
callbacks, including expired callbacks until drained. Queue overflow explicitly
fails before applying the command. Pending work expires after 10 seconds and
cannot execute later; once work begins, the caller awaits its real result.

Fragmented incoming JSON is limited to 32 MiB **before** buffer growth. Oversize
input gets `commandError` with `code:"message_too_large"` and disconnects;
binary input gets `code:"text_required"` and disconnects. The oversized command
has not been dispatched. This limits transport payload, not decoded image size.

There is only one generated/encoded frame in flight per host, and every send is
awaited under the existing send semaphore. Waiting for that semaphore plus
sending has a five-second deadline; a stalled peer is aborted, with no unbounded
frame or JSON task backlog. Headless still blocks its GL thread on a send for
up to that deadline. An edit may already be applied when its response cannot be
delivered: disconnection is an unknown acknowledgment outcome, never permission
to mark edits saved or blindly retry an export. Reconcile/reconnect through the
existing client recovery flow. Client-side outgoing buffering is separately
owned by Electron.

## Validation and remaining acceptance

The native host source (HSDRawViewer / HSDRawHeadless) lives in the `ssbmNucleus-hsdlib` fork repo,
which owns the static, typecheck, protocol, queue and cadence tests for it (they moved out of this repo
with the source on 2026-10-03). This repo consumes the prebuilt release pinned in
`app/utility/hsdlib.manifest.json`.

No application/native rebuild, restart, render launch, listener launch, process
termination, Dolphin or antivirus operation was performed. Full headless API
binding, actual HTTP/WebSocket headers on the OS listener, GPU readback/resize,
CSP guide alignment, hidden GPU utilization, last-frame retention during a real
pair export, and end-to-end Electron canvas latency require external maintenance
agent acceptance with rebuilt binaries. These managed/static results do not
establish GPU performance or visual parity by themselves.


### Ice Climbers animation archives

Combined previews use Popo's AJ as the shared animation catalogue. Nana's AJ
contains her overrides, not a second complete animation set (vanilla has 200
Popo entries and eight Nana overrides). Each member loads its own version of an
action when present; Nana falls back to Popo's shared motion otherwise. The
selected member's symbol is returned when available, while shared motions retain
their Popo symbol. Each renderer receives an independent animation manager.
Do not intersect the two AJ lists: that removes ordinary attacks and movement.
