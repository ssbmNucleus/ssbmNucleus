"""The old model imports are gone: nothing may still import one of their modules.

The one-call `import_model` path and its `model_*` assistant tools (v1) were deleted
when the studio became the only model import (switch-scope Tier 1). The studio and
the v4 workflow went in turn when rigswap became the import (2026-11-03; the tag
`archive/v4-importer` marks the last commit with them): `randall/model_import` and
`shared/modellab` now hold only the rigswap job, the vault save, the native rig
readers and the fighter table, so an import of any other module under them is a
leftover. A leftover import -- a lazy one inside a function included -- breaks
that code path at run time and breaks the frozen build (PyInstaller's warning
check), so every import in the backend, the eval harness and the scripts is
read here, not just the module-level ones.

`app/backend/artifacts/` is skipped: it holds recorded run folders (the
scripts an agent wrote during a past run), which nothing imports or runs.
"""
from tests.paths import BACKEND
import ast
import warnings
from pathlib import Path

NUCLEUS = BACKEND.parent
REPO = NUCLEUS.parent
EVAL_DIRS = (REPO / 'eval' / 'randall', REPO / 'eval' / 'corpus')
SCANNED = (BACKEND, *EVAL_DIRS, REPO / 'tools')
SKIPPED_DIRS = {BACKEND / 'artifacts'}
SKIPPED_NAMES = {'__pycache__', 'node_modules', 'venv', '.venv', 'python-deps'}

DELETED = (
    'randall.assistant.model_import', 'randall.assistant.model_recipe', 'randall.assistant.fit_story', 'randall.assistant.piece_labeller',
    'nucleus_api.modellab',
    # randall.model_import.tools (v1's model_* tools) is deleted; since 0.9.0 the name is the downloaded tools'
    # package (assemble, service). NARROWED still refuses an import of anything that package does not define.
    'shared.modellab.accessory_classifier', 'shared.modellab.accessory_evidence', 'shared.modellab.probes',
    'shared.modellab.source_manifest', 'shared.modellab.deform_audit',
    # eval harnesses that only drove the old path
    'model_edit_requests', 'model_repair_trial',
    # the v4 importer's helpers outside its two packages
    'randall.assistant.vision_ask', 'vault.echo.ft_parts_table',
)
# The packages the v4 importer lived in: what is left of them is all that may be imported.
NARROWED = ('randall.model_import', 'shared.modellab')


def _module_name(path):
    try:
        parts = list(path.relative_to(BACKEND).with_suffix('').parts)
    except ValueError:
        return ''
    return '.'.join(parts[:-1] if parts[-1] == '__init__' else parts)


def _absolute(current, is_package, level, module):
    if not level:
        return module or ''
    base = current.split('.') if current else []
    if not is_package:
        base = base[:-1]
    base = base[:len(base) - (level - 1)] if level > 1 else base
    return '.'.join(base + ([module] if module else []))


def _names(node, current, is_package):
    """Every dotted module name one AST node may import."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        base = _absolute(current, is_package, node.level, node.module)
        return [base] + [f'{base}.{alias.name}' for alias in node.names]
    if isinstance(node, ast.Call):
        # importlib.import_module('x.y'), __import__('x.y'), monkeypatch.setattr('x.y.z', ...)
        return [arg.value for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str)]
    return []


def _python_files():
    for root in SCANNED:
        if not root.is_dir():
            continue
        for path in root.rglob('*.py'):
            if SKIPPED_NAMES & set(path.parts) or any(skip in path.parents for skip in SKIPPED_DIRS):
                continue
            yield path


def test_nothing_imports_a_deleted_v1_module():
    found = []
    for path in _python_files():
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'))
        except SyntaxError:
            continue
        current, is_package = _module_name(path), path.name == '__init__.py'
        for node in ast.walk(tree):
            for name in _names(node, current, is_package):
                for deleted in DELETED:
                    if name == deleted or name.startswith(deleted + '.'):
                        found.append(f'{path.relative_to(REPO)}:{node.lineno} imports {deleted}')
    assert not found, '\n'.join(found)


def _source(module):
    """The file of a module or package under backend/, or None."""
    path = BACKEND.joinpath(*module.split('.'))
    for candidate in (path.with_suffix('.py'), path / '__init__.py'):
        if candidate.is_file():
            return candidate
    return None


def _defines(source, name):
    tree = ast.parse(source.read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
            return True
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == name for t in targets):
                return True
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if any((alias.asname or alias.name).split('.')[0] == name for alias in node.names):
                return True
    return False


def _exists(name):
    """`name` is a module or package under backend/, or a name its parent module defines."""
    if _source(name):
        return True
    parent, _, last = name.rpartition('.')
    source = _source(parent) if parent else None
    return bool(source) and _defines(source, last)


def test_nothing_imports_a_module_the_v4_importer_took_with_it():
    found = []
    for path in _python_files():
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'))
        except SyntaxError:
            continue
        current, is_package = _module_name(path), path.name == '__init__.py'
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                continue        # strings: a module named in a log line or a docstring example is not an import
            for name in _names(node, current, is_package):
                if any(name == package or name.startswith(package + '.') for package in NARROWED)                         and not _exists(name):
                    found.append(f'{path.relative_to(REPO)}:{node.lineno} imports {name}')
    assert not found, '\n'.join(found)


def test_the_deleted_modules_are_gone():
    for deleted in DELETED:
        if '.' not in deleted:
            assert not any((folder / f'{deleted}.py').exists() for folder in (REPO / 'eval', *EVAL_DIRS)), deleted
            continue
        path = BACKEND.joinpath(*deleted.split('.'))
        assert not path.with_suffix('.py').exists() and not path.is_dir(), deleted


def test_the_scan_sees_lazy_and_relative_imports():
    """The check itself: a function-level import and a relative one are both read."""
    tree = ast.parse('def f():\n    from . import model_import\n    import shared.modellab.probes as p\n')
    names = [name for node in ast.walk(tree) for name in _names(node, 'randall.assistant.tools', False)]
    assert 'randall.assistant.model_import' in names and 'shared.modellab.probes' in names
