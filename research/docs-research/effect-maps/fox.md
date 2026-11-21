# Fox — Firefox charge and flight fire

**September 9 correction:** `upb_charge_fire` is the flight-puff texture, now
labeled **Flight Fire Texture** with stored ID unchanged. Actual Fox charge
flames are EfCo scripts 299/300, live-confirmed and wired separately as
`charge_flames`. See the correction report (retired, git history before 2026-10-03)
for traces, isolated captures, and exact native operands. July charge
attributions below are historical and superseded.


Scope: EXTRAS_AUDIT task #3, "Firefox charge fire color" (the central ptcl
fire clumps the texture CLI can't reach). Everything else Fox/Falco
(laser/shine/sideb/upb layers) is already mapped/shipped — see
`docs/EXTRAS_AUDIT.md` and `fox-falco-shine-sparkles.md`. Shared file:
`EfFxData.dat` (Fox + Falco).

## Decomp mechanism (corrected September 9)

- CHARGE: `efSync_Spawn(1163)` -> `efLib_Create_Attach(3003)` loads
  **Model 3**, whose track-0x28 event emits particle **3010** (charge lines).
- LAUNCH: `efSync_Spawn(1164)` -> `efLib_Create_Attach(3004)` loads
  **Model 4**, whose track-0x28 event emits particle **3004**. That generator
  spawns scripts 5/6/7/9; scripts **5/9** use EfFx texture **group 3**.
- Actual charge flames: PlFx `SpecialHiHold` action 307 requests common gfx
  **298** at animation frame 15; that spawns EfCo **299/300/301** (broad
  flames, thin wisps, and gray smoke). Air hold goes to the same script.
- `efLib_Create_Attach`'s model index is **not** a particle-script index.
  The old direct `3003 = script 3` interpretation caused the false charge
  attribution. Model animation and fighter-subaction traces are required.
- Ground-bounce: `efSync_Spawn(1030)` (common bank).

## LIVE results (2 boots, solo Fox, FD plain-bg, `upb` f4–f70;
captures `tests/artifacts/probe-firefox-charge/` + `probe-firefox-charge2/`;
specs `backend/probes/firefox_charge_probe.json` / `firefox_charge_probe2.json`)

### ✅ FOUND: the MID-FLIGHT central fire clumps = ptcl scripts 5+9
= (almost exactly) the SHIPPED `upb.trail` layer

