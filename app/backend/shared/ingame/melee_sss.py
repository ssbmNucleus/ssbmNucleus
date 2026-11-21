"""
melee_sss.py -- stage-select screen state + closed-loop stage selection, read
from live RAM (melee_mem) and driven over the pipe (melee_pipe). The CSS analog
of melee_css.py, for the stage that a match is played on.

Ported from tools/ingame/nucleus/melee_sss.py (class identical; dev __main__ demo
dropped).

  hovered stage     icon-table INDEX at 0x804D6CAE -- the order stages appear in
                    mexcli get-sss-layout (Yoshi's=6, Fountain=8, Stadium=18,
                    Battlefield=24, FD=25, DreamLand=26). Per the doldecomp/melee
                    source this is the hovered ICON INDEX, not Melee's internal
                    stage id. (0x804D6CAD -- which an earlier version read with a
                    "+1 m-ex fallback" -- is actually the cursor's Y stick input,
                    0 at rest, so it only ever worked by falling through to +1.)
  stage cursor X/Y   a POINTER CHAIN, only valid on the stage-select scene:
                       P0 = *(0x804D7820); P1 = *(P0+0x10); P2 = *(P1+0x28)
                       x = float at P2+0x38; y = float at P2+0x3C
"""

import time

SSS_CURSOR_PTR = 0x804D7820
# Hovered stage = icon-table index, read at 0x804D6CAE (see module docstring).
SSS_HOVERED_STAGE = 0x804D6CAE

# SSSData global pointer; force_stage_id is a signed byte at +0x03. Writing a
# non-negative INTERNAL stage id there makes the SSS frame handler copy it into
# the match rules and start the match next frame, with NO cursor navigation --
# layout- and page-independent (custom stages on later pages work the same).
# From doldecomp/melee (mn/mnstagesel: SSSData.force_stage_id -> rules.xE,
# gm_801A4B60).
SSSDATA_PTR = 0x804D6C90
FORCE_STAGE_OFFSET = 0x03

SCENE_MAJOR = 0x80479D30
SCENE_MINOR = 0x80479D33
VS_MAJOR = 0x02
SSS_MINOR = 0x01

# Hovered ICON-TABLE INDEX per stage (the value at 0x804D6CAE == the get-sss-
# layout order), used to CONFIRM the cursor is over the intended stage. These are
# layout indices, NOT Melee internal stage ids -- a direct force-stage write
# (SSSData.force_stage_id) would instead need get-sss-layout's 'stageID'.
STAGE_ID = {
    "battlefield": 0x18,
    "finaldestination": 0x19,
    "dreamland": 0x1A,
    "pokemonstadium": 0x12,
    "yoshisstory": 0x06,
    "fountainofdreams": 0x08,
}

# Melee INTERNAL stage ids (== get-sss-layout 'stageID') -- what force_stage_id /
# rules.xE want, DISTINCT from the icon indices in STAGE_ID above (e.g. Battlefield
# is icon index 0x18 but internal id 0x1F). Custom stages get their own id (>0x20)
# which the build reads from get-sss-layout and passes through.
INTERNAL_STAGE_ID = {
    "battlefield": 0x1F,
    "finaldestination": 0x20,
    "dreamland": 0x1C,          # Dream Land N64 (the legal one; GrOp)
    "pokemonstadium": 0x03,
    "yoshisstory": 0x08,
    "fountainofdreams": 0x02,
}

