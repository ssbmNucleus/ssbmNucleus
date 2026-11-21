"""control_cache.py -- a persistent, on-disk library of INVARIANT capture shots.

Why this exists
---------------
Every ported costume is judged against its donor's UNTOUCHED vanilla fighter at
the same move, frame, camera and background. That control image can never
change -- and yet it was re-rendered every session: 7 of 26 targets in the
2026-07-30 grading run were vanilla controls (~27 % of a 584 s run), and
`verify_mon.py` additionally burned a SECOND Dolphin boot per mon purely to shoot
its control.

The key rule
------------
**The key must cover every parameter that can change the pixels.** A cached
control paired against a mon shot with a different camera distance, background,
frame or resolution is a silently invalid comparison -- and "the evidence sheet
is the bug" is the single most expensive recurring failure on this project. A key
collision here is worse than having no cache at all. So the key is a hash of the
FULL capture spec:

  character, ckind, costume colour, move, requested frame, orbit yaw, closeup
  on/off, cam dist/fov/height/side/pitch, plain-bg colour, stage, image width,
  aerial rise, bag (char/colour/offset), kirby-copy donor, scheduled mid-move
  inputs -- plus `env`, an identifier for the ISO's actual RENDER ENVIRONMENT.

`env` is a content hash of the files that decide how that vanilla fighter is
drawn in that build:

  main.dol            engine + m-ex core (an Ace-build vs vanilla-m-ex base)
  Pl<XX>.dat          the fighter's data/model
  Pl<XX>AJ.dat        its animations (the move frames themselves)
  Pl<XX><Cc>.dat      the vanilla costume DAT for this colour slot
  Gr<..>.dat          the stage

It deliberately does NOT hash the whole ISO: added mon costumes are NEW files
that cannot affect how the vanilla slot renders, and hashing the disc would
invalidate every control on every rebuild -- which is the same as having no
cache. It DOES hash everything that can.

Layout (persistent, gitignored -- regenerable image data):

  <root>/<char>/<key>.png     the image
  <root>/<char>/<key>.json    the full spec + provenance (so a stale or
                              mis-keyed entry is detectable by inspection)
  <root>/_env.json            memo of env hashes (keyed by iso size+mtime)

Root: $NUCLEUS_CONTROL_CACHE, else <app>/scratch/ingame/control-cache.

CLI:
  python -m shared.ingame.control_cache --list
  python -m shared.ingame.control_cache --verify          # re-hash every PNG
  python -m shared.ingame.control_cache --purge           # drop everything
  python -m shared.ingame.control_cache --purge --char drmario
  python -m shared.ingame.control_cache --purge --env <envhash>
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]          # backend/shared/ingame -> backend
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import file_retry  # noqa: E402  (after the path setup: this also runs as a script)

SCHEMA = 3      # 3: `autofit` joined the key (frameshot re-frames clipped shots)

# --- where ------------------------------------------------------------------ #


def cache_root() -> Path:
    env = os.environ.get("NUCLEUS_CONTROL_CACHE")
    if env:
        return Path(env)
    # backend/shared/ingame -> backend -> app ; app/scratch is gitignored and cleanable
    # (tools/clean.py), so a regenerable cache belongs there.
    return BACKEND.parent / "scratch" / "ingame" / "control-cache"


# --- render-environment identity -------------------------------------------- #
# char_select's normalised name -> the fighter's Pl file code.
CHAR_CODE = {
    "falcon": "Ca", "falco": "Fc", "fox": "Fx", "marth": "Ms", "roy": "Fe",
    "bowser": "Kp", "dk": "Dk", "ganondorf": "Gn", "jigglypuff": "Pr",
    "kirby": "Kb", "link": "Lk", "luigi": "Lg", "mario": "Mr", "mewtwo": "Mt",
    "ness": "Ns", "peach": "Pe", "pichu": "Pc", "pikachu": "Pk",
    "iceclimbers": "Pp", "samus": "Ss", "sheik": "Sk", "yoshi": "Ys",
    "younglink": "Cl", "zelda": "Zd", "drmario": "Dr", "gameandwatch": "Gw",
}

STAGE_FILE = {
    "battlefield": "GrNBa.dat",
    "finaldestination": "GrNLa.dat",
    "dreamland": "GrOp.dat",
    "pokemonstadium": "GrPs.dat",
    "yoshisstory": "GrSt.dat",
    "fountainofdreams": "GrIz.dat",
}


def _color_order(char_norm):
    """Vanilla CSS costume-suffix order for a normalised character name."""
    from core.constants import VANILLA_CSS_COLOR_ORDER
    from shared.ingame.char_select import norm
    for display, order in VANILLA_CSS_COLOR_ORDER.items():
        if norm(display) == char_norm:
            return order
    return []


DOL = "<main.dol>"      # not an FST entry -- see _dol_range


def _dol_range(f):
    """(offset, size) of the boot DOL. It is NOT in the FST: the disc header
    holds its offset at 0x420, and the size has to be derived from the DOL's own
    section table (7 text + 11 data sections; size = max(offset+size)).

    This was worth doing properly. Looking main.dol up in the FST -- the obvious
    thing -- silently returns "not found", and a constant "MISSING" in the hash
    means an m-ex/engine change (vanilla core vs Ace core) would NOT invalidate
    the cache. That is precisely the silent mis-pairing this module exists to
    make impossible."""
    import struct
    f.seek(0x420)
    dol_off = struct.unpack(">I", f.read(4))[0]
    f.seek(dol_off)
    hdr = f.read(0x100)
    offs = struct.unpack(">18I", hdr[0x00:0x48])
    sizes = struct.unpack(">18I", hdr[0x90:0xD8])
    end = max([0x100] + [o + s for o, s in zip(offs, sizes) if o and s])
    return dol_off, end


def env_files(char_norm, color, stage):
    """The FST entry names whose bytes decide this control's pixels."""
    names = [DOL]
    code = CHAR_CODE.get(char_norm)
    if code:
        names += [f"Pl{code}.dat", f"Pl{code}AJ.dat"]
        order = _color_order(char_norm)
        if 0 <= int(color) < len(order):
            names.append(f"Pl{code}{order[int(color)]}.dat")
    sf = STAGE_FILE.get(str(stage).lower())
    if sf:
        names.append(sf)
    return names


