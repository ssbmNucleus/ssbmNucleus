"""Generate the "Any Climbers" Gecko code (dev-only; the output is committed).

Melee decides a fighter follows its partner by asking `fp->kind == FTKIND_NANA`.
Five sites in the DOL ask it, all compiled to the same two instructions:

    lwz   rD, 4(rSRC)     # fp->kind
    cmpwi rD, 11          # FTKIND_NANA

Each site gets a C2 injection over the `lwz` that answers 11 for *any* follower
instead.  A follower is the second entity of a paired character (`x221F & 8`,
m-ex's master/slave bit).  The only vanilla fighters that bit is set for are
Nana, Sheik and Zelda, so excluding the two transform kinds is an exact test
that needs no MxDt lookup -- and therefore survives an m-ex core update, which
a pointer into MexData's heap would not.

Requires devkitPPC (assembler only).  Run:  python -m vault.climbers.engine.gen_engine_code
"""
import struct
import subprocess
import tempfile
from pathlib import Path

AS = Path(r"C:/devkitPro/devkitPPC/bin/powerpc-eabi-as.exe")
OBJCOPY = Path(r"C:/devkitPro/devkitPPC/bin/powerpc-eabi-objcopy.exe")

FTKIND_NANA = 11
FTKIND_SEAK = 7
FTKIND_ZELDA = 19

# addr -> (source register holding Fighter*, decomp symbol, what it gates)
SITES = {
    0x800A1040: (3,  "ftCo_800A101C+0x24",  "CPU AI type 6 + 15.0 follow leash"),
    0x800A13B4: (29, "ftCo_800A101C+0x398", "seed the 30-frame leader input log"),
    0x800A1748: (29, "ftCo_800A101C+0x72C", "follower reach constant (x56C = 1.0)"),
    0x800AA320: (3,  "ftCo_800AA320",       "stick deflection 0x40/0x7F"),
    0x800A0958: (31, "ftCo_800A08F0+0x68",  "crouch/fastfall CPU command script"),
}

# Popo's OnLoad is the only place that sets `has_follower` (x2222 & 0x04), the
# flag ftCo_800BFD9C reads to put the partner to sleep when the leader dies.
# A generic leader never gets it, so its partner would outlive it and the stock
# count would go wrong.  This hooks the branch we just took above -- reached
# only by a real follower -- and sets the bit on its LEADER, clearing it on
# itself so exactly one of the pair ever carries it.
#
# The leader is NOT simply player_entity[0]: after a D-pad-down swap the leader
# is entity 1, and assuming index 0 left BOTH fighters flagged (this function is
# re-run for the new follower on every swap, which re-set the old flag). Find it
# by comparing this fighter against entity 0 instead.
# r29 is the Fighter* here (r3 was clobbered two instructions earlier).
FOLLOWER_ARM = 0x800A105C
FOLLOWER_ARM_ASM = """
    li      0, 6
    stwu    1, -0x20(1)
    stw     10, 0x08(1)
    stw     11, 0x0C(1)
    stw     12, 0x10(1)
    lbz     11, 0xC(29)
    mulli   11, 11, 0xE90
    lis     12, 0x8045
    ori     12, 12, 0x3080
    add     11, 11, 12
    lwz     12, 0xB0(11)
    cmpwi   12, 0
    beq     1f
    lwz     10, 0x2C(12)
    cmplw   10, 29
    bne     3f
    lwz     12, 0xB4(11)
3:
    cmpwi   12, 0
    beq     1f
    lwz     12, 0x2C(12)
    cmpwi   12, 0
    beq     1f
    lbz     10, 0x2222(12)
    ori     10, 10, 4
    stb     10, 0x2222(12)
    lbz     10, 0x2222(29)
    andi.   10, 10, 0xFB
    stb     10, 0x2222(29)
1:
    lwz     12, 0x10(1)
    lwz     11, 0x0C(1)
    lwz     10, 0x08(1)
    addi    1, 1, 0x20
"""

# Both halves of a pair spawn at the player's spawn point plus
# `facing * ftCommon_800804EC(fp)`, which is `fp->x40 * scale`. Only Popo's and
# Nana's OnLoad set x40 (+5 and -5, read from PlPp.dat), so a generic pair stood
# in one spot, on every spawn and on the respawn platforms. This gives a follower
# whose x40 is still zero the Ice Climbers' 10-unit gap behind its leader. It is
# worked out from the master/slave bit on every call rather than stored in x40,
# so it stays right after a D-pad swap; the leader keeps its spawn point because
# when it spawns the follower does not exist yet. Standing still, the follower
# then closes onto its leader's exact spot within a second, as Nana does on Popo
# (measured in vanilla: -65 and -55 at Wait, both -55 by 150 frames later).
# The kind tests are TEMPLATE's: Sheik and Zelda set the bit when they transform.
FOLLOWER_SPAWN = 0x800804EC
FOLLOWER_SPAWN_GAP = -10.0
FOLLOWER_SPAWN_ASM = """
    lfs     1, 0x40(3)
    lbz     0, 0x221F(3)
    andi.   0, 0, 8
    beq     1f
    lwz     0, 4(3)
    cmpwi   0, {seak}
    beq     1f
    cmpwi   0, {zelda}
    beq     1f
    lwz     0, 0x40(3)
    cmpwi   0, 0
    bne     1f
    stwu    1, -0x10(1)
    lis     0, {gap_hi}
    stw     0, 0x08(1)
    lfs     1, 0x08(1)
    addi    1, 1, 0x10
1:
"""

