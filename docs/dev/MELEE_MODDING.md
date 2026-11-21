# Melee Modding Domain Knowledge

Technical reference for understanding Super Smash Bros. Melee costume and stage modding.

## DAT File Structure

Melee game assets are stored in `.dat` files using a hierarchical format:

### Header (0x20 bytes)
```
Offset  Size  Description
0x00    4     File size
0x04    4     Data block size
0x08    4     Relocation table count
0x0C    4     Root node count
0x10    4     Root node count (duplicate)
0x14-1F 12    Reserved/unknown
0x20    ...   Data block starts
```

### Structure
```
[Header 0x20 bytes]
[Data Block]
[Relocation Table - 4 bytes per entry]
[Root Node Table - 8 bytes per entry (offset + string offset)]
[String Table - null-terminated symbol names]
```

### Root Node Symbols

DAT files are identified by their **root node symbols**:

**Costume files** have `Ply` symbols:
- `PlyCaptain5KWh_Share_joint` - Captain Falcon White costume
- `PlyMars5KNr_Share_joint` - Marth Default costume
- `PlyFox5KGr_Share_joint` - Fox Green costume

**Data/effect mods** have only `ftData` symbols:
- `ftDataMars` - Marth character data (not a costume)
- `ftDataFox` - Fox character data

**Detection rule**: If file has `Ply*` symbols = costume file. If only `ftData*` symbols = data mod.

---

## Character Codes

Each character has a 2-letter code used in file naming:

| Character | Code | File Prefix | Notes |
|-----------|------|-------------|-------|
| Mario | Mr | PlMr | |
| Fox | Fx | PlFx | |
| Captain Falcon | Ca | PlCa | Display: "C. Falcon" |
| DK | Dk | PlDk | Donkey Kong |
| Kirby | Kb | PlKb | |
| Bowser | Kp | PlKp | Internal: "Koopa" |
| Link | Lk | PlLk | |
| Sheik | Sk | PlSk | |
| Ness | Ns | PlNs | |
| Peach | Pe | PlPe | |
| Ice Climbers | Pp | PlPp | Popo (lead climber) |
| Ice Climbers (Nana) | Nn | PlNn | Partner climber |
| Pikachu | Pk | PlPk | |
| Samus | Ss | PlSs | |
| Yoshi | Ys | PlYs | |
| Jigglypuff | Pr | PlPr | Internal: "Purin" |
| Mewtwo | Mt | PlMt | |
| Luigi | Lg | PlLg | |
| Marth | Ms | PlMs | Internal: "Mars" |
| Zelda | Zd | PlZd | |
| Young Link | Cl | PlCl | Internal: "Clink" |
| Dr. Mario | Dr | PlDr | |
| Falco | Fc | PlFc | |
| Pichu | Pc | PlPc | |
| Mr. Game & Watch | Gw | PlGw | Display: "G&W" |
| Ganondorf | Gn | PlGn | |
| Roy | Fe | PlFe | Internal: "Emblem" |

---

## Color/Costume Codes

Each vanilla costume has a 2-letter color code:

| Code | Color | Description |
|------|-------|-------------|
| Nr | Default | Neutral/primary costume |
| Bu | Blue | |
| Re | Red | |
| Gr | Green | |
| Ye | Yellow | |
| Bk | Black | |
| Wh | White | |
| Pi | Pink | |
| Or | Orange | |
| La | Lavender | Purple tint |
| Aq | Aqua | Light blue |
| Gy | Grey | |

### File Naming Convention

Costume files follow the pattern: `Pl[CharCode][ColorCode].dat`

Examples:
- `PlFxNr.dat` - Fox neutral (default orange)
- `PlFxGr.dat` - Fox green
- `PlCaRe.dat` - Captain Falcon red
- `PlMsWh.dat` - Marth white

### Vanilla Costume Counts

Melee has **128 total costumes** across 26 playable characters (plus Nana and Master Hand).

Characters have 4-6 costumes each. Example costume slots for Fox:
1. Nr (Neutral) - Orange
2. Or (Orange variant)
3. La (Lavender)
4. Gr (Green)

---

## Ice Climbers Special Handling

Ice Climbers are **two characters** that must stay paired:

| Role | Code | File | Description |
|------|------|------|-------------|
| Popo | Pp | PlPp*.dat | Lead climber (player controls) |
| Nana | Nn | PlNn*.dat | Partner climber (AI follows) |

### Color Pairing

Popo and Nana use **different color codes** for the same costume:

| Costume | Popo Code | Nana Code |
|---------|-----------|-----------|
| Default | Nr | Nr |
| Green | Gr | Ye |
| Orange | Or | Aq |
| Red | Re | Re |

### Import Behavior

When importing Ice Climbers costumes:
1. System looks for both Popo (PlPp) and Nana (PlNn) files
2. Matches them by color pairing rules
3. Nana files don't get separate CSPs or stock icons
4. Only Popo appears on character select screen

---

## CSP (Character Select Portrait)

CSPs are the character images shown on the character select screen.

### Dimensions
- **Standard**: 136x188 pixels
- **HD**: Multiples of 136x188 (e.g., 272x376, 544x752)

### Generation Process
1. Load character DAT file into 3D renderer (HSDRawViewer)
2. Position character at specific pose/angle
3. Render to transparent PNG
4. Crop and scale to CSP dimensions

