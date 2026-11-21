"""Shared CSP-render concurrency policy.

How many parallel HSDRawViewer renders a given machine should run, and a
staggered-launch guard so those renders don't race HSDRawViewer's ~1.5s init
window (the blank / T-pose bug seen when several instances spin up at once).

This mirrors the policy the ISO scanner uses (see iso_scanner.py) so the
texture-pack export and the HD-CSP cache can share it without importing the
heavy scanner module. Tunable via the same env vars the scanner honors.
"""
import os
import time
import threading
from contextlib import contextmanager


def csp_workers(*, default_limit=16) -> int:
    """Number of parallel CSP renders allowed on this machine.

    Bounded by logical CPU count and the caller's default limit. ISO scans use
    four: starting more GL contexts costs more than the small portraits save.
    Other batch callers retain the default limit of sixteen. Override with
    MEX_CSP_PARALLELISM (clamped [1, 32]) for tuning either workload.
    """
    env = os.environ.get('MEX_CSP_PARALLELISM')
    if env and env.isdigit():
        return max(1, min(int(env), 32))
    return max(1, min(os.cpu_count() or 2, default_limit))


# Spacing between HSDRawViewer launches. 1.5s matches Program.cs's combined
# init Sleep budget; raise if you still see flaky renders, set 0 to disable.
CSP_LAUNCH_STAGGER_S = float(os.environ.get('MEX_CSP_LAUNCH_STAGGER', '1.5'))
_launch_lock = threading.Lock()


def _csp_pool_active() -> bool:
    """True when a persistent CSP render pool is installed. Then per-render
    process-launch staggering is unnecessary (and would only slow pooled renders):
    worker startup applies its own stagger, while warm workers reuse their
    process. One-shot fallbacks also apply an explicit launch stagger."""
    try:
        import generate_csp
        return generate_csp.get_active_pool() is not None
    except Exception:
        return False


@contextmanager
def staggered_launch(*, force=False):
    """Serialize only the LAUNCH of each render so each HSDRawViewer gets a
    clean init window before the next starts; then release so renders overlap.

    Hold the lock for the stagger, release, then yield to run the actual render
    in parallel with others. A single, uncontended caller just pays the stagger
    once. Used by the HD-CSP cache so the texture-pack export can render in
    parallel safely (the lock is shared across all callers in this process).

    No-op when a render pool is active -- warm pooled renders don't launch a
    process. Actual worker starts and one-shot fallbacks pass force=True so
    their GL initialization remains spaced while the pool is installed.
    """
    if CSP_LAUNCH_STAGGER_S > 0 and (force or not _csp_pool_active()):
        with _launch_lock:
            time.sleep(CSP_LAUNCH_STAGGER_S)
    yield
