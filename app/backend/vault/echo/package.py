"""
package.py -- an Echo is a DIFF against a donor, materialised as an ordinary
custom-character package so every existing path (vault, install, CSS icon,
costumes, sounds, export, sharing) works unchanged.

    echo.json            {"donor": "Falco", "donor_prefix": "PlFc",
                          "name": "Peppy", "ops": [...], "version": 1}
    donor.zip            the PRISTINE MexCLI export-fighter package of the
                         donor (never edited; the diff always re-applies to it)
    fighter.zip          donor.zip with fighter.json renamed + the data DAT
                         patched by the ops  ==  what add-fighter installs

`materialize()` turns (donor.zip, echo.json) into fighter.zip bytes. It is
pure: same inputs, same bytes, so re-materialising after an edit is always
safe and the package never drifts from its diff.
"""
from __future__ import annotations

import io
import json
import zipfile

from . import ops as echo_ops
from .subactions import FighterDat

ECHO_JSON = "echo.json"
VERSION = 1


def find_data_dat(zf: zipfile.ZipFile) -> str:
    """The fighter DATA dat inside a fighter.zip: fighter.json names it
    (files.fighterDataPath / dataFile), else the first Pl*.dat that parses
    as a fighter (has an ftData root)."""
    names = zf.namelist()
    try:
        fj = json.loads(zf.read("fighter.json"))
    except KeyError:
        fj = {}
    cand = []
    files = fj.get("files") or fj.get("Files") or {}
    for key in ("fighterDataPath", "FighterDataPath", "dataFile", "DataFile"):
        v = files.get(key) if isinstance(files, dict) else None
        if isinstance(v, str):
            cand.append(v)
        elif isinstance(v, dict) and isinstance(v.get("fileName"), str):
            cand.append(v["fileName"])
    for c in cand:
        for n in names:
            if n.lower().endswith(c.lower()):
                return n
    for n in names:
        base = n.rsplit("/", 1)[-1]
        if base.lower().startswith("pl") and base.lower().endswith(".dat") \
                and not base.lower().endswith("aj.dat"):
            try:
                FighterDat(zf.read(n))
                return n
            except ValueError:
                continue
    raise ValueError("no fighter data DAT found in package")


def donor_dat_bytes(donor_zip: bytes) -> tuple[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(donor_zip)) as zf:
        name = find_data_dat(zf)
        return name, zf.read(name)


def find_aj_dat(zf: zipfile.ZipFile, data_name: str) -> str | None:
    """The animation file paired with the data DAT: fighter.json names it, else
    the sibling <base>AJ.dat."""
    try:
        fj = json.loads(zf.read("fighter.json"))
    except KeyError:
        fj = {}
    files = fj.get("files") or fj.get("Files") or {}
    for key in ("animFile", "AnimFile", "animationFile"):
        v = files.get(key) if isinstance(files, dict) else None
        name = v.get("fileName") if isinstance(v, dict) else v
        if isinstance(name, str):
            for n in zf.namelist():
                if n.lower().endswith(name.lower()):
                    return n
    stem = data_name[:-4] if data_name.lower().endswith(".dat") else data_name
    guess = f"{stem}AJ.dat"
    for n in zf.namelist():
        if n.lower().endswith(guess.lower()):
            return n
    return None


def materialize(donor_zip: bytes, echo: dict) -> tuple[bytes, dict]:
    """(donor.zip bytes, echo.json dict) -> (fighter.zip bytes, apply report).
    Raises echo_ops.OpError when an op does not validate."""
    ops = echo.get("ops") or []
    animations = echo.get("animations") or []
    name = echo.get("name")
    with zipfile.ZipFile(io.BytesIO(donor_zip)) as zin:
        dat_name = find_data_dat(zin)
        donor_dat = zin.read(dat_name)
        # value edits first (in-place bit writes on the data DAT)
        result = echo_ops.apply(donor_dat, ops)
        patched_dat = result.data
        aj_name = None
        anim_report = []
        if animations:
            # then animation overrides on the (AJ, patched Pl) pair; the import
            # refreshes the action-table offsets in the Pl and preserves the
            # subaction byte edits made above.
            from . import anim as echo_anim
            aj_name = find_aj_dat(zin, dat_name)
            if aj_name is None:
                raise ValueError("animation override requested but no AJ file in package")
            new_aj, patched_dat, anim_report = echo_anim.apply_overrides(
                zin.read(aj_name), patched_dat, animations)
        # then compiled move logic (Tier 2): {"entry": "fighter.c", "files": {name: text}}
        # -> MexTK build appended as the ftFunction root; existing bytes untouched.
        code = echo.get("code") or None
        code_report = None
        if code:
            from .tier2 import build as tier2_build
            files = code.get("files") or {}
            entry = code.get("entry") or tier2_build.DEFAULT_ENTRY
            before = len(patched_dat)
            patched_dat = tier2_build.build_pl_from_files(patched_dat, files, entry)
            code_report = {"entry": entry, "files": sorted(files), "bytes": len(patched_dat) - before}
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == dat_name:
                    data = patched_dat
                elif aj_name and item.filename == aj_name:
                    data = new_aj
                elif item.filename == "fighter.json" and name:
                    fj = json.loads(data)
                    fj["name"] = name
                    if "Name" in fj:
                        fj["Name"] = name
                    data = json.dumps(fj, indent=2).encode("utf-8")
                zout.writestr(item, data)
            zout.writestr(ECHO_JSON, json.dumps({**echo, "version": VERSION}, indent=2))
    return out.getvalue(), {**result.as_dict(), "data_dat": dat_name,
                            "aj_dat": aj_name, "animations": anim_report, "code": code_report}


def read_echo(fighter_zip: bytes) -> dict | None:
    """The echo.json carried by a materialised package (None = not an echo)."""
    with zipfile.ZipFile(io.BytesIO(fighter_zip)) as zf:
        if ECHO_JSON not in zf.namelist():
            return None
        return json.loads(zf.read(ECHO_JSON))


def recover_ops(donor_zip: bytes, edited_zip: bytes) -> list[dict]:
    """Diff the data DAT of an edited package against the donor's: imports a
    package someone hand-edited in HSDRawViewer as ops."""
    _, a = donor_dat_bytes(donor_zip)
    _, b = donor_dat_bytes(edited_zip)
    return echo_ops.diff(a, b)
