"""
extras_audit.py -- verify an EXTRA_TYPES definition against in-game reality.

The extras system (extra_types.py + vault/routes/extras/) is a set of DAT patch
recipes with UI previews (viewer ExtraPreviews.jsx). This driver answers, per
extra: do the offsets hit the right bytes, does the patch actually change the
in-game effect, and does the layer->appearance mapping match what the preview
promises? It is the workhorse for the extras audit.

Three stages (each skippable):

  1. offsets  -- static: diff the config's claimed 'vanilla' values against the
                 actual bytes of the vanilla DAT in storage/test-base (no boot).
  2. build    -- copy test-base, patch the target DAT with DISTINCTIVE test
                 colors using the app's own apply_hex_patches (the same code
                 the export path runs), export an ISO via MexCLI.
  3. game     -- frameshot the move(s) that show the effect; captures land in
                 tests/artifacts/extras-audit/<char>-<extra>/ for comparison
                 against the preview semantics.

Run from backend/ (Slippi closed, no other mexcli build running):

  python devtools/extras_audit.py --char Marth --extra sword
  python devtools/extras_audit.py --char Marth --extra sword --skip-build --iso <prev.iso>
  python devtools/extras_audit.py --char Marth --extra sword --vanilla   # unpatched control

Default test colors are maximally distinguishable (green/blue/magenta...) so
each layer's in-game role is unambiguous in the captures.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/
from core.config import STORAGE_PATH, PROJECT_ROOT  # noqa: E402
from core.extra_lookup import get_extra_type, get_storage_character  # noqa: E402
import mexcli.commands  # noqa: E402
from devtools.stress_build import parse_json  # noqa: E402

TEST_BASE = STORAGE_PATH / "test-base"
ART_ROOT = PROJECT_ROOT.parent / "tests" / "artifacts" / "extras-audit"

# Distinct, saturated test colors assigned to layers in order -- pure hues so
# "which layer is which region in game" is readable straight off a screenshot.
# The RGBY palette holds the SAME hues in Melee's 16-bit effect format.
TEST_PALETTE = ["00FF00", "0000FF", "FF00FF", "FF8000", "00FFFF", "FFFF00"]
TEST_PALETTE_RGBY = ["0FF0", "00FF", "FC1F", "B100", "0F0F", "BBB1"]
PALETTE_NAMES = ["green", "blue", "magenta", "orange", "cyan", "yellow"]

# Per-(character, extra) audit hints: which frameshot char/moves demonstrate
# the effect in game (sparse frame lists covering the visible window).
# Optional keys: "force" = extra color-layer values merged over the test
# palette (e.g. laser_ring's FObj trackType bytes must be 00 to disable the
# color animation or custom colors never show, exactly as the editor writes
# them); "input_at" = frameshot --input-at specs for multi-input specials
# (charge release etc.).
AUDIT_HINTS = {
    ("Marth", "sword"): {"char": "marth", "shots": ["fsmash:9-16", "fair:4-8"]},
    ("Roy", "sword"): {"char": "roy", "shots": ["fsmash:9-16", "fair:5-9"]},
    ("Link", "sword"): {"char": "link", "shots": ["fsmash:14-20", "fair:5-10"]},
    ("Young Link", "sword"): {"char": "younglink", "shots": ["fsmash:14-20", "fair:5-10"]},
    ("Fox", "laser"): {"char": "fox", "shots": ["neutralb:8,12,16,20,24"]},
    ("Falco", "laser"): {"char": "falco", "shots": ["neutralb:8,12,16,20,24"]},
    ("Fox", "sideb"): {"char": "fox", "shots": ["sideb:10,14,18,22"]},
    ("Falco", "sideb"): {"char": "falco", "shots": ["sideb:10,14,18,22"]},
    ("Fox", "shine"): {"char": "fox", "shots": ["downb:2,4,6,9,12"]},
    # Link WIRE 2026-07-02 (research/docs-research/effect-maps/link.md, MAP-LIVE
    # verified). Spin Attack Trail: up-B swirling blade/disc trail, visible
    # across the whole up-B active/rise window f6-30 (best-framed f6-16 per
    # the spec). Anti-colors far from vanilla white core/blue tint (lesson 6):
    # core magenta FF00FF, glow red FF0000 -- the LIVE-verified combo.
    # Shared with Young Link (same EfLkData.dat, no separate EfCl file).
    ("Link", "spin_attack_trail"): {"char": "link",
                                    "shots": ["upb:6,10,16,24,30"],
                                    "force": {"color1": "FF00FF", "color2": "FF0000"}},
    ("Young Link", "spin_attack_trail"): {"char": "younglink",
                                          "shots": ["upb:6,10,16,24,30"],
                                          "force": {"color1": "FF00FF", "color2": "FF0000"}},
    # upb: forced ANTI-FIRE colors -- palette orange/yellow read as vanilla
    # fire in the first audit pass and hid the verdict
    ("Fox", "upb"): {"char": "fox", "shots": ["upb:10,25,40,50,60,70"],
                     "force": {"tip": "00FF", "body": "00FF00",
                               "trail": "0000FF", "rings": "FF00FF",
                               "small_trail": "00FFFF", "dots": "FF00FF",
                               "charge_lines": "00FF00", "flare": "0000FF"}},
    # Task #12 migration (2026-07-02): force is now a target COLOR, not raw
    # degrees. apply_texture_extra_hue's `hue` was always an ABSOLUTE TARGET
    # HUE (hue_shift = hue - vanilla_hue), so "00FFFF" (pure cyan, hue=180)
    # is byte-identical to the old {"hue": "180"} force -- NOT
    # vanilla_hue+180 (see textures.py's module docstring / the
    # test_color_equal_to_old_hue_reproduces_identical_shift regression).
    ("Fox", "upb_texture"): {"char": "fox", "shots": ["upb:10,25,40,50,60,70"],
                             "force": {"color": "00FFFF"}},
    # Historical ID upb_charge_fire is the FLIGHT puff bitmap (EfFx group 3).
    # Model 4 emits particle 3004 -> scripts 5/9; upb.trail also tints these
    # puffs. Probe after launch. Actual charge flames are an EfCoData family;
    # see the retired fox-charge-correction report (git history before 2026-10-03).
    ("Fox", "upb_charge_fire"): {"char": "fox",
                                 "shots": ["upb:50,60,70"],
                                 "force": {"color1": "00FFFF"}},
    ("Falco", "upb_charge_fire"): {"char": "falco",
                                   "shots": ["upb:50,60,70"],
                                   "force": {"color1": "00FFFF"}},
    # Fox's charge animation separately spawns EfCo scripts 299/300. These
    # are broad puffs and thin wisps, independently live-verified 2026-09-09.
    ("Fox", "charge_flames"): {"char": "fox",
                              "shots": ["upb:18,25,32"],
                              "force": {"flame_c1": "00FFFF", "flame_c2": "00FFFF",
                                        "wisp_c1": "00FF00", "wisp_c2": "00FF00"}},
    # laser_ring fires around Fox at each SHOT (not on hit) -- dense early
    # frames catch the 8-frame KONST/TEV0 flash animation, the later frames
    # the settled colors (see docs/dev/EXTRAS_AUDIT.md laser_ring row)
    ("Fox", "laser_ring"): {"char": "fox",
                            "shots": ["neutralb:13,14,15,16,17,18,20,22,24,26"],
                            "force": {"color1": "FF00FF", "color2": "00FFFF",
                                      **{f"hue{i}": "00" for i in range(1, 7)}}},
    # common_shield: the cast-shared bubble TEXTURE (EfCoData 0x104320 IA8,
    # research/docs-research/effect-maps/common-shield.md). Not a color extra -- the
    # build patches a checkerboard test pattern into the region
    # (_patch_texture_region), unmistakable against the vanilla soft sphere.
    # `shield` recipe = hold L (Guard family 178-182); bubble is fully out by
    # f2 and shrinks slowly, any of f2-20 shows it.
    ("Fox", "common_shield"): {"char": "fox", "shots": ["shield:2,6,12,20"]},
    ("C. Falcon", "falcon_punch"): {"char": "falcon",
                                    "shots": ["neutralb:35,45,50,53,56,60,65"]},
    # punch fire texture: the bird + wing fire show ~f50-62, tail wisps ~f53-60
    ("C. Falcon", "punch_texture"): {"char": "falcon",
                                     "shots": ["neutralb:45,50,53,56,60,65"]},
    # kick: foot fire core/halo + chevrons f10-24, trail puffs/dots f24-34.
    # ANTI-FIRE colors forced (default palette's orange/yellow read as
    # vanilla fire). Live-poke mapped 2026-07 (tests/artifacts/
    # datram-probe-falcon/): color1=core, color2=round halo, front=chevron
    # streaks, trail/dots = the CF puff records (primary+secondary).
    ("C. Falcon", "falcon_kick"): {"char": "falcon",
                                   "shots": ["downb:10,16,24,34"],
                                   "force": {"color1": "00FF00",
                                             "color2": "FF00FF",
                                             "front_c1": "00FFFF",
                                             "trail_c1": "0000FF",
                                             "trail_c2": "FF00FF",
                                             "dots_c1": "00FF00",
                                             "dots_c2": "00FFFF"}},
    # side-B whiff shows the fist flare (f8-14); the hit_* layers are the
    # on-hit uppercut fire/smoke burst, verified 2026-07-02 with the
    # punching-bag 2nd player ("bag": DK parked 12 units in front so the
    # side-B connects; burst frames follow contact -- see the sidecar's
    # bag.hit + per-frame bag states for the contact frame)
    ("C. Falcon", "raptor_boost"): {"char": "falcon",
                                    "shots": ["sideb:8,11,14,17,20,23,26,30,34"],
                                    "bag": "dk", "bag_pos": "12,0",
                                    "force": {"color1": "00FF00",
                                              "color2": "FF00FF",
                                              "hit_smoke_c1": "00FFFF",
                                              "hit_smoke_c2": "0000FF",
                                              "hit_dots_c1": "00FF00",
                                              "hit_dots_c2": "FF00FF",
                                              "hit_mat_c1": "00FFFF"}},
    ("Pikachu", "thunder"): {"char": "pikachu", "shots": ["downb:20,30,40,50,60"]},
    ("Pichu", "thunder"): {"char": "pichu", "shots": ["downb:20,30,40,50,60"]},
    # long charge so the charging ball is big (charge center + bolts visible
    # f45-75), then throw at f90 (thrown-center frames f98+)
    ("Mewtwo", "shadow_ball"): {"char": "mewtwo",
                                "shots": ["neutralb:20,45,75,98,106"],
                                "input_at": ["90:PRESS B", "92:RELEASE B"]},
    ("Mewtwo", "upsmash"): {"char": "mewtwo",
                            "shots": ["usmash:8,10,12,14,16,18,20,24"]},
    # Samus WIRE 2026-07 (research/docs-research/effect-maps/samus.md). Screw Attack:
    # four arc quadrants + spiral spark ring visible through the up-B rise.
    # force keys match the RAW offsets dict (arc_c1/arc_c2), same as
    # pick_test_colors/--colors -- NOT the color1/color2 editor properties.
    ("Samus", "screw_attack"): {"char": "samus",
                                "shots": ["upb:8,12,16"],
                                "force": {"arc_c1": "00FF00", "arc_c2": "FF00FF"}},
    # Missile: contrail smoke trails the flying missile, back-blast puffs at
    # the cannon on launch -- anti-colors chosen far from the vanilla
    # brown/tan trail (spec lesson 6).
    ("Samus", "missile"): {"char": "samus",
                           "shots": ["sideb:14,22,32"],
                           "force": {"contrail_c1": "00FF00", "contrail_c2": "00FF00",
                                     "backblast_c1": "FF00FF", "backblast_c2": "FF00FF"}},
    # Charge Shot: radiating spark-needle lines around the arm cannon while
    # holding neutral-B. The fired ball is a texture and is NOT wired (spec
    # open lead) -- these frames only need to show the charging needles.
    ("Samus", "charge_shot"): {"char": "samus",
                               "shots": ["neutralb:20,40,54"],
                               "force": {"needles_c1": "FF00FF"}},
    # charge_ball: texture_recolor format (task #12) -- the FIRED charge-shot
    # ball is a raw RGB5A3 texel block in PlSs.dat @0x36840, not a color
    # record (see research/docs-research/effect-maps/samus.md, in-game verified
    # 2026-07-02 against tests/artifacts/samus-ball-texture/). Same charge
    # window as charge_shot, but must hold to FULL charge then fire so the
    # ball actually flies -- input_at PRESS/RELEASE B. Force ball=00FF00 to
    # match the verified-prototype ground truth
    # (036840_64x64_target_00FF00.png).
    ("Samus", "charge_ball"): {"char": "samus",
                               "shots": ["neutralb:54,58,62"],
                               "input_at": ["50:PRESS B", "52:RELEASE B"],
                               "force": {"color1": "00FF00"}},
    # Luigi WIRE 2026-07 (research/docs-research/effect-maps/luigi.md, LIVE-poked
    # 2026-07-02). Neutral-B fireball body/aura (PlLg.dat article): all
    # magenta per lesson 6/11 (fireball is green-family; magenta is the far
    # anti-color used in the spec's live verify pass). Spec AUDIT_HINTS:
    # `luigi:neutralb:8-40 anti FF00FF`.
    ("Luigi", "luigi_fireball"): {"char": "luigi",
                                  "shots": ["neutralb:8,16,24,32,40"],
                                  "force": {"fb_aura_42_c1": "FF00FF",
                                            "fb_aura_07_c1": "FF00FF",
                                            "fb_body_42_c1": "FF00FF"}},
    # Hand-spawn smoke + hand ring/portal (EfLgData.dat): same neutral-B
    # frame window, magenta anti-color (smoke/ring are green-family).
    ("Luigi", "luigi_fireball_smoke"): {"char": "luigi",
                                        "shots": ["neutralb:8,16,24,32,40"],
                                        "force": {"fb_smoke_s1_c1": "FF00FF",
                                                  "fb_smoke_s1_c2": "FF00FF",
                                                  "fb_smoke_s0a_c1": "FF00FF",
                                                  "fb_smoke_s0a_c2": "FF00FF",
                                                  "fb_smoke_s0b_c1": "FF00FF",
                                                  "fb_smoke_s0b_c2": "FF00FF",
                                                  "fb_smoke_s3_c1": "FF00FF",
                                                  "fb_smoke_s3_c2": "FF00FF",
                                                  "fb_smoke_s4_c1": "FF00FF",
                                                  "fb_smoke_s4_c2": "FF00FF",
                                                  "fb_dust_s5_c1": "FF00FF",
                                                  "fb_dust_s5_c2": "FF00FF",
                                                  "fb_particle_s6_c1": "FF00FF",
                                                  "fb_particle_s6_c2": "FF00FF",
                                                  "hand_ring_42_c1": "FF00FF",
                                                  "hand_ring_42_c2": "FF00FF",
                                                  "hand_ring_07_c1": "FF00FF",
                                                  "hand_ring_07_c2": "FF00FF"}},
    # Down-B tornado (Luigi Cyclone): pale-yellow/white swirl+finish, magenta
    # anti-color far from both. Spec AUDIT_HINTS: `luigi:downb:1-50 anti FF00FF`.
    ("Luigi", "luigi_cyclone"): {"char": "luigi",
                                 "shots": ["downb:10,14,20,30,40"],
                                 "force": {"torn_outer_c1": "FF00FF", "torn_outer_c2": "FF00FF",
                                           "torn_upper_c1": "FF00FF", "torn_upper_c2": "FF00FF",
                                           "torn_inner1_c1": "FF00FF", "torn_inner1_c2": "FF00FF",
                                           "torn_inner2_c1": "FF00FF", "torn_inner2_c2": "FF00FF",
                                           "torn_under_c1": "FF00FF", "torn_under_c2": "FF00FF",
                                           "torn_outer_fin_c1": "FF00FF", "torn_outer_fin_c2": "FF00FF",
                                           "torn_fin_c1": "FF00FF", "torn_fin_c2": "FF00FF",
                                           "torn_fin_s1_c1": "FF00FF", "torn_fin_s1_c2": "FF00FF",
                                           "torn_fin_s2_c1": "FF00FF", "torn_fin_s2_c2": "FF00FF",
                                           "torn_below_c1": "FF00FF", "torn_below_c2": "FF00FF"}},
    # Luigi hitspark WIRE 2026-07-02 (research/docs-research/effect-maps/luigi.md
    # "Proposed extra 3", punching-bag pass, tests/artifacts/extras-audit/
    # Luigi-sparks-bag/). spark_blue_s11 = on-hit impact spark: red
    # anti-color (vanilla is pale-blue/blue B5F6FF/0C17D7). Verified on
    # fair AND nair contact against a DK bag (bag dk @12,0 per the harness
    # validation); fair frame 8 is the impact frame used in the spec's
    # capture (spark_blue_s11-fair-f08.png).
    # (frame WINDOW, not a single frame: the impact flash is 1-2 frames wide
    # and contact timing jitters run-to-run -- a lone f8 capture missed it)
    ("Luigi", "luigi_hitspark"): {"char": "luigi",
                                  "shots": ["fair:5,6,7,8,9,10,12"],
                                  "bag": "dk", "bag_pos": "12,0",
                                  "force": {"hitspark_s11_c1": "FF0000",
                                            "hitspark_s11_c2": "FF0000"}},
    # Mario/Dr. Mario WIRE 2026-07 (research/docs-research/effect-maps/mario.md,
    # MAP-LIVE verified 2026-07-02, tests/artifacts/datram-probe-mario/ +
    # datram-probe-docmario/). Neutral-B fireball (Mario only): 15 CF
    # offsets + hand-ring 07/42 pair. Anti-color cyan (vanilla orange/red
    # per spec lesson 11/AUDIT_HINTS).
    ("Mario", "mario_fireball"): {"char": "mario",
                                  "shots": ["neutralb:16,24,46"],
                                  "force": {"hand_smoke_a_c1": "00FFFF", "hand_smoke_a_c2": "00FFFF",
                                            "hand_smoke_b_c1": "00FFFF", "hand_smoke_b_c2": "00FFFF",
                                            "hand_smoke_c_c1": "00FFFF", "hand_smoke_c_c2": "00FFFF",
                                            "trailing_fire_a_c1": "00FFFF", "trailing_fire_a_c2": "00FFFF",
                                            "trailing_fire_b_c1": "00FFFF", "trailing_fire_b_c2": "00FFFF",
                                            "trailing_fire_c_c1": "00FFFF", "trailing_fire_c_c2": "00FFFF",
                                            "ball_particles_a_c1": "00FF00", "ball_particles_a_c2": "00FF00",
                                            "ball_particles_b_c1": "00FF00", "ball_particles_b_c2": "00FF00",
                                            "ball_particles_c_c1": "00FF00", "ball_particles_c_c2": "00FF00",
                                            "ball_particles_d_c1": "00FF00", "ball_particles_d_c2": "00FF00",
                                            "landing_dust_a_c1": "FF00FF", "landing_dust_a_c2": "FF00FF",
                                            "landing_dust_b_c1": "FF00FF", "landing_dust_b_c2": "FF00FF",
                                            "landing_dust_c_c1": "FF00FF", "landing_dust_c_c2": "FF00FF",
                                            "square_particles_a_c1": "00FFFF", "square_particles_a_c2": "00FFFF",
                                            "square_particles_b_c1": "00FFFF", "square_particles_b_c2": "00FFFF",
                                            "hand_ring_07_c1": "00FFFF", "hand_ring_07_c2": "00FFFF",
                                            "hand_ring_42_c1": "00FFFF"}},
    # Fireball aura/glow halo material (PlMr.dat, Mario only). Same
    # neutral-B window; cyan anti-color (fireball is orange/red family).
    ("Mario", "mario_fireball_aura"): {"char": "mario",
                                       "shots": ["neutralb:16,24,46"],
                                       "force": {"aura_07_c1": "00FFFF", "aura_07_c2": "00FFFF",
                                                 "aura_42_c1": "00FFFF", "body_42_c1": "00FFFF"}},
    # Cape swing sparkle stars (EfMrData.dat, shared Mario/Doc, owner Mario).
    # Vanilla sparkles are inherently multi-hue (blue/cyan/magenta/pink) so
    # the live-poke shift was SUBTLE -- red anti-color per spec, flagged for
    # EYEBALL confirmation (not a clean-cut verdict like cloth).
    ("Mario", "cape_sparkles"): {"char": "mario",
                                 "shots": ["sideb:12,20"],
                                 "force": {"sparkle_a_c1": "FF0000", "sparkle_a_c2": "FF0000",
                                           "sparkle_b_c1": "FF0000", "sparkle_c_c1": "FF0000",
                                           "sparkle_trail_c1": "00FF00"}},
    # Doc shares the same EfMrData sparkle offsets (owner Mario) -- verify on
    # the Doc boot to confirm identical firing.
    ("Dr. Mario", "cape_sparkles"): {"char": "drmario",
                                     "shots": ["sideb:12,20"],
                                     "force": {"sparkle_a_c1": "FF0000", "sparkle_a_c2": "FF0000",
                                               "sparkle_b_c1": "FF0000", "sparkle_c_c1": "FF0000",
                                               "sparkle_trail_c1": "00FF00"}},
    # Mario cape CLOTH (PlMr.dat) -- the clean/strong ship headline. Green
    # anti-color (vanilla cloth is yellow).
    ("Mario", "mario_cape"): {"char": "mario",
                              "shots": ["sideb:12,20"],
                              "force": {"cloth_c1": "00FF00", "cloth_c2": "00FF00"}},
    # Doc cape CLOTH (PlDr.dat, his own file/offset) -- also clean/strong.
    # Green anti-color (vanilla cloth is white).
    ("Dr. Mario", "doc_cape"): {"char": "drmario",
                                "shots": ["sideb:12,20"],
                                "force": {"cloth_c1": "00FF00", "cloth_c2": "00FF00"}},
    # Down-B tornado (EfMrData.dat, shared Mario/Doc, owner Mario). Red/orange
    # anti-color (vanilla vortex is blue/cyan per spec AUDIT_HINTS).
    ("Mario", "mario_tornado"): {"char": "mario",
                                 "shots": ["downb:14,24"],
                                 "force": {"outer_swirl1_c1": "FF0000", "outer_swirl1_c2": "FF0000",
                                           "outer_swirl2_c1": "FF0000", "outer_swirl2_c2": "FF0000",
                                           "inner_side1_c1": "FF0000", "inner_side1_c2": "FF0000",
                                           "inner_side2_c1": "FF0000", "inner_side2_c2": "FF0000",
                                           "underneath_c1": "FF0000", "underneath_c2": "FF0000",
                                           "ground_ripple1_42_c1": "00FF00", "ground_ripple2_42_c1": "00FF00",
                                           "spin_haze1_42_c1": "00FF00", "spin_haze2_42_c1": "00FF00",
                                           "ground_haze_42_c1": "00FF00"}},
    # Doc reuses the same shared EfMrData tornado -- verify identical firing
    # on the Doc boot.
    ("Dr. Mario", "mario_tornado"): {"char": "drmario",
                                     "shots": ["downb:14,24"],
                                     "force": {"outer_swirl1_c1": "FF0000", "outer_swirl1_c2": "FF0000",
                                               "outer_swirl2_c1": "FF0000", "outer_swirl2_c2": "FF0000",
                                               "inner_side1_c1": "FF0000", "inner_side1_c2": "FF0000",
                                               "inner_side2_c1": "FF0000", "inner_side2_c2": "FF0000",
                                               "underneath_c1": "FF0000", "underneath_c2": "FF0000",
                                               "ground_ripple1_42_c1": "00FF00", "ground_ripple2_42_c1": "00FF00",
                                               "spin_haze1_42_c1": "00FF00", "spin_haze2_42_c1": "00FF00",
                                               "ground_haze_42_c1": "00FF00"}},
    # mario_coins: texture_recolor format, EfMrData.dat texGraphicBank group 0
    # (the up-B coin SPRITE, shared Mario/Doc -- see research/docs-research/effect-maps/
    # items.md). Coins spawn ON-CONNECT, so this needs the punching bag (dk
    # dx=8, per mission spec) -- up-B into the bag then hold the frame window
    # while the coin poses cycle. Force green per the texture_recolor
    # self-test convention (charge_ball precedent).
    ("Mario", "mario_coins"): {"char": "mario",
                               "shots": ["upb:6,10,14,18"],
                               "bag": "dk", "bag_pos": "8,0",
                               "force": {"color1": "00FF00"}},
    # Doc reuses the same shared EfMrData coin texture -- verify identical
    # firing on the Doc boot.
    ("Dr. Mario", "mario_coins"): {"char": "drmario",
                                   "shots": ["upb:6,10,14,18"],
                                   "bag": "dk", "bag_pos": "8,0",
                                   "force": {"color1": "00FF00"}},
    # Pikachu WIRE 2026-07-02 (research/docs-research/effect-maps/pikachu.md,
    # MAP-LIVE verified 2026-07-02, tests/artifacts/datram-probe-pikachu*/).
    # Aerial thunder-jolt CF group needs an AIRBORNE neutral-B. The
    # frameshot MoveRunner (backend/shared/ingame/moves.py) grew an 'airneutralb'
    # recipe 2026-07-02 (BAG-FIXED RE-TEST mission: jump to apex, then B in
    # the air) -- use it so the air jolt actually spawns. Frames chosen for
    # the airborne jolt's spark travel (higher rise => later contact).
    ("Pikachu", "pikachu_thunder_jolt_air"): {"char": "pikachu",
                                              "shots": ["airneutralb:20,30,44,58"],
                                              "force": {"jolt_air_mid_c1": "00FF00", "jolt_air_mid_c2": "FF00FF",
                                                        "jolt_air_outerflare_c1": "00FF00", "jolt_air_outerflare_c2": "FF00FF",
                                                        "jolt_air_midflare_c1": "00FF00", "jolt_air_midflare_c2": "FF00FF",
                                                        "jolt_air_innerborder_c1": "00FF00", "jolt_air_innerborder_c2": "FF00FF",
                                                        "jolt_air_innertri_c1": "00FF00"}},
    ("Pikachu", "pikachu_thunder_jolt_ground"): {"char": "pikachu",
                                                 "shots": ["neutralb:26,40"],
                                                 "force": {"jolt_gnd_a_c1": "00FF00", "jolt_gnd_a_c2": "FF00FF",
                                                           "jolt_gnd_b_c1": "00FF00", "jolt_gnd_b_c2": "FF00FF",
                                                           "jolt_gnd_c_c1": "00FF00", "jolt_gnd_c_c2": "FF00FF",
                                                           "jolt_gnd_d_c1": "00FF00", "jolt_gnd_d_c2": "FF00FF",
                                                           "jolt_gnd_head_c1": "00FFFF"}},
    ("Pikachu", "pikachu_fsmash"): {"char": "pikachu",
                                    "shots": ["fsmash:12,18"],
                                    "force": {"fsmash_pre_c1": "00FF00", "fsmash_pre_c2": "FF00FF",
                                              "fsmash_aura1_c1": "00FF00", "fsmash_aura1_c2": "FF00FF",
                                              "fsmash_aura2_c1": "00FF00", "fsmash_aura2_c2": "FF00FF",
                                              "fsmash_ball_c1": "00FF00", "fsmash_ball_c2": "FF00FF"}},
    # Ness WIRE 2026-07-02 (research/docs-research/effect-maps/ness.md, MAP-LIVE
    # verified 2026-07-02, tests/artifacts/datram-probe-ness/). Down-B PSI
    # Magnet absorb aura -- hold down-B to sustain.
    ("Ness", "ness_psi_magnet"): {"char": "ness",
                                  "shots": ["downb:6,14,24,40"],
                                  "force": {"psimag_a_c1": "00FF00", "psimag_a_c2": "FF00FF",
                                            "psimag_b_c1": "00FF00", "psimag_b_c2": "FF00FF",
                                            "psimag_c_c1": "00FF00", "psimag_c_c2": "FF00FF",
                                            "psimag_d_c1": "00FF00", "psimag_d_c2": "FF00FF",
                                            "psimag_e_c1": "00FF00", "psimag_e_c2": "FF00FF",
                                            "psimag_f_c1": "00FF00", "psimag_f_c2": "FF00FF",
                                            "psimag_g_c1": "00FF00", "psimag_g_c2": "FF00FF"}},
    # PK Thunder: ball travels then steers -- tail/lightning visible through
    # the rise, ball flare at the tip. lightning4 ships at the re-derived
    # offset 0x2D830 (see extra_types.py comment, NOT the spec's 0x2D82E).
    ("Ness", "ness_pk_thunder"): {"char": "ness",
                                  "shots": ["upb:10,20,34,50"],
                                  "force": {"tip_c1": "00FF00", "tail1_c1": "00FF00",
                                            "tail2_c1": "00FF00", "tail_main_c1": "00FF00",
                                            "ball_flare1_c2": "FF00FF", "ball_flare2_c2": "FF00FF",
                                            "lightning1_c1": "00FF00", "lightning2_c1": "00FF00",
                                            "lightning3_c1": "00FF00", "lightning4_c1": "00FF00"}},
    # ness_pk_fire: PK Fire burn PILLAR (PlNs.dat) -- ON-HIT ONLY, the pillar
    # only forms when the bolt connects (research/docs-research/effect-maps/items.md,
    # bag-verified 2026-07-02). bag dk dx=10 puts DK point-blank so PK Fire
    # connects on ~f22 and the pillar renders f24+. c1 = core (white/cream) ->
    # green, c2 = glow (blue/orange) -> magenta (anti-colors per lesson 11).
    ("Ness", "ness_pk_fire"): {"char": "ness",
                               "shots": ["sideb:24,32,44"],
                               "bag": "dk", "bag_pos": "10,0",
                               "force": {"pillar_ring_in_c1": "00FF00", "pillar_ring_in_c2": "FF00FF",
                                         "pillar_aura_c1": "00FF00", "pillar_aura_c2": "FF00FF",
                                         "pillar_ring_out_c1": "00FF00", "pillar_ring_out_c2": "FF00FF"}},
    # common_fire / common_flash -- EYEBALL-VERIFIED 2026-07-02.
    # (research/docs-research/effect-maps/effect-texbank.md section 4). EfCoData.dat
    # is the CAST-SHARED common effect bank; the extras are owned by Zelda in
    # the config, but EfCoData ships in EVERY build, so a common_fire/flash
    # ISO can be demonstrated with ANY consumer character (the "char" field
    # below is just which fighter frameshot boots -- it does NOT have to be
    # the config owner).
    #   - common_fire (grp9 orange fire cloud): CONFIRMED visible on Zelda's
    #     side-B Din's Fire. The recolor lands on the CHARGE FIREBALL held in
    #     Zelda's hand (frame 40 = full charge) -- green there vs vanilla
    #     orange, cropped-compare in the mission report. The mid-air explosion
    #     ring/ember at f20-30 is a GRAYSCALE mask (grp2/grp5, section 4c) and
    #     stays orange -- that is why the earlier f20-30 read looked "no-op".
    #     Demonstrate at f40 (the charged fireball), not the whiffed ember.
    #   - common_flash (grp3 purple star-burst): NOT visible on Zelda down-B
    #     (Transform, grp4 grayscale -- does not composite grp3). The marquee
    #     grp3 consumer is PIKACHU DOWN-B THUNDER: the purple radial star-burst
    #     behind Pikachu's head + the small purple lightning arc are grp3
    #     (vanilla hue 279 deg). Boot Pikachu, capture downb; the burst is
    #     clearest ~f45-55 (the thunder bolt has to descend + strike first).
    #     Anti-color: grp3 is purple, and the thunder impact has NATURAL green
    #     sparks, so 00FF00 half-collides (reads white-ish). Use an orange
    #     anti-color (FF7F00) -- maximally far from 279 deg purple AND from the
    #     green sparks -- for an unambiguous read.
    ("Zelda", "common_fire"): {"char": "zelda",
                               "shots": ["sideb:30,40,45"],
                               "force": {"color1": "00FF00"}},
    ("Zelda", "common_flash"): {"char": "pikachu",
                                "shots": ["downb:40,45,50,55"],
                                "force": {"color1": "FF7F00"}},
    # zelda_farore -- WIRE 2026-07-02 from research/docs-research/effect-maps/
    # zelda-sheik.md "Shippable-now summary". Farore's Wind teleport-burst
    # CORE flash (up-B), scripts 2 grnd / 3 air. Magenta poke per the spec
    # (vanilla is green/teal -- far anti-color). Frame WINDOW 4-18 per the
    # spec (the burst core is a brief bloom, not a single-frame flash --
    # template lesson re: capturing brief effects as a window, not one shot).
    ("Zelda", "zelda_farore"): {"char": "zelda",
                                "shots": ["upb:4,7,10,13,16,18"],
                                "force": {"farore_c1": "FF00FF", "farore_c2": "FF00FF"}},
    # zelda_transform -- WIRE 2026-07-02, same spec. Transform chest-flash
    # core orb/ring (down-B), scripts 6+9 (byte-identical, grouped). Green
    # poke per the spec (vanilla is periwinkle/deep-blue -- far anti-color).
    # Frame WINDOW 4-18 per the spec. IMPORTANT (template lesson 0): down-B
    # Transform leaves the fighter in Sleep afterward, which POISONS every
    # later experiment in the same boot -- fine for this single-extra verify
    # run (nothing runs after it), but do NOT batch this AUDIT_HINTS entry
    # with any other Zelda/Sheik move in one multi-shot boot.
    ("Zelda", "zelda_transform"): {"char": "zelda",
                                   "shots": ["downb:4,7,10,13,16,18"],
                                   "force": {"transform_c1": "00FF00", "transform_c2": "00FF00"}},
    # Pikachu WIRE 2026-07-02 from research/docs-research/effect-maps/efcodata.md
    # §6b. common_electric = the cast-wide on-hit/hitlag electric spark pool
    # (EfCoData.dat, shared, owner Pikachu). MAP-LIVE verified it on Zelda's
    # jab hitlag against a DK bag -- reuse that exact recipe: bag dk, jab,
    # a WINDOW of frames (impact flashes are 1-2 frames wide and contact
    # timing jitters run-to-run, template lesson re: luigi_hitspark) around
    # the capture jab f12 (frames 10-14). Green anti-color per spec (pool
    # vanilla is blue/white-family; the two warm outlier records at
    # elec_s0_b_c2/elec_s18_c1 are still far enough from green to read
    # clean). All 35 layer keys forced so every record in the group is
    # visibly patched, not just the 9 the MAP pass poked.
    ("Pikachu", "common_electric"): {"char": "zelda",
                                     "shots": ["jab:10,11,12,13,14,16"],
                                     "bag": "dk", "bag_pos": "12,0",
                                     "force": {
                                         "elec_s0_a_c1": "00FF00", "elec_s0_b_c2": "00FF00",
                                         "elec_s0_c_c2": "00FF00", "elec_s0_d_c2": "00FF00",
                                         "elec_s0_e_c2": "00FF00", "elec_s1_c1": "00FF00",
                                         "elec_s13_a_c1": "00FF00", "elec_s13_b_c2": "00FF00",
                                         "elec_s13_c_c2": "00FF00", "elec_s13_d_c2": "00FF00",
                                         "elec_s14_c1": "00FF00", "elec_s16_c1": "00FF00",
                                         "elec_s17_c1": "00FF00", "elec_s18_c1": "00FF00",
                                         "elec_s19_c1": "00FF00", "elec_s29_a_c1": "00FF00",
                                         "elec_s29_b_c2": "00FF00", "elec_s30_a_c1": "00FF00",
                                         "elec_s30_b_c2": "00FF00", "elec_s31_c1": "00FF00",
                                         "elec_s73_c1": "00FF00", "elec_s161_c1": "00FF00",
                                         "elec_s162_c1": "00FF00", "elec_s268_a_c1": "00FF00",
                                         "elec_s268_b_c2": "00FF00", "elec_s269_c1": "00FF00",
                                         "elec_s270_c1": "00FF00", "elec_s306_c1": "00FF00",
                                         "elec_s332_c1": "00FF00", "elec_s423_c1": "00FF00",
                                         "elec_s424_c1": "00FF00", "elec_s425_c1": "00FF00",
                                         "elec_s426_c1": "00FF00", "elec_s448_c1": "00FF00",
                                         "elec_s537_c1": "00FF00"}},
    # thunder_jolt_spark (s95, subtle caster-side cheek spark). MAP-LIVE
    # verified on Pikachu solo neutral-B (ground jolt): the frame window from
    # the LIVE capture session used f36 for the dissipation/cheek sparkles;
    # widen slightly per the hitspark-window lesson since the sparkle is a
    # short-lived accent, not a sustained effect. Magenta anti-color per
    # spec (vanilla is grayscale/white-family EAE7E9/6E6E6E/575757 -- far
    # from magenta on both hue and the "ambient/no-hue" axis).
    ("Pikachu", "thunder_jolt_spark"): {"char": "pikachu",
                                        "shots": ["neutralb:18,21,24,27,30,33"],
                                        "force": {"jolt_spark_a_c1": "FF00FF",
                                                  "jolt_spark_a_c2": "FF00FF",
                                                  "jolt_spark_b_c2": "FF00FF"}},
    # jab_finisher_spark WIRE 2026-07-02 from research/docs-research/effect-maps/
    # efcodata.md (STRAGGLER-CLOSEOUT). Rapid-jab (Attack100) finisher connect
    # flash (EfCoData s11/s15/s91). Uses the `rapidjab` recipe (1-on/1-off A
    # toggle) that chains Fox's jab into Attack100Loop; the pinned DK bag
    # (dx6, bag_pin) keeps the victim grounded + in range through the loop so
    # the finisher connects. Connect burst reads ~f20-28 (Attack100 loop/end).
    # Anti-color RED FF0000 -- vanilla is cyan/pink-white (s11 0554FF blue,
    # s15 57D0FF/0509FF cyan-blue, s91 75DBEB cyan), so red is far on hue for
    # every record (lesson 6/11). Owner Fox (representative rapid-jab char).
    ("Fox", "jab_finisher_spark"): {"char": "fox",
                                    "shots": ["rapidjab:20,22,24,26,28"],
                                    "bag": "dk", "bag_pos": "6,0", "bag_pin": True,
                                    "force": {"finisher_lead_c1": "FF0000",
                                              "finisher_burst_a_c2": "FF0000",
                                              "finisher_burst_b_c2": "FF0000",
                                              "finisher_flash_c2": "FF0000"}},
    # Bowser WIRE 2026-07-02 from research/docs-research/effect-maps/bowser.md
    # "Shippable-now summary". bowser_fire_breath = neutral-B, HOLD B to
    # sustain the flame stream (17 CF puff records across scripts 5-8).
    # MAP-LIVE (bowser_probe.json) held B via input_at PRESS/PRESS/PRESS/
    # RELEASE to keep the flame streaming across the whole probe window --
    # same recipe here. Frame WINDOW: flame visible ~f24-90, core judged
    # f40-60 (full stream), f24/f90 as edges (spec: "best judged f40-60").
    # Magenta anti-color (vanilla is orange/white family) -- single far-hue
    # anti-color is safe for every record per the spec (all vanilla hues
    # are warm). No bag needed (flame is solo-visible, no contact required).
    ("Bowser", "bowser_fire_breath"): {"char": "bowser",
                                       "shots": ["neutralb:24,40,50,60,90"],
                                       "input_at": ["1:PRESS B", "20:PRESS B",
                                                     "45:PRESS B", "70:RELEASE B"],
                                       "force": {
                                           "fb_s5_a_c1": "FF00FF", "fb_s5_a_c2": "FF00FF",
                                           "fb_s5_x_c1": "FF00FF", "fb_s5_b_c1": "FF00FF",
                                           "fb_s6_a_c1": "FF00FF", "fb_s6_a_c2": "FF00FF",
                                           "fb_s6_b_c1": "FF00FF", "fb_s6_b_c2": "FF00FF",
                                           "fb_s6_c_c1": "FF00FF",
                                           "fb_s7_a_c1": "FF00FF", "fb_s7_a_c2": "FF00FF",
                                           "fb_s7_b_c1": "FF00FF", "fb_s7_b_c2": "FF00FF",
                                           "fb_s7_c_c1": "FF00FF",
                                           "fb_s8_a_c1": "FF00FF", "fb_s8_b_c1": "FF00FF",
                                           "fb_s8_c_c1": "FF00FF"}},
    # Bowser WIRE 2026-07-03: breath_texture = the flame BODY texture (9x CI8
    # billboard frames in the EfKpData tex bank, palette hue-rotate). Shipped
    # off a USER report: with only the CF puffs recolored, the fire that LANDS
    # on the stage stays orange (itkoopaflame.c spawns the ptcl effect once
    # per flame item; sustained ground fire = the item's textured quads).
    # Same neutral-B hold-B recipe as bowser_fire_breath. Judged INVERSE:
    # texture body blue while the untouched CF puffs stay vanilla orange.
    # Blue anti-color (vanilla texture hue 28.2 orange -- blue is the far
    # hue AND the color the user actually wanted).
    ("Bowser", "breath_texture"): {"char": "bowser",
                                   "shots": ["neutralb:24,40,50,60,90"],
                                   "input_at": ["1:PRESS B", "20:PRESS B",
                                                "45:PRESS B", "70:RELEASE B"],
                                   "force": {"color1": "0714FF"}},
    # Jigglypuff WIRE 2026-07-02 from research/docs-research/effect-maps/
    # jigglypuff.md "Shippable-now summary". sing_notes = up-B Sing's three
    # circling musical notes (MODEL-REGION 070707 vertex-color pairs in
    # EfPrData.dat, not ptcl). MAP-LIVE verified 2026-07-02 (tests/
    # artifacts/datram-probe-jigglypuff/): notes visible frames ~20-110
    # (Sing loops), best-framed f40-70 (f8/f20 are too early, notes still
    # spawning). Anti-colors are PER-OPERAND per the spec (lesson 6/11):
    # red note -> green, blue note -> orange, green note -> magenta (each
    # far from its own vanilla hue, not one global anti-color).
    ("Jigglypuff", "sing_notes"): {"char": "jigglypuff",
                                   "shots": ["upb:40,50,60,70"],
                                   "force": {
                                       "note_red_core": "00FF00", "note_red_glow": "00FF00",
                                       "note_blue_core": "FF8000", "note_blue_glow": "FF8000",
                                       "note_green_core": "FF00FF", "note_green_glow": "FF00FF"}},
    # Ganondorf WIRE 2026-07-02 from research/docs-research/effect-maps/ganondorf.md
    # LIVE section. warlock_punch = Warlock/Falcon Punch dark aura + fist-
    # explosion, scripts 0+1. The fist-explosion burst fires on the VICTIM
    # at connect (LIVE-poke confirmed via the punching-bag harness, dk @
    # dx 11 -- Falcon side-B dx-12 connect precedent, lesson 7/14); the
    # solo f30 charge starburst is a DIFFERENT unpoked script and stays
    # vanilla purple. Connect lands ~f70 (Warlock Punch's long neutral-B
    # charge-release window per the spec) -- capture around/after contact.
    # Anti-color green (vanilla is dark-purple/magenta family).
    ("Ganondorf", "warlock_punch"): {"char": "ganondorf",
                                     "shots": ["neutralb:50,70,80,90"],
                                     "bag": "dk", "bag_pos": "11,0",
                                     "force": {"punch_a_c1": "00FF00", "punch_a_c2": "00FF00",
                                               "punch_b_c1": "00FF00", "punch_b_c2": "00FF00",
                                               "punch_c_c1": "00FF00", "punch_c_c2": "00FF00",
                                               "fist_a_c1": "00FF00", "fist_a_c2": "00FF00",
                                               "fist_b_c1": "00FF00", "fist_b_c2": "00FF00",
                                               "fist_c_c1": "00FF00", "fist_c_c2": "00FF00"}},
    # wizards_foot = Wizard's Foot (down-B) foot-fire streak, script 6 only
    # (the spec's draft script 2 was LIVE-DEAD and is not shipped). Solo-
    # visible during the dash -- no bag needed. Anti-color green (vanilla
    # is white/purple family).
    ("Ganondorf", "wizards_foot"): {"char": "ganondorf",
                                    "shots": ["downb:12,18,24,30"],
                                    "force": {"color1": "00FF00", "color2": "00FF00"}},
    # Ice Climbers WIRE 2026-07-02 from research/docs-research/effect-maps/
    # iceclimbers.md LIVE section. ice_shot = neutral-B Ice Shot: birth
    # swirl (script 0) + block-glow variants (scripts 3/4) + Family-A
    # sparkle (scripts 2/6/8/12). Forward-firing PROJECTILE, fully solo-
    # visible -- no bag needed. Projectile spawns ~f10, sparkle burst peaks
    # ~f16-22 (the f22 sparkle read SUBTLE in MAP-LIVE -- flagged for
    # EYEBALL double-check, per the spec). Anti-color red (vanilla is
    # blue/white family, no purple/warm operands anywhere in this file).
    # Char key "iceclimbers" (char_select.py canonical; config character
    # key is "Ice Climbers" per the existing CHAR_DAT_PREFIX convention).
    # One patch covers Popo+Nana (EfIcData.dat is a single shared bank).
    ("Ice Climbers", "ice_shot"): {"char": "iceclimbers",
                                   "shots": ["neutralb:10,16,22,30"],
                                   "force": {"birth_a_c1": "FF0000", "birth_a_c2": "FF0000",
                                             "birth_b_c1": "FF0000", "birth_b_c2": "FF0000",
                                             "birth_c_c1": "FF0000",
                                             "sparkle_c1": "FF0000", "sparkle_c2": "FF0000",
                                             "sparkle2_c1": "FF0000",
                                             "variant_a_c1": "FF0000", "variant_a_c2": "FF0000",
                                             "variant_b_c1": "FF0000",
                                             "variant_c_c1": "FF0000", "variant_c_c2": "FF0000",
                                             "variant_d_c1": "FF0000"}},
    # Kirby WIRE 2026-07-02 from research/docs-research/effect-maps/kirby.md
    # Shippable-now section. kirby_stone = Stone (down-B) transform-burst
    # dust: s8/s9/s14 (dominant) + s5 (secondary, subtler). Solo-visible on
    # a ground down-B whiff -- no bag needed. Frame window 24-40 (transform-
    # burst peak). Anti-color magenta (vanilla is white/teal/grey -- no
    # magenta/red anywhere in this group per spec AUDIT_HINTS).
    ("Kirby", "kirby_stone"): {"char": "kirby",
                               "shots": ["downb:24,28,34,40"],
                               "force": {"dust_a_c1": "FF00FF", "dust_b_c1": "FF00FF",
                                         "dust_c_c1": "FF00FF",
                                         "s9_a_c1": "FF00FF", "s9_a_c2": "FF00FF",
                                         "s9_b_c1": "FF00FF", "s9_c_c1": "FF00FF",
                                         "brk_a_c1": "FF00FF", "brk_b_c1": "FF00FF",
                                         "ground_a_c1": "FF00FF", "ground_b_c1": "FF00FF",
                                         "ground_c_c1": "FF00FF", "ground_d_c1": "FF00FF"}},
    # --- Kirby Copy Abilities (WIRE 2026-07-02, research/docs-research/effect-maps/
    # kirby.md section 6.4) --- HARNESS GAP, NO VERIFY MOVE: the solo-Kirby
    # shared/ingame/ harness (CLAUDE.md-mandated, no CPU) has no inhale+swallow+copy
    # primitive, so a copied special never loads its EfKb<XX>.dat bank in a
    # boot -- these 5 entries exist ONLY so a future mission with the
    # primitive has the char/target wired; they are placeholders, NOT a
    # working frameshot recipe. A build MUST run with --skip-game for these
    # ids (offsets-stage-only, per the WIRE mission's "no verify move" note)
    # -- do NOT remove --skip-game and expect a capture; "shots" is a
    # descriptive placeholder (the donor's own move) that will render the
    # DONOR's vanilla effect on solo Kirby, not the copied one, until the
    # primitive lands (kirby.md 6.4 options: scripted inhale->swallow via
    # pipe, or memory-poke Kirby's copy_kind/copied-fighter id pre-boot).
    ("Kirby", "kirby_copy_ganon"): {"char": "kirby",
                                     "shots": ["neutralb:1"],  # PLACEHOLDER -- inhale does not copy solo
                                     "force": {k: "FF00FF" for k in (
                                         "punch_a_c1", "punch_a_c2", "punch_b_c1", "punch_b_c2",
                                         "punch_c_c1", "punch_c_c2", "fist_a_c1", "fist_a_c2",
                                         "fist_b_c1", "fist_b_c2", "fist_c_c1", "fist_c_c2")}},
    ("Kirby", "kirby_copy_iceclimbers"): {"char": "kirby",
                                           "shots": ["neutralb:1"],  # PLACEHOLDER -- see harness-gap note above
                                           "force": {k: "FF00FF" for k in (
                                               "birth_a_c1", "birth_a_c2", "birth_b_c1", "birth_b_c2",
                                               "birth_c_c1", "sparkle_c1", "sparkle_c2", "sparkle2_c1",
                                               "variant_a_c1", "variant_a_c2", "variant_b_c1",
                                               "variant_c_c1", "variant_c_c2", "variant_d_c1")}},
    ("Kirby", "kirby_copy_bowser"): {"char": "kirby",
                                      "shots": ["neutralb:1"],  # PLACEHOLDER -- see harness-gap note above
                                      "force": {k: "FF00FF" for k in (
                                          "fb_s5_a_c1", "fb_s5_a_c2", "fb_s5_x_c1", "fb_s5_b_c1",
                                          "fb_s6_a_c1", "fb_s6_a_c2", "fb_s6_b_c1", "fb_s6_b_c2",
                                          "fb_s6_c_c1", "fb_s7_a_c1", "fb_s7_a_c2", "fb_s7_b_c1",
                                          "fb_s7_b_c2", "fb_s7_c_c1", "fb_s8_a_c1", "fb_s8_b_c1",
                                          "fb_s8_c_c1")}},
    ("Kirby", "kirby_copy_luigi"): {"char": "kirby",
                                     "shots": ["neutralb:1"],  # PLACEHOLDER -- see harness-gap note above
                                     "force": {k: "FF00FF" for k in (
                                         "fb_smoke_s0a_c1", "fb_smoke_s0a_c2", "fb_smoke_s0b_c1",
                                         "fb_smoke_s0b_c2", "fb_smoke_s1_c1", "fb_smoke_s1_c2",
                                         "fb_smoke_s3_c1", "fb_smoke_s3_c2", "fb_smoke_s4_c1",
                                         "fb_smoke_s4_c2", "fb_dust_s5_c1", "fb_dust_s5_c2",
                                         "fb_particle_s6_c1", "fb_particle_s6_c2")}},
    ("Kirby", "kirby_copy_mario"): {"char": "kirby",
                                     "shots": ["neutralb:1"],  # PLACEHOLDER -- see harness-gap note above
                                     "force": {k: "FF00FF" for k in (
                                         "hand_smoke_a_c1", "hand_smoke_a_c2", "hand_smoke_b_c1",
                                         "hand_smoke_b_c2", "hand_smoke_c_c1", "hand_smoke_c_c2",
                                         "trailing_fire_a_c1", "trailing_fire_a_c2", "trailing_fire_b_c1",
                                         "trailing_fire_b_c2", "trailing_fire_c_c1", "trailing_fire_c_c2",
                                         "ball_particles_a_c1", "ball_particles_a_c2", "ball_particles_b_c1",
                                         "ball_particles_b_c2", "ball_particles_c_c1", "ball_particles_c_c2",
                                         "ball_particles_d_c1", "ball_particles_d_c2", "landing_dust_a_c1",
                                         "landing_dust_a_c2", "landing_dust_b_c1", "landing_dust_b_c2",
                                         "landing_dust_c_c1", "landing_dust_c_c2", "square_particles_a_c1",
                                         "square_particles_a_c2", "square_particles_b_c1",
                                         "square_particles_b_c2")}},
    # Ganondorf WIRE 2026-07-02 from research/docs-research/effect-maps/ganondorf.md
    # S5b NARROW CONFIRM section. gerudo_dragon = the flame aura that
    # engulfs the victim on the Gerudo/Flame Choke (side-B) command-grab
    # connect, scripts 12/14/15/16. REQUIRES the punching-bag harness WITH
    # --bag-pin (lesson 19 / this mission's new frameshot.py flag): a
    # non-pinned bag gets knocked down by the first slam and can't be
    # re-grabbed, which is what blocked attribution for two earlier sweep
    # passes. bag dk dx=5 (narrow-confirm recipe, closer than warlock_punch's
    # dx=11 since Gerudo's grab range is shorter), pin=true. Anti-color cyan
    # (vanilla is purple/magenta family per lesson 11 -- the operands are
    # already magenta-adjacent, so cyan is the only anti-color far enough).
    ("Ganondorf", "gerudo_dragon"): {"char": "ganondorf",
                                     "shots": ["sideb:18,22,26,28"],
                                     "bag": "dk", "bag_pos": "5,0", "bag_pin": True,
                                     "force": {
                                         "s12_a_c1": "00FFFF", "s12_a_c2": "00FFFF",
                                         "s12_b_c1": "00FFFF", "s12_b_c2": "00FFFF",
                                         "s12_c_c1": "00FFFF", "s12_c_c2": "00FFFF",
                                         "s14_a_c1": "00FFFF", "s14_a_c2": "00FFFF",
                                         "s14_b_c1": "00FFFF", "s14_b_c2": "00FFFF",
                                         "s14_c_c1": "00FFFF", "s14_c_c2": "00FFFF",
                                         "s14_d_c1": "00FFFF", "s14_d_c2": "00FFFF",
                                         "s14_e_c1": "00FFFF", "s14_e_c2": "00FFFF",
                                         "s15_a_c1": "00FFFF", "s15_a_c2": "00FFFF",
                                         "s15_b_c1": "00FFFF", "s15_b_c2": "00FFFF",
                                         "s16_a_c1": "00FFFF", "s16_a_c2": "00FFFF",
                                         "s16_b_c1": "00FFFF", "s16_b_c2": "00FFFF",
                                         "s16_c_c1": "00FFFF", "s16_c_c2": "00FFFF"}},
}


def log(m):
    print(m, flush=True)


# --------------------------------------------------------------------------- #
# Stage 1: static offset check                                                 #
# --------------------------------------------------------------------------- #
def check_offsets(char, cfg):
    """Diff claimed vanilla values against the real vanilla DAT bytes. Only
    'size'-format layers are byte-comparable; matrix ('end') and multi-offset
    formats get their raw bytes printed for eyeball review."""
    target = cfg["target_file"]
    dat = TEST_BASE / "files" / target
    if not dat.exists():
        log(f"[offsets] SKIP: vanilla {target} not in {TEST_BASE / 'files'}")
        return None
    data = dat.read_bytes()
    vanilla = cfg.get("vanilla", {})
    ok = True
    log(f"[offsets] {char}/{cfg['id']} vs vanilla {target} ({len(data):#x} bytes)")
    for layer, off in cfg.get("offsets", {}).items():
        claimed = str(vanilla.get(layer, off.get("vanilla", ""))).upper()
        if "size" in off:
            actual = data[off["start"]:off["start"] + off["size"]].hex().upper()
            match = actual == claimed
            ok &= match
            log(f"  {layer:<10} @{off['start']:#07x} size={off['size']} "
                f"actual={actual} claimed={claimed} {'OK' if match else '** MISMATCH **'}")
        elif "end" in off:
            head = data[off["start"]:off["start"] + 16].hex(" ").upper()
            log(f"  {layer:<10} @{off['start']:#07x}..{off['end']:#x} "
                f"(matrix {off.get('format')}) head: {head}  [manual review]")
        elif "offsets" in off:
            for o in off["offsets"]:
                head = data[o:o + 12].hex(" ").upper()
                log(f"  {layer:<10} @{o:#07x} ({off.get('format')}) bytes: {head}  [manual review]")
    return ok


# --------------------------------------------------------------------------- #
# Stage 2: patch + export                                                      #
# --------------------------------------------------------------------------- #
def _layer_kind(off):
    """Classify a layer's color encoding: rgby (16-bit), rgb, rgba, or byte."""
    fmt = off.get("format", "")
    if fmt == "BYTE":
        return "byte"
    if fmt == "RGBY" or "ranges" in off:
        return "rgby"
    if fmt == "RGBA" or off.get("size") == 4:
        return "rgba"
    return "rgb"


