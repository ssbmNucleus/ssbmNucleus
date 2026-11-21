"""
Configuration and path constants for the MEX API backend.

Handles platform detection and path configuration for both development
and bundled (PyInstaller) execution modes.
"""

import os
import sys
import subprocess
import tempfile
from pathlib import Path


def get_subprocess_args():
    """Get platform-specific args to hide subprocess windows on Windows."""
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        return {'startupinfo': startupinfo, 'creationflags': subprocess.CREATE_NO_WINDOW}
    return {}


# Project root detection
if getattr(sys, 'frozen', False):
    # Running as bundled exe
    # When installed: C:\Users\...\AppData\Local\Programs\Melee Nexus\resources\backend\mex_backend.exe
    EXE_PATH = Path(sys.executable)
    RESOURCES_DIR = EXE_PATH.parent.parent  # resources/

    # For user data, use writable locations outside the install directory.
    # Key off the OS, not the AppImage mount path: the writable dir must be the
    # same whether the app runs as a mounted AppImage (exe under /tmp/.mount_*),
    # an extracted AppImage, or a bare binary — the old '/tmp/.mount_' check
    # missed the latter two and fell through to a bogus ~/AppData/Local path.
    _build_smoke_root = (
        os.environ.get('NUCLEUS_BUILD_SMOKE_ROOT', '').strip()
        if '--build-smoke-test' in sys.argv[1:]
        else ''
    )
    if _build_smoke_root:
        # Build verification must never create or mutate a real user profile.
        PROJECT_ROOT = Path(_build_smoke_root).expanduser().resolve()
    elif sys.platform == 'darwin':
        # macOS: the platform's own convention for app data, not a dotfile.
        PROJECT_ROOT = Path.home() / 'Library' / 'Application Support' / 'SSBM Nucleus'
    elif os.name != 'nt':
        # Linux: home-directory writable data dir
        PROJECT_ROOT = Path.home() / '.melee-nexus'
    else:
        # Windows: Use LocalAppData for writable user data
        appdata = os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))
        PROJECT_ROOT = Path(appdata) / 'SSBM Nucleus'
else:
    # Running as Python script (development)
    PROJECT_ROOT = Path(__file__).parent.parent.parent
    RESOURCES_DIR = PROJECT_ROOT  # In dev, resources are in project root

# The Electron bootstrap resolves this before starting the backend. Never create
# a missing selected root: a disconnected drive must fail, not appear empty.
# Development data normally shares the source checkout, so tests/tools must
# explicitly opt in to a separate data root while tools stay in RESOURCES_DIR.
_data_override = os.environ.get('NUCLEUS_DATA_ROOT', '').strip()
_smoke_mode = '--build-smoke-test' in sys.argv[1:]
if _data_override and not _smoke_mode:
    if not getattr(sys, 'frozen', False) and os.environ.get('NUCLEUS_ALLOW_DEV_DATA_ROOT') != '1':
        raise RuntimeError('NUCLEUS_DATA_ROOT in development requires NUCLEUS_ALLOW_DEV_DATA_ROOT=1')
    _chosen_root = Path(_data_override).expanduser()
    if not _chosen_root.is_absolute() or not _chosen_root.is_dir():
        raise RuntimeError(f'Selected Nucleus data folder is unavailable: {_chosen_root}')
    PROJECT_ROOT = _chosen_root.resolve()
PROJECT_ROOT.mkdir(parents=True, exist_ok=True)

# Updated backends and the offline mover share a per-root process lease. Keep
# this object alive until process exit; no shutdown path unlinks the lock file.
_DATA_ROOT_LEASE = None
if not _smoke_mode and (getattr(sys, 'frozen', False) or os.environ.get('NUCLEUS_MANAGED_DATA_ROOT') == '1'):
    from storage_data_lock import acquire_data_root_lock
    _DATA_ROOT_LEASE = acquire_data_root_lock(PROJECT_ROOT, exclusive=False)

