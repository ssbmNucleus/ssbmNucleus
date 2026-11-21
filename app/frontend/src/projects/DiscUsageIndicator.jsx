/**
 * DiscUsageIndicator - build-capacity meter for the install-page header.
 *
 * There are two independent limits:
 *  1. CSS memory: CSP texture RAM, capped separately for the console/offline VS
 *     CSS and the Dolphin/Slippi online CSS.
 *  2. Disc/image size: real hardware disc capacity and Dolphin's ~4 GiB ISO
 *     boot ceiling.
 *
 * "Free space" stubs the vanilla videos (Mv*.mth) rather than deleting them --
 * deleting is not safe, it crashes the build after every 1P clear, on the
 * title attract loop, and in Data -> Movies (Tracker #92). Stubbing frees disc
 * space only; it does not raise either CSS memory ceiling. See
 * docs/MEX_BUILD_LIMITS.md and backend/core/movie_stubs.py.
 */
import { useEffect, useState } from 'react'
import { api } from '../shared/transport/api'

// CSS memory ceilings. Console/local play should be keyed to the offline VS CSS;
// Dolphin/Slippi should be keyed to the online CSS, which loads more memory. Keep
// these as separate constants so new online/offline ladder results can land without
// mixing the two use cases.
const CONSOLE_COSTUME_HANG = 1150   // offline VS CSS, auto-compressed CSPs
const DOLPHIN_COSTUME_HANG = 1500   // Slippi online CSS, tested healthy through here

// Disc size has TWO thresholds. The console disc (from the backend = 1,459,978,240 B)
// is the real-hardware / SD limit. A build over it still RUNS in Dolphin (confirmed
// to +968 MiB over); Dolphin only stops booting once the ISO passes ~4 GiB = 2^32 —
// the GameCube image format's 32-bit byte offsets. See docs/MEX_BUILD_LIMITS.md §3.
const DOLPHIN_LIMIT = 4 * 1024 * 1024 * 1024   // ~4 GiB ISO-format ceiling

// Drawn left-to-right; costumes last so added skins sit by the free-space edge.
// Video is the big strippable chunk.
const CATEGORIES = [
  { key: 'video', label: 'Video', color: '#566270', strip: true, note: 'cutscenes / demos (stubbed, not deleted -- still play)' },
  { key: 'audio', label: 'Audio', color: '#7a5bbf' },
  // Trophies (Ty*) are NOT strippable: MexManager's TrophyLoader reads them when the
  // project opens, so deleting them breaks the workspace. Shown, not removable.
  { key: 'trophies', label: 'Trophies', color: '#8a7b4f' },
  { key: 'stages', label: 'Stages', color: '#3f8f5f' },
  { key: 'other', label: 'Other', color: '#455160' },
  { key: 'costumes', label: 'Costumes', color: '#c8503f' },
]
const STRIPPABLE = CATEGORIES.filter((c) => c.strip)

const fmtGB = (b) => `${(b / 1e9).toFixed(2)} GB`
const fmtMB = (b) => `${Math.round(b / 1e6)} MB`
// Remaining-space readout: GB once it's ≥ ~1 GB, else MB — keeps both bars legible.
const fmtSpace = (b) => (b >= 1e9 ? fmtGB(b) : fmtMB(b))