# r0 is the destination at every site, and CR0 is dead here: the instruction
# right after the hook is the original `cmpwi r0, 11`, which rewrites it.  So
# this needs no scratch register and no stack frame.
TEMPLATE = """
    lbz     0, 0x221F({src})
    andi.   0, 0, 8
    lwz     0, 4({src})
    beq     1f
    cmpwi   0, {seak}
    beq     1f
    cmpwi   0, {zelda}
    beq     1f
    li      0, {nana}
1:
"""


# --- Leader swap (D-pad down) ------------------------------------------------
#
# Melee routes BOTH "who reads the controller" and "who gets AI" through the
# same flag -- x221F bit 0x08, m-ex's master/slave bit (`Player_8003248C` takes
# it as its second argument). So swapping which half of a pair you drive is just
# toggling that bit on both fighters; the follower AI selection patched above
# keys off the same bit. The player's transformed[] mapping MUST move with it:
# Player_GetEntity uses transformed[0] to charge a stock, and the respawn code
# uses both entries to find the leader and follower. Leaving that mapping alone
# let the swapped leader die for free and left its follower on the platform.
#
# What does NOT come free is the AI's own setup -- ftCo_800A101C seeds the
# 30-frame leader input log, the follow leash and the follow state flags at
# spawn. Flipping the bit alone leaves the new follower half-configured and it
# just stands there, so the swap calls that function for it.
#
# Hooked into Fighter_procUpdate, which runs once per fighter per frame. The
# replaced instruction is `lwz r3,0x2C(r3)` (gobj -> Fighter*), chosen because
# r3 still holds the gobj there and r0/CR are both dead until the next
# instruction sets them.
SWAP_HOOK = 0x8006B848

FT_MS = 0x221F           # bit 0x08 = master/slave
FT_HAS_FOLLOWER = 0x2222  # bit 0x04 = partner sleeps when I die
# ft_var52. NOT ft_var50 (0x22F0): that one reads -1 on every fighter and the
# game rewrites it, so a counter stored there is wiped within a frame. 0x22F8 is
# zero on every fighter and is the slot the Tier-2 stance flag already proved
# holds across frames in-game.
FT_COOLDOWN = 0x22F8
# The orb's travel weight, a FLOAT in [0,1]: 1.0 at the moment of the swap,
# stepped down by 1/ORB_FRAMES each frame, orb drawn while it is > 0. Storing it
# as a float rather than a frame count is deliberate -- the lerp needs a float
# and the Gekko has no cheap int->float, so counting in the domain we actually
# use skips the whole 0x43300000 magic-number conversion dance.
#
# Verified in game the way ft_var50 taught: reads 0 on both fighters at boot,
# then ticks 1.0 -> 0.833 -> 0.556 -> 0.333 -> 0.111 -> exactly 0 and stays
# there. The game does not own it and the clamp leaves no drift.
FT_ORB_U = 0x22FC
# fp->motion_id (src/melee/ft/types.h: "/* fp+10 */ FtMotionId motion_id").
# The ftCommon motion-state enum is contiguous and ordered, which makes one
# comparison cover every state a swap must refuse:
#     -1      None
#     0..10   DeadDown .. DeadUpFallHitCameraIce   (the game's own test,
#             ftLib_8008732C, is exactly this range)
#     11      Sleep        -- the partner while its leader is dead
#     12..13  Rebirth, RebirthWait   -- on the respawn platform
#     14      Wait         -- the first state a fighter can act from
# So "motion_id < Wait" is dead OR asleep OR still spawning.
FT_MOTION_ID = 0x10
MS_WAIT = 14

FT_PLY = 0x0C
FT_INPUT_PRESSED = 0x668
DPAD_DOWN = 0x04
PLAYER_SLOTS = 0x80453080
PLAYER_STRIDE = 0xE90
ENTITY0 = 0xB0
PLAYER_TRANSFORMED = 0x0C  # two u8 indices: logical leader/follower -> entity slot

# StaticPlayer.staminas.byIndex[] -- the per-entity percent mirror the HUD
# reads. `Player_SetHPByIndex(slot, subchar, v)` indexes it by the fighter's ms
# bit, which is exactly what the swap toggles: after a swap each fighter starts
# writing to the OTHER slot, so without swapping the stored values too the HUD
# keeps showing the old leader's percent until someone next takes damage.
PERCENT_SLOT0 = 0x60
PERCENT_SLOT1 = 0x62

