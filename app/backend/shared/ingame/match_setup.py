"""
match_setup.py -- direct-memory match setup shared by the in-game harness.

Two small WriteProcessMemory pokes that let the harness load a match ALONE (one
player, no CPU): relax the CSS "Ready to Fight" gate so a solo roster can start,
and force Time mode with no time limit so a one-player match doesn't instantly
end. Used by both the crash-test runner (runner.py) and the stage screenshot
capture (capture.py) -- loading solo is simpler and faster (no add-CPU cursor
sweep) and nothing can attack/SD/move the camera.

NTSC 1.02 addresses (doldecomp/melee):
  * CSS start gate: mncharsel fn_80262F44 +0x120 == 0x80263064, originally
    `cmpwi r4, 2` (r4 = valid player count); patch to `cmpwi r4, 1`.
  * GameRules (persistent menu rules the CSS reads) at 0x8045BF10: mode byte +0x02
    (0=Time), time-limit byte +0x03 (0 = no time / infinite).
Always RPM-read the gate first and only patch the exact expected opcode.
"""

import time

HOOK_1P = 0x80263064
HOOK_1P_ORIG = 0x2C040002        # cmpwi r4, 2  (require >= 2 players)
HOOK_1P_PATCH = 0x2C040001       # cmpwi r4, 1  (allow a solo start)

GAMERULES = 0x8045BF10
RULES_MODE = GAMERULES + 0x02    # 0 = Time, 1 = Stock, 2 = Coin
RULES_TIME = GAMERULES + 0x03    # minutes; 0 = no time / infinite

# --- cursor-free selection (write the match directly, then warp CSS->SSS) -------
# The CSS cursor is just an input method; the match loads whatever the per-port
# player block holds. So we write a solo player block and routing-poke the CSS
# straight to the stage-select screen -- no cursor lock, no add-CPU, no START
# "ready player" gate. The caller then force_selects the stage (the engine's own
# start, which finalizes rules so the solo match sustains).
CSS_PLAYERS = 0x80480820         # CSS-embedded StartMeleeData players, stride 0x24
VSDATA_PTR = 0x804D3EE0          # *(this)+0x5F8 = persistent VsModeData players
VS_PLAYERS_OFF = 0x5F8
PLAYER_STRIDE = 0x24
# PlayerInitData: c_kind +0x00, slot_type +0x01 (0=human,1=cpu,3=NA), stocks +0x02,
#                 color/costume +0x03, port +0x04, controller +0x07, team +0x09.
PENDING_SCENE = 0x80479D35       # next minor scene (target_minor + 1); SSS = 0x02
LOOP_BREAK = 0x80479D64          # break the current scene loop so the next loads


def _noop(*_a, **_k):
    pass


def patch_one_player(d, log=_noop, retries=15):
    """Relax the CSS start gate to allow a SOLO match. Returns True if 1-player
    starts are enabled (patched now or already), False if the hook never read as
    expected (caller should fall back to adding a 2nd player).

    Retries the read: right after attaching, that memory can momentarily read as
    0 / garbage, and a single bad read would silently drop us onto the slower
    cursor+CPU path. We re-check for a few seconds until the opcode appears."""
    last = None
    for _ in range(max(1, retries)):
        cur = d.u32(HOOK_1P)
        last = cur
        if cur == HOOK_1P_PATCH:
            return True
        if cur == HOOK_1P_ORIG:
            d.write_u32(HOOK_1P, HOOK_1P_PATCH)
            if d.u32(HOOK_1P) == HOOK_1P_PATCH:
                log("1-player start enabled (patched 0x80263064 cmpwi r4,2 -> r4,1)")
                return True
        time.sleep(0.2)
    log(f"1-player hook never settled at 0x80263064 (last 0x{(last or 0):08X}); "
        f"falling back to a 2nd player")
    return False


