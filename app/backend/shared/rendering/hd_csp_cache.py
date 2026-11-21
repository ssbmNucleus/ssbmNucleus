"""
Content-addressed cache of 4x HD CSP renders, keyed by costume DAT md5.

Why this exists
---------------
The texture-pack / bundle export ships HD (544x752) portraits to Dolphin via a
sidecar texture pack. For costumes that came in through the vault that's easy --
the user's own `<skin>_csp_hd.png` is used. But costumes that came from a *patch*
(e.g. an "Animelee" project created from a vault patch) are extracted straight
from the patch's menu scene: they have only a 136x188 SD CSP and no vault
identity, so there is nothing to upgrade to. Measured on real projects, a
patch reskin is ~100% custom art by DAT bytes, so there is no shortcut -- the
only way to get an HD portrait is to render the costume at 4x.

Rendering is expensive (a headless HSDRawViewer spawn, ~1-3s each), so we cache
every render by the *content hash of the costume DAT*:
  - stable within a project  -> re-exporting the same bundle is instant
  - shared across projects    -> a costume rendered once is never rendered again
  - self-invalidating         -> edit the costume's bytes and the key changes

The vanilla bank pre-seed (see first_run_setup) renders the shipped vanilla
costumes into this same cache on first run, so app-native vanilla slots are warm
without an export-time render. Patch costumes (custom bytes) still render once on
first export, then hit the cache forever after.
"""

import hashlib
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Optional

import file_retry
from core.config import STORAGE_PATH
from shared.rendering.csp_concurrency import staggered_launch

logger = logging.getLogger(__name__)

# HD CSPs are always 4x (544x752) -- see the csp-manager HD rework. Scale is part
# of the cache key so a future change can coexist with already-cached renders.
HD_SCALE = 4

# Persistent, outside any project or temp dir, so it survives the texture-pack
# export's temp-copy cleanup and is shared across every project.
CACHE_DIR = STORAGE_PATH / "_csp_hd_cache"


def _cache_key(dat_hash: str, scale: int = HD_SCALE) -> str:
    return f"{dat_hash}_{scale}x.png"


def cached_path(dat_hash: str, scale: int = HD_SCALE) -> Path:
    """Path a render WOULD live at for this DAT hash (may not exist yet)."""
    return CACHE_DIR / _cache_key(dat_hash, scale)


def hash_dat(dat_path) -> Optional[str]:
    """md5 of a DAT file's bytes (the cache key). None if it can't be read."""
    try:
        return hashlib.md5(Path(dat_path).read_bytes()).hexdigest()
    except Exception as e:  # noqa: BLE001 - hashing is best-effort
        logger.warning(f"HD cache: cannot hash {dat_path}: {e}")
        return None


def get_cached(dat_hash: str, scale: int = HD_SCALE) -> Optional[Path]:
    """Return the cached HD CSP for this hash, or None on a miss."""
    if not dat_hash:
        return None
    p = cached_path(dat_hash, scale)
    return p if p.exists() else None


def effective_key_hash(dat_path, *, paired_dat_path=None, dat_hash=None,
                       color_index=None, gw_colors=None) -> Optional[str]:
    """The md5 the cache is actually keyed by.

    For Ice Climbers the partner (Nana) DAT is composited into the render, so the
    output depends on BOTH files -- fold the partner hash in, otherwise a
    Nana-only recolor (Popo bytes unchanged) would serve a stale composite.

    `color_index` is folded in for characters whose color is NOT in the DAT (Mr.
    Game & Watch: all 4 CSS slots share one PlGwNr.dat and differ only by index),
    so each color slot gets its own cache entry instead of colliding on the shared
    DAT hash. None (the default, everyone else) leaves the key unchanged.

    `gw_colors` ({'fill': (r,g,b), 'outline': (r,g,b,a)}, a G&W color mod's
    explicit colors from the m-ex GawColors table) takes precedence over
    color_index -- every distinct color pair gets its own cache entry.
    """
    h = dat_hash or hash_dat(dat_path)
    if not h:
        return None
    if paired_dat_path and Path(paired_dat_path).exists():
        ph = hash_dat(paired_dat_path)
        if ph:
            h = hashlib.md5(f"{h}+{ph}".encode()).hexdigest()
    if gw_colors is not None:
        fill = tuple(gw_colors.get('fill') or ())
        outline = tuple(gw_colors.get('outline') or ())
        h = hashlib.md5(f"{h}#g{fill}|{outline}".encode()).hexdigest()
    elif color_index is not None:
        h = hashlib.md5(f"{h}#c{color_index}".encode()).hexdigest()
    return h


