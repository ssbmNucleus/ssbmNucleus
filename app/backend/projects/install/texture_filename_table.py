"""
Managed index -> Dolphin-filename table for offline (zero-boot) texture packs.

The 16x16 placeholder for a GLOBAL costume index is byte-identical in every build
(generate_encoded_placeholder is deterministic), so the Dolphin load filename it
produces -- tex1_16x16_<texHash>_<tlutHash>_9.png -- is a PURE FUNCTION of the
index. That means the whole index -> filename relation can be precomputed once and
reused for every future build forever, with no Dolphin and no CSS scrolling.

This module owns that table for the running app:

  * It SEEDS from a shipped, proven table (backend/data/texture_filename_table_seed.json,
    validated bit-exact against harvested ground truth) into storage/ on first use.
  * For any index NOT yet in the table, it COMPUTES the filename from first
    principles -- the exact chain compute_texture_table.py validated:
        index N
          -> generate_encoded_placeholder(N)          (the deterministic 16x16 PNG)
          -> mexcli placeholder-bytes                 (the real CSP CI8 + RGB5A3
                                                       encode the export uses)
          -> texHash  = XXH64(imageData, seed=0)
             tlutHash = XXH64(palette[2*usedMin : 2*(usedMax+1)], seed=0)
          -> tex1_16x16_<texHash>_<tlutHash>_9.png
    Newly computed indices are persisted, so each one is paid for at most once.

The endpoint /api/mex/texture-pack/auto-apply uses this to name a build's entire
texture pack instantly when every index is already cached (the common case), and
to extend the table on the fly when a build introduces new costume indices.
"""

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from core.config import MEXCLI_PATH, PROJECT_ROOT, STORAGE_PATH, BACKEND_DATA_DIR
from projects.install.texture_pack import generate_encoded_placeholder

logger = logging.getLogger(__name__)

# Shipped seed (proven bit-exact) and the per-install persistent cache.
SEED_TABLE_PATH = BACKEND_DATA_DIR / "texture_filename_table_seed.json"
CACHE_TABLE_PATH = STORAGE_PATH / "texture_filename_table.json"

# Dolphin names CI8 textures (format 9) by XXH64 of the image data and of the
# USED palette index range.
_TEX_FMT = "9"


def _xxh64_hex(data: bytes) -> str:
    """XXH64(data, seed=0) as 16-char lowercase hex (the way Dolphin formats it)."""
    import xxhash  # imported lazily so the module loads even if xxhash is absent
    return format(xxhash.xxh64(data, seed=0).intdigest(), "016x")


def _load_json(path: Path) -> Optional[Dict]:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        logger.warning(f"Could not read filename table {path}: {e}")
        return None


def load_table() -> Dict:
    """Load the persistent cache, seeding it from the shipped table on first use.
    Returns a dict shaped { 'entries': { str(index): {filename, ...} }, ... }."""
    cache = _load_json(CACHE_TABLE_PATH)
    if cache and isinstance(cache.get("entries"), dict):
        return cache

    seed = _load_json(SEED_TABLE_PATH)
    entries = (seed or {}).get("entries", {}) if seed else {}
    table = {"entries": dict(entries), "count": len(entries), "source": "seed"}
    try:
        CACHE_TABLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_TABLE_PATH, "w") as f:
            json.dump(table, f, indent=2)
        logger.info(f"Seeded filename table cache with {len(entries)} indices -> {CACHE_TABLE_PATH}")
    except Exception as e:
        logger.warning(f"Could not persist seeded filename table: {e}")
    return table


def _save_table(table: Dict) -> None:
    table["count"] = len(table.get("entries", {}))
    try:
        CACHE_TABLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_TABLE_PATH, "w") as f:
            json.dump(table, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not persist filename table: {e}")


def _encoded_bytes(index: int, tmpdir: str) -> Tuple[bytes, bytes, int, int]:
    """Run the real CSP encoder (mexcli placeholder-bytes) on placeholder N.
    Returns (imageData, paletteData, usedMin, usedMax)."""
    png_path = os.path.join(tmpdir, f"ph{index}.png")
    generate_encoded_placeholder(index).save(png_path, format="PNG")
    out = subprocess.run(
        [str(MEXCLI_PATH), "placeholder-bytes", png_path],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise RuntimeError(
            f"mexcli placeholder-bytes failed for index {index}: {out.stderr[:300]}"
        )
    rec = json.loads(out.stdout.strip().splitlines()[-1])
    return (
        bytes.fromhex(rec["img"]),
        bytes.fromhex(rec["pal"]),
        rec["usedMin"],
        rec["usedMax"],
    )


def compute_record(index: int, tmpdir: str) -> Dict:
    """Compute the Dolphin filename record for one costume index (no Dolphin/ISO)."""
    img, pal, used_min, used_max = _encoded_bytes(index, tmpdir)
    tex_hash = _xxh64_hex(img)
    tlut_hash = _xxh64_hex(pal[2 * used_min: 2 * (used_max + 1)])
    return {
        "filename": f"tex1_16x16_{tex_hash}_{tlut_hash}_{_TEX_FMT}.png",
        "w": 16, "h": 16, "texHash": tex_hash, "tlutHash": tlut_hash, "fmt": _TEX_FMT,
    }


def ensure_table_covers(
    indices: Iterable[int],
    progress_cb: Optional[Callable[[int, int, int], None]] = None,
) -> Tuple[Dict, List[int]]:
    """Return (entries, computed_indices) where `entries` covers every requested
    index whose filename could be determined. Missing indices are computed from
    first principles and persisted. `progress_cb(done, total, index)` is called as
    each missing index is computed (total == number of MISSING indices).

    Raises if mexcli is needed but unavailable -- callers should fall back to the
    manual-scroll harvest in that case.
    """
    table = load_table()
    entries = table["entries"]

    wanted = sorted({int(i) for i in indices})
    missing = [i for i in wanted if str(i) not in entries]
    if not missing:
        return entries, []

    if not Path(MEXCLI_PATH).exists():
        raise RuntimeError(
            f"{len(missing)} costume indices are not in the texture table and MexCLI "
            f"is unavailable to compute them (looked at {MEXCLI_PATH})."
        )

    logger.info(f"Computing {len(missing)} new filename-table indices (no Dolphin): "
                f"{missing[:8]}{'...' if len(missing) > 8 else ''}")
    computed: List[int] = []
    with tempfile.TemporaryDirectory() as tmp:
        for n, index in enumerate(missing):
            entries[str(index)] = compute_record(index, tmp)
            computed.append(index)
            if progress_cb:
                try:
                    progress_cb(n + 1, len(missing), index)
                except Exception:
                    pass
    _save_table(table)
    logger.info(f"Filename table extended by {len(computed)} -> {len(entries)} indices total")
    return entries, computed
