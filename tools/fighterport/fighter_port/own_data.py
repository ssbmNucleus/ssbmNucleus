"""The donor's fighter data, written again for a fighter that keeps its OWN skeleton (stages 4, 5 and 9 of
ULTIMATE_PORT_PIPELINE.md as one function of a fighter, where the Pokemon Trainer campaign had them as scripts for
three species and two donors).

A fighter data file (Pl??.dat, root `ftData...`) names joints by index all over: hurtboxes, the six joints its
collision diamond is drawn round, the leg solver, the joints a hand pose moves, a whole second skeleton for the
shield pose, another for the metal body, and every hitbox and effect in its scripts. On the own-skeleton route the
costume's joints are the SOURCE fighter's, so each of those is wrong (or past the end). `build` rewrites every one,
each from the best source there is for it:

  the source game's own numbers   hurtboxes (`hit_data` in its vl.prc), the collision diamond's joints
                                  (`map_coll_data`)
  the frozen rig, measured        limb lengths for the leg solver, the hand and head regions, the shield pose's
                                  skeleton, stature (for the coin spheres and the drawn scale)
  the donor's own table           everything that is only an index: donor joint -> the slot the donor's table gives
                                  it -> the joint this rig binds to that slot. A donor joint with no slot (a sword, a
                                  cape, hair) goes to the nearest joint above it that has one; the sword goes to the
                                  rig's right item-hold joint.
  nothing (turned off)            dynamics (cloth), the donor's hand poses, its metal body, its sword trail, and
                                  which of the DONOR's costume pieces a script shows or hides

and then reads its own output back with a second reader (`census`, which shares no code with the writer) and checks
every joint index in the file against what it should now be. Nothing here runs the game: see `UNVERIFIED`.

    python -m fighter_port.own_data            (Duck Hunt on Marth: writes <work>/data/PlMs.dat and report.json)

Layouts are HSDRaw's (HSDRaw/Melee/Pl/*.cs); what each table is FOR is the decompilation's (file and line beside
each use). The joint-index consumers are the list in NATIVE_SKELETON_CONSUMERS.md, plus six that list does not
have and Marth's file does: the camera's zoom joint (attributes +0x16C, ftlib.c:334), the counter bubble and the
sword trail in Marth's own attributes (ftMars/types.h), the shield pose's skeleton (+0x20, ftCo_Guard.c:216-227),
the metal body's (+0x5C, ftmetal.c:181), and three bits of each action's flag word that name a low joint whose
pose is taken at once, not blended in, when the action starts (fighter.c:1245, 1308: joint 3 on Marth's turns).
"""
from __future__ import annotations

import bisect
import json
import math
import os
import struct
from collections import Counter
from pathlib import Path

import numpy as np

from . import fighters
from .compat.bone_lookup import SLOTS
from .rigmap import euler_xyz

HDR = 0x20
NONE = 255
MAX_HURTBOXES = 15              # ftcoll.c:3227 asserts past it and then writes anyway (types.h:1333)
READING_MARGIN = 0.03           # the share of the body's points another reading of the capsules must gain to win
MIRROR = 0.05                   # how far a left capsule's end may be from its right twin's, mirrored, and be its mirror
MAX_PARTS = 140                 # ftparts.h:51
MAX_DEPTH = 30                  # ftanim.c:128 "fighter joint depth num over!"
SPECIAL_GFX_BONES = (0x8D, 0x8E)    # ftCo_09F7.c:72-112: "the next of the five special joints", "the item-hold joint"

# ----------------------------------------------------------------------------------------------------- the donor
# What is true of a donor's own files, measured once and kept here so `build` needs only the fighter data itself.
# `tests/test_own_data.py` checks each against the files when they are on the machine.
#   lookup   the donor's own table of which joint is which (PlCo.dat, ftLoadCommonData +0x10, its fighter kind):
#            slot -> joint, 255 = none. Slot order is `bone_lookup.SLOTS` (HSDRaw's storage order, NOT the
#            decompilation's enum: they part ways at slot 16).
#   parent   the donor costume's joint tree (PlMsNr.dat), joint -> parent.
#   sword    joints that are the donor's weapon: 74 hangs off the right hand and carries nothing, 75 and 76 carry the
#            sword's six model pieces, 75 is the trail's joint and 76 holds 78 of his hitboxes.
#   attr_joints  joint indices inside the donor's OWN attribute block (ftData +0x04): Marth's counter bubble
#            (`AbsorbDesc x64`, bone at +0x64) and sword trail (`SwordAttrs x78`, bone at +0x78+0x14).
#   rig_height / scale   y span of the costume's rest joints, and attributes +0x8C: drawn height is the product.
#   ultimate_height      y span of the same fighter's rest joints in Ultimate (fighter/marth/model/body/c00/
#            model.nusktb, read out of the game's archive 2026-11-12; the top is a hair bone in both games).
DONOR = {
    'Marth': dict(
        root='ftDataMars', kind=18, joints=90, ultimate='marth',
        lookup=[0, 1, 2, 3, 4, 255, 5, 6, 7, 8, 9, 12, 13, 14, 15, 16, 21, 22, 25, 27, 28, 29, 31, 32, 33, 34, 35,
                36, 37, 38, 39, 40, 41, 42, 59, 60, 67, 69, 70, 71, 73, 77, 78, 79, 80, 81, 82, 83, 84, 255, 85, 86,
                88, 89],
        parent=[None, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 6, 4, 12, 13, 14, 15, 16, 13, 4, 19, 4, 21, 22, 22, 22, 25, 25,
                27, 28, 29, 29, 31, 32, 31, 34, 31, 36, 31, 38, 31, 31, 41, 28, 22, 44, 45, 46, 47, 22, 49, 50, 51,
                52, 22, 54, 55, 56, 57, 22, 59, 60, 60, 60, 60, 60, 60, 22, 67, 67, 69, 70, 71, 71, 73, 74, 75, 73,
                77, 73, 79, 73, 81, 73, 83, 73, 85, 70, 3, 0],
        sword=(74, 75, 76),
        attr_joints=((0x64, 'counter bubble'), (0x8C, 'sword trail')),
        rig_height=16.650622, scale=1.15, ultimate_height=19.744346),
}

# A slot the new rig leaves empty, and the slot that stands in for it (the same place on the body: Melee splits
# some joints in two, a twist joint and the joint itself).
SLOT_STAND_IN = {'waistB': 'waist', 'waist': 'waistB', 'lLegA': 'lLeg', 'rLegA': 'rLeg', 'lFootA': 'lFoot',
                 'rFootA': 'rFoot', 'lShoulderA': 'lShoulder', 'rShoulderA': 'rShoulder'}

# What is true of one fighter and cannot be worked out from its bindings: written in `fighters.py`, the one place a
# fighter is written into, and read here by the name this table always had.
#   item_hold  the joint an item is held at (Duck Hunt's bindings give both front paws a hold slot, but the dog
#              carries things in its mouth: `Have`).
FIGHTER = {name: dict(item_hold=joint) for name, joint in fighters.column('item_hold').items()}

# Melee's three hurtbox heights (HSDRaw HurtboxPositionType Low/Mid/High; Marth: 0 on his legs, 1 on body and arms,
# 2 on his head) against the source's `height` values. The source's names are known by their hashes, and they sit
# where the names say: `high` on the head, `low` on the two hind-leg capsules, `center` on everything else.
HEIGHTS = {'hit_height_low': 0, 'hit_height_center': 1, 'hit_height_high': 2}

# ftData +0x58, the leg solver (ft_0892.c:386-430). Ten joint bytes, and lengths the solver uses with them:
# len0 = +0x04, len1 = +0x0C + +0x18. Measured on fourteen of Melee's own fighters against their own costumes:
# +0x04 thigh, +0x0C shin, +0x20 upper arm, +0x28 forearm (each to half a percent), and +0x18 is how high the foot
# joint rests above the ground (twelve of fourteen to 0.01; Yoshi and Pikachu, whose legs fold back, differ).
IK_BYTES = {0x00: 'RLegJ', 0x01: 'LLegJ', 0x08: 'RKneeJ', 0x09: 'LKneeJ', 0x10: 'RFootJ', 0x11: 'LFootJ',
            0x1C: 'RShoulderJ', 0x1D: 'LShoulderJ', 0x24: 'RArmJ', 0x25: 'LArmJ'}
IK_SEGMENTS = {0x04: ('thigh', 0x00, 0x08), 0x0C: ('shin', 0x08, 0x10), 0x20: ('upper arm', 0x1C, 0x24),
               0x28: ('forearm', 0x24, 'rHand')}
IK_FOOT_HEIGHT = 0x18
ACTION_FLAG_JOINT = (23, 3)         # an action's flag word (+0x10 of its 0x18-byte row): first bit, bits
IK_UNTOUCHED = (0x14, 0x2C, 0x30)   # 0x2C = 50 and 0x30 = 30 on every fighter (limits); 0x14 fits no bone pair

# ftData +0x1C, the joints a hand or face pose moves: part -> the slot whose joint heads the region.
PART_ANCHOR = {0: 'lHand', 1: 'rHand', 2: 'headN'}
PART_SKIPS_ANCHOR = (2,)            # the head's part lists what hangs below the head, not the head (Marth: 63, 64)

# Script commands that hold a joint, as the decompilation's own bitfields lay them out (lb/types.h:717-950).
# (first bit, bits) from the top of the command's first word. The reader below uses these; the writer uses the
# app's command table; a test holds the two against each other.
CMD_GFX, CMD_HIT, CMD_HURT_STATE, CMD_MODEL_STATE = 0x0A, 0x0B, 0x1C, 0x1F
CMD_TEX_ANIM, CMD_PART_ANIM, CMD_SWORD_TRAIL, CMD_BONE_PHYSICS, CMD_WIND = 0x28, 0x29, 0x31, 0x32, 0x3A
CMD_END, CMD_SUBROUTINE, CMD_GOTO = 0x00, 0x05, 0x07
JOINT_FIELD = {CMD_GFX: (6, 8), CMD_HIT: (13, 8), CMD_HURT_STATE: (6, 8), CMD_BONE_PHYSICS: (6, 26),
               CMD_WIND: (24, 8)}
COMMON_FLAG = {CMD_GFX: 14, CMD_HIT: 21}        # "this is a slot, not a joint" (ftaction.c:252, 317)
GFX_HEAD_FLAG = 16                              # "use the top-of-head joint" (ftaction.c:247, spawn_gfx_0.useUnkBone)
CMD_NAME = {CMD_GFX: 'Graphic Effect', CMD_HIT: 'Create Hitbox', CMD_HURT_STATE: 'Set Bone Collision State',
            CMD_BONE_PHYSICS: 'Toggle Bone Physics', CMD_WIND: 'Aesthetic Wind Effect',
            CMD_MODEL_STATE: 'Change Model State', CMD_TEX_ANIM: 'Animate Texture', CMD_PART_ANIM: 'Animate Model',
            CMD_SWORD_TRAIL: 'Sword Trail'}
# Every command's size in bytes, by its code (the code is the top six bits of its first byte).
CMD_SIZE = {0x00: 4, 0x01: 4, 0x02: 4, 0x03: 4, 0x04: 4, 0x05: 8, 0x06: 4, 0x07: 8, 0x08: 4, 0x09: 4, 0x0A: 20,
            0x0B: 20, 0x0C: 4, 0x0D: 4, 0x0E: 4, 0x0F: 4, 0x10: 4, 0x11: 12, 0x12: 4, 0x13: 4, 0x14: 4, 0x15: 4,
            0x16: 4, 0x17: 4, 0x18: 4, 0x19: 4, 0x1A: 4, 0x1B: 4, 0x1C: 4, 0x1D: 4, 0x1E: 4, 0x1F: 4, 0x20: 4,
            0x21: 4, 0x22: 12, 0x23: 4, 0x24: 4, 0x25: 4, 0x26: 28, 0x27: 16, 0x28: 4, 0x29: 4, 0x2A: 4, 0x2B: 4,
            0x2C: 4, 0x2D: 4, 0x2E: 4, 0x2F: 4, 0x30: 4, 0x31: 4, 0x32: 4, 0x33: 4, 0x34: 4, 0x35: 4, 0x36: 12,
            0x37: 12, 0x38: 8, 0x39: 4, 0x3A: 16}

UNVERIFIED = [
    'Nothing here was run in the game. Every statement about what the engine does with a table is read from the '
    'decompilation.',
    'The shield pose and the hand/face poses are walked by the engine joint by joint beside the costume; that the '
    'walk lines up is checked here against the frozen order, not against a running fighter.',
    'Turning the metal body off (no pieces, an empty list) follows the loader as decompiled; no fighter of '
    "Melee's own ships that way. Nor does one ship with a metal skeleton shorter than the donor's: on a rig with "
    "fewer joints than the donor the skeleton is cut to the rig's count (ftmetal.c:181 pairs the two by counting), "
    'which has not been seen in the game either (Falco, 89 joints to Marth\'s 90, was the first such rig built).',
    'The costume as it stands has no texture animations; the two texture slots the donor\'s code and scripts '
    'animate now name textures it has (0 and 1), and the game stops at load unless the costume gives those two '
    'textures an animation (costume.add_empty_material_tree and static_materials do that for a static costume).',
    "PlCo.dat's second joint table (ftLoadCommonData +0x14, the joints a fighter kind leaves out of a tree walk) "
    'belongs to the package, not to this file.',
    'The ledge-grab box, camera box, item-pickup boxes and push box (ECB floats, +0x3C, +0x40, +0x50) hold no '
    "joint and are still Marth's numbers.",
    "The coin spheres are the donor's two, moved by the rest pose's height; a fighter whose rest pose is not how "
    'it stands in play (Duck Hunt rests upright with its arms out and plays on all fours) gets a rough fit.',
    "Ten of the donor's actions (its turns) name joint 3 as the joint whose pose is taken unblended; through the "
    "table that is still joint 3, the engine's own turning joint. If the port's clips turn the body on another "
    'joint, those actions want that joint instead (it must be one of the first eight).',
    "The low six bits of every action's flag word say whose skeleton its clip is for (18, Marth, on 300 of them; "
    'ftanim.c:781 sends a clip of another kind through both tables). That belongs to whoever writes the clips.',
]


# ------------------------------------------------------------------------------------------------------ the rig
def rest_worlds(frozen):
    """Every joint's rest matrix in the fighter's own space, in the frozen order. -> array (joints, 4, 4)"""
    order, index, out = frozen['order'], {}, []
    for i, j in enumerate(order):
        r = frozen['rest'][j]
        m = np.eye(4)
        m[:3, :3] = euler_xyz(r['r']) * np.asarray(r['s'], float)
        m[:3, 3] = r['t']
        p = frozen['parent'][j]
        if p is not None and p not in index:
            raise ValueError(f'{j}: its parent {p} comes after it; the order is not the costume\'s')
        out.append(out[index[p]] @ m if p is not None else m)
        index[j] = i
    return np.array(out)