FTCO_800A101C = 0x800A101C
EFSYNC_SPAWN = 0x8005FDDC   # (gfx_id, gobj, jobj)
FT_PLAYSFX = 0x80088148     # (fp, sfx_id, volume, panning)

# --- What the swap looks like ------------------------------------------------
#
# Two effects, playing together.
#
# GLOW_GFX is joint-attached and spawned on the INCOMING LEADER ONLY, and NOT at
# the moment of the swap -- it fires on the frame the travel weight reaches zero,
# i.e. when the orb arrives. So it reads as the IMPACT of control landing on that
# fighter, and the two effects tell one story instead of two.
#
# That is why the spawn lives in the per-frame block's "weight hit 0" branch
# rather than in the swap itself. The `ms` test there keeps it to the fighter you
# are now driving; the outgoing one ticks the same timer but draws nothing.
# It originally fired on both fighters at the press, which read as noise.
#
# How long it glows is the effect's own lifetime, not something this code sets:
# one spawn, then the generator runs itself out. Picking a GLOW_GFX that lasts
# about a second is therefore part of choosing the id.
#
# 1027 was chosen by looking at all 37 joint-attached commons in game. It is a
# COMMON id, so any pair gets it whoever leads -- the same property that ruled
# out Shulk's Monado aura, which lives in the Marth-only EfMsData.dat.
#
# (The original was 1060, Zelda/Sheik's transform flash, spawned on BOTH
# fighters at the press -- which is why the swap used to read as nothing but a
# swirl at their feet.)
GLOW_GFX = 1027

# ORB_GFX is spawned at a WORLD POSITION, once per frame, walked along the line
# from the outgoing leader to the incoming one so control visibly travels
# between the two bodies.
#
# Position spawning is the thing that makes a moving orb possible at all:
# efSync_Spawn is varargs and its third argument is an HSD_JObj* for some gfx
# ids and a Vec3* for others -- efAsync_Dispatch decides per id. So ORB_GFX MUST
# come from the Vec3-taking set or the callee reads a joint pointer as
# coordinates and the orb lands somewhere in deep space. The Vec3 ids, read out
# of efAsync_Dispatch's switch:
#
#   1000-1006 1008 1010-1023 1025 1028-1032 1034-1041 1046 1052 1053 1055-1057
#   1061-1063 1067-1074 1076 1079 1082-1084 1087-1095 1100 1140-1143
#
# and the joint-taking ones (valid for GLOW_GFX, NOT for ORB_GFX):
#
#   1026 1027 1033 1042-1045 1047-1051 1058-1060 1075 1080 1081 1085 1086 1097
#   1106-1110 1117 1118 1123 1124 1128-1133 1139
#
# None of the 144 are named ANYWHERE: the decomp enum is all `Ef_Id_UnkNNNN`
# (efasync.c is fully decompiled -- the ids just index data), and EfCoData.dat
# carries exactly one symbol, `effCommonDataTable`. They can only be picked by
# looking at them.
#
# Auditioning them needs a BUILD, not a live poke. The obvious shortcut --
# ram_search the `li r3, <id>` immediate in the injection and poke a new id
# between swaps -- does not work: the harness writes Dolphin's RAM from outside
# the process, so the JIT keeps executing the stale translated block. The write
# lands (it reads back) and the game goes on spawning the old id, which looks
# exactly like "every effect renders the same". DATA pokes are unaffected; it is
# only instruction memory that goes stale. So an audition build has to read the
# id from a data word (scratch/gfx_contact_sheet.py).
ORB_GFX = 1012
ORB_FRAMES = 18      # how long the orb takes to cross
ORB_Y = 8.0          # cur_pos is at the feet; lift the orb to chest height

