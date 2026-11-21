"""
The HSDRawViewer command line for menu files, retried when another process holds
the file open.
"""

import subprocess
import time
import logging
from core.config import HSDRAW_EXE, get_subprocess_args

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# HSDRawViewer CLI wrapper
# ─────────────────────────────────────────────────────────────────────────────

# .NET's IOException text when another process (a virus scanner, the search
# indexer, or a second HSDRawViewer reading the same DAT) holds a file open.
# Every operation only reads its inputs and writes whole output files, so
# running it again overwrites anything a failed attempt left behind.
_FILE_IN_USE = 'being used by another process'
_IN_USE_RETRY_DELAYS = (0.25, 0.75)


def _run_hsd_cli(args, timeout=120):
    if not HSDRAW_EXE.exists():
        logger.warning(f'HSDRawViewer not found at {HSDRAW_EXE}; skipping DAT processing')
        return None
    for delay in (*_IN_USE_RETRY_DELAYS, None):
        try:
            result = subprocess.run(
                [str(HSDRAW_EXE), *args],
                capture_output=True, text=True, timeout=timeout,
                **get_subprocess_args()
            )
        except subprocess.TimeoutExpired:
            logger.error(f'HSDRawViewer {args[0]} timed out')
            return None
        except Exception as e:
            logger.error(f'HSDRawViewer failed to start: {e}')
            return None
        busy = result.returncode != 0 and _FILE_IN_USE in f'{result.stdout}{result.stderr}'
        if not busy or delay is None:
            break
        logger.warning(f'HSDRawViewer {args[0]}: file in use by another process; retrying')
        time.sleep(delay)

    if result.returncode != 0:
        logger.error(f'HSDRawViewer {args[0]} exit {result.returncode}: {result.stdout}\n{result.stderr}')
        return None
    return result
