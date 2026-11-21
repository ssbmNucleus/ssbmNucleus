# Ef*Data.dat particle-bank format (decoded from the melee decomp)

Deterministic grammar for the `Ef*Data.dat` particle scripts, so effect-color
offsets are **derived structurally** instead of found by marker-scanning. This
replaces the "CF record / 07-block / 98-matrix" marker guesses with the real
sysdolphin particle opcodes.

Parser: `backend/skinlab/ptcl_parse.py` (run `--verify` for the ground-truth
self-test; all items PASS). Decomp: [doldecomp/melee](https://github.com/doldecomp/melee).

---

## 1. File / bank layout

An `Ef*Data.dat` is a standard HSD archive: `0x20` header
(`fileSize/dataSize/nbReloc/nbPublic`), a data section at `0x20`, a relocation
table, then public/extern symbol tables + a string bank. There is exactly one
public symbol, e.g. `effFoxDataTable` / `effCaptainDataTable` /
`effMewtwoDataTable` / `effSamusDataTable`, resolving to an **`SBM_EffectTable`**
at data-section offset 0 (HSDRaw `HSDLib/HSDRaw/Melee/Ef/SBM_EffectTable.cs`):

| off  | field            | meaning                                             |
|------|------------------|-----------------------------------------------------|
| 0x00 | `Particles`      | ptr → `HSD_ParticleGroup` (**the "cmdBank"**)       |
| 0x04 | `TextureGraphics`| ptr → `HSD_TEXGraphicBank` (**the "texBank"**)      |
| 0x08+| `Models[]`       | `SBM_EffectModel` array, 0x14 each (JOBJ/anim trees)|

`efasync.c:1246 psInitDataBankLoad(idx, ef_DAT_file, effDataTable_name, ...)`
is fed those two pointers as `cmdBank`/`texBank`.

### `HSD_ParticleGroup` (the ptcl bank)
`HSDLib/HSDRaw/Common/HSD_ParticleGroup.cs`:

| off    | type          | field                                                    |
|--------|---------------|----------------------------------------------------------|
| 0x00   | u16           | **version** (`0x00` or `0x40`-`0x43`; vanilla Ef* = `0x42`) |
| 0x02   | u16           | unk2 (= `EffectIDStart / 1000`)                          |
| 0x04   | s32           | **EffectIDStart** (bank's base gfx_id: Fox 3000, Falcon 4000, Mewtwo 13000, Samus 2000) |
| 0x08   | s32           | **GeneratorCount**                                       |
| 0x0C   | s32[Count]    | generator **offsets** relative to the `HSD_ParticleGroup` start (0 = "blank / same as previous") |

Each offset points to an **`HSD_ParticleGenerator`**: a `0x40`-byte header
(type/flags, texGroup, genLife, life, kind, grav, fric, vel xyz, radius, angle,
random, size, param1-3) followed by the **particle bytecode script** starting
at `+0x3C`. A generator's script runs until the next generator's offset (or the
tex bank).

Both `psInitDataBankLoad` versions are handled by the parser:
- **version 0** (particle.c:4516): count at `cmdBank[1]`, pointer table at
  `cmdBank+2` (byte 8).
- **version 0x40-0x43** (particle.c:4520): `count=cmdBank[1]`,
  `numCmdList=cmdBank[2]+count`, table base `= cmdBank + 3 - count`. This
  back-shift is what lets the runtime index the table by the **raw gfx_id**
  (which starts at `EffectIDStart`), so `psCmdListArray[bank][gfx_id]` lands on
  the right generator.

In practice every vanilla `Ef*Data.dat` is version `0x42`, and HSDRaw's
`HSD_ParticleGroup` (count at 0x08, offsets at 0x0C) is the authoritative
on-disk reader — that's what `ptcl_parse.py` uses.

---

## 2. Effect id → script index

Fighter code (`ftFox` etc.) calls `efSync_Spawn(gfx_id, ...)`. In `eflib.c`:

- `eflib.c:441` — the effect **descriptor** is
  `efAsync_DatEntries[gfx_id / 1000].data[gfx_id % 1000]`.
- `eflib.c:701-702` — `bank = gfx_id / 1000; generator = hsd_8039F05C(linkNo, bank, gfx_id)`.
- `hsd_8039F05C` (particle.c:8615) indexes `psCmdListArray[bank][idx]` with
  `idx == gfx_id` directly (bounds-checked against `psNumCmdList[bank]`).

Because of the version-0x40 back-shift, indexing by raw `gfx_id` is equivalent
to:

> **script index within the bank = `gfx_id − EffectIDStart` = `gfx_id % 1000`.**

So Fox `gfx_id 3000` → generator 0 in `EfFxData`, `3004` → generator 4, etc.
The audit doc's cites like "efSync_Spawn(1166) → efalt 0x48E → effect 0xBBD =
Models_5" concern the **Models[]** array (drawn geometry), which is a *separate*
index from the ptcl generators — see §4.

A future MAP mission can auto-name move→script by cross-referencing the fighter
`.c` `efSync_Spawn(<gfx_id>)` calls against `gfx_id − EffectIDStart`.

---

## 3. Particle bytecode grammar (color opcodes)

The generator/particle bytecode is walked by the interpreter in
`particle.c` (the big switch ~lines 5200-7185; runs at spawn and per-frame).
Opcodes:

- **`< 0x80`** low range: `operand = opcode & 0x1F` (u16-extended by 1 byte if
  `opcode & 0x20`); `opcode & 0xC0`: `0x00` = wait/nop, `0x40` = texture (reads
  1 poseNum byte). A nonzero operand yields (ends the frame). (`0x07` here is
  just a wait-7 — **not** a color marker; the reference "07 07 07 04" blocks are
  model data, §4.)
- **`>= 0x80`** high range, classified as `cls = opcode & 0xF8`, except
  `0xC0-0xCF`/`0xD0-0xDF` use `opcode & 0xF0` and a handful use the raw opcode.

### Color-carrying opcodes (the edit targets)

| opcode      | name    | decomp        | operand layout                                                   |
|-------------|---------|---------------|------------------------------------------------------------------|
| **0xC0-0xCF** | PrimCol | particle.c:6453 | `count`(u8, ext) then **1 byte per set channel**. Low nibble = channel mask: bit0=R bit1=G bit2=B bit3=A. |
| **0xD0-0xDF** | EnvCol  | particle.c:6511 | same as PrimCol.                                                  |
| **0xEA**      | MatCol  | particle.c:7030 | `count`(u8,ext) + `flags`(u8); `flags&1` → 1 RGB byte, `flags&8` → 1 A byte. |
| **0xEB**      | AmbCol  | particle.c:7072 | same as MatCol.                                                   |

`0xCF` = PrimCol with mask `0xF` = all four channels = **the "CF record"**.
Its literal RGBA bytes start at **opcode + 2** (after `CF` + the `count` byte).

The reference doc's **"secondary color at colorpos+7"** is now fully explained:
after a `0xCF 00 RR GG BB AA` PrimCol comes `0xAD` (PrimEnv flag, particle.c:5876)
then `0xDF 00 rr gg bb aa` (EnvCol all-channel). `CF(1) + count(1) + RGBA(4) +
AD(1) = 7`, so the EnvCol color operand sits exactly 7 bytes after the PrimCol
color operand. **Our "primary/secondary" = PrimCol/EnvCol.** (PrimCol tints the
particle's primary/texture color; EnvCol drives the environment/sustained tint,
matching the audit note that the secondary dominates the lingering puff.)

`count` is the interpolation frame count: `0` = set instantly, nonzero = fade
toward this value over `count` frames from the previous color. When `count`'s
high bit is set it is u16-extended (`(count&0x7F)<<8 | nextByte`). The parser
handles the extension.

### NOT literal colors (reported as delta ops, do not patch as color)

`0xBA` PrimColDelta (6191), `0xBB` EnvColDelta (6280), `0xE0` dual delta (6569),
`0xE9` dual selective delta (6718) carry **signed per-channel deltas** with
randomization — they perturb the target color, they don't set it. The parser
labels them `*_DELTA` and does not emit them as color operands.

### Every other opcode (for correct stream walking)

The parser decodes operand lengths for all opcodes so it can walk past
non-color commands: pos/vel set+add (`0x80`/`0x88`/`0x90`/`0x98`, 4 bytes per
set axis), `0xA0` size (count+float), `0xA2` grav / `0xA3` fric (float),
spawn-child variants (`0xA4`/`0xB9`/`0xF1`/`0xF2` 2B, `0xA5` 2B, `0xEF`/`0xF0`
3B, `0xAA` 4B), `0xA6` life (4B), `0xA7` cond-kill (1B), `0xA8` pos-rand (12B),
`0xA9` force-fn (4B), `0xAB` vel-scale (4B), `0xAC` size-rand (count+8),
`0xAD` PrimEnv, `0xAE`-`0xB1` mirror, `0xB2` appsrt, `0xB3` acmp (count+3),
`0xB6` rotate (count+4), `0xB7` aim-jobj (1B), `0xB8` force-jobj (9B),
`0xBC` posenum-rand (2B), `0xBD` vel-norm (8B), `0xBE` vel-mul (12B),
`0xBF` jobj-ofs (1B), `0xE1` callback (1B), `0xE3` palnum (1B),
`0xE4`/`0xE5` texflip (1B), `0xE8` trail (4B), `0xEC` userdata (5B),
`0xED` rotate-rand (9B), `0xFA` loop-mark (1B), `0xFB` loop-back,
`0xFC` mark, `0xFD` jump, `0xFE`/`0xFF` end. Full decomp cites in
`ptcl_parse.py:decode_one`. An unknown high opcode has an unknowable operand
length, so the parser stops that script (rare in vanilla; none hit in the four
test files).

---

## 4. Model-region color blocks (07 07 07 / 42 48 / 98 00 ##)

The reference doc's `07 07 07 04`, `42 48`, and `98 00 ##` color blocks
(falcon-kick tip `0x1DE00`, laser matrices, side-B material, Mewtwo upsmash
swirl `0xC754`, etc.) are **NOT particle bytecode**. They live in the
`SBM_EffectTable.Models[]` JOBJ trees — as HSD material colors, TEV/`HSD_TObjTev`
inputs, matanim `HSD_FOBJ` tracks, and display-list vertex colors — far past the
ptcl bank (which ends at the tex-bank pointer, typically < 0x1000). They are
real color data, just from a different HSD subsystem.

`ptcl_parse.py --models` does a secondary **signature scan** of the region past
the ptcl bank for these blocks (07-marker → two RGB at +4/+8; `98 00 NN` matrix
→ 2-byte colors at +4 step 4; `42 48` material → 0x10-byte block at −0x10). It's
a locator, not a full JOBJ decoder — the offsets it returns match the existing
`find_laser_offsets` / `find_*_offsets` finders in
`backend/blueprints/extras/helpers.py`. A full structural decode of these would
mean walking the JOBJ→DObj→MObj→material / TEV / display-list tree (HSDRaw
already models it) — out of scope for this ptcl decode mission but the obvious
next step for a "model color" parser.

---

## 5. Ground-truth verification

`python backend/skinlab/ptcl_parse.py --verify` — **all PASS** against the
in-game-verified offsets:

```
EfFxData.dat  (11 scripts, 36 color operands)
  PASS 0x127 prim FFFFFF   shine sparkles rec1 primary   (CF marker 0x125)
  PASS 0x12E env  2AA3EE   shine sparkles rec1 secondary (EnvCol 0xDF)
  PASS 0x143 prim FFFFFF   shine sparkles rec2 primary   (CF marker 0x141)
  PASS 0x2F0 prim FFFFFF   Firefox trailing fire large up-b (marker 0x2EE)
  PASS 0x384 prim FFF88F   Firefox trailing fire small   (marker 0x382)
  PASS 0x394 prim FF7111   Firefox trailing fire small   (marker 0x392)
EfCaData.dat  (17 scripts, 80 color operands)
  PASS 0x12F prim FFFFFF   falcon kick trail primary  (config trail_c1)
  PASS 0x136 env  D2CE9E   falcon kick trail secondary(config trail_c2 = EnvCol)
  PASS 0x474 prim FF290C   falcon kick square dots    (config dots_c1)
  PASS 0x6AF prim FFFFFF   falcon kick front chevron  (config front_c1)
  PASS 0x1DE00 model 07-block  color1=FFFFE5 color2=FFB200  falcon kick tip
EfMtData.dat  (9 scripts, 20 color operands)
  PASS 0xC754 model 07-block  color1=6600CC color2=000000  Mewtwo upsmash swirl
OVERALL: PASS
```

### Which empirical labels were right / wrong

- **RIGHT:** every CF/secondary offset. The color positions the config and the
  reference doc store (CF marker + 2 for primary, + 9 for the EnvCol secondary)
  are exactly the parser's `prim`/`env` operand offsets.
- **CLARIFIED:** "CF record" = PrimCol opcode `0xCF` (all-channel). The trailing
  `AD DF` is not a "separator marker" — it's `0xAD` (PrimEnv flag) + `0xDF`
  (EnvCol all-channel). "Secondary at +7" = the EnvCol color, and it wins the
  sustained tint because EnvCol is the environment color.
- **CLARIFIED:** the `CF <flag>` byte the reference calls a "flag" (00/07/08/18)
  is the PrimCol **interpolation count** (frames to fade in). It is safe to
  leave as-is when only recoloring.
- **RIGHT but relocated:** the `07 07 07`, `42 48`, `98 00` blocks are genuine
  colors but are **model** data, not ptcl scripts — a different parser domain.

---

## 6. How a MAP mission uses the parser

1. `python backend/skinlab/ptcl_parse.py <char>/EfXxData.dat --models` — get
   the full color inventory: every ptcl color operand (exact file offset,
   PrimCol/EnvCol/Mat/Amb, channels, vanilla bytes) grouped by script index,
   plus the model-region 07/42/98 blocks.
2. Map script index → move via `gfx_id − EffectIDStart` cross-referenced with
   the fighter `.c` `efSync_Spawn(<gfx_id>)` calls (§2).
3. Group operands into editor layers: a PrimCol/EnvCol pair in one script is a
   `_c1`/`_c2` couple; scripts sharing a move are one layer.
4. Live-poke / build-verify as usual (the parser tells you *where*, not *what
   it looks like*).

### Implication for task #8 (signature relocation)

The parser makes hardcoded ptcl offsets obsolete: **parse the actual file being
patched** and locate each color operand by `(script index, opcode kind, ordinal
within script)` instead of a raw byte offset. When a model import shifts the
bank, the ParticleGroup header + generator-offset table still resolve every
script deterministically, so the color operands move *with* the data — no
marker heuristics, no `find_*_offsets` scans, no off-by-N drift. The
model-region 07/42/98 blocks still need the signature scan (or a full JOBJ
walk) until a model-color parser lands, but the entire ptcl-bank half of every
character's offsets can be regenerated from the file on demand.
