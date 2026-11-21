r"""netrig.py -- scripted two-client Slippi netplay rig for desync testing.

Runs TWO real Slippi Dolphin instances on this machine, each signed into a
different Slippi account, direct-connects them over real Slippi matchmaking,
plays scripted sequences (e.g. Falcon dthrow spam), and yields a desync
verdict by diffing the two clients' own .slp recordings of the SAME game --
the finalized frames diverge if and only if the simulations diverged.

Instances (persistent, under NETRIG_ROOT, default ~/slippi-desync-rig):
  instance-a\        exe + User dir, account frozen at clone time
  instance-b\User    User dir refreshed each run from the live launcher
                     install (whatever account the launcher is signed into)
Both share instance-a's exe; -u picks the user dir. Per-instance separation:
  pipe input   slippibot1 / slippibot2   (Windows pipe namespace is global)
  netplay port 2627 / 2628
  spectator    51442 / 51443
  replays      replays-a\ / replays-b\   (the desync oracle's inputs)
  logs         each instance's User\Logs\dolphin.log (WriteToFile forced on)

Phases (CLI):
  smoke     launch both, attach RAM, wait for the Slippi main menu on both,
            verify both input pipes, report scene + log tails.  --keep leaves
            them running for manual poking; default terminates.
  kill      terminate any rig-launched Dolphins (from rig-state.json).
  status    scene + pid + log tail of whatever the rig has running.

Run from backend/:  python devtools/netrig.py smoke
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.ingame.boot import _patch_dolphin_ini, _patch_hotkeys, _write_ini  # noqa: E402
from shared.ingame.melee_mem import Dolphin  # noqa: E402
from shared.ingame import melee_pipe  # noqa: E402
from shared.ingame.nav import SCENE_MAJOR, SCENE_MINOR  # noqa: E402
from shared.ingame import dolphin_lock  # noqa: E402

RIG_ROOT = Path(os.environ.get("NETRIG_ROOT") or Path.home() / "slippi-desync-rig")
# Client B's default ISO (smoke/connect/play --iso-b): a vanilla 1.02 disc.
VANILLA_ISO = os.environ.get("NUCLEUS_VANILLA_ISO")
LIVE_NETPLAY = Path(os.environ.get("APPDATA", "")) / "Slippi Launcher" / "netplay"
STATE_PATH = RIG_ROOT / "rig-state.json"

MENU_MAJOR = 0x01          # Slippi main / Online-Play menu
ONLINE_CSS_MAJOR = 0x08    # Slippi online CSS

# --- Input backends ---------------------------------------------------------
# PRIMARY: XPad -- one ViGEm virtual Xbox 360 controller per instance
# (vgamepad + the ViGEmBus driver, already present on this machine). Full
# analog sticks, per-instance routing via XInput slot, no window focus games.
# The virtual pads MUST exist before their Dolphin launches (XInput devices
# are enumerated at startup).
#
# Historical fallbacks kept below, with the measured reasons they lost:
#  * slippibot pipes: ONE Dolphin creates ALL FOUR \\.\pipe\slippibot1..4 at
#    startup regardless of pad config (measured 2026-08-25), and pipe-creation
#    order follows process-init order, not launch order -- only one instance
#    per machine can be pipe-driven, nondeterministically.
#  * SendInput keyboard: DirectInput has no scancodes past F15, so it needs
#    ordinary keys plus window focus juggling. Digital stick only.

import ctypes as _ct

try:
    import vgamepad as _vg
except ImportError:      # pip install vgamepad (needs the ViGEmBus driver)
    _vg = None


def _xinput_connected_count():
    """Number of ALREADY-connected XInput pads (physical or virtual); the
    rig's virtual pads take the next free slots, so this is the base index
    Dolphin should be pointed at."""
    try:
        xi = _ct.WinDLL("xinput1_4")
    except OSError:
        return 0
    buf = (_ct.c_ubyte * 16)()
    n = 0
    for i in range(4):
        if xi.XInputGetState(i, _ct.byref(buf)) == 0:
            n += 1
        else:
            break
    return n


class XPad:
    """Pipe-compatible input driver over a ViGEm virtual X360 pad (analog)."""

    def __init__(self):
        if _vg is None:
            raise RuntimeError("vgamepad not installed (pip install vgamepad)")
        self.g = _vg.VX360Gamepad()
        self._btn = {
            "A": _vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
            "B": _vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
            "X": _vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
            "Y": _vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
            "Z": _vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
            "START": _vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
            "D_UP": _vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
            "D_DOWN": _vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
            "D_LEFT": _vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
            "D_RIGHT": _vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
        }
        self.g.reset()
        self.g.update()

    def _set_btn(self, btn, down):
        if btn == "L":
            self.g.left_trigger_float(1.0 if down else 0.0)
        elif btn == "R":
            self.g.right_trigger_float(1.0 if down else 0.0)
        elif down:
            self.g.press_button(self._btn[btn])
        else:
            self.g.release_button(self._btn[btn])

    def press_many(self, btns):
        """All pressed in ONE report -- same-frame simultaneity (the LRAS
        combo misfires as a pause when the presses trickle in)."""
        for btn in btns:
            self._set_btn(btn, True)
        self.g.update()

    def release_many(self, btns):
        for btn in btns:
            self._set_btn(btn, False)
        self.g.update()

    def press(self, btn):
        self._set_btn(btn, True)
        self.g.update()

    def release(self, btn):
        self._set_btn(btn, False)
        self.g.update()

    def tap(self, btn, hold=0.08):
        self.press(btn)
        time.sleep(hold)
        self.release(btn)

    # Stick convention matches melee_pipe: 0.0-1.0, 0.5 center, y=1.0 UP.
    def main(self, x, y):
        self.g.left_joystick_float(2 * x - 1, 2 * y - 1)
        self.g.update()

    def c(self, x, y):
        self.g.right_joystick_float(2 * x - 1, 2 * y - 1)
        self.g.update()

    def center(self):
        self.main(0.5, 0.5)

    def tilt(self, x, y, hold):
        self.main(x, y)
        time.sleep(hold)
        self.center()

    def neutral(self):
        self.g.reset()
        self.g.update()

    def close(self):
        try:
            self.g.reset()
            self.g.update()
        except Exception:
            pass


def _patch_xinput_pad(user_dir, xinput_index):
    """GCPad1 <- the virtual X360 pad in XInput slot `xinput_index`."""
    gc_path = os.path.join(user_dir, "Config", "GCPadNew.ini")

    def mutate_gc(upsert, replace_section):
        p = "GCPad1"
        replace_section(p, {})
        upsert(p, "Device", f"XInput/{xinput_index}/Gamepad")
        # Without this, Dolphin only reads the pad while its window has
        # FOCUS -- with two windows (or the user clicking around) input
        # silently dies mid-flow. Root cause of the 8-26 confirm failures.
        upsert(p, "Background Input", "True")
        upsert(p, "Buttons/A", "`Button A`")
        upsert(p, "Buttons/B", "`Button B`")
        upsert(p, "Buttons/X", "`Button X`")
        upsert(p, "Buttons/Y", "`Button Y`")
        upsert(p, "Buttons/Z", "`Shoulder R`")
        upsert(p, "Buttons/Start", "`Start`")
        upsert(p, "Main Stick/Up", "`Left Y+`")
        upsert(p, "Main Stick/Down", "`Left Y-`")
        upsert(p, "Main Stick/Left", "`Left X-`")
        upsert(p, "Main Stick/Right", "`Left X+`")
        upsert(p, "Main Stick/Radius", "100.0")
        upsert(p, "C-Stick/Up", "`Right Y+`")
        upsert(p, "C-Stick/Down", "`Right Y-`")
        upsert(p, "C-Stick/Left", "`Right X-`")
        upsert(p, "C-Stick/Right", "`Right X+`")
        upsert(p, "C-Stick/Radius", "100.0")
        upsert(p, "Triggers/L", "`Trigger L`")
        upsert(p, "Triggers/R", "`Trigger R`")
        upsert(p, "Triggers/L-Analog", "`Trigger L`")
        upsert(p, "Triggers/R-Analog", "`Trigger R`")
        upsert(p, "D-Pad/Up", "`Pad N`")
        upsert(p, "D-Pad/Down", "`Pad S`")
        upsert(p, "D-Pad/Left", "`Pad W`")
        upsert(p, "D-Pad/Right", "`Pad E`")
        replace_section("GCPad3", {})

    _write_ini(gc_path, mutate_gc)

# button -> (Dolphin DInput key name, keyboard scancode)
_KEYMAP = {
    "A": ("P", 0x19), "B": ("O", 0x18), "X": ("I", 0x17), "Y": ("U", 0x16),
    "Z": ("H", 0x23), "START": ("RETURN", 0x1C), "L": ("Q", 0x10),
    "R": ("E", 0x12),
    "MAIN_UP": ("W", 0x11), "MAIN_DOWN": ("S", 0x1F),
    "MAIN_LEFT": ("A", 0x1E), "MAIN_RIGHT": ("D", 0x20),
    "C_UP": ("T", 0x14), "C_DOWN": ("G", 0x22),
}

_user32 = _ct.WinDLL("user32", use_last_error=True) if os.name == "nt" else None
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_KEYUP = 0x0002


class _KEYBDINPUT(_ct.Structure):
    _fields_ = [("wVk", _ct.c_ushort), ("wScan", _ct.c_ushort),
                ("dwFlags", _ct.c_ulong), ("time", _ct.c_ulong),
                ("dwExtraInfo", _ct.POINTER(_ct.c_ulong))]


class _INPUT(_ct.Structure):
    class _U(_ct.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("pad", _ct.c_ubyte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", _ct.c_ulong), ("u", _U)]


def _send_scan(scan, down):
    inp = _INPUT()
    inp.type = 1  # INPUT_KEYBOARD
    flags = KEYEVENTF_SCANCODE | (0 if down else KEYEVENTF_KEYUP)
    inp.ki = _KEYBDINPUT(0, scan, flags, 0, None)
    _user32.SendInput(1, _ct.byref(inp), _ct.sizeof(_INPUT))


class KeyPad:
    """Pipe-compatible input driver: scancode SendInput of letter keys, with
    the target Dolphin focused for each burst (see namespace note above)."""

    def __init__(self, pid=None):
        self.pid = pid
        self._down = set()
        self._last_focus = 0.0

    def _focus(self):
        if self.pid and time.time() - self._last_focus > 1.5:
            from shared.ingame.screenshot_win import _foreground
            _foreground(self.pid)
            self._last_focus = time.time()
            time.sleep(0.05)

    def _set(self, name, down):
        if down and name not in self._down:
            self._focus()
            _send_scan(_KEYMAP[name][1], True)
            self._down.add(name)
        elif not down and name in self._down:
            _send_scan(_KEYMAP[name][1], False)
            self._down.discard(name)

    def press(self, btn):
        self._set(btn, True)

    def release(self, btn):
        self._set(btn, False)

    def tap(self, btn, hold=0.08):
        self.press(btn)
        time.sleep(hold)
        self.release(btn)

    def main(self, x, y):
        """Digital quantisation of the analog convention (0.5 = center,
        y=1.0 UP). Deadzone third in the middle."""
        self._set("MAIN_LEFT", x < 0.35)
        self._set("MAIN_RIGHT", x > 0.65)
        self._set("MAIN_UP", y > 0.65)
        self._set("MAIN_DOWN", y < 0.35)

    def c(self, x, y):
        self._set("C_UP", y > 0.65)
        self._set("C_DOWN", y < 0.35)

    def center(self):
        self.main(0.5, 0.5)

    def tilt(self, x, y, hold):
        self.main(x, y)
        time.sleep(hold)
        self.center()

    def neutral(self):
        for name in list(self._down):
            self._set(name, False)

    def close(self):
        self.neutral()


def _patch_keyboard_pad(user_dir):
    """GCPad1 <- DInput keyboard on ordinary letter keys (see note above)."""
    gc_path = os.path.join(user_dir, "Config", "GCPadNew.ini")

    def mutate_gc(upsert, replace_section):
        p = "GCPad1"
        replace_section(p, {})
        upsert(p, "Device", "DInput/0/Keyboard Mouse")
        upsert(p, "Background Input", "True")
        for btn in ("A", "B", "X", "Y", "Z"):
            upsert(p, f"Buttons/{btn}", f"`{_KEYMAP[btn][0]}`")
        upsert(p, "Buttons/Start", f"`{_KEYMAP['START'][0]}`")
        upsert(p, "Triggers/L", f"`{_KEYMAP['L'][0]}`")
        upsert(p, "Triggers/R", f"`{_KEYMAP['R'][0]}`")
        upsert(p, "Main Stick/Up", f"`{_KEYMAP['MAIN_UP'][0]}`")
        upsert(p, "Main Stick/Down", f"`{_KEYMAP['MAIN_DOWN'][0]}`")
        upsert(p, "Main Stick/Left", f"`{_KEYMAP['MAIN_LEFT'][0]}`")
        upsert(p, "Main Stick/Right", f"`{_KEYMAP['MAIN_RIGHT'][0]}`")
        upsert(p, "Main Stick/Radius", "100.0")
        upsert(p, "C-Stick/Up", f"`{_KEYMAP['C_UP'][0]}`")
        upsert(p, "C-Stick/Down", f"`{_KEYMAP['C_DOWN'][0]}`")
        upsert(p, "C-Stick/Radius", "100.0")
        replace_section("GCPad3", {})

    _write_ini(gc_path, mutate_gc)


def log(msg):
    print(f"[netrig {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def to_fullwidth(code):
    """ASCII connect code -> the fullwidth form Melee/direct-codes.json uses."""
    return "".join(chr(ord(c) + 0xFEE0) if 0x21 <= ord(c) <= 0x7E else c
                   for c in code)


def _patch_logger_ini(user_dir):
    """Force Dolphin file logging with the netplay-relevant categories on."""
    path = os.path.join(user_dir, "Config", "Logger.ini")

    def mutate(upsert, _replace):
        upsert("Options", "WriteToFile", "True")
        upsert("Options", "Verbosity", "4")  # Info
        # OSD carries the on-screen messages (the yellow "desync possible"
        # text bottom-right) when the build logs them -- scan-worthy.
        for cat in ("SLIPPI", "SLIPPI_ONLINE", "NETPLAY", "OSREPORT",
                    "BRAWLBACK", "EXI", "OSD"):
            upsert("Logs", cat, "True")
        # Info verbosity makes these fire hoses; the desync story never
        # needs interpreter/JIT internals.
        for cat in ("CORE", "POWERPC", "DYNA_REC", "MASTER"):
            upsert("Logs", cat, "False")

    _write_ini(path, mutate)


def _patch_framedump(user_dir, enable):
    """Dolphin-native frame dumping (User\\Dump\\Frames\\framedump0.avi):
    occlusion-proof eyes + a scrubbable record of desync moments, including
    the on-screen yellow OSD text. ~0.4 MB/s at menus, a few MB/s in game."""
    path = os.path.join(user_dir, "Config", "Dolphin.ini")

    def mutate(upsert, _replace):
        upsert("Movie", "DumpFrames", "True" if enable else "False")
        upsert("Movie", "DumpFramesSilent", "True")

    _write_ini(path, mutate)


def _patch_slippi_ports(user_dir, netplay_port, spectator_port, replay_dir):
    path = os.path.join(user_dir, "Config", "Dolphin.ini")

    def mutate(upsert, _replace):
        upsert("Core", "SlippiForceNetplayPort", "True")
        upsert("Core", "SlippiNetplayPort", str(netplay_port))
        upsert("Core", "SlippiSpectatorLocalPort", str(spectator_port))
        upsert("Core", "SlippiReplayDir", str(replay_dir))
        upsert("Core", "SlippiSaveReplays", "True")
        upsert("Core", "MemcardAPath",
               str(Path(user_dir) / "GC" / "MemoryCardA.USA.raw").replace("\\", "/"))
        upsert("Core", "MemcardBPath",
               str(Path(user_dir) / "GC" / "MemoryCardB.USA.raw").replace("\\", "/"))

    _write_ini(path, mutate)


class RigInstance:
    def __init__(self, name, user_dir, exe, iso, pipe_index, netplay_port,
                 spectator_port, input_backend="xpad", xinput_index=None):
        self.name = name
        self.user_dir = Path(user_dir)
        self.exe = Path(exe)
        self.iso = Path(iso)
        self.pipe_index = pipe_index
        self.netplay_port = netplay_port
        self.spectator_port = spectator_port
        self.input_backend = input_backend
        self.xinput_index = xinput_index
        self.replay_dir = RIG_ROOT / f"replays-{name}"
        self.proc = None
        self.mem = None
        self._pipe = None

    # -- identity ----------------------------------------------------------
    def user_json(self):
        p = self.user_dir / "Slippi" / "user.json"
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def connect_code(self):
        return self.user_json().get("connectCode", "")

    def seed_direct_code(self, peer_code):
        """Put the peer's connect code at the top of the Direct menu's
        remembered list so navigation is a fixed button sequence."""
        p = self.user_dir / "Slippi" / "direct-codes.json"
        entry = {"connectCode": to_fullwidth(peer_code),
                 "lastPlayed": int(time.time())}
        try:
            codes = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            codes = []
        codes = [c for c in codes
                 if c.get("connectCode") != entry["connectCode"]]
        codes.insert(0, entry)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(codes), encoding="utf-8")

    # -- prep --------------------------------------------------------------
    def patch_configs(self, dump=False):
        _patch_dolphin_ini(str(self.user_dir), f"slippibot{self.pipe_index}")
        if self.input_backend == "xpad":
            _patch_xinput_pad(str(self.user_dir), self.xinput_index)
        elif self.input_backend == "keys":
            _patch_keyboard_pad(str(self.user_dir))
        _patch_hotkeys(str(self.user_dir))
        _patch_logger_ini(str(self.user_dir))
        _patch_framedump(str(self.user_dir), dump)
        _patch_slippi_ports(str(self.user_dir), self.netplay_port,
                            self.spectator_port, self.replay_dir)
        self.replay_dir.mkdir(parents=True, exist_ok=True)

    def collect_dumps(self, tag):
        """Move this run's framedump AVIs into RIG_ROOT/dumps as
        <tag>-<name>.avi; returns the moved paths."""
        out = []
        dump_dir = self.user_dir / "Dump" / "Frames"
        dst_root = RIG_ROOT / "dumps"
        dst_root.mkdir(parents=True, exist_ok=True)
        for i, p in enumerate(sorted(dump_dir.glob("framedump*.avi"))):
            dst = dst_root / f"{tag}-{self.name}{'' if i == 0 else i}.avi"
            try:
                shutil.move(str(p), dst)
                out.append(dst)
            except OSError:
                pass
        return out

    # -- lifecycle ---------------------------------------------------------
    def launch(self):
        if not self.iso.exists():
            raise FileNotFoundError(f"[{self.name}] ISO missing: {self.iso}")
        if getattr(self, "_peer_seed", None):
            self.seed_direct_code(self._peer_seed)
        args = [str(self.exe), "-u", str(self.user_dir), "-b", "-e",
                str(self.iso)]
        self.proc = subprocess.Popen(args, cwd=str(self.exe.parent))
        log(f"[{self.name}] launched pid {self.proc.pid} "
            f"({self.user_json().get('displayName')} "
            f"{self.connect_code()}, pipe slippibot{self.pipe_index}, "
            f"port {self.netplay_port})")

    def attach(self, timeout=60.0):
        """Attach the RAM reader once Melee's MEM1 exists."""
        deadline = time.time() + timeout
        last_err = None
        while time.time() < deadline:
            if self.proc and self.proc.poll() is not None:
                raise RuntimeError(
                    f"[{self.name}] Dolphin exited (code {self.proc.poll()})")
            try:
                mem = Dolphin(self.proc.pid)
                if mem.base:
                    self.mem = mem
                    log(f"[{self.name}] MEM1 attached")
                    return
                mem.close()
            except OSError as e:
                last_err = e
            time.sleep(0.5)
        raise TimeoutError(f"[{self.name}] MEM1 never appeared: {last_err}")

    def scene(self):
        if not self.mem:
            return (None, None)
        if self.mem.base is None and not self.mem.locate():
            return (None, None)
        return (self.mem.u8(SCENE_MAJOR), self.mem.u8(SCENE_MINOR))

    def wait_scene_major(self, majors, timeout=90.0, label=""):
        deadline = time.time() + timeout
        while time.time() < deadline:
            maj, _ = self.scene()
            if maj in majors:
                return maj
            time.sleep(0.25)
        maj, mino = self.scene()
        raise TimeoutError(
            f"[{self.name}] never reached scene {label or majors}; "
            f"stuck at major={maj} minor={mino}")

    def pipe(self):
        if self._pipe is None:
            if self.input_backend == "xpad":
                self._pipe = XPad()  # normally pre-created in build_instances
            elif self.input_backend == "keys":
                self._pipe = KeyPad(pid=self.proc.pid if self.proc else None)
            else:
                self._pipe = melee_pipe.Pipe(
                    port=self.pipe_index, open_timeout=30.0,
                    alive=lambda: self.proc and self.proc.poll() is None)
        return self._pipe

    def log_tail(self, n=15):
        p = self.user_dir / "Logs" / "dolphin.log"
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            return lines[-n:]
        except OSError:
            return [f"(no log at {p})"]

    def _close_windows(self):
        """Post WM_CLOSE to every top-level window of the process -- a
        GRACEFUL Dolphin shutdown, which flushes/finalizes the .slp replay.
        TerminateProcess leaves truncated replays peppi cannot parse."""
        if os.name != "nt" or not self.proc:
            return
        import ctypes.wintypes as wt
        WM_CLOSE = 0x0010
        pid = self.proc.pid

        @_ct.WINFUNCTYPE(_ct.c_bool, wt.HWND, wt.LPARAM)
        def _cb(hwnd, _l):
            wpid = wt.DWORD(0)
            _user32.GetWindowThreadProcessId(hwnd, _ct.byref(wpid))
            if wpid.value == pid:
                _user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            return True

        _user32.EnumWindows(_cb, 0)

    def terminate(self):
        # Virtual pads OUTLIVE Dolphin restarts on purpose: they must exist
        # BEFORE the next launch (batch-mode Dolphin does not hotplug XInput),
        # and closing them here was exactly why relaunched instances went
        # input-dead. Only pipe/keyboard backends are per-process.
        if self._pipe and self.input_backend != "xpad":
            try:
                self._pipe.close()
            except Exception:
                pass
            self._pipe = None
        elif self._pipe:
            try:
                self._pipe.neutral()
            except Exception:
                pass
        if self.mem:
            self.mem.close()
            self.mem = None
        if self.proc and self.proc.poll() is None:
            try:
                self._close_windows()
                self.proc.wait(timeout=12)
            except (subprocess.TimeoutExpired, OSError):
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        self.proc = None


