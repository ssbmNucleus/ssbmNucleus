# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for MEX Backend API
Comprehensive bundling with all dependencies audited
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs
import os
import sys
from pathlib import Path

# In PyInstaller spec files, use SPECPATH instead of __file__
# SPECPATH is tools/build (repo root/tools/build); the app (backend/, utility/, ...) is
# app/ beside tools/. `project_root` is that app dir; the repo root is its parent.
project_root = Path(SPECPATH).parent.parent / 'app'

# Platform detection for executable naming
IS_WINDOWS = sys.platform == 'win32'
EXE_EXTENSION = '.exe' if IS_WINDOWS else ''

# =============================================================================
# RELEASE GATES: which unreleased features this build carries
# =============================================================================
# A feature behind a packaged_off gate (backend/core/gates.py) is left out of
# the bundle entirely, not just switched off, unless this build asks for it as
# a preview feature (NUCLEUS_PREVIEW_FEATURES, the build.bat selector; owner,
# 2026-11-04: "i kind of want the unreleased feature code not included").
# ship_guard.gate_ships is the one rule (ship_rules.json "ships_with_gate"
# entries follow it too), and core/build_smoke.py names the packages per gate
# and re-checks the frozen result from inside the exe. Both are loaded as
# plain files: importing the core package would run core.config.
import importlib.util as _ilu


def _load_file(name, path):
    spec = _ilu.spec_from_file_location(name, path)
    module = _ilu.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_ship_guard = _load_file('nucleus_ship_guard', Path(SPECPATH) / 'ship_guard.py')
_build_smoke = _load_file('nucleus_build_smoke', project_root / 'backend' / 'core' / 'build_smoke.py')
GATE_SHIPS = {name: _ship_guard.gate_ships(name) for name in _build_smoke._GATED_PACKAGES}
ASSISTANT_SHIPS = GATE_SHIPS['assistant']
# Every module prefix a closed gate keeps out: PyInstaller excludes them, and the
# check after Analysis fails the build if any of them still reached the bundle.
GATED_OUT = tuple(package for name, packages in _build_smoke._GATED_PACKAGES.items()
                  if not GATE_SHIPS[name] for package in packages)
print('Release gates: ' + ', '.join(f"{name} {'ships' if ships else 'left out'}"
                                    for name, ships in GATE_SHIPS.items()))

# =============================================================================
# THIRD-PARTY PACKAGES (hiddenimports)
# =============================================================================

