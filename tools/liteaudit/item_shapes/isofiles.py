"""The vanilla ISO the item shapes are read from: open it once (build.py), then DAT views by file name."""
from functools import lru_cache

import hsdgeom

_disc = None


def open_iso(iso):
    """stage_bake.FighterDisc over `iso` (read-only), used by disc() and dat() from now on."""
    global _disc
    from stage_bake import FighterDisc
    _disc = FighterDisc(iso)
    dat.cache_clear()
    return _disc


def disc():
    if _disc is None:
        raise RuntimeError('isofiles.open_iso() first')
    return _disc


@lru_cache(None)
def dat(name):
    return hsdgeom.Dat(disc().file(name), name)
