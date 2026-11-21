"""Offline Watch Lite collision bake. Never starts Dolphin or writes stagedump/.

Run with app/venv/Scripts/python.exe -B tools/liteaudit/stage_bake.py.
The policy below is deliberately joint-specific: an idle solo recording is NOT
evidence that a breakable/weighted platform is deterministic. See stagework's
random-*.md and report.json for excluded joints and measured coverage.
"""
import argparse
import ast
import gzip
import hashlib
import json
import math
import struct
import sys
import os
import re
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))  # tools.native_rig.fobj_reader
DEFAULT_DUMPS = REPO / "app/scratch/liteaudit/stagedump"
DEFAULT_OUT = REPO / "app/scratch/liteaudit/stagework"
DATA = REPO / "app/frontend/src/tracker/replays/data/stageCollision.json"
HEAVY_BYTES = 12 * 1024
ENABLED, HIDDEN, EMPTY, PLATFORM = 1 << 16, 1 << 18, 1 << 7, 1 << 8
# These are MapJoint indices, NOT map_gobj or model bone indices.
# Static = independent of match state. Neutral = retained fallback, not exact.
STATIC = {2: [2, 3], 3: [4, 6], 4: [3], 5: [7], 6: [3], 7: [],
          8: [1], 9: [2], 10: [], 11: [], 12: None, 13: [6, 7],
          14: None, 15: [], 16: [0], 17: [30], 18: [0, 1, 2],
          19: [0], 20: [1], 22: [], 23: [], 24: [], 25: [],
          27: [50], 28: None, 29: [3], 30: [2, 3, 4], 31: None, 32: None}
NEUTRAL = {4: [4, 5], 6: [0, 1, 2, 4, 5], 9: [0, 1, 3, 4],
           16: list(range(1, 10)), 19: list(range(1, 22)), 29: [0, 1, 2]}
# grMuteCity_801F04B8 command list + 801F0D20 spline collision are scripted;
# its RNG drives cars/items, not these MapJoints. Rainbow's teeter, carpets,
# donut blocks and camera-triggered appearing platforms are excluded.
ANIMATED = {8: [0], 10: None, 11: [0, 1, 2, 3, *range(12, 24), 44],
            22: [0, 1], 23: None, 30: [0, 1]}
# Existing FoD/Stadium event handling, Corneria anchor, and Great Bay turtle
# home fallback stay in meleeStages/litePaint until seed simulators replace them.
LEGACY = {2, 3, 7, 13, 27}
SOURCE = dict(zip([2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,22,23,24,25,27,28,29,30,31,32],
    ['izumi','pstadium','castle','kongo','zebes','corneria','story','onett','mutecity','rcruise','garden','greatbay','shrine','kraid','yorster','greens','fourside','inishie1','inishie2','venom','pura','bigblue','icemt','flatzone','oldpupupu','oldyoshi','oldkongo','battle','last']))
RANDOM = {2,3,4,5,6,7,9,11,13,15,16,17,18,19,20,22,24,25,27,29}
LONGER = {10:12000, 11:16000, 22:24000, 23:25200, 30:7200}
DECOMP = Path(os.environ.get('MELEE_DECOMP') or Path.home() / 'projects' / 'melee') / 'src' / 'melee' / 'gr'
EVIDENCE = {
 8: 'grStory: Randall path is frame-indexed; all collision repeats after 1200 frames. Shy Guy RNG is not MapLine geometry.',
 10: 'grMuteCity_801F04B8 command table and 801F0D20 collision spline are scripted. Car/item RNG does not modify these MapJoints. The early capture verifies a 6012-frame suffix loop after startup.',
 11: 'grRCruise scripted global scroll only; contact/camera-dependent groups excluded. The early capture verifies a 7200-frame loop for these joints.',
 12: 'grGarden random hazards do not move MapLine geometry; all vertices and visibility invariant in dump.',
 14: 'grShrine initialization/update has no collision-affecting RNG; all collision invariant in dump.',
 22: 'grVenom_802040F0/80204284 animate Great Fox independently of random arwing scheduler. The early capture verifies a 9999-frame terrain loop.',
 23: 'grpura stageGObj1_OnInit/GObjProc RNG selects background colors; collision path is scripted. Existing DAT animation length 12500, but 25200 live rows do not verify a complete vertex/flag repeat.',
 28: 'groldpupupu wind/background RNG does not change MapLine geometry; all collision invariant in dump.',
 30: 'groldkongo Ground_InitMapCollAndAnim/Ground_UpdateMapColl scripted platforms repeat every 499 frames. Barrel/bird RNG does not modify those five MapJoints.',
 31: 'grbattle collision invariant; no collision-affecting RNG.',
 32: 'grlast collision invariant; no collision-affecting RNG.',
}

# Porting decisions, checked against the named decomp functions. Offsets below
# are yakumono_param fields, not guessed numeric constants: the NPZ does not
# contain that DAT parameter block. A port must extract it independently.
PORTING = {
  2: (['grIzumi_801CC358'],
      'Joints 0/1 are the independently moving side platforms; joints 2/3 are the top platform and base. '
      'The xC4 platform state machine chooses dwell/rise/fall and target heights with Randf. '
      'Timers use x40/x44 plus the state-dependent wait; branch probabilities x30/x34. '
      'Recorded FoD events take priority; otherwise retain current witness fallback. No fixed period.'),
  3: (['grStadium_801D435C','grStadium_801D4548','grStadium_801D2A60'],
      'Transformation selection: joint 1+2 fire, 3 grass, 4 neutral, 5 rock, 7 water; joint 6 base is permanent. '
      'Joint 0 is the water windmill. 801D4548 chooses a non-repeating form via Randi(kinds length); '
      '801D435C randomizes the next wait. Water fountains use 801D2A60 (Randf, x48/x4A wait). '
      'Do not replace recorded stage events. Current morph timing is warning 302f, shrink/flat 181f, grow 121f; '
      'windmill -0.5 degrees/frame from creation. The dump remained neutral, so other forms are NOT live-validated. '
      '801D1E20 is background randomness, not terrain.'),
  4: (['grCastle_801CDFD8','grCastle_801CE054','grCastle_801CE19C',
       'grCastle_801CF7B0','grCastle_801CF868','grCastle_801CF750',
       'grCastle_801CEF04','grCastle_801CEACC','grCastle_801CFBD4'],
      'Joint 3 is permanent castle; 4/5 are weight-sensitive side platforms (callback 801CF750). '
      '801CDFD8 initializes xD4=x8+Randi(xA); 801CE054 chooses one of nine patterns excluding the '
      'last three, scheduled by 801CE19C. Satellite scheduler 801CF7B0/801CF868 chooses a weighted '
      'slot and a bone target (Randi(11)), with x0..x2 timer. 801CEF04 chooses active duration '
      'between x40/x42. 801CFBD4 grows blocks by x48, enables them at full scale, and disables '
      'immediately on shrink (x4C); nearby fighters delay growth. 801CEACC maps controller map_id '
      'Pura->joints11..14, Shrine->6,7,9,10 (8 disabled), Garden->0,1,2. These are enum names '
      'reused for castle map objects, NOT stage IDs. Joint3 stays permanent. Wind '
      '801D0BBC/801D0D24 is excluded. No universal period.'),
  5: (['fn_801D542C','grKongo_801D7BBC','grKongo_801D6074','grKongo_801D6198',
       'grKongo_801D7134','fn_801D7700','grKongo_801D77E0'],
      'Joints 0/1 are spawned logs/crates, randomized x in 801D6074, enabled in 801D6198 after animation. '
      'Spawn scheduler 801D7BBC uses weighted Randf/Randi choices and an unk0..unk4 wait, initialized in fn_801D542C. '
      'The main floor is joint 4, dynamic lines 39..69: 801D7134 edits the 15 plank pairs starting at line 40. '
      'Landing callback fn_801D7700 adds unkA4 angular impulse to a plank; 801D6AFC damps/couples them '
      'using unk90..unkAC. 801D77E0 propagates this to attached platforms (joints 2/3/5/6). '
      'Only joint 7, the rock, is independent. Do not bake a solo floor as a deterministic schedule. '
      'Barrel cannon RNG in 801D577C and visual splines in 801D651C are outside MapLine surfaces.'),
  6: (['grZebes_801D881C','grZebes_801DA528','grZebes_801DAA08','grZebes_801D9798','grZebes_801D99E0'],
      'Joint 0 is the dynamic connector, vertices 0..5 / lines 26..30, rewritten from bubble/column '
      'heights by 801D881C and grZebes_UpdateCollisionColumns; damage can disable it. '
      '801DA528 and damage callbacks fn_801DA9D8/fn_801DA9F0 drive the destructible supports and '
      'moving sides, joints 1/2/4/5. Joint 3 is the independent top platform. '
      '801DAA08 chooses effect/response slots with Randi(count); 801D881C uses Randf in its bubble state. '
      'Acid controller 801D9798/801D99E0 has randomized parameter min/max delays; 801D9508/801D95B8 '
      'use 3000+Randi(600). Acid hitboxes are not automatically floor lines. '
      'Keep the neutral fallback until damage inputs, stage parameters and item-state dependencies are ported.'),
  7: (['grCorneria_801E1970','grCorneria_801DCE1C','grCorneria_801DCCFC',
       'grCorneria_801DE8E4','grCorneria_801DED50'],
      'Ship joints 3/4 drift together; 801E1970 uses three Randf draws for target offsets/velocity '
      'inside yakumono limits. Grounded anchor fallback stays. Arwing surfaces are joints 0..2 and 5..7; '
      '801DCCFC randomizes wait ranges, 801DCE1C chooses flyby groups/routes and 801DED50 chooses '
      'substates/targets. Read the chosen GrJoint map link when attaching an arwing; do not confuse '
      'model bone numbers with the joint IDs below. Timing is state/animation-driven, not a frame loop. '
      'Smash-taunt voice selection 801E2AF4 is excluded from collision state.'),
  9: (['grOnett_801E3DA0','grOnett_801E40E4','grOnett_801E5214','grOnett_801E54B4'],
      'Joint 2 is permanent street/buildings. Joints 0/1 are weighted awnings with contact callbacks '
      '801E54B4; 801E5214 integrates sag/velocity/cooldown. Joints 3/4 are the drugstore platforms, '
      'hit-count callback 801E40E4; collapse state 5 removes them at ticks 20 and 90. '
      '801E3DA0 draws Randf for the x3C..x40 recovery timer after collapse, then rebuilds. '
      'An idle dump is STATIC but this is player-triggered TOGGLING in normal play. '
      'Car selection 801E41C8/801E43E0 and sound 801E5030 do not add MapLine floors.'),
  11: (['grRCruise_80200C04','grRCruise_802010A4','grRCruise_80200578',
        'grRCruise_8020071C','grRCruise_80200154','fn_80200460','grRCruise_80201588'],
      'Global scrolling and ship are deterministic. Joint 5 is the teeter controlled by 80200578 '
      'contact weight and 8020071C integration. Donut platforms are joints 27..43; 802010A4 records '
      'contacts, 80200C04 states idle->loaded->shake->fall->wait->blink use x20/x24 timers, shake '
      'every x28 frames with Randi(100*(x30-x2C)), gravity x34 capped x38, respawn x3C, blink x40/x44. '
      'Carpets are joints 24..26 (gobj 4 bones 1/26/51), callbacks fn_80200460 and 80200154, '
      'timers xC/x10/x14/x18/x1C. Joint12 is scripted on gobj1 bone19; lbl_803E5014 sets x4=true '
      'for joints12..23, so 80201588 explicitly skips their camera-dependent state machine. '
      'These are included in the bake. Appearing groups 4,6..10 are camera-triggered by 80201588 '
      '(Camera_8003118C), so visibility is not assumed independent of fighters. Joint 11 is disabled '
      'at initialization. Wind Randf in 80201110 is excluded. Baked joints are listed in report.json.'),
  13: (['grGreatBay_801F4694','grGreatBay_801F62F8','grGreatBay_801F5E28',
        'grGreatBay_801F60C4','grGreatBay_801F5914'],
      'Turtle joints 1..4: 801F4694 state machine uses rand_range for kame_wait_frame_a/b, '
      'kame_rebirth_frame_a/b, kame_x_fb_offset_a/b and kame_x_lr_offset_a/b. '
      '801F62F8 uses ZRANDI(weight total) to select a non-repeating turtle direction. '
      'Front/back pose enables joint 1; side poses enable 2/3/4. Diving hides all four. '
      'Joint 0 raft is contact-driven: 801F60C4 accumulates weight, 801F5E28 eases tilt/slide/down. '
      'Joint 5 Tingle responds to 801F5914 contacts and balloon state. Joints 6/7 are independent static shore. '
      'Moon timers and turtle item-spawn 801F63F4 RNG do not directly change MapLine collision; '
      'they can still consume the shared RNG stream. No fixed collision period.'),
  15: (['grKraid_801FE818','grKraid_801FEA00','grKraid_801FEE54',
        'grKraid_801FE440','grKraid_801FE6D8'],
      'ALL six joints rotate with the stage. 801FE818 initializes kraid_wait_time+Randi(kraid_wait_time_add). '
      '801FEA00 chooses Randi(3) attack animations; 801FEE54 chooses one of six non-repeating x positions '
      'or extreme positions, and random facing at x=0. Contact windows are attack ticks 147..169 '
      '(left) /123..138 (right), with hit test thresholds 158/130. 801FE6D8 sets angular velocity '
      'from hand x; 801FE440 draws rand_range(map_time_max,map_time_min), rotates and decelerates. '
      'Dynamic line kinds change with the rotation, even when enable/hide do not change. '
      'No frame-only motion is exact; the previous ground trail is retained.'),
  16: (['grYorster_802022A4','grYorster_80202428','grYorster_802024F0','grYorster_8020266C'],
      'No HSD_Rand calls in gryorster.c. This is player-triggered, not RNG-driven: nine destructible '
      'blocks are joints 1..9; joint 0 is fixed terrain. The gryorster mpJointSetCb2 damage callback '
      'starts break, hide, cooldown and restoration states. 8020266C uses damage x08/x0C, weight '
      'x00/x04, break delay x18 and end animation x1C; state2->3 disables the joint. After 323 '
      'ticks (0x143), restoration checks occupancy; retries wait 25 ticks (0x19), animation speed .3. '
      'CollJoint_TooFar changes in this dump do NOT mean a block broke. Do not infer a break '
      'schedule from the solo dump; numeric parameter values still need the DAT block.'),
  17: (['grGreens_802166C4','grGreens_80215358','grGreens_80215ED8','grGreens_8021483C'],
      'Joint 30 is terrain. Blocks are joints 0..29 in a 5-row x 6-column grid; joint = row*6+column, '
      'four vertices per joint. 802166C4 uses occupancy-dependent weights to choose column, '
      'Randi(x20) for bomb/star type, and randrange(x0_blockTimerMin,x4_blockTimerMax) for spawn wait. '
      '80215358 spawns at a selected grid cell; 80215ED8 advances falling/settled/destroyed states and '
      'moves/toggles the matching joint. Damage and explosions must feed the state machine. '
      'Wind/apple RNG in 80213C10 is not itself a MapLine change; item explosions can trigger damage.'),
  18: (['grFourside_801F3154','grFourside_UpdateCrane','grFourside_801F388C'],
      'Joints 0/1/2 are building collision; crane is joint 3 (line 15), UFO is joint 4 (lines 16..29). '
      '801F3154 seeds crane_wait+Randi(crane_wait_add); UpdateCrane plays 300-frame travel, '
      'then crane_iron_wait+Randi(crane_iron_wait_add), random up/down displacement, speed and bounce. '
      '801F388C rolls UFO probability, building Randi(3), and next wait add; model animation controls '
      'the UFO collision transform/hide. Helicopter 801F3C40/801F3CC8 has no additional MapJoint '
      'in this five-joint dump. No universal period.'),
  19: (['grInishie1_801FAD84','grInishie1_801FB0AC','fn_801FBEB8','fn_801FC9AC'],
      'Joint 0 is three disjoint ground islands. Joints 1..19 are breakable/coin blocks, '
      '20/21 the weight-sensitive pulley platforms (floor lines 26/27). 801FAD84 chooses block '
      'indices with Randi(BLOCK_COUNT), 801FB0AC includes Randi(19) selection and randomized '
      'unk0..unk4 / unk8..unkC timers. fn_801FBEB8 consumes damage; fn_801FC9AC consumes grounded '
      'weight for the pulley descent/fall/reset. Preserve contact history; no frame-only period. '
      'No changes occurred in this solo dump, which does not prove these pieces static.'),
  20: (['grInishie2_801FD018','grInishie2_801FD0B4','grInishie2_801FD4F0','grInishie2_801FD824'],
      'Joint 1 is permanent ground. Joints 12/13 are the two flying carpets; 801FD018 initializes '
      'unk0+Randi(unk2) and unk4+Randi(unk6), 801FD0B4 decrements these and removes/recreates '
      'their joints as carriers spawn. 801FD4F0/801FD824 choose Randi(2) spawn sides for hazards. '
      'Joint 14 belongs to Birdo (map_gobj15, it_802ECD3C); joint0 belongs to the independent '
      'map_gobj1 carrier initialized by 801FD824, not to Birdo. Joints2..11 '
      'are dormant in this recording. Port the item/controller collision link before assigning '
      'an item to those dormant joints. See exact joint/line table; that actor association is not '
      'proven by this dump alone. No fixed period.'),
  22: (['grVenom_8020362C','grVenom_80203B14','grVenom_80205AD4','grVenom_80205F30'],
      'Great Fox joints 0/1 follow independent model animation (802040F0/80204284), baked in range. '
      'Arwing joints 3/4 start disabled; joint 2 is additional initially disabled map collision. '
      '8020362C chooses flyby route/mode with Randi/Randf and 80203B14 random waits. '
      '80205AD4/80205F30 select route states and targets. Do not let those RNG calls invalidate '
      'the independent Great Fox animation, or bake their spawn schedule from a single dump. '
      'Some no-collision background flybys use the same scheduler; require the map link before '
      'emitting a surface. Numeric waits come from yakumono_param.'),
  24: (['grBigBlue_801E6C60','grBigBlue_801EB4AC','grBigBlue_801EC58C',
        'grBigBlue_801EC6C0','grBigBlue_801ECB50'],
      'No permanent static island is observed. Vehicle joints 0..32 are chosen/spawned/steered by '
      '801EC58C/801EC6C0/801ECB50 using reserved/free car pools, lane choices and parameter timers. '
      '801EB4AC chooses Randi(12) road sections, rejects inaccessible/recent/current choices, and '
      'activates: lane0->joint35; 1->50; 2->38..40; 3->36/37; 4->64/65; 5->33; '
      '6->52..54; 7->55..57; 8->58..60; 9->61..63; 10->51; 11->41..49. '
      'Joint34 and joint66 belong to other moving platform/controller links; their exact actor '
      'association needs GrJoint/DAT confirmation. 801E6C60 randomizes event waits, heights, and '
      'platform transitions, so a copied road recording is not deterministic. Timers/ranges are '
      'yakumono x fields. 801EDF44 has background traffic RNG that must be excluded from surfaces '
      'unless its chosen object attaches collision. No entire-stage period; ground-trail fallback stays.'),
  25: (['stageGObj9_OnInit','fn_801F8E58','fn_801F9038','grIceMt_GetRandomTimer',
        'grIceMt_GetRandomIndex','onJointCollision','fn_801F8C64'],
      'The scrolling terrain controller initially selects two distinct fields with Randi(6). '
      'fn_801F9038 chooses subsequent fields, excluding cooldown/current upper/under IDs. '
      'fn_801F8E58 chooses one of 12 eligible scroll programs with a cooldown, then a timer '
      'from yakumono s16 offsets 0x36/0x38. Breakable/slippery platforms also respond to '
      'onJointCollision/fn_801F8C64. All 217 MapJoints are terrain or block copies; map each '
      'field through icemt_field and grIm_803E4544, not by treating visible copy indices as a '
      'single repeating world. Observed translated ranges are 0..31,32..66,67..101,180..216; '
      '102..179 remain dormant in this dump. Exact ranges/vertices are below. '
      'The Adventure fixed sequence fn_801F9150 is not the randomized VS sequence. No frame loop.'),
  27: (['grFlatzone_802171D4','grFlatzone_802174EC','grFlatzone_80218060'],
      'Joint 50 is the fixed ground. Controller 802171D4 waits rand_int(unk4,unk0), '
      'chooses non-repeating layout/event 3 or 4, and starts platform machinery. '
      '80218060 selects Randi(8) platform arrangement and Randi(4) variation; 802174EC '
      'selects the next valid non-repeating animation via Randi(4)+1 and the grFz_803E7A68 table, '
      'with rand_int(unkC,unk8) wait. Joints 0..49 are alternate platform/tool copies, '
      'hidden/activated by animation visibility. Most remain hidden for the whole dump: drawing '
      'all of them is not exact. The old all-layout silhouette is retained strictly as a legacy fallback '
      'until this port replaces it; its high grounded-fit cannot validate visibility. '
      'Tool-fall item RNG in 80217EF0 does not add a new MapLine; '
      'preserve RNG consumption if replaying the shared stream. No fixed period.'),
  29: (['fn_8020F2A8','grOldYoshi_8020EC10'],
      'Joint 3 is the fixed island and its platforms; joints 0/1/2 are the three clouds. '
      'fn_8020F2A8 records contact; 8020EC10 advances cloud occupancy, disappearance and '
      'respawn timers, calling mpLib_80057BC0 / mpJointListAdd. Player-triggered, no RNG '
      'in the cloud state machine (the Randi(3) line is commented out). '
      'Background guest selection 8020F088/Randf/rand_range is excluded. '
      'Cloud sag uses x4/x8/xC; loaded time x0 starts disappearing, disable at x10, wait x2, '
      'then re-enable at x12. '
      'The neutral clouds are retained as the current fallback, not counted exact.'),
}


