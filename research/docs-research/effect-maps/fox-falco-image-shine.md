# Fox/Falco image shines — EfFxData.dat model 0 mapping spec

MAP 2026-09-09, verified IN-GAME. Target: the community "image shines" — the
Fox/Falco reflector mods with a picture inside the hexagon (NERV, Honeycomb,
Trollface, Pokéball, Poop Emoji, muOS, …). Companion to
[`fox.md`](fox.md) and [`fox-falco-shine-sparkles.md`](fox-falco-shine-sparkles.md),
which map the shine's *colour* operands; this is a MODEL finding.

Implemented by [`backend/blueprints/extras/effect_model.py`](../../../backend/blueprints/extras/effect_model.py).

## Verdict

The shine is `effFoxDataTable` **model 0** of `EfFxData.dat` (shared Fox/Falco
— there is no separate `EfFcData.dat`). The archive root holds
`{Particles*, TexGraphicBank*}` followed by an inline array of 0x14-byte
`SBM_EffectModel` entries `{f32 scale, JObj*, AnimJoint*, MatAnimJoint*,
ShapeAnimJoint*}`; entry 0 is the shine, at data offset 0x08 in vanilla.

Vanilla model 0:

```
JObj 0x1C368  flags 0x10000008 (ROOT_OPA | CLASSICAL_SCALE), scale 1
└─ JObj 0x1C3A8  flags 0x00040208 (OPA | BILLBOARD | CLASSICAL_SCALE), scale 0.422
   └─ DObj 0x1C358 → MObj 0x1C204 (rendermode 2 = VERTEX, no TObj)
                   → POBJ 0x1C340  flags 0x8000, 6×32B display list
                      GX_DRAW_TRIANGLE_FAN, 43 vertices
                      attrs: POS (INDEX8, XYZ, s16, frac 11) + CLR0 (DIRECT, RGBA6)
```

That display list at data 0x1C280 (**file 0x1C2A0**) IS the `shine_gradient`
extra's `hex` region: the alternating `621F…`/`AB9F…` RGBA6 vertex colours the
colour editor rewrites.

**An image shine replaces the child JObj's DObj with a two-triangle textured
quad.** Everything else in model 0 — the root JObj, the child JObj, the
AnimJoint, the MatAnimJoint and the ShapeAnimJoint — is byte-identical to
vanilla in every sampled mod. (The AnimJoint is one AObj, endframe 6, with
FObj tracks 8/9/10 = SCAX/SCAY/SCAZ: the shine's expanding pop. It overrides
the child JObj's static scale at runtime, which is why mods can and do set it
to 1.0.)

The replacement DObj, identical across every sampled mod:

| struct | values |
|---|---|
| MObj | rendermode **0x40000010** (TEX0), no PEDesc |
| Material | ambient **7F7F7FFF**, diffuse FFFFFFFF, specular FFFFFFFF, alpha 1.0, shininess 50 |
| TObj | texmap GX_TEXMAP0, texgensrc **4** (GX_TG_TEX0), rot 0 / scale 1 / trans 0, wrap REPEAT/REPEAT, repeat_s/t 1, flags **0x00340010**, blending 1.0, magFilt GX_LINEAR |
| ImageDesc | 256×256, RGB5A3 (GX fmt 5) or CI8 + TLUT (fmt 9); mipmap 0, maxLOD 0 |
| POBJ | flags 0x0000, ONE 32-byte display list |
| attrs | POS (INDEX8, XYZ, s16, frac 11, stride 6), NRM (INDEX8, XYZ, frac 7, stride 3), TEX0 (INDEX8, ST, u8, frac 7, stride 2), then the 0xFF terminator |
| display list | `90 0003` ×2 — two GX_DRAW_TRIANGLES, (0,1,2) and (0,2,3), 1-byte indices per attribute, NRM index always 0, NOP-padded to 32 bytes |
| geometry | quad corners (+8,−8), (−8,−8), (−8,+8), (+8,+8) at frac 11 (÷2048); UVs (1,1), (0,1), (0,0), (1,0) — i.e. **u = (x+8)/16, v = (8−y)/16** |

±8.0 matches the vanilla hexagon's ~8.27 radius, so the picture lands exactly
where the hexagon was.

## Two flag words are load-bearing (both cost an in-game bisect)

1. **The model ROOT JObj's pass gate.** `JOBJ_ROOT_OPA` (1<<28) → **`JOBJ_ROOT_TEXEDGE`
   (1<<30)**, i.e. vanilla `0x10000008` → mods' `0x40000008`
   (`sysdolphin/baselib/jobj.h`). The child moves `JOBJ_OPA` → `JOBJ_TEXEDGE`
   (`displayfunc.h`), and `HSD_JObjDisp` only descends passes the ROOT asks
   for. Setting the child's TEXEDGE without the root's drew **nothing at all**
   — the shine silently vanished, no error anywhere.
2. **The child JObj's static scale must be 1.0, not vanilla's 0.422.** Leaving
   0.422 made the game `assertion "0" failed in psdisp.c on line 2218`
   (`psDispParticles` ← `efLib_render_callback`: the default arm of its texture
   -format switch) and **freeze on the frame the shine drew**. Rebuilding with
   1.0 renders correctly. The size on screen is unchanged either way because
   the AnimJoint's scale tracks overwrite the value at runtime — but the file
   value still has to be 1.0. Mechanism not established; matching the shipped
   mods is what works.

Not load-bearing (tested both ways in-game, identical result): the NRM
attribute's comp_type — mods write 0 with the byte `0x80`; GX_S8 with `0x7F`
renders the same.

## Sampled mods (ssbmnucleus.net, 2026-09-09)

31 DATs from 17 posts. Three distinct shapes, only one of which is an image:

| shape | count | posts |
|---|---|---|
| **image** — one textured DObj (the format above) | **13** | Retrowave, NERV ×2 (EVA Regular + EVA Static), Jigglypuff stock icon, Jazz Cup, Trollface, Middle Finger, Shine Sprite, Pokéball, Poop Emoji, Strawhat, Grand Master, muOS |
| **model** — replacement geometry, 2–9 DObjs | 6 | Stop Sign (3 DObjs, 0 textures), Honeycomb (2 DObjs, 0 textures), Triforce (2 textured JObjs), Inferno ×3 (8 DObjs / 10 textures) |
| **gradient** — vanilla shape, colours only | 1 | Honeycomb "NoFill" variant |
| not an `effFoxDataTable` archive at all | 11 | NERV's optional `PlFx`/`PlFc` aura files; Inferno's HSDRawViewer `Models_N_(SBM_EffectModel…)` fragments |

Texture formats among the images: RGB5A3 (7) and CI8 + RGB5A3 TLUT (6).
Dimensions are mostly 256×256; two are not (Jigglypuff stock icon 300×200,
Shine Sprite 103×120), so the import path resamples to the configured size.

The "model" shape is **out of scope**: installing it needs whole-model
surgery, and `classify_model()` names it rather than guessing.

## Reproducing

Samples were downloaded with `backend/assistant/website.py` (`search_website_mods`
/ `_post`) into a scratch dir; the scan/dump scripts used are in
`.tmp/png-shine-20260909/` (`m0_dump.py` walks a model's JObj→DObj→MObj/TObj/POBJ
tree, `anim_dump.py` its AnimJoint/MatAnimJoint). Point
`NUCLEUS_IMAGE_SHINE_SAMPLES` at that samples directory to run
`backend/tests/test_image_shine.py`'s sample-driven tests.