hiddenimports = [
    # Flask ecosystem
    'flask',
    'flask_cors',
    'flask_socketio',
    'socketio',
    'engineio',
    'werkzeug',
    'werkzeug.utils',
    'jinja2',
    'click',
    'itsdangerous',
    'markupsafe',

    # WebSocket support with all backends
    'simple_websocket',
    'wsproto',
    'h11',

    # Replay frame parsing for deep stats (tracker/stats/deep_stats.py)
    'peppi_py',

    # Threading support for SocketIO
    'threading',
    'queue',

    # EngineIO threading backend - CRITICAL for PyInstaller
    # async_threading was a module in old python-engineio; it no longer exists,
    # and async_drivers.threading above is the current name. It was reported
    # "not found" on every build.
    'engineio.async_drivers',
    'engineio.async_drivers.threading',

    # DNS: dnspython is NOT in the build venv (it is only needed for eventlet's
    # async resolver, and the threading driver above is what we use). Listing it
    # produced two more "not found" errors per build for a dependency that is
    # deliberately absent.

    # Logging
    'logging.handlers',

    # Image processing
    'PIL',
    'PIL.Image',
    'PIL.ImageOps',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'PIL.ImageEnhance',
    'PIL.ImageStat',
    'PIL.ImageGrab',  # in-game test screenshots

    # NumPy for image processing
    'numpy',

    # YAML parsing
    'yaml',

    # Compression
    'zipfile',
    'py7zr',  # Optional 7z support
    'rarfile',  # .rar support; drives the bundled UnRAR in utility/unrar*

    # JSON/Data
    'json',

    # Backend modules (from backend/)
    'vault.importing.character_detector',
    'vault.importing.stage_detector',
    'backend.app',

    # In-game test engine (backend/shared/ingame/*, imported lazily so not auto-found)
    'shared.ingame',
    'shared.ingame.runner',
    'shared.ingame.boot',
    'shared.ingame.nav',
    'shared.ingame.observe',
    'shared.ingame.screenshot',
    'shared.ingame.melee_mem',
    'shared.ingame.melee_pipe',
    'shared.ingame.melee_css',
    'shared.ingame.melee_sss',
    'shared.ingame.char_select',

    # Particle-bank decoder used lazily by vault/extras/relocate.py
    # (extras install on effect files). Belt-and-braces alongside the static
    # `from shared.rendering import ptcl_parse`; ptcl_texbank is its --verify companion.
    'shared.rendering.ptcl_parse',
    'shared.rendering.ptcl_texbank',

    # MexCLI access (backend/mexcli): the project API and the one-shot command
    # runner - CRITICAL package
    'mexcli.project',
    'mexcli.commands',

    # The frozen build's self-check, run by `mex_backend --build-smoke-test`
    'core.build_smoke',

    # Retried file writes/swaps (backend/file_retry). Statically imported by
    # core.metadata and most writers; named so a refactor can't drop it.
    'file_retry',

    # Single-costume temp ISO builder for the per-mod in-game test
    'projects.install.test_build',

    # Utility modules (dynamically imported)
    #
    # These resolve because the whole processor tree also ships as DATA (see the
    # 'utility/tools/processor/*.py' datas entry) and is imported from disk at
    # runtime. generate_stock_icon and validate_costume used to be listed here
    # too and PyInstaller reported both as "Hidden import not found" on every
    # build: nothing in backend/ imports them, and the app's own stock icons come from
    # backend/shared/rendering/stock_gen.py. Dropped rather than "fixed", because five
    # routine ERROR lines in a build log are how a real one goes unnoticed.
    'generate_csp',
    'csp_logs',             # generate_csp's renderer-log cleanup (imported by it, csp_pool and app.py)
    'detect_character',
    'costume_validator',
    'bone_tables',
    'shared.vanilla_extract.bone_refs',
    'shared.vanilla_extract.menu_refs',
    'dat_processor',
]

# =============================================================================
# PATH SETUP
# =============================================================================

# Add paths for module discovery
# NOTE: the three utility/website/backend/... entries that used to sit here were
# removed on 2026-08-19 -- that tree does not exist and has not for a long time,
# so they contributed nothing but the illusion that the processor modules were
# on the search path. They are delivered as data (see datas below) and imported
# from disk at runtime instead. Deliberately NOT replaced with
# utility/tools/processor: analysing that tree as code would bundle a second,
# frozen copy of modules the app already loads from disk, and the two could
# then disagree.
additional_paths = [
    str(project_root / 'backend'),
]
# collect_submodules() below runs NOW, before Analysis puts pathex on sys.path.
# Without backend/ on it, collect_submodules('shared.ingame'/'randall.model_import'/...)
# finds no such package and returns [] without a word (measured 2026-09-28 with
# PyInstaller 6.22: 0 modules where the path gave 73).
# Appended, so nothing in backend/ can shadow a module the spec itself imports.
if additional_paths[0] not in sys.path:
    sys.path.append(additional_paths[0])

# =============================================================================
# DATA FILES (datas)
# =============================================================================

datas = []

# Python modules from utility (must be bundled as source)
utility_modules = [
    ('utility/tools/processor/*.py', 'utility/tools/processor'),
    ('utility/tools/services/*.py', 'utility/tools/services'),
]

for src_pattern, dst_folder in utility_modules:
    import glob
    for py_file in glob.glob(str(project_root / src_pattern)):
        datas.append((py_file, dst_folder))

# CSP generation data — scene/pose/template/render files the CSP renderer needs,
# but NOT raw ISO-derived game data. Which names are "raw ISO-derived" is NOT
# decided here: ship_guard.csp_data_excluded() derives it from the
# `csp-data-roster` scrub rule in tools/build/ship_rules.json, the same rule
# that strips those files out of the electron packaging stage. Keeping a second
# copy of the list in this spec is how the frozen backend and the installer got
# to disagree about what counts as retail data.
# Nothing needs those DATs here: generate_csp reads its vanilla references from
# the data folder's storage/test-base/files, which first-run setup copies from
# the user's own ISO. Nothing at run time writes into this tree either.
sys.path.insert(0, SPECPATH)
from ship_guard import csp_data_excluded  # noqa: E402

