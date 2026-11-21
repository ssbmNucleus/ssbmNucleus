# Disabling Final Destination's background "star" sparkles for `--plain-bg`

Research mission (static analysis only — no Dolphin boot). Goal: make FD
(`GrNLa` / internal `LAST`) render with **zero drifting background sparkles** on
the flat gray `--plain-bg` background, so effect-audit captures aren't polluted.

All decomp cites are from a local checkout of the Melee decomp (doldecomp/melee,
read-only). Addresses are NTSC 1.02 (GALE01), the build the harness targets.

---

## ✅ SOLVED (2026-07-02, GENERATOR PASS) — wired into `frameshot.py --plain-bg`

The stars are ONE long-lived psLib GENERATOR with **`bank == 0x1E`**, the
stage SPtcl/DPtcl bank: `efLib_Cb_SPtcl` routes bank 0x1E to grLib
(`eflib.c:998` / `grlib.c:159` → `hsd_8039F6CC`), spawned by the FD
background JObj anim's SPtcl key. Fighter effects use their own ef banks
(live-verified: fox up-B = generators bank 0x03 + 0x00), so bank 0x1E cleanly
separates stage particles from fighter particles.

Live probe `backend/devtools/research/fd_star_gen_hunt.py` (captures
`tests/artifacts/fd-star-gen-hunt/`), solo fox on vanilla FD `--plain-bg`:

- Pre-effects the psLib state is exactly **one generator**
  (`bank=0x1E link=0 idnum=0x0101 kind=0x08400000 type=0x0708 genLife=3799`,
  `jobj` in the stage tree) plus its **25 particles, all bank 0x1E** — the
  stars, nothing else.
- **Kill lever = UNLINK by bank**: walk the global generator list (head
  `hsd_804D78FC` @ **0x804D78FC**; `HSD_Generator.next +0x00`, `.bank +0x18`)
  and the per-linkNo particle lists (heads `hsd_804D0908[]` @ **0x804D0908**,
  linkNo < 8; `HSD_Particle.next +0x00`, `.bank +0x08`) and patch head/next
  pointers past every bank-0x1E node. Nothing is freed → no dangling
  pointers (a few leaked structs per anim loop, harmless for a capture
  session).
- The particle render pass walks these live lists **every composited frame**,
  so the unlink blanks the stars even while frozen with NO game step
  (star-metric 0 immediately) and 8/8 stepped samples (baseline 500 → 0).
  The generator did not respawn across the whole run; the per-capture re-poke
  covers an SPtcl re-fire at the anim loop anyway.
- **Fighter effects intact**: with the kill active, fox up-B fire renders
  fully at frames 12/25/42 (banks 0x00/0x03 generators untouched).

**Wired:** `backend/devtools/frameshot.py` `kill_stage_particles(d)` — called right
after both `assert_plain_bg` sites (post-READY/GO + per-capture), gated to
`--stage finaldestination`. Regression PASSED:
`python devtools/frameshot.py --char fox --move upb --frames 40,60 --plain-bg --iso
output/straggler-vanilla.iso` → stars gone in both captures, FireFox fire
fully present. (One run hit the known flaky "frame step stalled" harness
wedge; two subsequent identical runs passed clean, and the no-plain-bg
control also passed — not caused by the poke.)

---

## STATUS UPDATE (2026-07-02, FINAL DOLPHIN SWEEP): mechanism FOUND — the
## stars ARE efLib PARTICLES (§1's "not a particle system" conclusion is WRONG)

Candidate-C live pass (tools: `backend/devtools/research/fd_star_hunt.py` full-GObj-list A/B
sweep + `backend/devtools/research/fd_star_confirm.py` dense-sample confirm; captures
`tests/artifacts/fd-star-hunt/` + `fd-star-confirm/`):

