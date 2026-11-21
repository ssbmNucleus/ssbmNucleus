"""
framestep.py -- TAS-style debug-freeze + single-frame stepping via RAM pokes.

Melee's scene main loop (gm_801A4D34, decomp gm/gm_1A45.c) gates every game
logic frame on a debug-pause bitmask that ships in RETAIL builds: the develop
mode buttons (X+D-pad-up pause, Z step at DbLevel>=3) merely set bits in it, but
the *check* runs at any DbLevel -- so we skip the buttons and set the bits
directly with WriteProcessMemory:

  struct gm_80479D58_t {              // 0x80479D58
      u32 pad_frames;                 // +0x00
      u32 rendered_frames;            // +0x04
      u32 game_frames;                // +0x08  <- observe.FRAME_COUNTER 0x80479D60
      int loop_break;                 // +0x0C  <- match_setup.LOOP_BREAK 0x80479D64
      struct {
          u8 pause_bits;              // +0x10  bit0 = debug freeze  -> 0x80479D68
          u8 pause_bits_prev;         // +0x11
          u8 step_bits;               // +0x12  bit0 = run ONE frame -> 0x80479D6A
          u8 step_bits_prev;          // +0x13
          ...
      } unk_10;
  };

While frozen: game logic (fighters, physics, camera) is fully stopped, but the
render loop keeps presenting the frozen scene every vsync -- so PrintWindow
screenshots keep working and there is NO pause HUD or camera zoom (unlike the
START pause, which uses other bits of the same mask). Writing step_bits |= 1
makes the engine run exactly one logic frame and re-freeze; the frame counter
at +0x08 advances by exactly 1, which is how we confirm each step landed.

Input during freeze: the engine renews its per-frame pad snapshot
(HSD_PadCopyStatus) only on frames that RUN, so pipe inputs held while frozen
register as *fresh presses* on the next stepped frame -- exact-frame inputs.
"""

import time

from .observe import FRAME_COUNTER

PAUSE_BITS = 0x80479D68   # gm_80479D58.unk_10.x0
STEP_BITS = 0x80479D6A    # gm_80479D58.unk_10.x2
DEBUG_PAUSE_BIT = 0x01    # bit 0 = the develop-mode debug pause

# gm_80479D58 +0x04: the RENDERED-frame counter. Unlike game_frames (+0x08) it
# KEEPS COUNTING while the debug freeze is set -- measured 2026-07-30: 60/s with
# game_frames pinned. That makes it the freshness oracle the capture path was
# missing: after poking the camera or the plain-background words, wait for this
# to tick instead of sleeping a fixed 0.15 s and HOPING the renderer got there.
# The sleep was not paranoia -- with no wait at all, 18.8 % of captures at a new
# yaw came back byte-identical to the previous angle (i.e. stale).
RENDERED_FRAMES = 0x80479D5C


STEP_SHADOW = 0x80479D6B  # gm_80479D58.unk_10.x3 (engine's step-request shadow)


def snapshot(d):
    """Read-only failure evidence; unavailable RAM must not hide the failure."""
    result={}
    for name,address,reader in [('game_frames',FRAME_COUNTER,d.u32),
                                ('render_frames',RENDERED_FRAMES,d.u32),
                                ('pause',PAUSE_BITS,d.u8),('request',STEP_BITS,d.u8),
                                ('shadow',STEP_SHADOW,d.u8)]:
        try:result[name]=reader(address)
        except Exception as exc:result[name]=type(exc).__name__
    return result


def _settle(d, timeout=0.25):
    """Wait until the engine has re-armed the step handshake (x2/x3 clear).

    The engine clears the step-request byte only when x2 != x3 -- if a second
    request is written while the shadow (x3) is still set from the previous
    step, both wedge at 1 and 'step requested' reads true EVERY frame: the game
    free-runs with the freeze bit still set. So we always clear our request bit
    once the step is confirmed and wait for the shadow to drop before another
    request. (This wedge is real -- see framestep_probe.py.)"""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        x2 = d.u8(STEP_BITS)
        x3 = d.u8(STEP_SHADOW)
        if x2 is None or x3 is None:
            return False
        if x2 & DEBUG_PAUSE_BIT:
            d.write_u8(STEP_BITS, x2 & ~DEBUG_PAUSE_BIT)
        elif not (x3 & DEBUG_PAUSE_BIT):
            return True
        time.sleep(0.002)
    return False