csp_data_path = project_root / 'utility' / 'tools' / 'processor' / 'csp_data'
if csp_data_path.exists():
    for _f in csp_data_path.rglob('*'):
        if not _f.is_file():
            continue
        if csp_data_excluded(_f.name):
            continue  # raw ISO-derived — never bundle
        datas.append((str(_f), _f.parent.relative_to(project_root).as_posix()))
else:
    print(f'WARNING: csp_data not found at {csp_data_path} - CSP generation will be broken in this build')

# HSDRawViewer is NOT bundled into the backend exe: production uses the
# self-contained publish that electron-builder ships at resources/utility/HSDRawViewer
# (see package.json extraResources and Config.HSDRAW_EXE).

# Costume validator reference skeletons are NOT bundled. They are 159 per-bone
# transform tables lifted out of retail Pl*.dat -- Nintendo game data, and the
# last thing in this spec that still was. backend/shared/vanilla_extract/bone_refs.py derives them from
# the USER's own ISO into writable storage (<storage>/test-base/bone-refs) during
# first-run setup, and lazily on first validation for installs that predate it;
# costume_validator.ref_dir() finds that directory via the provider core.config
# registers. The in-tree copies stay for dev checkouts and are what
# tests/backend/test_bone_tables.py checks the generator against.
#
# The Windows-only SlippiCostumeValidator.exe/.dll are not bundled either:
# validation is pure Python now, and they remain in the tree solely as the
# oracle for the differential test in tests/backend/test_costume_validator.py.

# Vanilla character assets are NOT bundled. At runtime the frozen app reads them
# from %LOCALAPPDATA%\SSBM Nucleus\utility\assets\vanilla (config.VANILLA_ASSETS_DIR,
# a writable user dir — NOT this _MEIPASS bundle), populated from the USER's own ISO
# during first-run setup (first_run_setup._copy_character_assets). Bundling the dev's
# populated cache shipped ~102 MB of Nintendo game data that nothing reads. Ship none.
# (Sheik PNGs + menu sounds ship via electron extraResources, not this bundle.)

# Build assets (numbered CSPs and stock icons used by MEX)
build_assets_dir = project_root / 'build' / 'assets'
if build_assets_dir.exists():
    datas.append((str(build_assets_dir), 'build/assets'))

# Third-party license notices. Most bundled libraries (MIT, Ms-PL, Apache-2.0,
# Zlib) require their notice reach the end user, so this must ship, not just live
# in the repo. Served by shared/routes/legal.py for Settings > Credits & Licenses.
notices_file = project_root / 'THIRD_PARTY_NOTICES.md'
if notices_file.exists():
    datas.append((str(notices_file), '.'))

# Backend bundled assets (e.g. the hand-made Giga Bowser CSS icon used when
# seeding built-in custom characters). Modules resolve these from sys._MEIPASS
# in frozen builds via config.BACKEND_ASSETS_DIR.
#
# The retail HUD/pause/series IMAGERY is skipped: backend/shared/vanilla_extract/menu_refs.py exports
# it from the user's own game into utility/assets/menu_refs at first run and on
# project open, and the editors read only that copy (since 2026-11-19 the
# source tree holds none of these pictures; the skip stays so a re-added one
# still cannot reach the exe). Which files count as
# imagery is NOT decided here -- ship_guard.detect_excluded reads the
# `retail-hud-and-pause` category in ship_rules.json, the same list the guard
# flags a shipped artifact against. backend/assets is never staged for
# electron, so it reaches an installer only through this embed; a spec that
# disagreed with the rule is exactly how retail data kept shipping inside
# mex_backend. Note the slot MANIFESTS deliberately stay (md5s and dimensions,
# not pictures) so the mod-install path never depends on runtime derivation.
backend_assets_dir = project_root / 'backend' / 'assets'
if backend_assets_dir.exists():
    from ship_guard import detect_excluded  # noqa: E402
    for _f in backend_assets_dir.rglob('*'):
        if not _f.is_file():
            continue
        if detect_excluded('retail-hud-and-pause', _f.relative_to(project_root).as_posix()):
            continue
        datas.append((str(_f), _f.parent.relative_to(project_root).as_posix()))

