"""
nav.py -- drive Slippi's menus from the post-boot screen to the OFFLINE VS
character-select screen, by SCENE-STATE FEEDBACK (not blind timing), and add a
2nd player so a match can start.

This is the one hop that was NOT closed-loop in the harness (CSS/SSS already are),
and the place a timing-based recipe could wander onto the online screen on a
modded build. So this version reads the scene every step and:
  * succeeds only when it confirms the OFFLINE VS CSS (major 0x02, minor 0x00);
  * HARD-ABORTS if it ever detects the online CSS (major 0x08) -- holding B to
    back out -- so the test can never enter matchmaking / waste a real player's
    time. (This preserves the project rule: never drive the user's account
    online.)

Scene map (Melee 1.02, verified by the harness):
  major 0x80479D30 : 0x01 = Slippi main/Online-Play menu, 0x02 = offline VS,
                     0x08 = ONLINE CSS / matchmaking (forbidden)
  minor 0x80479D33 : within VS, 0x00 = char select, 0x01 = stage select,
                     0x02 = in-game
The modded ISO boots to the Slippi "Online Play" menu (Unranked highlighted);
the proven button recipe to reach the offline CSS is: B,B (out to the main menu)
-> D_DOWN (to VS Mode) -> A (VS submenu) -> A (-> offline CSS).

Not every build boots there. The ACE Build has no Online Play entry and boots
to the top-level main menu, where the first B drops back to the title screen.
So the menu is driven from its own state instead: `MenuFlow` (0x804A04F0,
mn/mnmain.h) holds the current menu kind and the hovered row, and each step
presses the one button that moves toward VS Mode -> Melee, backing out of any
other submenu with B. On a Slippi build that produces exactly the old recipe
(Online submenu 8 -> B -> 1P menu 1 -> B -> main 0 -> D_DOWN -> A -> A). If the
menu state can't be read the old recipe runs unchanged.
"""

import time

from .observe import FRAME_COUNTER, wait_game_frames

SCENE_MAJOR = 0x80479D30
SCENE_MINOR = 0x80479D33
ONLINE_CSS = 0x08
VS_MAJOR = 0x02
CSS_MINOR = 0x00
MENU_MAJOR = 0x01      # Slippi main / Online-Play menu (the boot screen)
BOOT_MAJOR = 0x00      # still booting / loading (no menu yet)
PACE = 0.18

# MenuFlow (mn/mnmain.h): cur_menu u8 @+0, hovered_selection u16 @+2.
MENU_FLOW = 0x804A04F0
MENU_KIND_MAIN = 0
MENU_KIND_VS = 2
MENU_KIND_LAST = 0x22      # highest MenuKind; anything above is not a menu state
MAIN_VS_ROW = 1            # "VS. Mode" on the main menu (vanilla, Slippi and ACE)
VS_MELEE_ROW = 0           # "Melee" in the VS submenu


class OnlineAbort(Exception):
    """Raised if the menu nav ever lands on the online CSS -- we back out and
    refuse to proceed, so we never matchmake against a real player."""


def at_offline_css(d):
    return d.u8(SCENE_MAJOR) == VS_MAJOR and d.u8(SCENE_MINOR) == CSS_MINOR


def is_online(d):
    return d.u8(SCENE_MAJOR) == ONLINE_CSS


def _hold_b_exit(p):
    """HOLD B to leave a CSS (a tap doesn't exit). Best-effort safety bail."""
    try:
        p.press("B")
        time.sleep(1.3)
        p.release("B")
        time.sleep(0.6)
    except Exception:
        pass


def _guard_online(d, p):
    if is_online(d):
        _hold_b_exit(p)
        raise OnlineAbort(
            "menu nav reached the online CSS (scene 0x08); aborted and backed "
            "out to avoid matchmaking. Close any open Slippi and retry."
        )