# The matching transform SFX (270158) is NOT usable: it lives in the Zelda/Sheik
# bank, and a pair's bank is its leader's. Appending it to a character bank
# gives a different id per leader, and this code needs one constant; appending
# to the common bank (main.ssm, group 0) would work but sfx ids are not raw
# indices -- they decode through lbAudioAx_800233EC against per-bank offset
# tables, so the resulting id can't be predicted without solving that first.
#
# So: a common-bank sfx instead. The safe ones are the ids played by code EVERY
# fighter shares -- ftCommon, ftcoll, ftcliffcommon -- because "every fighter
# does it" is exactly the property that makes the sound resident whoever leads.
# `main.ssm` IS that bank, and its `startIndex` is 0 with 246 entries -- so for
# ids 0..245 the sfx id is simply the bank index, and anything above 245 (288,
# and every 190115-style id) lives in another bank and is NOT usable here, the
# same reason the real Zelda transform sfx is not.
#
# The ids with a direct `ft_PlaySFX` call site in shared code, labelled by the
# caller -- the only ones whose meaning is actually sourced:
#
#   3 ground tech (ftCo_Passive)    4 ledge grab (ftcliffcommon)
#   8 wall tech (PassiveWall)       85 104 collision (ftcoll)
#   96 fighter.c                    110 127 128 129 shield (ftCo_Guard)
#   115 Sheik up-B (ftSk_SpecialHi) 130 shield break launch
#   228 229 230 (ft_0CDF)           234 star rod swing
#
# The other 230 are unlabelled, which is why they were auditioned by ear:
# `mexcli ssm-to-wav main.ssm <id> out.wav` decodes any of them, and
# scratch/sfx-all/ holds the whole bank as WAVs.
#
# 192 is one of those unlabelled ones -- chosen by listening, not by lineage.
# It was picked over 172 (also good) and over layering the two, which clips:
# summed they peak at 34381 against a 32767 ceiling, and Melee's mixer has no
# headroom to give. A single sound at volume 127 has no such problem.
SFX_TRANSFORM = 192

# 1s. Must stay comfortably above ORB_FRAMES (18) so the handover animation
# always finishes before another swap can start -- and above the 2 frames the
# `pressed` mask stays live, or the partner re-fires it on the very next frame
# and the pair lands back where it started (which reads as the swap silently
# not working at all).
SWAP_COOLDOWN_FRAMES = 60

# NOTE: the cooldown tick uses r14, not r0. In PPC `addi rD, rA, imm` treats
# rA=0 as the literal zero, so `addi r0, r0, -1` assembles to `li r0, -1` and
# would slam the counter to -1 every frame instead of decrementing it.
SWAP_ASM = """
    lwz     3, 0x2C(3)
    stwu    1, -0x50(1)
    mflr    0
    stw     0, 0x08(1)
    stw     3, 0x0C(1)
    stw     14, 0x10(1)
    stw     15, 0x14(1)
    stw     16, 0x18(1)
    stw     17, 0x1C(1)

    lwz     14, {cooldown}(3)
    cmpwi   14, 0
    ble     1f
    addi    14, 14, -1
    stw     14, {cooldown}(3)
1:
    lwz     0, {orbu}(3)
    cmpwi   0, 0
    beq     7f
    lfs     1, {orbu}(3)
    lis     0, {step_hi}
    ori     0, 0, {step_lo}
    stw     0, 0x30(1)
    lfs     3, 0x30(1)
    fsubs   1, 1, 3
    lis     0, 0
    stw     0, 0x30(1)
    lfs     2, 0x30(1)
    fcmpo   0, 1, 2
    bgt     5f
    li      0, 0
    stw     0, {orbu}(3)
    lbz     0, {ms}(3)
    andi.   0, 0, 8
    bne     7f
    lwz     4, 0(3)
    lwz     5, 0x28(4)
    li      3, {glowgfx}
    lis     12, {spawn_hi}
    ori     12, 12, {spawn_lo}
    mtctr   12
    bctrl
    b       7f
5:
    stfs    1, {orbu}(3)
    lbz     0, {ms}(3)
    andi.   0, 0, 8
    bne     7f
    lbz     14, {ply}(3)
    mulli   14, 14, {stride}
    lis     15, {slots_hi}
    ori     15, 15, {slots_lo}
    add     14, 14, 15
    lwz     15, {ent0}(14)
    lwz     16, {ent1}(14)
    cmpwi   15, 0
    beq     7f
    cmpwi   16, 0
    beq     7f
    lwz     15, 0x2C(15)
    lwz     16, 0x2C(16)
    lbz     0, {ms}(15)
    andi.   0, 0, 8
    beq     6f
    mr      17, 15
    mr      15, 16
    mr      16, 17
6:
    lfs     2, 0xB0(16)
    lfs     3, 0xB0(15)
    fsubs   2, 2, 3
    fmadds  2, 2, 1, 3
    stfs    2, 0x30(1)
    lfs     2, 0xB4(16)
    lfs     3, 0xB4(15)
    fsubs   2, 2, 3
    fmadds  2, 2, 1, 3
    lis     0, {orby_hi}
    ori     0, 0, {orby_lo}
    stw     0, 0x3C(1)
    lfs     4, 0x3C(1)
    fadds   2, 2, 4
    stfs    2, 0x34(1)
    lfs     2, 0xB8(16)
    lfs     3, 0xB8(15)
    fsubs   2, 2, 3
    fmadds  2, 2, 1, 3
    stfs    2, 0x38(1)
    lwz     4, 0(15)
    addi    5, 1, 0x30
    li      3, {orbgfx}
    lis     12, {spawn_hi}
    ori     12, 12, {spawn_lo}
    mtctr   12
    bctrl
7:
    lwz     3, 0x0C(1)
    lbz     0, {ms}(3)
    andi.   0, 0, 8
    bne     8f
    lwz     0, {cooldown}(3)
    cmpwi   0, 0
    bne     8f
    lwz     0, {pressed}(3)
    andi.   0, 0, {dpad}
    beq     8f

    lbz     14, {ply}(3)
    mulli   14, 14, {stride}
    lis     15, {slots_hi}
    ori     15, 15, {slots_lo}
    add     14, 14, 15
    lwz     15, {ent0}(14)
    lwz     16, {ent1}(14)
    cmpwi   15, 0
    beq     8f
    cmpwi   16, 0
    beq     8f
    lwz     15, 0x2C(15)
    lwz     16, 0x2C(16)

    lwz     0, {motion}(15)
    cmpwi   0, {wait}
    blt     8f
    lwz     0, {motion}(16)
    cmpwi   0, {wait}
    blt     8f

    lbz     0, {ms}(15)
    xori    0, 0, 8
    stb     0, {ms}(15)
    lbz     0, {ms}(16)
    xori    0, 0, 8
    stb     0, {ms}(16)

    lbz     0, {transformed0}(14)
    lbz     17, {transformed1}(14)
    stb     17, {transformed0}(14)
    stb     0, {transformed1}(14)

    li      0, {frames}
    stw     0, {cooldown}(15)
    stw     0, {cooldown}(16)

    lis     0, 0x3F80
    stw     0, {orbu}(15)
    stw     0, {orbu}(16)

    lhz     0, {pct0}(14)
    lhz     17, {pct1}(14)
    sth     17, {pct0}(14)
    sth     0, {pct1}(14)

    lbz     0, {ms}(15)
    andi.   0, 0, 8
    beq     2f
    mr      14, 15
    mr      17, 16
    b       3f
2:
    mr      14, 16
    mr      17, 15
3:
    lbz     0, {hasfoll}(17)
    ori     0, 0, 4
    stb     0, {hasfoll}(17)
    lbz     0, {hasfoll}(14)
    andi.   0, 0, 0xFB
    stb     0, {hasfoll}(14)

    mr      3, 14
    li      4, 0
    li      5, 0
    li      6, 0
    lis     12, {aiinit_hi}
    ori     12, 12, {aiinit_lo}
    mtctr   12
    bctrl

    mr      3, 17
    lis     4, {sfx_hi}
    ori     4, 4, {sfx_lo}
    li      5, 127
    li      6, 64
    lis     12, {sfx_fn_hi}
    ori     12, 12, {sfx_fn_lo}
    mtctr   12
    bctrl
8:
    lwz     0, 0x08(1)
    mtlr    0
    lwz     14, 0x10(1)
    lwz     15, 0x14(1)
    lwz     16, 0x18(1)
    lwz     17, 0x1C(1)
    lwz     3, 0x0C(1)
    addi    1, 1, 0x50
"""


