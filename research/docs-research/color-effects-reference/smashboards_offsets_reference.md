# Melee Color Effects Reference
Extracted from Smashboards thread "Changing Color Effects in Melee!" (Thread 313177)

## Color Formats

### 1. 07 07 07 Format (Basic RGB)
- Simple format: `07 RR GG BB` for each color
- Used for basic color effects
- Example: `07 FF FF FF 00 00 00 33`

### 2. 98 00 ## ## Format (Matrix/RGBY)
- Header: `98 00` followed by color count (2 bytes)
- Colors in RGBY 16-bit format
- Each entry: `## FC 00` where ## is the RGBY color value
- Used for: Lasers, many particle effects
- Example structure:
  ```
  98 00 17 22 FC 00 03 23 FC 00 05 21 FC 00 ...
  ```
  - `17` = number of colors (23 decimal)
  - `22 FC 00` = first color entry

### 3. 42 48 Format (Gradient/Material)
- Multiple RGBA values in sequence
- Format: `RR GG BB AA RR GG BB AA ... 3E 99 99 9A 42 48 00`
- The `42 48` marker appears at offset +0x10 from format start
- Used for: Shine, revival platform, pause screen borders
- Example:
  ```
  80 80 80 FF B3 B3 B3 FF FF FF FF FF 3E 99 99 9A 42 48 00
  ```
  - First 4 bytes: Color 1 (RGBA)
  - Next 4 bytes: Color 2 (RGBA)
  - Next 4 bytes: Color 3 (RGBA)

### 4. CF ## / DF ## Format (Color Effect)
- Header: `CF ##` or `DF ##` where ## is count
- Colors follow header
- Used for: Various special effects
- Input colors after the format header

---

## File Reference

| File | Character/Effect |
|------|-----------------|
| PlFx.dat | Fox (character-specific) |
| PlFc.dat | Falco (character-specific) |
| PlMs.dat | Marth |
| PlCa.dat | Captain Falcon |
| PlGn.dat | Ganondorf |
| PlKp.dat | Bowser |
| PlDr.dat | Dr. Mario |
| PlPe.dat | Peach |
| PlPp.dat | Ice Climbers |
| PlKb.dat | Kirby |
| EfFxData.dat | Fox/Falco SHARED effects (shine, firefox) |
| EfCaData.dat | Captain Falcon effects |
| EfGnData.dat | Ganondorf effects |
| EfCoData.dat | Common/shared effects (dust, smoke) |
| EfKpData.dat | Bowser effects |
| EfKbData.dat | Kirby effects |
| EfLgData.dat | Luigi effects |
| EfPkData.dat | Pikachu effects |
| PlCo.dat | Common character data (shield colors, auras) |

---

## Documented Offsets

### Fox (PlFx.dat)
| Offset | Effect | Format |
|--------|--------|--------|
| 0x13E20-0x13E70 | Laser wide (transparent) | 98 00 ## ## |
| 0x13EC0-0x13F10 | Laser thin (semi-transparent) | 98 00 ## ## |
| 0x13F60-0x13FB0 | Laser outline (opaque) | 98 00 ## ## |

### Falco (PlFc.dat)
| Offset | Effect | Format |
|--------|--------|--------|
| 0x13440-0x134A0 | Laser wide | 98 00 ## ## |
| 0x134E0-0x13540 | Laser thin | 98 00 ## ## |
| 0x13580-0x135E0 | Laser outline | 98 00 ## ## |

### Fox/Falco Shared (EfFxData.dat)
| Offset | Effect | Format |
|--------|--------|--------|
| 0x6D250 | Shine bubble | 42 48 |
| 0x1C2A0-0x1C340 | Shine (copy range for color swap) | varies |
| 0x18DA0-0x19D9F | Firefox _9 texture | texture |
| 0x10050 | Unknown effect | 07 07 07 |

**Shine transparent (42 48 format):**
- Original: `80 80 80 FF B3 B3 B3 FF FF FF FF FF 3E 99 99 9A 42 48 00`
- Transparent: `00 00 00 FF 00 00 00 FF FF FF FF FF 00 00 00 00 42 48 00`

