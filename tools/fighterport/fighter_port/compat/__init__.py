"""Helper modules the own-skeleton route was written against, kept here since the app let go of them.

The app held these until its clean-up of 2026-11-03 (commit 2dff8cce7, "delete the v4 engine"): an SMD reader and
writer, the readers of a fighter's files (joints, animation tracks, model parts), the table that says which joint is
which, the fighter's drawn scale, and the audit of who moves a fighter. The route's own modules still import them by
their old names (`shared.modellab.smd`, `randall.model_import.native_rig.bone_lookup`, ...). `install()` gives those
names back, pointing at the copies here, wherever the app no longer has them. It changes nothing the app still has.
"""
import importlib
import sys
import types

OLD_NAMES = {                       # (in the order they lean on each other)
    'shared.modellab.smd': 'smd',
    'randall.model_import.native_rig.rig_inventory': 'rig_inventory',
    'randall.model_import.native_rig.fobj_reader': 'fobj_reader',
    'shared.ingame.rig_preflight': 'rig_preflight',
    'randall.model_import.native_rig.animation_archive': 'animation_archive',
    'randall.model_import.native_rig.bone_lookup': 'bone_lookup',
    'randall.model_import.native_rig.fighter_scale': 'fighter_scale',
    'randall.model_import.native_rig.model_parts': 'model_parts',
    'randall.model_import.native_rig.movement_ownership': 'movement_ownership',
}


def _package(name):
    """The package `name`, as the app has it or as an empty stand-in (so that `from <name> import x` can find x)."""
    if name in sys.modules:
        return sys.modules[name]
    try:
        return importlib.import_module(name)
    except Exception:
        module = types.ModuleType(name)
        module.__path__ = []
        sys.modules[name] = module
        parent, _, leaf = name.rpartition('.')
        if parent:
            setattr(_package(parent), leaf, module)
        return module


def install():
    """Make every old name importable. -> the names that now point here."""
    given = []
    for old, here in OLD_NAMES.items():
        if old in sys.modules:
            continue
        parent, _, leaf = old.rpartition('.')
        package = _package(parent)
        try:
            importlib.import_module(old)                # the app still has it: leave it be
            continue
        except Exception:
            pass
        module = importlib.import_module(f'{__name__}.{here}')
        sys.modules[old] = module
        setattr(package, leaf, module)
        given.append(old)
    return given
