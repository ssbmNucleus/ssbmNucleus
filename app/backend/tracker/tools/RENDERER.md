# In-browser Melee character renderer (Watch Lite)

Goal: render actual Melee characters (not dots) in Watch Lite and in
**inline Randall clips in the chat** — so "show me these combos"
draws looping character animation instantly, instead of cold-launching Dolphin.

## How it works

Each animation frame is a single **SVG path string** (a character silhouette).
Per player, per frame we resolve:

```
actionName = charmaps.actionNameById[stateId]
animName   = char.animationMap[actionName] || char.specialsMap[stateId] || actionName
pathString = animData[cid][animName][ floor(state_age) % frames.length ]
```

then draw the path with the transform
`translate(x,y) · scale(charScale) · scale(facing,1) · scale(.1,-.1) · translate(-500,-500)`
on top of the world→screen mapping. All of this lives in
**`app/frontend/src/tracker/replays/meleeRender.js`** (`createRenderer(charmaps)`).

The bundle (`viz_export.py`) now carries the renderer inputs per frame:
`cid` (per-frame INTERNAL char id — handles Zelda↔Sheik transforms), `state`,
`age` (state_age), `dir` (facing), plus `x`/`y`.

Ice Climbers' Nana rides in `frames.fol` — a list of render-only follower rows
(`{of, x, y, state, cid, age, dir, air, shield}`, `of` = her leader's player
index) kept OUT of `meta.players`/the main frame arrays so every 1v1 check
(`players.length === 2`) and the conversion overlay stay leader-indexed. Her
entries are `null` on frames where she is dead/absent. `litePaint.js` draws
her and frames her in the camera; old consumers just ignore the key.

## Data provenance & the shippability decision

- **`charmaps.json`** (tracked) — action→animation name maps + the state-name
  table, extracted from `frankborden/slippilab` (MIT) via `extract_maps.mjs`.
  Just *names/tables*, not art — fine to ship and to mirror publicly.
- **Animation geometry** (the SVG paths) — slippilab's per-character zips
  (`tools/anim_zips/*.zip`, ~92 MB). These are **Nintendo-derived art**.

**DECISION (2026-07-15): bundle the slippilab geometry, defer ISO extraction.**
The zips are **bundled into the installer** (PyInstaller `datas` in
`tools/build/mex_backend.spec`; `clip_render.py` resolves them from
`sys._MEIPASS/backend/tracker/tools` in frozen builds). They are kept
**git-untracked** (`app/backend/tracker/tools/anim_zips/.gitignore`) so they ship in the built
installer from the working tree but **never enter the public source mirror** —
`tools/release_to_public.py` copies only `git ls-files` output. Net: end users
get Watch Lite characters; the public GitHub repo does not carry ripped art as
source. The remaining exposure is the art shipping in the downloadable installer,
which is an accepted tradeoff.

> Build-time requirement: the `.zip` files must be present on disk under
> `app/backend/tracker/tools/anim_zips/` when `mex_backend.spec` runs (they are not in git). The spec
> prints a WARNING and falls back to dot-only Watch Lite if they're missing.

**Runtime fallback (2026-07-30):** when no zips are available (fresh dev
checkout, or a build made without them staged), `anim_fetch.ensure_anim_zips()`
downloads them from the slippilab GitHub repo into the user-writable
`STORAGE_PATH/nucleome/anim_zips`. It runs during first-run setup (phase
`downloading_anims`) AND as a background thread on every backend start, so
existing installs pick the zips up automatically. `clip_render.zip_path()`
searches env override → bundled/dev dir → user-data dir, so bundled and
downloaded sets compose. Vault backups leave the downloaded folder out (it was most of a
175 MB 0.9.0 backup): `vault_backup._LOCAL_FOLDERS`, so a restore never writes it and a
replace keeps this computer's copy.

### Deferred: ISO extraction (task #11) — spiked 2026-07-15, feasible but shelved

Regenerating the geometry from the user's own ISO (clean-to-ship posture, like
CSP/stock/sprites) was prototyped end-to-end and **proven feasible**:

- Pipeline: `PlFxNr.dat` (model+skin) via HSDRawViewer `--model export` SMD +
  `--dump-pose <dat> <aj> <animSym> <out.json> <frame>` (engine-correct posed
  bone world matrices, via `JointAnimManager`) → skin in Python → orthographic
  side projection into slippilab's exact model space (`Px=10x+500, Py=500-10y`)
  → silhouette raster → contour trace → SVG path. Output landed within ~4 units
  of slippilab's own Fox `Wait1` path; recognizable posed Fox silhouettes,
  drop-in for `meleeRender.js`.
- **Timing** (this dev box: 12-core CPU + RTX 5060 Ti): naive pure-Python CPU =
  45.7 ms/frame → Fox ~28 min. Optimized (GPU skin+raster via **moderngl**,
  numba RDP, bbox-crop trace, 12-worker multiprocess) = **~700–790 frames/s →
  Fox (37 k frames) ≈ 50 s, all 26 chars (780 k frames) ≈ 16–18 min**, per-char
  lazy ≈ 1 min. The pipeline is CPU-*trace*-bound, not GPU-bound (GPU work is
  ~0.3 ms/frame), so a weak 4-core laptop is ~4–6× slower (Fox ~4–5 min, all-up
  ~1.5–2 h background) — fine for lazy-per-character, too slow for a synchronous
  upfront wizard.
- **Why shelved, not shipped:** the fast GPU-skinning rewrite still had a
  posing bug (arms/hands fanning) at hand-off, and making it pixel-clean across
  all 26 characters × every animation (capes, transforms, Ice Climbers, etc.) is
  a few days of geometry + QA work — not worth it vs. bundling. If revisited,
  only the geometry *source* changes; `charmaps.json`, `clip_render`'s interface,
  and `meleeRender.js` all stay. Scratch prototype lived in the session scratchpad
  (`proto.py`/`fast.py`/`proto_gpu*.py`), not committed.