# --- Audition build ----------------------------------------------------------
#
# Picking ORB_GFX/GLOW_GFX means looking at 109 effects, and the id lives in a
# `li r3, <id>` IMMEDIATE -- which cannot be poked live, because the harness
# writes Dolphin's RAM from outside the process and the JIT keeps executing the
# stale block (the write reads back fine; the game ignores it).
#
# So `--audition` emits the same code with both ids loaded from DATA instead:
#     lis r3, hi ; ori r3, r3, lo ; lwz r3, 0(r3)
# Data pokes DO take effect, so one build then sweeps every id.
#
# The scratch is an unused port's StaticPlayer block -- inert in a solo match,
# and measured to hold a poked value across 120 frames before being relied on.
AUDITION_SCRATCH = 0x80455C30      # +0 = orb gfx id, +4 = glow gfx id


def _load_gfx(reg: int, addr: int) -> str:
    return (f"    lis     {reg}, {hex(addr >> 16)}\n"
            f"    ori     {reg}, {reg}, {hex(addr & 0xFFFF)}\n"
            f"    lwz     {reg}, 0({reg})\n")


def _f32(value: float) -> int:
    """IEEE-754 single bits, so a float constant can be built with lis/ori.

    A Gecko code has no data section to `lfs` a literal out of, so every float
    the swap needs is materialised as its bit pattern in a GPR, stored to the
    stack and loaded back. 1.0f is even simpler -- 0x3F800000 goes straight to
    memory with `stw`, no FPU involved.
    """
    return struct.unpack(">I", struct.pack(">f", value))[0]