- **Full live GObj walk** (via `HSD_GObj_Entities` heads @0x804D782C — NOTE
  `plinklow_gobjs` @0x804D7828 holds the list TAILS, walking `next` from it
  sees one GObj per p_link): 48 renderable GObjs in a solo FD match, incl.
  SIX stage-class (cls 0003, gx_link 3) GObjs beyond the four x180[] slots.
  A/B-killing each GObj by temporarily NULLing `render_cb` (+0x1C — the GX
  render loop null-checks it; generic + reversible) found NO stage/UI GObj
  whose kill removes the sparkles.
- **DECISIVE:** killing the **efLib MAIN particle-render GObj** (classifier
  8, p_link 0xB, gx_link 7, render_cb `efLib_render_callback` = 0x8005C904,
  created in `efLib_Init` eflib.c:172) removes the stars **16/16 sampled
  frames (star-metric 0 vs baselines 1082/1816)**. The aux ptcl GObj
  (p_link 0xC, gx_link 8) kill does nothing (2387 ≈ baseline).
- So the drifting sparkles are ordinary particles drawn through the main
  efLib layer. §1's static conclusion ("animated JObj geometry, not ptcl")
  is falsified — which also explains why Candidates A/B (JObj render-flag
  masks) couldn't touch them.

**Why this is NOT wired into frameshot:** the gx7 GObj renders ALL efLib
particles — including the fighter effects the plain-bg audit captures exist
to show. Nulling it is only usable for captures that need NO particles.

**NEXT LEAD (the remaining work for a clean kill):** find the stars'
GENERATOR, not their renderer. Most likely spawn path: FD's background JObj
anim carries SPtcl/DPtcl keys — `efLib_Init` registers
`HSD_JObjSetSPtclCallback(efLib_Cb_SPtcl)` / `DPtcl`, so a stage JObj's
animation can spawn particles even while its RENDER flags are masked (this
fits every observation: A/B root-flag kills leave the anim running →
particles keep spawning). Options, in order of promise:
1. Enumerate live ptcl generators in a frozen solo FD match BEFORE any
   fighter effect exists (the only active generators should be the stars),
   read their gen/bank ids, then have frameshot kill generators with those
   ids each stepped frame (they likely respawn per-frame from the anim).
2. Strip the SPtcl/DPtcl tracks (or the ptcl bank reference) from
   `GrNLa.dat` in a test ISO — a build-side kill, immune to respawn.
3. Null `HSD_JObjSetSPtclCallback`'s stored pointer for the capture — a
   sledgehammer (kills ALL anim-driven ptcl game-wide), but fighter Ef
   effects are efSync/efAsync-spawned, not SPtcl, so it MAY be safe for
   audit captures; needs an A/B with a known fighter effect on screen.

## (Historical) STATUS: ❌ Candidate A + B FALSIFIED by live validation (2026-07-02) — NOT wired

A Dolphin validation slot ran the §5 protocol on vanilla FD `--plain-bg`
(marth, `extras-audit-Fox-laser_ring-vanilla.iso`). **Neither Candidate A nor
Candidate B removes the sparkles.** The patch was NOT wired into `frameshot.py`.

Live findings (all captures in `tests/artifacts/fd-star-fix/`):

- Stage GObj table `0x8049E848` read cleanly and consistently across boots:
  | slot | gobj | root jobj (+0x28) | root flags (+0x14) |
  |------|------|-------------------|--------------------|
  | 0 | 0x80c62480 | 0x80c635e0 | **0x0** (no render bits set at all) |
  | 1 | 0x80c63ea0 | 0x80c64b80 | 0x20000000 (JOBJ_ROOT_XLU) |
  | 2 | 0x80c65160 | 0x80c65a60 | 0x20000000 (JOBJ_ROOT_XLU) |
  | 3 | 0x80c65ec0 | 0x80c69080 | 0x30000000 (ROOT_OPA\|XLU) |
- **Candidate A** — cleared `0x701C0000` on the root JObj of slots 0/1/2, held
  live over ~20 frames, **readback confirmed flags = 0x0 at capture time**
  (`30-A-readback.png`). Sparkles STILL present. Slot 0 already had flags=0 so
  there was nothing to clear there in the first place.
