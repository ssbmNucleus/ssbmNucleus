# Mapping spec: Fox/Falco shine sparkles (addendum to the shipped shine extra)

Status: MAP verified live (Fox, 2026-07 datram poke session); WIRE pending.
Scope: adds a `sparkles` color layer to the existing `shine` extra
(format `shine_gradient`). Fox offsets verified; Falco offsets must be
located by signature (see below) — do NOT guess.

## Verified layers (Fox — EfFxData.dat)

| layer_id | format | offsets | vanilla bytes | semantic | verified |
|---|---|---|---|---|---|
| sparkles (rec A) | CF-multi | marker `0x125`, color `0x127` (3B), secondary `0x12E` (3B, colorpos+7) | marker row: `CF 00 FF FF FF FF AD DF 00 2A A3 EE` (color `FFFFFF`, secondary `2AA3EE`) | sparkle particles emitted around the shine hexagon | live poke @0x127 + @0x12E, visible recolor |
| sparkles (rec B) | CF-multi | marker `0x141`, color `0x143` (3B), secondary `0x14A` (3B) | marker row: `CF 07 FF FF FF 00 FA 07 B8 00 40 00` (color `FFFFFF`, secondary `004000`) | second sparkle record (same visual family) | live poke @0x143 |

WIRE 2026-07: both marker bytes (`CF` at 0x125 and 0x141) confirmed against a
fresh `wit`-extracted vanilla ISO (`Super Smash Bros. Melee (USA)
(En,Ja) (v1.02).iso`, `P-GALE/files/EfFxData.dat`) whose `EfFxData.dat` is
byte-identical (md5 `0888286953144a05fcf004e81c8250b3`) to
`storage/test-base/files/EfFxData.dat`. Vanilla bytes above recorded from that
extraction, matching the spec's cites exactly.

Rules (template lessons 1–3): verify `CF` at each marker byte before
writing; write the SAME user color to primary and secondary positions of
both records (secondary dominates sustained tint).

## Falco (EfFcData.dat) — locate by signature — CORRECTED: no such file, no search needed

WIRE 2026-07 finding: `EfFcData.dat` **does not exist** in vanilla Melee (nor
anywhere in `storage/test-base`, this repo, or a fresh `wit EXTRACT` of
`Super Smash Bros. Melee (USA) (En,Ja) (v1.02).iso`). Vanilla's
`P-GALE/files/` has `EfFxData.dat` and `EfFeData.dat` but no third Fox/Falco
effect file. This matches the existing `shine`/`laser_ring`/`upb_texture`
extras in `backend/core/extra_types.py`: all three are single config objects with
`target_file: "EfFxData.dat"`, `shared: True`, `sharedWith: ["Falco"]`,
`owner: "Fox"` — Fox and Falco literally share the one file at build/read
time (`get_extra_types`/`get_storage_character` resolve Falco's shared extras
back to the same Fox-owned `EfFxData.dat` config, no per-character offsets).

The originally-planned signature search over a nonexistent `EfFcData.dat`
would have hit 0 matches — which is exactly the "skip loudly" trigger. But
the correct action here isn't "skip Falco sparkles": since Fox and Falco
already share the *entire* shine extra including offsets, sparkles just
inherit that same sharing for free — no separate Falco offsets, no separate
Falco wiring, no skip. Falco gets sparkles automatically once the shared
`shine` config carries the `sparkles` property, exactly like `hex`/`inner`/
`outer`/`bubble` already do.

## Wiring notes

- Both config mirrors: add `sparkles` to the shine extra's properties with
  its offset lists (Fox exact; Falco as found), single color picker.
- colors.py handles `shine_gradient` at 4 sites (~lines 112/283/576/732 via
  `read_shine_gradient_colors`); extend that path so sparkles applies on all
  four (apply / read-current / install / restore-vanilla).
- ShineEditorModal: add a "Sparkles" picker + preview dot; both
  ExtraPreviews.jsx mirrors.
- AUDIT_HINTS: shine already covered (downb); reuse its frames; anti-color
  suggestion: orange `FF6600`.

## Verify build (DEFERRED — Dolphin busy with Samus MAP)

`python devtools/extras_audit.py --char fox --extra shine --colors sparkles=FF6600`
(and falco if wired). Main session runs this after the Samus mission frees
the emulator.
