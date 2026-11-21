"""Is a built costume Slippi-safe? The app's own check, read only.

Slippi netplay runs the game from each player's local files. The check
compares every joint's rest transform with vanilla's, because hurtboxes,
hitboxes and collision follow the joints: a moved joint changes the game, not
just the look. An import keeps the vanilla skeleton, so a failure here is a bug
in the export, never something to patch over.
"""
import sys


def check(dat_path):
    from core.config import PROCESSOR_DIR, SERVICES_DIR
    for path in (PROCESSOR_DIR, SERVICES_DIR):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    from dat_processor import validate_for_slippi
    result = validate_for_slippi(str(dat_path), auto_fix=False)
    return dict(slippi_safe=bool(result.get('slippi_safe')), needs_fix=bool(result.get('needs_fix')),
                detail=str(result.get('output') or result.get('error') or '')[-600:])