_ENV_MEMO = {}


def _iso_stamp(iso: Path):
    st = iso.stat()
    return f"{iso.resolve()}|{st.st_size}|{st.st_mtime_ns}"


def env_id(iso, char_norm, color, stage, log=None):
    """Content hash of the render environment (see module docstring).

    Returns (hex12, detail) where `detail` maps file name -> sha1/'MISSING' so a
    cache entry can be audited without re-reading the disc. Memoised per process
    and on disk (keyed by the ISO's size+mtime), because verify_mon spawns one
    frameshot process per mon and each would otherwise re-read ~8 MB."""
    iso = Path(iso)
    key = (_iso_stamp(iso), char_norm, int(color), str(stage).lower())
    if key in _ENV_MEMO:
        return _ENV_MEMO[key]
    memo_path = cache_root() / "_env.json"
    memo = {}
    if memo_path.is_file():
        try:
            memo = json.loads(memo_path.read_text(encoding="utf-8"))
        except Exception:
            memo = {}
    mk = "|".join(str(x) for x in key)
    if mk in memo:
        got = (memo[mk]["id"], memo[mk]["files"])
        _ENV_MEMO[key] = got
        return got

    from shared.vanilla_extract.vanilla_refs import list_files_in_iso
    entries = {e["name"].lower(): e for e in list_files_in_iso(iso)}
    detail, h = {}, hashlib.sha1()
    with open(iso, "rb") as f:
        for name in env_files(char_norm, color, stage):
            if name == DOL:
                off, size = _dol_range(f)
            else:
                e = entries.get(name.lower())
                if not e:
                    # A file we declared load-bearing is not on the disc. Do NOT
                    # fold a "MISSING" placeholder into the hash and carry on --
                    # that would make the key blind to whatever went wrong.
                    raise FileNotFoundError(
                        f"{name} is not in {Path(iso).name}: the render "
                        f"environment cannot be identified, so nothing may be "
                        f"cached against it")
                off, size = e["offset"], e["size"]
            f.seek(off)
            data = f.read(size)
            if len(data) != size:
                raise ValueError(f"truncated read of {name} from {iso}")
            dg = hashlib.sha1(data).hexdigest()
            detail[name] = dg
            h.update(f"{name}:{dg}\n".encode())
    got = (h.hexdigest()[:12], detail)
    _ENV_MEMO[key] = got
    memo[mk] = {"id": got[0], "files": got[1], "cached": time.time()}
    try:
        memo_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = memo_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(memo, indent=1), encoding="utf-8")
        file_retry.replace(tmp, memo_path)
    except Exception:
        pass
    if log:
        log(f"control-cache env {got[0]} for {char_norm} c{color} on {stage}")
    return got


