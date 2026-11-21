"""
Shared pytest fixtures for backend tests.

The headline fixture is `vault`, a temp-directory stand-in for the user's
`storage/` folder wired into the REAL `core.metadata` load/save path. Tests that
use it exercise actual metadata file IO (not monkeypatched lambdas), so the SAME
test will keep working when the storage backend swaps from metadata.json to
SQLite — that backend-agnostic property is the whole point of the Phase 0 safety
net for the vault-storage migration (see docs/VAULT_SQLITE_MIGRATION.md).

Usage:

    def test_something(vault):
        vault.write({'characters': {'Fox': {'skins': []}}})
        client = vault.client(storage_costumes, 'storage_costumes_bp')
        resp = client.post('/api/mex/storage/...', json={...})
        assert vault.read()['characters']['Fox']['skins'] == [...]
"""
import atexit
import functools
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import uuid
from pathlib import Path

import pytest
from flask import Flask


# SQLite in tests never waits for the disk. Every commit at the default
# synchronous=FULL flushes to the platter, and the assistant tests make a fresh
# chats.db and tasks.db per test and commit a dozen times a turn. In a checkout
# on a spinning disk (the randall-wt worktrees, under app/scratch, where
# core.config points tempfile) that was 65-230 ms a commit and about 5 s a
# download test, 138 s for four assistant files that take 4 s on an SSD; under
# load it ran into the tests' 5-second event timeouts. A flush only matters if
# the machine loses power mid-test. Patched before any app module is imported,
# so every connection the code under test opens gets it.
_sqlite_connect = sqlite3.connect


# The developer's real storage/nucleome.db holds credentials in its kv table
# (the Friends Discord session, the Patreon vault token). A test that forgets to
# point tracker.store.indexer.DB_PATH at tmp_path would read them, and a failing
# assert then prints a live token. Filled in below, once core.config is imported.
_REAL_CREDENTIAL_DBS = frozenset()


def _refuse_real_credential_db(database):
    if not _REAL_CREDENTIAL_DBS or not isinstance(database, (str, os.PathLike)):
        return
    name = os.fspath(database)
    if not isinstance(name, str) or name == ':memory:' or name.startswith('file:'):
        return
    if os.path.normcase(os.path.abspath(name)) in _REAL_CREDENTIAL_DBS:
        raise RuntimeError(
            f'Test opened the real {name}, which holds credentials. Point '
            'tracker.store.indexer.DB_PATH (or the path you connect to) at tmp_path.')


@functools.wraps(_sqlite_connect)
def _connect_without_flush(*args, **kwargs):
    _refuse_real_credential_db(args[0] if args else kwargs.get('database'))
    conn = _sqlite_connect(*args, **kwargs)
    try:
        conn.execute('PRAGMA synchronous=OFF')
    except sqlite3.DatabaseError:
        pass  # a corrupt or locked file reports itself at the caller's first statement, as before
    return conn


sqlite3.connect = _connect_without_flush

# Every test module historically inserts BACKEND_DIR itself; doing it here once
# (conftest imports before test collection) makes `import core.*` / `vault.*` / `shared.*`
# work without each test repeating the boilerplate.
# Path constants: defined once in tests/paths.py (repo/tests/backend/conftest.py is two levels
# below the repo root) and exposed here as module globals and as the `repo_paths` fixture.
from tests.paths import REPO, APP, BACKEND  # noqa: E402
BACKEND_DIR = BACKEND
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import core.metadata as core_metadata  # noqa: E402
import core.config as core_config      # noqa: E402

from tracker.store import indexer as tracker_indexer  # noqa: E402

_REAL_CREDENTIAL_DBS = frozenset(
    os.path.normcase(os.path.abspath(core_config.STORAGE_PATH / name)) for name in ('nucleome.db',))

# Nothing should read nucleome.db while pytest collects, but if an import ever
# does, it gets a throwaway database; private_nucleome_db below gives each test
# its own.
_collection_db_dir = tempfile.mkdtemp(prefix='nucleome-collect-')
atexit.register(shutil.rmtree, _collection_db_dir, ignore_errors=True)
tracker_indexer.DB_PATH = Path(_collection_db_dir) / 'nucleome.db'