def refresh_instance_b():
    """(Re)build instance-b's User dir from the live launcher install --
    Config/GC/GameSettings wholesale, Slippi minus caches -- then keep its
    identity current (user.json is the account the launcher is signed into)."""
    src = LIVE_NETPLAY / "User"
    dst = RIG_ROOT / "instance-b" / "User"
    if not (src / "Slippi" / "user.json").exists():
        raise FileNotFoundError(f"live netplay install has no user.json: {src}")
    for sub in ("Config", "GC", "GameSettings"):
        if (src / sub).exists():
            shutil.copytree(src / sub, dst / sub, dirs_exist_ok=True)
    (dst / "Slippi").mkdir(parents=True, exist_ok=True)
    for f in ("user.json", "direct-codes.json", "teams-codes.json"):
        if (src / "Slippi" / f).exists():
            shutil.copy2(src / "Slippi" / f, dst / "Slippi" / f)
    return dst


# Mode-menu rows (Ranked, Unranked, Direct, Teams, Party) sampled at these
# (x, y) fractions of the client area; the selected row renders saturated
# yellow. RAM held no clean cursor byte (searched 2026-08-25), so pixels are
# the ground truth here. The menu WRAPS on up/down.
MODE_ROWS = [(0.38, 0.31), (0.30, 0.40), (0.25, 0.51), (0.29, 0.61),
             (0.25, 0.71)]
MODE_DIRECT = 2


def mode_menu_selection(inst):
    """Which mode-menu row is highlighted (0..4), by pixel sampling; -1 if
    nothing looks selected (mid-animation)."""
    import io
    from PIL import Image
    from shared.ingame.screenshot_win import capture_via_printwindow
    png = capture_via_printwindow(inst.proc.pid, max_width=640)
    if not png:
        return -1
    img = Image.open(io.BytesIO(png)).convert("RGB")
    w, h = img.size
    scores = []
    for fx, fy in MODE_ROWS:
        px = img.crop((int(fx * w) - 6, int(fy * h) - 4,
                       int(fx * w) + 6, int(fy * h) + 4))
        rs = gs = bs = n = 0
        for r, g, b in px.getdata():
            rs += r; gs += g; bs += b; n += 1
        r, g, b = rs / n, gs / n, bs / n
        scores.append(r + g - 1.5 * b)  # yellowness
    best = max(range(5), key=lambda i: scores[i])
    if scores[best] < 220:  # nothing bright -- menu animating/faded
        return -1
    return best


