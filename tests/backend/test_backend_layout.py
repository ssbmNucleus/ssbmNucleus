"""Guard the backend package layout (2026-08-22 root cleanup).

The backend root holds entry points and the configuration-free storage bootstrap.
Ordinary application modules live in packages.
Modules that locate sibling trees through ``__file__`` depth are pinned here
because a move silently re-points them (character_detector's UTILITY_DIR did
exactly that during the cleanup and no other test noticed).
"""
from tests.gated import present
from tests.paths import BACKEND
from pathlib import Path
import subprocess
import sys



def test_root_holds_only_entry_points_and_storage_bootstrap():
    root_py = sorted(p.name for p in BACKEND.glob("*.py"))
    # Relocation and its shared lock must run before core.__init__ imports
    # configuration and acquires a lifetime lease on the active data root.
    assert root_py == ["app.py", "storage_data_lock.py",
                       "storage_relocation.py"], root_py


def test_storage_bootstrap_does_not_initialize_application():
    subprocess.run([
        sys.executable, "-c",
        "import sys; import storage_relocation; "
        "assert 'storage_data_lock' in sys.modules; "
        "assert not any(name in sys.modules for name in ('core', 'app', 'flask'))",
    ], cwd=BACKEND, check=True, timeout=10)


def test_mexcli_project_does_not_initialize_core():
    """core.state imports mexcli.project while core is initialising, and standalone
    workers use MexManager without the app's configuration, so neither the mexcli
    package nor its project API may import core (importing core runs core.config)."""
    subprocess.run([
        sys.executable, "-c",
        "import sys; import mexcli.project; "
        "assert not any(n == 'core' or n.startswith('core.') for n in sys.modules), "
        "sorted(n for n in sys.modules if n.startswith('core')); "
        "assert 'flask' not in sys.modules",
    ], cwd=BACKEND, check=True, timeout=10)


def test_packages_exist():
    # The 2026-10-03 reorganisation: folders mirror the app (Vault, Projects, Upload,
    # Tracker, Randall) plus the engines and routes every area shares.
    for pkg in ("core", "vault", "vault/routes", "vault/importing", "vault/climbers", "vault/echo",
                "projects", "projects/routes", "projects/install", "upload", "upload/routes",
                "vault/catalog", "vault/routes/custom_characters", "projects/routes/menus",
                "vault/menus", "vault/extras", "vault/importing/unified", "vault/routes/storage_costumes",
                "tracker", "tracker/routes", "tracker/store", "tracker/replays", "tracker/video",
                "tracker/video/combo_video", "tracker/stats", "tracker/combos",
                "tracker/cloud", "tracker/share", "randall", "randall/routes", "shared", "shared/routes",
                "randall/assistant", "randall/assistant/tasks", "randall/recolor", "randall/model_import/chat",
                "randall/website", "randall/delivery", "randall/reports", "randall/coach",
                "shared/rendering", "shared/modellab", "shared/ingame", "shared/aiengine",
                "shared/vanilla_extract", "shared/diagnostics", "nucleus_api", "devtools", "file_retry", "mexcli"):
        if pkg in LEFT_OUT_OF_PUBLIC and not present(LEFT_OUT_OF_PUBLIC[pkg]):
            continue
        assert (BACKEND / pkg / "__init__.py").is_file(), pkg


#: Packages the public source drop leaves out, and the gate each belongs to (core/build_smoke.py).
LEFT_OUT_OF_PUBLIC = {"tracker/video/combo_video": "combo_video", "randall/coach": "randall"}


def test_pre_reorganisation_packages_are_gone():
    """A leftover __pycache__ folder may survive a pull; a package may not."""
    for pkg in ("blueprints", "skinlab", "modellab", "ingame", "aiengine", "vanilla_extract",
                "nucleome_replays", "mod_install", "mod_vault_import", "climbers", "echo",
                "randall/blueprints", "tracker/combo_video"):
        assert not (BACKEND / pkg / "__init__.py").exists(), pkg


def test_randall_assistant_holds_the_chat_only():
    """The 2026-10-03 Randall reorganisation: each pipeline has its own package and the flat
    assistant/ keeps the chat itself. A module left behind by a pull would shadow nothing but
    would be read by the next person as the live copy."""
    moved = {"recolor": ("workflows", "skin_lab", "stage_lab", "materials", "texture_material",
                         "texture_inspection", "swatch_library", "vanilla"),
             "model_import/chat": ("studio_import", "import_job", "attached_model"),
             "website": ("website", "website_artwork", "website_bulk", "website_exports", "website_posts",
                         "website_protocol", "website_quarantine", "website_receipts", "website_safety",
                         "website_scope", "website_search", "vault_presence"),
             "delivery": ("deliver", "deliver_checks", "deliver_policy", "deliver_project", "deliver_receipts",
                          "deliver_replies", "deliver_steps", "destination", "game_tests", "projects"),
             "reports": ("chat_report", "chat_report_files", "report_transport", "wishes", "wish_evidence",
                         "wish_gate", "wish_keys", "wish_ledger", "wish_submit", "wish_text")}
    randall = BACKEND / "randall"
    for package, names in moved.items():
        for name in names:
            assert (randall / package / f"{name}.py").is_file(), (package, name)
            assert not (randall / "assistant" / f"{name}.py").exists(), name
            assert not (randall / "assistant" / "tasks" / f"{name}.py").exists(), name


def test_character_detector_utility_dir_resolves():
    from vault.importing import character_detector
    from core.config import PROJECT_ROOT
    assert character_detector.SCRIPT_DIR == PROJECT_ROOT
    assert character_detector.UTILITY_DIR == PROJECT_ROOT / "utility" / "tools" / "processor"
    assert character_detector.UTILITY_DIR.is_dir()


def test_devtools_shims_point_at_backend():
    """Every devtools script that imports backend code bootstraps sys.path to
    backend/ (so it runs from any cwd). Stdlib/PIL-only scripts need no shim."""
    import ast
    backend_names = ({p.name for p in BACKEND.iterdir() if p.is_dir() and p.name != '__pycache__'}
                     | {p.stem for p in BACKEND.glob("*.py")})
    for script in list((BACKEND / "devtools").glob("*.py")) + list((BACKEND / "devtools" / "research").glob("*.py")):
        if script.name == "__init__.py":
            continue
        src = script.read_text(encoding="utf-8")
        imported = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split('.')[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                imported.add(node.module.split('.')[0])
        if not imported & backend_names:
            continue
        depth = "parents[2]" if script.parent.name == "research" else "parents[1]"
        assert depth in src or "os.path.dirname(os.path.dirname(" in src, f"{script.name} lacks a backend/ sys.path shim"


def test_tracker_data_dirs_resolve():
    """tracker/baselines and tracker/tools stay at the package root (the spec ships
    them to backend/tracker/{baselines,tools}); the modules that find them, and
    watch_mods' backend dir, count __file__ levels from one folder further down
    since the 2026-10-03 feature split."""
    from tracker.stats import baseline_ranks
    from tracker.video import clip_render
    from tracker.replays import watch_mods
    backend = BACKEND.resolve()
    assert Path(baseline_ranks.BASE_DIR).resolve() == backend / "tracker" / "baselines"
    if present("randall"):
        from randall.coach import coach_data
        assert Path(coach_data.BASE_DIR).resolve() == backend / "tracker" / "baselines"
    assert Path(clip_render.TOOLS_DIR).resolve() == backend / "tracker" / "tools"
    assert Path(clip_render.CHARMAPS_PATH).is_file()
    assert Path(watch_mods.BACKEND_DIR).resolve() == backend