@pytest.fixture(scope='session')
def repo_paths():
    """REPO / APP / BACKEND as a namespace (same values as the module globals)."""
    from types import SimpleNamespace
    return SimpleNamespace(REPO=REPO, APP=APP, BACKEND=BACKEND)


@pytest.fixture(autouse=True)
def disable_live_fast_routing(monkeypatch):
    """Existing provider fakes must never fall through to a real Gemini or Jev
    request. A turn now opens with a decision call, so the decision endpoint
    needs the same default-off treatment as the fast lane.

    Routing integration tests explicitly enable them and fake the HTTP boundary.
    """
    monkeypatch.setenv('NUCLEUS_FAST_ROUTING', '0')
    monkeypatch.setenv('NUCLEUS_JEV_ROUTING', '0')


@pytest.fixture(autouse=True)
def no_live_mod_website(monkeypatch):
    """Randall's website tests fake the public mods API (tests/backend/website_site.py).
    One that forgets must fail at once, not search the live ssbmnucleus.net. The
    opt-in live test puts back `website_site.REAL_API`."""
    posts = sys.modules.get('randall.website.website_posts')
    if posts is not None:
        def refuse(path, params=None):
            raise AssertionError(f'test reached the live mod website: GET {path}')
        monkeypatch.setattr(posts, '_api', refuse)

        def refuse_rpc(name, *args, **kwargs):
            raise AssertionError(f'test reached the live website RPC {name}')
        for module in (posts, sys.modules.get('randall.website.website')):
            if module is not None:
                monkeypatch.setattr(module, '_rpc', refuse_rpc)


@pytest.fixture(scope='session')
def _test_shots_base(tmp_path_factory):
    return tmp_path_factory.mktemp('test-shots')


@pytest.fixture(autouse=True)
def test_shots_stay_in_tmp(monkeypatch, _test_shots_base):
    """An in-game test or capture writes its screenshots under output/test-shots
    (projects.routes.test_in_game.SHOTS_ROOT). A test that drives one writes
    them to its own temp folder, never into the dev app's output."""
    tig = sys.modules.get('projects.routes.test_in_game')
    if tig is not None:
        monkeypatch.setattr(tig, 'SHOTS_ROOT', _test_shots_base / uuid.uuid4().hex)


# ---------------------------------------------------------------------------
# Process-wide state a test must not hand to the next one. pytest-xdist runs
# many files in one worker process, and which files share a worker changes
# from run to run, so a leak here shows up as a different test failing in
# different runs.
# ---------------------------------------------------------------------------

def _menu_ref_derivations():
    return {t for t in threading.enumerate() if t.name == 'menu-refs-derive'}


@pytest.fixture(autouse=True)
def open_project_is_per_test(monkeypatch):
    """The open project (core.state) is a module global. Tests that opened one
    and never closed it left it open for every later test in the worker, and a
    route that writes the build (costumes' import, restore-vanilla) then tried
    to lock a project directory pytest had already deleted ("No such build
    directory: ...test_remove_route_deletes_vari0/project").

    Opening a project through set_project_path also starts the menu-ref
    derivation thread, which runs HSDRawViewer on that project and publishes
    into utility/assets/menu_refs with os.replace. A test must not leave that
    thread running into the next one, so it is waited for here.
    """
    from core import state
    monkeypatch.setattr(state, '_current_project_path', state._current_project_path)
    monkeypatch.setattr(state, '_mex_manager', state._mex_manager)
    before = _menu_ref_derivations()
    yield
    for thread in _menu_ref_derivations() - before:
        thread.join(timeout=120)


@pytest.fixture
def open_project(monkeypatch):
    """Open a project for one test without set_project_path's side effect.

    set_project_path also starts the menu-ref derivation thread, which exports
    the test project's GmPause / IfAll with HSDRawViewer and publishes the
    result over the developer's real utility/assets/menu_refs. Setting the
    state directly is what opening a project means for these tests; it is
    undone when the test ends.
    """
    from core import state

    def open_(project_path):
        monkeypatch.setattr(state, '_current_project_path', Path(project_path))
        monkeypatch.setattr(state, '_mex_manager', None)
    return open_


