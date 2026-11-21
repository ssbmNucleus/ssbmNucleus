"""Slippi identity discovery for nucleOME mode.

Reads the Slippi Launcher's own config files to answer two questions:
  - where do the user's replays live? (Settings -> settings.rootSlpPath)
  - who is the user online? (netplay user.json -> displayName/connectCode/uid)

PRIVACY: user.json also contains `playKey`, the user's netplay auth secret.
This module extracts ONLY the identity fields and never returns, stores, or
logs anything else from that file.
"""
import json
import os
import sys

SAFE_USER_FIELDS = ("displayName", "connectCode", "uid")


def _launcher_dir(*parts):
    """The Slippi Launcher's electron config dir for this OS, or None.
    Delegates to shared.ingame.boot.launcher_dir — the single per-OS definition."""
    from shared.ingame.boot import launcher_dir
    return launcher_dir(*parts)


def read_launcher_settings():
    """Slippi Launcher electron-store Settings file (JSON, no extension).
    Delegates to shared.ingame.boot.read_launcher_settings — the single reader."""
    from shared.ingame.boot import read_launcher_settings as read
    return read()


def _documents_dir():
    """The real Documents folder. On Windows this must go through the shell
    API — OneDrive "Known Folder Move" redirects Documents away from
    ~/Documents, and the Slippi Launcher (Electron) follows that redirect
    when it picks its default replay folder."""
    if os.name == "nt":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            # CSIDL_PERSONAL = 5 (Documents), SHGFP_TYPE_CURRENT = 0
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
                return buf.value
        except OSError:
            pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def get_replay_root():
    """The launcher-configured replay directory, or the Documents fallback."""
    settings = read_launcher_settings().get("settings") or {}
    root = settings.get("rootSlpPath")
    if root and os.path.isdir(root):
        return root
    fallback = os.path.join(_documents_dir(), "Slippi")
    return fallback if os.path.isdir(fallback) else None


def replay_root(conn):
    """The folder the index scans: the user's kv override if it still exists,
    else launcher auto-detection (get_replay_root)."""
    from . import indexer
    override = indexer.kv_get(conn, "replay_root_override")
    if override and os.path.isdir(override):
        return override
    return get_replay_root()


def get_launcher_accounts():
    """Display names of accounts known to the launcher (no codes stored there)."""
    accounts = read_launcher_settings().get("accounts") or {}
    return [a.get("displayName") for a in accounts.get("list") or [] if a.get("displayName")]


def _netplay_user_json_candidates():
    """Where the netplay Dolphin's user.json can live, most likely first.

    Windows netplay Dolphin is portable (<launcher>/netplay/User/...); off
    Windows the config tree is XDG/Application Support — shared.ingame.boot's
    _dolphin_user_root() already encodes that per-OS layout."""
    out = []
    portable = _launcher_dir("netplay", "User", "Slippi", "user.json")
    if portable:
        out.append(portable)
    if os.name != "nt":
        try:
            from shared.ingame.boot import _dolphin_user_root
            out.append(str(_dolphin_user_root() / "Slippi" / "user.json"))
        except ImportError:
            pass
    return out


def get_netplay_identity():
    """Active netplay identity from user.json — identity fields ONLY."""
    path = next((p for p in _netplay_user_json_candidates()
                 if os.path.exists(p)), None)
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f) or {}
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: data.get(k) for k in SAFE_USER_FIELDS if data.get(k)}


def login_code():
    """The active login's connect code, or None."""
    code = (get_netplay_identity().get("connectCode") or "").strip().upper()
    return code or None


def seen_login_codes(conn):
    """Slippi supports multiple logins but only the ACTIVE account's code is
    on disk (user.json is rewritten on switch). So we accumulate: a code seen
    in user.json is remembered as a login of this user and counts as "you"
    after a switch too. Only the active login is locked. A past login can be
    removed (set_codes), since it may be a friend who signed in once on this
    computer; it is then forgotten until it is the active login again, when
    this call records it afresh. Returns (seen, active)."""
    from . import indexer
    seen = indexer.kv_get(conn, "seen_login_codes") or []
    active = login_code()
    if active and active not in seen:
        seen = seen + [active]
        indexer.kv_set(conn, "seen_login_codes", seen)
    return seen, active


def set_codes(conn, codes, active=None):
    """Make exactly `codes` count as "me", plus the active login, which is
    always kept. A past login missing from `codes` is forgotten; a code that
    is not a login becomes a manual extra. Returns the codes now counted.

    Both lists are written in one transaction: they change together or not at
    all. `active` is the caller's seen_login_codes() answer, so user.json is
    read once per change."""
    from . import indexer
    wanted = []
    for c in codes:
        c = (c or "").strip().upper()
        if c and c not in wanted:
            wanted.append(c)
    seen = [c for c in (indexer.kv_get(conn, "seen_login_codes") or [])
            if c in wanted or c == active]
    if active and active not in seen:
        seen.append(active)
    extras = [c for c in wanted if c not in seen]
    with conn:
        for key, value in (("seen_login_codes", seen), ("user_codes", extras)):
            conn.execute(
                "INSERT INTO kv(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)))
    return seen + extras


def known_user_codes(conn):
    """The codes already recorded as "me" (logins seen and not removed, plus
    manual extras), read-only: unlike user_codes it never records the active
    login."""
    from . import indexer
    codes = list(indexer.kv_get(conn, "seen_login_codes") or [])
    for c in indexer.kv_get(conn, "user_codes") or []:
        if c and c not in codes:
            codes.append(c)
    return codes


def user_codes(conn):
    """All codes that count as "me": logins seen and not removed (the active
    one always) + manual extras."""
    from . import indexer
    codes, _active = seen_login_codes(conn)
    for c in indexer.kv_get(conn, "user_codes") or []:
        if c and c not in codes:
            codes.append(c)
    return codes
