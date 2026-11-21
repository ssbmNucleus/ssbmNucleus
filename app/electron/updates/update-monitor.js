// One check owner for startup, Settings and wake/focus refreshes.
function createUpdateMonitor({ check, notify = () => {}, now = Date.now,
  setTimer = setTimeout, clearTimer = clearTimeout, startupMs = 15_000,
  intervalMs = 6 * 60 * 60 * 1000, retryMs = 5 * 60 * 1000 }) {
  let status = { update: null, checkedAt: null, error: null };
  let pending = null;
  let timer = null;
  let dueAt = null;
  let started = false;
  let stopped = false;

  function schedule(ms) {
    if (timer !== null) clearTimer(timer);
    dueAt = now() + ms;
    if (!started || stopped) return;
    timer = setTimer(() => { timer = null; run(); }, ms);
    timer?.unref?.();
  }

  function run() {
    if (pending) return pending;
    if (stopped) return Promise.resolve({ success: false, error: 'Updater stopped' });
    if (timer !== null) clearTimer(timer);
    timer = null;
    pending = Promise.resolve().then(check).then(update => {
      if (!stopped) {
        status = { update: update || null, checkedAt: now(), error: null };
        // Both manual and background checks publish; null clears stale banners.
        try { notify(status.update); } catch { /* a closing window is harmless */ }
      }
      return { success: true, update: update || null };
    }, error => {
      const message = error?.message || String(error);
      if (!stopped) status = { ...status, checkedAt: now(), error: message };
      return { success: false, error: message };
    }).finally(() => {
      pending = null;
      if (!stopped) schedule(status.error ? retryMs : intervalMs);
    });
    return pending;
  }

  return {
    check: run,
    getStatus: () => ({ ...status }),
    start() {
      if (started || stopped) return;
      started = true;
      if (!pending) schedule(dueAt === null ? startupMs : Math.max(0, dueAt - now()));
    },
    checkIfDue() {
      if (started && !stopped && dueAt !== null && now() >= dueAt) return run();
      return pending || Promise.resolve(null);
    },
    stop() {
      stopped = true;
      if (timer !== null) clearTimer(timer);
      timer = null;
    },
  };
}

module.exports = { createUpdateMonitor };