def pick_test_colors(cfg, start_index=0, force=None):
    """Assign a distinct pure hue to each patchable color layer, in the layer's
    own encoding. `start_index` staggers the palette across a multi-extra batch
    so co-visible extras differ; `force` (from AUDIT_HINTS) overrides/adds
    layers (e.g. hue-index bytes)."""
    if cfg.get("format") == "texture_region":
        # No color layers -- the build patches a deterministic checkerboard
        # test pattern into the region (see _patch_texture_region); the
        # marker value here is only for logging/applied.json honesty.
        colors = {"texture": "checkerboard"}
        colors.update(force or {})
        return colors, start_index

    if cfg.get("type") == "texture":
        # Texture extras take a single target COLOR now (task #12 migration,
        # 2026-07-02 -- was a raw hue-degrees value). Default probe color is
        # an anti-fire test angle: vanilla_hue's recorded value + 180,
        # picked far from the vanilla hue per the "anti-color rule" (lesson
        # 6) so the shift is obviously visible in a capture -- this is a
        # NEW default choice, not required to reproduce old output (AUDIT_HINTS
        # entries that need byte-identical parity with a specific old
        # {"hue": N} force set an explicit "color" whose OWN hue equals N,
        # see the upb_texture hint below + textures.py's module docstring /
        # the test_color_equal_to_old_hue_reproduces_identical_shift
        # regression for why "N" and "vanilla_hue+N" are NOT the same
        # equivalence).
        import colorsys
        vanilla_hue = cfg.get("vanilla_hue", 15)
        target_hue = (vanilla_hue + 180) % 360
        r, g, b = colorsys.hls_to_rgb(target_hue / 360, 0.5, 1.0)
        colors = {"color": f"{round(r*255):02X}{round(g*255):02X}{round(b*255):02X}"}
        colors.update(force or {})
        return colors, start_index

    colors = {}
    i = start_index
    for layer, off in cfg.get("offsets", {}).items():
        kind = _layer_kind(off)
        if kind == "byte":
            continue
        if kind == "rgby":
            colors[layer] = TEST_PALETTE_RGBY[i % len(TEST_PALETTE_RGBY)]
        elif kind == "rgba":
            colors[layer] = TEST_PALETTE[i % len(TEST_PALETTE)] + "FF"
        else:
            colors[layer] = TEST_PALETTE[i % len(TEST_PALETTE)]
        i += 1
    if cfg.get("format") == "shine_gradient":
        # primary/secondary/flash1/flash2 are RGBY values, not offsets-driven
        colors = {"primary": TEST_PALETTE_RGBY[start_index % 6],
                  "secondary": TEST_PALETTE_RGBY[(start_index + 1) % 6],
                  "flash1": TEST_PALETTE_RGBY[(start_index + 2) % 6],
                  "flash2": TEST_PALETTE_RGBY[(start_index + 3) % 6],
                  "sparkles": TEST_PALETTE[start_index % len(TEST_PALETTE)]}
    colors.update(force or {})
    return colors, i


