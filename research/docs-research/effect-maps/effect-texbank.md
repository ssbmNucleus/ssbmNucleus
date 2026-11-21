# Ef*Data.dat TEXGraphicBank — texture-recolor map (STATIC, validated)

Decodes the **texture bank** half of an `Ef*Data.dat` (the ptcl-bytecode half is
`PTCL_FORMAT.md` / `ptcl_parse.py`). The marquee "texture-only" specials that
`efcodata.md` §3b flagged (Din's Fire, Vanish, Transform, Quick Attack, Link
arrow, Bowser Bomb, Pika thunder) plus Roy's fire (Marth has no fire) all resolve to texture
groups here; this doc produces the per-texture `{offset, w, h, gx_format}` a
`texture_recolor` extra needs, and reports the **validation** and a large
premise correction.

Tool: `backend/skinlab/ptcl_texbank.py` (`--json`, `--export DIR`, `--groups`,
`--hue`, `--verify`). Decoders reused from `skinlab/datprobe.py` +
`plss_ball_probe.py`. Decomp: `src/sysdolphin/baselib/particle.c`
(`psInitDataBankLocate` Phase-3, `psstructs.h _HSD_PSTexGroup`), HSDRaw
`HSD_TEXGraphic.cs`.

---

## 0. Headline (read first) — the marquee premise was half-right

**`efcodata.md` was right that these effects have no ptcl color operands, but
wrong about what to recolor.** The tex bank holds only **grayscale intensity/
alpha masks** for almost every group — I4 / I8 / IA4 / IA8, which carry NO hue.
Din's Fire, Vanish, Quick Attack, arrow, Bowser Bomb all reference those
**grayscale** groups (and their spawned children do too — traced below). You
cannot hue-rotate a grayscale mask; there is nothing to rotate.

**Of EfCoData's 36 texture groups, exactly TWO carry color:**

| group | fmt | dims | #img | dominant hue | what it is |
|---|---|---|---|---|---|
| **grp9** | CI8 | 64×64 | 10 | **41° (orange)** | the shared **fire cloud** — Din/Bowser/Charizard/Roy fire |
| **grp3** | CI8 | 128×128 | 2 | **279° (purple/magenta)** | the shared **electric/vanish star-burst** |

Everything else (grp0-2, 4-8, 10-35) is grayscale and tinted at runtime by the
particle's `primCol`/`envCol` — which for these scripts defaults to white (no
operands). **The color you see on a fire/electric effect comes from the shared
colored group (grp9 / grp3) it composites, not from the effect's own grayscale
mask.**

**This is exactly what mod 17088 proves:** its "rainbow fire whole cast" diff is
`0x8CD77–0x97F3F`, a pure texture edit, and it lands **entirely inside grp9's
extent `0x8CB40–0x97F40`** (image + palette region). Recoloring that one CI8
group shifted every fire effect in the game — Din's, Bowser Bomb fire, Charizard
breath, and Roy's Blazer/Flare-Blade — simultaneously. That is only possible if
grp9 is the single shared fire-color source. (Self-test: `--verify`, PASS.)

**Consequence for the marquee extras:** they are best shipped as **two shared
`texture_recolor` extras on EfCoData** — `common_fire` (grp9) and
`common_flash` (grp3, electric/vanish/transform) — each with a huge honest
also-affects list, NOT as per-effect recolors of grayscale masks. See §4.

**Marth / Roy fire:** EfMsData / EfFeData tex banks are **3 grayscale groups each,
zero color** (§5). Their only color records are the **blue** sword-glow ptcl
operands (already in `marth-effects.md` / `roy-effects.md`). **Marth has no fire
move at all** (Shield Breaker / Dancing Blade / Dolphin Slash / Counter); the
orange fire belongs to **Roy** (Flare Blade + Blazer) and draws from the shared
EfCoData grp9. The two char docs' "specials are EfCoData common bank"
quarantine claims were wrong and are corrected (gfx 1265/1266→`0x3E80`=16000=
EfMsData, 1296/1297→`0xBF68`=49000=EfFeData; §5).

---

## 1. TEXGraphicBank format (decoded, both sources agree)

`SBM_EffectTable` @ data-section 0 (file offset `0x20`):

