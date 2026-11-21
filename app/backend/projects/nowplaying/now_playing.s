# Now Playing: when a match starts, a banner with the current song's name
# slides in at the top left, holds for four seconds and slides back out.
#
# Gecko C2 at 0x802F3A60, the final `blr` of ifAll_802F390C (the in-match HUD
# setup, run once per match). The replaced instruction is that `blr`, so this
# code returns with its own `blr` and the C2 trailer is never reached.
#
# The idea is the ACE Build's "BGM Display" plugin; this is a clean-room
# implementation from the decomp's structures, the game's own SIS text library
# and MexTK's mxdt.h, and copies no ACE bytes (see docs/dev/NOW_PLAYING.md).
#
# The look: the white song name on a dark translucent bar flush with the left
# edge of the screen, with a thin gold rule under the bar; no label. Both are
# SIS texts on our own 640x480 canvas: the bar is the name text's own
# background box (HSD_Text.bg_color, drawn from pos to pos + box_size), the
# rule is a second, empty text with only a background. The bar is as wide as
# the name: the text renderer leaves the end of the last line it drew in
# HSD_Text.current_width, so the bar is sized from that each frame. The slide
# moves both texts' pos_x along an ease-out table; in and out use the same
# table, reversed. The bar is 28 px tall from y 18 and the rule ends at y 48,
# so both stay clear of a timed match's clock (its digits start at y 55).
#
# Pause. A player's pause (fn_8016CA68) hides the HUD and sets a bit in the
# scene's pause bits (gm_80479D58.unk_10.x0, read by gm_801A45E8): 1 in a
# match, 2 in Training; the free camera (gmcamera.c) sets 3 and hides the HUD
# too. In a match the scene loop then stops every proc on p_link 15, the HUD's
# own, so the GObj lives on p_link 16 (the game's match clock and pause-camera
# UI use it too), which still runs. While any of those bits is set the proc
# parks both texts off-screen, where they wait to be measured, and does not
# count the frame; on unpause the slide picks up where it was.
#
# The hook makes one GObj with a state block:
#   +0x00 Text*   bar   (the name text; 0 until the song is known)
#   +0x04 Text*   rule
#   +0x08 frames  (frames waited, then frames shown)
#   +0x0C name    (the label, made safe for the SIS encoder, see below)
# No song, no label, or no music within WAIT_FRAMES: the GObj just frees
# itself. After the slide out the texts are hidden and the GObj frees itself;
# the SIS heap is reset with the scene, which frees the texts and canvas.
#
# The name. The game's ASCII-to-SIS encoder (HSD_SisLib_803A67EC) handles
# letters, digits, space and " ' , - . : itself; any other byte is taken as
# the first half of a Shift-JIS pair together with the byte after it, which
# swallows that byte (or the terminator, and then runs on into stack garbage).
# Its output goes to a 128-byte stack buffer in Text_AddSubtext with no bounds
# check, at 3 bytes a letter and up to 7 for a space or digit. So the copy
# passes letters through and writes everything else as a full-width Shift-JIS
# pair (0x81xx punctuation and space, 0x82xx digits), which the encoder turns
# into 3 bytes each as well (1 if the font has no such glyph). With kerning
# on, the space/digit spacing opcodes the encoder would add are ignored by the
# renderer anyway, so the result looks the same. m-ex already stores labels
# in Shift-JIS with punctuation as such pairs ("100%" is "100" 81 93); a lead
# byte with a valid second byte is copied as it is, so kana show too. Any
# other byte (control, stray high byte) becomes a full-width '?', and a name
# over NAME_MAX glyphs ends in "...". Every glyph lands in the built-in font
# (codes 0x2000-0x211E), and NAME_MAX glyphs are at most 3 * 32 = 96 encoded
# bytes and 64 input bytes.

    .set GOBJ_CREATE,   0x803901F0   # GObj_Create(class, p_link, prio)
    .set GOBJ_FREE,     0x80390228   # HSD_GObjPLink_80390228(gobj)
    .set GOBJ_USERDATA, 0x80390B68   # GObj_InitUserData(gobj, kind, free, data)
    .set GOBJ_PROC,     0x8038FD54   # HSD_GObj_SetupProc(gobj, func, prio)
    .set MEM_ALLOC,     0x8037F1E4   # HSD_MemAlloc(size)
    .set MEM_FREE,      0x8037F1B0   # HSD_Free(ptr)
    .set CURRENT_BGM,   0x801C5A94   # Ground_801C5A94: stage_info.x98
    .set MEX_GETDATA,   0x803D7094   # m-ex: MEX_GetData(index)
    .set TEXT_CANVAS,   0x803A611C   # HSD_SisLib_803A611C (Text_CreateCanvas)
    .set TEXT_CREATE,   0x803A6754   # HSD_SisLib_803A6754 (Text_CreateText)
    .set TEXT_ADD,      0x803A6B98   # HSD_SisLib_803A6B98 (Text_AddSubtext, variadic)
    .set PAUSE_BITS,    0x80479D68   # gm_80479D58.unk_10.x0 (u8), see "Pause" above

    .set PAUSED,        0x0E         # bits 1-3: paused (match, Training), free camera
    .set GOBJ_CLASS,    14           # HSD_GOBJ_CLASS_UI
    .set GOBJ_PLINK,    16           # runs while paused (p_link 15, the HUD's, stops)
    .set MXDT_MEXDATA,  16
    .set FONT,          4            # a SIS slot the game never loads: the built-in font
    .set WAIT_FRAMES,   600
    .set SLIDE,         14           # frames per slide (table entries)
    .set HOLD,          240          # frames fully shown (4 s)
    .set SHOW_END,      2 * SLIDE + HOLD
    .set NAME_MAX,      32           # glyphs, "..." included (about 370 px of bar)

    .set ST_BAR,        0x00
    .set ST_RULE,       0x04
    .set ST_FRAMES,     0x08
    .set ST_NAME,       0x0C         # up to 2 * NAME_MAX + 1 bytes
    .set ST_SIZE,       0x60

    .set GOBJ_USER,     0x2C         # HSD_GObj.user_data
    .set TEXT_X,        0x00         # HSD_Text.pos_x
    .set TEXT_Y,        0x04         # HSD_Text.pos_y
    .set TEXT_BOX_W,    0x0C         # HSD_Text.box_size_x
    .set TEXT_BOX_H,    0x10         # HSD_Text.box_size_y
    .set TEXT_BG,       0x2C         # HSD_Text.bg_color (RGBA, drawn when A != 0)
    .set TEXT_SCALE,    0x34         # HSD_Text.x34 (x, y): copied into each new subtext
    .set TEXT_KERNING,  0x49         # HSD_Text.default_kerning
    .set TEXT_HIDDEN,   0x4D         # HSD_Text.hidden
    .set TEXT_WIDTH,    0x70         # HSD_Text.current_width: end of the last line drawn

    .macro call addr
    lis r12, \addr@h
    ori r12, r12, \addr@l
    mtctr r12
    bctrl
    .endm

