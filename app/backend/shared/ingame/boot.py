"""
boot.py -- launch a freshly-built ISO in an ISOLATED, throwaway Slippi Dolphin,
configured to be driven over the named pipe and read from RAM -- WITHOUT touching
the user's own Slippi setup.

Ported from the boot half of tools/ingame/dolphin/driver.js. The key property: we never
launch the user's real User dir. We make a temp copy of their Config/ + Slippi/
login + GC/, patch it (pipe controller on port 1, windowed, no confirm-stop),
and boot
Dolphin with `-u <temp dir>`. The user's Slippi config is read-only-copied and
otherwise untouched, so their netplay setup keeps working.

No PowerShell, no Node -- just shutil + subprocess.Popen + a tiny INI writer.
"""

import configparser
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

from .melee_pipe import (STOCK_PIPE_PREFIX, Pipe, ensure_fifo, pipe_close, pipe_in_use, pipe_open,
                         pipe_prefix, set_pipe_dir, set_pipe_prefix)
from .boot_errors import DolphinGraphicsError, read_graphics_failure

logger = logging.getLogger(__name__)

_k32_creationflags = 0
if os.name == "nt":
    _k32_creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Called as (pid, exe) right after DolphinBoot.launch() starts Dolphin, when
# the code running the boot set it: the in-game job owns the Dolphin it opened
# (projects/routes/test_in_game.py).
ON_LAUNCH = ContextVar("dolphin_on_launch", default=None)


# --------------------------------------------------------------------------- #
# Locate the user's Slippi Dolphin exe + template User dir from the path the    #
# frontend already stores (localStorage 'slippi_dolphin_path', verified by      #
# /api/mex/settings/slippi-path/verify to contain User/Config/Dolphin.ini).     #
# --------------------------------------------------------------------------- #
if os.name == "nt":
    DOLPHIN_EXE_NAMES = ["Slippi Dolphin.exe", "Dolphin.exe", "DolphinWx.exe"]
elif sys.platform == "darwin":
    # macOS ships Slippi as an .app bundle; the real executable lives inside it.
    DOLPHIN_EXE_NAMES = [
        "Slippi Dolphin.app/Contents/MacOS/Slippi Dolphin",
        "Slippi Dolphin", "Dolphin.app/Contents/MacOS/Dolphin", "dolphin-emu",
    ]
else:
    DOLPHIN_EXE_NAMES = [
        "Slippi_Online-x86_64.AppImage", "Slippi Dolphin", "slippi-dolphin",
        "dolphin-emu", "AppRun",
    ]

# The PLAYBACK build is a separate download with its own filename -- off Windows
# the Launcher names the AppImage after the build ("Slippi_Playback-…"), so the
# netplay names above never match inside playback/ and watch-with-mods reports
# "playback Dolphin not found" on a perfectly good Linux install.
if os.name == "nt":
    DOLPHIN_PLAYBACK_EXE_NAMES = ["Slippi Dolphin.exe"]
elif sys.platform == "darwin":
    DOLPHIN_PLAYBACK_EXE_NAMES = list(DOLPHIN_EXE_NAMES)
else:
    DOLPHIN_PLAYBACK_EXE_NAMES = [
        "Slippi_Playback-x86_64.AppImage", "Slippi_Playback.AppImage",
    ] + DOLPHIN_EXE_NAMES


def launcher_dir(*parts):
    """The Slippi Launcher's per-OS config/install dir (its Electron userData),
    optionally joined with `parts`. None on Windows when APPDATA is unset.

    THE one definition of this path — identity.py and watch_mods.py resolve
    the launcher's Settings / netplay / playback locations through it, so a
    layout change (Flatpak, XDG_CONFIG_HOME, a renamed userData dir) is fixed
    here once instead of drifting across per-module copies."""
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        if not base:
            return None
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library",
                            "Application Support")
    else:
        base = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "Slippi Launcher", *parts)


def read_launcher_settings():
    """The Slippi Launcher's electron-store Settings file (JSON, no extension),
    or {} when it is missing or unreadable.

    The one reader of that file: tracker/store/identity.py (replay folder,
    accounts) and core/playable_iso.py (the ISO the Launcher opens) both come
    through here, beside the one definition of where it lives."""
    path = launcher_dir("Settings")
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _appdata_fallbacks():
    if os.name == "nt":
        exe = launcher_dir()
        if exe is None:
            return []
        return [
            launcher_dir("netplay", "Slippi Dolphin.exe"),
            launcher_dir("playback", "Slippi Dolphin.exe"),
        ]
    # Linux: the Slippi Launcher drops the netplay/playback AppImages under
    # ~/.config/Slippi Launcher/, same layout as Windows minus the .exe.
    # macOS: the same layout under ~/Library/Application Support.
    out = []
    d = launcher_dir("netplay")
    if os.path.isdir(d):
        for name in DOLPHIN_EXE_NAMES:
            out.append(os.path.join(d, name))
    playback = playback_exe_in(launcher_dir("playback"))
    if playback:
        out.append(playback)
    return out