def force_time_infinite(d, log=_noop):
    """Time mode + no time limit, so a solo match doesn't instantly end."""
    d.write_u8(RULES_MODE, 0)
    d.write_u8(RULES_TIME, 0)
    log("VS rules set to Time / no time limit")


def write_solo_player(d, ckind, color=0):
    """Write a solo human match -- port 0 = `ckind`/`color`, ports 1-5 NA -- into
    BOTH the CSS-embedded StartMeleeData AND the persistent VsModeData, so a
    CSS->SSS memory warp (which skips CSS_Exit's panel->match copy) still starts a
    valid 1-player match as the chosen fighter. `ckind` is the EXTERNAL char id."""
    bases = [CSS_PLAYERS]
    container = d.u32(VSDATA_PTR)
    if container and 0x80000000 <= container < 0x81800000:
        bases.append(container + VS_PLAYERS_OFF)
    for base in bases:
        d.write_u8(base + 0x00, ckind & 0xFF)   # c_kind (external char id)
        d.write_u8(base + 0x01, 0)              # slot type: human
        d.write_u8(base + 0x02, 4)              # stocks
        d.write_u8(base + 0x03, color & 0xFF)  # costume / color slot
        d.write_u8(base + 0x04, 0)             # port
        d.write_u8(base + 0x07, 0)             # controller index
        d.write_u8(base + 0x09, 0)             # team
        d.write_u8(base + 0x0A, 0x78)          # nametag: none
        for port in range(1, 6):
            d.write_u8(base + port * PLAYER_STRIDE + 0x01, 3)  # NA (solo)


def _write_player_block(d, base, port, ckind, color, slot_type):
    """Write one PlayerInitData block at `base` (PlayerInitData layout, decomp
    src/melee/mn/types.h): c_kind +0x00, slot_type +0x01 (0=HMN, 1=CPU, 3=NA),
    stocks +0x02, color +0x03, port +0x04, sub_color +0x07, team +0x09, nametag
    +0x0A."""
    d.write_u8(base + 0x00, ckind & 0xFF)
    d.write_u8(base + 0x01, slot_type & 0xFF)
    d.write_u8(base + 0x02, 4)
    d.write_u8(base + 0x03, color & 0xFF)
    d.write_u8(base + 0x04, port & 0xFF)
    # +0x07 is sub_color (PlayerInitData, decomp src/melee/mn/types.h). Vanilla
    # copies it into StaticPlayer.controller_index (gm_16AE.c fn_8016D8AC), but
    # that field is NOT what the fighter polls pads with -- and our CSS->SSS warp
    # skips that whole PlayerInitData->StaticPlayer copy anyway. The mirroring bug
    # (bag polling pad 0 = the harness pipe) is fixed by writing the in-match
    # StaticPlayer.player_id directly after the match loads; see
    # fix_player_pad_indices(). Keep sub_color 0.
    d.write_u8(base + 0x07, 0)
    d.write_u8(base + 0x09, port & 0xFF)   # each port its own team = no friendly
    d.write_u8(base + 0x0A, 0x78)          # nametag: none


def _player_bases(d):
    """The two player-array bases the CSS->SSS warp path must both hold: the
    CSS-embedded StartMeleeData players, and the persistent VsModeData players
    (the warp skips CSS_Exit's panel->match copy, so both must be written)."""
    bases = [CSS_PLAYERS]
    container = d.u32(VSDATA_PTR)
    if container and 0x80000000 <= container < 0x81800000:
        bases.append(container + VS_PLAYERS_OFF)
    return bases