# ---- hook: runs at the end of the HUD setup ---------------------------------
    stwu r1, -0x20(r1)
    mflr r0
    stw r0, 0x24(r1)
    stw r31, 0x1C(r1)
    stw r30, 0x18(r1)

    li r3, GOBJ_CLASS
    li r4, GOBJ_PLINK
    li r5, 0
    call GOBJ_CREATE
    mr. r31, r3
    beq hook_exit

    li r3, ST_SIZE
    call MEM_ALLOC
    mr. r30, r3
    bne have_state
    mr r3, r31
    call GOBJ_FREE
    b hook_exit
have_state:
    li r0, 0
    stw r0, ST_BAR(r30)
    stw r0, ST_RULE(r30)
    stw r0, ST_FRAMES(r30)
    mr r3, r31
    li r4, 0
    lis r5, MEM_FREE@h
    ori r5, r5, MEM_FREE@l
    mr r6, r30
    call GOBJ_USERDATA

    bl think_end                 # LR = address of think

# ---- think(gobj): the GObj's proc, every frame -------------------------------
think:
    stwu r1, -0x40(r1)
    mflr r0
    stw r0, 0x44(r1)
    stmw r24, 0x18(r1)
    mr r31, r3                   # gobj
    lwz r30, GOBJ_USER(r3)       # state
    bl data_end