| off | field |
|---|---|
| +0x00 | `Particles` → `HSD_ParticleGroup` (ptcl bank, `ptcl_parse.py`) |
| +0x04 | `TextureGraphics` → `HSD_TEXGraphicBank` (this bank) |

**`HSD_TEXGraphicBank`** (offsets relative to bank start = `0x20 + tex_ptr`):

```
[0]            s32  num_groups
[1..num]       s32  group_offset[num_groups]   (relative to bank start;
                                                0 = null slot)
```

(HSDRaw `HSD_TEXGraphicBank.cs`: Length @0x00, per-group offset @`0x04*i`.
decomp `psInitDataBankLocate` Phase-3: `groups = texBank+1`, each nonzero entry
`+= texBank` at load.)

**`HSD_PSTexGroup`** (0x18 header, `psstructs.h`):

| off | type | field |
|---|---|---|
| +0x00 | u32 | `num` — image (pose) count |
| +0x04 | u32 | `fmt` — GXTexFmt |
| +0x08 | u32 | `tlutfmt` — GXTlutFmt (CI only) |
| +0x0C | u32 | `width` |
| +0x10 | u32 | `height` |
| +0x14 | u16 | `palnum` — #palettes (0 → one-per-image) |
| +0x16 | u16 | `palflag` — bit0 = single shared palette |
| +0x18 | s32[num] | `texTable` — image-data offsets (rel to bank) |
| +0x18+num*4 | s32[…] | `palTable` — palette offsets (CI; count per palflag/palnum) |

A running particle's `poseNum` selects `texTable[poseNum]`; a script's
`texGroup` (from `ptcl_parse` `Script.header['texGroup']`) selects the group.
Palette count rule (decomp Phase-3): `palflag&1` → 1 shared; else `palnum>0` →
`palnum`; else (`palnum==0`) → `num` (one per image). HSDRaw stores each palette
as a fixed 0x200-byte (256-entry) block.

**Offsets are RAW FILE offsets** (`0x20` header already added), directly usable
by `extras/texture_recolor.py` `_region()` and a hex editor.

---

## 2. EfCoData full group inventory

`python skinlab/ptcl_texbank.py ../storage/test-base/files/EfCoData.dat --hue`
(tex_bank @ `0x11C20`, 36 groups). Only color-bearing groups shown with hue;
grayscale groups carry alpha/intensity only.

| grp | off | fmt | dims | #img | hue | extent | role (from §3 script refs) |
|---|---|---|---|---|---|---|---|
| **3** | 0x48DA0 | CI8 | 128×128 | 2 | **279° purple** | 0x48DA0–0x511A0 | electric / vanish / transform star-burst |
| **9** | 0x8CB40 | CI8 | 64×64 | 10 | **41° orange** | 0x8CB40–0x97F40 | **shared fire cloud** (17088 target) |
| 2 | 0x18D20 | IA8 | 128×128 | 6 | — gray | 0x18D60–0x48D60 | Din explosion / charge mask |
| 4 | 0x511E0 | IA4 | 64×64 | 3 | — gray | 0x511E0–0x541E0 | transform / quick-attack streak mask |
| 5 | 0x54220 | IA8 | 128×128 | 4 | — gray | 0x54220–0x74220 | fire/smoke shape mask (Din children) |
| 7 | 0x78AA0 | IA8 | 64×64 | 6 | — gray | 0x78AA0–0x84AA0 | float dust / soft puff mask |
| 11 | 0x9FFA0 | I4 | 32×32 | 6 | — gray | 0x9FFA0–0xA0BA0 | vanish/thunder/bomb spark mask |
| 13 | 0xA2000 | I4 | 64×64 | 2 | — gray | 0xA2000–0xA3000 | Din 2nd / ember mask |
| 16 | 0xA53A0 | IA4 | 64×64 | 4 | — gray | 0xA53A0–0xA93A0 | Din ember trail mask |
| 23 | 0xB5100 | I8 | 32×32 | 3 | — gray | 0xB5100–0xB5D00 | Bowser Bomb shockwave mask |
| 26 | 0xBCDA0 | IA8 | 64×64 | 6 | — gray | 0xBCDA0–0xC8DA0 | Link arrow trail mask |