def write_bag_player(d, ckind, color=0, bag_ckind=0x01, bag_color=0, port=1):
    """Write a TWO-player match: port 0 = attacker (`ckind`/`color`), `port` =
    a punching-bag second HUMAN (`bag_ckind`/`bag_color`), all other ports NA.

    The bag is a HUMAN port with NO controller sending input. The harness pipe
    drives player slot 0 (the attacker); the bag slot has no pipe behind it, so
    its per-frame pad stays neutral and the fighter just stands in idle. Unlike
    a CPU it never walks over, attacks, or moves the camera (the CLAUDE.md
    warning). This makes on-hit-only effects (Raptor Boost hit burst, PK Fire
    pillar, ...) capturable without the CPU confound.

    Bag defaults to DK (0x01): a big, neutral hurtbox that's easy to connect
    with. `bag_ckind` is the EXTERNAL char id (see char_select.CKIND -- DK=0x01,
    Bowser=0x05). Returns the (attacker_slot, bag_slot) tuple written."""
    bag_port = port if port and port != 0 else 1
    for base in _player_bases(d):
        _write_player_block(d, base + 0, 0, ckind, color, 0)              # attacker
        _write_player_block(d, base + bag_port * PLAYER_STRIDE, bag_port,
                            bag_ckind, bag_color, 0)                       # bag (HMN)
        for p in range(1, 6):
            if p == bag_port:
                continue
            d.write_u8(base + p * PLAYER_STRIDE + 0x01, 3)                 # NA
    return (0, bag_port)


# --- in-match pad routing (fixes the punching-bag mirror) ----------------------
# The fighter reads its per-frame controller input from HSD_PadGameStatus indexed
# by StaticPlayer.player_id (decomp: fighter.c sets fp->x618_player_id =
# Player_GetPlayerId(fp->player_id), then reads HSD_PadGameStatus[x618_player_id]).
# On the normal CSS_Exit path, gm_16AE.c fn_8016D8AC copies PlayerInitData->slot
# into StaticPlayer.player_id (slot 0 -> its own index, else slot-1). Our CSS->SSS
# warp SKIPS that copy, so Player_InitOrResetPlayer's default player_id=0 sticks
# for EVERY slot -> every fighter polls HSD_PadGameStatus[0] = the harness pipe ->
# the bag MIRRORS the attacker frame-for-frame (bag did Mario's up-B; both clanked
# into Rebound). Solo runs never noticed: the lone player IS pad 0.
#
# StaticPlayer array: base 0x80453080, stride 0xE90 (matches shared/ingame/gamestate.py).
#   +0x46  controller_index   (color/effects, NOT input -- do not rely on it)
#   +0x48  player_id          (the pad-status index the fighter actually polls)
# The fighter caches player_id at spawn into ft+0x618, so we fix BOTH: the
# StaticPlayer field (source of truth) and each live fighter's cached copy.
PLAYER_BLOCK = 0x80453080
PLAYER_BLOCK_STRIDE = 0xE90
STATIC_PLAYER_ID = 0x48          # StaticPlayer.player_id
FT_X618_PLAYER_ID = 0x618        # Fighter.x618_player_id (cached at spawn)


def fix_player_pad_indices(d, ports, log=_noop):
    """Route each in-match player to its OWN controller pad. Call once the match
    is in-game (fighters spawned), same place as other post-load RAM patches.

    `ports` is the iterable of active port indices (e.g. (0, 1) for attacker +
    bag). Each port P is pointed at HSD_PadGameStatus[P]: on the warp path they
    all default to 0 (the pipe), which makes the bag mirror the attacker. Writes
    both StaticPlayer.player_id (+0x48) and, if the fighter is already spawned,
    its cached ft+0x618 copy."""
    for port in ports:
        base = PLAYER_BLOCK + PLAYER_BLOCK_STRIDE * port
        d.write_u8(base + STATIC_PLAYER_ID, port & 0xFF)
        gobj = d.u32(base + 0xB0)               # fighter GObj
        ft = d.u32(gobj + 0x2C) if gobj else 0  # Fighter struct (user_data)
        if ft:
            d.write_u8(ft + FT_X618_PLAYER_ID, port & 0xFF)
    log(f"routed in-match pads: ports {tuple(ports)} each poll their own pad")