data:
# Subtext y is the top of a 32-unit line and a glyph sits at its bottom, so a
# glyph scaled by sy starts 32 * (1 - sy) below its y.
d_bar_y:    .float 18.0          # bar top
d_bar_h:    .float 28.0          # bar height
d_rule_y:   .float 46.0          # rule top (bar bottom); it ends at 48, the clock's digits start at 55
d_rule_h:   .float 2.0
d_min_w:    .float 64.0          # the bar is never narrower than this
d_pad_r:    .float 16.0          # bar past the end of the name
d_away:     .float -1000.0       # where the texts wait to be measured
d_name_x:   .float 18.0
d_name_y:   .float -10.0         # from the bar top: glyphs 22.7..40 on screen
d_name_sx:  .float 0.56
d_name_sy:  .float 0.54
d_zero:     .float 0.0
d_bar_rgba: .byte 0x0C, 0x0E, 0x18, 0xC8  # dark blue-grey, 78% opaque
d_gold:     .byte 0xFF, 0xC8, 0x3C, 0xFF  # the rule
# how far out the banner is, slide frame 0..SLIDE-1: (1 - i/13)^3, an ease-out
d_ease:
    .float 1.000000, 0.786527, 0.605826, 0.455166, 0.331816, 0.233045, 0.156122
    .float 0.098316, 0.056896, 0.029131, 0.012289, 0.003641, 0.000455, 0.000000
# ASCII -> second byte of its full-width Shift-JIS form (first byte 0x81), for
# every printable non-letter, non-digit; all are glyphs in the built-in font
d_pairs:
    .byte 0x20, 0x40,  0x21, 0x49,  0x22, 0x68,  0x23, 0x94,  0x24, 0x90
    .byte 0x25, 0x93,  0x26, 0x95,  0x27, 0x66,  0x28, 0x69,  0x29, 0x6A
    .byte 0x2A, 0x96,  0x2B, 0x7B,  0x2C, 0x43,  0x2D, 0x7C,  0x2E, 0x44
    .byte 0x2F, 0x5E,  0x3A, 0x46,  0x3B, 0x47,  0x3C, 0x83,  0x3D, 0x81
    .byte 0x3E, 0x84,  0x3F, 0x48,  0x40, 0x97,  0x5B, 0x6D,  0x5C, 0x5E
    .byte 0x5D, 0x6E,  0x5E, 0x4F,  0x5F, 0x51,  0x60, 0x66,  0x7B, 0x6F
    .byte 0x7C, 0x62,  0x7D, 0x70,  0x7E, 0x60
    .set NPAIRS, 33
d_fmt:      .asciz "%s"
    .balign 4
data_end:
    mflr r29                     # r29 = data
    lwz r28, ST_BAR(r30)
    lis r4, PAUSE_BITS@ha
    lbz r4, PAUSE_BITS@l(r4)
    andi. r4, r4, PAUSED
    beq counting
    # paused: the frame does not count; the texts wait off-screen
    cmpwi r28, 0
    beq think_exit               # still waiting for the music
    lfs f0, d_away - data(r29)
    stfs f0, TEXT_X(r28)
    lwz r27, ST_RULE(r30)
    cmpwi r27, 0
    beq think_exit
    stfs f0, TEXT_X(r27)
    b think_exit

counting:
    lwz r4, ST_FRAMES(r30)
    addi r4, r4, 1
    stw r4, ST_FRAMES(r30)       # frames++
    cmpwi r28, 0
    bne showing

    # waiting for the match music
    cmpwi r4, WAIT_FRAMES
    bgt kill
    call CURRENT_BGM
    mr. r27, r3                  # bgm id, -1 until the music starts
    blt think_exit
    li r3, MXDT_MEXDATA
    call MEX_GETDATA
    cmpwi r3, 0
    beq kill
    lwz r4, 0x00(r3)             # MexData.metadata
    lwz r4, 0x20(r4)             # MexMetaData.bgm_count
    cmpw r27, r4
    bge kill
    lwz r4, 0x14(r3)             # MexData.music
    cmpwi r4, 0
    beq kill
    lwz r4, 0x0C(r4)             # MexMusicTable.labels
    cmpwi r4, 0
    beq kill
    slwi r0, r27, 2
    lwzx r27, r4, r0             # label
    cmpwi r27, 0
    beq kill

    # copy the label in a form the SIS encoder reads one glyph at a time
    addi r26, r30, ST_NAME       # name buffer
    li r5, 0                     # label index
    li r6, 0                     # name index
    li r7, 0                     # where "..." goes if the name is too long
    li r9, 0                     # glyphs so far