def swap_asm(audition: bool = False) -> str:
    asm = SWAP_ASM.format(
        cooldown=FT_COOLDOWN, ms=FT_MS, hasfoll=FT_HAS_FOLLOWER,
        pressed=FT_INPUT_PRESSED, dpad=DPAD_DOWN, ply=FT_PLY,
        motion=FT_MOTION_ID, wait=MS_WAIT,
        stride=PLAYER_STRIDE,
        slots_hi=hex(PLAYER_SLOTS >> 16), slots_lo=hex(PLAYER_SLOTS & 0xFFFF),
        ent0=ENTITY0, ent1=ENTITY0 + 4, frames=SWAP_COOLDOWN_FRAMES,
        transformed0=PLAYER_TRANSFORMED, transformed1=PLAYER_TRANSFORMED + 1,
        pct0=PERCENT_SLOT0, pct1=PERCENT_SLOT1,
        aiinit_hi=hex(FTCO_800A101C >> 16), aiinit_lo=hex(FTCO_800A101C & 0xFFFF),
        glowgfx=GLOW_GFX, orbgfx=ORB_GFX, orbu=FT_ORB_U,
        step_hi=hex(_f32(1.0 / ORB_FRAMES) >> 16),
        step_lo=hex(_f32(1.0 / ORB_FRAMES) & 0xFFFF),
        orby_hi=hex(_f32(ORB_Y) >> 16), orby_lo=hex(_f32(ORB_Y) & 0xFFFF),
        spawn_hi=hex(EFSYNC_SPAWN >> 16), spawn_lo=hex(EFSYNC_SPAWN & 0xFFFF),
        sfx_hi=hex(SFX_TRANSFORM >> 16), sfx_lo=hex(SFX_TRANSFORM & 0xFFFF),
        sfx_fn_hi=hex(FT_PLAYSFX >> 16), sfx_fn_lo=hex(FT_PLAYSFX & 0xFFFF),
    )
    if audition:
        asm = asm.replace(f"    li      3, {ORB_GFX}\n",
                          _load_gfx(3, AUDITION_SCRATCH))
        asm = asm.replace(f"    li      3, {GLOW_GFX}\n",
                          _load_gfx(3, AUDITION_SCRATCH + 4))
    return asm


# Death and respawn use Player_GetEntityAtIndex(slot, logical_index), which
# already resolves transformed[]. With that mapping kept in sync by the swap,
# the native logical follower index 1 is correct. Do not reintroduce the old
# 0x800BFE30 hook that passed a physical entity index to this logical lookup.


# --- Kind alias: let a pair's clone leader answer "which character am I?" ---
#
# A pair's leader is a DUPLICATE of its donor with a new internal kind, and
# Melee's character code asks `fp->kind == FTKIND_X` in ~130 places: Link's
# zair (`ftCo_AirCatch` refuses anyone but Link/Y.Link/Samus), Kirby's copy
# ability, Falcon/Ganon's flame (`ftLib_GetKind` switch), Fox/Falco, Marth/Roy,
# Pikachu/Pichu ... Patching every site is not tractable; rewriting the kind
# once, after the fighter is built, is. `fp->ft_data = gFtDataList[fp->kind]`
# runs at spawn (ft/fighter.c:729) and the costume/effects/sounds are already
# resolved by then, so from the first frame on the clone can carry its donor's
# kind and every vanilla check passes. The clone shares its data files with the
# donor by design (see pairs.build_pair_zip / MexFighter.Duplicate).
#
# Hooked at Fighter_procUpdate+4 (0x8006B84C, `lbz r0,0x221F(r3)`): r3 is the
# Fighter*, r0 is the instruction's own destination and CR0 is rewritten by
# the `rlwinm.` two instructions later, so no register needs saving.
#
# The original kind is stashed in ft_var51 (0x22F4) for anything that still
# needs the clone's real id: `player_kind_words` below, and the netplay probes,
# which read it to tell the two apart.
#
# Kirby copying a pair leader goes through the alias as well. A Kirby copy is
# keyed by the victim's `fp->kind` (`ftCo_800BD9E0`), which reads the aliased
# donor kind, so the copy runs the donor's vanilla path -- but only if the
# donor's cap is resident. Melee loads caps at match start for every present
# fighter and its sub-fighter by kind: `ftKb_SpecialN_800EEC34` queues the
# cap file (+ Kirby effect bank) from the DVD and `ftKb_SpecialN_800EED50`
# parses it into the hat table. Both are called with the CLONE's kind, which
# has no vanilla-table entry, so nothing was loaded and the copy hung the game
# the frame the swallow applied (measured 2026-09-15; copying the clone's
# real kind hung the same way). Aliasing the kind argument at the entry of
# those two functions loads the donor's cap instead, exactly as if the donor
# were in the match. m-ex leaves both entries unpatched (checked against the
# vanilla DOL), and the replaced instruction is the `mflr r0` prologue, so
# CR0/r0 are free.
#
# The HUD and the results screen must NOT get the alias. m-ex's gm_80168B34 hook
# picks a stock icon as `reserved + kind + stride * costume`, with `kind` from
# `Player_80036394(slot)`, which reads `fp->kind`: so every clone leader showed
# its DONOR'S stock, slot for slot (Plusle & Minun's first stock was yellow
# Pichu), and the same read fills the match-end standings the results screen
# draws from. Those two are the only callers that care: the other two only ask
# "is this Sheik?". So the fix is the function's own return, hooked at its exit
# (0x80036414, where the entity and no-entity paths meet; r31 is the slot and
# r3-r12 are dead) rather than at each caller. It answers with the stashed kind
# only when kind and stash are a pair from the alias table, because other code
# uses ft_var51 too (Echo's Tier-2 VAR_B) and a free slot reads 0.
#
# A pair can go without the D-pad swap (`pairs.set_no_swap`). The swap is shared
# code that refuses while the leader's cooldown is above zero, so a no-swap pair
# has its entry here set that cooldown once, at the leader's first frame, to more
# frames than any match lasts. It survives a respawn the way the stash does, and
# with no swap the orb and glow have nothing to start them.
#
# The (clone -> donor) table is per project, so these blocks are emitted by
# `engine_code.ensure_code` at export time with the words encoded here in
# Python -- no assembler in the shipped app.
ALIAS_HOOK = 0x8006B84C
ALIAS_HOOK_ORIG = 0x8803221F      # lbz r0,0x221F(r3)
FT_ORIG_KIND = 0x22F4             # ft_var51
NO_SWAP_COOLDOWN = 0x7FFF0000     # 414 days of frames; `lis` loads it in one word
KIRBY_CAP_PRELOAD_HOOK = 0x800EEC34   # ftKb_SpecialN_800EEC34(kind, costume, n): DVD preload
KIRBY_CAP_LOAD_HOOK = 0x800EED50      # ftKb_SpecialN_800EED50(kind, costume): parse into hats[]
KIRBY_CAP_HOOK_ORIG = 0x7C0802A6      # mflr r0 -- the prologue both functions start with
PLAYER_KIND_HOOK = 0x80036414         # Player_80036394's exit
PLAYER_KIND_HOOK_ORIG = 0x8001001C    # lwz r0,0x1C(r1)