# --- Kirby copy-ability install (no inhale needed) ------------------------------
# Solo/bag harness matches can never inhale+swallow, so the EfKb<XX> copy banks
# never load through gameplay. Decomp lever (kirby.md §6.4a): ftKb_Init_OnDeath
# (ftkirby.c:3039) runs on REBIRTH and, if the persisted copy kind is armed,
# calls ftKb_SpecialN_800F1BAC(gobj, unk4D, 0) -- the real copy INSTALL (sets
# fp->fv.kb.hat.kind, installs the per-donor special-N callbacks, loads the
# copy article; Kirby preloads ALL EfKb copy files, so the donor need not be in
# the match). Poking the live hat.kind alone does NOT install the stored
# callbacks (live-proven: neutral-B stays inhale), and a PRE-spawn poke is
# cleared by match load.
#
# ⚠ Do NOT set StaticPlayer flags.b1 (+0xAC mask 0x40) as the "has copy" arm --
# that bit is the SINGLE-PLAYER TEAM-FIGHTER flag (Classic Kirby Team; set by
# gm_1601.c:5105/vi0501.c): the vanilla condition `Player_GetFlagsBit1 &&
# unk4D != 4` only ever fires for Classic team Kirbys, and the same bit makes
# gm_80167320 REMOVE the player on death (Player_SetSlottype NA -- team members
# have one life) instead of respawning. Live-proven failure mode: gobj NULL
# forever after the KO. The death->respawn->OnDeath chain is one synchronous
# call stack (ftCo_800BFD9C -> gm_80167320 -> fn_8016719C -> Player_80032768 ->
# Fighter_UnkProcessDeath_80068354 -> ftData_OnDeath[kind]), so the two b1
# reads can never be split by RPM pokes. Instead we NOP the b1 check INSIDE
# ftKb_Init_OnDeath (same only-patch-the-expected-opcode discipline as the 1P
# CSS gate above) so `unk4D != 4` alone installs the copy on rebirth:
#   0x800EE638  beq +0x2C (0x4182002C, skip-install if !FlagsBit1) -> nop
#   StaticPlayer + 0x4D (u8) unk4D = persisted copy kind (INTERNAL FtKind);
#                                    4 = FTKIND_KIRBY = "no copy" (disarmed)
#
# ⚠ JIT gotcha: apply the code patch EARLY (arm_kirby_copy_ondeath, same boot
# phase as patch_one_player) -- Dolphin's JIT does not see external WPM writes
# to code it already compiled, and ftKb_Init_OnDeath runs at Kirby's INITIAL
# spawn too, so a patch applied mid-match hits a stale compiled block and does
# nothing (live-proven). Patched early it is side-effect-free: the vanilla
# match init leaves unk4D = 4 (= FTKIND_KIRBY, live-read), so the initial
# spawn's unk4D != 4 check still skips the install until a caller pokes a
# donor kind and rebirths.
#
# ⚠ THE DONOR MUST BE IN THE MATCH (e.g. bag=donor). Melee loads a donor's
# Kirby-copy data (PlKbCp hat article + EfKb effect bank) at match load only
# for fighters PRESENT in the match; installing a copy of an absent donor
# dereferences never-loaded data and HANGS the game -- live-proven: the
# frame counter freezes permanently right after the rebirth install, fighter
# stuck in Sleep(11), unrecoverable (kirby.md §6.4b).
SP_UNK4D = 0x4D
SP_STOCKS = 0x8E                 # s8 Player.stocks (decomp pl/player.h 0x8E)
FT_HAT_KIND = 0x2238             # fp + ftKb_FighterVars(0x222C) + hat.kind(0xC)
                                  # -- a u32 (stw in ftKb_Init_OnDeath): READ u32
KB_ONDEATH_B1_CHECK = 0x800EE638
KB_ONDEATH_B1_ORIG = 0x4182002C  # beq +0x2C (skip the 800F1BAC install)
KB_ONDEATH_B1_NOP = 0x60000000
FTKIND_KIRBY = 0x04