def playback_exe_in(playback_dir):
    """The playback Dolphin executable inside a Launcher playback/ dir, or None.

    THE one definition of playback-build detection -- watch_mods resolves the
    exe it hands the -i comm file through this. Off Windows the Launcher ships
    an AppImage whose name carries the build and can carry a version, so an
    exact-name miss falls back to any executable .AppImage in the directory:
    inside playback/ there is nothing else it could be."""
    if not playback_dir or not os.path.isdir(playback_dir):
        return None
    for name in DOLPHIN_PLAYBACK_EXE_NAMES:
        path = os.path.join(playback_dir, name)
        if os.path.exists(path) and (os.name == "nt" or os.access(path, os.X_OK)):
            return path
    if os.name == "nt":
        return None
    for entry in sorted(os.listdir(playback_dir)):
        if not entry.lower().endswith(".appimage"):
            continue
        path = os.path.join(playback_dir, entry)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def resolve_dolphin(slippi_path):
    """Return (dolphin_exe, template_user_dir) from the configured Slippi path.

    `slippi_path` may be the Slippi install folder (containing the exe + User/)
    or the exe itself. Falls back to the Slippi Launcher install under APPDATA.
    Raises if no Dolphin executable can be found."""
    candidates_exe = []
    template_user = None

    # NUCLEUS_SLIPPI_PATH overrides everything. Needed on macOS to point the
    # harness at a debuggable copy of Dolphin: the shipped Slippi build is
    # signed with the hardened runtime and no get-task-allow entitlement, which
    # makes task_for_pid fail even for root, so memory reads are impossible
    # against it. Re-signing a COPY ad-hoc with get-task-allow lifts that.
    # Also handy anywhere for testing against an alternate Dolphin build.
    override = os.environ.get("NUCLEUS_SLIPPI_PATH")
    if override:
        slippi_path = override

    if slippi_path:
        p = Path(slippi_path)
        is_exe_file = p.is_file() and (
            p.suffix.lower() == ".exe" if os.name == "nt"
            else os.access(p, os.X_OK)
        )
        if is_exe_file:
            candidates_exe.append(str(p))
            template_user = p.parent / "User"
        elif p.is_dir():
            for name in DOLPHIN_EXE_NAMES:
                cand = p / name
                if cand.exists():
                    candidates_exe.append(str(cand))
            if (p / "User").is_dir():
                template_user = p / "User"
            # Some installs nest the exe one level down.
            if not candidates_exe:
                for sub in p.iterdir() if p.exists() else []:
                    if sub.is_dir():
                        for name in DOLPHIN_EXE_NAMES:
                            cand = sub / name
                            if cand.exists():
                                candidates_exe.append(str(cand))
                                if (sub / "User").is_dir():
                                    template_user = sub / "User"

    for fb in _appdata_fallbacks():
        if os.path.exists(fb):
            candidates_exe.append(fb)
            if template_user is None:
                tu = Path(fb).parent / "User"
                if tu.is_dir():
                    template_user = tu

    exe = next((c for c in candidates_exe if os.path.exists(c)), None)
    if not exe:
        raise FileNotFoundError(
            "Could not find a Slippi Dolphin executable. Set the Slippi path in "
            "Settings (it should point to the folder with 'Slippi Dolphin.exe')."
        )
    if template_user and not Path(template_user).is_dir():
        template_user = None
    if template_user is None and os.name != "nt":
        # Linux Dolphin keeps config in XDG paths rather than a portable User/
        # dir next to the exe. ~/.config/SlippiOnline holds Config/ + Slippi/
        # exactly like a User dir, so it serves as the template to copy.
        xdg = _dolphin_user_root()
        if (xdg / "Config").is_dir():
            template_user = xdg
    return exe, (str(template_user) if template_user else None)


def _dolphin_user_root():
    """Where Dolphin keeps Config/, Load/, Dump/ off Windows.

    Linux uses XDG (~/.config/SlippiOnline); macOS uses
    ~/Library/Application Support/com.project-slippi.dolphin, and older builds
    used a plain "Slippi" folder there -- take whichever exists."""
    home = Path(os.path.expanduser("~"))
    if sys.platform == "darwin":
        # Confirmed against a real install: Slippi keeps a PORTABLE-style User/
        # dir nested per build --
        #   com.project-slippi.dolphin/netplay/User/Config/Dolphin.ini
        # -- not the flat XDG layout Linux uses. Probe for the one that actually
        # holds a Config/, newest-layout first, so older installs still resolve.
        base = home / "Library" / "Application Support"
        slippi = base / "com.project-slippi.dolphin"
        candidates = [
            slippi / "netplay" / "User",
            slippi / "playback" / "User",
            slippi,                      # older builds put Config/ directly here
            base / "Slippi",
            base / "SlippiOnline",
        ]
        for cand in candidates:
            if (cand / "Config").is_dir():
                return cand
        return candidates[0]
    return home / ".config" / "SlippiOnline"


def slippi_user_dir(slippi_path):
    """The Dolphin *User* directory for a configured Slippi install.

    Windows Slippi is portable and keeps everything in <slippi_path>/User.
    Linux Dolphin does not: there is no User/ folder beside the AppImage, and
    the config/texture tree lives in XDG at ~/.config/SlippiOnline. Building
    paths as <slippi_path>/User/... therefore points at nothing on Linux --
    silently, because the callers only ever check `.exists()`. That breaks
    Slippi-path verification, the GFX.ini writes behind the HD-texture toggle,
    and the Load/Textures pack install target.

    Prefer a real User/ dir when one is present (portable and extracted
    layouts, and WSL pointing at a Windows install) so Windows behaviour is
    unchanged; fall back to the XDG tree off Windows.
    """
    portable = Path(slippi_path) / "User"
    if portable.is_dir() or os.name == "nt":
        return portable
    xdg = _dolphin_user_root()
    return xdg if xdg.is_dir() else portable


def parse_dolphin_ini_iso_path(ini_path):
    """The ISO directory a Dolphin.ini names, or None.

    The first of [General] ISOPath0..9 that is an existing directory, else the
    parent of DefaultISO when that is one. An unreadable INI is None.
    """
    try:
        config = configparser.ConfigParser()
        config.read(ini_path, encoding="utf-8")

        if "General" in config:
            general = config["General"]

            for i in range(10):
                key = f"ISOPath{i}"
                if key in general:
                    iso_dir = general[key]
                    if iso_dir and Path(iso_dir).is_dir():
                        logger.info(f"Found ISO directory from {key}: {iso_dir}")
                        return iso_dir

            # DefaultISO is a file path, so take its directory
            if "DefaultISO" in general:
                default_iso = general["DefaultISO"]
                if default_iso:
                    iso_dir = str(Path(default_iso).parent)
                    if Path(iso_dir).is_dir():
                        logger.info(f"Found ISO directory from DefaultISO: {iso_dir}")
                        return iso_dir

        return None
    except Exception as e:
        logger.warning(f"Error parsing Dolphin.ini: {e}")
        return None


def iso_dir_from_slippi(slippi_path):
    """Return the user's Dolphin ISO directory -- the folder Slippi scans for
    games -- from Config/Dolphin.ini (ISOPath0..9 or DefaultISO's parent) under
    slippi_user_dir(). Falls back to its Games/ (created if needed)."""
    found = parse_dolphin_ini_iso_path(str(slippi_user_dir(slippi_path) / "Config" / "Dolphin.ini"))
    if found:
        return found
    fallback = str(slippi_user_dir(slippi_path) / "Games")
    os.makedirs(fallback, exist_ok=True)
    return fallback