@pytest.fixture(autouse=True)
def nucleus_api_workspace_is_per_test():
    """nucleus_api caches its workspace root keyed by the NUCLEUS_API_WORKSPACE
    string, together with the directory's identity. Tests point that variable
    at tmp_path, and pytest hands a deleted tmp_path's name to the next test
    with the same 30-character prefix (test_a_stale_approval_is_rejected_when_
    the_build_moved and ..._the_artifact_moved both get
    test_a_stale_approval_is_rejec0). The cache then answered with the identity
    of the deleted directory and refused the new one as "replaced". A test
    starts and ends with nothing installed.
    """
    def forget():
        workspace = sys.modules.get('nucleus_api._workspace')
        if workspace is not None:
            workspace.reset_workspace()
    forget()
    yield
    forget()


@pytest.fixture(autouse=True)
def private_scratch(tmp_path_factory, monkeypatch):
    """core.config.SCRATCH_PATH is the real app/scratch, shared by every
    xdist worker and every run on this machine. The website quarantine reads it
    at call time, and each process empties its quarantine folder on first use,
    so one worker deleted the objects another worker was reading (PermissionError
    on a delete-pending .bin). Each test gets its own folder, created only if
    something writes there.
    """
    root = tmp_path_factory.getbasetemp() / 'scratch' / uuid.uuid4().hex
    monkeypatch.setattr(core_config, 'SCRATCH_PATH', root)


@pytest.fixture(autouse=True)
def private_nucleome_db(tmp_path_factory, monkeypatch):
    """tracker.store.indexer.DB_PATH is the real storage/nucleome.db, whose kv
    table holds the developer's Friends Discord session and Patreon vault token.
    Every test starts on its own empty database (created only if something
    connects); tests that seed one still monkeypatch DB_PATH themselves.
    """
    root = tmp_path_factory.getbasetemp() / 'nucleome'
    root.mkdir(exist_ok=True)
    monkeypatch.setattr(tracker_indexer, 'DB_PATH', root / f'{uuid.uuid4().hex}.db')


@pytest.fixture(autouse=True)
def private_dolphin_pool(tmp_path_factory, monkeypatch):
    """shared.ingame.dolphin_lock.LOCK_PATH is this machine's real harness lock
    under %LOCALAPPDATA%, and the file beside it (harness-dolphin.json) says how
    many harness Dolphins the machine runs and which copies of Dolphin they
    are. On a dev machine set to several slots a boot neither waits for other
    Dolphins nor runs the stock one, and a test that assumed one slot failed
    there (2026-11-10). Every test starts on a machine of its own: no lock
    files, no machine file, no pool settings in the environment. The folder is
    created only if something takes a lock.
    """
    from shared.ingame import dolphin_lock
    root = tmp_path_factory.getbasetemp() / 'harness-lock' / uuid.uuid4().hex
    monkeypatch.setattr(dolphin_lock, 'LOCK_PATH', root / dolphin_lock.LOCK_PATH.name)
    monkeypatch.delenv('NUCLEUS_DOLPHIN_SLOTS', raising=False)
    monkeypatch.delenv('NUCLEUS_DOLPHIN_SLOT_DIR', raising=False)


@pytest.fixture(autouse=True)
def close_lab_sessions_left_open():
    """Skin/Stage Lab sessions deliberately outlive a turn (follow-up edits use
    them) and are capped at two. A test that runs a real turn -- a recolor
    workflow opens a private skin copy -- would otherwise leave a live viewer
    process behind, and every later open in this process fails with "Close an
    existing Skin Lab session first". Close only what this test opened."""
    labs = [sys.modules.get(name) for name in ('randall.recolor.skin_lab', 'randall.recolor.stage_lab')]
    before = {id(lab): set(lab._sessions) for lab in labs if lab is not None}
    yield
    for name in ('randall.recolor.skin_lab', 'randall.recolor.stage_lab'):
        lab = sys.modules.get(name)
        if lab is None:
            continue
        with lab._lock:
            for session_id in set(lab._sessions) - before.get(id(lab), set()):
                item = lab._sessions.pop(session_id, None)
                if item is None:
                    continue
                # Test doubles carry only some of these; a failed close must not
                # fail the test that already passed.
                for release in (lambda: item['timer'].cancel(), lambda: item['viewer'].close(),
                                lambda: item['scratch'].cleanup()):
                    try:
                        release()
                    except Exception:
                        pass