# Real VANILLA stage-select coordinates in cursor space, taken straight from the
# build's own SSS layout (mexcli get-sss-layout). The in-app "Test in game" ISO
# is always built fresh from vanilla Melee, so its stage-select screen is the
# full vanilla roster and these are exact -- a single targeted move lands on the
# tile, no screen scan needed. The previous values were libmelee's TOURNAMENT
# layout, which on the vanilla SSS point at the WRONG tiles: (15,3.5)=Onett (not
# Stadium), (10,15.5)=Yoshi's Story (not Fountain), (3.5,15.5)=Brinstar (not
# Yoshi's). Battlefield/FD/Dream Land/Random happened to line up, which is why
# only some stages were wrong.
STAGE_TARGET = {
    "battlefield": (1.3, -9.1),
    "finaldestination": (6.6, -9.1),
    "dreamland": (12.3, -9.1),         # Dream Land N64 -- the legal one (GrOp)
    "pokemonstadium": (2.0, 3.7),
    "yoshisstory": (9.9, 15.7),
    "fountainofdreams": (16.5, 15.7),
    "random": (-14.1, 3.6),
}

ALIASES = {
    "bf": "battlefield",
    "fd": "finaldestination", "dreamland64": "dreamland", "dl": "dreamland",
    "ps": "pokemonstadium", "stadium": "pokemonstadium", "ps2": "pokemonstadium",
    "ys": "yoshisstory", "yoshis": "yoshisstory", "yoshistory": "yoshisstory",
    "fod": "fountainofdreams", "fountain": "fountainofdreams",
    "rng": "random", "randomstage": "random",
}


def norm(name):
    key = "".join(ch for ch in str(name).lower() if ch.isalnum())
    return ALIASES.get(key, key)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