def launch_real(slippi_path, iso_path):
    """Launch the user's REAL Slippi Dolphin booting `iso_path` for normal play:
    their own User dir / config / controllers, a visible window, and NO pipe
    controller (unlike DolphinBoot, which is the isolated test harness). Detached
    so the game keeps running independently of the backend. Returns the exe used."""
    exe, _ = resolve_dolphin(slippi_path)
    start_detached([str(exe), "-e", str(iso_path)], cwd=str(Path(exe).parent))
    return exe


def start_detached(args, *, cwd, env=None, **popen_kwargs):
    """Start a game someone plays: an argument list (never a shell), detached from
    the backend so it survives backend churn, with its own window visible (no
    CREATE_NO_WINDOW). Never owned by core.child_procs: a game that restarts
    itself starts a new copy and exits, and a kill-on-close job would take the
    copy down with Nucleus. Returns the Popen. `env` is the whole environment
    (None: the backend's without Nucleus's settings and secrets, core/child_env.py)."""
    if env is None:
        from core.child_env import child_environment
        env = child_environment()
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0)
    return subprocess.Popen(list(args), cwd=cwd, env=env, creationflags=creationflags, **popen_kwargs)


# --------------------------------------------------------------------------- #
# Tiny Dolphin-INI reader/writer (section -> ordered key/value), matching       #
# driver.js's writeIni semantics: parse, upsert keys, re-stringify.             #
# --------------------------------------------------------------------------- #
def _parse_ini(text):
    sections = {"": {}}
    order = [""]
    current = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            if current not in sections:
                sections[current] = {}
                order.append(current)
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            sections[current][k.strip()] = v.strip()
    return sections, order