def vanilla_names():
    # Read the literal without importing stage_dump (which imports the harness).
    tree = ast.parse((REPO / 'tools/liteaudit/stage_dump.py').read_text('utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'VANILLA' for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError('stage_dump.VANILLA missing')


def compact(value):
    return json.dumps(value, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def pack_simulators(packs, source_dir):
    """Keep generator inputs in stageSim; ship one collision + sim asset per ID."""
    for path in sorted((source_dir / 'stageSim').glob('*.json')):
        if not path.stem.isdigit() or path.stem == '10':
            continue  # Stage 10 shares the calibrated collision capture below.
        table = json.loads(path.read_text(encoding='utf-8'))
        if table:
            packs.setdefault(path.stem, {})['sim'] = table
    # Fighter hitboxes/ECB/weights live in data/fighters/<internal-id>.json.
    # Each stage remains one request; a replay loads only its present fighters.


def pack_simulator_files(source_dir):
    packs = {path.stem: json.loads(path.read_text(encoding='utf-8'))
             for path in sorted((source_dir / 'stages').glob('*.json')) if path.stem.isdigit()}
    pack_simulators(packs, source_dir)
    for sid, pack in packs.items():
        pack = {key: pack[key] for key in ('collision', 'movers', 'sim') if key in pack}
        (source_dir / 'stages' / f'{sid}.json').write_text(compact(pack) + '\n', encoding='utf-8', newline='\n')


def write_stage_data(stages, data_path, movers_path=None, sim10_path=None):
    """Deterministically partition generated tables, preserving unowned tables.

    The historical DAT movers and extended stage-10 capture have no tracked
    producer. Their canonical data now lives in stages/{23,10}.json. Accept
    freshly generated legacy tables too; --split-existing migrates/repackages
    them without needing the original captures or running Dolphin.
    """
    def encode(value):
        # Least-squares fits can differ only in the sign of rounded zero
        # across BLAS builds. Canonicalize it without changing any coordinates.
        def canonical(item):
            if isinstance(item, dict): return {key: canonical(val) for key, val in item.items()}
            if isinstance(item, list): return [canonical(val) for val in item]
            return 0.0 if isinstance(item, float) and item == 0 else item
        result = canonical(value)
        # DAT simulator inputs are not least-squares fits. Preserve their
        # authored signed zeros exactly, just as --pack-sim does.
        if isinstance(value, dict) and 'sim' in value:
            result['sim'] = value['sim']
        return (compact(result) + '\n').encode()

    source_dir = DATA.parent
    output_dir = data_path.parent
    packs = {}
    for path in sorted((source_dir / 'stages').glob('*.json')):
        packs[path.stem] = json.loads(path.read_text(encoding='utf-8'))
    # Custom output may itself be a previously split bake.
    if output_dir != source_dir:
        for path in sorted((output_dir / 'stages').glob('*.json')):
            packs[path.stem] = json.loads(path.read_text(encoding='utf-8'))
    movers = json.loads((movers_path or source_dir / 'meleeMovers.json').read_text(encoding='utf-8'))
    sim10 = json.loads((sim10_path or source_dir / 'stageSim/10.json').read_text(encoding='utf-8'))
    if sim10.get('groups'):
        packs.setdefault('10', {})['sim'] = sim10
    pack_simulators(packs, source_dir)
    for sid, table in movers.items():
        if len(compact(table).encode()) > HEAVY_BYTES:
            packs.setdefault(sid, {})['movers'] = table
    core = {}
    for sid, original in stages.items():
        entry = dict(original)
        if entry.pop('deferred', False):
            entry.update(packs[sid]['collision'])
        if len(compact(entry).encode()) > HEAVY_BYTES:
            packs.setdefault(sid, {})['collision'] = {
                'groups': entry['groups'], 'tracks': entry['tracks']}
            entry.update(groups=[], tracks=[], deferred=True)
        if sid == '10' and packs.get(sid, {}).get('collision'):
            # One canonical capture for both consumers; never retain the old
            # extended sampler with the previous frame calibration.
            packs[sid]['sim'] = {key: original[key] for key in ('range', 'loop', 'loopStart', 'static') if key in original}
            packs[sid]['sim']['collision'] = True
        core[sid] = entry
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'stages').mkdir(exist_ok=True)
    for sid, pack in sorted(packs.items(), key=lambda pair: int(pair[0])):
        if sid not in core:
            continue
        if 'collision' in pack or 'movers' in pack:
            core[sid]['deferred'] = True
        # Explicit key order makes migrations and subsequent bakes identical.
        pack = {key: pack[key] for key in ('collision', 'movers', 'sim') if key in pack}
        (output_dir / 'stages' / f'{sid}.json').write_bytes(encode(pack))
    data_path.write_bytes(encode({'schema': 1, 'stages': core}))
    small_movers = {sid: table for sid, table in movers.items() if 'movers' not in packs.get(sid, {})}
    (output_dir / 'meleeMovers.json').write_bytes(encode(small_movers))
    (output_dir / 'stageSim').mkdir(exist_ok=True)
    # Compatibility input for old external generators; runtime uses stages/10.
    (output_dir / 'stageSim/10.json').write_bytes(b'{}\n')


def rounded(a):
    return np.round(a, 4).tolist()


def slippi_frames(match_frames):
    """Boundary rows are AFTER the same Slippi frame, including frame zero.

    During countdown the match counter is held at zero. Recover those rows
    by index backwards from the first counter value 1: its predecessor is 0.
    All five early captures independently confirm this with RAM seed == raw
    replay pre seed at s+1 on every countdown row (C16 calibration.json).
    """
    frames = np.asarray(match_frames, dtype=np.int64).copy()
    zero = np.flatnonzero(frames == 0)
    if len(zero) > 1:
        last = int(zero[-1])
        if not np.array_equal(zero, np.arange(last + 1)) or last + 1 == len(frames) or frames[last + 1] != 1:
            raise ValueError('Countdown needs a contiguous zero prefix followed by match_frame 1')
        frames[:last + 1] = np.arange(-last, 1)
    return frames


def load_dump(path):
    with np.load(path, allow_pickle=False) as src:
        d = {k: src[k] for k in src.files}
    d['frames'] = slippi_frames(d['match_frame'])
    # Last sample wins for duplicate gameplay frames; countdown rows are distinct.
    _, rev = np.unique(d['frames'][::-1], return_index=True)
    keep = np.sort(len(d['match_frame']) - 1 - rev)
    for key in ('frames', 'match_frame', 'verts', 'line_flags', 'joint_flags', 'seed'):
        if key in d:
            d[key] = d[key][keep]
    return d


def joint_lines(d, joint):
    j = d['joints'][joint]
    return [i for k in range(0, 10, 2) for i in range(int(j[k]), int(j[k] + j[k+1]))]


def line_states(d, ids, joint):
    flags = d['line_flags'][:, ids]
    jf = d['joint_flags'][:, joint, None]
    active = ((flags & ENABLED) != 0) & ((flags & (HIDDEN | EMPTY)) == 0)
    active &= ((jf & ENABLED) != 0) & ((jf & HIDDEN) == 0)
    # PLATFORM is normally in MapLine.lo_flags, not CollLine.flags (mplib.c init).
    return np.where(active, (flags & 15) | ((flags | d['lines'][ids, 7]) & PLATFORM), 0).astype(int)


def lines_at(d, joints, frame=0):
    out = []
    for j in joints:
        ids = joint_lines(d, j)
        flags = line_states(d, ids, j)[frame]
        for lid, flag in zip(ids, flags):
            if flag & 15:
                a, b = d['lines'][lid, :2]
                out.append([int(lid), int(flag), *rounded(d['verts'][frame, [a,b]].ravel())])
    return out


def silhouette(lines):
    """Largest connected solid floor/wall upper chain; flat artificial underside.

    A monotone x chain cannot self-intersect. Keep ALL real floors separately,
    so caves and disjoint landmasses are never filled across or lost. Drawing
    edges remain authoritative collision; the underside is decorative only.
    """
    solid = [l for l in lines if not l[1] & PLATFORM and l[1] & 13]
    adjacency = {}
    for l in solid:
        a, b = tuple(l[2:4]), tuple(l[4:6])
        # Traversal along floors left->right, with vertical walls joining them.
        if a[0] > b[0]: a,b = b,a
        if a == b: continue
        adjacency.setdefault(a, []).append(b)
        if a[0] == b[0]: adjacency.setdefault(b, []).append(a)
    paths = []
    def walk(p):
        nxt = [b for b in adjacency.get(p[-1], []) if b not in p]
        if not nxt:
            if len(p) > 1 and p[-1][0] > p[0][0]: paths.append(p)
        else:
            for b in nxt: walk(p + [b])
    for a in adjacency:
        walk([a])
    if not paths: return []
    chain = max(paths, key=lambda p: (p[-1][0]-p[0][0], max(y for x,y in p)))
    # Keep the actual wall extents when available; fill only this landmass.
    left, right = chain[0][0], chain[-1][0]
    bottom = min([p[1] for p in chain] + [min(l[3],l[5]) for l in lines
                 if left <= l[2] <= right and left <= l[4] <= right]) - 5
    poly = [list(p) for p in chain] + [[right,bottom],[left,bottom],list(chain[0])]
    return poly


def keyframes(times, values, tolerance):
    """Adaptive stride/lerp, bounded by maximum 2D vertex distance on ALL rows."""
    values = np.asarray(values, dtype=np.float64)
    keep = {0, len(times)-1}
    stack = [(0, len(times)-1)]
    while stack:
        a,b = stack.pop()
        if b <= a+1: continue
        t = (times[a+1:b]-times[a]) / (times[b]-times[a])
        interp = values[a] + t[:, None] * (values[b]-values[a])
        error = np.linalg.norm((values[a+1:b]-interp).reshape(len(t), -1, 2), axis=2).max(axis=1)
        i = int(np.argmax(error))
        if error[i] > tolerance:
            mid = a+1+i
            keep.add(mid); stack.extend([(a,mid),(mid,b)])
    ids = sorted(keep)
    return [[int(times[i]), *rounded(values[i])] for i in ids]


def sample(keys, times):
    k = np.asarray(keys)
    return np.stack([np.interp(times, k[:,0], k[:,i]) for i in range(1,k.shape[1])], axis=1)


def find_period(d, groups):
    if not groups or np.any(np.diff(d['frames']) != 1): return None, None
    vertices = sorted({int(x) for j in groups for lid in joint_lines(d,j) for x in d['lines'][lid,:2]})
    v = d['verts'][:,vertices]
    if np.max(np.abs(v-v[:1])) < .01: return None, None
    flags = np.concatenate([line_states(d,joint_lines(d,j),j) for j in groups], axis=1)
    # Use a moving pose to reject parked-pose coincidences cheaply. Then verify
    # EVERY vertex and flag across at least two complete cycles. A startup
    # prefix may be nonperiodic; preserve it and wrap only the verified suffix.
    n = len(v)
    delta = np.max(np.linalg.norm(v[1:] - v[:-1], axis=2), axis=1)
    anchor = n//2 + int(np.argmax(delta[n//2:])) + 1
    candidates = np.flatnonzero(np.max(np.abs(v[:anchor] - v[anchor]), axis=(1,2)) <= .01)
    for period in sorted(anchor - int(other) for other in candidates):
        if period < 30 or period > n//2: continue
        bad = np.any(flags[period:] != flags[:-period], axis=1)
        bad |= np.max(np.linalg.norm(v[period:] - v[:-period], axis=2), axis=1) > .01
        start = int(np.flatnonzero(bad)[-1] + 1) if bad.any() else 0
        if start + 2 * period <= n and np.max(np.abs(v[start:start+period] - v[start])) > .01:
            return period, start
    return None, None


def bake_group(d, j, tolerance, period, loop_start=None):
    ids = joint_lines(d,j)
    vertices = sorted({int(x) for lid in ids for x in d['lines'][lid,:2]})
    if not vertices: return None, []
    states = line_states(d,ids,j)
    if not states.any(): return None, []
    local = {v:i for i,v in enumerate(vertices)}
    times = d['frames']
    v = d['verts'][:,vertices].astype(float)
    delta = v[:,0]-v[0,0]
    translation_error = float(np.linalg.norm(v-(v[:1]+delta[:,None]),axis=2).max())
    translation = translation_error < tolerance / 4
    # Camera-projected rigid stage models may need a 2D affine transform rather
    # than a rotation (Venom banks in 3D). Verify the fit against EVERY vertex.
    base = np.asarray(rounded(v[0]))
    design = np.c_[base, np.ones(len(base))]
    matrix = np.linalg.lstsq(design, v.transpose(1,0,2).reshape(len(base),-1), rcond=None)[0]
    matrix = matrix.reshape(3,len(v),2).transpose(1,0,2)
    fitted = np.einsum('vi,fij->fvj',design,matrix)
    affine = not translation and np.linalg.norm(fitted-v,axis=2).max() < tolerance / 4
    vals = delta if translation else v.reshape(len(v),-1)
    n = loop_start+period+1 if period else len(times)
    keys = keyframes(times[:n], vals[:n], tolerance*.8)
    # No interpolation across a visibility/kind transition: flags are step-held.
    changes = np.r_[True, np.any(states[1:n] != states[:n-1], axis=1)]
    flags = [[int(times[i]), *states[i].tolist()] for i in np.flatnonzero(changes)]
    g = dict(joint=j, vertices=vertices,
             lines=[[lid,local[int(d['lines'][lid,0])],local[int(d['lines'][lid,1])]] for lid in ids],
             keys=keys, flags=flags)
    if translation: g['base'] = rounded(v[0])
    elif affine:
        g['base'] = rounded(v[0]); g['affine'] = True
        # Select key times in vertex space, so large stages get the same world
        # error bound as small ones. Matrix coefficients need finer precision.
        lookup = {int(t):i for i,t in enumerate(times)}
        g['keys'] = [[k[0], *np.round(matrix[lookup[k[0]]].ravel(),8).tolist()] for k in keys]
        keys = g['keys']
    eval_times = np.where(times >= times[loop_start], (times-times[loop_start]) % period+times[loop_start], times) if period else times
    prediction = sample(keys,eval_times)
    if translation: prediction = np.asarray(g['base'])[None] + prediction[:,None]
    elif affine: prediction = np.einsum('vi,fij->fvj',design,prediction.reshape(-1,3,2))
    else: prediction = prediction.reshape(v.shape)
    err = np.linalg.norm(prediction-v,axis=2)
    return g, err.ravel().tolist()


def classify(d):
    moving, deforming = [], []
    for j,row in enumerate(d['joints']):
        a,n=map(int,row[-2:]); v=d['verts'][:,a:a+n]
        if np.max(np.abs(v-v[:1])) <= 1e-5: continue
        moving.append(j)
        # Pairwise distances catch rigid rotation, translation, and deformation.
        # Three anchors avoid a quadratic array on the larger collision groups.
        for anchor in {0,n//2,n-1}:
            dist=np.linalg.norm(v-v[:,anchor:anchor+1],axis=2)
            if np.max(np.abs(dist-dist[:1])) > .02:
                deforming.append(j); break
    bits = ENABLED | HIDDEN | EMPTY
    toggle = np.any((d['line_flags'] & bits) != (d['line_flags'][:1] & bits)) or np.any((d['joint_flags'] & (ENABLED|HIDDEN)) != (d['joint_flags'][:1] & (ENABLED|HIDDEN)))
    classes = (['DEFORMING' if deforming else 'RIGID-ANIMATED'] if moving else []) + (['TOGGLING'] if toggle else [])
    return '+'.join(classes) or 'STATIC', moving, deforming


def second_dump(d,path):
    if not path.exists(): return None
    b=load_dump(path)
    if not np.array_equal(d['lines'],b['lines']): return {'error':'topology differs'}
    t,ia,ib=np.intersect1d(d['frames'],b['frames'],return_indices=True)
    if not len(t): return {'error':'no equal match frames'}
    return dict(frames=len(t), vertex_max=float(np.linalg.norm(d['verts'][ia]-b['verts'][ib],axis=2).max()),
                line_flag_differences=int(np.count_nonzero(d['line_flags'][ia]!=b['line_flags'][ib])),
                joint_flag_differences=int(np.count_nonzero(d['joint_flags'][ia]!=b['joint_flags'][ib])))


def project(entry,frame):
    out=list(entry['static']) + list(entry.get('neutral',[]))
    start = entry.get('loopStart', entry['range'][0])
    if entry.get('loop') and (start == entry['range'][0] or frame >= start):
        frame=(frame-start)%entry['loop']+start
    if not entry['range'][0] <= frame <= entry['range'][1]: return out
    for g in entry['groups']:
        keys=entry['tracks'][g['track']] if 'track' in g else g['keys']
        values=sample(keys,np.array([frame]))[0]
        if g.get('affine'): v=np.c_[g['base'],np.ones(len(g['base']))] @ values.reshape(3,2)
        else: v=np.asarray(g['base'])+values if 'base' in g else values.reshape(-1,2)
        flags=g['flags'][max(0,np.searchsorted([f[0] for f in g['flags']],frame,side='right')-1)][1:]
        for (lid,a,b),state in zip(g['lines'],flags):
            if state & 15: out.append([lid,state,*v[a].tolist(),*v[b].tolist()])
    return out


def share_tracks(entry):
    tracks=[]
    for g in entry['groups']:
        keys=g.pop('keys'); found=None
        a=np.asarray(keys)
        for i,t in enumerate(tracks):
            b=np.asarray(t)
            if a.shape == b.shape and np.max(np.abs(a-b)) < .0005:
                found=i; break
        if found is None: found=len(tracks); tracks.append(keys)
        g['track']=found
    entry['tracks']=tracks


def write_truth(d,entry,out,sid):
    # Independent expected coordinates are copied from NPZ, not reconstructed
    # from baked keys. Used by the JS evaluator/paint-path audit.
    owners=np.zeros(len(d['lines']),dtype=int)
    for j in range(len(d['joints'])): owners[joint_lines(d,j)]=j
    states=np.zeros(d['line_flags'].shape,dtype=int)
    for j in range(len(d['joints'])):
        ids=joint_lines(d,j);states[:,ids]=line_states(d,ids,j)
    rows=[]
    for frame in range(len(d['frames'])):
        ids=np.flatnonzero(states[frame])
        rows.append([[int(i),int(states[frame,i]),*d['verts'][frame,d['lines'][i,:2]].astype(float).ravel().tolist()] for i in ids])
    data=dict(frames=d['frames'].tolist(),rows=rows,
              known=sorted({l[0] for l in entry['static']}|{l[0] for g in entry['groups'] for l in g['lines']}),
              neutral=[l[0] for l in entry['neutral']])
    with gzip.GzipFile(filename=str(out/f'truth-{sid}.json.gz'),mode='wb',mtime=0) as f:
        f.write(compact(data).encode())


def composite(sid,name,d,entry,out):
    image=Image.new('RGB',(1200,800),'#0a0c12'); draw=ImageDraw.Draw(image)
    for tile,index in enumerate(np.linspace(0,len(d['frames'])-1,6,dtype=int)):
        truth=lines_at(d,range(len(d['joints'])),index)
        baked=project(entry,int(d['frames'][index]))
        if not truth: continue
        pts=np.asarray([l[2:] for l in truth]).reshape(-1,2)
        lo,hi=pts.min(axis=0),pts.max(axis=0)
        scale=min(360/max(hi[0]-lo[0],1),330/max(hi[1]-lo[1],1))
        ox=(tile%3)*400+20-lo[0]*scale; oy=(tile//3)*400+365+lo[1]*scale
        def point(p): return ox+p[0]*scale,oy-p[1]*scale
        draw.text(((tile%3)*400+12,(tile//3)*400+10),f'{sid} {name} / slp {d["frames"][index]}',fill='white')
        for l in truth: draw.line([point(l[2:4]),point(l[4:6])],fill='#b95757',width=3)
        for l in baked: draw.line([point(l[2:4]),point(l[4:6])],fill='#56dcc8' if l[1]&1 else '#8d9ad2',width=1)
    draw.text((12,780),'Red: live collision. Cyan: baked floors. Blue: baked walls/ceilings. Red alone = unresolved.',fill='white')
    image.save(out/f'stage-{sid}.png')


def function_block(source,name):
    # Match a definition rather than a forward declaration or call. Preserve
    # line numbers; source evidence is read-only and is never shipped to phones.
    for match in re.finditer(r'\b'+re.escape(name)+r'\s*\(',source):
        p=match.end(); depth=1
        while p<len(source) and depth:
            depth+=(source[p]=='(')-(source[p]==')');p+=1
        while p<len(source) and source[p].isspace():p+=1
        if p==len(source) or source[p]!='{':continue
        end=p+1;depth=1
        while end<len(source) and depth:
            depth+=(source[end]=='{')-(source[end]=='}');end+=1
        return source.count('\n',0,match.start())+1,source[match.start():end]
    return None


def porting_note(sid,name,d,entry,out,decomp):
    if sid not in PORTING:return
    functions,decision=PORTING[sid]
    path=decomp/f'gr{SOURCE[sid]}.c'
    source=path.read_text('utf-8')
    note=[f'# {sid}: {name} collision port', '', decision, '',
          f'Source: `{path}`; SHA256 `{hashlib.sha256(path.read_bytes()).hexdigest()}`.',
          f'Observed Slippi frames {entry["range"]}; Slippi frame = match_frame (countdown recovered by row index). See report.json for independent captures.', '',
          '## Replay/simulator requirements', '',
          'Use `stageSim/index.js` registerStageSim. Output original MapLine IDs, current kind and active visibility. '
          'Read leader `frames.seed[port][idx]` and fighter positions/history; missing seed is not zero. '
          'HSD_Rand advances the shared uint32 LCG (imul(seed,214013)+2531011) and returns seed>>>16; '
          'HSD_Randi(n) is floor(n*value/65536). Replay per-frame seeds do not identify the stage call offset. '
          'Preserve call ordering, including noncollision consumers, and checkpoint for arbitrary seeking. '
          'Player damage/contact inputs and stage DAT animation/parameter blocks may be needed in addition to seeds. '
          'Return null if unavailable; do not label the retained neutral/ground-trail fallback exact.', '',
          '## Collision-affecting source entry points', '']
    for fn in functions:
        found=function_block(source,fn)
        if not found:raise ValueError(f'{path}: definition {fn} missing')
        lineno,block=found
        note.append(f'- `{fn}` at `{path.name}:{lineno}`.')
        for k,line in enumerate(block.splitlines()):
            if re.search(r'HSD_Rand|ZRAND|rand_range|rand_int|mpJoint|mpLib_80057|Ground_UpdateMapColl',line):
                note.append(f'  - L{lineno+k}: `{line.strip()}`')
    note += ['', '## Exact dump joint/line map', '',
             'Indices below are MapJoint/MapLine, not model bones or map_gobj IDs. '
             'Ranges are inclusive. A dormant joint has geometry but no active lines in this capture. '
             'Policy `pending` means a simulator must own it; `neutral` is an unverified retained pose. '
             'Visibility counts apply ENABLED/HIDDEN/EMPTY, not the proximity-only TooFar flag.', '',
             '| Joint | Vertex range | Lines | Policy | Active line-frames | Vertex displacement max |',
             '|---:|---|---|---|---:|---:|']
    for j,row in enumerate(d['joints']):
        a,n=map(int,row[-2:]);ids=joint_lines(d,j)
        ranges=[]
        for kind,k in zip(['floor','ceiling','right','left','dynamic'],range(0,10,2)):
            start,count=map(int,row[k:k+2])
            if count:ranges.append(f'{kind} {start}..{start+count-1}')
        policy='static' if j in (range(len(d['joints'])) if STATIC[sid] is None else STATIC[sid]) else 'baked' if any(g['joint']==j for g in entry['groups']) else 'neutral' if j in NEUTRAL.get(sid,[]) else 'pending'
        motion=float(np.linalg.norm(d['verts'][:,a:a+n]-d['verts'][:1,a:a+n],axis=2).max()) if n else 0
        note.append(f'| {j} | {a}..{a+n-1} | {"; ".join(ranges)} | {policy} | {np.count_nonzero(line_states(d,ids,j))} | {motion:.5f} |')
    note += ['', 'All actor associations explicitly marked unconfirmed above remain porting questions. '
             'Numeric yakumono parameter values are not contained in the NPZ and were not fabricated. '
             'Verify the port against a different seed/character and an interaction-heavy capture.', '']
    (out/f'random-{sid}.md').write_text('\n'.join(note),encoding='utf-8')


def runtime_composites(out,report):
    previews=json.loads((out/'runtime-preview.json').read_text())
    overview=Image.new('RGB',(2000,2400),'#0a0c12')
    for row in report:
        sid=row['stage'];shots=previews.get(str(sid),[])
        image=Image.new('RGB',(1200,800),'#0a0c12');draw=ImageDraw.Draw(image)
        for tile,shot in enumerate(shots):
            points=[p for l in shot['truth']+shot['lines'] for p in (l[2:4],l[4:6])]+shot['main']
            if not points:continue
            pts=np.array(points);lo,hi=pts.min(0),pts.max(0)
            scale=min(360/max(hi[0]-lo[0],1),330/max(hi[1]-lo[1],1))
            ox=tile%3*400+20-lo[0]*scale;oy=tile//3*400+365+lo[1]*scale
            def point(p):return ox+p[0]*scale,oy-p[1]*scale
            if len(shot['main'])>=4:draw.polygon([point(p) for p in shot['main']],fill='#20243b')
            for l in shot['truth']:draw.line([point(l[2:4]),point(l[4:6])],fill='#9c4646',width=3)
            for l in shot['lines']:draw.line([point(l[2:4]),point(l[4:6])],fill='#6fddc5' if l[1]&1 else '#8591b1',width=2)
            draw.text((tile%3*400+12,tile//3*400+10),f'{sid} {row["name"]} / {shot["frame"]} / {shot["source"]}',fill='white')
        draw.text((12,780),'Actual stageGeometryAt: cyan floors, blue walls, decorative fill. Red: live truth. No fighter-trail self-validation.',fill='white')
        image.save(out/f'stage-{sid}-runtime.png')
        i=next(i for i,r in enumerate(report) if r['stage']==sid)
        overview.paste(image.crop((0,0,400,400)),(i%5*400,i//5*400))
    overview.save(out/'runtime-overview.png')


def markdown_report(report,out,data):
    runtime_path=out/'runtime-validation.json'
    runtime={r['stage']:r for r in json.loads(runtime_path.read_text())} if runtime_path.exists() else {}
    note=['# Vanilla stage collision audit', '',
          'Class is OBSERVED in the solo dump; a source-driven random/player-triggered stage can look STATIC while idle. '
          'Exact coverage is the fraction of active line-frames represented by independently known static/scripted collision, '
          'not a claim that the whole stage or a second seed was validated. Legacy/neutral poses and trails remain fallbacks. '
          'Line error is max/mean world endpoint distance from the actual JS evaluator over every unique dumped frame. '
          'Floor fit measures live floor endpoints and midpoints against actual stageGeometryAt floors (no fighter trails); '
          'it does not penalize ghost fallback surfaces, so a high score does not prove random-stage correctness. '
          'Data sizes are raw per-entry JSON; entries include dormant topology for future animation. No -b data was supplied unless the row says so.', '',
          '| ID / stage | Observed class | Exact coverage / mode | JS max / mean | Live floors <=3 | Raw bytes |',
          '|---|---|---|---|---:|---:|']
    for r in report:
        if 'error' in r:continue
        rt=runtime.get(r['stage']);e=rt['exact'] if rt else {}
        errors=f'{e["max"]:.5f} / {e["mean"]:.5f}' if e.get('max') is not None else 'no exact lines'
        fit=f'{rt["drawn_floor"]["within3"]:.1%}' if rt else 'not run'
        mode='partial/random' if r['stage'] in RANDOM else 'static' if not r['animated_joints'] else f'loop {r["loop"]}' if r['loop'] else 'bounded'
        note.append(f'| {r["stage"]} {r["name"]} | {r["classification"]} | {r["coverage"]:.1%} {mode} | {errors} | {fit} | {r["bytes"]} |')
    note+=['', '## Source evidence and coverage limits', '']
    for r in report:
        sid=r['stage']
        note.append(f'- **{sid} {r["name"]}**: '+EVIDENCE.get(sid,f'See [random-{sid}.md](random-{sid}.md) for collision functions, state/timers and full joint/line mapping.')+f' Live range {r["range"]}; second dump: {r["second"]}.')
    note+=['', '## Additional captures needed', '',
          'Capture from stage initialization (Slippi -123 onward), not only from ~75: early replay coverage is missing. '
          'Request total frame counts: '+', '.join(f'{sid}: {n}' for sid,n in LONGER.items())+'. '
          'These are minimum next capture budgets, not proven periods. Extend further if no complete repeat appears. '
          'Use a different seed/character for all animated stages; interactive stages also need contact/damage cases. '
          'Current full live loop evidence is Randall 1200 and Kongo64 499 only.', '', '## Real replays', '']
    replays_path=out/'replays.json'
    if replays_path.exists():
        for game in json.loads(replays_path.read_text()):note.append('- `'+str(game['id'])+'` stage '+str(game['stage'])+': `'+compact(game)+'`')
    note+=['', 'Only three eligible vanilla nonlegal files exist in this corpus. Both Mute City files end before the '
          'first captured frame, so they cannot validate the baked motion; Brinstar tests the retained neutral pose. '
          'Zero samples is not a pass. The requested >=90% target is not established for the other nonlegal stages.', '',
          '## Payload', '']
    total=b''
    for path in [REPO/'app/frontend/src/tracker/replays/meleeStages.js',data,REPO/'app/frontend/src/tracker/replays/data/meleeMovers.json']:
        raw=path.read_bytes();total+=raw
        note.append(f'- `{path.name}`: {len(raw):,} raw bytes; {len(gzip.compress(raw,mtime=0)):,} gzip bytes.')
    note.append(f'- Combined: {len(total):,} raw; {len(gzip.compress(total,mtime=0)):,} gzip (estimate, not a production build).')
    note+=['', '## Verification scope', '',
          'runtime-validation.json includes all-stage paint-path floor distance, authored baseline comparison, visibility/flag and endpoint counts. '
          'stage-<id>.png compares selected baked geometry to truth; stage-<id>-runtime.png shows the actual paint geometry and fill. '
          'Randall is drawn separately by the host and included in floor metrics. '
          'No browser/phone rasterization or second-seed determinism test was possible from these inputs. '
          'Random simulators are intentionally unimplemented; see registry and porting notes. '
          'Brinstar Depths, Big Blue and Icicle Mountain therefore still have no exact stage surfaces. '
          'Some actor-to-joint associations in random notes explicitly remain unresolved. '
          'The older check_render.mjs mover spy expects direct moverSegments calls for stage23; '
          'covered live frames now use collisionGeometry, so its movers_call_missing flag needs '
          'an integrator update. That unowned harness was not changed.', '']
    (out/'report.md').write_text('\n'.join(note),encoding='utf-8')


class FighterNumericDat:
    """Small read-only DAT view; roots and offsets are relative to its data block."""
    def __init__(self, data):
        _, ds, nr, nroot, nref = struct.unpack_from('>5I', data)
        self.d = data[32:32+ds]
        table = 32+ds+nr*4
        names = table+(nroot+nref)*8
        self.roots = {}
        for i in range(nroot):
            off, n = struct.unpack_from('>II', data, table+i*8)
            self.roots[data[names+n:data.index(b'\0', names+n)].decode()] = off
    def u(self, at): return struct.unpack_from('>I', self.d, at)[0]
    def f(self, at): return struct.unpack_from('>f', self.d, at)[0]
    def h(self, at): return struct.unpack_from('>h', self.d, at)[0]

class FighterDisc:
    def __init__(self, iso):
        from shared.vanilla_extract.vanilla_refs import list_files_in_iso
        self.iso = iso
        self.entries = {e['name']: e for e in list_files_in_iso(iso)}
        with iso.open('rb') as f:
            f.seek(0x420); self.base = struct.unpack('>I', f.read(4))[0]
            f.seek(self.base); h = f.read(0x100)
        self.sections = list(zip(struct.unpack_from('>18I', h), struct.unpack_from('>18I', h, 0x48), struct.unpack_from('>18I', h, 0x90)))
    def file(self, name):
        e = self.entries[name]
        with self.iso.open('rb') as f:
            f.seek(e['offset']); return f.read(e['size'])
    def ram(self, addr, size):
        with self.iso.open('rb') as f:
            for off, start, n in self.sections:
                if start <= addr and addr+size <= start+n:
                    f.seek(self.base+off+addr-start); return f.read(size)
        raise ValueError(hex(addr))

def commands(fd, action, end, legacy=False):
    if legacy:
        script = fd.script(action.index)
        return [(c.frame, c.code, c.fields) for c in script.commands if not c.after_end] if script else []
    # ftAction command control: bounded loops/subroutines, with a hard limit
    # only to reject malformed/no-time-progress scripts, never truncate output.
    from vault.echo.subactions import read_bits, to_signed
    from vault.echo.commands import COMMANDS
    at = action.script_offset
    if at is None: return []
    # ChangeMotionState installs timer=0 then runs ftAction_80073240 at
    # pose zero, which subtracts one tick before executing the first event.
    # Absolute waits re-anchor this; an initial relative wait does not.
    time = -1; stack = []; loops = []; result = []
    for _ in range(100000):
        code = fd.dat.buf[32+at] >> 2
        spec = COMMANDS[code]; fields = {}
        for p in spec.params:
            v = read_bits(fd.dat.buf, (32+at)*8+p.bit_offset, p.bits)
            fields[p.key] = to_signed(v,p.bits) if p.signed else v
        nxt = at+spec.size
        if code == 0: break
        if code == 1: time += fields['frame']
        elif code == 2: time = max(time, fields['frame'])
        elif code == 3: loops.append([nxt, fields['count']])
        elif code == 4:
            if not loops: raise ValueError('loop underflow')
            loops[-1][1] -= 1
            if loops[-1][1] > 0: nxt = loops[-1][0]
            else: loops.pop()
        elif code == 5: stack.append(nxt); nxt = fields['pointer']
        elif code == 6:
            if not stack: break
            nxt = stack.pop()
        elif code == 7: nxt = fields['pointer']
        elif code == 8: break  # waits for animation completion
        else: result.append((max(0,time), code, fields))
        if time > end: break
        at = nxt
    else: raise ValueError('command stream did not advance')
    return result

def skeleton_at(d, root):
    nodes = []
    def walk(at, parent):
        while at:
            i = len(nodes); nodes.append((parent, [d.f(at+20+k*4) for k in range(9)]))
            walk(d.u(at+8), i); at = d.u(at+12)
    walk(root, -1)
    return nodes


def skeleton(raw):
    d = FighterNumericDat(raw); nodes = []
    def walk(at, parent):
        while at:
            i = len(nodes); nodes.append((parent, [d.f(at+20+k*4) for k in range(9)]))
            walk(d.u(at+8), i); at = d.u(at+12)
    walk(next(v for k,v in d.roots.items() if k.endswith('_joint')), -1)
    return nodes


def item_commands(d, at, horizon=600, initial_timer=0):
    """itanimlist.c / lbcommand.c. Retain numeric hit commands, not DAT bytes."""
    result=[]; time=initial_timer; stack=[]; loops=[]
    if not at:return result,False
    for _ in range(20000):
        w=d.u(at); op=w>>26; nxt=at+4
        if op==0:return result,False
        if op==1:time+=w&0x3ffffff
        elif op==2:time=max(time,w&0x3ffffff)
        elif op==3:loops.append([nxt,w&0x3ffffff])
        elif op==4:
            loops[-1][1]-=1
            if loops[-1][1]:nxt=loops[-1][0]
            else:loops.pop()
        elif op==5:stack.append(at+8);nxt=d.u(at+4)
        elif op==6:
            if not stack:return result,False
            nxt=stack.pop()
        elif op==7:nxt=d.u(at+4)
        elif op==8:return result,True # animation-loop synchronization
        elif op==9:pass # background flash
        elif op==10:nxt=at+20
        elif op==11:
            a,b,c,e,q=[d.u(at+4*i) for i in range(1,6)]
            h=[(w>>23)&7,d.h(at+6)*.003906,d.h(at+8)*.003906,d.h(at+10)*.003906,
               (a>>16)*.003906,w&8191,(w>>20)&7,c>>23,(c>>14)&511,(c>>5)&511,
               e>>23,(e>>18)&31,(w>>13)&127,bool(q&0x1000),((e&1)<<1)|((e&2)>>1)]
            result.append([time,op,h]);nxt=at+24
        elif op in [12,13]:result.append([time,op,[(w>>23)&7,w&8191 if op==12 else (w&65535)*.003906]])
        elif op==14:result.append([time,op,w&0x3ffffff])
        elif op==15:result.append([time,op,0])
        elif op==16:
            sub=(w>>18)&255;nxt=at+(12 if sub in [0,1,2] else 8 if sub in [10,11] else 4)
        elif 17<=op<=25:pass
        else:raise ValueError(f'unknown item command {op} at {at:x}')
        if time>horizon:return result,True
        at=nxt
    raise ValueError('item command stream did not advance')


def item_anim(d, root):
    from tools.native_rig.fobj_reader import Track,decode
    tracks=[]; ends=[]; index=0
    def walk(at):
        nonlocal index
        while at:
            node=index;index+=1;a=d.u(at+8)
            if a:
                ends.append(d.f(a+4));fo=d.u(a+8)
                while fo:
                    length=d.u(fo+4);typ,vf,sf=d.d[fo+12:fo+15];ptr=d.u(fo+16)
                    if typ in [1,2,3,5,6,7,8,9,10]:
                        tracks.append(Track(node,typ,vf,sf,0,d.f(fo+8),length,ptr,decode(d.d[ptr:ptr+length],vf,sf)))
                    fo=d.u(fo)
            walk(d.u(at));at=d.u(at+4)
    if root:walk(root)
    return max(ends,default=0),tracks


def effect_initial_generators(d, model):
    """The synchronous efAsync_Dispatch AnimAll flush, JObj channel 40.

    KEY records include a wait just like CON records. The numeric fighter
    pose reader does not consume KEY waits, so parse these event channels
    explicitly instead of treating their bit patterns as SRT values.
    """
    from tools.native_rig.fobj_reader import read_number, read_varint
    root=d.roots['effCommonDataTable'];found=[]
    def walk(at):
        while at:
            a=d.u(at+8)
            fo=d.u(a+8) if a else 0
            while fo:
                if d.d[fo+12]==40:
                    n=d.u(fo+4);ptr=d.u(fo+16);buf=d.d[ptr:ptr+n]
                    vf=d.d[fo+13];cursor=0;clock=-d.f(fo+8)
                    while cursor<len(buf):
                        word,cursor=read_varint(buf,cursor)
                        assert word&15==6, 'particle channel needs a non-KEY adapter'
                        for _ in range((word>>4)+1):
                            value,cursor=read_number(buf,cursor,vf)
                            bits=struct.unpack('>I',struct.pack('>f',value))[0]
                            if clock==0:found.append((bits&63,(bits>>6)&0xffffff))
                            if cursor<len(buf):
                                wait,cursor=read_varint(buf,cursor);clock+=wait
                fo=d.u(fo)
            walk(d.u(at));at=d.u(at+4)
    walk(d.u(root+8+model*20+8))
    return found


def bake_items(data_root, out, decomp):
    """Item_80267978's article/state lookup, authored item scripts and poses.

    Runtime modifiers are explicitly selected in the shared stage16 sampler.
    Unknown kinds are never assigned a generic projectile radius.
    """
    sys.path.insert(0,str(REPO/'app/backend'))
    from shared.vanilla_extract.vanilla_refs import known_vanilla_iso
    disc=FighterDisc(known_vanilla_iso() or REPO/'app/Super Smash Bros. Melee (USA) (En,Ja) (v1.02).iso')
    symbols={m[0]:(int(m[1],16),int(m[2],16)) for m in re.findall(r'(\w+) = \.[^:]+:0x([0-9A-Fa-f]+); // type:object size:0x([0-9A-Fa-f]+)',(decomp/'config/GALE01/symbols.txt').read_text())}
    enum=(decomp/'src/melee/it/forward.h').read_text().split('typedef enum ItemKind {')[1].split('} ItemKind')[0]
    names=re.findall(r'^\s*(?:/\*.*?\*/\s*)?(It_(?:Kind|PKind)_\w+)\s*,',enum,re.M)
    kinds={name:i for i,name in enumerate(names)}
    articles={}
    co=FighterNumericDat(disc.file('ItCo.dat'));public=co.roots['itPublicData']
    common=co.u(public);common_articles=co.u(public+4)
    for kind in range(kinds['It_Kind_Kuriboh']):articles[kind]=(co,co.u(common_articles+4*kind),'ItCo.dat')
    # ftXX_Init_OnLoad registers these x48 entries; Link/Fox use kind IDs in
    # their special attributes, which also handles Young Link and Falco.
    fixed={'Ss':['Samus_Bomb','Samus_Charge','Samus_Missile','Samus_GBeam'],
           'Pe':['Peach_Explode','Peach_Turnip','Peach_Parasol','Peach_Toad','Peach_ToadSpore'],
           'Gw':['GameWatch_Greenhouse','GameWatch_Manhole','GameWatch_Fire','GameWatch_Parachute','GameWatch_Turtle','GameWatch_Breath','GameWatch_Judge','GameWatch_Panic','GameWatch_Chef','GameWatch_Rescue'],
           'Kb':['Kirby_CBeam','Kirby_Hammer','Unk1','Unk2'],
           'Mr':['Mario_Fire','Mario_Cape'], 'Dr':['DrMario_Vitamin'], 'Lg':['Luigi_Fire'],
           'Mt':['Mewtwo_Disable','Mewtwo_ShadowBall'],
           'Kp':['Koopa_Flame'],'Pp':['IceClimber_Ice','IceClimber_Blizzard','IceClimber_GumStrings'],
           'Sk':['Seak_NeedleThrow','Seak_NeedleHeld','Seak_Vanish','Seak_Chain'],
           'Zd':['Zelda_DinFire','Zelda_DinFire_Explode'],
           'Ys':['Yoshi_EggThrow','Yoshi_Star','Yoshi_EggLay'],
           'Ns':['Ness_PKFire','Ness_PKFire_Flame','Ness_PKFlush','Ness_PKThunder','Ness_PKThunder1','Ness_PKThunder2','Ness_PKThunder3','Ness_PKThunder4','Ness_PKFlush_Explode','Ness_Bat','Ness_Yoyo']}
    for code in ['Fx','Fc','Lk','Cl','Pk','Pc',*fixed]:
        d=FighterNumericDat(disc.file(f'Pl{code}.dat'));root=next(iter(d.roots.values()));items=d.u(root+0x48);attrs=d.u(root+4)
        if code in ['Fx','Fc']:
            entries=[(0,d.u(attrs+0x1c)),(1,d.u(attrs+0x20)),(2 if code=='Fx' else 3,kinds['It_Kind_Fox_Illusion' if code=='Fx' else 'It_Kind_Falco_Phantasm'])]
        elif code in ['Lk','Cl']:entries=[(i,d.u(attrs+off)) for i,off in enumerate([0x48,0x2c,0xbc,0xc,0x10])]
        elif code in ['Pk','Pc']:entries=[(i,d.u(attrs+off)) for i,off in enumerate([0xdc,0x14,0x18])]
        elif code=='Mr':entries=[(0,kinds['It_Kind_Mario_Fire']),(2,kinds['It_Kind_Mario_Cape'])]
        elif code=='Dr':entries=[(1,kinds['It_Kind_DrMario_Vitamin']),(2,kinds['It_Kind_DrMario_Sheet'])]
        else:entries=[(i,kinds['It_Kind_'+name]) for i,name in enumerate(fixed[code]) if 'It_Kind_'+name in kinds]
        for i,kind in entries:articles[kind]=(d,d.u(items+4*i),f'Pl{code}.dat')
    # ftKb_SpecialN_800F16D0 registers copy articles from hat_dynamics, at
    # offset 12 of each copy descriptor (these are not PlKb's x48 array).
    copies={'Mr':{0:'MarioFire'},'Dr':{0:'DrMarioVitamin'},'Lg':{0:'LuigiFire'},
            'Pp':{0:'IceClimberIce'},'Pe':{0:'PeachToad',1:'PeachToadSpore'},
            'Fx':{0:'FoxLaser',1:'FoxBlaster'},'Fc':{3:'FalcoLaser',4:'FalcoBlaster'},
            'Lk':{0:'LinkArrow',1:'LinkBow'},'Cl':{0:'CLinkArrow',1:'CLinkBow'},
            'Mt':{3:'MewtwoShadowBall'},'Ns':{0:'NessPKFlush',1:'NessPKFlush_Explode'},
            'Pk':{0:'PikachuTJolt_Ground',1:'PikachuTJolt_Air'},
            'Pc':{0:'PichuTJolt_Ground',1:'PichuTJolt_Air'},'Ss':{0:'SamusCharge'},
            'Sk':{0:'SeakNeedleThrow',1:'SeakNeedleHeld'},'Kp':{0:'KoopaFlame'},
            'Gw':{5:'GameWatchChef',6:'GameWatchChefPan'},'Ys':{5:'YoshiEggLay'}}
    for code,entries in copies.items():
        filename=f'PlKbCp{code}.dat';d=FighterNumericDat(disc.file(filename));root=next(iter(d.roots.values()))
        for i,name in entries.items():articles[kinds['It_Kind_Kirby_'+name]]=(d,d.u(root+12+4*i),filename)
    (data_root/'items').mkdir(exist_ok=True);summary=[]
    for kind,(d,article,filename) in sorted(articles.items()):
        if not article:continue
        name=names[kind]; base=symbols['it_803F14C4' if kind<43 else 'it_803F3100'][0]
        state_addr=struct.unpack('>I',disc.ram(base+(kind if kind<43 else kind-43)*60,4))[0]
        if not state_addr:continue
        size=next((n for a,n in symbols.values() if a==state_addr),None)
        if size is None:raise ValueError(f'missing item state table {name} {state_addr:x}')
        state_ids=struct.unpack('>'+('iIII'*(size//16)),disc.ram(state_addr,size))[::4]
        attr=d.u(article);states=d.u(article+12);model=d.u(article+16)
        model_error=None
        try:nodes=skeleton_at(d,d.u(model) if model else 0) or [(-1,[0,0,0,1,1,1,0,0,0])]
        except (ValueError,IndexError,struct.error) as e:
            model_error=str(e);nodes=[(-1,[0,0,0,1,1,1,0,0,0])]
        nodes[0]=(-1,[0,0,0,1,1,1,0,0,0])
        moves={};issues=[]
        for anim in sorted(set(state_ids)):
            if anim<0:continue
            try:
                # PK Fire's pillar starts with a relative wait. StateChange
                # calls it_802799E4 immediately (timer 0 -> -1), so its
                # second attack begins at age 8, not 9. Retain the existing
                # age convention of the older item adapters.
                ptr=states+16*anim;cmds,truncated=item_commands(d,d.u(ptr+12),initial_timer=-1 if kind in [67,78,146] else 0)
                if not any(op==11 and h[13] for _,op,h in cmds):
                    moves[anim]={'frames':{},'end':0,'truncated':False};continue
                if model_error:raise ValueError(model_error)
                end,tracks=item_anim(d,d.u(ptr))
                frames={};active={};cursor=0;jolt_joint=[]
                last=max([int(end),*(int(c[0]) for c in cmds)],default=0)
                for frame in range(min(last,600)+1):
                    while cursor<len(cmds) and cmds[cursor][0]<=frame:
                        _,op,h=cmds[cursor];cursor+=1
                        if op==11:active[h[0]]=h.copy()
                        elif op==14:active.pop(h,None)
                        elif op==15:active={}
                        elif op in [12,13] and h[0] in active:active[h[0]][5 if op==12 else 4]=h[1]
                    if not active:continue
                    matrices,_=pose(nodes,[t for t in tracks if t.node!=0],min(frame,end),legacy=False)
                    if kind in [90,92,148,150]:jolt_joint.append(matrices[6][:3,3].tolist())
                    spheres=[]
                    for h in active.values():
                        if not h[13] or h[11] in [8,11]:continue
                        pos=matrices[h[12]]@np.array([*h[1:4],1])
                        spheres.append([h[0],*pos[:3].tolist(),*h[4:12],h[12],h[14]])
                    if spheres:frames[frame]=spheres
                moves[anim]={'frames':frames,'end':last,'truncated':truncated}
                if jolt_joint:moves[anim]['joint6']=jolt_joint
            except (ValueError,IndexError,KeyError,AssertionError,struct.error) as e:issues.append([anim,str(e)])
        special=d.u(article+4)
        # Numeric special parameters are selected by the runtime family below.
        family=('laser' if 'Laser' in name and ('Fox' in name or 'Falco' in name) else
                'fireball' if kind in [48,49,105,130,131,132] else
                'chef' if kind in [122,155] else
                'shadow' if kind in [112,144] else
                'needle' if kind in [79,152] else
                'pkfire' if kind==66 else 'pkpillar' if kind==67 else
                'pkflash' if kind in [68,145] else 'pkexplode' if kind in [78,146] else
                'dinfire' if kind==108 else 'dinexplode' if kind==109 else
                'pkthunder' if kind==69 else 'pktrail' if kind in [70,71,72,73] else
                'thunder' if kind in [81,82] else
                'jolt' if kind in [89,91,147,149] else 'joltair' if kind in [90,92,148,150] else
                'illusion' if name.endswith(('Fox_Illusion','Falco_Phantasm')) else
                'missile' if name.endswith('Samus_Missile') else
                'charge' if name.endswith(('Samus_Charge','SamusCharge','ShadowBall')) else
                'arrow' if name.endswith(('_Arrow','LinkArrow')) else
                'boomerang' if name.endswith('_Boomerang') else
                'turnip' if name.endswith('_Turnip') else
                'bomb' if name.endswith(('Link_Bomb','CLink_Bomb','Samus_Bomb')) else
                'attached' if 'GameWatch_' in name else 'authored')
        special_count={'laser':2,'fireball':4 if kind in [105,132] else 5,'chef':0,'shadow':12,'needle':3,'pkfire':2,'pkpillar':3,'pkflash':11,'pkexplode':5,'dinfire':12,'dinexplode':5,'pkthunder':5,'thunder':3,'jolt':4,'illusion':2,'missile':14,'charge':8,'arrow':9,'boomerang':17,'turnip':1,'bomb':4 if kind==93 else 13}.get(family,0)
        obj={'kind':kind,'name':name,'source':filename,'family':family,'scale':d.f(attr+0x60),
             'states':list(state_ids),'animations':moves,
             'special':[d.f(special+4*i) for i in range(special_count)] if special else [],
             'throwSpeed':d.f(attr+4),'gravity':d.f(attr+0x10),'maxFallSpeed':d.f(attr+0x14),'spawnVy':d.f(attr+0x18),'weight':int(d.f(attr+0x1c)),
             'ecb':[d.f(attr+0x40+4*i) for i in range(4)],
             'velocityDirectionThreshold':co.f(common+0x78)}
        if family=='boomerang':obj['special'][:3]=[d.u(special+4*i) for i in range(3)]
        if kind in [58,59]:obj['special'][:5]=[d.u(special+4*i) for i in range(5)]
        if family=='turnip':
            obj['faceDamage']=[d.u(special+12+8*i) for i in range(d.u(special+4))]
            obj['faceWeights']=[d.u(special+8+8*i) for i in range(d.u(special+4))]
        # Only these native states install ITEM_DROP_UPDATE. Explosions reset
        # xC40 to 1; carry the throw modifier only through their flight state.
        drops={0:[3,4],1:[3,4,5],2:[3],3:[3],4:[5,6],6:[9,10],7:[5],11:[3],12:[3],
               16:[4],17:[3],19:[3],21:[3],22:[3,4],23:[3,4],24:[7,8],
               25:[6],30:[3],34:[3],42:[3],58:[2,3],59:[2,3],99:[3]}
        if kind in drops:obj['dropStates']=drops[kind]
        if family=='fireball':
            obj['bounce']=d.f(attr+0x58)
            if kind in [49,131]:
                # itDrMarioPill_UnkMotion0_Phys selects the common x68
                # spin rate before Item_Phys advances the rotating ECB.
                obj['mapSpin']=[d.f(attr+0xc),co.f(common+0x68),bool(d.d[attr+1]&0x20)]
            # efAlt/efSync: only the synchronous muzzle generator belongs
            # before priority-13 material effects. Bounce effects are queued.
            source={48:('EfMrData.dat',1001),105:('EfLgData.dat',18000),130:('EfKbMr.dat',32000),132:('EfKbLg.dat',37000)}.get(kind)
            if source:
                effect=FighterNumericDat(disc.file(source[0]));eb=effect.u(0)
                version=effect.u(eb)>>16;first=effect.u(eb+4) if version else 0
                ep=eb+effect.u(eb+(12 if version else 8)+4*(source[1]-first))
                obj['spawnDraws']=int(not(effect.u(ep+8)&0x100) and effect.f(ep+40)>=0)
                ep=eb+effect.u(eb+(12 if version else 8)+4*(source[1]+2-first))
                obj['bounceDraws']=int(not(effect.u(ep+8)&0x100) and effect.f(ep+40)>=0)
            else:obj['spawnDraws']=1;obj['bounceDraws']=0 # ftMr_SpecialN_VitaminRandom
        if family=='chef':
            obj['hitlag']=[co.f(common+0xb8),co.f(common+0xbc)]
            obj['special']=[d.f(special+4*i) for i in range(1,4)]
            obj['trajectories']=[[d.f(special+16+20*i+4*j) for j in range(5)] for i in range(5)]
        if family=='shadow':
            obj['special'][8]=d.u(special+0x20)
            # Physics replaces the grandchild translation with the random
            # offset. Its parent retains this authored translation.
            obj['oscillatorParent']=nodes[1][1][6:9]
        if family in ['pkthunder','pktrail']:
            # The loop repeats the same root-centered attack. Trail model
            # stretch/rotation cannot move it, and C never scales its radius.
            for move in moves.values():
                assert all(h[1:4]==[0,0,0] and h[12]==0 for hs in move['frames'].values() for h in hs)
                assert all(hs==move['frames'][0] for hs in move['frames'].values())
                move.update(frames={0:move['frames'][0]},end=0,truncated=False)
        if family=='pkthunder':
            # efSync 0x4EE creates model effect 10000. efLib_Create queues
            # its animation for priority 15; it has no synchronous Rand call.
            obj['spawnDraws']=0
        if family in ['shadow','needle','thunder','jolt']:
            effect_file='EfPkData.dat' if family=='jolt' and kind in [89,91] else 'EfCoData.dat'
            effect_id={'shadow':0x43,'needle':0x6a,'thunder':0x24c,'jolt':7000,'pkthunder':10000}[family]
            if family=='pkthunder':effect_file='EfNsData.dat'
            if family=='jolt' and kind in [147,149]:effect_file='EfKbPk.dat';effect_id=36000
            effect=FighterNumericDat(disc.file(effect_file));eb=effect.u(0)
            version=effect.u(eb)>>16;first=effect.u(eb+4) if version else 0
            ep=eb+effect.u(eb+(12 if version else 8)+4*(effect_id-first))
            obj['mapDraws' if family=='shadow' else 'spawnDraws']=int(not(effect.u(ep+8)&0x100) and effect.f(ep+40)>=0)
            if family=='thunder':
                ep=eb+effect.u(eb+(12 if version else 8)+4*(0x19-first))
                obj['mapDraws']=int(not(effect.u(ep+8)&0x100) and effect.f(ep+40)>=0)
        (data_root/f'items/{kind}.json').write_text(compact(obj)+'\n',encoding='utf8',newline='\n')
        summary.append({'kind':kind,'name':name,'states':state_ids,'issues':issues,'frames':sum(len(m['frames']) for m in moves.values())})
    (out/'items-extraction.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf8')
    (data_root/'items/index.json').write_text(compact([row['kind'] for row in summary])+'\n',encoding='utf8',newline='\n')
    manifest=data_root.parent/'stageData.js'
    manifest.write_text(re.sub(r'export const ITEM_IDS = Object.freeze\(\[[^\n]+\]\)',
        'export const ITEM_IDS = Object.freeze('+compact([row['kind'] for row in summary])+')',manifest.read_text()),encoding='utf8',newline='\n')
    print(compact(summary))

def fighter_value(events, frame):
    """FOBJ value after consuming keys at the requested frame.

    FObjUpdateAnim selects p1 at a CON endpoint; zero-duration keys at that
    time are consumed too. The older Marth projection is pinned separately.
    """
    p0=p1=d0=d1=t0=t1=0.;last=0;first=True
    for event in events:
        op=event['op']
        if op==5:
            d0,d1=d1,event['tan'];last=op;continue
        if first:
            p1,d1,t1=event['value'],event['tan'],float(event['frame'])
            last,first=op,False
            if frame<t1:return p1
            continue
        p0,p1=p1,event['value'];t0,t1=t1,float(event['frame'])
        if op==4:d0,d1=d1,event['tan']
        elif op==3 or last!=5:d0,d1=d1,0.
        if frame<t1:
            u=(frame-t0)/(t1-t0)
            if last in [1,6]:return p0
            if last==2:return p0+(p1-p0)*u
            return ((2*u**3-3*u**2+1)*p0+(u**3-2*u**2+u)*(t1-t0)*d0
                    +(-2*u**3+3*u**2)*p1+(u**3-u**2)*(t1-t0)*d1)
        last=op
    return p1


def fighter_extent(events):
    """Absolute bound including between-key Hermite extrema.

    A cubic lies in the convex hull of its Bezier controls. SRT animation
    blending also keeps translation/scale inside their endpoint bounds.
    """
    bound=0.;p0=p1=d0=d1=t0=t1=0.;last=0;first=True
    for event in events:
        op=event['op']
        if op==5:d0,d1=d1,event['tan'];last=op;continue
        if first:
            p1,d1,t1=event['value'],event['tan'],float(event['frame'])
            bound=max(bound,abs(p1));last,first=op,False;continue
        p0,p1=p1,event['value'];t0,t1=t1,float(event['frame'])
        if op==4:d0,d1=d1,event['tan']
        elif op==3 or last!=5:d0,d1=d1,0.
        bound=max(bound,abs(p0),abs(p1))
        if last not in [1,2,6]:
            bound=max(bound,abs(p0+(t1-t0)*d0/3),abs(p1-(t1-t0)*d1/3))
        last=op
    return bound

def pose(nodes, tracks, frame, remove_trans=None, legacy=False):
    from tools.native_rig.fobj_reader import native_value
    values = [v[:] for _,v in nodes]
    for tr in tracks:
        if tr.type in [1,2,3,5,6,7,8,9,10]:
            ix = tr.type-1 if tr.type<=3 else tr.type-5 if tr.type>=8 else tr.type+1
            values[tr.node][ix] = (native_value if legacy else fighter_value)(tr.events,frame-tr.start)
    if remove_trans is not None:
        # ftAnim_8006E054 transfers TransN to fighter motion, then clears its
        # local translation. Slippi already records the resulting root pos.
        values[remove_trans][6:] = [0., 0., 0.]
    matrices = []
    for i,(parent,_) in enumerate(nodes):
        rx,ry,rz,sx,sy,sz,x,y,z = values[i]
        cx,cy,cz = math.cos(rx),math.cos(ry),math.cos(rz)
        ax,ay,az = math.sin(rx),math.sin(ry),math.sin(rz)
        m=np.array([[cz*cy,cz*ay*ax-az*cx,cz*ay*cx+az*ax,x],[az*cy,az*ay*ax+cz*cx,az*ay*cx-cz*ax,y],[-ay,cy*ax,cy*cx,z],[0,0,0,1.]])
        m[:3,:3]*=np.array([sx,sy,sz])[None,:]
        matrices.append(m if parent<0 else matrices[parent]@m)
    return matrices, values


def missile_blend(nodes, tracks, start, duration):
    """ftAnim_8006E9B4 + lb_8000C490, known Luigi launch -> flight history.

    ChangeMotionState evaluates start-1 and start on entry. Primary SRTs
    retain the launch pose; secondary SRTs advance the requested animation.
    """
    def quat(v):
        x,y,z=[a*.5 for a in v[:3]];sx,sy,sz=map(math.sin,[x,y,z]);cx,cy,cz=map(math.cos,[x,y,z])
        return np.array([sx*cy*cz-cx*sy*sz,cx*sy*cz+sx*cy*sz,cx*cy*sz-sx*sy*cz,cx*cy*cz+sx*sy*sz])
    _,current=pose(nodes,tracks,start);qs=[quat(v) for v in current];result={}
    for tick,frame in enumerate(range(start-1,start+duration-1),1):
        _,target=pose(nodes,tracks,frame);t=1/(duration-tick+1);mats=[]
        for k,((parent,_),v) in enumerate(zip(nodes,target)):
            q=quat(v);old=qs[k];dot=float(q@old)
            if dot<0:old=-old;dot=-dot
            angle=math.acos(min(1,dot))
            qs[k]=q*t+old*(1-t) if angle<1e-8 else (q*math.sin(t*angle)+old*math.sin((1-t)*angle))/math.sin(angle)
            current[k][3:]=[a*t+b*(1-t) for a,b in zip(v[3:],current[k][3:])]
            x,y,z,w=qs[k];m=np.eye(4)
            m[:3,:3]=[[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],[2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],[2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]]
            m[:3,:3]*=np.array(current[k][3:6])[None,:];m[:3,3]=current[k][6:]
            mats.append(m if parent<0 else mats[parent]@m)
        if frame>=start:result[frame]=mats
    return result

def bake_fighters(data_root, out, decomp, cids=None):
    """Regenerate numeric vanilla attributes/attacks/ECBs from a read-only ISO.

    PlCo supplies part mappings; PlXX supplies common attributes/subactions;
    PlXXAJ and a default costume supply posed bones. No Nintendo binaries are
    written. Copy costumes supply their replacement skeletons explicitly.
    """
    sys.path.insert(0, str(REPO / 'app/backend'))
    from shared.vanilla_extract.vanilla_refs import known_vanilla_iso
    from vault.echo.subactions import FighterDat
    from tools.native_rig.fobj_reader import read_figatree
    iso=known_vanilla_iso() or REPO/'app/Super Smash Bros. Melee (USA) (En,Ja) (v1.02).iso'
    disc=FighterDisc(iso)
    # it_80270E30's hit-effect dispatch, before Kingdom's priority-14 respawn
    # draw. hsd_8039F05C draws once iff !(kind & 0x100) && random >= 0.
    # Particle updates are later; their commands do not belong to this prefix.
    effects=FighterNumericDat(disc.file('EfCoData.dat')); base=effects.u(0)
    version=effects.u(base)>>16; first=effects.u(base+4) if version else 0
    def generator_draws(effect):
        at=base+effects.u(base+(12 if version else 8)+4*(effect-first))
        return int(not(effects.u(at+8)&0x100) and effects.f(at+40)>=0)
    # GFX 1021 -> efAsync model3 -> immediate AnimAll -> generators8/266.
    # Generator266 consumes one Randf before Chef chooses its trajectory.
    chef_generators=effect_initial_generators(effects,3)
    assert all(bank==0 for bank,_ in chef_generators)
    chef_draws=sum(generator_draws(gen) for _,gen in chef_generators)
    path=data_root/'stageSim/19.json'; kingdom=json.loads(path.read_text())
    # ityaku spawns It_PKind_Random (160); Item_802674AC assigns hold_kind 3.
    # Thus it_80270E30 always takes its ordinary Ef_Id_Unk1000 branch, NOT
    # the element-specific dispatch reserved for hold_kind 4/6. Its Randi(8)
    # happens before all priority-14 material callbacks.
    kingdom['hitEffectDraws']=[1]*17
    kingdom['breakEffectDraws']=generator_draws(476)
    path.write_text(compact(kingdom)+'\n',encoding='utf8',newline='\n')
    symbols={m[0]:(int(m[1],16),int(m[2],16)) for m in re.findall(r'(\w+) = \.[^:]+:0x([0-9A-Fa-f]+); // type:object size:0x([0-9A-Fa-f]+)', (decomp/'config/GALE01/symbols.txt').read_text())}
    common=disc.ram(symbols['ftData_MotionStateList'][0],341*32)
    special=struct.unpack('>33I',disc.ram(symbols['ftData_CharacterStateTables'][0],33*4))
    plco=FighterNumericDat(disc.file('PlCo.dat')); parts=plco.u(plco.roots['ftLoadCommonData']+16)
    item_throws=plco.u(plco.roots['ftLoadCommonData']+4)
    weights=json.loads((data_root/'stageSim/24.json').read_text())['weights']
    (data_root/'fighters').mkdir(exist_ok=True)
    summary=[]
    for cid in cids if cids is not None else range(27):
        code='Mr Fx Ca Dk Kb Kp Lk Sk Ns Pe Pp Nn Pk Ss Ys Pr Mt Lg Ms Zd Cl Dr Fc Pc Gw Gn Fe'.split()[cid]; fd=FighterDat(disc.file(f'Pl{code}.dat'))
        attrs=fd.dat.ptr(fd.ft_root); weight=fd.dat.f32(attrs+0x88); scale=fd.dat.f32(attrs+0x8c)
        assert weight==weights[cid], (cid,weight,weights[cid])
        # ftData_80085A14 populates x14 from Nana's own nonempty AJ. Only
        # actions without animation bytes borrow Popo (80085FD4 / 80086060).
        model=f'Pl{code}Nr.dat'
        if model not in disc.entries:
            model=next(n for n in disc.entries if re.fullmatch(f'Pl{code}[A-Z][a-z].dat',n))
        nodes=skeleton(disc.file(model)); aj=disc.file(f'Pl{code}AJ.dat') if f'Pl{code}AJ.dat' in disc.entries else b''
        # ftParts_SetupParts reserves holes listed in PlCo pData[5]. Kirby's
        # raw costume has 46 nodes but the fighter parts array has 61 slots.
        missing_table=plco.u(plco.roots['ftLoadCommonData']+20)
        missing=plco.u(missing_table+cid*4)
        holes={plco.d[plco.u(missing)+4*i] for i in range(plco.u(missing+4))} if missing else set()
        joint_indices={}; node=0; part=0
        while node<len(nodes):
            if part not in holes:joint_indices[part]=node;node+=1
            part+=1
        variants={}
        if cid==4:
            for copy in ['Pr','Mt']:
                hat=FighterNumericDat(disc.file(f'PlKbCp{copy}.dat'))
                mask=hat.u(next(iter(hat.roots.values()))+16)
                filled={plco.d[plco.u(missing)+4*i] for i in range(plco.u(missing+4)) if mask&(1<<i)}
                variant=skeleton(disc.file(f'PlKbNrCp{copy}.dat'))
                mapping={};node=0;part=0
                while node<len(variant):
                    if part not in holes-filled:mapping[part]=node;node+=1
                    part+=1
                variants[copy]=(variant,mapping)
        other=FighterDat(disc.file('PlPp.dat')) if cid==11 else None
        otheraj=disc.file('PlPpAJ.dat') if cid==11 else None
        raw=FighterNumericDat(disc.file(f'Pl{code}.dat')); cp=raw.u(fd.ft_root+0x44); bones=[joint_indices[raw.h(cp+2*i)] for i in range(6)]
        partmap=plco.u(plco.u(parts+cid*4)+4)
        bone_map=list(plco.d[partmap:partmap+54])
        address=special[cid]; size=next(n for a,n in symbols.values() if a==address)
        table=common+disc.ram(address,size)
        indices=[struct.unpack_from('>i',table,i)[0] for i in range(0,len(table),32)]
        # These common states select their submotion in their entry callback.
        # Wait1 is the initial ordinary idle; other idle variants stay gated.
        for state,name in [(14,'Wait1')]:
            indices[state]=next(a.index for a in (other or fd).actions if a.motion in [name,'Wait'])
        held_nodes=None;grip_nodes=set()
        if cid in [6,9,20]:
            # Fighter_OnItemPickup -> ApplyPartAnim slot 1. The grip freezes
            # its animated joints (flags_b5) over the ordinary body motion.
            # Unkeyed grip channels retain the initial Wait secondary pose;
            # RHaveN additionally cancels model scale (8007F6A4).
            wait=fd.actions[indices[14]]
            clip=FighterNumericDat(aj[wait.anim_offset:wait.anim_offset+wait.anim_size])
            _,_,wait_tracks,*_=read_figatree(clip.d,next(iter(clip.roots.values())))
            _,wait_values=pose(nodes,wait_tracks,0)
            article=raw.u(raw.u(fd.ft_root+0x48)+(4 if cid==9 else 0))
            grip_kind=raw.d[raw.u(article)]&7
            grip=raw.u(raw.u(fd.ft_root+0x1c)+4);start=raw.h(grip)
            _,grip_tracks=item_anim(raw,raw.u(raw.u(grip+8)+4*{1:1,2:0,3:2,4:3}[grip_kind]))
            grip_nodes={joint_indices[start+t.node] for t in grip_tracks}
            held_nodes=[(parent,wait_values[k][:] if k in grip_nodes else values[:]) for k,(parent,values) in enumerate(nodes)]
            hold=joint_indices[raw.d[raw.u(fd.ft_root+8)+16]]
            held_nodes[hold][1][3:6]=[1/scale]*3
            for tr in grip_tracks:
                ix=tr.type-1 if tr.type<=3 else tr.type-5 if tr.type>=8 else tr.type+1
                held_nodes[joint_indices[start+tr.node]][1][ix]=fighter_value(tr.events,-tr.start)
        hitboxes={}; ecbs={}; motions={}; issues=[]; extracted={}
        # Per-bone local SRT bounds across common poses provide a conservative
        # ECB radius even during fractional walks and blended Fall/FallF/FallB.
        extents=[[abs(x) for x in v] for _,v in nodes]
        for state,index in enumerate(indices):
            if index<0 or index>=len(fd.actions): continue
            owner=other if other and not fd.actions[index].anim_size else fd
            a=owner.actions[index]; animbytes=otheraj if owner is other else aj
            if not a.anim_size or not a.motion: continue
            motions[state]=a.motion
            if index not in extracted:
                try:
                    clip=FighterNumericDat(animbytes[a.anim_offset:a.anim_offset+a.anim_size])
                    end,counts,tracks,*_=read_figatree(clip.d,next(iter(clip.roots.values())))
                    # 80085FD4 substitutes Nana's animation only. ChangeMotionState
                    # still installs xC (commands) and x10 (flags) from her own
                    # action entry rather than the borrowed animation entry.
                    cmds=commands(fd,fd.actions[index],end,legacy=cid==18 and state<341) if 44<=state<=74 or 94<=state<=119 or state>=341 or state in [187,195,217,219,220,221,222,256,257] else []
                    if cid==17 and state in [345,351]:
                        # SpecialSFly_Enter keeps the launch hitbox while
                        # changing only its animation/command stream.
                        cmds=sorted(cmds+[c for c in commands(fd,fd.actions[indices[347]],end) if c[1]==11],key=lambda c:c[0])
                    if cid in [12,23] and state in [345,350]:
                        # Skull Bash changes to its flight stream with SkipHit.
                        cmds=sorted(cmds+[c for c in commands(fd,fd.actions[indices[347]],end) if c[1]==11],key=lambda c:c[0])
                    move_nodes,move_joints=variants.get(a.motion[:2],(nodes,joint_indices))
                    if cid==4 and a.motion.startswith('Fc'):
                        # ftAnim_8006FCE4 consumes conditional FigaTree nodes
                        # selected by x594_bits even when that live body part
                        # is absent. Falco's tree has 48 nodes, Kirby's body 46.
                        masks={plco.d[plco.u(missing)+4*i]:1<<i for i in range(plco.u(missing+4))}
                        mapping={};part=0
                        for node in range(len(counts)):
                            while masks.get(part,0) and not(masks[part] & (a.flags>>9)&0x1fff):part+=1
                            if part in move_joints:mapping[node]=move_joints[part]
                            part+=1
                        tracks=[tr for tr in tracks if tr.node in mapping]
                        for tr in tracks:tr.node=mapping[tr.node]
                    missile_poses={}
                    if cid==17 and state in [345,351]:
                        blend=raw.d[raw.u(fd.ft_root+16)+2*index]
                        start=next(t for t,op,h in cmds if op==11)
                        missile_poses=missile_blend(move_nodes,tracks,start,blend)
                    # ECB data is needed for head collisions and respawn clearance;
                    # keep all authored common poses, not just Marth's jump poses.
                    # Copy costumes replace Kirby's hierarchy. Resolve the
                    # six common ECB part IDs through the current costume;
                    # its node numbers must not index base-costume extents.
                    move_bones=[move_joints[raw.h(cp+2*i)] for i in range(6)]
                    needs_ecb=max(move_bones)<len(move_nodes) and any(k==index and (14<=s<=91 or s>=341 or s in [250,252,253,254,255,256,257]) for s,k in enumerate(indices))
                    if needs_ecb and a.motion[:2] not in variants:
                        for tr in tracks:
                            if tr.type not in [5,6,7,8,9,10]:continue
                            ix=tr.type-5 if tr.type>=8 else tr.type+1
                            if ix>=6 and tr.node==joint_indices[bone_map[1]] and fd.actions[index].flags&0x80000000:continue
                            extents[tr.node][ix]=max(extents[tr.node][ix],fighter_extent(tr.events))
                    frames={}; elements={}; ecb=[]; active={}; cursor=0;spawns=[];hold_frames=[];yoyo=[];tether=[];chain_hand=[];runtime_bones={}
                    aircatch=cid in [6,13,20] and a.motion=='AirCatch'
                    hold=raw.d[raw.u(fd.ft_root+8)+16] if cid in [6,9,20] else None
                    laser_move=cid in [1,22] and a.motion in ['SpecialNLoop','SpecialAirNLoop'] or cid==4 and a.motion in ['FxSpecialNLoop','FxSpecialAirNLoop','FcSpecialNLoop','FcSpecialAirNLoop']
                    laser_frames={int(t) for t,op,h in cmds if laser_move and op==19 and h['flag']==2 and h['value']}
                    fire_kind=({0:48,17:105,21:49}.get(cid) if a.motion in ['SpecialN','SpecialAirN'] else
                               {'MrSpecialN':130,'MrSpecialAirN':130,'LgSpecialN':132,'LgSpecialAirN':132,'DrSpecialN':131,'DrSpecialAirN':131}.get(a.motion) if cid==4 else None)
                    fire_frames={int(t) for t,op,h in cmds if fire_kind is not None and op==24 and h['value']==0}
                    chef_kind=122 if cid==24 and state in [353,354] else 155 if cid==4 and a.motion in ['GwSpecialN','GwSpecialAirN'] else None
                    chef_frames={int(t) for t,op,h in cmds if chef_kind is not None and op==19 and h['flag']==0 and h['value']}
                    shadow_kind=112 if cid==16 and a.motion.startswith('Special') else 144 if cid==4 and a.motion.startswith('MtSpecial') else None
                    shadow_frames={int(t):h['flag'] for t,op,h in cmds if shadow_kind is not None and op==19 and h['flag'] in [1,3] and h['value']==1 and ('NStart' in a.motion or 'NLoop' in a.motion or 'NEnd' in a.motion)}
                    pkfire_frames={int(t) for t,op,h in cmds if cid==8 and a.motion in ['SpecialS','SpecialAirS'] and op==24 and h['value']==0}
                    pkflash_kind=68 if cid==8 and state in [349,353] else 145 if cid==4 and state in [436,440] else None
                    pkflash_frames={0} if pkflash_kind is not None else set()
                    samus_frames={int(t) for t,op,h in cmds if cid==13 and state in [349,350,351,352,355,356] and op==24 and h['value']==0}
                    if cid==13 and state in [346,348]:samus_frames.add(1)
                    if cid==4 and a.motion in ['SsSpecialN','SsSpecialAirN']:
                        samus_frames={max(1,int(t)) for t,op,h in cmds if op==19 and h['flag']==1 and h['value']==1}
                    link_frames={int(t) for t,op,h in cmds if cid in [6,20] and a.motion in ['SpecialS1','SpecialAirS1'] and op==19 and h['flag']==0 and h['value']}
                    if cid in [6,20] and a.motion in ['SpecialNEnd','SpecialAirNEnd']:link_frames.add(0)
                    if cid==4 and a.motion in ['LkSpecialNEnd','LkSpecialAirNEnd','ClSpecialNEnd','ClSpecialAirNEnd']:
                        link_frames={int(t) for t,op,h in cmds if op==19 and h['flag']==1 and h['value']==1}
                    throw_frames={int(t) for t,op,h in cmds if cid in [6,9,20] and 94<=state<=119 and op==20 and h['enabled']==0}
                    for frame in range(int(end)+1):
                        while cursor<len(cmds) and cmds[cursor][0]<=frame:
                            _,op,h=cmds[cursor];cursor+=1
                            if op==11:active[h['id']]=dict(h)
                            elif op==16:active={}
                            elif op==15:active.pop(h.get('hitbox_id',h.get('id')) if cid==18 else h['index'],None)
                            elif cid!=18 and op in [12,13] and h['hitbox_id'] in active:
                                key='damage' if op==12 else 'size';active[h['hitbox_id']][key]=h[key]
                        if not active and not needs_ecb and hold is None and frame not in laser_frames and frame not in fire_frames and frame not in chef_frames and frame not in shadow_frames and frame not in pkfire_frames and frame not in pkflash_frames and frame not in samus_frames and frame not in link_frames and frame not in throw_frames and not (state==250 and frame==0):continue
                        # Keep the validated Marth projection unchanged. Other
                        # characters include root-driven normals (Fox/Bowser/
                        # Puff fsmash), whose translation must not be added twice.
                        trans = move_joints[bone_map[1]] if cid != 18 and fd.actions[index].flags & 0x80000000 else None
                        matrices,values=pose(move_nodes,tracks,frame,remove_trans=trans,legacy=cid==18)
                        if cid==7 and 349<=state<=354:
                            bone=matrices[move_joints[26]]
                            chain_hand.append(((bone[:3,3]+bone[:3,:3]@np.array([0,0,.1]))*scale).tolist())
                        if aircatch:
                            # AirCatch appends FighterBone[139] at runtime.
                            # Export its ordinary attachment pose, not a fake
                            # costume joint. Link's offset is local +Z six;
                            # Samus attaches directly to ThrowN.
                            bone=matrices[move_joints[bone_map[49] if cid!=13 else 51]]
                            # Fighter matrices scale translation by the DAT
                            # model factor; their attachment basis uses the
                            # independent x34_scale (one in vanilla VS).
                            tip=bone[:3,3]*scale+bone[:3,:3]@np.array([0,0,6 if cid!=13 else 0])
                            tether.append(tip.tolist())
                        if frame in missile_poses:matrices=missile_poses[frame]
                        if cid==8 and a.motion in ['AttackHi4','AttackLw4']:
                            yoyo.append([*(matrices[move_joints[61]][:3,3]*scale).tolist(),*(matrices[move_joints[2]][:3,3]*scale).tolist()])
                        if hold is not None:
                            held_matrices,_=pose(held_nodes,[t for t in tracks if t.node not in grip_nodes],frame,remove_trans=trans)
                            hold_frames.append((held_matrices[move_joints[hold]][:3,3]*scale).tolist())
                        if frame in laser_frames:
                            bone=matrices[move_joints[44 if cid==4 else bone_map[49]]]
                            # HSD_MtxSRT compensates inherited scale in the basis;
                            # joint translations inherit fighter scale, offsets do not.
                            pos=bone[:3,3]*scale+bone[:3,:3]@np.array([0,1.45,5.016] if cid==4 else [0,1.2325000762939453,4.263599872589111])
                            da=raw.u(fd.ft_root+4)+(0x220 if a.motion.startswith('Fx') else 0x244 if a.motion.startswith('Fc') else 0);angle=raw.f(da+0x10);speed=raw.f(da+0x14)
                            spawns.append({'frame':frame,'kind':raw.u(da+0x1c),'pos':pos.tolist(),'velocity':[speed*math.cos(angle),speed*math.sin(angle)],'phase':1})
                        if frame in fire_frames:
                            bone=matrices[move_joints[bone_map[21 if cid==4 else 23]]]
                            spawns.append({'frame':frame,'kind':fire_kind,'pos':(bone[:3,3]*scale).tolist(),'phase':9})
                        if frame in chef_frames:
                            bone=matrices[move_joints[bone_map[31]]]
                            # LThumbNb retains the model scale in its basis; unlike
                            # RHaveN/RThumbNa it has no inverse-scale item grip.
                            pos=(bone[:3,3]+bone[:3,:3]@np.array([2.5,6.5,0]))*scale
                            spawns.append({'frame':frame,'kind':chef_kind,'pos':pos.tolist(),'phase':9,'beforeDraws':chef_draws})
                        if cid==4 and chef_kind is not None and frame<=1:
                            # fn_8010CFB0 creates the pan at LThumbNb in
                            # accessory4. Its map callback never updates
                            # the default spawn CollData rectangle.
                            bone=matrices[move_joints[bone_map[31]]]
                            spawns.append({'frame':frame,'kind':156,'pos':(bone[:3,3]*scale).tolist(),'phase':9,'held':True})
                        if frame in shadow_frames:
                            bone=matrices[move_joints[39 if cid==4 else 35]]
                            # RShoulderN / Kirby RHandN retain model scale;
                            # unlike RHaveN, their local offset scales too.
                            pos=(bone[:3,3]+bone[:3,:3]@np.array([0,0,2]))*scale
                            spawns.append({'frame':frame,'kind':shadow_kind,'pos':pos.tolist(),'detachPos':(bone[:3,3]*scale).tolist(),'phase':1,'held':shadow_frames[frame]==3})
                        if frame in pkfire_frames:
                            da=raw.u(fd.ft_root+4);air='Air' in a.motion
                            pos=matrices[move_joints[42]][:3,3]*scale+np.array([0,raw.f(da+0x34),raw.f(da+0x30)])
                            angle=raw.f(da+(0x20 if air else 0x28));speed=raw.f(da+(0x24 if air else 0x2c))
                            spawns.append({'frame':frame,'kind':66,'pos':pos.tolist(),'velocity':[speed*math.cos(angle),speed*math.sin(angle)],'phase':9})
                        if frame in pkflash_frames:
                            # The final offset uses Fighter.x34_scale, not
                            # co_attrs.model_scaling (Kirby's latter is .92).
                            pos=matrices[move_joints[5 if cid==4 else 24]][:3,3]*scale+np.array([0,3 if cid==4 else 3*scale,0])
                            spawns.append({'frame':0,'kind':pkflash_kind,'pos':pos.tolist(),'phase':1})
                        if cid==8 and state in [359,363] and frame==0:
                            spawns.append({'frame':0,'kind':69,'pos':(matrices[move_joints[24]][:3,3]*scale).tolist(),'phase':1})
                        if frame in link_frames:
                            arrow=a.motion.endswith('NEnd')
                            bone=matrices[move_joints[44 if cid==4 else bone_map[49 if arrow else 31]]]
                            pos=bone[:3,3]*scale
                            if not arrow:
                                # it_80273B50: hold_kind 8 releases relative to
                                # the negated item attachment joint translation.
                                # Boomerang PickedUp installs animation 0 at 0.
                                article=raw.u(raw.u(fd.ft_root+0x48)+4)
                                article_model=raw.u(article+16);attach=raw.u(article_model+8)
                                _,item_tracks=item_anim(raw,raw.u(raw.u(article+12)))
                                _,item_values=pose(skeleton_at(raw,raw.u(article_model)),item_tracks,0)
                                pos-=bone[:3,:3]@np.array(item_values[attach][6:9])*scale
                            kind=(140 if a.motion.startswith('Lk') else 141) if cid==4 else (64 if cid==6 else 65) if arrow else (60 if cid==6 else 61)
                            spawns.append({'frame':frame,'kind':kind,'pos':pos.tolist(),'phase':5 if arrow else 9})
                        if frame in throw_frames:
                            hold=raw.d[raw.u(fd.ft_root+8)+16]
                            bone=held_matrices[move_joints[hold]]
                            pos=bone[:3,3]*scale
                            article=raw.u(raw.u(fd.ft_root+0x48)+(4 if cid==9 else 0))
                            article_model=raw.u(article+16);attach=raw.u(article_model+8)
                            item_nodes=skeleton_at(raw,raw.u(article_model))
                            # it_80273748 resets the item model, then applies
                            # the negated attachment translation in hand space.
                            pos-=bone[:3,:3]@np.array(item_nodes[attach][1][6:9])*scale
                            flag=next((h['value'] for t,op,h in reversed(cmds) if t<=frame and op==19 and h['flag']==0),0)
                            velocity=plco.f(item_throws+12*(state-94))*fd.dat.f32(attrs+0xb0)*(.01*((flag>>12)&1023) if flag else 1)
                            angle=plco.f(item_throws+12*(state-94)+4)
                            if flag and flag&4095!=361:angle=math.radians((flag&4095)-4096 if flag&2048 else flag&4095)
                            spawns.append({'frame':frame,'kind':'held','pos':pos.tolist(),'velocity':[velocity*math.cos(angle),velocity*math.sin(angle)],'phase':9})
                        if frame in samus_frames:
                            da=raw.u(fd.ft_root+4)
                            if cid==4:
                                pos=matrices[move_joints[44]][:3,3]*scale
                                spawns.append({'frame':frame,'kind':151,'pos':pos.tolist(),'phase':1})
                            elif state in [349,350,351,352]:
                                pos=matrices[move_joints[56]][:3,3]*scale;pos[2]+=raw.f(da+0x34)
                                spawns.append({'frame':frame,'kind':95,'state':int(state in [350,352]),'pos':pos.tolist(),'phase':9})
                            elif state in [346,348]:
                                pos=matrices[move_joints[51]][:3,3]*scale
                                spawns.append({'frame':frame,'kind':94,'pos':pos.tolist(),'phase':1})
                            else:
                                pos=matrices[move_joints[0]][:3,3]*scale+np.array([raw.f(da+0x7c),raw.f(da+0x78),raw.f(da+0x74)])
                                spawns.append({'frame':frame,'kind':93,'state':1,'pos':pos.tolist(),'phase':9})
                        if needs_ecb:
                            points=np.array([matrices[b][:3,3] for b in move_bones])*scale
                            ecb.append([float(points[:,2].min()),float(points[:,2].max()),float(points[:,1].min()),float(points[:,1].max())])
                        if not active:continue
                        spheres=[];els=[]
                        for h in sorted(active.values(),key=lambda h:h['id']):
                            runtime=aircatch and h['bone']==139 and not h['use_common_bone_ids']
                            bone=move_joints[bone_map[h['bone']] if h['use_common_bone_ids'] else h['bone']] if not runtime else 0
                            # ftAnim_8006FA58/FB88 always apply 8007F6A4 to
                            # ft_data.x8.x10 (RHaveN): its local scale cancels
                            # model_scaling, including Cape's authored hitbox.
                            # Other attack bones retain the model scale.
                            offset=np.array([h['z_offset']*.003906,h['y_offset']*.003906,h['x_offset']*.003906,1])
                            pos=matrices[bone]@offset
                            pos[:3]*=scale
                            if runtime:
                                assert not any(offset[:3]), 'tether offset needs oriented runtime matrix'
                                pos[:3]=0;runtime_bones[h['id']]=139
                            if cid!=18 and bone==move_joints.get(raw.d[raw.u(fd.ft_root+8)+16]):
                                pos[:3]=matrices[bone][:3,3]*scale+matrices[bone][:3,:3]@offset[:3]
                            spheres.append([h['id'],*pos[:3].tolist(),h['size']*.003906,h['damage'],h['hit_group'],h['angle'],h['knockback_growth'],h['weight_set_knockback'],h['base_knockback']])
                            els.append([h['id'],h['element'],h['item_hit_interaction'],h['only_hit_grabbed_fighter'],h.get('hit_grounded_fighters',1)+2*h.get('hit_aerial_fighters',1)])
                        frames[frame]=spheres;elements[frame]=els
                    move={'motion':a.motion,'frames':frames,'elements':elements,'end':end}
                    if aircatch:
                        da=raw.u(fd.ft_root+4);article=raw.u(raw.u(fd.ft_root+0x48)+(3 if cid==13 else 2)*4);ta=raw.u(article+4)
                        move['runtimeBones']=runtime_bones
                        move['tether']={'attach':tether,'launch':raw.u(da+(0xc0 if cid==13 else 0xa8)),
                                        'kind':96 if cid==13 else raw.u(da+0xbc),
                                        # AirCatch reads TetherAttributes+0x40:
                                        # it_802B75FC writes x18 * air coefficient.
                                        'speed':float(np.float32(raw.f(ta+0x18)*raw.f(ta+(0x60 if cid==13 else 0x50)))),
                                        'segment':raw.f(ta+0x10),
                                        'count':int(raw.u(ta+0xc)*raw.f(ta+(0x60 if cid==13 else 0x50)))}
                        if cid==13:
                            move['tether'].update(minimum=raw.f(ta+0x14),retract=raw.u(da+0xc4),mapRadius=1.5)
                    if cid in [12,23] and state in [361,365]:
                        # The animation loops, but its command stream does
                        # not restart. procCollPos flushes the two generators.
                        move['thunderHit']=[next(t for t,op,h in cmds if op==16),
                                            sum(generator_draws({0x412:0x13,0x407:0x3c}[h['gfx_id']]) for t,op,h in cmds if t==0 and op==10 and h['gfx_id'] in [0x412,0x407])]
                    if yoyo:move['yoyo']={'positions':yoyo,'unrotate':next((t for t,op,h in cmds if op==19 and h['flag']==0 and h['value']),None)}
                    if hold_frames:move['heldItemPos']=hold_frames
                    if cid in [1,22] and a.motion in ['SpecialS','SpecialAirS']:
                        spawns += [{'frame':t,'kind':56 if cid==1 else 57,'pos':[0,0,0],'velocity':[0,0],'phase':1} for t,op,h in cmds if op==19 and h['flag']==2 and h['value']==1]
                    if cid in [6,20] and a.motion in ['SpecialLw','SpecialAirLw']:
                        spawns += [{'frame':t,'kind':58 if cid==6 else 59,'held':True,'phase':9} for t,op,h in cmds if op==24 and h['value']==0]
                    if cid==9 and state in [352,353]:
                        spawns += [{'frame':t,'kind':99,'held':True,'phase':9} for t,op,h in cmds if op==24 and h['value']==0]
                    if cid in [12,23] or cid==4 and state in [429,430,526,527]:
                        da=raw.u(fd.ft_root+4)+(0x1c0 if state in [429,430] else 0x1dc if cid==4 else 0)
                        if state in [341,342,429,430,526,527]:
                            off=8 if state in [342,430,527] else 0
                            # GFX 1042 queues generator 0x13 for procCollPos,
                            # after the input RNG anchor and map/ceiling pass.
                            spawns += [{'frame':t,'kind':raw.u(da+0x14),'pos':[0,raw.f(da+off+4),raw.f(da+off)],'phase':1,
                                        'releaseDraws':sum(generator_draws(0x13) for at,code,fields in cmds if at==t and code==10 and fields['gfx_id']==0x412)}
                                       for t,op,h in cmds if op==19 and h['flag']==0 and h['value']==1]
                        if state in [360,364]:
                            spawns += [{'frame':t,'kind':raw.u(da+0xdc),'pos':[0,raw.f(da+0xd0),0],'phase':9} for t,op,h in cmds if op==24 and h['value']==0]
                    if spawns:move['articleSpawns']=spawns
                    if cid==9 and a.motion in ['SpecialSEnd','SpecialAirSEnd']:
                        matrices,_=pose(move_nodes,tracks,0)
                        move['bomberPosition']=(matrices[move_joints[4]][:3,3]*scale).tolist()
                    if chain_hand:move['chainHand']=chain_hand
                    charge=next(((t,h) for t,op,h in cmds if op==56),None)
                    if charge:move['charge']=[charge[0],charge[1]['charge_frames'],charge[1]['charge_rate']*.003906]
                    if 94<=state<=119:
                        mul=fd.dat.f32(attrs+0xb4)*plco.f(item_throws+12*(state-94)+8)
                        move['itemThrowDamage']=[[0,mul]]+[[t,mul*.01*(h['value']&0x3fffff)] for t,op,h in cmds if op==19 and h['flag']==1 and h['value']]
                    extracted[index]=(move,ecb)
                except (ValueError,IndexError,KeyError,AssertionError,struct.error) as e:
                    issues.append([state,a.motion,str(e)]);continue
            move,ecb=extracted[index]
            if cid==4 and state in [512,513]:
                move={**move,'articleSpawns':[{**s,'kind':131} for s in move.get('articleSpawns',[])]}
            if cid==4 and state in [516,519]:
                move={**move,'articleSpawns':[{**s,'kind':141} for s in move.get('articleSpawns',[])]}
            if cid==4 and state in [526,527]:
                move={**move,'articleSpawns':[{**s,'kind':149} for s in move.get('articleSpawns',[])]}
            hitboxes[state]=move
            if ecb:ecbs[state]=ecb
        # Byte-for-byte projections of the validated C15/C25 Marth tables.
        # The hashes pin their original key order and 7/11-column row formats;
        # no reference binary or old duplicated stage table is needed to rebuild.
        if cid == 18:
            actual = {}
            for state, motion in [('44', 'Attack11'), ('45', 'Attack12'), ('50', 'AttackDash'), ('56', 'AttackHi3'), ('57', 'AttackLw3'), ('63', 'AttackHi4'), ('64', 'AttackLw4'), ('65', 'AttackAirN'), ('66', 'AttackAirF'), ('67', 'AttackAirB'), ('68', 'AttackAirHi'), ('69', 'AttackAirLw'), ('187', 'DownAttackU'), ('195', 'DownAttackD'), ('256', 'CliffAttackSlow'), ('257', 'CliffAttackQuick')]:
                found = next(m for m in hitboxes.values() if m['motion'] == motion)
                actual[state] = {'motion': found['motion'], 'frames': {str(k): [h[:7] for h in hs] for k,hs in found['frames'].items()}}
            assert hashlib.sha256(compact(actual).encode()).hexdigest() == 'c1a7f1d3e78c53cc7cf34932df868ef24d5050e4afc4ade0a006d8be413b901f', 'Marth stage 16 byte projection changed'
            actual = {}
            for state, motion in [('44', 'Attack11'), ('45', 'Attack12'), ('50', 'AttackDash'), ('56', 'AttackHi3'), ('57', 'AttackLw3'), ('60', 'AttackS4'), ('63', 'AttackHi4'), ('64', 'AttackLw4'), ('65', 'AttackAirN'), ('66', 'AttackAirF'), ('67', 'AttackAirB'), ('68', 'AttackAirHi'), ('69', 'AttackAirLw'), ('187', 'DownAttackU'), ('195', 'DownAttackD'), ('256', 'CliffAttackSlow'), ('257', 'CliffAttackQuick'), ('70', 'LandingAirN'), ('71', 'LandingAirF'), ('72', 'LandingAirB'), ('73', 'LandingAirHi'), ('74', 'LandingAirLw'), ('217', 'CatchAttack')]:
                found = next(m for m in hitboxes.values() if m['motion'] == motion)
                actual[state] = {'motion': found['motion'], 'frames': {str(k): [h[:11] for h in hs] for k,hs in found['frames'].items()}}
            assert hashlib.sha256(compact(actual).encode()).hexdigest() == 'c3f5a349006d048aa15e38198d86fc98b4e5c106d95ddd36c5a948042a2817cb', 'Marth stage 6 byte projection changed'
            actual = {k: ecbs[int(k)] for k in ['14', '25', '26', '27', '28']}
            assert hashlib.sha256(compact(actual).encode()).hexdigest() == '1ef6d696864fb305e591c81324163257270c8c38a1eb3d79be570a0e4ba12448', 'Marth ECB byte projection changed'
        stop=next((index for state,index in enumerate(indices) if state==250),None)
        owner=other if other and not fd.actions[stop].anim_size else fd
        a=owner.actions[stop];animbytes=otheraj if owner is other else aj
        clip=FighterNumericDat(animbytes[a.anim_offset:a.anim_offset+a.anim_size]);_,_,tracks,*_=read_figatree(clip.d,next(iter(clip.roots.values())))
        _,values=pose(nodes,tracks,0,legacy=cid==18)
        radii=[];scales=[]
        for i,(parent,_) in enumerate(nodes):
            parent_scale=scales[parent] if parent>=0 else 1.
            radii.append((radii[parent] if parent>=0 else 0.)+parent_scale*math.sqrt(sum(v*v for v in extents[i][6:])))
            scales.append(parent_scale*max(extents[i][3:6]))
        obj={'cid':cid,'weight':weight,'gravity':fd.dat.f32(attrs+0x5c),'modelScale':scale,'ecbRadius':max(radii[b] for b in bones)*scale+.01,'ecbBones':bones,'stopCeilTranslationY':values[joint_indices[bone_map[1]]][7]*scale,'hitboxes':hitboxes,'ecb':ecbs}
        if cid in [6,20]:
            da=raw.u(fd.ft_root+4);cc=plco.u(plco.roots['ftLoadCommonData']);obj['linkArticles']={'chargeMax':raw.f(da),'chargeStart':18,'boomerang':[raw.f(da+4*i) for i in range(5,11)],'smashThreshold':plco.f(cc+0x3c),'smashFrames':plco.u(cc+0x40)+plco.f(cc+0x44)}
        if cid==17:
            da=raw.u(fd.ft_root+4)
            obj['missile']={'max':raw.f(da+12),'damage':raw.f(da+16),'damageSlope':raw.f(da+20),'speed':raw.f(da+0x24),'speedSlope':raw.f(da+0x28)}
        if cid==9:
            da=raw.u(fd.ft_root+4);obj['turnipPluck']={'rareOdds':raw.u(da+0x14),'rareItems':[[raw.u(da+0x18+i*8),raw.u(da+0x1c+i*8)] for i in range(raw.u(da+0x10))]};obj['bomberSmashFrames']=raw.u(da+0x30)
        if cid==13:
            da=raw.u(fd.ft_root+4);obj['chargeShot']={'max':raw.f(da+0x18),'ticks':raw.u(da+0x20)}
            obj['morphBallEcb']=[raw.f(da+0x84+i*4) for i in range(6)]
        if cid==4:
            da=raw.u(fd.ft_root+4)
            obj['chargeShot']={'max':raw.f(da+0x168),'ticks':raw.u(da+0x170)}
            obj['copyArrows']={prefix:{'chargeMax':raw.f(da+off),'chargeStart':next(t for t,op,h in commands(fd,fd.actions[indices[state]],60) if op==19 and h['flag']==2 and h['value']==1)} for prefix,off,state in [('Lk',0x268,401),('Cl',0x27c,514)]}
        if cid in [4,24]:obj['chefMax']=raw.f(raw.u(fd.ft_root+4)+(0x3e8 if cid==4 else 0x1c))
        if cid in [4,16]:
            da=raw.u(fd.ft_root+4)+(0x384 if cid==4 else 0)
            obj['shadowBall']={'max':raw.f(da),'ticks':raw.u(da+12),'lag':raw.u(da+16)}
        if cid in [4,7]:
            da=raw.u(fd.ft_root+4)+(0x290 if cid==4 else 0)
            obj['needles']=[raw.f(da+4*i) for i in range(4)]
        if cid==7:
            # Chain aims blend local joints, not global hand positions.
            # Retain only hand ancestors and their numeric FOBJ channels.
            da=raw.u(fd.ft_root+4);items=raw.u(fd.ft_root+0x48);ta=raw.u(raw.u(items+12)+4)
            selected=set()
            for node in [joint_indices[26],*bones]:
                while node>=0:selected.add(node);node=nodes[node][0]
            ancestors=sorted(selected);lookup={v:i for i,v in enumerate(ancestors)}
            aim=[]
            for motion,rest_item in [(305,4),(308,5)]:
                a=fd.actions[motion];clip=FighterNumericDat(aj[a.anim_offset:a.anim_offset+a.anim_size])
                _,_,tracks,*_=read_figatree(clip.d,next(iter(clip.roots.values())))
                rest=[nodes[0]]+skeleton_at(raw,raw.u(raw.u(items+4*rest_item)+8))
                aim.append({'rest':[rest[k][1] for k in ancestors],
                    'tracks':[[lookup[t.node],t.type-1 if t.type<=3 else t.type-5 if t.type>=8 else t.type+1,t.start,
                               [[e['op'],e['frame'],e['value'],e['tan']] for e in t.events]]
                              for t in tracks if t.node in lookup and t.type in [1,2,3,5,6,7,8,9,10]]})
            obj['chain']={'attrs':[raw.u(ta)]+[raw.f(ta+i) for i in range(4,0x64,4)],
                'fighter':[raw.f(da+i) for i in range(0x14,0x2c,4)],
                'smooth':plco.f(plco.u(plco.roots['ftLoadCommonData'])+275*4),
                'parents':[lookup.get(nodes[k][0],-1) for k in ancestors],
                'hand':lookup[joint_indices[26]],'ecb':[lookup[k] for k in bones],
                'base':[nodes[k][1] for k in ancestors],'aim':aim}
        if cid in [12,23]:
            da=raw.u(fd.ft_root+4)
            obj['thunder']={'speed':raw.f(da+0xc0),'count':raw.u(da+0xd4),'delay':raw.u(da+0xd8),'hitOffset':raw.f(da+0xbc),'hitWidth':raw.f(da+0xc4),'hitHeight':raw.f(da+0xc8)}
            obj['skullBash']={'max':raw.f(da+0x24),'damage':raw.f(da+0x28),'damageSlope':raw.f(da+0x2c),'speed':raw.f(da+0x3c),'speedSlope':raw.f(da+0x40)}
        if cid==8:
            da=raw.u(fd.ft_root+4);obj['yoyo']=[raw.f(da+0xac+4*i) for i in range(3)]
        # Exact earlier-state references: no float quantization and no omitted
        # runtime poses. stageData expands these once when the lazy pack loads.
        for key in ['hitboxes','ecb']:
            seen={}
            for state,value in obj[key].items():
                signature=compact(value)
                if signature in seen:obj[key][state]=seen[signature]
                else:seen[signature]=int(state)
        path=data_root/f'fighters/{cid}.json';path.write_text(compact(obj)+'\n',encoding='utf-8',newline='\n')
        summary.append({'cid':cid,'code':code,'weight':weight,'scale':scale,'model':model,'motions':len(hitboxes),'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'issues':issues})
        print(compact(summary[-1]),flush=True)
    (out/'fighters-extraction.json').write_text(json.dumps(summary,indent=2)+'\n', encoding='utf8')
    return summary


def bake_yorster(data_root):
    """Authored block rotations, including the hidden pose before restoration."""
    sys.path.insert(0,str(REPO/'app/backend'))
    from shared.vanilla_extract.vanilla_refs import known_vanilla_iso
    from tools.native_rig.fobj_reader import native_value
    disc=FighterDisc(known_vanilla_iso() or REPO/'app/Super Smash Bros. Melee (USA) (En,Ja) (v1.02).iso')
    d=FighterNumericDat(disc.file('GrYt.dat'));group=d.u(d.roots['map_head']+8)+52
    animations=d.u(group+4);angles=[]
    for ai,count,rate in [(0,325,1),(1,1,1),(2,26,.3)]:
        _,tracks=item_anim(d,d.u(animations+4*ai))
        rotation=next(t for t in tracks if t.node==10 and t.type==1)
        # The same authored rotations drive all nine block joints.
        for node in range(11,19):assert next(t for t in tracks if t.node==node and t.type==1).events==rotation.events
        age=np.float32(0);values=[]
        for i in range(count):
            values.append(float(np.float32(native_value(rotation.events,float(age)))))
            age=np.float32(age+np.float32(rate))
        angles.append(values)
    path=data_root/'stageSim/16.json';obj=json.loads(path.read_text(encoding='utf8'))
    obj['blockAngles']=angles
    path.write_text(compact(obj)+'\n',encoding='utf8',newline='\n')
    pack_simulator_files(data_root)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dumps',type=Path,default=DEFAULT_DUMPS)
    parser.add_argument('--out',type=Path,default=DEFAULT_OUT)
    parser.add_argument('--data',type=Path,default=DATA)
    parser.add_argument('--decomp',type=Path,default=DECOMP)
    parser.add_argument('--tolerance',type=float,default=.02)
    parser.add_argument('--validate-js',action='store_true',help='audit the JS evaluator, paint geometry and real corpus (writes scratch truth fixtures)')
    parser.add_argument('--split-existing',action='store_true',help='repartition shipped/generated JSON without rebaking captures')
    parser.add_argument('--fighters', action='store_true', help='regenerate all numeric fighter packs from the vanilla ISO (read-only)')
    parser.add_argument('--items', action='store_true', help='regenerate numeric item/article packs from the vanilla ISO (read-only)')
    parser.add_argument('--fighter-cids', type=int, nargs='+', choices=range(27), help='optional internal fighter IDs for an incremental fighter bake')
    parser.add_argument('--yorster-poses',action='store_true',help='bake authored Yoshi Island block collision rotations')
    parser.add_argument('--pack-sim',action='store_true',help='refresh only stages/*.json from canonical stageSim tables')
    parser.add_argument('--collision-links',type=int,nargs='+',choices=[4,6,16,17,19],help='extract numeric MapLine adjacency for item ray correction')
    parser.add_argument('--movers',type=Path,help='optional freshly generated legacy movers table')
    parser.add_argument('--sim10',type=Path,help='optional freshly generated extended stage-10 table')
    args=parser.parse_args(); args.out.mkdir(parents=True,exist_ok=True)
    if args.tolerance <= 0: parser.error('tolerance must be positive')
    if args.fighters:
        bake_fighters(args.data.parent, args.out, args.decomp.parents[2], args.fighter_cids)
        return
    if args.items:
        bake_items(args.data.parent, args.out, args.decomp.parents[2])
        return
    if args.collision_links:
        sys.path.insert(0,str(REPO/'app/backend'))
        from shared.vanilla_extract.vanilla_refs import known_vanilla_iso
        disc=FighterDisc(known_vanilla_iso() or REPO/'app/Super Smash Bros. Melee (USA) (En,Ja) (v1.02).iso')
        for sid in args.collision_links:
            name={4:'GrCs',6:'GrZe',16:'GrYt',17:'GrGr',19:'GrI1'}[sid]
            raw=FighterNumericDat(disc.file(name+'.dat'));coll=raw.roots['coll_data'];at=raw.u(coll+8)
            path=args.data.parent/f'stageSim/{sid}.json';obj=json.loads(path.read_text(encoding='utf8'))
            obj['lineLinks']=[list(struct.unpack_from('>4h',raw.d,at+16*i+4)) for i in range(raw.u(coll+12))]
            path.write_text(compact(obj)+'\n',encoding='utf8',newline='\n')
        pack_simulator_files(args.data.parent)
        return
    if args.yorster_poses:
        bake_yorster(args.data.parent)
        return
    if args.pack_sim:
        pack_simulator_files(args.data.parent)
        return
    if args.split_existing:
        source = args.data if args.data.exists() else DATA
        stages = json.loads(source.read_text(encoding='utf-8'))['stages']
        write_stage_data(stages, args.data, args.movers, args.sim10)
        return
    stages={}; report=[]
    for sid,name in vanilla_names().items():
        if sid==26: continue # Adventure-only Icetop is not a VS stage.
        path=args.dumps/f'stage-{sid}-early.npz'
        if not path.exists(): path=args.dumps/f'stage-{sid}.npz'
        if not path.exists():
            report.append(dict(stage=sid,name=name,error='missing dump'));continue
        d=load_dump(path);nj=len(d['joints'])
        static=list(range(nj)) if STATIC[sid] is None else STATIC[sid]
        animated=list(range(nj)) if sid in ANIMATED and ANIMATED[sid] is None else ANIMATED.get(sid,[])
        neutral=NEUTRAL.get(sid,[])
        period,loop_start=find_period(d,animated)
        entry=dict(name=name,range=[int(d['frames'][0]),int(d['frames'][-1])],loop=period,
                   static=lines_at(d,static),neutral=lines_at(d,neutral),groups=[],
                   partial=sid in RANDOM,legacy=sid in LEGACY)
        if period: entry['loopStart'] = int(d['frames'][loop_start])
        entry['main']=silhouette(entry['static']+entry['neutral'])
        errors=[]
        for j in animated:
            g,err=bake_group(d,j,min(args.tolerance,.002) if sid==8 else args.tolerance,period,loop_start)
            if g: entry['groups'].append(g); errors.extend(err)
        share_tracks(entry)
        # Static errors cover every endpoint at every dumped row (not frame 0 only).
        for line in entry['static']:
            lid=line[0]; coords=np.asarray(line[2:]).reshape(2,2)
            err=np.linalg.norm(d['verts'][:,d['lines'][lid,:2]]-coords,axis=2)
            errors.extend(err.ravel().tolist())
        cls,moving,deforming=classify(d)
        exact_ids={l[0] for l in entry['static']}|{l[0] for g in entry['groups'] for l in g['lines']}
        active_total=active_known=0
        for j in range(nj):
            ids=joint_lines(d,j);states=line_states(d,ids,j)
            active_total+=int(np.count_nonzero(states))
            active_known+=int(np.count_nonzero(states[:,[i for i,lid in enumerate(ids) if lid in exact_ids]]))
        payload=compact(entry).encode()
        row=dict(stage=sid,name=name,classification=cls,moving_joints=moving,deforming_joints=deforming,
                 behavior='RANDOM/player-triggered parts' if sid in RANDOM else 'DETERMINISTIC',
                 frames=len(d['frames']),range=entry['range'],loop=period,loopStart=entry.get('loopStart'),static_joints=static,animated_joints=animated,
                 neutral_joints=neutral,exact_line_frames=active_known,total_line_frames=active_total,
                 coverage=active_known/active_total if active_total else 1,
                 max_error=max(errors) if errors else None,mean_error=float(np.mean(errors)) if errors else None,
                 bytes=len(payload),gzip_bytes=len(gzip.compress(payload,mtime=0)),
                 second=second_dump(d,args.dumps/f'stage-{sid}-b.npz'),source=f'gr{SOURCE[sid]}.c',
                 source_sha256=hashlib.sha256((args.decomp/f'gr{SOURCE[sid]}.c').read_bytes()).hexdigest(),
                 evidence=EVIDENCE.get(sid,f'See random-{sid}.md'),
                 dump=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                 requested_frames=LONGER.get(sid) if not period else None)
        stages[str(sid)]=entry;report.append(row)
        porting_note(sid,name,d,entry,args.out,args.decomp)
        composite(sid,name,d,entry,args.out)
        if args.validate_js: write_truth(d,entry,args.out,sid)
        print(f'{sid:2} {cls:28} known={row["coverage"]:6.1%} max={row["max_error"]} bytes={len(payload)} loop={period}',flush=True)
    args.data.parent.mkdir(parents=True,exist_ok=True)
    write_stage_data(stages, args.data, args.movers, args.sim10)
    (args.out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    if args.validate_js:
        env=dict(os.environ,STAGE_BAKE_AUDIT=str(args.out.resolve()))
        subprocess.run(['node','--test','--experimental-test-isolation=none','app/frontend/src/tracker/replays/stageCollision.test.js'],cwd=REPO,env=env,check=True)
        runtime_composites(args.out,report)
    markdown_report(report,args.out,args.data)


if __name__=='__main__': main()