def get_or_render_hd(
    dat_path,
    *,
    scale: int = HD_SCALE,
    paired_dat_path=None,
    dat_hash: Optional[str] = None,
    color_index: Optional[int] = None,
    gw_colors: Optional[dict] = None,
    log: Optional[logging.Logger] = None,
) -> Optional[Path]:
    """Return a cached 4x HD CSP for this costume DAT, rendering + caching on miss.

    `dat_path` is copied into a throwaway temp dir before rendering, because
    `generate_csp` writes its output (`<stem>_csp_hd.png`) NEXT TO the input --
    we never want to litter a source dir (the vanilla bank, a live project, etc.).
    Returns the cached path, or None if the render failed (caller falls back to SD).
    """
    log = log or logger
    dat_path = Path(dat_path)

    h = effective_key_hash(dat_path, paired_dat_path=paired_dat_path,
                           dat_hash=dat_hash, color_index=color_index,
                           gw_colors=gw_colors)
    if not h:
        return None

    dest = cached_path(h, scale)
    if dest.exists():
        return dest

    # Lazy import: generate_csp pulls in the heavy HSDRaw stack. costume_assets
    # already imports it at module load, so this is free in practice, but keeping
    # it lazy avoids any import-time coupling for callers that never render.
    from generate_csp import generate_csp

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="hdcsp_"))
    try:
        local = tmp / dat_path.name
        shutil.copy2(dat_path, local)

        paired_local = None
        if paired_dat_path and Path(paired_dat_path).exists():
            paired_local = tmp / Path(paired_dat_path).name
            shutil.copy2(paired_dat_path, paired_local)

        # Render under a staggered launch instead of a full lock: concurrent
        # callers (e.g. the parallel texture-pack export) get spaced HSDRawViewer
        # launches to avoid the init race, then render in parallel. Cache HITS
        # return above and never reach here.
        with staggered_launch():
            out = generate_csp(
                str(local),
                scale=scale,
                paired_dat_filepath=str(paired_local) if paired_local else None,
                color_index=color_index,
                gw_colors=gw_colors,
            )
        if not out or not Path(out).exists():
            log.warning(f"HD cache: render produced no output for {dat_path.name} ({h[:8]})")
            return None

        # Atomic publish: write a unique temp name in the cache dir, then replace.
        tmp_dest = dest.with_name(f"{dest.name}.{os.getpid()}.tmp")
        shutil.copy2(out, tmp_dest)
        file_retry.replace(tmp_dest, dest)
        log.info(f"HD cache: rendered {dat_path.name} at {scale}x -> {dest.name}")
        return dest
    except Exception as e:  # noqa: BLE001 - a failed render must never break export
        log.warning(f"HD cache: render error for {dat_path.name}: {e}")
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def preseed_vanilla_hd_csps(
    progress: Optional[Callable[[int, int, int, int, int], None]] = None,
    log: Optional[logging.Logger] = None,
) -> dict:
    """Render every shipped vanilla costume into the HD cache (keyed by DAT md5).

    Idempotent: already-cached hashes are skipped, so this is safe to re-run and
    cheap once warm. Intended to run in a background thread after first-run setup
    (the vanilla DATs are extracted from the user's ISO during setup). Never
    raises -- a missed pre-seed just means the costume renders on demand at export.

    The vanilla bank is laid out as <Char>/<Code>/<Code>.dat, so a per-costume DAT
    is exactly the file whose parent folder is named after it (this excludes the
    animation `Pl<Xx>AJ.dat` and common `Pl<Xx>.dat` files that sit one level up).
    """
    log = log or logger
    from core.config import VANILLA_ASSETS_DIR

    rendered = skipped = failed = 0
    try:
        costume_dats = sorted(
            d for d in Path(VANILLA_ASSETS_DIR).rglob('*.dat')
            if d.stem == d.parent.name and re.match(r'^Pl', d.stem)
        )
    except Exception as e:  # noqa: BLE001
        log.warning(f"HD cache preseed: cannot scan {VANILLA_ASSETS_DIR}: {e}")
        return {'rendered': 0, 'skipped': 0, 'failed': 0, 'total': 0}

    total = len(costume_dats)
    log.info(f"HD cache preseed: {total} vanilla costumes to warm")
    # Pool persistent --csp-server workers across the whole preseed batch: each
    # costume renders through a warm worker, and the per-render launch stagger
    # no-ops while the pool is active. One-shot fallback per costume; kill switch
    # MEX_CSP_SERVER=0.
    from shared.rendering.csp_pool import active_pool
    # The loop below renders strictly sequentially, so ONE warm worker is
    # optimal: extra idle --csp-server GL contexts add no throughput and their
    # GPU pressure can flip HSDRawViewer into its blank-render failure mode.
    with active_pool(workers=1):
        for i, dat in enumerate(costume_dats):
            h = hash_dat(dat)
            if h and get_cached(h):
                skipped += 1
            elif get_or_render_hd(dat, dat_hash=h, log=log):
                rendered += 1
            else:
                failed += 1
            if progress:
                try:
                    progress(i + 1, total, rendered, skipped, failed)
                except Exception:  # noqa: BLE001 - progress is best-effort
                    pass

    log.info(
        f"HD cache preseed done: {rendered} rendered, {skipped} already cached, "
        f"{failed} failed (of {total})")
    return {'rendered': rendered, 'skipped': skipped, 'failed': failed, 'total': total}