def rig_height(worlds):
    """y span of the rest joints (the measure ULTIMATE_PORT_PIPELINE.md's scale table uses)."""
    ys = np.asarray(worlds)[:, 1, 3]
    return float(ys.max() - ys.min())


def tree_links(parents):
    """A joint tree as the game stores it. parents: joint -> parent index or None, in costume order.
    -> [(first child or None, next sibling or None)]. Refuses a tree whose depth-first walk (child first, then
    sibling: ftAnim_GetNextJointInTree) is not 0, 1, 2 ...: the engine pairs a tree's nodes with the fighter's
    joints by counting."""
    kids = {}
    for i, p in enumerate(parents):
        if p is not None:
            if not 0 <= p < i:
                raise ValueError(f'joint {i}: parent {p} does not come before it')
            kids.setdefault(p, []).append(i)
    links = []
    for i, p in enumerate(parents):
        mine = kids.get(i, [])
        sibs = kids.get(p, []) if p is not None else [k for k, q in enumerate(parents) if q is None]
        at = sibs.index(i)
        links.append((mine[0] if mine else None, sibs[at + 1] if at + 1 < len(sibs) else None))
    walk, stack, cur, deepest = [], [], 0, 0
    while cur is not None:
        walk.append(cur)
        child, nxt = links[cur]
        if child is not None:
            stack.append(cur)
            deepest = max(deepest, len(stack))
            cur = child
        elif nxt is not None:
            cur = nxt
        else:
            cur = None
            while stack:
                up = stack.pop()
                if links[up][1] is not None:
                    cur = links[up][1]
                    break
    if walk != list(range(len(parents))):
        raise ValueError('the tree does not walk in index order')
    if deepest >= MAX_DEPTH:
        raise ValueError(f'the tree is {deepest} deep; the engine walks at most {MAX_DEPTH - 1}')
    return links


def region(parents, names, anchor, capacity, skip_anchor=False, skip_prefix='__'):
    """The joints of one body region, nearest first: `anchor` and what hangs below it (helpers left out), cut to
    the room the donor's list has. -> (members, dropped)"""
    kids = {}
    for i, p in enumerate(parents):
        if p is not None:
            kids.setdefault(p, []).append(i)
    out, queue = [], [anchor]
    while queue:
        cur = queue.pop(0)
        if not names[cur].startswith(skip_prefix) and not (skip_anchor and cur == anchor):
            out.append(cur)
        queue.extend(kids.get(cur, []))
    return out[:capacity], out[capacity:]


# ----------------------------------------------------------------------------------------- donor joint -> new joint
def joint_map(donor, forward, *, item_joint=None, item_target=None):
    """Where each of the donor's joints goes on the new rig. -> {donor joint: dict(to, tier, via)}
    forward: the new rig's table, slot -> joint (255 none). Tiers, first that applies:
      SWORD     one of the donor's weapon joints -> the rig's right item-hold joint (its right hand without one)
      ITEM      the donor's item-hold joint -> the rig's (`item_target`)
      SLOT      the donor's table gives the joint a slot, and the rig binds that slot
      STAND_IN  the rig leaves that slot empty and binds the slot beside it (SLOT_STAND_IN)
      ANCESTOR  none of those: the nearest joint above it in the DONOR's tree that has one"""
    reverse = {}
    for slot, joint in enumerate(donor['lookup']):
        if joint != NONE:
            reverse[joint] = slot                          # HSDRaw: the last slot to name a joint wins
    slot_of = {name: i for i, name in enumerate(SLOTS)}

    def bound(name):
        j = forward[slot_of[name]]
        return None if j == NONE else j

    sword_target, sword_via = None, None
    for name in ('rHave', 'rHand', 'lHave', 'lHand'):
        if bound(name) is not None:
            sword_target, sword_via = bound(name), name
            break

    def direct(j):
        if j in donor['sword'] and sword_target is not None:
            return dict(to=sword_target, tier='SWORD', via=sword_via)
        if item_joint is not None and j == item_joint and item_target is not None:
            return dict(to=item_target, tier='ITEM', via='item hold')
        slot = reverse.get(j)
        if slot is None:
            return None
        name = SLOTS[slot]
        if bound(name) is not None:
            return dict(to=bound(name), tier='SLOT', via=name)
        other = SLOT_STAND_IN.get(name)
        if other is not None and bound(other) is not None:
            return dict(to=bound(other), tier='STAND_IN', via=f'{name}>{other}')
        return None

    out = {}
    for j in range(donor['joints']):
        row, up = direct(j), j
        while row is None:
            up = donor['parent'][up]
            if up is None:
                raise ValueError(f'donor joint {j} has no slot and nothing above it has one')
            above = direct(up)
            if above is not None:
                row = dict(to=above['to'], tier='ANCESTOR', via=f'{up}:{above["via"]}')
        out[j] = row
    return out


def hurt_joint(target, parents, hurt_joints):
    """A joint a script may switch the hurtbox of: `target` if it carries one, else the nearest joint above it that
    does, else the nearest below, else the first. (ftColl_8007B128 stops the game on a joint with no hurtbox.)"""
    if target in hurt_joints:
        return target, 'itself'
    up = parents[target]
    while up is not None:
        if up in hurt_joints:
            return up, 'above'
        up = parents[up]
    kids = {}
    for i, p in enumerate(parents):
        if p is not None:
            kids.setdefault(p, []).append(i)
    queue = list(kids.get(target, []))
    while queue:
        cur = queue.pop(0)
        if cur in hurt_joints:
            return cur, 'below'
        queue.extend(kids.get(cur, []))
    return sorted(hurt_joints)[0], 'first'


def _put(word, first, count, value):
    """`word` with `count` bits from bit `first` (counted from the top) set to `value`."""
    if not 0 <= value < 1 << count:
        raise ValueError(f'{value} does not fit {count} bits')
    shift = 32 - first - count
    return (word & ~(((1 << count) - 1) << shift) & 0xFFFFFFFF) | (value << shift)


def command_target(code, word, donor, jmap, forward, reverse, parents, hurt_joints):
    """What becomes of one script command that holds a joint. word: the command's first four bytes.
    -> dict(word: the first four bytes now, tier: how the joint was re-pointed or None when the command is left
    as it is, kept: why it is left, donor_joint: the donor joint it named)
    Left as they are: an effect on "the top of the head" or on a selector (the engine picks the joint), and a
    command that names a SLOT the rig binds (the rig's own table answers it). A slot the rig leaves empty would
    read joint 255: the command is given the slot of the joint the donor's joint maps to, or that joint itself.
    A hurtbox switch must name a joint that carries a hurtbox (`hurt_joint`)."""
    first, bits = JOINT_FIELD[code]
    value = _bits(word, first, bits)
    left = dict(word=word, tier=None, donor_joint=None)
    if code == CMD_GFX and _bits(word, GFX_HEAD_FLAG, 1):
        return dict(left, kept='the top-of-head joint, by its flag')
    common = code in COMMON_FLAG and _bits(word, COMMON_FLAG[code], 1)
    if code == CMD_GFX and not common and value in SPECIAL_GFX_BONES:
        return dict(left, kept='a selector (the item joint / the next special joint)')
    if common:
        if value >= len(SLOTS):
            raise ValueError(f'{CMD_NAME[code]} names slot {value}')
        if forward[value] != NONE:
            return dict(left, kept=f'a slot the rig binds ({SLOTS[value]})')
        was = donor['lookup'][value]
        if was == NONE:
            raise ValueError(f'{CMD_NAME[code]} names slot {SLOTS[value]}, which the donor itself leaves empty')
        target = jmap[was]['to']
        if reverse[target] != NONE:
            return dict(word=_put(word, first, bits, reverse[target]), tier='SLOT>' + jmap[was]['tier'], kept=None,
                        donor_joint=was)
        return dict(word=_put(_put(word, COMMON_FLAG[code], 1, 0), first, bits, target), tier='SLOT>JOINT',
                    kept=None, donor_joint=was)
    if code == CMD_BONE_PHYSICS and not 0 <= value < donor['joints']:
        return dict(left, kept="bone physics on no joint of the donor's (dynamics are off)")
    if not 0 <= value < donor['joints']:
        raise ValueError(f"{CMD_NAME[code]} names joint {value}: not one of the donor's")
    target, tier = jmap[value]['to'], jmap[value]['tier']
    if code == CMD_HURT_STATE:
        target, where = hurt_joint(target, parents, hurt_joints)
        if where != 'itself':
            tier += f'>hurtbox {where}'
    return dict(word=_put(word, first, bits, target), tier=tier, kept=None, donor_joint=value)


def trail_target(word):
    """A Sword Trail command's first word, and what was done to it. The donor's own sword's trail is turned off
    (its joint is the donor's, and for a fighter kind the engine does not know there is no trail to draw:
    ftafterimage.c:411); a held sword item's trail is the item's own (ftafterimage.c:399-413) and stays."""
    if (word & 0xFF) == 0xFF:
        return word, 'already off'
    if _bits(word, 6, 1):
        return word, "a held sword item's, left"
    return _put(word, 6, 26, (1 << 25) - 1), "the donor sword's, turned off"   # no item bit, state -1


# ------------------------------------------------------------------------------------------- the source game's own
def source_tables(prc_bytes, order):
    """The source fighter's own hurtboxes and collision joints, out of its vl.prc.
    -> dict(hurt=[dict(bone, a, b, radius, height, part)], ecb=[dict(bone, offset)])
    A bone the frozen rig does not have, or a height that is none of the three known, is refused by name."""
    from echo_ultimate.gamedata.prc import Prc, hash40
    by_hash = {}
    for j in order:
        if by_hash.setdefault(hash40(j), j) != j:
            raise ValueError(f'two joints share a name but for its case: {j}')
    if hash40(SOURCE_ROOT) not in by_hash and order:
        # the model's own root ("top", above Trans): the rig's top joint, or (the source's skeleton as it is read
        # before there is a rig: preflight) its first, which is the top of its tree
        by_hash[hash40(SOURCE_ROOT)] = RIG_ROOT if RIG_ROOT in order else order[0]
    fields = ('hit_data node_id offset1_x offset1_y offset1_z offset2_x offset2_y offset2_z size part height '
              'map_coll_data node offset_x offset_y offset_z').split()
    parts = 'collision_part_body collision_part_head collision_part_body_legs collision_part_etc'.split()
    root = Prc(prc_bytes, list(fields) + list(HEIGHTS) + parts).root

    def bone(value, where):
        name = by_hash.get(value.value)
        if name is None:
            raise ValueError(f'{where}: the rig has no joint for {value.text}')
        return name

    hurt = []
    for i, e in enumerate(root['hit_data']):
        height = e['height'].text
        if height not in HEIGHTS:
            raise ValueError(f'hit_data[{i}]: unknown height {height}')
        hurt.append(dict(bone=bone(e['node_id'], f'hit_data[{i}]'),
                         a=[float(e[f'offset1_{k}']) for k in 'xyz'], b=[float(e[f'offset2_{k}']) for k in 'xyz'],
                         radius=float(e['size']), height=height, part=e['part'].text))
    ecb = [dict(bone=bone(e['node'], f'map_coll_data[{i}]'), offset=[float(e[f'offset_{k}']) for k in 'xyz'])
           for i, e in enumerate(root['map_coll_data'])]
    return dict(hurt=hurt, ecb=ecb)


def hurtboxes(rows, order, grabbable=None):
    """The source's hurtboxes as Melee's. Both games keep a capsule in its joint's own space (two ends and a
    radius), and the frozen rig's joints are the source's at the source's size, so the numbers carry over as they
    are (`capsule_check` is the evidence). -> [dict(joint, height, grabbable, a, b, radius)]
    grabbable: the names of the joints whose capsule a grab can take hold of; every capsule when not given (the
    source keeps no such flag)."""
    if not 1 <= len(rows) <= MAX_HURTBOXES:
        raise ValueError(f'{len(rows)} hurtboxes: Melee holds 1 to {MAX_HURTBOXES}')
    index = {j: i for i, j in enumerate(order)}
    out = []
    for r in rows:
        if r['bone'] not in index:
            raise ValueError(f'hurtbox on {r["bone"]}: not a joint of the rig')
        out.append(dict(joint=index[r['bone']], height=HEIGHTS[r['height']],
                        grabbable=1 if grabbable is None or r['bone'] in grabbable else 0,
                        a=[float(v) for v in r['a']], b=[float(v) for v in r['b']], radius=float(r['radius'])))
    return out


def rehome_folded(rows, folded, source_world):
    """The source's hurtboxes with each one on a bone the rig FOLDED (own_skeleton: over the joint limit, a bone is
    folded into the kept bone above it and rides it as it rests there) put on that kept bone, its two ends carried
    into the kept bone's space at rest: in every pose it is where the folded bone's would have been on the rig.
    (Rivals 2's Zetterburn, 2026-11-13: six of his twelve capsules are on twist bones, `HipPart2_R` and the like,
    which the rig folds, and prepare stopped on `not a joint of the rig`.)
    folded        {bone: the kept bone it went into} (the frozen rig's provenance `folded`)
    source_world  {bone: its rest matrix in the fighter's space} of the source's own skeleton
    -> (rows, [what was moved, in words])"""
    out, said = [], []
    for r in rows:
        to = folded.get(r['bone'])
        if to is None:
            out.append(r)
            continue
        carry = np.linalg.inv(np.asarray(source_world[to], float)) @ np.asarray(source_world[r['bone']], float)
        a, b = (list((carry @ np.array([*map(float, r[k]), 1.0]))[:3]) for k in ('a', 'b'))
        out.append(dict(r, bone=to, a=[float(v) for v in a], b=[float(v) for v in b], folded_from=r['bone']))
        said.append(f"{r['bone']} -> {to}")
    return out, said


def joints_mirror(right, left, tolerance=None):
    """Whether two joints' rest matrices are mirror images of each other across the fighter's middle (x = 0): the
    left one is where the right one is, mirrored, and its three axes are the right one's mirrored, each kept or
    turned about (a left limb is modelled as its right one's mirror, and which axes are turned about differs from
    game to game and from joint to joint). -> the three signs (+1 kept, -1 turned about), or None when they are
    not mirror images."""
    right, left = np.asarray(right, float), np.asarray(left, float)
    flip = np.diag([-1.0, 1.0, 1.0])
    if np.abs(flip @ right[:3, 3] - left[:3, 3]).max() > (MIRROR if tolerance is None else tolerance):
        return None
    turn = right[:3, :3].T @ flip @ left[:3, :3]          # the left joint's axes in the mirrored right joint's own
    signs = np.sign(np.diag(turn))
    if np.abs(turn - np.diag(signs)).max() > 0.01:
        return None
    return [float(s) for s in signs]


