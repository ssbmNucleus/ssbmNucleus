"""The Slippi Launcher's playback Dolphin: where it is, the vanilla ISO beside it, its User dir, and
the INI settings a watch needs (dump flags, render window, video backend, recording aspect, and the
per-user Gecko overrides for hidden names, widescreen and no music)."""

import glob
import os
import sys


def _launcher_playback_dir():
    """The Slippi Launcher's playback-build folder for this OS, or None.
    Delegates to shared.ingame.boot.launcher_dir — the single per-OS definition."""
    from shared.ingame.boot import launcher_dir
    return launcher_dir("playback")


def playback_dolphin_path():
    """Full path to the Launcher's PLAYBACK Dolphin executable, or None.

    Watch-with-mods needs the playback build specifically (it takes the -i comm
    file); the netplay build is not a substitute, so this does not fall back to
    shared.ingame.boot.resolve_dolphin (which prefers netplay)."""
    from shared.ingame.boot import playback_exe_in
    return playback_exe_in(_launcher_playback_dir())


def launcher_vanilla_iso():
    """The vanilla ISO to build watch ISOs from: the Slippi Launcher's
    configured ISO when present, else the app's own recorded vanilla ISO
    (Settings → first-run setup). The launcher path only exists where the
    Launcher is installed and configured, so the app record is what makes
    Watch work on a machine where Nucleus was set up first."""
    from tracker.store import identity
    settings = identity.read_launcher_settings().get("settings") or {}
    iso = settings.get("isoPath")
    if iso and os.path.exists(iso):
        return iso
    from shared.vanilla_extract import vanilla_refs
    known = vanilla_refs.known_vanilla_iso()
    return str(known) if known else None


def _playback_user_dir():
    """The playback Dolphin's User dir (Config/, Dump/, GameSettings/…).

    Windows playback is portable: <playback>/User. Off Windows there is no
    User/ beside the AppImage (unless extracted); the playback build keeps its
    own XDG tree SEPARATE from netplay's SlippiOnline — writing into the wrong
    one silently disables recording flags, so prefer a real portable User/
    when present, else the per-OS playback config dir."""
    d = _launcher_playback_dir()
    if os.name == "nt":
        return os.path.join(d, "User") if d else None
    if d and os.path.isdir(os.path.join(d, "User")):
        return os.path.join(d, "User")
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Application Support",
                            "com.project-slippi.dolphin", "playback", "User")
    return os.path.join(home, ".config", "SlippiPlayback")