def _write_ini(path, mutate):
    text = ""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    sections, order = _parse_ini(text)

    def upsert(section, key, value):
        if section not in sections:
            sections[section] = {}
            order.append(section)
        sections[section][key] = str(value)

    def replace_section(section, kv):
        if section not in sections:
            order.append(section)
        sections[section] = dict(kv)

    mutate(upsert, replace_section)

    lines = []
    first = True
    for name in order:
        if name == "" and not sections.get("", {}):
            continue
        if name != "":
            if not first:
                lines.append("")
            lines.append(f"[{name}]")
            first = False
        for k, v in sections[name].items():
            lines.append(f"{k} = {v}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _patch_dolphin_ini(user_dir, pipe_name, render_size=None, interactive=False):
    path = os.path.join(user_dir, "Config", "Dolphin.ini")
    # Captures are PrintWindow grabs of the render window's client area, so the
    # window size IS the screenshot resolution -- raising it is the only way to
    # get a bigger shot. Keep any override on-screen: an oversized window gets
    # clipped by the desktop and PrintWindow returns the clipped pixels.
    rw, rh = render_size or (1280, 960)
    if interactive:
        original = configparser.ConfigParser(strict=False, interpolation=None)
        original.read(path, encoding="utf-8")
        device = original.get("Core", "SIDevice0", fallback="6").strip()
        if device not in ("6", "12"):
            raise ValueError("Configure a Standard Controller or GameCube Adapter on "
                             "port 1 in Slippi before starting a playable preview.")
        if device == "6":
            pads = configparser.ConfigParser(strict=False, interpolation=None)
            pads.read(os.path.join(user_dir, "Config", "GCPadNew.ini"), encoding="utf-8")
            mapping = pads.get("GCPad1", "Device", fallback="").strip()
            if not mapping or mapping.lower().startswith("pipe/"):
                raise ValueError("Configure your port-1 controller mapping in Slippi "
                                 "before starting a playable preview. An empty or "
                                 "automation-pipe mapping cannot provide your controls.")

    def mutate(upsert, replace_section):
        upsert("Input", "BackgroundInput", "True")       # accept input unfocused
        upsert("Interface", "ConfirmStop", "False")      # no "are you sure" on stop
        upsert("Interface", "PauseOnFocusLost", "False")
        # Copied absolute paths would bypass the GC/ copy and write the user's
        # live memory cards. Empty paths select this run's own User/GC defaults.
        upsert("Core", "MemcardAPath", "")
        upsert("Core", "MemcardBPath", "")
        upsert("Display", "Fullscreen", "False")
        # The owned preview/capture targets a separate render surface. A copied
        # RenderToMain=True would put the game inside Dolphin's settings GUI.
        upsert("Display", "RenderToMain", "False")
        upsert("Display", "RenderWindowAutoSize", "False")
        upsert("Display", "RenderWindowWidth", str(rw))
        upsert("Display", "RenderWindowHeight", str(rh))
        if not interactive:
            upsert("Core", "SIDevice0", "6")  # automated checks use pipe port 1
        upsert("Core", "SIDevice1", "0")
        upsert("Core", "SIDevice2", "0")
        upsert("Core", "SIDevice3", "6" if interactive else "0")

    _write_ini(path, mutate)

    gc_path = os.path.join(user_dir, "Config", "GCPadNew.ini")

    def mutate_gc(upsert, replace_section):
        p = "GCPad4" if interactive else "GCPad1"
        replace_section(p, {})  # wipe inherited keyboard mapping
        upsert(p, "Device", f"Pipe/0/{pipe_name}")
        for btn in ["A", "B", "X", "Y", "Z", "L", "R"]:
            upsert(p, f"Buttons/{btn}", f"Button {btn}")
        upsert(p, "Buttons/Start", "Button START")
        upsert(p, "Buttons/Threshold", "50.0")
        upsert(p, "Main Stick/Up", "Axis MAIN Y +")
        upsert(p, "Main Stick/Down", "Axis MAIN Y -")
        upsert(p, "Main Stick/Left", "Axis MAIN X -")
        upsert(p, "Main Stick/Right", "Axis MAIN X +")
        upsert(p, "Main Stick/Radius", "100.0")
        upsert(p, "D-Pad/Up", "Button D_UP")
        upsert(p, "D-Pad/Down", "Button D_DOWN")
        upsert(p, "D-Pad/Left", "Button D_LEFT")
        upsert(p, "D-Pad/Right", "Button D_RIGHT")
        upsert(p, "C-Stick/Up", "Axis C Y +")
        upsert(p, "C-Stick/Down", "Axis C Y -")
        upsert(p, "C-Stick/Left", "Axis C X -")
        upsert(p, "C-Stick/Right", "Axis C X +")
        upsert(p, "C-Stick/Radius", "100.0")
        upsert(p, "Triggers/L", "Button L")
        upsert(p, "Triggers/R", "Button R")
        upsert(p, "Triggers/L-Analog", "Axis L -+")
        upsert(p, "Triggers/R-Analog", "Axis R -+")
        upsert(p, "Triggers/Threshold", "90.0")
        if not interactive:
            replace_section("GCPad3", {})  # drop inherited port-3 keyboard cursor

    _write_ini(gc_path, mutate_gc)


# The only channels a run's dolphin.log carries: the game's own OSReport text.
# OSREPORT_HLE is mainline Dolphin's name for the HLE half; Slippi's
# Ishiiruka-based build logs both halves as OSREPORT and ignores the extra key.
LOG_CHANNELS = ("OSREPORT", "OSREPORT_HLE")


def _patch_logger_ini(user_dir):
    """Log only Dolphin's OSReport channel, to User/Logs/dolphin.log.

    Melee (and m-ex / HSD) print assertions, heap failures and missing files
    through OSReport, so a hang that leaves the frame counter frozen usually
    has its cause here. Every other channel the copied Logger.ini names is
    written off: a template whose log channels were all toggled on (Dolphin's
    log configuration has a "toggle all") otherwise gives each run its PowerPC
    exceptions at Info, about 10 MB a minute (28.8 MB for a 3-minute 0.9.0
    smoke test). Dolphin leaves a channel the file does not name off."""
    path = os.path.join(user_dir, "Config", "Logger.ini")
    cfg = configparser.ConfigParser(strict=False, interpolation=None)
    cfg.optionxform = str
    if os.path.exists(path):
        try:
            cfg.read(path, encoding="utf-8")
        except configparser.Error:
            pass
    for sec in ("Options", "Logs"):
        if not cfg.has_section(sec):
            cfg.add_section(sec)
    cfg["Options"]["WriteToFile"] = "True"
    cfg["Options"]["WriteToConsole"] = "False"
    cfg["Options"]["Verbosity"] = "4"
    logs = cfg["Logs"]
    kept = {name.upper() for name in LOG_CHANNELS}
    for key in list(logs):
        # Compared without case: Dolphin may read keys that way, so a
        # template's `osreport` must not stay off beside our `OSREPORT`.
        logs[key] = "True" if key.upper() in kept else "False"
    present = {key.upper() for key in logs}
    for name in LOG_CHANNELS:
        if name.upper() not in present:
            logs[name] = "True"
    with open(path, "w", encoding="utf-8") as f:
        cfg.write(f, space_around_delimiters=True)


def _patch_hotkeys(user_dir):
    """Neutralise the keyboard hotkeys that fire over BackgroundInput=True.

    Because we run with background input on (so the pipe controller works while
    the app -- not Dolphin -- has focus), Dolphin's keyboard hotkeys ALSO fire
    while the user is interacting with our window. The worst offender is plain
    `F` = Toggle Fullscreen (Slippi's default), which yanks the throwaway/embedded
    Dolphin into fullscreen mid-run. We blank that and the other plain-key globals
    a user could hit by accident while typing (Esc=Stop, Tab=speed limit,
    Y=OSD chat, Enter=send chat). State-save F-keys keep their modifiers/Fn keys
    and are left alone. This only touches the throwaway copy; the real config is
    untouched."""
    path = os.path.join(user_dir, "Config", "Hotkeys.ini")

    def mutate(upsert, _replace):
        s = "Hotkeys1"
        for binding in (
            "Toggle Fullscreen",
            "Stop/Hide OSD chat",
            "Toggle OSD chat",
            "Send OSD chat message",
            "Disable Emulation Speed Limit",
        ):
            upsert(s, f"Keys/{binding}", "")

    _write_ini(path, mutate)


def _patch_turbo(user_dir):
    """Uncap emulation speed and mute audio in the THROWAWAY config.

    Only real-time waits are affected -- boot, menu navigation and the post-load
    READY/GO frame gate. Every frameshot capture is taken with the game
    debug-frozen and stepped one logic frame at a time, so frame exactness is
    untouched by how fast the emulator runs between those points. Audio is off
    because nothing listens to it and the DSP costs CPU that the uncapped core
    can use instead.

    `EmulationSpeed = 0` is Dolphin's "unlimited". Slippi's jukebox is muted
    separately (it is a Slippi addition, not a Dolphin DSP backend)."""
    path = os.path.join(user_dir, "Config", "Dolphin.ini")

    def mutate(upsert, _replace):
        upsert("Core", "EmulationSpeed", "0")
        upsert("Core", "SlippiJukeboxEnabled", "False")
        upsert("Core", "SlippiJukeboxVolume", "0")
        upsert("DSP", "Backend", "No audio output")
        upsert("DSP", "Volume", "0")

    _write_ini(path, mutate)


def _patch_clean_osd(user_dir):
    """Turn off the emulator OSD overlays for a clean screenshot: Dolphin's FPS
    counter and Slippi's on-screen ping ("Delay: N"). Keys are written lowercase
    to match how Slippi writes GFX.ini (Dolphin reads them case-insensitively)."""
    path = os.path.join(user_dir, "Config", "GFX.ini")

    def mutate(upsert, _replace):
        upsert("Settings", "showfps", "False")
        upsert("Settings", "shownetplayping", "False")
        upsert("Settings", "shownetplaymessages", "False")

    _write_ini(path, mutate)

    # General OSD messages ("Wrote memory card A contents to ...") are a
    # Dolphin.ini Interface setting, not GFX.ini -- they photobomb captures
    # whenever the game touches the memory card near the shot.
    dolphin_ini = os.path.join(user_dir, "Config", "Dolphin.ini")

    def mutate_iface(upsert, _replace):
        upsert("Interface", "OnScreenDisplayMessages", "False")

    _write_ini(dolphin_ini, mutate_iface)


def _patch_gfx_internal_res(user_dir, scale):
    """Render at `scale`x native (1 = 640x528). Rendering ABOVE the window size
    supersamples: Dolphin downsamples to the window, which is what the capture
    grabs, so stage textures come back far cleaner at the same output size."""
    path = os.path.join(user_dir, "Config", "GFX.ini")

    def mutate(upsert, _replace):
        upsert("Settings", "InternalResolution", str(int(scale)))

    _write_ini(path, mutate)


def _patch_gfx_textures(user_dir, dump=False, hires=True):
    path = os.path.join(user_dir, "Config", "GFX.ini")

    def mutate(upsert, _replace):
        upsert("Settings", "DumpTextures", "True" if dump else "False")
        upsert("Settings", "HiresTextures", "True" if hires else "False")

    _write_ini(path, mutate)


def dolphin_running():
    """Return the pids of any already-running Dolphin EMULATOR process (the user's
    own Slippi window). The in-game harness launches and drives its OWN throwaway
    Dolphin, so a second one open at the same time steals the foreground -- the test
    then just sits on the menu, never pressing a button. Returns [] on error.
    Note: the Slippi LAUNCHER ("Slippi Launcher.exe") is a different process and
    is intentionally NOT matched."""
    if os.name != "nt":
        return _dolphin_running_proc()
    pids = []
    for name in DOLPHIN_EXE_NAMES:  # "Slippi Dolphin.exe", "Dolphin.exe", "DolphinWx.exe"
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True,
                creationflags=_k32_creationflags, timeout=10,
            ).stdout or ""
        except Exception:
            continue
        for line in out.splitlines():
            line = line.strip()
            if not line or line.upper().startswith("INFO:"):
                continue
            cells = [c.strip().strip('"') for c in line.split('","')]
            if cells and cells[0].lower() == name.lower() and len(cells) > 1:
                pids.append(cells[1])
    return pids


