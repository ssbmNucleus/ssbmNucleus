# L-load: on the character select screen (CSS), tapping L scrolls a player
# through their fighter's group -- base -> alternate 1 -> ... -> base.
#
# Gecko C2 at 0x80263334, the epilogue of fn_80262F44 (a CSS GObj proc that runs
# every CSS frame). The replaced instruction, lwz r0,0x34(r1), is the last line.
# Clean-room code from the decomp's structures; see docs/dev/L_LOAD.md.
#
# The group table sits between `bl after_table` and `after_table`. It is filled
# per project at export (projects/lload/code.py), so this source assembles with
# an empty table and gen_code.py splits the words around it:
#   count (base + alternates), then count x {external fighter id, CSS icon}
#   ... ; a count of 0 ends the table.
# Each alternate's CSS icon is "tucked" behind its base (projects/lload/layout.py):
# the CSS takes the portrait and costume count from the selected icon's fighter,
# so the selected icon has to move along with the selected fighter.

    .set CSSDATA_PTR_HI, 0x804D
    .set CSSDATA_PTR_LO, 0x6CB0
    .set DOORS,        0x803F0DFC
    .set PADCOPY,      0x804C20BC
    .set DUPCHECK,     0x8025DAA0   # mnCharSel: is this door's costume taken? (m-ex patched)
    .set REDRAW,       0x8025DB34   # mnCharSel: redraw this door's portrait (m-ex patched)
    .set COSTUMES,     0x80169238   # costume count for an external id
    .set MENU_SFX,     0x80024030   # lbAudioAx_80024030(2) = the costume-change sound

    .macro call addr
    lis r12, \addr@h
    ori r12, r12, \addr@l
    mtctr r12
    bctrl
    .endm

    stwu r1, -0x30(r1)
    mflr r0
    stw r0, 0x34(r1)
    stmw r25, 0x10(r1)
    bl after_table
table:
    # groups: count (base + alternates), then count x {external id, icon}; count 0 ends
    .byte 0x00
    .balign 4
after_table:
    mflr r31                     # r31 = table
    lis r30, CSSDATA_PTR_HI
    lwz r30, CSSDATA_PTR_LO(r30) # CSSData*
    cmpwi r30, 0
    beq exit
    li r29, 0                    # port
port_loop:
    lis r3, PADCOPY@h
    ori r3, r3, PADCOPY@l
    mulli r4, r29, 0x44
    add r28, r3, r4              # &HSD_PadCopyStatus[p]
    lwz r0, 8(r28)               # trigger (newly pressed)
    andi. r0, r0, 0x40           # L
    beq next_port
    lis r3, DOORS@h
    ori r3, r3, DOORS@l
    mulli r4, r29, 0x24
    add r27, r3, r4              # &doors[p]
    lbz r0, 0xB(r27)             # p_kind (3 = closed)
    cmpwi r0, 3
    beq next_port
    add r26, r30, r4             # players[p] is at +0x70
    lbz r5, 0x70(r26)            # c_kind (external id)
    mr r6, r31
group_loop:
    lbz r7, 0(r6)                # entries in this group
    cmpwi r7, 0
    beq next_port
    li r8, 0
entry_loop:
    slwi r9, r8, 1
    add r9, r9, r6
    lbz r10, 1(r9)               # entry's external id
    cmplw r10, r5
    beq found
    addi r8, r8, 1
    cmplw r8, r7
    blt entry_loop
    slwi r9, r7, 1               # skip to the next group
    add r6, r6, r9
    addi r6, r6, 1
    b group_loop
found:
    addi r8, r8, 1               # next entry, wrapping to the base
    cmplw r8, r7
    blt have_next
    li r8, 0
have_next:
    slwi r9, r8, 1
    add r9, r9, r6
    lbz r8, 1(r9)                # new external id
    lbz r9, 2(r9)                # new icon
apply:
    stb r8, 0x70(r26)            # c_kind
    stb r9, 0xE(r27)             # sel_icon
    mr r25, r8
    li r0, 0
    stb r0, 0xD(r27)             # costume 0, then the CSS's own duplicate rule
dup:
    mr r3, r29
    call DUPCHECK
    cmpwi r3, 0
    beq dup_done
    lbz r10, 0xD(r27)
    addi r10, r10, 1
    stb r10, 0xD(r27)
    mr r3, r25
    call COSTUMES
    lbz r0, 0xD(r27)
    cmpw r0, r3
    blt dup
    li r0, 0
    stb r0, 0xD(r27)
dup_done:
    mr r3, r29
    call REDRAW
    li r3, 2
    call MENU_SFX
    lwz r0, 8(r28)
    rlwinm r0, r0, 0, 26, 24     # consume the L press (clear bit 0x40)
    stw r0, 8(r28)
next_port:
    addi r29, r29, 1
    cmpwi r29, 4
    blt port_loop
exit:
    lmw r25, 0x10(r1)
    lwz r0, 0x34(r1)
    mtlr r0
    addi r1, r1, 0x30
    lwz r0, 0x34(r1)             # replaced instruction