### File Naming
- `PlFxNr_csp.png` - Standard naming
- `csp_PlFxGr sm4sh fox.png` - With custom costume name

---

## Stock Icons

Small square icons shown during gameplay to indicate remaining lives.

### Dimensions
- **Standard**: 24x24 pixels
- **HD**: Multiples of 24 (e.g., 48x48, 96x96)

### Generation
Generated from CSP by cropping character's head region and scaling down.

---

## Slippi Compatibility

[Slippi](https://slippi.gg) is the online netplay system for Melee. Costume mods must be "Slippi safe" to avoid desyncs.

### What Makes a Costume Unsafe

The `SlippiCostumeValidator.exe` tool checks for issues that cause desyncs:
- Modified collision/hurtbox data
- Changed animation timing
- Altered physics values
- Non-standard bone structures

### Validation Process

1. Copy costume to temp file with proper Melee filename (e.g., `PlFxGr.dat`)
2. Run `SlippiCostumeValidator.exe` on the temp file
3. Compare MD5 hash before/after - if changed, file needed fixes
4. If `auto_fix=True`, apply the fixed version back to original

### Safe vs Unsafe

- **Safe costumes**: Only texture/model visual changes
- **Unsafe costumes**: Any gameplay-affecting data modified

Users can:
- Auto-fix during import (applies Slippi patches)
- Import as-is (for offline use only)
- Manually retest and override status

---

## Stage Files

### File Format
Stage files use `Gr*.dat` naming:
- `GrBb.dat` - Big Blue
- `GrFd.dat` - Final Destination
- `GrIz.dat` - Icicle Mountain

### Dynamic Alternate Stages (DAS)

MEX supports multiple stage variants per slot. Users can swap between variants on the stage select screen.

---

## MEX Project Structure

MEX (Melee Ex) is the modding framework this app uses.

### Project Files
```
build/
├── project.mexproj     # XML project configuration
├── data/
│   └── fighters/       # Per-character mod data
├── files/              # Game files (extracted from ISO)
│   ├── Pl*.dat         # Character costumes
│   ├── Ef*.dat         # Effect data
│   ├── Gr*.dat         # Stage files
│   └── audio/          # Sound files
├── assets/             # CSP images, icons
└── sys/                # System files
```

### MexCLI Commands

The `mexcli.exe` tool provides command-line access:
- `open` - Open/create project
- `import-costume` - Add costume to project
- `remove-costume` - Remove costume
- `reorder-costumes` - Change costume slot order
- `build` - Export modified ISO

---

## Storage Vault Structure

User's imported costumes are stored locally before adding to MEX project:

```
storage/
├── [character name]/           # e.g., "Fox", "Marth"
│   ├── [costume_id]/          # UUID folder
│   │   ├── metadata.json      # Name, slippi status, etc.
│   │   ├── PlFxGr.dat         # Costume file
│   │   ├── PlFxGr_csp.png     # CSP image
│   │   └── PlFxGr_stock.png   # Stock icon
│   └── ...
└── stages/
    └── [stage folders]/
```

### Metadata Schema
```json
{
  "name": "SM4SH Fox Green",
  "slippi_safe": true,
  "costume_code": "PlFxGr",
  "original_filename": "sm4sh_fox_green.dat",
  "imported_at": "2024-01-15T12:00:00Z"
}
```

---

## Effect Data Files

Character effects (lasers, projectiles, etc.) are stored in `Ef*.dat` files:

| File | Character | Contents |
|------|-----------|----------|
| EfFxData.dat | Fox | Laser, shine, illusion effects |
| EfFcData.dat | Falco | Laser, shine, phantasm effects |
| EfCaData.dat | C. Falcon | Falcon Punch flame, Raptor Boost |
| EfMsData.dat | Marth | Sword trails |

### Modding Effects

Effect colors (laser color, shine color, etc.) can be modified by:
1. Extracting effect data from EfXxData.dat
2. Modifying color values in the binary
3. Recompiling back to the file

The app provides visual editors for common effects (Fox/Falco lasers, shine colors, sword trails).

---

## Texture Packs

For Slippi/Dolphin users, costumes can be exported as **texture packs** that don't modify the ISO:

### How It Works
1. Export build with texture mapping enabled
2. Play game with "Dump Textures" enabled in Dolphin
3. App watches for dumped textures and matches to costumes
4. Generates `Load/Textures/GALE01/` folder for Dolphin

### Dolphin Paths
```
Slippi/
├── User/
│   ├── Config/
│   │   └── GFX.ini          # DumpTextures, HiresTextures settings
│   ├── Dump/Textures/GALE01/ # Dumped game textures
│   └── Load/Textures/GALE01/ # Custom texture pack
```

---

## Common Issues

### "File needs proper character filename"
The validator requires files named `Pl[Char][Color].dat`. Custom names like `cool_fox.dat` must be renamed during validation.

### "Unknown Color detected"
Custom color codes (not in vanilla Melee) are treated as data mods, not costumes. These files may have character info but lack standard color identification.

### Ice Climbers Missing Nana
When importing Ice Climbers, both Popo and Nana files must be present. Popo-only imports will have a mismatched partner.

### CSP Generation Fails
Usually means HSDRawViewer couldn't load the model. Check that:
- File is a valid costume (has Ply symbols)
- File isn't corrupted
- 3D viewer process is running