def select_mode_direct(inst, timeout=45.0):
    """Closed-loop: step the wrapped mode menu until Direct is highlighted,
    then press A and confirm via the scene flip to the online CSS."""
    pad = inst.pipe()
    deadline = time.time() + timeout
    blind = 0
    while time.time() < deadline:
        sel = mode_menu_selection(inst)
        if sel == MODE_DIRECT:
            blind = 0
            pad.tap("A", 0.08)
            t = time.time() + 4.0
            while time.time() < t:
                if inst.scene()[0] == ONLINE_CSS_MAJOR:
                    return
                time.sleep(0.2)
            continue  # A eaten -- re-verify selection and retry
        if sel >= 0:
            blind = 0
            steps = (MODE_DIRECT - sel) % 5
            down = steps <= 2
            pad.tilt(0.5, 0.0 if down else 1.0, 0.12)
        else:
            blind += 1   # menu not visible -- keep watching (mid-animation)
        time.sleep(0.55)
    try:
        from shared.ingame.screenshot_win import capture_via_printwindow
        img = capture_via_printwindow(inst.proc.pid, max_width=800)
        dbg = RIG_ROOT / f"debug-{inst.name}-modemenu.png"
        if img:
            dbg.write_bytes(img)
            log(f"[{inst.name}] debug screenshot: {dbg}")
    except Exception:
        pass
    raise TimeoutError(f"[{inst.name}] could not reach Direct on the mode menu")


def move_to_digital(cursor, pad, tx, ty, tol=1.5, timeout=10.0):
    """Bang-bang CSS cursor control for the digital KeyPad: pulse toward the
    target, settle, re-read. Converges to ~a cell width, which the caller then
    confirms via the hovered-index read."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        x, y = cursor.read_pos()
        if x is None:
            time.sleep(0.05)
            continue
        ex, ey = tx - x, ty - y
        if abs(ex) < tol and abs(ey) < tol:
            pad.center()
            return True
        # y RAM axis: +down; pad convention y=1.0 UP.
        pad.main(0.5 + (0.5 if ex > 0 else -0.5) * (abs(ex) > tol),
                 0.5 + (-0.5 if ey > 0 else 0.5) * (abs(ey) > tol))
        time.sleep(min(0.12, max(0.03, 0.006 * max(abs(ex), abs(ey)))))
        pad.center()
        time.sleep(0.08)
    pad.center()
    return False


_CSS_LOCK = None


def direct_css_selected(inst):
    """The green '- Character selected' status line on the Direct CSS panel
    (pixel probe -- the offline lock byte does not exist online)."""
    import io
    from PIL import Image
    from shared.ingame.screenshot_win import capture_via_printwindow
    png = capture_via_printwindow(inst.proc.pid, max_width=640)
    if not png:
        return False
    img = Image.open(io.BytesIO(png)).convert("RGB")
    w, h = img.size
    # Measured on the real locked CSS: the green status dash sits at
    # x 0.60-0.62, y 0.625-0.627; unlocked screens have ZERO green here.
    box = img.crop((int(0.50 * w), int(0.55 * h),
                    int(0.75 * w), int(0.68 * h)))
    green = sum(1 for r, g, b in box.getdata()
                if g > 150 and g > r + 40 and g > b + 40)
    return green > 6


def select_character_online(inst, char="falcon", costume=0, css_index=7,
                            css_pos=None):
    """Steer the online-CSS cursor to `char` and lock in. The offline
    P1_LOCKED byte does not exist on the online CSS; the hovered-index read
    is the ground truth. SERIALIZED across instances: a concurrent selection
    once locked Young Link while reporting Falcon (suspected pad-report
    crosstalk during simultaneous updates)."""
    global _CSS_LOCK
    import threading
    if _CSS_LOCK is None:
        _CSS_LOCK = threading.Lock()
    from shared.ingame.melee_css import Cursor
    pad = inst.pipe()
    if char == "any":
        # Modded builds rearrange the CSS (bigtest hovered=13 where vanilla
        # Falcon sits, and the vanilla grid coords are all wrong) -- for a
        # VICTIM client the character is irrelevant, so just lock whatever
        # the cursor is on, green-dash verified.
        _CSS_LOCK.acquire()
        try:
            # Optional open-loop strokes first (builds whose glove spawns
            # off-grid, e.g. Salandit's literal ISO -- calibrated via the
            # cssprobe command).
            strokes = os.environ.get("NETRIG_CSS_STROKES", "").strip()
            for part in [p for p in strokes.split(";") if p]:
                sx, sy, ms = part.split(",")
                pad.main(float(sx), float(sy))
                time.sleep(float(ms) / 1000.0)
                pad.center()
                time.sleep(0.15)
            for _try in range(10):
                pad.tap("A", 0.08)
                time.sleep(1.0)
                if not direct_css_selected(inst) and _try >= 1:
                    # sweep across the row until a cell takes
                    pad.main(1.0, 0.5)
                    time.sleep(0.05)
                    pad.center()
                    time.sleep(0.2)
                if direct_css_selected(inst):
                    log(f"[{inst.name}] selected whatever the cursor was on "
                        "(char=any)")
                    return
            raise RuntimeError(f"[{inst.name}] could not lock any character")
        finally:
            _CSS_LOCK.release()
    grid = json.loads((Path(__file__).resolve().parents[1] / "shared" / "ingame"
                       / "grid.json").read_text())
    if css_pos is not None:
        # Explicit target for MODDED CSS layouts (coords + icon index read
        # from the build's own mex css layout; the vanilla grid is wrong
        # there). NETRIG_CSS_LAYOUT_<INST> = path to the project's
        # data/css.json supplies the build's own icon table so the
        # hovered-delta correction works (deltas are offset-invariant).
        tx, ty = css_pos
        cells = []
        layout = os.environ.get(f"NETRIG_CSS_LAYOUT_{inst.name.upper()}")
        if layout and Path(layout).exists():
            icons = json.loads(Path(layout).read_text())["fighterIcons"]
            cells = [(ic["x"], ic["y"]) for ic in icons]
    else:
        tx, ty = grid[char]
        cells = list(grid.values())   # grid.json is ordered by CSS index
        # The caller-supplied css_index is only right for Falcon; derive
        # the true index from the grid ordering (yoshi=5 was hovered while
        # the check demanded 7 -> nav failure).
        css_index = list(grid).index(char)
    cur = Cursor(inst.mem, inst.pipe())
    _CSS_LOCK.acquire()
    try:
        _select_character_locked(inst, cur, pad, cells, tx, ty,
                                 char, costume, css_index)
    finally:
        _CSS_LOCK.release()


def _select_character_locked(inst, cur, pad, cells, tx, ty,
                             char, costume, css_index):
    if inst.input_backend == "keys":
        move_to_digital(cur, pad, tx, ty)
    else:
        cur.move_to(tx, ty)
    if css_index < 0:
        # DEAD RECKONING for builds whose hovered-index byte is unreliable
        # (Salandit's Animelee CC core): trust the coords, lock blind, and
        # let cmd_play's kinds check + reconnect loop catch a wrong pick.
        # NETRIG_CSS_STROKES="sx,sy,ms;..." replaces the RAM-fed move with
        # OPEN-LOOP timed stick strokes from the glove's (reproducible)
        # spawn -- calibrated visually from the pre-lock screenshot this
        # branch drops in watch/.
        strokes = os.environ.get("NETRIG_CSS_STROKES", "").strip()
        if strokes:
            for part in strokes.split(";"):
                sx, sy, ms = part.split(",")
                pad.main(float(sx), float(sy))
                time.sleep(float(ms) / 1000.0)
                pad.center()
                time.sleep(0.15)
        else:
            cur.move_to(tx, ty, tol=0.6)
        time.sleep(0.3)
        try:
            from shared.ingame.screenshot_win import capture_via_printwindow
            img = capture_via_printwindow(inst.proc.pid, max_width=760)
            if img:
                wd = RIG_ROOT / "watch"
                wd.mkdir(exist_ok=True)
                (wd / f"css_prelock_{inst.name}.png").write_bytes(img)
        except Exception:
            pass
        for _ in range(4):
            pad.tap("A", 0.08)
            time.sleep(0.9)
            if direct_css_selected(inst):
                for _ in range(max(0, costume)):
                    pad.tap("X", 0.06)
                    time.sleep(0.35)
                log(f"[{inst.name}] dead-reckoned a pick at ({tx},{ty})")
                return
        raise RuntimeError(f"[{inst.name}] dead-reckoning lock failed")
    for _ in range(6):
        hov = cur.hovered()
        if hov == css_index:
            break
        # Relative correction: we know where the cell we ACTUALLY landed on
        # sits in grid coords, so aim off by the same delta (robust to a
        # constant online-CSS layout offset).
        if hov is not None and 0 <= hov < len(cells):
            dx = tx - cells[hov][0]
            dy = ty - cells[hov][1]
            x, y = cur.read_pos()
            if x is not None:
                tx2, ty2 = x + dx, y + dy
                if inst.input_backend == "keys":
                    move_to_digital(cur, pad, tx2, ty2, tol=0.8)
                else:
                    cur.move_to(tx2, ty2, tol=0.6)
        elif not cells:
            # Custom css_pos on a modded layout: the mex-icon-space ->
            # cursor-space y offset varies per build (-1.5..-5.5 measured),
            # so scan vertically around the given target until the icon
            # index matches (a wrong guess lands exactly one row off).
            _scan = getattr(cur, "_nr_scan", 0)
            cur._nr_scan = _scan + 1
            ty2 = ty + (1.2 * ((_scan // 2) + 1)) * (1 if _scan % 2 else -1)
            cur.move_to(tx, ty2, tol=0.6)
        else:
            if inst.input_backend == "keys":
                move_to_digital(cur, pad, tx, ty, tol=0.8)
            else:
                cur.move_to(tx, ty, tol=0.6)
        time.sleep(0.2)
    if cur.hovered() != css_index:
        raise RuntimeError(f"[{inst.name}] CSS cursor not on {char} "
                           f"(hovered={cur.hovered()})")
    for attempt in range(4):
        if cur.hovered() != css_index:        # drifted since the check
            cur.move_to(tx, ty, tol=0.6)
            time.sleep(0.15)
            continue
        pad.tap("A", 0.08)
        time.sleep(0.5)
        if direct_css_selected(inst):         # green "Character selected"
            break
        time.sleep(0.4)
        if direct_css_selected(inst):
            break
    else:
        raise RuntimeError(f"[{inst.name}] could not verify lock on {char}")
    # Costume cycles with X only AFTER the token is placed (X before the
    # lock is a no-op -- measured: --costume-a 3 still gave default).
    for _ in range(max(0, costume)):
        pad.tap("X", 0.06)
        time.sleep(0.35)
    if costume:
        # The green dash can flicker right after a tap -- settle and
        # re-probe before declaring the lock lost (one run aborted here).
        for _ in range(6):
            if direct_css_selected(inst):
                break
            time.sleep(0.5)
        else:
            pad.tap("A", 0.08)          # re-place the token if it popped
            time.sleep(1.0)
            if not direct_css_selected(inst):
                raise RuntimeError(f"[{inst.name}] lock lost while "
                                   "cycling costume")
    log(f"[{inst.name}] selected {char} (costume {costume})")


def nav_to_direct_search(inst, char="falcon", costume=0, css_index=7,
                         css_pos=None, phase="all"):
    """From boot to 'Searching for <peer>' in Direct mode. Sequence discovered
    empirically 2026-08-25 (screenshots in the session log):
      Online-Play menu (scene 0x01, cursor on Unranked) -> down -> A ->
      Direct CSS (scene 0x08) -> pick char -> START (code entry) ->
      Z (commit auto-filled peer code) -> START (jump to CONFIRM) -> A."""
    pad = inst.pipe()
    if phase in ("all", "select"):
        inst.wait_scene_major({MENU_MAJOR}, timeout=120,
                              label="Online-Play menu")
        pad.neutral()
        select_mode_direct(inst)
        inst.wait_scene_major({ONLINE_CSS_MAJOR}, timeout=10,
                              label="Direct CSS")
        time.sleep(1.5)
        select_character_online(inst, char, costume, css_index,
                                css_pos=css_pos)
        if phase == "select":
            return
    pad.tap("START", 0.08)            # code-entry screen
    time.sleep(1.5)
    pad.tap("Z", 0.08)                # commit the auto-filled peer code
    # The Direct UI applies the autofill asynchronously. On a cold shader/
    # network run 0.8 s was short enough that START became a literal "1" in
    # the tag field, leaving one client waiting forever for an assignment.
    time.sleep(1.5)
    if os.environ.get("NETRIG_SKIP_CONFIRM_START", "") == inst.name:
        # User-corrected flow for the old core: Z autofills, START
        # confirms. Nothing else.
        pad.tap("START", 0.08)
        time.sleep(1.0)
    else:
        pad.tap("START", 0.08)        # highlight CONFIRM (vanilla flow)
        time.sleep(0.5)
        pad.tap("A", 0.08)
        time.sleep(1.0)
    log(f"[{inst.name}] confirmed peer code -- searching")


IN_MATCH_MINOR = 0x02   # scene (8,2) = live online match (measured)

STADIUM_RNG_CALL = 0x801D463C
STADIUM_CONTROLLER_GOBJ = 0x8049E6C8 + 0x180 + 2 * 4
GOBJ_USER_DATA = 0x2C
STADIUM_GROUND_STATE = 0xDC
STADIUM_GROUND_FORM = 0xDE
STADIUM_FORM_INDEX = {"fire": 0, "grass": 1, "rock": 2, "water": 3}
STADIUM_FORM_ID = {"fire": 3, "grass": 4, "rock": 6, "water": 9}


def force_stadium_form(instances, form_name):
    """Force Stadium's next form selection identically on both clients.

    This patches the not-yet-JIT-compiled ``bl HSD_Randi`` call before the
    online match loads.  It changes only the test processes and lets the real
    stage timer initiate the transformation on the same simulation frame.
    """
    index = STADIUM_FORM_INDEX[form_name]
    instruction = 0x38600000 | index  # li r3, index
    for inst in instances:
        original = inst.mem.bytes(STADIUM_RNG_CALL, 4)
        if not original or len(original) != 4:
            raise RuntimeError(
                f"[{inst.name}] could not read Stadium RNG call site")
        if not inst.mem.write_u32(STADIUM_RNG_CALL, instruction):
            raise RuntimeError(
                f"[{inst.name}] could not force Stadium {form_name}")
    log(f"[stadium] both clients will select {form_name} "
        f"(form {STADIUM_FORM_ID[form_name]})")


def stadium_form_state(inst):
    gobj = inst.mem.u32(STADIUM_CONTROLLER_GOBJ)
    ground = inst.mem.u32(gobj + GOBJ_USER_DATA) if gobj else None
    if not ground:
        return None, None
    return (inst.mem.u16(ground + STADIUM_GROUND_FORM),
            inst.mem.u16(ground + STADIUM_GROUND_STATE))


def capture_stadium_review(instances, proof_label, phase, evidence=None):
    '''Save a labeled pair of full Dolphin frames plus optional telemetry.'''
    from shared.ingame.screenshot_win import capture_via_printwindow

    if proof_label:
        safe_label = re.sub(r'[^A-Za-z0-9._-]+', '-', proof_label).strip('-')
        target = RIG_ROOT / 'watch' / 'stadium-review' / safe_label
        stem = phase
    else:
        target = RIG_ROOT / 'watch'
        stem = time.strftime(f'{phase}-%Y%m%d-%H%M%S')
    target.mkdir(parents=True, exist_ok=True)
    for inst in instances:
        img = capture_via_printwindow(inst.proc.pid, max_width=960)
        if img:
            (target / f'{stem}-{inst.name}.png').write_bytes(img)
    if evidence is not None:
        (target / f'{stem}.json').write_text(
            json.dumps(evidence, indent=2), encoding='utf-8')
    log(f'[stadium] captured {phase} review -> {target}')
    return target


def connect_flow(a, b, args):
    """Launch, navigate and matchmake both instances; returns when both are
    in the live match (scene 8,2)."""
    a.launch()
    b.launch()
    save_state([a, b])
    a.attach()
    b.attach()
    forced_form = getattr(args, "stadium_form", None)
    if forced_form:
        force_stadium_form((a, b), forced_form)
    # The two navigations are fully independent (own pad, own RAM, own
    # window) -- run them CONCURRENTLY.
    import threading
    errs = {}

    def _nav(inst, char, costume, css_override=None):
        try:
            kw = {}
            if css_override:
                x, y, idx = css_override
                kw = {"css_pos": (x, y), "css_index": idx}
            nav_to_direct_search(inst, char=char, costume=costume, **kw)
        except Exception as e:
            errs[inst.name] = e

    def _parse_css(s):
        if not s:
            return None
        x, y, idx = s.split(",")
        return (float(x), float(y), int(idx))
    if os.environ.get("NETRIG_MANUAL_B"):
        # A automates fully; B is driven interactively via probe_cmd.txt
        # (stroke/tap/shot lines; 'go' ends manual control). Screenshot
        # after every batch -> watch/probe.png.
        from shared.ingame.screenshot_win import capture_via_printwindow
        _nav(a, args.char_a, args.costume_a,
             _parse_css(getattr(args, 'css_a', None)))
        if errs:
            raise RuntimeError(f"navigation failed: {errs}")
        pad = b.pipe()
        cmd_path = RIG_ROOT / "probe_cmd.txt"
        cmd_path.unlink(missing_ok=True)
        wd = RIG_ROOT / "watch"
        wd.mkdir(exist_ok=True)
        def _shot():
            img = capture_via_printwindow(b.proc.pid, max_width=760)
            if img:
                (wd / "probe.png").write_bytes(img)
        b.wait_scene_major({MENU_MAJOR}, timeout=120, label="menu (b)")
        pad.neutral()
        select_mode_direct(b)
        b.wait_scene_major({ONLINE_CSS_MAJOR}, timeout=10, label="CSS (b)")
        time.sleep(1.5)
        _shot()
        log("MANUAL B: css ready -- commands to " + str(cmd_path))
        manual_deadline = time.time() + 600
        while time.time() < manual_deadline:
            if not cmd_path.exists():
                time.sleep(0.4)
                continue
            lines = cmd_path.read_text().strip().splitlines()
            cmd_path.unlink(missing_ok=True)
            done_manual = False
            for line in lines:
                parts = line.split()
                if not parts:
                    continue
                if parts[0] == "stroke":
                    pad.main(float(parts[1]), float(parts[2]))
                    time.sleep(float(parts[3]) / 1000.0)
                    pad.center()
                    time.sleep(0.2)
                elif parts[0] == "tap":
                    ms = float(parts[2]) / 1000.0 if len(parts) > 2 else 0.08
                    pad.tap(parts[1].upper(), ms)
                    time.sleep(0.4)
                elif parts[0] == "tilt":
                    pad.tilt(float(parts[1]), float(parts[2]), 0.1)
                    time.sleep(0.3)
                elif parts[0] == "go":
                    done_manual = True
                    break
            _shot()
            log("MANUAL B: batch applied")
            if done_manual:
                break
        log("MANUAL B: handing back to automation")
        log("both searching -- waiting for the match to start")
        deadline = time.time() + 120
        while time.time() < deadline:
            sa, sb = a.scene(), b.scene()
            if sa == (ONLINE_CSS_MAJOR, IN_MATCH_MINOR) and sb == sa:
                log("MATCH LIVE on both clients")
                time.sleep(3.0)
                return
            time.sleep(1.0)
        raise TimeoutError(f"match never started (a={a.scene()} b={b.scene()})")
    if os.environ.get("NETRIG_SEQ_NAV"):
        # Serialize SELECTION ONLY (crosstalk window); the search/code
        # phase must stay near-simultaneous or the first search expires.
        def _nav2(inst, char, costume, css_override, phase):
            kw = {"phase": phase}
            if css_override:
                x, y, idx = css_override
                kw.update(css_pos=(x, y), css_index=idx)
            try:
                nav_to_direct_search(inst, char=char, costume=costume, **kw)
            except Exception as e:
                errs[inst.name] = e
                log(f"[{inst.name}] navigation FAILED: {e!r}")
        _nav2(a, args.char_a, args.costume_a,
              _parse_css(getattr(args, 'css_a', None)), "select")
        _nav2(b, args.char_b, args.costume_b,
              _parse_css(getattr(args, 'css_b', None)), "select")
        if errs:
            raise RuntimeError(f"navigation failed: {errs}")
        t1 = threading.Thread(target=_nav2, args=(a, args.char_a,
             args.costume_a, None, "code"))
        t2 = threading.Thread(target=_nav2, args=(b, args.char_b,
             args.costume_b, None, "code"))
        t1.start(); t2.start(); t1.join(); t2.join()
        if errs:
            raise RuntimeError(f"navigation failed: {errs}")
        log("both searching -- waiting for the match to start")
        deadline = time.time() + 120
        while time.time() < deadline:
            sa, sb = a.scene(), b.scene()
            if sa == (ONLINE_CSS_MAJOR, IN_MATCH_MINOR) and sb == sa:
                log("MATCH LIVE on both clients")
                time.sleep(3.0)
                return
            time.sleep(1.0)
        raise TimeoutError(f"match never started (a={a.scene()} b={b.scene()})")
    ta = threading.Thread(target=_nav, args=(a, args.char_a, args.costume_a,
                          _parse_css(getattr(args, 'css_a', None))))
    tb = threading.Thread(target=_nav, args=(b, args.char_b, args.costume_b,
                          _parse_css(getattr(args, 'css_b', None))))
    ta.start()
    tb.start()
    ta.join()
    tb.join()
    if errs:
        raise RuntimeError(f"navigation failed: {errs}")
    log("both searching -- waiting for the match to start")
    deadline = time.time() + 120
    while time.time() < deadline:
        sa, sb = a.scene(), b.scene()
        if sa == (ONLINE_CSS_MAJOR, IN_MATCH_MINOR) and sb == sa:
            log("MATCH LIVE on both clients")
            time.sleep(3.0)  # ready-go
            return
        time.sleep(1.0)
    raise TimeoutError(f"match never started (a={a.scene()} b={b.scene()})")


def detect_my_port(inst, timeout=8.0):
    """Which in-game port this client controls: hold left briefly and see
    which player moves in THIS client's own simulation."""
    from shared.ingame.gamestate import Player
    players = [Player(inst.mem, 0), Player(inst.mem, 1)]
    before = [p.pos() for p in players]
    pad = inst.pipe()
    pad.main(0.15, 0.5)          # gentle walk left
    time.sleep(0.6)
    pad.center()
    time.sleep(0.2)
    after = [p.pos() for p in players]
    moved = []
    for i in range(2):
        if before[i] and after[i] and None not in before[i] + after[i]:
            moved.append(abs(after[i][0] - before[i][0]))
        else:
            moved.append(0.0)
    port = 0 if moved[0] >= moved[1] else 1
    log(f"[{inst.name}] controls in-game port {port + 1} "
        f"(moved {moved[0]:.2f} vs {moved[1]:.2f})")
    return port