(Full 36-group dump: `ptcl_texbank.py … --json`. All remaining groups are
grayscale.)

### CI8 palette layout (the recolor targets)

Both colored groups are **CI8, tlutfmt=2 (RGB5A3), one palette per image**
(`palnum=0`), so a hue-rotate recolors the **palettes**, not the pixel indices:

- **grp9 (fire):** images `0x8CB40`+`k*0x1000` (k=0..9); palettes
  `0x96B40`+`k*0x200` (k=0..9), each 256×RGB5A3.
- **grp3 (flash):** images `0x48DA0`, `0x4CDA0`; palettes `0x50DA0`, `0x50FA0`.

---

## 3. Marquee script → texGroup → child-generator trace

From `ptcl_parse` (`Script.header['texGroup']`) + a spawn-child trace
(`SPAWN_GEN` operand = child generator index). Every marquee script has **0
color operands** (confirmed) and references **grayscale** groups; their spawned
children also stay grayscale. **None reach grp9/grp3 directly** — the colored
fire/flash is composited by a separate common-bank GFX / additive layer, which
is why the *shared* colored group is the correct recolor target.

| script | move / consumers (efcodata.md §3b) | texGroup | spawn children → their texGroups |
|---|---|---|---|
| 110 | Din's Fire ember `itzeldadinfire` | 16 (gray) | 111→16, 112→13, 122→5, 123→7 |
| 456 | Din's Fire 2nd | 13 (gray) | 457→13, 458→25, 459→23, 460→24 |
| 358 | Din's Fire explosion | 2 (gray) | 359→5, 360→11, 363→11, 361→13, 362→26 |
| 113 | Din's charge glow `ftZd_SpecialS` | 2 (gray) | 114→5, 115→11, 116→13 |
| 106 | Zelda↔Sheik Transform | 4 (gray) | — |
| 109/121 | Sheik/Zelda Vanish up-B | 11 (gray) | — |
| 72 | Pikachu Quick Attack | 4 (gray) | 2 children |
| 588 | Pika down-B thunder | 11 (gray) | 3 children |
| 97/323 | Bowser Bomb landing | 11 / 23 (gray) | 97→2 children, 323→1 child |
| 146 | Link arrow `itlinkarrow` | 26 (gray) | 2 children |
| 286 | Peach Float dust | 7 (gray) | — |

**grp9 (fire) real consumers** (scripts whose `texGroup==9`): 25, 26, 58, 67,
76, 117, 232, 302, 394, 439, 445, 554, 555, 561 — the generic flame/fire-cloud
generators shared by fire moves (Charizard breath, Din/Bowser/Roy fire draw the
colored cloud from here). **grp3 (flash) consumers**: the electric/vanish
star-burst generators. (Full lists: `--json` + a `texGroup==N` filter.)

---

## 4. texture_recolor-ready entries (the deliverable)

Because color lives in the two shared CI8 groups, ship **two EfCoData shared
extras**, each recoloring one group's whole image+palette extent. Vanilla
dominant hue is the saturation-weighted `plss_ball_probe` value
(`ptcl_texbank … --hue`).

### 4a. `common_fire` — EfCoData grp9 (orange fire, hue 41°)

```jsonc
{
  "id": "common_fire",
  "format": "texture_recolor",
  "target_file": "EfCoData.dat",
  "texture": {                       // CI8: recolor is a PALETTE hue-rotate;
    "gx_format": 9,                  // needs CI-palette support in
    "width": 64, "height": 64,       // texture_recolor.py (see §6 — NOT yet
    "images": [                      // supported; RGB5A3/565 only today).
      {"offset": "0x8CB40", "palette": "0x96B40"},
      {"offset": "0x8DB40", "palette": "0x96D40"},
      {"offset": "0x8EB40", "palette": "0x96F40"},
      {"offset": "0x8FB40", "palette": "0x97140"},
      {"offset": "0x90B40", "palette": "0x97340"},
      {"offset": "0x91B40", "palette": "0x97540"},
      {"offset": "0x92B40", "palette": "0x97740"},
      {"offset": "0x93B40", "palette": "0x97940"},
      {"offset": "0x94B40", "palette": "0x97B40"},
      {"offset": "0x95B40", "palette": "0x97D40"}
    ],
    "palette_format": 2              // RGB5A3
  },
  "vanilla_dominant_hue": 41,
  "also_affects": [
    "Zelda Din's Fire (all phases)", "Bowser Bomb fire", "Charizard flame-breath",
    "Roy Flare Blade / Blazer fire (Marth has no fire move)",
    "generic cast-wide flames"
  ]
}
```