def capsule_check(capsules, order, parents, worlds, points=None, owner=None, accepted=()):
    """Where each capsule is at rest, and whether that is on the body. Per capsule: its two ends in the fighter's
    space; whether it runs toward the joint's own child (a limb's capsule should); with the body's points
    (`points`, and `owner`: the joint each point follows most), how many of its own joint's points it holds.
    Then the same count with the ends read five other ways (axes swapped, mirrored): the reading used must win,
    and a reading that holds no more than `READING_MARGIN` more of the body, or holds less of the capsules' own
    points on the mean over the capsules (one dense part, a big head, outvotes the rest in a plain count), has not
    won.

    Left and right ('pairs', 'sides_ok'). This is a check of the ROUTE's work, not of the game's table: that the
    rig and the reader put each capsule of a pair on its own side, on the same part of the body as its twin. So:
      - each of a pair is on its own side of the fighter's middle, always;
      - a pair that comes out as mirror images (to `MIRROR`) is right;
      - a pair that does not is held against the two JOINTS. Where they are not mirror images of each other the
        rig is at fault, and the pair fails. Where they are, the rig is exact and the difference is in the game's
        own numbers for the two capsules ('lopsided_in_the_source': Wolf's table gives one knee's far end +0.4
        and the other's -0.4). That is the game's and is carried as it is, as long as the two still lie on the
        same part of the body: no end further from its twin's mirror image than the thinner capsule's own radius
        (Wolf's knees: 0.79 against 1.4). Further apart than that they are not a pair on one limb any more: a
        capsule was read wrong, or the game means something a reader must look at, and the pair fails until its
        right joint is named in `accepted` (the fighter's `lopsided` in `fighters.py`)."""
    worlds = np.asarray(worlds)
    kids = {}
    for i, p in enumerate(parents):
        if p is not None:
            kids.setdefault(p, []).append(i)

    def ends(c, how=lambda v: v):
        m = worlds[c['joint']]
        return (m @ np.r_[how(c['a']), 1.0])[:3], (m @ np.r_[how(c['b']), 1.0])[:3]

    def inside(p, a, b, radius):
        ab = b - a
        length = float(ab @ ab)
        t = np.clip(((p - a) @ ab) / length, 0, 1) if length > 1e-12 else np.zeros(len(p))
        return np.linalg.norm(p - (a + t[:, None] * ab), axis=1) <= radius

    readings = {'as written': lambda v: v, 'x and z swapped': lambda v: [v[2], v[1], v[0]],
                'x and y swapped': lambda v: [v[1], v[0], v[2]], 'x mirrored': lambda v: [-v[0], v[1], v[2]],
                'y mirrored': lambda v: [v[0], -v[1], v[2]], 'turned (y, z, x)': lambda v: [v[1], v[2], v[0]]}
    rows = []
    for c in capsules:
        a, b = ends(c)
        row = dict(joint=c['joint'], name=order[c['joint']], a=[round(float(v), 3) for v in a],
                   b=[round(float(v), 3) for v in b], radius=c['radius'])
        axis = b - a
        child = next((k for k in kids.get(c['joint'], []) if not order[k].startswith('__')), None)
        if child is not None and np.linalg.norm(axis) > 1e-6:
            to_child = worlds[child][:3, 3] - worlds[c['joint']][:3, 3]
            if np.linalg.norm(to_child) > 1e-6:
                row['toward_child'] = round(float(axis @ to_child / np.linalg.norm(axis) / np.linalg.norm(to_child)), 3)
                row['child'] = order[child]
        rows.append(row)
    out = dict(capsules=rows)
    names = {order[c['joint']]: c for c in capsules}
    pairs = []
    for name, c in names.items():
        if name.endswith('R') and name[:-1] + 'L' in names:
            other = names[name[:-1] + 'L']
            (ra, rb), (la, lb) = ends(c), ends(other)
            flip = np.array([-1.0, 1.0, 1.0])
            error = float(max(np.abs(ra * flip - la).max(), np.abs(rb * flip - lb).max()))
            row = dict(right=name, left=name[:-1] + 'L', right_x=round(float((ra[0] + rb[0]) / 2), 3),
                       left_x=round(float((la[0] + lb[0]) / 2), 3), mirror_error=round(error, 4))
            row['own_sides'] = bool(row['right_x'] < 0 < row['left_x'])
            if error < MIRROR:
                row['ok'] = row['own_sides']
            else:
                # not mirror images: is it the rig, or the game's own numbers for the two?
                signs = joints_mirror(worlds[c['joint']], worlds[other['joint']])
                width = float(min(c['radius'], other['radius']))
                row.update(lopsided_in_the_source=signs is not None, thinner_radius=round(width, 4),
                           source_numbers=dict(right=dict(a=list(c['a']), b=list(c['b']), radius=c['radius']),
                                               left=dict(a=list(other['a']), b=list(other['b']),
                                                         radius=other['radius'])))
                if signs is None:
                    row.update(ok=False, why='the two joints are not mirror images of each other at rest: the rig '
                                             'is at fault, not the game\'s table')
                elif name in accepted:
                    row.update(ok=row['own_sides'], why="the game's own table, looked at and accepted (the "
                                                        "fighter's `lopsided` in fighters.py)")
                elif error <= width:
                    row.update(ok=row['own_sides'],
                               why="the game's own table gives the two different numbers; they still lie on the "
                                   "same part of the body (no end further off than the thinner one's radius): "
                                   'carried as it is')
                else:
                    row.update(ok=False,
                               why="the game's own table gives the two different numbers, and they are further "
                                   'apart than a capsule is wide: read wrong, or the game means it. Look at the '
                                   f"model; if the game means it, write lopsided=['{name}'] in the fighter's "
                                   'entry in fighter_port/fighters.py')
            pairs.append(row)
    out['pairs'] = pairs
    out['sides_ok'] = all(p['ok'] for p in pairs)
    if points is not None:
        points, owner = np.asarray(points, float), np.asarray(owner)
        table = {}
        for label, how in readings.items():
            covered, own = np.zeros(len(points), bool), []
            for c in capsules:
                hit = inside(points, *ends(c, how), c['radius'])
                covered |= hit
                mine = owner == c['joint']
                own.append([int((hit & mine).sum()), int(mine.sum())])
            shares = [i / n for i, n in own if n]
            table[label] = dict(body_inside=round(float(covered.mean()), 4), own_points=own,
                                capsules_inside=round(float(np.mean(shares)) if shares else 0.0, 4))
        out['readings'] = table
        # Another reading must hold clearly more of the body to be called better. Where a fighter's capsules lie
        # nearly along one axis of their joints, turning another axis about hardly moves them, and the count
        # cannot tell the two readings apart (Wolf, whose capsules have almost no y: 'y mirrored' holds 0.702 of
        # his body against 0.692 as written; the readings that are wrong hold 0.39 to 0.55, and on Duck Hunt 0.25
        # to 0.54 against 0.65). A tie does not overturn the game's own reading; it is written down below.
        # The count is of points, so one dense part outvotes the rest: Incineroar's head and fur are 62,346 of the
        # body's 113,000 points, and read 'x and y swapped' the head's round capsule holds 49,172 of them against
        # 27,856, so that reading held 0.549 of the body against 0.444 while it put every limb's capsule off its
        # limb (the arms 0.30 of their own points against 1.0). So a reading must ALSO hold more of each capsule's
        # own points, on the mean over the capsules ('capsules_inside', each capsule one vote), to win.
        best = max(table, key=lambda k: table[k]['body_inside'])
        clearly = table[best]['body_inside'] - table['as written']['body_inside'] > READING_MARGIN
        per_capsule = table[best]['capsules_inside'] > table['as written']['capsules_inside']
        out['best_reading'] = best if clearly and per_capsule else 'as written'
        out['closest_other_reading'] = None if best == 'as written' else dict(
            reading=best, body_inside=table[best]['body_inside'], as_written=table['as written']['body_inside'],
            capsules_inside=table[best]['capsules_inside'],
            capsules_as_written=table['as written']['capsules_inside'],
            why=None if not clearly else ('it holds more of the body only through one dense part: each capsule '
                                          'holds less of the points of its own joint' if not per_capsule else None))
        for row, own in zip(rows, table['as written']['own_points']):
            row['own_points_inside'], row['own_points'] = own
    return out


def sides_problems(check):
    """What `capsule_check` found wrong with the left and right pairs, a line a pair, each with the numbers and what
    to do about it (said here so that the stage that stops and the preflight that warns say the same thing)."""
    out = []
    for p in check['pairs']:
        if p['ok']:
            continue
        if not p['own_sides']:
            out.append(f"hurtboxes {p['right']} and {p['left']}: not each on its own side of the fighter (their middles "
                       f"are at x {p['right_x']} and {p['left_x']}; right is the fighter's -x). The rig's joints or "
                       'the reader have the two the wrong way round')
        else:
            n = p.get('source_numbers') or {}
            out.append(f"hurtboxes {p['right']} and {p['left']}: not mirror images (an end is {p['mirror_error']} off; "
                       f"the thinner is {p.get('thinner_radius')} in radius): {p.get('why')}. The game's numbers: "
                       f"right {n.get('right')}, left {n.get('left')}")
    return out


def lopsided_notes(check):
    """The pairs the game's own table gives different numbers that are carried as they are: to be said, not hidden."""
    return [f"hurtboxes {p['right']} and {p['left']}: the game's own table is lopsided (an end is {p['mirror_error']} "
            f"off its twin's mirror image, the capsule {p.get('thinner_radius')} in radius): carried as it is"
            for p in check['pairs'] if p['ok'] and p.get('lopsided_in_the_source')]


SOURCE_ROOT = 'top'         # what an Ultimate table calls the model's root, which no skeleton file lists
RIG_ROOT = '__engine_Top'   # the rig's joint for it (own_skeleton.ROOT_CHAIN[0])


def ecb_six(source_nodes, at):
    """The six of a source's collision joints the engine can hold, when the source lists more (Ivysaur: eight, with
    its bulb's `Flower` and the model's root). Melee draws its diamond round the lowest and highest and the furthest
    back and forward of its six (mpcoll.c:357-372), so the six kept are, first, the joint that makes each side of
    the source's box at rest, then the rest in the source's order. at: {name: (forward, up)} at rest.
    -> (six names in the source's order, [the names left out])"""
    nodes = list(dict.fromkeys(source_nodes))
    if not nodes:
        raise ValueError('the source has no stage-collision joints')
    if len(nodes) <= 6:
        # Melee evaluates extrema across six slots (its own donor repeats a shoulder).
        # Repeating a source point fills the table without changing the collision bounds.
        return nodes + [nodes[-1]] * (6 - len(nodes)), []
    keep = []
    for axis, pick in ((1, min), (1, max), (0, min), (0, max)):
        side = pick(at[n][axis] for n in nodes)
        best = next(n for n in nodes if at[n][axis] == side)      # (a tie: the first in the source's order)
        if best not in keep:
            keep.append(best)
    for n in nodes:
        if len(keep) == 6:
            break
        if n not in keep:
            keep.append(n)
    return [n for n in nodes if n in keep], [n for n in nodes if n not in keep]


def ecb_joints(donor_six, donor_slot, source_nodes, new_slot, index):
    """The six joints the collision diamond is drawn round.
    Melee does not give the six places a meaning: it takes the lowest and highest y and the least and greatest x
    over all six (mpColl_LoadECB_JObj, mpcoll.c:357-372), so the six are a set. The donor's file still keeps an
    order (Marth: head, right shoulder, right shoulder again, right knee, left knee, hip), and the source's list
    is the same order (head, shoulder R, shoulder L, knee R, knee L, hip). Each of the donor's places takes the
    source joint that is the same part of the body (by the two tables' slots); a place whose part is already
    taken (Marth's second right shoulder) takes what the source has left, in the source's order.
    donor_six: the donor's six joints; donor_slot / new_slot: joint -> slot name or None on each rig;
    source_nodes: the source's joints by name. -> ([six new indices], [how each was chosen])"""
    if len(donor_six) != 6 or len(source_nodes) != 6:
        raise ValueError('six joints each side')
    left = list(source_nodes)
    chosen, how = [None] * 6, [None] * 6
    for i, dj in enumerate(donor_six):
        want = donor_slot.get(dj)
        hit = next((n for n in left if want is not None and new_slot.get(index[n]) == want), None)
        if hit is not None:
            left.remove(hit)
            chosen[i], how[i] = index[hit], f'same part ({want})'
    for i in range(6):
        if chosen[i] is None:
            n = left.pop(0)
            chosen[i], how[i] = index[n], "what the source's list had left"
    return chosen, how


def ik_lengths(worlds, joints, ground=0.0):
    """The leg solver's lengths, measured on the rest rig. joints: dict(thigh=(a, b), ...) of joint index pairs
    and foot=the foot joint. -> dict(name: length)"""
    worlds = np.asarray(worlds)
    out = {}
    for name, pair in joints.items():
        if name == 'foot':
            out['foot height'] = float(worlds[pair][1, 3] - ground)
        else:
            a, b = pair
            out[name] = float(np.linalg.norm(worlds[a][:3, 3] - worlds[b][:3, 3]))
    return out


def default_scale(donor, measured_ultimate=None):
    """The drawn scale that keeps a fighter at the size Ultimate gives it beside the donor: the donor's drawn
    height in Melee over the donor's own height in Ultimate. (The new fighter's height cancels: its rig is in
    Ultimate's units, so the factor is the two games' units measured on the fighter both have.)"""
    ultimate = measured_ultimate or donor['ultimate_height']
    return donor['rig_height'] * donor['scale'] / ultimate


def source_height(skeleton_path):
    """y span of an Ultimate skeleton's rest joints."""
    import ssbh_data_py as ssbh
    from .ultimate import skeleton_metadata
    meta = skeleton_metadata(ssbh.skel_data.read_skel(str(skeleton_path)))
    return rig_height(rest_worlds(meta))