class SyncMonitor:
    """Live desync detection: the same game simulated on both clients must
    agree. Compares percents (discrete, decisive) and positions (tolerance
    for rollback transients) and scans both dolphin.logs for Slippi's own
    desync lines."""

    SANE = 10000.0

    def __init__(self, a, b):
        from shared.ingame.gamestate import Player
        self.a, self.b = a, b
        self.pa = [Player(a.mem, 0), Player(a.mem, 1)]
        self.pb = [Player(b.mem, 0), Player(b.mem, 1)]
        self.strikes = 0
        self.desynced = False
        self.report = []
        self._last_log_scan = 0.0
        self._last_debug = 0.0
        self._last_frames = (None, None)
        self._freeze_since = None
        self._skew_logged = 0.0

    def _frames(self):
        """(frame_a, frame_b) from each client's global game-frame counter."""
        from shared.ingame.observe import FRAME_COUNTER
        try:
            return self.a.mem.u32(FRAME_COUNTER), self.b.mem.u32(FRAME_COUNTER)
        except Exception:
            return None, None

    def _frame_gate(self):
        """Wall-clock sampling across time-skewed clients false-positived (a
        4.5s-confirmed 'divergence' on stadium-15589 with byte-identical
        replays: one client's live present lagged the other's). Compare
        state only when both sims are on ~the same frame; a genuinely
        FROZEN client (counter stuck while the peer advances) is its own
        reportable event -- that's the crash symptom."""
        fa, fb = self._frames()
        if fa is None or fb is None:
            return False
        la, lb = self._last_frames
        self._last_frames = (fa, fb)
        frozen = (la is not None
                  and ((fa == la and fb - (lb or fb) > 60)
                       or (fb == lb and fa - (la or fa) > 60)))
        if frozen:
            if self._freeze_since is None:
                self._freeze_since = time.time()
            elif (time.time() - self._freeze_since > 5.0
                    and not self.desynced):
                self.desynced = True
                msg = (f"one client FROZEN (frames a={fa} b={fb}) -- "
                       "crash/hang, not input skew")
                self.report.append(msg)
                log(f"!!! DESYNC-ADJACENT: {msg}")
        else:
            self._freeze_since = None
        if abs(fa - fb) > 1:
            now = time.time()
            if now - self._skew_logged > 10.0:
                self._skew_logged = now
                log(f"[sync] clients frame-skewed (a={fa} b={fb}, "
                    f"d={fa - fb:+d}) -- comparison paused")
            return False
        return True

    def _log_hits(self, inst):
        """Tail-scan (cheap: seek near the end, never read the whole file)."""
        p = inst.user_dir / "Logs" / "dolphin.log"
        try:
            with open(p, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 40000))
                tail = f.read().decode("utf-8", errors="replace")
        except OSError:
            return []
        # The rig itself lives under ``slippi-desync-rig``; matching the
        # bare word therefore turns every ordinary replay-path log line into
        # a false alarm.  Slippi's actual diagnostics use explicit phrases.
        phrases = ("desync detected", "desynchronized", "desync on frame",
                   "desync!")
        return [ln for ln in tail.splitlines()
                if any(phrase in ln.lower() for phrase in phrases)]

    def _sample(self, player):
        """(x, y, percent, state, kind) with stale-pointer protection: re-resolve
        the fighter pointer every read and reject insane magnitudes."""
        player.resolve()
        pos = player.pos()
        pct = player.percent()
        st = player.state()
        kind = player.kind()
        if not pos or None in pos or pct is None or st is None or kind is None:
            return None
        x, y = pos
        if abs(x) > self.SANE or abs(y) > self.SANE or not (0 <= pct < 1000):
            return None
        return (x, y, pct, st, kind)

    def check(self):
        # Compare only while BOTH clients are in the live match; a client
        # dropping out of (8,2) alone is itself a reportable event.
        sa, sb = self.a.scene(), self.b.scene()
        in_a = sa == (ONLINE_CSS_MAJOR, IN_MATCH_MINOR)
        in_b = sb == (ONLINE_CSS_MAJOR, IN_MATCH_MINOR)
        if in_a != in_b and not self.desynced:
            self.desynced = True
            msg = f"one client left the match (scenes a={sa} b={sb})"
            self.report.append(msg)
            log(f"!!! DESYNC-ADJACENT: {msg}")
        if not (in_a and in_b):
            return self.desynced
        if not self._frame_gate():
            return self.desynced
        diffs = []
        samples = []
        for i in range(2):
            va, vb = self._sample(self.pa[i]), self._sample(self.pb[i])
            samples.append((va, vb))
            if va is None or vb is None:
                continue
            if abs(va[2] - vb[2]) > 0.5:
                diffs.append(f"P{i+1} percent a={va[2]:.1f} b={vb[2]:.1f}")
            if abs(va[0] - vb[0]) > 4 or abs(va[1] - vb[1]) > 4:
                diffs.append(f"P{i+1} pos a=({va[0]:.1f},{va[1]:.1f}) "
                             f"b=({vb[0]:.1f},{vb[1]:.1f})")
            if va[4] != vb[4]:
                diffs.append(f"P{i+1} kind a={va[4]} b={vb[4]}")
        now = time.time()
        if now - self._last_debug > 5.0:
            self._last_debug = now
            log("[sync] " + "  ".join(
                f"P{i+1} a={va and (round(va[0],1), round(va[2],1))} "
                f"b={vb and (round(vb[0],1), round(vb[2],1))}"
                for i, (va, vb) in enumerate(samples)))
        if diffs:
            self.strikes += 1
            if self.strikes >= 3 and not self.desynced:
                # A real desync NEVER heals -- rollback transients during
                # hectic frames do, but under a heavy build (Animelee CE) a
                # prediction window survived a single 1s confirmation and
                # false-positived. Demand the divergence outlive THREE
                # confirmation samples spaced 1.5s (a real desync is
                # permanent, so the extra 4.5s costs nothing).
                confirm = None
                for _ in range(3):
                    time.sleep(1.5)
                    if not self._frame_gate():
                        # skewed sample proves nothing either way -- a real
                        # desync will keep striking on aligned samples
                        confirm = None
                        break
                    confirm = []
                    for i in range(2):
                        va = self._sample(self.pa[i])
                        vb = self._sample(self.pb[i])
                        if va is None or vb is None:
                            continue
                        if (abs(va[2] - vb[2]) > 0.5 or abs(va[0] - vb[0]) > 4
                                or abs(va[1] - vb[1]) > 4):
                            confirm.append(
                                f"P{i+1} a=({va[0]:.1f},{va[2]:.1f}%) "
                                f"b=({vb[0]:.1f},{vb[2]:.1f}%)")
                    if not confirm:
                        break
                if confirm:
                    self.desynced = True
                    self.report = list(diffs) + ["confirmed: " + "; ".join(confirm)]
                    log("!!! DESYNC (state divergence persisted + confirmed): "
                        + "; ".join(confirm))
                else:
                    log("[sync] transient divergence healed -- not a desync "
                        f"({'; '.join(diffs)})")
                    self.strikes = 0
        else:
            self.strikes = 0
        if now - self._last_log_scan > 3.0:   # keep disk churn off the clients
            self._last_log_scan = now
            for inst in (self.a, self.b):
                for ln in self._log_hits(inst):
                    if ln not in self.report:
                        self.report.append(ln)
                        self.desynced = True
                        log(f"!!! DESYNC ({inst.name} dolphin.log): {ln.strip()}")
        return self.desynced