def _dolphin_running_proc():
    """Linux dolphin_running: scan /proc cmdlines for a Dolphin emulator process
    (AppImages exec through a wrapper, so match cmdline, not just comm)."""
    needles = ("slippi dolphin", "slippi_online", "slippi-dolphin", "dolphin-emu")
    pids = []
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/cmdline", "rb") as f:
                    cmd = f.read().replace(b"\x00", b" ").decode("utf-8", "ignore").lower()
            except OSError:
                continue
            if any(n in cmd for n in needles) and "launcher" not in cmd:
                pids.append(entry)
    except OSError:
        return []
    return pids


DOLPHIN_OPEN_MSG = ("Close the other Dolphin window to continue — an "
                    "already-open Slippi Dolphin steals input focus from the "
                    "throwaway one this run boots, so it would just sit on "
                    "the menu.")


def wait_until_no_dolphin(emit=None, log=lambda m: None, timeout=300.0,
                          percentage=5, stop_event=None):
    """Block until the user's own Dolphin window(s) close, telling them why
    via the progress channel. Returns True when clear to boot; False when
    the timeout expires with Dolphin still open, or at once when `stop_event`
    is set (the job was cancelled). `emit` is the usual (stage, percentage,
    message) progress emitter.

    A machine configured for several harness Dolphins
    (NUCLEUS_DOLPHIN_SLOTS > 1) runs siblings on purpose: their inputs go
    through each run's own pipe with background input on, so another open
    Dolphin is not waited for there."""
    from . import dolphin_lock
    if dolphin_lock.slot_count() > 1:
        return True
    pids = dolphin_running()
    if not pids:
        return True
    log(f"waiting for the user's Dolphin to close (pids {pids})")
    if emit:
        emit("waiting", percentage, DOLPHIN_OPEN_MSG)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not dolphin_running():
            log("the other Dolphin closed; continuing")
            return True
        if stop_event is not None:
            if stop_event.wait(1.0):
                log("stopped while waiting for the other Dolphin to close")
                return False
        else:
            time.sleep(1.0)
    log("timed out waiting for the other Dolphin to close")
    return False


def pick_pipe_index(max_index=8):
    """Pick a slippibot<N> pipe index NOT currently in use, so we never collide
    with a Slippi instance the user already has open."""
    for n in range(1, max_index + 1):
        if not pipe_in_use(n):
            return n
    return 1


def _same_file(a, b):
    """Two paths to one file, compared as written (no file is opened)."""
    if not a or not b:
        return False
    return (os.path.normcase(os.path.abspath(str(a)))
            == os.path.normcase(os.path.abspath(str(b))))


RUN_OWNER = "owner.pid"      # in each run dir: the pid of the harness process that made it


