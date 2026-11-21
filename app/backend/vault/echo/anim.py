"""
anim.py -- fighter animation overrides for the Echo pipeline.

A fighter's per-action animations live in Pl<Xx>AJ.dat as concatenated FigaTree
DATs; the action table in Pl<Xx>.dat points at each by (offset, size). The
FigaTree encode/decode lives in C# (HSDRaw), so this module shells out to the
`--anim` verbs in HSDRawViewer (see core.config.HSDRAW_EXE):

    --anim export <AJ> <symbol|substring> <out.anim>
    --anim import <AJ> <symbol|substring> <in.anim|.smd|.dae|.chr0|.dat>
                  <out-AJ> --pl <Pl> <out-Pl> [--error N]

An override is applied to (AJ, Pl) as a unit and produces a new (AJ, Pl) pair;
import rebuilds the whole AJ and refreshes every action offset in the Pl file,
so the two must always travel together.

Three override kinds, all keeping the DONOR's skeleton (no retargeting):
  - file    : import an authored clip (.anim/.smd/.dae/.chr0) onto a move
  - source  : copy another of the donor's own animations onto a move
  - exaggerate : scale the move's own rotation keys (a built-in edit, so a
                 distinctive animation needs no external art)

The move -> action symbol mapping reuses vault.echo.moves, so overrides speak the
same community names as the value ops.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from .moves import MoveTable
from .subactions import FighterDat


class AnimError(ValueError):
    """An override that cannot be applied as written (user-facing; maps to 422)."""


SUPPORTED_CLIP_EXTS = (".anim", ".smd", ".dae", ".chr0", ".dat")
_CLIP_ID = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
MAX_CLIP_BYTES = 32 * 1024 * 1024


def clips_dir() -> Path:
    """Where uploaded clips live: storage/echo/clips/<id><ext>."""
    from core.config import STORAGE_PATH
    d = Path(STORAGE_PATH) / "echo" / "clips"
    d.mkdir(parents=True, exist_ok=True)
    return d


def store_clip(filename: str, data: bytes) -> dict:
    """Save an uploaded clip; the id is content-addressed so re-uploads dedupe."""
    import hashlib
    ext = Path(filename or "").suffix.lower()
    if ext not in SUPPORTED_CLIP_EXTS:
        raise AnimError(f"unsupported clip format '{ext or filename}' "
                        f"(use one of {', '.join(SUPPORTED_CLIP_EXTS)})")
    if not data:
        raise AnimError("empty clip upload")
    if len(data) > MAX_CLIP_BYTES:
        raise AnimError(f"clip is {len(data)} bytes; limit is {MAX_CLIP_BYTES}")
    cid = hashlib.sha1(data).hexdigest()[:16]
    dest = clips_dir() / f"{cid}{ext}"
    if not dest.exists():
        dest.write_bytes(data)
    return {"clip": cid, "filename": Path(filename).name, "bytes": len(data),
            "format": ext.lstrip(".")}


def list_clips() -> list[dict]:
    out = []
    for f in sorted(clips_dir().iterdir()):
        if f.is_file() and f.suffix.lower() in SUPPORTED_CLIP_EXTS:
            out.append({"clip": f.stem, "format": f.suffix.lstrip("."), "bytes": f.stat().st_size})
    return out


def resolve_clip(ov: dict) -> Path:
    """The file an override imports: an uploaded clip id, or a literal path."""
    if "clip" in ov:
        cid = str(ov["clip"])
        if not _CLIP_ID.match(cid):
            raise AnimError(f"bad clip id '{cid}'")
        hits = [f for f in clips_dir().glob(f"{cid}.*") if f.suffix.lower() in SUPPORTED_CLIP_EXTS]
        if not hits:
            raise AnimError(f"clip '{cid}' not found -- upload it first (anim.store_clip)")
        return hits[0]
    return Path(str(ov["file"]))


def _action_index_or_error(mt: MoveTable, move, part, what: str, errors: list[str], tag: str) -> bool:
    try:
        mt.action_index(move, part)
        return True
    except Exception as e:  # unknown move / part -- MoveTable raises KeyError/ValueError
        errors.append(f"{tag}: {what} {e}")
        return False


def validate_overrides(data_dat: bytes, overrides: list) -> list[str]:
    """Every problem with a list of overrides, all at once (empty = fine).
    Mirrors vault.echo.ops.plan: the UI shows all errors, the copilot fixes them in one go."""
    errors: list[str] = []
    if not isinstance(overrides, list):
        return ["animations must be a list"]
    fd = FighterDat(data_dat)
    mt = MoveTable(fd)
    for i, ov in enumerate(overrides):
        tag = f"animation[{i}]"
        if not isinstance(ov, dict):
            errors.append(f"{tag}: must be an object")
            continue
        move = ov.get("move")
        if not move:
            errors.append(f"{tag}: 'move' is required")
            continue
        if not _action_index_or_error(mt, move, ov.get("part"), "", errors, tag):
            continue
        kinds = [k for k in ("file", "clip", "source", "exaggerate") if k in ov]
        if len(kinds) != 1:
            errors.append(f"{tag}: needs exactly one of file/clip/source/exaggerate "
                          f"(got {', '.join(kinds) if kinds else 'none'})")
            continue
        kind = kinds[0]
        if kind in ("file", "clip"):
            try:
                path = resolve_clip(ov)
            except AnimError as e:
                errors.append(f"{tag}: {e}")
                continue
            if not path.is_file():
                errors.append(f"{tag}: file not found: {path}")
            elif path.suffix.lower() not in SUPPORTED_CLIP_EXTS:
                errors.append(f"{tag}: unsupported clip format '{path.suffix}' "
                              f"(use one of {', '.join(SUPPORTED_CLIP_EXTS)})")
        elif kind == "source":
            _action_index_or_error(mt, ov.get("source"), ov.get("source_part"), "source", errors, tag)
        else:
            try:
                factor = float(ov["exaggerate"])
                if not (0 < factor <= 10):
                    raise ValueError
            except (TypeError, ValueError):
                errors.append(f"{tag}: exaggerate must be a number in (0, 10]")
        if "error" in ov:
            try:
                if float(ov["error"]) < 0:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append(f"{tag}: error (key tolerance) must be a number >= 0")
        if "map" in ov and not Path(str(ov["map"])).is_file():
            errors.append(f"{tag}: joint map not found: {ov['map']}")
    return errors


def _hsdraw() -> str:
    from core.config import HSDRAW_EXE
    if not Path(HSDRAW_EXE).exists():
        raise RuntimeError(f"HSDRawViewer not built at {HSDRAW_EXE}")
    return str(HSDRAW_EXE)


def _run(args: list[str]) -> str:
    from core.config import get_subprocess_args
    r = subprocess.run([_hsdraw(), *args], capture_output=True, text=True,
                       **get_subprocess_args())
    out = (r.stdout or "") + (r.stderr or "")
    if "ERROR:" in out:
        # the verb's own diagnosis (wrong skeleton, over 0x8000, bad clip ...): user-facing
        msg = next((ln for ln in out.splitlines() if ln.startswith("ERROR:")), out.strip()[-400:])
        raise AnimError(msg[len("ERROR:"):].strip())
    if r.returncode != 0:
        raise RuntimeError(f"HSDRawViewer --anim failed: {out.strip()[-800:]}")
    return out


def action_symbol(data_dat: bytes, move: str, part: str | None) -> str:
    """The action-table symbol for a move/part (e.g. Ply<Name>5K_..._AttackS4S_...)."""
    fd = FighterDat(data_dat)
    mt = MoveTable(fd)
    idx = mt.action_index(move, part)
    sym = fd.actions[idx].symbol
    if not sym:
        raise ValueError(f"{move}/{part} (action {idx}) has no animation symbol")
    return sym


# ---------------------------------------------------------------------------
# .anim (Maya) keyframe transforms -- pure text, no C# needed
# ---------------------------------------------------------------------------
def exaggerate_anim(text: str, factor: float = 1.5) -> tuple[str, int]:
    """Scale every rotation key value by `factor`. Bigger swing, same timing.
    Returns (new_text, keys_changed)."""
    out, in_rot, in_keys, n = [], False, False, 0
    for line in text.splitlines():
        st = line.strip()
        if st.startswith("anim "):
            in_rot = ".rotate" in st
            in_keys = False
        elif st.startswith("keys {"):
            in_keys = True
        elif st == "}" and in_keys:
            in_keys = False
        elif in_keys and in_rot and st and (st[0].isdigit() or st[0] == "-"):
            toks = st.split()
            try:
                v = float(toks[1])
                if abs(v) > 1e-6:
                    toks[1] = f"{v * factor:.6f}"
                    n += 1
                out.append(" " + " ".join(toks))
                continue
            except (ValueError, IndexError):
                pass
        out.append(line)
    return "\n".join(out) + "\n", n


ANIM_TRANSFORMS = {"exaggerate": exaggerate_anim}


# ---------------------------------------------------------------------------
# apply a list of overrides to an (AJ, Pl) pair
# ---------------------------------------------------------------------------
def apply_overrides(aj_bytes: bytes, pl_bytes: bytes, overrides: list[dict],
                    workdir: Path | None = None) -> tuple[bytes, bytes, list[dict]]:
    """Apply animation overrides, returning (new_aj, new_pl, report).

    Each override: {"move", "part"?, and one of:
        "file": <path>            import an external clip
        "source": <move>[,"source_part"]   copy another donor animation
        "exaggerate": <factor>    scale rotation keys of the move's own clip
        "clip": <id>              import a clip stored with store_clip()
      optional "error": <float> encode tolerance, "map": <joints.ini> for named-joint clips }
    """
    problems = validate_overrides(pl_bytes, overrides)
    if problems:
        raise AnimError("; ".join(problems))
    tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="echo_anim_"))
    tmp.mkdir(parents=True, exist_ok=True)
    aj = tmp / "cur_AJ.dat"
    pl = tmp / "cur_Pl.dat"
    aj.write_bytes(aj_bytes)
    pl.write_bytes(pl_bytes)
    report = []

    for i, ov in enumerate(overrides):
        move, part = ov["move"], ov.get("part")
        err = float(ov.get("error", 0.0001))
        target = action_symbol(pl.read_bytes(), move, part)

        # produce the clip file to import
        clip = tmp / f"clip_{i}.anim"
        if "file" in ov or "clip" in ov:
            src = resolve_clip(ov)
            if not src.exists():
                raise AnimError(f"animation[{i}] file not found: {src}")
            clip = src
            kind = f"{'clip' if 'clip' in ov else 'file'}:{src.name}"
        elif "source" in ov:
            src_sym = action_symbol(pl.read_bytes(), ov["source"], ov.get("source_part"))
            _run(["--anim", "export", str(aj), src_sym, str(clip)])
            kind = f"source:{ov['source']}"
        elif "exaggerate" in ov:
            base = tmp / f"base_{i}.anim"
            _run(["--anim", "export", str(aj), target, str(base)])
            new_text, changed = exaggerate_anim(base.read_text(), float(ov["exaggerate"]))
            clip.write_text(new_text)
            kind = f"exaggerate x{ov['exaggerate']} ({changed} keys)"
        else:
            raise AnimError(f"animation[{i}] needs one of file/clip/source/exaggerate")

        out_aj = tmp / f"AJ_{i}.dat"
        out_pl = tmp / f"Pl_{i}.dat"
        cmd = ["--anim", "import", str(aj), target, str(clip),
               str(out_aj), "--pl", str(pl), str(out_pl), "--error", str(err)]
        if ov.get("map"):
            cmd += ["--map", str(ov["map"])]
        try:
            log = _run(cmd)
        except AnimError as e:
            raise AnimError(f"animation[{i}] ({move}{'/' + part if part else ''}): {e}") from None
        aj, pl = out_aj, out_pl
        report.append({"move": move, "part": part, "symbol": target, "kind": kind,
                       "log": log.strip().splitlines()[-1]})

    return aj.read_bytes(), pl.read_bytes(), report


