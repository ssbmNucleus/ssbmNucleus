# Effect Offsets Reference

Source: [structured offsets json](melee_color_offsets.json)

## Format Reference

### `CF_##`
- Color effect format with AD DF markers
- Structure: `CF [count] [color1 RGBA] AD DF [flags] [color2 RGB]`
- Note: AD DF appears to be a separator/marker

### `07_07_07`
- Basic two-color format
- Structure: `[04|07] [R1] [G1] [B1] 00 [R2] [G2] [B2]`
- Note: First byte is 04 or 07, then two RGB colors

### `42_48`
- Three-color gradient/material format
- Structure: `[R1][G1][B1][A1] [R2][G2][B2][A2] [R3][G3][B3][A3] [3E|3F] [??] [??] [??] 42 48`
- Note: Three RGBA colors, marker bytes, then 42 48 terminator

### `98_00_##_##`
- Matrix format with RGBY 16-bit colors
- Structure: `98 00 [count_hi] [count_lo] [color] FC 00 [color] FC 00 ...`
- Note: Used for lasers, shine, complex multi-color effects

### `85_80_08`
- Menu-specific two-color format
- Structure: `85 80 08 0F ... [color 1] [color 2]`
- Note: Shows up in `MnSlMap.usd` for loading-preview and NOW LOADING elements

### `random`
- Non-standard format, often just RGB values
- Structure: `Varies per effect`

## File Reference

- `PlFx.dat`: Fox (character-specific)
- `PlFc.dat`: Falco (character-specific)
- `PlMs.dat`: Marth
- `PlCa.dat`: Captain Falcon
- `PlGn.dat`: Ganondorf
- `PlKp.dat`: Bowser
- `PlDr.dat`: Dr. Mario
- `PlPe.dat`: Peach
- `PlPp.dat`: Ice Climbers
- `PlKb.dat`: Kirby
- `EfFxData.dat`: Fox/Falco shared effects, including shine and Firefox
- `EfCaData.dat`: Captain Falcon effects
- `EfGnData.dat`: Ganondorf effects
- `EfCoData.dat`: Common/shared effects, including dust and smoke
- `EfKpData.dat`: Bowser effects
- `EfKbData.dat`: Kirby effects
- `EfLgData.dat`: Luigi effects
- `EfPkData.dat`: Pikachu effects
- `PlCo.dat`: Common character data, including shields and auras

## Texture Types

- `_5`: with transparency support
- `_8`: standard texture
- `_9`: used for Firefox flame and some effects
- `_14`: used for Falcon Punch

## Body Auras / Hitbox Elements

- `Normal`: no aura
- `Fire`: fire effect on hit
- `Electric`: lightning effect on hit
- `Darkness`: dark purple aura, like Ganondorf moves

These are scattered throughout character files and `PlCo.dat`.

Warning: changing hitbox elements can cause netplay desyncs.

## Tools Mentioned

- `HxD`: hex editor; `Ctrl+K` compares files and `F6` cycles differences
- `GCRebuilder` / `GCTool`: import or export DAT files from ISO
- `Dolphin`: texture dumping; OpenGL dumps `.tga`, Direct3D11 dumps `.png`
- `DAT Texture Wizard`: DAT file editing
- `CrazyHand`: hitbox and moveset editor
- `Melee Toolkit`: general-purpose Melee tool
- `TexConv.exe` + `TCS scripts`: TPL format conversion

## Tips

- To find unknown offsets, compare edited and vanilla files in HxD and cycle through differences.
- For `98 00 ## ##`, the useful starting offset is the `98`, and the bytes at offset `+0x2` hold the color count.
- For `42 48`, the useful start is usually the `42` marker minus `0x10`.
- Firefox and shine both live in `EfFxData.dat`, so edits there often need to be merged.
- `PlFc.dat` and `PlFx.dat` changes may cause desyncs. `EfCoData.dat` and shine edits were noted as appearing safe.

## Practical Workflow

1. find a known effect mod that changes the same thing
2. diff it against vanilla
3. identify the matching format or offset block
4. verify whether the file is costume-local, character-local, or shared

## Status

- 🟢 Nucleus already has an effect mod that covers this offset block.
- 🔴 The offset is known, but the app does not expose it yet.
- ✅ Additionally verified frame-by-frame in game via the audit workflow
  (`docs/dev/EXTRAS_AUDIT.md`) — byte semantics confirmed, app UI matches.

## Offset Data

## Bowser

WIRE 2026-07-02 from the MAP-LIVE spec `research/docs-research/effect-maps/bowser.md`
(`EfKpData.dat`, symbol `effKoopaDataTable`, 9 generators/scripts 0-8).
Neutral-B fire breath (scripts 5-8) and Whirling Fortress up-B (scripts 0-2)
are near-byte-identical clones — Nintendo reused the fortress ptcl scripts
for the flame. CF record layout: `CF <flag> RRGGBB AA AD DF 0X rrggbb`, color
at marker+2, secondary at colorpos+7 (template lesson 3). 🟢✅ fire breath is
exposed + verified LIVE as the `bowser_fire_breath` extra (Dolphin build
verify itself deferred, see `docs/dev/EXTRAS_AUDIT.md`).

### `EfKpData.dat` — Fire Breath (neutral-B) — app extra `bowser_fire_breath`

#### `CF_##`

- 🟢✅ `0x3E2`: flame core puff, script 5 (`fb_s5_a_c1`). LIVE: magenta poke
  turned the whole near-field flame body vivid pink. Data: `FF FF FF FF AD DF 00 FF E8 51`