# Pin Python's tempfile cache as well as the environment inherited by native
# children. No fallback to the OS temp directory when selected storage fails.
_scratch_override = os.environ.get('NUCLEUS_SCRATCH_DIR', '').strip()
SCRATCH_PATH = PROJECT_ROOT / 'scratch'
if _scratch_override and not _smoke_mode:
    _chosen_scratch = Path(_scratch_override)
    if not _chosen_scratch.is_absolute() or _chosen_scratch.resolve() != SCRATCH_PATH.resolve():
        raise RuntimeError('Nucleus scratch must be the scratch folder inside the selected data root')
SCRATCH_PATH.mkdir(parents=True, exist_ok=True)
for _temp_key in ('TMP', 'TEMP', 'TMPDIR'):
    os.environ[_temp_key] = str(SCRATCH_PATH)
tempfile.tempdir = str(SCRATCH_PATH)

# Backend directory (for local imports)
BACKEND_DIR = Path(__file__).parent.parent

# Bundled backend assets/data. In frozen builds these live inside the PyInstaller
# bundle (_MEIPASS) — shipped via mex_backend.spec datas at 'backend/assets' and
# 'backend/data'. Modules MUST resolve them through these constants, NOT via
# Path(__file__)/'assets' (in a frozen build __file__ points into _MEIPASS at a
# path that does NOT match the datas layout, so the asset is "missing" → broken
# images / empty manifests in the installed app only).
if getattr(sys, 'frozen', False):
    BACKEND_ASSETS_DIR = Path(sys._MEIPASS) / 'backend' / 'assets'
    BACKEND_DATA_DIR = Path(sys._MEIPASS) / 'backend' / 'data'
else:
    BACKEND_ASSETS_DIR = BACKEND_DIR / 'assets'
    BACKEND_DATA_DIR = BACKEND_DIR / 'data'

# Base path for bundled/dev assets stays separate from writable user data.
BASE_PATH = RESOURCES_DIR

# Platform tag for the per-OS native tool directories. macOS must be its own
# branch: it is not Windows, so every `else` below used to hand it the LINUX
# binaries, which silently cannot run on Darwin.
IS_MACOS = sys.platform == 'darwin'


def bugreport_channel() -> str:
    """Which platform bucket an in-app bug report files under.

    Must stay inside the set the bug-report worker accepts -- its CHANNELS is
    {windows, mac, linux} and anything else is rejected with "bad platform",
    losing the report. Lives here rather than in the blueprint so the packaged
    build smoke test can check it without importing Flask, which is what gives
    macOS and Linux builds any coverage of this at all.
    """
    # Read sys.platform directly rather than the IS_MACOS constant: the
    # constant is bound at import time, so a test cannot exercise the darwin
    # branch on any other host.
    if sys.platform == 'win32':
        return 'windows'
    if sys.platform == 'darwin':
        return 'mac'
    return 'linux'


# Uncompressed budget for an in-app bug report zip: keeps the compressed upload
# well under the bug-report worker's 64 MB cap (and the zone's request-body
# limit). The "Report this chat" bundle shares the same ceiling.
BUGREPORT_ZIP_BUDGET = 48 * 1024 * 1024

# The ssbmnucleus.net Supabase project the desktop publisher and Randall's
# website search talk to (the anon key ships in the website bundle; RLS
# protects the data). Never a user key.
SUPABASE_URL = 'https://nttxcjrnqccogsibeqzz.supabase.co'
SUPABASE_ANON_KEY = ('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im50dHhjanJucWNjb2dzaWJlcXp6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjAyMDY3NTYsImV4cCI6MjA3NTc4Mjc1Nn0.'
                     '5EJaMlem2rASzuttx1_PtwGd2cuyAOtM8VJmwwiEudo')

NATIVE_TAG = 'mac' if IS_MACOS else 'linux'
NATIVE_RID = 'osx-arm64' if IS_MACOS else 'linux-x64'

# Dev runs use the pinned prebuilt toolchain that `python tools/build/fetch_native.py all`
# unpacks under utility/mex/<rid>/ and utility/hsdraw/<rid>/ (self-contained .NET, so no
# dotnet install and no DOTNET_ROOT are needed). Windows is always win-x64.
_DEV_RID = 'win-x64' if os.name == 'nt' else NATIVE_RID

