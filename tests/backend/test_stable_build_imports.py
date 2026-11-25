"""What a stable build carries, and shipped code never imports a package a build can leave out.

Since 0.9.0 a stable build carries the assistant (Randall's chat, its tools and the
app MCP: `randall`, `nucleus_api`, `shared.aiengine`, `shared.modellab`, the
build-change approval route) and its model-import runtime, and still leaves out
Combo Video and the Tracker coach (`randall.coach`, gate "randall"). Windows
stable builds also carry Play since 0.10.0. Every gate can
still be closed for a build (core/gates.py packaged_off), so the import rule below
holds for each of them.

test_stable_build_boots.py proves app.py starts without the left-out packages, but
it only sees imports that run at startup. Most of the app imports lazily, inside
the function that needs it, and such an import only fails when a user reaches that
function in an installed app. This walks every shipped backend module and refuses
an import of a gate's packages (core/build_smoke.py, _GATED_PACKAGES) from code
outside that gate unless it sits under an ``if ...enabled(...)`` gate check.
"""
import ast
import importlib.util
import json
import os
import subprocess
import sys

import pytest

from tests.paths import APP, BACKEND, REPO

sys.path.insert(0, str(BACKEND))
from core import build_smoke  # noqa: E402
from core.build_smoke import _GATED_PACKAGES  # noqa: E402
from core.gates import GATES  # noqa: E402

GATED = tuple(p for packages in _GATED_PACKAGES.values() for p in packages)

# Not shipped as app code: CLIs and probes the app never imports.
NOT_APP_CODE = ('devtools/', 'scripts/', 'probes/')

#: What a stable build carries, spelled out on purpose: a test that derived it from
#: gates.py would pass whatever gates.py said.
STABLE_SHIPS = {'assistant': True, 'combo_video': False, 'randall': False, 'play': sys.platform == 'win32'}


def _under(name, packages):
    return any(name == p or name.startswith(p + '.') for p in packages)


def _app_modules():
    listed = subprocess.run(['git', 'ls-files', '--', 'app/backend/*.py'], cwd=REPO,
                            capture_output=True, text=True, check=True).stdout.split()
    for rel in listed:
        rel = rel[len('app/backend/'):]
        module = rel[:-3].replace('/', '.')
        if module.endswith('.__init__'):
            module = module[:-len('.__init__')]
        if rel.startswith(NOT_APP_CODE):
            continue
        yield rel, module


def _imports(tree, module):
    """(lineno, imported name, guarded) for every import in the module."""
    def visit(node, guarded):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.If) and 'enabled(' in ast.unparse(child.test):
                # Only the true branch is behind the gate.
                for stmt in child.body:
                    yield from visit_one(stmt, True)
                for stmt in child.orelse:
                    yield from visit_one(stmt, guarded)
                continue
            yield from visit_one(child, guarded)

    def visit_one(node, guarded):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name, guarded
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ''
            if node.level:
                parts = module.split('.')
                anchor = parts[:len(parts) - node.level]
                base = '.'.join(anchor + ([base] if base else []))
            for alias in node.names:
                yield node.lineno, f'{base}.{alias.name}' if base else alias.name, guarded
                if base:
                    yield node.lineno, base, guarded
        yield from visit(node, guarded)

    yield from visit(tree, False)


def test_shipped_code_imports_no_left_out_package():
    """Per gate: code outside a gate's packages reaches them only under an enabled() check.

    The assistant's own code counts as shipped for the coach and Combo Video, since a
    stable build carries it without them."""
    modules = list(_app_modules())
    trees = {rel: ast.parse((BACKEND / rel).read_text(encoding='utf-8'), filename=rel)
             for rel, _module in modules}
    offenders = []
    for gate, packages in _GATED_PACKAGES.items():
        for rel, module in modules:
            if _under(module, packages):
                continue
            for lineno, name, guarded in _imports(trees[rel], module):
                if _under(name, packages) and not guarded:
                    offenders.append(f'app/backend/{rel}:{lineno} imports {name} ({gate})')
    assert not offenders, ('shipped code imports a package a build can leave out; move what it '
                           'needs into shipped code, or import it behind the gate:\n  '
                           + '\n  '.join(sorted(set(offenders))))


def _ship_guard():
    spec = importlib.util.spec_from_file_location(
        'ship_guard_for_stable_test', REPO / 'tools' / 'build' / 'ship_guard.py')
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    return guard


def test_every_gate_with_left_out_code_is_a_release_gate():
    assert set(_GATED_PACKAGES) == set(STABLE_SHIPS)
    assert set(_GATED_PACKAGES) <= set(GATES)


def test_a_stable_build_carries_the_expected_gated_code(monkeypatch):
    """The build rule (ship_guard.gate_ships: the spec, the stage, the build scripts)."""
    monkeypatch.delenv('NUCLEUS_PREVIEW_FEATURES', raising=False)
    guard = _ship_guard()
    assert {name: guard.gate_ships(name) for name in _GATED_PACKAGES} == STABLE_SHIPS


def test_the_frozen_smoke_expects_the_same_contents(monkeypatch):
    """core/build_smoke.py re-checks the bundle from inside the exe with its own copy of the rule."""
    monkeypatch.delenv('NUCLEUS_PREVIEW_FEATURES', raising=False)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    assert {name: build_smoke._feature_ships(name) for name in _GATED_PACKAGES} == STABLE_SHIPS
    # A preview can still ask for a gate a stable build leaves out.
    monkeypatch.setenv('NUCLEUS_PREVIEW_FEATURES', 'assistant,randall')
    assert build_smoke._feature_ships('randall') is True
    assert build_smoke._feature_ships('combo_video') is False


