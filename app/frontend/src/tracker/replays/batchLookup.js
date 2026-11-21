// Per-row lookups for the Replays list (Slippi ranks by connect code, final
// stocks by game id). Each list render says which keys it still lacks; this
// sends them ONE request at a time, at most `batchSize` keys each, and never
// asks again for a key that was answered (a failed one waits out retryMs).
//
// Firing a fresh POST for every missing key on every render (which the page
// used to do) stacked overlapping requests whenever a month or page opened
// while an earlier lookup was still out. /ranks serializes its slippi.gg
// fetches behind a lock, so those POSTs sat open for tens of seconds each and
// filled the browser's six connections to the backend: the month's own list
// request then queued behind them, which showed as a month that loads nothing
// and a pager stuck disabled.
export function createBatchLookup({ request, onResult, batchSize, retryMs = 30000, now = Date.now }) {
  const asked = new Set() // in flight or answered; never re-sent
  // Failed keys sit out retryMs, then go again on the page's next want()
  // (paging, reopening a month, an answer re-rendering the rows). Re-sending
  // them on every render would turn a down backend into a request loop;
  // never re-sending them would leave a transient failure blank for good.
  const failedAt = new Map()
  let wanted = []
  let busy = false
  let stopped = false

  const ready = (k) => !asked.has(k) && !(now() - (failedAt.get(k) ?? -Infinity) < retryMs)

  async function pump() {
    if (busy || stopped) return
    const batch = wanted.filter(ready).slice(0, batchSize)
    if (!batch.length) return
    busy = true
    for (const k of batch) asked.add(k)
    try {
      const data = await request(batch)
      if (!stopped) onResult(batch, data)
    } catch {
      const at = now()
      for (const k of batch) {
        asked.delete(k)
        failedAt.set(k, at)
      }
    } finally {
      busy = false
      pump()
    }
  }

  return {
    // The keys the page currently lacks, in the order it wants them.
    want(keys) {
      wanted = [...new Set(keys)]
      pump()
    },
    // The page is gone: send nothing more, apply nothing that comes back.
    stop() {
      stopped = true
    },
  }
}
