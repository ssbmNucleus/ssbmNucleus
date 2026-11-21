/**
 * Extra types configuration for character-specific mods
 * Each extra type defines editable properties that modify specific dat file offsets
 */

// NOTE: Offsets are character-specific - do not copy between characters
export const EXTRA_TYPES = {
  'C. Falcon': [
    {
      // Rebuilt 2026-07; offsets marker-verified against vanilla EfCaData.dat.
      // Mirrors backend/core/extra_types.py.
      id: 'falcon_punch',
      name: 'Falcon Punch',
      description: 'Falcon Punch fire tip, lens flares, and smoke colors',
      targetFile: 'EfCaData.dat',
      icon: 'punch',
      offsets: {
        color1: { start: 0x202F0, size: 3, format: 'RGB' },
        color2: { start: 0x202F4, size: 3, format: 'RGB' },
        // _c1/_c2 suffixes: EffectEditorPage fans the two pickers out here
        flare_lines_c2: {
          format: '070707',
          offsets: [0x22D64, 0x22E30, 0x22EFC, 0x22FC8, 0x23094,
                    0x23160, 0x2322C, 0x232F8, 0x233C4, 0x23490]
        },
        flare_small_c1: { start: 0x22D0C, size: 3, format: 'RGB' },
        flare_big_c1: { start: 0x235D0, size: 3, format: 'RGB' },
        smoke: { format: 'CF', offsets: [0x918, 0x925, 0x956] },
        trail_smoke: { format: 'CF', offsets: [0x1D8, 0x1E5, 0x216] },
        wing_smoke: { format: 'CF', offsets: [0x3AA, 0x3B7, 0x3ED] },
        dots: { format: 'CF', offsets: [0x29A, 0x2AA] }
      },
      vanilla: {
        color1: 'FF7F00',
        color2: 'FF0000',
        flare_lines_c2: 'FFFFFF',
        flare_small_c1: 'FFCC00',
        flare_big_c1: 'FF9900',
        smoke: 'DE8E2B',
        trail_smoke: 'FFFFFF',
        wing_smoke: 'FEFFE1',
        dots: 'FF051A'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Main punch fire color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Punch fire secondary color', format: 'RGB' }
      ]
    },
    {
      // NEW 2026-07 from the reference 🔴 list; offsets verified via the
      // working "Blue Falcon Kick and Raptor Boost" mod byte-diff + in-game
      // live pokes (docs/EXTRAS_AUDIT.md). 07-block @0x1DE00: +4 = foot fire
      // core, +8 = round glow halo. CF offsets = COLOR positions (marker+2)
      // written as direct RGB; _c1 = record primaries, _c2 = the +7
      // secondaries (sustained puff tint). Mirrors backend/core/extra_types.py.
      id: 'falcon_kick',
      name: 'Falcon Kick',
      description: 'Falcon Kick fire, trail smoke, and spark colors',
      targetFile: 'EfCaData.dat',
      icon: 'punch',
      offsets: {
        color1: { start: 0x1DE04, size: 3, format: 'RGB' },
        color2: { start: 0x1DE08, size: 3, format: 'RGB' },
        front_c1: { format: 'RGB', offsets: [0x6AF, 0x6B6] },
        trail_c1: {
          format: 'RGB',
          offsets: [0x12F, 0x149, 0x159, 0x16C, 0x17C,
                    0x58F, 0x5A9, 0x5B9, 0x5CC, 0x5DC,
                    0x640, 0x64E, 0x65C]
        },
        trail_c2: {
          format: 'RGB',
          offsets: [0x136, 0x150, 0x160, 0x173, 0x183,
                    0x596, 0x5B0, 0x5C0, 0x5D3, 0x5E3,
                    0x647, 0x655, 0x663]
        },
        dots_c1: { format: 'RGB', offsets: [0x474, 0x484, 0x4D9, 0x4E6, 0x539] },
        dots_c2: { format: 'RGB', offsets: [0x47B, 0x48B, 0x4E0, 0x4ED, 0x540] }
      },
      vanilla: {
        color1: 'FFFFE5',
        color2: 'FFB200',
        front_c1: 'FFFFFF',
        trail_c1: 'FFFFFF',
        trail_c2: 'D2CE9E',
        dots_c1: 'FF290C',
        dots_c2: 'FFFF82'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Kick fire core and trail color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Glow halo and trail fade color', format: 'RGB' }
      ]
    },
    {
      // NEW 2026-07, same provenance as falcon_kick. 07-block @0x24B74:
      // +4 = fist lens-flare core, +8 = glow halo (whiff-verified in-game).
      // The hit_* layers = the on-hit uppercut fire/smoke burst records,
      // VERIFIED ON-HIT 2026-07-02 with the punching-bag harness (DK bag).
      // hit_mat_c1 = HSD material DIFFUSE ONLY @0x25440 -- the bag live-poke
      // confirmed ambient @0x2543C (808080) is a 42_48 no-op (Mario/Fox
      // precedent) so it is dropped; diffuse alone recolors the raptor
      // uppercut lens-flare burst. Mirrors backend/core/extra_types.py.
      id: 'raptor_boost',
      name: 'Raptor Boost',
      description: 'Raptor Boost fist flare and hit fire/smoke colors',
      targetFile: 'EfCaData.dat',
      icon: 'punch',
      offsets: {
        color1: { start: 0x24B78, size: 3, format: 'RGB' },
        color2: { start: 0x24B7C, size: 3, format: 'RGB' },
        hit_smoke_c1: {
          format: 'RGB',
          offsets: [0x76F, 0x77F, 0x78F, 0x79F, 0x8A0, 0x8AE, 0x8BC]
        },
        hit_smoke_c2: {
          format: 'RGB',
          offsets: [0x776, 0x786, 0x796, 0x7A6, 0x8A7, 0x8B5, 0x8C3]
        },
        hit_dots_c1: { format: 'RGB', offsets: [0x82C, 0x83C] },
        hit_dots_c2: { format: 'RGB', offsets: [0x833, 0x843] },
        hit_mat_c1: { format: 'RGB', offsets: [0x25440] }
      },
      vanilla: {
        color1: 'F9FFB2',
        color2: 'FFB200',
        hit_smoke_c1: 'CACACA',
        hit_smoke_c2: 'C51D00',
        hit_dots_c1: 'FF051A',
        hit_dots_c2: 'FFFF82',
        hit_mat_c1: '808080'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Fist flare core and hit fire color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Flare glow and hit smoke fade color', format: 'RGB' }
      ]
    },
    {
      // Audit 2026-07: the dominant Falcon Punch fire (bird body, wing fire,
      // tail streamers) = effCaptainDataTable Models_0. Its texture list has
      // ten entries but only THREE unique image nodes (TObjs share image
      // data): lava tile (idx 0), ember tile (idx 6), tail-wisp (idx 9) --
      // target each node ONCE. Texture extras have no standalone card (see
      // getExtraTypes); applied via the backend /storage/textures/* routes.
      // NESTED inside falcon_punch's EffectEditorPage
      // (modifications.fire), same pattern as Fox/Falco's upb_texture
      // inside EffectEditorPage (task #12 migration, 2026-07-02 -- this extra
      // previously had NO frontend wiring at all). Mirrors
      // backend/core/extra_types.py.
      id: 'punch_texture',
      name: 'Falcon Punch Fire Texture',
      description: 'Falcon Punch fire color',
      targetFile: 'EfCaData.dat',
      type: 'texture',
      texturePath: 'effCaptainDataTable/Models_0_/RootJoint',
      textureIndex: 0, // canonical (lava tile; vanilla ref / hue detection)
      textureTargets: [
        { path: 'effCaptainDataTable/Models_0_/RootJoint', index: 0 },
        { path: 'effCaptainDataTable/Models_0_/RootJoint', index: 6 },
        { path: 'effCaptainDataTable/Models_0_/RootJoint', index: 9 }
      ],
      // Recorded reference AND the apply-time shift source (see
      // backend/vault/extras/textures.py's "Vanilla-hue SOURCE"
      // docstring section).
      vanillaHue: 15,
      // ColorPicker UX (task #12): editor sends {"color": "RRGGBB"};
      // backend converts to degrees via hex_to_hue(color) - vanillaHue. Old
      // saved mods' {"hue": degrees} shape is still accepted forever
      // (resolve_hue_shift back-compat).
      properties: [
        { id: 'color', name: 'Fire Color', description: 'Falcon Punch fire/bird texture color', format: 'RGB' }
      ]
    }
  ],
  // Sword trails render as a two-color ribbon (inner edge -> outer edge, with
  // an alpha fade from blade to tail); the 9 DAT bytes are
  // [alpha_blade][alpha_tail][inner RGB][pad][outer RGB] -- see the decomp's
  // itSword_UnkBytes + ft/ftafterimage.c. Mirrors backend/core/extra_types.py.
  Marth: [
    {
      id: 'sword',
      name: 'Sword Trail',
      description: 'Sword swing trail colors',
      targetFile: 'PlMs.dat',
      icon: 'sword',
      offsets: {
        inner: { start: 0x394A, size: 3, format: 'RGB' },
        outer: { start: 0x394E, size: 3, format: 'RGB' },
        alpha_blade: { start: 0x3948, size: 1, format: 'BYTE' },
        alpha_tail: { start: 0x3949, size: 1, format: 'BYTE' }
      },
      vanilla: {
        inner: '00FFFF',     // Cyan
        outer: 'FFFFFF',     // White
        alpha_blade: 'FF',
        alpha_tail: '00'
      },
      properties: [
        { id: 'inner', name: 'Inner Edge', description: 'Color along the hilt-side edge of the trail', format: 'RGB' },
        { id: 'outer', name: 'Outer Edge', description: 'Color along the tip-side edge of the trail', format: 'RGB' }
      ]
    }
  ],
  Roy: [
    {
      id: 'sword',
      name: 'Sword Trail',
      description: 'Sword swing trail colors',
      targetFile: 'PlFe.dat',
      icon: 'sword',
      offsets: {
        inner: { start: 0x3AA2, size: 3, format: 'RGB' },
        outer: { start: 0x3AA6, size: 3, format: 'RGB' },
        alpha_blade: { start: 0x3AA0, size: 1, format: 'BYTE' },
        alpha_tail: { start: 0x3AA1, size: 1, format: 'BYTE' }
      },
      vanilla: {
        inner: 'EB7850',     // Orange
        outer: 'FFFFFF',     // White
        alpha_blade: 'FF',
        alpha_tail: '00'
      },
      properties: [
        { id: 'inner', name: 'Inner Edge', description: 'Color along the hilt-side edge of the trail', format: 'RGB' },
        { id: 'outer', name: 'Outer Edge', description: 'Color along the tip-side edge of the trail', format: 'RGB' }
      ]
    }
  ],
  Link: [
    {
      id: 'sword',
      name: 'Sword Trail',
      description: 'Sword swing trail colors',
      targetFile: 'PlLk.dat',
      icon: 'sword',
      offsets: {
        inner: { start: 0x35EE, size: 3, format: 'RGB' },
        outer: { start: 0x35F2, size: 3, format: 'RGB' },
        alpha_blade: { start: 0x35EC, size: 1, format: 'BYTE' },
        alpha_tail: { start: 0x35ED, size: 1, format: 'BYTE' }
      },
      vanilla: {
        inner: '00FFFF',     // Cyan
        outer: 'FFFFFF',     // White
        alpha_blade: 'FF',
        alpha_tail: '00'
      },
      properties: [
        { id: 'inner', name: 'Inner Edge', description: 'Color along the hilt-side edge of the trail', format: 'RGB' },
        { id: 'outer', name: 'Outer Edge', description: 'Color along the tip-side edge of the trail', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07-02 from research/docs-research/effect-maps/link.md (MAP-LIVE
      // verified). EfLkData.dat model-region 07 07 07 04 marker @0x550C:
      // +4 = bright core (0x5510, vanilla FFFFFF), +8 = tint/glow (0x5514,
      // vanilla 0000FF). Live-poke confirmed: core->magenta + tint->red
      // turned the swirling up-B blade/disc trail magenta/red across the
      // whole up-B active window (f6-f30). Shared with Young Link: ftCLink
      // has no EfCl file and loads EfLkData directly. Mirrors
      // backend/core/extra_types.py.
      id: 'spin_attack_trail',
      name: 'Spin Attack Trail',
      description: 'Up-B swirling blade/disc trail core and glow colors',
      targetFile: 'EfLkData.dat',
      icon: 'spin_attack_trail',
      shared: true,
      sharedWith: ['Young Link'],
      owner: 'Link',
      offsets: {
        color1: { start: 0x5510, size: 3, format: 'RGB' },
        color2: { start: 0x5514, size: 3, format: 'RGB' }
      },
      vanilla: {
        color1: 'FFFFFF',
        color2: '0000FF'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Up-B trail bright core', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Up-B trail tint/glow', format: 'RGB' }
      ]
    }
  ],
  'Young Link': [
    {
      id: 'sword',
      name: 'Sword Trail',
      description: 'Sword swing trail colors',
      targetFile: 'PlCl.dat',
      icon: 'sword',
      offsets: {
        inner: { start: 0x3792, size: 3, format: 'RGB' },
        outer: { start: 0x3796, size: 3, format: 'RGB' },
        alpha_blade: { start: 0x3790, size: 1, format: 'BYTE' },
        alpha_tail: { start: 0x3791, size: 1, format: 'BYTE' }
      },
      vanilla: {
        inner: '00FFFF',     // Cyan
        outer: 'FFFFFF',     // White
        alpha_blade: 'FF',
        alpha_tail: '00'
      },
      properties: [
        { id: 'inner', name: 'Inner Edge', description: 'Color along the hilt-side edge of the trail', format: 'RGB' },
        { id: 'outer', name: 'Outer Edge', description: 'Color along the tip-side edge of the trail', format: 'RGB' }
      ]
    }
  ],
  Pikachu: [
    {
      id: 'thunder',
      name: 'Thunder',
      description: 'Down-B Thunder bolt colors',
      targetFile: 'PlPk.dat',
      icon: 'thunder',
      format: '07_07_07',
      // NOT shared with Pichu: Pichu's bolt reads PlPc.dat (audit 2026-07);
      // Pichu has his own entry below.
      offsets: {
        color1: { start: 0xC358, size: 3, format: 'RGB' },
        color2: { start: 0xC35C, size: 3, format: 'RGB' }
      },
      vanilla: {
        color1: 'FFFFFF',  // White
        color2: 'FFFF00'   // Yellow
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Main bolt color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Bolt glow color', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07-02 from research/docs-research/effect-maps/pikachu.md (MAP-LIVE
      // verified). AERIAL half of neutral-B thunder jolt -- EfPkData.dat CF
      // records (script 1-4). PRIM = starburst core, ENV (colorpos+7) =
      // outer lens glow (dominant tint). Only confirmed via an AIRBORNE
      // neutral-B (grounded neutralb only fires the PlPk ground bolt, see
      // pikachu_thunder_jolt_ground). Mirrors backend/core/extra_types.py.
      id: 'pikachu_thunder_jolt_air',
      name: 'Thunder Jolt (Aerial)',
      description: 'Aerial neutral-B thunder jolt starburst and lens-flare colors',
      targetFile: 'EfPkData.dat',
      icon: 'neutralb',
      offsets: {
        jolt_air_mid_c1: { format: 'RGB', offsets: [0x168] },
        jolt_air_mid_c2: { format: 'RGB', offsets: [0x16F] },
        jolt_air_outerflare_c1: { format: 'RGB', offsets: [0x1D0] },
        jolt_air_outerflare_c2: { format: 'RGB', offsets: [0x1D7] },
        jolt_air_midflare_c1: { format: 'RGB', offsets: [0x238] },
        jolt_air_midflare_c2: { format: 'RGB', offsets: [0x23F] },
        jolt_air_innerborder_c1: { format: 'RGB', offsets: [0x2A0] },
        jolt_air_innerborder_c2: { format: 'RGB', offsets: [0x2A7] },
        jolt_air_innertri_c1: { format: 'RGB', offsets: [0x2AD] }
      },
      vanilla: {
        color1: 'FFFFFF',
        color2: '6681FA',
        jolt_air_mid_c1: 'FFFFFF',
        jolt_air_mid_c2: '6681FA',
        jolt_air_outerflare_c1: '0B0BE6',
        jolt_air_outerflare_c2: '07078F',
        jolt_air_midflare_c1: '8FD6FF',
        jolt_air_midflare_c2: '0C0CFF',
        jolt_air_innerborder_c1: 'FE061B',
        jolt_air_innerborder_c2: 'FB9E14',
        jolt_air_innertri_c1: 'FFFFFF'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Starburst core and inner triangle color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Outer/mid lens-flare glow color', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07-02, same mission as pikachu_thunder_jolt_air. GROUND
      // half of the thunder jolt -- PlPk.dat traveling bolt article,
      // separate target_file (one target_file per extra convention).
      // Mirrors backend/core/extra_types.py.
      id: 'pikachu_thunder_jolt_ground',
      name: 'Thunder Jolt (Ground Bolt)',
      description: 'Grounded neutral-B thunder jolt traveling bolt colors',
      targetFile: 'PlPk.dat',
      icon: 'neutralb',
      offsets: {
        jolt_gnd_a_c1: { format: 'RGB', offsets: [0x14E00] },
        jolt_gnd_a_c2: { format: 'RGB', offsets: [0x14E04] },
        jolt_gnd_b_c1: { format: 'RGB', offsets: [0x14ECC] },
        jolt_gnd_b_c2: { format: 'RGB', offsets: [0x14ED0] },
        jolt_gnd_c_c1: { format: 'RGB', offsets: [0x14F98] },
        jolt_gnd_c_c2: { format: 'RGB', offsets: [0x14F9C] },
        jolt_gnd_d_c1: { format: 'RGB', offsets: [0x15064] },
        jolt_gnd_d_c2: { format: 'RGB', offsets: [0x15068] },
        jolt_gnd_head_c1: { format: 'RGB', offsets: [0x151F4] }
      },
      vanilla: {
        color1: 'B2E5FF',
        color2: '0000FF',
        jolt_gnd_a_c1: 'B2E5FF',
        jolt_gnd_a_c2: '0000FF',
        jolt_gnd_b_c1: 'B2E5FF',
        jolt_gnd_b_c2: '0000FF',
        jolt_gnd_c_c1: 'B2E5FF',
        jolt_gnd_c_c2: '0000FF',
        jolt_gnd_d_c1: 'B2E5FF',
        jolt_gnd_d_c2: '0000FF',
        jolt_gnd_head_c1: '004CFF'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Traveling bolt core and spawn head color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Traveling bolt glow color', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07-02 from research/docs-research/effect-maps/pikachu.md. GROUND
      // forward-smash electric arc, 4 070707 model-region blocks in
      // EfPkData.dat. AIR clone (0x17Cxx) NOT bundled -- unverified solo,
      // pending punching-bag/EYEBALL. Mirrors backend/core/extra_types.py.
      id: 'pikachu_fsmash',
      name: 'Forward Smash Arc',
      description: 'Forward smash electric arc and ball colors',
      targetFile: 'EfPkData.dat',
      icon: 'fsmash',
      offsets: {
        fsmash_pre_c1: { format: 'RGB', offsets: [0x148E0] },
        fsmash_pre_c2: { format: 'RGB', offsets: [0x148E4] },
        fsmash_aura1_c1: { format: 'RGB', offsets: [0x14C84] },
        fsmash_aura1_c2: { format: 'RGB', offsets: [0x14C88] },
        fsmash_aura2_c1: { format: 'RGB', offsets: [0x14D50] },
        fsmash_aura2_c2: { format: 'RGB', offsets: [0x14D54] },
        fsmash_ball_c1: { format: 'RGB', offsets: [0x14E10] },
        fsmash_ball_c2: { format: 'RGB', offsets: [0x14E14] }
      },
      vanilla: {
        color1: 'CCE5FF',
        color2: '0000FF',
        fsmash_pre_c1: 'CCE5FF',
        fsmash_pre_c2: '0000FF',
        fsmash_aura1_c1: 'CCE5FF',
        fsmash_aura1_c2: '0000FF',
        fsmash_aura2_c1: 'CCE5FF',
        fsmash_aura2_c2: '0000FF',
        fsmash_ball_c1: 'FFFFFF',
        fsmash_ball_c2: '004CFF'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Arc core and ball color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Arc glow and ball glow color', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07-02 from research/docs-research/effect-maps/efcodata.md §6b
      // "Shippable-now summary". EfCoData.dat is the CAST-SHARED common
      // effect bank (not per-character) -- this pool of 25 scripts is the
      // generic 15070 "Purple Electric Pack" target: subaction event-GFX
      // spawned sparks with no attributable single-move C-caller, so
      // semantics come from a LIVE poke, not decomp cross-ref. MAP-LIVE
      // 2026-07-02 (tests/artifacts/datram-probe-efcodata-zelda/): poked 9
      // of the 25 records green while Zelda took a jab hit -- the body-wide
      // BLUE ELECTRIC ARC + RADIAL SPARK RAYS that flash on hitlag turned
      // bright GREEN. This is the ON-HIT/HITLAG electric spark burst that
      // fires when an ELECTRIC-element hitbox connects -- verified as a group; remaining un-poked
      // records are the same 15070 sweep and ship with the group per spec.
      //
      // Per template lesson 12: vanilla bytes are NOT uniform across the 35
      // records -- each is its own layer_id with its own byte-verified
      // vanilla. `_c1` = each script's first/primary record (25 scripts),
      // `_c2` = additional records in multi-record scripts (10 records
      // across scripts 0/13/29/30/268). Owner: Pikachu (most-associated
      // character for a cast-wide electric effect, same pattern as
      // common_fire/common_flash under Zelda); sharedWith the rest of the
      // roster -- description says plainly this is NOT Pikachu-only.
      // Mirrors backend/core/extra_types.py.
      id: 'common_electric',
      name: 'Electric Hit Spark',
      // ACCURACY FIX 2026-07-02: the spark only spawns on Element==Electric(2)
      // hitbox connect, so it is NOT cast-wide. Old config listed the whole
      // roster (Marth/Roy/Link/Mario/... with no electric attack) -- wrong.
      // sharedWith is now DATA-DERIVED via backend/shared/rendering/hitbox_elements.py
      // (vanilla Element==2 hitbox scan; roster minus owner Pikachu; self-test
      // Zelda electric / Pikachu-Pichu many / Marth zero). See
      // research/docs-research/effect-maps/efcodata.md for the per-char electric table.
      description: "On-hit electric spark burst color -- the blue electric arc + radial spark rays that flash when an ELECTRIC-element attack connects (Pikachu/Pichu thunder & jolts, Zelda's jab + lightning kicks, Fox/Falco shine, Ness's PK Thunder & electric aerials, Mewtwo's electric hits, Ganondorf's jab/dair, Samus's screw attack/grapple, Sheik's needles/side-B, Doc's electric fsmash, Kirby's copied neutral-B, G&W's Judgment 6). Shared out of the common effects file; characters with no electric attack (Marth, Roy, Link, Mario, ...) never trigger it",
      targetFile: 'EfCoData.dat',
      icon: 'thunder',
      shared: true,
      // DATA-DERIVED via backend/shared/rendering/hitbox_elements.py (vanilla
      // Element==2 hitbox scan); roster minus owner Pikachu.
      sharedWith: ['C. Falcon', 'Falco', 'Fox', 'Ganondorf', 'Kirby', 'Mewtwo',
        'Ness', 'Pichu', 'Samus', 'Sheik', 'Zelda', 'Dr. Mario', 'G&W'],
      owner: 'Pikachu',
      offsets: {
        elec_s0_a_c1: { format: 'RGB', offsets: [0xDC5] },
        elec_s0_b_c2: { format: 'RGB', offsets: [0xDDB] },
        elec_s0_c_c2: { format: 'RGB', offsets: [0xDF1] },
        elec_s0_d_c2: { format: 'RGB', offsets: [0xE0F] },
        elec_s0_e_c2: { format: 'RGB', offsets: [0xE1D] },
        elec_s1_c1: { format: 'RGB', offsets: [0xEAD] },
        elec_s13_a_c1: { format: 'RGB', offsets: [0x1384] },
        elec_s13_b_c2: { format: 'RGB', offsets: [0x13AB] },
        elec_s13_c_c2: { format: 'RGB', offsets: [0x13BA] },
        elec_s13_d_c2: { format: 'RGB', offsets: [0x13D7] },
        elec_s14_c1: { format: 'RGB', offsets: [0x1425] },
        elec_s16_c1: { format: 'RGB', offsets: [0x14F5] },
        elec_s17_c1: { format: 'RGB', offsets: [0x1560] },
        elec_s18_c1: { format: 'RGB', offsets: [0x15BA] },
        elec_s19_c1: { format: 'RGB', offsets: [0x1609] },
        elec_s29_a_c1: { format: 'RGB', offsets: [0x1C17] },
        elec_s29_b_c2: { format: 'RGB', offsets: [0x1C24] },
        elec_s30_a_c1: { format: 'RGB', offsets: [0x1C8D] },
        elec_s30_b_c2: { format: 'RGB', offsets: [0x1C9A] },
        elec_s31_c1: { format: 'RGB', offsets: [0x1CFF] },
        elec_s73_c1: { format: 'RGB', offsets: [0x2F15] },
        elec_s161_c1: { format: 'RGB', offsets: [0x5550] },
        elec_s162_c1: { format: 'RGB', offsets: [0x55B1] },
        elec_s268_a_c1: { format: 'RGB', offsets: [0x854E] },
        elec_s268_b_c2: { format: 'RGB', offsets: [0x855B] },
        elec_s269_c1: { format: 'RGB', offsets: [0x85B6] },
        elec_s270_c1: { format: 'RGB', offsets: [0x860E] },
        elec_s306_c1: { format: 'RGB', offsets: [0x9779] },
        elec_s332_c1: { format: 'RGB', offsets: [0xA1DD] },
        elec_s423_c1: { format: 'RGB', offsets: [0xCDB7] },
        elec_s424_c1: { format: 'RGB', offsets: [0xCE18] },
        elec_s425_c1: { format: 'RGB', offsets: [0xCE84] },
        elec_s426_c1: { format: 'RGB', offsets: [0xCEEF] },
        elec_s448_c1: { format: 'RGB', offsets: [0xD87D] },
        elec_s537_c1: { format: 'RGB', offsets: [0x10019] }
      },
      vanilla: {
        color1: 'FFF305',
        color2: 'FF0000',
        elec_s0_a_c1: 'FFF305',
        elec_s0_b_c2: 'FF0000',
        elec_s0_c_c2: '1155FF',
        elec_s0_d_c2: '1FA60D',
        elec_s0_e_c2: '26CF10',
        elec_s1_c1: '1165FF',
        elec_s13_a_c1: '0063FF',
        elec_s13_b_c2: '0061FF',
        elec_s13_c_c2: '000000',
        elec_s13_d_c2: '003FFF',
        elec_s14_c1: 'A30CFF',
        elec_s16_c1: '82A1F8',
        elec_s17_c1: '210CFF',
        elec_s18_c1: '3FFF00',
        elec_s19_c1: '210CFF',
        elec_s29_a_c1: 'E6FEFF',
        elec_s29_b_c2: '0D6DFC',
        elec_s30_a_c1: 'FFFFFF',
        elec_s30_b_c2: 'FBFEB5',
        elec_s31_c1: '5F9BFC',
        elec_s73_c1: '4FA4FF',
        elec_s161_c1: 'A1C7FF',
        elec_s162_c1: 'B9DBFD',
        elec_s268_a_c1: 'BFFEC7',
        elec_s268_b_c2: '4EFA48',
        elec_s269_c1: 'F870C8',
        elec_s270_c1: '82DBF8',
        elec_s306_c1: 'FC94FF',
        elec_s332_c1: '210CFF',
        elec_s423_c1: 'F9101C',
        elec_s424_c1: '190DFC',
        elec_s425_c1: '9CF5FD',
        elec_s426_c1: '7AF2FF',
        elec_s448_c1: '0E07D9',
        elec_s537_c1: '70F6FF'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Electric spark burst color (every script\'s primary record)', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Additional spark records in the multi-record scripts', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07-02 from research/docs-research/effect-maps/efcodata.md §6b. s95
      // (EfCoData script 95) is the CASTER-SIDE half of Pikachu's neutral-B
      // Thunder Jolt -- MAP-LIVE 2026-07-02 (Pikachu solo, tests/artifacts/
      // datram-probe-efcodata-pika/): poking all 3 records magenta turned
      // the small dissipation/cheek sparkles at Pikachu magenta-white.
      // HONESTY NOTE (also in the description below): the big blue Thunder
      // Jolt fountain/travelling bolt is a SEPARATE texture-driven article
      // effect and is UNCHANGED by this extra -- s95 only owns the small
      // caster-side spark, a real but SUBTLE recolor. sharedWith Luigi: s95
      // is also the side-B "remove" GFX (a despawn flash, not a visible
      // move) -- listed for honesty per the also-affects rule. The record
      // at 0x3930 is a 3rd operand folded into the `_c2` bucket alongside
      // 0x3921 (no `_c3` precedent anywhere in this config; both are
      // grayscale-family ambient tones). Mirrors backend/core/extra_types.py.
      id: 'thunder_jolt_spark',
      name: 'Thunder Jolt Cheek Spark',
      description: 'Subtle caster-side dissipation/cheek sparkle on Pikachu\'s neutral-B Thunder Jolt -- this is a small accent spark, NOT the big blue jolt fountain/bolt itself (that is a separate texture effect and is unaffected). Also affects the Luigi side-B remove flash (shared common-bank script)',
      targetFile: 'EfCoData.dat',
      icon: 'thunder',
      shared: true,
      sharedWith: ['Luigi'],
      owner: 'Pikachu',
      offsets: {
        jolt_spark_a_c1: { format: 'RGB', offsets: [0x391A] },
        jolt_spark_a_c2: { format: 'RGB', offsets: [0x3921] },
        jolt_spark_b_c2: { format: 'RGB', offsets: [0x3930] }
      },
      vanilla: {
        color1: 'EAE7E9',
        color2: '6E6E6E',
        jolt_spark_a_c1: 'EAE7E9',
        jolt_spark_a_c2: '6E6E6E',
        jolt_spark_b_c2: '575757'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Cheek spark core color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Cheek spark ambient/glow color', format: 'RGB' }
      ]
    }
  ],
  Pichu: [
    {
      id: 'thunder',
      name: 'Thunder',
      description: 'Down-B Thunder bolt colors',
      targetFile: 'PlPc.dat',
      icon: 'thunder',
      format: '07_07_07',
      // Same 07 07 07 04 block as Pikachu's, at Pichu's own offset 0xBF14
      offsets: {
        color1: { start: 0xBF18, size: 3, format: 'RGB' },
        color2: { start: 0xBF1C, size: 3, format: 'RGB' }
      },
      vanilla: {
        color1: 'FFFFFF',  // White
        color2: 'FFFF00'   // Yellow
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Main bolt color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Bolt glow color', format: 'RGB' }
      ]
    }
  ],
  Mewtwo: [
    {
      id: 'shadow_ball',
      name: 'Shadow Ball',
      description: 'Shadow Ball colors',
      targetFile: 'PlMt.dat',
      icon: 'shadowball',
      format: 'direct_rgb',
      // Live-poke mapped 2026-07 (docs/EXTRAS_AUDIT.md): thrown center
      // @0x100AC, charging-ball center @0x105CC, four inner-ball lightning
      // bolts. color1 = bright core (center flash / bolt line), color2 =
      // glow; the _c1/_c2 suffixes fan the charge/bolt layers out from the
      // same two pickers (EffectEditorPage convention).
      offsets: {
        color1: { start: 0x100B0, size: 3, format: 'RGB' },
        color2: { start: 0x100B4, size: 3, format: 'RGB' },
        charge_c1: { start: 0x105D0, size: 3, format: 'RGB' },
        charge_c2: { start: 0x105D4, size: 3, format: 'RGB' },
        bolts_c1: { format: 'RGB', offsets: [0x102D0, 0x10390, 0x10450, 0x10510] },
        bolts_c2: { format: 'RGB', offsets: [0x102D4, 0x10394, 0x10454, 0x10514] }
      },
      vanilla: {
        color1: 'FFFFFF',  // White center
        color2: '0000FF',  // Blue glow
        charge_c1: 'FFFFFF',
        charge_c2: '0000FF',
        bolts_c1: 'FFFFFF',
        bolts_c2: '007FFF'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Center flash and bolt color (charging + thrown)', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Inner glow color', format: 'RGB' }
      ]
    },
    {
      // Up-smash (Galaxy Force) swirl -- EfMtData 07 07 07 04 marker @0xC754
      id: 'upsmash',
      name: 'Up Smash Swirl',
      description: 'Up-smash swirl colors',
      targetFile: 'EfMtData.dat',
      icon: 'shadowball',
      format: 'direct_rgb',
      offsets: {
        color1: { start: 0xC758, size: 3, format: 'RGB' },
        color2: { start: 0xC75C, size: 3, format: 'RGB' }
      },
      vanilla: {
        color1: '6600CC',  // Purple
        color2: '000000'   // Black
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Main swirl color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Swirl secondary color', format: 'RGB' }
      ]
    }
  ],
  Falco: [
    {
      id: 'laser',
      name: 'Laser Color',
      description: 'Change laser beam colors',
      targetFile: 'PlFc.dat',
      icon: 'laser',
      // Offset definitions for the 98 matrix format (Falco-specific).
      // center/tip = the bright white core line down the beam (RGB-format
      // matrices, audit 2026-07); mirrors backend/core/extra_types.py.
      offsets: {
        wide: { start: 0x13440, end: 0x134A0 },
        thin: { start: 0x134E0, end: 0x13540 },
        outline: { start: 0x13580, end: 0x135E0 },
        tip: { start: 0x13620, end: 0x13643, format: 'RGB' },
        center: { start: 0x13643, end: 0x1368E, format: 'RGB' }
      },
      properties: [
        { id: 'wide', name: 'Wide Layer', description: 'Transparent outer glow' },
        { id: 'thin', name: 'Thin Layer', description: 'Semi-transparent middle' },
        { id: 'outline', name: 'Outline', description: 'Opaque inner core' },
        { id: 'center', name: 'Center Line', description: 'Bright core line down the beam', format: 'RGB' },
        { id: 'tip', name: 'Center Tip', description: 'Leading tip of the core line', format: 'RGB' }
      ]
    },
    {
      id: 'sideb',
      name: 'Side-B Color',
      description: 'Phantasm afterimage colors',
      targetFile: 'PlFc.dat',
      afterimageModel: true,
      icon: 'sideb',
      format: '42_48',
      // 42_48 format: 3 RGBA colors
      offsets: {
        primary: { start: 0x1EC48, size: 4 },
        secondary: { start: 0x1EC4C, size: 4 },
        tertiary: { start: 0x1EC50, size: 4 }
      },
      vanilla: {
        primary: '0099FFFF',
        secondary: 'CCE6FFFF',
        tertiary: 'FFFFFFFF'
      },
      properties: [
        { id: 'primary', name: 'Primary', description: 'Main afterimage color' },
        { id: 'secondary', name: 'Secondary', description: 'Edge/gradient color' },
        { id: 'tertiary', name: 'Glow', description: 'Outer glow color' }
      ]
    },
    {
      id: 'gun',
      name: 'Gun Model',
      description: 'Replace Falco\'s blaster gun model',
      targetFile: 'PlFc.dat',
      icon: 'gun',
      type: 'model',  // Model type - uses .dae file instead of hex patches
      modelPath: 'ftDataFalco/Articles/Articles_1/Model_/RootModelJoint'
    }
  ],
  Fox: [
    {
      id: 'laser',
      name: 'Laser Color',
      description: 'Change laser beam colors',
      targetFile: 'PlFx.dat',
      icon: 'laser',
      // Offset definitions for the 98 matrix format (Fox-specific).
      // center/tip = the bright white core line down the beam (RGB-format
      // matrices, audit 2026-07); mirrors backend/core/extra_types.py.
      offsets: {
        wide: { start: 0x13E20, end: 0x13E80 },
        thin: { start: 0x13EC0, end: 0x13F20 },
        outline: { start: 0x13F60, end: 0x13FC0 },
        tip: { start: 0x14000, end: 0x14023, format: 'RGB' },
        center: { start: 0x14023, end: 0x1406E, format: 'RGB' }
      },
      properties: [
        { id: 'wide', name: 'Wide Layer', description: 'Transparent outer glow' },
        { id: 'thin', name: 'Thin Layer', description: 'Semi-transparent middle' },
        { id: 'outline', name: 'Outline', description: 'Opaque inner core' },
        { id: 'center', name: 'Center Line', description: 'Bright core line down the beam', format: 'RGB' },
        { id: 'tip', name: 'Center Tip', description: 'Leading tip of the core line', format: 'RGB' }
      ]
    },
    {
      id: 'sideb',
      name: 'Side-B Color',
      description: 'Illusion afterimage colors',
      targetFile: 'PlFx.dat',
      icon: 'sideb',
      format: '42_48',
      // 42_48 format: 3 RGBA colors
      offsets: {
        primary: { start: 0x2204C, size: 4 },
        secondary: { start: 0x22050, size: 4 },
        tertiary: { start: 0x22054, size: 4 }
      },
      vanilla: {
        primary: '0099FFFF',
        secondary: 'CCE6FFFF',
        tertiary: 'FFFFFFFF'
      },
      properties: [
        { id: 'primary', name: 'Primary', description: 'Main afterimage color' },
        { id: 'secondary', name: 'Secondary', description: 'Edge/gradient color' },
        { id: 'tertiary', name: 'Glow', description: 'Outer glow color' }
      ]
    },
    {
      id: 'upb',
      name: 'Up-B Color',
      description: 'Firefox/Firebird flame colors',
      targetFile: 'EfFxData.dat',
      icon: 'upb',
      shared: true,  // Shared between Fox and Falco
      sharedWith: ['Falco'],  // Characters that share this extra
      owner: 'Fox',  // Which character owns the mods in storage
      offsets: {
        // 98 matrix format for flame tip
        tip: { start: 0x1AC80, end: 0x1AD00, format: 'RGBY' },
        // 98 matrix format for firefox body when not textured
        body: { start: 0x1A880, end: 0x1AA50, format: 'RGB' },
        // CF format - trailing fire (all sizes combined)
        // CF XX RR GG BB - color at offset+2
        trail: {
          format: 'CF',
          offsets: [
            0x2EE, 0x2F4, 0x324, 0x32B,  // Large trailing fire
            0x52E, 0x534,  // Big trailing fire
            0x55E  // Central mid-flight fire clumps (live-verified 2026-07-03)
          ]
        },
        // Small trailing fire (audit 2026-07: previously uncovered).
        // Real CF markers verified against vanilla bytes.
        small_trail: {
          format: 'CF',
          offsets: [0x382, 0x392, 0x3A2, 0x3B2, 0x3C4]
        },
        // Square dot particles during travel
        dots: {
          format: 'CF',
          offsets: [0x43A, 0x44A]
        },
        // Lines coming off the charge
        charge_lines: {
          format: 'CF',
          offsets: [0x5AF]
        },
        // Lens flare while in motion (marker verified at 0x1A508)
        flare: { start: 0x1A508, format: '070707' },
        // 070707 format - fire rings
        // 07 07 07 04 RR GG BB 00 RR GG BB - colors at +4 and +8
        rings: {
          format: '070707',
          offsets: [0x1B454, 0x1B520]
        }
      },
      vanilla: {
        tip: 'FE60',      // Fire orange (RGBY)
        body: 'FFFFFF',   // White (RGB)
        trail: 'FFFFFF',  // White (RGB)
        small_trail: 'FFF88F',
        dots: 'FF290C',
        charge_lines: 'FFFFFF',
        flare: 'FFE54C',
        rings: 'FFFF00'   // Yellow (RGB)
      },
      properties: [
        { id: 'tip', name: 'Flame Tip', description: 'Fire effect at the tip', format: 'RGBY' },
        { id: 'body', name: 'Body Glow', description: 'Firefox body when charging', format: 'RGB' },
        { id: 'trail', name: 'Trail Fire', description: 'Trailing fire particles', format: 'RGB' },
        { id: 'small_trail', name: 'Small Trail Fire', description: 'Small trailing fire particles', format: 'RGB' },
        { id: 'dots', name: 'Travel Dots', description: 'Square dot particles', format: 'RGB' },
        { id: 'charge_lines', name: 'Charge Lines', description: 'Lines coming off the charge', format: 'RGB' },
        { id: 'flare', name: 'Motion Flare', description: 'Lens flare while flying', format: 'RGB' },
        { id: 'rings', name: 'Fire Rings', description: 'Circular fire rings', format: 'RGB' }
      ]
    },
    {
      // Flight-fire texture color (the EffectEditorPage "Fire Texture"
      // ColorPicker applies this via the backend; no standalone card - see
      // getExtraTypes). Models_4 lists the flame image at tex idx 1 AND 2
      // (the flight cone streamers) but both TObjs share ONE image node --
      // importing at idx 1 recolors both; do NOT also target idx 2 (audit
      // 2026-07). Fox's charge flames are a separate EfCoData script family;
      // see the retired fox-charge-correction report (git history before 2026-10-03). Mirrors backend/core/extra_types.py.
      // ColorPicker UX (task #12 migration, 2026-07-02, was a hue slider):
      // editor sends {"color": "RRGGBB"}; backend converts to degrees via
      // hex_to_hue(color) - vanillaHue. Old saved mods' {"hue": degrees}
      // shape is still accepted forever (resolve_hue_shift back-compat).
      id: 'upb_texture',
      name: 'Up-B Fire Texture',
      description: 'Firefox/Firebird flame color',
      targetFile: 'EfFxData.dat',
      type: 'texture',
      texturePath: 'effFoxDataTable/Models_4_/RootJoint',
      textureIndex: 1,
      shared: true,
      sharedWith: ['Falco'],
      owner: 'Fox',
      // Recorded reference AND the apply-time shift source (see
      // backend/vault/extras/textures.py's "Vanilla-hue SOURCE"
      // docstring section).
      vanillaHue: 15,
      properties: [
        { id: 'color', name: 'Fire Color', description: 'Firefox/Firebird flame texture color', format: 'RGB' }
      ]
    },
    {
      // Corrected 2026-09-09: FLIGHT puff bitmap, not charge fire. Keep the
      // existing ID and palette layout for saved mods. Model 4 emits particle
      // 3004 -> scripts 5/9 use texGroup 3 (8-frame CI8 32x32, RGB5A3 palettes).
      // upb.trail also tints these puffs; nested upb_texture changes separate
      // model streamers. See the retired fox-charge-correction report (git history before 2026-10-03) for the model/
      // particle trace and final-export palette readback. Backend mirror agrees.
      id: 'upb_charge_fire',
      partOf: 'upb',  // edited inside the upb unit's page (getUnitParts)
      name: 'Flight Fire Texture',
      description: 'Firefox/Firebird fire-puff texture during flight. Works with the Up-B trail colors.',
      targetFile: 'EfFxData.dat',
      icon: 'fireball',
      format: 'texture_recolor',
      shared: true,
      sharedWith: ['Falco'],
      owner: 'Fox',
      texture: {
        gxFormat: 9, // CI8
        width: 32,
        height: 32,
        images: [
          { offset: '0xD6E0', palette: '0xF6E0' },
          { offset: '0xDAE0', palette: '0xF8E0' },
          { offset: '0xDEE0', palette: '0xFAE0' },
          { offset: '0xE2E0', palette: '0xFCE0' },
          { offset: '0xE6E0', palette: '0xFEE0' },
          { offset: '0xEAE0', palette: '0x100E0' },
          { offset: '0xEEE0', palette: '0x102E0' },
          { offset: '0xF2E0', palette: '0x104E0' }
        ],
        paletteFormat: 2 // RGB5A3
      },
      vanillaDominantHue: 35.7,
      vanilla: {
        color1: 'FF9400' // representative vanilla swatch (hue 35.7 at full S/V)
      },
      properties: [
        { id: 'color1', name: 'Flight Fire Texture', description: 'Fire-puff texture during flight; Up-B trail colors also tint these puffs', format: 'RGB' }
      ]
    },
    {
      // LIVE 2026-09-09: common script 298 -> s299 broad flames / s300 wisps.
      // Fox-only: Falco charge showed neither family in the consumer test.
      // RGB offsets preserve alpha; exact restore uses each native operand's
      // reference bytes, not these representative swatches. Backend mirror agrees.
      id: 'charge_flames',
      partOf: 'upb',  // edited inside the upb unit's page (getUnitParts)
      name: 'Charge Flames',
      description: "Fox's rising flame puffs and thin wisps while charging Firefox. Uses a common-bank effect triggered by Fox's charge.",
      targetFile: 'EfCoData.dat',
      icon: 'fireball',
      offsets: {
        flame_c1: { format: 'RGB', offsets: [0x93C4, 0x93D1, 0x93ED, 0x93FA] },
        flame_c2: { format: 'RGB', offsets: [0x93CB, 0x93D8, 0x93F4, 0x9401] },
        wisp_c1: { format: 'RGB', offsets: [0x945A, 0x9467, 0x947A] },
        wisp_c2: { format: 'RGB', offsets: [0x9461, 0x946E, 0x9481] },
      },
      vanilla: {
        flame_c1: 'FEF3A0', flame_c2: 'FC885A',
        wisp_c1: 'FEF6B9', wisp_c2: 'FD9A73',
      },
      properties: [
        { id: 'flame_c1', name: 'Core', description: 'Broad rising flame puffs: primary color', format: 'RGB' },
        { id: 'flame_c2', name: 'Tint', description: 'Broad rising flame puffs: blended tint', format: 'RGB' },
        { id: 'wisp_c1', name: 'Core', description: 'Thin flame wisps: primary color', format: 'RGB' },
        { id: 'wisp_c2', name: 'Tint', description: 'Thin flame wisps: blended tint', format: 'RGB' },
      ]
    },
    {
      id: 'shine',
      name: 'Shine Color',
      description: 'Reflector shield colors',
      targetFile: 'EfFxData.dat',
      icon: 'shine',
      shared: true,  // Shared between Fox and Falco
      sharedWith: ['Falco'],  // Characters that share this extra
      owner: 'Fox',  // Which character owns the mods in storage
      // Second kind of shine mod (2026-09-09): the community "image shines"
      // (NERV, Honeycomb, Trollface, ...) put a picture where the hexagon is
      // instead of recoloring it, so they have no color layers. Presence of
      // this key is what turns on the editor's Colors/Image switch; the
      // install/build side is backend/vault/routes/extras/effect_model.py.
      // Mirrors backend/core/extra_types.py.
      imageModel: {
        rootIndex: 0,
        rootSymbol: 'effFoxDataTable',
        modelIndex: 0,     // effFoxDataTable Models_0 == the shine
        width: 256,
        height: 256,
        gxFormat: 5,       // RGB5A3
        halfExtent: 8.0
      },
      offsets: {
        // 98 matrix format for main hexagon shape
        hex: { start: 0x1C2A0, end: 0x1C350, format: 'RGBY' },
        // 98 matrix format for inner glow
        inner: { start: 0x1C860, end: 0x1C8D0, format: 'RGBY' },
        // 98 matrix format for outer glow (multiple matrices, same color)
        outer: {
          format: '98_multi',
          ranges: [
            { start: 0x1C8E0, end: 0x1C920 },
            { start: 0x1C91F, end: 0x1C960 },
            { start: 0x1C95E, end: 0x1C9A0 }
          ]
        },
        // 42_48 format for transparent bubble
        bubble: { start: 0x1B4C4, format: '42_48', size: 12 },
        // Sparkle particles emitted around the shine hexagon (audit 2026-07,
        // research/docs-research/effect-maps/fox-falco-shine-sparkles.md). Two CF
        // records; color = marker+2 (3B RGB), secondary = colorpos+7 (3B RGB,
        // dominates sustained tint). Shared Fox/Falco -- EfFxData.dat is
        // literally the same file for both (no separate EfFcData.dat exists
        // in vanilla), so these offsets apply to Falco unchanged.
        sparkles: {
          format: 'CF-multi',
          records: [
            { marker: 0x125, color: 0x127, secondary: 0x12E },
            { marker: 0x141, color: 0x143, secondary: 0x14A }
          ]
        }
      },
      vanilla: {
        hex: '621F',       // Blue-ish (RGBY)
        inner: '63FF',     // Blue (RGBY)
        outer: '63FF',     // Blue (RGBY)
        bubble: '808080FFFFFFFFFFFFFFFFFF',  // Gray/white gradient (3x RGBA)
        sparkles: 'FFFFFF'  // Vanilla sparkle color (both records' primary color bytes)
      },
      properties: [
        { id: 'hex', name: 'Hexagon', description: 'Main shield shape', format: 'RGBY' },
        { id: 'inner', name: 'Inner Glow', description: 'Inner glow effect', format: 'RGBY' },
        { id: 'outer', name: 'Outer Glow', description: 'Outer flash effect', format: 'RGBY' },
        { id: 'bubble', name: 'Bubble', description: 'Transparent bubble overlay', format: '42_48' },
        { id: 'sparkles', name: 'Sparkles', description: 'Sparkle particles around the shield', format: 'RGB' }
      ]
    },
    {
      // Audit 2026-07: the muzzle-FLASH model drawn on every blaster shot
      // (EfFxData Models_5, efSync 1166; shared Fox/Falco). NOT the beam or
      // the red muzzle ring -- those live elsewhere (laser extra / ptcl).
      // color1 = TEV KONST (bright streak burst), color2 = TEV0 (dim-area
      // tint, subtle). hue1-6 are NOT hues: they're FObj matanim trackType
      // bytes (KONST_R/G/B + TEV0_R/G/B) that animate the colors to
      // hardcoded vanilla values -- custom colors are invisible unless
      // they're zeroed (HSD_A_T_NONE), so every custom mod writes 00.
      // Mirrors backend/core/extra_types.py.
      id: 'laser_ring',
      name: 'Blaster Flash',
      description: 'Streak burst around the fighter when firing the blaster (beam + red ring are separate)',
      targetFile: 'EfFxData.dat',
      icon: 'laser_ring',
      shared: true,
      sharedWith: ['Falco'],
      owner: 'Fox',
      offsets: {
        color1: { start: 0x1D2FC, size: 3, format: 'RGB' },
        color2: { start: 0x1D300, size: 3, format: 'RGB' },
        hue1: { start: 0x1D974, size: 1, format: 'BYTE' },
        hue2: { start: 0x1D988, size: 1, format: 'BYTE' },
        hue3: { start: 0x1D99C, size: 1, format: 'BYTE' },
        hue4: { start: 0x1D9B0, size: 1, format: 'BYTE' },
        hue5: { start: 0x1D9C4, size: 1, format: 'BYTE' },
        hue6: { start: 0x1D9D8, size: 1, format: 'BYTE' }
      },
      vanilla: {
        color1: 'FF004C',
        color2: 'B20000',
        hue1: '0C',
        hue2: '0D',
        hue3: '0E',
        hue4: '10',
        hue5: '11',
        hue6: '12'
      },
      properties: [
        { id: 'color1', name: 'Streaks', description: 'Streak burst around the fighter when firing', format: 'RGB' },
        { id: 'color2', name: 'Dim Tint', description: 'Tint of the flash texture\'s dim areas (subtle in game)', format: 'RGB' }
      ]
    },
    {
      id: 'gun',
      name: 'Gun Model',
      description: 'Replace Fox\'s blaster gun model',
      targetFile: 'PlFx.dat',
      icon: 'gun',
      type: 'model',  // Model type - uses .dae file instead of hex patches
      modelPath: 'ftDataFox/Articles/Articles_1/Model_/RootModelJoint'
    },
    {
      // WIRE 2026-07-02 from research/docs-research/effect-maps/efcodata.md. Rapid-jab
      // (Attack100) FINISHER connect flash, shared out of EfCoData.dat --
      // scripts 11/15/91. MAP-LIVE verified via the `rapidjab` recipe with a
      // pinned bag: poking s11/s15/s91 red recolored the finisher connect
      // burst (pink-white/cyan -> red). owner Fox; sharedWith DATA-DERIVED via
      // backend/shared/rendering/hitbox_elements.py --attack100 (the fighters whose
      // action table carries the Attack100 motion state, minus Fox). Finite-
      // jab chars (Mario/Luigi/DK/Bowser/Ness) never reach Attack100 and are
      // correctly excluded. Mirrors backend/core/extra_types.py.
      id: 'jab_finisher_spark',
      name: 'Rapid Jab Finisher Spark',
      // HIDDEN from the extras menu by user request (2026-07-02). The mapping is
      // kept intact so any already-saved extra of this id still resolves, but
      // `hidden: true` removes it from the character menu (getExtraTypes filter).
      hidden: true,
      description: 'Connect flash of the rapid-jab (Attack100) FINISHER -- the pink-white/cyan spark burst that flashes when the infinite jab\'s finishing hit connects. Shared out of the common effects file, so it affects EVERY rapid-jab character\'s finisher: Fox, Falco, C. Falcon, Kirby, Link, Young Link, Mewtwo, Sheik, and G&W (Judgment). Characters with only a finite jab combo (no infinite rapid jab) never trigger it',
      targetFile: 'EfCoData.dat',
      icon: 'thunder',
      shared: true,
      // DATA-DERIVED via backend/shared/rendering/hitbox_elements.py --attack100
      // (Attack100 motion-state scan); roster minus owner Fox.
      sharedWith: ['C. Falcon', 'Falco', 'Kirby', 'Link', 'Mewtwo', 'Sheik', 'Young Link', 'G&W'],
      owner: 'Fox',
      offsets: {
        finisher_lead_c1: { format: 'RGB', offsets: [0x12AF] },
        finisher_burst_a_c2: { format: 'RGB', offsets: [0x148D] },
        finisher_burst_b_c2: { format: 'RGB', offsets: [0x14A1] },
        finisher_flash_c2: { format: 'RGB', offsets: [0x376F] }
      },
      vanilla: {
        color1: '0554FF',
        color2: '75DBEB',
        finisher_lead_c1: '0554FF',
        finisher_burst_a_c2: '57D0FF',
        finisher_burst_b_c2: '0509FF',
        finisher_flash_c2: '75DBEB'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Leading connect spark (s11)', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Electric burst body + cyan flash (s15/s91)', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07-10 from research/docs-research/effect-maps/common-shield.md.
      // The shield BUBBLE texture: one 128x128 IA8 image at EfCoData 0x104320
      // (MAP-LIVE verified: memset -> opaque white square, Animelee splice ->
      // anime rim ring). IA8 carries NO hue -- the per-port tint is applied
      // engine-side -- so this is a TEXTURE-REPLACEMENT extra, not a color
      // extra: no offsets/color properties; mods are imported files (a full
      // modded EfCoData.dat, or an image encoded to the grayscale texture)
      // handled by ShieldTextureEditorModal + backend texture_region.py.
      // Owner Fox (cast-wide precedent, jab_finisher_spark); sharedWith =
      // roster minus Fox minus YOSHI (his shield is the egg, not the bubble).
      // Mirrors backend/core/extra_types.py.
      id: 'common_shield',
      name: 'Shield',
      description: 'Shield bubble texture -- the shared grayscale sphere texture every character\'s shield bubble draws (the per-port red/blue/yellow/green tint is applied by the game engine and is not editable here). Yoshi is unaffected -- his shield is the egg, not the bubble',
      targetFile: 'EfCoData.dat',
      icon: 'effect',
      format: 'texture_region',
      type: 'texture_region',
      shared: true,
      sharedWith: ['Bowser', 'C. Falcon', 'DK', 'Dr. Mario', 'Falco', 'G&W', 'Ganondorf', 'Ice Climbers', 'Jigglypuff', 'Kirby', 'Link', 'Luigi', 'Mario', 'Marth', 'Mewtwo', 'Ness', 'Peach', 'Pichu', 'Pikachu', 'Roy', 'Samus', 'Sheik', 'Young Link', 'Zelda'],
      owner: 'Fox',
      textureRegion: {
        offset: 0x104320,
        size: 0x8000,
        width: 128,
        height: 128,
        gxFormat: 3   // IA8
      },
      vanilla: {},
      properties: []
    }
  ],
  Samus: [
    {
      // WIRE 2026-07 from research/docs-research/effect-maps/samus.md (MAP stage).
      // Screw Attack (up-B) electric arcs: four identical 07 07 07 04
      // model-region blocks, marker-verified against vanilla EfSsData.dat --
      // +4 = bright core (also drives the rising spiral spark ring), +8 =
      // glow halo. color1/color2 auto-fan to every _c1/_c2 offset key
      // (EffectEditorPage convention). Mirrors backend/core/extra_types.py.
      id: 'screw_attack',
      name: 'Screw Attack',
      description: 'Up-B spinning swirl and electric arc core and glow colors',
      targetFile: 'EfSsData.dat',
      icon: 'thunder',
      offsets: {
        arc_c1: { format: 'RGB', offsets: [0x11588, 0x11648, 0x11708, 0x117C8] },
        arc_c2: { format: 'RGB', offsets: [0x1158C, 0x1164C, 0x1170C, 0x117CC] },
        // Warm joint0 swirl, live verified at upb f12 (2026-09-09).
        // Independent RGB slots use the backend's model-owner layout guard.
        warm_swirl_c1: { start: 0x114C8, size: 3, format: 'RGB', model_tev_anchor: 0x114C4 },
        warm_swirl_c2: { start: 0x114CC, size: 3, format: 'RGB', model_tev_anchor: 0x114C4 }
      },
      vanilla: {
        color1: 'FFFFFF',
        color2: '0000FF',
        arc_c1: 'FFFFFF',
        arc_c2: '0000FF',
        warm_swirl_c1: 'FFFF8A',
        warm_swirl_c2: 'FF4C00'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Swirl and arc cores', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Swirl and arc outer glow', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07 from research/docs-research/effect-maps/samus.md. Missile
      // (side-B) contrail smoke + launch back-blast puff -- CF particle
      // records in EfSsData.dat, marker-verified against vanilla bytes
      // (CF marker -> color at marker+2 = c1, secondary at colorpos+7 = c2).
      // contrail = script 9 (PRIMCOL/ENVCOL #0 & #1); backblast = script 13
      // (PRIMCOL/ENVCOL #1 & #2, chained off marker 0x612). color1/color2
      // auto-fan to all four _c1/_c2 offset keys. Deliberately NOT wired:
      // the PlSs missile-body material A/B (spec flags it uncertain --
      // pending EYEBALL) and the cyan script-16 group (pending
      // punching-bag; no attributable element on a whiffed missile).
      // Mirrors backend/core/extra_types.py.
      id: 'missile',
      name: 'Missile',
      description: 'Side-B missile contrail smoke and launch back-blast colors',
      targetFile: 'EfSsData.dat',
      icon: 'punch',
      offsets: {
        contrail_c1: { format: 'RGB', offsets: [0x470, 0x47D] },
        contrail_c2: { format: 'RGB', offsets: [0x477, 0x484] },
        backblast_c1: { format: 'RGB', offsets: [0x61F, 0x62D] },
        backblast_c2: { format: 'RGB', offsets: [0x626, 0x634] }
      },
      vanilla: {
        color1: 'C27742',
        color2: '6E1B1D',
        contrail_c1: 'C27742',
        contrail_c2: '6E1B1D',
        backblast_c1: 'D3ABA1',
        backblast_c2: '51231F'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Contrail smoke and back-blast puff core', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Contrail and back-blast sustained tint', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07 from research/docs-research/effect-maps/samus.md. Neutral-B
      // charge: radiating spark-needle lines around the arm cannon (CF
      // record, script 5, PRIMCOL/ENVCOL #0). The FIRED charge-shot ball is
      // explicitly NOT wired here -- the spec's live-poke pass found every
      // color-record candidate left the ball vanilla; it is a texture
      // effect (flagged for a future texture pass). Mirrors
      // backend/core/extra_types.py.
      id: 'charge_shot',
      name: 'Charge Shot',
      description: 'Neutral-B charging spark needle colors',
      targetFile: 'EfSsData.dat',
      icon: 'shadowball',
      offsets: {
        needles_c1: { start: 0x2E9, size: 3, format: 'RGB' },
        needles_c2: { start: 0x2F0, size: 3, format: 'RGB' }
      },
      vanilla: {
        color1: 'FFFFFF',
        color2: '090087',
        needles_c1: 'FFFFFF',
        needles_c2: '090087'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Radiating charge spark-needle lines', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Needle secondary tint', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07 from research/docs-research/effect-maps/samus.md (charge_ball
      // section, IN-GAME VERIFIED). The FIRED charge-shot ball (blue outer
      // glow / pink inner ring / white core) is a single RGB5A3 texture
      // embedded in an effect/particle texture-graphics block in PlSs.dat --
      // NOT on a JOBJ->DObj->MObj material tree, so it's unreachable by the
      // CLI `type: 'texture'` export/import path (textures.py). First
      // consumer of the `format: 'texture_recolor'` format: a plain single
      // ColorPicker whose apply rotates every texel's hue by
      // (target_hue - vanillaDominantHue), preserving each texel's S/V/alpha
      // (HSV) so the blue/pink/white gradient survives -- never a flat fill.
      // Ground truth: the verified plss_ball_probe prototype (its codecs are
      // backend/shared/rendering/gx_texels.py) + tests/artifacts/samus-ball-texture/. The I4 shape map
      // at 0x36040 is a separate grayscale texture, untouched by this layer.
      // Mirrors backend/core/extra_types.py.
      id: 'charge_ball',
      partOf: 'charge_shot',  // edited inside the charge_shot unit's page (getUnitParts)
      name: 'Charge Ball',
      description: 'Fired charge-shot projectile ball color',
      targetFile: 'PlSs.dat',
      icon: 'shadowball',
      format: 'texture_recolor',
      texture: { offset: 0x36840, width: 64, height: 64, gxFormat: 5 }, // RGB5A3
      vanillaDominantHue: 239,
      vanilla: {
        color1: '0004FF' // representative vanilla swatch (hue 239 at full S/V)
      },
      properties: [
        { id: 'color1', name: 'Ball Color', description: 'Fired charge-shot ball color (blue glow / pink ring / white core, recolored together)', format: 'RGB' }
      ]
    }
  ],
  Luigi: [
    {
      // WIRE 2026-07 from research/docs-research/effect-maps/luigi.md (MAP-LIVE
      // verified). Neutral-B fireball body/aura -- lives in the PlLg.dat
      // ARTICLE, not EfLgData (confirmed by live-poking these 3 offsets
      // magenta: fireball body/core aura turned magenta, smoke trail
      // unaffected). fb_aura_42's PrimCol @0xF42C (00FF00) is the dominant
      // green -- the EYEBALL-flagged lead/primary per the spec's suggested
      // grouping. All three offsets are one visual (aura+body recolor
      // together) so color1 fans to all three; no secondary layer exists in
      // this file (that's the split-out luigi_fireball_smoke extra in
      // EfLgData.dat -- config schema is one targetFile per extra). Split
      // from the spec's single "Proposed extra 1" table across its two
      // target files, same pattern as Samus screw_attack/missile/
      // charge_shot each getting one target file. Mirrors backend/core/extra_types.py.
      id: 'luigi_fireball',
      name: 'Fireball',
      description: 'Neutral-B fireball body and aura color',
      targetFile: 'PlLg.dat',
      icon: 'fireball',
      offsets: {
        fb_aura_42_c1: { format: 'RGB', offsets: [0xF42C] },
        fb_aura_07_c1: { format: 'RGB', offsets: [0xF3BC] },
        fb_body_42_c1: { format: 'RGB', offsets: [0xF4CC] }
      },
      vanilla: {
        color1: '00FF00',
        fb_aura_42_c1: '00FF00',
        fb_aura_07_c1: 'FF6600',
        fb_body_42_c1: 'FFFFFF'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Fireball body/aura core color', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07 from research/docs-research/effect-maps/luigi.md. Neutral-B
      // fireball hand-spawn smoke puffs + the oval hand ring/portal --
      // EfLgData.dat CF particle records + one 42_48/07 hand-ring
      // model-block pair. Live-poke verified: hand-spawn smoke puff turned
      // magenta (script 1 = dominant, NOT the "weak grey/olive" STATIC
      // guess); hand ring/portal turned magenta at fireball spawn. The
      // *traveling* fireball trail stayed green under every poke here --
      // that trail is common-bank (EfCoData), quarantined, not wired. c1 =
      // smoke primaries + ring, c2 = smoke secondaries (CF colorpos+7,
      // dominates sustained puff tint). Mirrors backend/core/extra_types.py.
      id: 'luigi_fireball_smoke',
      partOf: 'luigi_fireball',  // edited inside the luigi_fireball unit's page (getUnitParts)
      name: 'Fireball Smoke & Hand Ring',
      description: 'Neutral-B fireball hand-spawn smoke and hand ring colors',
      targetFile: 'EfLgData.dat',
      icon: 'fireball',
      offsets: {
        fb_smoke_s1_c1: { format: 'RGB', offsets: [0x186, 0x194, 0x1A7, 0x1B4] },
        fb_smoke_s1_c2: { format: 'RGB', offsets: [0x18D, 0x19B, 0x1AE, 0x1BB] },
        fb_smoke_s0a_c1: { format: 'RGB', offsets: [0xFF] },
        fb_smoke_s0a_c2: { format: 'RGB', offsets: [0x106] },
        fb_smoke_s0b_c1: { format: 'RGB', offsets: [0x10C] },
        fb_smoke_s0b_c2: { format: 'RGB', offsets: [0x113] },
        fb_smoke_s3_c1: { format: 'RGB', offsets: [0x26D] },
        fb_smoke_s3_c2: { format: 'RGB', offsets: [0x281] },
        fb_smoke_s4_c1: { format: 'RGB', offsets: [0x2DD] },
        fb_smoke_s4_c2: { format: 'RGB', offsets: [0x2F1] },
        fb_dust_s5_c1: { format: 'RGB', offsets: [0x352] },
        fb_dust_s5_c2: { format: 'RGB', offsets: [0x372] },
        fb_particle_s6_c1: { format: 'RGB', offsets: [0x3FE] },
        fb_particle_s6_c2: { format: 'RGB', offsets: [0x40E] },
        hand_ring_42_c1: { format: 'RGB', offsets: [0x11260] },
        hand_ring_42_c2: { format: 'RGB', offsets: [0x11264] },
        hand_ring_07_c1: { format: 'RGB', offsets: [0x111F0] },
        hand_ring_07_c2: { format: 'RGB', offsets: [0x111F4] }
      },
      vanilla: {
        color1: '93A394',
        color2: '22AB0A',
        fb_smoke_s1_c1: '93A394',
        fb_smoke_s1_c2: '22AB0A',
        fb_smoke_s0a_c1: '26FF43',
        fb_smoke_s0a_c2: '2ABA4E',
        fb_smoke_s0b_c1: '149C2D',
        fb_smoke_s0b_c2: '0C5419',
        fb_smoke_s3_c1: '02FD02',
        fb_smoke_s3_c2: '052E15',
        fb_smoke_s4_c1: '16FD22',
        fb_smoke_s4_c2: '0A4F12',
        fb_dust_s5_c1: 'BDFDBB',
        fb_dust_s5_c2: '31F83B',
        fb_particle_s6_c1: '1ADC24',
        fb_particle_s6_c2: '7CFF70',
        hand_ring_42_c1: '66FF99',
        hand_ring_42_c2: 'FFFFFF',
        hand_ring_07_c1: 'CCFFE5',
        hand_ring_07_c2: '19B200'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Hand-spawn smoke puff and hand ring core color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Smoke sustained tint and hand ring glow', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07 from research/docs-research/effect-maps/luigi.md. Down-B
      // tornado (Luigi Cyclone): 5 070707 model-region swirl blocks + 5
      // 42_48 finish/dissipation-ring blocks in EfLgData.dat, all
      // pale-yellow/white -> single color1/color2 editor pair. Live-poke
      // verified magenta on both the swirl (07-blocks) and the
      // trailing/ground finish ring (42_48 blocks). 07-block note (spec):
      // col2 sits at col1+4 (marker+8), separator 00 at marker+7; since
      // col1 != col2 per block, each is a direct RGB slot (falcon_kick
      // technique) rather than the shared single-color '070707' format.
      // Mirrors backend/core/extra_types.py.
      id: 'luigi_cyclone',
      name: 'Luigi Cyclone',
      description: 'Down-B tornado swirl and finish ring colors',
      targetFile: 'EfLgData.dat',
      icon: 'thunder',
      offsets: {
        torn_outer_c1: { start: 0x11A80, size: 3, format: 'RGB' },
        torn_outer_c2: { start: 0x11A84, size: 3, format: 'RGB' },
        torn_upper_c1: { start: 0x11B4C, size: 3, format: 'RGB' },
        torn_upper_c2: { start: 0x11B50, size: 3, format: 'RGB' },
        torn_inner1_c1: { start: 0x11C18, size: 3, format: 'RGB' },
        torn_inner1_c2: { start: 0x11C1C, size: 3, format: 'RGB' },
        torn_inner2_c1: { start: 0x11CE4, size: 3, format: 'RGB' },
        torn_inner2_c2: { start: 0x11CE8, size: 3, format: 'RGB' },
        torn_under_c1: { start: 0x11DB0, size: 3, format: 'RGB' },
        torn_under_c2: { start: 0x11DB4, size: 3, format: 'RGB' },
        torn_outer_fin_c1: { format: 'RGB', offsets: [0x11AF0] },
        torn_outer_fin_c2: { format: 'RGB', offsets: [0x11AF4] },
        torn_fin_c1: { format: 'RGB', offsets: [0x11BBC] },
        torn_fin_c2: { format: 'RGB', offsets: [0x11BC0] },
        torn_fin_s1_c1: { format: 'RGB', offsets: [0x11C88] },
        torn_fin_s1_c2: { format: 'RGB', offsets: [0x11C8C] },
        torn_fin_s2_c1: { format: 'RGB', offsets: [0x11D54] },
        torn_fin_s2_c2: { format: 'RGB', offsets: [0x11D58] },
        torn_below_c1: { format: 'RGB', offsets: [0x11E20] },
        torn_below_c2: { format: 'RGB', offsets: [0x11E24] }
      },
      vanilla: {
        color1: 'FFFFB2',
        color2: 'FFB200',
        torn_outer_c1: 'FFFFB2',
        torn_outer_c2: 'FFB200',
        torn_upper_c1: 'FFFFB2',
        torn_upper_c2: 'FFCC00',
        torn_inner1_c1: 'FFFFE5',
        torn_inner1_c2: 'FFFF00',
        torn_inner2_c1: 'FFFFCC',
        torn_inner2_c2: 'FFFF00',
        torn_under_c1: 'FFFFCC',
        torn_under_c2: 'FFB200',
        torn_outer_fin_c1: 'FFFFD0',
        torn_outer_fin_c2: 'FFFFFF',
        torn_fin_c1: 'FFFFD0',
        torn_fin_c2: 'FFFFFF',
        torn_fin_s1_c1: 'FFFFD0',
        torn_fin_s1_c2: 'FFFFFF',
        torn_fin_s2_c1: 'FFFFD0',
        torn_fin_s2_c2: 'FFFFFF',
        torn_below_c1: 'FFFFE3',
        torn_below_c2: 'FFFFFF'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Tornado swirl and finish ring core color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Tornado glow and finish ring highlight', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07-02 from research/docs-research/effect-maps/luigi.md "Proposed
      // extra 3" -- ON-HIT ONLY, verified via the punching-bag harness
      // (spark_blue_s11, EfLgData.dat script 11). Poking prim 0x60A / env
      // 0x611 RED turned the small inner jagged burst of Luigi's melee-hit
      // contact flash red on both fair and nair against a DK bag (contact
      // frames, pixel-diff confirmed). The surrounding white/yellow rays +
      // glow are common-bank and stay unchanged -- s11 colors ONLY the
      // inner burst. CF-multi format (prim=core @marker, env=glow
      // @marker+7); count/aux record @0x617 is the interp-frame-count byte
      // (cnt=4), not a color operand -- left unwritten. Single conceptual
      // color: prim=core, env=glow -> color1/color2. Mirrors
      // backend/core/extra_types.py.
      id: 'luigi_hitspark',
      name: 'Impact Spark',
      description: 'On-hit melee contact flash inner burst color',
      targetFile: 'EfLgData.dat',
      icon: 'spark',
      offsets: {
        hitspark_s11_c1: { format: 'RGB', offsets: [0x60A] },
        hitspark_s11_c2: { format: 'RGB', offsets: [0x611] }
      },
      vanilla: {
        color1: 'B5F6FF',
        color2: '0C17D7',
        hitspark_s11_c1: 'B5F6FF',
        hitspark_s11_c2: '0C17D7'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Contact-flash inner burst core color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Contact-flash inner burst glow color', format: 'RGB' }
      ]
    }
  ],
  Mario: [
    {
      // WIRE 2026-07 from research/docs-research/effect-maps/mario.md (MAP-LIVE
      // verified 2026-07-02). Mario only -- Doc throws vitamin pills, never
      // spawns gfx_id 1146, so this extra is intentionally NOT shared.
      // Neutral-B fireball: five CF particle groups in EfMrData.dat (hand
      // smoke at spawn, trailing fire plume, ball particles around the orb,
      // landing/expiry dust, square particles at the endpoint) plus the hand
      // circle 07/42 ring that flashes around Mario's hand at spawn (kept
      // here, NOT in mario_tornado, since Doc has no fireball to show it).
      // c1 = PrimCol record primaries, c2 = EnvCol secondaries at colorpos+7
      // (dominates sustained puff tint). Each CF record's vanilla bytes
      // differ (byte-verified), so every record is its own key -- the
      // color1/color2 pickers still fan out to ALL of them. Mirrors
      // backend/core/extra_types.py.
      id: 'mario_fireball',
      name: 'Fireball',
      description: 'Neutral-B fireball smoke, trail, particle, and hand-ring colors',
      targetFile: 'EfMrData.dat',
      icon: 'fireball',
      offsets: {
        hand_smoke_a_c1: { format: 'RGB', offsets: [0x162] },
        hand_smoke_a_c2: { format: 'RGB', offsets: [0x169] },
        hand_smoke_b_c1: { format: 'RGB', offsets: [0x177] },
        hand_smoke_b_c2: { format: 'RGB', offsets: [0x17E] },
        hand_smoke_c_c1: { format: 'RGB', offsets: [0x184] },
        hand_smoke_c_c2: { format: 'RGB', offsets: [0x18B] },
        trailing_fire_a_c1: { format: 'RGB', offsets: [0x20C] },
        trailing_fire_a_c2: { format: 'RGB', offsets: [0x213] },
        trailing_fire_b_c1: { format: 'RGB', offsets: [0x21F] },
        trailing_fire_b_c2: { format: 'RGB', offsets: [0x226] },
        trailing_fire_c_c1: { format: 'RGB', offsets: [0x22C] },
        trailing_fire_c_c2: { format: 'RGB', offsets: [0x233] },
        ball_particles_a_c1: { format: 'RGB', offsets: [0x2E5] },
        ball_particles_a_c2: { format: 'RGB', offsets: [0x2EC] },
        ball_particles_b_c1: { format: 'RGB', offsets: [0x2F2] },
        ball_particles_b_c2: { format: 'RGB', offsets: [0x2F9] },
        ball_particles_c_c1: { format: 'RGB', offsets: [0x355] },
        ball_particles_c_c2: { format: 'RGB', offsets: [0x35C] },
        ball_particles_d_c1: { format: 'RGB', offsets: [0x362] },
        ball_particles_d_c2: { format: 'RGB', offsets: [0x369] },
        landing_dust_a_c1: { format: 'RGB', offsets: [0x3CA] },
        landing_dust_a_c2: { format: 'RGB', offsets: [0x3D1] },
        landing_dust_b_c1: { format: 'RGB', offsets: [0x3DD] },
        landing_dust_b_c2: { format: 'RGB', offsets: [0x3E4] },
        landing_dust_c_c1: { format: 'RGB', offsets: [0x3EA] },
        landing_dust_c_c2: { format: 'RGB', offsets: [0x3F1] },
        square_particles_a_c1: { format: 'RGB', offsets: [0x476] },
        square_particles_a_c2: { format: 'RGB', offsets: [0x47D] },
        square_particles_b_c1: { format: 'RGB', offsets: [0x486] },
        square_particles_b_c2: { format: 'RGB', offsets: [0x48D] },
        hand_ring_07_c1: { format: 'RGB', offsets: [0x11AF8] },
        hand_ring_07_c2: { format: 'RGB', offsets: [0x11AFC] },
        hand_ring_42_c1: { format: 'RGB', offsets: [0x11B68] }
      },
      vanilla: {
        color1: 'FFA217',
        color2: 'D43B08',
        hand_smoke_a_c1: 'FFFFFF',
        hand_smoke_a_c2: 'FFCC4A',
        hand_smoke_b_c1: 'FFA217',
        hand_smoke_b_c2: 'BA120D',
        hand_smoke_c_c1: '9C060B',
        hand_smoke_c_c2: '540405',
        trailing_fire_a_c1: 'C7BB0D',
        trailing_fire_a_c2: 'D43B08',
        trailing_fire_b_c1: 'FFA800',
        trailing_fire_b_c2: 'FF5900',
        trailing_fire_c_c1: 'FF070F',
        trailing_fire_c_c2: '510A00',
        ball_particles_a_c1: 'FDEB74',
        ball_particles_a_c2: 'E33C09',
        ball_particles_b_c1: 'B90303',
        ball_particles_b_c2: '610101',
        ball_particles_c_c1: 'FDE467',
        ball_particles_c_c2: 'D42304',
        ball_particles_d_c1: '7D4202',
        ball_particles_d_c2: '2E0000',
        landing_dust_a_c1: 'FEFCE2',
        landing_dust_a_c2: 'FFF75C',
        landing_dust_b_c1: 'FCE669',
        landing_dust_b_c2: 'D60B0E',
        landing_dust_c_c1: 'F9AC06',
        landing_dust_c_c2: '6B0507',
        square_particles_a_c1: 'FF290C',
        square_particles_a_c2: 'FFFF82',
        square_particles_b_c1: 'FFFF6E',
        square_particles_b_c2: 'FF0C14',
        hand_ring_07_c1: 'FFFFB2',
        hand_ring_07_c2: 'FF6600',
        hand_ring_42_c1: 'FFFF99'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Fireball smoke/trail/particle core color and hand ring', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Fireball sustained tint / glow', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07 from research/docs-research/effect-maps/mario.md. Fireball
      // AURA/glow halo material -- lives in PlMr.dat (player-file, not
      // EfMrData), so it's a separate targetFile per the Luigi
      // screw_attack/missile/charge_shot precedent (one targetFile per
      // extra). Live-poke: cyan turned the soft round glow surrounding the
      // fireball orb cyan and contributed to the body glow; the fireball's
      // white core orb itself is a separate texture, untouched. Ship 42
      // DIFFUSE (+4) only -- ambient (+0) is a verified no-op (Fox/Falco
      // precedent). Mirrors backend/core/extra_types.py.
      id: 'mario_fireball_aura',
      partOf: 'mario_fireball',  // edited inside the mario_fireball unit's page (getUnitParts)
      name: 'Fireball Aura',
      description: 'Fireball glow halo and body material color',
      targetFile: 'PlMr.dat',
      icon: 'fireball',
      offsets: {
        aura_07_c1: { format: 'RGB', offsets: [0xFA44] },
        aura_07_c2: { format: 'RGB', offsets: [0xFA48] },
        aura_42_c1: { format: 'RGB', offsets: [0xFAB4] },
        body_42_c1: { format: 'RGB', offsets: [0xFB54] }
      },
      vanilla: {
        color1: 'FF6600',
        color2: 'FF3300',
        aura_07_c1: 'FF6600',
        aura_07_c2: 'FF3300',
        aura_42_c1: 'FF4C00',
        body_42_c1: 'FFFFFF'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Aura glow halo core and body material color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Aura glow halo outer tint', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07 from research/docs-research/effect-maps/mario.md. Side-B cape
      // swing sparkle stars -- EfMrData.dat CF particle records. SHARED with
      // Dr. Mario (same file, same fighter moveset -- cape/tornado/up-B run
      // for both), following the Fox/Falco shared-file precedent (owner +
      // shared/sharedWith, mods stored under the owner). Live-poke: red on
      // all four records shifted the swing sparkle stars (subtle -- vanilla
      // sparkles are inherently multi-hue so the shift reads faint; flagged
      // for EYEBALL). The 0x567 record is a black/alpha-mask PrimCol base
      // with no envcol pair, but an isolated green poke produced a visible
      // cyan/teal trailing sparkle -- confirmed live, not dead. Cape CLOTH
      // color is a separate per-character extra (mario_cape / doc_cape
      // below) since it lives in each character's own player file. Mirrors
      // backend/core/extra_types.py.
      id: 'cape_sparkles',
      name: 'Cape Sparkles',
      description: 'Side-B cape swing sparkle star colors',
      targetFile: 'EfMrData.dat',
      icon: 'sideb',
      shared: true,
      sharedWith: ['Dr. Mario'],
      owner: 'Mario',
      offsets: {
        sparkle_a_c1: { format: 'RGB', offsets: [0x4E0] },
        sparkle_a_c2: { format: 'RGB', offsets: [0x4E7] },
        sparkle_b_c1: { format: 'RGB', offsets: [0x4ED] },
        sparkle_c_c1: { format: 'RGB', offsets: [0x505] },
        sparkle_trail_c1: { format: 'RGB', offsets: [0x569] }
      },
      vanilla: {
        color1: '6BFDFF',
        color2: '1105FF',
        sparkle_a_c1: '6BFDFF',
        sparkle_a_c2: '1105FF',
        sparkle_b_c1: 'D1A3FF',
        sparkle_c_c1: 'BF09A1',
        sparkle_trail_c1: '000000'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Cape sparkle star colors (subtle -- vanilla is multi-hue)', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Sparkle secondary tint', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07 from research/docs-research/effect-maps/mario.md. Mario cape
      // CLOTH color -- PlMr.dat 42_48 material, marker @0x14EBC. Live-poke:
      // green turned the cape cloth bright green, STRONG and clean (the ship
      // headline for the cape group). Separate targetFile from
      // cape_sparkles (Luigi cloth/smoke precedent). Mirrors
      // backend/core/extra_types.py.
      id: 'mario_cape',
      name: 'Cape Cloth',
      description: 'Side-B cape cloth color',
      targetFile: 'PlMr.dat',
      icon: 'sideb',
      offsets: {
        cloth_c1: { format: 'RGB', offsets: [0x14EAC] },
        cloth_c2: { format: 'RGB', offsets: [0x14EB0] }
      },
      vanilla: {
        color1: 'FFFFFF',
        color2: 'FFFFFF',
        cloth_c1: 'FFFFFF',
        cloth_c2: 'FFFFFF'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Cape cloth color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Cape cloth secondary/shading color', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07 from research/docs-research/effect-maps/mario.md. Down-B
      // tornado (both chars): 5 identical 07 07 07 04 swirl blocks + 5
      // 42_48 ground-ripple/spin-haze blocks in EfMrData.dat -- shared per
      // the Fox/Falco precedent (owner Mario, sharedWith Dr. Mario).
      // Live-poke: red on all 5 07-blocks turned the whole tornado vortex +
      // spin arcs + ground ripple full red, identical on Doc. 42 diffuse(+4)
      // turned the ground ripple/spin haze green in the split test;
      // ambient(+0) was a confirmed no-op -- ship diffuse only. The fireball
      // hand-circle 07/42 pair is spatially adjacent but semantically the
      // fireball's hand ring (Mario-only) -- kept in mario_fireball instead.
      // Mirrors backend/core/extra_types.py.
      id: 'mario_tornado',
      name: 'Tornado',
      description: 'Down-B tornado swirl and ground haze colors',
      targetFile: 'EfMrData.dat',
      icon: 'thunder',
      shared: true,
      sharedWith: ['Dr. Mario'],
      owner: 'Mario',
      offsets: {
        outer_swirl1_c1: { format: 'RGB', offsets: [0x12380] },
        outer_swirl1_c2: { format: 'RGB', offsets: [0x12384] },
        outer_swirl2_c1: { format: 'RGB', offsets: [0x1244C] },
        outer_swirl2_c2: { format: 'RGB', offsets: [0x12450] },
        inner_side1_c1: { format: 'RGB', offsets: [0x12518] },
        inner_side1_c2: { format: 'RGB', offsets: [0x1251C] },
        inner_side2_c1: { format: 'RGB', offsets: [0x125E4] },
        inner_side2_c2: { format: 'RGB', offsets: [0x125E8] },
        underneath_c1: { format: 'RGB', offsets: [0x126B0] },
        underneath_c2: { format: 'RGB', offsets: [0x126B4] },
        ground_ripple1_42_c1: { format: 'RGB', offsets: [0x123F0] },
        ground_ripple2_42_c1: { format: 'RGB', offsets: [0x124BC] },
        spin_haze1_42_c1: { format: 'RGB', offsets: [0x12588] },
        spin_haze2_42_c1: { format: 'RGB', offsets: [0x12654] },
        ground_haze_42_c1: { format: 'RGB', offsets: [0x12720] }
      },
      vanilla: {
        color1: 'B2FFFF',
        color2: '0000FF',
        outer_swirl1_c1: 'B2FFFF',
        outer_swirl1_c2: '0000FF',
        outer_swirl2_c1: 'B2FFFF',
        outer_swirl2_c2: '0000FF',
        inner_side1_c1: '99CCFF',
        inner_side1_c2: '0000FF',
        inner_side2_c1: '99CCFF',
        inner_side2_c2: '0000FF',
        underneath_c1: 'CCFFFF',
        underneath_c2: '0033FF',
        ground_ripple1_42_c1: 'FFFFD0',
        ground_ripple2_42_c1: 'FFFFD0',
        spin_haze1_42_c1: 'FFFFD0',
        spin_haze2_42_c1: 'FFFFD0',
        ground_haze_42_c1: 'FFFFE3'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Tornado vortex core and ground haze color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Tornado glow halo', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07-02 from research/docs-research/effect-maps/items.md (items
      // pass). The up-B "coin" ring is NOT a color record -- mario.md's
      // upb_coin CF records (EfMrData 0x62C-0x70F) tested DEAD under the
      // punching bag. This pass located the REAL coin sprite: a plain
      // texture in Mario's own tex bank, EfMrData.dat texGraphicBank group
      // 0 -- 8x CI8 64x64 images (spin poses) each with its own 256-entry
      // RGB5A3 palette (offsets from shared/rendering/ptcl_texbank.py --groups 0
      // --json, byte-verified 2026-07-02). vanillaDominantHue 47.6 (gold),
      // same shape as the common_fire/common_flash CI8-palette
      // texture_recolor consumers. SHARED with Dr. Mario (EfMrData.dat is
      // the shared Mario/Doc effect table) -- owner/sharedWith pattern
      // (mario_tornado/cape_sparkles precedent), mods stored once under
      // Mario. Mirrors backend/core/extra_types.py.
      id: 'mario_coins',
      name: 'Coin Color',
      description: 'Up-B coin sprite color -- affects the shared effects file, also recolors Dr. Mario\'s up-B coins',
      targetFile: 'EfMrData.dat',
      icon: 'upb',
      format: 'texture_recolor',
      shared: true,
      sharedWith: ['Dr. Mario'],
      owner: 'Mario',
      texture: {
        gxFormat: 9, // CI8
        width: 64,
        height: 64,
        images: [
          { offset: '0x7A0', palette: '0x87A0' },
          { offset: '0x17A0', palette: '0x89A0' },
          { offset: '0x27A0', palette: '0x8BA0' },
          { offset: '0x37A0', palette: '0x8DA0' },
          { offset: '0x47A0', palette: '0x8FA0' },
          { offset: '0x57A0', palette: '0x91A0' },
          { offset: '0x67A0', palette: '0x93A0' },
          { offset: '0x77A0', palette: '0x95A0' }
        ],
        paletteFormat: 2 // RGB5A3
      },
      vanillaDominantHue: 47.6,
      vanilla: {
        color1: 'FFCA00' // representative vanilla swatch (hue 47.6 at full S/V, gold)
      },
      properties: [
        { id: 'color1', name: 'Coin Color', description: 'Up-B coin sprite color (spin poses; shared with Dr. Mario)', format: 'RGB' }
      ]
    }
  ],
  'Dr. Mario': [
    {
      // WIRE 2026-07 from research/docs-research/effect-maps/mario.md. Doc cape
      // CLOTH color -- his OWN PlDr.dat, different offset than Mario's PlMr
      // (Doc-owned extra, not shared -- only the sparkles above are shared).
      // Marker @0x19CBC (the old reference cite 0x19CA0 was off by 0xC / 12
      // bytes). Live-poke + ref mod 13332 (Blue Cape Dr. Mario, byte-diff
      // clean at 0x19CAC-0x19CB2) both confirm: green turned the cape bright
      // green, STRONG and clean -- the strongest ship candidate in the whole
      // spec. Mirrors backend/core/extra_types.py.
      id: 'doc_cape',
      name: 'Cape Cloth',
      description: 'Side-B cape cloth color',
      targetFile: 'PlDr.dat',
      icon: 'sideb',
      offsets: {
        cloth_c1: { format: 'RGB', offsets: [0x19CAC] },
        cloth_c2: { format: 'RGB', offsets: [0x19CB0] }
      },
      vanilla: {
        color1: 'FFFFFF',
        color2: 'FFFFFF',
        cloth_c1: 'FFFFFF',
        cloth_c2: 'FFFFFF'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Cape cloth color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Cape cloth secondary/shading color', format: 'RGB' }
      ]
    }
  ],
  Ness: [
    {
      // WIRE 2026-07-02 from research/docs-research/effect-maps/ness.md (MAP-LIVE
      // verified). Down-B PSI Magnet absorb aura -- EfNsData.Models[2], 7
      // 070707 model-region blocks. Per-record vanilla bytes DIFFER
      // (psimag_a's c1 is 00CCFF not white) -- kept as per-record keys.
      // Mirrors backend/core/extra_types.py.
      id: 'ness_psi_magnet',
      name: 'PSI Magnet',
      description: 'Down-B PSI Magnet absorb aura core and glow colors',
      targetFile: 'EfNsData.dat',
      icon: 'downb',
      offsets: {
        psimag_a_c1: { format: 'RGB', offsets: [0x163B8] },
        psimag_a_c2: { format: 'RGB', offsets: [0x163BC] },
        psimag_b_c1: { format: 'RGB', offsets: [0x16478] },
        psimag_b_c2: { format: 'RGB', offsets: [0x1647C] },
        psimag_c_c1: { format: 'RGB', offsets: [0x16538] },
        psimag_c_c2: { format: 'RGB', offsets: [0x1653C] },
        psimag_d_c1: { format: 'RGB', offsets: [0x165F8] },
        psimag_d_c2: { format: 'RGB', offsets: [0x165FC] },
        psimag_e_c1: { format: 'RGB', offsets: [0x166B8] },
        psimag_e_c2: { format: 'RGB', offsets: [0x166BC] },
        psimag_f_c1: { format: 'RGB', offsets: [0x16778] },
        psimag_f_c2: { format: 'RGB', offsets: [0x1677C] },
        psimag_g_c1: { format: 'RGB', offsets: [0x16838] },
        psimag_g_c2: { format: 'RGB', offsets: [0x1683C] }
      },
      vanilla: {
        color1: 'FFFFFF',
        color2: '0000FF',
        psimag_a_c1: '00CCFF',
        psimag_a_c2: '0000FF',
        psimag_b_c1: 'FFFFFF',
        psimag_b_c2: '0000FF',
        psimag_c_c1: 'FFFFFF',
        psimag_c_c2: '007FFF',
        psimag_d_c1: 'FFFFFF',
        psimag_d_c2: '007FFF',
        psimag_e_c1: 'FFFFFF',
        psimag_e_c2: '0066FF',
        psimag_f_c1: 'FFFFFF',
        psimag_f_c2: '007FFF',
        psimag_g_c1: 'FFFFFF',
        psimag_g_c2: '007FFF'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Absorb aura bright core color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Absorb aura electric-blue arc glow color', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07-02 from research/docs-research/effect-maps/ness.md. PK Thunder
      // ball flare + tail/bolt -- PlNs.dat article model, NOT EfNsData.
      // CRITICAL FIX: the spec's 0x2D82E poke for "lightning4" landed on
      // non-color bytes -- re-derived from the record's own 07 07 07 04
      // marker (@0x2D828): c1 = marker+4 = 0x2D82C, c2 = marker+8 = 0x2D830.
      // Byte-verified against storage/test-base/files/PlNs.dat 2026-07-02.
      // Mirrors backend/core/extra_types.py.
      id: 'ness_pk_thunder',
      name: 'PK Thunder',
      description: 'Up-B PK Thunder ball flare and tail/bolt colors',
      targetFile: 'PlNs.dat',
      icon: 'upb',
      offsets: {
        tip_c1: { format: 'RGB', offsets: [0x2403C] },
        tail1_c1: { format: 'RGB', offsets: [0x2C3FC] },
        tail2_c1: { format: 'RGB', offsets: [0x2C77C] },
        tail_main_c1: { format: 'RGB', offsets: [0x2CAFC] },
        ball_flare1_c2: { format: 'RGB', offsets: [0x2D3D0] },
        ball_flare2_c2: { format: 'RGB', offsets: [0x2D530] },
        lightning1_c1: { format: 'RGB', offsets: [0x2D5F0] },
        lightning2_c1: { format: 'RGB', offsets: [0x2D6B0] },
        lightning3_c1: { format: 'RGB', offsets: [0x2D770] },
        lightning4_c1: { format: 'RGB', offsets: [0x2D830] }
      },
      vanilla: {
        color1: '004CFF',
        color2: '0000FF',
        tip_c1: '004CFF',
        tail1_c1: '004CFF',
        tail2_c1: '004CFF',
        tail_main_c1: '004CFF',
        ball_flare1_c2: '0000FF',
        ball_flare2_c2: '0000FF',
        lightning1_c1: '0033FF',
        lightning2_c1: '0033FF',
        lightning3_c1: '0033FF',
        lightning4_c1: '0066FF'
      },
      properties: [
        { id: 'color1', name: 'Tail/Bolt', description: 'Tail, lightning, and tip color', format: 'RGB' },
        { id: 'color2', name: 'Ball Flare', description: 'Ball flare and aura color', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07-02 from research/docs-research/effect-maps/items.md (items-pass
      // MAP, bag-verified 2026-07-02). PK Fire burn PILLAR -- the article
      // that spawns when the PK Fire bolt connects; its animated model +
      // 070707 color blocks live in PlNs.dat (the player file), NOT
      // EfNsData. Three 07 07 07 04 markers: bottom ring INSIDE (0x11A8C),
      // MAIN fire aura (0x11B58), bottom ring OUTSIDE (0x11DF8); c1 =
      // marker+4 core, c2 = marker+8 glow. LIVE (punching-bag, DK dx=10):
      // poking all 6 green/magenta turned the vanilla BLUE ring GREEN with
      // MAGENTA glow edges/sparks. The orange fire body itself did NOT
      // recolor (texture, not this extra). Per-record vanilla bytes differ
      // (aura c1 FFFFE5 cream vs rings' c1 FFFFFF) -- kept as per-record
      // keys. Byte-verified against storage/test-base/files/PlNs.dat
      // 2026-07-02. On-hit only (demonstrable every time via the bag).
      // Mirrors backend/core/extra_types.py.
      id: 'ness_pk_fire',
      name: 'PK Fire',
      description: 'Side-B PK Fire pillar\'s hit-ring and aura accent colors (the orange fire body itself is texture)',
      targetFile: 'PlNs.dat',
      icon: 'sideb',
      offsets: {
        pillar_ring_in_c1: { format: 'RGB', offsets: [0x11A90] },
        pillar_ring_in_c2: { format: 'RGB', offsets: [0x11A94] },
        pillar_aura_c1: { format: 'RGB', offsets: [0x11B5C] },
        pillar_aura_c2: { format: 'RGB', offsets: [0x11B60] },
        pillar_ring_out_c1: { format: 'RGB', offsets: [0x11DFC] },
        pillar_ring_out_c2: { format: 'RGB', offsets: [0x11E00] }
      },
      vanilla: {
        color1: 'FFFFFF',
        color2: '007FFF',
        pillar_ring_in_c1: 'FFFFFF',
        pillar_ring_in_c2: '007FFF',
        pillar_aura_c1: 'FFFFE5',
        pillar_aura_c2: 'FF9900',
        pillar_ring_out_c1: 'FFFFFF',
        pillar_ring_out_c2: '007FFF'
      },
      properties: [
        { id: 'color1', name: 'Ring Core', description: 'Pillar hit-ring core color (bottom rings, inside + outside)', format: 'RGB' },
        { id: 'color2', name: 'Aura Glow', description: 'Pillar aura and ring glow color (blue rings, orange aura)', format: 'RGB' }
      ]
    }
  ],
  Zelda: [
    {
      // WIRE 2026-07 from research/docs-research/effect-maps/effect-texbank.md
      // section 4a. EfCoData.dat is the CAST-SHARED common effect bank (not
      // a per-character file) -- its texGraphicBank group 9 is the ONLY
      // color-bearing fire texture in the whole game (CI8, hue 41 orange);
      // Din's Fire/Bowser Bomb/Charizard breath/Roy's Blazer+Flare-Blade
      // all draw the colored fire cloud from THIS one shared group (proven
      // by mod 17088 "rainbow fire whole cast", a pure diff of grp9's extent
      // 0x8CB40-0x97F40 that shifted every fire effect simultaneously;
      // ptcl_texbank.py --verify PASSes on that containment). Owner = Zelda
      // (Din's Fire is the most singularly-associated move for this shared
      // bank); sharedWith lists every other consumer so the card also
      // appears under their extras tabs (owner/sharedWith pattern, Fox/Falco
      // upb precedent) -- installs/mods are stored once, under Zelda, and
      // apply cast-wide since the file itself is shared. Charizard/Pokemon
      // Trainer is not a selectable character in this app's roster, so it's
      // documented in the description but omitted from sharedWith. Their OWN
      // grayscale masks (Din/Vanish/Quick-Attack/arrow/Bomb texGroups) carry
      // no hue and are deliberately NOT wired (see effect-texbank.md section
      // 4c) -- recoloring them would be a no-op.
      //
      // First CI8 (indexed-palette) consumer of format: 'texture_recolor':
      // the config's `texture` key is the multi-image { images: [...] }
      // shape (10 poses, each its own 256-entry RGB5A3 palette) -- apply =
      // hue-rotate each image's PALETTE entries, pixel indices untouched
      // (vault/extras/texture_recolor.py CI-palette path).
      // vanillaDominantHue 41 (saturation-weighted, measured from the
      // vanilla palettes via ptcl_texbank.py --hue). Mirrors
      // backend/core/extra_types.py.
      id: 'common_fire',
      name: 'Fire Color',
      description: 'Shared fire-cloud texture color -- affects the shared effects file, also recolors Din\'s Fire, Bowser Bomb fire, Charizard flame-breath, and Roy\'s Flare Blade + Blazer fire for other characters',
      targetFile: 'EfCoData.dat',
      icon: 'fireball',
      format: 'texture_recolor',
      shared: true,
      // Marth has NO fire moves (Shield Breaker / Dancing Blade / Dolphin Slash
      // / Counter are all non-fire); the fire Flare Blade + Blazer are ROY's.
      // Marth was previously mislabeled here and is correctly excluded.
      sharedWith: ['Bowser', 'Roy'],
      owner: 'Zelda',
      texture: {
        gxFormat: 9, // CI8
        width: 64,
        height: 64,
        images: [
          { offset: '0x8CB40', palette: '0x96B40' },
          { offset: '0x8DB40', palette: '0x96D40' },
          { offset: '0x8EB40', palette: '0x96F40' },
          { offset: '0x8FB40', palette: '0x97140' },
          { offset: '0x90B40', palette: '0x97340' },
          { offset: '0x91B40', palette: '0x97540' },
          { offset: '0x92B40', palette: '0x97740' },
          { offset: '0x93B40', palette: '0x97940' },
          { offset: '0x94B40', palette: '0x97B40' },
          { offset: '0x95B40', palette: '0x97D40' }
        ],
        paletteFormat: 2 // RGB5A3
      },
      vanillaDominantHue: 41,
      vanilla: {
        color1: 'FF9900' // representative vanilla swatch (hue 41 at full S/V)
      },
      properties: [
        { id: 'color1', name: 'Fire Color', description: 'Shared fire-cloud color (Din\'s Fire, Bowser Bomb, Charizard breath, Roy\'s Flare Blade/Blazer fire -- all draw from this one shared texture)', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07 from research/docs-research/effect-maps/effect-texbank.md
      // section 4b. Sibling of common_fire: EfCoData.dat texGraphicBank
      // group 3, the shared electric/vanish/transform star-burst (CI8, 2
      // images, hue 279 purple/magenta). Same shared-file reasoning:
      // Sheik/Zelda Vanish + Transform + Pikachu/Pichu thunder/Quick-Attack
      // burst all composite this ONE texture. Owner = Zelda (Vanish is the
      // move most associated with this burst); sharedWith the other
      // consumers. Mirrors backend/core/extra_types.py.
      id: 'common_flash',
      name: 'Flash Color',
      description: 'Shared electric/flash star-burst texture color -- affects the shared effects file, also recolors Zelda Vanish flash, Zelda-Sheik Transform flash, and Pikachu/Pichu thunder and Quick Attack burst for other characters',
      targetFile: 'EfCoData.dat',
      icon: 'thunder',
      format: 'texture_recolor',
      shared: true,
      sharedWith: ['Sheik', 'Pikachu', 'Pichu'],
      owner: 'Zelda',
      texture: {
        gxFormat: 9, // CI8
        width: 128,
        height: 128,
        images: [
          { offset: '0x48DA0', palette: '0x50DA0' },
          { offset: '0x4CDA0', palette: '0x50FA0' }
        ],
        paletteFormat: 2 // RGB5A3
      },
      vanillaDominantHue: 279,
      vanilla: {
        color1: 'B400FF' // representative vanilla swatch (hue 279 at full S/V)
      },
      properties: [
        { id: 'color1', name: 'Flash Color', description: 'Shared electric/flash star-burst color (Vanish, Transform, Pikachu/Pichu thunder and Quick Attack -- all draw from this one shared texture)', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07-02 from research/docs-research/effect-maps/zelda-sheik.md
      // "Shippable-now summary". EfZdData.dat (symbol effZeldaDataTable) is
      // the SHARED Zelda/Sheik effects bank (both forms' scripts live in one
      // file). Farore's Wind teleport-burst CORE flash (scripts 2 grnd / 3
      // air): the yellow/orange ribbon spirals are a model-region element
      // and stay put -- only this ptcl-bank core recolors. Live-poke
      // verified 2026-07-02 (magenta poke, tests/artifacts/
      // datram-probe-zelda2/farore_burst-upb-f10.png). Offsets are the
      // parser's exact COLOR-BYTE positions (CF opcode is 2 bytes before
      // each) -- format 'RGB' with direct `offsets` lists writes right at
      // these addresses, no marker skip (falcon_kick front_c1/trail_c1
      // precedent). Mirrors backend/core/extra_types.py.
      id: 'zelda_farore',
      name: "Farore's Wind",
      description: "Farore's Wind teleport-burst core flash color (up-B)",
      targetFile: 'EfZdData.dat',
      icon: 'upb',
      offsets: {
        farore_c1: { format: 'RGB', offsets: [0x257, 0x2B8, 0x2C5, 0x2CC] },
        farore_c2: { format: 'RGB', offsets: [0x25E, 0x2BF] }
      },
      vanilla: {
        farore_c1: '03860E',
        farore_c2: '035814'
      },
      properties: [
        { id: 'color1', name: 'Burst Core', description: 'Teleport-burst core flash color (up-B)', format: 'RGB' },
        { id: 'color2', name: 'Burst Glow', description: 'Teleport-burst environmental glow color (up-B)', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07-02, same spec. Transform chest-flash core orb/ring
      // (scripts 6 + 9, byte-identical per spec lesson 12 -- verified equal,
      // one grouped layer is safe). Fires on BOTH forms' down-B transform
      // (Zelda->Sheik AND Sheik->Zelda); owner Zelda, sharedWith Sheik so
      // the card also appears under Sheik's extras tab (installs stored
      // once under Zelda since the file is shared -- common_fire/
      // common_flash owner/sharedWith pattern). The surrounding pink+blue
      // sparkle STARS are a separate element and stay put. Live-poke
      // verified 2026-07-02 on BOTH forms (green poke; tests/artifacts/
      // datram-probe-zelda2/transform_flash-downb-f04..18.png +
      // datram-probe-sheik2/sheik_transform_shared-downb-f10,f18.png).
      // Mirrors backend/core/extra_types.py.
      id: 'zelda_transform',
      name: 'Transform Flash',
      description: "Zelda<->Sheik transform chest-flash core color (down-B, both forms)",
      targetFile: 'EfZdData.dat',
      icon: 'downb',
      shared: true,
      sharedWith: ['Sheik'],
      owner: 'Zelda',
      offsets: {
        transform_c1: { format: 'RGB', offsets: [0x371, 0x37E, 0x67B, 0x688] },
        transform_c2: { format: 'RGB', offsets: [0x378, 0x385, 0x682, 0x68F] }
      },
      vanilla: {
        transform_c1: '6D68FF',
        transform_c2: '000082'
      },
      properties: [
        { id: 'color1', name: 'Flash Core', description: 'Transform chest-flash core color (down-B, both forms)', format: 'RGB' },
        { id: 'color2', name: 'Flash Glow', description: 'Transform chest-flash environmental glow color (down-B, both forms)', format: 'RGB' }
      ]
    }
  ],
  Bowser: [
    {
      // WIRE 2026-07-02 from research/docs-research/effect-maps/bowser.md
      // "Shippable-now summary". Neutral-B fire breath: 11 CF particle
      // records across scripts 5-8 of EfKpData.dat (Nintendo cloned the
      // Whirling Fortress ptcl scripts for the flame). MAP-LIVE verified
      // 2026-07-02 (tests/artifacts/datram-probe-bowser/): magenta-poking
      // all 17 offsets turned the WHOLE near-field flame body vivid pink --
      // the STATIC-pass fear that this would be subtle/texture-dominant
      // was wrong; these CF puffs ARE the dominant flame color, texture
      // only adds detail/highlights. Layout: `CF <flag> RRGGBB AA AD DF 0X
      // rrggbb`, color at marker+2; most records also carry a SECONDARY
      // color at colorpos+7 that dominates sustained puff tint (template
      // lesson 3) -- those get `_c2` counterparts; a few records have no
      // meaningful secondary (bytes are 00 00 00, unused) and ship
      // `_c1`-only, exactly like Mario's `hand_ring_42_c1` precedent. Every
      // vanilla byte differs record-to-record (template lesson 12), so
      // each is its own offset key rather than a shared vanilla string --
      // all 17 byte-verified against vanilla EfKpData.dat. The `FFFFFF`
      // white primaries are load-bearing: per the spec, recoloring them is
      // what turned the whole flame magenta, so they ship alongside the
      // already-orange records. Single multi-record flame layer per the
      // spec's grouping recommendation. Mirrors backend/core/extra_types.py.
      id: 'bowser_fire_breath',
      name: 'Fire Breath',
      description: 'Neutral-B fire breath flame puff colors',
      targetFile: 'EfKpData.dat',
      icon: 'fireball',
      offsets: {
        fb_s5_a_c1: { format: 'RGB', offsets: [0x3E2] },
        fb_s5_a_c2: { format: 'RGB', offsets: [0x3E9] },
        fb_s5_x_c1: { format: 'RGB', offsets: [0x3FB] },
        fb_s5_b_c1: { format: 'RGB', offsets: [0x40F] },
        fb_s6_a_c1: { format: 'RGB', offsets: [0x490] },
        fb_s6_a_c2: { format: 'RGB', offsets: [0x497] },
        fb_s6_b_c1: { format: 'RGB', offsets: [0x49D] },
        fb_s6_b_c2: { format: 'RGB', offsets: [0x4A4] },
        fb_s6_c_c1: { format: 'RGB', offsets: [0x4BB] },
        fb_s7_a_c1: { format: 'RGB', offsets: [0x566] },
        fb_s7_a_c2: { format: 'RGB', offsets: [0x56D] },
        fb_s7_b_c1: { format: 'RGB', offsets: [0x573] },
        fb_s7_b_c2: { format: 'RGB', offsets: [0x57A] },
        fb_s7_c_c1: { format: 'RGB', offsets: [0x587] },
        fb_s8_a_c1: { format: 'RGB', offsets: [0x5EE] },
        fb_s8_b_c1: { format: 'RGB', offsets: [0x609] },
        fb_s8_c_c1: { format: 'RGB', offsets: [0x628] }
      },
      vanilla: {
        fb_s5_a_c1: 'FFFFFF',
        fb_s5_a_c2: 'FFE851',
        fb_s5_x_c1: 'FFFFFF',
        fb_s5_b_c1: 'FFD9B8',
        fb_s6_a_c1: 'FFFFFF',
        fb_s6_a_c2: 'C06401',
        fb_s6_b_c1: 'FF804A',
        fb_s6_b_c2: '942514',
        fb_s6_c_c1: 'FFA973',
        fb_s7_a_c1: 'FFC607',
        fb_s7_a_c2: 'FF0206',
        fb_s7_b_c1: 'FFEF40',
        fb_s7_b_c2: 'FF0A0E',
        fb_s7_c_c1: 'FFFFFF',
        fb_s8_a_c1: 'FFFFFF',
        fb_s8_b_c1: 'FFFFFF',
        fb_s8_c_c1: 'FFD9B8'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Fire breath flame puff primary color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Fire breath sustained puff tint', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07-03, the bowser.md "texture lead" shipped. The fire
      // breath's flame BODY is a 9-frame animated CI8 billboard in
      // EfKpData.dat's tex bank (group 0: 9x 64x64 CI8, images
      // 0x6C0+i*0x1000, palettes 0x96C0+i*0x200). The scripts 5-8 CF puffs
      // (bowser_fire_breath) tint it, but the texture's own orange
      // modulates through -- most visibly on LANDED ground flames, where
      // the one-shot ptcl spawn has faded and the burning item's textured
      // quads dominate. Recolor = hue-rotate each frame's palette entries
      // (upb_charge_fire precedent). Mirrors backend/core/extra_types.py.
      id: 'breath_texture',
      partOf: 'bowser_fire_breath',  // edited inside the bowser_fire_breath unit's page (getUnitParts)
      name: 'Fire Breath Texture',
      description: 'Fire breath flame body texture color -- the textured fire that lingers where the flames land',
      targetFile: 'EfKpData.dat',
      icon: 'fireball',
      format: 'texture_recolor',
      texture: {
        gxFormat: 9, // CI8
        width: 64,
        height: 64,
        images: [
          { offset: '0x6C0', palette: '0x96C0' },
          { offset: '0x16C0', palette: '0x98C0' },
          { offset: '0x26C0', palette: '0x9AC0' },
          { offset: '0x36C0', palette: '0x9CC0' },
          { offset: '0x46C0', palette: '0x9EC0' },
          { offset: '0x56C0', palette: '0xA0C0' },
          { offset: '0x66C0', palette: '0xA2C0' },
          { offset: '0x76C0', palette: '0xA4C0' },
          { offset: '0x86C0', palette: '0xA6C0' }
        ],
        paletteFormat: 2 // RGB5A3
      },
      vanillaDominantHue: 28.2,
      vanilla: {
        color1: 'FF7800' // representative vanilla swatch (hue 28.2 at full S/V)
      },
      properties: [
        { id: 'color1', name: 'Flame Texture Color', description: 'Fire breath flame body texture color', format: 'RGB' }
      ]
    }
  ],
  Jigglypuff: [
    {
      // WIRE 2026-07-02 from research/docs-research/effect-maps/jigglypuff.md
      // "Shippable-now summary". Sing (up-B) draws three musical notes
      // circling Jiggly -- MODEL-REGION geometry in EfPrData.dat (NOT
      // ptcl), each note a 070707 vertex-color pair: marker+4 = bright
      // core, marker+8 = fill/glow (block format doc, spec lesson 2).
      // LIVE-poke verified 2026-07-02 (tests/artifacts/
      // datram-probe-jigglypuff/): red core/glow poked green -> bottom note
      // turned green; blue poked orange -> upper-left note turned orange;
      // green poked magenta -> right note turned magenta. All per-record
      // vanilla byte-verified against storage/test-base/files/
      // EfPrData.dat (spec lesson 12 -- do NOT share one vanilla string;
      // each note's core is FFFFFF but each glow differs). Shipped as SIX
      // independent per-note-color properties (not a _c1/_c2 fan-out pair)
      // so each of the three notes can be themed on its own --
      // EffectEditorPage renders one ColorPicker per `properties`
      // entry generically; no suffix fan-out needed since each property id
      // IS its own offset key. The 42_48 note-material diffuses (blue
      // @0x5574, green @0x5634) are DELIBERATELY left unshipped per the
      // spec: LIVE could not isolate their contribution (poked together
      // with the 070707 pair every time; the note body fully recolored
      // from the 070707 pair alone) and there is no red material block at
      // all. Mirrors backend/core/extra_types.py.
      id: 'sing_notes',
      name: 'Sing Notes',
      description: 'Up-B Sing musical note colors (red/blue/green, each independently themeable)',
      targetFile: 'EfPrData.dat',
      icon: 'upb',
      offsets: {
        note_red_core: { start: 0x5444, size: 3, format: 'RGB' },
        note_red_glow: { start: 0x5448, size: 3, format: 'RGB' },
        note_blue_core: { start: 0x5504, size: 3, format: 'RGB' },
        note_blue_glow: { start: 0x5508, size: 3, format: 'RGB' },
        note_green_core: { start: 0x55C4, size: 3, format: 'RGB' },
        note_green_glow: { start: 0x55C8, size: 3, format: 'RGB' }
      },
      vanilla: {
        note_red_core: 'FFFFFF',
        note_red_glow: 'FF0000',
        note_blue_core: 'FFFFFF',
        note_blue_glow: '0000FF',
        note_green_core: 'FFFFFF',
        note_green_glow: '00FF00'
      },
      properties: [
        { id: 'note_red_core', name: 'Red Note Core', description: 'Red note bright core', format: 'RGB' },
        { id: 'note_red_glow', name: 'Red Note Glow', description: 'Red note fill/glow', format: 'RGB' },
        { id: 'note_blue_core', name: 'Blue Note Core', description: 'Blue note bright core', format: 'RGB' },
        { id: 'note_blue_glow', name: 'Blue Note Glow', description: 'Blue note fill/glow', format: 'RGB' },
        { id: 'note_green_core', name: 'Green Note Core', description: 'Green note bright core', format: 'RGB' },
        { id: 'note_green_glow', name: 'Green Note Glow', description: 'Green note fill/glow', format: 'RGB' }
      ]
    }
  ],
  Ganondorf: [
    {
      // WIRE 2026-07-02 from research/docs-research/effect-maps/ganondorf.md LIVE
      // section. Warlock/Falcon Punch dark aura + fist-explosion burst
      // (scripts 0+1). LIVE-poke: green replaced the vanilla purple
      // connect-burst on the VICTIM at contact (needs the punching-bag
      // harness -- bag dk, dx 11 -- to demonstrate; the solo charge
      // starburst is a different, unpoked script). Per spec lesson 12 the
      // group's vanilla bytes do NOT share one string -- each distinct
      // vanilla value gets its own offset key (mario_fireball
      // hand_smoke_a/b/c precedent). _c1 = PRIMCOL (birth/bright), _c2 =
      // ENVCOL (sustained/fade). Mirrors backend/core/extra_types.py.
      id: 'warlock_punch',
      name: 'Warlock Punch',
      description: 'Warlock Punch dark aura and fist-explosion colors (best seen on contact)',
      targetFile: 'EfGnData.dat',
      icon: 'punch',
      offsets: {
        punch_a_c1: { format: 'RGB', offsets: [0x154] },
        punch_a_c2: { format: 'RGB', offsets: [0x15B] },
        punch_b_c1: { format: 'RGB', offsets: [0x161] },
        punch_b_c2: { format: 'RGB', offsets: [0x168] },
        punch_c_c1: { format: 'RGB', offsets: [0x192] },
        punch_c_c2: { format: 'RGB', offsets: [0x199] },
        fist_a_c1: { format: 'RGB', offsets: [0x224] },
        fist_a_c2: { format: 'RGB', offsets: [0x22B] },
        fist_b_c1: { format: 'RGB', offsets: [0x231] },
        fist_b_c2: { format: 'RGB', offsets: [0x238] },
        fist_c_c1: { format: 'RGB', offsets: [0x262] },
        fist_c_c2: { format: 'RGB', offsets: [0x269] }
      },
      vanilla: {
        punch_a_c1: '280021',
        punch_a_c2: '11002E',
        punch_b_c1: '47004F',
        punch_b_c2: '130245',
        punch_c_c1: '000000',
        punch_c_c2: '1B0245',
        fist_a_c1: 'A200AB',
        fist_a_c2: '400591',
        fist_b_c1: '75039C',
        fist_b_c2: '280587',
        fist_c_c1: '000000',
        fist_c_c2: '540775'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Dark aura core and fist-explosion primary color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Dark aura and fist-explosion sustained tint', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07-02, same spec. Wizard's Foot (down-B) foot-fire --
      // script 6 (0x4CF/0x4D6) only. The spec's draft script 2
      // (0x306-0x31D) was LIVE-DEAD and is NOT shipped (see
      // docs/EXTRAS_AUDIT.md). LIVE-poke: green poke on script 6 produced
      // green foot-fire streaks under Ganon during the dash; the larger
      // purple impact starburst on connect is a still-unattributed script
      // (open lead, not this layer). Solo down-B whiff demonstrates it, no
      // bag needed. Mirrors backend/core/extra_types.py.
      id: 'wizards_foot',
      name: "Wizard's Foot",
      description: "Wizard's Foot dash foot-fire streak colors",
      targetFile: 'EfGnData.dat',
      icon: 'punch',
      offsets: {
        color1: { start: 0x4CF, size: 3, format: 'RGB' },
        color2: { start: 0x4D6, size: 3, format: 'RGB' }
      },
      vanilla: {
        color1: 'FFDEFF',
        color2: '3D0261'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Foot-fire streak core color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Foot-fire streak sustained tint', format: 'RGB' }
      ]
    },
    {
      // WIRE 2026-07-02 from research/docs-research/effect-maps/ganondorf.md S5b
      // NARROW CONFIRM section. gerudo_dragon = the purple/magenta flame
      // aura that engulfs the victim on the Gerudo/Flame Choke (side-B)
      // command-grab connect -- scripts 12/14/15/16 (0x76C-0x9BC). The
      // earlier draft script 4 (0x3CC-0x3E3) was LIVE-DEAD and is NOT
      // shipped. Found via a sweep using the NEW --bag-pin harness option
      // (zeros the bag's knockback + re-pins its position every stepped
      // frame -- unblocks command grabs, which otherwise knock the bag out
      // of re-grab range after the first slam); a final NARROW CONFIRM poke
      // (s12/14/15/16 ONLY, cyan) isolated the aura cleanly -- the white
      // smoke puffs (s7/9/10/11, a sibling script group) and the impact
      // green-ray starburst stayed vanilla, confirming s12/14/15/16 own the
      // flame aura alone. AUDIT_HINTS uses bag dk dx=5 pin=true. All 26
      // offsets byte-verified against vanilla EfGnData.dat (every record
      // has a DISTINCT vanilla value per lesson 12). _c1 = PRIMCOL
      // (flame bright/birth), _c2 = ENVCOL (sustained flame tint). Mirrors
      // backend/core/extra_types.py.
      id: 'gerudo_dragon',
      name: 'Gerudo Dragon',
      description: 'Gerudo Dragon (side-B command grab) flame aura colors (best seen on contact)',
      targetFile: 'EfGnData.dat',
      icon: 'sideb',
      offsets: {
        s12_a_c1: { format: 'RGB', offsets: [0x76C] },
        s12_a_c2: { format: 'RGB', offsets: [0x773] },
        s12_b_c1: { format: 'RGB', offsets: [0x779] },
        s12_b_c2: { format: 'RGB', offsets: [0x780] },
        s12_c_c1: { format: 'RGB', offsets: [0x7AF] },
        s12_c_c2: { format: 'RGB', offsets: [0x7B6] },
        s14_a_c1: { format: 'RGB', offsets: [0x875] },
        s14_a_c2: { format: 'RGB', offsets: [0x87C] },
        s14_b_c1: { format: 'RGB', offsets: [0x885] },
        s14_b_c2: { format: 'RGB', offsets: [0x88C] },
        s14_c_c1: { format: 'RGB', offsets: [0x895] },
        s14_c_c2: { format: 'RGB', offsets: [0x89C] },
        s14_d_c1: { format: 'RGB', offsets: [0x8A5] },
        s14_d_c2: { format: 'RGB', offsets: [0x8AC] },
        s14_e_c1: { format: 'RGB', offsets: [0x8B6] },
        s14_e_c2: { format: 'RGB', offsets: [0x8BD] },
        s15_a_c1: { format: 'RGB', offsets: [0x92C] },
        s15_a_c2: { format: 'RGB', offsets: [0x933] },
        s15_b_c1: { format: 'RGB', offsets: [0x93C] },
        s15_b_c2: { format: 'RGB', offsets: [0x943] },
        s16_a_c1: { format: 'RGB', offsets: [0x9A0] },
        s16_a_c2: { format: 'RGB', offsets: [0x9A7] },
        s16_b_c1: { format: 'RGB', offsets: [0x9AE] },
        s16_b_c2: { format: 'RGB', offsets: [0x9B5] },
        s16_c_c1: { format: 'RGB', offsets: [0x9BC] },
        s16_c_c2: { format: 'RGB', offsets: [0x9C3] }
      },
      vanilla: {
        s12_a_c1: 'F2D1FF', s12_a_c2: '2D0359',
        s12_b_c1: '7C40D7', s12_b_c2: '280242',
        s12_c_c1: '1F0138', s12_c_c2: '000000',
        s14_a_c1: 'BEA7CA', s14_a_c2: '9609C5',
        s14_b_c1: 'C607FF', s14_b_c2: '5E06A1',
        s14_c_c1: 'B07FC7', s14_c_c2: 'AD33E1',
        s14_d_c1: '81198C', s14_d_c2: '500BA3',
        s14_e_c1: '3D087D', s14_e_c2: '3E034F',
        s15_a_c1: '7605B3', s15_a_c2: 'D88AFF',
        s15_b_c1: 'D873FF', s15_b_c2: '730AAB',
        s16_a_c1: 'E36DF3', s16_a_c2: 'A007FF',
        s16_b_c1: '2D0047', s16_b_c2: '220133',
        s16_c_c1: 'D1C3DE', s16_c_c2: '000000'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Gerudo Dragon flame aura core color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Gerudo Dragon flame aura sustained tint', format: 'RGB' }
      ]
    }
  ],
  Kirby: [
    {
      // WIRE 2026-07-02 from research/docs-research/effect-maps/kirby.md
      // Shippable-now section. kirby_stone = the Stone (down-B) transform-
      // burst dust: scripts s8/s9/s14 carry the DOMINANT visible color
      // (poked magenta -> the entire radial burst + rock-debris tint +
      // swirl rings turned bright magenta, unambiguous); s5 (ground-
      // transform starburst) is a subtler secondary contributor. s6
      // (air-stone transform, draft candidate) LIVE-poked DEAD and is NOT
      // shipped. Final Cutter, Hammer, Inhale, and Puff-air are all dead in
      // EfKbData's ptcl bank (model/texture/item-article driven) -- not
      // wired here; see the spec's DEAD section. All offsets byte-verified
      // against vanilla EfKbData.dat (each record has a DISTINCT vanilla
      // value per lesson 12, so each gets its own key). _c1 = PRIMCOL
      // (dust/debris bright), _c2 = the one ENVCOL (s9's teal sustain
      // tint). Mirrors backend/core/extra_types.py.
      id: 'kirby_stone',
      name: 'Stone',
      description: 'Stone (down-B) transform-burst dust and rock-debris colors',
      targetFile: 'EfKbData.dat',
      icon: 'downb',
      offsets: {
        dust_a_c1: { format: 'RGB', offsets: [0x51E] },
        dust_b_c1: { format: 'RGB', offsets: [0x52B] },
        dust_c_c1: { format: 'RGB', offsets: [0x532] },
        s9_a_c1: { format: 'RGB', offsets: [0x58B] },
        s9_a_c2: { format: 'RGB', offsets: [0x592] },
        s9_b_c1: { format: 'RGB', offsets: [0x598] },
        s9_c_c1: { format: 'RGB', offsets: [0x59F] },
        brk_a_c1: { format: 'RGB', offsets: [0x796] },
        brk_b_c1: { format: 'RGB', offsets: [0x7A3] },
        ground_a_c1: { format: 'RGB', offsets: [0x381] },
        ground_b_c1: { format: 'RGB', offsets: [0x38E] },
        ground_c_c1: { format: 'RGB', offsets: [0x3A9] },
        ground_d_c1: { format: 'RGB', offsets: [0x3AF] }
      },
      vanilla: {
        dust_a_c1: 'FFFFFF',
        dust_b_c1: 'FFFFFF',
        dust_c_c1: 'FFFFFF',
        s9_a_c1: 'CCCCCC',
        s9_a_c2: '09A9BA',
        s9_b_c1: 'CACACA',
        s9_c_c1: 'BABABA',
        brk_a_c1: 'FFFFFF',
        brk_b_c1: 'FFFFFF',
        ground_a_c1: 'FFFF00',
        ground_b_c1: 'FFFFFF',
        ground_c_c1: 'FFFFFF',
        ground_d_c1: 'FFFF00'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Transform-burst dust and rock-debris core color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Dust sustained teal tint', format: 'RGB' }
      ]
    },
    // --- Copy Abilities (WIRE 2026-07-02, research/docs-research/effect-maps/kirby.md
    // section 6). Each EfKb<XX>.dat copy bank is a byte-identical SLICE of
    // its donor's own EfXxData.dat ptcl records at shifted offsets (position-
    // matched: script ordinal, in-script operand ordinal, bytes -- NOT
    // absolute-offset diffing). Kirby's copied specials resolve exclusively
    // into the copy-range bank (decomp-verified), so recoloring these never
    // touches the donor character's own extra. Only the 5 FULL/high-overlap
    // copies twinning an already-shipped+verified donor extra are wired
    // (Gn/Ic/Kp/Lg/Mr); the LIVE-hold three (Ca/Ss/Pk) + Pc are blocked on a
    // copy-inhale harness primitive (kirby.md 6.4) and are NOT shipped.
    // Mirrors backend/core/extra_types.py.
    {
      id: 'kirby_copy_ganon',
      name: 'Copy Ability: Warlock Punch',
      description: 'Copied Warlock Punch dark aura and fist-explosion colors (twins the donor Ganondorf warlock_punch extra, 12/12 records)',
      targetFile: 'EfKbGn.dat',
      icon: 'punch',
      offsets: {
        punch_a_c1: { format: 'RGB', offsets: [0xE4] },
        punch_a_c2: { format: 'RGB', offsets: [0xEB] },
        punch_b_c1: { format: 'RGB', offsets: [0xF1] },
        punch_b_c2: { format: 'RGB', offsets: [0xF8] },
        punch_c_c1: { format: 'RGB', offsets: [0x122] },
        punch_c_c2: { format: 'RGB', offsets: [0x129] },
        fist_a_c1: { format: 'RGB', offsets: [0x1B4] },
        fist_a_c2: { format: 'RGB', offsets: [0x1BB] },
        fist_b_c1: { format: 'RGB', offsets: [0x1C1] },
        fist_b_c2: { format: 'RGB', offsets: [0x1C8] },
        fist_c_c1: { format: 'RGB', offsets: [0x1F2] },
        fist_c_c2: { format: 'RGB', offsets: [0x1F9] }
      },
      vanilla: {
        punch_a_c1: '280021',
        punch_a_c2: '11002E',
        punch_b_c1: '47004F',
        punch_b_c2: '130245',
        punch_c_c1: '000000',
        punch_c_c2: '1B0245',
        fist_a_c1: 'A200AB',
        fist_a_c2: '400591',
        fist_b_c1: '75039C',
        fist_b_c2: '280587',
        fist_c_c1: '000000',
        fist_c_c2: '540775'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Copied dark aura core and fist-explosion primary color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Copied dark aura and fist-explosion sustained tint', format: 'RGB' }
      ]
    },
    {
      id: 'kirby_copy_iceclimbers',
      name: 'Copy Ability: Ice Shot',
      description: 'Copied Ice Shot birth swirl and block-glow colors (twins the donor Ice Climbers ice_shot extra, 17 of 19 copy records matching shipped donor layers)',
      targetFile: 'EfKbIc.dat',
      icon: 'neutralb',
      offsets: {
        birth_a_c1: { format: 'RGB', offsets: [0xBA] },
        birth_a_c2: { format: 'RGB', offsets: [0xC1] },
        birth_b_c1: { format: 'RGB', offsets: [0xC7] },
        birth_b_c2: { format: 'RGB', offsets: [0xCE] },
        birth_c_c1: { format: 'RGB', offsets: [0xDB] },
        sparkle_c1: { format: 'RGB', offsets: [0x17D, 0x30D] },
        sparkle_c2: { format: 'RGB', offsets: [0x184, 0x314] },
        sparkle2_c1: { format: 'RGB', offsets: [0x18A, 0x31A] },
        variant_a_c1: { format: 'RGB', offsets: [0x1E6] },
        variant_a_c2: { format: 'RGB', offsets: [0x1ED] },
        variant_b_c1: { format: 'RGB', offsets: [0x1F3] },
        variant_c_c1: { format: 'RGB', offsets: [0x24E] },
        variant_c_c2: { format: 'RGB', offsets: [0x255] },
        variant_d_c1: { format: 'RGB', offsets: [0x25B] }
      },
      vanilla: {
        birth_a_c1: '79B8F7',
        birth_a_c2: '0101F9',
        birth_b_c1: '2E66FF',
        birth_b_c2: '0B07EE',
        birth_c_c1: '679CFE',
        sparkle_c1: 'FAFCFF',
        sparkle_c2: '515DFF',
        sparkle2_c1: 'BAEEFF',
        variant_a_c1: 'FAFCFF',
        variant_a_c2: '2E17FF',
        variant_b_c1: '1AB4DE',
        variant_c_c1: 'FAFCFF',
        variant_c_c2: '2E17FF',
        variant_d_c1: '82EBFF'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Copied Ice Shot birth swirl and sparkle core color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Copied Ice Shot sustained blue tint', format: 'RGB' }
      ]
    },
    {
      id: 'kirby_copy_bowser',
      name: 'Copy Ability: Fire Breath',
      description: 'Copied fire breath flame puff colors (twins the donor Bowser bowser_fire_breath extra, 17/17 records)',
      targetFile: 'EfKbKp.dat',
      icon: 'fireball',
      offsets: {
        fb_s5_a_c1: { format: 'RGB', offsets: [0xA2] },
        fb_s5_a_c2: { format: 'RGB', offsets: [0xA9] },
        fb_s5_x_c1: { format: 'RGB', offsets: [0xBB] },
        fb_s5_b_c1: { format: 'RGB', offsets: [0xCF] },
        fb_s6_a_c1: { format: 'RGB', offsets: [0x150] },
        fb_s6_a_c2: { format: 'RGB', offsets: [0x157] },
        fb_s6_b_c1: { format: 'RGB', offsets: [0x15D] },
        fb_s6_b_c2: { format: 'RGB', offsets: [0x164] },
        fb_s6_c_c1: { format: 'RGB', offsets: [0x17B] },
        fb_s7_a_c1: { format: 'RGB', offsets: [0x226] },
        fb_s7_a_c2: { format: 'RGB', offsets: [0x22D] },
        fb_s7_b_c1: { format: 'RGB', offsets: [0x233] },
        fb_s7_b_c2: { format: 'RGB', offsets: [0x23A] },
        fb_s7_c_c1: { format: 'RGB', offsets: [0x247] },
        fb_s8_a_c1: { format: 'RGB', offsets: [0x2AE] },
        fb_s8_b_c1: { format: 'RGB', offsets: [0x2C9] },
        fb_s8_c_c1: { format: 'RGB', offsets: [0x2E8] }
      },
      vanilla: {
        fb_s5_a_c1: 'FFFFFF',
        fb_s5_a_c2: 'FFE851',
        fb_s5_x_c1: 'FFFFFF',
        fb_s5_b_c1: 'FFD9B8',
        fb_s6_a_c1: 'FFFFFF',
        fb_s6_a_c2: 'C06401',
        fb_s6_b_c1: 'FF804A',
        fb_s6_b_c2: '942514',
        fb_s6_c_c1: 'FFA973',
        fb_s7_a_c1: 'FFC607',
        fb_s7_a_c2: 'FF0206',
        fb_s7_b_c1: 'FFEF40',
        fb_s7_b_c2: 'FF0A0E',
        fb_s7_c_c1: 'FFFFFF',
        fb_s8_a_c1: 'FFFFFF',
        fb_s8_b_c1: 'FFFFFF',
        fb_s8_c_c1: 'FFD9B8'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Copied fire breath flame puff primary color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Copied fire breath sustained puff tint', format: 'RGB' }
      ]
    },
    {
      id: 'kirby_copy_luigi',
      name: 'Copy Ability: Fireball Smoke',
      description: "Copied fireball hand-spawn smoke colors (twins the donor Luigi luigi_fireball_smoke extra, 20 of 24 copy records matching shipped donor layers -- the 4 misses are Luigi's model-region green-fire blocks a ptcl copy can't carry)",
      targetFile: 'EfKbLg.dat',
      icon: 'fireball',
      offsets: {
        fb_smoke_s0a_c1: { format: 'RGB', offsets: [0xC7] },
        fb_smoke_s0a_c2: { format: 'RGB', offsets: [0xCE] },
        fb_smoke_s0b_c1: { format: 'RGB', offsets: [0xD4] },
        fb_smoke_s0b_c2: { format: 'RGB', offsets: [0xDB] },
        fb_smoke_s1_c1: { format: 'RGB', offsets: [0x14E, 0x15C, 0x16F, 0x17C] },
        fb_smoke_s1_c2: { format: 'RGB', offsets: [0x155, 0x163, 0x176, 0x183] },
        fb_smoke_s3_c1: { format: 'RGB', offsets: [0x235] },
        fb_smoke_s3_c2: { format: 'RGB', offsets: [0x249] },
        fb_smoke_s4_c1: { format: 'RGB', offsets: [0x2A5] },
        fb_smoke_s4_c2: { format: 'RGB', offsets: [0x2B9] },
        fb_dust_s5_c1: { format: 'RGB', offsets: [0x31A] },
        fb_dust_s5_c2: { format: 'RGB', offsets: [0x33A] },
        fb_particle_s6_c1: { format: 'RGB', offsets: [0x3C6] },
        fb_particle_s6_c2: { format: 'RGB', offsets: [0x3D6] }
      },
      vanilla: {
        color1: '93A394',
        color2: '22AB0A',
        fb_smoke_s0a_c1: '26FF43',
        fb_smoke_s0a_c2: '2ABA4E',
        fb_smoke_s0b_c1: '149C2D',
        fb_smoke_s0b_c2: '0C5419',
        fb_smoke_s1_c1: '93A394',
        fb_smoke_s1_c2: '22AB0A',
        fb_smoke_s3_c1: '02FD02',
        fb_smoke_s3_c2: '052E15',
        fb_smoke_s4_c1: '16FD22',
        fb_smoke_s4_c2: '0A4F12',
        fb_dust_s5_c1: 'BDFDBB',
        fb_dust_s5_c2: '31F83B',
        fb_particle_s6_c1: '1ADC24',
        fb_particle_s6_c2: '7CFF70'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Copied fireball hand-spawn smoke puff core color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Copied fireball smoke sustained tint', format: 'RGB' }
      ]
    },
    {
      id: 'kirby_copy_mario',
      name: 'Copy Ability: Fireball',
      description: "Copied fireball smoke, trail, particle, and dust colors (twins the donor Mario mario_fireball extra, 30 of 33 copy records matching shipped donor layers -- the 3 misses are the 0x11Axx hand-ring model-region blocks a ptcl copy can't carry). NOTE the copy's script 0 clones the donor's script 1.",
      targetFile: 'EfKbMr.dat',
      icon: 'fireball',
      offsets: {
        hand_smoke_a_c1: { format: 'RGB', offsets: [0xB2] },
        hand_smoke_a_c2: { format: 'RGB', offsets: [0xB9] },
        hand_smoke_b_c1: { format: 'RGB', offsets: [0xC7] },
        hand_smoke_b_c2: { format: 'RGB', offsets: [0xCE] },
        hand_smoke_c_c1: { format: 'RGB', offsets: [0xD4] },
        hand_smoke_c_c2: { format: 'RGB', offsets: [0xDB] },
        trailing_fire_a_c1: { format: 'RGB', offsets: [0x15C] },
        trailing_fire_a_c2: { format: 'RGB', offsets: [0x163] },
        trailing_fire_b_c1: { format: 'RGB', offsets: [0x16F] },
        trailing_fire_b_c2: { format: 'RGB', offsets: [0x176] },
        trailing_fire_c_c1: { format: 'RGB', offsets: [0x17C] },
        trailing_fire_c_c2: { format: 'RGB', offsets: [0x183] },
        ball_particles_a_c1: { format: 'RGB', offsets: [0x2A5] },
        ball_particles_a_c2: { format: 'RGB', offsets: [0x2AC] },
        ball_particles_b_c1: { format: 'RGB', offsets: [0x2B2] },
        ball_particles_b_c2: { format: 'RGB', offsets: [0x2B9] },
        ball_particles_c_c1: { format: 'RGB', offsets: [0x235] },
        ball_particles_c_c2: { format: 'RGB', offsets: [0x23C] },
        ball_particles_d_c1: { format: 'RGB', offsets: [0x242] },
        ball_particles_d_c2: { format: 'RGB', offsets: [0x249] },
        landing_dust_a_c1: { format: 'RGB', offsets: [0x31A] },
        landing_dust_a_c2: { format: 'RGB', offsets: [0x321] },
        landing_dust_b_c1: { format: 'RGB', offsets: [0x32D] },
        landing_dust_b_c2: { format: 'RGB', offsets: [0x334] },
        landing_dust_c_c1: { format: 'RGB', offsets: [0x33A] },
        landing_dust_c_c2: { format: 'RGB', offsets: [0x341] },
        square_particles_a_c1: { format: 'RGB', offsets: [0x3C6] },
        square_particles_a_c2: { format: 'RGB', offsets: [0x3CD] },
        square_particles_b_c1: { format: 'RGB', offsets: [0x3D6] },
        square_particles_b_c2: { format: 'RGB', offsets: [0x3DD] }
      },
      vanilla: {
        color1: 'FFA217',
        color2: 'D43B08',
        hand_smoke_a_c1: 'FFFFFF',
        hand_smoke_a_c2: 'FFCC4A',
        hand_smoke_b_c1: 'FFA217',
        hand_smoke_b_c2: 'BA120D',
        hand_smoke_c_c1: '9C060B',
        hand_smoke_c_c2: '540405',
        trailing_fire_a_c1: 'C7BB0D',
        trailing_fire_a_c2: 'D43B08',
        trailing_fire_b_c1: 'FFA800',
        trailing_fire_b_c2: 'FF5900',
        trailing_fire_c_c1: 'FF070F',
        trailing_fire_c_c2: '510A00',
        ball_particles_a_c1: 'FDEB74',
        ball_particles_a_c2: 'E33C09',
        ball_particles_b_c1: 'B90303',
        ball_particles_b_c2: '610101',
        ball_particles_c_c1: 'FDE467',
        ball_particles_c_c2: 'D42304',
        ball_particles_d_c1: '7D4202',
        ball_particles_d_c2: '2E0000',
        landing_dust_a_c1: 'FEFCE2',
        landing_dust_a_c2: 'FFF75C',
        landing_dust_b_c1: 'FCE669',
        landing_dust_b_c2: 'D60B0E',
        landing_dust_c_c1: 'F9AC06',
        landing_dust_c_c2: '6B0507',
        square_particles_a_c1: 'FF290C',
        square_particles_a_c2: 'FFFF82',
        square_particles_b_c1: 'FFFF6E',
        square_particles_b_c2: 'FF0C14'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Copied fireball smoke/trail/particle core color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Copied fireball sustained tint / glow', format: 'RGB' }
      ]
    }
  ],
  'Ice Climbers': [
    {
      // WIRE 2026-07-02 from research/docs-research/effect-maps/iceclimbers.md LIVE
      // section. Ice Shot (neutral-B) is a forward-firing PROJECTILE, fully
      // solo-visible -- covers the birth swirl (script 0), the block-glow
      // variants (scripts 3/4), and the sparkle family (Family A: scripts
      // 2/6/8/12, identical vanilla bytes across all four generators, one
      // key each). EfIcData.dat is a SHARED file (efAsync_DatEntries has
      // exactly ONE EfIc entry) -- both Popo and Nana resolve the same
      // bank, so one patch covers both climbers automatically; there is no
      // separate Nana copy to also patch. Config character key
      // 'Ice Climbers' matches the existing CHAR_DAT_PREFIX entry; the
      // in-game/audit char key is 'iceclimbers' (char_select.py canonical,
      // aliases ics/icies/popo resolve to it). freeze_crystals (Family B,
      // scripts 9/11/13/15) is LIVE-DEAD (item texture, not this ptcl bank)
      // and NOT shipped. Mirrors backend/core/extra_types.py.
      id: 'ice_shot',
      name: 'Ice Shot',
      description: 'Ice Shot (neutral-B) birth swirl, block glow, and sparkle colors -- affects both Popo and Nana',
      targetFile: 'EfIcData.dat',
      icon: 'neutralb',
      offsets: {
        birth_a_c1: { format: 'RGB', offsets: [0xE2] },
        birth_a_c2: { format: 'RGB', offsets: [0xE9] },
        birth_b_c1: { format: 'RGB', offsets: [0xEF] },
        birth_b_c2: { format: 'RGB', offsets: [0xF6] },
        birth_c_c1: { format: 'RGB', offsets: [0x103] },
        sparkle_c1: { format: 'RGB', offsets: [0x1A5, 0x335, 0x3EC, 0x58C] },
        sparkle_c2: { format: 'RGB', offsets: [0x1AC, 0x33C, 0x3F3, 0x593] },
        sparkle2_c1: { format: 'RGB', offsets: [0x1B2, 0x342, 0x3F9, 0x599] },
        variant_a_c1: { format: 'RGB', offsets: [0x20E] },
        variant_a_c2: { format: 'RGB', offsets: [0x215] },
        variant_b_c1: { format: 'RGB', offsets: [0x21B] },
        variant_c_c1: { format: 'RGB', offsets: [0x276] },
        variant_c_c2: { format: 'RGB', offsets: [0x27D] },
        variant_d_c1: { format: 'RGB', offsets: [0x283] }
      },
      vanilla: {
        birth_a_c1: '79B8F7',
        birth_a_c2: '0101F9',
        birth_b_c1: '2E66FF',
        birth_b_c2: '0B07EE',
        birth_c_c1: '679CFE',
        sparkle_c1: 'FAFCFF',
        sparkle_c2: '515DFF',
        sparkle2_c1: 'BAEEFF',
        variant_a_c1: 'FAFCFF',
        variant_a_c2: '2E17FF',
        variant_b_c1: '1AB4DE',
        variant_c_c1: 'FAFCFF',
        variant_c_c2: '2E17FF',
        variant_d_c1: '82EBFF'
      },
      properties: [
        { id: 'color1', name: 'Primary', description: 'Ice Shot birth swirl and sparkle core color', format: 'RGB' },
        { id: 'color2', name: 'Secondary', description: 'Ice Shot sustained blue tint', format: 'RGB' }
      ]
    }
  ]
}

/**
 * Check if a character has any extras available (including shared)
 * @param {string} character - Character name
 * @returns {boolean}
 */
export function hasExtras(character) {
  if (EXTRA_TYPES[character]?.some(t => !t.hidden)) {
    return true
  }
  // Check if any other character has shared extras for this character
  for (const [otherChar, extras] of Object.entries(EXTRA_TYPES)) {
    for (const extra of extras) {
      if (!extra.hidden && extra.shared && extra.sharedWith?.includes(character)) {
        return true
      }
    }
  }
  return false
}

/**
 * Get all extra types for a character, including shared extras from other characters.
 * Texture-type extras are excluded: they have no standalone card/editor (their
 * hue slider lives inside a sibling color editor, e.g. upb_texture inside
 * EffectEditorPage) and are applied via the backend /storage/textures/* routes.
 * @param {string} character - Character name
 * @returns {Array}
 */
export function getExtraTypes(character) {
  return collectExtraTypes(character).filter(t => t.type !== 'texture' && !t.hidden && !t.partOf)
}

/**
 * A move is ONE extra whose mod carries nested parts (mirrors the backend's
 * core.extra_types.UNIT_PARTS). The parts stay in EXTRA_TYPES for id lookups
 * and install logic but are edited inside the primary's page and never listed
 * on their own. Returns the part configs THIS character has (charge_flames is
 * Fox-only even though Up-B is shared with Falco).
 */
export const UNIT_PARTS = {
  upb: ['upb_charge_fire', 'charge_flames'],
  mario_fireball: ['mario_fireball_aura'],
  luigi_fireball: ['luigi_fireball_smoke'],
  bowser_fire_breath: ['breath_texture'],
  charge_shot: ['charge_ball'],
}

export function getUnitParts(character, typeId) {
  return (UNIT_PARTS[typeId] || []).map(id => getExtraType(character, id)).filter(Boolean)
}

/**
 * All extra types for a character including shared AND texture-type entries
 * (the unfiltered list, for id lookups).
 */
function collectExtraTypes(character) {
  // Start with the character's own extras
  const result = [...(EXTRA_TYPES[character] || [])]

  // Add shared extras from other characters
  for (const [otherChar, extras] of Object.entries(EXTRA_TYPES)) {
    if (otherChar === character) continue
    for (const extra of extras) {
      if (extra.shared && extra.sharedWith?.includes(character)) {
        // Include the shared extra (it's already configured with owner info)
        result.push(extra)
      }
    }
  }

  return result
}

/**
 * Get a specific extra type by id (including shared and texture extras)
 * @param {string} character - Character name
 * @param {string} typeId - Extra type id (e.g., 'laser')
 * @returns {Object|null}
 */
export function getExtraType(character, typeId) {
  const types = collectExtraTypes(character)
  return types.find(t => t.id === typeId) || null
}

