# Extras System Expansion Notes (Updated with Spoiler Data)

## Currently Implemented
- Fox laser (PlFx.dat) - 98 00 ## ## format
- Falco laser (PlFc.dat) - 98 00 ## ## format

---

## Format Corrections

### CF ## Format (NEW)
Actually much more complex than originally documented:
```
CF [count] [R1][G1][B1][A1] AD DF [flags] [R2][G2][B2]
```
- `AD DF` is a marker/separator
- The byte after `AD DF` is flags (00, 05, 07, 08, 09, 0C, 0F, 10, etc.)
- Two color values: RGBA before AD DF, RGB after

### 07 07 07 Format
Actually starts with `04` or `07`:
```
[04|07] [R1][G1][B1] 00 [R2][G2][B2] 00
```
- First byte is 04 or 07
- Color 1: bytes 1-3
- Color 2: bytes 5-7

### 42 48 Format
```
[R1][G1][B1][A1] [R2][G2][B2][A2] [R3][G3][B3][A3] [3E|3F] [??][??][??] 42 48
```
- Three RGBA colors
- Sometimes only 2 colors before the marker bytes

### Random Format (Sword Swings)
```
[R1] 00 [R2] [??] [??] 00 FF FF FF
```
Used for: Marth, Link, Roy, Young Link sword swings

---

## High Priority Additions

### 1. Shine (Fox/Falco Shared)
**File:** EfFxData.dat
**Format:** 98 00 ## ## (matrix)

| Offset Range | Effect |
|--------------|--------|
| 0x1C2A0-0x1C340 | Main shine effect |
| 0x1C8E0-0x1C990 | First frames (inner hex, outer glow, outer border) |

Plus CF ## sparkles at offset `0x125`.

### 2. Side-B Illusion
**Fox:** PlFx.dat offset `0x22050` (42 48 format)
**Falco:** PlFc.dat offset `0x1EC40` (42 48 format)
Data: `00 99 FF FF CC E6 FF FF FF FF FF FF 3E 99 99 9A`

### 3. Firefox/Firebird
**File:** EfFxData.dat
**Format:** Mixed CF ## and 07 07 07

| Offset | Effect | Format |
|--------|--------|--------|
| 0x2EE-0x536 | Trailing fire (multiple) | CF ## |
| 0x383-0x3C4 | Small trailing fire | CF ## |
| 0x43A-0x44A | Square dots | CF ## |
| 0x4A9 | Trailing smoke | CF ## |
| 0x5AF | Lines off charge | CF ## |
| 0x1A500 | Lens flare in motion | 07 07 07 |
| 0x1B450-0x1B520 | Fire rings | 07 07 07 |
| 0x1AC80-0x1AD00 | Firefox tip | 98 00 ## ## |

---

## Medium Priority Additions

### Captain Falcon (EfCaData.dat)
Extensive offsets for Falcon Punch, Kick, and Raptor Boost.

**Falcon Punch lens flare (07 07 07):**
- 0x22D60, 0x22E30, 0x22EF0, 0x22FC0, 0x23090, 0x23160, 0x23220, 0x232F0, 0x233C0, 0x23490

**Falcon Punch lens flare (42 48):**
- 0x22D00 - Small lens flare
- 0x235C0 - Big lens flare

**Falcon Kick tip:** 0x1DE00 (07 07 07)
**Falcon Punch tip:** 0x202E0 (07 07 07)
**Raptor Boost lens:** 0x24B70 (07 07 07), 0x25440 (42 48)

Plus ~40 CF ## offsets for smoke/particles on all specials.

### Mario Fireball (PlMr.dat + EfMrData.dat)
**PlMr.dat:**
- 0xFA40 - Fireball aura inner/outer (07 07 07)
- 0xFAB0 - Fireball aura main (42 48)
- 0xFB50 - Fireball color (42 48)
- 0x14EAC - Cape back (42 48)

**EfMrData.dat:** ~25 offsets for fireball, cape sparkle, tornado, up-B contact

### Luigi Fireball (PlLg.dat + EfLgData.dat)
Similar structure to Mario, green colors.
Plus full tornado color support.

### Ness PK Moves (PlNs.dat)
**30 offsets** covering:
- PK Fire (lens flare, fire rings, aura)
- PK Flash (charge, explosion - many offsets)
- PK Thunder (tip, tail, aura, lightning bolts)

### Pikachu/Pichu (PlPk.dat + EfPkData.dat)
**Note:** EfPkData.dat is SHARED between Pikachu and Pichu!
- Thunder (Down B)
- Neutral B (ground and aerial)
- Forward Smash aura

### Mewtwo (PlMt.dat + EfMtData.dat)
- Shadow Ball center/bolts (charging and thrown)
- Up Smash swirl/mist
- Forward Smash burst
- Up B flash/light

---

## Lower Priority (Simpler Effects)

### Sword Swing Colors (Random Format)
| Character | File | Offset |
|-----------|------|--------|
| Marth | PlMs.dat | 0x3948 |
| Link | PlLk.dat | 0x35E0 |
| Roy | PlFe.dat | 0x3AA0 |
| Young Link | PlCl.dat | 0x3790 |

### Peach (PlPe.dat)
- Turnip leaves (6 offsets)
- Turnip color: 0x164F0
- Umbrella (4 offsets)

### Kirby (PlKb.dat + EfKbData.dat)
Extremely detailed - Up B sword colors, hammer, dash attack, down B rocks/halos.

### Ice Climbers (PlPp.dat)
- Up B Rope: 0xE840 (42 48)

### Dr. Mario Cape (PlDr.dat)
- Cape color: 0x19CA0 (42 48)

### Falco Jacket (PlFc.dat)
- Inside jacket: 0x7C00 (42 48)

### Jigglypuff Sing Notes (EfPrData.dat)
- Red: 0x5440
- Green: 0x55C0
- Blue: 0x5500

---

## UI Elements

### Menu Hand (MnSlChr.usd)
- 0x10050 - Hand color (07 07 07)
- 0x10130 - P# outline (07 07 07)

### Pause Screen (GmPause.usd)
- 0x1234, 0x12E0, 0x138C - Borders (42 48)
- 0x1FAB-0x1FFF - Button icons (98 00 ## ##)

---

## Implementation Recommendations

### Phase 1: Expand Spacies
1. Add shine support (EfFxData.dat matrix offsets)
2. Add side-B illusion (42 48 in PlFx/PlFc)
3. Add firefox fire colors (CF ## in EfFxData.dat)

### Phase 2: Add Popular Characters
1. Captain Falcon - Falcon Punch is iconic
2. Marth - Sword swing is simple (random format)
3. Mario/Luigi - Fireball colors

### Phase 3: Full Coverage
1. Ness PK moves
2. Pikachu effects
3. Mewtwo Shadow Ball
4. Remaining characters

---

## Files Created
- `melee_color_offsets.json` - Full structured database
- `smashboards_offsets_reference.md` - Original reference (outdated)
- `extras_expansion_notes.md` - This file
