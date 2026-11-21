"""
melee_css.py -- character-select state + closed-loop cursor control, read from
live RAM (melee_mem) and driven over the pipe (melee_pipe). No timing guesswork:
we read the cursor's actual position every step and steer toward the target, so
positioning is deterministic regardless of cursor acceleration or grid layout.

Ported from tools/ingame/nucleus/melee_css.py (class identical; dev __main__ demo
dropped). Addresses (Melee 1.02, found empirically by the harness's discover.py):
  port-1 cursor X  0x804A85FC  (float, ~ -30 left .. +30 right)
  port-1 cursor Y  0x804A860C  (float, ~ -27 up .. +25 down; +Y is downward)
  port-1 costume   0x80480823  (byte, increments on X)
"""

import time

P1_CURSOR_X = 0x804A85FC
P1_CURSOR_Y = 0x804A860C
P1_COSTUME = 0x80480823
P1_LOCKED = 0x804AA162  # 0 = hovering, 1 = locked in (coin down)
# Hovered character as a CSS GRID INDEX (Dr.Mario=0, Mario=1 ... Fox=10 ...
# Roy=24). The value libmelee's "Extract Menu Info" gecko code reads -- it lets
# us CONFIRM which character the cursor is actually over (vs trusting coords).
P1_HOVERED = 0x803F0E0A


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


class Cursor:
    def __init__(self, dolphin, pipe):
        self.d = dolphin
        self.p = pipe

    def pos(self):
        """Validated cursor read; returns (None, None) on an out-of-range or
        NaN value (the address occasionally returns a transient garbage read)."""
        x = self.d.f32(P1_CURSOR_X)
        y = self.d.f32(P1_CURSOR_Y)
        if x is None or y is None or x != x or y != y or abs(x) > 45 or abs(y) > 40:
            return (None, None)
        return (x, y)

    def read_pos(self, tries=5):
        for _ in range(tries):
            x, y = self.pos()
            if x is not None:
                return (x, y)
            time.sleep(0.01)
        return (None, None)

    def costume(self):
        return self.d.u8(P1_COSTUME)

    def hovered(self):
        """The CSS grid index of the character the cursor is currently over
        (Dr.Mario=0 ... Fox=10 ... Roy=24). Ground truth, grid-layout-independent
        -- use it to confirm a selection or to scan for a custom character."""
        return self.d.u8(P1_HOVERED)

    def locked(self):
        return self.d.u8(P1_LOCKED) == 1

    def unlock(self):
        """If a character is locked in, press B to release it (so we can pick
        a different one). Safe no-op when already free."""
        if self.locked():
            self.p.tap("B", 0.05)
            time.sleep(0.25)
            return True
        return False

    def set_costume(self, target, max_presses=16):
        """Cycle the costume with X, reading the costume index each time, until
        it equals target. No press-counting -- closed-loop on the real value."""
        for _ in range(max_presses):
            cur = self.costume()
            if cur == target:
                return True
            self.p.tap("X", 0.05)
            time.sleep(0.22)
        return self.costume() == target

    def select(self, tx, ty, costume=0, lock=True, css_index=None):
        """Closed-loop character selection: release any prior lock, steer to the
        cell, set the costume by reading it, then lock with A. If css_index is
        given, CONFIRM the cursor is on the right character via the hovered-index
        read (move_to can stop on a neighbour cell) and retry a few times."""
        self.unlock()
        self.move_to(tx, ty)
        if css_index is not None:
            for _ in range(4):
                time.sleep(0.15)
                if self.hovered() == css_index:
                    break
                self.move_to(tx, ty, tol=0.6)
        time.sleep(0.1)
        got_costume = self.set_costume(costume)
        on_target = (self.hovered() == css_index) if css_index is not None else True
        if lock:
            for _ in range(3):
                self.p.tap("A", 0.05)
                time.sleep(0.2)
                if self.locked():
                    break
        return on_target and got_costume and (self.locked() if lock else True)

    def move_to(self, tx, ty, tol=1.0, timeout=8.0, kp=0.05, kd=0.18, verbose=False):
        """Closed-loop PD control: steer the cursor to (tx,ty) with stick
        deflection = kp*error - kd*velocity. The velocity (damping) term stops
        the cursor overshooting/oscillating, so it converges tight enough
        (tol ~1 unit) to land on the lockable centre of the cell. x=1.0 right,
        y=1.0 down."""
        start = time.time()
        prev = None
        while time.time() - start < timeout:
            x, y = self.read_pos()
            if x is None:
                # Transient garbage read: HOLD the last stick input and re-poll.
                # Snapping to neutral (center) mid-glide is what makes the cursor
                # jitter -- and a stale read doesn't mean the cursor moved.
                time.sleep(0.02)
                continue
            ex, ey = tx - x, ty - y
            if abs(ex) < tol and abs(ey) < tol:
                self.p.center()
                return True
            vx = (x - prev[0]) if prev else 0.0
            vy = (y - prev[1]) if prev else 0.0
            sx = 0.5 + clamp(kp * ex - kd * vx, -0.5, 0.5)
            sy = 0.5 + clamp(kp * ey - kd * vy, -0.5, 0.5)
            self.p.main(sx, sy)
            prev = (x, y)
            time.sleep(0.03)
        self.p.center()
        return False