def wait_menu_ready(d, timeout=30.0, settle_frames=200, log=lambda m: None,
                    prompt_pipe=None, prompt_grace=5.0, prompt_pace=1.0,
                    check_startup=None):
    """Wait for the Slippi boot menu to LOAD and become input-ready before we
    press anything. Two host-independent waits, both essential:

      1) until we're OFF the boot/loading screen and on the menu scene (major
         0x01). Right after boot the scene is major 0x00 (still loading) -- RAM
         maps and we can attach seconds before the menu actually appears.
         Pressing then drops the early B,B inputs, which shifts the whole
         B,B -> D_DOWN -> A -> A recipe so a later A lands on the ONLINE CSS.
      2) a fixed number of GAME frames for the menu's fade-in: even after the
         scene flag flips, the menu eats inputs for ~3s while it animates in
         (confirmed: a 0.5s settle drops inputs and wanders online; ~3s lands on
         the offline CSS cleanly). Counted in game frames so it's the same on a
         fast or slow machine.

    When prompt_pipe is supplied, a pre-menu scene that persists past
    prompt_grace is treated as an unexpected acknowledgement prompt (for
    example Melee's save-data prompt). We tap A while RAM still reports that
    scene and keep polling instead of assuming a fixed number of prompt pages.

    Returns True once ready (or already past the menu at a CSS); False if the
    menu never appeared."""
    start = time.time()
    last_prompt_press = None
    press_start_next = True
    while time.time() - start < timeout:
        if check_startup:
            check_startup()
        maj = d.u8(SCENE_MAJOR)
        if maj in (VS_MAJOR, ONLINE_CSS):   # already at a CSS -- the caller handles it
            return True
        if maj == MENU_MAJOR:
            break
        elapsed = time.time() - start
        if (prompt_pipe is not None and maj == BOOT_MAJOR
                and elapsed >= prompt_grace
                and (last_prompt_press is None
                     or time.time() - last_prompt_press >= prompt_pace)):
            log("pre-menu scene still active; acknowledging unexpected prompt")
            prompt_pipe.tap("A", 0.06)
            last_prompt_press = time.time()
        elif (prompt_pipe is not None and maj is not None
                and maj not in (BOOT_MAJOR, MENU_MAJOR)
                and elapsed >= prompt_grace
                and (last_prompt_press is None
                     or time.time() - last_prompt_press >= prompt_pace)):
            # Modded builds (Diet Melee family and other entry-hacked packs)
            # boot into their OWN title/press-start scene, whose major is none
            # of the vanilla Slippi ones. Alternate START and A to advance it
            # -- harmless on scenes that ignore them, and the CSS check above
            # exits the moment one lands.
            btn = "START" if press_start_next else "A"
            press_start_next = not press_start_next
            log(f"unknown pre-menu scene major={maj:#x}; tapping {btn} to advance")
            prompt_pipe.tap(btn, 0.06)
            last_prompt_press = time.time()
        time.sleep(0.1)
    else:
        log("boot menu (scene 0x01) never appeared within timeout")
        return False
    log(f"menu loaded after {time.time() - start:.1f}s; "
        f"waiting {settle_frames} game frames for it to be input-ready")
    wait_game_frames(d, settle_frames, log=log)
    return True


def menu_flow(d):
    """(current menu kind, hovered row) from MenuFlow, or None when it can't be
    read or doesn't hold a menu state (then the caller falls back to the
    button recipe)."""
    try:
        cur = d.u8(MENU_FLOW)
        hov = d.u8(MENU_FLOW + 3)          # low byte of the big-endian u16
    except Exception:
        return None
    if cur is None or hov is None or cur > MENU_KIND_LAST:
        return None
    return cur, hov


def next_menu_button(cur, hov):
    """The one button that moves the main menu toward VS Mode -> Melee."""
    if cur == MENU_KIND_MAIN:
        target = MAIN_VS_ROW
    elif cur == MENU_KIND_VS:
        target = VS_MELEE_ROW
    else:
        return "B"                          # any other submenu: back out one level
    if hov < target:
        return "D_DOWN"
    if hov > target:
        return "D_UP"
    return "A"


def _drive_menu(d, p, start, timeout, log, check_startup=None, max_steps=16):
    """Walk the menu to the offline CSS by reading MenuFlow before every press.
    Returns True at the CSS, False on timeout, None if the menu state is
    unreadable (use the button recipe instead)."""
    for _ in range(max_steps):
        if check_startup:
            check_startup()
        if at_offline_css(d):
            return True
        _guard_online(d, p)
        if time.time() - start > timeout:
            return False
        if d.u8(SCENE_MAJOR) != MENU_MAJOR:
            # between scenes (entering the CSS) -- give it a moment
            time.sleep(0.2)
            continue
        state = menu_flow(d)
        if state is None:
            return None
        btn = next_menu_button(*state)
        log(f"menu kind={state[0]} row={state[1]} -> {btn}")
        p.tap(btn, 0.06)
        time.sleep(1.5 if btn == "A" else PACE)
    # poll for the CSS after the last press
    sub = time.time()
    while time.time() - sub < 6.0 and time.time() - start <= timeout:
        if at_offline_css(d):
            return True
        _guard_online(d, p)
        time.sleep(0.2)
    return at_offline_css(d)