def shepherd_target(bme, bpad):
    """The TARGET always returns to CENTER STAGE, ground level: recover if
    knocked off, drop through platforms, walk to x=0, stand there and get
    grabbed. Driven from B's OWN simulation (that's what B's inputs act on)."""
    bmp = bme.pos()
    if not bmp or None in bmp:
        return
    if bme.airborne() and bmp[1] < -8:          # knocked off: recover
        bpad.main(0.9 if bmp[0] < 0 else 0.1, 0.5)
        bpad.tap("Y", 0.09)
        time.sleep(0.05)
        return
    if bmp[1] > 8 and not bme.airborne():       # parked on a platform: drop
        bpad.main(0.5, 0.0)
        time.sleep(0.12)
        bpad.center()
        return
    if abs(bmp[0]) > 8:                         # walk home to center stage
        bpad.main(0.68 if bmp[0] < 0 else 0.32, 0.5)
    else:
        bpad.center()                           # stand still, accept the grab


def walk_to_stadium_water_edges(a, b, port_a, monitor=None, proof_label=None):
    """Walk both players to opposite water-form edges and capture the proof."""
    from shared.ingame.gamestate import Player

    centre_evidence = {'stadium': {}}
    for inst in (a, b):
        form, state = stadium_form_state(inst)
        centre_evidence['stadium'][inst.name] = {
            'form': form, 'state': state}
    capture_stadium_review(
        (a, b), proof_label, 'water-center', centre_evidence)

    actors = [
        ("a", Player(a.mem, port_a), a.pipe(), -60.0),
        ("b", Player(b.mem, 1 - port_a), b.pipe(), 60.0),
    ]
    reached = {"a": False, "b": False}
    deadline = time.time() + 14.0
    while time.time() < deadline and not all(reached.values()):
        if monitor and monitor.check():
            raise RuntimeError("desync flagged during Stadium edge walk")
        for name, player, pad, target in actors:
            if reached[name]:
                pad.center()
                continue
            player.resolve()
            snap = player.snapshot()
            x = snap.get("x")
            grounded = snap.get("airborne") is False
            if x is not None and grounded and (
                    x <= target if target < 0 else x >= target):
                reached[name] = True
                pad.center()
            else:
                pad.main(0.20 if target < 0 else 0.80, 0.50)
        time.sleep(0.08)

    for _, _, pad, _ in actors:
        pad.neutral()
    time.sleep(1.0)

    evidence = {"reached": reached, "players": {}, "stadium": {}}
    for name, player, _, _ in actors:
        player.resolve()
        evidence["players"][name] = player.snapshot()
    for inst in (a, b):
        form, state = stadium_form_state(inst)
        evidence["stadium"][inst.name] = {"form": form, "state": state}

    target = capture_stadium_review(
        (a, b), proof_label, 'water-edge', evidence)
    log(f"[stadium] water-edge proof {evidence['players']} -> {target}")

    expected = STADIUM_FORM_ID["water"]
    forms_ok = all(item["form"] == expected
                   for item in evidence["stadium"].values())
    if not all(reached.values()) or not forms_ok:
        raise RuntimeError(f"Stadium water-edge proof failed: {evidence}")
    return evidence