Recolor mechanics: for each of the 10 images, decode its 256-entry RGB5A3
palette, hue-rotate by `(target − 41)°` (preserving S/V/alpha, `recolor_texels`),
re-encode in place. Pixel indices are untouched. Extent `0x8CB40–0x97F40` — the
diff-validation range.

### 4b. `common_flash` — EfCoData grp3 (purple star-burst, hue 279°)

```jsonc
{
  "id": "common_flash",
  "format": "texture_recolor",
  "target_file": "EfCoData.dat",
  "texture": {
    "gx_format": 9, "width": 128, "height": 128,
    "images": [
      {"offset": "0x48DA0", "palette": "0x50DA0"},
      {"offset": "0x4CDA0", "palette": "0x50FA0"}
    ],
    "palette_format": 2
  },
  "vanilla_dominant_hue": 279,
  "also_affects": [
    "Sheik/Zelda Vanish flash", "Zelda↔Sheik Transform flash",
    "Pikachu thunder / Quick Attack burst", "generic electric star-bursts"
  ]
}
```

### 4c. Grayscale marquee masks — NOT recolorable

Din/Vanish/Quick-Attack/arrow/Bomb `texGroup`s (2,4,5,7,11,13,16,23,26) are
grayscale alpha masks; a `texture_recolor` on them is a no-op (no hue). Their
apparent color is the shared grp9/grp3 above (recolor those instead) plus, where
present, ptcl color operands in OTHER files (e.g. Bowser's own EfKpData). Do NOT
wire per-effect recolors of these masks.

### Shared-texture collisions

grp9 and grp3 are each **one image group shared by many effects** → one extra
each with the full also-affects list (already reflected above). There is no
per-character split possible at the texture layer; a fire recolor is inherently
cast-wide, matching 17088's behavior.

---

## 5. Marth (EfMsData) / Roy (EfFeData) fire — findings + doc corrections

**Tex banks:** both files have `tex_bank @ 0x200`, **3 groups, all grayscale:**

| grp | fmt | dims | #img | content (exported PNG) |
|---|---|---|---|---|
| 0 | I8 | 64×64 | 1 | swing arc mask |
| 1 | I4 | 64×64 | 2 | **Dolphin-Slash dolphin** silhouette mask |
| 2 | I8 | 64×64 | 1 | swing arc mask |

Zero color in either tex bank. Their only color records are the **blue** ptcl
sword-glow operands (`0x11A/0x121/0x192/0x199/0x1E0/0x1E7`,
`4AA7F8`/`00A6FF`/`0000C2`/`A300E8`), already documented. The files are
byte-identical in ptcl content (EffectIDStart 16000 vs 49000).

**Where the orange fire is:** the shared **EfCoData grp9** (§4a). **Roy's** Flare
Blade and Blazer draw the shared fire cloud; 17088 shifting grp9 shifts Roy's fire
too. **Marth has no fire move** (his EfMsData grayscale-only bank reflects that).
There is **no orange fire texture and no orange color operand in EfMsData/EfFeData**.

**Routing correction (was wrong in both char docs):**

| gfx id | efsync.c | resolves to | bank |
|---|---|---|---|
| 1265 (0x4F1) Marth Counter | `case 0x4F1 → efLib_Create*(0x3E80)` | 16000 | **EfMsData** (not EfCoData) |
| 1266 (0x4F2) Marth Shield-Breaker | `case 0x4F2 → efLib_Create*(0x3E80)` | 16000 | **EfMsData** |
| 1296 (0x510) Roy Counter | `case 0x510 → efLib_Create*(0xBF68)` | 49000 | **EfFeData** (not EfCoData) |
| 1297 (0x511) Roy Shield-Breaker | `case 0x511 → efLib_Create*(0xBF68)` | 49000 | **EfFeData** |

So those gfx ids ARE the blue sword-glow scripts in the character's own file —
editable there — NOT EfCoData records. `marth-effects.md` / `roy-effects.md`
"quarantine" sections corrected accordingly (2026-07-02). The only thing that
truly belongs to a shared EfCoData extra is the **fire texture (grp9)**.

---

## 6. Validation + tool

- **`python skinlab/ptcl_texbank.py --verify`** → **PASS**: the 17088 rainbow-
  fire diff (`0x8CD77–0x97F3F`) is *fully contained* in grp9's decoded extent
  (`0x8CB40–0x97F40`). This is the ground-truth that the bank offset/size decode
  is correct — the diff can only be contained if every group offset, image size
  (`gx_image_size(CI8,64,64)=0x1000`), and per-image palette offset is right.
- Structural check: all 36 EfCoData groups + 3 each in EfMs/EfFeData parse with
  plausible dims/formats, monotonic extents, 0 warnings.
- PNGs exported to `tests/artifacts/efco-texbank/` (grp2,3,4,7,9,11,13,16,23,26),
  `tests/artifacts/efms-texbank/`, `tests/artifacts/effe-texbank/`. grp9 poses =
  orange fire clouds; grp3 = purple star-burst; EfMs grp1 = dolphin.

### Open / not-yet-shippable

- **WIRE DONE 2026-07-02**: CI-palette recolor is now in `texture_recolor.py`
  — promoted `_decode_palette`/`encode_palette` from `plss_ball_probe.py` as
  `decode_palette`/`encode_palette`, added the multi-image `{"images":
  [{"offset", "palette"}, ...]}` config shape (`_is_palette_cfg`/`_images`/
  `_palette_region` helpers), and branched `apply_texture_recolor`/
  `restore_texture_recolor`/`read_current_dominant_color` on it. Recolors the
  TLUT, never the pixel indices. `common_fire` (grp9, owner Zelda, sharedWith
  Bowser/Roy — Marth has no fire move) and `common_flash` (grp3, owner Zelda, sharedWith
  Sheik/Pikachu/Pichu) are wired in both `extra_types.py` and
  `extraTypes.js`, plus editor/preview mirrors, `extras_audit.py`
  `AUDIT_HINTS`, and `docs/EXTRAS_AUDIT.md`/`Effect-Offsets-Reference.md`.
  Self-test + a real MexCLI-exported build both confirm: image index bytes
  unchanged, palette bytes changed, restore byte-identical to vanilla, and
  the sibling shared group untouched. See `docs/EXTRAS_AUDIT.md` "Zelda
  `common_fire`"/"`common_flash`" rows for the full writeup.
- LIVE: ✅ EYEBALL-VERIFIED 2026-07-02 — the composite color follows the shared
  group recolor, exactly as 17088 predicted.
  - **grp9 (fire):** Zelda side-B Din's Fire **charge fireball** (the fire cloud
    in her hand, `sideb:40`) recolors green vs vanilla orange. NOT the whiffed
    mid-air ember/explosion — that is a §4c grayscale mask (grp2/grp5) and stays
    orange. Captures: `tests/artifacts/extras-audit/Zelda-common_fire/`.
  - **grp3 (flash):** demonstrated on **Pikachu down-B thunder** (`downb:45-55`)
    — the purple radial star-burst behind Pikachu's head recolors (orange with a
    FF7F00 anti-color). NOT Zelda down-B (that is Transform = grp4 grayscale, does
    not composite grp3). Captures: `.../Zelda-common_flash/`.
  - Two demonstration gotchas worth banking: (1) EfCoData ships in EVERY build,
    so a common_fire/flash ISO can be captured with ANY consumer character — pick
    the char whose move most visibly composites the group, regardless of the
    config owner (Pikachu for flash). (2) grp3 is 279° purple; 00FF00 half-
    collides with thunder's natural green sparks — use an orange/cyan anti-color.
  Verify commands (from `backend/`): `python devtools/extras_audit.py --char Zelda
  --extra common_fire` / `--extra common_flash` (AUDIT_HINTS now boots Pikachu
  for flash at `downb:40,45,50,55` with a FF7F00 anti-color).