def _palette_name(c):
    c = c.upper()
    for pal in (TEST_PALETTE, TEST_PALETTE_RGBY):
        for idx, v in enumerate(pal):
            if c in (v, v + "FF"):
                return PALETTE_NAMES[idx]
    return c


def _patch_shine(dat, cfg, colors):
    """Mirror colors.py's shine_gradient branch: remap the two alternating hex
    colors current->new, plus the startup-flash ranges."""
    from vault.extras.color_read import read_shine_gradient_colors
    from vault.extras.color_patch import patch_matrix_colors

    if colors.get("sparkles") and cfg["offsets"].get("sparkles"):
        from vault.extras.color_patch import patch_shine_sparkle_color
        patch_shine_sparkle_color(dat, cfg["offsets"]["sparkles"],
                                  colors["sparkles"])

    hex_off = cfg["offsets"]["hex"]
    cur = read_shine_gradient_colors(dat, hex_off)
    vanilla = cfg.get("vanilla", {})
    color_map = {cur.get("primary", vanilla["primary"]): colors["primary"],
                 cur.get("secondary", vanilla["secondary"]): colors["secondary"]}
    with open(dat, "r+b") as f:
        f.seek(hex_off["start"])
        data = f.read(hex_off["end"] - hex_off["start"])
        f.seek(hex_off["start"])
        f.write(patch_matrix_colors(data, color_format="RGBY", color_map=color_map))
        flash_map = {vanilla["flash1"]: colors["flash1"],
                     vanilla["flash2"]: colors["flash2"]}
        for rng in cfg.get("flash_offsets", {}).get("ranges", []):
            f.seek(rng["start"])
            data = f.read(rng["end"] - rng["start"])
            f.seek(rng["start"])
            f.write(patch_matrix_colors(data, color_format="RGBY", color_map=flash_map))


