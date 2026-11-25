import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BACKEND_URL } from '../../shared/config/config'
import { api } from '../../shared/transport/api'
import { refreshJob, useJobEnd, useLatestJob } from '../../shared/jobs/useJobs'
import { passView } from '../../shared/jobs/passView'
import { replayScanNeedsRefresh } from './scanRefresh'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { charName, stageName, formatDuration } from '../../shared/data/meleeNames'

// "2026-07" -> "July 2026"
const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December']
function monthLabel(ym) {
  const [y, m] = ym.split('-')
  return `${MONTH_NAMES[Number(m) - 1] || m} ${y}`
}
import IconSelect from '../../shared/ui/IconSelect'
import WatchModsModal from './WatchModsModal'
import { useMuReplay } from './useMuReplay'
import { PLAY_ENABLED } from '../../shared/config/features'
import PlaylistModsModal from './PlaylistModsModal'
import WatchLiteModal from './WatchLiteModal'
import ReplayRow from './ReplayRow'
import MonthPager from './MonthPager'
import { createBatchLookup } from './batchLookup'
import './ReplaysPage.css'

const API = `${BACKEND_URL}/api/nucleome`
const PAGE_SIZE = 50
// POST /ranks answers at most this many codes per request
const RANK_BATCH = 50
// Mirrors the backend's PLAYLIST_CLIP_CAP runaway backstop — a longer
// selection still opens, but only this many games are queued.
const PLAYLIST_CAP = 2000
// "Play [N] games" default, like the Combos tab's "Play [N] combos".
const PLAYLIST_DEFAULT = 25

// A selected game as a whole-game playlist clip. `full` makes the backend
// read the frames from its own index (-123 .. last_frame, unpadded); the
// frames here only serve Watch Lite and the backend's no-last_frame fallback.
function fullGameClip(g) {
  const end = g.last_frame ?? (g.duration_s ? Math.round(g.duration_s * 60) - 123 : null)
  return { game_id: g.id, full: true, start_frame: -123, end_frame: end }
}

function formatTotal(seconds) {
  const h = Math.floor(seconds / 3600)
  return h ? `${h}h ${Math.round((seconds % 3600) / 60)}m` : formatDuration(seconds)
}

// nucleOME Replays: browse/filter the indexed .slp corpus. Scanning is
// user-triggered (a full first scan of a big corpus takes minutes), so the
// empty state is a big "Scan replays" button, with live progress while the
// backend walks the directory.

// The Lite popup's title: you first in a 1v1 ("Fox vs Marth"), the teams in
// doubles ("Fox & Falco vs Marth & Sheik", yours first), everyone in a
// free-for-all.
function liteTitle(g) {
  const ps = g.players || []
  const name = (p) => charName(p.character)
  const mine = (p) => p.port === g.user_port
  if (g.is_teams && ps.every((p) => p.team != null)) {
    const teams = new Map()
    for (const p of ps) teams.set(p.team, [...(teams.get(p.team) || []), p])
    return [...teams.values()]
      .sort((a, b) => b.some(mine) - a.some(mine))
      .map((t) => t.map(name).join(' & ')).join(' vs ')
  }
  return [...ps].sort((a, b) => mine(b) - mine(a)).map(name).join(' vs ')
}