class VaultHarness:
    """A temp vault: real metadata IO + filesystem helpers + a wired Flask client."""

    def __init__(self, storage: Path, monkeypatch):
        self.storage = storage
        self.project_root = storage.parent
        self._mp = monkeypatch

    # ---- metadata IO (goes through the real core.metadata, redirected to tmp) ----
    def write(self, metadata: dict) -> dict:
        core_metadata.save_metadata(metadata)
        return metadata

    def read(self):
        return core_metadata.load_metadata()

    # ---- filesystem helpers ----
    def path(self, *parts) -> Path:
        p = self.storage.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def touch(self, *parts, data: bytes = b'x') -> Path:
        p = self.path(*parts)
        p.write_bytes(data)
        return p

    def add_costume_files(self, character, skin_id, *, csp=False, stock=False, hd=False):
        """Create the on-disk footprint that list_storage_costumes checks for."""
        self.touch(character, f'{skin_id}.zip')
        if csp:
            self.touch(character, f'{skin_id}_csp.png')
        if stock:
            self.touch(character, f'{skin_id}_stc.png')
        if hd:
            self.touch(character, f'{skin_id}_csp_hd.png')

    def add_stage_variant_zip(self, stage, variant_id):
        """Stage variant zips live at storage/das/<stage>/<id>.zip."""
        self.touch('das', stage, f'{variant_id}.zip')

    # ---- Flask client wired to this vault ----
    def client(self, module, bp_attr: str):
        """Build a test client for one blueprint, repointing its module-level
        STORAGE_PATH / PROJECT_ROOT at this temp vault. (Blueprints bind those
        names at import time, so patching core.config alone is not enough.)
        A blueprint package (vault/routes/storage_costumes/) splits its routes
        over submodules, each with its own binding: those are repointed too."""
        modules = [module]
        if hasattr(module, '__path__'):
            prefix = module.__name__ + '.'
            modules += [m for name, m in sorted(sys.modules.items())
                        if name.startswith(prefix) and m is not None]
        for mod in modules:
            if hasattr(mod, 'STORAGE_PATH'):
                self._mp.setattr(mod, 'STORAGE_PATH', self.storage)
            if hasattr(mod, 'PROJECT_ROOT'):
                self._mp.setattr(mod, 'PROJECT_ROOT', self.project_root)
        app = Flask(__name__)
        app.register_blueprint(getattr(module, bp_attr))
        return app.test_client()


@pytest.fixture
def vault(tmp_path, monkeypatch):
    storage = tmp_path / 'storage'
    storage.mkdir()
    # Redirect the canonical metadata file at the temp vault. core.metadata
    # resolves METADATA_FILE at call time, and every blueprint's load_metadata/
    # save_metadata is the same function object, so this one patch covers them all.
    monkeypatch.setattr(core_metadata, 'METADATA_FILE', storage / 'metadata.json')
    monkeypatch.setattr(core_config, 'STORAGE_PATH', storage, raising=False)
    # Default to the JSON backend (existing tests assert JSON-specific behavior).
    monkeypatch.setattr(core_config, 'VAULT_BACKEND', 'json', raising=False)
    monkeypatch.setattr(core_config, 'VAULT_DB_PATH', storage / 'vault.db', raising=False)
    monkeypatch.setattr(core_config, 'VAULT_DUAL_WRITE', False, raising=False)
    return VaultHarness(storage, monkeypatch)


@pytest.fixture(params=['json', 'db'])
def dual_backend(request, tmp_path, monkeypatch):
    """Like `vault`, but parametrized over BOTH storage backends so a single
    test asserts identical behavior on JSON and SQLite — the equivalence proof
    for the metadata.json -> DB migration."""
    storage = tmp_path / 'storage'
    storage.mkdir()
    monkeypatch.setattr(core_metadata, 'METADATA_FILE', storage / 'metadata.json')
    monkeypatch.setattr(core_config, 'STORAGE_PATH', storage, raising=False)
    monkeypatch.setattr(core_config, 'VAULT_DB_PATH', storage / 'vault.db', raising=False)
    monkeypatch.setattr(core_config, 'VAULT_BACKEND', request.param, raising=False)
    # Test each backend in isolation; dual-write is covered by its own test.
    monkeypatch.setattr(core_config, 'VAULT_DUAL_WRITE', False, raising=False)
    harness = VaultHarness(storage, monkeypatch)
    harness.backend = request.param
    return harness