# Backend bundled data. Keep this explicit so interpreter caches or ad-hoc
# analysis files under backend/data cannot silently enter the executable.
# Resolved via config.BACKEND_DATA_DIR (sys._MEIPASS in frozen builds).
backend_data_dir = project_root / 'backend' / 'data'
expected_backend_data = (
    'any_climbers.ini',
    'clone_engine.dat',
    'texture_filename_table_seed.json',
    'vanilla_geom_hashes.json',
    'menus/compatibility_manifest.json',
)
for filename in expected_backend_data:
    data_file = backend_data_dir / filename
    if not data_file.is_file():
        raise SystemExit(f'backend data missing: {data_file}')
    datas.append((str(data_file), (Path('backend/data') / filename).parent.as_posix()))

# nucleOME data (coach baselines + Watch Lite charmaps) ships by default since
# nucleOME's 0.7.0 release. Set NUCLEUS_BUNDLE_NUCLEOME=0 to strip it again
# (e.g. a build with nucleOME re-gated).
BUNDLE_NUCLEOME = os.environ.get('NUCLEUS_BUNDLE_NUCLEOME', '1') == '1'

if not BUNDLE_NUCLEOME:
    print('nucleOME: data EXCLUDED from this build (NUCLEUS_BUNDLE_NUCLEOME=0)')
else:
    # Coach baseline packs (tier populations + player pack + situation tables),
    # built by <monorepo>/build_packs_v2.py. coach_data resolves them from
    # sys._MEIPASS in frozen builds. These are git-tracked -- a clean clone
    # must produce the same installer as the dev box, so FAIL if absent.
    # NOTE: these ship even while Randall is gated off (NUCLEUS_RANDALL=0) --
    # the Stats page's /deep/baselines panels read the same packs.
    baselines_dir = project_root / 'backend' / 'tracker' / 'baselines'
    if baselines_dir.exists():
        datas.append((str(baselines_dir), 'backend/tracker/baselines'))
    else:
        raise SystemExit(f'nucleOME: coach baselines missing at {baselines_dir} '
                         '- the coach would ship with no reference data')

    # Watch Lite (in-browser character clips): the action->animation maps
    # (charmaps.json, git-tracked) bundle; the per-character animation zips
    # deliberately do NOT. They are slippilab-derived, git-ignored, and ~88 MB
    # -- bundling them only where the working tree happens to have them made
    # Windows/Linux installers diverge. Instead every nucleOME-enabled backend
    # start downloads missing zips in the background into
    # STORAGE_PATH/nucleome/anim_zips (tracker/routes/lite.py + first-run setup),
    # which clip_render falls back to when the bundle has none.
    lite_tools_dir = project_root / 'backend' / 'tracker' / 'tools'
    lite_charmaps = lite_tools_dir / 'charmaps.json'
    if lite_charmaps.exists():
        datas.append((str(lite_charmaps), 'backend/tracker/tools'))
    else:
        raise SystemExit(f'nucleOME: charmaps.json missing at {lite_charmaps} '
                         '- Watch Lite would be broken in this build')

# Dynamic Alternate Stages framework
das_dir = project_root / 'utility' / 'DynamicAlternateStages'
if das_dir.exists():
    datas.append((str(das_dir), 'utility/DynamicAlternateStages'))

# In-game test engine data: the calibrated CSS cursor grid (shared.ingame loads it via
# dirname(__file__)/grid.json, so it must land in the bundle's shared/ingame/ folder).
grid_json = project_root / 'backend' / 'shared' / 'ingame' / 'grid.json'
if grid_json.exists():
    datas.append((str(grid_json), 'shared/ingame'))

# =============================================================================
# BINARIES
# =============================================================================

binaries = []

hiddenimports += ['devtools.frameshot', 'devtools.effect_probe',
                  'devtools.extras_doctor', 'devtools.fps_batch', 'shared.rendering.datprobe']