export default function DiscUsageIndicator({ projectLoaded, totalCostumes = 0 }) {
  const [data, setData] = useState(null)
  const [hovered, setHovered] = useState(null)
  const [stripOpen, setStripOpen] = useState(false)
  const [selected, setSelected] = useState({})
  const [busy, setBusy] = useState(false)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    if (!projectLoaded) return undefined
    let cancelled = false
    api.get('/project/disc-usage')
      .then((d) => { if (cancelled) return; setData(d || null) })
      .catch(() => { if (!cancelled) setData(null) })
    return () => { cancelled = true }
  }, [projectLoaded, totalCostumes, nonce])

  if (!projectLoaded) return null

  // ── Secondary limit: disc size (real-hardware ceiling; Dolphin tolerates over) ──
  const disc = data
    ? (() => {
      const { capacity, used, free, breakdown } = data
      const pct = (b) => `${Math.max(0, Math.min(100, (b / capacity) * 100))}%`
      const overConsole = used > capacity
      const overConsoleBy = used - capacity            // bytes past the console disc
      const overDolphin = used > DOLPHIN_LIMIT
      const dolphinFree = DOLPHIN_LIMIT - used         // headroom before the ISO won't boot
      // How many more costumes fit in each free space, capped by the matching
      // CSS-memory ceiling (so we never promise more than the game can load).
      const avg = data.avgSkinBytes || 497 * 1024      // ~bytes per added costume on disc
      const consoleMemRoom = Math.max(0, CONSOLE_COSTUME_HANG - totalCostumes)
      const dolphinMemRoom = Math.max(0, DOLPHIN_COSTUME_HANG - totalCostumes)
      const consoleFits = Math.min(Math.floor(free / avg), consoleMemRoom)
      const dolphinFits = Math.min(Math.floor(dolphinFree / avg), dolphinMemRoom)
      // Reclaimable size per strippable category: video is STUBBED, not deleted,
      // so its real gain is the file minus its stub, not the whole category (an
      // added fighter's own movie is never touched and stays counted as used).
      const reclaimable = data.reclaimable || {}
      const gainOf = (key) => (key === 'video' ? (reclaimable.video ?? breakdown[key]) : breakdown[key])
      const anyStrippable = STRIPPABLE.some((c) => gainOf(c.key) > 0)
      const selectedBytes = STRIPPABLE.reduce(
        (s, c) => s + (selected[c.key] ? gainOf(c.key) || 0 : 0), 0)
      const hov = hovered ? CATEGORIES.find((c) => c.key === hovered) : null
      return { capacity, used, free, breakdown, pct, overConsole, overConsoleBy,
        overDolphin, dolphinFree, consoleFits, dolphinFits, anyStrippable, selectedBytes,
        gainOf, hov }
    })()
    : null

  const doStrip = async () => {
    const targets = STRIPPABLE.filter((c) => selected[c.key]).map((c) => c.key)
    if (!targets.length) return
    setBusy(true)
    try {
      await api.post('/project/strip', { targets })
      setStripOpen(false); setSelected({}); setNonce((n) => n + 1)
    } catch (err) {
      console.error('Strip failed:', err)
    } finally { setBusy(false) }
  }

  return (
    <div className="disc-usage">
      {/* Two disc bars (console + Dolphin): each shows free space and ~how many more costumes fit */}
      {disc && (
        <div className="disc-usage__section">
          {/* CONSOLE bar: build composition, full width = the 1.46 GB console disc */}
          <div
            className="disc-usage__gauge"
            title="Real GameCube / SD-console disc (1.46 GB). A build past the end of this bar won't boot on hardware; costume room uses the offline VS CSS memory ceiling."
          >
            <span className="disc-usage__gauge-label">Console</span>
            <div className="disc-usage__barwrap">
              {disc.hov && (
                <div className="disc-usage__tip">
                  <span className="disc-usage__dot" style={{ background: disc.hov.color }} />
                  {disc.hov.label}: {fmtMB(disc.breakdown[disc.hov.key])} (
                  {Math.round((disc.breakdown[disc.hov.key] / disc.capacity) * 100)}%)
                  {disc.hov.strip ? ' · shrinkable (Free space)' : ''}
                </div>
              )}
              <div className={`disc-usage__bar${disc.overConsole ? ' is-over' : ''}`}>
                {CATEGORIES.map((c) => (disc.breakdown[c.key] > 0 ? (
                  <span
                    key={c.key}
                    className="disc-usage__seg"
                    style={{ width: disc.pct(disc.breakdown[c.key]), background: c.color }}
                    title={`${c.label}: ${fmtMB(disc.breakdown[c.key])}`}
                    onMouseEnter={() => setHovered(c.key)}
                    onMouseLeave={() => setHovered((h) => (h === c.key ? null : h))}
                  />
                ) : null))}
              </div>
            </div>
            <span className={`disc-usage__gauge-val ${disc.overConsole ? 'is-over' : 'is-ok'}`}>
              {disc.overConsole
                ? `${fmtMB(disc.overConsoleBy)} over`
                : `${fmtSpace(disc.free)} free · ~${disc.consoleFits} costumes`}
            </span>
          </div>

          {/* DOLPHIN bar: build size, full width = the ~4 GiB ISO boot ceiling */}
          <div
            className="disc-usage__gauge"
            title="Dolphin / ISO-format ceiling (~4 GiB = 2^32). Dolphin runs an over-disc build up to here; costume room uses the Slippi online CSS memory ceiling."
          >
            <span className="disc-usage__gauge-label">Dolphin</span>
            <div className="disc-usage__barwrap">
              <div className="disc-usage__bar">
                <span
                  className={`disc-usage__dolfill ${disc.overDolphin ? 'is-fatal' : 'is-ok'}`}
                  style={{ width: `${Math.max(2, Math.min(100, (disc.used / DOLPHIN_LIMIT) * 100))}%` }}
                />
              </div>
            </div>
            <span className={`disc-usage__gauge-val ${disc.overDolphin ? 'is-fatal' : 'is-ok'}`}>
              {disc.overDolphin
                ? 'won’t boot'
                : `${fmtSpace(disc.dolphinFree)} free · ~${disc.dolphinFits} costumes`}
            </span>
          </div>

          {disc.anyStrippable && (
            <button
              type="button"
              className="disc-usage__free-btn"
              onClick={() => setStripOpen((o) => !o)}
              title="Shrink vanilla videos to free disc space (for real-hardware / SD builds) -- they're stubbed, not deleted, so 1P endings, the title screen, and Data -> Movies still play"
            >
              Free space ▾
            </button>
          )}

          {stripOpen && (
            <div className="disc-usage__strip">
              <div className="disc-usage__strip-title">
                Shrink vanilla videos to a few seconds each to free disc space
              </div>
              <div className="disc-usage__strip-subtitle">
                Only the 28 vanilla Mv*.mth files are touched -- never an added
                character's own movie. Every scene that plays one still works.
              </div>
              {STRIPPABLE.map((c) => (disc.gainOf(c.key) > 0 ? (
                <label key={c.key} className="disc-usage__strip-row">
                  <input
                    type="checkbox"
                    checked={!!selected[c.key]}
                    onChange={(e) => setSelected((s) => ({ ...s, [c.key]: e.target.checked }))}
                  />
                  <span className="disc-usage__dot" style={{ background: c.color }} />
                  <span className="disc-usage__strip-label">{c.label}</span>
                  <span className="disc-usage__strip-size">{fmtMB(disc.gainOf(c.key))}</span>
                </label>
              ) : null))}
              <div className="disc-usage__strip-actions">
                <button type="button" className="disc-usage__strip-cancel"
                  onClick={() => { setStripOpen(false); setSelected({}) }}>
                  Cancel
                </button>
                <button type="button" className="disc-usage__strip-go" disabled={busy || disc.selectedBytes === 0}
                  onClick={doStrip}>
                  {busy ? 'Removing…' : disc.selectedBytes ? `Free up ${fmtMB(disc.selectedBytes)}` : 'Select to remove'}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