- **A/B per slot** (`10-slot{0,1,2,3}-cleared.png`): no individual slot clear
  removed the sparkles; if anything the twinkle count varied frame-to-frame
  (they animate), which is the only difference between shots.
- **Negative control caveat:** the doc expected slot 3 to blank the *platform*.
  Under `--plain-bg` ("No Stage Textures") the FD platform surface is already
  invisible (flat gray), so slot-3 clear produced no obvious visual delta —
  the negative control is **inconclusive under plain-bg** and cannot confirm
  the mapping. The decisive criterion (do sparkles vanish?) failed regardless.
- **Candidate B** — root bits cleared + `JOBJ_HIDDEN (0x10)` set on the child
  chain of slots 0/1/2 (`31-B-hidden-children.png`): sparkles STILL present.

Interpretation: clearing the render mask on these four `x180[]` GObj roots (and
hiding their children) does not stop the drifting stars, so the sparkles are
**not** drawn through `stage_info.x180[0..2]` as §1 hypothesized — they are
submitted by some other render path (e.g. a separate GObj not in `x180[]`, a
different render class/gxlink, or geometry deeper in the tree not reached by the
root-flag mask). The static analysis mechanism (§1) is **wrong or incomplete**.
The writes provably stuck (readback), so this is a mapping/mechanism miss, not a
flaky poke.

Next steps if this is picked up again (all UNVERIFIED):
- Live-enumerate ALL stage/background GObjs (not just `x180[]`) — e.g. walk the
  gobj_list for the stage's gobj class and A/B each, or diff the RAM/JObj set
  between a stage WITH visible sparkles and one without.
- Candidate C (patch `GrNLa.dat` in the ISO) is now the more promising route
  since the RAM-side hypothesis about which GObjs own the stars was wrong —
  but the star geometry/material must first be positively identified in the DAT
  (HSDRaw), not inferred from the `x180[]` slot labels.

---

## 1. Mechanism

### FD is `grlast.c` / `grNLa`, handled generically by `ground.c`

- `StageData grNLa_803E7F90` (`src/melee/gr/grlast.c:151`) — file `"/GrNLa.dat"`,
  `OnInit = grLast_OnInit`.
- `grLast_OnInit` (`grlast.c:167`) creates the persistent stage GObjs:

  ```c
  grLast_8021A7F4(0);   // background anime layer  (StageCallbacks[0])
  grLast_8021A7F4(1);   // background anime layer  (StageCallbacks[1])
  grLast_8021A7F4(2);   // background anime layer  (StageCallbacks[2])
  grLast_8021A7F4(3);   // "map type" = the platform + collision line binding
  ```

  Callback table `grLast_803E7EBC` (`grlast.c:76`) labels 0/1/2 as
  "generic anime gobj" and 3 as "map type". GObjs 4–9 are **only** created during
  the Master Hand boss transform (`grLast_8021B920`, `grlast.c:727`) and event
  match #50 — they never exist in a normal VS match.

### The "stars" are animated JObj geometry, NOT an HSD particle system