hiddenimports += collect_submodules('shared.ingame')
hiddenimports += ['psutil']
# The assistant (backend/randall, the nucleus_api facade it scripts, and the AI
# plumbing in shared/aiengine) ships only when its gate does; see RELEASE GATES.
if ASSISTANT_SHIPS:
    # AI provider plumbing (imported lazily inside request handlers)
    hiddenimports += ['shared.aiengine', 'shared.aiengine.image_api', 'shared.aiengine.decisions',
                      'shared.aiengine.fast_lane', 'shared.aiengine.model_upload',
                      'huggingface_hub', 'tqdm']
    # Assistant help is needed in installed apps, which have no source wiki tree.
    for help_name in ('Vault-Vs-Project', 'Character-Mod-Workflow', 'CSP-And-Pose-Workflow',
                      'Slippi-Safety', 'Manual-Import', 'Skin-Creator', 'Test-In-Game',
                      'Vault-And-Distribution-Workflow', 'Assistant'):
        datas.append((str(project_root.parent / 'docs' / 'wiki' / (help_name + '.md')), 'assistant/help'))
    hiddenimports += ['randall.assistant.engine', 'randall.assistant.store', 'randall.assistant.tools']
    # The app's MCP server (randall/mcp, docs/dev/APP_MCP.md): shared/routes/mcp.py imports it lazily, behind
    # the assistant gate, on the first POST /api/mcp.
    hiddenimports += collect_submodules('randall.mcp')
    # The model import (backend/randall/model_import): import_model runs rigswap as a
    # subprocess and saves its costume to the vault. The app reaches the job and the
    # save only through lazy imports (studio_import -> import_job -> studio.finish), so collect the
    # package explicitly -- and fail if that found nothing. shared.modellab is its
    # fighter table.
    model_import_modules = collect_submodules('randall.model_import')
    for module in ('randall.model_import.chat.import_job', 'randall.model_import.studio.finish'):
        if module not in model_import_modules:
            raise SystemExit(f'randall.model_import: collect_submodules found no {module} '
                             f'(got {len(model_import_modules)}); is backend/ on sys.path?')
    hiddenimports += model_import_modules + collect_submodules('shared.modellab')
    # The scripting FACADE (nucleus_api). Nothing in the production import graph
    # reaches it: app.py never imports it, and the assistant tools that do import
    # it do so inside a function. That is fine in a dev checkout with the source on
    # disk and fatal in a frozen build, so name every public module here. Globbed
    # from the package directory rather than listed: the review found the facade
    # growing a module per surface (builds/menus/codes/...), and a spec that named
    # them one by one is the same failure mode that left initial_parts_state.json
    # out of preview.2.
    #
    # collect_submodules('nucleus_api') is deliberately NOT used: it IMPORTS the
    # package at analysis time, and the facade's import chain reaches the assistant
    # and the blueprint helpers, so a spec run would execute half the app.
    nucleus_api_dir = project_root / 'backend' / 'nucleus_api'
    nucleus_api_modules = sorted(p.stem for p in nucleus_api_dir.glob('*.py')
                                 if p.stem != '__init__')
    if 'gendocs' not in nucleus_api_modules:
        raise SystemExit('nucleus_api: gendocs.py missing — the facade layout changed')
    hiddenimports += ['nucleus_api'] + [f'nucleus_api.{name}' for name in nucleus_api_modules]
    # API.md is the facade's contract, read by the assistant when it writes a
    # script. tests/backend/test_api_md_equality.py keeps it equal to gendocs.build().
    nucleus_api_doc = nucleus_api_dir / 'API.md'
    if not nucleus_api_doc.is_file():
        raise SystemExit(f'nucleus_api: {nucleus_api_doc} missing')
    datas.append((str(nucleus_api_doc), 'nucleus_api'))