def nav_to_css(d, p, timeout=35.0, attempts=3, log=lambda m: None,
               check_startup=None):
    """Drive from the post-boot menu to the OFFLINE VS CSS. Returns True once
    confirmed at the offline CSS; raises OnlineAbort if it ever hits the online
    scene; returns False on timeout. Uses only the persistent pipe `p`."""
    start = time.time()
    p.neutral()
    # CRITICAL: do not press until the menu has loaded AND faded in -- pressing
    # into the boot screen drops inputs and the recipe wanders online.
    if not wait_menu_ready(d, timeout=min(30.0, timeout), log=log,
                           prompt_pipe=p, check_startup=check_startup):
        return at_offline_css(d)

    for attempt in range(1, attempts + 1):
        if check_startup:
            check_startup()
        if at_offline_css(d):
            return True
        _guard_online(d, p)
        if time.time() - start > timeout:
            break
        driven = _drive_menu(d, p, start, timeout, log, check_startup)
        if driven:
            log("reached offline VS character-select")
            return True
        if driven is False:
            continue
        log(f"menu nav attempt {attempt}: B,B -> D_DOWN -> A -> A")

        p.tap("B", 0.06); time.sleep(PACE)   # out of Online Play...
        p.tap("B", 0.06); time.sleep(PACE)   # ...back to the main menu
        _guard_online(d, p)                  # a dropped B must not leave us online
        p.tap("D_DOWN", 0.06); time.sleep(PACE)  # down to VS Mode
        p.tap("A", 0.06); time.sleep(1.5)        # -> VS submenu (Melee)
        _guard_online(d, p)
        p.tap("A", 0.06)                         # -> offline character select

        # Poll for the offline CSS (watching for an accidental online entry).
        sub = time.time()
        while time.time() - sub < 6.0:
            if check_startup:
                check_startup()
            if at_offline_css(d):
                log("reached offline VS character-select")
                return True
            _guard_online(d, p)
            if time.time() - start > timeout:
                return at_offline_css(d)
            time.sleep(0.2)

    return at_offline_css(d)


def wait_css_ready(d, cur, timeout=10.0, settle=1.5, log=lambda m: None):
    """The offline-CSS scene flag (major 0x02 / minor 0x00) flips a BEAT BEFORE
    the screen is actually interactive -- the hand cursor and the port panels
    aren't live yet. Driving inputs in that window (notably the add-CPU press)
    silently does nothing. Wait until the port-1 cursor reads a valid position
    (proves the CSS is live), then settle a little more so inputs land."""
    start = time.time()
    while time.time() - start < timeout:
        x, y = cur.read_pos(tries=3)
        if x is not None:
            log(f"CSS interactive; cursor at ({x:+.1f},{y:+.1f})")
            time.sleep(settle)
            return True
        time.sleep(0.1)
    log("CSS cursor never came alive within timeout")
    time.sleep(settle)
    return False


# --- CSS port / player-slot RAM (decoded from the Slippi "Extract Menu Info"
#     gecko, GALE01r2.ini: the same per-port struct the hovered-char byte lives
#     in). This gives ground-truth feedback for adding a 2nd player, so the
#     CPU/"open the port door" step is closed-loop + verified in RAM, exactly
#     like character selection -- not a guessed timing/coordinate.
#
#   controller status : byte at 0x803F0E08 + 0x24*port  (0=HUMAN, 1=CPU, 3=EMPTY)
#   hand-cursor entity: ptr  at 0x804A0BC0 + 0x04*port ; coin-down = *(ptr)+5 == 2
CSS_PORT_STATUS = 0x803F0E08
CSS_CURSOR_PTR = 0x804A0BC0
STATUS_HUMAN, STATUS_CPU, STATUS_EMPTY = 0, 1, 3


def port_status(d, port):
    """Controller slot type for `port` (0-indexed: 0=P1...3=P4)."""
    return d.u8(CSS_PORT_STATUS + 0x24 * port)


def port_present(d, port):
    """True if `port` holds a player (HUMAN or CPU) at the CSS."""
    return port_status(d, port) in (STATUS_HUMAN, STATUS_CPU)


def any_extra_player(d):
    """True if any of ports 2-4 holds a player -- a match needs one besides us."""
    return any(port_present(d, i) for i in (1, 2, 3))


def port_coin_down(d, port):
    """True if `port`'s coin is down (character locked in)."""
    base = d.deref(CSS_CURSOR_PTR + 0x04 * port)
    if base is None:
        return False
    return d.u8(base + 5) == 2