- The **only** ptcl generator in `grlast.c` is `grLib_801C96F8(0x7531, …)`
  (`grlast.c:811`, inside `grLast_8021B920` **case 9**). That case is gated behind
  `Stage_80225194() == 0xB0` (Master Hand boss) / `0xFB` (Event #50)
  (`grlast.c:524`). In VS mode it is never reached.
- FD does **not** call `psInitDataBankLoad` for a background sparkle bank; the
  generic hook at `ground.c:481` only fires if `stage_info.map_ptcl` is non-NULL,
  which is the adventure-mode enemy generator, not FD's backdrop.
- Therefore the drifting sparkles are small textured quads in the `GrNLa.dat`
  **background model layers**, drawn every frame through GObjs 0/1/2 and animated
  by their material/texture anim. They are ordinary JObj→DObj geometry.

### Why Achilles' "No Stage Textures" leaves them visible

`assert_plain_bg` (`backend/devtools/frameshot.py:110`) writes:

- `0x80452C70 = RRGGBB00`  — flat background clear color (Camera background).
- `0x80453000 = 0x00C40000` — Achilles' "No Stage Textures" render-flag word.

The "No Stage Textures" code forces stage **materials** to render untextured; it
does **not** remove geometry. The star quads still get submitted, now as flat
untextured sprites — which is exactly the residual "small colored/gray sparkle"
symptom. The flat clear color only paints the empty backdrop *behind* them.

### Exact render path (where a hide takes effect)

Each FD stage GObj is set up with a GX render link:

```
grLast_8021A7F4()  -> GObj_SetupGXLink(gobj, grDisplay_801C5DB0, 3, 0)   grlast.c:206
```

Per frame:

```
grDisplay_801C5DB0(gobj, code)                       grdisplay.c:74
  -> HSD_GObj_JObjCallback(gobj, code)               grdisplay.c:129 (non-b5 path)
       jobj = gobj->hsd_obj                          gobj.c:209
       -> HSD_JObjDispAll(jobj, NULL,
                          HSD_GObj_80390EB8(code), 0) gobj.c:215
```

`HSD_JObjDispAll` (`jobj.c:571`) for a **non-instance root** draws only when the
render mask matches the root JObj's flag bits:

```c
if (jobj->flags & (flags << 0x12)) HSD_JObjDisp(jobj, ...);      // self  -> bits 18..
if (jobj->flags & (flags << 0x1C)) { walk children DispAll; }    // kids  -> bits 28..
```

`flags` = `HSD_GObj_804085F0[code]`, the small trsp mask (OPA=1/XLU=2/TEXEDGE=4).
`flags << 0x1C` tests the JObj **root render bits** `JOBJ_ROOT_OPA/XLU/TEXEDGE`
(`1<<28 / 1<<29 / 1<<30`, `jobj.h:96`). `flags << 0x12` tests bits `1<<18..`.

**Key consequence:** if we clear those root bits on a GObj's root JObj, *both*
the self-draw and the child-walk masks miss → the entire subtree stops rendering
— while `Ground_801C1CD0`'s `HSD_JObjAnimAll` and matrix setup (`jobj.c:562`,
which don't depend on those bits) keep running safely, and collision is untouched
(see risks). Note `JOBJ_HIDDEN` (`1<<4`) is **not** sufficient here: `HSD_JObjDisp`
(`displayfunc.c:486`) and the non-instance branch of `HSD_JObjDispAll` never test
`JOBJ_HIDDEN` on a root — only the `JOBJ_INSTANCE` branch does (`jobj.c:576`,
`grdisplay.c:35`). The game's own anim-driven hide (`HSD_JObjSetFlagsAll(jobj,
JOBJ_HIDDEN)`, `jobj.c:428`) only works because it targets *child/instance* nodes.

### Collision is independent of these GObjs' rendering

Collision data is loaded once, globally, via `mpLibLoad(stage_info.coll_data)`
in `Ground_801C0800` (`ground.c:485`) — not through any GObj's render callback.
`Ground_801C2ED0` (collision-line binding, `ground.c:1654`) runs in the map GObj's
**init** callback `grLast_8021A9C4` (`grlast.c:274`, GObj 3), and per-frame
`Ground_801C2FE0` runs from its logic proc, not its render proc. Suppressing a
GObj's *rendering* therefore cannot break collision, camera bounds, or blastzones.

---

## 2. RAM addresses / pointer chain

Symbols (from `config/GALE01/symbols.txt`):

- `stage_info = 0x8049E6C8` (`.bss`, `symbols.txt:25800`), struct `StageInfo`
  (`src/melee/gr/types.h:58`).
- `stage_info.x180[4]` at offset `+0x180` → **`0x8049E848`**; an array of 4
  `HSD_GObj*` (`types.h:86`). `Ground_801C2BBC(gobj, map_id)` stores
  `x180[map_id] = gobj` (`ground.c:1561`), so:

  | slot | RAM address of the `HSD_GObj*` | FD role |
  |------|-------------------------------|---------|
  | `x180[0]` | `0x8049E848` | background anime layer (sparkles) |
  | `x180[1]` | `0x8049E84C` | background anime layer (sparkles) |
  | `x180[2]` | `0x8049E850` | background anime layer (sparkles) |
  | `x180[3]` | `0x8049E854` | **platform** (map/collision) — KEEP |

Struct offsets to reach the root JObj flags:

- `HSD_GObj +0x28` = `hsd_obj` (root `HSD_JObj*`) (`gobj.h:41`).
- `HSD_JObj +0x14` = `u32 flags` (`jobj.h:112`).

So to hide FD background layer N (N ∈ {0,1,2}) at match time:

```
gobj  = read_u32(0x8049E848 + 4*N)     # HSD_GObj*
if gobj == 0: skip                     # not yet created / not this stage
jobj  = read_u32(gobj + 0x28)          # root HSD_JObj*  (hsd_obj)
if jobj == 0: skip
flags = read_u32(jobj + 0x14)
write_u32(jobj + 0x14, flags & ~0x7C0000 & ~0x70000000)
#   clears (0x7<<18)=0x001C0000  (self-disp mask bits 18..20)
#   and    (0x7<<28)=0x70000000  (JOBJ_ROOT_OPA|XLU|TEXEDGE, child-walk mask)
```

Clearing `0x701C0000` on the root makes every render pass' mask miss for that
subtree. Anim/matrix procs are unaffected. Re-assert after READY/GO like the
existing plain-bg pokes (stage load can rebuild the tree; late writes are safe).

---

## 3. Ranked candidate interventions

### Candidate A (RECOMMENDED) — clear root render bits on `x180[0..2]`

- **What:** for N=0,1,2, follow `x180[N]` → `hsd_obj` → `flags`, clear
  `0x701C0000`.
- **Widths/values:** three `read_u32` (chase pointers) + one `write_u32` each
  (`flags &= ~0x701C0000`). Guard against NULL at each hop.
- **When:** after READY/GO (same point as `assert_plain_bg`), re-assert each
  frame before capture.
- **Pros:** purely additive to the existing poke path; only touches non-collision
  background layers; leaves the platform (slot 3) fully intact; no ISO edit.
- **Cons:** slot→layer mapping (0/1/2 = background) is inferred from the callback
  table labels + boss-only usage of 4–9, not yet live-verified. If a live check
  shows the platform's *visible surface* is actually one of 0–2, back off that
  slot. (Mitigation: A/B each slot individually first — see §5.)
- **Risk:** LOW. Cannot affect collision/camera/blastzones (§1). Worst case a
  wrong slot hides part of the visible platform — cosmetic, reversible, and
  caught immediately by the before/after screenshots.

### Candidate B (fallback, also RAM) — JOBJ_HIDDEN on children of `x180[0..2]`

- If A under-hides (root has drawable DObjs on child nodes only), walk
  `jobj->child` (`+0x10`) chain and set `JOBJ_HIDDEN` (`0x10`) on each, which the
  instance/child branch honors. More pointer-chasing; only needed if A leaves
  residue. Prefer A first.

### Candidate C (file-patch fallback) — neutralize the sparkle layer in `GrNLa.dat`

- Only if RAM proves flaky. `GrNLa.dat` root map JObj → the DObjs for the
  background layers. Two sub-options, applied to the **ISO copy** of `GrNLa.dat`:
  1. Zero the root-render flag bits (`0x70000000`) on the specific background
     JObj(s) in the file's JObj headers — same effect as A, baked in.
  2. Set the sparkle material's alpha/enable so the quads render fully
     transparent.
- **Cons:** requires resolving on-disk DAT offsets for the exact JObj/material
  (HSDRaw inspection of `GrNLa.dat`), and edits the shipped stage file. Higher
  effort, more fragile across ISO variants. Use only if A and B both fail.
- Offsets are **not** hard-coded here on purpose: they must be read from the
  actual `GrNLa.dat` in the target ISO with HSDRaw (the map JObj tree under the
  archive's scene root), since they are file-relative, not fixed RAM addresses.

---

## 4. Draft plain-bg patch (DO NOT APPLY — wire after live validation)

Drop-in extension of `assert_plain_bg` in `backend/devtools/frameshot.py`. Only engages on
FD; other stages are unaffected. `d.read_u32` / `d.write_u32` already exist on the
`Dolphin` object used by the harness.

```python
# Final Destination (internal id LAST) background "star" layers live at
# stage_info.x180[0..2]; slot 3 is the platform (keep). Clearing the root
# JObj render bits stops the subtree from drawing without touching collision.
# See research/docs-research/fd-star-particles.md.
_FD_STAGE_GOBJ_TABLE = 0x8049E848      # stage_info(0x8049E6C8) + 0x180
_FD_BG_SLOTS = (0, 1, 2)               # background anime layers; 3 = platform
_JOBJ_RENDER_BITS = 0x701C0000         # (0x7<<28) root OPA|XLU|TEXEDGE + (0x7<<18)

