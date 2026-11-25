"""The frozen build's self-check: `mex_backend --build-smoke-test`.

build.bat, build-linux.sh and build-macos.sh run the packaged executable with
that flag right after PyInstaller, so this runs INSIDE the shipped app. app.py
dispatches here before it imports Flask, prints "Build smoke test failed: ..."
and exits 1 on any exception, and exits 0 after "Build smoke test passed: ...".
It imports the packaged tools and reads the bundled data they need, and must
never import Flask (tests/backend/test_build_smoke.py proves the order).
"""

import os
import sys
from pathlib import Path

_BUILD_SMOKE_MODULES = (
    "generate_csp",
    "detect_character",
    "costume_validator",
    "bone_tables",
    "dat_processor",
    "falcon_neutralize",
)

_BUILD_SMOKE_DATA_FILES = (
    "texture_filename_table_seed.json",
    "vanilla_geom_hashes.json",
)

# The model import (it runs rigswap as a subprocess of its own Python; these are the app's side of it: the chat
# job and the vault save), reached lazily.
_BUILD_SMOKE_MODEL_IMPORT_MODULES = (
    "randall.model_import.chat.studio_import",
    "randall.model_import.chat.import_job",
    "randall.model_import.studio.finish",
)


# The code each release gate (core/gates.py) can leave out of a build.
# tools/build/mex_backend.spec leaves a gate's packages out unless the gate ships
# (ship_guard.gate_ships: the gate is not packaged_off, or the build asks for it as
# a preview feature with NUCLEUS_PREVIEW_FEATURES, the same variable the spec reads
# in the same build), and the frozen smoke below proves it from inside the shipped
# exe. Since 0.9.0 the assistant ships by default; Combo Video, the Tracker
# coach (gate "randall", which lives inside the assistant's package) and Play do not.
_GATED_PACKAGES = {
    "assistant": ("randall", "nucleus_api", "shared.aiengine", "shared.modellab",
                  # the approval card for a change the assistant proposed
                  "projects.routes.menus.build_changes"),
    "combo_video": ("tracker.video.combo_video", "tracker.routes.combo_video"),
    "randall": ("randall.coach", "randall.routes.coach"),
    "play": ("play",),
}


def _feature_ships(name):
    """Whether gated feature `name` is in this build: always in a dev checkout;
    in a frozen build when its gate is not packaged_off, stable builds open it
    (gates.release_features: Play once PLAY_IN_STABLE), or the build asked for it
    as a preview feature. The same rule as tools/build/ship_guard.gate_ships, which
    decided what the spec put in this exe."""
    if not getattr(sys, "frozen", False):
        return True
    wanted = {f.strip().lower() for f in os.environ.get("NUCLEUS_PREVIEW_FEATURES", "").split(",")}
    if name in wanted:
        return True
    from core.gates import GATES, release_features
    return not GATES[name].packaged_off or name in release_features()


def _bundled_modules():
    """Every module name frozen into this exe, read from PyInstaller's own table.
    Read, not imported: finding a route module would import its package, and
    with it Flask, which this smoke must never reach."""
    importers = sys.modules.get("pyimod02_importers")
    toc = getattr(getattr(importers, "pyz_archive", None), "toc", None)
    if toc is None:
        raise RuntimeError("cannot read the bundle's module table (PyInstaller layout changed?)")
    return set(toc)


def _smoke_gated_packages():
    """A frozen build carries exactly the gated packages its features ship."""
    if not getattr(sys, "frozen", False):
        print("Gated features in this build: all (dev checkout)")
        return
    bundled = _bundled_modules()
    for feature, packages in _GATED_PACKAGES.items():
        ships = _feature_ships(feature)
        for package in packages:
            present = any(m == package or m.startswith(package + ".") for m in bundled)
            if present != ships:
                state = "carries" if present else "is missing"
                raise RuntimeError(f"the build {state} {package} ({feature} "
                                   f"{'ships' if ships else 'does not ship'})")
    shipped = [f for f in _GATED_PACKAGES if _feature_ships(f)]
    print(f"Gated features in this build: {', '.join(shipped) or 'none'}")


def _smoke_model_import(importlib):
    """Import the model import's app side and its fighter table. -> [(name, module)]"""
    imported = [(name, importlib.import_module(name)) for name in _BUILD_SMOKE_MODEL_IMPORT_MODULES]
    fighters = importlib.import_module("randall.model_import.chat.import_job").fighters()
    if not fighters:
        raise RuntimeError("the model import targets no fighter")
    print(f"Model import: import_model and the vault save, {len(fighters)} fighters")
    return imported