export default function ReplaysPage() {
  const [identity, setIdentity] = useState(null)
  const [status, setStatus] = useState(null) // {index}
  const [facets, setFacets] = useState(null)
  const [months, setMonths] = useState(null)       // [{ym, count}] | null
  const [monthData, setMonthData] = useState({})   // ym -> {games, loading}
  const [expanded, setExpanded] = useState(() => new Set())
  const [filters, setFilters] = useState({ my_char: '', opp_char: '', stage: '', opponent: '', result: '', teams: '' })
  const [opponentDraft, setOpponentDraft] = useState('')
  const [addOpen, setAddOpen] = useState(false)
  const [codeDraft, setCodeDraft] = useState('')
  const [watchModsGame, setWatchModsGame] = useState(null)
  // Play builds: "Watch in Nucleus Unlocked" on each row (null when Play is off).
  const muReplay = useMuReplay(PLAY_ENABLED)
  const [liteGame, setLiteGame] = useState(null)
  const [rootDraft, setRootDraft] = useState(null) // null = untouched, show detected root
  const [scanError, setScanError] = useState(null)
  const [ranks, setRanks] = useState({}) // code -> {tier, rating, ...}
  const [stocks, setStocks] = useState({}) // game_id -> {port: stocks_left}
  const startedScan = useRef(null) // the scan this screen started
  // Every list request takes a number from loadSeq; latestLoad[ym] is the one
  // whose answer that month may show, so a slow page-3 response can't clobber
  // the page-4 the user already clicked to. loadMonths empties latestLoad, so
  // a page still in flight from the previous view (other filters, before a
  // rescan) can't land in the new one either. monthsSeq does the same for the
  // month list itself.
  const loadSeq = useRef(0)
  const latestLoad = useRef({})
  const monthsSeq = useRef(0)
  // Multi-select: game id -> game. Survives paging, month toggles and filter
  // changes, so a playlist can be assembled from anywhere in the library.
  const [selected, setSelected] = useState(() => new Map())
  const [playlist, setPlaylist] = useState(null) // {clips, title, games}
  const [playCount, setPlayCount] = useState(PLAYLIST_DEFAULT) // "Play [N]"

  // Rows in on-screen order (open months, newest first) for shift-click
  // ranges; refreshed every render.
  const visibleRowsRef = useRef([])
  const selectAnchor = useRef(null) // id of the last plain-clicked row

  // Plain click toggles one game. Shift-click sets every row between the last
  // clicked one and this one to this row's new state, like a file manager.
  const toggleSelect = useCallback((g, shift = false) => {
    playSound('boop')
    const rows = visibleRowsRef.current
    const from = shift ? rows.findIndex((r) => r.id === selectAnchor.current) : -1
    const to = rows.findIndex((r) => r.id === g.id)
    setSelected((prev) => {
      const next = new Map(prev)
      const on = !next.has(g.id)
      const range = from >= 0 && to >= 0
        ? rows.slice(Math.min(from, to), Math.max(from, to) + 1)
        : [g]
      for (const r of range) {
        if (on) next.set(r.id, r)
        else next.delete(r.id)
      }
      return next
    })
    selectAnchor.current = g.id
  }, [])

  const fetchJson = useCallback((url, opts) => api.request(url, opts), [])

  const refreshIdentity = useCallback(async () => {
    try {
      setIdentity(await fetchJson(`${API}/identity`))
      setFacets(await fetchJson(`${API}/replays/facets`))
    } catch { /* backend not up yet; the empty state still renders */ }
  }, [fetchJson])

  const filterParams = useCallback((currentFilters) => {
    const params = new URLSearchParams()
    for (const [k, v] of Object.entries(currentFilters)) {
      if (v !== '' && v != null) params.set(k, v)
    }
    return params
  }, [])

  // load one PAGE of one month's games (pages replace the list — a month
  // with hundreds of games stays a fixed-size view, not an ever-growing one)
  const loadMonthGames = useCallback(async (ym, page, currentFilters) => {
    const seq = ++loadSeq.current
    latestLoad.current[ym] = seq
    const isLatest = () => latestLoad.current[ym] === seq
    setMonthData((prev) => ({
      ...prev,
      // `paged` = this month has rendered once already; page swaps skip the
      // staggered row entrance so paging doesn't strobe
      [ym]: { games: prev[ym]?.games || [], page, loading: true, paged: Boolean(prev[ym]) },
    }))
    try {
      const params = filterParams(currentFilters)
      params.set('month', ym)
      params.set('limit', PAGE_SIZE)
      params.set('offset', page * PAGE_SIZE)
      const data = await fetchJson(`${API}/replays?${params}`)
      if (!isLatest()) return // a newer click or a new view superseded this
      setMonthData((prev) => ({
        ...prev,
        [ym]: { games: data.games, page, loading: false, paged: Boolean(prev[ym]?.paged) },
      }))
    } catch {
      if (!isLatest()) return
      // `failed`: reopening the month asks again instead of showing this
      // empty result as if it were the month's games
      setMonthData((prev) => ({
        ...prev,
        [ym]: { ...(prev[ym] || { games: [], page: 0 }), loading: false, failed: true },
      }))
    }
  }, [fetchJson, filterParams])

  // (re)load the month buckets, reset expansion, auto-open + load the newest
  const loadMonths = useCallback(async (currentFilters) => {
    const seq = ++monthsSeq.current
    latestLoad.current = {}
    setMonthData({})
    setExpanded(new Set())
    try {
      const { months: ms } = await fetchJson(`${API}/replays/months?${filterParams(currentFilters)}`)
      if (monthsSeq.current !== seq) return // filters changed again meanwhile
      setMonths(ms)
      if (ms.length) {
        setExpanded(new Set([ms[0].ym]))
        loadMonthGames(ms[0].ym, 0, currentFilters)
      }
    } catch {
      if (monthsSeq.current === seq) setMonths([])
    }
  }, [fetchJson, filterParams, loadMonthGames])

  const toggleMonth = (ym) => {
    playSound('boop')
    const opening = !expanded.has(ym)
    setExpanded((prev) => {
      const next = new Set(prev)
      if (opening) next.add(ym)
      else next.delete(ym)
      return next
    })
    // side effects stay OUT of the state updater — React double-invokes
    // updaters in dev, which double-fetched the month
    if (opening && (!monthData[ym] || monthData[ym].failed)) loadMonthGames(ym, 0, filters)
  }

  useEffect(() => {
    refreshIdentity()
    fetchJson(`${API}/replays/status`).then(setStatus).catch(() => {})
  }, [refreshIdentity, fetchJson])

  useEffect(() => {
    loadMonths(filters)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters])

  // every game currently loaded across expanded months (feeds ranks/stocks)
  const loadedGames = useMemo(
    () => Object.values(monthData).flatMap((m) => m.games || []),
    [monthData])

  // Rank and final-stock lookups for the loaded rows: one request of each
  // kind in flight, no key asked twice (batchLookup.js says why).
  const rankLookup = useRef(null)
  const stockLookup = useRef(null)
  useEffect(() => {
    const post = (path, body) => fetchJson(`${API}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const rankLk = createBatchLookup({
      batchSize: RANK_BATCH,
      request: (codes) => post('/ranks', { codes }),
      onResult: (_codes, d) => setRanks((prev) => ({ ...prev, ...d })),
    })
    const stockLk = createBatchLookup({
      batchSize: PAGE_SIZE,
      request: (ids) => post('/replays/stocks', { game_ids: ids }),
      onResult: (ids, d) => setStocks((prev) => {
        const next = { ...prev }
        for (const id of ids) next[id] = d[id] || {} // seed misses so we don't refetch
        return next
      }),
    })
    rankLookup.current = rankLk
    stockLookup.current = stockLk
    return () => { rankLk.stop(); stockLk.stop() }
  }, [fetchJson])

  // Slippi ranks (cached server-side): both sides of every game on the page.
  useEffect(() => {
    const codes = new Set()
    if (identity?.active_login_code) codes.add(identity.active_login_code)
    for (const g of loadedGames) {
      for (const p of g.players || []) {
        if (p.code) codes.add(p.code)
      }
    }
    rankLookup.current?.want([...codes].filter((c) => !(c in ranks)))
  }, [loadedGames, identity, ranks])

  // Final stock counts for the row summary (read from each .slp's last frame).
  useEffect(() => {
    stockLookup.current?.want(loadedGames.map((g) => g.id).filter((id) => !(id in stocks)))
  }, [loadedGames, stocks])

  // The scan is a `replay_scan` job; the cloud loop runs one every ten
  // minutes too. When one ends, reload what it changed: the list only when it
  // added, updated or removed games (reloading closes the open months), or
  // when this screen started it.
  const scan = passView(useLatestJob('replay_scan'))
  const scanRunning = scan.running
  useJobEnd('replay_scan', (job) => {
    fetchJson(`${API}/replays/status`).then(setStatus).catch(() => {})
    if (replayScanNeedsRefresh(job, startedScan.current)) {
      refreshIdentity()
      loadMonths(filters)
    }
  })

  // `dir` (optional) = a manually entered folder; the backend remembers it
  const startScan = async (dir) => {
    playSound('boop')
    setScanError(null)
    try {
      const { job_id: jobId } = await fetchJson(`${API}/replays/scan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(dir ? { dir } : {}),
      })
      startedScan.current = jobId
      refreshJob(jobId).catch(() => {})
    } catch (e) {
      // 409 = already running (fine); 400 = the folder doesn't exist
      if (e.message === '400') setScanError('Folder not found')
    }
  }

  // The current Slippi login is always "you" (locked); these manage the rest:
  // the user's other accounts, and earlier logins seen on this computer.
  const saveCodes = async (next) => {
    playSound('boop')
    await fetchJson(`${API}/identity/codes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ codes: next }),
    }).catch(() => {})
    refreshIdentity()
    loadMonths(filters)
  }

  const addCode = (code) => {
    const cleaned = code.trim().toUpperCase()
    if (!cleaned) return
    setCodeDraft('')
    setAddOpen(false)
    saveCodes([...(identity?.user_codes || []), cleaned])
  }

  const removeCode = (code) => {
    saveCodes((identity?.user_codes || []).filter((c) => c !== code))
  }

  const setFilter = (key, value) => setFilters((f) => ({ ...f, [key]: value }))

  // games on the currently visible pages (expanded months only)
  const shownGames = (months || [])
    .filter((mo) => expanded.has(mo.ym))
    .flatMap((mo) => monthData[mo.ym]?.games || [])
  visibleRowsRef.current = shownGames
  const allShownSelected = shownGames.length > 0 && shownGames.every((g) => selected.has(g.id))
  const toggleShown = () => {
    playSound('boop')
    setSelected((prev) => {
      const next = new Map(prev)
      for (const g of shownGames) {
        if (allShownSelected) next.delete(g.id)
        else next.set(g.id, g)
      }
      return next
    })
  }
  const selectedGames = [...selected.values()]
  const selectedSeconds = selectedGames.reduce((n, g) => n + (g.duration_s || 0), 0)

  // Queue games WHOLE. Ticked games play in the order they were ticked (the
  // Map keeps insertion order); `chronological` plays oldest first instead.
  const openPlaylist = (list, { chronological = false } = {}) => {
    // by id: a self-play game (both ports are your codes) is listed twice
    const games = [...new Map([...list].map((g) => [g.id, g])).values()]
    if (chronological) {
      games.sort((a, b) => (a.start_at || '').localeCompare(b.start_at || '') || a.id - b.id)
    }
    const clips = games.map(fullGameClip).filter((c) => c.end_frame != null)
    if (!clips.length) return
    setPlaylist({
      clips,
      games,
      title: `Watch ${clips.length} game${clips.length === 1 ? '' : 's'}`,
    })
  }

  // Top-right "Play": the ticked games if any, else the latest N games that
  // match the current filters (the Combos tab's "Play [N] combos").
  const playGames = async () => {
    playSound('boop')
    if (selected.size) return openPlaylist(selected.values())
    const want = Math.min(PLAYLIST_CAP, Math.max(1, playCount || PLAYLIST_DEFAULT))
    const games = []
    try {
      while (games.length < want) {
        const params = filterParams(filters)
        const limit = Math.min(200, want - games.length) // backend page cap
        params.set('limit', limit)
        params.set('offset', games.length)
        const data = await fetchJson(`${API}/replays?${params}`)
        games.push(...(data.games || []))
        if ((data.games || []).length < limit) break
      }
    } catch { /* backend not up */ }
    openPlaylist(games, { chronological: true })
  }

  const indexed = status?.index?.parsed ?? identity?.index?.parsed ?? 0
  const totalGames = (months || []).reduce((n, m) => n + m.count, 0)
  const userCodes = identity?.user_codes || []
  const aliasNames = [...new Set((identity?.aliases || []).map((a) => a.name))]
  const [allAliases, setAllAliases] = useState(false)

  if (!scanRunning && indexed === 0) {
    const effectiveRoot = (rootDraft ?? identity?.replay_root ?? '').trim()
    // only pass the folder along when the user actually changed it, so an
    // untouched auto-detected path never freezes into a manual override
    const manualDir = rootDraft != null && effectiveRoot !== identity?.replay_root
      ? effectiveRoot : undefined
    return (
      <div className="replays-page">
        <div className="replays-empty">
          <h2>No replays found</h2>
          <input
            className="replays-empty-path"
            type="text"
            spellCheck={false}
            value={rootDraft ?? identity?.replay_root ?? ''}
            placeholder="Path to your Slippi replay folder…"
            onChange={(e) => { setRootDraft(e.target.value); setScanError(null) }}
            onKeyDown={(e) => { if (e.key === 'Enter' && effectiveRoot) startScan(manualDir) }}
          />
          {(scanError || scan.error) && (
            <p className="replays-empty-error">{scanError || `Scan failed: ${scan.error}`}</p>
          )}
          <button
            className="replays-scan-btn"
            onMouseEnter={playHoverSound}
            onClick={() => startScan(manualDir)}
            disabled={!effectiveRoot}
          >
            Scan replays
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="replays-page">
      {identity?.netplay && (
        <div className="replays-identity">
          <div className="replays-identity-who">
            <span className="replays-identity-name">{identity.netplay.displayName}</span>
            {aliasNames.length > 1 && (() => {
              const others = aliasNames.filter((n) => n !== identity.netplay.displayName)
              const shown = allAliases ? others : others.slice(0, 3)
              return (
                <span className={`replays-identity-aliases${allAliases ? ' replays-identity-aliases--all' : ''}`}>
                  aka {shown.join(', ')}
                  {others.length > 3 && (
                    <button
                      type="button" className="replays-aliases-toggle"
                      onMouseEnter={playHoverSound}
                      onClick={() => { playSound('boop'); setAllAliases((v) => !v) }}
                    >
                      {allAliases ? 'fewer' : `+${others.length - 3} more`}
                    </button>
                  )}
                </span>
              )
            })()}
          </div>
          <div className="replays-identity-codes">
            {userCodes.map((code) => {
              // Only the current login is locked. A past login can be a
              // friend who signed in once on this computer, so it gets the ×.
              const isActive = code === identity.active_login_code
              const isPastLogin = !isActive && (identity.login_codes || []).includes(code)
              return (
                <span key={code} className={`replays-code-chip is-you ${isActive ? 'is-login' : ''}`}>
                  {code}
                  {isActive ? (
                    <span className="replays-chip-lock" title="Your current Slippi login">✓</span>
                  ) : (
                    <button
                      className="replays-chip-x"
                      onMouseEnter={playHoverSound}
                      onClick={() => removeCode(code)}
                      title={isPastLogin
                        ? 'An earlier Slippi login on this computer. Not you? Remove it'
                        : 'Not you? Remove this code'}
                    >
                      ×
                    </button>
                  )}
                </span>
              )
            })}
            <div className="replays-add-code">
              <button
                className="replays-code-chip replays-code-add"
                onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); setAddOpen((o) => !o) }}
              >
                + add
              </button>
              {addOpen && (
                <div className="replays-add-pop">
                  <form onSubmit={(e) => { e.preventDefault(); addCode(codeDraft) }}>
                    <input
                      autoFocus
                      type="text"
                      placeholder="ABCD#123"
                      value={codeDraft}
                      onChange={(e) => setCodeDraft(e.target.value)}
                    />
                  </form>
                  {(identity.account_suggestions || []).length > 0 && (
                    <>
                      <p className="replays-add-section">Your other Slippi accounts</p>
                      {(identity.account_suggestions || []).map(({ account, code, games: n }) => (
                        <button
                          key={code}
                          className="replays-add-suggestion replays-add-suggestion--account"
                          onMouseEnter={playHoverSound}
                          onClick={() => addCode(code)}
                          title={`Games under this code use the netplay name “${account}”, which matches your Slippi account`}
                        >
                          <span>{code} <span className="replays-add-account">“{account}”</span></span>
                          <span className="replays-add-count">{n.toLocaleString()} games</span>
                        </button>
                      ))}
                    </>
                  )}
                  {(identity.top_codes || []).filter(({ code }) =>
                    !userCodes.includes(code)
                    && !(identity.account_suggestions || []).some((s) => s.code === code)
                  ).length > 0 && (
                    <p className="replays-add-section">Frequent codes in your replays</p>
                  )}
                  {(identity.top_codes || [])
                    .filter(({ code }) => !userCodes.includes(code)
                      && !(identity.account_suggestions || []).some((s) => s.code === code))
                    .slice(0, 4)
                    .map(({ code, games: n }) => (
                      <button
                        key={code}
                        className="replays-add-suggestion"
                        onMouseEnter={playHoverSound}
                        onClick={() => addCode(code)}
                      >
                        <span>{code}</span>
                        <span className="replays-add-count">{n.toLocaleString()} games</span>
                      </button>
                    ))}
                </div>
              )}
            </div>
          </div>
          <button className="replays-rescan" onMouseEnter={playHoverSound} onClick={() => startScan()} disabled={scanRunning}>
            {scanRunning ? 'Scanning…' : 'Rescan'}
          </button>
        </div>
      )}

      {scanRunning && (
        <div className="replays-scanbar">
          <div className="replays-scanbar-fill" style={{
            width: scan.total ? `${(100 * scan.done) / scan.total}%` : '100%',
          }} />
          <span className="replays-scanbar-text">
            Scanning… {scan.done.toLocaleString()}
            {scan.total ? ` / ${scan.total.toLocaleString()}` : ''} files
          </span>
        </div>
      )}
      {!scanRunning && scan.error && (
        <p className="replays-scan-failed">Scan failed: {scan.error}</p>
      )}

      <div className="replays-filters">
        <IconSelect
          value={filters.my_char}
          onChange={(v) => setFilter('my_char', v)}
          placeholder="Me: any character"
          options={(facets?.my_characters || []).map(({ character, games: n }) => ({
            value: character,
            label: charName(character),
            count: n,
            icon: `${API}/stock/${character}/0`,
          }))}
        />
        <IconSelect
          value={filters.opp_char}
          onChange={(v) => setFilter('opp_char', v)}
          placeholder="Vs: any character"
          options={(facets?.opp_characters || []).map(({ character, games: n }) => ({
            value: character,
            label: charName(character),
            count: n,
            icon: `${API}/stock/${character}/0`,
          }))}
        />
        <IconSelect
          value={filters.stage}
          onChange={(v) => setFilter('stage', v)}
          placeholder="Any stage"
          options={(facets?.stages || []).map(({ stage, games: n }) => ({
            value: stage,
            label: stageName(stage),
            count: n,
            icon: `${API}/stage-icon/${stage}`,
          }))}
        />
        <IconSelect
          value={filters.result}
          onChange={(v) => setFilter('result', v)}
          placeholder="Any result"
          options={[
            { value: 'win', label: 'Wins' },
            { value: 'loss', label: 'Losses' },
          ]}
        />
        <IconSelect
          value={filters.teams}
          onChange={(v) => setFilter('teams', v)}
          placeholder="Singles & doubles"
          options={[
            { value: 'singles', label: 'Singles' },
            { value: 'doubles', label: 'Doubles' },
          ]}
        />
        <form
          className="replays-opponent-search"
          onSubmit={(e) => { e.preventDefault(); setFilter('opponent', opponentDraft.trim()) }}
        >
          <input
            type="text"
            placeholder="Opponent name or code…"
            value={opponentDraft}
            onChange={(e) => setOpponentDraft(e.target.value)}
            onBlur={() => setFilter('opponent', opponentDraft.trim())}
          />
        </form>
        <span className="replays-count">{totalGames.toLocaleString()} games</span>
        <div className="replays-playall-group">
          {selected.size > 0 ? (
            <>
              <button type="button" className="replays-sel-btn" onMouseEnter={playHoverSound}
                      onClick={toggleShown} disabled={!shownGames.length}>
                {allShownSelected ? 'Deselect shown' : 'Select shown'}
              </button>
              <button type="button" className="replays-sel-btn" onMouseEnter={playHoverSound}
                      onClick={() => { playSound('boop'); setSelected(new Map()) }}>
                Clear
              </button>
              <button type="button" className="replays-playall" onMouseEnter={playHoverSound}
                      onClick={playGames}
                      title={`Play the ticked games back-to-back, whole — with skins, and record them to one video${
                        selectedSeconds > 0 ? ` (${formatTotal(selectedSeconds)})` : ''}${
                        selected.size > PLAYLIST_CAP ? `; only the first ${PLAYLIST_CAP.toLocaleString()} play` : ''}`}>
                ▶ Play {selected.size.toLocaleString()} selected
              </button>
            </>
          ) : (
            <>
              <button type="button" className="replays-playall" onMouseEnter={playHoverSound}
                      onClick={playGames} disabled={!totalGames}
                      title="Play the latest games matching these filters back-to-back, whole — with skins, and record them to one video. Tick games to pick exactly which.">
                ▶ Play
              </button>
              <input
                className="replays-playcount"
                type="number"
                min={1}
                value={playCount}
                onChange={(e) => {
                  const v = parseInt(e.target.value, 10)
                  setPlayCount(Number.isFinite(v) ? Math.max(1, v) : '')
                }}
                onBlur={(e) => { if (!e.target.value) setPlayCount(PLAYLIST_DEFAULT) }}
                title="How many of the latest games to queue"
              />
              <span className="replays-playall-suffix">games</span>
            </>
          )}
        </div>
      </div>

      <div className="replays-months">
        {months && months.length === 0 && (
          <p className="replays-none">No games match these filters.</p>
        )}
        {(months || []).map((mo) => {
          const md = monthData[mo.ym]
          const isOpen = expanded.has(mo.ym)
          const loaded = md?.games || []
          return (
            <section key={mo.ym} data-ym={mo.ym}
                     className={`replay-month ${isOpen ? 'is-open' : ''}`}>
              <button className="replay-month-head" onMouseEnter={playHoverSound}
                      onClick={() => toggleMonth(mo.ym)}>
                <span className="replay-month-caret">▸</span>
                <span className="replay-month-name">{monthLabel(mo.ym)}</span>
                <span className="replay-month-count">{mo.count.toLocaleString()}</span>
              </button>
              {isOpen && (
                <div className="replays-list">
                  {loaded.map((g, i) => (
                    <ReplayRow key={g.id} g={g} i={i} ranks={ranks} stocks={stocks}
                               instant={Boolean(md?.paged)}
                               selected={selected.has(g.id)} onSelect={toggleSelect}
                               onWatch={setWatchModsGame} onLite={setLiteGame} muReplay={muReplay} />
                  ))}
                  {mo.count > PAGE_SIZE && (
                    <MonthPager
                      page={md?.page || 0}
                      pages={Math.ceil(mo.count / PAGE_SIZE)}
                      loading={md?.loading}
                      onPage={(p) => {
                        playSound('boop')
                        loadMonthGames(mo.ym, p, filters)
                        // jump back to the month's top so a short last page
                        // can't strand the viewport in collapsed space
                        document.querySelector(`[data-ym="${mo.ym}"]`)
                          ?.scrollIntoView({ block: 'start' })
                      }}
                    />
                  )}
                </div>
              )}
            </section>
          )
        })}
      </div>

      {playlist && (
        <PlaylistModsModal
          clips={playlist.clips} title={playlist.title} unit="game"
          onClose={() => setPlaylist(null)}
          // the row's Lite rule: any game with two or more players
          onWatchLite={playlist.games.every((g) => g.players.length >= 2)
            ? () => {
              const games = playlist.games
              setPlaylist(null)
              setLiteGame({ playlist: games })
            }
            : undefined}
        />
      )}

      {liteGame?.playlist && (
        <WatchLiteModal
          clips={liteGame.playlist.map((g) => ({
            gameId: g.id, title: liteTitle(g), subtitle: stageName(g.stage),
          }))}
          onClose={() => setLiteGame(null)} />
      )}

      {liteGame && !liteGame.playlist && (
        <WatchLiteModal gameId={liteGame.id}
          title={liteTitle(liteGame)}
          subtitle={stageName(liteGame.stage)}
          onClose={() => setLiteGame(null)} />
      )}

      {watchModsGame && (
        <WatchModsModal game={watchModsGame} onClose={() => setWatchModsGame(null)} />
      )}
    </div>
  )
}
