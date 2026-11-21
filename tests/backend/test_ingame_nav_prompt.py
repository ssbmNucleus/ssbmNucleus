import pytest

import shared.ingame.nav as nav


class _Clock:
    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class _Scene:
    def __init__(self):
        self.major = nav.BOOT_MAJOR
        self.minor = 0

    def u8(self, address):
        if address == nav.SCENE_MAJOR:
            return self.major
        if address == nav.SCENE_MINOR:
            return self.minor
        raise AssertionError(f'unexpected address: {address:#x}')


class _Pipe:
    def __init__(self, scene, prompt_destination=nav.MENU_MAJOR):
        self.scene = scene
        self.prompt_destination = prompt_destination
        self.taps = []
        self.prompt_acks = 0
        self.menu_inputs = []
        self.held = []

    def neutral(self):
        pass

    def tap(self, button, _duration):
        self.taps.append(button)
        if self.scene.major == nav.BOOT_MAJOR:
            assert button == 'A'
            self.prompt_acks += 1
            if self.prompt_acks == 2:
                self.scene.major = self.prompt_destination
            return

        self.menu_inputs.append(button)
        if self.menu_inputs[-5:] == ['B', 'B', 'D_DOWN', 'A', 'A']:
            self.scene.major = nav.VS_MAJOR
            self.scene.minor = nav.CSS_MINOR

    def press(self, button):
        self.held.append(('press', button))

    def release(self, button):
        self.held.append(('release', button))


def _fake_time(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(nav.time, 'time', clock.time)
    monkeypatch.setattr(nav.time, 'sleep', clock.sleep)
    monkeypatch.setattr(nav, 'wait_game_frames', lambda *_a, **_k: True)
    return clock


def test_nav_to_css_acknowledges_pre_menu_prompts_until_scene_changes(monkeypatch):
    _fake_time(monkeypatch)
    scene = _Scene()
    pipe = _Pipe(scene)

    assert nav.nav_to_css(scene, pipe, timeout=20.0)
    assert pipe.taps[:2] == ['A', 'A']
    assert pipe.menu_inputs == ['B', 'B', 'D_DOWN', 'A', 'A']
    assert nav.at_offline_css(scene)


def test_prompt_recovery_still_hard_aborts_online_css(monkeypatch):
    _fake_time(monkeypatch)
    scene = _Scene()
    pipe = _Pipe(scene, prompt_destination=nav.ONLINE_CSS)

    with pytest.raises(nav.OnlineAbort):
        nav.nav_to_css(scene, pipe, timeout=20.0)

    assert ('press', 'B') in pipe.held
    assert ('release', 'B') in pipe.held