# MEX CLI path (platform-aware)
if getattr(sys, 'frozen', False):
    # Running as compiled exe bundled with Electron
    if os.name == 'nt':
        MEXCLI_PATH = RESOURCES_DIR / "utility/mex/mexcli.exe"
    else:
        # Linux/macOS: prefer the per-OS dir (production), then mex (fallback)
        native_path = RESOURCES_DIR / f"utility/mex-{NATIVE_TAG}/mexcli"
        fallback_path = RESOURCES_DIR / "utility/mex/mexcli"
        MEXCLI_PATH = native_path if native_path.exists() else fallback_path
else:
    # Running as Python script (development): the fetched prebuilt MexCLI. The old
    # source-build output stays as a last-resort fallback for machines that still
    # carry it.
    def _first_existing(*cands):
        for c in cands:
            if c.exists():
                return c
        return cands[0]

    _mexcli_name = 'mexcli.exe' if os.name == 'nt' else 'mexcli'
    MEXCLI_PATH = _first_existing(
        RESOURCES_DIR / f"utility/mex/{_DEV_RID}/{_mexcli_name}",
        RESOURCES_DIR / f"utility/MexManager/MexCLI/bin/Release/net8.0/{'' if os.name == 'nt' else NATIVE_RID + '/'}{_mexcli_name}")

# HSDRawViewer path for 3D model streaming (platform-aware).
# On Linux the WinForms viewer cannot run; the headless port (HSDRawHeadless)
# ships the same CLI surface as a native `hsdrawviewer` binary.
if getattr(sys, 'frozen', False):
    if os.name == 'nt':
        HSDRAW_EXE = RESOURCES_DIR / "utility/HSDRawViewer/HSDRawViewer.exe"
    else:
        HSDRAW_EXE = RESOURCES_DIR / f"utility/hsdraw-{NATIVE_TAG}/hsdrawviewer"
else:
    if os.name == 'nt':
        HSDRAW_EXE = RESOURCES_DIR / "utility/hsdraw/win-x64/HSDRawViewer.exe"
    else:
        HSDRAW_EXE = RESOURCES_DIR / f"utility/hsdraw/{_DEV_RID}/hsdrawviewer"
    # Dev only: a local build of the HSDLib fork (ssbmNucleus-hsdlib), tried before its release is
    # published and pinned in hsdlib.manifest.json. Never read by a frozen app.
    if os.environ.get('NUCLEUS_HSDRAW_EXE', '').strip():
        HSDRAW_EXE = Path(os.environ['NUCLEUS_HSDRAW_EXE'].strip())

# User data paths (writable locations)
MEX_PROJECT_PATH = PROJECT_ROOT / "build/project.mexproj"
# NUCLEUS_STORAGE_DIR points the vault at an alternate folder without touching
# the real one — used by `run.bat --record` to load the curated demo vault
# (storage-sample) for trailer capture.
_storage_override = os.environ.get('NUCLEUS_STORAGE_DIR', '').strip()
if _storage_override and _data_override and not _smoke_mode:
    raise RuntimeError('NUCLEUS_STORAGE_DIR cannot be combined with a full NUCLEUS_DATA_ROOT selection')
STORAGE_PATH = Path(_storage_override) if _storage_override else PROJECT_ROOT / "storage"
CUSTOM_CHARACTERS_PATH = STORAGE_PATH / "custom_characters"
OUTPUT_PATH = PROJECT_ROOT / "output"
PROJECTS_PATH = PROJECT_ROOT / "projects"
LOGS_PATH = PROJECT_ROOT / "logs"

# Vault storage backend selector. 'json' = the historical storage/metadata.json
# (default, authoritative); 'db' = the SQLite vault.db. Set NUCLEUS_VAULT_DB=1 to
# opt in. Flip the default only once the migration is proven on real data — see
# docs/dev/VAULT_SQLITE_MIGRATION.md. Read live (via config.VAULT_BACKEND) at the DAL
# so it stays test-monkeypatchable.
_vault_flag = os.environ.get('NUCLEUS_VAULT_DB', '').strip().lower()
VAULT_BACKEND = 'db' if _vault_flag in ('1', 'true', 'db', 'yes', 'on') else 'json'
VAULT_DB_PATH = STORAGE_PATH / "vault.db"