### Captain Falcon (EfCaData.dat)
| Offset | Effect | Format |
|--------|--------|--------|
| 0x12D00-0x134FF | Falcon Punch _14 texture | texture |
| 0x13500-0x136FF | Falcon Punch Wings _14 texture | texture |
| 0x13700-0x146FF | Falcon Punch Fire _5 (transparent) | texture |
| 0x7C00 | Unknown effect | 42 48 |
| 0x24B70 | Raptor Boost Hand Lens Flare | 07 07 07? |
| 0x22050 | Effect (mentioned for red changes) | 42 48 |

**Falcon Punch smoke offsets mentioned:**
- Search for: `00 99 FF FF CC E6 FF FF FF FF FF FF 3E 99 99 9A 42 48 00`
- Change `00 99 FF` and `CC E6 FF` for smoke color

### Marth (PlMs.dat)
| Offset | Effect | Format |
|--------|--------|--------|
| 0x3940 area | Sword swing color | RRGGBB |

**Note:** Sword trail has two colors - main and secondary. RRGGBB format works for main color.

### Ice Climbers (PlPp.dat)
| Offset | Effect | Format |
|--------|--------|--------|
| 0xD960 | Ice block color | varies |

### Pause Screen Borders (unknown file)
| Offset | Effect | Format |
|--------|--------|--------|
| 0x1234 | Bottom Right border | 42 48 |
| 0x12E0 | Bottom Left border | 42 48 |
| 0x138C | Top Left border | 42 48 |

### Revival Platform (EfCoData.dat or PlCo.dat)
- Documented by nube - multiple color offsets for platform glow
- One offset controls color directly below character's feet

### Bowser (EfKpData.dat)
- CF## effects at start of file (undocumented)
- Flame effects are in this file

---

## Texture Types

| Type | Description |
|------|-------------|
| _5 | With transparency support |
| _8 | Standard texture |
| _9 | Used for firefox flame, some effects |
| _14 | Used for Falcon Punch |

---

## Body Auras / Hitbox Elements

Can change hitbox element to add visual effects:
- **Normal** - No aura
- **Fire** - Fire effect on hit
- **Electric** - Lightning effect on hit
- **Darkness** - Dark purple aura (like Ganon moves)

These are scattered throughout character files and PlCo.dat.

**Warning:** Changing hitbox elements can cause netplay desyncs!

---

## Tools Mentioned

- **HxD** - Hex editor (Ctrl+K to compare files, F6 to cycle differences)
- **GCRebuilder / GCTool** - Import/export dat files from ISO
- **Dolphin** - Texture dumping (OpenGL = .tga, Direct3D11 = .png)
- **DAT Texture Wizard (DTW)** - DRGN's tool for dat file editing
- **CrazyHand** - Hitbox/moveset editor
- **Melee Toolkit** - General purpose tool
- **TexConv.exe + TCS scripts** - TPL format conversion

---

## Tips & Tricks

1. **Finding unknown offsets:** Open two files in HxD, press Ctrl+K, then F6 to cycle through differences

2. **For 98 00 ## ## format:** The tool wants offset of `98`, uses bytes at offset+2 for color count

3. **For 42 48 format:** Actual format starts at offset of `42` minus 0x10

4. **Dumping textures for specific action:**
   - Start action in Dolphin
   - Pause
   - Delete all dumped textures
   - Resume
   - Do the move
   - Pause at end
   - Check new textures in folder

5. **Firefox/Shine conflict:** Both use EfFxData.dat - need to merge changes if modifying both

6. **Netplay safety:** PlFc.dat and PlFx.dat changes may cause desyncs. EfCoData.dat and shine changes appear safe.

---

## Undocumented / Requested Effects

These were asked about but not fully documented:
- Ness PK Thunder colors
- Sheik vanish/needles/chain
- Mario/Dr. Mario fireballs (may be textures/auras)
- Luigi misfire fire
- Zelda Din's Fire
- Full Ganondorf Warlock Punch
- Falco phantasm (not in EfFxData.dat)

---

## RGBY Color Reference

The 98 matrix format uses RGBY 16-bit colors. The ## value maps to specific colors.
See the thread for full color tables.