copy_loop:
    lbzx r0, r27, r5
    cmpwi r0, 0
    beq copy_done
    addi r5, r5, 1
    cmpwi r9, NAME_MAX
    bge copy_long
    cmpwi r9, NAME_MAX - 3
    bne copy_count
    mr r7, r6
copy_count:
    addi r9, r9, 1
    li r10, 0x81
    li r12, 0x48                 # full-width '?' for anything without a glyph
    cmplwi r0, 0x80
    blt copy_ascii
    # m-ex writes labels in Shift-JIS (punctuation as full-width pairs): a
    # lead byte with a valid second byte goes through as it is
    cmplwi r0, 0x81
    blt copy_pair
    cmplwi r0, 0x9F
    ble copy_lead
    cmplwi r0, 0xE0
    blt copy_pair
    cmplwi r0, 0xFC
    bgt copy_pair
copy_lead:
    lbzx r11, r27, r5
    cmplwi r11, 0x40
    blt copy_pair
    cmplwi r11, 0xFC
    bgt copy_pair
    cmplwi r11, 0x7F
    beq copy_pair
    mr r10, r0
    mr r12, r11
    addi r5, r5, 1
    b copy_pair
copy_ascii:
    cmplwi r0, 0x20              # control characters: '?'
    blt copy_pair
    ori r11, r0, 0x20            # letters: the encoder maps these itself
    cmplwi r11, 0x61
    blt copy_digit
    cmplwi r11, 0x7A
    bgt copy_digit
    stbx r0, r26, r6
    addi r6, r6, 1
    b copy_loop
copy_digit:
    li r10, 0x82                 # digits: 0x824F..0x8258
    mr r12, r0                   # (addi with rA = r0 would read 0)
    addi r12, r12, 0x1F
    cmplwi r0, 0x30
    blt copy_punct
    cmplwi r0, 0x39
    ble copy_pair
copy_punct:
    li r10, 0x81
    li r12, 0x48                 # full-width '?' unless the table has it (0x7F)
    addi r11, r29, d_pairs - data - 2
    li r4, NPAIRS
    mtctr r4
copy_find:
    lbzu r4, 2(r11)
    cmpw r4, r0
    bne copy_next
    lbz r12, 1(r11)
    b copy_pair
copy_next:
    bdnz copy_find
copy_pair:
    stbx r10, r26, r6
    addi r6, r6, 1
    stbx r12, r26, r6
    addi r6, r6, 1
    b copy_loop
copy_long:                       # one glyph too many: cut, and end in "..."
    mr r6, r7
    li r9, NAME_MAX
    add r11, r26, r6
    lbz r0, -2(r11)              # no space before the dots
    cmpwi r0, 0x81
    bne copy_dots
    lbz r0, -1(r11)
    cmpwi r0, 0x40
    bne copy_dots
    addi r6, r6, -2
copy_dots:
    li r10, 0x81
    li r12, 0x44                 # full-width '.'
    li r4, 3
    mtctr r4
copy_dot:
    stbx r10, r26, r6
    addi r6, r6, 1
    stbx r12, r26, r6
    addi r6, r6, 1
    bdnz copy_dot