@pytest.mark.parametrize('packaged_off', [False, True], ids=['shipped', 'held-back'])
def test_the_gate_still_leaves_the_assistant_out_when_it_is_held_back(monkeypatch, packaged_off):
    """Holding the assistant back for a build is one switch: gates.py packaged_off."""
    monkeypatch.delenv('NUCLEUS_PREVIEW_FEATURES', raising=False)
    monkeypatch.setitem(GATES, 'assistant', GATES['assistant']._replace(packaged_off=packaged_off))
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    assert build_smoke._feature_ships('assistant') is (not packaged_off)
    # A preview package opens it again, as for the 0.9.0 previews.
    monkeypatch.setenv('NUCLEUS_PREVIEW_FEATURES', 'assistant')
    assert build_smoke._feature_ships('assistant') is True


def test_the_gate_command_the_build_scripts_ask():
    """build.bat, build-linux.sh and build-macos.sh set the frontend flag from its exit code."""
    env = {k: v for k, v in os.environ.items() if k != 'NUCLEUS_PREVIEW_FEATURES'}
    script = REPO / 'tools' / 'build' / 'ship_guard.py'
    shipped = subprocess.run([sys.executable, str(script), 'gate', 'assistant'],
                             capture_output=True, text=True, env=env, timeout=60)
    assert shipped.returncode == 0 and 'assistant: ships' in shipped.stdout, shipped.stdout + shipped.stderr
    held = subprocess.run([sys.executable, str(script), 'gate', 'combo_video'],
                          capture_output=True, text=True, env=env, timeout=60)
    assert held.returncode == 1 and 'left out' in held.stdout, held.stdout + held.stderr
    for name in ('build.bat', 'build-linux.sh', 'build-macos.sh'):
        text = (REPO / 'tools' / 'build' / name).read_text(encoding='utf-8')
        assert 'ship_guard.py" gate assistant' in text, name
        assert 'VITE_ASSISTANT_PREVIEW=1' in text, name
        # the flag is decided before the frontend is built
        assert text.index('gate assistant') < text.index('npm run build'), name


def test_the_frontend_flag_is_the_one_the_build_scripts_set():
    features = (APP / 'frontend' / 'src' / 'shared' / 'config' / 'features.js').read_text(encoding='utf-8')
    line = next(line for line in features.splitlines() if line.startswith('export const ASSISTANT_ENABLED'))
    assert "import.meta.env.VITE_ASSISTANT_PREVIEW === '1'" in line, line


def _dist(tmp_path, *chunks):
    assets = tmp_path / 'frontend' / 'dist' / 'assets'
    assets.mkdir(parents=True)
    for chunk in chunks:
        (assets / f'{chunk}-a1b2c3.js').write_text('//', encoding='utf-8')
    return tmp_path


def test_the_stage_verifies_gated_chunks_for_the_platform(tmp_path, monkeypatch):
    monkeypatch.delenv('NUCLEUS_PREVIEW_FEATURES', raising=False)
    guard = _ship_guard()
    play_chunks = ('PlayApp',) if STABLE_SHIPS['play'] else ()
    good = _dist(tmp_path / 'good', 'index', 'AssistantPanel', *play_chunks)
    assert guard.gated_frontend_leaks(good) == []
    assert guard.gated_frontend_missing(good) == []

    missing = guard.gated_frontend_missing(_dist(tmp_path / 'missing', 'index'))
    assert any('AssistantPanel' in m for m in missing)
    assert any('PlayApp' in m for m in missing) is STABLE_SHIPS['play']

    leaky = _dist(tmp_path / 'leaky', 'index', 'AssistantPanel', 'PlayApp', 'CoachPage', 'ComboVideoPage')
    leaks = guard.gated_frontend_leaks(leaky)
    assert any('CoachPage' in leak for leak in leaks) and any('ComboVideoPage' in leak for leak in leaks)
    assert not any('AssistantPanel' in leak for leak in leaks)
    assert any('PlayApp' in leak for leak in leaks) is not STABLE_SHIPS['play']


def test_a_stable_stage_carries_the_model_import_package_on_every_platform(monkeypatch):
    """Randall's model import needs rigswap's package and the manifest of the tools the user downloads (its Python
    and Blender: utility/model_import_tools.json): staged and verified in every stable build now that the
    assistant ships. Neither Blender nor rigswap's Python ships in any installer since 0.9.0."""
    monkeypatch.delenv('NUCLEUS_PREVIEW_FEATURES', raising=False)
    guard = _ship_guard()
    rules = json.loads((REPO / 'tools' / 'build' / 'ship_rules.json').read_text(encoding='utf-8'))
    staged = {e['src']: e for e in rules['stage']['common']}
    for src in ('utility/rigswap/app', 'utility/model_import_tools.json'):
        entry = staged[src]
        assert not entry.get('optional'), f'{src} must fail the stage when missing'
        assert guard.gate_ships(entry['ships_with_gate']) is True, src
    verify = [w['path'] for w in rules['verify']['common']
              if isinstance(w, dict) and guard.gate_ships(w['ships_with_gate'])]
    assert 'utility/rigswap/app/rigswap/plugins/melee/costume.pyc' in verify
    assert 'utility/model_import_tools.json' in verify
    package = json.loads((APP / 'package.json').read_text(encoding='utf-8'))
    copied = {r['from'] for r in package['build']['extraResources'] if isinstance(r, dict)}
    assert {'utility/rigswap/app', 'utility/model_import_tools.json'} <= copied
    for platform in ('win', 'linux', 'mac'):
        each = {r['from'] for r in package['build'].get(platform, {}).get('extraResources', [])
                if isinstance(r, dict)}
        assert not each & {'utility/blender', 'utility/rigswap', 'utility/rigswap/python'}, platform