def source_pose(root, fighter, frozen, stem, frame='end'):
    """One frame of one of the source's clips as the frozen rig's own local values (helpers included).
    -> ({joint: dict(r, t, s)}, the frame). `frame`: a number, or 'end' for the clip's last."""
    import ssbh_data_py as ssbh
    from . import batch_evaluation as batch
    from . import native_port as core
    from . import rig_benchmark as bench
    from . import rotation_charts, scale_helpers
    from .source_preflight import ANY_BONE, RawSource
    from .ultimate import skeleton_metadata
    src = Path(root) / 'gamedata' / 'fighter' / fighter
    skel = src / 'model' / 'body' / 'c00' / 'model.nusktb'
    raw = RawSource.from_files(skel, src / 'motion' / 'body' / 'c00' / f'{stem}.nuanmb', allow_unbound=ANY_BONE)
    core.sanitize_scale(raw)
    at = float(raw.end if frame == 'end' else frame)
    times = np.array([at])
    from .own_skeleton import source_rig
    source = source_rig(skel, frozen)                   # (less the bones the rig folded: own_skeleton.fold_plan)
    scaled, charted = core.rebuild_helpers(frozen, source)
    target = core.rig_from_meta(frozen)
    compensated = set(frozen.get('provenance', {}).get('scale_helpers', []))
    reference = {j: w for j, w in batch.raw_worlds(raw, times).items() if j in source.world}
    parent_scales = {j: np.array([raw.parts(raw.parent[j], float(f))[2] if raw.parent[j] in raw.tracks
                                  else np.ones(3) for f in times]) for j in compensated}
    worlds = rotation_charts.expand_worlds(charted, scale_helpers.expand_worlds(scaled, reference, parent_scales,
                                                                                compensated))
    for j in target.order:
        if j not in worlds:
            if not j.startswith('__engine_'):
                raise ValueError(f'{j} is not in the clip\'s pose')
            p = target.parent[j]
            worlds[j] = (worlds[p] if p is not None else np.broadcast_to(np.eye(4), (1, 4, 4))).copy()
    vectors = bench.local_vectors(target, [{j: worlds[j][0] for j in target.order}], project_shear=True)
    pose = {j: dict(r=[float(v) for v in vectors[j][0][:3]], t=[float(v) for v in vectors[j][0][3:6]],
                    s=[float(v) for v in vectors[j][0][6:9]]) for j in target.order}
    # the pose put back together must be the clip's
    back = rest_worlds(dict(order=frozen['order'], parent=frozen['parent'], rest=pose))
    error = max(float(np.abs(back[i][:3, 3] - worlds[j][0][:3, 3]).max()) for i, j in enumerate(frozen['order']))
    return pose, at, error


# ------------------------------------------------------------------------------------------ a second reader (census)
class _File:
    """A fighter file read with nothing but `struct`: the reader the writer's work is checked with."""

    def __init__(self, payload):
        self.b = bytes(payload)
        size, self.size, nrel, nroot, nref = struct.unpack_from('>5I', self.b)
        if size != len(self.b):
            raise ValueError('the file is not the length its header says')
        rel = HDR + self.size
        self.relocs = set(struct.unpack_from(f'>{nrel}I', self.b, rel))
        table = rel + 4 * nrel
        strings = table + 8 * (nroot + nref)
        self.roots = {}
        for i in range(nroot):
            off, name = struct.unpack_from('>II', self.b, table + 8 * i)
            end = self.b.index(b'\0', strings + name)
            self.roots[self.b[strings + name:end].decode('ascii', 'replace')] = off
        self.targets = sorted({self.u32(o) for o in self.relocs} | set(self.roots.values()))

    def u8(self, o):
        return self.b[HDR + o]

    def s16(self, o):
        return struct.unpack_from('>h', self.b, HDR + o)[0]

    def u16(self, o):
        return struct.unpack_from('>H', self.b, HDR + o)[0]

    def u32(self, o):
        return struct.unpack_from('>I', self.b, HDR + o)[0]

    def i32(self, o):
        return struct.unpack_from('>i', self.b, HDR + o)[0]

    def f32(self, o):
        return struct.unpack_from('>f', self.b, HDR + o)[0]

    def ptr(self, o):
        return self.u32(o) if o in self.relocs else None

    def end(self, o):
        i = bisect.bisect_right(self.targets, o)
        return self.targets[i] if i < len(self.targets) else self.size

    def tree(self, root, child=8, sibling=12):
        """A joint tree's nodes in the engine's walking order. -> [(offset, parent position or None)]"""
        out, pending, seen = [], [(root, None)], set()
        while pending:
            off, parent = pending.pop()
            if off in seen:
                raise ValueError('a joint tree loops')
            seen.add(off)
            at = len(out)
            out.append((off, parent))
            sib, kid = self.ptr(off + sibling), self.ptr(off + child)
            if sib is not None:
                pending.append((sib, parent))
            if kid is not None:
                pending.append((kid, at))
        return out


def _bits(word, first, count):
    return (word >> (32 - first - count)) & ((1 << count) - 1)