def live_runs(runs_root):
    """Names of the run dirs under `runs_root` that ANOTHER live harness
    process made. On a machine with several slots, runs share a runs root and
    overlap, and pruning it to the newest five would take a longer run's User
    dir from under its Dolphin. A process holds one slot, so a dir of this
    process's own that is not the current one is never live."""
    from .dolphin_lock import _pid_alive
    live = []
    try:
        entries = list(Path(runs_root).iterdir())
    except OSError:
        return live
    for entry in entries:
        try:
            pid = int((entry / RUN_OWNER).read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
        if pid != os.getpid() and _pid_alive(pid):
            live.append(entry.name)
    return live


class DolphinBootCancelled(RuntimeError):
    """Cancellation of an owned interactive preview, not a game failure."""


class DolphinBoot:
    """Owns the isolated run dir + the launched Dolphin process. Use as a
    context manager so the temp User dir and the process are always cleaned up
    (the user's real Slippi config is never written)."""

    def __init__(self, iso_path, slippi_path, runs_root, pipe_index=None,
                 hires_textures=False, load_seed=None, clean_osd=False,
                 turbo=False, render_size=None, internal_res=None,
                 log=lambda m: None, interactive=False, stop_event=None,
                 input_backend=None, deadline=None):
        from .memory_input import select_backend
        # Seconds the launched Dolphin may live (see _arm_deadline). None is
        # no limit: playable previews and harness sessions stay up on purpose.
        self.deadline = deadline
        self.timed_out = False
        self._deadline_timer = None
        self.input_backend = select_backend(input_backend)
        if interactive and self.input_backend != "pipe":
            raise ValueError("Memory input is for automated harness sessions, not playable previews")
        self._memory_input = None
        # This boot's own depth of the machine-wide Dolphin lock: released once,
        # and only if it was taken (a caller may hold an outer depth).
        self._holds_lock = False
        self.iso_path = iso_path
        self.slippi_path = slippi_path
        self.runs_root = Path(runs_root)
        self.log = log
        self.pipe_index = pipe_index
        self.hires_textures = hires_textures
        self.load_seed = load_seed  # optional path to a Load/Textures dir to pre-seed
        self.clean_osd = clean_osd  # turn off FPS/ping OSD overlays (capture mode)
        self.turbo = turbo          # uncapped emulation speed + no audio
        self.render_size = render_size    # (w, h) render window; None = 1280x960
        self.internal_res = internal_res  # EFB scale multiple; None = leave as-is
        self.run_dir = None
        self.user_dir = None
        self.exe = None
        self._pipe_from_slot = False
        self.proc = None
        self._next_graphics_check = 0.0
        self.interactive = interactive
        self.stop_event = stop_event

    def check_cancelled(self):
        if self.stop_event is not None and self.stop_event.is_set():
            raise DolphinBootCancelled("Playable preview stopped.")

    @staticmethod
    def _slot_pipe():
        """The pipe of the lock slot this process holds, when a machine runs
        more than one harness Dolphin; None otherwise (single-slot machines keep
        pick_pipe_index, which avoids a Slippi the user has open)."""
        from . import dolphin_lock
        slot = dolphin_lock.current_slot()
        if dolphin_lock.slot_count() > 1 and slot is not None:
            return dolphin_lock.slot_pipe(slot)
        return None

    def _route_to_slot(self):
        """Point this boot at the lock slot the process holds, and return the
        pipe index that goes with it (None: no slot decides it).

        A pipe NUMBER does not separate two stock Dolphins on Windows (see
        dolphin_lock.slot_kit), so where the machine keeps a copy of Dolphin
        for the slot, the boot runs that copy and drives its first pipe under
        the copy's own prefix. A slot's copy stands in for the Dolphin it was
        copied FROM, and only for that one: a boot that resolved to another
        Dolphin (NUCLEUS_SLIPPI_PATH naming an alternate build, or a slot copy
        itself) keeps it, and its pipes are then the caller's business."""
        from . import dolphin_lock
        pipe = self._slot_pipe()
        kit = dolphin_lock.slot_kit(dolphin_lock.current_slot()) if pipe is not None else None
        if kit and not _same_file(kit["stock_exe"], getattr(self, "_resolved_exe", None)):
            kit = None
        set_pipe_prefix(kit["prefix"] if kit else STOCK_PIPE_PREFIX)
        if kit:
            self.exe = kit["exe"]
            self.log(f"slot {dolphin_lock.current_slot()}: its own Dolphin {kit['exe']} "
                     f"(pipes {kit['prefix']}1-4)")
            return 1     # the copy's first pipe; GCPad1's device is still called slippibot1
        return pipe

    def _use_slot_pipe(self):
        """After the lock is taken in launch(): move an automatically chosen
        pipe onto the held slot's pipe, and the boot onto the slot's own copy
        of Dolphin where there is one, so sibling slots share nothing."""
        if self.input_backend == "memory" or not self._pipe_from_slot:
            return
        pipe = self._route_to_slot()
        if pipe is None or pipe == self.pipe_index:
            return
        self.pipe_index = pipe
        _patch_dolphin_ini(str(self.user_dir), f"slippibot{pipe}",
                           render_size=self.render_size, interactive=self.interactive)
        if os.name != "nt":
            ensure_fifo(pipe)
        self.log(f"slot pipe: slippibot{pipe}")

    def prepare(self):
        self.check_cancelled()
        self.exe, template_user = resolve_dolphin(self.slippi_path)
        self._resolved_exe = self.exe      # what the caller's settings name; a slot's copy may stand in for it
        # One run dir per boot, even when two slots start in the same second.
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self.run_dir = self.runs_root / f"test-{stamp}"
        suffix = 1
        while True:
            try:
                self.run_dir.mkdir()
                break
            except FileExistsError:
                self.run_dir = self.runs_root / f"test-{stamp}-{suffix}"
                suffix += 1
        # Keep only the newest few runs (~50 MB each); never this one, and
        # never one another harness process is still running in.
        (self.run_dir / RUN_OWNER).write_text(str(os.getpid()), encoding="utf-8")
        from core.run_retention import prune_runs  # lazy: importing ingame must not initialise core
        prune_runs(self.runs_root, keep=5,
                   protect=(self.run_dir.name, *live_runs(self.runs_root)))
        self.user_dir = self.run_dir / "User"
        (self.user_dir / "Config").mkdir(parents=True, exist_ok=True)

        # Copy the user's Config + Slippi login + memory card into the
        # throwaway User dir. GC/ is deliberately copied (never linked) so
        # Melee does not enter its first-boot save-data flow, while the user's
        # real card and SRAM remain untouched.
        if template_user:
            src_cfg = Path(template_user) / "Config"
            if src_cfg.is_dir():
                shutil.copytree(src_cfg, self.user_dir / "Config", dirs_exist_ok=True)
            src_slippi = Path(template_user) / "Slippi"
            if src_slippi.is_dir():
                shutil.copytree(src_slippi, self.user_dir / "Slippi", dirs_exist_ok=True)
            src_gc = Path(template_user) / "GC"
            if src_gc.is_dir():
                shutil.copytree(src_gc, self.user_dir / "GC", dirs_exist_ok=True)

        self.check_cancelled()

        if self.pipe_index is None:
            self._pipe_from_slot = True
            self.pipe_index = (1 if self.input_backend == "memory" else
                               self._route_to_slot() or pick_pipe_index())
        _patch_dolphin_ini(str(self.user_dir), f"slippibot{self.pipe_index}",
                           render_size=self.render_size, interactive=self.interactive)
        _patch_hotkeys(str(self.user_dir))
        if self.input_backend == "memory":
            from .memory_input import prepare
            prepare(self.user_dir, self.iso_path)

        if self.clean_osd:
            _patch_clean_osd(str(self.user_dir))

        if self.internal_res:
            _patch_gfx_internal_res(str(self.user_dir), self.internal_res)

        if self.turbo:
            _patch_turbo(str(self.user_dir))

        if self.hires_textures:
            _patch_gfx_textures(str(self.user_dir), dump=False, hires=True)
            # Pre-seed the HD textures before boot (CacheHiresTextures indexes the
            # Load folder once at startup; injecting after boot wouldn't be seen).
            if self.load_seed and Path(self.load_seed).is_dir():
                dst = self.user_dir / "Load" / "Textures"
                dst.mkdir(parents=True, exist_ok=True)
                shutil.copytree(self.load_seed, dst, dirs_exist_ok=True)

        if os.name != "nt" and self.input_backend == "pipe":
            # Linux Dolphin reads controller pipes as FIFOs under the user
            # dir's Pipes/; the FIFO must exist before Dolphin scans
            # controllers, and melee_pipe must write into THIS run's dir.
            set_pipe_dir(self.user_dir / "Pipes")
            ensure_fifo(self.pipe_index)

        # Capture only the game's OSReport channel (m-ex / HSD assertions, heap
        # exhaustion messages) to User/Logs/dolphin.log so a hang or crash
        # leaves a diagnosis behind; cleanup() preserves that file.
        _patch_logger_ini(str(self.user_dir))

        self.log(f"isolated User dir: {self.user_dir}")
        suffix = ""
        if self.input_backend == "pipe":
            from . import dolphin_lock
            suffix = f"  (pipe {pipe_prefix()}{self.pipe_index})"
            if (self._pipe_from_slot and dolphin_lock.slot_count() > 1
                    and dolphin_lock.current_slot() is None):
                # Several slots and none held yet: this exe and pipe are what
                # the settings name, not what will run (seen as a misleading
                # "stock exe, slippibot1" line ahead of the slot's own).
                suffix += "  -- until launch takes a slot: that slot's own Dolphin and pipe then replace both"
        self.log(f"Dolphin exe: {self.exe}{suffix}")
        self.log(f"controller input backend: {self.input_backend}")
        return self

    def launch(self):
        self.check_cancelled()
        # ENFORCED one-Dolphin-at-a-time: every boot path in the repo funnels
        # through here, so the machine-wide lock is taken at the chokepoint --
        # not left to callers. Re-entrant per process (a caller that already
        # acquired with a nicer purpose string is a no-op). Queue time comes
        # from MELEE_DOLPHIN_LOCK_WAIT (seconds, default 600); set
        # MELEE_DOLPHIN_LOCK=0 to bypass in an emergency.
        if os.environ.get("MELEE_DOLPHIN_LOCK", "1") != "0":
            from . import dolphin_lock
            wait = float(os.environ.get("MELEE_DOLPHIN_LOCK_WAIT", "600"))
            self.log("acquiring the machine-wide Dolphin lock...")
            purpose = f"DolphinBoot {os.path.basename(str(self.iso_path))}"
            if self.stop_event is None:
                dolphin_lock.acquire(purpose, wait=wait)
                self._holds_lock = True
            else:
                deadline = time.monotonic() + max(0, wait)
                while True:
                    self.check_cancelled()
                    try:
                        dolphin_lock.acquire(purpose, wait=0)
                        self._holds_lock = True
                        break
                    except dolphin_lock.BusyError:
                        if time.monotonic() >= deadline:
                            raise
                        self.stop_event.wait(0.25)
            self._use_slot_pipe()
            # A Dolphin launched WITHOUT the lock (pre-lock code, or the
            # user's own window) still owns the screen/input: queue behind it
            # instead of double-launching. A multi-slot machine runs sibling
            # harness Dolphins by design, so a running one is not a reason to
            # wait there: each slot owns its lock, pipe and User dir.
            if dolphin_lock.slot_count() > 1:
                pass
            elif self.stop_event is not None:
                deadline = time.monotonic() + max(0, wait)
                while dolphin_running():
                    self.check_cancelled()
                    if time.monotonic() >= deadline:
                        raise RuntimeError(DOLPHIN_OPEN_MSG)
                    self.stop_event.wait(0.25)
            elif dolphin_running() and not wait_until_no_dolphin(log=self.log, timeout=wait):
                self._release_lock()
                raise RuntimeError(
                    "another Dolphin (launched outside the lock) is still "
                    "running after the wait -- close it, or raise "
                    "MELEE_DOLPHIN_LOCK_WAIT")
        self.check_cancelled()
        args = [self.exe, "-u", str(self.user_dir), "-b", "-e", self.iso_path]
        self.log(f"launching: {args}")
        from core.child_env import child_environment
        self.proc = subprocess.Popen(
            args, cwd=os.path.dirname(self.exe),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=child_environment(),
        )
        self._arm_deadline()
        on_launch = ON_LAUNCH.get()
        if on_launch is not None:
            try:
                on_launch(self.proc.pid, self.exe)
            except Exception as exc:
                self.log(f"launch hook failed: {exc}")
        # Register as the embeddable Dolphin so the frontend's "test in game"
        # panel can pin our render window inside the app (shared/ingame/embed.py).
        try:
            from . import embed
            embed.set_active(self.proc.pid, process=self.proc)
        except Exception:
            pass
        return self.proc

    def _arm_deadline(self):
        """A run that sets `deadline` never keeps its Dolphin longer than that.

        Every wait in a run has its own time limit, but a call that blocks has
        none (a controller write to a Dolphin that has stopped responding), and
        nothing above the run was counting: on 2026-11-10 one pause capture
        held its Dolphin and the machine-wide lock for three hours. Ending the
        process is what frees such a run: its calls fail, it returns its
        failure, and its own cleanup() releases the lock. So the timer ends the
        one process this boot launched, through the retained handle, and does
        nothing else: no cleanup and no lock release from the timer thread.
        """
        if not self.deadline or self.proc is None:
            return
        timer = threading.Timer(float(self.deadline), self._end_at_deadline,
                                args=(self.proc,))
        timer.daemon = True
        self._deadline_timer = timer
        timer.start()

    def _end_at_deadline(self, proc):
        if proc is not self.proc or proc.poll() is not None:
            return
        self.timed_out = True
        self.log(f"deadline: Dolphin pid {proc.pid} is still running after "
                 f"{float(self.deadline):.0f}s; ending it")
        try:
            from . import embed
            embed.park(proc.pid)        # as terminate(): a dying window flashes
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            pass
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass

    @property
    def pid(self):
        return self.proc.pid if self.proc else None

    def alive(self):
        """True while the launched Dolphin process is still running."""
        return self.proc is not None and self.proc.poll() is None

    def check_graphics_startup(self):
        """Fail promptly on a known native graphics error from our own process.

        Controller/RAM availability is not proof that graphics initialized.
        Polling is throttled to twice a second and never inspects unrelated PIDs.
        """
        self.check_cancelled()
        if not self.alive() or os.name != "nt":
            return
        now = time.monotonic()
        if now < self._next_graphics_check:
            return
        self._next_graphics_check = now + 0.5
        failure = read_graphics_failure(self.proc.pid)
        if failure and self.alive():
            self.log(failure)
            raise DolphinGraphicsError(failure)

    def open_pipe(self, timeout=12.0):
        r"""Open the controller pipe (Pipe(self.pipe_index)) the ROBUST way:
        retrying across the brief windows where Dolphin has torn the pipe down to
        re-arm it on a controller refresh (game boot / stage load). wait_for_pipe
        only confirms the pipe was up at one earlier moment; by the time we open
        it for real -- after the up-to-20s memory-attach loop -- it may be mid
        re-arm, which used to surface as "CreateFile(...slippibot1) failed: 2".
        Bails fast if Dolphin has exited. Raises OSError if it never comes up.
        In memory mode this compatibility entry point returns MemoryInput;
        no Windows pipe is opened."""
        if self.input_backend == "memory":
            if not self._wait_for_memory_input(timeout):
                raise OSError("Memory input hook never became ready (unsupported or conflicting game code)")
            return self._memory_input
        def alive():
            self.check_cancelled()
            return self.alive()
        return Pipe(self.pipe_index, open_timeout=timeout, alive=alive)

    def wait_for_pipe(self, timeout=45.0):
        r"""Dolphin only creates \\.\pipe\slippibot<N> once its input plugin
        initialises (~when the game starts booting); a fixed sleep races it.
        Probe the pipe until it opens.

        Polled at 50 ms, not 600 ms: the 600 ms poll was granularity, not
        necessity -- the pipe could be live for half a second before anyone
        noticed, on the critical path of every boot. Probing is a cheap
        CreateFile against a named pipe. Memory mode waits for its RAM hook's
        heartbeat instead, without probing the global pipe namespace."""
        if self.input_backend == "memory":
            return self._wait_for_memory_input(timeout)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                return False  # Dolphin exited during boot
            self.check_graphics_startup()
            h = pipe_open(self.pipe_index)
            if h is not None:
                pipe_close(h)
                return True
            time.sleep(0.05)
        return False

    def _wait_for_memory_input(self, timeout):
        """Compatibility for existing callers: readiness means a live pad hook.

        No global named-pipe probe/open is allowed in this backend. Resolve
        MEM1 from the retained child PID and require an advancing raw-pad poll.
        """
        if self._memory_input is not None:
            return True
        from .melee_mem import Dolphin
        from .memory_input import MemoryInput, mailbox_address, HEARTBEAT
        d = Dolphin(self.pid)
        deadline = time.monotonic() + timeout
        previous = None
        try:
            while time.monotonic() < deadline and self.alive():
                self.check_graphics_startup()
                if d.base is not None or d.locate():
                    address = mailbox_address(d)
                    if address is not None:
                        count = d.u32(address + HEARTBEAT)
                        if previous is not None and count is not None and count != previous:
                            self._memory_input = MemoryInput(d, address, alive=self.alive)
                            self.log(f"memory input ready: pid={self.pid}, mailbox={address:#x}")
                            return True
                        previous = count
                time.sleep(0.05)
        finally:
            if self._memory_input is None:
                d.close()
        return False

    def terminate(self):
        timer, self._deadline_timer = getattr(self, "_deadline_timer", None), None
        if timer is not None:
            timer.cancel()
        if self._memory_input is not None:
            try:
                self._memory_input.close()
            except Exception as exc:
                self.log(f"memory input close: {exc}")
            finally:
                self._memory_input = None
        if self.proc:
            try:
                from . import embed
                # Park the render window offscreen BEFORE killing the process:
                # a dying GL window flashes black wherever it sits (very visible
                # when it's pinned topmost over the app by the embed).
                if self.proc.poll() is None:
                    embed.park(self.proc.pid)
                embed.clear_active(self.proc.pid)
            except Exception:
                pass
        if self.proc and self.proc.poll() is None:
            pid = self.proc.pid
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                pass
            if self.proc.poll() is None:
                # Use the retained handle for the Dolphin we launched. Never
                # expand cleanup to a process tree or match an executable name.
                try:
                    self.proc.kill()
                    self.proc.wait(timeout=5)
                except Exception:
                    pass
        # Free this boot's depth of the machine-wide Dolphin slot. A second
        # terminate, or one after a failed prepare, must not spend a depth an
        # outer caller (verify_costume's coordinator) still holds.
        self._release_lock()

    def _release_lock(self):
        if not getattr(self, "_holds_lock", False):
            return
        self._holds_lock = False
        try:
            from . import dolphin_lock
            dolphin_lock.release()
        except Exception:
            pass

    def cleanup(self):
        self.terminate()
        self.saved_log = None
        if self.run_dir and self.run_dir.exists():
            # keep the OSReport log next to the runs root (the run dir itself goes)
            src = self.run_dir / "User" / "Logs" / "dolphin.log"
            if src.is_file() and src.stat().st_size > 0:
                dst = self.runs_root / f"{self.run_dir.name}-dolphin.log"
                try:
                    shutil.copy2(src, dst)
                    self.saved_log = dst
                    self.log(f"OSReport log kept: {dst}")
                except OSError:
                    pass
            shutil.rmtree(self.run_dir, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cleanup()
        return False
