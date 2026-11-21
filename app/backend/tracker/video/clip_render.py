"""clip_render — data for in-app "Watch Lite" (in-browser character clips).

The frontend renders a replay/combo window as animated 2D characters (see
frontend/src/tracker/replays/meleeRender.js) instead of launching Dolphin. This module supplies the two
things the browser can't derive from a bundle alone:

  charmaps()          action->animation maps + state-name table (tools/charmaps.json)
  anims_for_clip(b)   the SVG-path animation frames a specific clip actually uses

Geometry source = slippilab's per-character animation zips (MIT code; the outline
geometry is game-derived). These are BUNDLED into the app: PyInstaller ships
tools/charmaps.json + tools/anim_zips/*.zip inside the backend exe (see
mex_backend.spec), so Watch Lite works for end users out of the box. The zips stay
git-untracked (tools/anim_zips/.gitignore) so they never enter the PUBLIC source
mirror (release_to_public.py copies only tracked files) while the built installer
still includes them. When they're missing anyway (fresh dev checkout, build made
without them staged), anim_fetch downloads them from the slippilab repo into the
user-writable STORAGE_PATH/nucleome/anim_zips — during first-run setup and as a
background thread at backend start (see zip_path()'s search order). Regenerating this geometry from the user's own ISO via HSDRaw
was spiked and deferred (feasible + fast, but needs cross-character QA; see
tools/RENDERER.md). If revisited, only the geometry source changes; this interface
stays.
"""
import json
import os
import sys
import threading
import zipfile

if getattr(sys, "frozen", False):  # PyInstaller bundle (see mex_backend.spec)
    TOOLS_DIR = os.path.join(sys._MEIPASS, "backend", "tracker", "tools")
else:
    # tracker/video/ -> the renderer data stays at tracker/tools (one level up)
    TOOLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
CHARMAPS_PATH = os.path.join(TOOLS_DIR, "charmaps.json")
_BUNDLED_ZIPS_DIR = os.path.join(TOOLS_DIR, "anim_zips")


def user_zips_dir():
    """Writable download target for the zips (first-run setup fetches them
    here when a build didn't bundle them — the PyInstaller bundle is
    read-only)."""
    from core.config import STORAGE_PATH
    return os.path.join(str(STORAGE_PATH), "nucleome", "anim_zips")


def _dir_has_zips(d):
    try:
        return any(n.endswith(".zip") for n in os.listdir(d))
    except OSError:
        return False


def _zip_dirs():
    return (os.environ.get("NUCLEOME_ANIM_ZIPS"), _BUNDLED_ZIPS_DIR,
            user_zips_dir())


def zips_dir():
    """First location that actually holds animation zips: env override, the
    bundled/dev tools dir, then the user-data copy downloaded by first-run
    setup. None when no zips exist anywhere (Watch Lite falls back to dots)."""
    for d in _zip_dirs():
        if d and _dir_has_zips(d):
            return d
    return None


def zip_path(name):
    """Absolute path of one character's zip, searching every candidate dir —
    a bundled partial set and a downloaded remainder may coexist."""
    for d in _zip_dirs():
        if d:
            p = os.path.join(d, name + ".zip")
            if os.path.exists(p):
                return p
    return None

# internal char id -> zip basename (slippilab actionMapByInternalId order)
_INT_TO_ZIP = ["mario", "fox", "captainFalcon", "donkeyKong", "kirby", "bowser",
               "link", "sheik", "ness", "peach", "iceClimbers", "iceClimbers",
               "pikachu", "samus", "yoshi", "jigglypuff", "mewtwo", "luigi",
               "marth", "zelda", "youngLink", "doctorMario", "falco", "pichu",
               "mrGameAndWatch", "ganondorf", "roy"]

_charmaps = None
_anim_cache = {}                       # cid -> {animName: [svg path per frame]}
_lock = threading.Lock()


def charmaps():
    global _charmaps
    if _charmaps is None:
        with open(CHARMAPS_PATH, encoding="utf-8") as f:
            _charmaps = json.load(f)
    return _charmaps


def zips_available():
    return os.path.exists(CHARMAPS_PATH) and zips_dir() is not None


def _anim_name(cm, cid, state):
    ch = cm["chars"].get(str(cid))
    if not ch:
        return None
    action = (cm["actionNameById"][state]
              if state < len(cm["actionNameById"]) else None)
    return (ch["animationMap"].get(action) or ch["specialsMap"].get(str(state))
            or action)


def _fallback_name(name):
    """Mirror of meleeRender.js fallbackFor: the stand-in animation drawn when
    slippilab's geometry has none for a real action (throw victims, Yoshi's
    shield, Jigglypuff's crouch, grab specials). Shipped alongside the mapped
    name so the renderer's fallback has frames to draw."""
    if not name:
        return None
    if name == "SquatWait":
        return "SquatWait1"
    if name == "Guard":
        return "GuardOn"
    if name.startswith("Thrown"):
        return "DamageFlyN"
    if name.startswith("Capture") or name == "YoshiEgg":
        return "CaptureWaitHi"
    return None


def _load_char(cid):
    """Full animation set for one internal char id (cached). Empty if no zip;
    a miss is not cached, so a zip the downloader adds later is found."""
    hit = _anim_cache.get(cid)
    if hit is not None:
        return hit
    with _lock:
        hit = _anim_cache.get(cid)
        if hit is not None:
            return hit
        out = {}
        if 0 <= cid < len(_INT_TO_ZIP):
            path = zip_path(_INT_TO_ZIP[cid])
            if path:
                with zipfile.ZipFile(path) as z:
                    for name in z.namelist():
                        out[name[:-5]] = json.loads(z.read(name))
        if out:
            _anim_cache[cid] = out
        return out


def anims_for_clip(bundle):
    """Only the animations this clip's (cid, state) pairs resolve to — keeps the
    payload to what's on screen, not a full 4 MB character."""
    cm = charmaps()
    need = {}                          # cid -> set(animName)
    f = bundle["frames"]
    for i in range(len(f["cid"])):     # 1v1 or doubles/FFA (2..4 ports)
        for cid, state in zip(f["cid"][i], f["state"][i]):
            nm = _anim_name(cm, cid, state)
            if nm:
                need.setdefault(cid, set()).add(nm)
                fb = _fallback_name(nm)
                if fb:
                    need[cid].add(fb)
    # ICs Nana: follower rows carry their own (cid, state) pairs, with nulls
    # on frames where she is dead/absent.
    for fo in f.get("fol", []):
        for cid, state in zip(fo["cid"], fo["state"]):
            if cid is None or state is None:
                continue
            nm = _anim_name(cm, cid, state)
            if nm:
                need.setdefault(cid, set()).add(nm)
                fb = _fallback_name(nm)
                if fb:
                    need[cid].add(fb)
    out = {}
    for cid, names in need.items():
        full = _load_char(cid)
        out[str(cid)] = {nm: full[nm] for nm in names if nm in full}
    return out