- 🟢✅ `0x3E9`: └ +7 secondary, warm fringe (`fb_s5_a_c2`). Data: `FF E8 51`
- 🟢✅ `0x3FB`: flame puff, script 5 (`fb_s5_x_c1`; no meaningful secondary — +7 bytes are `00 00 00`, unused). Data: `FF FF FF 05 00 00 00 00 05 A0`
- 🟢✅ `0x40F`: flame ember puff, script 5 (`fb_s5_b_c1`; no secondary). Data: `FF D9 B8 FF AD DF 0A 00 00 00`
- 🟢✅ `0x490`: flame smoke, script 6 (`fb_s6_a_c1`). Data: `FF FF FF 00 AD DF 00 C0 64 01`
- 🟢✅ `0x497`: └ +7 secondary, deep orange (`fb_s6_a_c2`). Data: `C0 64 01`
- 🟢✅ `0x49D`: orange flame puff, script 6 (`fb_s6_b_c1`). Data: `FF 80 4A FF AD DF 05 94 25 14`
- 🟢✅ `0x4A4`: └ +7 secondary, dark red (`fb_s6_b_c2`). Data: `94 25 14`
- 🟢✅ `0x4BB`: flame wisp, script 6 (`fb_s6_c_c1`; no secondary). Data: `FF A9 73 FF AD DF 03 4A 27 19`
- 🟢✅ `0x566`: orange flame, script 7 (`fb_s7_a_c1`). Data: `FF C6 07 00 AD DF 00 FF 02 06`
- 🟢✅ `0x56D`: └ +7 secondary, red (`fb_s7_a_c2`). Data: `FF 02 06`
- 🟢✅ `0x573`: bright orange flame, script 7 (`fb_s7_b_c1`). Data: `FF EF 40 1E AD DF 0C FF 0A 0E`
- 🟢✅ `0x57A`: └ +7 secondary, red (`fb_s7_b_c2`). Data: `FF 0A 0E`
- 🟢✅ `0x587`: flame tip, script 7 (`fb_s7_c_c1`; no secondary). Data: `FF FF FF C8 AD DF 0A 00 00 00`
- 🟢✅ `0x5EE`: flame burst, script 8 (`fb_s8_a_c1`). The record's +7 bytes
  (`FF E8 51`) are non-zero (same value as `0x3E9`'s secondary) but the spec
  table intentionally ships this record `_c1`-only — followed exactly per
  the mission's "follow the spec's grouping exactly" instruction, not
  re-derived here. Data: `FF FF FF C8 AD DF 00 FF E8 51`
- 🟢✅ `0x609`: flame, script 8 (`fb_s8_b_c1`; no secondary). Data: `FF FF FF C8 AD DF 06 00 00 00`
- 🟢✅ `0x628`: ember, script 8 (`fb_s8_c_c1`; no secondary). Data: `FF D9 B8 00 AD DF 0F 00 00 00`

#### `07_07_07` — DEAD, not wired

- 🔴⚪ `0x170D8`: flame model bright core (only orange block in the whole
  file — was the strongest hypothesis pre-LIVE). LIVE 2026-07-02: magenta
  poke of this + `0x170DC` + the 4248 diffuse at `0x17148` left the flame
  body FULLY ORANGE (0 magenta pixels) — the single orange block does NOT
  tint the flame; the CF ptcl records above are the real control. Data: `04 FF FF 00 00 FF 4C 00`

### `EfKpData.dat` — Whirling Fortress (up-B) — NOT wired (harness-blocked)

- 🔴 scripts 0-2 CF records (`0xF2`-`0x283`) — grounded up-B poke: DEAD. The
  visible grounded spin is GOLD radial sparks + white smoke ring, no blue
  anywhere in vanilla; neither the ptcl nor model poke changed it.
- 🔴 `0x14D54`-`0x1629C` blue `070707`/`42_48` model-region cluster (white/
  blue spinning wind trail) — DEAD on the grounded probe for the same
  reason. This is very likely the AERIAL Whirling Fortress (flight variant)
  trail, never triggered by a standing up-B — HARNESS-BLOCKED, not
  proven-dead. Needs a future up-B-while-airborne re-probe (jump first, or
  spawn off a ledge) before it can ship or be marked truly dead.
- Bowser Bomb (down-B) landing shockwave routes to the common `EfCoData.dat`
  bank (`gfx_id < 0x250`) — quarantined, not a Bowser-file layer.
- Koopa Klaw (side-B) draws no effect spawn (on-hit grab, like Falcon
  raptor on-whiff) — not mappable without the punching-bag harness.

## DK

MAP-LIVE pass on `EfDkData.dat` found no shippable color layer. Every
giant-punch/headbutt/spinning-punch effect examined reads as a WHITE
ADDITIVE texture — the visible flash/glow comes from texture alpha
compositing, not a ptcl/model color byte, so there is nothing for a
`070707`/`CF`/`42_48` color layer to control. No offsets are listed here
because none live-poke verified a tintable element; see the DK row in
`docs/dev/EXTRAS_AUDIT.md` for the ⚪ DEAD verdict. A future mission targeting
DK would need a texture-hue-shift approach (à la C. Falcon `punch_texture` /
Fox `upb_texture`), not a color-record extra.

## C. Falcon

### `EfCaData.dat`

> 2026-07: the punch-related blocks below are exposed + verified as the
> `falcon_punch` extra (tip, lens flares, smokes, dots). Real markers are
> mostly cited-minus-2 for CF entries; punch tip 070707 marker = 0x202EC;
> 0x22E30 flare is an `07 07 07 07` variant. 🟢✅ The dominant punch fire
> (bird body/wings/tail streamers) is textured geometry in effect entry 0
> (`effCaptainDataTable/Models_0_`): three unique image nodes at texture
> idx 0 (lava tile), 6 (ember tile), 9 (tail fire wisp) — exposed + verified
> 2026-07 as the `punch_texture` hue-shift extra (see `docs/dev/EXTRAS_AUDIT.md`
> for the shared-image-node gotcha). The lingering trail fire puffs are ptcl
> fire (texture bank, not CLI-addressable), still recolorable via the CF
> smoke/dots color layers above.
>
> 2026-07: the Falcon Kick (down-B) and Raptor Boost (side-B) blocks below
> are exposed as the `falcon_kick` and `raptor_boost` extras. Offsets
> verified two ways: byte-diff of the working "Blue Falcon Kick and Raptor
> Boost" mod (post 14832) against vanilla, then live RAM pokes in-game
> (`tests/artifacts/datram-probe-falcon/`), then the ✅ layers through the
> full build path (`tests/artifacts/extras-audit/C.Falcon-*/`). CF record
> layout: `CF <flag> RRGGBB AA AD DF 0X rrggbb` — cites below are the
> PRIMARY color position (marker+2; the few off-by-one cites are
> corrected in place), and every record has a SECONDARY color at cite+7
> driving the sustained puff tint (the extras write both via `_c1`/`_c2`).
> ⚠️ The over-B smoke/dots/material records are the ON-HIT uppercut burst:
> a whiffed side-B shows only the fist flare + generic white dash dust
> (live pokes on all of them were null on whiff). They ship as
> `raptor_boost` `hit_*` layers but remain unverified until the
> punching-bag (second do-nothing port) harness extension lands. The warm
> launch-flame burst behind Falcon on down-B frames ~10–16 is textured/
> ptcl fire (not these color records) and stays vanilla — a future
> `kick_texture` would need the Models_2 route (decomp: efAsync_Spawn
> 0x490 → effect 0xFA2 = EfCaData entry 2).

#### `CF_##`

- 🟢✅ `0x12F`: Trailing Smoke Down B (falcon_kick `trail`; secondary at +7). Data: `FF FF FF FF AD DF 00 D2 CE 9E`
- 🟢✅ `0x149`: Trailing Smoke Down B (was cited 0x14A — off by one). Data: `FF FF FF FF AD DF 00 6F 66 39`
- 🟢✅ `0x159`: Trailing Smoke Down B (was cited 0x15A — off by one). Data: `FF FF FF FF AD DF 00 6F 66 39`
- 🟢✅ `0x16C`: Trailing Smoke Down B. Data: `FF FF FF B4 AD DF 00 00 00 00`
- 🟢✅ `0x17C`: Trailing Smoke Down B. Data: `FF FF FF 64 AD DF 00 00 00 00`
- 🔴 `0x1DA`: Trailing Smoke Neutral B. Data: `FF FF FF FF AD DF 00 FF C2 57`
- 🔴 `0x1E7`: Trailing Smoke Neutral B. Data: `FF 5A 07 FF AD DF 05 CA 00 0D`
- 🔴 `0x219`: Trailing Smoke Neutral B. Data: `00 00 00 64 AD DF 09 FF 11 19`
- 🔴 `0x29C`: Square Dots Neutral B. Data: `FF 05 1A FF AD DF 00 FF FF 82`
- 🔴 `0x2AC`: Square Dots Neutral B. Data: `FF FF 6E FF AD DF 00 FF 0C 14`
- 🔴 `0x3AC`: Smoke on wings of Neutral B. Data: `FE FF E1 FF AD DF 00 A6 04 01`
- 🔴 `0x3B9`: Smoke on wings of Neutral B. Data: `FF A8 51 FF AD DF 09 CC 0A 0D`
- 🔴 `0x3EF`: Smoke on wings of Neutral B. Data: `FF 61 0C 00 AD DF 09 00 00 00`
- 🟢✅ `0x474`: Square Dots Down B (falcon_kick `dots`). Data: `FF 29 0C FF AD DF 00 FF FF 82`
- 🟢✅ `0x484`: Square Dots Down B. Data: `FF FF 6E FF AD DF 00 FF 0C 14`
- 🟢✅ `0x4D9`: Circle Dots Down B (was cited 0x4DA — off by one). Data: `FF FF FF FF AD DF 00 FC FF 19`
- 🟢✅ `0x4E6`: Circle Dots Down B. Data: `F8 62 11 00 AD DF 06 C5 09 10`
- 🟢✅ `0x539`: Circle Dots Down B. Data: `FF F9 DE FF AD DF 00 FF F0 11`
- 🟢✅ `0x58F`: Trailing Smoke Down B (was cited 0x58E — off by one). Data: `FF FF FF FF AD DF 00 D2 CE 9E`
- 🟢✅ `0x5A9`: Trailing Smoke Down B. Data: `FF FF FF FF AD DF 00 6F 66 39`
- 🟢✅ `0x5B9`: Trailing Smoke Down B. Data: `FF FF FF FF AD DF 00 00 00 00`
- 🟢✅ `0x5CC`: Trailing Smoke Down B. Data: `FF FF FF B4 AD DF 00 00 00 00`
- 🟢✅ `0x5DC`: Trailing Smoke Down B. Data: `FF FF FF 64 AD DF 00 00 00 00`
- 🟢✅ `0x640`: Trailing Smoke Down B and After Smoke of Over B (falcon_kick `trail`; live-verified as the late trail-cloud fringes on down-B). Data: `F3 F0 94 00 AD DF 00 FF 78 17`
- 🟢✅ `0x64E`: Trailing Smoke Down B and After Smoke of Over B. Data: `AD 40 05 50 AD DF 07 62 06 03`
- 🟢✅ `0x65C`: Trailing Smoke Down B and After Smoke of Over B. Data: `DE 5A 26 00 AD DF 0F 00 00 00`
- 🟢✅ `0x6AF`: Front of Down B (falcon_kick `front` = the yellow chevron fire streaks at the foot). Data: `FF FF FF FF AD DF 00 FF F3 07`
- 🟢⏳ `0x76F`: Smoke of Over B large (raptor_boost `hit_smoke`; ON-HIT — not visible on whiff, pending punching-bag harness). Data: `CA CA CA C8 AD DF 00 C5 1D 00`
- 🟢⏳ `0x77F`: Smoke of Over B small (raptor_boost `hit_smoke`, on-hit). Data: `FF DB 0C 64 AD DF 00 A1 08 0D`
- 🟢⏳ `0x78F`: Smoke Behind Falcon Over B (raptor_boost `hit_smoke`, on-hit). Data: `C7 C6 B9 C8 AD DF 00 E1 D2 04`
- 🟢⏳ `0x79F`: Smoke Behind Falcon Over B (raptor_boost `hit_smoke`, on-hit). Data: `FF AF 19 64 AD DF 00 A3 0B 0E`
- 🟢⏳ `0x82C`: Square Dots Over B (raptor_boost `hit_dots`, on-hit). Data: `FF 05 1A FF AD DF 00 FF FF 82`
- 🟢⏳ `0x83C`: Square Dots Over B (raptor_boost `hit_dots`, on-hit). Data: `FF FF 6E FF AD DF 00 FF 0C 14`
- 🟢⏳ `0x8A0`: Square Smoke after Over B (raptor_boost `hit_smoke`, on-hit). Data: `F3 F0 94 00 AD DF 00 FF 78 17`
- 🟢⏳ `0x8AE`: Smoke after Over B (raptor_boost `hit_smoke`, on-hit). Data: `AE 6F 57 50 AD DF 07 63 32 30`
- 🟢⏳ `0x8BC`: Smoke after Over B (raptor_boost `hit_smoke`, on-hit). Data: `DE D4 CF 00 AD DF 0F 00 00 00`
- 🔴 `0x91A`: Smoke after neutral B. Data: `DE 8E 2B FF AD DF 00 FF 07 07`
- 🔴 `0x927`: Smoke after neutral B. Data: `FD 51 26 FF AD DF 09 A4 04 09`
- 🔴 `0x958`: Smoke after neutral B. Data: `00 00 00 64 AD DF 09 75 00 03`

#### `07_07_07`

- 🟢✅ `0x1DE00`: Tip of falcon kick (falcon_kick `color1`/`color2`; marker `07 07 07 04` @0x1DE00 exactly, core RGB @+4, glow-halo RGB @+8 — the cited data line starts at the marker's `04` byte). Data: `04 FF FF E5 00 FF B2 00`
- 🔴 `0x202E0`: Tip of falcon punch. Data: `04 FF 7F 00 00 FF 00 00`
- 🔴 `0x22D60`: Falcon punch lens flare extending lines. Data: `04 FF FF FF 00 00 7F FF`
- 🔴 `0x22E30`: Falcon punch lens flare extending lines. Data: `07 FF FF FF 00 00 7F FF`
- 🔴 `0x22EF0`: Falcon punch lens flare extending lines. Data: `04 FF FF FF 00 00 7F FF`
- 🔴 `0x22FC0`: Falcon punch lens flare extending lines. Data: `04 FF FF FF 00 00 7F FF`
- 🔴 `0x23090`: Falcon punch lens flare extending lines. Data: `04 FF FF FF 00 00 7F FF`
- 🔴 `0x23160`: Falcon punch lens flare extending lines. Data: `04 FF FF FF 00 00 7F FF`
- 🔴 `0x23220`: Falcon punch lens flare extending lines. Data: `04 FF FF FF 00 00 7F FF`
- 🔴 `0x232F0`: Falcon punch lens flare extending lines. Data: `04 FF FF FF 00 00 7F FF`
- 🔴 `0x233C0`: Falcon punch lens flare extending lines. Data: `04 FF FF FF 00 00 7F FF`
- 🔴 `0x23490`: Falcon punch lens flare extending lines. Data: `04 FF FF FF 00 00 7F FF`
- 🟢✅ `0x24B74`: Raptor Boost Hand Lens Flare (was cited 0x24B70; marker @0x24B74, flare-core RGB @+4, glow RGB @+8 = raptor_boost `color1`/`color2` — whiff-verified in-game). Data: `04 F9 FF B2 00 FF B2 00`

#### `42_48`

- 🔴 `0x22D00`: Falcon Punch Small Lens Flare Beginning. Data: `80 80 80 FF FF CC 00 FF FF FF FF FF 00 00 00 00`
- 🔴 `0x235C0`: Falcon Punch Big Lens Flare Beginning. Data: `80 80 80 FF FF 99 00 FF FF FF FF FF 00 00 00 00`
- 🟢⏳ `0x2543C`: Part of Raptor Boost Smoke (was cited 0x25440; the HSD material actually starts at 0x2543C: ambient RGBA @0x2543C, diffuse @0x25440, specular @0x25444 = raptor_boost `hit_mat` [ambient+diffuse]; ON-HIT, pending punching-bag harness). Data: `80 80 80 FF FF FF FF FF FF FF FF FF 00 00 00 00`

## Dr. Mario

WIRE 2026-07 from the MAP-LIVE spec `research/docs-research/effect-maps/mario.md`
(live-poke verified 2026-07-02, `tests/artifacts/datram-probe-docmario/`).
Doc reuses Mario's moveset outright — there is **no `EfDrData.dat`**; Doc's
cape sparkles, tornado, and up-B coin all fire from the **shared**
`EfMrData.dat` (see the Mario section below for those offsets, wired as
`cape_sparkles`/`mario_tornado`, owner Mario, sharedWith Dr. Mario). Doc's
neutral-B throws vitamin pills instead of a fireball (no `efSync_Spawn(1146)`),
so the fireball rows do NOT apply to him. Only his cape CLOTH color is
Doc-owned (his own `PlDr.dat`, different offset than Mario's `PlMr.dat`).
Final-verify build deferred; see `docs/dev/EXTRAS_AUDIT.md` Dr. Mario rows for the
exact verify commands.

### `PlDr.dat`

#### `42_48`

- 🟢 `0x19CAC` (block start = diffuse; env `0x19CB0`; marker `42 48` @0x19CBC):
  Cape cloth color — **old cite 0x19CA0 was off by 0xC (12 bytes); real
  block start 0x19CAC**. Data:
  `FF FF FF FF FF FF FF FF 33 33 33 FF 3F 80 00 00`. Confirmed by BOTH ref mod
  13332 ("Blue Cape Dr. Mario", clean 5-byte diff at 0x19CAC-0x19CB2:
  `FFFFFF`→`00D0FF`) and live-poke (green turned the cape bright green —
  STRONG, clean, the strongest ship candidate in the whole spec). Wired as
  `cloth_c1`/`cloth_c2` in `doc_cape`.

## Falco

### `PlFc.dat`

#### `42_48`

- 🔴 `0x7C00`: Inside of Falco's jacket. Data: `80 48 1F FF F7 87 2C FF FF FF FF FF 3F 80 00 00`
- 🟢✅ `0x1EC40`: Side B illusion (colors at +8; the block is an HSD material: ambient/diffuse/specular RGBA — diffuse dominates visually). Data: `00 99 FF FF CC E6 FF FF FF FF FF FF 3E 99 99 9A`

#### `98_00_##_##`

- 🟢✅ `0x13440-0x13490`: Laser: wide, transparent (outer glow)
- 🟢✅ `0x134E0-0x13530`: Laser: thin, semi-transparent (middle band)
- 🟢✅ `0x13580-0x135D0`: Laser: outline opaque (inner core)
- 🟢✅ `0x13620-0x1368E`: Laser: white center line (exposed as laser `tip`+`center` 2026-07; tip = `80 00 08` RGB matrix @0x13620, line body = `98 00 12` RGB matrix @**0x13643** — the old 0x13640 cite was off by 3; build-verified via Fox's identical layout)

## Fox

### `PlFx.dat`

#### `42_48`

- 🟢✅ `0x22050`: Side B Illusion (same HSD-material semantics as Falco's). Data: `00 99 FF FF CC E6 FF FF FF FF FF FF 3E 99 99 9A`

#### `98_00_##_##`

- 🟢✅ `0x13E20-0x13E70`: Laser: wide, transparent (outer glow)
- 🟢✅ `0x13EC0-0x13F10`: Laser: thin, semi-transparent (middle band)
- 🟢✅ `0x13F60-0x13FB0`: Laser: outline opaque (inner core)
- 🟢✅ `0x14000-0x14022`: Laser: Tip of middle white line (exposed as laser `tip` 2026-07: `80 00 08` RGB matrix, 8 entries)
- 🟢✅ `0x14023-0x1406E`: Laser: white center line (exposed as laser `center` 2026-07: `98 00 12` RGB matrix, 18 entries — old end cite 0x14060 was short; verified in-game, green core line capture in tests/artifacts/extras-audit/Fox-laser/)

## Fox / Falco Shared

### `EfFxData.dat`

> 2026-07 texture findings (audit): the Firefox FLIGHT fire (the big cone
> streamers) is the `_9` flame texture in effect entry 4
> (`effFoxDataTable/Models_4_`, texture idx 1; idx 2 is the same shared image
> node) — 🟢✅ exposed as the `upb_texture` hue-shift extra. The CHARGE-phase
> fire is NOT a model texture: the charge effect (entry 3 = `Models_3_`) has
> only grayscale streak/swirl textures — its orange comes from vertex/material
> colors (the `rings`/`charge_lines` layers below) plus ptcl fire whose
> texture lives in the effect table's TextureGraphics bank, which the HSDRaw
> `--texture` CLI cannot address. Not exposable as a texture extra today.

#### `CF_##`

- 🟢✅ `0x125`: Shine Sparkles (wired + build-verified 2026-07-02: orange sparkles in `tests/artifacts/extras-audit/Fox-shine/fox-downb-f12.png` — see
  `docs/dev/EXTRAS_AUDIT.md` shine row). Marker `0x125`, color `0x127` (3B),
  secondary `0x12E` (3B, colorpos+7, dominates sustained tint). Second CF
  record: marker `0x141`, color `0x143` (3B), secondary `0x14A` (3B). Data:
  `CF 00 FF FF FF FF AD DF 00 2A A3 EE` / `CF 07 FF FF FF 00 FA 07 B8 00 40
  00`. Shared Fox/Falco: `EfFcData.dat` does not exist in vanilla — Fox and
  Falco share `EfFxData.dat` outright, so these offsets apply to both with no
  separate Falco search. Exposed as the `sparkles` property on the `shine`
  extra (`backend/core/extra_types.py` / `frontend/src/shared/data/extraTypes.js`).
- 🟢✅ `0x2EE`: Trailing Fire Large Up B (upb `trail` verified: blue trail fire in flight). Data: `CF 00 FF FF FF`
- 🟢 `0x2F4`: Trailing Fire Large Up B. Data: `CF 18 FF FF FF`
- 🟢 `0x324`: Trailing Fire Large Up B. Data: `CF 08 FF FF FF`
- 🟢 `0x32B`: Trailing Fire Large Up B. Data: `CF 08 FF FF FF`
- 🟢✅ `0x382`: Trailing Fire Small Up B (real CF marker is at 0x382, one byte before the old cite; exposed as upb `small_trail` 2026-07). Data: `CF 00 FF F8 8F FF AD DF 00 FF A9 07`
- 🟢✅ `0x392`: Trailing Fire Small Up B (marker corrected -0x1). Data: `CF 00 FF 71 11 FF AD DF 00 91 07 0B`
- 🟢✅ `0x3A2`: Trailing Fire Small Up B (marker corrected -0x1). Data: `CF 00 FF FD EE FF AD DF 00 FF EF 05`
- 🟢✅ `0x3B2`: Trailing Fire Small Up B (marker corrected -0x1). Data: `CF 00 FF 76 14 FF AD DF 00 FF 94 19`
- 🟢✅ `0x3C4`: Trailing Fire Small Up B (exposed as upb `small_trail`). Data: `CF 08 FA 91 19 00 AD DF 08 87 05 0B`
- 🟢✅ `0x43A`: Square Dots Up B (exposed as upb `dots` 2026-07). Data: `CF 00 FF 29 0C FF AD DF 00 FF FF 82`
- 🟢✅ `0x44A`: Square Dots Up B (exposed as upb `dots`). Data: `CF 00 FF FF 6E FF AD DF 00 FF 0C 14`
- 🔴 `0x4A9`: Trailing Smoke Over B. Data: `CF 00 7F 7F 7F B4 AD DF 00 0C 05 C1`
- 🟢✅ `0x5AF`: Lines Coming Off Up B Charge (exposed as upb `charge_lines` 2026-07). Data: `CF 00 FF FF FF 64 AD DF 00 86 0A FA`
- 🟢 `0x52E`: Trailing Fire Big Up B. Data: `CF 00 FF FF FF`
- 🟢 `0x536`: Trailing Fire Big Up B. Data: `CF 18 FF FF FF`

#### `07_07_07`

- 🟢✅ `0x1A508`: Lens Flare of Up B in motion (REAL 07 07 07 04 marker at 0x1A508 — the 0x1A500 cite includes an `85 80 08 0F` prefix; writing at 0x1A500+4/+8 corrupts the effect script and hangs the game at launch. Exposed as upb `flare` 2026-07). Data: `04 FF E5 4C 00 FF 33 00`
- 🟢✅ `0x1B450`: Fire Ring for Up B (upb `rings` verified: the charge pillar streaks; real markers 0x1B454/0x1B520). Data: `04 FF FF CC 00 FF 7F 00`
- 🟢 `0x1B520`: Fire Ring for Up B. Data: `04 FF FF 00 00 FF 33 00`

#### `98_00_##_##`

- 🟢 `0x1AC80-0x1AD00`: Tip of Firefox
- 🟢✅ `0x1C2A0-0x1C340`: Shine main effect (verified: bright hexagon edge + band fill, two alternating RGBY colors)
- 🟢 `0x1C8E0-0x1C990`: First Frames of Shine (inner hex, outer glow, outer border). Note: the app's flash1/flash2 layers showed NO in-game effect in the 2026-07 audit (exact-value remap probably matches nothing) — needs byte-level investigation

#### TObj TEV block + matanim (Blaster Flash — the app's `laser_ring` extra, mapped 2026-07)

The muzzle-flash model drawn on every blaster shot (decomp `itfoxblaster.c`
`efSync_Spawn(1166)` → efalt `0x48E` → effect 0xBBD = `effFoxDataTable`
`Models_5`; Fox and Falco share it). NOT the beam (PlFx/PlFc laser matrices
above) and NOT the red muzzle ring (ptcl). See `docs/dev/EXTRAS_AUDIT.md`.

- 🟢✅ `0x1D2EC-0x1D30B`: the model's `HSD_TObjTev` block. `85 80 08 0F` at
  0x1D2F4 = TEV color inputs (TEX0/KONST/TEXC/ZERO: pixel =
  tev0·(1−texI) + konst·texI) and `07 07 07 07` = alpha inputs (alpha TEV
  inactive) — **structure bytes, not color markers; do not patch them**.
  - 🟢✅ `0x1D2FC`: KONST RGB `FF 00 4C` = `color1` — the bright streak burst
    around the fighter (verified in-game with magenta).
  - 🟢✅ `0x1D300`: TEV0 RGB `B2 00 00` = `color2` — the flash texture's dim
    areas (verified: practically invisible in game).
- 🟢✅ `0x1D974`, `0x1D988`, `0x1D99C`, `0x1D9B0`, `0x1D9C4`, `0x1D9D8`: the
  trackType bytes (`0C 0D 0E` = KONST_R/G/B, `10 11 12` = TEV0_R/G/B; `0F` =
  KONST_A unused) of six `HSD_FOBJDesc` matanim tracks that animate both TEV
  colors orange→vanilla over 8 frames and then hold hardcoded vanilla values.
  **They are NOT hue indexes.** Writing `00` (`HSD_A_T_NONE`, skipped by the
  engine) disables the animation — REQUIRED for the static colors above to
  show (verified: with the tracks intact, custom colors are pixel-identical
  to vanilla). The keyframe data are six 14-byte u16-quantized FObj buffers
  at `0x1D8C8-0x1D925`.

## Common / Cast-Shared (`EfCoData.dat`)

Not a per-character file — `EfCoData.dat` (`effCommonDataTable`) is the
**shared common effect bank**, loaded once and referenced by many
characters' particle scripts via a common `texGraphicBank` (see
`research/docs-research/effect-maps/effect-texbank.md`). Of its 36 texture groups,
exactly two carry color (everything else is a grayscale intensity/alpha
mask, recolor is a no-op — see that doc §4c); both are wired as `Zelda`-
owned `texture_recolor` extras (owner/sharedWith pattern, WIRE 2026-07-02).

### `EfCoData.dat` texGraphicBank

#### CI8 palette groups (the recolor targets)

- 🟢✅ **group 9** (`common_fire`, app extra id `common_fire`): CI8, 64×64,
  10 images, dominant hue 41° (orange). Images `0x8CB40 + k*0x1000` (k=0..9);
  palettes `0x96B40 + k*0x200` (k=0..9), each 256×RGB5A3. The shared fire
  cloud — Din's Fire, Bowser Bomb fire, Charizard flame-breath, Marth
  Flare Blade/Blazer fire, Roy Flare Blade/Blazer fire all composite this
  ONE texture (proven by mod 17088 "rainbow fire whole cast", a pure diff
  fully contained in this group's extent; `ptcl_texbank.py --verify`
  PASSes). Owner **Zelda**, `sharedWith: ["Bowser", "Marth", "Roy"]`.
  Extent `0x8CB40-0x97F40`.
- 🟢✅ **group 3** (`common_flash`, app extra id `common_flash`): CI8,
  128×128, 2 images, dominant hue 279° (purple/magenta). Images `0x48DA0`,
  `0x4CDA0`; palettes `0x50DA0`, `0x50FA0`. The shared electric/vanish
  star-burst — Sheik/Zelda Vanish flash, Zelda↔Sheik Transform flash,
  Pikachu/Pichu thunder and Quick Attack burst all composite this ONE
  texture. Owner **Zelda**, `sharedWith: ["Sheik", "Pikachu", "Pichu"]`.
  Extent `0x48DA0-0x511A0`.

Recolor mechanics (CI8, `texture_recolor` format, `vault/extras/
texture_recolor.py`): each image's pixel data is an INDEX into its own
256-entry palette — apply decodes the palette, hue-rotates every entry by
`(target_hue − vanilla_dominant_hue)` preserving S/V/alpha, re-encodes, and
writes only the palette bytes back. Pixel index bytes are never touched.
Config shape: `"texture": {"gx_format": 9, "width", "height", "images":
[{"offset", "palette"}, ...], "palette_format": 2}` (RGB5A3 TLUT).

#### Grayscale groups (NOT recolorable — do not wire)

Groups 2, 4, 5, 7, 11, 13, 16, 23, 26 (IA8/IA4/I4/I8 alpha/intensity masks
for Din/Vanish/Quick-Attack/arrow/Bomb) carry no hue; their apparent color
comes from the shared CI8 groups above, not their own texture. See
`ptcl_texbank.py … --groups <n> --hue` to re-derive the full 36-group
inventory (`--json` for per-image/palette offsets).

### `EfCoData.dat` ptcl colour records (the ptcl-bank pool, not texGraphicBank)

Separate from the texture groups above: 592 particle-script generators
(`ptcl bank 0x420..0x11C20`), most spawned by subaction event-GFX with no
single attributable C-level move caller (the classic "generic hit/electric
spark" pool 15070 "Purple Electric Pack" recolors). Wired as `Pikachu`-owned
color-record extras (owner/sharedWith pattern, same as `common_fire`/
`common_flash`, WIRE 2026-07-02; see `research/docs-research/effect-maps/
efcodata.md` §3c/§4/§6b for the full derivation).

- 🟢✅ **`common_electric`** (25 scripts: `0,1,13,14,16,17,18,19,29,30,31,
  73,161,162,268,269,270,306,332,423,424,425,426,448,537`; 35 total
  PrimCol/EnvCol records incl. 10 secondary operands in scripts
  0/13/29/30/268). The cast-wide **on-hit/hitlag electric spark burst** —
  the blue arc + radial spark rays that flash on ANY character taking a
  hit. LIVE-verified 2026-07-02 by green-poking 9 of the 25 records on
  Zelda's jab hitlag against a punching-bag DK. Per-record vanilla bytes
  differ (NOT a uniform blue — e.g. `0xDC5 FFF305`, `0xDDB FF0000`, `0x1560
  210CFF`, `0x13BA 000000`, `0x15BA 3FFF00`); shipped as individual
  `elec_s<script>[_<ordinal>]_c1/_c2` layer keys, all byte-verified. Owner
  **Pikachu**, `sharedWith` = the rest of the 25-character roster (this is
  explicitly NOT Pikachu-specific).
- 🟢🟡✅ **`thunder_jolt_spark`** (script 95, `0x391A` PRIM / `0x3921` ENV /
  `0x3930` PRIM). The CASTER-SIDE dissipation/cheek spark on Pikachu's
  neutral-B Thunder Jolt — verified but SUBTLE: the marquee jolt fountain/
  travelling bolt is a separate texture-driven article effect and is
  unaffected. Owner **Pikachu**, `sharedWith: ["Luigi"]` (side-B remove
  despawn-flash GFX shares the script — a housekeeping flash, not a
  visually meaningful Luigi move).
- 🟡✅ **`jab_finisher_spark`** (scripts 11/15/91; 4 records). The rapid-jab
  (Attack100) **FINISHER connect flash** — the pink-white/cyan spark burst on
  the victim when the infinite jab's finishing hit connects. LIVE-verified
  colorable 2026-07-02 (STRAGGLER-CLOSEOUT) via the `rapidjab` recipe
  (`shared/ingame/moves.py`, a 1-on/1-off A toggle that chains Fox's jab into
  **Attack100Loop**) with a pinned DK bag: poking all 4 records RED recolored
  the connect diamond/burst (vanilla pink-white/cyan → red). Records/keys:
  - `0x12AF` (s11) ENV `0554FF` = leading connect spark → `finisher_lead_c1` (`color1`).
  - `0x148D` (s15) ENV `57D0FF` = electric burst body → `finisher_burst_a_c2` (`color2`).
  - `0x14A1` (s15) ENV `0509FF` = electric burst body 2 → `finisher_burst_b_c2` (`color2`).
  - `0x376F` (s91) ENV `75DBEB` = cyan flash → `finisher_flash_c2` (`color2`).

  All 4 byte-verified against vanilla `EfCoData.dat`. Owner **Fox** (a
  representative rapid-jab char); `sharedWith` = the Attack100 roster minus Fox
  (table below). The generic gold radial hit-spark streaks stay gold
  (texture/model, not these ENV records). Note `s44` (`0x22E3`) is the generic
  white energy-shell glow shared with DK grab-stage / shells / Master Hand —
  NOT part of the jab finisher, left out of the group.

#### Attack100 (rapid-jab) roster — `jab_finisher_spark` owner + sharedWith

DATA-DERIVED via `backend/shared/rendering/hitbox_elements.py --attack100`: the
fighters whose vanilla action table carries the literal `Attack100`
motion-state action (`ACTION_Attack100Start/Loop/End`). Those are precisely
the characters that reach `Attack100Loop/End` and so spawn EfCoData scripts
11/15/91. The action table is not positionally fixed across fighters, so
detection is by action-SYMBOL name (not slot index).

| Character | Has Attack100 (spawns the finisher spark)? |
|---|---|
| **Fox** (owner) | yes |
| Falco | yes |
| C. Falcon | yes |
| Kirby | yes |
| Link | yes |
| Young Link | yes |
| Mewtwo | yes |
| Sheik | yes |
| G&W (Judgment) | yes |
| Mario, Luigi, DK, Bowser, Ness | **no** — finite 3-hit jab (`Attack13`), never an infinite Attack100 loop |
| Marth, Roy, Peach, Jigglypuff, Zelda, Pikachu, Pichu, Samus, Ganondorf, Yoshi, Ice Climbers, Dr. Mario | **no** — no rapid-jab / finite jab combo only |

HONESTY NOTE: an early "known-truth" list named Mario/Luigi/DK/Bowser/Ness/
Falcon as HAVE. Only C. Falcon among them actually carries the Attack100 motion
state; the other five have a finite `Attack13` third jab, not an infinite
rapid loop (SmashWiki confirms finite neutral attacks), so they never spawn
11/15/91 and are correctly excluded. Regenerate the list with
`python -m shared.rendering.hitbox_elements --attack100` (from `backend/`; includes a
self-test).

## Ganondorf

### `EfGnData.dat`

WIRE 2026-07-02 from the MAP-LIVE spec `research/docs-research/effect-maps/
ganondorf.md`. Bank index 19 in `efAsync_DatEntries`, `effect_id_start =
19000` → script index = gfx_id − 19000. **Ganondorf is a Falcon clone that
reuses ftCaptain code entirely** (`ftGanon/` has only `ftGn_Init.c`; every
special runs the shared `ftCaptain/ftCa_Special*.c` functions, branching on
`FTKIND_GANON` and spawning a symbolic effect id offset **+0x7C** from
Falcon's own). NOT byte-identical to Falcon, though — the ptcl operands are
genuine dark/purple recolors at the parallel script indices (Falcon orange
`FF7F00` → Ganon purple `280021`/`47004F`/`A200AB`/etc.), so each script has
real vanilla purple bytes to map, same as a normal character.

#### `CF_##` (scripts 0+1 — Warlock/Falcon Punch dark aura + fist explosion)

- 🟢✅ `0x154`: punch dark aura core (PRIM). Ships as `warlock_punch punch_a_c1`. Data: `28 00 21`
- 🟢✅ `0x15B`: punch dark aura env tint (ENV). `punch_a_c2`. Data: `11 00 2E`
- 🟢✅ `0x161`: punch mid purple (PRIM). `punch_b_c1`. Data: `47 00 4F`
- 🟢✅ `0x168`: punch deep-purple env (ENV). `punch_b_c2`. Data: `13 02 45`
- 🟢✅ `0x192`: punch black fade (PRIM). `punch_c_c1`. Data: `00 00 00`
- 🟢✅ `0x199`: punch purple fade env (ENV). `punch_c_c2`. Data: `1B 02 45`
- 🟢✅ `0x224`: fist-explosion magenta-purple core (PRIM). `fist_a_c1`. Data: `A2 00 AB`
- 🟢✅ `0x22B`: fist-explosion purple env (ENV). `fist_a_c2`. Data: `40 05 91`
- 🟢✅ `0x231`: fist-explosion purple (PRIM). `fist_b_c1`. Data: `75 03 9C`
- 🟢✅ `0x238`: fist-explosion purple env (ENV). `fist_b_c2`. Data: `28 05 87`
- 🟢✅ `0x262`: fist-explosion black fade (PRIM). `fist_c_c1`. Data: `00 00 00`
- 🟢✅ `0x269`: fist-explosion purple fade env (ENV). `fist_c_c2`. Data: `54 07 75`

LIVE-VERIFIED 2026-07-02 (`tests/artifacts/datram-probe-ganondorf/
probe-ganondorf/warlock_punch-neutralb-f50.png`): green poke replaced the
vanilla purple connect-burst **on the victim at contact** — the
fist-explosion is on-hit only (needs the punching-bag harness, `bag dk, dx
11`). The f30 solo charge starburst is a DIFFERENT, unpoked script and stays
vanilla purple. All 12 offsets byte-verified against vanilla `EfGnData.dat`.
Ships as the `warlock_punch` extra (DualColor `_c1`/`_c2` fan-out across all
12 per-record keys, split per template lesson 12 since the group's vanilla
bytes do NOT share one string — two distinct blacks plus four distinct
purples).

#### `CF_##` (script 6 — Wizard's Foot foot-fire, NEW LEAD)

- 🟢✅ `0x4CF`: foot-fire streak core (PRIM). Ships as `wizards_foot color1`. Data: `FF DE FF`
- 🟢✅ `0x4D6`: foot-fire streak env tint (ENV). `wizards_foot color2`. Data: `3D 02 61`

LIVE-VERIFIED 2026-07-02 (`tests/artifacts/datram-probe-ganondorf/
probe-ganondorf-leads/leads_downb-downb-f24.png` & `-f30.png`): green poke
on script 6 produced green foot-fire streaks under Ganon during the dash.
The larger purple impact starburst on connect is a still-unattributed
script (open lead, not this layer). Solo down-B whiff is sufficient to
demonstrate — no bag needed. Both offsets byte-verified against vanilla
`EfGnData.dat`. Ships as `wizards_foot`.

#### `CF_##` (script 2 — Wizard's Foot draft dash-trail) — NOT wired, DEAD

- 🔴 `0x306`–`0x31D`: pink-magenta/purple dash-trail candidate. **LIVE-DEAD**
  2026-07-02 — poking these had no visible effect on the solo down-B
  dash-trail (`probe-ganondorf-solo/wizards_foot-downb-f26.png` vs vanilla,
  pokes active + readback-OK). The visible purple foot-trail is NOT this
  script. Not shipped.

#### `CF_##` (scripts 3/4/5 — Gerudo Dragon draft candidates) — NOT wired, DEAD/open lead

- ⚪ Script 3 (0 operands) = TEXTURE-ONLY, not a ptcl layer.
- 🔴 `0x3CC`–`0x3E3` (script 4, grounded dragon): magenta/lilac dragon body
  candidate. **LIVE-DEAD** 2026-07-02 — the grab-connect burst stayed
  purple with pokes active (`probe-ganondorf-gerudo/
  gerudo_dragon-sideb-f22.png` & `-f28.png`). **SUPERSEDED — the real owner
  is scripts 12/14/15/16, see below.** Not shipped.
- ⚪ Script 5 (aerial dragon, 10 operands, grayscale PRIMs tinted by tan/
  purple ENVs — the dragon smoke/dust cloud, related to the s7/9/10/11
  smoke family below): unpoked, open lead.

#### `CF_##` (scripts 12/14/15/16 — Gerudo Dragon flame aura) — app extra `gerudo_dragon`

- 🟢✅ `0x76C`: s12 flame aura (PRIM). `s12_a_c1`. Data: `F2 D1 FF`
- 🟢✅ `0x773`: s12 flame env (ENV). `s12_a_c2`. Data: `2D 03 59`
- 🟢✅ `0x779`: s12 flame purple core (PRIM). `s12_b_c1`. Data: `7C 40 D7`
- 🟢✅ `0x780`: s12 flame env (ENV). `s12_b_c2`. Data: `28 02 42`
- 🟢✅ `0x7AF`: s12 (PRIM). `s12_c_c1`. Data: `1F 01 38`
- 🟢✅ `0x7B6`: s12 env (ENV). `s12_c_c2`. Data: `00 00 00`
- 🟢✅ `0x875`: s14 flame (PRIM). `s14_a_c1`. Data: `BE A7 CA`
- 🟢✅ `0x87C`: s14 flame env (ENV). `s14_a_c2`. Data: `96 09 C5`
- 🟢✅ `0x885`: s14 flame magenta (PRIM). `s14_b_c1`. Data: `C6 07 FF`
- 🟢✅ `0x88C`: s14 flame env (ENV). `s14_b_c2`. Data: `5E 06 A1`
- 🟢✅ `0x895`: s14 (PRIM). `s14_c_c1`. Data: `B0 7F C7`
- 🟢✅ `0x89C`: s14 env (ENV). `s14_c_c2`. Data: `AD 33 E1`
- 🟢✅ `0x8A5`: s14 (PRIM). `s14_d_c1`. Data: `81 19 8C`
- 🟢✅ `0x8AC`: s14 env (ENV). `s14_d_c2`. Data: `50 0B A3`
- 🟢✅ `0x8B6`: s14 (PRIM). `s14_e_c1`. Data: `3D 08 7D`
- 🟢✅ `0x8BD`: s14 env (ENV). `s14_e_c2`. Data: `3E 03 4F`
- 🟢✅ `0x92C`: s15 flame magenta (PRIM). `s15_a_c1`. Data: `76 05 B3`
- 🟢✅ `0x933`: s15 flame env (ENV). `s15_a_c2`. Data: `D8 8A FF`
- 🟢✅ `0x93C`: s15 flame (PRIM). `s15_b_c1`. Data: `D8 73 FF`
- 🟢✅ `0x943`: s15 flame env (ENV). `s15_b_c2`. Data: `73 0A AB`
- 🟢✅ `0x9A0`: s16 flame magenta (PRIM). `s16_a_c1`. Data: `E3 6D F3`
- 🟢✅ `0x9A7`: s16 flame env (ENV). `s16_a_c2`. Data: `A0 07 FF`
- 🟢✅ `0x9AE`: s16 (PRIM). `s16_b_c1`. Data: `2D 00 47`
- 🟢✅ `0x9B5`: s16 env (ENV). `s16_b_c2`. Data: `22 01 33`
- 🟢✅ `0x9BC`: s16 (PRIM). `s16_c_c1`. Data: `D1 C3 DE`
- 🟢✅ `0x9C3`: s16 env (ENV). `s16_c_c2`. Data: `00 00 00`

LIVE-VERIFIED 2026-07-02 via a 2-stage sweep + the NEW `--bag-pin` harness
option (`shared/ingame/gamestate.py Bag.pin()`, unblocks command grabs that would
otherwise knock the bag out of re-grab range after the first slam): a broad
sweep (s12/14/15/16 green) then a NARROW CONFIRM poke (s12/14/15/16 ONLY,
cyan, `tests/artifacts/probe-ganondorf-gerudo-narrow/
gerudo_aura_s12_14_15_16-sideb-f20.png` vs vanilla) isolated the purple/
magenta flame aura engulfing the victim at the grab-connect. The sibling
smoke scripts (s7/9/10/11, below) stayed white; the impact green-ray
starburst + white flash (a still-unattributed script) stayed vanilla. All
26 offsets byte-verified against vanilla `EfGnData.dat`. Ships as the
`gerudo_dragon` extra (DualColor `_c1`/`_c2` fan-out, every record its own
key per template lesson 12 — no two records share a byte string).

#### Open leads (scripts 7/9/10/11 smoke family + unattributed 6–16 remainder)

- ⚪ Scripts 7/9/10/11 (`0x52F`–`0x708`): the gray/white SMOKE puffs
  accompanying the Gerudo dragon — LIVE-poked green during the S5b sweep,
  grew larger/whiter with NO hue change (confirms grayscale/tan-env
  reading). Not the colored flame; a future dust-recolor extra could target
  these separately.
- Scripts 6 (foot-fire, ships as `wizards_foot` above; 2 col), 9/10/11 (see
  smoke family), 12/14/15/16 (ships as `gerudo_dragon` above). No decomp
  caller found in ftCaptain specials for the remainder. ~190 model-region
  colour blocks past the ptcl bank (Gerudo dragon-head + wizard's-foot
  geometry) = model recolor, out of scope for a ptcl-layer extra.

## Jigglypuff

WIRE 2026-07-02 from the MAP-LIVE spec `research/docs-research/effect-maps/jigglypuff.md`
(`EfPrData.dat`, symbol `effPurinDataTable`; the Sing notes are MODEL-REGION
`07_07_07` vertex-color pairs, not a ptcl-bank record). LIVE-poke verified
2026-07-02 (`tests/artifacts/datram-probe-jigglypuff/`): red core/glow poked
green turned the bottom note green, blue poked orange turned the upper-left
note orange, green poked magenta turned the right note magenta.
🟢 all three notes are exposed + LIVE-verified as the `sing_notes` extra
(six independent core/glow properties; Dolphin build verify itself deferred,
see `docs/dev/EXTRAS_AUDIT.md`).

### `EfPrData.dat` — Sing (up-B) — app extra `sing_notes`

#### `07_07_07`

- 🟢 `0x5440` marker (`0x5444` core / `0x5448` glow): Red note of Sing.
  Data: `07 07 07 04 FF FF FF 00 FF 00 00`. LIVE: green poke -> note turned
  green (`note_red_core`/`note_red_glow`).
- 🟢 `0x5500` marker (`0x5504` core / `0x5508` glow): Blue note of Sing.
  Data: `07 07 07 04 FF FF FF 00 00 00 FF`. LIVE: orange poke -> note turned
  orange (`note_blue_core`/`note_blue_glow`).
- 🟢 `0x55C0` marker (`0x55C4` core / `0x55C8` glow): Green note of Sing.
  Data: `07 07 07 04 FF FF FF 00 00 FF 00`. LIVE: magenta poke -> note turned
  magenta (`note_green_core`/`note_green_glow`).
- 🔴 `0x5580` marker (block `0x5570`, diffuse `0x5574` = `0000FF`): blue
  note 42_48 material. NOT wired — LIVE could not isolate its contribution
  from the 070707 pair (poked together every time; note body fully
  recolored from the 070707 pair alone).
- 🔴 `0x5640` marker (block `0x5630`, diffuse `0x5634` = `00FF00`): green
  note 42_48 material. Same caveat as above; no red material block exists.
- 🔴 `0x5680` (petals `0x5684`/`0x5688`) + `0x5700` marker (center
  diffuse `0x56F4` = `FFADFF`): Rest (down-B) flower burst. UNCONFIRMED /
  harness-blocked open lead — offsets are marker-verified + readback-OK but
  the flower never rendered in a solo plain-bg downb sweep (f1-70); needs a
  manual EYEBALL pass, not wired.

## Kirby

WIRE 2026-07-02 from the MAP-LIVE spec `research/docs-research/effect-maps/kirby.md`.
`EfKbData.dat` bank: `EffectTable@0x20 ParticleGroup@0xE0 version=0x42
tex_bank@0x980`, 19 generators, `effect_id_start = 5000` (0x1388) → script
index N (1-based) = generator id `0x1388 + (N-1)`. **ONE shippable extra
found: `kirby_stone`** (Stone/down-B transform-burst dust, scripts s5+s8+s9+
s14). Final Cutter (up-B), Hammer (side-B), Inhale (neutral-B), and Puff-air
(aerials) are ALL DEAD in this file's ptcl bank — every visible element is
model/texture/item-article driven (Cutter Beam = `It_Kind_Kirby_CBeam` item;
hammer swirl = hammer item DAT; inhale suction = white-particle/model; no
aerial ptcl spawns at all). The pre-existing candidate list below (from an
earlier static reference pass, before this campaign's LIVE pass) used
"Down B rocks" offsets **2 bytes early** (line-start cites, template lesson
1) — `0x51C`→`0x51E`, `0x529`→`0x52B`, `0x664`→`0x666` are close-but-wrong;
the corrected, LIVE-poke-verified offsets are marked 🟢✅ below with their
`kirby_stone` layer keys. `_c1` = PRIMCOL (dust/debris bright), `_c2` = the
one ENVCOL (s9's teal sustain tint).

### `EfKbData.dat` — Stone (down-B) — app extra `kirby_stone`

- 🟢✅ `0x51E`: s8 transform dust bright (PRIM). `dust_a_c1`. Data: `FF FF FF`
- 🟢✅ `0x52B`: s8 dust (PRIM). `dust_b_c1`. Data: `FF FF FF`
- 🟢✅ `0x532`: s8 dust fade (PRIM). `dust_c_c1`. Data: `FF FF FF`
- 🟢✅ `0x58B`: s9 grey dust (PRIM). `s9_a_c1`. Data: `CC CC CC`
- 🟢✅ `0x592`: s9 env, teal sustain (ENV). `s9_a_c2`. Data: `09 A9 BA`
- 🟢✅ `0x598`: s9 grey dust (PRIM). `s9_b_c1`. Data: `CA CA CA`
- 🟢✅ `0x59F`: s9 grey dust fade (PRIM). `s9_c_c1`. Data: `BA BA BA`
- 🟢✅ `0x796`: s14 stone-break dust (PRIM). `brk_a_c1`. Data: `FF FF FF`
- 🟢✅ `0x7A3`: s14 stone-break puff (PRIM). `brk_b_c1`. Data: `FF FF FF`
- 🟢✅ `0x381`: s5 ground-transform starburst, secondary (PRIM). `ground_a_c1`. Data: `FF FF 00`
- 🟢✅ `0x38E`: s5 ground flash, secondary (PRIM). `ground_b_c1`. Data: `FF FF FF`
- 🟢✅ `0x3A9`: s5, secondary (PRIM). `ground_c_c1`. Data: `FF FF FF`
- 🟢✅ `0x3AF`: s5 puff, secondary (PRIM). `ground_d_c1`. Data: `FF FF 00`
- ⚪ `0x42E`–`0x465` (script 6, air-stone transform): LIVE-poked DEAD 2026-07-02
  — no visible change on the air down-B burst (reuses s5/dust visuals). Not
  shipped.

LIVE-VERIFIED 2026-07-02 (`tests/artifacts/probe-kirby/kirby_stone_dust-downb-f34.png`
vs `vanilla-downb-f34.png`): magenta poke on s8/s9/s14 turned the entire
radial transform burst + rock-debris tint + swirl rings bright magenta,
unambiguous; s5 (`.../kirby_stone_ground-downb-f06.png`) gave a subtler-but-
real recolor of the early transform starburst. All 13 offsets byte-verified
against vanilla `EfKbData.dat`. Ships as the `kirby_stone` extra (DualColor
`_c1`/`_c2` fan-out, per-record vanilla per template lesson 12 — the FFFFFF-
family dust records are NOT byte-identical to each other as a group, so each
keeps its own key).

### `EfKbData.dat` — Final Cutter / Hammer / Inhale / Puff-air — NOT wired, DEAD

- 🔴 `0x1CA`–`0x206` (script 1, blade), `0x27C`–`0x293` (script 2, beam),
  `0x32A` (script 4, flash): Final Cutter. **LIVE-DEAD** — the startup
  birth-flash, sword blade + trail, and descending Cutter-Beam wave are all
  model/item-article driven (the beam is the `It_Kind_Kirby_CBeam` item),
  unchanged by any script-1/2/4 poke. Not shipped.
- 🔴 Script 7 (`0x4C8`, hammer head): no color operand in the ptcl bank.
  **LIVE-DEAD** — poking the s8 dust records (shared candidate) green left
  the entire hammer swing identical; the purple/yellow spin-swirl aura is
  the hammer ITEM effect, the wooden head is a model. Not shipped.
- 🔴 Scripts 4 (`0x32A`)/10/11 (`0x5F3`–`0x67A`): Inhale. **LIVE-DEAD** — the
  white suction dots + wind puff stayed white/gray under a cyan poke; the
  inhale star is an `efAsync` item article. Not shipped.
- 🔴 Scripts 17/18 (`0x8DE`–`0x962`): Puff-air (aerials). **NO EFFECT** —
  nair/fair spawn no aerial ptcl at all on FD. Not shipped.
- Scripts 10/11/12/15/16 remain **open leads** (unattributed, poked in the
  inhale/puff sweeps with no visible change on the moves tested; likely
  on-hit or copy-ability variants).
- **Kirby Copy Abilities** (9 `EfKbXx.dat` ptcl copies, e.g. `EfKbPk`/`EfKbCa`
  byte-identical to their donor's own bank) — 5 SHIPPED 2026-07-02 as
  `kirby_copy_<donor>` extras (see the dedicated section below); 4 held for a
  future LIVE spot-verify, see spec §6.3/§6.4.

### `EfKb<XX>.dat` — Copy Abilities — 5 SHIPPED (parser-confident, LIVE-confirm-deferred)

WIRE 2026-07-02 from `research/docs-research/effect-maps/kirby.md` §6. Each copy file's
ptcl bank is a byte-identical, position-matched (script ordinal + in-script
operand ordinal — NOT absolute-offset diffing, since the copy's smaller
header shifts every record) slice of the donor's own already-shipped extra.
Decomp (`efalt.c` case resolution, spec §6.0) proves a copied special draws
EXCLUSIVELY from the copy-range bank (e.g. `EfKbGn` id 47000, not
Ganondorf's own 4000) — recoloring a copy never touches the donor's own
extra. All offsets below are the COPY file's own shifted positions,
re-derived via raw byte reads against `storage/test-base/files/EfKb<XX>.dat`
(not transcribed from the spec's abbreviated §6.1 sample tables) and
position-matched against the donor's shipped config to confirm byte-identity.
**HARNESS GAP (blocks LIVE, all 5):** the solo-Kirby `shared/ingame/` harness has no
inhale+swallow+copy primitive, so a copied special never loads these banks in
a boot — ships on parser+decomp confidence, `extras_audit.py --skip-game`
offsets/build stage PASS for all 5, Dolphin verify deferred to a future
harness slot (spec §6.4).

- 🟢 `EfKbGn.dat` — **`kirby_copy_ganon`** (Copy Ability: Warlock Punch).
  Twins `warlock_punch` 12/12 (FULL). `punch_a_c1/_c2 0xE4/0xEB`,
  `punch_b_c1/_c2 0xF1/0xF8`, `punch_c_c1/_c2 0x122/0x129` (script 0);
  `fist_a_c1/_c2 0x1B4/0x1BB`, `fist_b_c1/_c2 0x1C1/0x1C8`,
  `fist_c_c1/_c2 0x1F2/0x1F9` (script 1). Ganon's own script 2
  (`0x296`-`0x2AD`) is not part of the shipped donor set — excluded.
- 🟢 `EfKbIc.dat` — **`kirby_copy_iceclimbers`** (Copy Ability: Ice Shot).
  Twins `ice_shot` 17 of 19 copy records. `birth_a/b/c_c1[/_c2] 0xBA-0xDB`
  (script 0), `sparkle_c1/_c2/sparkle2_c1 0x17D/0x184/0x18A` +
  `0x30D/0x314/0x31A` (scripts 2,6), `variant_a/b_c1[/_c2] 0x1E6-0x1F3`
  (script 3), `variant_c/d_c1[/_c2] 0x24E-0x25B` (script 4). The copy's
  script 5 (`0x2B4`/`0x2BB`) twins a donor record never shipped as an
  `ice_shot` layer (donor's own "misc" script 5) — excluded.
- 🟢 `EfKbKp.dat` — **`kirby_copy_bowser`** (Copy Ability: Fire Breath).
  Twins `bowser_fire_breath` 17/17 (FULL). Copy scripts 0/1/2/3 map to donor
  scripts 5/6/7/8 respectively (position-verified): `fb_s5_* 0xA2-0xCF`,
  `fb_s6_* 0x150-0x17B`, `fb_s7_* 0x226-0x247`, `fb_s8_* 0x2AE-0x2E8`.
- 🟢 `EfKbLg.dat` — **`kirby_copy_luigi`** (Copy Ability: Fireball Smoke).
  Twins `luigi_fireball_smoke` 20 of 24 copy records (scripts 0,1,3,4,5,6 —
  `fb_smoke_s0a/s0b 0xC7-0xDB`, `fb_smoke_s1_c1/_c2 0x14E/0x15C/0x16F/0x17C`
  + `0x155/0x163/0x176/0x183`, `fb_smoke_s3/_s4 0x235-0x2B9`,
  `fb_dust_s5 0x31A/0x33A`, `fb_particle_s6 0x3C6/0x3D6`). The remaining 12
  copy records twin the donor's own unshipped pair-1 records per script —
  excluded, matching the donor's own "20/24" scope.
- 🟢 `EfKbMr.dat` — **`kirby_copy_mario`** (Copy Ability: Fireball). Twins
  `mario_fireball` 30 of 33 copy records. **NOTE the copy's script 0 clones
  the donor's script 1** (Mario's own donor script 0 absent from the copy
  bank) — position-matching caught and corrected an initial script3↔script5
  mis-pairing before shipping (`hand_smoke_* 0xB2-0xDB` = donor s1,
  `trailing_fire_* 0x15C-0x183` = donor s2, `ball_particles_c/d 0x235-0x249`
  = donor s5, `ball_particles_a/b 0x2A5-0x2B9` = donor s4,
  `landing_dust_* 0x31A-0x341` = donor s6, `square_particles_* 0x3C6-0x3DD`
  = donor s7). The 2 excluded copy records twin the donor's own unshipped
  pair, matching the donor's "30/33" scope.

**NOT wired this mission (LIVE-hold + harness-gapped, spec §6.3/§6.4):**
`EfKbCa` (Falcon — copied punch actually reuses Kick/trail/dots ptcl, low
shipped overlap), `EfKbSs` (Samus — only 2 records twin a shipped extra),
`EfKbPk` (Pikachu — 6 records, jolt starburst unconfirmed live),
`EfKbPc` (Pichu — no donor `EfPcData.dat` Ef file exists to diff against).

### `PlKb.dat`

#### `07_07_07`

- 🔴 `0x117D0`: Up B projectile front/trail. Data: `07 07 07 04 FF FF FF 00 00 B2 FF`
- 🔴 `0x11890`: Up B other half. Data: `07 07 07 04 FF FF FF 00 00 B2 FF`

#### `42_48`

- 🔴 `0x12ABC`: Side B hammer handle. Data: `80 80 80 FF FF FF FF FF FF FF FF FF 3F 80 00 00 42 48`
- 🔴 `0x12B5C`: Side B hammer head wood. Data: `80 80 80 FF FF FF FF FF FF FF FF FF 3F 80 00 00 42 48`
- 🔴 `0x12BFC`: Side B hammer head star. Data: `80 80 80 FF FF FF FF FF FF FF FF FF 3F 80 00 00 42 48`

### `EfKbData.dat`

#### `07_07_07`

- 🔴 `0xD15C`: Up B falling effect. Data: `07 07 07 04 FF FF FF 00 00 B2 FF`
- 🔴 `0xF50C`: Jab rapid color. Data: `07 07 07 04 FF FF FF 00 00 CC FF`

#### `42_48`

- 🔴 `0xC17C`: Up B spin at top. Data: `80 80 80 FF FF FF FF FF FF FF FF FF 00 00 00 00 42 48`
- 🔴 `0xD1CC`: Up B falling colors. Data: `80 80 80 FF 00 FF FF FF FF FF FF FF 00 00 00 00 42 48`
- 🔴 `0xEC94`: Side B end effect. Data: `80 80 80 FF FF FF FF FF FF FF FF FF 00 00 00 00 42 48`

#### `CF_##`

- 🔴 `0x1C8`: Dash Attack smoke
- 🔴 `0x1D5`: Dash Attack smoke
- 🔴 `0x1FD`: Dash Attack faint smoke
- 🔴 `0x27A`: Dash Attack square particles
- 🔴 `0x28A`: Dash Attack square particles
- 🔴 `0x37F`: Neutral B swallow particle
- 🔴 `0x38C`: Neutral B swallow particles
- 🔴 `0x3A7`: Neutral B particles
- 🔴 `0x3AD`: Neutral B particles
- 🔴 `0x42C`: Neutral B swallow particles
- 🔴 `0x439`: Neutral B swallow particles
- 🔴 `0x454`: Neutral B particles
- 🔴 `0x45A`: Neutral B particles

(Neutral B swallow/particle candidates above = the Inhale scripts 4/10/11 —
**LIVE-DEAD 2026-07-02**, see the "Final Cutter / Hammer / Inhale / Puff-air
— NOT wired, DEAD" section above; the white suction dots are model/item
driven, not a colorable ptcl operand.)

**SUPERSEDED 2026-07-02** — the "Down B rocks/halo/line/ray" candidate list
that was here (`0x51C`/`0x529`/`0x530`/`0x589`/`0x596`/`0x5F1`/`0x5FE`/
`0x605`/`0x664`/`0x671`/`0x678`/`0x6D4`/`0x6E1`/`0x6E8`/`0x794`/`0x7A1`/
`0x7A8`/`0x801`/`0x80E`/`0x815`/`0x869`/`0x876`/`0x87D`/`0x8DC`/`0x8E9`/
`0x8F0`/`0x94C`/`0x959`/`0x960`) was a static line-start read, consistently
2 bytes early per template lesson 1. The corrected, LIVE-poke-verified
offsets ship as the `kirby_stone` extra — see "`EfKbData.dat` — Stone
(down-B) — app extra `kirby_stone`" above for the exact byte-verified list
(`0x51E`/`0x52B`/`0x532`/`0x58B`/`0x592`/`0x598`/`0x59F`/`0x796`/`0x7A3`/
`0x381`/`0x38E`/`0x3A9`/`0x3AF`; `0x42E`-`0x465` LIVE-DEAD, not shipped).

#### `98_00_##_##`

- 🔴 `0xB580-0xB5F5`: Dash attack front column
- 🔴 `0xB5F6-0xB657`: Dash attack second column
- 🔴 `0xB658-0xB6A5`: Dash attack last column
- 🔴 `0xC3C0-0xC416`: Up B blade 1 trailing
- 🔴 `0xC417-0xC46D`: Up B blade 1 solid
- 🔴 `0xC4C0-0xC576`: Up B blade 2
- 🔴 `0xC5C0-0xC5DE`: Up B blade 3 tip
- 🔴 `0xC5DF-0xC675`: Up B blade 3 rest
- 🔴 `0xC6C0-0xC716`: Up B blade 4 trailing
- 🔴 `0xC717-0xC75D`: Up B blade 4 solid
- 🔴 `0xC7A0-0xC7EE`: Up B shadow spin
- 🔴 `0xDA80-0xDB5A`: Up B sword color
- 🔴 `0xDB5B-0xDB99`: Up B sword handle
- 🔴 `0xDB9A-0xDBC0`: Up B handle back

## Ice Climbers

### `PlPp.dat`

#### `42_48`

- 🔴 `0xE840`: Up B Rope. Data: `B3 B3 B3 FF FF FF FF FF FF FF FF FF 3F 80 00 00`

### `EfIcData.dat`

WIRE 2026-07-02 from the MAP-LIVE spec `research/docs-research/effect-maps/
iceclimbers.md`. Bank index 14 in `efAsync_DatEntries`, `effect_id_start =
14000` → script index = gfx_id − 14000. **Popo and Nana SHARE this file** —
`efAsync_DatEntries` has exactly ONE `EfIcData.dat` entry, so a single patch
here recolors BOTH climbers' Ice Shots automatically; there is no separate
Nana copy to also patch (unlike a fighter-DAT edit). Almost everything in
this file is icy-blue (`79B8F7`, `2E66FF`, `515DFF`, `1994FF`, `0F3BFF`) —
no purple/warm operands anywhere, so red is the universal anti-color.

#### `CF_##` (script 0 — Ice Shot birth flash)

- 🟢✅ `0xE2`: birth flash light-blue core (PRIM). Ships as `ice_shot birth_a_c1`. Data: `79 B8 F7`
- 🟢✅ `0xE9`: birth flash pure-blue env (ENV). `birth_a_c2`. Data: `01 01 F9`
- 🟢✅ `0xEF`: birth flash blue (PRIM). `birth_b_c1`. Data: `2E 66 FF`
- 🟢✅ `0xF6`: birth flash blue env (ENV). `birth_b_c2`. Data: `0B 07 EE`
- 🟢✅ `0x103`: birth flash blue (PRIM, no paired ENV). `birth_c_c1`. Data: `67 9C FE`

LIVE-VERIFIED 2026-07-02 (`tests/artifacts/datram-probe-iceclimbers/
probe-iceclimbers-solo/ice_shot_birth-neutralb-f10.png`): the spawn swirl
vortex turned red (vanilla blue swirl → red). All 5 offsets byte-verified.

#### `CF_##` (Family A sparkle — scripts 2, 6, 8, 12) — identical vanilla across all four

- 🟢✅ `0x1A5`/`0x335`/`0x3EC`/`0x58C`: sparkle near-white core (PRIM). Ships as `ice_shot sparkle_c1` (one key, 4 offsets — byte-identical). Data: `FA FC FF`
- 🟢✅ `0x1AC`/`0x33C`/`0x3F3`/`0x593`: sparkle blue env (ENV). `sparkle_c2`. Data: `51 5D FF`
- 🟢✅ `0x1B2`/`0x342`/`0x3F9`/`0x599`: sparkle pale-cyan (PRIM). `sparkle2_c1`. Data: `BA EE FF`

LIVE-VERIFIED (subtle) 2026-07-02 (`probe-iceclimbers-solo/
ice_shot_sparkle-neutralb-f22.png`): the birth/impact sparkle burst at the
block base goes red — flagged for EYEBALL double-check at f22 (subtle
shift). All 3 keys / 12 offsets byte-verified.

#### `CF_##` (scripts 3/4 — Ice Shot block-glow variants)

- 🟢✅ `0x20E`: variant near-white (PRIM, script 3). Ships as `ice_shot variant_a_c1`. Data: `FA FC FF`
- 🟢✅ `0x215`: variant blue env (ENV, script 3). `variant_a_c2`. Data: `2E 17 FF`
- 🟢✅ `0x21B`: variant cyan-blue (PRIM, script 3). `variant_b_c1`. Data: `1A B4 DE`
- 🟢✅ `0x276`: variant near-white (PRIM, script 4). `variant_c_c1`. Data: `FA FC FF`
- 🟢✅ `0x27D`: variant blue env (ENV, script 4). `variant_c_c2`. Data: `2E 17 FF`
- 🟢✅ `0x283`: variant pale-cyan (PRIM, script 4). `variant_d_c1`. Data: `82 EB FF`

LIVE-VERIFIED 2026-07-02 (`probe-iceclimbers-solo/
ice_shot_variants-neutralb-f22.png`): one ice block's internal glow turns
red inside. All 6 offsets byte-verified. Scripts 0, Family A, and 3/4 all
ship together as ONE `ice_shot` extra (one recolorable Ice Shot look, per
the spec's editor grouping).

#### `CF_##` (Family B freeze crystals — scripts 9, 11, 13, 15) — NOT wired, DEAD

- 🔴 `0x44A`/`0x527`/`0x5EA`/`0x656`: freeze crystal blue (PRIM). Candidate
  vanilla `19 94 FF`.
- 🔴 `0x451`/`0x52E`/`0x5F1`/`0x65D`: freeze crystal deep-blue env (ENV).
  Candidate vanilla `13 03 BD`.
- 🔴 `0x458`/`0x535`/`0x5F8`/`0x664`: freeze crystal blue (PRIM). Candidate
  vanilla `0F 3B FF`.

**LIVE-DEAD** 2026-07-02 (`probe-iceclimbers-freeze/
freeze_crystals-neutralb-f22.png` & `-f30.png`): the victim (DK) froze and
shattered but the blue snowflake glyph + crystal shards stayed BLUE with
pokes active + readback-OK. The freeze visual is item texture/model, not
these ptcl operands — candidate for a future `type: "texture"` recolor, not
a ptcl layer. Not shipped. (The green radial hit-spark seen in the same
capture is a shared/common-bank effect present in vanilla too — not ours.)

#### Texture-only / no ptcl colour

- ⚪ Script 1 (Ice Shot travel): 0 operands, texture-only.
- ⚪ Script 7 (`0x36B7`, down-B Blizzard): 0 operands, texture-only — the
  snow model is the item's own geometry/texture.

#### Quarantine (NOT EfIcData layers)

- ⚠️ `0x4AE`/`0x4AF`/`0x4B0` → gfx `0xB3B0`/`0xB3B1`/`0xB3B6` (`efalt.c:453`,
  bank `0x2E`): spawned by `itClimbersice` but land in a DIFFERENT, higher
  effect bank, NOT EfIcData — do not ship as EfIc layers.
- ⚠️ Up-B Belay rope sparkle + side-B Squall Hammer swirl: no EfIc ptcl
  record located; likely fighter/item model + common-bank (`EfCoData.dat`)
  sparks — confirm in a future LIVE pass before declaring dead.

## Link

### `PlLk.dat`

#### `random`

- 🟢✅ `0x35EC`: Sword Swing. Data: `FF 00 00 FF FF 00 FF FF FF`. Note: Older notes sometimes cite 0x35E0 as the line start, but the editable color bytes begin at 0x35EC. Layout is the same as Marth 0x3948 (alphas + inner/outer RGB)

### `EfLkData.dat`

WIRE 2026-07-02 from the MAP-LIVE spec `research/docs-research/effect-maps/link.md`.
This file carries **no `HSD_ParticleGroup`** (Particles ptr = 0) — every color
lives in the `Models[]` model-region (signature-scanned via
`shared/rendering/ptcl_parse.py --models`, not the usual ptcl bank), so only a live
poke (not the parser) can attribute semantics. Shared by Young Link: `ftCLink`
has no separate `EfClData.dat` and loads `EfLkData` directly (no Child-Link
entry in `efasync.c efAsync_DatEntries[51]`) — a per-character edit here
affects BOTH Link and Young Link (`spin_attack_trail`'s `sharedWith`).

#### `07_07_07` (model-region blocks, no script index)

- 🟢✅ `0x550C` (marker; `color1` @ `0x5510`, `color2` @ `0x5514`): Up-B (Spin Attack) swirling blade/disc trail. Data: `07 07 07 04 FF FF FF 00 00 00 FF 00`. color1 (marker+4) = bright core (vanilla white), color2 (marker+8) = tint/glow (vanilla blue). LIVE-VERIFIED 2026-07-02: core→magenta + tint→red turned the swirling up-B disc trail magenta/red across the whole active window (f6–f30, best-framed f6–16). Byte-verified against vanilla `EfLkData.dat` 2026-07-02. Ships as the `spin_attack_trail` extra (owner Link, `sharedWith: ["Young Link"]`)
- 🔴 `0x4A1`: near-black `07_07_07` block (`c1=040206`, `c2=1C0E0E`). DEAD — no visible change on any tested move; too dark to read.

#### `42_48` / `98matrix` (not wired)

- ⚪ `0x558C`: generic material default (`808080 FFFFFF FFFFFF FFFFFF`). DEAD — no visible change.
- ⚪ `0x56A0`, `0x7860`: model vertex-color matrices. DEAD — invisible on every tested move.
- ⚪ `0x7758`–`0x7808`: generic LOD materials, not poked (same signature as the confirmed-dead `0x558C`).

#### Open leads

- **Bomb explosion disc (down-B) — UNTESTED.** The MAP-LIVE pass could not
  reach a bomb-throw+detonate recipe (Link's down-B recipe stalls in
  `LightThrowF4`, holding the pulled bomb — `MoveError`). EfLkData's second
  effect model (root `0x7A08`, `Models[2]`/`Models[3]`) is the strongest
  remaining candidate for the bomb visual; every other block in the file was
  live-poked dead, so if the bomb disc lives here it's in this untested
  model's own color slots, not the already-ruled-out 42/98 blocks. Needs a
  bomb-throw recipe added to `shared/ingame/moves.py` before it can be probed.
- **Hookshot chain/tip (s93/s331)** — per lesson 16/17 of
  `docs/dev/EXTRAS_MISSION_TEMPLATE.md`, these are common-bank (EfCoData) colors
  spawned from the `itlinkhookshot.c` article, not EfLkData — quarantined,
  same as the bomb/boomerang/arrow findings below. Confirmed reachable only
  by whiffing the tether into open air (the punching-bag harness force-parks
  the victim and skips the mid-flight phase where the chain/tip particles
  spawn) — STILL PENDING a dedicated common-bank/tether mapping pass, not
  wired here.

#### Quarantine (NOT EfLkData layers)

- ⚠️ Bomb explosion / boomerang trail / arrow / hookshot chain colors:
  spawned from the **article item files** (`itlinkbomb.c`,
  `itlinkboomerang.c`, `itlinkarrow.c`, `itlinkhookshot.c`) using **common-bank
  (EfCoData) gfx ids** (arrow `1096`, hookshot `1052`/`1009`) or (bomb/
  boomerang) no `efSync_Spawn` at all — their visuals are the article DAT
  model + subaction events. The community-known editable boomerang/arrow/bomb
  colors live in **`PlLk.dat`** (mods 15262/15263), out of this file's scope.
- ⚠️ Young Link visual tweaks → **`PlCl.dat`** (mod 12904), never a
  `EfClData.dat` (no such file exists).

## Luigi

WIRE 2026-07 from the MAP-LIVE spec `research/docs-research/effect-maps/luigi.md`
(live magenta-poke verified 2026-07-02, `tests/artifacts/datram-probe-luigi/`).
Every 🟢 offset below is marker-verified against vanilla bytes AND confirmed
by an in-game live poke (not just cited). Shipped as three extras:
`luigi_fireball` (PlLg.dat), `luigi_fireball_smoke` (EfLgData.dat),
`luigi_cyclone` (EfLgData.dat) — split across two target files because the
config schema is one `target_file` per extra (same pattern as Samus
screw_attack/missile/charge_shot). Final-verify build deferred to another
mission; see `docs/dev/EXTRAS_AUDIT.md` Luigi rows for the exact verify commands.

### `PlLg.dat` (fireball ARTICLE — not EfLgData; `It_Kind_Luigi_Fire`)

#### `07_07_07`

- 🟢 `0xF3B8` (marker; col1 `0xF3BC`): Fireball aura inner/outer. Data: `07 07 07 04 FF 66 00 00 FF 33 00`. Wired as `fb_aura_07_c1` in `luigi_fireball` (direct RGB @0xF3BC, part of the recolored aura group)

#### `42_48`

- 🟢 `0xF428` (prim `0xF42C`): Fireball aura — **the dominant green** (PrimCol `00FF00`). Data: `80 80 80 FF 00 FF 00 FF FF FF FF FF 3F 00 00 00 42 48`. Wired as `fb_aura_42_c1` in `luigi_fireball` — this is the EYEBALL-flagged lead/primary offset (spec: poking all 5 PlLg offsets together turned the fireball body/core aura magenta while the smoke trail stayed green)
- 🟢 `0xF4C8` (prim `0xF4CC`): Fireball core body. Data: `00 00 00 FF FF FF FF FF FF FF FF FF 00 00 00 00 42 48`. Wired as `fb_body_42_c1` in `luigi_fireball`

### `EfLgData.dat`

#### `07_07_07` (marker+4 = col1, marker+8 = col2; col1≠col2 per tornado block so each is wired as a direct RGB slot, falcon_kick technique)

- 🟢 `0x111E0` (col1 `0x111F0`, col2 `0x111F4`): Neutral-B hand ring. Data: `07 07 07 04 CC FF E5 00 19 B2 00`. Wired as `hand_ring_07_c1`/`hand_ring_07_c2` in `luigi_fireball_smoke` (part of the recolored ring — live-poke turned the oval ring/portal at Luigi's hand magenta at fireball spawn)
- 🟢 `0x11A7C` (col1 `0x11A80`, col2 `0x11A84`): Tornado outer swirl. Data: `07 07 07 04 FF FF B2 00 FF B2 00`. Wired as `torn_outer_c1`/`torn_outer_c2` in `luigi_cyclone`
- 🟢 `0x11B48` (col1 `0x11B4C`, col2 `0x11B50`): Tornado upper swirl. Data: `07 07 07 04 FF FF B2 00 FF CC 00`. Wired as `torn_upper_c1`/`torn_upper_c2`
- 🟢 `0x11C14` (col1 `0x11C18`, col2 `0x11C1C`): Tornado inner side 1. Data: `07 07 07 04 FF FF E5 00 FF FF 00`. Wired as `torn_inner1_c1`/`torn_inner1_c2`
- 🟢 `0x11CE0` (col1 `0x11CE4`, col2 `0x11CE8`): Tornado inner side 2. Data: `07 07 07 04 FF FF CC 00 FF FF 00`. Wired as `torn_inner2_c1`/`torn_inner2_c2`
- 🟢 `0x11DAC` (col1 `0x11DB0`, col2 `0x11DB4`): Tornado underneath. Data: `07 07 07 04 FF FF CC 00 FF B2 00`. Wired as `torn_under_c1`/`torn_under_c2`

Live verdict: all 5 tornado 07-blocks together (`tornado_07`) turned BOTH the
horizontal swirls around Luigi's arms AND the ground ring magenta
(`tornado_07-downb-f14.png`).

#### `CF_##` (hand-spawn smoke particle records; color at marker+2 = `_c1`, secondary at colorpos+7 = `_c2` per lesson 3 — corrected from the old CF marker-only cites)

- 🟢 `0xFD` (marker; color `0xFF`, secondary `0x106`): Fireball hand/spawn smoke puff (script 0, record a). Wired as `fb_smoke_s0a_c1`/`fb_smoke_s0a_c2` in `luigi_fireball_smoke`. Vanilla `26FF43`/`2ABA4E`
- 🟢 `0x10A` (marker; color `0x10C`, secondary `0x113`): Fireball hand/spawn smoke puff (script 0, record b). Wired as `fb_smoke_s0b_c1`/`fb_smoke_s0b_c2`. Vanilla `149C2D`/`0C5419`
- 🟢 `0x184` (marker; color `0x186`/`0x194`/`0x1A7`/`0x1B4`, secondary `0x18D`/`0x19B`/`0x1AE`/`0x1BB`): **STRONG** fireball hand/spawn smoke puff (script 1, 4 records) — was flagged "weak grey/olive lead" pre-LIVE; corrected: live-poke turned it a **strong bright magenta**, a dominant fireball smoke layer. Wired as `fb_smoke_s1_c1`/`fb_smoke_s1_c2`. Vanilla `93A394`/`22AB0A`
- 🟢 `0x26B` (marker; color `0x26D`, secondary `0x281`): Fireball spawn smoke (script 3). Wired as `fb_smoke_s3_c1`/`fb_smoke_s3_c2`. Vanilla `02FD02`/`052E15`
- 🟢 `0x2DB` (marker; color `0x2DD`, secondary `0x2F1`): Fireball spawn smoke (script 4). Wired as `fb_smoke_s4_c1`/`fb_smoke_s4_c2`. Vanilla `16FD22`/`0A4F12`
- 🟢 `0x350` (marker; color `0x352`, secondary `0x372`): Fireball smoke/dust (script 5). Wired as `fb_dust_s5_c1`/`fb_dust_s5_c2`. Vanilla `BDFDBB`/`31F83B`
- 🟢 `0x3FC` (marker; color `0x3FE`, secondary `0x40E`): Fireball particles (script 6). Wired as `fb_particle_s6_c1`/`fb_particle_s6_c2`. Vanilla `1ADC24`/`7CFF70`

Live verdict: the `fb_smoke_particles` poke turned the hand-spawn smoke puff
magenta; the traveling fireball trail (further from the hand) stayed green
under every poke here — that trail is **common-bank (EfCoData)**, quarantined,
NOT an EfLgData layer.

#### `42_48`

- 🟢 `0x1125C` (prim `0x11260`, env `0x11264`): Ring/portal around hand after fireball. Data: `80 80 80 FF 66 FF 99 FF FF FF FF FF 00 00 00 00 42 48`. Wired as `hand_ring_42_c1`/`hand_ring_42_c2` in `luigi_fireball_smoke`
- 🟢 `0x11AEC` (prim `0x11AF0`, env `0x11AF4`): Tornado outer ring finish. Data: `80 80 80 FF FF FF D0 FF FF FF FF FF 00 00 00 00 42 48`. Wired as `torn_outer_fin_c1`/`torn_outer_fin_c2` in `luigi_cyclone`
- 🟢 `0x11BB8` (prim `0x11BBC`, env `0x11BC0`): Tornado finish. Data: `80 80 80 FF FF FF D0 FF FF FF FF FF 00 00 00 00 42 48`. Wired as `torn_fin_c1`/`torn_fin_c2`
- 🟢 `0x11C84` (prim `0x11C88`, env `0x11C8C`): Tornado finish side 1. Data: `80 80 80 FF FF FF D0 FF FF FF FF FF 00 00 00 00 42 48`. Wired as `torn_fin_s1_c1`/`torn_fin_s1_c2`
- 🟢 `0x11D50` (prim `0x11D54`, env `0x11D58`): Tornado finish side 2. Data: `80 80 80 FF FF FF D0 FF FF FF FF FF 00 00 00 00 42 48`. Wired as `torn_fin_s2_c1`/`torn_fin_s2_c2`
- 🟢 `0x11E1C` (prim `0x11E20`, env `0x11E24`): Tornado below Luigi. Data: `80 80 80 FF FF FF E3 FF FF FF FF FF 00 00 00 00 42 48`. Wired as `torn_below_c1`/`torn_below_c2`

Live verdict: all 5 finish blocks together (`tornado_42_finish`) turned the
tornado ring/dissipation finish magenta — subtle at peak swirl but clear on
the trailing/ground ring (`tornado_42_finish-downb-f24.png` ground ring pink,
`-f14.png` residual ring purple vs vanilla white).

#### Not wired (see spec quarantine/open-leads)

- 🟡 `spark_yellow_s9` (CF `0x536`/`0x53D`/`0x547`, grp4), `spark_yellow_s10`
  (CF `0x5A6`/`0x5AD`/`0x5B3`, grp4): up-B (Super Jump Punch) coin/sweetspot
  spark — **on-hit only**, no solo GFX (poked blue on whiffed up-B AND down-B,
  no change). Pending the punching-bag harness. Anti-color for future wiring:
  `0000FF`.
- 🟡 `spark_blue_s11` (CF `0x60A`/`0x611`/`0x617`, grp5): impact spark —
  **on-hit only**, no solo GFX (poked red on taunt/side-B/up-B, no change).
  Luigi's taunt draws no spark GFX solo at all. Pending punching-bag. Anti-color
  for future wiring: `FF0000`.
- ⚠️ Side-B (Green Missile) flame/trail (common-bank gfx `0x50A`) and misfire
  flame: normal missile draws only a white smoke trail (EfCoData, quarantined);
  no misfire rolled during the MAP-LIVE pass — LIVE-pending-multiple-attempts,
  not wired.
- ⚠️ Fireball hand-cast GFX + impact (gfx 1287/1288/1202) and tornado spawn
  (gfx `0x509`): every `efSync_Spawn` id in Luigi's decomp source is <18000 →
  resolves into **EfCoData** (common bank), never an EfLgData/PlLg layer.
  Route to any EfCoData mapping mission.
- ⚠️ 9 texanim/matrix `98matrix` blocks (`0xD4F7`, `0x1131C`, `0x1147B`,
  `0x11EE0`, `0x11FC0`, `0x12060`, `0x120C0`, `0x120E0`, `0x12893`): matrix/
  texanim tables, not RGB triples. Never ship as color layers.

## Mario

WIRE 2026-07 from the MAP-LIVE spec `research/docs-research/effect-maps/mario.md`
(live-poke verified 2026-07-02, `tests/artifacts/datram-probe-mario/` +
`tests/artifacts/datram-probe-mario-extra/`). Every 🟢 offset below is
marker-verified against vanilla bytes AND confirmed by an in-game live poke.
Shipped as six extras: `mario_fireball` (EfMrData.dat, Mario only),
`mario_fireball_aura` (PlMr.dat, Mario only), `cape_sparkles` (EfMrData.dat,
**shared** — owner Mario, sharedWith Dr. Mario), `mario_cape` (PlMr.dat,
Mario), `mario_tornado` (EfMrData.dat, **shared**), `mario_coins`
(EfMrData.dat `texGraphicBank`, `texture_recolor` format, **shared**) — split
across target files because the config schema is one `target_file` per extra
(Luigi/Samus precedent). `EfMrData.dat` is the shared Mario/Doc effect table
(not a common bank like EfCoData): its rows are char layers for BOTH
characters except the fireball ptcls (Doc never spawns `gfx_id 1146`). The
up-B "coin punch" CF records were confirmed **DEAD** with the punching-bag
harness 2026-07-02 (see below) — the coin sprite turned out to be a plain
texture in the same file's tex bank, resolved as `mario_coins` (items-pass
MAP, `research/docs-research/effect-maps/items.md`). Final-verify build deferred for
all six; see `docs/dev/EXTRAS_AUDIT.md` Mario/Dr. Mario rows for the exact verify
commands.

### `PlMr.dat`

#### `07_07_07`

- 🟢 `0xFA40` (marker; col1 `0xFA44`, col2 `0xFA48`): Fireball aura glow halo
  inner/outer — the soft round glow surrounding the fireball orb turned cyan
  under live-poke. Data: `07 07 07 04 FF 66 00 00 FF 33 00`.
  Un-corroborated by ref mod 15777 (adds a new fireball model instead of
  touching this block) but LIVE-confirmed. Wired as `aura_07_c1`/`aura_07_c2`
  in `mario_fireball_aura` (Mario only).

#### `42_48`

- 🟢 `0xFAB0` (marker; diffuse `0xFAB4`): Fireball aura material — contributes
  to the fireball body glow, bundled in the cyan-aura poke. Data:
  `80 80 80 FF FF 4C 00 FF FF FF FF FF 3F 00 00 00 42 48`. Ships DIFFUSE
  (+4) only — ambient (+0) is a verified no-op (Fox/Falco precedent). Wired
  as `aura_42_c1` in `mario_fireball_aura`.
- 🟢 `0xFB50` (marker; diffuse `0xFB54`): Fireball color material — the
  white core orb itself stayed a separate texture, unaffected; this block
  contributes to the surrounding glow. Data:
  `00 00 00 FF FF FF FF FF FF FF FF FF 00 00 00 00 42 48`. Wired as
  `body_42_c1` in `mario_fireball_aura`.
- 🟢 `0x14EAC` (block start = diffuse; env `0x14EB0`; marker `42 48` @0x14EBC): Cape cloth color —
  turned bright green under live-poke, STRONG and clean (the ship headline
  of the cape group). Data: `FF FF FF FF FF FF FF FF 33 33 33 FF 3F 80 00 00`.
  Wired as `cloth_c1`/`cloth_c2` in `mario_cape` (Mario; Doc's own cloth is
  `PlDr.dat` 0x19CA8, see the Dr. Mario section — different offset, same
  block layout).

### `EfMrData.dat` (shared Mario/Dr. Mario effect table; `EffectIDStart = 1000`)

#### `07_07_07` (marker+4 = col1/core, marker+8 = col2/glow)

- 🟢 `0x11AF4` (col1 `0x11AF8`, col2 `0x11AFC`): Fireball hand circle — the
  ring that flashes around Mario's hand at spawn; verified via the
  neutral-B poke (spatially adjacent to the tornado script region but
  semantically the fireball's own hand ring). Data:
  `07 07 07 04 FF FF B2 00 FF 66 00`. Wired as `hand_ring_07_c1`/
  `hand_ring_07_c2` in `mario_fireball` (Mario only — kept OUT of
  `mario_tornado` since Doc has no fireball to show it).
- 🟢 `0x1237C` (col1 `0x12380`, col2 `0x12384`): Tornado outer swirl 1 —
  red poke turned the whole vortex + spin arcs + ground ripple full red,
  identical on Doc. Data: `07 07 07 04 B2 FF FF 00 00 00 FF`. Wired as
  `outer_swirl1_c1`/`outer_swirl1_c2` in `mario_tornado` (**shared**, owner
  Mario, sharedWith Dr. Mario).
- 🟢 `0x12448` (col1 `0x1244C`, col2 `0x12450`): Tornado outer swirl 2. Data:
  `07 07 07 04 B2 FF FF 00 00 00 FF`. Wired as `outer_swirl2_c1`/
  `outer_swirl2_c2`.
- 🟢 `0x12514` (col1 `0x12518`, col2 `0x1251C`): Tornado inner side 1. Data:
  `07 07 07 04 99 CC FF 00 00 00 FF`. Wired as `inner_side1_c1`/
  `inner_side1_c2`.
- 🟢 `0x125E0` (col1 `0x125E4`, col2 `0x125E8`): Tornado inner side 2. Data:
  `07 07 07 04 99 CC FF 00 00 00 FF`. Wired as `inner_side2_c1`/
  `inner_side2_c2`.
- 🟢 `0x126AC` (col1 `0x126B0`, col2 `0x126B4`): Tornado underneath. Data:
  `07 07 07 04 CC FF FF 00 00 33 FF`. Wired as `underneath_c1`/
  `underneath_c2`.

All six markers verified at their exact old-cited offsets (no drift).

#### `CF_##` (color at marker+2 = `_c1`, secondary/EnvCol at colorpos+7 = `_c2`
per lesson 3; each record's vanilla bytes differ, so every record is its
own key rather than grouped — the `mario_fireball` editor's two pickers
still fan out to all of them)

- 🟢 `0x160` (color `0x162`, secondary `0x169`): Fireball hand/muzzle smoke
  burst at spawn (record a). Vanilla `FFFFFF`/`FFCC4A`. Wired as
  `hand_smoke_a_c1`/`hand_smoke_a_c2` in `mario_fireball` (Mario only).
- 🟢 `0x175` (color `0x177`, secondary `0x17E`): Hand/muzzle smoke (record
  b). Vanilla `FFA217`/`BA120D`. Wired as `hand_smoke_b_c1`/
  `hand_smoke_b_c2`.
- 🟢 `0x182` (color `0x184`, secondary `0x18B`, interp cnt=7): Hand/muzzle
  smoke (record c). Vanilla `9C060B`/`540405`. Wired as `hand_smoke_c_c1`/
  `hand_smoke_c_c2`.
- 🟢 `0x20A` (color `0x20C`, secondary `0x213`): Trailing fire plume behind
  the fireball (record a). Vanilla `C7BB0D`/`D43B08`. Wired as
  `trailing_fire_a_c1`/`trailing_fire_a_c2`.
- 🟢 `0x21D` (color `0x21F`, secondary `0x226`): Trailing fire plume (record
  b). Vanilla `FFA800`/`FF5900`. Wired as `trailing_fire_b_c1`/
  `trailing_fire_b_c2`.
- 🟢 `0x22A` (color `0x22C`, secondary `0x233`, cnt=8): Trailing fire plume
  (record c). Vanilla `FF070F`/`510A00`. Wired as `trailing_fire_c_c1`/
  `trailing_fire_c_c2`.
- 🟢 `0x2E3` (color `0x2E5`, secondary `0x2EC`): Scattered ball particles /
  end-burst sparks (record a). Vanilla `FDEB74`/`E33C09`. Wired as
  `ball_particles_a_c1`/`ball_particles_a_c2`.
- 🟢 `0x2F0` (color `0x2F2`, secondary `0x2F9`, cnt=12): Ball particles
  (record b). Vanilla `B90303`/`610101`. Wired as `ball_particles_b_c1`/
  `ball_particles_b_c2`.
- 🟢 `0x353` (color `0x355`, secondary `0x35C`): Ball particles (record c).
  Vanilla `FDE467`/`D42304`. Wired as `ball_particles_c_c1`/
  `ball_particles_c_c2`.
- 🟢 `0x360` (color `0x362`, secondary `0x369`, cnt=12): Particles around
  fireball (record d). Vanilla `7D4202`/`2E0000`. Wired as
  `ball_particles_d_c1`/`ball_particles_d_c2`.
- 🟢 `0x3C8` (color `0x3CA`, secondary `0x3D1`): Fireball landing/expiry
  dust (record a) — **old cite 0x3C9 was off by 1; real marker 0x3C8**.
  Vanilla `FEFCE2`/`FFF75C`. Wired as `landing_dust_a_c1`/
  `landing_dust_a_c2`.
- 🟢 `0x3DB` (color `0x3DD`, secondary `0x3E4`): Landing dust (record b).
  Vanilla `FCE669`/`D60B0E`. Wired as `landing_dust_b_c1`/
  `landing_dust_b_c2`.
- 🟢 `0x3E8` (color `0x3EA`, secondary `0x3F1`, cnt=7): Landing dust (record
  c). Vanilla `F9AC06`/`6B0507`. Wired as `landing_dust_c_c1`/
  `landing_dust_c_c2`.
- 🟢 `0x474` (color `0x476`, secondary `0x47D`): Square particles at
  fireball endpoint (record a). Vanilla `FF290C`/`FFFF82`. Wired as
  `square_particles_a_c1`/`square_particles_a_c2`.
- 🟢 `0x484` (color `0x486`, secondary `0x48D`): Square particles (record
  b). Vanilla `FFFF6E`/`FF0C14`. Wired as `square_particles_b_c1`/
  `square_particles_b_c2`.

Fireball CF verdict: all 15 records live-poke confirmed (`fb_hand_smoke`,
`fb_trailing_fire`, `fb_ball_particles`, `fb_landing_dust`,
`fb_square_particles` groups) — Mario only, no equivalent effect on Doc.

- 🟢 `0x4DE` (color `0x4E0`, secondary `0x4E7`): Cape swing sparkle star
  (record a). Vanilla `6BFDFF`/`1105FF`. Wired as `sparkle_a_c1`/
  `sparkle_a_c2` in `cape_sparkles` (**shared**, owner Mario, sharedWith
  Dr. Mario).
- 🟢 `0x4EB` (color `0x4ED`, cnt=8): Cape swing sparkle (record b) — **old
  cite 0x4EC was bogus; real marker 0x4EB**. No AD/DF secondary pair.
  Vanilla `D1A3FF`. Wired as `sparkle_b_c1`.
- 🟢 `0x503` (color `0x505`, cnt=4): Cape sparkle faint (record c). Vanilla
  `BF09A1`. Wired as `sparkle_c_c1`.
- 🟢 `0x567` (color `0x569`): Smaller trailing cape sparkle — black/alpha-
  mask PrimCol base with no envcol pair, but an isolated green poke
  produced a visible cyan/teal sparkle at the cape's bottom edge; **NOT
  dead**. Vanilla `000000`. Wired as `sparkle_trail_c1`.

Cape sparkle verdict: SUBTLE — vanilla sparkles are inherently multi-hue
(blue/cyan/magenta/pink stars), so the poke shift reads faint. Flagged for
EYEBALL confirmation, not a clean-cut verdict like the cloth. Fires
identically on Doc (confirmed via `docmario_probe`).

- ⚪ `0x62C`/`0x635`, `0x63D`, `0x69C`/`0x6A5`, `0x6A9`, `0x700`/`0x709`,
  `0x70F`: Up-B "coin punch" contact CF records (hypothesized: contact
  coin/burst, rays, fist effect). **DEAD, confirmed 2026-07-02 with the
  punching-bag harness** (`tests/artifacts/extras-audit/Mario-upb_coin-bag/`):
  all 6 records poked green/magenta/red produced no measurable change to the
  on-contact coin ring, for either Mario or Doc. **The coin was never a color
  record — it was EfMrData `texGraphicBank` group 0 all along**, a plain
  texture (8× CI8 64×64 spin-pose images at `0x7A0`-`0x97A0`, each with its
  own RGB5A3 palette; see `research/docs-research/effect-maps/items.md` §4). Shipped as
  the `mario_coins` extra (`texture_recolor` format, CI8-palette shape, shared
  Mario/Dr. Mario) — see the `EfMrData.dat` texGraphicBank note below. These 6
  CF offsets stay unwired/dead.

#### `texGraphicBank` (texture, not a ptcl/model color record)

- 🟢✅ Group 0 (8 images, CI8, 64×64, extent `0x7A0`-`0x97A0`): the up-B coin
  sprite (spin poses). Each image `{offset, palette}` pair: `0x7A0`/`0x87A0`,
  `0x17A0`/`0x89A0`, `0x27A0`/`0x8BA0`, `0x37A0`/`0x8DA0`, `0x47A0`/`0x8FA0`,
  `0x57A0`/`0x91A0`, `0x67A0`/`0x93A0`, `0x77A0`/`0x95A0` (RGB5A3 palette
  format, byte-verified against vanilla `EfMrData.dat` 2026-07-02, from
  `python shared/rendering/ptcl_texbank.py EfMrData.dat --groups 0 --json`).
  `vanilla_dominant_hue` 47.6 (gold). Recolor rotates each image's palette
  entries only (pixel indices untouched) — same CI8-palette `texture_recolor`
  shape as `common_fire`/`common_flash`. Wired as `mario_coins` (**shared**,
  owner Mario, sharedWith Dr. Mario — `EfMrData.dat` is the shared Mario/Doc
  effect table).

#### `42_48` (marker+16 = `42 48`; color RGBA at block start; diffuse @+4
dominates, ambient @+0 is a verified no-op — Fox/Falco precedent, ships
diffuse only)

- 🟢 `0x11B64` (marker `0x11B74`; diffuse `0x11B68`): Ring around hand after
  fireball. Data: `80 80 80 FF FF FF 99 FF FF FF FF FF 00 00 00 00 42 48`.
  Wired as `hand_ring_42_c1` in `mario_fireball` (Mario only — bundled with
  the fireball hand-ring 07-block, not the tornado extra).
- 🟢 `0x123EC` (marker `0x123FC`; diffuse `0x123F0`): Tornado ground ripple
  / outer ending — green split-test turned the ground ripple + horizontal
  spin haze visibly green; ambient(+0) magenta split-test produced no
  change. Data: `80 80 80 FF FF FF D0 FF FF FF FF FF 00 00 00 00 42 48`.
  Wired as `ground_ripple1_42_c1` in `mario_tornado` (**shared**).
- 🟢 `0x124B8` (marker `0x124C8`; diffuse `0x124BC`): Tornado ground ripple
  / outer ending. Data:
  `80 80 80 FF FF FF D0 FF FF FF FF FF 00 00 00 00 42 48`. Wired as
  `ground_ripple2_42_c1`.
- 🟢 `0x12584` (marker `0x12594`; diffuse `0x12588`): Tornado spin haze
  side 1. Data: `80 80 80 FF FF FF D0 FF FF FF FF FF 00 00 00 00 42 48`.
  Wired as `spin_haze1_42_c1`.
- 🟢 `0x12650` (marker `0x12660`; diffuse `0x12654`): Tornado spin haze
  side 2. Data: `80 80 80 FF FF FF D0 FF FF FF FF FF 00 00 00 00 42 48`.
  Wired as `spin_haze2_42_c1`.
- 🟢 `0x1271C` (marker `0x1272C`; diffuse `0x12720`): Tornado ground haze
  below Mario — **old cite 0x1271B was off by 1; real marker 0x1271C**.
  Data: `80 80 80 FF FF FF E3 FF FF FF FF FF 00 00 00 00 42 48`. Wired as
  `ground_haze_42_c1`.

Ambient bytes (block+0: 0x11B64, 0x123EC, 0x124B8, 0x12584, 0x12650,
0x1271C) are a verified no-op — NOT exposed (would be a dead editor
control). Tornado verdict: all 5 diffuse blocks together turned the ground
ripple / spin haze visibly green in the split test; fires identically on
Doc (confirmed via `docmario_probe`).

## Marth

### `PlMs.dat`

#### `random`

- 🟢✅ `0x3948`: Sword Swing. Data: `FF 00 00 FF FF 00 FF FF FF`. Note: layout is `[alpha at blade][alpha at tail][inner-edge RGB][pad][outer-edge RGB]` (decomp itSword_UnkBytes / ftafterimage.c) — NOT three RGB colors; vanilla trail is inner-cyan → outer-white

### `EfMsData.dat`

- 🔴 **`sword_glow` — HARNESS-BLOCKED, DO NOT WIRE (LIVE 2026-07-02).** Blue
  sword-glow ptcl scripts identified structurally (`research/docs-research/effect-maps/
  marth-effects.md`), but the moves that would demonstrate them could not be
  reached with the current harness (mission rule: no layer ships 🟢 without an
  eyeballed change) — the candidate remains genuinely undemonstrated, not
  confirmed dead. Do not add this as an extra until a harness fix (or a
  different demo move) lands; see `marth-effects.md` for the exact blocker.

## Mewtwo

### `PlMt.dat`

#### `07_07_07`

- 🟢✅ `0x100B0`: Shadow Ball center when thrown. Data: `FF FF FF 00 00 00 FF 00` (verified: color1 = center, color2 = ring; only the THROWN ball — charge center is 0x105D0 below)
- 🟢✅ `0x102D0`: Inner Shadow Ball bolt. Data: `FF FF FF 00 00 7F FF 00` (marker @0x102CC; +4 = bolt line, +8 = bolt glow; live-poke + build-verified 2026-07, exposed as shadow_ball `bolts_c1`/`bolts_c2`)
- 🟢✅ `0x10390`: Inner Shadow Ball bolt. Data: `FF FF FF 00 00 7F FF 00` (marker @0x1038C; same layer)
- 🟢✅ `0x10450`: Inner Shadow Ball bolt. Data: `FF FF FF 00 00 7F FF 00` (marker @0x1044C; same layer)
- 🟢✅ `0x10510`: Inner Shadow Ball bolt. Data: `FF FF FF 00 00 7F FF 00` (marker @0x1050C; same layer)
- 🟢✅ `0x105D0`: Shadow Ball center charging. Data: `FF FF FF 00 00 00 FF 00` (marker @0x105CC; +4 = charge center flash, +8 = glow around it; does NOT affect the thrown ball — exposed as shadow_ball `charge_c1`/`charge_c2`)

### `EfMtData.dat`

#### `07_07_07`

- 🟢✅ `0xC758`: Up Smash swirl. Data: `66 00 CC 00 00 00 00 00` (marker @0xC754; exposed as the Mewtwo `upsmash` extra 2026-07). Verified by human eyes 2026-07-02: the color change is real but VERY subtle (faint swirl element on the whiffed up-smash — automated whole-frame diffing missed it). No separate on-hit effect exists for this move.
- 🔴 `0xCD30`: Forward Smash burst. Data: `FF A9 FF 00 33 00 66 00`
- 🔴 `0xCDFC`: Forward Smash burst. Data: `FF 7F FF 00 00 00 00 FF`
- 🔴 `0xD994`: Up B flash. Data: `E5 FF FF 00 66 00 66 00`
- 🔴 `0xDA54`: Up B flash. Data: `E5 FF FF 00 66 00 66 00`
- 🔴 `0xDBE0`: Up B light. Data: `FF FF FF 00 00 00 FF 00`

#### `42_48`

- 🔴 `0xC7C4`: Up Smash mist. Data: `80 80 80 FF 00 00 00 FF`
- 🔴 `0xDA00`: Up B flash right side. Data: `80 80 80 FF FF FF FF FF`
- 🔴 `0xDAC0`: Up B flash left side. Data: `80 80 80 FF FF FF FF FF`

## Ness

WIRE 2026-07-02 from the MAP-LIVE spec `research/docs-research/effect-maps/ness.md` +
the items-pass MAP `research/docs-research/effect-maps/items.md`. PK Thunder
tail/ball/lightning below is shipped as extra `ness_pk_thunder`; PK Fire's
burn PILLAR (the on-hit article, three `070707` blocks) is shipped as
`ness_pk_fire` (bag-verified 2026-07-02). The remaining PK Fire / PK Flash
rows are **NOT** EfNsData/PlNs model-color layers per LIVE (PK Flash stayed
vanilla green under every EfNsData model poke — it's the PK Flash article's
own model / a common effect; PK Fire's hand-cast flash was identical across
every poke — also article/common, not wired) and are left here unmarked as
historical candidates only, not open leads. `EfNsData.dat` Models[2]
(`ness_psi_magnet`, down-B PSI Magnet absorb aura, 7 `070707` blocks) is a
SEPARATE file from this section — see `research/docs-research/effect-maps/ness.md`
for its offset table (not duplicated here; PlNs is this doc's Ness scope).

### `PlNs.dat`

#### `07_07_07`

- 🔴 `0x10190`: PK Fire lens flare. Data: `04 FF FF 66 00 FF E5 00` (not wired — PK Fire cast flash is article/common, not an EfNsData/PlNs model layer per LIVE)
- 🟢✅ `0x11A8C` (marker; `pillar_ring_in_c1` @ `0x11A90`, `pillar_ring_in_c2` @ `0x11A94`): PK Fire pillar bottom ring INSIDE. Data: `04 FF FF FF 00 00 7F FF`. **VERIFIED 2026-07-02 with the punching bag** (`research/docs-research/effect-maps/items.md` §2, DK dx=10): the vanilla BLUE horizontal ring through the target's midsection turned bright GREEN with magenta glow edges/sparks at f24. Wired as `ness_pk_fire`.
- 🟢✅ `0x11B58` (marker; `pillar_aura_c1` @ `0x11B5C`, `pillar_aura_c2` @ `0x11B60`): PK Fire pillar MAIN fire aura. Data: `04 FF FF E5 00 FF 99 00`. **VERIFIED 2026-07-02 with the punching bag**: aura ring/glow at the pillar base turned green+purple at f32. The tall orange fire BODY column itself did NOT recolor (texture, not this block). Wired as `ness_pk_fire`.
- 🟢✅ `0x11DF8` (marker; `pillar_ring_out_c1` @ `0x11DFC`, `pillar_ring_out_c2` @ `0x11E00`): PK Fire pillar bottom ring OUTSIDE. Data: `04 FF FF FF 00 00 7F FF`. **VERIFIED 2026-07-02 with the punching bag** — same result as the inside ring. Wired as `ness_pk_fire`.
- 🔴 `0x16A10`: PK Flash charge aura. Data: `04 00 CC 00 00 00 99 00` (not wired — PK Flash stayed vanilla green under every EfNsData model poke per LIVE; not an EfNsData/PlNs model layer)
- 🔴 `0x16C10`: PK Flash charge center. Data: `04 FF FF FF 00 00 E5 00` (see above)
- 🔴 `0x16CD0`: PK Flash charge flash. Data: `04 FF FF FF 00 00 E5 00` (see above)
- 🔴 `0x16D90`: PK Flash charge flash. Data: `04 FF FF FF 00 00 E5 00` (see above)
- 🔴 `0x16E50`: PK Flash charge flash. Data: `04 FF FF FF 00 00 E5 00` (see above)
- 🔴 `0x16F10`: PK Flash charge flash. Data: `04 FF FF FF 00 00 E5 00` (see above)
- 🔴 `0x1D630`: PK Flash explosion. Data: `04 00 CC 00 00 00 99 00` (see above)
- 🔴 `0x1D6F0`: PK Flash explosion. Data: `04 FF FF FF 00 00 CC 00` (see above)
- 🔴 `0x1D7B0`: PK Flash explosion. Data: `04 FF FF FF 00 00 CC 00` (see above)
- 🔴 `0x1D870`: PK Flash explosion. Data: `04 FF FF FF 00 00 CC 00` (see above)
- 🔴 `0x1D930`: PK Flash explosion. Data: `04 FF FF EF 00 00 CC 00` (see above)
- 🔴 `0x1D9F0`: PK Flash explosion. Data: `04 FF FF FF 00 00 CC 00` (see above)
- 🔴 `0x1DAB0`: PK Flash explosion. Data: `04 FF FF FF 00 00 CC 00` (see above)
- 🔴 `0x1DB70`: PK Flash explosion. Data: `04 FF FF FF 00 00 4C FF` (see above)
- 🔴 `0x1DC30`: PK Flash explosion. Data: `04 FF FF FF 00 00 4C FF` (see above)
- 🔴 `0x1DCF0`: PK Flash explosion. Data: `04 FF FF FF 00 00 CC 00` (see above)
- 🟢✅ `0x24038` (marker; extra key `tip_c1` @ marker+4 = `0x2403C`): PK Thunder tip. Data: `04 FF FF FF 00 00 4C FF` (verified 2026-07-02; vanilla `004CFF`; fans from `ness_pk_thunder`'s Tail/Bolt picker)
- 🟢✅ `0x2C3F8` (marker; `tail1_c1` @ `0x2C3FC`): PK Thunder tail. Data: `04 FF FF FF 00 00 4C FF` (verified; vanilla `004CFF`)
- 🟢✅ `0x2C778` (marker; `tail2_c1` @ `0x2C77C`): PK Thunder tail. Data: `04 FF FF FF 00 00 4C FF` (verified; vanilla `004CFF`)
- 🟢✅ `0x2CAF8` (marker; `tail_main_c1` @ `0x2CAFC`): PK Thunder tail main. Data: `04 FF FF FF 00 00 4C FF` (verified; vanilla `004CFF`)
- 🟢✅ `0x2D3CC` (marker; `ball_flare1_c2` @ `0x2D3D0`): PK Thunder aura. Data: `04 FF FF FF 00 00 00 FF` (verified; vanilla `0000FF`; fans from the Ball Flare picker, colorpos+8)
- 🟢✅ `0x2D52C` (marker; `ball_flare2_c2` @ `0x2D530`): PK Thunder aura and ball. Data: `04 FF FF FF 00 00 00 FF` (verified; vanilla `0000FF`)
- 🟢✅ `0x2D5EC` (marker; `lightning1_c1` @ `0x2D5F0`): PK Thunder lightning. Data: `04 FF FF FF 00 00 33 FF` (verified; vanilla `0033FF`)
- 🟢✅ `0x2D6AC` (marker; `lightning2_c1` @ `0x2D6B0`): PK Thunder lightning. Data: `04 FF FF FF 00 00 33 FF` (verified; vanilla `0033FF`)
- 🟢✅ `0x2D76C` (marker; `lightning3_c1` @ `0x2D770`): PK Thunder lightning. Data: `04 FF FF FF 00 00 33 FF` (verified; vanilla `0033FF`)
- 🟢✅ `0x2D828` (marker; `lightning4_c1` @ **`0x2D830`**, NOT `0x2D82E`): PK Thunder lightning. Data: `04 FF FF F9 00 00 66 FF`. **WIRE CORRECTION 2026-07-02**: the previous cite `0x2D82E` pointed at byte 2 of c1 (marker+6, mid-`FFFFF9`), not a color position — it patches raw geometry data and would corrupt the record. Byte-dumped against the marker (`07 07 07 04` @ `0x2D828`, identical structure to the other 3 lightning records) confirms c1 = marker+4 = `0x2D82C` (`FFFFF9`) and c2 = marker+8 = `0x2D830` (`0066FF`, the value this row's "lightning" label refers to). Ships at `0x2D830`, byte-verified against vanilla `PlNs.dat` 2026-07-02.

### `EfNsData.dat`

Not duplicated here (out of this doc's `PlNs.dat`-focused historical scope) —
see `research/docs-research/effect-maps/ness.md` for the full 🟢 VERIFIED `Models[2]`
PSI Magnet table (extra `ness_psi_magnet`, 7 `070707` blocks, per-record
vanilla). `Models[0]`/`Models[1]` (bat sparkle / yo-yo spark) are on-hit-only,
pending the punching-bag harness — not wired.

#### Not wired (see spec quarantine/open-leads)

- ⚠️ `EfNsData.dat` `Models[0]` (2 `070707` blocks, `0x13270`/`0x13330`) and
  `Models[1]` (9 `070707` blocks, `0x13D84`–`0x14390`): bat swing sparkle /
  yo-yo disc spark, on-hit only — neither responded to neutralb/sideb/downb/upb
  solo, and re-booted bat/yo-yo tests show the sparkle/spark only appears
  on-contact. Pending the punching-bag harness (task exists).
- ⚠️ PK Fire (side-B) hand-cast flash and PK Flash (neutral-B) explosion: not
  `EfNsData.dat` model blocks — self-colored article model / common-bank
  effect (see the `07_07_07` rows above, unmarked).
- ⚠️ Ness's PK Thunder hit sparks (`efSync_Spawn(1030/1262/1263)`) resolve into
  **EfCoData** (common bank, cast-shared) — never a Ness layer. Quarantine
  list shared with Pikachu, see the Pikachu section below.

## Peach

### `PlPe.dat`

#### `42_48`

- 🔴 `0x160A0`: Turnip Leaves. Data: `B3 B3 B3 FF FF FF FF FF FF FF FF FF 3F 80 00 00`
- 🔴 `0x16140`: Turnip Leaves. Data: `B3 B3 B3 FF FF FF FF FF FF FF FF FF 3F 80 00 00`
- 🔴 `0x161E0`: Turnip Leaves. Data: `B3 B3 B3 FF FF FF FF FF FF FF FF FF 3F 80 00 00`
- 🔴 `0x16280`: Turnip Leaves. Data: `B3 B3 B3 FF FF FF FF FF FF FF FF FF 3F 80 00 00`
- 🔴 `0x16320`: Turnip Leaves. Data: `B3 B3 B3 FF FF FF FF FF FF FF FF FF 3F 80 00 00`
- 🔴 `0x163C0`: Turnip Leaves. Data: `B3 B3 B3 FF FF FF FF FF FF FF FF FF 3F 80 00 00`
- 🔴 `0x164F0`: Turnip Color. Data: `AC B3 A6 FF F9 FF F9 FF FF FF FF FF 3F 80 00 00`
- 🔴 `0x1D890`: Umbrella Handle. Data: `B3 B3 B3 FF FF FF FF FF FF FF FF FF 3F 80 00 00`
- 🔴 `0x1D940`: Umbrella Handle. Data: `80 80 80 FF B3 B3 B3 FF FF FF FF FF 3F 80 00 00`
- 🔴 `0x1D9D0`: Umbrella Outside Bottom Border. Data: `FF FF FF FF FF FF FF FF FF FF FF FF 3F 66 66 66`
- 🔴 `0x1DA70`: Umbrella Top. Data: `FF FF FF FF FF FF FF FF FF FF FF FF 3F 80 00 00`
- 🔴 `0x1DB10`: Umbrella Inside Bottom Border. Data: `FF FF FF FF FF FF FF FF FF FF FF FF 3F 66 66 66`

### `EfPeData.dat`

WIRE 2026-07-02 (`docs/dev/EXTRAS_AUDIT.md` "Peach: nothing shippable"): LIVE
found no attributable color-record effects in Peach's own effect bank.
Peach's signature visuals (Toad spore cloud, vegetable pull, parasol, Peach
Bomber flash) route through common-bank (`EfCoData.dat`) or item/texture
systems covered elsewhere in the audit, not a per-character `EfPeData`
ptcl/model color layer. ⚪ DEAD -- do not re-open without a new decomp lead.

#### `42_48`

- 🔴 `0xDC0`: Down B Dirt. Data: `B3 B3 B3 FF FF FF FF FF FF FF FF FF 3F 80 00 00`

## Pichu

### `PlPc.dat`

#### `07_07_07`

- 🟢✅ `0xBF14`: Down B Thunder. Data: `07 07 07 04 FF FF FF 00 FF FF 00` (added + verified 2026-07: color1 @0xBF18 = bolt core, color2 @0xBF1C = glow. Same block layout as Pikachu's 0xC350)

## Pikachu

WIRE 2026-07-02 from the MAP-LIVE spec `research/docs-research/effect-maps/pikachu.md`.
Down-B thunder (`0xC350`) was already shipped/verified before this pass and is
unchanged. Three new groups shipped this pass: `pikachu_thunder_jolt_air`
(EfPkData CF), `pikachu_thunder_jolt_ground` (PlPk ground bolt), `pikachu_fsmash`
(EfPkData 07-blocks) — all 🟡 PENDING EYEBALL (mechanical WIRE done, Dolphin
verify deferred, see `docs/dev/EXTRAS_AUDIT.md`). **Label correction (LIVE found):**
the "nair/dsmash electric arcs" label on the 0x17Cxx air-clone cluster below is
WRONG — the air clone didn't drive nair or dsmash in solo tests, and the dsmash
electric burst is a SEPARATE, unattributed effect that stayed vanilla-blue
under both the ground and air-clone pokes (candidate home: one of the 48
unlabeled 98-matrix blocks, not yet mapped). Do not read "Forward Smash"-labeled
0x17Cxx rows as verified nair/dsmash offsets.

### `PlPk.dat`

#### `07_07_07`

- 🟢✅ `0xC350`: Down B Thunder. Data: `04 FF FF FF 00 FF FF 00` (verified: color1 = bolt core, color2 = glow. Pikachu-only — Pichu's bolt is in PlPc.dat, see Pichu section)
- 🟢✅ `0x14DFC` (marker; extra key `jolt_gnd_a_c1`/`_c2` @ `0x14E00`/`0x14E04`): Ground Neutral B. Data: `04 B2 E5 FF 00 00 00 FF` (verified 2026-07-02 as part of `pikachu_thunder_jolt_ground`; vanilla c1 `B2E5FF`, c2 `0000FF`; grounded neutral-B turned the traveling bolt green-arc + magenta)
- 🟢✅ `0x14EC8` (marker; `jolt_gnd_b_c1`/`_c2` @ `0x14ECC`/`0x14ED0`): Ground Neutral B. Data: `04 B2 E5 FF 00 00 00 FF` (verified, same group)
- 🟢✅ `0x14F94` (marker; `jolt_gnd_c_c1`/`_c2` @ `0x14F98`/`0x14F9C`): Ground Neutral B. Data: `04 B2 E5 FF 00 00 00 FF` (verified, same group)
- 🟢✅ `0x15060` (marker; `jolt_gnd_d_c1`/`_c2` @ `0x15064`/`0x15068`): Ground Neutral B tail. Data: `04 B2 E5 FF 00 00 00 FF` (verified, same group)
- 🟢✅ `0x151F4` (extra key `jolt_gnd_head_c1`, single RGB, cyan-poked): Ground Neutral B head. Data: `07 FF FF FF 00 00 4C FF` (verified; vanilla `004CFF`; spawn starburst teal / cheek spark purple observed on LIVE)

### `EfPkData.dat`

Note: SHARED WITH PICHU

#### `CF_##`

- 🟢✅ `0x168`/env `0x16F` (extra keys `jolt_air_mid_c1`/`_c2`): Aerial Neutral B middle. Data: `FF FF FF C8 AD DF 00 66 81 FA` (verified 2026-07-02 as part of `pikachu_thunder_jolt_air`; PRIM `FFFFFF` = starburst core, ENV `6681FA` = outer lens glow, dominant sustained tint. Only confirmed via an AIRBORNE neutral-B — grounded neutralb does not fire this group, see moves.py gap note in EXTRAS_AUDIT.md)
- 🟢✅ `0x1D0`/env `0x1D7` (`jolt_air_outerflare_c1`/`_c2`): Aerial Neutral B outer lens flare. Data: `0B 0B E6 C8 AD DF 00 07 07 8F` (verified, same group)
- 🟢✅ `0x238`/env `0x23F` (`jolt_air_midflare_c1`/`_c2`): Aerial Neutral B middle lens flare. Data: `8F D6 FF C8 AD DF 00 0C 0C FF` (verified, same group)
- 🟢✅ `0x2A0`/env `0x2A7` (`jolt_air_innerborder_c1`/`_c2`): Aerial Neutral B inner border. Data: `FE 06 1B 32 AD DF 00 FB 9E 14` (verified, same group; ENV is orange `FB9E14` — magenta preferred over green as the anti-color, template lesson 11)
- 🟢✅ `0x2AD` (`jolt_air_innertri_c1`, prim only): Aerial Neutral B inner triangles. Data: `FF FF FF FF B1 B6 04 3F C9 0F` (verified, same group; vanilla `FFFFFF`)
- 🔴 `0x35D`: Over B smoke majority. Data: `FF FF FF FF AD DF 00 F9 68 01` (SKIP — solo side-B charge+launch reads plain white/gray, no visible response to the poke; 15070 also left it vanilla, not worth wiring)
- 🔴 `0x36A`: Over B outline/ending smoke. Data: `FC 8A 55 00 AD DF 10 84 00 00` (SKIP, see above)
- 🔴 `0x3D8`: Over B middle lens flare. Data: `FC F8 8D FF AD DF 00 F8 CF 02` (brief launch flash not captured at the tested frames — EYEBALL/punching-bag if skull-bash is ever revisited; leaning skip, whole move reads non-electric)
- 🔴 `0x3E5`: Over B ending lens flare. Data: `F7 03 0B 00 AD DF 08 84 00 00` (see above)
- 🔴 `0x440`: Over B starting lens flare. Data: `FF FF FF FF AD DF 00 F8 CF 02` (see above)
- 🔴 `0x44D`: Over B lines. Data: `FD 63 68 00 AD DF 08 84 00 00` (see above)
- 🔴 `0x4A7`: Over B lines. Data: `FF FF FF FF AD DF 00 F9 68 01` (see above)
- 🔴 `0x4B0`: Over B lines. Data: `FC 8A 55 00 AD DF 0C 84 00 00` (see above)

#### `07_07_07`

- 🟢✅ `0x148DC` (marker; extra keys `fsmash_pre_c1`/`_c2` @ `0x148E0`/`0x148E4`): Forward Smash lightning (GROUND, confirmed — label was previously ambiguous vs the 0x17Cxx air clone below). Data: `04 CC E5 FF 00 00 00 FF` (verified 2026-07-02 as part of `pikachu_fsmash`; fsmash arc turned green+magenta; vanilla c1 `CCE5FF`, c2 `0000FF`)
- 🟢✅ `0x14C80` (marker; `fsmash_aura1_c1`/`_c2` @ `0x14C84`/`0x14C88`): Forward Smash aura half 1 (GROUND). Data: `04 CC E5 FF 00 00 00 FF` (verified, same group)
- 🟢✅ `0x14D4C` (marker; `fsmash_aura2_c1`/`_c2` @ `0x14D50`/`0x14D54`): Forward Smash aura half 2 (GROUND). Data: `04 CC E5 FF 00 00 00 FF` (verified, same group)
- 🟢✅ `0x14E0C` (marker; `fsmash_ball_c1`/`_c2` @ `0x14E10`/`0x14E14`): Forward Smash ball/head (GROUND). Data: `04 FF FF FF 00 00 4C FF` (verified, same group; vanilla c1 `FFFFFF`, c2 `004CFF`)
- 🔴 `0x17C5C`/`0x18000`/`0x180CC`/`0x1818C`: byte-identical AIR-clone cluster of the four ground fsmash blocks above (same marker offsets +0x33FC). **NOT wired** — LIVE tested this cluster against fsmash/nair/dsmash solo and it did NOT respond to any of them (see the label-correction note at the top of this section); its owning aerial/2nd-hit trigger context is unknown. EYEBALL / punching-bag pending. Do not label this "nair/dsmash arcs" — that hypothesis is disproven.

#### `42_48`

- 🔴 `0x13F10`: Down B Aura. Data: `FF FF FF FF FF FF FF FF FF` (adjacent material recolor near the fsmash group per the 15070 diff; not a mission target, still open)

#### Not wired (see spec quarantine/open-leads)

- 🔴 skull-bash smoke/lens-flare CF group (`0x35D`/`0x36A`/`0x3D8`/`0x3E5`/
  `0x440`/`0x44D`/`0x4A7`/`0x4B0`, see rows above) — SKIP, reads plain
  white/gray/non-electric solo.
- 🔴 fsmash AIR clone (`0x17C5C`/`0x18000`/`0x180CC`/`0x1818C`) — unverified,
  did not respond to fsmash/nair/dsmash solo. EYEBALL/punching-bag pending.
- ⚠️ dsmash electric burst: unattributed, stayed vanilla-blue under both the
  ground and air-clone fsmash pokes — NOT `0x148xx`/`0x17Cxx`. Candidate home:
  one of the 48 unlabeled 98-matrix blocks between `0x14EC0`-`0x15DE0` /
  `0x180xx`-`0x1B0xx`. Open lead, not wired.
- ⚠️ Pikachu quick attack (up-B) streaks: `efSync_Spawn(1012)`, gated
  `kind != PICHU`, resolves into **EfCoData** (common bank) — never an EfPk
  layer. Quarantine diff clusters (vanilla `EfCoData` md5 `739290ea…` vs
  15070 `d1dd8ecd…`, shared with the Ness PK Thunder hit-spark quarantine
  above): `0xDC5 0xDDB 0xDF1 0xE0F 0xE1D 0xEAD 0x1033 0x12AF 0x1384 0x13AB
  0x13BA 0x13D7 0x1425 0x148D 0x14A1 0x14F5 0x1560 0x15BA 0x1609 0x1C17 0x1C24
  0x1C8D 0x1C9A 0x1CFF 0x2F15 0x5550 0x55B1 0x854E 0x855B 0x85B6 0x860E 0x9779
  0xA1DD 0xCDB7 0xCE18 0xCE84 0xCEEF 0xCFEC 0xD87D 0xD897 0x10019` (material
  `0x115AA8`/`0x115B74`).

## Roy

### `PlFe.dat`

#### `random`

- 🟢✅ `0x3AA0`: Sword Swing. Data: `FF 00 EB 78 50 00 FF FF FF`. Note: same layout as Marth 0x3948 (alphas + inner/outer RGB); Roy's vanilla inner edge is orange `EB7850`

### `EfFeData.dat`

- 🔴 **`sword_glow` — DEAD, entire bank (LIVE 2026-07-02).** EfFeData's ptcl
  bank mirrors Marth's EfMsData structurally (same 3 blue sword-glow scripts,
  `effEmblemDataTable`, EffectIDStart 49000 vs Marth's 16000) but ALL 5 poked
  moves (neutralb/sideb/downb/upb/sword swings) came back flat — pixel-diffs
  within star-twinkle noise, eyeballed Flare Blade (neutralb f30): no fire, no
  glow, only the shipped trail (`PlFe.dat 0x3AA0`) changed. **Nothing to ship
  from EfFeData** — see `research/docs-research/effect-maps/roy-effects.md`.
- ⚠️ **Roy's fire (Flare Blade / Blazer) is NOT in this file.** EfFeData's own
  texture bank is 3 grayscale groups (I4/I8, zero color) — the visible orange
  fire is the **shared EfCoData texGraphicBank group 9** (the ONE colored CI8
  fire texture in the game; Din's Fire, Bowser Bomb, Charizard breath, and
  Marth/Roy Flare Blade/Blazer all composite it). Already shipped as the
  Zelda-owned `common_fire` extra with `sharedWith: ["Bowser", "Marth", "Roy"]`
  — see the Mario section reference / `docs/dev/EXTRAS_AUDIT.md` common_fire row.
  Do not re-wire Roy's fire here.

## Samus

WIRE 2026-07 from the MAP-stage spec `research/docs-research/effect-maps/samus.md`.
Every offset below is marker-verified against vanilla `EfSsData.dat` bytes
(re-checked directly during WIRE, not just cited from the spec). Structural
parser cross-ref: `python shared/rendering/ptcl_parse.py EfSsData.dat --models` (symbol
`effSamusDataTable`, `effect_id_start=2000`).

### `EfSsData.dat`

#### `07_07_07` (model-region blocks, no script index)

- 🟢✅ `0x11584`: Up-B (Screw Attack) arc 1/4. Data: `07 07 07 04 FF FF FF 00 00 00 FF 00`. color1 (marker+4) = arc bright core (also drives the rising spiral spark ring), color2 (marker+8) = glow halo
- 🟢✅ `0x11644`: Up-B (Screw Attack) arc 2/4. Same layout/vanilla as 0x11584
- 🟢✅ `0x11704`: Up-B (Screw Attack) arc 3/4. Same layout/vanilla as 0x11584
- 🟢✅ `0x117C4`: Up-B (Screw Attack) arc 4/4. Same layout/vanilla as 0x11584

#### `CF_##` (particle records; color at marker+2, secondary at colorpos+7)

- 🟢✅ `0x46E`: Side-B Missile contrail smoke, record #0 (script 9, PRIMCOL #0). Data: `CF 00 C2 77 42 FF AD DF 00 6E 1B 1D 00`. `contrail_c1[0]` @0x470 = `C27742`, `contrail_c2[0]` (ENVCOL) @0x477 = `6E1B1D`
- 🟢✅ `0x47B`: Side-B Missile contrail smoke, record #1 (script 9, PRIMCOL #1). Data: `CF 20 86 7E 82 00 AD DF 20 00 00 00 A0`. `contrail_c1[1]` @0x47D = `867E82`, `contrail_c2[1]` (ENVCOL) @0x484 = `000000`
- 🟢✅ `0x61D`: Side-B Missile launch back-blast puff, record #1 (script 13, PRIMCOL #1, chained off marker 0x612). Data: `CF 05 D3 AB A1 FF AD DF 05 51 23 1F 00`. `backblast_c1[0]` @0x61F = `D3ABA1`, `backblast_c2[0]` (ENVCOL) @0x626 = `51231F`
- 🟢✅ `0x62B`: Side-B Missile launch back-blast puff, record #2 (script 13, PRIMCOL #2). Data: `CF 0F 44 3B 43 00 AD DF 0F 00 00 00 00`. `backblast_c1[1]` @0x62D = `443B43`, `backblast_c2[1]` (ENVCOL) @0x634 = `000000`
- 🟢✅ `0x2E7`: Neutral-B charge spark needles (script 5, PRIMCOL #0). Data: `CF 00 FF FF FF 00 AD DF 00 09 00 87 00`. `needles_c1` @0x2E9 = `FFFFFF` (radiating spark-needle lines around the arm cannon), `needles_c2` (ENVCOL) @0x2F0 = `090087`
- 🟡 `0x752` (script 16): structurally an exact clone of the back-blast group (same PRIMCOL/ENVCOL #0/#1/#2 ordinals, same texGrp 5) — no attributable visual on a whiffed missile. Real 13986-diff target, NOT wired; pending EYEBALL/punching-bag (see spec open leads)

#### Not wired (see spec quarantine/open-leads)

- ⚠️ `PlSs.dat` missile-body material (ambient `0x10600/0x106A0/0x10740/0x107E0`, `0xD414`): weak A/B in the MAP pass, not wired — pending EYEBALL with the effect region cropped.
- 🟡 `bomb` (down-B) candidate groups (EfSsData 0x4DF/0x6D6/0x7CF): detonation-frame flash bloom washed out every anti-color poke — pending EYEBALL with a tighter frame window, not wired this pass.
- Quarantined: `EfCoData.dat` (cast-shared common-effects file) — never a Samus layer, see spec.

### `PlSs.dat` (raw texture, `texture_recolor` format)

WIRE 2026-07: fired charge-shot ball, `charge_ball` extra. Not a ptcl/model
color record (every candidate above left the ball vanilla) — it is a single
RGB5A3 texture embedded in an effect/particle texture-graphics block, NOT on
a JOBJ→DObj→MObj material tree (`HSDRawViewer --texture export` fails with
`Expected HSD_JOBJ ... got SBM_FighterData`, ruling out the CLI `type:
"texture"` path used by Fox `upb_texture`/Falcon `punch_texture`). First
consumer of the new `format: "texture_recolor"` extra type
(`backend/vault/extras/texture_recolor.py`): a plain single ColorPicker
that rotates every texel's hue by `(target_hue − vanilla_dominant_hue)`,
preserving S/V/alpha (HSV) — never a flat fill, so the blue-glow/pink-ring/
white-core gradient survives the recolor.

- 🟢✅ `0x36840` (64×64, RGB5A3): the fired charge-shot ball — blue outer glow, magenta/pink inner ring, white core (~half transparent). `vanilla_dominant_hue = 239°` (saturation-weighted; the outer glow dominates). Ground truth / in-game verified prototype: `backend/shared/rendering/plss_ball_probe.py` + `tests/artifacts/samus-ball-texture/` (green/red recolor PNGs + patched DATs, verify capture `verify/samus-neutralb-f62.png`). IN-GAME VERIFIED 2026-07-02 (charge-and-fire boot, no garble/hang). STRAGGLER (not part of this texture): the thin blue elliptical orbit rings around the flying ball stay vanilla — separate unmapped element, not this layer.
- ⚪ `0x36040` (64×64, I4 grayscale): shape/intensity map for the same ball — **deliberately untouched** by the recolor (no hue to shift; the Powerbeam mod 14701 reshapes this region, corroborating it as the shape channel).

## Young Link

### `PlCl.dat`

#### `random`

- 🟢✅ `0x3790`: Sword Swing. Data: `FF 00 00 FF FF 00 FF FF FF`. Note: same layout as Marth 0x3948 (alphas + inner/outer RGB)

## Zelda / Sheik

Both forms' particle scripts live in ONE shared file, `EfZdData.dat` (symbol
`effZeldaDataTable`, id_start 17000). MAP-LIVE 2026-07-02:
`research/docs-research/effect-maps/zelda-sheik.md`. WIRE 2026-07-02: `zelda_farore`
+ `zelda_transform` shipped (app extra ids); Nayru's Love + both gradient
rings are DEAD (no live-poke attribution) and are NOT wired. `EfZdData.dat`
offsets below are the parser's exact color-BYTE positions (the `CF` opcode
is 2 bytes earlier); config format is direct `RGB` at these addresses, no
marker skip.

### `EfZdData.dat`

#### `CF_##` — Farore's Wind (scripts 2 grnd / 3 air) — app extra `zelda_farore`

- 🟢✅ `0x257` (PRIM, s2#0) / `0x25E` (ENV, s2#0): vanilla `03860E` / `035814` — grounded Farore's Wind burst core.
- 🟢✅ `0x2B8` (PRIM, s3#0) / `0x2BF` (ENV, s3#0): vanilla `0A7D3D` / `001C8C` — aerial burst core (up-B); magenta live-poke recolored the whole teleport-burst core, `tests/artifacts/datram-probe-zelda2/farore_burst-upb-f10.png`. The yellow/orange ribbon spirals are a MODEL-region element and stay put — not part of this layer.
- 🟢✅ `0x2C5` (PRIM, s3#1): vanilla `0BC52D` — part of the recolored burst core.
- 🟢✅ `0x2CC` (PRIM, s3#2): vanilla `01757E` — part of the recolored burst core.
- App grouping: `farore_c1` = the 4 PRIM offsets (multi-RGB); `farore_c2` = the 2 ENV offsets. Per-record vanilla bytes all DIFFER (spec lesson 12) — each offset keeps its own vanilla byte in the config.

#### `CF_##` — Transform flash (scripts 6 / 9, byte-identical) — app extra `zelda_transform` (owner Zelda, sharedWith Sheik)

- 🟢✅ `0x371` (PRIM core, s6) / `0x378` (ENV core, s6): vanilla `6D68FF` / `000082`.
- 🟢✅ `0x37E` (PRIM secondary, s6) / `0x385` (ENV secondary, s6): vanilla `FD676A` / `8F0000`.
- 🟢✅ `0x67B` (PRIM core, s9) / `0x682` (ENV core, s9): vanilla `6D68FF` / `000082` — BYTE-IDENTICAL to s6 (verified).
- 🟢✅ `0x688` (PRIM secondary, s9) / `0x68F` (ENV secondary, s9): vanilla `FD676A` / `8F0000` — BYTE-IDENTICAL to s6.
- Live-poke verified 2026-07-02 on BOTH forms (green poke): the chest-flash core orb/ring recolored on Zelda's down-B Transform AND on Sheik's down-B Transform (`tests/artifacts/datram-probe-zelda2/transform_flash-downb-f04..18.png` + `datram-probe-sheik2/sheik_transform_shared-downb-f10,f18.png`). The surrounding pink+blue sparkle STARS are a separate, unwired element.
- App grouping: `transform_c1` = the 4 PRIM offsets (s6+s9, multi-RGB); `transform_c2` = the 4 ENV offsets (s6+s9). Since s6==s9 byte-for-byte, one vanilla string per operand covers both records.
- ⚠️ Down-B Transform leaves the fighter in `Sleep` afterward, which poisons every later live-poke experiment in the same boot (template lesson 0) — verify this extra alone, don't batch with other Zelda/Sheik moves.

#### `CF_##` — DEAD, not wired

- ⚪ `0x186`/`0x18D` (s0, Nayru's Love grounded) and `0x1EE`/`0x1F5` (s1, aerial): vanilla `FFFFFF`/`06F406` both. Magenta poke — the reflect crystal + rim glow stayed fully blue; the color lives in a MODEL-region block, not these ptcl operands.
- ⚪ `0x3D4`/`0x3DB` + `0x3F3`/`0x3FA` (s7, gradient ring head/grad steps): vanilla `FFFFFF`/`0000FF` and `54DAFF`/`0000FF`. Magenta poke, no change on Nayru (neutralb) or Farore (upb) — not the blue crystal rim; unattributed.
- ⚪ `0x525`/`0x52C` + `0x544`/`0x54B` (s8, gradient ring head/grad steps): vanilla `FFFFFF`/`FF0CBB` and `FFBFFF`/`7F007F`. Green poke, no change on Nayru/Farore. OPEN LEAD: the pink sparkle stars visible during the transform are the strongest remaining candidate — never poked on downb (out of MAP boot budget).

#### Quarantine — routes to `EfCoData.dat` (common bank), NOT this file

Din's Fire (ember/explosion/charge glow), Sheik needles, the Sheik/Zelda
Farore-air companion spark, and Sheik Vanish all dispatch through
`EfCoData.dat` via `efsync.c`, not `EfZdData.dat` — out of this file's
scope. Sheik Vanish in particular has NO Zelda/Sheik-file color layer
possible; any Vanish recolor work belongs to an `EfCoData.dat` mission.

## Yoshi

MAP-LIVE 2026-07-02 (`research/docs-research/effect-maps/yoshi.md`): **both `EfYs`
ptcl candidates are DEAD — nothing shippable, nothing wired.**

- ⚪ `EfYsData.dat 0xAA`/`0xB1` (egg-throw core, CF, s0): vanilla `FEF777`/`FB0F1E`. Green/magenta poke, no visible change — the thrown egg is a `PlYs` model, not this puff.
- ⚪ `EfYsData.dat 0x112..0x16B` (egg flash, CF, s1, 10 PRIM steps, all vanilla `FFFFFF`): unreached by the solo harness — owner is the egg-LAY hatch flash (subaction spawn), not triggerable via sideb/downb alone.

No `zelda`-style app extra exists for Yoshi from this pass; see the spec for
the full quarantine list of cast-shared candidates that must NOT ship as
Yoshi layers.

## Menu / Stage Select

### `MnSlChr.usd`

#### `random`

- 🔴 `0x948`: Background. Data: `80 80 80 FF 00 0B 1A FF FF FF FF`

#### `07_07_07`

- 🔴 `0x10050`: Hand color. Data: `07 FF FF FF 00 00 00 33`
- 🔴 `0x10130`: P# Outline on Hand. Data: `07 FF 33 33 00 00 00 00`
- 🔴 `0x348E88`: Bottom frame. Data: `07 07 07 07 83 8F 94 00 83 8F 94`
- 🔴 `0x348F48`: Rule. Data: `07 07 07 07 92 9E A3 00 92 9E A3`
- 🔴 `0x349008`: Top frame. Data: `07 07 07 07 83 8F 94 00 83 8F 94`

### `MnSlMap.usd`

Note: 070707 effects are often constrained by adjacent 4248 effects. Color 2 of the 4248 effect limits both 070707 colors, and setting 4248 color 2 to FFFFFF gives full control. For the 3D preview entries, color 1 only slightly nudges color 2 and is constrained by it.

#### `07_07_07`

- 🔴 `0x95A00`: STAGE SELECT text (color 1) and outline (color 2). Data: `07 07 07 07 7F 7F 7F 00 7F 7F 7F`. Note: constrained by 42_48 at 95A70
- 🔴 `0x95B78`: Wires around screen (color 1) and outline (color 2). Data: `07 07 07 04 66 66 66 00 66 66 66`. Note: constrained by 42_48 at 95BE8
- 🔴 `0x96C44`: Stage name (color 1) and outline (color 2). Data: `07 07 07 04 FF FF FF 00 FF FF FF`
- 🔴 `0x9784C`: RANDOM text (color 1) and outline (color 2). Data: `07 07 07 04 00 00 00 00 00 00 00`

#### `42_48`

- 🔴 `0x6D1B0`: Blue background texture layer. Data: `80 80 80 FF FD FB FF FF FF FF FF FF 3F 7F BE 77 42 48`. Note: Set alpha to 00 to remove the blue background texture
- 🔴 `0x6D250`: Background images on stage select. Data: `80 80 80 FF B3 B3 B3 FF FF FF FF FF 3E 99 99 9A 42 48`. Note: Set alpha to 00 to remove the background images
- 🔴 `0x6D2F0`: Square grid in background (color 2). Data: `66 80 80 FF 99 B3 B3 FF E6 FF FF FF 3F 00 00 00 42 48`. Note: Change 3F to 00 to hide grid
- 🔴 `0x6EE1C`: Stage select cursor (color 2). Data: `80 80 80 FF 99 B3 B3 FF FF FF FF FF 3F 7F BE 77 42 48`
- 🔴 `0x6F0FC`: Flashing outline around hovered stage icon (color 2). Data: `FF FF FF FF FF FF FF FF FF FF FF FF 3F 7F BE 77 42 48`. Note: Flash 1 uses only the red channel from color 2. Flash 2 uses the full color 2 value. Example: 00FF00 gives a black first flash and green second flash
- 🔴 `0x78B24`: Kongo Jungle wooden poles 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x78BC4`: Kongo Jungle platforms 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x78C64`: Kongo Jungle floor 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x78D04`: Jungle Japes 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x78DA4`: Mushroom Kingdom II 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x78E44`: Mushroom Kingdom 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x78EE4`: Fountain of Dreams top platform 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x78F84`: Fountain of Dreams main platform 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x79024`: Fountain of Dreams flares under platform 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x790C4`: Fountain of Dreams waterfall 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x79164`: Green Greens 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x79204`: Dream Land 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x792A4`: Peach's Castle main 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x79344`: Peach's Castle platform 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x793E4`: Peach's Castle top 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x79484`: Peach's Castle other parts 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x79524`: Peach's Castle drawbridge 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x795C4`: Peach's Castle peak 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x79664`: Onett buildings 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x79704`: Fourside 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x797A4`: Rainbow Cruise 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x79844`: Brinstar 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x798E4`: Brinstar Depths 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x79984`: Temple 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x79A24`: Yoshi's Island 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x79AC4`: Yoshi's Story 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x79B64`: Yoshi's Island 64 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x79C04`: Kongo Jungle 64 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x79CA4`: Big Blue top 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x79D44`: Mute City outer loop 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x79DE4`: Mute City main track 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x79E84`: Flat Zone 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x79F24`: Venom/Corneria 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x79FC4`: Icicle Mountain 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x7A064`: Great Bay sphere 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x7A105`: Great Bay turtle 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x7A1A4`: All 3D preview bases. Data: `00 00 66 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x7A264`: Loading logo 3D preview. Data: `FF FF FF FF FF FF FF FF FF FF FF FF 3F 7F BE 77 42 48`
- 🔴 `0x7A304`: Pokemon Stadium 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x7A3A4`: Poke Floats 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x7A444`: Battlefield 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x7A4E4`: Final Destination 3D preview. Data: `00 33 99 FF 00 4C B3 FF 80 CC FF FF 3F 80 00 00 42 48`
- 🔴 `0x95A70`: STAGE SELECT text constraint. Data: `80 80 80 FF FF FF FF FF FF FF FF FF 00 00 00 00 42 48`. Note: Set color 2 to FFFFFF, then use 95A00 for separate text and outline control
- 🔴 `0x95B1C`: Circular STAGE SELECT. Data: `80 80 80 FF CC CC CC FF FF FF FF FF 00 00 00 00 42 48`
- 🔴 `0x95BE8`: Wires around screen constraint. Data: `80 80 80 FF FF FF FF FF FF FF FF FF 3F 7F BE 77 42 48`. Note: Set color 2 to FFFFFF, then use 95B78 for separate inner and outer wire control
- 🔴 `0x960D4`: Stage icon rows 2 and 4. Data: `80 80 80 FF FF FF FF FF FF FF FF FF 3F 7F BE 77 42 48`. Note: Set alpha to 00000000 to gray out rows 2 and 4
- 🔴 `0x96174`: Some stage portrait outlines. Data: `80 80 80 FF CC CC CC FF FF FF FF FF 3F 7F BE 77 42 48`
- 🔴 `0x96234`: Stage icon rows 1 and 3. Data: `80 80 80 FF FF FF FF FF FF FF FF FF 3F 7F BE 77 42 48`. Note: Set alpha to 00000000 to gray out rows 1 and 3
- 🔴 `0x96CB4`: Stage name color. Data: `80 80 80 FF FF FF FF FF FF FF FF FF 3F 7F BE 77 42 48`
- 🔴 `0x97404`: Bottom row icons. Data: `80 80 80 FF FF FF FF FF FF FF FF FF 3F 7F BE 77 42 48`. Note: Set alpha to 00000000 to gray out bottom row
- 🔴 `0x974A4`: Unknown. Data: `80 80 80 FF FF FF FF FF FF FF FF FF 3F 7F BE 77 42 48`
- 🔴 `0x978BC`: RANDOM text constraint. Data: `80 80 80 FF FF FF FF FF FF FF FF FF 3F 7F BE 77 42 48`. Note: Constrains the 070707 text and outline colors at 9784C
- 🔴 `0x9795C`: RANDOM box color. Data: `80 80 80 FF FF CC CC FF FF FF FF FF 3F 7F BE 77 42 48`
- 🔴 `0x97C04`: Icicle Mountain/Flat Zone icons. Data: `80 80 80 FF FF FF FF FF FF FF FF FF 3F 7F BE 77 42 48`. Note: Set alpha to 00000000 to gray out
- 🔴 `0x97CA4`: Unknown. Data: `80 80 80 FF FF FF FF FF FF FF FF FF 3F 7F BE 77 42 48`
- 🔴 `0x98130`: NOW LOADING screen tint after stage select (color 2). Data: `80 80 80 FF 00 00 00 FF FF FF FF FF 00 00 00 00 42 48`
- 🔴 `0x981F0`: Unknown. Data: `80 80 80 FF FF FF FF FF FF FF FF FF 3F 7F BE 77 42 48`

#### `85_80_08`

- 🔴 `0x7A1F0`: Loading logo 3D preview brightness. Data: `85 80 08 0F 07 43 04 07 96 96 96 FF 96 96 96`. Note: Both colors affect the brightness of the loading logo 3D preview at 7A264
- 🔴 `0x98180`: NOW LOADING text (color 1) and text box (color 2). Data: `85 80 08 0F 44 43 04 07 FF CC 33 FF 00 00 00`

## Pause

### `GmPause.usd`

#### `42_48`

- 🔴 `0x1234`: Bottom Right border. Data: `80 80 80 FF FF 00 FF FF FF 00 FF FF 3F 7F BE 77 42 48`
- 🔴 `0x12E0`: Bottom Left border. Data: `80 80 80 FF FF 00 FF FF FF 00 FF FF 3F 7F BE 77 42 48`
- 🔴 `0x138C`: Top Left border. Data: `80 80 80 FF FF 00 FF FF FF 00 FF FF 3F 7F BE 77 42 48`

#### `98_00_##_##`

- 🔴 `0x1FAB-0x1FAD`: + sign between A and St, RESET bar corner
- 🔴 `0x1FDB-0x1FFF`: L button