def alias_words(aliases: dict[int, int], no_swap=()) -> list[int]:
    """Instruction words for the Fighter_procUpdate alias block. The clones in
    `no_swap` also lock their swap cooldown."""
    words = [0x80030004]                         # lwz r0,4(r3)        fp->kind
    for clone, donor in sorted(aliases.items()):
        lock = ([0x3C000000 | (NO_SWAP_COOLDOWN >> 16),   # lis r0,cooldown@h
                 0x90030000 | FT_COOLDOWN]                # stw r0,ft_var52(r3)
                if clone in no_swap else [])
        words += [0x2C000000 | (clone & 0xFFFF),  # cmpwi r0,clone
                  0x40820000 | (4 + len(lock)) * 4,  # bne past this entry
                  0x90030000 | FT_ORIG_KIND,      # stw r0,ft_var51(r3)  stash the clone kind
                  0x38000000 | (donor & 0xFFFF),  # li r0,donor
                  0x90030004] + lock              # stw r0,4(r3)         fp->kind = donor
    words.append(ALIAS_HOOK_ORIG)                # the replaced lbz
    return words


def kirby_cap_words(aliases: dict[int, int]) -> list[int]:
    """Instruction words for a cap-loader entry hook: r3 (the kind) becomes
    the donor for every clone, then the replaced `mflr r0` runs."""
    words = []
    for clone, donor in sorted(aliases.items()):
        words += [0x2C030000 | (clone & 0xFFFF),  # cmpwi r3,clone
                  0x40820008,                     # bne +8
                  0x38600000 | (donor & 0xFFFF)]  # li r3,donor
    words.append(KIRBY_CAP_HOOK_ORIG)
    return words


def player_kind_words(aliases: dict[int, int]) -> list[int]:
    """Instruction words for the Player_80036394 exit hook: an aliased fighter
    answers with the clone kind it stashed, then the replaced `lwz` runs."""
    table = []
    for clone, donor in sorted(aliases.items()):
        table += [0x2C040000 | (clone & 0xFFFF),   # cmpwi r4,clone
                  0x40820010,                      # bne +16
                  0x2C030000 | (donor & 0xFFFF),   # cmpwi r3,donor
                  0x40820008,                      # bne +8
                  0x7C832378]                      # mr r3,r4
    entity = [0x1C9F0000 | PLAYER_STRIDE,          # mulli r4,r31,stride
              0x3CA00000 | (PLAYER_SLOTS >> 16),   # lis r5,player_slots@h
              0x60A50000 | (PLAYER_SLOTS & 0xFFFF),  # ori r5,r5,player_slots@l
              0x7C842A14,                          # add r4,r4,r5
              0x88A40000 | PLAYER_TRANSFORMED,     # lbz r5,transformed[0](r4)
              0x54A5103A,                          # slwi r5,r5,2
              0x7C842A14,                          # add r4,r4,r5
              0x80840000 | ENTITY0,                # lwz r4,player_entity(r4)
              0x8084002C,                          # lwz r4,0x2C(r4)      gobj -> Fighter*
              0x80840000 | FT_ORIG_KIND]           # lwz r4,ft_var51(r4)
    skip = (len(entity) + len(table) + 1) * 4
    return ([0x2C030000,                           # cmpwi r3,0
             0x41800000 | skip]                    # blt past the table   -1: no entity
            + entity + table + [PLAYER_KIND_HOOK_ORIG])