def run_build_smoke_test():
    """Import packaged backend tools without starting the server."""
    import importlib
    from core.runtime_versions import check_unix_python, check_windows_python

    check_windows_python()
    # The macOS/Linux floor is about the Python inside the packaged backend; dev
    # and CI interpreters there (Ubuntu's 3.12.3) run this smoke unfrozen.
    if getattr(sys, "frozen", False):
        check_unix_python()

    # Exercise the native NumPy/OpenBLAS runtime explicitly. A missing native
    # dependency otherwise prevents the installed backend from starting at all.
    numpy = importlib.import_module("numpy")
    solution = numpy.linalg.solve([[3.0, 1.0], [1.0, 2.0]], [9.0, 8.0])
    if not numpy.allclose(solution, [2.0, 3.0]):
        raise RuntimeError("numpy.linalg.solve returned an unexpected result")
    print(f"Native runtime: Python {sys.version.split()[0]}, NumPy {numpy.__version__}")

    # Python 3.13/native-wheel compatibility: normal archive and image paths.
    import bz2
    import io
    import lzma
    import zipfile
    from PIL import Image

    sample = b"Nucleus runtime smoke" * 32
    for codec in (bz2, lzma):
        if codec.decompress(codec.compress(sample)) != sample:
            raise RuntimeError(f"{codec.__name__} round-trip failed")
    for compression in (zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", compression=compression) as writer:
            writer.writestr("sample.txt", sample)
        with zipfile.ZipFile(archive) as reader:
            if reader.read("sample.txt") != sample:
                raise RuntimeError("ZIP round-trip failed")
    image_bytes = io.BytesIO()
    Image.new("RGBA", (4, 4), "red").save(image_bytes, format="PNG")
    image_bytes.seek(0)
    with Image.open(image_bytes) as image:
        if image.resize((8, 8)).getpixel((0, 0)) != (255, 0, 0, 255):
            raise RuntimeError("Pillow image round-trip failed")
    print(f"Archive/image runtime: bzip2, LZMA, ZIP, Pillow {Image.__version__}")

    core_config = importlib.import_module("core.config")
    imported = [("numpy", numpy), ("core.config", core_config)]
    imported.extend(
        (module_name, importlib.import_module(module_name))
        for module_name in _BUILD_SMOKE_MODULES
    )

    # 7z import. py7zr needs Cryptodome, of which the spec bundles only the AES
    # pieces (CRYPTODOME_KEEP in mex_backend.spec); a password-protected round
    # trip proves those are all it loads.
    py7zr = importlib.import_module("py7zr")
    imported.append(("py7zr", py7zr))
    import tempfile

    seven = io.BytesIO()
    with py7zr.SevenZipFile(seven, "w", password="smoke") as writer:
        writer.writestr(sample, "sample.txt")
    seven.seek(0)
    with tempfile.TemporaryDirectory() as unpacked:
        with py7zr.SevenZipFile(seven, "r", password="smoke") as reader:
            reader.extractall(path=unpacked)
        if (Path(unpacked) / "sample.txt").read_bytes() != sample:
            raise RuntimeError("encrypted 7z round-trip failed")
    print(f"7z runtime: py7zr {py7zr.__version__}, AES")

    for filename in _BUILD_SMOKE_DATA_FILES:
        data_file = core_config.BACKEND_DATA_DIR / filename
        if not data_file.is_file():
            raise RuntimeError(f"bundled backend data is missing: {data_file}")

    _smoke_gated_packages()
    if _feature_ships("assistant"):
        imported.extend(_smoke_model_import(importlib))

    # In-app bug reports, as far as this can go without a network or Flask.
    # Every report that has ever reached Discord came from Windows, and the two
    # halves that vary per OS are exactly these: the channel string the worker
    # validates, and zipping a log directory that lives somewhere different on
    # each platform. Checking them here is what gives the macOS and Linux
    # builds any coverage -- their runners build the installer but run no
    # pytest job. Deliberately stdlib-only: importing the blueprint would pull
    # in Flask and break the tools-before-Flask ordering this smoke test exists
    # to prove (tests/backend/test_build_smoke.py).
    channel = core_config.bugreport_channel()
    if channel not in ("windows", "mac", "linux"):
        raise RuntimeError(f"bug reports would be rejected: bad platform {channel!r}")
    import io as _io
    import zipfile as _zipfile

    logs_dir = core_config.LOGS_PATH
    if not os.access(logs_dir, os.W_OK):
        raise RuntimeError(f"bug-report logs dir is not writable: {logs_dir}")
    _buf = _io.BytesIO()
    with _zipfile.ZipFile(_buf, "w", _zipfile.ZIP_DEFLATED) as _zf:
        for _p in logs_dir.rglob("*"):
            if _p.is_file():
                _zf.write(_p, f"logs/{_p.relative_to(logs_dir).as_posix()}")
        _zf.writestr("report.json", "{}")
    with _zipfile.ZipFile(_buf) as _zf:
        if _zf.testzip() is not None or "report.json" not in _zf.namelist():
            raise RuntimeError("bug-report log zip did not round-trip")
    print(f"Bug reports: channel {channel}, log zip {_buf.getbuffer().nbytes} bytes")

    if getattr(sys, "frozen", False):
        bundle_path = getattr(sys, "_MEIPASS", None)
        if not bundle_path:
            raise RuntimeError("frozen build does not define sys._MEIPASS")
        bundle_root = Path(bundle_path).resolve()
        for module_name, module in imported:
            module_file = getattr(module, "__file__", None)
            if not module_file:
                raise RuntimeError(f"{module_name} has no import path")
            resolved = Path(module_file).resolve()
            try:
                resolved.relative_to(bundle_root)
            except ValueError as exc:
                raise RuntimeError(
                    f"{module_name} resolved outside sys._MEIPASS: {resolved}"
                ) from exc

    names = [name for name, _ in imported]
    print("Build smoke test passed: " + ", ".join(names))