# --- the key ---------------------------------------------------------------- #
# EVERY field here changes pixels. Adding a capture knob without adding it here
# is how two shots taken under different settings collide on one key -- the
# failure this module is most responsible for preventing. If you add a flag to
# frameshot that touches the image, add it here and bump SCHEMA.
#
# `pipeline` deserves its own note. It is the FRAME BUDGET the capture path
# spends before a shot: how many game frames the harness rides out after the
# stage load, how many it spends letting the camera pan back after a recenter,
# how many it steps to settle the idle. Those are not cosmetic. An idle capture
# is a frame of a LOOPING Wait animation, so shifting the budget by n frames
# rotates the animation phase and changes the picture -- measured 2026-07-30:
# dropping the 60-frame camera pan moved the idle shots by mean 1.6-5.0 (up to
# 11 % of pixels) while every mid-move frame stayed bit-identical (jab 0.000).
# Within one run the mon and its control share the budget, so the comparison is
# always valid; ACROSS runs only this key field stops a control captured under
# an old budget from being served to a run using a new one.
SPEC_FIELDS = (
    "schema", "env", "pipeline", "char", "ckind", "color", "move", "frame",
    "yaw", "closeup", "cam_dist", "cam_fov", "cam_height", "cam_side",
    "cam_pitch", "plain_bg", "stage", "width", "rise", "bag", "kirby_copy",
    "input_at", "autofit",
)


def make_spec(*, env, char, ckind, color, move, frame, yaw, closeup, cam_dist,
              cam_fov, cam_height, cam_side, cam_pitch, plain_bg, stage, width,
              rise, pipeline=None, bag=None, kirby_copy=None, input_at=None,
              autofit=False):
    def f(v):
        return None if v is None else round(float(v), 4)
    return {
        "schema": SCHEMA, "env": str(env),
        "pipeline": (dict(sorted(pipeline.items())) if pipeline else None),
        "char": str(char),
        "ckind": int(ckind), "color": int(color), "move": str(move),
        "frame": int(frame), "yaw": f(yaw), "closeup": bool(closeup),
        "cam_dist": f(cam_dist), "cam_fov": f(cam_fov),
        "cam_height": f(cam_height), "cam_side": f(cam_side),
        "cam_pitch": f(cam_pitch),
        "plain_bg": (str(plain_bg).lower() if plain_bg else None),
        "stage": str(stage).lower(), "width": int(width), "rise": int(rise),
        "bag": bag, "kirby_copy": kirby_copy,
        "input_at": sorted(input_at) if input_at else None,
        # frameshot's autofit re-frames a subject the fixed camera clips, so it
        # can change the picture -- that makes it part of the key, not a detail.
        "autofit": bool(autofit),
    }


def key_of(spec) -> str:
    missing = [k for k in SPEC_FIELDS if k not in spec]
    if missing:
        raise ValueError(f"control-cache spec is missing {missing} -- an "
                         f"un-keyed parameter would let two different images "
                         f"share one entry")
    canon = json.dumps({k: spec[k] for k in SPEC_FIELDS}, sort_keys=True,
                       separators=(",", ":"))
    return hashlib.sha1(canon.encode()).hexdigest()[:20]


def _paths(spec, root=None):
    root = Path(root or cache_root())
    d = root / str(spec["char"])
    k = key_of(spec)
    return d / f"{k}.png", d / f"{k}.json"