def dthrow_loop(a, b, port_a, throws=10, monitor=None, inject_after=None,
                min_seconds=None, moves=("dthrow",), edge_walk=False,
                edge_walk_at=85.0, proof_label=None, stadium_form=None):
    """A chases B's character and grab->dthrows it repeatedly; B cooperates
    (shepherd_target). Closed-loop on each client's own simulation. If
    inject_after is set, a one-sided state poke fires after that many throws
    WHILE the match is live, so the monitor gets a fair shot at catching it.
    min_seconds keeps the match alive past the throw quota (Pokemon Stadium
    desyncs happen at TRANSFORMATIONS ~1min in -- a 40s match proves nothing)."""
    from shared.ingame.gamestate import Player
    me = Player(a.mem, port_a)
    me_on_b = Player(b.mem, port_a)  # same network player in B's simulation
    foe = Player(a.mem, 1 - port_a)
    bme = Player(b.mem, 1 - port_a)   # B's own character, in B's sim
    pad = a.pipe()
    bpad = b.pipe()
    done = 0
    injected = False
    edge_walk_done = False
    form_capture_done = False
    t0 = time.time()
    deadline = t0 + max(180, (min_seconds or 0) + 90)
    grabbed_states = set(range(0xDF, 0xE9))  # ftCommon capture* attacker/victim
    ledge_states = set(range(0xFC, 0x108))   # CliffCatch..Cliff* actions
    last_x, stuck_since = None, time.time()

    def trainer_ring_state(player):
        """Compact transform/input evidence for a Pokemon Trainer port."""
        d = player.d
        base = 0x80453080 + player.port * 0xE90
        active = d.u8(base + 0x0C)
        idle = d.u8(base + 0x0D)
        entities = []
        for physical in (0, 1):
            gobj = d.u32(base + 0xB0 + 4 * physical)
            ft = d.u32(gobj + 0x2C) if gobj else 0
            entities.append({
                "physical": physical,
                "gobj": f"0x{gobj:08X}" if gobj else None,
                "ft": f"0x{ft:08X}" if ft else None,
                "kind": d.u32(ft + 0x04) if ft else None,
                "state": d.u32(ft + 0x10) if ft else None,
                "pad": d.u8(ft + 0x618) if ft else None,
                "held": f"0x{d.u32(ft + 0x65C):08X}" if ft else None,
                "down": f"0x{d.u32(ft + 0x668):08X}" if ft else None,
                "timer_lw": d.u8(ft + 0x687) if ft else None,
                "flags_221d": f"0x{d.u8(ft + 0x221D):02X}" if ft else None,
                "flags_221f": f"0x{d.u8(ft + 0x221F):02X}" if ft else None,
                "var_c": f"0x{d.u32(ft + 0x22F0):08X}" if ft else None,
                "var_b": d.u32(ft + 0x22F4) if ft else None,
                "var_a": d.u32(ft + 0x22F8) if ft else None,
            })
        return {"active": active, "idle": idle, "entities": entities}

    while ((done < throws or (min_seconds and time.time() - t0 < min_seconds))
           and time.time() < deadline):
        if monitor and monitor.check():
            log("stopping choreography -- desync flagged")
            break
        if a.scene() != (ONLINE_CSS_MAJOR, IN_MATCH_MINOR):
            log("[choreo] match ended (scene left 8,2) -- stopping")
            break
        if inject_after is not None and done >= inject_after and not injected:
            injected = True
            pb = Player(b.mem, port_a)
            pb.resolve()
            ok = pb.set_percent(142.0)
            log(f"[inject] MID-MATCH set_percent(142) on B's copy of A's "
                f"char -> write_ok={ok}; b reads {pb.percent()}")
        me.resolve(); foe.resolve(); bme.resolve()
        if (proof_label and stadium_form and not form_capture_done
                and time.time() - t0 >= edge_walk_at):
            forms = [stadium_form_state(inst) for inst in (a, b)]
            expected = STADIUM_FORM_ID[stadium_form]
            if all(form == expected and state == 0 for form, state in forms):
                evidence = {"stadium": {
                    inst.name: {"form": form, "state": state}
                    for inst, (form, state) in zip((a, b), forms)
                }}
                capture_stadium_review(
                    (a, b), proof_label, f'{stadium_form}-center', evidence)
                form_capture_done = True
        if edge_walk and not edge_walk_done \
                and time.time() - t0 >= edge_walk_at:
            forms = [stadium_form_state(inst) for inst in (a, b)]
            water = STADIUM_FORM_ID["water"]
            if all(form == water and state == 0 for form, state in forms):
                walk_to_stadium_water_edges(
                    a, b, port_a, monitor=monitor, proof_label=proof_label)
                edge_walk_done = True
                me.resolve(); foe.resolve(); bme.resolve()
                continue
        shepherd_target(bme, bpad)
        mp, fp = me.pos(), foe.pos()
        st = me.state()
        if not mp or not fp or None in mp + fp:
            time.sleep(0.1)
            continue
        # Self-preservation first: airborne below stage level -> recover
        # toward center (drift, double jump, up-B). Never chase into the blast
        # zone again (run 3: the rig 4-stocked itself doing exactly that).
        if me.airborne() and mp[1] < -8:
            pad.main(0.9 if mp[0] < 0 else 0.1, 0.5)
            pad.tap("Y", 0.09)
            time.sleep(0.25)
            if (me.pos() or (0, 0))[1] < -20:
                pad.main(0.5, 1.0)
                pad.tap("B", 0.1)          # up-B
                time.sleep(0.9)
            pad.center()
            continue
        # A foe BELOW stage level is not approachable (that's how the rig
        # 4-stocked itself); a GROUNDED foe is always approachable no matter
        # the x (stage widths vary -- x=60 is on-stage on Dreamland). Camp
        # toward their x, clamped to center-ish, until they come back up.
        if fp[1] < -8:
            safe_x = max(-35.0, min(35.0, fp[0]))
            ddx = safe_x - mp[0]
            if abs(ddx) > 6:
                pad.main(0.72 if ddx > 0 else 0.28, 0.5)
                time.sleep(0.06)
            else:
                pad.center()
                time.sleep(0.2)
            continue
        # Hanging on the ledge: release with down, then jump back toward
        # center stage.
        if st in ledge_states:
            pad.main(0.5, 0.0); time.sleep(0.12)     # release
            pad.center(); time.sleep(0.25)
            toward = 1.0 if mp[0] < 0 else 0.0
            pad.main(toward, 0.5)
            pad.tap("Y", 0.08); time.sleep(0.25)
            pad.tap("Y", 0.08)                       # double jump in
            time.sleep(0.5)
            pad.center()
            continue
        dx, dy = fp[0] - mp[0], fp[1] - mp[1]
        # Anti-stuck: no x progress for 3s while not adjacent -> hop.
        if last_x is not None and abs(mp[0] - last_x) > 2:
            stuck_since = time.time()
        last_x = mp[0]
        if time.time() - stuck_since > 3.0 and abs(dx) > 6:
            pad.main(1.0 if dx > 0 else 0.0, 0.5)
            pad.tap("Y", 0.08)
            time.sleep(0.6)
            pad.center()
            stuck_since = time.time()
            continue
        if abs(dx) <= 12 and dy > 8:
            # Foe is on a platform above. STOP first -- a jump inherits ground
            # momentum, and dashing into a full hop sails clean past the
            # platform -- then neutral hop and drift gently sideways.
            pad.center()
            time.sleep(0.28)                          # kill momentum
            pad.tap("Y", 0.09)                        # neutral full hop
            time.sleep(0.15)
            pad.main(0.68 if dx > 0 else 0.32, 0.5)   # gentle drift
            time.sleep(0.35)
            pad.center()
            time.sleep(0.3)                           # land on the platform
            continue
        if abs(dx) <= 12 and dy < -8:
            # Foe below: drop through the platform (smash down).
            pad.main(0.5, 0.0)
            time.sleep(0.12)
            pad.center()
            time.sleep(0.45)
            continue
        if abs(dx) > 28:
            pad.main(1.0 if dx > 0 else 0.0, 0.5)   # dash when far
            time.sleep(0.08)
            continue
        if abs(dx) > 10:
            pad.main(0.72 if dx > 0 else 0.28, 0.5)  # walk when close
            time.sleep(0.06)
            continue
        pad.center()
        time.sleep(0.18)                            # settle momentum
        mp, fp = me.pos(), foe.pos()
        if mp and fp and None not in mp + fp and abs(fp[0] - mp[0]) > 13:
            continue                                # overshot -- re-approach
        if fp and mp and abs(fp[1] - mp[1]) > 8:
            continue                                # different storey -- climb
        move = moves[done % len(moves)]
        if move == "swap":
            before = me.kind()
            expected = {27: 28, 28: 29, 29: 27}.get(before)
            if expected is None:
                raise RuntimeError(
                    f"swap choreography requires Pokemon Trainer kind, got {before}")
            log(f"[choreo] swap input {before}->{expected}: "
                f"a={trainer_ring_state(me)} "
                f"b={trainer_ring_state(me_on_b)}")
            # Down-B: hold down while B transitions from up to down, then
            # release both.  Wait for the engine's 14-frame swap callback and
            # require both simulations to expose the destination fighter.
            pad.main(0.5, 0.0)
            time.sleep(0.08)
            pad.tap("B", 0.08)
            time.sleep(0.35)
            pad.center()
            swap_deadline = time.time() + 3.0
            kinds = (None, None)
            while time.time() < swap_deadline:
                if monitor and monitor.check():
                    break
                me.resolve()
                me_on_b.resolve()
                kinds = (me.kind(), me_on_b.kind())
                if kinds == (expected, expected):
                    break
                time.sleep(0.08)
            if kinds != (expected, expected):
                log(f"[choreo] failed swap state: a={trainer_ring_state(me)} "
                    f"b={trainer_ring_state(me_on_b)}")
                raise RuntimeError(
                    f"Pokemon Change {before}->{expected} failed or diverged: "
                    f"client kinds={kinds}")
            done += 1
            log(f"[choreo] swap #{done}: {before}->{expected} on both clients "
                f"at t+{time.time() - t0:.0f}s")
            # Each arriving form enforces a 24-emulated-frame cooldown. Wall
            # time is not equivalent while Direct is catching up/rolling back,
            # so wait on the replicated fighter counter on both simulations.
            cooldown_deadline = time.time() + 5.0
            ages = (None, None)
            while time.time() < cooldown_deadline:
                me.resolve()
                me_on_b.resolve()
                ages = (me.d.u32(me.ft + 0x22F8) if me.ft else None,
                        me_on_b.d.u32(me_on_b.ft + 0x22F8)
                        if me_on_b.ft else None)
                if all(age is not None and age >= 24 for age in ages):
                    break
                if monitor and monitor.check():
                    break
                time.sleep(0.08)
            if not all(age is not None and age >= 24 for age in ages):
                raise RuntimeError(
                    f"Pokemon Change cooldown did not advance on both clients: "
                    f"ages={ages}")
            continue
        if move == "upb":
            # Falcon Dive: a COMMAND GRAB, same victim-ride mechanism as
            # throws (user saw the OSD on up-B too). Must actually CONNECT
            # to test the grab boundary (straight-up dives from 10 units
            # away just whiff -- user-observed). Walk to point blank, then
            # dive ANGLED TOWARD the foe. Center-ish only, so the helpless
            # fall lands on stage.
            if abs(mp[0]) > 40:
                move = "dthrow"                     # too near an edge
            else:
                for _ in range(10):                 # close to point blank
                    mp2, fp2 = me.pos(), foe.pos()
                    if not mp2 or not fp2 or None in mp2 + fp2:
                        break
                    ddx = fp2[0] - mp2[0]
                    if abs(ddx) <= 5:
                        break
                    pad.main(0.72 if ddx > 0 else 0.28, 0.5)
                    time.sleep(0.08)
                pad.center()
                time.sleep(0.15)
                fp2 = foe.pos()
                mp2 = me.pos()
                toward = 0.72 if (fp2 and mp2 and fp2[0] >= mp2[0]) else 0.28
                pad.main(toward, 1.0)               # up-forward
                pad.tap("B", 0.1)
                time.sleep(1.6)                     # dive + flip/fall
                pad.center()
                done += 1
                log(f"[choreo] up-B #{done} at t+{time.time() - t0:.0f}s")
                time.sleep(1.2)
                continue
        pad.tap("Z", 0.06)                          # grab
        time.sleep(0.35)
        fs = foe.state()
        if fs in grabbed_states:
            if move == "uthrow":
                pad.main(0.5, 1.0)                  # uthrow
            else:
                pad.main(0.5, 0.0)                  # dthrow
            time.sleep(0.15)
            pad.center()
            done += 1
            log(f"[choreo] {move} #{done} at t+{time.time() - t0:.0f}s "
                f"(foe state {hex(fs) if fs else fs})")
            time.sleep(1.4)                          # let them land
        else:
            time.sleep(0.25)
    pad.neutral()
    bpad.neutral()
    if edge_walk and not edge_walk_done:
        forms = [stadium_form_state(inst) for inst in (a, b)]
        raise RuntimeError(
            f"water edge walk never ran (forms/states={forms})")
    if proof_label and stadium_form and not form_capture_done:
        forms = [stadium_form_state(inst) for inst in (a, b)]
        raise RuntimeError(
            f"{stadium_form} form screenshot never ran (forms/states={forms})")
    return done


def lras_quit(inst):
    """End the match NOW. All four inputs must land in the SAME report --
    trickled presses read as a pause (measured). Fire the combo twice with a
    beat between, which also covers the already-paused case."""
    pad = inst.pipe()
    combo = ["L", "R", "A", "START"]
    for _ in range(2):
        if hasattr(pad, "press_many"):
            pad.press_many(combo)
            time.sleep(1.2)
            pad.release_many(combo)
        else:
            for btn in combo:
                pad.press(btn)
            time.sleep(1.2)
            pad.neutral()
        time.sleep(0.6)
    log(f"[{inst.name}] LRAS quit sent")


class Watchdog:
    """Rolling eyes on both clients: every `period` seconds save
    watch/latest-<name>.png + a state line, and if the current phase blows
    its time budget, scream and keep a stall screenshot. The 'it is just
    sitting there and nothing notices' killer."""

    def __init__(self, instances, period=5.0):
        import threading
        self.instances = instances
        self.period = period
        self.dir = RIG_ROOT / "watch"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.phase = "startup"
        self.deadline = time.time() + 120
        self._alerted = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def set_phase(self, name, budget_s):
        self.phase = name
        self.deadline = time.time() + budget_s
        self._alerted = False

    def _snap(self, inst, prefix="latest"):
        try:
            from shared.ingame.screenshot_win import capture_via_printwindow
            if inst.proc and inst.proc.poll() is None:
                img = capture_via_printwindow(inst.proc.pid, max_width=640)
                if img:
                    (self.dir / f"{prefix}-{inst.name}.png").write_bytes(img)
        except Exception:
            pass

    def _run(self):
        while not self._stop.is_set():
            lines = []
            for inst in self.instances:
                self._snap(inst)
                lines.append(f"{inst.name}={inst.scene()}")
            overdue = time.time() > self.deadline
            if overdue and not self._alerted:
                self._alerted = True
                ts = time.strftime("%H%M%S")
                for inst in self.instances:
                    self._snap(inst, prefix=f"stall-{ts}")
                log(f"[watchdog] STALL: phase '{self.phase}' over budget "
                    f"({'  '.join(lines)}) -- see {self.dir}\\stall-{ts}-*.png")
            try:
                (self.dir / "state.log").open("a").write(
                    f"{time.strftime('%H:%M:%S')} phase={self.phase} "
                    f"{'  '.join(lines)}{' OVERDUE' if overdue else ''}\n")
            except OSError:
                pass
            self._stop.wait(self.period)

    def stop(self):
        self._stop.set()


POSTGAME_MINOR = 0x00       # back at the Direct CSS after a game
STAGE_SELECT_MINOR = 0x01   # the loser/quitter's stage-select scene


def _online_stage_cursor(a):
    """StageCursor with its scene gates retargeted to the ONLINE rematch SSS
    (scene 8,1). The stage pick MUST go through the real cursor + A press:
    a force_stage_id memory write starts the game only LOCALLY (measured --
    the opponent never receives the pick and stays on the CSS)."""
    from shared.ingame.melee_sss import StageCursor

    class OnlineStageCursor(StageCursor):
        def on_stage_select(self):
            return (self.d.u8(SCENE_MAJOR) == ONLINE_CSS_MAJOR
                    and self.d.u8(SCENE_MINOR) == STAGE_SELECT_MINOR)

        def ensure_stage_select(self):
            return self.on_stage_select()

    return OnlineStageCursor(a.mem, a.pipe())


