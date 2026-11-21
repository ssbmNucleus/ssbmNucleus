# Debugging CSP / portrait render bugs

> **Note (2026-08-22):** `xrun_shots.py` referenced below was removed in the cleanup pass (git history has it).

When a character-select portrait (CSP) or stock icon renders wrong — black blob, white
blob, missing part, blank, wrong eyes — this is the repeatable workflow to localize and
fix it. It came out of the xrunriot batch (Vader/Link-Fox/Tails) and the vault batch
(Slippy/Falcon/Mario/Luigi/Marth).

## The pipeline (what produces a CSP)

```
generate_csp.py  →  HSDRawViewer.exe --csp <dat> <out.png> [--scale N] [--head-bone B]
                    [--hide-dobjs a,b,c] [anim.anim] [scene_or_camera.yml]
```
- Renderer source: `<ssbmNucleus-hsdlib>/HSDRawViewer/` (C#, OpenGL). Dev exe:
  `bin/Release/net6.0-windows/HSDRawViewer.exe`. Rebuild: `dotnet build … -c Release`.
- Shaders are RUNTIME assets in `…/bin/Release/net6.0-windows/Shader/` (editable without a
  C# rebuild), copied from the source `Shader/` on build.
- The canonical wrapper that the app calls is `backend/shared/rendering/costume_assets.py`
  `build_csp_and_stock`; `generate_csp.generate_csp(dat)` is the same render path.
- Renderer logs: each one-shot `--csp` process writes `csp_debug_<pid>.log` and each
  `--csp-server` pool worker writes `csp_server_<pid>.log` into `%TEMP%`, which in the app is
  the data folder's `scratch/`. A clean render's log is deleted when its process exits; a failed
  one's is kept (the path is in the CSP log) for a few days, then the backend's start sweeps it
  (`utility/tools/processor/csp_logs.py`).
- Hiding: a curated scene `.yml` carries baked `hiddenNodes`; otherwise `low_poly_dobjs()`
  derives the hide set from the **vanilla** `Pl<XX>.dat` ftData. `--hide-dobjs` is
  AUTHORITATIVE and *replaces* scene `hiddenNodes` (pass `--hide-dobjs 9999` to disable all
  hiding — a no-op index).

## ⚠️ Use the INSTALLED vault, not the repo

The costumes the user sees live in the installed app vault
`%LOCALAPPDATA%\SSBM Nucleus\storage\<Character>\<slot-id>-<costume>.zip` (each zip =
`Pl*Mod.dat` + `csp.png` + `stc.png`). The repo `storage/` is a separate dev copy and often
holds *different* (sometimes working) versions — diagnosing it gives false results.

## The loop

1. **Reproduce on the right file.** `python utility/tools/processor/csp_debug.py "Char/slot-id"`
   resolves the installed-vault zip, extracts the DAT, probes it, and renders it three ways
   (normal / no-hide / bundled-current) into `csp_debug_out/<slot>/`.
2. **Get ground truth.** Compare to the bundled `csp.png` and, when needed, to the model
   in-game (boot it solo — see `backend/shared/ingame/README.md`). A render
   that's right in-game but wrong in CSP ⇒ the renderer mishandles valid data, not a bad DAT.
3. **Read the probe** (see cause table). The decisive splits:
   - normal broken but **no-hide fixes it** ⇒ over-hiding (cause D).
   - **UNDECODABLE > 0** ⇒ white blobs on those parts (cause E).
   - many TLUTs sharing few pixel-blobs ⇒ swatch model (cause A).
   - has `mexCostume` accessories and one's missing ⇒ cause B.
   - grey/blank eyes + has matanim ⇒ cause C.
   - blank even with no-hide ⇒ geometry not drawn (cause F).
4. **Fix in HSDRawViewer**, `dotnet build -c Release`, re-render with `csp_debug.py`, compare.
5. **Regression-check** vanilla + an unrelated costume (the render path is shared).
6. The app bakes CSPs at import; existing costumes need their CSPs **regenerated**
   (Manage CSPs / re-import) to pick up a renderer fix.

## Tools

- `utility/tools/processor/csp_debug.py` — probe + render + heuristic diagnosis (above).
- `backend/shared/rendering/datprobe.py` — pure-Python DAT reader (roots, JOBJ/DObj/TOBJ walk,
  `decode_image`, matanim tex-anims). Ground truth for "what does this DAT actually contain".
- Texture montage / material-color probes: see the snippets in `csp_debug.py` (`probe()`),
  reusable for ad-hoc digs.

## Known cause classes

| # | Symptom | Root cause | Status |
|---|---------|-----------|--------|
| A | Black/colored blob; many textures but few unique pixel-blobs + many TLUTs | Palette-"swatch" model (each part = a 5×5 single-color CI8, real color in its TLUT); exporter dedupes identical pixel blobs; the GL texture cache keyed on image-bytes-only collapsed them to one decode → first palette everywhere | **FIXED** — cache key = `(imageData, tlutData)` in `RenderJObj.cs` |
| B | Missing cap / Navi / cape / companion | m-ex costume accessory in `MEX_CostumeSymbol.Accessories[]`; `--csp` only rendered the main `_Share_joint` | **FIXED** — splice each `RootJoint` + follow its `AttachBone` delta in `Program.cs` |
| C | Blank / grey eyes | Real eye only in the separate `*_matanim_joint`; CSP applied no matanim | **FIXED** — matanim applied at frame 0 across all three `LoadAnimation` paths |
| D | A body part or the whole model is missing, but its textures decode fine | Over-hiding: scene `hiddenNodes` / `low_poly_dobjs` come from **vanilla** `Pl<XX>.dat` and are wrong for a custom / reordered model | OPEN — make the low-poly hide set robust for non-vanilla geometry |
| E | White blobs on specific parts (fur, mask…) | Those textures are UNDECODABLE → `PreLoadTexture` skips them → the material's white shows through | rare — C# decodes most; usually really cause G |
| F | Model renders blank / only a stray part, even with hiding disabled, but POBJ pointers exist in the DAT | **POBJ attribute list missing its `GX_VA_NULL` terminator** → `GX_DisplayList.Open()` reads ZERO primitives → no geometry. Common in imported / re-exported models | **FIXED** — `RenderDObj.cs` appends the terminator instead of discarding the pobj |
| G | Model renders a flat white / dark silhouette (form correct, no texture detail) | The costume's body material carries **more TObjs than its RenderMode TEX0..7 bits** (real skin is a shared atlas past the flagged units) and/or `DF_ALL` force-enables phantom (unbound) units → the shader sampled the wrong / an empty unit → flat white (atlas ignored) or black (unbound-unit TEV combine). The *original* "multi-tex/`GX_TG_NRM` texgen" theory here was a wrong turn. | **FIXED** — `RenderJObj.SetupMObj` forces `hasTEX[i]` for every LOADED TObj and gates the per-unit init by texture COUNT |
| H | A specific layered part (metal armor, pauldrons, trim) renders **flat grey / solid**, replacing the real skin under it | Material stacks a `MODULATE` skin + an **`RGB_MASK`** detail/tint TObj whose **alpha is opaque**. The shader implemented `RGB_MASK` identically to `ALPHA_MASK` — `mix(prev, tex.rgb, tex.a)` — so opaque alpha made the mask fully REPLACE the skin. GX (`tobj.c` `HSD_TExpColorIn`) mixes `RGB_MASK` by the texture's own **RGB per-channel** (`out = prev*(1-tex.rgb) + tex.rgb²`), not alpha. | **FIXED** — `gx_lightmap.frag` `RGB_MASK` case mixes by `pass.rgb` |

Diagnostics: set `CSP_DOBJ_DEBUG=1` in the env before rendering — the renderer then logs a per-render DObj breakdown (`[cspdbg] dobjs=.. noPobj=.. hidden=.. opaPass=.. neither=..`), POBJ build skips, `[texfail]`/`[texdbg]` per texture, and `EnableBuffers FAILED`. Invaluable for D/E/F/G.

Fixed-cause details: see the `csp-renderer-edge-case-fixes` memory.

## Vault batch (installed vault, 2026-06-29)

| Costume | Symptom | Cause | Status |
|---|---|---|---|
| Fox `shitslippy-plfxsp` (Slippy) | only the blaster rendered | F (POBJ no NULL terminator) | **FIXED** |
| Luigi `pllgpg-pllgpg` | blank | F (POBJ no NULL terminator) | **body FIXED**; eyes still wrong (G) |
| Falcon `plcagr-plcagr01` (Ryu) | flat white silhouette | G (atlas past RenderMode TEX bits) | **FIXED** (hasTEX force) |
| Mario `plmrnr-plmrnr01` | flat black silhouette | G (`DF_ALL` phantom units) + H (`RGB_MASK` grey overcoat) | **FIXED** |
| Marth `plmsgr-plmsgr01` (Lyn) | dark body + flat-grey pauldrons/armor | G (hasTEX) fixed the body/mask; **H (`RGB_MASK` alpha vs rgb)** the grey armor | **FIXED** |

Cause **G** (flat white/dark body) was resolved by the `hasTEX` fixes (see the memory). The
remaining flat-grey **armor / pauldrons** on the Marth "Lyn" skin and the black overcoat on
`plmrnr` were cause **H**: the `RGB_MASK` colormap op was mixing by the texture's alpha instead
of its RGB (per the decomp), so an opaque grey/tint mask fully replaced the skin beneath.
Whole-vault scan: only **4 costumes** use `RGB_MASK` (`plmsgr01/10`, `plmrnr01/09`) — **zero
vanilla** — so the shader fix is safe; all 4 render correctly now. Re-render (Manage CSPs /
re-import) to apply; the packaged app needs a `build.bat` rebuild to ship the shader.