# --- lookup / store --------------------------------------------------------- #
def lookup(spec, root=None):
    """Path to the cached PNG for `spec`, or None. Verifies the sidecar exists
    and its recorded spec MATCHES -- a sidecar that disagrees with the key means
    a hash collision or a hand-edited cache, and we refuse it rather than serve
    a possibly-wrong control."""
    png, side = _paths(spec, root)
    if not (png.is_file() and side.is_file()):
        return None
    try:
        rec = json.loads(side.read_text(encoding="utf-8"))
    except Exception:
        return None
    if any(rec.get("spec", {}).get(k) != spec[k] for k in SPEC_FIELDS):
        return None
    if png.stat().st_size < 1024:
        return None
    return png


def store(spec, png_bytes_or_path, provenance=None, root=None):
    """Write an image into the cache. `provenance` is free-form (iso path, run
    dir, actual frame reached...) and is recorded for auditing only -- it is NOT
    part of the key."""
    png, side = _paths(spec, root)
    png.parent.mkdir(parents=True, exist_ok=True)
    data = (Path(png_bytes_or_path).read_bytes()
            if isinstance(png_bytes_or_path, (str, Path)) else png_bytes_or_path)
    tmp = png.with_suffix(".png.tmp")
    tmp.write_bytes(data)
    file_retry.replace(tmp, png)
    rec = {"key": key_of(spec), "spec": spec,
           "sha1": hashlib.sha1(data).hexdigest(),
           "bytes": len(data), "stored": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "provenance": provenance or {}}
    tmp = side.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    file_retry.replace(tmp, side)
    return png


def fetch(spec, dest, root=None):
    """Copy the cached image for `spec` to `dest`. Returns True on a hit."""
    src = lookup(spec, root)
    if src is None:
        return False
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return True


# --- maintenance ------------------------------------------------------------ #
def entries(root=None):
    root = Path(root or cache_root())
    for side in sorted(root.glob("*/*.json")):
        try:
            rec = json.loads(side.read_text(encoding="utf-8"))
        except Exception:
            continue
        rec["_sidecar"] = side
        rec["_png"] = side.with_suffix(".png")
        yield rec


def verify(root=None):
    """Re-hash every cached PNG against its sidecar. Returns (ok, bad[])."""
    ok, bad = 0, []
    for rec in entries(root):
        p = rec["_png"]
        if not p.is_file():
            bad.append((str(p), "png missing"))
            continue
        h = hashlib.sha1(p.read_bytes()).hexdigest()
        if h != rec.get("sha1"):
            bad.append((str(p), "sha1 mismatch"))
        elif key_of(rec["spec"]) != rec.get("key"):
            bad.append((str(p), "key does not match its own spec"))
        else:
            ok += 1
    return ok, bad


def purge(root=None, char=None, env=None):
    """Drop cache entries. No filter = everything."""
    n = 0
    for rec in entries(root):
        if char and rec["spec"].get("char") != char:
            continue
        if env and rec["spec"].get("env") != env:
            continue
        for p in (rec["_png"], rec["_sidecar"]):
            if p.is_file():
                p.unlink()
        n += 1
    return n


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="vanilla control-shot cache")
    ap.add_argument("--root", default=None)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--purge", action="store_true")
    ap.add_argument("--char")
    ap.add_argument("--env")
    a = ap.parse_args(argv)
    root = Path(a.root) if a.root else cache_root()
    print(f"cache root: {root}")
    if a.purge:
        print(f"purged {purge(root, a.char, a.env)} entries")
        return 0
    if a.verify:
        ok, bad = verify(root)
        print(f"{ok} verified, {len(bad)} bad")
        for p, why in bad:
            print(f"  BAD {p}: {why}")
        return 1 if bad else 0
    rows = list(entries(root))
    if a.list:
        for rec in rows:
            s = rec["spec"]
            print(f"  {s['char']:12s} c{s['color']} {s['move']:8s} "
                  f"f{s['frame']:02d} yaw={s['yaw']} env={s['env']} "
                  f"cam={s['cam_dist']}/{s['cam_height']} bg={s['plain_bg']} "
                  f"-> {rec['_png'].name}")
    print(f"{len(rows)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