def rematch_to_stage(a, b, stage_name, watchdog=None):
    """The IN-SESSION reroll (no relaunching): LRAS -> both back at the CSS ->
    quitter presses START -> loser's stage select appears -> cursor-select the
    stage (real button presses, so the pick is transmitted) -> rematch."""
    if watchdog:
        watchdog.set_phase("rematch", 90)
    lras_quit(a)
    deadline = time.time() + 25
    while time.time() < deadline:
        if (a.scene() == (ONLINE_CSS_MAJOR, POSTGAME_MINOR)
                and b.scene() == (ONLINE_CSS_MAJOR, POSTGAME_MINOR)):
            break
        time.sleep(0.5)
    else:
        raise TimeoutError(f"post-game CSS never appeared "
                           f"(a={a.scene()} b={b.scene()})")
    time.sleep(1.5)
    # BOTH clients must press START after the match ends -- the WINNER too
    # (user-corrected: the first in-anger reroll had A pick Stadium on the
    # SSS and then wait forever because B never STARTed off its post-game
    # screen). B first, a few taps with beats between.
    for _ in range(3):
        b.pipe().tap("START", 0.1)
        time.sleep(1.0)
    # Re-lock safety: the cursor retains the previous character; if the
    # green status dash is missing, a bare A press re-locks it.
    for inst in (b, a):
        if direct_css_selected(inst):
            continue
        for _ in range(3):
            inst.pipe().tap("A", 0.08)
            time.sleep(1.2)
            if direct_css_selected(inst):
                break
        else:
            raise TimeoutError(f"[{inst.name}] could not re-lock character "
                               "on the rematch CSS")
        log(f"[rematch] {inst.name} re-locked its character")
    for _ in range(6):                       # quitter advances to stage select
        a.pipe().tap("START", 0.1)
        t = time.time() + 4.0
        while time.time() < t:
            if a.scene() == (ONLINE_CSS_MAJOR, STAGE_SELECT_MINOR):
                break
            time.sleep(0.2)
        if a.scene() == (ONLINE_CSS_MAJOR, STAGE_SELECT_MINOR):
            break
    else:
        raise TimeoutError("stage select never appeared after START")
    from shared.ingame.melee_sss import STAGE_ID
    log(f"[rematch] on the stage select -- cursor-selecting {stage_name}")
    sc = _online_stage_cursor(a)
    if not sc.select_by_id(STAGE_ID[stage_name], press=True, pages=1):
        raise RuntimeError(f"could not cursor-select {stage_name} on the "
                           "rematch stage select")
    deadline = time.time() + 30
    while time.time() < deadline:
        if (a.scene() == (ONLINE_CSS_MAJOR, IN_MATCH_MINOR)
                and b.scene() == (ONLINE_CSS_MAJOR, IN_MATCH_MINOR)):
            log("[rematch] MATCH LIVE on the forced stage")
            time.sleep(3.0)
            return
        time.sleep(0.5)
    raise TimeoutError(f"rematch never started (a={a.scene()} b={b.scene()})")


def classify_game_end(ra, rb, we_played):
    """THE headline desync signal: the game itself ending the match. A desync
    (or an idle timeout) terminates as NO_CONTEST where EACH client blames the
    OTHER for the LRAS; a genuine quit names the same initiator in both
    replays. `we_played` disambiguates desync from idle-timeout."""
    try:
        from peppi_py import read_slippi
        ea = read_slippi(str(ra)).end
        eb = read_slippi(str(rb)).end
    except Exception as e:
        return None, f"(end-parse failed: {e})"
    if ea is None or eb is None:
        return None, "(no end events)"
    try:
        nframes = len(read_slippi(str(ra)).frames.id)
    except Exception:
        nframes = None
    def is_nc(m):
        # peppi may hand back the enum name OR the raw byte (7 = No Contest;
        # the raw form silently defeated the check and buried a real desync
        # -- the Casshern run ended 10s in with mutual blame, verdict CLEAN).
        return "NO_CONTEST" in str(m).upper() or str(m).strip() == "7"

    both_nc = is_nc(ea.method) and is_nc(eb.method)
    mutual_blame = str(ea.lras_initiator) != str(eb.lras_initiator)
    if both_nc and mutual_blame:
        # Idle timeout needs ~3 MINUTES of nothing; a short match that ends
        # in mutual blame can only be a desync (the Casshern raw-install
        # died 6s in with 0 throws and the old we_played gate called it
        # CLEAN -- duration disambiguates, not throw count).
        short = nframes is not None and nframes < 7200
        if we_played or short:
            return True, ("GAME-DECLARED DESYNC: No Contest with mutual LRAS "
                          f"blame ({'active play' if we_played else 'match died at'} "
                          f"{nframes} frames)")
        return None, ("mutual-blame No Contest on an idle match "
                      "(desync OR idle timeout -- check slpdiff)")
    return False, f"(end: {ea.method}, initiator a={ea.lras_initiator} b={eb.lras_initiator})"