def hide_fd_background(d):
    for n in _FD_BG_SLOTS:
        gobj = d.read_u32(_FD_STAGE_GOBJ_TABLE + 4 * n)
        if not gobj:
            continue
        jobj = d.read_u32(gobj + 0x28)          # HSD_GObj.hsd_obj
        if not jobj:
            continue
        flags = d.read_u32(jobj + 0x14)         # HSD_JObj.flags
        d.write_u32(jobj + 0x14, flags & ~_JOBJ_RENDER_BITS)
```

Call it right after each `assert_plain_bg(d, args.plain_bg)` (only when the stage
is FD), e.g. inside the capture loop:

```python
if args.plain_bg:
    assert_plain_bg(d, args.plain_bg)
    if args.stage == "finaldestination":
        hide_fd_background(d)
```

---

## 5. How a later Dolphin slot should validate

1. Boot FD `--plain-bg` **vanilla** (no new poke). Screenshot: confirm the flat
   gray backdrop still shows the drifting sparkles (baseline of the problem).
2. **A/B each slot individually first** to confirm the 0/1/2 = background mapping
   and that slot 3 is the platform: apply the flag-clear to only `x180[0]`, cap;
   then only `[1]`; then only `[2]`; then only `[3]` (expect [3] to blank the
   *platform* — the negative control). Compare the four shots.
3. Apply the full Candidate A poke (slots 0,1,2) after READY/GO, re-assert each
   frame, screenshot. **Pass = sparkles gone, platform intact.**
4. Sanity: run a normal move capture on FD plain-bg and confirm the fighter,
   collision behavior (character stands on the platform), and effect colors are
   unchanged vs the sparkly baseline.
5. If A leaves residue → try Candidate B (JOBJ_HIDDEN on children) on the same
   slots. If RAM is unreliable → Candidate C (patch `GrNLa.dat` in the ISO).

---

## Summary

- FD's VS-mode background sparkles are **animated background JObj geometry**
  (GObjs 0/1/2 in `grlast.c`), not an HSD particle bank — so Achilles'
  "No Stage Textures" flag strips their textures but still draws the quads.
- **Top candidate (A):** at match time, chase
  `stage_info.x180[N] (0x8049E848+4N)` → `+0x28 hsd_obj` → `+0x14 flags`, and
  clear `0x701C0000` for N ∈ {0,1,2}. Stops the subtree rendering; leaves the
  platform (slot 3), collision, camera, and blastzones untouched. Re-assert after
  READY/GO alongside the existing plain-bg pokes.
- Fallbacks: JOBJ_HIDDEN on child nodes (B), or an ISO-side `GrNLa.dat` flag/alpha
  edit (C).
