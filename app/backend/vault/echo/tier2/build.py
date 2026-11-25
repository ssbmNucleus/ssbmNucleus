"""Compile fighter C with MexTK and splice the result into a Pl DAT.

    ftfunction = compile_dir(src_dir)              # bytes of ftFunction.dat
    new_pl     = build_pl(pl_bytes, src_dir)       # Pl + appended ftFunction root
    new_pl     = build_pl_from_files(pl_bytes, {"fighter.c": "...", ...})

MexTK compiles with devkitPPC (`-c` only, relocation done by MexTK itself) and
resolves engine symbols through its `melee.link`; it finds its headers relative
to its own exe (`-I <exe>/include`), so sources include the outer header as
`../mex.h`. The compiled DAT is appended to the Pl with vault.echo.datroot rather
than MexTK's `-dat` flag, because that flag goes through HSDRaw's save, which
is not byte-exact on Pl files.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..datroot import merge_bytes, parse

HERE = Path(__file__).resolve().parent
INCLUDE_DIR = HERE / "include"          # hud.c, ftwrap.c -- copied beside every build
DEFAULT_ENTRY = "fighter.c"
FTFUNCTION_SYMBOL = "ftFunction"

_CANDIDATES = [
    os.environ.get("MEXTK_DIR", ""),
    str(Path.home() / "Downloads" / "yt" / "MexTK"),
    str(HERE.parents[4] / "utility" / "MexTK"),
]


class BuildError(RuntimeError):
    """MexTK / devkitPPC failed. `.log` carries the compiler output."""

    def __init__(self, msg: str, log: str = ""):
        super().__init__(msg)
        self.log = log


def find_mextk() -> Path | None:
    for c in _CANDIDATES:
        if c and (Path(c) / "MexTK.exe").is_file():
            return Path(c)
    return None


def mextk_info() -> dict:
    d = find_mextk()
    dk = Path(r"C:\devkitPro\devkitPPC\bin\powerpc-eabi-gcc.exe")
    return {"mextk": str(d) if d else None,
            "headers": bool(d and (d / "mex.h").is_file() and (d / "include" / "fighter.h").is_file()),
            "link": bool(d and (d / "melee.link").is_file()),
            "devkitppc": dk.is_file()}


def _strip_noise(log: str) -> str:
    """Keep the lines a caller can act on (compiler diagnostics)."""
    keep = []
    for line in log.splitlines():
        s = line.strip()
        if not s or s.startswith(("x | ", "saving ")) or "|" in s and s.split("|")[0].strip() in ("x", "\ufffd"):
            continue
        keep.append(line)
    return "\n".join(keep)


def compile_dir(src_dir, entry: str = DEFAULT_ENTRY, mextk_dir=None) -> bytes:
    """Compile `<src_dir>/<entry>` into a standalone ftFunction DAT (bytes).
    The helper sources in include/ are copied beside the entry unless the
    directory already carries files of the same name."""
    mextk = Path(mextk_dir) if mextk_dir else find_mextk()
    if mextk is None or not (mextk / "MexTK.exe").is_file():
        raise BuildError("MexTK.exe not found (set MEXTK_DIR); see tier2/README.md 'Toolchain'")
    src_dir = Path(src_dir)
    if not (src_dir / entry).is_file():
        raise BuildError(f"{entry} not found in {src_dir}")
    with tempfile.TemporaryDirectory(prefix="nucleus_tier2_") as tmp:
        work = Path(tmp) / "src"
        shutil.copytree(src_dir, work)
        for helper in INCLUDE_DIR.glob("*.c"):
            if not (work / helper.name).exists():
                shutil.copy(helper, work / helper.name)
        out = Path(tmp) / "ftFunction.dat"
        cmd = [str(mextk / "MexTK.exe"), "-ff", "-i", f"src/{entry}", "-s", FTFUNCTION_SYMBOL,
               "-o", str(out), "-ow", "-q"]
        from core.child_env import child_environment
        r = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, env=child_environment())
        log = _strip_noise((r.stdout or "") + (r.stderr or ""))
        if r.returncode != 0 or not out.is_file():
            raise BuildError("MexTK compile failed:\n" + log, log)
        data = out.read_bytes()
    roots = [n for _, n in parse(data)[2]]
    if FTFUNCTION_SYMBOL not in roots:
        raise BuildError(f"compiled DAT has no {FTFUNCTION_SYMBOL} root (roots: {roots})", log)
    return data


def build_pl(pl_bytes: bytes, src_dir, entry: str = DEFAULT_ENTRY, mextk_dir=None) -> bytes:
    """Pl DAT + compiled code root. Existing Pl bytes are preserved verbatim."""
    roots = [n for _, n in parse(pl_bytes)[2]]
    if FTFUNCTION_SYMBOL in roots:
        raise BuildError(f"Pl already carries an {FTFUNCTION_SYMBOL} root -- build from the donor's original")
    return merge_bytes(pl_bytes, compile_dir(src_dir, entry, mextk_dir))


def build_pl_from_files(pl_bytes: bytes, files: dict[str, str], entry: str = DEFAULT_ENTRY,
                        mextk_dir=None) -> bytes:
    """Same, with the sources given as {filename: text} (the echo.json shape)."""
    if not isinstance(files, dict) or entry not in files:
        raise BuildError(f"code.files must contain the entry file {entry!r}")
    with tempfile.TemporaryDirectory(prefix="nucleus_tier2_src_") as tmp:
        for name, text in files.items():
            if "/" in name or "\\" in name or name.startswith("."):
                raise BuildError(f"bad source name {name!r}")
            (Path(tmp) / name).write_text(text, encoding="utf-8")
        return build_pl(pl_bytes, tmp, entry, mextk_dir)


def check_files(files: dict[str, str], entry: str = DEFAULT_ENTRY, mextk_dir=None) -> dict:
    """Compile-only validation of tier-2 sources: {ok, bytes|error}."""
    try:
        with tempfile.TemporaryDirectory(prefix="nucleus_tier2_chk_") as tmp:
            for name, text in (files or {}).items():
                (Path(tmp) / name).write_text(text, encoding="utf-8")
            data = compile_dir(tmp, entry, mextk_dir)
        return {"ok": True, "bytes": len(data)}
    except BuildError as e:
        return {"ok": False, "error": str(e)}
