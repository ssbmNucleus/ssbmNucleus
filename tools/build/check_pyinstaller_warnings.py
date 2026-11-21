#!/usr/bin/env python3
"""Fail a build when PyInstaller finds a new missing project dependency.

PyInstaller's warning file is intentionally noisy: optional third-party
backends and platform-specific standard-library modules account for hundreds
of entries.  The useful regression signal is much smaller -- a missing module
imported directly by Nucleus code.  Keep the deliberate loose-module and
optional-extension exceptions explicit here so a new project-level miss cannot
disappear into the inventory.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


MISSING_RE = re.compile(r"^missing module named (?P<name>.+?) - imported by (?P<importers>.+)$")

# These files are copied into sys._MEIPASS as source and added to sys.path by
# backend/core/config.py.  They deliberately are not frozen into the PYZ.
LOOSE_RUNTIME_MODULES = {
    "bone_tables",
    "costume_validator",
    "csp_logs",
    "dat_processor",
    "detect_character",
    "falcon_neutralize",
    "generate_csp",
}

# Optional functionality has an explicit fallback when these packages are not
# installed in the compact desktop runtime.
OPTIONAL_PROJECT_MODULES = {
    # Compatibility imports used after the processor directory is added to
    # sys.path in frozen builds; the packaged sibling/module supplies them.
    "datprobe",
    "imagehash",
    # Delayed verification-only import; shared.rendering.ptcl_texbank is bundled under
    # its package name and the runtime path does not require this alias.
    "ptcl_texbank",
    "pyo3_runtime",
    # shared.ingame.screenshot_wgc's Windows Graphics Capture backend: only the
    # developer's NUCLEUS_DOLPHIN_CAPTURE=wgc switch imports it (in-game QA,
    # requirements-ingame-qa.txt); the app captures with PrintWindow and the
    # installer does not carry it.
    "windows_capture",
    # POSIX-only advisory file locking. core.build_transaction and
    # storage_data_lock import it inside a try on non-Windows platforms and use
    # msvcrt on Windows; a Windows build never needs it (added 2026-09-22 when
    # the cross-process build lock landed).
    "fcntl",
}

KNOWN_PROJECT_MISSING = LOOSE_RUNTIME_MODULES | OPTIONAL_PROJECT_MODULES

# Present only on Windows: the Windows file-locking module. A build for another
# platform legitimately lacks it; a Windows build that lacks it is broken.
WINDOWS_ONLY_MODULES = {
    "msvcrt",
}

PROJECT_IMPORT_MODULES = LOOSE_RUNTIME_MODULES | {
    "app",
}

# The packages the old flat layout named one by one, at their 2026-10-03 homes
# (blueprints/ became the five */routes/ packages).
PROJECT_IMPORT_PREFIXES = (
    "backend.",
    "core.",
    "mexcli.",
    "vault.routes.",
    "vault.importing.",
    "projects.routes.",
    "projects.install.",
    "upload.routes.",
    "tracker.",
    "randall.model_import.",
    "randall.coach.",
    "shared.routes.",
    "shared.aiengine.",
    "shared.diagnostics.",
    "shared.ingame.",
    "shared.modellab.",
    "shared.rendering.",
    "shared.vanilla_extract.",
)


# Top-level names of Nucleus's own code: a missing name under one of these is a
# deleted or renamed module, never a third-party attribute.
PROJECT_TOP_LEVEL = {prefix.rstrip(".") for prefix in PROJECT_IMPORT_PREFIXES} | PROJECT_IMPORT_MODULES


def _module_name(raw: str) -> str:
    return raw.strip().strip("'").strip('"')


def _attribute_of_present_module(name: str, missing: set[str]) -> bool:
    """`from scipy.optimize import minimize` reads to PyInstaller as a missing
    module `scipy.optimize.minimize`: a function imported from a third-party
    module that is there, not a missing dependency. Only when that module
    itself is not missing, and never under Nucleus's own packages."""
    parent = name.rpartition(".")[0]
    return (bool(parent) and name.split(".")[0] not in PROJECT_TOP_LEVEL
            and not name.startswith(PROJECT_IMPORT_PREFIXES) and parent not in missing)


def _is_project_importer(importer: str) -> bool:
    importer = importer.strip()
    module = importer.split(" ", 1)[0]
    if module in PROJECT_IMPORT_MODULES:
        return True
    if module.startswith(PROJECT_IMPORT_PREFIXES):
        return True
    normalized = importer.replace("/", "\\").lower()
    return "\\backend\\" in normalized and "\\site-packages\\" not in normalized


def unexpected_project_missing(lines: list[str], platform: str = sys.platform) -> list[tuple[str, str]]:
    known = KNOWN_PROJECT_MISSING | (set() if platform == "win32" else WINDOWS_ONLY_MODULES)
    matches = [match for match in (MISSING_RE.match(line.strip()) for line in lines) if match]
    missing = {_module_name(match.group("name")) for match in matches}
    unexpected: list[tuple[str, str]] = []
    for match in matches:
        importers = match.group("importers").split(", ")
        if not any(_is_project_importer(importer) for importer in importers):
            continue
        name = _module_name(match.group("name"))
        if name not in known and not _attribute_of_present_module(name, missing):
            unexpected.append((name, match.group(0)))
    return unexpected


def check(path: Path) -> int:
    if not path.is_file():
        print(f"ERROR: PyInstaller warning inventory not found: {path}")
        return 2

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    all_missing = sum(line.startswith("missing module named ") for line in lines)
    unexpected = unexpected_project_missing(lines)
    if unexpected:
        print("ERROR: PyInstaller found unexpected missing modules imported by Nucleus code:")
        for name, line in unexpected:
            print(f"  - {name}: {line}")
        print("Bundle the dependency, make the import explicitly optional, or document it in the guard.")
        return 1

    print(
        "PyInstaller warning check: PASS -- "
        f"{all_missing} total missing-module entries; "
        "no unexpected project-level dependencies."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("warning_file", type=Path)
    args = parser.parse_args()
    return check(args.warning_file)


if __name__ == "__main__":
    raise SystemExit(main())