# TODO(S3/verification): the in-game verifier's `engine_version()` hashes its
# own SOURCE files (shared/ingame/*.py + devtools/frameshot.py). In a onefile build
# those paths do not exist, every hash collapses to None, and two different
# engines produce the same id — a cache key that cannot tell them apart.
# shared/ingame/verify_costume.py:256. The fix is a BUILD-generated digest manifest
# shipped beside the code and read in preference to the source hashes. No
# generator exists under tools/build/ as of 2026-09-22; when one lands it must
# write backend/shared/ingame/engine_digest.json and this block ships it without
# further edits. Until then the block is a no-op and the verifier keeps its
# source-hash behaviour, which is correct in a dev checkout and degraded (not
# wrong) when frozen.
engine_digest = project_root / 'backend' / 'shared' / 'ingame' / 'engine_digest.json'
if engine_digest.is_file():
    datas.append((str(engine_digest), 'shared/ingame'))
else:
    print('NOTE: shared/ingame/engine_digest.json not generated — the frozen verifier '
          'will fall back to source hashes (all None). See the TODO in this spec.')

# Native extras. vgamepad is optional (netplay tooling).
import importlib.util
if importlib.util.find_spec('vgamepad'):
    hiddenimports += collect_submodules('vgamepad')
    datas += collect_data_files('vgamepad')
    binaries += collect_dynamic_libs('vgamepad')

# Note: .NET executables (mexcli.exe, HSDRawViewer.exe) are included in datas
# They will be bundled in electron-builder separately with their full runtime

# =============================================================================
# ANALYSIS
# =============================================================================

a = Analysis(
    [str(project_root / 'backend' / 'app.py'),
     str(project_root / 'backend' / 'mexcli' / 'project.py')],
    pathex=additional_paths,
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude heavy packages not needed
        'matplotlib',
        'pandas',
        'tkinter',
        '_tkinter',
        'PyQt5',
        'PyQt6',
        'notebook',
        'IPython',
        'jupyter',

        # Test frameworks (not needed in production)
        'pytest',
        'pytest-flask',

        # Not used since shared/rendering/regions.py replaced scipy.ndimage. A
        # build venv that still has it installed must not ship its 82 compiled
        # files (docs/dev/WINDOWS_SIGNING.md).
        'scipy',

        # Unreleased features this build does not ship (RELEASE GATES above).
        *GATED_OUT,
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# A closed gate's code must not be in the bundle at all. An exclude stops
# PyInstaller following imports into it; this catches anything that still got
# in (a hidden import, a collect_submodules) before a stable build ships it.
_leaked = sorted({entry[0] for entry in a.pure
                  if any(entry[0] == p or entry[0].startswith(p + '.') for p in GATED_OUT)})
if _leaked:
    raise SystemExit('Release gates: unreleased code reached the bundle: ' + ', '.join(_leaked[:20]))
if GATED_OUT:
    print(f'Release gates: none of {", ".join(GATED_OUT)} is in the bundle')

# Cryptodome arrives only through py7zr (7z AES), but PyInstaller's stock hook
# bundles all 42 of its compiled files. A password-protected 7z loads these four
# (measured 2026-11-04, pycryptodomex 3.23, py7zr 1.0). Every unsigned compiled
# file is one Smart App Control can block (docs/dev/WINDOWS_SIGNING.md). The
# build smoke test's encrypted 7z round trip fails the build if this falls short.
CRYPTODOME_KEEP = {'_cpuid_c', '_raw_aes', '_raw_aesni', '_raw_cbc'}


def _cryptodome_unused(dest):
    parts = dest.replace('\\', '/').split('/')
    return parts[0] == 'Cryptodome' and parts[-1].split('.')[0] not in CRYPTODOME_KEEP


_unused = [entry for entry in a.binaries if _cryptodome_unused(entry[0])]
a.binaries = [entry for entry in a.binaries if not _cryptodome_unused(entry[0])]
print(f'Cryptodome: kept {", ".join(sorted(CRYPTODOME_KEEP))}; left out {len(_unused)} unused compiled files')

# =============================================================================
# BUNDLE
# =============================================================================

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=f'mex_backend{EXE_EXTENSION}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # Never UPX: it rewrites every packed dll/pyd and strips its Authenticode
    # signature, and Smart App Control checks them when the backend unpacks
    # them (check_pe_signatures.py reads the packed copies' sources).
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Console app so stdout/stderr work; Electron hides the window via windowsHide
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