def alias_ini_lines(aliases: dict[int, int], no_swap=()) -> list[str]:
    """Gecko C2 lines for a project's clone->donor table (all four hooks)."""
    if not aliases:
        return []
    out = []
    block = c2_block(ALIAS_HOOK, alias_words(aliases, no_swap))
    out.append(f"{block[0]} #Fighter_procUpdate+4 -- clone leaders answer as their donor kind")
    out.extend(block[1:])
    block = c2_block(KIRBY_CAP_PRELOAD_HOOK, kirby_cap_words(aliases))
    out.append(f"{block[0]} #ftKb_SpecialN_800EEC34 -- preload the donor's Kirby cap for a clone")
    out.extend(block[1:])
    block = c2_block(KIRBY_CAP_LOAD_HOOK, kirby_cap_words(aliases))
    out.append(f"{block[0]} #ftKb_SpecialN_800EED50 -- load the donor's Kirby cap for a clone")
    out.extend(block[1:])
    block = c2_block(PLAYER_KIND_HOOK, player_kind_words(aliases))
    out.append(f"{block[0]} #Player_80036394 -- the HUD and results name the clone, not its donor")
    out.extend(block[1:])
    return out


def assemble(asm: str) -> list[int]:
    with tempfile.TemporaryDirectory() as td:
        src, obj, binf = Path(td) / "a.s", Path(td) / "a.o", Path(td) / "a.bin"
        src.write_text(asm)
        subprocess.run([str(AS), "-mregnames", "-mbig", "-mgekko",
                        "-o", str(obj), str(src)], check=True, capture_output=True)
        subprocess.run([str(OBJCOPY), "-O", "binary", str(obj), str(binf)],
                       check=True, capture_output=True)
        data = binf.read_bytes()
    return [int.from_bytes(data[i:i + 4], "big") for i in range(0, len(data), 4)]


def c2_block(addr: int, words: list[int]) -> list[str]:
    # Gecko C2: body is measured in 8-byte lines, so an odd instruction count
    # is padded with a 00000000 terminator (see the bundled m-ex codes).
    body = list(words)
    if len(body) % 2:
        body.append(0x00000000)
    else:
        body += [0x60000000, 0x00000000]
    lines = [f"C2{addr & 0x01FFFFFF:06X} {len(body) // 2:08X}"]
    for i in range(0, len(body), 2):
        lines.append(f"{body[i]:08X} {body[i + 1]:08X}")
    return lines


def build(audition: bool = False) -> str:
    title = ("Any Climbers - GFX AUDITION [SSBM Nucleus]" if audition
             else "Any Climbers - Generic Follower AI [SSBM Nucleus]")
    out = [f"$!GAMEPLAY | {title}"]
    for addr, (src, sym, what) in SITES.items():
        asm = TEMPLATE.format(src=src, seak=FTKIND_SEAK,
                              zelda=FTKIND_ZELDA, nana=FTKIND_NANA)
        words = assemble(asm)
        block = c2_block(addr, words)
        out.append(f"{block[0]} #{sym} -- {what}")
        out.extend(block[1:])

    block = c2_block(FOLLOWER_ARM, assemble(FOLLOWER_ARM_ASM))
    out.append(f"{block[0]} #ftCo_800A101C+0x40 -- set has_follower on the leader")
    out.extend(block[1:])

    block = c2_block(FOLLOWER_SPAWN, assemble(FOLLOWER_SPAWN_ASM.format(
        seak=FTKIND_SEAK, zelda=FTKIND_ZELDA,
        gap_hi=hex(_f32(FOLLOWER_SPAWN_GAP) >> 16))))
    out.append(f"{block[0]} #ftCommon_800804EC -- a follower spawns behind its leader")
    out.extend(block[1:])

    block = c2_block(SWAP_HOOK, assemble(swap_asm(audition)))
    out.append(f"{block[0]} #Fighter_procUpdate -- D-pad down swaps leader/follower")
    out.extend(block[1:])

    return "\n".join(out) + "\n"


if __name__ == "__main__":
    import sys
    audition = "--audition" in sys.argv
    text = build(audition)
    dest = (Path(__file__).resolve().parents[4] / "scratch" / "audition.ini"
            if audition else
            Path(__file__).resolve().parents[3] / "data" / "any_climbers.ini")
    dest.write_text(text, encoding="utf-8")
    print(text)
    print(f"-> {dest}")