def _patch_texture_region(dat, cfg):
    """Mirror colors.py's texture_region branch (lesson 13). Writes a
    checkerboard IA8 test pattern over the region via the same
    vault/extras/texture_region.py primitives the install path uses --
    a capture showing a sharp-edged checkered bubble instead of the vanilla
    soft sphere proves the region + relocation logic end to end."""
    from vault.extras import texture_region as tr

    tcfg = tr.parse_cfg(cfg)
    w, h = tcfg["width"], tcfg["height"]
    from PIL import Image
    img = Image.new("LA", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            on = ((x // 16) + (y // 16)) % 2 == 0
            px[x, y] = (255 if on else 64, 255)
    import io as _io
    buf = _io.BytesIO()
    img.convert("RGBA").save(buf, "PNG")
    region = tr.png_to_region(buf.getvalue(), cfg)
    tr.write_region(dat, cfg, region)


def _patch_texture_recolor(dat, cfg, colors):
    """Mirror colors.py's texture_recolor branch (lesson 13: special-format
    extras need a SECOND patch mirror here or they silently no-op in the
    verify build). Rotates the raw texel block's hue via the same
    vault/extras/texture_recolor.py primitives the live install path
    uses -- NOT the HSDRawViewer CLI (this format is for textures that
    aren't reachable by that CLI, see the module docstring)."""
    from vault.extras.texture_recolor import apply_texture_recolor

    prop_id = cfg["properties"][0]["id"]
    color = colors.get(prop_id)
    if not color:
        log(f"[build] texture_recolor {cfg['id']}: no '{prop_id}' color in {colors}, skipping")
        return
    tex_cfg = dict(cfg["texture"])
    tex_cfg["_target_file"] = cfg["target_file"]
    apply_texture_recolor(dat, tex_cfg, color, vanilla_hue=cfg.get("vanilla_dominant_hue"))


def build_iso(char, jobs, out_iso, keep=False):
    """Patch every (cfg, colors) job into ONE copy of test-base and export."""
    from vault.extras.color_patch import apply_hex_patches  # deferred

    tag = "_".join(cfg["id"] for cfg, _ in jobs)
    work = (STORAGE_PATH / "test-builds" / f"extras_{char}_{tag}_proj".replace(" ", "_")).resolve()
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    log(f"[build] copying test-base -> {work}")
    shutil.copytree(TEST_BASE, work)

    # hex patches first (their offsets assume the vanilla DAT layout), texture
    # imports LAST -- HSDRawViewer re-saves the DAT and may shift the layout,
    # which would put later hex writes at wrong offsets (learned the hard way:
    # laser_ring patched after the fire-texture import hung the game)
    jobs = sorted(jobs, key=lambda j: j[0].get("type") == "texture")
    for cfg, colors in jobs:
        dat = work / "files" / cfg["target_file"]
        if not dat.exists():
            raise SystemExit(f"[build] {cfg['target_file']} not in test-base files/")
        log(f"[build] {cfg['id']} -> {cfg['target_file']}: "
            + ", ".join(f"{k}={v}({_palette_name(v)})" for k, v in colors.items()))
        if cfg.get("type") == "texture":
            # hue-shift the texture(s) with the app's own export/shift/import
            # flow -- one target per unique image node (TObjs share image
            # nodes; re-shifting a shared node via a second index round-trips
            # it back toward vanilla). Accepts BOTH the new {"color": hex}
            # shape (pick_test_colors' default / AUDIT_HINTS force) and the
            # old {"hue": degrees} shape (back-compat, in case a caller still
            # forces raw degrees) via textures.resolve_hue_shift -- same
            # back-compat contract the live install path uses.
            import vault.extras.helpers as ex_helpers
            from vault.extras.textures import (
                export_texture, shift_texture_hue, import_texture, get_texture_targets,
                resolve_hue_shift)
            from core.config import HSDRAW_EXE
            if not ex_helpers.HSDRAW_VIEWER_PATH:
                ex_helpers.HSDRAW_VIEWER_PATH = HSDRAW_EXE
            target_hue = resolve_hue_shift(None, cfg.get("id"), cfg, colors)
            if target_hue is None:
                target_hue = cfg.get("vanilla_hue", 30) + 180
            for ti, (node_path, idx) in enumerate(get_texture_targets(cfg)):
                png = work / f"_tex_{cfg['id']}_t{ti}.png"
                shifted = work / f"_tex_{cfg['id']}_t{ti}_shifted.png"
                export_texture(dat, node_path, idx, png)
                shift_texture_hue(png, shifted, int(target_hue))
                import_texture(dat, node_path, idx, shifted, dat)
        elif cfg.get("format") == "shine_gradient":
            _patch_shine(dat, cfg, colors)
        elif cfg.get("format") == "texture_recolor":
            _patch_texture_recolor(dat, cfg, colors)
        elif cfg.get("format") == "texture_region":
            _patch_texture_region(dat, cfg)
        else:
            modifications = {layer: {"color": c} for layer, c in colors.items()}
            apply_hex_patches(dat, cfg["offsets"], modifications)

    out_iso = Path(out_iso).resolve()
    out_iso.parent.mkdir(parents=True, exist_ok=True)
    log(f"[build] mexcli export -> {out_iso} (takes a minute)...")
    cp = mexcli.commands.run(["export", str((work / 'project.mexproj').resolve()),
                     str(out_iso), "1.0", "false", "false"], timeout=1800, check=False)
    res = parse_json(cp.stdout) or {}
    if not out_iso.exists():
        log(f"[build] EXPORT FAILED success={res.get('success')} err={res.get('error')}")
        log(f"  stderr: {(cp.stderr or '')[:400]}")
        raise SystemExit(1)
    log(f"[build] ISO ok ({out_iso.stat().st_size / 1024 / 1024:.0f} MB)")
    if not keep:
        shutil.rmtree(work, ignore_errors=True)
    return out_iso


# --------------------------------------------------------------------------- #
# Stage 3: in-game captures                                                    #
# --------------------------------------------------------------------------- #
def run_frameshot(iso, char, shots, out_dir, input_at=None, plain_bg="404040",
                  bag=None, bag_pos=None, bag_pin=False):
    cmd = [sys.executable, str(Path(__file__).parent / "frameshot.py"),
           "--iso", str(iso), "--char", char, "--out", str(out_dir)]
    if plain_bg:
        cmd += ["--plain-bg", plain_bg]
    if bag:
        cmd += ["--bag", bag]
        if bag_pos:
            cmd += ["--bag-pos", bag_pos]
        if bag_pin:
            cmd += ["--bag-pin"]
    for s in shots:
        cmd += ["--shot", s]
    for spec in input_at or []:
        cmd += ["--input-at", spec]
    log(f"[game] {' '.join(cmd)}")
    return subprocess.run(cmd).returncode


def merge_shots(hints):
    """Union the move:frames specs of a batch (same move -> merged frame set)."""
    by_move = {}
    order = []
    for hint in hints:
        for s in hint["shots"]:
            move, _, spec = s.partition(":")
            if move not in by_move:
                by_move[move] = set()
                order.append(move)
            for part in spec.split(","):
                part = part.strip()
                if "-" in part:
                    a, b = part.split("-", 1)
                    by_move[move].update(range(int(a), int(b) + 1))
                elif part:
                    by_move[move].add(int(part))
    return [f"{m}:{','.join(str(f) for f in sorted(by_move[m]))}" for m in order]


def main():
    ap = argparse.ArgumentParser(description="audit extras against in-game reality")
    ap.add_argument("--char", required=True, help="extra_types character key, e.g. Marth")
    ap.add_argument("--extra", help="one extra id, e.g. sword")
    ap.add_argument("--extras", help="comma list for a one-boot batch, e.g. laser,sideb,shine")
    ap.add_argument("--colors", help="override layer colors (single-extra runs): inner=00FF00,outer=FF00FF")
    ap.add_argument("--vanilla", action="store_true",
                    help="skip patching: build/capture the UNPATCHED control")
    ap.add_argument("--iso", help="reuse an existing ISO (skips the build stage)")
    ap.add_argument("--skip-offsets", action="store_true")
    ap.add_argument("--skip-game", action="store_true")
    ap.add_argument("--keep", action="store_true", help="keep the work project dir")
    ap.add_argument("--no-plain-bg", action="store_true",
                    help="keep the real stage visuals in captures")
    args = ap.parse_args()

    extra_ids = ([e.strip() for e in args.extras.split(",") if e.strip()]
                 if args.extras else ([args.extra] if args.extra else []))
    if not extra_ids:
        raise SystemExit("pass --extra <id> or --extras a,b,c")

    cfgs = []
    for eid in extra_ids:
        cfg = get_extra_type(args.char, eid)
        if not cfg:
            raise SystemExit(f"no extra '{eid}' for '{args.char}' in extra_types.py")
        if cfg.get("type") == "model":
            raise SystemExit(f"'{eid}' is a model extra; needs its own flow")
        cfgs.append(cfg)

    if not args.skip_offsets:
        for cfg in cfgs:
            if cfg.get("type") != "texture":
                check_offsets(args.char, cfg)

    hints = []
    for cfg in cfgs:
        hint = AUDIT_HINTS.get((args.char, cfg["id"]))
        if not hint and not args.skip_game:
            raise SystemExit(f"no AUDIT_HINTS entry for ({args.char}, {cfg['id']}) "
                             f"-- add one (which char/moves/frames show this effect)")
        hints.append(hint)

    tag = f"{args.char}-{'-'.join(extra_ids)}{'-vanilla' if args.vanilla else ''}".replace(" ", "")
    if args.iso:
        iso = Path(args.iso).resolve()
    else:
        jobs = []
        applied = {}
        pal_i = 0
        for cfg, hint in zip(cfgs, hints):
            colors = {}
            if not args.vanilla:
                colors, pal_i = pick_test_colors(
                    cfg, start_index=pal_i, force=(hint or {}).get("force"))
                if args.colors and len(cfgs) == 1:
                    for pair in args.colors.split(","):
                        k, _, v = pair.partition("=")
                        colors[k.strip()] = v.strip().upper()
            jobs.append((cfg, colors))
            applied[cfg["id"]] = {
                "target_file": cfg["target_file"],
                "owner": get_storage_character(args.char, cfg["id"]),
                "colors": {k: f"{v} ({_palette_name(v)})" for k, v in colors.items()},
                "preview_semantics": {p["id"]: p.get("description", p.get("name"))
                                      for p in cfg.get("properties", [])},
            }
        iso = build_iso(args.char, jobs,
                        PROJECT_ROOT / "output" / f"extras-audit-{tag}.iso",
                        keep=args.keep)
        (ART_ROOT / tag).mkdir(parents=True, exist_ok=True)
        (ART_ROOT / tag / "applied.json").write_text(json.dumps(
            {"char": args.char, "extras": applied, "iso": str(iso)}, indent=2))

    if args.skip_game:
        log("done (game stage skipped)")
        return 0
    out_dir = ART_ROOT / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    input_at = [s for h in hints for s in (h or {}).get("input_at", [])]
    # punching-bag 2nd player for on-hit-only effects (AUDIT_HINTS "bag" +
    # optional "bag_pos"/"bag_pin"): first hint that wants one wins for the
    # whole boot. bag_pin (lesson 19) zeros the bag's knockback each stepped
    # frame + re-pins its position, unblocking command-grab/rapid-jab
    # finishers that would otherwise knock it out of re-grab range -- see
    # frameshot.py --bag-pin / shared/ingame/gamestate.py Bag.pin().
    bag = next((h["bag"] for h in hints if h and h.get("bag")), None)
    bag_pos = next((h.get("bag_pos") for h in hints
                    if h and h.get("bag") and h.get("bag_pos")), None)
    bag_pin = next((h.get("bag_pin") for h in hints
                    if h and h.get("bag") and h.get("bag_pin")), False)
    rc = run_frameshot(iso, hints[0]["char"], merge_shots(hints), out_dir,
                       input_at=input_at,
                       plain_bg=None if args.no_plain_bg else "404040",
                       bag=bag, bag_pos=bag_pos, bag_pin=bag_pin)
    log(f"[game] captures -> {out_dir} (rc={rc})")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
