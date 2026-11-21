# Common shield bubble — EfCoData.dat mapping spec

MAP 2026-07-10. Target: the cast-shared shield bubble visual (hold L/R —
Guard states 178/179). Companion to `efcodata.md` (ptcl/electric findings);
this is a MODEL-REGION texture finding, quarantined here per the template's
"EfCoData findings get their own section" rule.

## Verdict (MAP-STATIC, verified by 3 reference-mod diffs)

The shield bubble's editable data is ONE texture:

| thing | value |
|---|---|
| target file | `EfCoData.dat` (cast-shared common effect bank) |
| image data | file offset **0x104320**, size **0x8000** (32768 bytes) |
| format | **IA8** (GX fmt 3) — intensity+alpha, **no hue** |
| dimensions | 128×128, no palette |
| ImageDescs | **10** headers point at this one image (ptr `0x104300` = data-section offset): file offsets 0x1166B0, 0x117110, 0x1171D0, 0x117290, 0x117350, 0x117410, 0x1174D0, 0x117590, 0x118528, 0x118B44 — all `{w=128, h=128, fmt=3}` |
| vanilla md5 (whole file) | 739290ead708aeb98bd5118c1abe4a34 |

Decoded vanilla texture = the familiar gray sphere with top specular
highlight (see scratchpad decode; classic bubble look).

**The bubble COLOR is not in the DAT.** IA8 carries no hue; the per-port
red/blue/yellow/green (and team) tint is applied engine-side (DOL decides
by port/team — smashboards thread post #33, and no color operand exists in
the region). So `common_shield` is a **texture-replacement extra, not a
color extra**. The Animelee screenshot confirms: modded texture, tint still
per-port.

**Yoshi exception:** Yoshi has no bubble — his shield is the egg (own model
+ textures in `PlYs*.dat`, see website post 2936 "Multicolored Egg
Shields"). Exclude Yoshi from `sharedWith`.

## Reference mods (all confirm the extent)

All three full-DAT community mods are vanilla-sized and change bytes ONLY
inside `0x104320..0x10C320`:

| mod | source | diff |
|---|---|---|
| Animelee Shields (post 2962/wp19520) | `ssbm-backup\uploads\posts\2022\04\post_15776\EfCoData.dat` | 37 regions, first 0x104454 last 0x10C201 |
| Grab Me! Shield (post 1201/wp5414) | `...\2020\10\post_14015\EfCoData(grab me! shield).dat` | 20 regions, 0x105CBE..0x10A989 |
| Smash 4 style shield (post 4050/wp30663) | `...\2024\01\post_16864\EfCoData sm4sh sheild.dat` | 27529 bytes, 0x10445C..0x10C1E2 |

None touches the ImageDesc headers (no format flip to a colored format —
RGB5A3 would be size-compatible at 16bpp but no reference mod does it; keep
IA8 in scope, treat format-flips as out of scope).

“Neon simple shield” (post 3533/wp25365) ships a DTW-named texture
`EfCoData.dat_0x104320_3.psd/png` — DTW naming = `<file>_0x<image data file
offset>_<GX fmt>`, independent confirmation of offset+format. Many other
website “shield” mods are Dolphin texture packs (`tex1_*.png`) — out of
scope (not DAT data).

## MAP-LIVE verification (2026-07-10) — VERIFIED ✅

Live RAM poke via `effect_probe.py` (new `fill`/`copy` block-poke forms) +
new `shield` move recipe in `ingame/moves.py` (hold L; a digital L press on
the frozen-step pipe lands in GuardReflect 182 first, so the recipe accepts
the whole Guard family 178–182; L stays HELD past execute() so the bubble
survives the capture frames). One boot, Fox solo on FD, plain bg
(`backend/probes/common_shield_probe.json`):

- `vanilla` control: classic soft red-tinted bubble (P1 port tint).
- `solid_disc` (memset 0xFF over 0x104320+0x8000): bubble became an OPAQUE
  WHITE SQUARE with a circle outline — the full 128×128 quad shows, proving
  both intensity AND alpha of the bubble come from this one texture.
- `animelee_texture` (region copy from the Animelee mod): clean anime-style
  rim ring, flat interior — and STILL port-red, re-confirming the tint is
  engine-side, not in the texture.

Captures: `<repo-parent>/tests/artifacts/datram-probe-common-shield/`.
No Dolphin texture-cache masking observed (full-region pokes change the
texture hash; captures updated live within the same boot).

Final verify (2026-07-10) — ✅ EYEBALL-VERIFIED: `extras_audit.py --char Fox
--extra common_shield` (the new `_patch_texture_region` checkerboard mirror)
→ in-game the bubble renders the exact 16px checker pattern as a full square
(alpha 255 everywhere), red port-tint modulating it — vs the vanilla soft
sphere control. Captures `tests/artifacts/extras-audit/Fox-common_shield/`
(+ `-vanilla/` control, both f2/6/12/20).

⚠ First build attempt produced a CORRUPT ISO (mexcli reported success, FST
string table garbage, boot hang) — root cause was C: **disk full**, not the
patch. mexcli does not fail loudly on ENOSPC; check free space when an
export boots to nothing.

## Wiring notes (for WIRE)

- New format `texture_region` (not `texture_recolor` — no palette/hue; not
  `type: texture` — no HSDRawViewer node path needed, plain byte region):
  install copies the region bytes from a stored mod DAT (or PNG-encoded
  IA8) into the target; restore-vanilla copies the vanilla region back.
- Offset safety: before writing, verify the target still has an ImageDesc
  `{ptr, 128, 128, fmt 3}` consistent with the region (re-saved DATs shift;
  relocate by scanning ImageDescs for a 128×128 fmt-3 entry whose data
  extent has the vanilla prefix, else skip loudly — same philosophy as
  `relocate.py`).
- Import: website effect path (`mod_type=effect`, `effect_type=shield`)
  already stores the raw DAT under `<owner>/models/<mod_id>.dat`; the
  install branch reads the SAME region out of the stored DAT. DTW-named
  loose PNG/PSD posts are texture-only; PNG import = IA8 encode of a
  128×128 grayscale+alpha image.
- Owner: Fox (cast-wide precedent, `jab_finisher_spark`); sharedWith =
  whole selectable roster minus Fox minus Yoshi (egg, not bubble).
- AUDIT_HINTS: any char, move `shield`, frames ~8–20 (bubble fully out;
  GuardOn is 178, full Guard 179); `--plain-bg` fine (bubble is additive
  over the fighter).
- Editor: no color pickers — texture preview + mod cards + restore
  vanilla. Preview should draw the gray bubble and note the per-port tint
  honesty rule (tint NOT editable).

## Open leads (not blocking)

- What the OTHER 9 ImageDescs draw (shield-break flash? reflect bubble?
  star-KO?) — all 10 share the one image, so any consumer recolors with it;
  live pass only verified the Guard bubble. Honest description says
  "shield bubble (and other bubble-type visuals drawing the same shared
  texture)".
- PlCo.dat "shield colors" community claim (2012): not substantiated for
  the bubble visual; the bubble tint didn't come from EfCoData; if a future
  mission wants per-port tint editing it should look at the DOL color
  table, not the DATs.
