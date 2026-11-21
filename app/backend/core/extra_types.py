"""
Extra types configuration for character-specific mods.
Each extra type defines editable properties that modify specific dat file offsets.
Python mirror of frontend config with additional patching information.
"""

# Extra type definitions per character
# NOTE: Offsets are character-specific - do not copy between characters
EXTRA_TYPES = {
    "C. Falcon": [
        {
            # Rebuilt 2026-07 (a config for this existed only in a dev session;
            # the vault holds saved mods that were dead until now). Every
            # offset marker-verified against vanilla EfCaData.dat bytes.
            "id": "falcon_punch",
            "name": "Falcon Punch",
            "description": "Falcon Punch fire tip, lens flares, and smoke colors",
            "target_file": "EfCaData.dat",
            "offsets": {
                # 07 07 07 04 block at 0x202EC: two RGB tip colors
                "color1": {"start": 0x202F0, "size": 3, "format": "RGB"},
                "color2": {"start": 0x202F4, "size": 3, "format": "RGB"},
                # Lens-flare extending lines (0x22E30 is an 07 07 07 07
                # variant; colors still at marker+4/+8). The _c1/_c2 suffixes
                # make DualColorEditorModal fan the two pickers out to these.
                "flare_lines_c2": {
                    "format": "070707",
                    "offsets": [0x22D64, 0x22E30, 0x22EFC, 0x22FC8, 0x23094,
                                0x23160, 0x2322C, 0x232F8, 0x233C4, 0x23490]
                },
                # 42_48 material diffuse slots (RGB only; alpha byte kept)
                "flare_small_c1": {"start": 0x22D0C, "size": 3, "format": "RGB"},
                "flare_big_c1": {"start": 0x235D0, "size": 3, "format": "RGB"},
                # CF particle scripts (color at marker+2)
                "smoke": {"format": "CF", "offsets": [0x918, 0x925, 0x956]},
                "trail_smoke": {"format": "CF", "offsets": [0x1D8, 0x1E5, 0x216]},
                "wing_smoke": {"format": "CF", "offsets": [0x3AA, 0x3B7, 0x3ED]},
                "dots": {"format": "CF", "offsets": [0x29A, 0x2AA]}
            },
            "vanilla": {
                "color1": "FF7F00",       # Orange tip
                "color2": "FF0000",       # Red tip secondary
                "flare_lines_c2": "FFFFFF",
                "flare_small_c1": "FFCC00",
                "flare_big_c1": "FF9900",
                "smoke": "DE8E2B",
                "trail_smoke": "FFFFFF",
                "wing_smoke": "FEFFE1",
                "dots": "FF051A"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Main punch fire color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Punch fire secondary color", "format": "RGB"}
            ]
        },
        {
            # NEW 2026-07 from the reference 🔴 list; every offset verified by
            # byte-diffing the working "Blue Falcon Kick and Raptor Boost"
            # community mod (post_14832) against vanilla, then live-poke
            # mapped in-game (docs/dev/EXTRAS_AUDIT.md). 07 07 07 04 marker
            # @0x1DE00 (the reference's 0x1DE00 cite is 4 bytes early on the
            # colors): +4 = fire core at the foot, +8 = the big round glow
            # halo. CF particle records (layout CF <flag> RRGGBB AA AD DF 0X
            # rrggbb): the offsets below are the COLOR positions (marker+2),
            # written directly as RGB; each record also has a secondary color
            # at +7 that drives the sustained puff tint, so _c1 = primaries
            # (bright/birth), _c2 = secondaries (sustained/fade). front_c1 =
            # the yellow chevron fire streaks at the foot (record 0x6AD,
            # primary 0x6AF + secondary 0x6B6 grouped: one visual).
            "id": "falcon_kick",
            "name": "Falcon Kick",
            "description": "Falcon Kick fire, trail smoke, and spark colors",
            "target_file": "EfCaData.dat",
            "offsets": {
                "color1": {"start": 0x1DE04, "size": 3, "format": "RGB"},
                "color2": {"start": 0x1DE08, "size": 3, "format": "RGB"},
                "front_c1": {"format": "RGB", "offsets": [0x6AF, 0x6B6]},
                "trail_c1": {"format": "RGB",
                             "offsets": [0x12F, 0x149, 0x159, 0x16C, 0x17C,
                                         0x58F, 0x5A9, 0x5B9, 0x5CC, 0x5DC,
                                         0x640, 0x64E, 0x65C]},
                "trail_c2": {"format": "RGB",
                             "offsets": [0x136, 0x150, 0x160, 0x173, 0x183,
                                         0x596, 0x5B0, 0x5C0, 0x5D3, 0x5E3,
                                         0x647, 0x655, 0x663]},
                "dots_c1": {"format": "RGB",
                            "offsets": [0x474, 0x484, 0x4D9, 0x4E6, 0x539]},
                "dots_c2": {"format": "RGB",
                            "offsets": [0x47B, 0x48B, 0x4E0, 0x4ED, 0x540]}
            },
            "vanilla": {
                "color1": "FFFFE5",     # near-white fire core
                "color2": "FFB200",     # orange glow halo
                "front_c1": "FFFFFF",
                "trail_c1": "FFFFFF",
                "trail_c2": "D2CE9E",
                "dots_c1": "FF290C",
                "dots_c2": "FFFF82"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Kick fire core and trail color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Glow halo and trail fade color", "format": "RGB"}
            ]
        },
        {
            # NEW 2026-07, same provenance as falcon_kick. 07 07 07 04 marker
            # @0x24B74 (reference cite 0x24B70 is the line start): +4 = the
            # fist lens-flare core, +8 = its glow halo -- both live-poke
            # verified on the side-B whiff. hit_smoke/hit_dots = the ON-HIT
            # uppercut burst's smoke cloud + square dot particles, VERIFIED
            # on-hit 2026-07-02 with the punching-bag harness (extras_audit
            # --bag dk; docs/dev/EXTRAS_AUDIT.md raptor_boost row). hit_mat_c1 =
            # the HSD material ambient@0x2543C + diffuse@0x25440 RGBs.
            # LIVE-POKE VERIFIED 2026-07-02 (on-hit backlog, DK bag,
            # falcon_onhit_probe.json / tests/artifacts/extras-audit/
            # Falcon-raptor_hitmat-bag/): poking DIFFUSE @0x25440 to green turned
            # the raptor UPPERCUT LENS-FLARE burst GREEN (central radial flare at
            # the fist; hitmat_diffuse_25440-sideb-f22.png vs vanilla orange). It
            # is a COLOR layer, not a texture. AMBIENT @0x2543C (808080) is per
            # Mario/Fox 42_48 precedent a visual NO-OP -- diffuse @0x25440 is the
            # real control; ambient can be dropped. (Explains the earlier "no
            # delta" note: only the diffuse slot renders.) hit_mat_c1 now
            # targets DIFFUSE ONLY (0x25440) -- ambient dropped per this
            # finding (was previously writing both offsets).
            "id": "raptor_boost",
            "name": "Raptor Boost",
            "description": "Raptor Boost fist flare and hit fire/smoke colors",
            "target_file": "EfCaData.dat",
            "offsets": {
                "color1": {"start": 0x24B78, "size": 3, "format": "RGB"},
                "color2": {"start": 0x24B7C, "size": 3, "format": "RGB"},
                "hit_smoke_c1": {"format": "RGB",
                                 "offsets": [0x76F, 0x77F, 0x78F, 0x79F,
                                             0x8A0, 0x8AE, 0x8BC]},
                "hit_smoke_c2": {"format": "RGB",
                                 "offsets": [0x776, 0x786, 0x796, 0x7A6,
                                             0x8A7, 0x8B5, 0x8C3]},
                "hit_dots_c1": {"format": "RGB", "offsets": [0x82C, 0x83C]},
                "hit_dots_c2": {"format": "RGB", "offsets": [0x833, 0x843]},
                "hit_mat_c1": {"format": "RGB", "offsets": [0x25440]}
            },
            "vanilla": {
                "color1": "F9FFB2",     # pale-yellow flare core
                "color2": "FFB200",     # orange flare glow
                "hit_smoke_c1": "CACACA",
                "hit_smoke_c2": "C51D00",
                "hit_dots_c1": "FF051A",
                "hit_dots_c2": "FFFF82",
                "hit_mat_c1": "808080"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Fist flare core and hit fire color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Flare glow and hit smoke fade color", "format": "RGB"}
            ]
        },
        {
            # Audit 2026-07: the dominant Falcon Punch fire (bird body, wing
            # fire, tail streamers) is textured geometry in effect entry 0
            # (decomp: efSync_Spawn(1167) -> efalt case 0x48F -> effects
            # 0xFA0/0xFA1 = effCaptainDataTable entries 0 + 1). Models_0's
            # texture list shows TEN entries but they are THREE unique image
            # nodes (TObjs share image data): the lava tile (idx 0, also
            # listed at 1-5/7), the ember tile (idx 6, also 8) and the fire
            # wisp (idx 9) = the tail fire clouds. Target each node ONCE --
            # repeat export/shift/import on a shared node round-trips it back
            # toward vanilla. Models_1 (also spawned) is grayscale streaks -
            # nothing to shift. The lingering trail fire puffs + ember dots
            # are ptcl (see falcon_punch's smoke/dots color layers), not
            # model textures.
            "id": "punch_texture",
            "name": "Falcon Punch Fire Texture",
            "description": "Falcon Punch fire color",
            "target_file": "EfCaData.dat",
            "type": "texture",  # Texture type - CLI export/hue-shift/import (see vault/extras/textures.py)
            "texture_path": "effCaptainDataTable/Models_0_/RootJoint",
            "texture_index": 0,  # canonical (lava tile; vanilla ref / hue detection)
            "texture_targets": [
                {"path": "effCaptainDataTable/Models_0_/RootJoint", "index": 0},
                {"path": "effCaptainDataTable/Models_0_/RootJoint", "index": 6},
                {"path": "effCaptainDataTable/Models_0_/RootJoint", "index": 9}
            ],
            "vanilla_hue": 15,  # Orange-red lava tile -- recorded reference AND the
                                # apply-time shift source (see textures.py's
                                # "Vanilla-hue SOURCE" docstring section)
            # Task #12 migration (2026-07-02): ColorPicker UX, not a hue
            # slider -- editor sends {"color": "RRGGBB"}, backend converts to
            # degrees via hex_to_hue(color) - vanilla_hue. Nested inside
            # falcon_punch's DualColorEditorModal (modifications.fire), same
            # pattern as Fox/Falco's upb_texture inside UpBEditorModal. Old
            # saved mods' {"hue": degrees} shape is still accepted forever
            # (backend/vault/extras/textures.py resolve_hue_shift).
            "properties": [
                {"id": "color", "name": "Fire Color", "description": "Falcon Punch fire/bird texture color", "format": "RGB"}
            ]
        }
    ],
    "Falco": [
        {
            "id": "laser",
            "name": "Laser Color",
            "description": "Change laser beam colors",
            "target_file": "PlFc.dat",
            # Offset definitions for the 98 matrix format (Falco-specific).
            # center/tip: same white core-line matrices as Fox's (see the
            # Fox laser entry); byte-verified at these offsets 2026-07.
            "offsets": {
                "wide": {"start": 0x13440, "end": 0x134A0, "format": "RGBY"},
                "thin": {"start": 0x134E0, "end": 0x13540, "format": "RGBY"},
                "outline": {"start": 0x13580, "end": 0x135E0, "format": "RGBY"},
                "tip": {"start": 0x13620, "end": 0x13643, "format": "RGB"},
                "center": {"start": 0x13643, "end": 0x1368E, "format": "RGB"}
            },
            # Vanilla/default colors (Falco's red laser + white center line)
            "vanilla": {
                "wide": "FC00",
                "thin": "FC00",
                "outline": "FC00",
                "tip": "FFFFFF",
                "center": "FFFFFF"
            },
            "properties": [
                {"id": "wide", "name": "Wide Layer", "description": "Transparent outer glow"},
                {"id": "thin", "name": "Thin Layer", "description": "Semi-transparent middle"},
                {"id": "outline", "name": "Outline", "description": "Opaque inner core"},
                {"id": "center", "name": "Center Line", "description": "Bright core line down the beam", "format": "RGB"},
                {"id": "tip", "name": "Center Tip", "description": "Leading tip of the core line", "format": "RGB"}
            ]
        },
        {
            "id": "sideb",
            "name": "Side-B Color",
            "description": "Phantasm afterimage colors",
            "target_file": "PlFc.dat",
            "afterimage_model": True,
            "format": "42_48",
            # 42_48 format: 3 RGBA colors at a single offset
            "offsets": {
                "primary": {"start": 0x1EC48, "size": 4, "format": "RGBA"},
                "secondary": {"start": 0x1EC4C, "size": 4, "format": "RGBA"},
                "tertiary": {"start": 0x1EC50, "size": 4, "format": "RGBA"}
            },
            "vanilla": {
                "primary": "0099FFFF",
                "secondary": "CCE6FFFF",
                "tertiary": "FFFFFFFF"
            },
            "properties": [
                {"id": "primary", "name": "Primary", "description": "Main afterimage color"},
                {"id": "secondary", "name": "Secondary", "description": "Edge/gradient color"},
                {"id": "tertiary", "name": "Glow", "description": "Outer glow color"}
            ]
        },
        {
            "id": "gun",
            "name": "Gun Model",
            "description": "Replace Falco's blaster gun model",
            "target_file": "PlFc.dat",
            "type": "model",  # Model type - uses .dae file instead of hex patches
            "model_path": "ftDataFalco/Articles/Articles_1/Model_/RootModelJoint",
            "icon": "gun"
        }
    ],
    # Sword trails: the 9 bytes are NOT three RGB colors. They are the tail of
    # the decomp's itSword_UnkBytes trail params (melee it/items/types.h),
    # rendered by ft/ftafterimage.c as a two-color ribbon:
    #   +0 alpha at the blade (newest edge)   +1 alpha at the tail (fade-out)
    #   +2..4 inner-edge RGB   +5 unused   +6..8 outer-edge RGB
    # The old main/secondary/tertiary triplet layout straddled the alpha bytes
    # (audit 2026-07: patching "main" reversed the fade instead of recoloring).
    # Vanilla verified against the real DATs: inner cyan / orange (Roy),
    # outer white, alpha FF->00.
    "Marth": [
        {
            "id": "sword",
            "name": "Sword Trail",
            "description": "Sword swing trail colors",
            "target_file": "PlMs.dat",
            "offsets": {
                "inner": {"start": 0x394A, "size": 3, "format": "RGB"},
                "outer": {"start": 0x394E, "size": 3, "format": "RGB"},
                "alpha_blade": {"start": 0x3948, "size": 1, "format": "BYTE"},
                "alpha_tail": {"start": 0x3949, "size": 1, "format": "BYTE"}
            },
            "vanilla": {
                "inner": "00FFFF",     # Cyan
                "outer": "FFFFFF",     # White
                "alpha_blade": "FF",
                "alpha_tail": "00"
            },
            "properties": [
                {"id": "inner", "name": "Inner Edge", "description": "Color along the hilt-side edge of the trail", "format": "RGB"},
                {"id": "outer", "name": "Outer Edge", "description": "Color along the tip-side edge of the trail", "format": "RGB"}
            ]
        }
    ],
    "Roy": [
        {
            "id": "sword",
            "name": "Sword Trail",
            "description": "Sword swing trail colors",
            "target_file": "PlFe.dat",
            "offsets": {
                "inner": {"start": 0x3AA2, "size": 3, "format": "RGB"},
                "outer": {"start": 0x3AA6, "size": 3, "format": "RGB"},
                "alpha_blade": {"start": 0x3AA0, "size": 1, "format": "BYTE"},
                "alpha_tail": {"start": 0x3AA1, "size": 1, "format": "BYTE"}
            },
            "vanilla": {
                "inner": "EB7850",     # Orange
                "outer": "FFFFFF",     # White
                "alpha_blade": "FF",
                "alpha_tail": "00"
            },
            "properties": [
                {"id": "inner", "name": "Inner Edge", "description": "Color along the hilt-side edge of the trail", "format": "RGB"},
                {"id": "outer", "name": "Outer Edge", "description": "Color along the tip-side edge of the trail", "format": "RGB"}
            ]
        }
    ],
    "Link": [
        {
            "id": "sword",
            "name": "Sword Trail",
            "description": "Sword swing trail colors",
            "target_file": "PlLk.dat",
            "offsets": {
                "inner": {"start": 0x35EE, "size": 3, "format": "RGB"},
                "outer": {"start": 0x35F2, "size": 3, "format": "RGB"},
                "alpha_blade": {"start": 0x35EC, "size": 1, "format": "BYTE"},
                "alpha_tail": {"start": 0x35ED, "size": 1, "format": "BYTE"}
            },
            "vanilla": {
                "inner": "00FFFF",     # Cyan
                "outer": "FFFFFF",     # White
                "alpha_blade": "FF",
                "alpha_tail": "00"
            },
            "properties": [
                {"id": "inner", "name": "Inner Edge", "description": "Color along the hilt-side edge of the trail", "format": "RGB"},
                {"id": "outer", "name": "Outer Edge", "description": "Color along the tip-side edge of the trail", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07-02 from research/docs-research/effect-maps/link.md (MAP-LIVE
            # verified). EfLkData.dat has NO ptcl bank -- this is a model-region
            # 07 07 07 04 marker @0x550C (signature-scanned, not ptcl-parsed):
            # +4 = bright core (0x5510, vanilla FFFFFF), +8 = tint/glow
            # (0x5514, vanilla 0000FF). Live-poke confirmed: core->magenta +
            # tint->red turned the swirling up-B blade/disc trail magenta/red
            # across the whole up-B active window (f6-f30, captures
            # tests/artifacts/datram-probe-link/block_550c_white_blue-upb-*.png).
            # Shared with Young Link: ftCLink has no EfCl file and loads
            # EfLkData directly (efasync.c efAsync_DatEntries[51] has no
            # Child-Link entry) -- confirmed by MAP, see link.md "Young Link
            # sharing". All other model-region candidates in this file (near-
            # black 07-block, generic 42/98 material/vertex blocks) were
            # live-poked DEAD -- not wired.
            "id": "spin_attack_trail",
            "name": "Spin Attack Trail",
            "description": "Up-B swirling blade/disc trail core and glow colors",
            "target_file": "EfLkData.dat",
            "shared": True,
            "sharedWith": ["Young Link"],
            "owner": "Link",
            "offsets": {
                "color1": {"start": 0x5510, "size": 3, "format": "RGB"},
                "color2": {"start": 0x5514, "size": 3, "format": "RGB"}
            },
            "vanilla": {
                "color1": "FFFFFF",
                "color2": "0000FF"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Up-B trail bright core", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Up-B trail tint/glow", "format": "RGB"}
            ]
        }
    ],
    "Young Link": [
        {
            "id": "sword",
            "name": "Sword Trail",
            "description": "Sword swing trail colors",
            "target_file": "PlCl.dat",
            "offsets": {
                "inner": {"start": 0x3792, "size": 3, "format": "RGB"},
                "outer": {"start": 0x3796, "size": 3, "format": "RGB"},
                "alpha_blade": {"start": 0x3790, "size": 1, "format": "BYTE"},
                "alpha_tail": {"start": 0x3791, "size": 1, "format": "BYTE"}
            },
            "vanilla": {
                "inner": "00FFFF",     # Cyan
                "outer": "FFFFFF",     # White
                "alpha_blade": "FF",
                "alpha_tail": "00"
            },
            "properties": [
                {"id": "inner", "name": "Inner Edge", "description": "Color along the hilt-side edge of the trail", "format": "RGB"},
                {"id": "outer", "name": "Outer Edge", "description": "Color along the tip-side edge of the trail", "format": "RGB"}
            ]
        }
    ],
    "Pikachu": [
        {
            "id": "thunder",
            "name": "Thunder",
            "description": "Down-B Thunder bolt colors",
            "target_file": "PlPk.dat",
            "format": "07_07_07",
            # NOT shared with Pichu: these offsets live in Pikachu's own
            # PlPk.dat; Pichu's bolt reads PlPc.dat (audit 2026-07 confirmed a
            # PlPk patch leaves Pichu's thunder vanilla). Pichu has his own
            # entry below.
            # 07 07 07 04 format at 0xC354
            "offsets": {
                "color1": {"start": 0xC358, "size": 3, "format": "RGB"},
                "color2": {"start": 0xC35C, "size": 3, "format": "RGB"}
            },
            "vanilla": {
                "color1": "FFFFFF",  # White
                "color2": "FFFF00"   # Yellow
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Main bolt color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Bolt glow color", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07-02 from research/docs-research/effect-maps/pikachu.md
            # (MAP-LIVE verified 2026-07-02, tests/artifacts/
            # datram-probe-pikachu-airjolt/). AERIAL thunder-jolt half of the
            # neutral-B move: 4 CF particle records + 1 prim-only record in
            # EfPkData.dat (script index 1-4). Grounded neutral-B only fires
            # the PlPk ground bolt (separate extra, pikachu_thunder_jolt_ground)
            # -- the main sweep's neutralb missed this half entirely; only
            # confirmed via an AIRBORNE neutral-B. PRIM (marker+2) = bright
            # starburst core, ENV (colorpos+7) = outer radial lens glow
            # (dominates sustained tint, template lesson 3). Named separately
            # from the down-B 'thunder' extra above (do NOT touch/collide).
            "id": "pikachu_thunder_jolt_air",
            "name": "Thunder Jolt (Aerial)",
            "description": "Aerial neutral-B thunder jolt starburst and lens-flare colors",
            "target_file": "EfPkData.dat",
            "offsets": {
                "jolt_air_mid_c1": {"format": "RGB", "offsets": [0x168]},
                "jolt_air_mid_c2": {"format": "RGB", "offsets": [0x16F]},
                "jolt_air_outerflare_c1": {"format": "RGB", "offsets": [0x1D0]},
                "jolt_air_outerflare_c2": {"format": "RGB", "offsets": [0x1D7]},
                "jolt_air_midflare_c1": {"format": "RGB", "offsets": [0x238]},
                "jolt_air_midflare_c2": {"format": "RGB", "offsets": [0x23F]},
                "jolt_air_innerborder_c1": {"format": "RGB", "offsets": [0x2A0]},
                "jolt_air_innerborder_c2": {"format": "RGB", "offsets": [0x2A7]},
                "jolt_air_innertri_c1": {"format": "RGB", "offsets": [0x2AD]}
            },
            "vanilla": {
                "color1": "FFFFFF",
                "color2": "6681FA",
                "jolt_air_mid_c1": "FFFFFF",
                "jolt_air_mid_c2": "6681FA",
                "jolt_air_outerflare_c1": "0B0BE6",
                "jolt_air_outerflare_c2": "07078F",
                "jolt_air_midflare_c1": "8FD6FF",
                "jolt_air_midflare_c2": "0C0CFF",
                "jolt_air_innerborder_c1": "FE061B",
                "jolt_air_innerborder_c2": "FB9E14",
                "jolt_air_innertri_c1": "FFFFFF"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Starburst core and inner triangle color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Outer/mid lens-flare glow color", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07-02, same mission as pikachu_thunder_jolt_air.
            # GROUND half of the thunder jolt -- lives in PlPk.dat (the
            # traveling bolt article), a separate file/home from the aerial
            # EfPk CF group (config schema = one target_file per extra, see
            # luigi_fireball/luigi_fireball_smoke precedent). Grounded
            # neutral-B: the traveling jolt bolt went green-arc + magenta,
            # spawn starburst teal, cheek spark purple (LIVE-confirmed).
            # jolt_gnd_head is a single cyan-poked RGB (no separate c2).
            "id": "pikachu_thunder_jolt_ground",
            "name": "Thunder Jolt (Ground Bolt)",
            "description": "Grounded neutral-B thunder jolt traveling bolt colors",
            "target_file": "PlPk.dat",
            "offsets": {
                "jolt_gnd_a_c1": {"format": "RGB", "offsets": [0x14E00]},
                "jolt_gnd_a_c2": {"format": "RGB", "offsets": [0x14E04]},
                "jolt_gnd_b_c1": {"format": "RGB", "offsets": [0x14ECC]},
                "jolt_gnd_b_c2": {"format": "RGB", "offsets": [0x14ED0]},
                "jolt_gnd_c_c1": {"format": "RGB", "offsets": [0x14F98]},
                "jolt_gnd_c_c2": {"format": "RGB", "offsets": [0x14F9C]},
                "jolt_gnd_d_c1": {"format": "RGB", "offsets": [0x15064]},
                "jolt_gnd_d_c2": {"format": "RGB", "offsets": [0x15068]},
                "jolt_gnd_head_c1": {"format": "RGB", "offsets": [0x151F4]}
            },
            "vanilla": {
                "color1": "B2E5FF",
                "color2": "0000FF",
                "jolt_gnd_a_c1": "B2E5FF",
                "jolt_gnd_a_c2": "0000FF",
                "jolt_gnd_b_c1": "B2E5FF",
                "jolt_gnd_b_c2": "0000FF",
                "jolt_gnd_c_c1": "B2E5FF",
                "jolt_gnd_c_c2": "0000FF",
                "jolt_gnd_d_c1": "B2E5FF",
                "jolt_gnd_d_c2": "0000FF",
                "jolt_gnd_head_c1": "004CFF"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Traveling bolt core and spawn head color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Traveling bolt glow color", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07-02 from research/docs-research/effect-maps/pikachu.md.
            # GROUND forward-smash electric arc, 4 070707 model-region
            # blocks in EfPkData.dat (0x148xx cluster). LIVE-verified: fsmash
            # arc turned green+magenta; the byte-identical AIR clone
            # (0x17Cxx) did NOT respond to fsmash/nair/dsmash solo -- NOT
            # bundled here (pending punching-bag/EYEBALL, see spec open lead
            # #2). Ship ground-only.
            "id": "pikachu_fsmash",
            "name": "Forward Smash Arc",
            "description": "Forward smash electric arc and ball colors",
            "target_file": "EfPkData.dat",
            "offsets": {
                "fsmash_pre_c1": {"format": "RGB", "offsets": [0x148E0]},
                "fsmash_pre_c2": {"format": "RGB", "offsets": [0x148E4]},
                "fsmash_aura1_c1": {"format": "RGB", "offsets": [0x14C84]},
                "fsmash_aura1_c2": {"format": "RGB", "offsets": [0x14C88]},
                "fsmash_aura2_c1": {"format": "RGB", "offsets": [0x14D50]},
                "fsmash_aura2_c2": {"format": "RGB", "offsets": [0x14D54]},
                "fsmash_ball_c1": {"format": "RGB", "offsets": [0x14E10]},
                "fsmash_ball_c2": {"format": "RGB", "offsets": [0x14E14]}
            },
            "vanilla": {
                "color1": "CCE5FF",
                "color2": "0000FF",
                "fsmash_pre_c1": "CCE5FF",
                "fsmash_pre_c2": "0000FF",
                "fsmash_aura1_c1": "CCE5FF",
                "fsmash_aura1_c2": "0000FF",
                "fsmash_aura2_c1": "CCE5FF",
                "fsmash_aura2_c2": "0000FF",
                "fsmash_ball_c1": "FFFFFF",
                "fsmash_ball_c2": "004CFF"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Arc core and ball color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Arc glow and ball glow color", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07-02 from research/docs-research/effect-maps/efcodata.md §6b
            # "Shippable-now summary". EfCoData.dat is the CAST-SHARED common
            # effect bank (not per-character) -- this pool of 25 scripts is
            # the generic 15070 "Purple Electric Pack" target: subaction
            # event-GFX spawned sparks with no attributable single-move
            # C-caller, so semantics come from a LIVE poke, not decomp
            # cross-ref. MAP-LIVE 2026-07-02 (tests/artifacts/
            # datram-probe-efcodata-zelda/): poked 9 of the 25 records green
            # while Zelda took a jab hit -- the body-wide BLUE ELECTRIC ARC +
            # RADIAL SPARK RAYS that flash on hitlag turned bright GREEN
            # (electric_pool_on_jab-jab-f12.png vs vanilla-jab-f12.png). This
            # is the cast-wide ON-HIT / HITLAG electric spark burst that
            # fires on EVERY character when they take a hit -- verified as a
            # group; the remaining un-poked records are the same 15070 sweep
            # (same look, same subaction-GFX provenance) and ship with the
            # group per the spec (isolating each of 25 records individually
            # was not needed to ship).
            #
            # Per template lesson 12: the group's vanilla bytes are NOT
            # uniform (a shared "vanilla" string would ship a wrong
            # reset/preview color) -- every one of the 35 records below is
            # its OWN layer_id with its OWN byte-verified vanilla (verified
            # 2026-07-02 against storage/test-base/files/EfCoData.dat, md5
            # 739290ead708aeb98bd5118c1abe4a34). Records are split by
            # in-script ordinal, not by hue family: `_c1` = each script's
            # FIRST/primary color record (25 scripts, one each), `_c2` = the
            # ADDITIONAL records in scripts that carry more than one env/prim
            # operand (10 records across scripts 0/13/29/30/268) -- this
            # keeps the DualColorEditorModal's two-picker fan-out
            # (`key.endsWith('_c1')`/`_c2`) meaningful while every record
            # still gets its own exact-byte vanilla entry. Owner: Pikachu
            # (most-associated character for an electric effect, same "surface
            # under a real roster entry" precedent as common_fire/common_flash
            # under Zelda).
            #
            # ACCURACY FIX 2026-07-02 (extras accuracy pass): the electric hit
            # spark in EfCoData.dat only spawns when a hitbox whose HitElement
            # == Electric(2) CONNECTS -- so it is NOT cast-wide. The old config
            # listed the whole roster (Marth, Roy, Link, Mario, ... none of
            # which own an electric attack) and claimed "flashes on EVERY
            # character", which was wrong. sharedWith is now DATA-DERIVED:
            # backend/shared/rendering/hitbox_elements.py walks every vanilla Pl<XX>.dat
            # subaction table, decodes Create Hitbox (cmd 0x0B) events, and
            # keeps the characters that spawn at least one Element==2 hitbox
            # (list = roster minus owner Pikachu; self-test: Zelda electric,
            # Pikachu/Pichu many, Marth ZERO). See research/docs-research/effect-maps/
            # efcodata.md for the per-character electric-move table.
            # Anti-color: green 00FF00 (vanilla operands are blue/white/cyan-
            # family per spec lesson 6/11; the two outlier warm records at
            # 0xDDB/0x15BA are still far enough from green).
            "id": "common_electric",
            "name": "Electric Hit Spark",
            "description": ("On-hit electric spark burst color -- the blue electric arc + "
                             "radial spark rays that flash when an ELECTRIC-element attack "
                             "connects (Pikachu/Pichu thunder & jolts, Zelda's jab + "
                             "lightning kicks, Fox/Falco shine, Ness's PK Thunder & electric "
                             "aerials, Mewtwo's electric hits, Ganondorf's jab/dair, Samus's "
                             "screw attack/grapple, Sheik's needles/side-B, Doc's electric "
                             "fsmash, Kirby's copied neutral-B, G&W's Judgment 6). Shared out "
                             "of the common effects file; characters with no electric attack "
                             "(Marth, Roy, Link, Mario, ...) never trigger it"),
            "target_file": "EfCoData.dat",
            "shared": True,
            # DATA-DERIVED via backend/shared/rendering/hitbox_elements.py (vanilla
            # Element==2 hitbox scan); roster minus owner Pikachu.
            "sharedWith": ["C. Falcon", "Falco", "Fox", "Ganondorf", "Kirby", "Mewtwo",
                           "Ness", "Pichu", "Samus", "Sheik", "Zelda", "Dr. Mario", "G&W"],
            "owner": "Pikachu",
            "offsets": {
                # script 0 (5 records: 1 primary + 4 additional)
                "elec_s0_a_c1": {"format": "RGB", "offsets": [0xDC5]},
                "elec_s0_b_c2": {"format": "RGB", "offsets": [0xDDB]},
                "elec_s0_c_c2": {"format": "RGB", "offsets": [0xDF1]},
                "elec_s0_d_c2": {"format": "RGB", "offsets": [0xE0F]},
                "elec_s0_e_c2": {"format": "RGB", "offsets": [0xE1D]},
                # script 1
                "elec_s1_c1": {"format": "RGB", "offsets": [0xEAD]},
                # script 13 (4 records: 1 primary + 3 additional)
                "elec_s13_a_c1": {"format": "RGB", "offsets": [0x1384]},
                "elec_s13_b_c2": {"format": "RGB", "offsets": [0x13AB]},
                "elec_s13_c_c2": {"format": "RGB", "offsets": [0x13BA]},
                "elec_s13_d_c2": {"format": "RGB", "offsets": [0x13D7]},
                # script 14
                "elec_s14_c1": {"format": "RGB", "offsets": [0x1425]},
                # script 16
                "elec_s16_c1": {"format": "RGB", "offsets": [0x14F5]},
                # script 17
                "elec_s17_c1": {"format": "RGB", "offsets": [0x1560]},
                # script 18
                "elec_s18_c1": {"format": "RGB", "offsets": [0x15BA]},
                # script 19
                "elec_s19_c1": {"format": "RGB", "offsets": [0x1609]},
                # script 29 (2 records)
                "elec_s29_a_c1": {"format": "RGB", "offsets": [0x1C17]},
                "elec_s29_b_c2": {"format": "RGB", "offsets": [0x1C24]},
                # script 30 (2 records)
                "elec_s30_a_c1": {"format": "RGB", "offsets": [0x1C8D]},
                "elec_s30_b_c2": {"format": "RGB", "offsets": [0x1C9A]},
                # script 31
                "elec_s31_c1": {"format": "RGB", "offsets": [0x1CFF]},
                # script 73
                "elec_s73_c1": {"format": "RGB", "offsets": [0x2F15]},
                # script 161
                "elec_s161_c1": {"format": "RGB", "offsets": [0x5550]},
                # script 162
                "elec_s162_c1": {"format": "RGB", "offsets": [0x55B1]},
                # script 268 (2 records)
                "elec_s268_a_c1": {"format": "RGB", "offsets": [0x854E]},
                "elec_s268_b_c2": {"format": "RGB", "offsets": [0x855B]},
                # script 269
                "elec_s269_c1": {"format": "RGB", "offsets": [0x85B6]},
                # script 270
                "elec_s270_c1": {"format": "RGB", "offsets": [0x860E]},
                # script 306
                "elec_s306_c1": {"format": "RGB", "offsets": [0x9779]},
                # script 332
                "elec_s332_c1": {"format": "RGB", "offsets": [0xA1DD]},
                # script 423
                "elec_s423_c1": {"format": "RGB", "offsets": [0xCDB7]},
                # script 424
                "elec_s424_c1": {"format": "RGB", "offsets": [0xCE18]},
                # script 425
                "elec_s425_c1": {"format": "RGB", "offsets": [0xCE84]},
                # script 426
                "elec_s426_c1": {"format": "RGB", "offsets": [0xCEEF]},
                # script 448
                "elec_s448_c1": {"format": "RGB", "offsets": [0xD87D]},
                # script 537
                "elec_s537_c1": {"format": "RGB", "offsets": [0x10019]}
            },
            "vanilla": {
                "color1": "FFF305",
                "color2": "FF0000",
                "elec_s0_a_c1": "FFF305",
                "elec_s0_b_c2": "FF0000",
                "elec_s0_c_c2": "1155FF",
                "elec_s0_d_c2": "1FA60D",
                "elec_s0_e_c2": "26CF10",
                "elec_s1_c1": "1165FF",
                "elec_s13_a_c1": "0063FF",
                "elec_s13_b_c2": "0061FF",
                "elec_s13_c_c2": "000000",
                "elec_s13_d_c2": "003FFF",
                "elec_s14_c1": "A30CFF",
                "elec_s16_c1": "82A1F8",
                "elec_s17_c1": "210CFF",
                "elec_s18_c1": "3FFF00",
                "elec_s19_c1": "210CFF",
                "elec_s29_a_c1": "E6FEFF",
                "elec_s29_b_c2": "0D6DFC",
                "elec_s30_a_c1": "FFFFFF",
                "elec_s30_b_c2": "FBFEB5",
                "elec_s31_c1": "5F9BFC",
                "elec_s73_c1": "4FA4FF",
                "elec_s161_c1": "A1C7FF",
                "elec_s162_c1": "B9DBFD",
                "elec_s268_a_c1": "BFFEC7",
                "elec_s268_b_c2": "4EFA48",
                "elec_s269_c1": "F870C8",
                "elec_s270_c1": "82DBF8",
                "elec_s306_c1": "FC94FF",
                "elec_s332_c1": "210CFF",
                "elec_s423_c1": "F9101C",
                "elec_s424_c1": "190DFC",
                "elec_s425_c1": "9CF5FD",
                "elec_s426_c1": "7AF2FF",
                "elec_s448_c1": "0E07D9",
                "elec_s537_c1": "70F6FF"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Electric spark burst color (every script's primary record)", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Additional spark records in the multi-record scripts", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07-02 from research/docs-research/effect-maps/efcodata.md §6b.
            # s95 (EfCoData script 95) is the CASTER-SIDE half of Pikachu's
            # neutral-B Thunder Jolt -- MAP-LIVE 2026-07-02 (Pikachu solo,
            # tests/artifacts/datram-probe-efcodata-pika/): poking all 3
            # records magenta turned the small dissipation/cheek sparkles at
            # Pikachu magenta-white (thunder_jolt_spark-neutralb-f36.png vs
            # vanilla-neutralb-f36.png -- pink-white star bursts at chin+foot
            # absent in vanilla). HONESTY NOTE (also in the description
            # below): the big blue Thunder Jolt fountain / travelling bolt is
            # a SEPARATE texture-driven article effect and is UNCHANGED by
            # this extra -- s95 only owns the small caster-side spark, this
            # is a real but SUBTLE recolor, not the marquee jolt visual.
            # sharedWith Luigi: s95 is also the side-B "remove" GFX per the
            # spec's §3a table (0x50A), but that's a housekeeping despawn
            # flash, not a visible Luigi move -- listed for honesty per the
            # also-affects rule, not expected to be visually meaningful for
            # Luigi. All 3 offsets byte-verified against vanilla
            # EfCoData.dat 2026-07-02.
            "id": "thunder_jolt_spark",
            "name": "Thunder Jolt Cheek Spark",
            "description": ("Subtle caster-side dissipation/cheek sparkle on Pikachu's "
                             "neutral-B Thunder Jolt -- this is a small accent spark, NOT "
                             "the big blue jolt fountain/bolt itself (that is a separate "
                             "texture effect and is unaffected). Also affects the Luigi "
                             "side-B remove flash (shared common-bank script)"),
            "target_file": "EfCoData.dat",
            "shared": True,
            "sharedWith": ["Luigi"],
            "owner": "Pikachu",
            # NOTE: the record at 0x3930 is a 3rd operand (another
            # env/ambient-family byte per the ptcl_parse structural read) --
            # folded into the `_c2` (secondary/glow) bucket alongside 0x3921
            # since the editor UI only fans two pickers (`_c1`/`_c2`, no
            # `_c3` precedent anywhere else in this config); both are
            # grayscale-family ambient tones so sharing one picker is a
            # faithful grouping, not a lossy one.
            "offsets": {
                "jolt_spark_a_c1": {"format": "RGB", "offsets": [0x391A]},
                "jolt_spark_a_c2": {"format": "RGB", "offsets": [0x3921]},
                "jolt_spark_b_c2": {"format": "RGB", "offsets": [0x3930]}
            },
            "vanilla": {
                "color1": "EAE7E9",
                "color2": "6E6E6E",
                "jolt_spark_a_c1": "EAE7E9",
                "jolt_spark_a_c2": "6E6E6E",
                "jolt_spark_b_c2": "575757"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Cheek spark core color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Cheek spark ambient/glow color", "format": "RGB"}
            ]
        }
    ],
    "Pichu": [
        {
            "id": "thunder",
            "name": "Thunder",
            "description": "Down-B Thunder bolt colors",
            "target_file": "PlPc.dat",
            "format": "07_07_07",
            # Same 07 07 07 04 block as Pikachu's, at Pichu's own offset 0xBF14
            "offsets": {
                "color1": {"start": 0xBF18, "size": 3, "format": "RGB"},
                "color2": {"start": 0xBF1C, "size": 3, "format": "RGB"}
            },
            "vanilla": {
                "color1": "FFFFFF",  # White
                "color2": "FFFF00"   # Yellow
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Main bolt color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Bolt glow color", "format": "RGB"}
            ]
        }
    ],
    "Ness": [
        {
            # WIRE 2026-07-02 from research/docs-research/effect-maps/ness.md
            # (MAP-LIVE verified 2026-07-02, tests/artifacts/
            # datram-probe-ness/). Down-B PSI Magnet absorb aura --
            # EfNsData.Models[2], 7 070707 model-region blocks (c1 = marker+4
            # bright core, c2 = marker+8 electric-blue arc glow -- what the
            # 15070 "Purple Electric Pack" recolored). LIVE: poking these
            # turned the whole down-B aura green-core + magenta-arcs.
            # Model[0]/[1] are the on-hit bat/yo-yo sparkle -- NOT wired yet
            # (solo-unverifiable, pending punching-bag harness, spec open
            # lead #2/#3). Per-record vanilla bytes DIFFER (psimag_a's c1 is
            # 00CCFF, not white like the rest) -- byte-verified against
            # storage/test-base/files/EfNsData.dat 2026-07-02, kept as
            # per-record keys (template lesson 12).
            "id": "ness_psi_magnet",
            "name": "PSI Magnet",
            "description": "Down-B PSI Magnet absorb aura core and glow colors",
            "target_file": "EfNsData.dat",
            "offsets": {
                "psimag_a_c1": {"format": "RGB", "offsets": [0x163B8]},
                "psimag_a_c2": {"format": "RGB", "offsets": [0x163BC]},
                "psimag_b_c1": {"format": "RGB", "offsets": [0x16478]},
                "psimag_b_c2": {"format": "RGB", "offsets": [0x1647C]},
                "psimag_c_c1": {"format": "RGB", "offsets": [0x16538]},
                "psimag_c_c2": {"format": "RGB", "offsets": [0x1653C]},
                "psimag_d_c1": {"format": "RGB", "offsets": [0x165F8]},
                "psimag_d_c2": {"format": "RGB", "offsets": [0x165FC]},
                "psimag_e_c1": {"format": "RGB", "offsets": [0x166B8]},
                "psimag_e_c2": {"format": "RGB", "offsets": [0x166BC]},
                "psimag_f_c1": {"format": "RGB", "offsets": [0x16778]},
                "psimag_f_c2": {"format": "RGB", "offsets": [0x1677C]},
                "psimag_g_c1": {"format": "RGB", "offsets": [0x16838]},
                "psimag_g_c2": {"format": "RGB", "offsets": [0x1683C]}
            },
            "vanilla": {
                "color1": "FFFFFF",
                "color2": "0000FF",
                "psimag_a_c1": "00CCFF",
                "psimag_a_c2": "0000FF",
                "psimag_b_c1": "FFFFFF",
                "psimag_b_c2": "0000FF",
                "psimag_c_c1": "FFFFFF",
                "psimag_c_c2": "007FFF",
                "psimag_d_c1": "FFFFFF",
                "psimag_d_c2": "007FFF",
                "psimag_e_c1": "FFFFFF",
                "psimag_e_c2": "0066FF",
                "psimag_f_c1": "FFFFFF",
                "psimag_f_c2": "007FFF",
                "psimag_g_c1": "FFFFFF",
                "psimag_g_c2": "007FFF"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Absorb aura bright core color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Absorb aura electric-blue arc glow color", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07-02 from research/docs-research/effect-maps/ness.md. PK
            # Thunder ball flare + tail/bolt -- lives in PlNs.dat (the
            # article's own animated model), NOT EfNsData (config schema =
            # one target_file per extra). LIVE-confirmed: ball flare ->
            # magenta-poke offsets, tail/bolt -> green-poke offsets. Tail/aura
            # (4 records) + ball flare (2 records) + lightning (4 records,
            # RENUMBERED lightning1-4 here). CRITICAL FIX: the spec's
            # 0x2D82E poke for "lightning4" landed on non-color bytes
            # (F90000, the tail of c1) -- re-derived from the record's own
            # 07 07 07 04 marker (@0x2D828, matching the other 3 lightning
            # records' identical structure): c1 = marker+4 = 0x2D82C
            # (FFFFF9), c2 = marker+8 = 0x2D830 (0066FF). Byte-verified
            # against storage/test-base/files/PlNs.dat 2026-07-02 -- ships
            # at the re-derived offset, not the spec's original cite.
            "id": "ness_pk_thunder",
            "name": "PK Thunder",
            "description": "Up-B PK Thunder ball flare and tail/bolt colors",
            "target_file": "PlNs.dat",
            "offsets": {
                "tip_c1": {"format": "RGB", "offsets": [0x2403C]},
                "tail1_c1": {"format": "RGB", "offsets": [0x2C3FC]},
                "tail2_c1": {"format": "RGB", "offsets": [0x2C77C]},
                "tail_main_c1": {"format": "RGB", "offsets": [0x2CAFC]},
                "ball_flare1_c2": {"format": "RGB", "offsets": [0x2D3D0]},
                "ball_flare2_c2": {"format": "RGB", "offsets": [0x2D530]},
                "lightning1_c1": {"format": "RGB", "offsets": [0x2D5F0]},
                "lightning2_c1": {"format": "RGB", "offsets": [0x2D6B0]},
                "lightning3_c1": {"format": "RGB", "offsets": [0x2D770]},
                "lightning4_c1": {"format": "RGB", "offsets": [0x2D830]}
            },
            "vanilla": {
                "color1": "004CFF",
                "color2": "0000FF",
                "tip_c1": "004CFF",
                "tail1_c1": "004CFF",
                "tail2_c1": "004CFF",
                "tail_main_c1": "004CFF",
                "ball_flare1_c2": "0000FF",
                "ball_flare2_c2": "0000FF",
                "lightning1_c1": "0033FF",
                "lightning2_c1": "0033FF",
                "lightning3_c1": "0033FF",
                "lightning4_c1": "0066FF"
            },
            "properties": [
                {"id": "color1", "name": "Tail/Bolt", "description": "Tail, lightning, and tip color", "format": "RGB"},
                {"id": "color2", "name": "Ball Flare", "description": "Ball flare and aura color", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07-02 from research/docs-research/effect-maps/items.md (the
            # items-pass MAP, bag-verified 2026-07-02). PK Fire burn PILLAR --
            # the article that spawns when the PK Fire bolt connects
            # (itnesspkfirepillar.c); its animated model + 070707 color blocks
            # live in PlNs.dat (the player file), NOT EfNsData -- neither PK
            # Fire item has an efSync_Spawn call. Three 07 07 07 04 markers:
            # bottom ring INSIDE (0x11A8C), MAIN fire aura (0x11B58), bottom
            # ring OUTSIDE (0x11DF8); c1 = marker+4 core, c2 = marker+8 glow
            # (template lesson 2). LIVE (punching-bag, DK dx=10): poking all 6
            # green/magenta turned the vanilla BLUE horizontal ring through
            # DK's midsection unmistakably GREEN with MAGENTA glow edges +
            # sparks at f24, whole pillar base green+purple at f32. The tall
            # ORANGE FIRE BODY column itself did NOT recolor -- that's a
            # separate texture (not this extra); only the ring accents + aura
            # glow (the 070707 c2 blocks) are colorable, matching vanilla's
            # own layout (007FFF blue rings editable, fire body textured).
            # Per-record vanilla bytes differ (aura c1 FFFFE5 cream vs rings'
            # c1 FFFFFF) -- kept as per-record keys per template lesson 12;
            # byte-verified against storage/test-base/files/PlNs.dat
            # 2026-07-02. On-hit only (the pillar only forms when PK Fire
            # connects) -- fully demonstrable every time via the bag, not
            # harness-blocked. A same-region 8-block 42_48 material follow-up
            # (diffuse @0x11B00/0x11BCC/0x11C6C/0x11D0C/0x11DAC/0x11E6C/
            # 0x11F0C/0x11F38) was poked magenta with NO visible change (same
            # class as the Mario-tornado-42 no-op) -- not wired.
            "id": "ness_pk_fire",
            "name": "PK Fire",
            "description": "Side-B PK Fire pillar's hit-ring and aura accent colors (the orange fire body itself is texture)",
            "target_file": "PlNs.dat",
            "offsets": {
                "pillar_ring_in_c1": {"format": "RGB", "offsets": [0x11A90]},
                "pillar_ring_in_c2": {"format": "RGB", "offsets": [0x11A94]},
                "pillar_aura_c1": {"format": "RGB", "offsets": [0x11B5C]},
                "pillar_aura_c2": {"format": "RGB", "offsets": [0x11B60]},
                "pillar_ring_out_c1": {"format": "RGB", "offsets": [0x11DFC]},
                "pillar_ring_out_c2": {"format": "RGB", "offsets": [0x11E00]}
            },
            "vanilla": {
                "color1": "FFFFFF",
                "color2": "007FFF",
                "pillar_ring_in_c1": "FFFFFF",
                "pillar_ring_in_c2": "007FFF",
                "pillar_aura_c1": "FFFFE5",
                "pillar_aura_c2": "FF9900",
                "pillar_ring_out_c1": "FFFFFF",
                "pillar_ring_out_c2": "007FFF"
            },
            "properties": [
                {"id": "color1", "name": "Ring Core", "description": "Pillar hit-ring core color (bottom rings, inside + outside)", "format": "RGB"},
                {"id": "color2", "name": "Aura Glow", "description": "Pillar aura and ring glow color (blue rings, orange aura)", "format": "RGB"}
            ]
        }
    ],
    "Mewtwo": [
        {
            "id": "shadow_ball",
            "name": "Shadow Ball",
            "description": "Shadow Ball colors",
            "target_file": "PlMt.dat",
            "format": "direct_rgb",
            # All five 07 07 07 04 blocks live-poke mapped 2026-07 (see
            # docs/dev/EXTRAS_AUDIT.md): thrown center @0x100AC, charging-ball
            # center @0x105CC (separate effect -- pre-fix mods looked inert
            # while charging), four inner-ball lightning bolts @0x102CC/
            # 0x1038C/0x1044C/0x1050C. In every block color1 (marker+4) is
            # the bright core (center flash / bolt line) and color2
            # (marker+8) the glow around it, so the charge/bolt layers fan
            # out from the same two pickers via the _c1/_c2 suffixes
            # (DualColorEditorModal convention, like falcon_punch).
            "offsets": {
                "color1": {"start": 0x100B0, "size": 3, "format": "RGB"},
                "color2": {"start": 0x100B4, "size": 3, "format": "RGB"},
                "charge_c1": {"start": 0x105D0, "size": 3, "format": "RGB"},
                "charge_c2": {"start": 0x105D4, "size": 3, "format": "RGB"},
                "bolts_c1": {"format": "RGB",
                             "offsets": [0x102D0, 0x10390, 0x10450, 0x10510]},
                "bolts_c2": {"format": "RGB",
                             "offsets": [0x102D4, 0x10394, 0x10454, 0x10514]}
            },
            "vanilla": {
                "color1": "FFFFFF",   # White center
                "color2": "0000FF",   # Blue glow
                "charge_c1": "FFFFFF",
                "charge_c2": "0000FF",
                "bolts_c1": "FFFFFF",
                "bolts_c2": "007FFF"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Center flash and bolt color (charging + thrown)", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Inner glow color", "format": "RGB"}
            ]
        },
        {
            # Up-smash (Galaxy Force) swirl colors -- EfMtData 07 07 07 04
            # marker @0xC754 (vanilla 66 00 CC / 00 00 00). Implemented from
            # the reference 🔴 list; the reference's 0xC758 cite is the
            # marker+4 color, the marker itself is 0xC754.
            "id": "upsmash",
            "name": "Up Smash Swirl",
            "description": "Up-smash swirl colors",
            "target_file": "EfMtData.dat",
            "format": "direct_rgb",
            "offsets": {
                "color1": {"start": 0xC758, "size": 3, "format": "RGB"},
                "color2": {"start": 0xC75C, "size": 3, "format": "RGB"}
            },
            "vanilla": {
                "color1": "6600CC",  # Purple
                "color2": "000000"   # Black
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Main swirl color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Swirl secondary color", "format": "RGB"}
            ]
        }
    ],
    "Fox": [
        {
            "id": "laser",
            "name": "Laser Color",
            "description": "Change laser beam colors",
            "target_file": "PlFx.dat",
            # Offset definitions for the 98 matrix format (Fox-specific).
            # center/tip = the bright white core line down the beam (audit
            # 2026-07, live-poke verified): tip is an 8-entry `80 00 08` RGB
            # matrix (leading point), center an 18-entry `98 00 12` RGB
            # matrix (line body). Both are also emitted by
            # find_laser_offsets relative to the wide/thin/outline cluster.
            "offsets": {
                "wide": {"start": 0x13E20, "end": 0x13E80, "format": "RGBY"},
                "thin": {"start": 0x13EC0, "end": 0x13F20, "format": "RGBY"},
                "outline": {"start": 0x13F60, "end": 0x13FC0, "format": "RGBY"},
                "tip": {"start": 0x14000, "end": 0x14023, "format": "RGB"},
                "center": {"start": 0x14023, "end": 0x1406E, "format": "RGB"}
            },
            # Vanilla/default colors (Fox's red laser + white center line)
            "vanilla": {
                "wide": "FC00",
                "thin": "FC00",
                "outline": "FC00",
                "tip": "FFFFFF",
                "center": "FFFFFF"
            },
            "properties": [
                {"id": "wide", "name": "Wide Layer", "description": "Transparent outer glow"},
                {"id": "thin", "name": "Thin Layer", "description": "Semi-transparent middle"},
                {"id": "outline", "name": "Outline", "description": "Opaque inner core"},
                {"id": "center", "name": "Center Line", "description": "Bright core line down the beam", "format": "RGB"},
                {"id": "tip", "name": "Center Tip", "description": "Leading tip of the core line", "format": "RGB"}
            ]
        },
        {
            "id": "sideb",
            "name": "Side-B Color",
            "description": "Illusion afterimage colors",
            "target_file": "PlFx.dat",
            "format": "42_48",
            # 42_48 format: 3 RGBA colors at a single offset
            "offsets": {
                "primary": {"start": 0x2204C, "size": 4, "format": "RGBA"},
                "secondary": {"start": 0x22050, "size": 4, "format": "RGBA"},
                "tertiary": {"start": 0x22054, "size": 4, "format": "RGBA"}
            },
            "vanilla": {
                "primary": "0099FFFF",
                "secondary": "CCE6FFFF",
                "tertiary": "FFFFFFFF"
            },
            "properties": [
                {"id": "primary", "name": "Primary", "description": "Main afterimage color"},
                {"id": "secondary", "name": "Secondary", "description": "Edge/gradient color"},
                {"id": "tertiary", "name": "Glow", "description": "Outer glow color"}
            ]
        },
        {
            "id": "upb",
            "name": "Up-B Color",
            "description": "Firefox/Firebird flame colors",
            "target_file": "EfFxData.dat",
            "shared": True,  # Shared between Fox and Falco
            "sharedWith": ["Falco"],  # Characters that share this extra
            "owner": "Fox",  # Which character owns the mods in storage
            "offsets": {
                # 98 matrix format for flame tip (mixed color/position data - needs safe mode)
                "tip": {"start": 0x1AC80, "end": 0x1AD00, "format": "RGBY", "vanilla": "FE60"},
                # 98 matrix format for firefox body when not textured
                "body": {"start": 0x1A880, "end": 0x1AA50, "format": "RGB", "vanilla": "FFFFFF"},
                # CF format - trailing fire (all sizes combined)
                # CF XX RR GG BB - color at offset+2
                "trail": {
                    "format": "CF",
                    "offsets": [
                        0x2EE, 0x2F4, 0x324, 0x32B,  # Large trailing fire
                        0x52E, 0x534,  # Big trailing fire
                        0x55E  # Central mid-flight fire clumps (CF @0x55E, live-verified 2026-07-03)
                    ]
                },
                # Small trailing fire (audit 2026-07: previously uncovered).
                # Real CF markers verified against vanilla bytes -- the
                # reference doc's citations are off by one for the first four.
                "small_trail": {
                    "format": "CF",
                    "offsets": [0x382, 0x392, 0x3A2, 0x3B2, 0x3C4]
                },
                # Square dot particles during travel
                "dots": {
                    "format": "CF",
                    "offsets": [0x43A, 0x44A]
                },
                # Lines coming off the charge
                "charge_lines": {
                    "format": "CF",
                    "offsets": [0x5AF]
                },
                # Lens flare while in motion. Marker verified at 0x1A508 (the
                # reference cites the 0x1A500 line start, which includes an
                # 85 80 08 0F prefix -- writing there corrupts the effect
                # script and hangs the game at Firefox launch).
                "flare": {"start": 0x1A508, "format": "070707"},
                # 07 07 07 04 format - fire rings
                # Pattern: 07 07 07 04 RR GG BB 00 RR GG BB - colors at +4 and +8
                "rings": {
                    "format": "070707",
                    "offsets": [0x1B454, 0x1B520]  # Actual marker positions
                }
            },
            "vanilla": {
                "tip": "FE60",      # Fire orange (RGBY)
                "body": "FFFFFF",   # White (RGB)
                "trail": "FFFFFF",  # White (RGB)
                "small_trail": "FFF88F",
                "dots": "FF290C",
                "charge_lines": "FFFFFF",
                "flare": "FFE54C",
                "rings": "FFFF00"   # Yellow (RGB) - from FF FF CC / FF 7F 00
            },
            "properties": [
                {"id": "tip", "name": "Flame Tip", "description": "Fire effect at the tip (RGBY)"},
                {"id": "body", "name": "Body Glow", "description": "Firefox body when charging"},
                {"id": "trail", "name": "Trail Fire", "description": "Trailing fire particles"},
                {"id": "small_trail", "name": "Small Trail Fire", "description": "Small trailing fire particles"},
                {"id": "dots", "name": "Travel Dots", "description": "Square dot particles"},
                {"id": "charge_lines", "name": "Charge Lines", "description": "Lines coming off the charge"},
                {"id": "flare", "name": "Motion Flare", "description": "Lens flare while flying"},
                {"id": "rings", "name": "Fire Rings", "description": "Circular fire rings"}
            ]
        },
        {
            "id": "upb_texture",
            "name": "Up-B Fire Texture",
            "description": "Firefox/Firebird flame color",
            "target_file": "EfFxData.dat",
            "type": "texture",  # Texture type - CLI export/hue-shift/import (see vault/extras/textures.py)
            # Audit 2026-07 (decomp: efSync 0x48C -> effect 3004 = table entry
            # 4 = Models_4 = the FLIGHT effect): the model lists the flame
            # image twice (tex idx 1 and idx 2 = the flight cone streamers),
            # but both TObjs SHARE one image node -- importing at idx 1
            # recolors both. Do NOT also target idx 2: a second export/shift/
            # import round-trips the shared image back toward vanilla.
            # Charge Model 3 has grayscale streak/swirl textures. Fox's orange
            # charge flames come from a separate EfCoData script family;
            # see the retired fox-charge-correction report (git history before 2026-10-03).
            "texture_path": "effFoxDataTable/Models_4_/RootJoint",
            "texture_index": 1,
            "shared": True,  # Shared between Fox and Falco
            "sharedWith": ["Falco"],
            "owner": "Fox",
            "vanilla_hue": 15,  # Orange-red -- recorded reference AND the apply-time
                                # shift source (see textures.py's "Vanilla-hue
                                # SOURCE" docstring section)
            # Task #12 migration (2026-07-02): ColorPicker UX, not a hue
            # slider -- editor sends {"color": "RRGGBB"}, backend converts to
            # degrees via hex_to_hue(color) - vanilla_hue. Nested inside
            # upb's UpBEditorModal (modifications.fire). Old saved mods'
            # {"hue": degrees} shape is still accepted forever
            # (backend/vault/extras/textures.py resolve_hue_shift).
            "properties": [
                {"id": "color", "name": "Fire Color", "description": "Firefox/Firebird flame texture color", "format": "RGB"}
            ]
        },
        {
            # Corrected 2026-09-09: this is the FLIGHT puff bitmap, not charge
            # fire. Preserve the existing ID and palette layout for saved mods.
            # Model 4's animation emits particle 3004 -> scripts 5/9 use
            # texGroup 3 (8-frame CI8 32x32, per-frame RGB5A3 palettes).
            # The same puffs are tinted by upb.trail; the nested upb_texture
            # controls the separate model streamers. The final export retained
            # all 2582 changed palette bytes (cyan), with image indices intact.
            # See the retired fox-charge-correction report (git history before 2026-10-03).
            "id": "upb_charge_fire",
            "part_of": "upb",  # edited inside the upb unit (see UNIT_PARTS)
            "name": "Flight Fire Texture",
            "description": "Firefox/Firebird fire-puff texture during flight. Works with the Up-B trail colors.",
            "target_file": "EfFxData.dat",
            "format": "texture_recolor",
            "shared": True,
            "sharedWith": ["Falco"],
            "owner": "Fox",
            "texture": {
                "gx_format": 9,   # CI8
                "width": 32,
                "height": 32,
                "images": [
                    {"offset": "0xD6E0", "palette": "0xF6E0"},
                    {"offset": "0xDAE0", "palette": "0xF8E0"},
                    {"offset": "0xDEE0", "palette": "0xFAE0"},
                    {"offset": "0xE2E0", "palette": "0xFCE0"},
                    {"offset": "0xE6E0", "palette": "0xFEE0"},
                    {"offset": "0xEAE0", "palette": "0x100E0"},
                    {"offset": "0xEEE0", "palette": "0x102E0"},
                    {"offset": "0xF2E0", "palette": "0x104E0"}
                ],
                "palette_format": 2  # RGB5A3
            },
            "vanilla_dominant_hue": 35.7,
            "vanilla": {
                "color1": "FF9400"  # representative vanilla swatch (hue 35.7 at full S/V)
            },
            "properties": [
                {"id": "color1", "name": "Flight Fire Texture", "description": "Fire-puff texture during flight; Up-B trail colors also tint these puffs", "format": "RGB"}
            ]
        },
        {
            # LIVE 2026-09-09: Fox SpecialHiHold emits common particle 298 at
            # animation frame 15 -> s299 broad flames + s300 thin wisps.
            # Independent s299/s300 probes and Falco's negative consumer test
            # are recorded in the retired fox-charge-correction report (git history before 2026-10-03). Fox-only UI;
            # target is the shared EfCoData bank, not the EfFx flight bitmap.
            # RGB positions are marker-verified operands; alpha is untouched.
            # Swatches are representative. Exact restore reads each operand's
            # distinct vanilla reference bytes via restore_extra_color_bytes.
            "id": "charge_flames",
            "part_of": "upb",  # edited inside the upb unit (see UNIT_PARTS)
            "name": "Charge Flames",
            "description": "Fox's rising flame puffs and thin wisps while charging Firefox. Uses a common-bank effect triggered by Fox's charge.",
            "target_file": "EfCoData.dat",
            "offsets": {
                "flame_c1": {"format": "RGB", "offsets": [0x93C4, 0x93D1, 0x93ED, 0x93FA]},
                "flame_c2": {"format": "RGB", "offsets": [0x93CB, 0x93D8, 0x93F4, 0x9401]},
                "wisp_c1": {"format": "RGB", "offsets": [0x945A, 0x9467, 0x947A]},
                "wisp_c2": {"format": "RGB", "offsets": [0x9461, 0x946E, 0x9481]},
            },
            "vanilla": {
                "flame_c1": "FEF3A0", "flame_c2": "FC885A",
                "wisp_c1": "FEF6B9", "wisp_c2": "FD9A73",
            },
            "properties": [
                {"id": "flame_c1", "name": "Core", "description": "Broad rising flame puffs: primary color", "format": "RGB"},
                {"id": "flame_c2", "name": "Tint", "description": "Broad rising flame puffs: blended tint", "format": "RGB"},
                {"id": "wisp_c1", "name": "Core", "description": "Thin flame wisps: primary color", "format": "RGB"},
                {"id": "wisp_c2", "name": "Tint", "description": "Thin flame wisps: blended tint", "format": "RGB"},
            ],
        },
        {
            "id": "shine",
            "name": "Shine Color",
            "description": "Reflector shield colors (two-color gradient)",
            "target_file": "EfFxData.dat",
            "shared": True,  # Shared between Fox and Falco
            "sharedWith": ["Falco"],  # Characters that share this extra
            "owner": "Fox",  # Which character owns the mods in storage
            "format": "shine_gradient",  # Special two-color gradient format
            # SECOND capability on the same extra (2026-09-09): "image shines"
            # -- the community mods with a picture inside the hexagon (NERV,
            # Honeycomb, Trollface, ...). Those replace effFoxDataTable model
            # 0's DObj with a textured quad, so they have no color operands
            # and the offsets below read garbage from them. A mod carrying an
            # image is installed by vault/routes/extras/effect_model.py instead
            # (append + repoint, fully revertible); everything else in the
            # file -- including the gradient bytes underneath and the sparkle
            # /flash colors -- is untouched. Both kinds live in this one
            # extra's mod list because both patch the same model.
            "image_model": {
                "root_index": 0,
                "root_symbol": "effFoxDataTable",
                "model_index": 0,   # effFoxDataTable Models_0 == the shine
                "width": 256,
                "height": 256,
                "gx_format": 5,     # RGB5A3: 15-bit color + 3-bit alpha
                "half_extent": 8.0  # vanilla hexagon radius is ~8.27
            },
            "offsets": {
                # 98 matrix format for main hexagon shape - contains two alternating colors
                "hex": {"start": 0x1C2A0, "end": 0x1C350, "format": "RGBY"},
                # Sparkle particles emitted around the shine hexagon (audit
                # 2026-07, research/docs-research/effect-maps/fox-falco-shine-sparkles.md).
                # Two CF records; color = marker+2 (3B RGB), secondary =
                # colorpos+7 (3B RGB, dominates sustained tint per template
                # lesson 3). Shared Fox/Falco -- EfFxData.dat is literally
                # the same file for both (no separate EfFcData.dat exists in
                # vanilla), so these offsets apply to Falco with no
                # per-character search/adjustment needed.
                "sparkles": {
                    "format": "CF-multi",
                    "records": [
                        {"marker": 0x125, "color": 0x127, "secondary": 0x12E},
                        {"marker": 0x141, "color": 0x143, "secondary": 0x14A}
                    ]
                }
            },
            # Two-color vanilla pattern: primary (bright edge) and secondary (fill)
            # These are the colors that appear in the hex region in alternating pattern
            "vanilla": {
                "primary": "621F",    # Bright blue edge/outline vertices
                "secondary": "AB9F",  # Grayish fill/interior vertices
                "flash1": "63FF",     # Startup flash color (blue)
                "flash2": "FFFF",     # Startup flash highlight (white)
                "sparkles": "FFFFFF"  # Vanilla sparkle color (both records' primary color bytes)
            },
            # Flash region: outer glow during shine startup (98_multi format, 3 ranges)
            "flash_offsets": {
                "ranges": [
                    {"start": 0x1C8E0, "end": 0x1C920},
                    {"start": 0x1C91F, "end": 0x1C960},
                    {"start": 0x1C95E, "end": 0x1C9A0}
                ]
            },
            "properties": [
                {"id": "primary", "name": "Primary (Edge)", "description": "Bright edge/outline color", "format": "RGBY"},
                {"id": "secondary", "name": "Secondary (Fill)", "description": "Fill/interior color", "format": "RGBY"},
                {"id": "flash1", "name": "Flash Color", "description": "Startup flash color", "format": "RGBY"},
                {"id": "flash2", "name": "Flash Highlight", "description": "Startup flash highlight", "format": "RGBY"},
                {"id": "sparkles", "name": "Sparkles", "description": "Sparkle particles around the shield", "format": "RGB"}
            ]
        },
        {
            # Audit 2026-07 (decomp itfoxblaster.c efSync_Spawn(1166) ->
            # efalt 0x48E -> effect 0xBBD = effFoxDataTable Models_5): this is
            # the muzzle-FLASH model drawn on every blaster shot (Fox AND
            # Falco share it; NOT a hit effect, and NOT the beam or the red
            # muzzle ring -- the beam is the PlFx/PlFc "laser" extra and the
            # ring is a ptcl particle, neither is touched here).
            # color1/color2 are the TObj TEV register colors of Models_5's
            # one textured DObj: pixel = tev0*(1-texI) + konst*texI, so
            # color1 (KONST) = the bright streak burst around the fighter,
            # color2 (TEV0) = the texture's dim areas (barely visible).
            # The "hue1-6" bytes are NOT hues: they are the trackType fields
            # of six FObj matanim tracks (KONST_R/G/B = 0x0C/0D/0E, TEV0_R/G/B
            # = 0x10/11/12; 0x0F = KONST_A unused) that animate both colors
            # orange->vanilla over 8 frames and then HOLD hardcoded vanilla
            # values. Custom colors are INVISIBLE unless these tracks are
            # disabled, so every custom mod writes 00 (HSD_A_T_NONE; the
            # engine's TObjUpdateFunc silently skips it -- decomp tobj.c).
            # Cost: the 8-frame orange flash becomes the static custom color.
            "id": "laser_ring",
            "name": "Blaster Flash",
            "description": "Streak burst around the fighter when firing the blaster (beam + red ring are separate)",
            "target_file": "EfFxData.dat",
            "shared": True,
            "sharedWith": ["Falco"],
            "owner": "Fox",
            "offsets": {
                "color1": {"start": 0x1D2FC, "size": 3, "format": "RGB"},
                "color2": {"start": 0x1D300, "size": 3, "format": "RGB"},
                # FObj trackType bytes -- 00 disables the flash animation so
                # the static colors above take effect (required; verified
                # in-game 2026-07: with these left vanilla, custom colors do
                # nothing). Non-UI layers; the editor writes 00 on save and
                # the backend injects 00 if a mod lacks them.
                "hue1": {"start": 0x1D974, "size": 1, "format": "BYTE"},
                "hue2": {"start": 0x1D988, "size": 1, "format": "BYTE"},
                "hue3": {"start": 0x1D99C, "size": 1, "format": "BYTE"},
                "hue4": {"start": 0x1D9B0, "size": 1, "format": "BYTE"},
                "hue5": {"start": 0x1D9C4, "size": 1, "format": "BYTE"},
                "hue6": {"start": 0x1D9D8, "size": 1, "format": "BYTE"}
            },
            "vanilla": {
                "color1": "FF004C",
                "color2": "B20000",
                "hue1": "0C",
                "hue2": "0D",
                "hue3": "0E",
                "hue4": "10",
                "hue5": "11",
                "hue6": "12"
            },
            "properties": [
                {"id": "color1", "name": "Streaks", "description": "Streak burst around the fighter when firing", "format": "RGB"},
                {"id": "color2", "name": "Dim Tint", "description": "Tint of the flash texture's dim areas (subtle in game)", "format": "RGB"}
            ]
        },
        {
            "id": "gun",
            "name": "Gun Model",
            "description": "Replace Fox's blaster gun model",
            "target_file": "PlFx.dat",
            "type": "model",  # Model type - uses .dae file instead of hex patches
            "model_path": "ftDataFox/Articles/Articles_1/Model_/RootModelJoint",
            "icon": "gun"
        },
        {
            # WIRE 2026-07-02 from research/docs-research/effect-maps/efcodata.md
            # (STRAGGLER-CLOSEOUT LIVE RESULTS block + §3a). The rapid-jab
            # (Attack100) FINISHER connect flash, shared out of the common
            # effects file EfCoData.dat -- scripts 11/15/91. MAP-LIVE VERIFIED
            # 2026-07-02 via the new `rapidjab` recipe (shared/ingame/moves.py, a
            # 1-on/1-off A toggle that chains Fox's jab into Attack100Loop) with
            # a pinned DK bag (dx6): poking s11(0x12AF)/s15(0x148D+0x14A1)/
            # s91(0x376F) RED recolored the finisher connect diamond/burst on
            # the victim (vanilla pink-white/cyan -> red) at the connect frame
            # f24. s11 = leading connect spark, s15 = the electric burst body
            # (2 records), s91 = the cyan flash. The generic gold radial
            # hit-spark streaks stay gold (texture/model, lesson 14). Captures:
            # tests/artifacts/datram-probe-efcodata-rapidjab/. All 4 offsets
            # byte-verified against storage/test-base/files/EfCoData.dat
            # 2026-07-02 (s11 0554FF, s15 57D0FF/0509FF, s91 75DBEB) -- per-
            # record vanilla bytes DIFFER, kept as per-record keys (lesson 12).
            #
            # Owner = Fox (a representative rapid-jab char). sharedWith =
            # DATA-DERIVED via backend/shared/rendering/hitbox_elements.py --attack100
            # (the fighters whose action table carries the literal Attack100
            # motion state, i.e. exactly the ones that reach Attack100Loop/End
            # and spawn 11/15/91), minus the owner Fox. NOTE Mario/Luigi/DK/
            # Bowser/Ness/etc. have only a FINITE 3-hit jab (Attack13), never
            # reach Attack100, and so are correctly EXCLUDED (see the honesty
            # note in hitbox_elements.py). The finisher spark is common to
            # EVERY rapid-jab character's Attack100 finisher.
            "id": "jab_finisher_spark",
            "name": "Rapid Jab Finisher Spark",
            # HIDDEN from the extras menu by user request (2026-07-02). Mapping
            # kept intact so any already-saved extra of this id still applies;
            # the frontend menu filters `hidden` (getExtraTypes / hasExtras).
            "hidden": True,
            "description": ("Connect flash of the rapid-jab (Attack100) FINISHER -- the "
                             "pink-white/cyan spark burst that flashes when the infinite "
                             "jab's finishing hit connects. Shared out of the common effects "
                             "file, so it affects EVERY rapid-jab character's finisher: "
                             "Fox, Falco, C. Falcon, Kirby, Link, Young Link, Mewtwo, Sheik, "
                             "and G&W (Judgment). Characters with only a finite jab combo "
                             "(no infinite rapid jab) never trigger it"),
            "target_file": "EfCoData.dat",
            "shared": True,
            # DATA-DERIVED via backend/shared/rendering/hitbox_elements.py --attack100
            # (Attack100 motion-state scan); roster minus owner Fox.
            "sharedWith": ["C. Falcon", "Falco", "Kirby", "Link", "Mewtwo",
                           "Sheik", "Young Link", "G&W"],
            "owner": "Fox",
            "offsets": {
                # s11 -- leading connect spark
                "finisher_lead_c1": {"format": "RGB", "offsets": [0x12AF]},
                # s15 -- electric burst body (2 records)
                "finisher_burst_a_c2": {"format": "RGB", "offsets": [0x148D]},
                "finisher_burst_b_c2": {"format": "RGB", "offsets": [0x14A1]},
                # s91 -- cyan flash
                "finisher_flash_c2": {"format": "RGB", "offsets": [0x376F]}
            },
            "vanilla": {
                "color1": "0554FF",
                "color2": "75DBEB",
                "finisher_lead_c1": "0554FF",
                "finisher_burst_a_c2": "57D0FF",
                "finisher_burst_b_c2": "0509FF",
                "finisher_flash_c2": "75DBEB"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Leading connect spark (s11)", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Electric burst body + cyan flash (s15/s91)", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07-10 from research/docs-research/effect-maps/common-shield.md.
            # The shield BUBBLE texture: one 128x128 IA8 image at EfCoData
            # 0x104320 referenced by 10 TObjs (MAP-LIVE verified: memset ->
            # opaque white square, Animelee splice -> anime rim ring). IA8 is
            # intensity+alpha with NO hue -- the per-port red/blue/yellow/
            # green tint is applied engine-side (DOL port/team table), so
            # this is a TEXTURE-REPLACEMENT extra, not a color extra: no
            # 'offsets', no color properties; mods carry a source (full
            # modded EfCoData.dat from the website effect import, or a PNG
            # encoded to IA8) and install copies the region bytes
            # (vault/extras/texture_region.py, relocation-guarded via
            # the ImageDesc scan). Owner Fox (cast-wide precedent,
            # jab_finisher_spark); sharedWith = roster minus Fox minus YOSHI
            # -- Yoshi has no bubble, his shield is the egg (own model in
            # PlYs*.dat).
            "id": "common_shield",
            "name": "Shield",
            "description": ("Shield bubble texture -- the shared grayscale sphere texture "
                             "every character's shield bubble draws (the per-port "
                             "red/blue/yellow/green tint is applied by the game engine and "
                             "is not editable here). Yoshi is unaffected -- his shield is "
                             "the egg, not the bubble"),
            "target_file": "EfCoData.dat",
            "format": "texture_region",
            "type": "texture_region",
            "shared": True,
            "sharedWith": ["Bowser", "C. Falcon", "DK", "Dr. Mario", "Falco",
                           "G&W", "Ganondorf", "Ice Climbers", "Jigglypuff",
                           "Kirby", "Link", "Luigi", "Mario", "Marth",
                           "Mewtwo", "Ness", "Peach", "Pichu", "Pikachu",
                           "Roy", "Samus", "Sheik", "Young Link", "Zelda"],
            "owner": "Fox",
            "texture_region": {
                "offset": "0x104320",
                "size": "0x8000",
                "width": 128,
                "height": 128,
                "gx_format": 3   # IA8
            },
            "vanilla": {},
            "properties": []
        }
    ],
    "Samus": [
        {
            # WIRE 2026-07 from research/docs-research/effect-maps/samus.md (MAP
            # stage). Screw Attack (up-B) electric arcs: four identical
            # 07 07 07 04 model-region blocks (one per arc/quadrant), marker
            # verified against vanilla EfSsData.dat -- +4 = bright core
            # (also drives the rising spiral spark ring), +8 = glow halo.
            # color1/color2 top-level properties auto-fan to every _c1/_c2
            # offset key (DualColorEditorModal convention -- same as Mewtwo
            # bolts / Falcon falcon_kick/raptor_boost). ptcl tags:
            # model-region blocks (past the ptcl bank, no script index) per
            # shared/rendering/ptcl_parse.py --models.
            "id": "screw_attack",
            "name": "Screw Attack",
            "description": "Up-B spinning swirl and electric arc core and glow colors",
            "target_file": "EfSsData.dat",
            "offsets": {
                "arc_c1": {"format": "RGB",
                           "offsets": [0x11588, 0x11648, 0x11708, 0x117C8]},
                "arc_c2": {"format": "RGB",
                           "offsets": [0x1158C, 0x1164C, 0x1170C, 0x117CC]},
                # Model0 joint0 warm swirl; live before/after verified at
                # upb f12 on 2026-09-09. Its TEV has an I8 texture owner,
                # distinct from the four briefly visible I4 arc textures.
                "warm_swirl_c1": {"start": 0x114C8, "size": 3, "format": "RGB",
                                  "model_tev_anchor": 0x114C4},
                "warm_swirl_c2": {"start": 0x114CC, "size": 3, "format": "RGB",
                                  "model_tev_anchor": 0x114C4}
            },
            "vanilla": {
                "color1": "FFFFFF",
                "color2": "0000FF",
                "arc_c1": "FFFFFF",
                "arc_c2": "0000FF",
                "warm_swirl_c1": "FFFF8A",
                "warm_swirl_c2": "FF4C00"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Swirl and arc cores", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Swirl and arc outer glow", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07 from research/docs-research/effect-maps/samus.md. Missile
            # (side-B) contrail smoke + launch back-blast puff -- CF particle
            # records in EfSsData.dat. Every offset marker-verified against
            # vanilla bytes (CF marker -> color at marker+2 = c1, secondary
            # at colorpos+7 = c2, per the template's CF-record convention).
            # contrail = script 9 (PRIMCOL/ENVCOL #0 & #1); backblast =
            # script 13 (PRIMCOL/ENVCOL #1 & #2, chained off marker 0x612).
            # color1/color2 auto-fan to all four _c1/_c2 offset keys.
            # Deliberately NOT wired: the PlSs missile-body material A/B
            # (spec flags it uncertain -- pending EYEBALL) and the cyan
            # script-16 group (pending punching-bag; no attributable element
            # on a whiffed missile).
            "id": "missile",
            "name": "Missile",
            "description": "Side-B missile contrail smoke and launch back-blast colors",
            "target_file": "EfSsData.dat",
            "offsets": {
                "contrail_c1": {"format": "RGB", "offsets": [0x470, 0x47D]},
                "contrail_c2": {"format": "RGB", "offsets": [0x477, 0x484]},
                "backblast_c1": {"format": "RGB", "offsets": [0x61F, 0x62D]},
                "backblast_c2": {"format": "RGB", "offsets": [0x626, 0x634]}
            },
            "vanilla": {
                "color1": "C27742",
                "color2": "6E1B1D",
                "contrail_c1": "C27742",
                "contrail_c2": "6E1B1D",
                "backblast_c1": "D3ABA1",
                "backblast_c2": "51231F"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Contrail smoke and back-blast puff core", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Contrail and back-blast sustained tint", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07 from research/docs-research/effect-maps/samus.md. Neutral-B
            # charge: radiating spark-needle lines around the arm cannon (CF
            # record, script 5, PRIMCOL/ENVCOL #0). The FIRED charge-shot
            # ball is explicitly NOT wired here -- the spec's live-poke pass
            # found every color-record candidate left the ball vanilla; it
            # is a texture effect (flagged for a future texture pass, see
            # research/docs-research/effect-maps/samus.md open leads).
            "id": "charge_shot",
            "name": "Charge Shot",
            "description": "Neutral-B charging spark needle colors",
            "target_file": "EfSsData.dat",
            "offsets": {
                "needles_c1": {"start": 0x2E9, "size": 3, "format": "RGB"},
                "needles_c2": {"start": 0x2F0, "size": 3, "format": "RGB"}
            },
            "vanilla": {
                "color1": "FFFFFF",
                "color2": "090087",
                "needles_c1": "FFFFFF",
                "needles_c2": "090087"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Radiating charge spark-needle lines", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Needle secondary tint", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07 from research/docs-research/effect-maps/samus.md
            # (charge_ball section, IN-GAME VERIFIED). The FIRED charge-shot
            # ball (blue outer glow / pink inner ring / white core) is NOT a
            # ptcl/model color record -- every candidate the MAP pass poked
            # left it vanilla. It IS a single RGB5A3 texture embedded in an
            # effect/particle texture-graphics block in PlSs.dat (NOT on a
            # JOBJ->DObj->MObj material tree, so the CLI `type: "texture"`
            # export/import machinery in textures.py can't reach it --
            # confirmed: `HSDRawViewer --texture export` returns "Expected
            # HSD_JOBJ ... got SBM_FighterData"). First consumer of the
            # `texture_recolor` format (raw texel hue-rotate patch,
            # vault/extras/texture_recolor.py): presents as a plain
            # single ColorPicker, apply = rotate every texel's hue by
            # (target_hue - vanilla_dominant_hue), preserving each texel's
            # S/V/alpha (HSV, matches shared/rendering/stock_gen.py's precedent) --
            # never a flat fill, so the blue/pink/white gradient structure
            # survives. Ground truth: the verified plss_ball_probe prototype
            # this format promotes into the extras plumbing (gx_texels.py
            # carries its codecs) and tests/artifacts/samus-ball-texture/.
            # vanilla_dominant_hue 239 (saturation-weighted, computed from
            # the vanilla texture itself). The I4 shape/intensity map at
            # 0x36040 is a SEPARATE texture (grayscale, no hue) and is
            # deliberately NOT part of this layer's byte range.
            "id": "charge_ball",
            "part_of": "charge_shot",  # edited inside the charge_shot unit (see UNIT_PARTS)
            "name": "Charge Ball",
            "description": "Fired charge-shot projectile ball color",
            "target_file": "PlSs.dat",
            "format": "texture_recolor",
            "texture": {
                "offset": 0x36840,
                "width": 64,
                "height": 64,
                "gx_format": 5  # RGB5A3
            },
            "vanilla_dominant_hue": 239,
            "vanilla": {
                "color1": "0004FF"  # representative vanilla swatch (hue 239 at full S/V)
            },
            "properties": [
                {"id": "color1", "name": "Ball Color", "description": "Fired charge-shot ball color (blue glow / pink ring / white core, recolored together)", "format": "RGB"}
            ]
        }
    ],
    "Luigi": [
        {
            # WIRE 2026-07 from research/docs-research/effect-maps/luigi.md (MAP-LIVE
            # verified). Neutral-B fireball body/aura -- lives in the PlLg.dat
            # ARTICLE, not EfLgData (confirmed by live-poking these 3 offsets
            # magenta: fireball body/core aura turned magenta, smoke trail
            # unaffected). fb_aura_42's PrimCol @0xF42C (00FF00) is the
            # dominant green -- the EYEBALL-flagged lead/primary per the
            # spec's suggested grouping. All three offsets are one visual
            # (aura+body recolor together) so color1 fans to all three; no
            # secondary layer exists in this file (that's the split-out
            # luigi_fireball_smoke extra in EfLgData.dat, config schema is
            # one target_file per extra -- see extras_audit.py check_offsets).
            # Split from the spec's single "Proposed extra 1" table across
            # its two target files, same pattern as Samus screw_attack/
            # missile/charge_shot each getting one target_file.
            "id": "luigi_fireball",
            "name": "Fireball",
            "description": "Neutral-B fireball body and aura color",
            "target_file": "PlLg.dat",
            "offsets": {
                "fb_aura_42_c1": {"format": "RGB", "offsets": [0xF42C]},
                "fb_aura_07_c1": {"format": "RGB", "offsets": [0xF3BC]},
                "fb_body_42_c1": {"format": "RGB", "offsets": [0xF4CC]}
            },
            "vanilla": {
                "color1": "00FF00",
                "fb_aura_42_c1": "00FF00",
                "fb_aura_07_c1": "FF6600",
                "fb_body_42_c1": "FFFFFF"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Fireball body/aura core color", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07 from research/docs-research/effect-maps/luigi.md. Neutral-B
            # fireball hand-spawn smoke puffs + the oval hand ring/portal --
            # EfLgData.dat CF particle records + one 42_48/07 hand-ring
            # model-block pair. Live-poke verified: hand-spawn smoke puff
            # turned magenta (script 1 = dominant, NOT the "weak grey/olive"
            # STATIC guess); hand ring/portal turned magenta at fireball
            # spawn. The *traveling* fireball trail stayed green under every
            # poke here -- that trail is common-bank (EfCoData), quarantined,
            # not wired. c1 = smoke primaries + ring, c2 = smoke secondaries
            # (CF colorpos+7, dominates sustained puff tint per lesson 3).
            "id": "luigi_fireball_smoke",
            "part_of": "luigi_fireball",  # edited inside the luigi_fireball unit (see UNIT_PARTS)
            "name": "Fireball Smoke & Hand Ring",
            "description": "Neutral-B fireball hand-spawn smoke and hand ring colors",
            "target_file": "EfLgData.dat",
            "offsets": {
                "fb_smoke_s1_c1": {"format": "RGB",
                                    "offsets": [0x186, 0x194, 0x1A7, 0x1B4]},
                "fb_smoke_s1_c2": {"format": "RGB",
                                    "offsets": [0x18D, 0x19B, 0x1AE, 0x1BB]},
                "fb_smoke_s0a_c1": {"format": "RGB", "offsets": [0xFF]},
                "fb_smoke_s0a_c2": {"format": "RGB", "offsets": [0x106]},
                "fb_smoke_s0b_c1": {"format": "RGB", "offsets": [0x10C]},
                "fb_smoke_s0b_c2": {"format": "RGB", "offsets": [0x113]},
                "fb_smoke_s3_c1": {"format": "RGB", "offsets": [0x26D]},
                "fb_smoke_s3_c2": {"format": "RGB", "offsets": [0x281]},
                "fb_smoke_s4_c1": {"format": "RGB", "offsets": [0x2DD]},
                "fb_smoke_s4_c2": {"format": "RGB", "offsets": [0x2F1]},
                "fb_dust_s5_c1": {"format": "RGB", "offsets": [0x352]},
                "fb_dust_s5_c2": {"format": "RGB", "offsets": [0x372]},
                "fb_particle_s6_c1": {"format": "RGB", "offsets": [0x3FE]},
                "fb_particle_s6_c2": {"format": "RGB", "offsets": [0x40E]},
                "hand_ring_42_c1": {"format": "RGB", "offsets": [0x11260]},
                "hand_ring_42_c2": {"format": "RGB", "offsets": [0x11264]},
                "hand_ring_07_c1": {"format": "RGB", "offsets": [0x111F0]},
                "hand_ring_07_c2": {"format": "RGB", "offsets": [0x111F4]}
            },
            "vanilla": {
                "color1": "93A394",
                "color2": "22AB0A",
                "fb_smoke_s1_c1": "93A394",
                "fb_smoke_s1_c2": "22AB0A",
                "fb_smoke_s0a_c1": "26FF43",
                "fb_smoke_s0a_c2": "2ABA4E",
                "fb_smoke_s0b_c1": "149C2D",
                "fb_smoke_s0b_c2": "0C5419",
                "fb_smoke_s3_c1": "02FD02",
                "fb_smoke_s3_c2": "052E15",
                "fb_smoke_s4_c1": "16FD22",
                "fb_smoke_s4_c2": "0A4F12",
                "fb_dust_s5_c1": "BDFDBB",
                "fb_dust_s5_c2": "31F83B",
                "fb_particle_s6_c1": "1ADC24",
                "fb_particle_s6_c2": "7CFF70",
                "hand_ring_42_c1": "66FF99",
                "hand_ring_42_c2": "FFFFFF",
                "hand_ring_07_c1": "CCFFE5",
                "hand_ring_07_c2": "19B200"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Hand-spawn smoke puff and hand ring core color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Smoke sustained tint and hand ring glow", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07 from research/docs-research/effect-maps/luigi.md. Down-B
            # tornado (Luigi Cyclone): 5 070707 model-region swirl blocks +
            # 5 42_48 finish/dissipation-ring blocks in EfLgData.dat, all
            # pale-yellow/white -> single color1/color2 editor pair. Live-poke
            # verified magenta on both the swirl (07-blocks) and the
            # trailing/ground finish ring (42_48 blocks). 07-block note (spec):
            # col2 sits at col1+4 (marker+8), separator 00 at marker+7; since
            # col1 != col2 per block, each is a direct RGB slot (falcon_kick
            # technique) rather than the shared single-color '070707' format.
            "id": "luigi_cyclone",
            "name": "Luigi Cyclone",
            "description": "Down-B tornado swirl and finish ring colors",
            "target_file": "EfLgData.dat",
            "offsets": {
                # 07-block swirl: col1/col2 DIFFER (see spec), so each is
                # written as a direct RGB slot at its exact byte position --
                # NOT the shared '070707' single-color format (which would
                # force col1==col2). Same technique as falcon_kick's
                # top-level color1/color2. Spec's "col1/col2 off" ARE the
                # marker+4/marker+8 byte positions already (marker = col1-4).
                "torn_outer_c1": {"start": 0x11A80, "size": 3, "format": "RGB"},
                "torn_outer_c2": {"start": 0x11A84, "size": 3, "format": "RGB"},
                "torn_upper_c1": {"start": 0x11B4C, "size": 3, "format": "RGB"},
                "torn_upper_c2": {"start": 0x11B50, "size": 3, "format": "RGB"},
                "torn_inner1_c1": {"start": 0x11C18, "size": 3, "format": "RGB"},
                "torn_inner1_c2": {"start": 0x11C1C, "size": 3, "format": "RGB"},
                "torn_inner2_c1": {"start": 0x11CE4, "size": 3, "format": "RGB"},
                "torn_inner2_c2": {"start": 0x11CE8, "size": 3, "format": "RGB"},
                "torn_under_c1": {"start": 0x11DB0, "size": 3, "format": "RGB"},
                "torn_under_c2": {"start": 0x11DB4, "size": 3, "format": "RGB"},
                "torn_outer_fin_c1": {"format": "RGB", "offsets": [0x11AF0]},
                "torn_outer_fin_c2": {"format": "RGB", "offsets": [0x11AF4]},
                "torn_fin_c1": {"format": "RGB", "offsets": [0x11BBC]},
                "torn_fin_c2": {"format": "RGB", "offsets": [0x11BC0]},
                "torn_fin_s1_c1": {"format": "RGB", "offsets": [0x11C88]},
                "torn_fin_s1_c2": {"format": "RGB", "offsets": [0x11C8C]},
                "torn_fin_s2_c1": {"format": "RGB", "offsets": [0x11D54]},
                "torn_fin_s2_c2": {"format": "RGB", "offsets": [0x11D58]},
                "torn_below_c1": {"format": "RGB", "offsets": [0x11E20]},
                "torn_below_c2": {"format": "RGB", "offsets": [0x11E24]}
            },
            "vanilla": {
                "color1": "FFFFB2",
                "color2": "FFB200",
                "torn_outer_c1": "FFFFB2",
                "torn_outer_c2": "FFB200",
                "torn_upper_c1": "FFFFB2",
                "torn_upper_c2": "FFCC00",
                "torn_inner1_c1": "FFFFE5",
                "torn_inner1_c2": "FFFF00",
                "torn_inner2_c1": "FFFFCC",
                "torn_inner2_c2": "FFFF00",
                "torn_under_c1": "FFFFCC",
                "torn_under_c2": "FFB200",
                "torn_outer_fin_c1": "FFFFD0",
                "torn_outer_fin_c2": "FFFFFF",
                "torn_fin_c1": "FFFFD0",
                "torn_fin_c2": "FFFFFF",
                "torn_fin_s1_c1": "FFFFD0",
                "torn_fin_s1_c2": "FFFFFF",
                "torn_fin_s2_c1": "FFFFD0",
                "torn_fin_s2_c2": "FFFFFF",
                "torn_below_c1": "FFFFE3",
                "torn_below_c2": "FFFFFF"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Tornado swirl and finish ring core color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Tornado glow and finish ring highlight", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07-02 from research/docs-research/effect-maps/luigi.md
            # "Proposed extra 3" -- ON-HIT ONLY, verified via the punching-bag
            # harness (spark_blue_s11, EfLgData.dat script 11). Poking prim
            # 0x60A / env 0x611 RED turned the small inner jagged burst of
            # Luigi's melee-hit contact flash red on both fair and nair
            # against a DK bag (contact frames, pixel-diff confirmed:
            # vanilla red~=0 vs poked red~=1400-3000). The surrounding
            # white/yellow rays + glow are common-bank and stay unchanged --
            # s11 colors ONLY the inner burst. CF-multi format per lesson 3
            # (prim=core @marker, env=glow @marker+7); count/aux record at
            # 0x617 is the interp-frame-count byte for this CF record (cnt=4,
            # per spec table) -- not a color operand, left unwritten same as
            # every other CF record's count byte in this file (front_c1 in
            # falcon_kick/raptor_boost precedent likewise never exposes the
            # count byte as an editor color). Single conceptual color:
            # prim=core, env=glow -> color1/color2.
            "id": "luigi_hitspark",
            "name": "Impact Spark",
            "description": "On-hit melee contact flash inner burst color",
            "target_file": "EfLgData.dat",
            "offsets": {
                "hitspark_s11_c1": {"format": "RGB", "offsets": [0x60A]},
                "hitspark_s11_c2": {"format": "RGB", "offsets": [0x611]}
            },
            "vanilla": {
                "color1": "B5F6FF",
                "color2": "0C17D7",
                "hitspark_s11_c1": "B5F6FF",
                "hitspark_s11_c2": "0C17D7"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Contact-flash inner burst core color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Contact-flash inner burst glow color", "format": "RGB"}
            ]
        }
    ],
    "Mario": [
        {
            # WIRE 2026-07 from research/docs-research/effect-maps/mario.md (MAP-LIVE
            # verified 2026-07-02, tests/artifacts/datram-probe-mario/). Mario
            # only -- Doc throws vitamin pills, never spawns gfx_id 1146, so
            # this extra is intentionally NOT shared. Neutral-B fireball: five
            # CF particle groups in EfMrData.dat (hand smoke at spawn,
            # trailing fire plume, ball particles around the orb, landing/
            # expiry dust, square particles at the endpoint) plus the hand
            # circle 07/42 ring that flashes around Mario's hand at spawn
            # (spatially adjacent to the down-B tornado script region but
            # confirmed via the neutral-B poke, not down-B -- kept here, NOT
            # in mario_tornado, since Doc has no fireball to show it). c1 =
            # PrimCol record primaries, c2 = EnvCol secondaries at colorpos+7
            # (dominates sustained puff tint per template lesson 3). Every
            # offset marker-verified; the old landing-dust cite (0x3C9) was
            # off by 1 (real marker 0x3C8). Each CF record's vanilla bytes
            # differ (byte-verified against storage/test-base/files/
            # EfMrData.dat), so every record is its own key rather than
            # grouped under one shared vanilla string (grouping only works
            # when a group's vanilla bytes are identical, e.g. Falcon's
            # trail_c1) -- the one picker per color1/color2 still fans out to
            # ALL of them via the DualColorEditorModal convention.
            "id": "mario_fireball",
            "name": "Fireball",
            "description": "Neutral-B fireball smoke, trail, particle, and hand-ring colors",
            "target_file": "EfMrData.dat",
            "offsets": {
                "hand_smoke_a_c1": {"format": "RGB", "offsets": [0x162]},
                "hand_smoke_a_c2": {"format": "RGB", "offsets": [0x169]},
                "hand_smoke_b_c1": {"format": "RGB", "offsets": [0x177]},
                "hand_smoke_b_c2": {"format": "RGB", "offsets": [0x17E]},
                "hand_smoke_c_c1": {"format": "RGB", "offsets": [0x184]},
                "hand_smoke_c_c2": {"format": "RGB", "offsets": [0x18B]},
                "trailing_fire_a_c1": {"format": "RGB", "offsets": [0x20C]},
                "trailing_fire_a_c2": {"format": "RGB", "offsets": [0x213]},
                "trailing_fire_b_c1": {"format": "RGB", "offsets": [0x21F]},
                "trailing_fire_b_c2": {"format": "RGB", "offsets": [0x226]},
                "trailing_fire_c_c1": {"format": "RGB", "offsets": [0x22C]},
                "trailing_fire_c_c2": {"format": "RGB", "offsets": [0x233]},
                "ball_particles_a_c1": {"format": "RGB", "offsets": [0x2E5]},
                "ball_particles_a_c2": {"format": "RGB", "offsets": [0x2EC]},
                "ball_particles_b_c1": {"format": "RGB", "offsets": [0x2F2]},
                "ball_particles_b_c2": {"format": "RGB", "offsets": [0x2F9]},
                "ball_particles_c_c1": {"format": "RGB", "offsets": [0x355]},
                "ball_particles_c_c2": {"format": "RGB", "offsets": [0x35C]},
                "ball_particles_d_c1": {"format": "RGB", "offsets": [0x362]},
                "ball_particles_d_c2": {"format": "RGB", "offsets": [0x369]},
                "landing_dust_a_c1": {"format": "RGB", "offsets": [0x3CA]},
                "landing_dust_a_c2": {"format": "RGB", "offsets": [0x3D1]},
                "landing_dust_b_c1": {"format": "RGB", "offsets": [0x3DD]},
                "landing_dust_b_c2": {"format": "RGB", "offsets": [0x3E4]},
                "landing_dust_c_c1": {"format": "RGB", "offsets": [0x3EA]},
                "landing_dust_c_c2": {"format": "RGB", "offsets": [0x3F1]},
                "square_particles_a_c1": {"format": "RGB", "offsets": [0x476]},
                "square_particles_a_c2": {"format": "RGB", "offsets": [0x47D]},
                "square_particles_b_c1": {"format": "RGB", "offsets": [0x486]},
                "square_particles_b_c2": {"format": "RGB", "offsets": [0x48D]},
                "hand_ring_07_c1": {"format": "RGB", "offsets": [0x11AF8]},
                "hand_ring_07_c2": {"format": "RGB", "offsets": [0x11AFC]},
                "hand_ring_42_c1": {"format": "RGB", "offsets": [0x11B68]}
            },
            "vanilla": {
                "color1": "FFA217",
                "color2": "D43B08",
                "hand_smoke_a_c1": "FFFFFF",
                "hand_smoke_a_c2": "FFCC4A",
                "hand_smoke_b_c1": "FFA217",
                "hand_smoke_b_c2": "BA120D",
                "hand_smoke_c_c1": "9C060B",
                "hand_smoke_c_c2": "540405",
                "trailing_fire_a_c1": "C7BB0D",
                "trailing_fire_a_c2": "D43B08",
                "trailing_fire_b_c1": "FFA800",
                "trailing_fire_b_c2": "FF5900",
                "trailing_fire_c_c1": "FF070F",
                "trailing_fire_c_c2": "510A00",
                "ball_particles_a_c1": "FDEB74",
                "ball_particles_a_c2": "E33C09",
                "ball_particles_b_c1": "B90303",
                "ball_particles_b_c2": "610101",
                "ball_particles_c_c1": "FDE467",
                "ball_particles_c_c2": "D42304",
                "ball_particles_d_c1": "7D4202",
                "ball_particles_d_c2": "2E0000",
                "landing_dust_a_c1": "FEFCE2",
                "landing_dust_a_c2": "FFF75C",
                "landing_dust_b_c1": "FCE669",
                "landing_dust_b_c2": "D60B0E",
                "landing_dust_c_c1": "F9AC06",
                "landing_dust_c_c2": "6B0507",
                "square_particles_a_c1": "FF290C",
                "square_particles_a_c2": "FFFF82",
                "square_particles_b_c1": "FFFF6E",
                "square_particles_b_c2": "FF0C14",
                "hand_ring_07_c1": "FFFFB2",
                "hand_ring_07_c2": "FF6600",
                "hand_ring_42_c1": "FFFF99"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Fireball smoke/trail/particle core color and hand ring", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Fireball sustained tint / glow", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07 from research/docs-research/effect-maps/mario.md. Fireball
            # AURA/glow halo material -- lives in PlMr.dat (player-file, not
            # EfMrData), so it's a separate target_file per the Luigi
            # screw_attack/missile/charge_shot precedent (one target_file per
            # extra). Live-poke: cyan turned the soft round glow surrounding
            # the fireball orb cyan (0xFA40 07-block) and contributed to the
            # body glow (0xFAB0/0xFB50 42-blocks); the fireball's white core
            # orb itself is a separate texture, untouched. Un-corroborated by
            # ref mod 15777 (that mod adds a new model instead) but LIVE-
            # confirmed. Ship 42 DIFFUSE (+4) only -- ambient (+0) is a
            # verified no-op (template lesson, Fox/Falco precedent).
            "id": "mario_fireball_aura",
            "part_of": "mario_fireball",  # edited inside the mario_fireball unit (see UNIT_PARTS)
            "name": "Fireball Aura",
            "description": "Fireball glow halo and body material color",
            "target_file": "PlMr.dat",
            "offsets": {
                "aura_07_c1": {"format": "RGB", "offsets": [0xFA44]},
                "aura_07_c2": {"format": "RGB", "offsets": [0xFA48]},
                "aura_42_c1": {"format": "RGB", "offsets": [0xFAB4]},
                "body_42_c1": {"format": "RGB", "offsets": [0xFB54]}
            },
            "vanilla": {
                "color1": "FF6600",
                "color2": "FF3300",
                "aura_07_c1": "FF6600",
                "aura_07_c2": "FF3300",
                "aura_42_c1": "FF4C00",
                "body_42_c1": "FFFFFF"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Aura glow halo core and body material color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Aura glow halo outer tint", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07 from research/docs-research/effect-maps/mario.md. Side-B
            # cape swing sparkle stars -- EfMrData.dat CF particle records.
            # SHARED with Dr. Mario (same file, same fighter moveset per
            # decomp: ftMr_Special* is Mario's code, keyed on FTKIND_MARIO
            # only for the fireball branch -- cape/tornado/up-B run for both),
            # following the Fox/Falco shared-file precedent (owner + shared/
            # sharedWith, mods stored under the owner). Live-poke: red poke on
            # all four records shifted the swing sparkle stars (subtle --
            # vanilla sparkles are inherently multi-hue blue/cyan/magenta/pink
            # so the shift reads faint; flagged for EYEBALL). The 0x567 record
            # is a black/alpha-mask PrimCol base with NO envcol pair, but an
            # isolated green poke produced a visible cyan/teal trailing
            # sparkle at the cape's bottom edge -- confirmed live, not dead.
            # Cape CLOTH color is a separate per-character extra (mario_cape /
            # doc_cape below) since it lives in each character's own player
            # file at a different offset.
            "id": "cape_sparkles",
            "name": "Cape Sparkles",
            "description": "Side-B cape swing sparkle star colors",
            "target_file": "EfMrData.dat",
            "shared": True,
            "sharedWith": ["Dr. Mario"],
            "owner": "Mario",
            "offsets": {
                "sparkle_a_c1": {"format": "RGB", "offsets": [0x4E0]},
                "sparkle_a_c2": {"format": "RGB", "offsets": [0x4E7]},
                "sparkle_b_c1": {"format": "RGB", "offsets": [0x4ED]},
                "sparkle_c_c1": {"format": "RGB", "offsets": [0x505]},
                "sparkle_trail_c1": {"format": "RGB", "offsets": [0x569]}
            },
            "vanilla": {
                "color1": "6BFDFF",
                "color2": "1105FF",
                "sparkle_a_c1": "6BFDFF",
                "sparkle_a_c2": "1105FF",
                "sparkle_b_c1": "D1A3FF",
                "sparkle_c_c1": "BF09A1",
                "sparkle_trail_c1": "000000"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Cape sparkle star colors (subtle -- vanilla is multi-hue)", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Sparkle secondary tint", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07 from research/docs-research/effect-maps/mario.md. Mario
            # cape CLOTH color -- PlMr.dat 42_48 material, marker @0x14EBC.
            # Live-poke: green turned the cape cloth bright green, STRONG and
            # clean (the ship headline for the cape group). Separate
            # target_file from cape_sparkles (Luigi cloth/smoke precedent).
            "id": "mario_cape",
            "name": "Cape Cloth",
            "description": "Side-B cape cloth color",
            "target_file": "PlMr.dat",
            "offsets": {
                "cloth_c1": {"format": "RGB", "offsets": [0x14EAC]},
                "cloth_c2": {"format": "RGB", "offsets": [0x14EB0]}
            },
            "vanilla": {
                "color1": "FFFFFF",
                "color2": "FFFFFF",
                "cloth_c1": "FFFFFF",
                "cloth_c2": "FFFFFF"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Cape cloth color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Cape cloth secondary/shading color", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07 from research/docs-research/effect-maps/mario.md. Down-B
            # tornado (both chars): 5 identical 07 07 07 04 swirl blocks
            # (outer/inner/underneath) + 5 42_48 ground-ripple/spin-haze
            # blocks in EfMrData.dat -- shared per the Fox/Falco precedent
            # (owner Mario, sharedWith Dr. Mario). Live-poke: red on all 5
            # 07-blocks turned the whole tornado vortex + spin arcs + ground
            # ripple full red, identical on Doc. 42 diffuse(+4) turned the
            # ground ripple/spin haze green in the split test; ambient(+0) was
            # a confirmed no-op -- ship diffuse only. The fireball hand-circle
            # 07/42 pair (0x11AF4/0x11B64 region) is spatially adjacent but
            # semantically the fireball's hand ring (Mario-only, verified via
            # the neutral-B poke) -- kept in mario_fireball instead, not here.
            "id": "mario_tornado",
            "name": "Tornado",
            "description": "Down-B tornado swirl and ground haze colors",
            "target_file": "EfMrData.dat",
            "shared": True,
            "sharedWith": ["Dr. Mario"],
            "owner": "Mario",
            "offsets": {
                "outer_swirl1_c1": {"format": "RGB", "offsets": [0x12380]},
                "outer_swirl1_c2": {"format": "RGB", "offsets": [0x12384]},
                "outer_swirl2_c1": {"format": "RGB", "offsets": [0x1244C]},
                "outer_swirl2_c2": {"format": "RGB", "offsets": [0x12450]},
                "inner_side1_c1": {"format": "RGB", "offsets": [0x12518]},
                "inner_side1_c2": {"format": "RGB", "offsets": [0x1251C]},
                "inner_side2_c1": {"format": "RGB", "offsets": [0x125E4]},
                "inner_side2_c2": {"format": "RGB", "offsets": [0x125E8]},
                "underneath_c1": {"format": "RGB", "offsets": [0x126B0]},
                "underneath_c2": {"format": "RGB", "offsets": [0x126B4]},
                "ground_ripple1_42_c1": {"format": "RGB", "offsets": [0x123F0]},
                "ground_ripple2_42_c1": {"format": "RGB", "offsets": [0x124BC]},
                "spin_haze1_42_c1": {"format": "RGB", "offsets": [0x12588]},
                "spin_haze2_42_c1": {"format": "RGB", "offsets": [0x12654]},
                "ground_haze_42_c1": {"format": "RGB", "offsets": [0x12720]}
            },
            "vanilla": {
                "color1": "B2FFFF",
                "color2": "0000FF",
                "outer_swirl1_c1": "B2FFFF",
                "outer_swirl1_c2": "0000FF",
                "outer_swirl2_c1": "B2FFFF",
                "outer_swirl2_c2": "0000FF",
                "inner_side1_c1": "99CCFF",
                "inner_side1_c2": "0000FF",
                "inner_side2_c1": "99CCFF",
                "inner_side2_c2": "0000FF",
                "underneath_c1": "CCFFFF",
                "underneath_c2": "0033FF",
                "ground_ripple1_42_c1": "FFFFD0",
                "ground_ripple2_42_c1": "FFFFD0",
                "spin_haze1_42_c1": "FFFFD0",
                "spin_haze2_42_c1": "FFFFD0",
                "ground_haze_42_c1": "FFFFE3"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Tornado vortex core and ground haze color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Tornado glow halo", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07-02 from research/docs-research/effect-maps/items.md (items
            # pass). The up-B "coin" ring is NOT a color record -- mario.md's
            # upb_coin CF records (EfMrData 0x62C-0x70F) tested DEAD under the
            # punching bag (green/magenta/red all no-op). This pass located
            # the REAL coin sprite: a plain texture in Mario's own tex bank,
            # EfMrData.dat texGraphicBank group 0 -- 8x CI8 64x64 images (one
            # per spin pose) at 0x7A0/0x17A0/.../0x77A0 (extent
            # 0x7A0-0x97A0), each with its own 256-entry RGB5A3 palette
            # (offsets from `python shared/rendering/ptcl_texbank.py EfMrData.dat
            # --groups 0 --json`, byte-verified against
            # storage/test-base/files/EfMrData.dat 2026-07-02: all 8 image
            # blocks + palette headers match exactly). vanilla_dominant_hue
            # 47.6 (gold), same shape as the `common_fire`/`common_flash`
            # CI8-palette texture_recolor consumers (recolor rotates each
            # image's PALETTE entries; pixel indices untouched). SHARED with
            # Dr. Mario (EfMrData.dat is the shared Mario/Doc effect table,
            # mario.md confirms both characters' up-B reads the same file) --
            # owner/sharedWith pattern (mario_tornado/cape_sparkles
            # precedent), mods stored once under Mario.
            "id": "mario_coins",
            "name": "Coin Color",
            "description": "Up-B coin sprite color -- affects the shared effects file, also recolors Dr. Mario's up-B coins",
            "target_file": "EfMrData.dat",
            "format": "texture_recolor",
            "shared": True,
            "sharedWith": ["Dr. Mario"],
            "owner": "Mario",
            "texture": {
                "gx_format": 9,   # CI8
                "width": 64,
                "height": 64,
                "images": [
                    {"offset": "0x7A0", "palette": "0x87A0"},
                    {"offset": "0x17A0", "palette": "0x89A0"},
                    {"offset": "0x27A0", "palette": "0x8BA0"},
                    {"offset": "0x37A0", "palette": "0x8DA0"},
                    {"offset": "0x47A0", "palette": "0x8FA0"},
                    {"offset": "0x57A0", "palette": "0x91A0"},
                    {"offset": "0x67A0", "palette": "0x93A0"},
                    {"offset": "0x77A0", "palette": "0x95A0"}
                ],
                "palette_format": 2  # RGB5A3
            },
            "vanilla_dominant_hue": 47.6,
            "vanilla": {
                "color1": "FFCA00"  # representative vanilla swatch (hue 47.6 at full S/V, gold)
            },
            "properties": [
                {"id": "color1", "name": "Coin Color", "description": "Up-B coin sprite color (spin poses; shared with Dr. Mario)", "format": "RGB"}
            ]
        }
    ],
    "Dr. Mario": [
        {
            # WIRE 2026-07 from research/docs-research/effect-maps/mario.md. Doc cape
            # CLOTH color -- his OWN PlDr.dat, different offset than Mario's
            # PlMr (Doc-owned extra, not shared -- only the sparkles above are
            # shared). Marker @0x19CBC (the old reference cite 0x19CA0 was off
            # by 0xC / 12 bytes). Live-poke + ref mod 13332 (Blue Cape Dr.
            # Mario, byte-diff clean at 0x19CAC-0x19CB2) both confirm: green
            # turned the cape bright green, STRONG and clean -- the strongest
            # ship candidate in the whole spec.
            "id": "doc_cape",
            "name": "Cape Cloth",
            "description": "Side-B cape cloth color",
            "target_file": "PlDr.dat",
            "offsets": {
                "cloth_c1": {"format": "RGB", "offsets": [0x19CAC]},
                "cloth_c2": {"format": "RGB", "offsets": [0x19CB0]}
            },
            "vanilla": {
                "color1": "FFFFFF",
                "color2": "FFFFFF",
                "cloth_c1": "FFFFFF",
                "cloth_c2": "FFFFFF"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Cape cloth color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Cape cloth secondary/shading color", "format": "RGB"}
            ]
        }
    ],
    "Zelda": [
        {
            # WIRE 2026-07 from research/docs-research/effect-maps/effect-texbank.md
            # section 4a. EfCoData.dat is the CAST-SHARED common effect bank
            # (not a per-character file) -- its texGraphicBank group 9 is the
            # ONLY color-bearing fire texture in the whole game (CI8, hue 41
            # orange); Din's Fire/Bowser Bomb/Charizard breath/Roy's
            # Blazer+Flare-Blade all draw the colored fire cloud from THIS
            # one shared group (proven by mod 17088 "rainbow fire whole
            # cast", a pure diff of grp9's extent 0x8CB40-0x97F40 that
            # shifted every fire effect simultaneously; ptcl_texbank.py
            # --verify PASSes on that containment). Owner = Zelda (Din's
            # Fire is the most singularly-associated move for this shared
            # bank); sharedWith lists every other consumer so the card also
            # appears under their extras tabs (owner/sharedWith pattern,
            # Fox/Falco upb precedent) -- installs/mods are stored once,
            # under Zelda, and apply cast-wide since the file itself is
            # shared. Their OWN grayscale masks (Din/Vanish/Quick-Attack/
            # arrow/Bomb texGroups) carry no hue and are deliberately NOT
            # wired (see effect-texbank.md section 4c) -- recoloring them
            # would be a no-op.
            #
            # First CI8 (indexed-palette) consumer of texture_recolor: the
            # config's "texture" key is the multi-image {"images": [...]}
            # shape (10 poses, each its own 256-entry RGB5A3 palette) --
            # apply = hue-rotate each image's PALETTE entries, pixel indices
            # untouched (vault/extras/texture_recolor.py CI-palette
            # path). vanilla_dominant_hue 41 (saturation-weighted, measured
            # from the vanilla palettes via ptcl_texbank.py --hue).
            "id": "common_fire",
            "name": "Fire Color",
            "description": ("Shared fire-cloud texture color -- affects the shared effects "
                             "file, also recolors Din's Fire, Bowser Bomb fire, Charizard "
                             "flame-breath, and Roy's Flare Blade + Blazer fire for other "
                             "characters"),
            "target_file": "EfCoData.dat",
            "format": "texture_recolor",
            "shared": True,
            # NOTE: Charizard/Pokemon Trainer is not a selectable character in
            # this app's roster (Melee has no standalone PT slot here) -- the
            # also_affects description above still documents the effect for
            # honesty, but sharedWith only lists characters the UI can show
            # the card under.
            # Marth has NO fire moves (Shield Breaker / Dancing Blade / Dolphin
            # Slash / Counter are all non-fire) -- the fire Flare Blade + Blazer
            # belong to ROY only. Marth was previously mislabeled here and is
            # correctly excluded.
            "sharedWith": ["Bowser", "Roy"],
            "owner": "Zelda",
            "texture": {
                "gx_format": 9,   # CI8
                "width": 64,
                "height": 64,
                "images": [
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
                "palette_format": 2  # RGB5A3
            },
            "vanilla_dominant_hue": 41,
            "vanilla": {
                "color1": "FF9900"  # representative vanilla swatch (hue 41 at full S/V)
            },
            "properties": [
                {"id": "color1", "name": "Fire Color", "description": "Shared fire-cloud color (Din's Fire, Bowser Bomb, Charizard breath, Roy's Flare Blade/Blazer fire -- all draw from this one shared texture)", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07 from research/docs-research/effect-maps/effect-texbank.md
            # section 4b. Sibling of common_fire: EfCoData.dat texGraphicBank
            # group 3, the shared electric/vanish/transform star-burst (CI8,
            # 2 images, hue 279 purple/magenta). Same shared-file reasoning:
            # Sheik/Zelda Vanish + Transform + Pikachu thunder/Quick-Attack
            # burst all composite this ONE texture. Owner = Zelda (Vanish is
            # the move most associated with this burst); sharedWith the
            # other consumers.
            "id": "common_flash",
            "name": "Flash Color",
            "description": ("Shared electric/flash star-burst texture color -- affects the "
                             "shared effects file, also recolors Zelda Vanish flash, "
                             "Zelda-Sheik Transform flash, and Pikachu/Pichu thunder and "
                             "Quick Attack burst for other characters"),
            "target_file": "EfCoData.dat",
            "format": "texture_recolor",
            "shared": True,
            "sharedWith": ["Sheik", "Pikachu", "Pichu"],
            "owner": "Zelda",
            "texture": {
                "gx_format": 9,   # CI8
                "width": 128,
                "height": 128,
                "images": [
                    {"offset": "0x48DA0", "palette": "0x50DA0"},
                    {"offset": "0x4CDA0", "palette": "0x50FA0"}
                ],
                "palette_format": 2  # RGB5A3
            },
            "vanilla_dominant_hue": 279,
            "vanilla": {
                "color1": "B400FF"  # representative vanilla swatch (hue 279 at full S/V)
            },
            "properties": [
                {"id": "color1", "name": "Flash Color", "description": "Shared electric/flash star-burst color (Vanish, Transform, Pikachu/Pichu thunder and Quick Attack -- all draw from this one shared texture)", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07-02 from research/docs-research/effect-maps/zelda-sheik.md
            # "Shippable-now summary". EfZdData.dat (symbol effZeldaDataTable)
            # is the SHARED Zelda/Sheik effects bank (both forms' scripts
            # live in one file). Farore's Wind teleport-burst CORE flash
            # (scripts 2 grnd / 3 air): the yellow/orange ribbon spirals are
            # a model-region element and stay put -- only this ptcl-bank
            # core recolors. Live-poke verified 2026-07-02 (magenta poke,
            # tests/artifacts/datram-probe-zelda2/farore_burst-upb-f10.png).
            # Offsets are the parser's exact COLOR-BYTE positions (CF opcode
            # is 2 bytes before each) -- format 'RGB' with direct 'offsets'
            # lists writes right at these addresses, no marker skip (see
            # falcon_kick's front_c1/trail_c1 precedent). Per spec lesson 12
            # all 6 vanilla bytes differ record-to-record, so each offset
            # keeps its own vanilla entry below (helpers.read_current_colors
            # only samples the FIRST offset per layer for the UI swatch --
            # acceptable since farore_c1's 4 offsets share one picker anyway).
            "id": "zelda_farore",
            "name": "Farore's Wind",
            "description": "Farore's Wind teleport-burst core flash color (up-B)",
            "target_file": "EfZdData.dat",
            "offsets": {
                # farore_c1 = the 4 PRIMCOL records (grnd s2 #0 + air s3 #0/#1/#2)
                "farore_c1": {"format": "RGB", "offsets": [0x257, 0x2B8, 0x2C5, 0x2CC]},
                # farore_c2 = the 2 ENVCOL records (grnd s2 + air s3)
                "farore_c2": {"format": "RGB", "offsets": [0x25E, 0x2BF]}
            },
            "vanilla": {
                # Grouped vanilla strings below are for the editor's reset
                # swatch only (first offset in each list: 0x257 / 0x25E);
                # relocate.py's per-offset guard uses the individual bytes
                # baked into the code, not this string.
                "farore_c1": "03860E",
                "farore_c2": "035814"
            },
            "properties": [
                {"id": "color1", "name": "Burst Core", "description": "Teleport-burst core flash color (up-B)", "format": "RGB"},
                {"id": "color2", "name": "Burst Glow", "description": "Teleport-burst environmental glow color (up-B)", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07-02, same spec. Transform chest-flash core orb/ring
            # (scripts 6 + 9, byte-identical per spec lesson 12 -- verified
            # equal, one grouped layer is safe). Fires on BOTH forms' down-B
            # transform (Zelda->Sheik AND Sheik->Zelda); owner Zelda,
            # sharedWith Sheik so the card also appears under Sheik's extras
            # tab (installs stored once under Zelda since the file is
            # shared -- common_fire/common_flash owner/sharedWith pattern).
            # The surrounding pink+blue sparkle STARS are a separate
            # element and stay put. Live-poke verified 2026-07-02 on BOTH
            # forms (green poke; tests/artifacts/datram-probe-zelda2/
            # transform_flash-downb-f04..18.png +
            # datram-probe-sheik2/sheik_transform_shared-downb-f10,f18.png).
            "id": "zelda_transform",
            "name": "Transform Flash",
            "description": "Zelda<->Sheik transform chest-flash core color (down-B, both forms)",
            "target_file": "EfZdData.dat",
            "shared": True,
            "sharedWith": ["Sheik"],
            "owner": "Zelda",
            "offsets": {
                # transform_c1 = core+secondary PRIMCOL, s6 then s9 (byte-identical)
                "transform_c1": {"format": "RGB", "offsets": [0x371, 0x37E, 0x67B, 0x688]},
                # transform_c2 = core+secondary ENVCOL, s6 then s9 (byte-identical)
                "transform_c2": {"format": "RGB", "offsets": [0x378, 0x385, 0x682, 0x68F]}
            },
            "vanilla": {
                "transform_c1": "6D68FF",
                "transform_c2": "000082"
            },
            "properties": [
                {"id": "color1", "name": "Flash Core", "description": "Transform chest-flash core color (down-B, both forms)", "format": "RGB"},
                {"id": "color2", "name": "Flash Glow", "description": "Transform chest-flash environmental glow color (down-B, both forms)", "format": "RGB"}
            ]
        }
    ],
    "Bowser": [
        {
            # WIRE 2026-07-02 from research/docs-research/effect-maps/bowser.md
            # "Shippable-now summary". Neutral-B fire breath: 11 CF particle
            # records across scripts 5-8 of EfKpData.dat (Nintendo cloned the
            # Whirling Fortress ptcl scripts for the flame). MAP-LIVE
            # verified 2026-07-02 (tests/artifacts/datram-probe-bowser/):
            # magenta-poking all 17 offsets turned the WHOLE near-field flame
            # body vivid pink -- the STATIC-pass fear that this would be
            # subtle/texture-dominant was wrong; these CF puffs ARE the
            # dominant flame color, texture only adds detail/highlights.
            # Layout: `CF <flag> RRGGBB AA AD DF 0X rrggbb`, color at
            # marker+2; most records also carry a SECONDARY color at
            # colorpos+7 that dominates sustained puff tint (template lesson
            # 3) -- those get `_c2` counterparts; a few records have no
            # meaningful secondary (bytes are 00 00 00, unused) and ship
            # `_c1`-only, exactly like Mario's `hand_ring_42_c1` precedent.
            # Every vanilla byte differs record-to-record (template lesson
            # 12), so each is its own offset key rather than a shared
            # vanilla string -- all 17 byte-verified against vanilla
            # `EfKpData.dat`. The `FFFFFF` white primaries are load-bearing:
            # per the spec, recoloring them is what turned the whole flame
            # magenta, so they ship alongside the already-orange records.
            # Single multi-record flame layer per the spec's grouping
            # recommendation (one editor entry, not split _c1/_c2 per
            # script) -- `_c1` = primaries (bright/birth), `_c2` = the +7
            # secondaries (sustained/fade fringe).
            "id": "bowser_fire_breath",
            "name": "Fire Breath",
            "description": "Neutral-B fire breath flame puff colors",
            "target_file": "EfKpData.dat",
            "offsets": {
                "fb_s5_a_c1": {"format": "RGB", "offsets": [0x3E2]},
                "fb_s5_a_c2": {"format": "RGB", "offsets": [0x3E9]},
                "fb_s5_x_c1": {"format": "RGB", "offsets": [0x3FB]},
                "fb_s5_b_c1": {"format": "RGB", "offsets": [0x40F]},
                "fb_s6_a_c1": {"format": "RGB", "offsets": [0x490]},
                "fb_s6_a_c2": {"format": "RGB", "offsets": [0x497]},
                "fb_s6_b_c1": {"format": "RGB", "offsets": [0x49D]},
                "fb_s6_b_c2": {"format": "RGB", "offsets": [0x4A4]},
                "fb_s6_c_c1": {"format": "RGB", "offsets": [0x4BB]},
                "fb_s7_a_c1": {"format": "RGB", "offsets": [0x566]},
                "fb_s7_a_c2": {"format": "RGB", "offsets": [0x56D]},
                "fb_s7_b_c1": {"format": "RGB", "offsets": [0x573]},
                "fb_s7_b_c2": {"format": "RGB", "offsets": [0x57A]},
                "fb_s7_c_c1": {"format": "RGB", "offsets": [0x587]},
                "fb_s8_a_c1": {"format": "RGB", "offsets": [0x5EE]},
                "fb_s8_b_c1": {"format": "RGB", "offsets": [0x609]},
                "fb_s8_c_c1": {"format": "RGB", "offsets": [0x628]}
            },
            "vanilla": {
                "fb_s5_a_c1": "FFFFFF",
                "fb_s5_a_c2": "FFE851",
                "fb_s5_x_c1": "FFFFFF",
                "fb_s5_b_c1": "FFD9B8",
                "fb_s6_a_c1": "FFFFFF",
                "fb_s6_a_c2": "C06401",
                "fb_s6_b_c1": "FF804A",
                "fb_s6_b_c2": "942514",
                "fb_s6_c_c1": "FFA973",
                "fb_s7_a_c1": "FFC607",
                "fb_s7_a_c2": "FF0206",
                "fb_s7_b_c1": "FFEF40",
                "fb_s7_b_c2": "FF0A0E",
                "fb_s7_c_c1": "FFFFFF",
                "fb_s8_a_c1": "FFFFFF",
                "fb_s8_b_c1": "FFFFFF",
                "fb_s8_c_c1": "FFD9B8"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Fire breath flame puff primary color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Fire breath sustained puff tint", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07-03, the bowser.md "texture lead" shipped. The fire
            # breath's flame BODY is a 9-frame animated CI8 billboard in
            # EfKpData.dat's tex bank (ptcl_texbank: single group 0 @0x660,
            # 9x 64x64 CI8, images 0x6C0+i*0x1000, palettes 0x96C0+i*0x200,
            # extent 0x6C0..0xA8C0). The scripts 5-8 CF puffs
            # (bowser_fire_breath) tint it, but the texture's own orange
            # modulates through -- most visibly on LANDED ground flames,
            # where the one-shot efSync ptcl spawn (itkoopaflame.c
            # x44_spawned) has faded and the burning item's textured quads
            # dominate. Community corroboration: post 14698 "Blue Fire
            # Bowser" diffs EXACTLY this extent (41276 bytes, 0 outside).
            # Recolor = hue-rotate each frame's PALETTE entries; pixel
            # indices untouched (upb_charge_fire precedent). Vanilla
            # dominant hue 28.2 measured over all 9 palettes.
            "id": "breath_texture",
            "part_of": "bowser_fire_breath",  # edited inside the bowser_fire_breath unit (see UNIT_PARTS)
            "name": "Fire Breath Texture",
            "description": "Fire breath flame body texture color -- the textured fire that lingers where the flames land",
            "target_file": "EfKpData.dat",
            "format": "texture_recolor",
            "texture": {
                "gx_format": 9,   # CI8
                "width": 64,
                "height": 64,
                "images": [
                    {"offset": "0x6C0", "palette": "0x96C0"},
                    {"offset": "0x16C0", "palette": "0x98C0"},
                    {"offset": "0x26C0", "palette": "0x9AC0"},
                    {"offset": "0x36C0", "palette": "0x9CC0"},
                    {"offset": "0x46C0", "palette": "0x9EC0"},
                    {"offset": "0x56C0", "palette": "0xA0C0"},
                    {"offset": "0x66C0", "palette": "0xA2C0"},
                    {"offset": "0x76C0", "palette": "0xA4C0"},
                    {"offset": "0x86C0", "palette": "0xA6C0"}
                ],
                "palette_format": 2  # RGB5A3
            },
            "vanilla_dominant_hue": 28.2,
            "vanilla": {
                "color1": "FF7800"  # representative vanilla swatch (hue 28.2 at full S/V)
            },
            "properties": [
                {"id": "color1", "name": "Flame Texture Color", "description": "Fire breath flame body texture color", "format": "RGB"}
            ]
        }
    ],
    "Jigglypuff": [
        {
            # WIRE 2026-07-02 from research/docs-research/effect-maps/jigglypuff.md
            # "Shippable-now summary". Sing (up-B) draws three musical notes
            # circling Jiggly -- MODEL-REGION geometry in EfPrData.dat (NOT
            # ptcl), each note a 070707 vertex-color pair: marker+4 = bright
            # core, marker+8 = fill/glow (block format doc, spec lesson 2).
            # LIVE-poke verified 2026-07-02 (tests/artifacts/
            # datram-probe-jigglypuff/): red core/glow poked green -> bottom
            # note turned green; blue poked orange -> upper-left note turned
            # orange; green poked magenta -> right note turned magenta. All
            # per-record vanilla byte-verified against storage/test-base/
            # files/EfPrData.dat (spec lesson 12 -- these do NOT share one
            # vanilla string; each note's core is FFFFFF but each glow
            # differs). Shipped as SIX independent per-note-color properties
            # (not a _c1/_c2 fan-out pair) so each of the three notes can be
            # themed on its own -- DualColorEditorModal renders one
            # ColorPicker per `properties` entry generically, no suffix
            # fan-out needed since each property id IS its own offset key.
            # The 42_48 note-material diffuses (blue @0x5574, green @0x5634)
            # are DELIBERATELY left unshipped per the spec: LIVE could not
            # isolate their contribution (poked together with the 070707
            # pair every time; the note body fully recolored from the
            # 070707 pair alone) and there is no red material block at all.
            # Open lead research/docs-research/effect-maps/jigglypuff.md "Open leads"
            # #2 if a future pass wants to try isolating them.
            "id": "sing_notes",
            "name": "Sing Notes",
            "description": "Up-B Sing musical note colors (red/blue/green, each independently themeable)",
            "target_file": "EfPrData.dat",
            "offsets": {
                "note_red_core": {"start": 0x5444, "size": 3, "format": "RGB"},
                "note_red_glow": {"start": 0x5448, "size": 3, "format": "RGB"},
                "note_blue_core": {"start": 0x5504, "size": 3, "format": "RGB"},
                "note_blue_glow": {"start": 0x5508, "size": 3, "format": "RGB"},
                "note_green_core": {"start": 0x55C4, "size": 3, "format": "RGB"},
                "note_green_glow": {"start": 0x55C8, "size": 3, "format": "RGB"}
            },
            "vanilla": {
                "note_red_core": "FFFFFF",
                "note_red_glow": "FF0000",
                "note_blue_core": "FFFFFF",
                "note_blue_glow": "0000FF",
                "note_green_core": "FFFFFF",
                "note_green_glow": "00FF00"
            },
            "properties": [
                {"id": "note_red_core", "name": "Red Note Core", "description": "Red note bright core", "format": "RGB"},
                {"id": "note_red_glow", "name": "Red Note Glow", "description": "Red note fill/glow", "format": "RGB"},
                {"id": "note_blue_core", "name": "Blue Note Core", "description": "Blue note bright core", "format": "RGB"},
                {"id": "note_blue_glow", "name": "Blue Note Glow", "description": "Blue note fill/glow", "format": "RGB"},
                {"id": "note_green_core", "name": "Green Note Core", "description": "Green note bright core", "format": "RGB"},
                {"id": "note_green_glow", "name": "Green Note Glow", "description": "Green note fill/glow", "format": "RGB"}
            ]
        }
    ],
    "Ganondorf": [
        {
            # WIRE 2026-07-02 from research/docs-research/effect-maps/ganondorf.md
            # LIVE section. Ganondorf reuses ftCaptain code (Falcon clone,
            # offset +0x7C on every symbolic effect id) but the ptcl colors
            # are genuine dark-purple recolors, not a byte-identical clone --
            # scripts 0+1 (0x4A38/0x4A39) are the Warlock/Falcon Punch dark
            # aura + fist-explosion burst. LIVE-poke 2026-07-02
            # (probe-ganondorf/warlock_punch-neutralb-f50.png): green poke on
            # the fist_* records replaced the vanilla purple connect-burst on
            # the VICTIM at contact (needs the punching-bag harness --
            # bag dk, dx 11 -- to demonstrate; the f30 solo charge starburst
            # is a different, unpoked script and stays purple). Per spec
            # lesson 12 the group's vanilla bytes do NOT share one string --
            # two distinct blacks plus four distinct purples -- so every
            # record with a DIFFERENT vanilla byte value gets its OWN offset
            # key (mario_fireball hand_smoke_a/b/c precedent), each a
            # single-offset RGB list. _c1 suffix = PRIMCOL (birth/bright),
            # _c2 = ENVCOL (sustained/fade), following the falcon_punch/
            # falcon_kick _c1/_c2 convention (DualColorEditorModal fans both
            # pickers across every _c1/_c2-suffixed offset key). All 12
            # offsets byte-verified 2026-07-02 against vanilla EfGnData.dat.
            "id": "warlock_punch",
            "name": "Warlock Punch",
            "description": "Warlock Punch dark aura and fist-explosion colors (best seen on contact)",
            "target_file": "EfGnData.dat",
            "offsets": {
                "punch_a_c1": {"format": "RGB", "offsets": [0x154]},
                "punch_a_c2": {"format": "RGB", "offsets": [0x15B]},
                "punch_b_c1": {"format": "RGB", "offsets": [0x161]},
                "punch_b_c2": {"format": "RGB", "offsets": [0x168]},
                "punch_c_c1": {"format": "RGB", "offsets": [0x192]},
                "punch_c_c2": {"format": "RGB", "offsets": [0x199]},
                "fist_a_c1": {"format": "RGB", "offsets": [0x224]},
                "fist_a_c2": {"format": "RGB", "offsets": [0x22B]},
                "fist_b_c1": {"format": "RGB", "offsets": [0x231]},
                "fist_b_c2": {"format": "RGB", "offsets": [0x238]},
                "fist_c_c1": {"format": "RGB", "offsets": [0x262]},
                "fist_c_c2": {"format": "RGB", "offsets": [0x269]}
            },
            "vanilla": {
                "punch_a_c1": "280021",
                "punch_a_c2": "11002E",
                "punch_b_c1": "47004F",
                "punch_b_c2": "130245",
                "punch_c_c1": "000000",
                "punch_c_c2": "1B0245",
                "fist_a_c1": "A200AB",
                "fist_a_c2": "400591",
                "fist_b_c1": "75039C",
                "fist_b_c2": "280587",
                "fist_c_c1": "000000",
                "fist_c_c2": "540775"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Dark aura core and fist-explosion primary color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Dark aura and fist-explosion sustained tint", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07-02, same spec. Wizard's Foot (down-B) foot-fire --
            # script 6 (0x4CF/0x4D6) only. The spec's draft script 2
            # (0x306-0x31D) was LIVE-DEAD (poke had no visible effect on the
            # solo dash-trail) and is NOT shipped -- see
            # docs/dev/EXTRAS_AUDIT.md and the spec's "DO NOT SHIP" section.
            # LIVE-poke 2026-07-02 (probe-ganondorf-leads/leads_downb-
            # downb-f24.png & -f30.png): green poke on script 6 produced
            # green foot-fire streaks under Ganon during the dash. The larger
            # purple impact starburst on connect is a still-unattributed
            # script (open lead, not this layer). Solo down-B whiff is
            # sufficient to demonstrate -- no bag needed.
            "id": "wizards_foot",
            "name": "Wizard's Foot",
            "description": "Wizard's Foot dash foot-fire streak colors",
            "target_file": "EfGnData.dat",
            "offsets": {
                "color1": {"start": 0x4CF, "size": 3, "format": "RGB"},
                "color2": {"start": 0x4D6, "size": 3, "format": "RGB"}
            },
            "vanilla": {
                "color1": "FFDEFF",
                "color2": "3D0261"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Foot-fire streak core color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Foot-fire streak sustained tint", "format": "RGB"}
            ]
        },
        {
            # WIRE 2026-07-02 from research/docs-research/effect-maps/ganondorf.md
            # SS5b NARROW CONFIRM section. gerudo_dragon = the purple/
            # magenta flame aura that engulfs the victim on the Gerudo/Flame
            # Choke (side-B) command-grab connect -- scripts 12/14/15/16
            # (0x76C-0x9BC). Found via a 2-stage sweep: the earlier draft
            # script 4 (0x3CC-0x3E3) was LIVE-DEAD (grab-connect burst
            # unchanged) and is NOT shipped; a broad sweep_B poke
            # (s12/14/15/16, green) then showed a clear tint change on the
            # flame at connect using the NEW --bag-pin harness option (zeros
            # the bag's knockback + re-pins its position every stepped
            # frame -- unblocks command grabs, which otherwise knock the bag
            # out of re-grab range after the first slam, per lesson 19); a
            # final NARROW CONFIRM poke (s12/14/15/16 ONLY, cyan) isolated
            # the aura cleanly at f20/f26 -- the white smoke puffs (s7/9/10/
            # 11, a separate sibling script group) stayed white and the
            # impact green-ray starburst + white flash (yet another
            # unattributed script) stayed vanilla, confirming s12/14/15/16
            # own the flame aura alone. AUDIT_HINTS MUST use bag dk dx=5
            # pin=true (the narrow-confirm recipe) -- a non-pinned bag can't
            # be re-grabbed after the first knockdown. All 26 offsets
            # byte-verified 2026-07-02 against vanilla EfGnData.dat via
            # ptcl_parse (every record has a DISTINCT vanilla value per
            # lesson 12 -- no two records share a byte string, so each gets
            # its own key, following the warlock_punch precedent above).
            # _c1 = PRIMCOL (flame bright/birth), _c2 = ENVCOL (sustained
            # flame tint).
            "id": "gerudo_dragon",
            "name": "Gerudo Dragon",
            "description": "Gerudo Dragon (side-B command grab) flame aura colors (best seen on contact)",
            "target_file": "EfGnData.dat",
            "offsets": {
                # script 12 (0x76C-0x7B6)
                "s12_a_c1": {"format": "RGB", "offsets": [0x76C]},
                "s12_a_c2": {"format": "RGB", "offsets": [0x773]},
                "s12_b_c1": {"format": "RGB", "offsets": [0x779]},
                "s12_b_c2": {"format": "RGB", "offsets": [0x780]},
                "s12_c_c1": {"format": "RGB", "offsets": [0x7AF]},
                "s12_c_c2": {"format": "RGB", "offsets": [0x7B6]},
                # script 14 (0x875-0x8BD)
                "s14_a_c1": {"format": "RGB", "offsets": [0x875]},
                "s14_a_c2": {"format": "RGB", "offsets": [0x87C]},
                "s14_b_c1": {"format": "RGB", "offsets": [0x885]},
                "s14_b_c2": {"format": "RGB", "offsets": [0x88C]},
                "s14_c_c1": {"format": "RGB", "offsets": [0x895]},
                "s14_c_c2": {"format": "RGB", "offsets": [0x89C]},
                "s14_d_c1": {"format": "RGB", "offsets": [0x8A5]},
                "s14_d_c2": {"format": "RGB", "offsets": [0x8AC]},
                "s14_e_c1": {"format": "RGB", "offsets": [0x8B6]},
                "s14_e_c2": {"format": "RGB", "offsets": [0x8BD]},
                # script 15 (0x92C-0x943)
                "s15_a_c1": {"format": "RGB", "offsets": [0x92C]},
                "s15_a_c2": {"format": "RGB", "offsets": [0x933]},
                "s15_b_c1": {"format": "RGB", "offsets": [0x93C]},
                "s15_b_c2": {"format": "RGB", "offsets": [0x943]},
                # script 16 (0x9A0-0x9C3)
                "s16_a_c1": {"format": "RGB", "offsets": [0x9A0]},
                "s16_a_c2": {"format": "RGB", "offsets": [0x9A7]},
                "s16_b_c1": {"format": "RGB", "offsets": [0x9AE]},
                "s16_b_c2": {"format": "RGB", "offsets": [0x9B5]},
                "s16_c_c1": {"format": "RGB", "offsets": [0x9BC]},
                "s16_c_c2": {"format": "RGB", "offsets": [0x9C3]}
            },
            "vanilla": {
                "s12_a_c1": "F2D1FF", "s12_a_c2": "2D0359",
                "s12_b_c1": "7C40D7", "s12_b_c2": "280242",
                "s12_c_c1": "1F0138", "s12_c_c2": "000000",
                "s14_a_c1": "BEA7CA", "s14_a_c2": "9609C5",
                "s14_b_c1": "C607FF", "s14_b_c2": "5E06A1",
                "s14_c_c1": "B07FC7", "s14_c_c2": "AD33E1",
                "s14_d_c1": "81198C", "s14_d_c2": "500BA3",
                "s14_e_c1": "3D087D", "s14_e_c2": "3E034F",
                "s15_a_c1": "7605B3", "s15_a_c2": "D88AFF",
                "s15_b_c1": "D873FF", "s15_b_c2": "730AAB",
                "s16_a_c1": "E36DF3", "s16_a_c2": "A007FF",
                "s16_b_c1": "2D0047", "s16_b_c2": "220133",
                "s16_c_c1": "D1C3DE", "s16_c_c2": "000000"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Gerudo Dragon flame aura core color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Gerudo Dragon flame aura sustained tint", "format": "RGB"}
            ]
        }
    ],
    "Ice Climbers": [
        {
            # WIRE 2026-07-02 from research/docs-research/effect-maps/iceclimbers.md
            # LIVE section. Ice Shot (neutral-B) is a forward-firing
            # PROJECTILE, fully solo-visible -- covers the birth swirl
            # (script 0), the block-glow variants (scripts 3/4), and the
            # sparkle family (Family A: scripts 2/6/8/12, identical vanilla
            # bytes across all four generators -- one visual, four spawns).
            # EfIcData.dat is a SHARED file (efAsync_DatEntries has exactly
            # ONE EfIc entry) -- both Popo and Nana resolve the same bank, so
            # one patch covers both climbers automatically; there is no
            # separate Nana copy to also patch (unlike a fighter-DAT edit).
            # Owner key follows the existing CHAR_DAT_PREFIX / char_select.py
            # convention: config character = "Ice Climbers" (already used at
            # CHAR_DAT_PREFIX["Ice Climbers"] = "PlPp"); the in-game/audit
            # char key is "iceclimbers" (char_select.py canonical, aliases
            # ics/icies/popo all resolve to it).
            # LIVE-poke 2026-07-02 (probe-iceclimbers-solo/): birth swirl
            # vortex turned red (ice_shot_birth-neutralb-f10.png, vanilla
            # blue -> red); block-base sparkle burst turned red, SUBTLE --
            # flagged for EYEBALL double-check at f22
            # (ice_shot_sparkle-neutralb-f22.png); one ice block's internal
            # glow turned red (ice_shot_variants-neutralb-f22.png). freeze
            # crystals (Family B, scripts 9/11/13/15) are LIVE-DEAD (freeze
            # snowflake/crystal stayed blue -- item texture, not this ptcl
            # bank) and are NOT shipped, per the spec's "DO NOT SHIP" section.
            # Per spec lesson 12, per-record vanilla bytes DIFFER across the
            # birth/sparkle/variants groups -- each DISTINCT vanilla value
            # gets its own offset key (mario_fireball hand_smoke_a/b/c
            # precedent); offsets that share an IDENTICAL vanilla value stay
            # grouped in one key's offsets list (Family A's 4 sparkle
            # generators are byte-identical, so they collapse to one key
            # each for PRIM/PRIM-b/ENV). All offsets byte-verified
            # 2026-07-02 against vanilla EfIcData.dat.
            "id": "ice_shot",
            "name": "Ice Shot",
            "description": "Ice Shot (neutral-B) birth swirl, block glow, and sparkle colors -- affects both Popo and Nana",
            "target_file": "EfIcData.dat",
            "offsets": {
                # script 0 -- birth flash
                "birth_a_c1": {"format": "RGB", "offsets": [0xE2]},
                "birth_a_c2": {"format": "RGB", "offsets": [0xE9]},
                "birth_b_c1": {"format": "RGB", "offsets": [0xEF]},
                "birth_b_c2": {"format": "RGB", "offsets": [0xF6]},
                "birth_c_c1": {"format": "RGB", "offsets": [0x103]},
                # Family A sparkle (scripts 2,6,8,12) -- identical vanilla
                # bytes across all four generators, one key each
                "sparkle_c1": {"format": "RGB", "offsets": [0x1A5, 0x335, 0x3EC, 0x58C]},
                "sparkle_c2": {"format": "RGB", "offsets": [0x1AC, 0x33C, 0x3F3, 0x593]},
                "sparkle2_c1": {"format": "RGB", "offsets": [0x1B2, 0x342, 0x3F9, 0x599]},
                # scripts 3/4 -- block-glow variants
                "variant_a_c1": {"format": "RGB", "offsets": [0x20E]},
                "variant_a_c2": {"format": "RGB", "offsets": [0x215]},
                "variant_b_c1": {"format": "RGB", "offsets": [0x21B]},
                "variant_c_c1": {"format": "RGB", "offsets": [0x276]},
                "variant_c_c2": {"format": "RGB", "offsets": [0x27D]},
                "variant_d_c1": {"format": "RGB", "offsets": [0x283]}
            },
            "vanilla": {
                "birth_a_c1": "79B8F7",
                "birth_a_c2": "0101F9",
                "birth_b_c1": "2E66FF",
                "birth_b_c2": "0B07EE",
                "birth_c_c1": "679CFE",
                "sparkle_c1": "FAFCFF",
                "sparkle_c2": "515DFF",
                "sparkle2_c1": "BAEEFF",
                "variant_a_c1": "FAFCFF",
                "variant_a_c2": "2E17FF",
                "variant_b_c1": "1AB4DE",
                "variant_c_c1": "FAFCFF",
                "variant_c_c2": "2E17FF",
                "variant_d_c1": "82EBFF"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Ice Shot birth swirl and sparkle core color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Ice Shot sustained blue tint", "format": "RGB"}
            ]
        }
    ],
    "Kirby": [
        {
            # WIRE 2026-07-02 from research/docs-research/effect-maps/kirby.md
            # Shippable-now section. kirby_stone = the Stone (down-B)
            # transform-burst dust: scripts s8/s9/s14 carry the DOMINANT
            # visible color (poked magenta -> the entire radial burst +
            # rock-debris tint + swirl rings turned bright magenta,
            # unambiguous); s5 (ground-transform starburst) is a subtler
            # secondary contributor, poked magenta gave a real but fainter
            # recolor of the early burst. s6 (air-stone transform, draft
            # candidate) LIVE-poked DEAD -- no visible change -- and is NOT
            # shipped per the spec's explicit exclusion. Final Cutter,
            # Hammer, Inhale, and Puff-air are ALL dead in EfKbData's ptcl
            # bank (model/texture/item-article driven) -- do not add them
            # here; see the spec's DEAD section. Per spec lesson 12 every
            # record's vanilla bytes were re-verified byte-exact against
            # storage/test-base/files/EfKbData.dat 2026-07-02 (matches the
            # spec's ptcl_parse dump s2 verbatim) -- s8/s9/s14 share
            # FFFFFF14/FFFFFFFF/FFFFFF00-style dim-alpha PRIM records but
            # each is its own distinct byte string per record, so each gets
            # its own offset key (mario_fireball hand_smoke_a/b/c
            # precedent); the RGB byte is at the ptcl_parse file_off (probe
            # pokes RGB directly there, matching falcon_kick's direct-RGB
            # convention). _c1 = PRIMCOL (dust/debris bright), _c2 = the one
            # ENVCOL (s9's teal sustain tint).
            "id": "kirby_stone",
            "name": "Stone",
            "description": "Stone (down-B) transform-burst dust and rock-debris colors",
            "target_file": "EfKbData.dat",
            "offsets": {
                # s8 transform dust (dominant)
                "dust_a_c1": {"format": "RGB", "offsets": [0x51E]},
                "dust_b_c1": {"format": "RGB", "offsets": [0x52B]},
                "dust_c_c1": {"format": "RGB", "offsets": [0x532]},
                # s9 grey dust + teal env (dominant)
                "s9_a_c1": {"format": "RGB", "offsets": [0x58B]},
                "s9_a_c2": {"format": "RGB", "offsets": [0x592]},
                "s9_b_c1": {"format": "RGB", "offsets": [0x598]},
                "s9_c_c1": {"format": "RGB", "offsets": [0x59F]},
                # s14 stone-break dust (dominant)
                "brk_a_c1": {"format": "RGB", "offsets": [0x796]},
                "brk_b_c1": {"format": "RGB", "offsets": [0x7A3]},
                # s5 ground-transform starburst (secondary, subtler)
                "ground_a_c1": {"format": "RGB", "offsets": [0x381]},
                "ground_b_c1": {"format": "RGB", "offsets": [0x38E]},
                "ground_c_c1": {"format": "RGB", "offsets": [0x3A9]},
                "ground_d_c1": {"format": "RGB", "offsets": [0x3AF]}
            },
            "vanilla": {
                "dust_a_c1": "FFFFFF",
                "dust_b_c1": "FFFFFF",
                "dust_c_c1": "FFFFFF",
                "s9_a_c1": "CCCCCC",
                "s9_a_c2": "09A9BA",
                "s9_b_c1": "CACACA",
                "s9_c_c1": "BABABA",
                "brk_a_c1": "FFFFFF",
                "brk_b_c1": "FFFFFF",
                "ground_a_c1": "FFFF00",
                "ground_b_c1": "FFFFFF",
                "ground_c_c1": "FFFFFF",
                "ground_d_c1": "FFFF00"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Transform-burst dust and rock-debris core color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Dust sustained teal tint", "format": "RGB"}
            ]
        },
        # --- Copy Abilities (WIRE 2026-07-02, research/docs-research/effect-maps/kirby.md
        # section 6). Kirby's copy abilities load a per-donor EfKb<XX>.dat whose
        # ptcl bank is a byte-identical SLICE of the donor's own EfXxData.dat
        # bank at shifted offsets (proven via ptcl_parse (script ordinal, in-
        # script operand ordinal, bytes) matching -- NOT absolute-offset diffing,
        # since the copy's smaller header shifts every record). Each copy's
        # `effect_id_start` is the donor's COPY-range id (e.g. EfKbGn=47000 vs
        # EfGnData's own 4000), and Kirby's copied specials
        # (ftKirby/ftkirbyspecial<donor>.c efSync_Spawn) resolve exclusively
        # into that copy-range bank (decomp-verified, kirby.md 6.0) -- so
        # recoloring EfKbGn recolors ONLY Kirby's copied Warlock Punch, never
        # touching Ganondorf's own EfGnData. This is what makes a per-copy
        # extra clean and non-colliding; hence ONE `kirby_copy_<donor>` extra
        # per copy file (owner Kirby), not a single mega-extra.
        #
        # SHIP SCOPE: only the 5 copies whose ptcl records are FULL/high-overlap
        # byte-identical twins of an ALREADY-SHIPPED+VERIFIED donor extra (Gn/Ic/
        # Kp/Lg/Mr, kirby.md 6.3 "6 ship on parser+decomp confidence" -- no 6th
        # free copy is named beyond these 5). The LIVE-hold three (EfKbCa/Ss/Pk
        # + EfKbPc) are NOT wired here -- see kirby.md 6.4: the solo-Kirby
        # shared/ingame/ harness has no inhale+swallow+copy primitive, so a copied
        # special never loads those copy banks in a boot (HARNESS GAP, not a
        # data problem). Offsets below are the COPY file's own shifted
        # positions (re-derived directly from ptcl_parse against storage/
        # test-base/files/EfKb<XX>.dat, then position-matched script-by-script
        # against the donor's already-shipped config to confirm byte-identity --
        # every value below was read straight off the vanilla file bytes, not
        # transcribed from the spec's abbreviated section 6.1 tables). Records
        # whose donor twin exists in the copy bank but was never shipped as a
        # donor layer (e.g. Ganon's script 2, ICS's script 5, Mario/Luigi's
        # model-region-only records) are excluded, matching the "byte-identical
        # to an ALREADY-SHIPPED donor extra" scope -- not the full copy bank.
        # Preview: DualColorEditorModal/ExtraPreviews reuse the donor's own
        # preview branch (a copied ability looks like the donor effect); no new
        # preview shapes were authored. Pictograms: skipped gracefully (the
        # registry keys strictly on `<extraId>_<layerId>.png`, so a copy can't
        # trivially alias a donor's PNG without new assets/registry plumbing --
        # `pictogramSrc` already returns null for unregistered ids). No editor
        # section-heading mechanism exists in the UI (flat extra list per
        # character) -- shipped as standard extra rows, named "Copy Ability: X"
        # in their `name` field so they read as a group.
        {
            "id": "kirby_copy_ganon",
            "name": "Copy Ability: Warlock Punch",
            "description": "Copied Warlock Punch dark aura and fist-explosion colors (twins the donor Ganondorf warlock_punch extra, 12/12 records)",
            "target_file": "EfKbGn.dat",
            "offsets": {
                "punch_a_c1": {"format": "RGB", "offsets": [0xE4]},
                "punch_a_c2": {"format": "RGB", "offsets": [0xEB]},
                "punch_b_c1": {"format": "RGB", "offsets": [0xF1]},
                "punch_b_c2": {"format": "RGB", "offsets": [0xF8]},
                "punch_c_c1": {"format": "RGB", "offsets": [0x122]},
                "punch_c_c2": {"format": "RGB", "offsets": [0x129]},
                "fist_a_c1": {"format": "RGB", "offsets": [0x1B4]},
                "fist_a_c2": {"format": "RGB", "offsets": [0x1BB]},
                "fist_b_c1": {"format": "RGB", "offsets": [0x1C1]},
                "fist_b_c2": {"format": "RGB", "offsets": [0x1C8]},
                "fist_c_c1": {"format": "RGB", "offsets": [0x1F2]},
                "fist_c_c2": {"format": "RGB", "offsets": [0x1F9]}
            },
            "vanilla": {
                "punch_a_c1": "280021",
                "punch_a_c2": "11002E",
                "punch_b_c1": "47004F",
                "punch_b_c2": "130245",
                "punch_c_c1": "000000",
                "punch_c_c2": "1B0245",
                "fist_a_c1": "A200AB",
                "fist_a_c2": "400591",
                "fist_b_c1": "75039C",
                "fist_b_c2": "280587",
                "fist_c_c1": "000000",
                "fist_c_c2": "540775"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Copied dark aura core and fist-explosion primary color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Copied dark aura and fist-explosion sustained tint", "format": "RGB"}
            ]
        },
        {
            "id": "kirby_copy_iceclimbers",
            "name": "Copy Ability: Ice Shot",
            "description": "Copied Ice Shot birth swirl and block-glow colors (twins the donor Ice Climbers ice_shot extra, 17 of 19 copy records matching shipped donor layers)",
            "target_file": "EfKbIc.dat",
            "offsets": {
                "birth_a_c1": {"format": "RGB", "offsets": [0xBA]},
                "birth_a_c2": {"format": "RGB", "offsets": [0xC1]},
                "birth_b_c1": {"format": "RGB", "offsets": [0xC7]},
                "birth_b_c2": {"format": "RGB", "offsets": [0xCE]},
                "birth_c_c1": {"format": "RGB", "offsets": [0xDB]},
                "sparkle_c1": {"format": "RGB", "offsets": [0x17D, 0x30D]},
                "sparkle_c2": {"format": "RGB", "offsets": [0x184, 0x314]},
                "sparkle2_c1": {"format": "RGB", "offsets": [0x18A, 0x31A]},
                "variant_a_c1": {"format": "RGB", "offsets": [0x1E6]},
                "variant_a_c2": {"format": "RGB", "offsets": [0x1ED]},
                "variant_b_c1": {"format": "RGB", "offsets": [0x1F3]},
                "variant_c_c1": {"format": "RGB", "offsets": [0x24E]},
                "variant_c_c2": {"format": "RGB", "offsets": [0x255]},
                "variant_d_c1": {"format": "RGB", "offsets": [0x25B]}
            },
            "vanilla": {
                "birth_a_c1": "79B8F7",
                "birth_a_c2": "0101F9",
                "birth_b_c1": "2E66FF",
                "birth_b_c2": "0B07EE",
                "birth_c_c1": "679CFE",
                "sparkle_c1": "FAFCFF",
                "sparkle_c2": "515DFF",
                "sparkle2_c1": "BAEEFF",
                "variant_a_c1": "FAFCFF",
                "variant_a_c2": "2E17FF",
                "variant_b_c1": "1AB4DE",
                "variant_c_c1": "FAFCFF",
                "variant_c_c2": "2E17FF",
                "variant_d_c1": "82EBFF"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Copied Ice Shot birth swirl and sparkle core color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Copied Ice Shot sustained blue tint", "format": "RGB"}
            ]
        },
        {
            "id": "kirby_copy_bowser",
            "name": "Copy Ability: Fire Breath",
            "description": "Copied fire breath flame puff colors (twins the donor Bowser bowser_fire_breath extra, 17/17 records)",
            "target_file": "EfKbKp.dat",
            "offsets": {
                "fb_s5_a_c1": {"format": "RGB", "offsets": [0xA2]},
                "fb_s5_a_c2": {"format": "RGB", "offsets": [0xA9]},
                "fb_s5_x_c1": {"format": "RGB", "offsets": [0xBB]},
                "fb_s5_b_c1": {"format": "RGB", "offsets": [0xCF]},
                "fb_s6_a_c1": {"format": "RGB", "offsets": [0x150]},
                "fb_s6_a_c2": {"format": "RGB", "offsets": [0x157]},
                "fb_s6_b_c1": {"format": "RGB", "offsets": [0x15D]},
                "fb_s6_b_c2": {"format": "RGB", "offsets": [0x164]},
                "fb_s6_c_c1": {"format": "RGB", "offsets": [0x17B]},
                "fb_s7_a_c1": {"format": "RGB", "offsets": [0x226]},
                "fb_s7_a_c2": {"format": "RGB", "offsets": [0x22D]},
                "fb_s7_b_c1": {"format": "RGB", "offsets": [0x233]},
                "fb_s7_b_c2": {"format": "RGB", "offsets": [0x23A]},
                "fb_s7_c_c1": {"format": "RGB", "offsets": [0x247]},
                "fb_s8_a_c1": {"format": "RGB", "offsets": [0x2AE]},
                "fb_s8_b_c1": {"format": "RGB", "offsets": [0x2C9]},
                "fb_s8_c_c1": {"format": "RGB", "offsets": [0x2E8]}
            },
            "vanilla": {
                "fb_s5_a_c1": "FFFFFF",
                "fb_s5_a_c2": "FFE851",
                "fb_s5_x_c1": "FFFFFF",
                "fb_s5_b_c1": "FFD9B8",
                "fb_s6_a_c1": "FFFFFF",
                "fb_s6_a_c2": "C06401",
                "fb_s6_b_c1": "FF804A",
                "fb_s6_b_c2": "942514",
                "fb_s6_c_c1": "FFA973",
                "fb_s7_a_c1": "FFC607",
                "fb_s7_a_c2": "FF0206",
                "fb_s7_b_c1": "FFEF40",
                "fb_s7_b_c2": "FF0A0E",
                "fb_s7_c_c1": "FFFFFF",
                "fb_s8_a_c1": "FFFFFF",
                "fb_s8_b_c1": "FFFFFF",
                "fb_s8_c_c1": "FFD9B8"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Copied fire breath flame puff primary color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Copied fire breath sustained puff tint", "format": "RGB"}
            ]
        },
        {
            "id": "kirby_copy_luigi",
            "name": "Copy Ability: Fireball Smoke",
            "description": "Copied fireball hand-spawn smoke colors (twins the donor Luigi luigi_fireball_smoke extra, 20 of 24 copy records matching shipped donor layers -- the 4 misses are Luigi's model-region green-fire blocks a ptcl copy can't carry)",
            "target_file": "EfKbLg.dat",
            "offsets": {
                "fb_smoke_s0a_c1": {"format": "RGB", "offsets": [0xC7]},
                "fb_smoke_s0a_c2": {"format": "RGB", "offsets": [0xCE]},
                "fb_smoke_s0b_c1": {"format": "RGB", "offsets": [0xD4]},
                "fb_smoke_s0b_c2": {"format": "RGB", "offsets": [0xDB]},
                "fb_smoke_s1_c1": {"format": "RGB",
                                    "offsets": [0x14E, 0x15C, 0x16F, 0x17C]},
                "fb_smoke_s1_c2": {"format": "RGB",
                                    "offsets": [0x155, 0x163, 0x176, 0x183]},
                "fb_smoke_s3_c1": {"format": "RGB", "offsets": [0x235]},
                "fb_smoke_s3_c2": {"format": "RGB", "offsets": [0x249]},
                "fb_smoke_s4_c1": {"format": "RGB", "offsets": [0x2A5]},
                "fb_smoke_s4_c2": {"format": "RGB", "offsets": [0x2B9]},
                "fb_dust_s5_c1": {"format": "RGB", "offsets": [0x31A]},
                "fb_dust_s5_c2": {"format": "RGB", "offsets": [0x33A]},
                "fb_particle_s6_c1": {"format": "RGB", "offsets": [0x3C6]},
                "fb_particle_s6_c2": {"format": "RGB", "offsets": [0x3D6]}
            },
            "vanilla": {
                "color1": "93A394",
                "color2": "22AB0A",
                "fb_smoke_s0a_c1": "26FF43",
                "fb_smoke_s0a_c2": "2ABA4E",
                "fb_smoke_s0b_c1": "149C2D",
                "fb_smoke_s0b_c2": "0C5419",
                "fb_smoke_s1_c1": "93A394",
                "fb_smoke_s1_c2": "22AB0A",
                "fb_smoke_s3_c1": "02FD02",
                "fb_smoke_s3_c2": "052E15",
                "fb_smoke_s4_c1": "16FD22",
                "fb_smoke_s4_c2": "0A4F12",
                "fb_dust_s5_c1": "BDFDBB",
                "fb_dust_s5_c2": "31F83B",
                "fb_particle_s6_c1": "1ADC24",
                "fb_particle_s6_c2": "7CFF70"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Copied fireball hand-spawn smoke puff core color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Copied fireball smoke sustained tint", "format": "RGB"}
            ]
        },
        {
            "id": "kirby_copy_mario",
            "name": "Copy Ability: Fireball",
            "description": "Copied fireball smoke, trail, particle, and dust colors (twins the donor Mario mario_fireball extra, 30 of 33 copy records matching shipped donor layers -- the 3 misses are the 0x11Axx hand-ring model-region blocks a ptcl copy can't carry). NOTE the copy's script 0 clones the donor's script 1 (Mario's own script 0 is not present in the copy bank).",
            "target_file": "EfKbMr.dat",
            "offsets": {
                "hand_smoke_a_c1": {"format": "RGB", "offsets": [0xB2]},
                "hand_smoke_a_c2": {"format": "RGB", "offsets": [0xB9]},
                "hand_smoke_b_c1": {"format": "RGB", "offsets": [0xC7]},
                "hand_smoke_b_c2": {"format": "RGB", "offsets": [0xCE]},
                "hand_smoke_c_c1": {"format": "RGB", "offsets": [0xD4]},
                "hand_smoke_c_c2": {"format": "RGB", "offsets": [0xDB]},
                "trailing_fire_a_c1": {"format": "RGB", "offsets": [0x15C]},
                "trailing_fire_a_c2": {"format": "RGB", "offsets": [0x163]},
                "trailing_fire_b_c1": {"format": "RGB", "offsets": [0x16F]},
                "trailing_fire_b_c2": {"format": "RGB", "offsets": [0x176]},
                "trailing_fire_c_c1": {"format": "RGB", "offsets": [0x17C]},
                "trailing_fire_c_c2": {"format": "RGB", "offsets": [0x183]},
                "ball_particles_a_c1": {"format": "RGB", "offsets": [0x2A5]},
                "ball_particles_a_c2": {"format": "RGB", "offsets": [0x2AC]},
                "ball_particles_b_c1": {"format": "RGB", "offsets": [0x2B2]},
                "ball_particles_b_c2": {"format": "RGB", "offsets": [0x2B9]},
                "ball_particles_c_c1": {"format": "RGB", "offsets": [0x235]},
                "ball_particles_c_c2": {"format": "RGB", "offsets": [0x23C]},
                "ball_particles_d_c1": {"format": "RGB", "offsets": [0x242]},
                "ball_particles_d_c2": {"format": "RGB", "offsets": [0x249]},
                "landing_dust_a_c1": {"format": "RGB", "offsets": [0x31A]},
                "landing_dust_a_c2": {"format": "RGB", "offsets": [0x321]},
                "landing_dust_b_c1": {"format": "RGB", "offsets": [0x32D]},
                "landing_dust_b_c2": {"format": "RGB", "offsets": [0x334]},
                "landing_dust_c_c1": {"format": "RGB", "offsets": [0x33A]},
                "landing_dust_c_c2": {"format": "RGB", "offsets": [0x341]},
                "square_particles_a_c1": {"format": "RGB", "offsets": [0x3C6]},
                "square_particles_a_c2": {"format": "RGB", "offsets": [0x3CD]},
                "square_particles_b_c1": {"format": "RGB", "offsets": [0x3D6]},
                "square_particles_b_c2": {"format": "RGB", "offsets": [0x3DD]}
            },
            "vanilla": {
                "color1": "FFA217",
                "color2": "D43B08",
                "hand_smoke_a_c1": "FFFFFF",
                "hand_smoke_a_c2": "FFCC4A",
                "hand_smoke_b_c1": "FFA217",
                "hand_smoke_b_c2": "BA120D",
                "hand_smoke_c_c1": "9C060B",
                "hand_smoke_c_c2": "540405",
                "trailing_fire_a_c1": "C7BB0D",
                "trailing_fire_a_c2": "D43B08",
                "trailing_fire_b_c1": "FFA800",
                "trailing_fire_b_c2": "FF5900",
                "trailing_fire_c_c1": "FF070F",
                "trailing_fire_c_c2": "510A00",
                "ball_particles_a_c1": "FDEB74",
                "ball_particles_a_c2": "E33C09",
                "ball_particles_b_c1": "B90303",
                "ball_particles_b_c2": "610101",
                "ball_particles_c_c1": "FDE467",
                "ball_particles_c_c2": "D42304",
                "ball_particles_d_c1": "7D4202",
                "ball_particles_d_c2": "2E0000",
                "landing_dust_a_c1": "FEFCE2",
                "landing_dust_a_c2": "FFF75C",
                "landing_dust_b_c1": "FCE669",
                "landing_dust_b_c2": "D60B0E",
                "landing_dust_c_c1": "F9AC06",
                "landing_dust_c_c2": "6B0507",
                "square_particles_a_c1": "FF290C",
                "square_particles_a_c2": "FFFF82",
                "square_particles_b_c1": "FFFF6E",
                "square_particles_b_c2": "FF0C14"
            },
            "properties": [
                {"id": "color1", "name": "Primary", "description": "Copied fireball smoke/trail/particle core color", "format": "RGB"},
                {"id": "color2", "name": "Secondary", "description": "Copied fireball sustained tint / glow", "format": "RGB"}
            ]
        }
    ]
}

# A move is ONE extra with nested parts. The primary type's mods carry the
# parts' recipes under modifications['parts'][<part id>]; the part types stay
# in EXTRA_TYPES for id lookups / install logic but are edited inside the
# primary's editor and hidden from the menus (`part_of` on the part config).
# Legacy nested textures (upb -> 'fire' -> upb_texture, falcon_punch ->
# punch_texture) keep their own key; see vault/routes/extras/colors.py
# SIBLING_TEXTURE_EXTRAS.
UNIT_PARTS = {
    "upb": ["upb_charge_fire", "charge_flames"],
    "mario_fireball": ["mario_fireball_aura"],
    "luigi_fireball": ["luigi_fireball_smoke"],
    "bowser_fire_breath": ["breath_texture"],
    "charge_shot": ["charge_ball"],
}
PART_OWNER = {part: primary for primary, parts in UNIT_PARTS.items() for part in parts}


# Character to dat file prefix mapping
CHAR_DAT_PREFIX = {
    "C. Falcon": "PlCa",
    "Falco": "PlFc",
    "Fox": "PlFx",
    "Marth": "PlMs",
    "Roy": "PlFe",
    "Bowser": "PlKp",
    "DK": "PlDk",
    "Ganondorf": "PlGn",
    "Jigglypuff": "PlPr",
    "Kirby": "PlKb",
    "Link": "PlLk",
    "Luigi": "PlLg",
    "Mario": "PlMr",
    "Mewtwo": "PlMt",
    "Ness": "PlNs",
    "Peach": "PlPe",
    "Pichu": "PlPc",
    "Pikachu": "PlPk",
    "Ice Climbers": "PlPp",
    "Samus": "PlSs",
    "Sheik": "PlSk",
    "Yoshi": "PlYs",
    "Young Link": "PlCl",
    "Zelda": "PlZd",
    "Dr. Mario": "PlDr",
    "G&W": "PlGw"
}