def freeze(d):
    """Halt game logic (rendering continues). Idempotent."""
    cur = d.u8(PAUSE_BITS)
    if cur is None:
        return False
    if not (cur & DEBUG_PAUSE_BIT):
        d.write_u8(PAUSE_BITS, cur | DEBUG_PAUSE_BIT)
    return _settle(d)


def unfreeze(d):
    """Resume normal 60fps game logic. Idempotent."""
    cur = d.u8(PAUSE_BITS)
    if cur is None:
        return False
    if cur & DEBUG_PAUSE_BIT:
        d.write_u8(PAUSE_BITS, cur & ~DEBUG_PAUSE_BIT)
    return True


def is_frozen(d):
    cur = d.u8(PAUSE_BITS)
    return bool(cur & DEBUG_PAUSE_BIT) if cur is not None else False


def wait_render_frames(d, n=2, timeout=0.5, poll=0.002):
    """Block until the RENDERED-frame counter has advanced by `n` (default 2:
    one frame to consume the RAM poke we just made, one to be sure it was fully
    composited). Returns the number of rendered frames observed -- 0 means the
    counter is unreadable or stuck, and the caller should fall back to a sleep
    rather than assume the screen is current.

    This is a *verification*, not a delay: it returns as soon as the renderer
    has actually produced new frames (~1 frame at 60 Hz, faster if emulation is
    uncapped), where the fixed sleep it replaces always cost its full 0.15 s and
    still only assumed freshness."""
    f0 = d.u32(RENDERED_FRAMES)
    if f0 is None:
        return 0
    t0 = time.time()
    while time.time() - t0 < timeout:
        f = d.u32(RENDERED_FRAMES)
        if f is None:
            return 0
        if f < f0:            # counter reset under us (scene flip) -- re-anchor
            f0 = f
        elif f - f0 >= n:
            return f - f0
        time.sleep(poll)
    return 0


def step(d, n=1, timeout_per=1.0):
    """Advance exactly `n` game-logic frames while frozen. Returns the number of
    frames actually stepped (== n on success). Each step is confirmed against
    the global game-frame counter and the handshake is re-armed before the next
    request (see _settle), so a return of n means exactly n frames ran."""
    done = 0
    for _ in range(max(0, int(n))):
        # The public per-frame budget covers both re-arming the previous
        # handshake and observing this request. A separate 250 ms gate could
        # reject a healthy scheduler pause before the advertised budget.
        deadline = time.monotonic() + timeout_per
        if not _settle(d, timeout=max(0., deadline-time.monotonic())):
            break
        f0 = d.u32(FRAME_COUNTER)
        if f0 is None:
            break
        cur = d.u8(STEP_BITS)
        if cur is None:
            break
        d.write_u8(STEP_BITS, cur | DEBUG_PAUSE_BIT)
        while time.monotonic() < deadline:
            f = d.u32(FRAME_COUNTER)
            if f is not None and f != f0:
                break
            time.sleep(0.001)
        else:
            break
        # our step ran; clear the request NOW so it can't wedge against x3
        cur = d.u8(STEP_BITS)
        if cur is not None and cur & DEBUG_PAUSE_BIT:
            d.write_u8(STEP_BITS, cur & ~DEBUG_PAUSE_BIT)
        # count REAL frames advanced (a late clear can let one extra frame run;
        # callers must know the true count, not the request count)
        f_end = d.u32(FRAME_COUNTER)
        done += (f_end - f0) if f_end is not None else 1
        if done >= n:
            break
    return done