copy_done:
    cmpwi r9, 0
    beq kill
    li r0, 0
    stbx r0, r26, r6

    # a canvas with its own 640x480 ortho camera, drawn after the HUD
    li r3, FONT
    li r4, 0                     # no parent: create the camera
    li r5, 9                     # class / p_link / p_prio / gx_link / gx_prio /
    li r6, 13                    #   camera render prio: the values the game's
    li r7, 0                     #   own in-match camera text uses (gmcamera.c)
    li r8, 14
    li r9, 0
    li r10, 11
    call TEXT_CANVAS
    mr r25, r3                   # canvas index for this font
    mr r4, r25
    li r3, FONT
    call TEXT_CREATE
    mr. r28, r3
    beq kill
    stw r28, ST_BAR(r30)
    mr r4, r25
    li r3, FONT
    call TEXT_CREATE
    mr. r27, r3
    beq kill                     # hides the bar
    stw r27, ST_RULE(r30)
    li r0, 0
    stw r0, ST_FRAMES(r30)       # restart the count for the display time

    # the bar: name text with a background box, out of sight until measured
    li r0, 1
    stb r0, TEXT_KERNING(r28)
    lfs f0, d_away - data(r29)
    stfs f0, TEXT_X(r28)
    lfs f0, d_bar_y - data(r29)
    stfs f0, TEXT_Y(r28)
    lfs f0, d_min_w - data(r29)
    stfs f0, TEXT_BOX_W(r28)
    lfs f0, d_bar_h - data(r29)
    stfs f0, TEXT_BOX_H(r28)
    lwz r0, d_bar_rgba - data(r29)
    stw r0, TEXT_BG(r28)

    lfs f0, d_name_sx - data(r29)   # the name (text_color stays white)
    stfs f0, TEXT_SCALE(r28)
    lfs f0, d_name_sy - data(r29)
    stfs f0, TEXT_SCALE + 4(r28)
    lfs f1, d_name_x - data(r29)
    lfs f2, d_name_y - data(r29)
    mr r3, r28
    addi r4, r29, d_fmt - data   # "%s": a '%' in the name is never a format
    mr r5, r26
    creqv 6, 6, 6
    call TEXT_ADD

    # the rule: an empty text that is only its background box
    lfs f0, d_away - data(r29)
    stfs f0, TEXT_X(r27)
    lfs f0, d_rule_y - data(r29)
    stfs f0, TEXT_Y(r27)
    lfs f0, d_min_w - data(r29)
    stfs f0, TEXT_BOX_W(r27)
    lfs f0, d_rule_h - data(r29)
    stfs f0, TEXT_BOX_H(r27)
    lwz r0, d_gold - data(r29)
    stw r0, TEXT_BG(r27)
    lfs f1, d_zero - data(r29)
    fmr f2, f1
    mr r3, r27
    li r4, 0                     # no format: a subtext with no glyphs
    creqv 6, 6, 6
    call TEXT_ADD
    b think_exit

showing:                         # r4 = frames since the banner was made (1, 2, ...)
    cmpwi r4, SHOW_END
    bgt kill
    lwz r27, ST_RULE(r30)
    # width: the end of the name as last drawn (at least d_min_w), plus padding
    lfs f1, TEXT_WIDTH(r28)
    lfs f0, d_min_w - data(r29)
    fcmpo cr0, f0, f1
    blt have_width               # (a NaN takes the minimum)
    fmr f1, f0
have_width:
    lfs f0, d_pad_r - data(r29)
    fadds f1, f1, f0
    stfs f1, TEXT_BOX_W(r28)
    stfs f1, TEXT_BOX_W(r27)
    # slide: table index s-1 coming in, the last entry (0) while held, then back
    addi r5, r4, -1
    cmpwi r4, SLIDE
    ble have_index
    li r5, SLIDE - 1
    cmpwi r4, SLIDE + HOLD
    ble have_index
    subfic r5, r4, SHOW_END
have_index:
    slwi r5, r5, 2
    addi r6, r29, d_ease - data
    lfsx f2, r6, r5
    fmuls f1, f1, f2             # x = -width * ease: flush left when in,
    fneg f1, f1                  #   just off the left edge when out
    stfs f1, TEXT_X(r28)
    stfs f1, TEXT_X(r27)
    b think_exit

kill:                            # hide what was made, free the GObj
    lwz r3, ST_BAR(r30)
    cmpwi r3, 0
    beq kill_rule
    li r0, 1
    stb r0, TEXT_HIDDEN(r3)
kill_rule:
    lwz r3, ST_RULE(r30)
    cmpwi r3, 0
    beq kill_gobj
    li r0, 1
    stb r0, TEXT_HIDDEN(r3)
kill_gobj:
    mr r3, r31
    call GOBJ_FREE               # also frees the state block (HSD_Free)
think_exit:
    lmw r24, 0x18(r1)
    lwz r0, 0x44(r1)
    mtlr r0
    addi r1, r1, 0x40
    blr

# ---- back in the hook: attach think as the GObj's proc ----------------------
think_end:
    mflr r4
    mr r3, r31
    li r5, 0
    call GOBJ_PROC

hook_exit:
    lwz r30, 0x18(r1)
    lwz r31, 0x1C(r1)
    lwz r0, 0x24(r1)
    mtlr r0
    addi r1, r1, 0x20
    blr                          # the replaced instruction