def arm_kirby_copy_ondeath(d, log=_noop, retries=15):
    """NOP ftKb_Init_OnDeath's team-fighter gate so `unk4D != 4` alone installs
    a copy ability on every Kirby (re)spawn. MUST run in the early boot phase
    (with patch_one_player), before the JIT compiles the function at Kirby's
    first spawn. Verified opcode patch; returns True if armed."""
    last = None
    for _ in range(max(1, retries)):
        cur = d.u32(KB_ONDEATH_B1_CHECK)
        last = cur
        if cur == KB_ONDEATH_B1_NOP:
            return True
        if cur == KB_ONDEATH_B1_ORIG:
            d.write_u32(KB_ONDEATH_B1_CHECK, KB_ONDEATH_B1_NOP)
            if d.u32(KB_ONDEATH_B1_CHECK) == KB_ONDEATH_B1_NOP:
                log("kirby-copy armed (NOP'd ftKb_Init_OnDeath b1 gate "
                    "@0x800EE638)")
                return True
        time.sleep(0.2)
    log(f"kirby-copy arm FAILED: 0x800EE638 read 0x{(last or 0):08X} "
        f"(expected beq 0x4182002C)")
    return False

# Donor name -> INTERNAL FighterKind (decomp src/melee/ft/forward.h). These are
# the copy donors with an EfKb<XX>.dat ptcl bank (kirby.md §6).
KIRBY_COPY_FTKIND = {
    "mario": 0x00, "falcon": 0x02, "bowser": 0x05, "iceclimbers": 0x0A,
    "pikachu": 0x0C, "samus": 0x0D, "luigi": 0x11, "pichu": 0x17,
    "ganon": 0x19,
}
# Copied neutral-B START motion state per donor (base ftKb_MS_SpecialN=353);
# entering one of these instead of 353 proves the copy installed.
KIRBY_COPY_STATES = {
    "mario": 399, "samus": 407, "pikachu": 429, "luigi": 431, "falcon": 433,
    "bowser": 443, "iceclimbers": 453, "pichu": 526, "ganon": 528,
}


def set_kirby_copy(d, donor_ftkind, port=0):
    """Set the persisted copy kind (StaticPlayer unk4D) the armed
    ftKb_Init_OnDeath reads on rebirth. Requires arm_kirby_copy_ondeath() to
    have run in the early boot phase (JIT gotcha above). Call AFTER the match
    loads (match load clears a pre-spawn unk4D); the copy actually INSTALLS on
    the next rebirth -- use install_kirby_copy_via_rebirth() for the whole
    sequence. donor_ftkind=FTKIND_KIRBY (4) = 'no copy'."""
    sp = PLAYER_BLOCK + PLAYER_BLOCK_STRIDE * port
    d.write_u8(sp + SP_UNK4D, donor_ftkind & 0xFF)
    return d.u8(sp + SP_UNK4D) == (donor_ftkind & 0xFF)


def read_kirby_hat(d, port=0):
    """Kirby's live copied-fighter id (fp->fv.kb.hat.kind, a u32); None if the
    fighter chain is unresolvable (mid-death), 4 = FTKIND_KIRBY = no copy
    (0 also reads as no-copy on a fresh spawn that never ran OnDeath)."""
    gobj = d.u32(PLAYER_BLOCK + PLAYER_BLOCK_STRIDE * port + 0xB0)
    ft = d.u32(gobj + 0x2C) if gobj else 0
    return d.u32(ft + FT_HAT_KIND) if ft else None