def census(payload, root_name, joints=None, attr_joints=()):
    """Every joint index in a fighter file, and the other things `build` changes, read independently of it.
    -> dict(joints=[dict(consumer, value, kind, live, at)], facts={...})
    kind: JOINT (an index into the costume's joints), SLOT (an index into the table of which joint is which),
    SELECTOR (a script's "the item joint" / "the next special joint"). live: False for a value the engine never
    reads (past a count, or behind one that is zero). joints: the joint count to hold JOINT values against."""
    f = _File(payload)
    if root_name not in f.roots:
        raise ValueError(f'no {root_name} in the file')
    r = f.roots[root_name]
    rows, facts = [], {}

    def add(consumer, value, at, kind='JOINT', live=True, **more):
        rows.append(dict(consumer=consumer, value=int(value), kind=kind, live=live, at=at, **more))

    attrs = f.ptr(r)
    facts['model_scale'] = f.f32(attrs + 0x8C)
    add('attributes.cameraZoomJoint', f.i32(attrs + 0x16C), attrs + 0x16C)
    own = f.ptr(r + 0x04)
    for off, label in attr_joints:
        add(f'ownAttributes.{label}', f.i32(own + off), own + off)

    # +0x08 the model tables: which pieces are drawn, which textures are animated, five named joints
    m = f.ptr(r + 0x08)
    groups, table = f.u32(m), f.ptr(m + 4)
    facts['visibility_groups'] = groups
    shown = []
    for c in range((f.end(table) - table) // 16):
        for mode in range(4):
            g = f.ptr(table + c * 16 + mode * 4)
            if g is None:
                continue
            for i in range(groups):
                variants, v = f.u32(g + i * 8), f.ptr(g + i * 8 + 4)
                for k in range(variants if v is not None else 0):
                    count, e = f.u32(v + k * 8), f.ptr(v + k * 8 + 4)
                    shown.append(dict(costume=c, mode=mode, group=i, variant=k,
                                      pieces=[f.u8(e + n) for n in range(count)] if e is not None else []))
    facts['visibility'] = shown
    textures, tex = f.u32(m + 8), f.ptr(m + 0x0C)
    facts['texture_slots'] = {}
    if tex is not None:
        for c in range((f.end(tex) - tex) // 4):
            p = f.ptr(tex + c * 4)
            if p is not None:
                facts['texture_slots'][c] = [f.u16(p + 2 * k) for k in range(textures)]
    facts['texture_count'] = textures
    for i, name in enumerate(('itemHold', 'shield', 'topOfHead', 'leftFoot', 'rightFoot')):
        add(f'modelLookup.{name}', f.u8(m + 0x10 + i), m + 0x10 + i)

    # +0x10 / +0x18 one pair of bytes an action: (frames to blend in, which dynamics clip)
    for slot, label in ((0x10, 'actions'), (0x18, 'demo actions')):
        p = f.ptr(r + slot)
        if p is not None:
            n = (f.end(p) - p) // 2
            facts[f'dynamics_clip_bytes.{label}'] = sum(1 for i in range(n) if f.u8(p + 2 * i + 1))
            facts[f'blend_bytes.{label}'] = [f.u8(p + 2 * i) for i in range(n)]

    # +0x1C hand and face regions
    p = f.ptr(r + 0x1C)
    facts['parts'] = []
    for i in range((f.end(p) - p) // 4 if p is not None else 0):
        e = f.ptr(p + 4 * i)
        if e is None:
            continue
        start, count, entries, anims = f.s16(e), f.s16(e + 2), f.ptr(e + 4), f.ptr(e + 8)
        add(f'part[{i}].start', start, e)
        room = f.end(entries) - entries if entries is not None else 0
        for k in range(room):
            add(f'part[{i}].entry[{k}]', f.u8(entries + k), entries + k, live=k < count)
        trees = []
        for k in range((f.end(anims) - anims) // 4 if anims is not None else 0):
            a = f.ptr(anims + 4 * k)
            if a is not None:
                nodes = f.tree(a, child=0, sibling=4)
                trees.append(dict(nodes=len(nodes), animated=sum(1 for o, _ in nodes if f.ptr(o + 8) is not None)))
        facts['parts'].append(dict(part=i, start=start, count=count, room=room, poses=trees))

    # +0x20 the shield pose: a skeleton of its own
    p = f.ptr(r + 0x20)
    if p is not None and f.ptr(p) is not None:
        nodes = f.tree(f.ptr(p))
        facts['shield_pose'] = dict(
            nodes=len(nodes), parents=[q for _, q in nodes],
            rest=[[f.f32(o + 0x14 + 4 * k) for k in range(9)] for o, _ in nodes])

    # +0x2C dynamics
    p = f.ptr(r + 0x2C)
    if p is not None:
        count, descs, bubbles, bub = f.u32(p), f.ptr(p + 4), f.u32(p + 8), f.ptr(p + 0x0C)
        facts['dynamics'] = dict(count=count, bubbles=bubbles)
        room = (f.end(descs) - descs) // 0x18 if descs is not None else 0
        for i in range(room):
            add(f'dynamics[{i}].joint', f.i32(descs + i * 0x18), descs + i * 0x18, live=i < count)
        for i in range(bubbles if bub is not None else 0):
            add(f'dynamicsBubble[{i}].joint', f.i32(bub + i * 0x14), bub + i * 0x14)

    # +0x30 hurtboxes
    p = f.ptr(r + 0x30)
    count, arr = f.u32(p), f.ptr(p + 4)
    facts['hurtboxes'] = []
    for i in range((f.end(arr) - arr) // 0x28):
        o = arr + i * 0x28
        add(f'hurtbox[{i}]', f.u32(o), o, live=i < count)
        if i < count:
            facts['hurtboxes'].append(dict(joint=f.u32(o), height=f.u32(o + 4), grabbable=f.u32(o + 8),
                                           a=[f.f32(o + 0x0C + 4 * k) for k in range(3)],
                                           b=[f.f32(o + 0x18 + 4 * k) for k in range(3)], radius=f.f32(o + 0x24)))
    facts['hurtbox_count'] = count

    p = f.ptr(r + 0x34)
    add('centre', f.i32(p), p)
    facts['centre_size'] = f.f32(p + 4)
    p = f.ptr(r + 0x38)
    facts['coins'] = []
    for i in range((f.end(p) - p) // 0x14 if p is not None else 0):
        o = p + i * 0x14
        add(f'coin[{i}]', f.i32(o), o)
        facts['coins'].append(dict(joint=f.i32(o), offset=[f.f32(o + 4 + 4 * k) for k in range(3)],
                                   size=f.f32(o + 0x10)))
    p = f.ptr(r + 0x44)
    for i in range(6):
        add(f'ecb[{i}]', f.s16(p + 2 * i), p + 2 * i)
    p = f.ptr(r + 0x54)
    for i, name in enumerate(('head', 'rightArm', 'leftLeg', 'rightLeg', 'leftArm')):
        add(f'special.{name}', f.i32(p + 4 * i), p + 4 * i)
    p = f.ptr(r + 0x58)
    if p is not None:
        for off, name in IK_BYTES.items():
            add(f'ik.{name}', f.u8(p + off), p + off)
        facts['ik'] = {f'0x{o:02X}': f.f32(p + o) for o in (0x04, 0x0C, 0x14, 0x18, 0x20, 0x28, 0x2C, 0x30)}

    # +0x5C the metal body: a skeleton of its own, with pieces
    p = f.ptr(r + 0x5C)
    if p is not None:
        nodes, pieces = f.tree(p), 0
        for o, _ in nodes:
            d = f.ptr(o + 0x10)
            while d is not None:
                pieces += 1
                d = f.ptr(d + 4)
        facts['metal'] = dict(nodes=len(nodes), pieces=pieces)

    # the scripts: every block an action or a demo action reaches, through subroutines and jumps
    entries = []
    for slot, label in ((0x0C, 'action'), (0x14, 'demo')):
        t = f.ptr(r + slot)
        for i in range((f.end(t) - t) // 0x18 if t is not None else 0):
            s = f.ptr(t + i * 0x18 + 0x0C)
            if s is not None:
                entries.append((f'{label}[{i}]', s))
            snap = _bits(f.u32(t + i * 0x18 + 0x10), *ACTION_FLAG_JOINT)
            if snap:
                add(f'{label}[{i}].unblendedJoint', snap, t + i * 0x18 + 0x10)
    blocks, pending, stopped = {}, list(entries), []
    while pending:
        label, off = pending.pop(0)
        if off in blocks:
            continue
        blocks[off] = label
        pos, end, ended = off, f.end(off), False
        while pos < end:
            code = f.u8(pos) >> 2
            size = CMD_SIZE.get(code)
            if size is None:
                stopped.append(dict(block=off, at=pos, code=code))
                break
            if pos + size > end:
                break
            word = f.u32(pos)
            where = f'{label} block 0x{off:X} +0x{pos - off:X}'
            if code in (CMD_SUBROUTINE, CMD_GOTO):
                target = f.ptr(pos + 4)
                if target is not None:
                    pending.append((label, target))
            elif code in JOINT_FIELD:
                first, count = JOINT_FIELD[code]
                value, kind = _bits(word, first, count), 'JOINT'
                if code == CMD_BONE_PHYSICS and value >= 1 << 25:
                    value -= 1 << 26
                if code in COMMON_FLAG and _bits(word, COMMON_FLAG[code], 1):
                    kind = 'SLOT'
                if code == CMD_GFX and _bits(word, GFX_HEAD_FLAG, 1):
                    kind = 'HEAD'
                elif code == CMD_GFX and kind == 'JOINT' and value in SPECIAL_GFX_BONES:
                    kind = 'SELECTOR'
                add(f'script {CMD_NAME[code]} @0x{pos:X}', value, pos, kind=kind, live=not ended,
                    command=CMD_NAME[code], where=where)
            elif code == CMD_MODEL_STATE:
                facts.setdefault('model_state_groups', Counter())[_bits(word, 6, 7)] += 1
            elif code == CMD_TEX_ANIM:
                used = facts.setdefault('texture_slots_used', Counter())
                used[_bits(word, 7, 7)] += 1
                if _bits(word, 6, 1):
                    used[_bits(word, 14, 7)] += 1
            elif code == CMD_PART_ANIM:
                facts.setdefault('part_poses_used', Counter())[(_bits(word, 6, 7), _bits(word, 13, 7))] += 1
            elif code == CMD_SWORD_TRAIL:
                state = word & 0xFF
                key = 'item' if _bits(word, 6, 1) and state != 0xFF else ('off' if state == 0xFF else 'own')
                facts.setdefault('sword_trail', Counter())[key] += 1
            if code == CMD_END:
                ended = True
            pos += size
    facts['script_blocks'] = len(blocks)
    facts['script_entries'] = len(entries)
    facts['script_stopped'] = stopped
    for key in ('model_state_groups', 'texture_slots_used', 'part_poses_used', 'sword_trail'):
        facts[key] = {str(k): v for k, v in sorted(facts.get(key, {}).items(), key=lambda kv: str(kv[0]))}
    if joints is not None:
        facts['out_of_range'] = [row['consumer'] for row in rows
                                 if row['kind'] == 'JOINT' and not 0 <= row['value'] < joints]
    return dict(joints=rows, facts=facts)


def costume_census(payload):
    """What the costume has to be named by: its joints, pieces and textures (in the order the engine counts
    them: every piece of every joint, each piece's textures in turn), and whether it has a texture-animation
    tree. -> dict(root, joints, pieces, textures, material_tree)"""
    f = _File(payload)
    names = [n for n in f.roots if n.endswith('_joint')
             and not n.endswith(('_matanim_joint', '_anim_joint', '_shapeanim_joint'))]
    if len(names) != 1:
        raise ValueError('one joint tree is expected in a costume')
    nodes = f.tree(f.roots[names[0]])
    pieces = textures = 0
    for off, _ in nodes:
        d = f.ptr(off + 0x10)
        while d is not None:
            pieces += 1
            mat = f.ptr(d + 8)
            t = f.ptr(mat + 8) if mat is not None else None
            while t is not None:
                textures += 1
                t = f.ptr(t + 4)
            d = f.ptr(d + 4)
    return dict(root=names[0], joints=len(nodes), parents=[p for _, p in nodes], pieces=pieces, textures=textures,
                material_tree=any(n.endswith('_matanim_joint') for n in f.roots))


# ------------------------------------------------------------------------------------------------------ the writer
class _Edit:
    """The fighter file being rewritten: in-place writes, and the two things that move bytes (a pointer that
    becomes null or stops being one, and new bytes on the end)."""

    def __init__(self, payload):
        from vault.echo.subactions import FighterDat
        self.ft = FighterDat(bytes(payload))
        self.dat = self.ft.dat
        self.root = self.ft.ft_root

    def u8(self, o):
        return self.dat.buf[HDR + o]

    def s16(self, o):
        return struct.unpack_from('>h', self.dat.buf, HDR + o)[0]

    def set_u8(self, o, v):
        if not 0 <= v <= 255:
            raise ValueError(f'{v} does not fit a byte')
        self.dat.buf[HDR + o] = v

    def set_s16(self, o, v):
        struct.pack_into('>h', self.dat.buf, HDR + o, v)

    def set_u16(self, o, v):
        struct.pack_into('>H', self.dat.buf, HDR + o, v)

    def write(self, o, blob):
        self.dat.buf[HDR + o:HDR + o + len(blob)] = blob

    def set_pointers(self, values):
        """values: {slot: target or None}. A slot given a target becomes a pointer; one given None is zeroed and
        stops being one."""
        relocs = set(self.dat.relocs)
        for slot, target in values.items():
            self.dat.set_u32(slot, 0 if target is None else target)
            (relocs.discard if target is None else relocs.add)(slot)
        if relocs != self.dat.relocs:
            self.dat._rebuild(bytes(self.dat.buf[HDR:HDR + self.dat.data_size]), relocs)

    def bytes(self):
        return self.dat.to_bytes()


def links_past(nodes, ptr, keep, child=8, sibling=12):
    """The links to take out of a joint tree so that only its first `keep` nodes are left, in the engine's walking
    order: {slot: None} (for `_Edit.set_pointers`). `nodes`: [(offset, parent position)] in that order
    (`_File.tree`); `ptr(slot)`: where the link at a slot points, or None."""
    place = {offset: i for i, (offset, _parent) in enumerate(nodes)}
    return {offset + link: None for offset, _parent in nodes[:keep] for link in (child, sibling)
            if ptr(offset + link) is not None and place[ptr(offset + link)] >= keep}


def _node(flags, rest):
    """One joint of a pose tree (HSD_Joint, 0x40 bytes), its two links left empty."""
    blob = bytearray(0x40)
    struct.pack_into('>I', blob, 4, flags)
    struct.pack_into('>9f', blob, 0x14, *rest['r'], *rest['s'], *rest['t'])
    return blob


def build(pl_bytes, frozen, lookup, root, fighter, donor='Marth', costume_bytes=None, *, model_scale=None,
          item_hold=None, shield_pose=None, grabbable=None, texture_slots=None, keep_metal=False, source=None,
          donor_ultimate_skeleton=None, body_points=None, pieces=None):
    """The donor's fighter data, rewritten for the frozen rig. -> (the new file, a report)

    pl_bytes       the donor's fighter data (Pl??.dat)
    frozen         the frozen rig (order, parent, rest)
    lookup         the rig's table of which joint is which (`forward`: slot -> joint, `reverse`: joint -> slot)
    root           the folder that holds `gamedata/fighter/<fighter>` (the source game's own files)
    costume_bytes  the new costume, to hold the piece and texture numbers against (not changed)
    model_scale    the drawn scale (attributes +0x8C). None: the size Ultimate gives the fighter beside the donor.
    item_hold      the joint an item is held at, by name. None: the shared fighters.item_hold selector (explicit choice, hold slot, then hand).
    shield_pose    {joint: dict(r, t, s)} for the stick-centred shield pose. None: the rest pose.
    grabbable      names of the joints whose hurtbox a grab can take. None: all of them.
    texture_slots  which of the costume's textures the donor's eye-animation slots name. None: 0, 1, ...
    keep_metal     leave the donor's metal body in (it is skinned to the donor's joints by number).
    source         dict(hurt, ecb) in place of reading the source's vl.prc
    donor_ultimate_skeleton  the donor's own Ultimate skeleton, to measure again in place of the kept number
    body_points    (points, the joint each follows most): the body at rest, for the hurtbox check
    pieces         {'high': [...], 'low': [...]}: the costume's pieces by the engine's numbers, the body and its
                   low-detail copy (`skin_cost.pieces`). None: no piece is named, so none is ever hidden, and the
                   whole body is drawn again for the shadow. With 'groups' ([[[piece, ...] a choice] a group]: the
                   parts the game's clips show and hide, `own_faces.pieces`) the body is the first group and each
                   of those a group after it, in tables of their own (`model_lists`).
    """
    if donor not in DONOR:
        raise ValueError(f'no donor facts for {donor}')
    D = DONOR[donor]
    order = list(frozen['order'])
    n = len(order)
    index = {j: i for i, j in enumerate(order)}
    parents = [None if frozen['parent'][j] is None else index[frozen['parent'][j]] for j in order]
    forward, reverse = list(lookup['forward']), list(lookup['reverse'])
    if len(forward) != len(SLOTS) or len(reverse) != n or not 1 <= n <= MAX_PARTS:
        raise ValueError('the lookup is not for this rig, or the rig is larger than a fighter may be')
    links = tree_links(parents)
    worlds = rest_worlds(frozen)
    height = rig_height(worlds)
    slot_of = {name: i for i, name in enumerate(SLOTS)}
    new_slot = {j: SLOTS[s] for j, s in enumerate(reverse) if s != NONE}
    donor_slot = {}
    for s, j in enumerate(D['lookup']):
        if j != NONE:
            donor_slot[j] = SLOTS[s]

    def bound(name):
        return None if forward[slot_of[name]] == NONE else forward[slot_of[name]]

    ed = _Edit(pl_bytes)
    if ed.ft.ft_root_name != D['root']:
        raise ValueError(f'the file is {ed.ft.ft_root_name}, not {D["root"]}')
    dat, r = ed.dat, ed.root
    report = dict(schema='own-data-v1', fighter=fighter, donor=donor, joints=n, donor_joints=D['joints'])

    # the item-hold joint, and the map every plain index goes through
    model = dat.ptr(r + 0x08)
    donor_item = ed.u8(model + 0x10)
    told = fighters.get(fighter, 'item_hold')
    name = item_hold or told
    if name is not None and name not in index:
        raise ValueError(f'item-hold joint {name} is not on the rig')
    if item_hold:
        hold_source = 'the parameter'
    else:
        bound_names = {slot: order[bound(slot)] for slot in ('rHave', 'lHave', 'rHand', 'lHand')
                       if bound(slot) is not None}
        name, hold_source = fighters.item_hold(fighter, bound_names, set(order))
        if told:
            hold_source = "the fighter's item_hold in fighters.py"
    if name is None:
        raise ValueError('the rig has no joint to hold an item at')
    item_target = index[name]
    jmap = joint_map(D, forward, item_joint=donor_item, item_target=item_target)
    used = Counter()

    def go(j, what):
        if not 0 <= j < D['joints']:
            raise ValueError(f'{what}: {j} is not one of the donor\'s joints')
        used[j] += 1
        return jmap[j]['to']

    # ---- 1. hurtboxes: the source's own
    vl = Path(root) / 'gamedata' / 'fighter' / fighter / 'param' / 'vl.prc'
    if source is None and not vl.is_file():
        from . import source_game                       # (a game written out by its own reader gives the tables)
        if (source_game.folder(root, fighter) / 'game.json').is_file():
            source = source_game.tables(root, fighter)
    src = source or source_tables(vl.read_bytes(), order)
    folded = ((frozen.get('provenance') or {}).get('folded') or {})
    rehomed = []
    if any(r['bone'] in folded for r in src['hurt']):
        # a capsule on a bone the rig folded rides the bone it went into (`rehome_folded`)
        import ssbh_data_py as ssbh
        from . import native_port as core
        from .ultimate import skeleton_metadata
        skel = Path(root) / 'gamedata' / 'fighter' / fighter / 'model' / 'body' / 'c00' / 'model.nusktb'
        whole = core.rig_from_meta(skeleton_metadata(ssbh.skel_data.read_skel(str(skel))))
        hurt, rehomed = rehome_folded(src['hurt'], folded, whole.world)
        src = dict(src, hurt=hurt)
    capsules = hurtboxes(src['hurt'], order, grabbable)
    bank = dat.ptr(r + 0x30)
    room = (dat.struct_end(dat.ptr(bank + 4)) - dat.ptr(bank + 4)) // 0x28
    was_count = dat.u32(bank)
    if len(capsules) <= room:
        arr = dat.ptr(bank + 4)
        for i in range(room):
            c = capsules[min(i, len(capsules) - 1)]                 # a spare place repeats the last: nothing stale
            ed.write(arr + i * 0x28, struct.pack('>III7f', c['joint'], c['height'], c['grabbable'], *c['a'],
                                                 *c['b'], c['radius']))
        dat.set_u32(bank, len(capsules))
        how = f'in place ({room} places, {len(capsules)} used)'
    else:
        from . import compat
        compat.install()
        from .hurtbox_bank import apply as write_bank
        new, _ = write_bank(ed.bytes(), root_name=D['root'], joint_count=n, capsules=capsules)
        ed = _Edit(new)
        dat, r = ed.dat, ed.root
        how = f'a new bank on the end ({room} places were too few)'
    hurt_joints = {c['joint'] for c in capsules}
    points = owner = None
    if body_points is not None:
        points, owner = body_points
    check = capsule_check(capsules, order, parents, worlds, points, owner,
                          accepted=tuple(fighters.get(fighter, 'lopsided') or ()))
    report['hurtboxes'] = dict(
        source='hit_data in the source\'s vl.prc', written=how, donor_count=was_count, rehomed=rehomed,
        table=[dict(c, name=order[c['joint']], source_height=s['height'], source_part=s['part'])
               for c, s in zip(capsules, src['hurt'])],
        heights=HEIGHTS, check=check,
        grabbable='every capsule (the source keeps no such flag)' if grabbable is None else sorted(grabbable),
        first="capsule 0 is the one a ground hazard is charged to (ftCo_Bury.c:91): the source's first, on "
              + order[capsules[0]['joint']])

    # ---- 2. the collision diamond's six joints: the source's own
    ecb = dat.ptr(r + 0x44)
    donor_six = [ed.s16(ecb + 2 * i) for i in range(6)]
    kept, dropped = ecb_six([e['bone'] for e in src['ecb']],
                            {e['bone']: (float(worlds[index[e['bone']]][2, 3]), float(worlds[index[e['bone']]][1, 3]))
                             for e in src['ecb']})
    six, why = ecb_joints(donor_six, donor_slot, kept, new_slot, index)
    for i, j in enumerate(six):
        ed.set_s16(ecb + 2 * i, j)
    xs = [float(worlds[j][2, 3]) for j in six]
    ys = [float(worlds[j][1, 3]) for j in six]
    report['ecb'] = dict(
        source='map_coll_data in the source\'s vl.prc', donor=donor_six,
        donor_parts=[donor_slot.get(j) for j in donor_six], source_nodes=[e['bone'] for e in src['ecb']],
        written=six, names=[order[j] for j in six], how=why, left_out=dropped,
        source_offsets_nonzero=[e['bone'] for e in src['ecb'] if any(abs(v) > 1e-9 for v in e['offset'])],
        rest_box=dict(forward=[round(min(xs), 3), round(max(xs), 3)], up=[round(min(ys), 3), round(max(ys), 3)]),
        meaning='Melee takes the lowest and highest of all six, and the furthest back and forward: the places '
                'have no meaning of their own (mpcoll.c:357-372). Kept in the donor\'s order all the same.',
        floats_left=[round(dat.f32(ecb + 0x0C + 4 * i), 3) for i in range(4)])

    # ---- 3. centre, the five special joints; 7. the camera's joint, the donor's own attribute joints, the five
    #         named joints of the model tables
    plain = []

    def repoint(label, at, width, special=None):
        was = {1: ed.u8, 2: ed.s16, 4: dat.i32}[width](at)
        now = special if special is not None else go(was, label)
        {1: ed.set_u8, 2: ed.set_s16, 4: dat.set_i32}[width](at, now)
        row = jmap.get(was, {})
        plain.append(dict(consumer=label, was=was, now=now, name=order[now],
                          tier='ITEM' if special is not None else row.get('tier'),
                          via='item hold' if special is not None else row.get('via')))

    centre = dat.ptr(r + 0x34)
    repoint('centre', centre, 4)
    ids = dat.ptr(r + 0x54)
    for i, label in enumerate(('head', 'rightArm', 'leftLeg', 'rightLeg', 'leftArm')):
        repoint(f'special.{label}', ids + 4 * i, 4)
    attrs = dat.ptr(r)
    repoint('attributes.cameraZoomJoint', attrs + 0x16C, 4)
    own = dat.ptr(r + 0x04)
    for off, label in D['attr_joints']:
        repoint(f'ownAttributes.{label}', own + off, 4)
    model = dat.ptr(r + 0x08)
    repoint('modelLookup.itemHold', model + 0x10, 1, special=item_target)
    for i, label in enumerate(('shield', 'topOfHead', 'leftFoot', 'rightFoot'), 1):
        repoint(f'modelLookup.{label}', model + 0x10 + i, 1)
    report['plain'] = plain
    report['centre'] = dict(size_left=dat.f32(centre + 4),
                            why='2.0 on almost every fighter of Melee\'s, large or small: not a measure of the body')
    report['item_hold'] = dict(joint=item_target, name=order[item_target], donor_joint=donor_item,
                               chosen_by=hold_source)
    # the shield's joint is SCALED to the shield's size every frame (ftCo_Guard.c:ftCo_80091D58): whatever hangs
    # under it grows with the shield (Slap City's Ittle, whose shield fell to YRot: six times her size). PORT_CHECKLIST 11.42
    shield_at = next(p['now'] for p in plain if p['consumer'] == 'modelLookup.shield')
    report['shield'] = dict(joint=shield_at, name=order[shield_at],
                            under=[order[j] for j, p in enumerate(parents) if p == shield_at],
                            why='Melee scales this joint to the shield\'s size every frame: it must have nothing under it')

    # ---- 4. the leg solver: ten joints through the map, lengths measured on this rig
    ik = dat.ptr(r + 0x58)
    report['ik'] = None
    if ik is not None:
        donor_bytes = {off: ed.u8(ik + off) for off in IK_BYTES}
        for off, label in IK_BYTES.items():
            repoint(f'ik.{label}', ik + off, 1)
        new_bytes = {off: ed.u8(ik + off) for off in IK_BYTES}
        hand = go(D['lookup'][slot_of['rHand']], 'the forearm\'s far end')
        measure = {}
        for off, (label, a, b) in IK_SEGMENTS.items():
            measure[label] = (new_bytes[a], hand if b == 'rHand' else new_bytes[b])
        measure['foot'] = new_bytes[0x10]
        lengths = ik_lengths(worlds, measure, ground=float(worlds[0][1, 3]))
        left = ik_lengths(worlds, dict(thigh=(new_bytes[0x01], new_bytes[0x09]), shin=(new_bytes[0x09], new_bytes[0x11]),
                                       foot=new_bytes[0x11]), ground=float(worlds[0][1, 3]))
        rows = []
        for off, (label, _, _) in IK_SEGMENTS.items():
            rows.append(dict(field=f'0x{off:02X}', what=label, was=dat.f32(ik + off), now=lengths[label],
                             between=[order[j] for j in measure[label]]))
            dat.set_f32(ik + off, lengths[label])
        rows.append(dict(field=f'0x{IK_FOOT_HEIGHT:02X}', what='foot joint above the ground',
                         was=dat.f32(ik + IK_FOOT_HEIGHT), now=lengths['foot height'], between=[order[measure['foot']]]))
        dat.set_f32(ik + IK_FOOT_HEIGHT, lengths['foot height'])
        report['ik'] = dict(joints={IK_BYTES[o]: dict(was=donor_bytes[o], now=new_bytes[o], name=order[new_bytes[o]])
                                    for o in IK_BYTES},
                            lengths=rows, left_side={k: round(v, 4) for k, v in left.items()},
                            left_alone={f'0x{o:02X}': dat.f32(ik + o) for o in IK_UNTOUCHED})

    # ---- 5. hand and face regions: the joints rebuilt, the donor's poses for them emptied
    parts = dat.ptr(r + 0x1C)
    report['parts'] = []
    emptied = {}
    for i in range((dat.struct_end(parts) - parts) // 4 if parts is not None else 0):
        e = dat.ptr(parts + 4 * i)
        if e is None:
            continue
        anchor_slot = PART_ANCHOR.get(i)
        anchor = bound(anchor_slot) if anchor_slot else None
        if anchor is None:
            anchor = go(ed.s16(e), f'part {i}')
        entries = dat.ptr(e + 4)
        capacity = ed.s16(e + 2) if entries is not None else 0      # the donor's own count: the list has no slack
        members, dropped = region(parents, order, anchor, capacity, skip_anchor=i in PART_SKIPS_ANCHOR)
        was = dict(start=ed.s16(e), entries=[ed.u8(entries + k) for k in range(capacity)])
        ed.set_s16(e, anchor)
        ed.set_s16(e + 2, len(members))
        for k in range(capacity):                                   # a place past the last member repeats it
            ed.set_u8(entries + k, members[min(k, len(members) - 1)] if members else anchor)
        anims = dat.ptr(e + 8)
        poses = 0
        for k in range((dat.struct_end(anims) - anims) // 4 if anims is not None else 0):
            a = dat.ptr(anims + 4 * k)
            if a is not None:
                poses += 1
                for field in (0, 4, 8, 12):                 # child, next, the animation itself, its constraint
                    emptied[a + field] = None
        report['parts'].append(dict(part=i, anchor=order[anchor], anchor_slot=anchor_slot, was=was,
                                    members=[order[m] for m in members], dropped=[order[m] for m in dropped],
                                    room=capacity, poses_emptied=poses))
    ed.set_pointers(emptied)

    # ---- 6. dynamics off: the count (ftCo_8009CF84 and every loop after it run on it), and each action's choice
    #         of dynamics clip. The byte beside it is how many frames the action blends in over (fighter.c:1281):
    #         that one stays.
    phys = dat.ptr(r + 0x2C)
    report['dynamics'] = None
    if phys is not None:
        was = dat.u32(phys)
        descs = dat.ptr(phys + 4)
        dead = []
        for i in range((dat.struct_end(descs) - descs) // 0x18 if descs is not None else 0):
            j = dat.i32(descs + i * 0x18)
            dat.set_i32(descs + i * 0x18, go(j, f'dynamics {i}'))
            dead.append(dict(was=j, now=jmap[j]['to'], name=order[jmap[j]['to']], tier=jmap[j]['tier']))
        dat.set_u32(phys, 0)
        cleared = {}
        for slot, label in ((0x10, 'actions'), (0x18, 'demo actions')):
            p = dat.ptr(r + slot)
            count = 0
            for i in range((dat.struct_end(p) - p) // 2 if p is not None else 0):
                if ed.u8(p + 2 * i + 1):
                    ed.set_u8(p + 2 * i + 1, 0)
                    count += 1
            cleared[label] = count
        report['dynamics'] = dict(chains_was=was, chains_now=0, bubbles=dat.u32(phys + 8), unused_descriptors=dead,
                                  clip_bytes_cleared=cleared)

    # ---- 10. the drawn scale (before the coin spheres, which are sized by it)
    donor_scale = dat.f32(attrs + 0x8C)
    measured = None
    if donor_ultimate_skeleton is not None and Path(donor_ultimate_skeleton).exists():
        measured = source_height(donor_ultimate_skeleton)
    scale = float(model_scale) if model_scale is not None else default_scale(D, measured)
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('the drawn scale must be a positive number')
    dat.set_f32(attrs + 0x8C, scale)
    report['scale'] = dict(
        written=scale, chosen_by='the parameter' if model_scale is not None else
        'default: the donor\'s drawn height in Melee over its height in Ultimate',
        rig_height=height, drawn_height=height * scale, donor_rig_height=D['rig_height'], donor_scale=donor_scale,
        donor_drawn_height=D['rig_height'] * donor_scale, donor_ultimate_height=D['ultimate_height'],
        donor_ultimate_height_measured_now=measured, drawn_with_donor_scale=height * donor_scale,
        tallest_joint=order[int(np.argmax(worlds[:, 1, 3]))])

    # ---- 7. coin spheres: the donor's, moved to this body's size. A sphere's place goes through its joint (so it
    #         is in the rig's units); its size does not (ft_07C6.c:24-31, lbColl_8000A1A8 takes the size and the
    #         player's own scale), so it is in drawn units.
    coins = dat.ptr(r + 0x38)
    report['coins'] = []
    if coins is not None:
        ratio = height / D['rig_height']
        drawn = height * scale / (D['rig_height'] * donor_scale)
        for i in range((dat.struct_end(coins) - coins) // 0x14):
            o = coins + i * 0x14
            was_joint = dat.i32(o)
            now = go(was_joint, f'coin sphere {i}')
            off = np.array([dat.f32(o + 4 + 4 * k) for k in range(3)])
            # the donor's offsets are plain "up" (its hip and root joints stand square); this joint may not
            local = np.linalg.solve(worlds[now][:3, :3], off * ratio)
            size = dat.f32(o + 0x10)
            dat.set_i32(o, now)
            for k in range(3):
                dat.set_f32(o + 4 + 4 * k, float(local[k]))
            dat.set_f32(o + 0x10, size * drawn)
            centre_at = worlds[now] @ np.r_[local, 1.0]
            report['coins'].append(dict(was=dict(joint=was_joint, offset=[round(float(v), 3) for v in off], size=size),
                                        joint=now, name=order[now], offset=[round(float(v), 4) for v in local],
                                        size=size * drawn, rest_centre=[round(float(v), 3) for v in centre_at[:3]],
                                        tier=jmap[was_joint]['tier']))

    # ---- 7. the shield pose: a skeleton of its own, walked beside the fighter's from its second joint on
    #         (ftCo_Guard.c:216-227, ftAnim_8006FA58). The donor's nodes are used again and more put on the end.
    holder = dat.ptr(r + 0x20)
    report['shield_pose'] = None
    if holder is not None and dat.ptr(holder) is not None:
        old = _File(ed.bytes()).tree(dat.ptr(holder))
        flags = dat.u32(old[0][0] + 4)
        base = (dat.data_size + 0x1F) // 0x20 * 0x20
        at = [old[i][0] if i < len(old) else base + (i - len(old)) * 0x40 for i in range(n)]
        pose = {j: dict(frozen['rest'][j]) for j in order}
        given = 0
        for j, v in (shield_pose or {}).items():
            if j not in index:
                raise ValueError(f'shield pose: {j} is not a joint of the rig')
            pose[j] = dict(r=list(v['r']), t=list(v['t']), s=list(v['s']))
            given += 1
        new_blob, new_pointers, pointers = bytearray(max(0, n - len(old)) * 0x40), [], {}
        for i, j in enumerate(order):
            node = _node(flags, pose[j])
            child, nxt = links[i]
            for field, target in ((8, child), (12, nxt)):
                if target is not None:
                    struct.pack_into('>I', node, field, at[target])
                if i < len(old):
                    pointers[at[i] + field] = None if target is None else at[target]
                elif target is not None:
                    new_pointers.append(at[i] - base + field)
            if i < len(old):
                ed.write(at[i], bytes(node))
            else:
                new_blob[at[i] - base:at[i] - base + 0x40] = node
        for i in range(n, len(old)):                        # a smaller rig: the donor's spare nodes are cut loose
            pointers[old[i][0] + 8] = pointers[old[i][0] + 12] = None
        ed.set_pointers(pointers)
        if new_blob:
            got = dat.append_struct(bytes(new_blob), new_pointers, align=0x20)
            if got != base:
                raise ValueError('the new shield-pose joints did not land where they were pointed at')
        moved = sum(1 for j in order if any(abs(a - b) > 1e-6 for k in 'rts'
                                            for a, b in zip(pose[j][k], frozen['rest'][j][k])))
        report['shield_pose'] = dict(nodes_was=len(old), nodes_now=n, reused=min(n, len(old)),
                                     added=max(0, n - len(old)), joints_given=given, joints_off_rest=moved,
                                     pose='the rest pose' if not given else 'given')

    # ---- 7. the metal body: a third skeleton, the donor's, whose pieces are skinned to the donor's joints by
    #         number (ft_800C85B8 pairs its nodes with the fighter's joints by counting). Its pieces are taken off;
    #         the list of which to show is emptied with the others below.
    metal = dat.ptr(r + 0x5C)
    report['metal'] = None
    if metal is not None:
        before = _File(ed.bytes())
        nodes = before.tree(metal)
        with_pieces = [o for o, _ in nodes if dat.ptr(o + 0x10) is not None]
        cut = 0
        if not keep_metal:
            ed.set_pointers({o + 0x10: None for o in with_pieces})
            if len(nodes) > n:
                # A rig with FEWER joints than the donor (found on Falco, 89 to Marth's 90; Wolf and Duck Hunt have
                # more): the donor's metal skeleton would have nodes left over, each paired by counting with a
                # joint the fighter does not have. The tree is cut after its first n nodes: every link from one of
                # those to a later node is taken out. A node is only ever reached from an earlier one (its parent,
                # or the sibling before it), so what is left is exactly the first n, in the same order.
                ed.set_pointers(links_past(nodes, before.ptr, n))
                cut = len(nodes) - len(_File(ed.bytes()).tree(metal))
                if len(nodes) - cut != n:
                    raise ValueError(f"the donor's metal skeleton did not cut to the rig's {n} joints")
        left = len(nodes) - cut
        report['metal'] = dict(nodes=left, donor_nodes=len(nodes), cut=cut, joints_with_pieces=len(with_pieces),
                               kept=bool(keep_metal),
                               note='its joints past the rig\'s would be read off the end' if left > n else
                               'its nodes pair with the rig\'s first %d joints; with no pieces that moves nothing'
                               % left + (f' ({cut} nodes past the rig\'s last joint were cut off: the rig has fewer '
                                         'joints than the donor)' if cut else ''))

    # ---- 8. the scripts
    report['scripts'] = _scripts(ed, D, jmap, go, forward, reverse, parents, hurt_joints, order, n)

    # ---- 9. the model tables: nothing of the donor's costume is shown or hidden, the texture slots name textures
    #         the costume has
    model = dat.ptr(r + 0x08)
    groups, table = dat.u32(model), dat.ptr(model + 4)
    modes = ('high detail', 'low detail', 'metal body', 'body while metal')
    emptied_lists, seen = [], set()
    for c in range((dat.struct_end(table) - table) // 16):
        for mode in range(4):
            g = dat.ptr(table + c * 16 + mode * 4)
            if g is None or (mode == 2 and keep_metal):
                continue
            for i in range(groups):
                variants, v = dat.u32(g + i * 8), dat.ptr(g + i * 8 + 4)
                for k in range(variants if v is not None else 0):
                    if v + k * 8 in seen:
                        continue
                    seen.add(v + k * 8)
                    count, e = dat.u32(v + k * 8), dat.ptr(v + k * 8 + 4)
                    emptied_lists.append(dict(costume=c, mode=modes[mode], group=i, variant=k,
                                              was=[ed.u8(e + x) for x in range(count)] if e is not None else []))
                    dat.set_u32(v + k * 8, 0)
    # the pieces the engine shows and hides as a set: the body in the ordinary pass, its low-detail copy in the
    # shadow's (and a reflection's, and the off-screen bubble's), the body again while the fighter is metal (the
    # donor's metal body is gone, and the engine hides the high-detail set then)
    named, switched = {}, [list(map(list, g)) for g in (pieces or {}).get('groups') or []]
    if switched:
        low_body = pieces.get('low_body', pieces.get('low') or [])
        lists = model_lists(pieces['high'], low_body, switched, pieces.get('low_groups'))
        base = (dat.data_size + 3) // 4 * 4
        blob, slots, at = lists(base)
        if dat.append_struct(blob, slots, align=4) != base:
            raise RuntimeError('the lists of pieces did not land where they were laid out for')
        if keep_metal:
            raise ValueError("the donor's metal body cannot be kept beside groups of the costume's own: its list "
                             "has the donor's number of groups")
        for c in range((dat.struct_end(table) - table) // 16):
            ed.set_pointers({table + c * 16 + mode * 4: base + at[which]
                             for mode, which in enumerate(('high', 'low', 'metal', 'high'))})
        dat.set_u32(model, 1 + len(switched))
        named = {modes[0]: list(pieces['high']), modes[1]: list(low_body), modes[3]: list(pieces['high'])}
    elif pieces:
        done = set()
        for c in range((dat.struct_end(table) - table) // 16):
            for mode, which in ((0, 'high'), (1, 'low'), (3, 'high')):
                g = dat.ptr(table + c * 16 + mode * 4)
                if g is None or not pieces.get(which):
                    continue
                variants, v = dat.u32(g), dat.ptr(g + 4)
                if not variants or v is None:
                    raise ValueError(f'the donor has no first choice of its first group to name {modes[mode]} pieces in')
                if v in done:
                    continue
                done.add(v)
                numbers = bytes(pieces[which])
                e = dat.ptr(v + 4)
                if e is not None and dat.struct_end(e) - e >= len(numbers):
                    ed.write(e, numbers)
                else:
                    ed.set_pointers({v + 4: dat.append_struct(numbers + bytes(-len(numbers) % 4), align=4)})
                dat.set_u32(v, len(numbers))
                named[modes[mode]] = list(pieces[which])
    costume = costume_census(costume_bytes) if costume_bytes is not None else None
    tex_count, tex = dat.u32(model + 8), dat.ptr(model + 0x0C)
    slots = list(texture_slots) if texture_slots is not None else list(range(tex_count))
    if len(slots) > tex_count:
        raise ValueError(f'{len(slots)} texture slots: the donor has room for {tex_count}')
    if costume is not None:
        if costume['joints'] != n or costume['parents'] != parents:
            raise ValueError('the costume\'s joints are not the frozen rig\'s')
        if texture_slots is None:
            slots = slots[:costume['textures']]
        if any(not 0 <= s < costume['textures'] for s in slots):
            raise ValueError(f'texture slots {slots}: the costume has {costume["textures"]} textures')
    was_slots = {}
    for c in range((dat.struct_end(tex) - tex) // 4 if tex is not None else 0):
        p = dat.ptr(tex + c * 4)
        if p is not None:
            was_slots[c] = [struct.unpack_from('>H', dat.buf, HDR + p + 2 * k)[0] for k in range(tex_count)]
            for k, s in enumerate(slots):
                ed.set_u16(p + 2 * k, s)
    dat.set_u32(model + 8, len(slots))
    report['model_tables'] = dict(
        groups=groups, groups_now=1 + len(switched) if switched else groups, switched=switched,
        low_switched=list((pieces or {}).get('low_groups') or []),
        rest=list((pieces or {}).get('rest') or []),
        lists_emptied=len(emptied_lists), lists=emptied_lists,
        pieces_named_now=sum(len(v) for v in named.values()), named=named,
        texture_slots_was=was_slots, texture_slots_now=slots,
        costume=None if costume is None else {k: v for k, v in costume.items() if k != 'parents'},
        how='the donor\'s lists are left behind for tables of the costume\'s own: the body is the first group '
            '(high detail and while metal; its low-detail copy in the shadow\'s pass), and each set of parts the '
            'game\'s clips show one of is a group after it, drawn in the high-detail pass and while metal'
            if switched else
            'every list of pieces is cut to nothing where it lies (the groups and their choices stay, so a script '
            'that picks a choice picks an empty one); then the first choice of the first group names the '
            'costume\'s own pieces: the body (high detail, and while metal) and its low-detail copy'
            if named else
            'every list of pieces is cut to nothing where it lies (the groups and their choices stay, so a script '
            'that picks a choice picks an empty one): no piece is ever hidden, none is named')

    out = ed.bytes()
    report['joint_map'] = {str(j): dict(jmap[j], name=order[jmap[j]['to']], uses=used[j]) for j in sorted(used)}
    report['verify'] = verify(pl_bytes, out, D, jmap, report, order, parents, frozen, costume, item_target,
                              keep_metal)
    report['unverified'] = list(UNVERIFIED)
    return out, report


MAX_GROUPS = 11                 # ftparts.c ftParts_8007487C: "fighter parts model num over!" at twelve


def model_lists(high, low, switched, low_switched=None):
    """The model lists of a costume whose parts are shown and hidden in groups (ftData +0x08 -> one row a costume
    of four pointers: high detail, low detail, the metal body, the body while metal; each to one {choices, pointer}
    a group; each choice {pieces, pointer to their numbers}). The engine draws one choice of each group
    (ftparts.c ftParts_80074B6C) in whichever of the four its pass shows.
      high detail, body while metal   group 0 has one choice, the body (`high`); group k + 1 the choices of
                                      `switched[k]`
      low detail                      group 0's one choice is the low-detail copy (`low`); the other groups have
                                      no choices by default. `low_switched` can supply corresponding choices
                                      for opacity-controlled pieces, removed from `low` by the caller
      the metal body                  no choices at all (the donor's metal body is gone)
    -> a function of the place the bytes will lie at, giving (the bytes, the places in them that are pointers,
    {'high', 'low', 'metal': where each table starts})"""
    if 1 + len(switched) > MAX_GROUPS:
        raise ValueError(f'{1 + len(switched)} groups: the engine holds {MAX_GROUPS}')
    low_switched = [[] for _ in switched] if low_switched is None else low_switched
    if len(low_switched) != len(switched) or any(len(b) not in (0, len(a)) for a, b in zip(switched, low_switched)):
        raise ValueError('low-detail choices must match the high-detail groups')
    if any(not 0 <= x <= 255 for group in [[high], [low]] + switched + low_switched for choice in group for x in choice):
        raise ValueError('a piece number does not fit a byte')

    def lay(base):
        blob, slots = bytearray(), []

        def put(data):
            blob.extend(bytes(-len(blob) % 4))
            at = len(blob)
            blob.extend(data)
            return at

        def table(groups):
            rows = []
            for choices in groups:
                found = [(len(numbers), put(bytes(numbers)) if numbers else None) for numbers in choices]
                at = None
                if found:
                    at = put(b''.join(struct.pack('>II', n, 0 if where is None else base + where) for n, where in found))
                    slots.extend(at + 8 * k + 4 for k, (_n, where) in enumerate(found) if where is not None)
                rows.append((len(found), at))
            start = put(b''.join(struct.pack('>II', n, 0 if at is None else base + at) for n, at in rows))
            slots.extend(start + 8 * k + 4 for k, (_n, at) in enumerate(rows) if at is not None)
            return start

        none = [[] for _ in switched]
        at = dict(high=table([[list(high)]] + switched), low=table([[list(low)]] + low_switched),
                  metal=table([[]] + none))
        return bytes(blob) + bytes(-len(blob) % 4), slots, at
    return lay


def _scripts(ed, D, jmap, go, forward, reverse, parents, hurt_joints, order, n):
    """Every script command that holds a joint, in every block an action or a demo action reaches."""
    from vault.echo.commands import POINTER_COMMANDS
    from vault.echo.subactions import ACTION_SIZE
    ft, dat = ed.ft, ed.dat
    entries = [(f'action[{a.index}]', a.script_offset) for a in ft.actions if a.script_offset is not None]
    demo = dat.ptr(ft.ft_root + 0x14)
    for i in range((dat.struct_end(demo) - demo) // ACTION_SIZE if demo is not None else 0):
        off = dat.ptr(demo + i * ACTION_SIZE + 0x0C)
        if off is not None:
            entries.append((f'demo[{i}]', off))
    # an action's own flag word: three bits that name a low joint (see ACTION_FLAG_JOINT)
    snapped = Counter()
    first, bits = ACTION_FLAG_JOINT
    for table in (dat.ptr(ft.ft_root + 0x0C), demo):
        for i in range((dat.struct_end(table) - table) // ACTION_SIZE if table is not None else 0):
            at = table + i * ACTION_SIZE + 0x10
            was = _bits(dat.u32(at), first, bits)
            if was:
                now = go(was, f'the flag word of action row 0x{at:X}')
                if now >= 1 << bits:
                    raise ValueError(f'action flags: joint {now} does not fit {bits} bits')
                dat.set_u32(at, _put(dat.u32(at), first, bits, now))
                snapped[f'{was}>{now} ({order[now]})'] += 1
    entry_blocks = {o for _, o in entries}
    blocks, pending = {}, list(entries)
    while pending:
        label, off = pending.pop(0)
        if off in blocks:
            continue
        blocks[off] = ft.decode_script(off)
        for c in blocks[off].commands:
            if c.code in POINTER_COMMANDS and c.pointer is not None and c.pointer not in blocks:
                pending.append((label, c.pointer))
    tiers, by_command, notes = Counter(), Counter(), []
    kept = Counter()
    trail = Counter()
    for off, script in blocks.items():
        if script.unknown_code is not None:
            notes.append(f'block 0x{off:X} stops at an unknown command 0x{script.unknown_code:02X}')
        for cmd in script.commands:
            word = dat.u32(cmd.offset)
            if cmd.code in JOINT_FIELD:
                by_command[cmd.name] += 1
                row = command_target(cmd.code, word, D, jmap, forward, reverse, parents, hurt_joints)
                if row['tier'] is None:
                    kept[row['kept']] += 1
                    continue
                go(row['donor_joint'], f'{cmd.name} at 0x{cmd.offset:X}')
                dat.set_u32(cmd.offset, row['word'])
                tiers[row['tier']] += 1
            elif cmd.code == CMD_SWORD_TRAIL:
                now, what = trail_target(word)
                dat.set_u32(cmd.offset, now)
                trail[what] += 1
    return dict(blocks=len(blocks), entries=len(entries), reached_only_by_pointer=len(set(blocks) - entry_blocks),
                joint_commands=dict(by_command), repointed_by_tier=dict(tiers), repointed=sum(tiers.values()),
                left_as_they_are=dict(kept), sword_trail=dict(trail), action_flag_joints=dict(snapped),
                notes=notes)


# ------------------------------------------------------------------------------------------------------- checking
def verify(before_bytes, after_bytes, D, jmap, report, order, parents, frozen, costume, item_target, keep_metal):
    """Reads both files with the second reader and holds every joint index in the new one against what it should
    be, worked out again here from the OLD file's own values (not from what the writer recorded).
    -> dict(ok, problems, checked, joints=[every joint index in the new file])"""
    n = len(order)
    root = D['root']
    old = census(before_bytes, root, attr_joints=D['attr_joints'])
    new = census(after_bytes, root, joints=n, attr_joints=D['attr_joints'])
    problems, checked = [], Counter()
    old_rows = {row['consumer']: row for row in old['joints']}
    new_rows = {row['consumer']: row for row in new['joints']}
    of, nf = old['facts'], new['facts']

    def expect(name, value, want, kind):
        checked[kind] += 1
        if value != want:
            problems.append(f'{name}: {value}, should be {want}')

    hurt = [c['joint'] for c in report['hurtboxes']['table']]
    hurt_set = set(hurt)
    part_rows = {p['part']: p for p in report['parts']}
    index = {j: i for i, j in enumerate(order)}
    for name, row in new_rows.items():
        v = row['value']
        if row['kind'] == 'JOINT' and not 0 <= v < n:
            problems.append(f'{name}: joint {v} is past the rig\'s {n}')
            continue
        if row['kind'] == 'SLOT':
            checked['script slot'] += 1
            if not (0 <= v < len(SLOTS)):
                problems.append(f'{name}: slot {v}')
            continue
        if row['kind'] in ('HEAD', 'SELECTOR'):
            checked['script selector'] += 1
            continue
        was = old_rows.get(name)
        if name.startswith('hurtbox['):
            i = int(name[8:-1])
            expect(name, v, hurt[min(i, len(hurt) - 1)], 'hurtbox')
        elif name.startswith('ecb['):
            expect(name, v, report['ecb']['written'][int(name[4:-1])], 'ecb')
        elif name.startswith('part['):
            p = part_rows[int(name[5:name.index(']')])]
            members = [index[m] for m in p['members']]
            if name.endswith('.start'):
                expect(name, v, index[p['anchor']], 'part')
            else:
                k = int(name[name.index('entry[') + 6:-1])
                if k >= p['room']:                          # the list's padding: as it was
                    expect(name, v, was['value'] if was else None, 'part')
                else:
                    expect(name, v, members[min(k, len(members) - 1)] if members else index[p['anchor']], 'part')
        elif name == 'modelLookup.itemHold':
            expect(name, v, item_target, 'table')
        elif name.startswith('script '):
            if was is None:
                problems.append(f'{name}: a command the donor did not have')
                continue
            if was['kind'] == 'SLOT':
                checked['script slot'] += 1
                continue
            want = jmap[was['value']]['to'] if 0 <= was['value'] < D['joints'] else was['value']
            if row['command'] == CMD_NAME[CMD_HURT_STATE]:
                want = hurt_joint(want, parents, hurt_set)[0]
                if v not in hurt_set:
                    problems.append(f'{name}: joint {v} carries no hurtbox')
            expect(name, v, want, 'script')
        else:
            if was is None:
                problems.append(f'{name}: not in the donor\'s file')
                continue
            expect(name, v, jmap[was['value']]['to'], 'table')
    for name in old_rows:
        if name not in new_rows:
            problems.append(f'{name}: gone from the new file')

    # the capsules: on the right sides, and read the way that puts them on the body
    shape = report['hurtboxes']['check']
    problems += sides_problems(shape)
    if shape.get('best_reading', 'as written') != 'as written':
        near = shape.get('closest_other_reading') or {}
        problems.append(f'the hurtboxes sit on the body better read as "{shape["best_reading"]}": that reading holds '
                        f'{near.get("body_inside")} of the body\'s points, the game\'s own {near.get("as_written")}. '
                        'The capsules\' ends were read from the wrong fields or in the wrong order '
                        '(own_data.source_tables); the report\'s hurtboxes.check.readings has every count')
    # counts and shapes
    if nf['hurtbox_count'] != len(hurt) or not 1 <= nf['hurtbox_count'] <= MAX_HURTBOXES:
        problems.append(f'hurtbox count {nf["hurtbox_count"]}')
    for got, want in zip(nf['hurtboxes'], report['hurtboxes']['table']):
        for key in ('height', 'grabbable'):
            if got[key] != want[key]:
                problems.append(f'hurtbox on {want["name"]}: {key} {got[key]}')
        if max(abs(a - b) for a, b in zip(got['a'] + got['b'] + [got['radius']],
                                          want['a'] + want['b'] + [want['radius']])) > 1e-5:
            problems.append(f'hurtbox on {want["name"]}: its capsule is not the source\'s')
    if nf.get('dynamics', {}).get('count', 0) != 0:
        problems.append('dynamics are still on')
    for label in ('actions', 'demo actions'):
        if nf.get(f'dynamics_clip_bytes.{label}', 0):
            problems.append(f'{label}: an action still picks a dynamics clip')
        if nf.get(f'blend_bytes.{label}') != of.get(f'blend_bytes.{label}'):
            problems.append(f'{label}: a blend-in byte changed')
    if 'shield_pose' in nf:
        if nf['shield_pose']['parents'] != parents:
            problems.append('the shield pose\'s skeleton is not the rig\'s')
        checked['shield pose joints'] = nf['shield_pose']['nodes']
    for p in nf['parts']:
        if any(t['nodes'] != 1 or t['animated'] for t in p['poses']):
            problems.append(f'part {p["part"]}: a donor pose still moves joints')
        if not 0 <= p['count'] <= p['room']:
            problems.append(f'part {p["part"]}: {p["count"]} joints in room for {p["room"]}')
    modes = ('high detail', 'low detail', 'metal body', 'body while metal')
    meant = report['model_tables'].get('named') or {}
    switched = report['model_tables'].get('switched') or []
    if nf['visibility_groups'] != report['model_tables'].get('groups_now', nf['visibility_groups']):
        problems.append(f'{nf["visibility_groups"]} model groups, not {report["model_tables"]["groups_now"]}')
    if switched:
        drawn = {(row['mode'], row['group'], row['variant']) for row in nf['visibility']}
        for g, choices in enumerate(switched):
            for mode in (0, 3):
                if any((mode, g + 1, k) not in drawn for k in range(len(choices))):
                    problems.append(f'the {modes[mode]} lists do not have every choice of group {g + 1}')
    if switched:
        for g, choices in enumerate(report['model_tables'].get('low_switched') or []):
            if any((1, g + 1, k) not in drawn for k in range(len(choices))):
                problems.append(f'the low detail lists do not have every choice of group {g + 1}')
    for row in nf['visibility']:
        if keep_metal and row['mode'] == 2:
            continue
        want = meant.get(modes[row['mode']], []) if (row['group'], row['variant']) == (0, 0) else []
        if switched and row['group'] > 0 and row['mode'] in (0, 3):
            choices = switched[row['group'] - 1] if row['group'] - 1 < len(switched) else []
            want = choices[row['variant']] if row['variant'] < len(choices) else []
        if row['group'] > 0 and row['mode'] == 1 and report['model_tables'].get('low_switched'):
            low_groups = report['model_tables']['low_switched']
            choices = low_groups[row['group'] - 1] if row['group'] <= len(low_groups) else []
            want = choices[row['variant']] if row['variant'] < len(choices) else []
        if row['pieces'] != want:
            problems.append(f'the {modes[row["mode"]]} list of group {row["group"]}, choice {row["variant"]} names '
                            f'{row["pieces"]}, not {want}')
        if costume is not None and any(x >= costume['pieces'] for x in row['pieces']):
            problems.append(f'a {modes[row["mode"]]} list names a piece the costume does not have')
    if 'metal' in nf and not keep_metal and nf['metal']['pieces']:
        problems.append('the metal body still has pieces')
    if 'metal' in nf and nf['metal']['nodes'] > n:
        problems.append(f"the donor's metal skeleton has {nf['metal']['nodes']} joints and the rig {n}: the engine pairs "
                        'them by counting, and the ones left over have no joint (own_data.build cuts them off unless '
                        'the metal body is kept: --keep-metal cannot be used on a rig smaller than the donor)')
    slots = nf['texture_slots']
    for c, row in slots.items():
        if costume is not None and any(s >= costume['textures'] for s in row):
            problems.append(f'costume {c}: texture slot past the costume\'s {costume["textures"]}')
    for slot in nf['texture_slots_used']:
        if int(slot) >= nf['texture_count']:
            problems.append(f'a script animates texture slot {slot} of {nf["texture_count"]}')
    for group in nf['model_state_groups']:
        if int(group) >= nf['visibility_groups']:
            problems.append(f'a script sets model group {group} of {nf["visibility_groups"]}')
    for key in nf['part_poses_used']:
        problems.append(f'a script plays part pose {key}: the donor\'s poses are emptied, check it')
    if nf['sword_trail'].get('own'):
        problems.append('a script still turns the donor\'s sword trail on')
    if nf['script_blocks'] != of['script_blocks'] or nf['script_stopped'] or of['script_stopped']:
        problems.append('the scripts no longer read as they did')
    if abs(nf['model_scale'] - report['scale']['written']) > 1e-6:
        problems.append('the drawn scale is not the one chosen')
    if nf.get('ik'):
        for row in report['ik']['lengths']:
            if abs(nf['ik'][row['field']] - row['now']) > 1e-4:
                problems.append(f'leg solver {row["field"]}: {nf["ik"][row["field"]]}')
    # a third reading of the scripts, by the app's own decoder and its own table of commands
    theirs = app_script_joints(after_bytes)
    mine = {row['at']: (row['kind'], row['value']) for row in new['joints'] if row['consumer'].startswith('script ')}
    if theirs != mine:
        odd = sorted(set(theirs.items()) ^ set(mine.items()))[:6]
        problems.append(f'the two script readers disagree at {odd}')
    checked['script joints read the same by both readers'] = len(mine)
    # the app's own reader must still take the file, and write every command back as it read it
    from vault.echo.subactions import FighterDat
    again = FighterDat(after_bytes)
    round_trip = again.verify_roundtrip()
    if round_trip:
        problems.append(f'{len(round_trip)} commands do not write back as read')
    if again.to_bytes() != after_bytes:
        problems.append('the file does not come back out of the reader as it went in')
    listing = [dict(consumer=row['consumer'], value=row['value'], kind=row['kind'], live=row['live'],
                    name=order[row['value']] if row['kind'] == 'JOINT' and 0 <= row['value'] < n else
                    (SLOTS[row['value']] if row['kind'] == 'SLOT' and 0 <= row['value'] < len(SLOTS) else None))
               for row in new['joints']]
    live = [row for row in listing if row['kind'] == 'JOINT']
    return dict(ok=not problems, problems=problems, checked=dict(checked),
                joint_indices=len(live), highest=max(row['value'] for row in live), limit=n,
                out_of_range=nf['out_of_range'], actions=len(again.actions), round_trip_problems=len(round_trip),
                by_joint={order[j]: c for j, c in sorted(Counter(row['value'] for row in live).items())},
                facts={k: nf[k] for k in ('hurtbox_count', 'script_blocks', 'script_entries', 'texture_slots',
                                          'texture_slots_used', 'model_state_groups', 'sword_trail', 'metal',
                                          'dynamics', 'visibility_groups') if k in nf},
                joints=listing)


def app_script_joints(payload):
    """The joints in the scripts as the app's decoder reads them (its own command table, its own walk).
    -> {command offset: (kind, value)}, in `census`'s terms."""
    from vault.echo.commands import POINTER_COMMANDS
    from vault.echo.subactions import ACTION_SIZE, FighterDat
    ft = FighterDat(payload)
    pending = [a.script_offset for a in ft.actions if a.script_offset is not None]
    demo = ft.dat.ptr(ft.ft_root + 0x14)
    for i in range((ft.dat.struct_end(demo) - demo) // ACTION_SIZE if demo is not None else 0):
        off = ft.dat.ptr(demo + i * ACTION_SIZE + 0x0C)
        if off is not None:
            pending.append(off)
    seen, out = set(), {}
    while pending:
        off = pending.pop()
        if off in seen:
            continue
        seen.add(off)
        for c in ft.decode_script(off).commands:
            f = c.fields
            if c.code in POINTER_COMMANDS and c.pointer is not None:
                pending.append(c.pointer)
            elif c.code == CMD_GFX:
                kind = 'HEAD' if (f['unk1'] >> 15) & 1 else ('SLOT' if f['use_common_bone_ids'] else (
                    'SELECTOR' if f['bone_id'] in SPECIAL_GFX_BONES else 'JOINT'))
                out[c.offset] = (kind, f['bone_id'])
            elif c.code == CMD_HIT:
                out[c.offset] = ('SLOT' if f['use_common_bone_ids'] else 'JOINT', f['bone'])
            elif c.code == CMD_HURT_STATE:
                out[c.offset] = ('JOINT', f['bone_id'])
            elif c.code == CMD_BONE_PHYSICS:
                value = f['bone_id'] & 0x3FFFFFF
                out[c.offset] = ('JOINT', value - (1 << 26) if value >= 1 << 25 else value)
            elif c.code == CMD_WIND:
                out[c.offset] = ('JOINT', f['unknown1'] & 0xFF)
    return out


# ------------------------------------------------------------------------------------------------------- running
def body_points(smd_path, joints):
    """The body at rest out of the costume stage's own mesh file: (points, the joint each follows most)."""
    from .compat import smd
    model = smd.load(smd_path)
    points, owner = [], []
    for tri in model.triangles:
        for v in tri.verts:
            points.append(v.pos)
            owner.append(max(v.weights, key=lambda w: w[1])[0])
    owner = np.array(owner)
    if len(owner) and owner.max() >= joints:
        raise ValueError('the mesh names joints the rig does not have')
    return np.array(points, float), owner


def main(argv=None):
    import argparse
    repo = Path(os.environ.get('NUCLEUS_REPO') or Path(__file__).resolve().parents[3])
    ap = argparse.ArgumentParser(description='The donor\'s fighter data, rewritten for a fighter on its own skeleton.')
    ap.add_argument('--fighter', default='duckhunt')
    ap.add_argument('--donor', default='Marth')
    ap.add_argument('--work', type=Path, default=None, help='the fighter\'s work folder (rig/, body/; data/ is written)')
    ap.add_argument('--donor-dir', type=Path, default=repo / 'app/scratch/brawl-oneshot/port/donor')
    ap.add_argument('--root', type=Path, default=Path(os.environ.get('ULTIMATE_DUMP') or Path.home() / 'shulk-calibration-20260904'))
    ap.add_argument('--model-scale', type=float, default=None)
    ap.add_argument('--item-hold', default=None)
    ap.add_argument('--shield-clip', default='b00guardon', help='the source clip whose last frame is the shield pose')
    ap.add_argument('--rest-shield', action='store_true', help='use the rest pose for the shield pose')
    ap.add_argument('--keep-metal', action='store_true')
    a = ap.parse_args(argv)
    work = a.work or repo / 'app/scratch' / f'{a.fighter}-native'
    frozen = json.loads((work / 'rig' / f'rig-{a.fighter}.json').read_text('utf-8'))
    lookup = json.loads((work / 'rig' / 'lookup.json').read_text('utf-8'))
    pl = (a.donor_dir / f'Pl{"Ms" if a.donor == "Marth" else a.donor}.dat').read_bytes()
    costume_path = work / 'body' / f'{a.fighter}.dat'
    costume = costume_path.read_bytes() if costume_path.exists() else None
    notes = {}
    pose = None
    if not a.rest_shield:
        try:
            pose, frame, error = source_pose(a.root, a.fighter, frozen, a.shield_clip)
            notes['shield_pose'] = dict(clip=a.shield_clip, frame=frame, put_back_error=error,
                                        why='the stick-centred shield pose is the last frame of the clip that '
                                            'raises the shield (the source\'s `guard` clip is the tilt wheel)')
            if error > 1e-3:
                notes['shield_pose']['refused'] = 'the pose does not go back together; the rest pose is used'
                pose = None
        except Exception as exc:                            # said, not hidden: the rest pose is used instead
            notes['shield_pose'] = dict(clip=a.shield_clip, failed=f'{type(exc).__name__}: {exc}'[:300],
                                        used='the rest pose')
    points = None
    smd_path = work / 'body' / f'{a.fighter}.smd'
    if smd_path.exists():
        try:
            points = body_points(smd_path, len(frozen['order']))
            notes['body_points'] = dict(file=str(smd_path), points=len(points[0]))
        except Exception as exc:
            notes['body_points'] = dict(failed=f'{type(exc).__name__}: {exc}'[:300])
    skeleton = None
    for candidate in (a.root / 'gamedata' / 'fighter' / DONOR[a.donor]['ultimate'] / 'model/body/c00/model.nusktb',
                      work / 'tmp' / f'{DONOR[a.donor]["ultimate"]}-ultimate' / 'fighter' / DONOR[a.donor]['ultimate']
                      / 'model/body/c00/model.nusktb'):
        if candidate.exists():
            skeleton = candidate
            break
    notes['donor_ultimate_skeleton'] = str(skeleton) if skeleton else 'not on this machine: the kept number is used'
    receipt = work / 'body' / 'receipt.json'
    pieces = json.loads(receipt.read_text('utf-8')).get('pieces') if receipt.exists() else None
    out, report = build(pl, frozen, lookup, a.root, a.fighter, a.donor, costume, model_scale=a.model_scale,
                        item_hold=a.item_hold, shield_pose=pose, keep_metal=a.keep_metal,
                        donor_ultimate_skeleton=skeleton, body_points=points, pieces=pieces)
    report['inputs'] = dict(donor_file=str(a.donor_dir), work=str(work), source=str(a.root), **notes)
    if report['shield_pose'] and pose:
        report['shield_pose']['pose'] = f'{a.shield_clip}, last frame'
    dest = work / 'data'
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / f'Pl{"Ms" if a.donor == "Marth" else a.donor}.dat'
    target.write_bytes(out)
    (dest / 'report.json').write_text(json.dumps(report, indent=1, default=float), 'utf-8')
    v, s = report['verify'], report['scripts']
    print(f'{target}  ({len(pl)} -> {len(out)} bytes)')
    print(f'  hurtboxes {len(report["hurtboxes"]["table"])} (was {report["hurtboxes"]["donor_count"]}); '
          f'ecb {report["ecb"]["names"]}')
    print(f'  scripts: {s["repointed"]} joints re-pointed {s["repointed_by_tier"]}; left {s["left_as_they_are"]}; '
          f'sword trail {s["sword_trail"]}; action flags {s["action_flag_joints"]}')
    print(f'  scale {report["scale"]["written"]:.4f} (rig {report["scale"]["rig_height"]:.3f} -> drawn '
          f'{report["scale"]["drawn_height"]:.3f}; {a.donor} {report["scale"]["donor_drawn_height"]:.3f})')
    print(f'  check: {"PASS" if v["ok"] else "FAIL"}  {v["joint_indices"]} joint indices, highest {v["highest"]} '
          f'of {v["limit"]}; {v["checked"]}')
    for line in v['problems'][:20]:
        print('    ' + line)
    for line in lopsided_notes(report['hurtboxes']['check']):
        print('  note: ' + line)
    near = report['hurtboxes']['check'].get('closest_other_reading')
    if v['ok'] and near and near.get('why'):
        print(f"  note: read as \"{near['reading']}\" the hurtboxes hold {near['body_inside']} of the body's points, as "
              f"the game writes them {near['as_written']}, but {near['why']} ({near['capsules_inside']} against "
              f"{near['capsules_as_written']} on the mean): the game's stands")
    elif v['ok'] and near:
        print(f"  note: read as \"{near['reading']}\" the hurtboxes hold {near['body_inside']} of the body's points, as "
              f"the game writes them {near['as_written']}: too close to tell apart on this fighter, the game's stands")
    if not v['ok']:
        print(f"  the numbers behind each line are in {dest / 'report.json'} (verify.problems, hurtboxes.check)")
    return 0 if v['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