def _set_ini_keys(ini_path, updates):
    """Minimal INI edit preserving unknown lines: updates = {(section, key): value}.
    Missing sections/keys are appended. Dolphin's ini parser is forgiving, so a
    line-based edit is safer than configparser round-tripping."""
    lines = []
    if os.path.exists(ini_path):
        with open(ini_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    pending = dict(updates)
    out, section = [], None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            # leaving a section: append any keys it was still missing
            for (s, k) in [sk for sk in pending if sk[0] == section]:
                out.append(f"{k} = {pending.pop((s, k))}")
            section = stripped[1:-1]
            out.append(line)
            continue
        key = stripped.split("=", 1)[0].strip() if "=" in stripped else None
        if key and (section, key) in pending:
            out.append(f"{key} = {pending.pop((section, key))}")
        else:
            out.append(line)
    for (s, k) in [sk for sk in pending if sk[0] == section]:
        out.append(f"{k} = {pending.pop((s, k))}")
    for (s, k), v in pending.items():
        out.extend(["", f"[{s}]", f"{k} = {v}"])
    os.makedirs(os.path.dirname(ini_path), exist_ok=True)
    with open(ini_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


_DUMP_KEYS = {("Movie", "DumpFrames"): None, ("DSP", "DumpAudio"): None}


def _dolphin_ini():
    user = _playback_user_dir()
    if not user:
        raise RuntimeError("no APPDATA — cannot find the playback Dolphin's User dir")
    return os.path.join(user, "Config", "Dolphin.ini")


def _set_dump_flags(enabled, ini=None):
    """Frame and audio dumping on or off (``ini``: the Dolphin.ini, when known)."""
    val = "True" if enabled else "False"
    _set_ini_keys(ini or _dolphin_ini(), {k: val for k in _DUMP_KEYS})


def _force_render_window():
    """The embed needs Dolphin to open a DEDICATED render window. With
    RenderToMain=True (the default on some installs) the game renders inside
    the GUI shell — a window with child windows, which window discovery
    correctly refuses to embed — so the modal waits forever on "the game
    appears here once Dolphin boots". Forced off before every launch."""
    user = _playback_user_dir()
    if not user:
        return
    try:
        _set_ini_keys(os.path.join(user, "Config", "Dolphin.ini"),
                      {("Display", "RenderToMain"): "False"})
    except OSError:
        pass  # playback still works, just not embedded


# Dolphin's video backend lives in Dolphin.ini [Core] GFXBackend -- NOT in
# GFX.ini, which is the usual first guess and has no Backend key at all.
_BACKEND_KEY = ("Core", "GFXBackend")
_SAFE_BACKEND = "OGL"


def _ensure_video_backend():
    """Give Dolphin an explicit video backend if it has none.

    With GFXBackend absent OR EMPTY, Dolphin falls back to its compiled-in
    default, which on Windows is Direct3D 11. On a machine that cannot create
    a D3D11 device that is a modal "Failed to initialize Direct3D" dialog over
    a black window, before a single frame plays.

    This is our problem specifically because _force_render_window() CREATES
    Dolphin.ini when it does not exist -- so for anyone who installed the
    playback build through the Slippi Launcher but never launched it, Nucleus
    authors the very file that has no backend in it, and we are the first
    thing they ever meet the failure through.

    OGL is the safe default: it is what Slippi's playback build ships with in
    practice and it works on every GPU that can run Melee.

    ONLY when absent or empty. A deliberate choice -- D3D, Vulkan, anything --
    is never overwritten. Note the empty case is why this tests falsiness and
    not `is None`: _read_ini_key returns "" for `GFXBackend = `, which is a
    real and common state (it is what the netplay build ships with), and an
    `is not None` check would skip exactly the machines that need this.
    """
    user = _playback_user_dir()
    if not user:
        return
    ini = os.path.join(user, "Config", "Dolphin.ini")
    try:
        if not _read_ini_key(ini, *_BACKEND_KEY):
            _set_ini_keys(ini, {_BACKEND_KEY: _SAFE_BACKEND})
    except OSError:
        pass  # never block playback over a config nicety


# Dolphin: 0=Auto, 1=Force 16:9, 2=Force 4:3, 3=Stretch to Window.
_ASPECT_KEY = ("Settings", "AspectRatio")
_ASPECT_FORCE_4_3 = "2"
_ASPECT_FORCE_16_9 = "1"


def _read_ini_key(ini_path, section, key):
    """Current value of one INI key, or None if the section/key is absent."""
    if not os.path.exists(ini_path):
        return None
    cur = None
    with open(ini_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if s.startswith("[") and s.endswith("]"):
                cur = s[1:-1]
            elif cur == section and "=" in s and s.split("=", 1)[0].strip() == key:
                return s.split("=", 1)[1].strip()
    return None


def _gfx_ini():
    """The playback Dolphin's GFX.ini (where AspectRatio lives), or None."""
    user = _playback_user_dir()
    return os.path.join(user, "Config", "GFX.ini") if user else None


def _force_aspect(ini, widescreen=False):
    """Force 4:3 (16:9 with ``widescreen``) in the playback Dolphin while
    dumping frames or watching widescreen. The caller reads the old value first
    and puts it back with _restore_aspect.

    The framedump inherits Dolphin's render target, and playback Dolphin runs
    EMBEDDED in a narrow modal panel — left alone, clips dump at the panel's
    aspect (observed 462x480) and play back horizontally squished. ffmpeg's
    `scale=-2:480` preserves whatever aspect it is handed, so this has to be
    corrected at the source.
    """
    _set_ini_keys(ini, {_ASPECT_KEY: _ASPECT_FORCE_16_9 if widescreen else _ASPECT_FORCE_4_3})


def _restore_aspect(ini, prior):
    """Put back the value _force_aspect replaced: ``prior`` as read before it,
    or Dolphin's default (0 = Auto) when the key was absent. Idempotent."""
    _set_ini_keys(ini, {_ASPECT_KEY: prior if prior is not None else "0"})


def _clear_old_dumps():
    user = _playback_user_dir()
    if not user:
        return
    for sub, pattern in (("Frames", "framedump*.avi"), ("Audio", "*.wav")):
        for f in glob.glob(os.path.join(user, "Dump", sub, pattern)):
            try:
                os.remove(f)
            except OSError:
                pass


# The playback ISO's game id is vanilla 1.02 NTSC = GALE01, revision 2.
_PLAYBACK_GAME_IDS = ("GALE01r2", "GALE01")
# Slippi's "$Optional: Show Player Names" playback Gecko code injects each
# player's Slippi display name as an in-game HUD element. Disabling it via a
# per-user GameSettings override anonymizes the recording — no replay editing.
_SHOW_NAMES_CODE = "$Optional: Show Player Names"
# The playback Dolphin ships this code in its Sys GameSettings but leaves it
# off. Enabling it renders the game at 16:9; Dolphin must also be told the
# picture is 16:9 (AspectRatio=1), or it squeezes it back into 4:3.
_WIDESCREEN_CODE = "$Optional: Widescreen 16:9"
# Also shipped (off) in the playback Sys GameSettings: one 04 write at
# 0x80023FFC, inside lbAudioAx_80023F28 (the BGM stream starter), turning
# `li r4, 0x7F` (VOL_MAX) into `li r4, 0`. Every stage/menu song still starts,
# just at volume 0; SFX, voices and the announcer go through fn_80023750 and
# are untouched. Audio only — no gameplay state, so replays stay in sync.
_NO_MUSIC_CODE = "$Optional: Game Music OFF"
_MARKER = "SSBM Nucleus"


def _game_settings_dir():
    """The playback Dolphin's per-user GameSettings folder, or None."""
    user = _playback_user_dir()
    return os.path.join(user, "GameSettings") if user else None


def _user_overrides(gs_dir):
    """The user's own override files that write_playback_overrides would
    replace, {game id: text} (latin-1, so any bytes come back unchanged)."""
    found = {}
    for gid in _PLAYBACK_GAME_IDS:
        try:
            with open(os.path.join(gs_dir, f"{gid}.ini"), "rb") as f:
                data = f.read()
        except OSError:
            continue
        if _MARKER.encode() not in data.split(b"\n", 1)[0]:
            found[gid] = data.decode("latin-1")
    return found


def write_playback_overrides(gs_dir, hide_names=False, widescreen=False, no_music=False):
    """The playback options as one per-user GameSettings override: hiding
    names disables the Show Player Names code (anonymizes a recording, no
    replay editing); widescreen and no_music enable Slippi's shipped codes.
    Read _user_overrides first: this replaces a user's own file."""
    os.makedirs(gs_dir, exist_ok=True)
    # Dolphin adds [Gecko_Enabled] to the Sys defaults and drops anything
    # listed under [Gecko_Disabled].
    enabled = ([_WIDESCREEN_CODE] if widescreen else []) + ([_NO_MUSIC_CODE] if no_music else [])
    disabled = [_SHOW_NAMES_CODE] if hide_names else []
    for gid in _PLAYBACK_GAME_IDS:
        with open(os.path.join(gs_dir, f"{gid}.ini"), "w", encoding="utf-8") as f:
            f.write(
                f"# Written by {_MARKER} (Watch options) — safe to delete.\n"
                "[Gecko_Enabled]\n" + "".join(c + "\n" for c in enabled) + "\n"
                "[Gecko_Disabled]\n" + "".join(c + "\n" for c in disabled)
            )


def remove_playback_overrides(gs_dir, user_files=None):
    """Delete the override files Nucleus wrote, then put back the user's own
    that they replaced (``user_files``, from _user_overrides). Idempotent."""
    for gid in _PLAYBACK_GAME_IDS:
        ini = os.path.join(gs_dir, f"{gid}.ini")
        try:
            with open(ini, "rb") as f:
                ours = _MARKER.encode() in f.readline()
            if ours:
                os.remove(ini)
        except OSError:
            pass
        text = (user_files or {}).get(gid)
        if text is not None and os.path.isdir(gs_dir) and not os.path.exists(ini):
            with open(ini, "wb") as f:
                f.write(text.encode("latin-1"))