def add_cpu(d, p, cur=None, log=lambda m: None):
    """Open a port door (add a 2nd player) -- closed-loop and RAM-VERIFIED. The
    player panels sit along port-1's spawn row, to the right; we sweep the hand
    cursor rightward and press A, checking the per-port controller status after
    each press, and STOP the instant any of ports 2-4 becomes a player. If a
    stray A locks our own character, we read the coin-down byte and unlock (B).
    Any extra player works -- the match only needs one besides us. Returns True
    once a 2nd player is present."""
    if any_extra_player(d):
        log("a 2nd player is already present")
        return True
    if cur is None:
        # No cursor feedback -- fall back to the old open-loop nudge once.
        p.main(1.0, 0.5); time.sleep(0.15); p.center(); time.sleep(PACE)
        p.tap("A", 0.06); time.sleep(PACE)
        return any_extra_player(d)

    # Wait for the cursor to be live, then anchor to the spawn (= port-1 panel).
    for _ in range(40):
        x, _y = cur.read_pos(tries=2)
        if x is not None:
            break
        time.sleep(0.1)
    x0, y0 = cur.read_pos()
    if x0 is None:
        x0, y0 = -22.0, -9.0
    log(f"add_cpu: spawn cursor ({x0:+.1f},{y0:+.1f}); sweeping right for a port door")

    for dy in (0.0, -3.0, 3.0, -6.0):
        for dx in (8.0, 12.0, 16.0, 20.0, 24.0, 28.0, 32.0):
            if any_extra_player(d):
                break
            cur.move_to(x0 + dx, y0 + dy, tol=1.5, timeout=2.0)
            p.tap("A", 0.06)
            time.sleep(0.18)
            if any_extra_player(d):
                port = next(i for i in (1, 2, 3) if port_present(d, i))
                log(f"added a 2nd player on port {port + 1} at offset "
                    f"(dx={dx:+.0f},dy={dy:+.0f}); status={port_status(d, port)}")
                return True
            if port_coin_down(d, 0):  # an A strayed onto a character -> unlock
                p.tap("B", 0.05)
                time.sleep(0.2)
        if any_extra_player(d):
            break
    return any_extra_player(d)


def wait_css_running(d, p, timeout=8.0):
    """True once the offline CSS is RUNNING, which is later than the scene bytes
    naming it. They flip when the scene before it ends (a match that was quit,
    the stage-select screen backed out of), and the CSS then loads for about a
    quarter second with the scene's frame counter standing at the old scene's
    last value. The CSS's own loop starts that counter again from zero and
    clears the loop-break flag as it does, so a stage-select warp
    (match_setup.warp_to_stage_select) written in the loading window is wiped:
    the game sits on the CSS and the caller's 8 s wait for the SSS runs out.
    That lost every variant after the first in a bulk stage capture (found
    2026-11-10). So the CSS counts as back once its counter is seen moving. At
    the timeout the answer is the bytes' alone, as it always was."""
    start = time.time()
    counter, moves = None, 0     # the frame counter as last read on the CSS, and how often it had moved
    while time.time() - start < timeout:
        if at_offline_css(d):
            now = d.u32(FRAME_COUNTER)
            if now is not None:
                if counter is not None and now != counter:
                    moves += 1   # the first move is the restart itself; the second is the loop running
                counter = now
            if moves >= 2:
                return True
        else:
            counter, moves = None, 0
        _guard_online(d, p)
        time.sleep(0.05)
    return at_offline_css(d)


def reset_to_css(d, p, timeout=8.0, log=lambda m: None):
    """Quit a running match back to the CSS so the next check can run: pause with
    START, then press L+R+A+START together (Melee's quit-to-CSS), which lands on
    a still-ready CSS (the prior fighter stays locked, the CPU stays). Returns
    True once that CSS is running (wait_css_running). Only for a RUNNING MATCH:
    pressed on a menu, the same buttons back out of it."""
    p.tap("START", 0.08)
    time.sleep(0.7)
    p.frame(["PRESS L", "PRESS R", "PRESS A", "PRESS START", "FLUSH"])
    time.sleep(0.8)
    p.frame(["RELEASE L", "RELEASE R", "RELEASE A", "RELEASE START", "FLUSH"])
    # No fixed post-release sleep: the CSS takes a variable time to come up and
    # the poll is the actual answer. The old `time.sleep(1.2)` here was dead
    # wall-clock on EVERY between-target recovery (measured 2026-07-30:
    # recover_to_css cost 7.5 s of a 22.5 s target, nearly all of it fixed
    # sleeps). Polling at 50 ms finds the same CSS, sooner.
    return wait_css_running(d, p, timeout)