def newest_slp(replay_dir):
    slps = sorted(Path(replay_dir).rglob("*.slp"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    return slps[0] if slps else None


# External (.slp Game Start) stage ids for the legal six.
EXTERNAL_STAGE = {2: "fountainofdreams", 3: "pokemonstadium",
                  8: "yoshisstory", 28: "dreamland", 31: "battlefield",
                  32: "finaldestination"}
STAGE_BY_NAME = {v: k for k, v in EXTERNAL_STAGE.items()}


def stage_from_slp(replay_dir, newer_than, timeout=20.0):
    """Read the stage id straight from the GROWING .slp's Game Start block --
    the reliable source (the old RAM address reads 0 online)."""
    import struct as _st
    deadline = time.time() + timeout
    while time.time() < deadline:
        p = newest_slp(replay_dir)
        if p and p.stat().st_mtime >= newer_than - 5:
            try:
                raw = p.read_bytes()[:4096]
                p35 = raw.find(b"\x35")
                if p35 >= 0:
                    gs = p35 + 1 + raw[p35 + 1]
                    if raw[gs] == 0x36:
                        sid = _st.unpack(">H", raw[gs + 5 + 0xE:
                                                   gs + 5 + 0x10])[0]
                        return sid, EXTERNAL_STAGE.get(sid)
            except OSError:
                pass
        time.sleep(1.0)
    return None, None


def cmd_play(args):
    a, b = build_instances(Path(args.iso_a), Path(args.iso_b),
                           dump=getattr(args, "dump", False))
    log(f"A = {a.user_json().get('displayName')} {a.connect_code()} | "
        f"B = {b.user_json().get('displayName')} {b.connect_code()}")
    want = getattr(args, "require_stage", None)
    wd = None
    with dolphin_lock.hold("netrig play (two instances)", wait=60):
        try:
            needs_connect = True
            for attempt in range(1, getattr(args, "max_attempts", 8) + 1):
                t0 = time.time()
                if needs_connect:
                    if wd:
                        wd.set_phase("connect", 180)
                    connect_flow(a, b, args)
                    if wd is None:
                        wd = Watchdog([a, b])
                    needs_connect = False
                sid, sname = stage_from_slp(a.replay_dir, t0)
                log(f"stage this match: {sname or f'unknown (id={sid})'}")
                # Verify the characters actually locked (a mis-lock once
                # shipped Young Link while reporting Falcon).
                from shared.ingame.gamestate import Player
                # An online rematch can report scene (8,2) a few seconds
                # before its fighter objects are installed.  Starting the
                # proof timer in that gap produces an empty match and makes
                # every later sample unreadable.  Gate on both fighter
                # objects, then reconnect cleanly if the rematch never
                # finishes materializing.
                kinds = [None, None]
                fighter_deadline = time.time() + 12.0
                while time.time() < fighter_deadline:
                    kinds = [Player(a.mem, i).kind() for i in (0, 1)]
                    if all(kind is not None for kind in kinds):
                        break
                    time.sleep(0.5)
                log(f"character kinds this match: {kinds}")
                if any(kind is None for kind in kinds):
                    log("[chars] fighter objects never appeared -- full "
                        "reconnect")
                    a.terminate()
                    b.terminate()
                    time.sleep(2.0)
                    needs_connect = True
                    continue
                wrong_chars = (args.char_a == "falcon"
                               and args.char_b == "falcon"
                               and kinds != [2, 2])
                if wrong_chars:
                    # Rematching keeps the locked characters -- only a full
                    # reconnect fixes a mis-lock.
                    log("[chars] wrong character locked -- full reconnect")
                    lras_quit(a)
                    time.sleep(4.0)
                    a.terminate()
                    b.terminate()
                    time.sleep(2.0)
                    needs_connect = True
                    continue
                if want and sname is None:
                    log("[stage] could not read stage id -- proceeding anyway")
                if want and sname is not None and sname != want:
                    if getattr(args, "full_reconnect_reroll", False):
                        log(f"[stage] want {want}, got {sname} -- full "
                            f"reconnect reroll (attempt {attempt})")
                        a.terminate()
                        b.terminate()
                        time.sleep(2.0)
                        needs_connect = True
                        continue
                    log(f"[stage] want {want}, got {sname} -- in-session "
                        f"reroll (attempt {attempt})")
                    try:
                        rematch_to_stage(a, b, want, watchdog=wd)
                    except (TimeoutError, RuntimeError) as e:
                        # A botched rematch must not kill the run -- fall
                        # back to a full reconnect (fresh roll).
                        log(f"[rematch] failed ({e}) -- full reconnect")
                        a.terminate()
                        b.terminate()
                        time.sleep(2.0)
                        needs_connect = True
                    continue   # re-read the stage from the NEW replay
                break
            else:
                raise RuntimeError(f"never rolled stage {want}")
            min_s = getattr(args, "min_seconds", None)
            if wd:
                wd.set_phase("choreography", max(300, (min_s or 0) + 120))
            port_a = detect_my_port(a)
            mon = SyncMonitor(a, b)
            proof_label = getattr(args, "proof_label", None)
            if proof_label:
                normal_evidence = {"stadium": {}}
                for inst in (a, b):
                    form, state = stadium_form_state(inst)
                    normal_evidence["stadium"][inst.name] = {
                        "form": form, "state": state}
                time.sleep(1.0)
                capture_stadium_review(
                    (a, b), proof_label, "normal", normal_evidence)
            mv = tuple((getattr(args, 'moves', None) or 'dthrow').split(','))
            n = dthrow_loop(a, b, port_a, throws=args.throws, monitor=mon,
                            inject_after=2 if args.inject_desync else None,
                            min_seconds=min_s, moves=mv,
                            edge_walk=getattr(args, "edge_walk", False),
                            edge_walk_at=getattr(args, "edge_walk_at", 85.0),
                            proof_label=proof_label,
                            stadium_form=getattr(args, "stadium_form", None))
            log(f"choreography done: {n} dthrows landed")
            if wd:
                wd.set_phase("wind-down", 120)
            for _ in range(6):   # settle + final sync sweep
                mon.check()
                time.sleep(1.0)
            lras_quit(a)
            # Let the match end fully and Slippi FINALIZE both .slp files
            # (terminating during the end sequence leaves truncated replays
            # that peppi cannot read).
            deadline = time.time() + 30
            while time.time() < deadline:
                if (a.scene() != (ONLINE_CSS_MAJOR, IN_MATCH_MINOR)
                        and b.scene() != (ONLINE_CSS_MAJOR, IN_MATCH_MINOR)):
                    break
                time.sleep(1.0)
            ra, rb = newest_slp(a.replay_dir), newest_slp(b.replay_dir)
            for path in (ra, rb):
                if not path:
                    continue
                last, still = -1, 0
                deadline = time.time() + 30
                while time.time() < deadline and still < 3:
                    size = path.stat().st_size
                    still = still + 1 if size == last else 0
                    last = size
                    time.sleep(1.0)
        finally:
            if wd:
                wd.stop()
            a.terminate()
            b.terminate()
            if getattr(args, "dump", False):
                tag = time.strftime("%Y%m%d-%H%M%S")
                for inst in (a, b):
                    for p in inst.collect_dumps(tag):
                        log(f"framedump: {p}")
            STATE_PATH.unlink(missing_ok=True)
        # Verdict AFTER the graceful close -- the replays only finish flushing
        # once Dolphin exits, and classify_game_end needs finalized files.
        ra = newest_slp(a.replay_dir)
        rb = newest_slp(b.replay_dir)
        game_says, why = (None, "(replays missing)")
        if ra and rb:
            game_says, why = classify_game_end(ra, rb,
                                               we_played=locals().get("n", 0) > 0)
        mon_flag = locals().get("mon") and mon.desynced
        verdict = "DESYNC" if (mon_flag or game_says) else "CLEAN"
        log(f"=== VERDICT: {verdict} ===")
        log(f"  game end: {why}")
        if locals().get("mon"):
            for ln in mon.report:
                log(f"  {ln}")
        log(f"replay a: {ra}")
        log(f"replay b: {rb}")
        log("forensics: python devtools/slpdiff.py <a> <b>")


def cmd_cssprobe(args):
    """Interactive CSS steering for builds whose cursor RAM is unreadable:
    boot ONLY instance A to the Direct CSS, then poll rig-root
    `probe_cmd.txt` for commands, screenshotting after each into
    watch/probe.png. Commands (one per line):
        stroke SX SY MS   -- hold main stick (SX,SY floats) for MS ms
        tap BTN [MS]      -- tap a button (A/B/X/START/Z)
        shot              -- just screenshot
        done              -- terminate
    The full stroke sequence you converge on = the NETRIG_CSS_STROKES
    recipe for a real play run (glove spawn is boot-reproducible)."""
    from shared.ingame.screenshot_win import capture_via_printwindow
    exe = RIG_ROOT / "instance-a" / "Slippi Dolphin.exe"
    base = _xinput_connected_count()
    a = RigInstance("a", RIG_ROOT / "instance-a" / "User", exe,
                    Path(args.iso_a), pipe_index=1, netplay_port=2627,
                    spectator_port=51442, input_backend="xpad",
                    xinput_index=base)
    a.patch_configs()
    # Pad must exist BEFORE Dolphin launches (no XInput hotplug) -- the
    # missing pre-create left the probe input-dead on its first attempts.
    a._pipe = XPad()
    log(f"virtual pad created (XInput slot {base})")
    cmd_path = RIG_ROOT / "probe_cmd.txt"
    cmd_path.unlink(missing_ok=True)
    wd = RIG_ROOT / "watch"
    wd.mkdir(exist_ok=True)

    def shot(tag="probe"):
        img = capture_via_printwindow(a.proc.pid, max_width=760)
        if img:
            (wd / f"{tag}.png").write_bytes(img)
            log(f"screenshot -> watch/{tag}.png")

    with dolphin_lock.hold("netrig cssprobe", wait=60):
        a.launch()
        a.attach()
        pad = a.pipe()
        a.wait_scene_major({MENU_MAJOR}, timeout=120, label="Online-Play menu")
        pad.neutral()
        select_mode_direct(a)
        a.wait_scene_major({ONLINE_CSS_MAJOR}, timeout=10, label="Direct CSS")
        time.sleep(1.5)
        shot()
        log("CSS ready -- write commands to " + str(cmd_path))
        try:
            while True:
                if not cmd_path.exists():
                    time.sleep(0.4)
                    continue
                lines = cmd_path.read_text().strip().splitlines()
                cmd_path.unlink(missing_ok=True)
                stop = False
                for line in lines:
                    parts = line.split()
                    if not parts:
                        continue
                    if parts[0] == "stroke":
                        sx, sy, ms = float(parts[1]), float(parts[2]), float(parts[3])
                        pad.main(sx, sy)
                        time.sleep(ms / 1000.0)
                        pad.center()
                        time.sleep(0.2)
                        log(f"stroke {sx},{sy},{ms:.0f}")
                    elif parts[0] == "tap":
                        ms = float(parts[2]) / 1000.0 if len(parts) > 2 else 0.08
                        pad.tap(parts[1].upper(), ms)
                        time.sleep(0.4)
                        log(f"tap {parts[1]}")
                    elif parts[0] == "done":
                        stop = True
                        break
                shot()
                if stop:
                    break
        finally:
            a.terminate()
    log("cssprobe done")


def cmd_connect(args):
    a, b = build_instances(Path(args.iso_a), Path(args.iso_b))
    log(f"A = {a.user_json().get('displayName')} {a.connect_code()} | "
        f"B = {b.user_json().get('displayName')} {b.connect_code()}")
    with dolphin_lock.hold("netrig connect (two instances)", wait=60):
        connect_flow(a, b, args)
        log("connected -- instances left running (netrig.py kill to stop); "
            "NOTE: the virtual pads die when this process exits")


def build_instances(iso_a, iso_b, dump=False):
    exe = RIG_ROOT / "instance-a" / "Slippi Dolphin.exe"
    base = _xinput_connected_count()
    a = RigInstance("a", RIG_ROOT / "instance-a" / "User", exe, iso_a,
                    pipe_index=1, netplay_port=2627, spectator_port=51442,
                    input_backend="xpad", xinput_index=base)
    b = RigInstance("b", refresh_instance_b(), exe, iso_b,
                    pipe_index=2, netplay_port=2628, spectator_port=51443,
                    input_backend="xpad", xinput_index=base + 1)
    # The virtual pads must exist BEFORE Dolphin starts (XInput enumeration
    # happens at launch). Creation order fixes the slot order: a then b.
    a._pipe = XPad()
    b._pipe = XPad()
    log(f"virtual pads created (XInput slots {base} and {base + 1})")
    code_a, code_b = a.connect_code(), b.connect_code()
    if not code_a or not code_b:
        raise RuntimeError(f"missing connect code: a={code_a!r} b={code_b!r}")
    if code_a == code_b:
        raise RuntimeError(
            f"both instances are the SAME account ({code_a}); sign the "
            "launcher into the second account and rerun")
    # Dolphin REWRITES direct-codes.json on exit (real history returns,
    # e.g. ATHENA#0), so a one-time seed is clobbered before any
    # relaunch/reconnect -- remember the peer code and re-seed on every
    # launch instead.
    a._peer_seed = code_b
    b._peer_seed = code_a
    a.seed_direct_code(code_b)
    b.seed_direct_code(code_a)
    a.patch_configs(dump=dump)
    b.patch_configs(dump=dump)
    return a, b


def save_state(instances):
    STATE_PATH.write_text(json.dumps({
        "pids": {i.name: (i.proc.pid if i.proc else None) for i in instances},
        "started": time.time(),
    }), encoding="utf-8")


def cmd_kill():
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log("no rig state; nothing to kill")
        return
    for name, pid in (state.get("pids") or {}).items():
        if not pid:
            continue
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True)
            log(f"[{name}] killed pid {pid}")
        except Exception as e:
            log(f"[{name}] kill {pid} failed: {e}")
    STATE_PATH.unlink(missing_ok=True)


def cmd_smoke(args):
    a, b = build_instances(Path(args.iso_a), Path(args.iso_b))
    log(f"A = {a.user_json().get('displayName')} {a.connect_code()}  |  "
        f"B = {b.user_json().get('displayName')} {b.connect_code()}")
    with dolphin_lock.hold("netrig smoke (two instances)", wait=60):
        try:
            a.launch()
            b.launch()
            save_state([a, b])
            a.attach()
            b.attach()
            for inst in (a, b):
                maj = inst.wait_scene_major(
                    {MENU_MAJOR, ONLINE_CSS_MAJOR}, timeout=120,
                    label="Slippi main menu")
                log(f"[{inst.name}] reached scene major={maj:#x}")
            for inst in (a, b):
                inst.pipe().neutral()
                log(f"[{inst.name}] input pipe slippibot{inst.pipe_index} OK")
            for inst in (a, b):
                log(f"[{inst.name}] dolphin.log tail:")
                for line in inst.log_tail(8):
                    print(f"    {line}")
            if args.keep:
                log("smoke OK -- instances left running (netrig.py kill to stop)")
                return
            log("smoke OK -- terminating both")
        finally:
            if not args.keep:
                a.terminate()
                b.terminate()
                STATE_PATH.unlink(missing_ok=True)


def cmd_status():
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log("no rig state")
        return
    for name, pid in (state.get("pids") or {}).items():
        alive = False
        if pid:
            try:
                mem = Dolphin(pid)
                maj = mem.u8(SCENE_MAJOR)
                mino = mem.u8(SCENE_MINOR)
                alive = True
                log(f"[{name}] pid {pid} scene major={maj} minor={mino}")
                mem.close()
            except OSError:
                pass
        if not alive:
            log(f"[{name}] pid {pid}: not attachable (dead?)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sm = sub.add_parser("smoke", help="launch both instances to the menu")
    sm.add_argument("--iso-a", default=str(RIG_ROOT / "test-a.iso"))
    sm.add_argument("--iso-b",
                    default=VANILLA_ISO,
                    help="client B's ISO (default: $NUCLEUS_VANILLA_ISO)")
    sm.add_argument("--keep", action="store_true",
                    help="leave both running after the checks")
    cn = sub.add_parser("connect",
                        help="boot both, navigate to Direct, connect them")
    cn.add_argument("--iso-a", default=str(RIG_ROOT / "test-a.iso"))
    cn.add_argument("--iso-b",
                    default=VANILLA_ISO,
                    help="client B's ISO (default: $NUCLEUS_VANILLA_ISO)")
    cn.add_argument("--char-a", default="falcon")
    cn.add_argument("--char-b", default="falcon")
    cn.add_argument("--costume-a", type=int, default=0)
    cn.add_argument("--costume-b", type=int, default=0)
    pl = sub.add_parser("play",
                        help="connect, run the dthrow choreography with live "
                             "desync monitoring, LRAS out, collect replays")
    pl.add_argument("--iso-a", default=str(RIG_ROOT / "test-a.iso"))
    pl.add_argument("--iso-b",
                    default=VANILLA_ISO,
                    help="client B's ISO (default: $NUCLEUS_VANILLA_ISO)")
    pl.add_argument("--char-a", default="falcon")
    pl.add_argument("--char-b", default="falcon")
    pl.add_argument("--costume-a", type=int, default=0)
    pl.add_argument("--costume-b", type=int, default=0)
    pl.add_argument("--throws", type=int, default=10)
    pl.add_argument("--moves", default="dthrow",
                    help="comma list cycled per rep: dthrow,uthrow,upb,swap")
    pl.add_argument("--stadium-form", choices=tuple(STADIUM_FORM_INDEX),
                    help="force Stadium's next form identically on both clients")
    pl.add_argument("--edge-walk", action="store_true",
                    help="during forced water, walk both fighters to opposite "
                         "edges and save screenshots plus JSON evidence")
    pl.add_argument("--edge-walk-at", type=float, default=85.0,
                    help="earliest match time for the settled water-edge walk")
    pl.add_argument("--proof-label",
                    help="save labeled normal/water screenshots under "
                         "watch/stadium-review/<label>")
    pl.add_argument("--css-a", default=None,
                    help="explicit CSS target 'x,y,iconIndex' for a modded layout (client A)")
    pl.add_argument("--css-b", default=None,
                    help="same for client B")
    pl.add_argument("--min-seconds", type=int, default=None,
                    help="keep the match alive at least this long (Stadium "
                         "transformations happen ~1min in)")
    pl.add_argument("--inject-desync", action="store_true",
                    help="positive control: force a one-sided state edit "
                         "mid-match to prove the desync detector fires")
    pl.add_argument("--dump", action="store_true",
                    help="Dolphin-native frame dumping on both instances; "
                         "AVIs collected into <rig>/dumps/ after the run")
    pl.add_argument("--require-stage", choices=sorted(STAGE_BY_NAME),
                    help="requeue matches until the random stage is this one")
    pl.add_argument("--max-attempts", type=int, default=8)
    pl.add_argument("--full-reconnect-reroll", action="store_true",
                    help="reroll a required stage with a clean reconnect "
                         "instead of the faster in-session stage select")
    cp = sub.add_parser("cssprobe", help="interactive CSS steering (A only)")
    cp.add_argument("--iso-a", default=str(RIG_ROOT / "test-a.iso"))
    sub.add_parser("kill", help="terminate rig-launched Dolphins")
    sub.add_parser("status", help="scene + pid of running rig instances")
    args = ap.parse_args()
    if args.cmd in ("smoke", "connect", "play") and not args.iso_b:
        ap.error("--iso-b is required (or set NUCLEUS_VANILLA_ISO)")
    if args.cmd == "cssprobe":
        cmd_cssprobe(args)
        return
    if args.cmd == "smoke":
        cmd_smoke(args)
    elif args.cmd == "connect":
        cmd_connect(args)
    elif args.cmd == "play":
        cmd_play(args)
    elif args.cmd == "kill":
        cmd_kill()
    elif args.cmd == "status":
        cmd_status()


if __name__ == "__main__":
    main()