def install_kirby_copy_via_rebirth(d, donor_ftkind, port=0, log=_noop,
                                   timeout=30.0):
    """Give an in-match Kirby the `donor_ftkind` copy ability: arm the install
    (set_kirby_copy), KO him (teleport below the bottom blastzone at high
    percent), and ride the death->Rebirth cycle so ftKb_Init_OnDeath runs
    ftKb_SpecialN_800F1BAC. Runs UNFROZEN in real time (restores the previous
    freeze state); leaves Kirby on/near the rebirth halo -- callers settle him
    with safe_reset()/settle_to_wait() and MUST re-resolve any cached fighter
    pointers (the respawn re-inits the fighter). Returns the post-rebirth
    hat.kind (== donor on success, else 0/None)."""
    from . import framestep
    from .gamestate import Player
    from .observe import is_in_game

    pl = Player(d, port)
    was_frozen = framestep.is_frozen(d)
    framestep.unfreeze(d)
    # The CSS->SSS warp skips the PlayerInitData->StaticPlayer copy (same class
    # of gap as fix_player_pad_indices), so StaticPlayer.stocks (+0x8E) is 0 --
    # a death then DESTROYS the fighter gobj with no rebirth (live-proven:
    # gobj stayed NULL forever). Seed stocks so the KO respawns.
    sp = PLAYER_BLOCK + PLAYER_BLOCK_STRIDE * port
    if (d.u8(sp + SP_STOCKS) or 0) < 2:
        d.write_u8(sp + SP_STOCKS, 5)
    if d.u32(KB_ONDEATH_B1_CHECK) != KB_ONDEATH_B1_NOP:
        log("kirby-copy: ftKb_Init_OnDeath gate NOT armed -- call "
            "arm_kirby_copy_ondeath() in the early boot phase (JIT gotcha); "
            "aborting")
        if was_frozen:
            framestep.freeze(d)
        return None
    set_kirby_copy(d, donor_ftkind, port)
    pl.resolve()
    pl.set_percent(999)
    pl.set_pos(0.0, -300.0)          # below FD's bottom blastzone (-140)
    saw_dead = False
    t0 = time.time()
    st = None
    while time.time() - t0 < timeout:
        d.write_u8(sp + SP_UNK4D, donor_ftkind & 0xFF)  # hold THROUGH the death
        if not is_in_game(d):
            log("kirby-copy: left in-game during the KO?! aborting")
            break
        pl.resolve()
        st = pl.state()
        if st is not None and (st <= 10 or st in (12, 13)):
            saw_dead = True
        if saw_dead and st in (13, 14):          # RebirthWait / Wait = respawned
            break
        if not saw_dead and st is not None:
            pl.set_pos(0.0, -300.0)              # keep shoving until it dies
        time.sleep(0.02)
    hat = None
    for _ in range(200):                          # let the gobj chain re-resolve
        hat = read_kirby_hat(d, port)
        if hat == (donor_ftkind & 0xFF):
            break
        time.sleep(0.03)
    # ride the rebirth in REAL TIME until the fighter reaches the halo/idle --
    # re-freezing mid-death (Sleep) has stalled the frame-step handshake.
    t1 = time.time()
    while time.time() - t1 < 10.0:
        pl.resolve()
        if pl.state() in (12, 13, 14):
            break
        time.sleep(0.03)
    fix_player_pad_indices(d, [port], log=_noop)  # respawn re-inits ft+0x618
    if was_frozen:
        framestep.freeze(d)
    log(f"kirby-copy: donor=0x{donor_ftkind:02X} saw_dead={saw_dead} "
        f"last_state={st} hat.kind={hat} "
        f"({'INSTALLED' if hat == (donor_ftkind & 0xFF) else 'NOT installed'})")
    return hat


def warp_to_stage_select(d):
    """Routing poke: break the CSS frame loop with the SSS minor pending, so the VS
    major re-inits onto the stage-select screen -- skipping the cursor lock and the
    START 'ready player' gate. Only valid once on the vanilla CSS (the Slippi menu
    doesn't run the vanilla scene engine)."""
    d.write_u8(PENDING_SCENE, 0x02)   # SSS minor (0x01) + 1
    d.write_u8(LOOP_BREAK, 1)