# Dual-write canary: when the DB backend is active, ALSO keep metadata.json in
# sync on every save. This makes the JSON a live rollback backup and keeps any
# path=-based JSON reader (e.g. the duel assembler) current. On by default during
# rollout; set NUCLEUS_VAULT_DUAL_WRITE=0 to turn it off once the DB is proven.
_dual_write_flag = os.environ.get('NUCLEUS_VAULT_DUAL_WRITE', '').strip().lower()
VAULT_DUAL_WRITE = _dual_write_flag not in ('0', 'false', 'no', 'off')

# Asset paths (user-extracted assets, not bundled)
VANILLA_ASSETS_DIR = PROJECT_ROOT / "utility" / "assets" / "vanilla"

# Bundled community gecko-code library (49 named codes) used to seed the vault
# Codes section. Shipped builds carry it as seed_codes.ini beside mexcli — a
# DIFFERENT filename on purpose: a codes.ini beside mexcli.exe would change
# `mexcli create`/`import-iso` behavior (they load codes.ini from their own
# directory and would enable all 49 codes on every new project).
if getattr(sys, 'frozen', False):
    if os.name == 'nt':
        BUNDLED_CODES_INI = RESOURCES_DIR / "utility/mex/seed_codes.ini"
    else:
        _seed_native = RESOURCES_DIR / f"utility/mex-{NATIVE_TAG}/seed_codes.ini"
        BUNDLED_CODES_INI = _seed_native if _seed_native.exists() else RESOURCES_DIR / "utility/mex/seed_codes.ini"
else:
    BUNDLED_CODES_INI = RESOURCES_DIR / f"utility/mex/{_DEV_RID}/seed_codes.ini"

# Processor tools paths for CSP generation and slippi validation
if getattr(sys, 'frozen', False):
    # Running as bundled exe - modules are bundled in the exe
    PROCESSOR_DIR = Path(sys._MEIPASS) / "utility" / "tools" / "processor"
    SERVICES_DIR = Path(sys._MEIPASS) / "utility" / "tools" / "services"
else:
    # Running as Python script
    PROCESSOR_DIR = RESOURCES_DIR / "utility" / "tools" / "processor"
    SERVICES_DIR = RESOURCES_DIR / "utility" / "tools" / "services"

# Processor tools log into the app's logs folder (see processor/logging_config.py)
if _data_override or _smoke_mode:
    os.environ['NUCLEUS_LOGS_DIR'] = str(LOGS_PATH)
else:
    os.environ.setdefault('NUCLEUS_LOGS_DIR', str(LOGS_PATH))

# Add processor tools to path for imports (CSP generation, slippi validation)
sys.path.insert(0, str(PROCESSOR_DIR))
sys.path.insert(0, str(SERVICES_DIR))
sys.path.insert(0, str(BACKEND_DIR))

# Slippi bone-reference tables. They are retail game data, so nothing ships:
# bone_refs derives them from the user's own ISO into writable storage (see
# docs/dev/VANILLA_ASSET_POLICY.md). Teach the validator where to look, and give it
# a provider that generates them on demand -- installs made before first-run
# generation existed have no tables until something asks for them, and a
# validator with no references reports every costume "safe" instead of erroring
# (the silent failure mode from the shipped 0.6.4 Fix button).
try:
    import costume_validator as _costume_validator

    def _derive_bone_refs():
        # Imported lazily: bone_refs imports this module, so a top-level import
        # here would be circular.
        from shared.vanilla_extract.bone_refs import ensure_bone_refs
        return ensure_bone_refs()

    _costume_validator.set_ref_dir_provider(_derive_bone_refs)
except Exception:  # noqa: BLE001 - the validator is optional tooling
    pass

# Ensure directories exist
STORAGE_PATH.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH.mkdir(exist_ok=True)
PROJECTS_PATH.mkdir(exist_ok=True)
LOGS_PATH.mkdir(exist_ok=True)
MEX_PROJECT_PATH.parent.mkdir(exist_ok=True)  # Create build/ directory