class StageCursor:
    """Stage-select state + closed-loop cursor control (bang-bang tilt, matching
    libmelee's choose_stage; the cursor has a large input deadzone so small PD
    deflections stall -- full-deflection one-axis-at-a-time converges)."""

    def __init__(self, dolphin, pipe):
        self.d = dolphin
        self.p = pipe

    def _p2(self):
        a = self.d.deref(SSS_CURSOR_PTR, 0x10)   # P0 + 0x10
        if a is None:
            return None
        b = self.d.deref(a, 0x28)                # P1 + 0x28
        if b is None:
            return None
        p2 = self.d.u32(b)                       # P2
        if p2 is None or not (0x80000000 <= p2 < 0x81800000):
            return None
        return p2

    def pos(self):
        p2 = self._p2()
        if p2 is None:
            return (None, None)
        x = self.d.f32(p2 + 0x38)
        y = self.d.f32(p2 + 0x3C)
        if x is None or y is None or x != x or y != y or abs(x) > 40 or abs(y) > 40:
            return (None, None)
        return (x, y)

    def read_pos(self, tries=6):
        for _ in range(tries):
            x, y = self.pos()
            if x is not None:
                return (x, y)
            time.sleep(0.01)
        return (None, None)

    def on_stage_select(self):
        return (self.d.u8(SCENE_MAJOR) == VS_MAJOR
                and self.d.u8(SCENE_MINOR) == SSS_MINOR)

    def wait_for_stage_select(self, timeout=8.0):
        start = time.time()
        while time.time() - start < timeout:
            if self.on_stage_select():
                return True
            time.sleep(0.05)
        return False

    def ensure_stage_select(self):
        """Make sure we're on the stage-select scene, advancing from a locked
        CSS with START if needed (over THIS persistent pipe, verifying the scene
        actually changed)."""
        if self.on_stage_select():
            return True
        for _ in range(4):
            self.p.tap("START", 0.06)
            if self.wait_for_stage_select(timeout=2.5):
                return True
        return self.on_stage_select()

    def hovered_stage(self):
        """The icon-table index of the stage the cursor is over (the get-sss-
        layout order), read straight from 0x804D6CAE -- ground truth, used to
        confirm a selection. Compare to STAGE_ID. Returns 0 (no stage) when the
        cursor is between tiles."""
        return self.d.u8(SSS_HOVERED_STAGE)

    def hovered_name(self):
        v = self.hovered_stage()
        for name, sid in STAGE_ID.items():
            if sid == v:
                return name
        return None

    def move_to(self, tx, ty, wiggle=1.5, timeout=8.0, verbose=False):
        """Full-deflection bang-bang to (tx,ty), correcting the larger error
        first, holding the tilt and re-polling fast. +x right, +y down."""
        start = time.time()
        while time.time() - start < timeout:
            x, y = self.read_pos()
            if x is None:
                # Transient garbage read: hold the last input and re-poll rather
                # than snapping to neutral mid-glide (that causes the jitter).
                time.sleep(0.02)
                continue
            ex, ey = tx - x, ty - y
            if abs(ex) <= wiggle and abs(ey) <= wiggle:
                self.p.center()
                return True
            if abs(ey) > wiggle and abs(ey) >= abs(ex):
                self.p.main(0.5, 1.0 if ey > 0 else 0.0)   # +y down = pipe y 1.0
            else:
                self.p.main(1.0 if ex > 0 else 0.0, 0.5)
            time.sleep(0.016)
        self.p.center()
        return False

    def select(self, name, press=True, hold=None):
        """Steer to a stage by name and press A to pick it (which, with a locked
        CSS, starts the match). `hold` (e.g. 'X') is held through the load to
        trigger a DAS alternate stage.

        STAGE_TARGET holds the real vanilla stage-select coordinates, so we move
        straight to the target -- no screen scan -- and CONFIRM via the
        ground-truth hovered-stage id (the SSS analog of the CSS hovered() check),
        with a small local nudge in case the cursor landed just off the icon's
        hitbox. If the intended stage can't be confirmed we DON'T press (fail the
        check rather than silently test the wrong stage). 'random' has no stage
        id, so it just uses its coordinate."""
        key = norm(name)
        if key not in STAGE_TARGET:
            raise KeyError(f"no stage target for '{name}' "
                           f"(known: {', '.join(sorted(STAGE_TARGET))})")
        if not self.ensure_stage_select():
            return False
        tx, ty = STAGE_TARGET[key]
        target_id = STAGE_ID.get(key)
        reached = self.move_to(tx, ty)
        if target_id is not None:
            reached = False
            for dx, dy in ((0.0, 0.0), (0.0, 0.0), (1.2, 0.0), (-1.2, 0.0),
                           (0.0, 1.2), (0.0, -1.2)):
                if dx or dy:
                    self.move_to(tx + dx, ty + dy, wiggle=0.9, timeout=2.0)
                time.sleep(0.05)  # let the hovered byte settle once the cursor rests
                if self.hovered_stage() == target_id:
                    reached = True
                    break
            if not reached:
                return False
        if not press:
            return reached
        return self._confirm(tx, ty, hold=hold)

    def _confirm(self, tx, ty, hold=None):
        """Press A and verify the match actually starts (the scene leaves
        stage-select), re-pressing if a tap didn't take. If `hold` is a button,
        keep it held through the confirm + load (the DAS trigger). Don't use
        A/B/R to hold (A selects, B backs out, R flips pages)."""
        if hold:
            self.p.press(hold)
        try:
            for _ in range(6):
                self.p.center()   # only re-centers the stick; keeps `hold` down
                time.sleep(0.12)
                self.p.tap("A", 0.08)
                time.sleep(0.4)
                if not self.on_stage_select():
                    if hold:
                        time.sleep(0.7)  # keep holding so DAS reads it at load
                    return True
                self.move_to(tx, ty, timeout=2.0)
            return False
        finally:
            if hold:
                self.p.release(hold)

    def switch_page(self, n, settle=0.6):
        """Advance n m-ex stage-select pages by pressing R. Custom stages live
        on a page after the main Melee page."""
        for _ in range(max(0, n)):
            self.p.tap("R", 0.08)
            time.sleep(settle)

    def select_at(self, x, y, page=0, press=True, hold=None):
        """Select a stage by its explicit SSS icon coordinate (and page) -- from
        the build manifest. Advances to the stage's page with R first, verifying
        the page switch took (an R tap right after the START->SSS transition can
        be dropped, silently leaving us on page 0 where (x,y) is a vanilla
        stage), then steers and confirms. `hold` triggers a DAS alternate."""
        if not self.ensure_stage_select():
            return False
        self.switch_page(page)
        reached = self.move_to(x, y)
        if page > 0:
            vanilla_ids = set(STAGE_ID.values())
            for _ in range(4):
                hv = self.hovered_stage()
                if hv and hv not in vanilla_ids:
                    break  # on a custom tile -> page switch worked
                self.switch_page(1)
                reached = self.move_to(x, y)
        if not press:
            return reached
        return self._confirm(x, y, hold=hold)

    def find_stage_pos(self, target_id, pages=1, verbose=False):
        """Closed-loop, layout-INDEPENDENT search: SETTLE the cursor at a grid of
        points and read the hovered-stage id at each, until the target stage is
        under the cursor; return that (x,y) -- or None. Depends on
        hovered_stage() being populated."""
        if not self.ensure_stage_select():
            return None
        xs = [-26, -21, -16, -11, -6, -1, 4, 9, 14, 19, 24]
        ys = [-16, -11, -6, -1, 4, 9, 14]
        for page in range(max(1, pages)):
            for yi, y in enumerate(ys):
                row = xs if yi % 2 == 0 else list(reversed(xs))
                for x in row:
                    self.move_to(x, y, wiggle=1.2, timeout=1.5)
                    time.sleep(0.06)
                    if self.hovered_stage() == target_id:
                        return self.read_pos()
            if page + 1 < pages:
                self.switch_page(1)
        return None

    def select_by_id(self, target_id, press=True, hold=None, pages=1):
        """Select a stage by its hovered-stage id via closed-loop settle-read
        search -- robust to ANY SSS layout, as long as hovered_stage() is
        populated. `hold` triggers a DAS alternate."""
        pos = self.find_stage_pos(target_id, pages=pages)
        if pos is None or pos[0] is None:
            return False
        for _ in range(3):
            self.move_to(pos[0], pos[1], wiggle=0.9)
            if self.hovered_stage() == target_id:
                break
            time.sleep(0.1)
        if not press:
            return self.hovered_stage() == target_id
        return self._confirm(pos[0], pos[1], hold=hold)

    # --- direct force-select (no cursor, layout/page independent) -------------
    def force_select(self, internal_id, hold=None, timeout=4.0, hold_settle=0.5):
        """Select + start a stage by writing the engine's own force_stage_id field
        (SSSData+0x03) instead of moving the cursor: the SSS frame handler sees a
        non-negative value, copies it into the match rules and starts the match
        the next frame. No cursor, no page switching -- works for ANY layout and
        for custom stages on later SSS pages, unlike select()/select_at(), which
        depend on coordinates.

        `internal_id` is Melee's INTERNAL stage id (0..0x7F, the signed-byte
        field; from get-sss-layout 'stageID' / INTERNAL_STAGE_ID). `hold` (e.g.
        'X') is held through the load to trigger a DAS alternate; `hold_settle` is
        how long to keep it held on the live stage-select screen BEFORE triggering
        the load, so the engine actually polls the button (without this, the
        memory-fast load fires before the press registers and DAS reads no/stale
        button -- loading the wrong alternate). Requires a Dolphin handle opened
        for writing (melee_mem PROCESS_VM_WRITE). Returns whether the match
        started."""
        if internal_id is None or not (0 <= int(internal_id) <= 0x7F):
            return False
        if not self.ensure_stage_select():
            return False
        if hold:
            self.p.press(hold)
            if hold_settle > 0:
                time.sleep(hold_settle)   # let the held button register before the load fires
        try:
            start = time.time()
            while time.time() - start < timeout:
                s = self.d.u32(SSSDATA_PTR)
                if s and 0x80000000 <= s < 0x81800000:
                    self.d.write_s8(s + FORCE_STAGE_OFFSET, int(internal_id))
                time.sleep(0.1)
                if not self.on_stage_select():
                    if hold:
                        time.sleep(0.7)  # keep holding so DAS reads it at load
                    return True
            return not self.on_stage_select()
        finally:
            if hold:
                self.p.release(hold)