Poking script 5 whites green + script 9 whites magenta turned the entire
central billowing fire-clump column GREEN with MAGENTA wisps at f50/f60/f70
(green px 0→19520/21909/21356 vs vanilla; judged visually: the big puffs =
s5, the smaller intermediate wisps = s9), while the outer streamer cone
(upb_texture's Models_4) and lens flare stayed orange. Evidence:
`s5_green_s9_magenta-upb-f50/60/70.png` vs `vanilla-upb-f60.png`.

| record | offsets (color operand) | vanilla | shipped? |
|---|---|---|---|
| s5 head | 0x2F0 | `FFFFFFC8` | ✅ `trail` (CF marker 0x2EE) |
| s5 fade | 0x2F6 | `FFFFFF32` (count 24) | ✅ `trail` (0x2F4) |
| s5 mid | 0x326 | `FFFFFF64` (count 8) | ✅ `trail` (0x324) |
| s5 tail | 0x32D | `FFFFFF00` (count 8) | ✅ `trail` (0x32B) |
| s9 head | 0x530 | `FFFFFFC8` | ✅ `trail` (0x52E) |
| s9 fade | 0x536 | `FFFFFF32` (count 24) | ✅ `trail` (0x534) |
| **s9 tail** | **0x560** | **`FFFFFF00` (count 6)** | **❌ NOT in `trail` — WIRE should add it** |

**Correction to the audit record:** the upb_texture EYEBALL note claimed
"the central ptcl fire clumps remain the documented CLI-unreachable
bitmap". WRONG for mid-flight — the flight clumps recolor TODAY via the
existing `upb.trail` color layer (proven above). The only gap is the one
missing record 0x560 (same script-9 family, byte-white vanilla like its
siblings), which the s9 magenta poke visibly bound along with 0x530/0x536.

**WIRE action (mechanical):** append `0x55E` to `upb.trail.offsets` in
BOTH config mirrors (`backend/core/extra_types.py` + `frontend/src/config/
extraTypes.js`) — the layer stores CF-marker positions (color at +2), and
the CF marker for the 0x560 operand is at 0x55E. No editor change (trail
is an existing picker). Verify: `python devtools/extras_audit.py --char Fox
--extra upb --colors trail=00FF00` and check the flight clump column at
upb f50-70 goes fully green with no white/orange ptcl puff residue.

### Shipped: Flight Fire Texture (`upb_charge_fire`, EfFx group 3)

The stored ID retains its July name for compatibility. The menu name and
verification hint are corrected to **Flight Fire Texture**, up-B 50/60/70.
This edits the eight-frame CI8 32x32 puff bitmap used during flight by
scripts 5/9. The `upb.trail` controls tint these same puffs; nested
`upb_texture` changes separate model streamers.

Group 3's file layout remains: header `0xD680`; images
`0xD6E0/0xDAE0/0xDEE0/0xE2E0/0xE6E0/0xEAE0/0xEEE0/0xF2E0`;
RGB5A3 palettes `0xF6E0/0xF8E0/0xFAE0/0xFCE0/0xFEE0/0x100E0/0x102E0/0x104E0`.
Vanilla dominant hue is 35.7 degrees. The September combined export retained
all 2,582 cyan palette-byte changes at those addresses, with image indices
unchanged. The old charge attribution was incorrect, including the later
claim that cyan merely blended to red.

### Shipped: Fox Charge Flames (`charge_flames`, EfCo scripts 299/300)

The main session independently recolored script 299's broad puffs cyan and
script 300's thin wisps green during charge; Falco did not show this family
in baseline or probe. Four RGB keys (`flame_c1`, `flame_c2`, `wisp_c1`,
`wisp_c2`) are exposed only for Fox. Smoke script 301 remains unchanged.
Exact restore uses native reference bytes at each operand, not representative
group swatches. The correction report has all fourteen offsets and capture
paths. Audit hint: up-B 18/25/32.

### Historical July dead-poke results (wrong bank for charge flames)

Every color-bearing EfFxData script was live-poked with strong anti-colors
against the charge window (f4–f40, two boots):

| script | records poked | result on charge |
|---|---|---|
| s3 (mistakenly equated with charge Model 3) | 0x240/0x247/0x24D (white prim / `D7FBFF` env / white) | no visible delta f4–f40 (both boots) |
| s0 (3000) | 0x127/0x12E/0x143 | slight magenta shift in the lavender charge streaks (f18 mag 441 vs 46) — streak tint only, NOT the fire clumps |
| s2 (3002) | 0x1E0/0x1E7 | nothing |
| s5+s9 | (trail) | flight-only; zero effect during charge |
| s6 (= shipped `small_trail`, the only ORANGE-valued records) | all 10 | nothing during charge |
| s7 (= shipped `dots`) | all 4 | nothing during charge |
| s8 (grey prim + blue env; suspected smoke) | 0x4AB/0x4B2/0x4B8 | nothing |
| s10 (= shipped `charge_lines`) | already shipped/verified | (not re-poked) |

The July conclusion that charge orange must be baked into EfFx textures is
superseded. Those probes found no charge-flame response in EfFx, but the
missing family was **EfCo scripts 299/300**, not another EfFx texture group.
No dead verdict here applies to those common scripts.

Open leads (unpoked, low priority): s0's streak tint could be surfaced as
a tiny `charge_streaks` color layer (magenta shift was visible but subtle
— EYEBALL-grade captures needed); script 8's owner effect never appeared
in the up-B window (likely a different Fox move's smoke).
