"""nav_to_css drives the main menu from MenuFlow (0x804A04F0), so builds that
don't boot into Slippi's Online Play submenu (the ACE Build boots to the
top-level main menu, where B returns to the title screen) still reach the
offline CSS, while a Slippi build gets exactly the old B,B,D_DOWN,A,A."""
import shared.ingame.nav as nav


class _Clock:
    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class _Menu:
    """A main menu modelled on the RAM the probes read (2026-09-21):
    Slippi boots in submenu 8 (Online) whose parent is 1 (1P) whose parent is
    the main menu; ACE boots straight into the main menu at row 0."""

    MAIN_ROWS = 5

    def __init__(self, cur, hov, parents=None):
        self.major = nav.MENU_MAJOR
        self.minor = 0
        self.cur, self.hov = cur, hov
        self.parents = parents or {}

    def u8(self, address):
        if address == nav.SCENE_MAJOR:
            return self.major
        if address == nav.SCENE_MINOR:
            return self.minor
        if address == nav.MENU_FLOW:
            return self.cur
        if address == nav.MENU_FLOW + 3:
            return self.hov
        raise AssertionError(f'unexpected address: {address:#x}')

    def press(self, button):
        if self.major != nav.MENU_MAJOR:
            return
        if button == 'B':
            if self.cur == nav.MENU_KIND_MAIN:
                self.major = nav.BOOT_MAJOR          # back to the title screen
            else:
                self.cur, self.hov = self.parents.get(self.cur, nav.MENU_KIND_MAIN), 0
        elif button == 'D_DOWN':
            self.hov = min(self.hov + 1, self.MAIN_ROWS - 1)
        elif button == 'D_UP':
            self.hov = max(self.hov - 1, 0)
        elif button == 'A':
            if self.cur == nav.MENU_KIND_MAIN and self.hov == nav.MAIN_VS_ROW:
                self.cur, self.hov = nav.MENU_KIND_VS, 0
            elif self.cur == nav.MENU_KIND_VS and self.hov == nav.VS_MELEE_ROW:
                self.major, self.minor = nav.VS_MAJOR, nav.CSS_MINOR
            elif self.cur == nav.MENU_KIND_MAIN and self.hov == 0:
                self.cur, self.hov = 1, 0            # into the 1P menu


class _Pipe:
    def __init__(self, menu):
        self.menu = menu
        self.taps = []

    def neutral(self):
        pass

    def tap(self, button, _duration):
        self.taps.append(button)
        self.menu.press(button)

    def press(self, button):
        pass

    def release(self, button):
        pass


def _fake_time(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(nav.time, 'time', clock.time)
    monkeypatch.setattr(nav.time, 'sleep', clock.sleep)
    monkeypatch.setattr(nav, 'wait_game_frames', lambda *_a, **_k: True)
    return clock


def test_slippi_boot_menu_gets_the_old_recipe(monkeypatch):
    _fake_time(monkeypatch)
    menu = _Menu(cur=8, hov=1, parents={8: 1, 1: nav.MENU_KIND_MAIN})
    pipe = _Pipe(menu)
    assert nav.nav_to_css(menu, pipe, timeout=20.0)
    assert pipe.taps == ['B', 'B', 'D_DOWN', 'A', 'A']


def test_ace_main_menu_never_presses_b(monkeypatch):
    _fake_time(monkeypatch)
    menu = _Menu(cur=nav.MENU_KIND_MAIN, hov=0)
    pipe = _Pipe(menu)
    assert nav.nav_to_css(menu, pipe, timeout=20.0)
    assert pipe.taps == ['D_DOWN', 'A', 'A']
    assert 'B' not in pipe.taps


def test_cursor_below_vs_moves_up(monkeypatch):
    _fake_time(monkeypatch)
    menu = _Menu(cur=nav.MENU_KIND_MAIN, hov=3)
    pipe = _Pipe(menu)
    assert nav.nav_to_css(menu, pipe, timeout=20.0)
    assert pipe.taps == ['D_UP', 'D_UP', 'A', 'A']


def test_next_menu_button():
    assert nav.next_menu_button(8, 1) == 'B'
    assert nav.next_menu_button(nav.MENU_KIND_MAIN, 0) == 'D_DOWN'
    assert nav.next_menu_button(nav.MENU_KIND_MAIN, 1) == 'A'
    assert nav.next_menu_button(nav.MENU_KIND_VS, 2) == 'D_UP'
    assert nav.next_menu_button(nav.MENU_KIND_VS, 0) == 'A'


def test_unreadable_menu_state_falls_back_to_the_recipe():
    class _NoMenu:
        def u8(self, address):
            raise RuntimeError('unmapped')
    assert nav.menu_flow(_NoMenu()) is None

    class _Garbage:
        def u8(self, address):
            return 0xFF
    assert nav.menu_flow(_Garbage()) is None
