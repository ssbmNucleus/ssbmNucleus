import { Fragment, lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { BACKEND_URL } from '../../shared/config/config'
import { api } from '../../shared/transport/api'
import { refreshJob, useJobEnd, useLatestJob } from '../../shared/jobs/useJobs'
import { passView } from '../../shared/jobs/passView'
import { comboScanNeedsRefresh } from '../replays/scanRefresh'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { charName, stageName, moveName, formatDate, slippiProfileUrl, openSlippiProfile } from '../../shared/data/meleeNames'
import IconSelect from '../../shared/ui/IconSelect'
import FilterSelect from '../../shared/ui/FilterSelect'
import LiteButton from '../lib/LiteGate'
import ShareLinkButton from '../share/ShareLinkButton'
import ComboLibraryStatus from './ComboLibraryStatus'
import { createComboPageRequest } from './comboPageRequest'
import NumberedPager from '../../shared/ui/NumberedPager'
import './CombosPage.css'

const API = `${BACKEND_URL}/api/nucleome`
const PAGE_SIZE = 50
// Browsing the list does not need the playback renderer or its dependencies.
const WatchModsModal = lazy(() => import('../replays/WatchModsModal'))
const WatchLiteModal = lazy(() => import('../replays/WatchLiteModal'))
const PlaylistModsModal = lazy(() => import('../replays/PlaylistModsModal'))
// The "Play [N]" playlist count is user-set (default 25) and intentionally
// UNcapped — combo marathons are a feature. The backend keeps a high runaway
// backstop (PLAYLIST_CLIP_CAP), but the UI doesn't clamp.
const PLAYLIST_DEFAULT = 25

// Filter dropdowns: preset options (value '' = any) plus typed-number rows so
// any exact value is reachable. min_moves / min_damage values are plain
// numbers; start_pct encodes direction: '<N' = starts under N%, 'N+' = starts
// at N%+ (queryParams maps those onto the API's max_start / min_start).
const isNum = (v) => /^\d+(\.\d+)?$/.test(v)

const MIN_MOVES = [
  { value: '4', label: '4+ moves' },
  { value: '5', label: '5+ moves' },
  { value: '6', label: '6+ moves' },
  { value: '7', label: '7+ moves' },
]
const MIN_MOVES_INPUTS = [{
  key: 'n', before: 'At least', after: 'moves',
  encode: (n) => `${Math.round(n)}`,
  decode: (v) => (isNum(v) ? Number(v) : null),
  format: (n) => `${n}+ moves`,
}]
const MIN_DAMAGE = [
  { value: '30', label: '30%+' },
  { value: '50', label: '50%+' },
  { value: '70', label: '70%+' },
  { value: '100', label: '100%+' },
]
const MIN_DAMAGE_INPUTS = [{
  key: 'n', before: 'At least', after: '% damage',
  encode: (n) => `${n}`,
  decode: (v) => (isNum(v) ? Number(v) : null),
  format: (n) => `${n}%+ damage`,
}]
const START_PERCENT = [
  { value: '<0', label: 'From 0%' },
  { value: '<25', label: 'Starts under 25%' },
  { value: '<50', label: 'Starts under 50%' },
  { value: '50+', label: 'Starts at 50%+' },
]
const START_PERCENT_INPUTS = [
  {
    key: 'under', before: 'Starts under', after: '%',
    encode: (n) => `<${n}`,
    decode: (v) => (v.startsWith('<') && isNum(v.slice(1)) ? Number(v.slice(1)) : null),
    format: (n) => `Starts under ${n}%`,
  },
  {
    key: 'from', before: 'Starts at', after: '%+',
    encode: (n) => `${n}+`,
    decode: (v) => (v.endsWith('+') && isNum(v.slice(0, -1)) ? Number(v.slice(0, -1)) : null),
    format: (n) => `Starts at ${n}%+`,
  },
]
const KINDS = [
  { value: 'true', label: 'True combos' },
  { value: 'string', label: 'Strings' },
]
// Sort metrics rendered as a toggle-button row. `defDir` is the direction a
// button lands on when first picked (the natural one for that metric); clicking
// the active button flips it. The chosen sort+direction also drives the "Play"
// playlist, so a marathon plays in whatever order you're browsing.
const SORTS = [
  { value: 'recent', label: 'Recent', defDir: 'desc' },
  { value: 'damage', label: 'Damage', defDir: 'desc' },
  { value: 'moves', label: 'Moves', defDir: 'desc' },
  { value: 'start_percent', label: 'Start %', defDir: 'asc' },
  { value: 'duration', label: 'Length', defDir: 'desc' },
]

// "U-Tilt → U-Tilt → Fair ×2"
function moveSequence(movesList) {
  return (movesList || [])
    .map((m) => moveName(m.move_id) + (m.hits > 1 ? ` ×${m.hits}` : ''))
    .join(' → ')
}

// A player's display name; if they have a connect code it's a button that
// opens their slippi.gg profile in the system browser.
function PlayerName({ name, code, fallback, className }) {
  const label = name || code || fallback
  if (!slippiProfileUrl(code)) {
    return <span className={className}>{label}</span>
  }
  return (
    <button
      type="button"
      className={`${className} combo-name-link`}
      onMouseEnter={playHoverSound}
      onClick={() => { playSound('boop'); openSlippiProfile(code) }}
      title={`Open ${code} on slippi.gg`}
    >
      {label}
    </button>
  )
}

function ComboRow({ c, i, onWatch, onLite }) {
  const durationS = ((c.end_frame - c.start_frame) / 60).toFixed(1)
  const me = (c.game.players || []).find((p) => p.port === c.port)
  const opp = (c.game.players || []).find((p) => p.port === c.opp_port)
  const seq = moveSequence(c.moves_list)
  return (
    <div className="combo-row" style={{ '--row-i': Math.min(i, 14) }}>
      <div className="combo-who" title={charName(c.character)}>
        <img className="combo-stock" alt=""
             src={`${API}/stock/${c.character}/${me?.costume ?? 0}`}
             onError={(e) => { e.target.style.display = 'none' }} />
        <PlayerName className="combo-player" name={c.name}
                    code={c.code} fallback={`P${c.port}`} />
      </div>
      <div className="combo-main">
        <div className="combo-seq" title={seq}>
          {(c.moves_list || []).map((m, k) => (
            <Fragment key={k}>
              {k > 0 && <span className="combo-seq-arrow">→</span>}
              <span className="combo-move">
                {moveName(m.move_id)}
                {m.hits > 1 && <span className="combo-move-hits">×{m.hits}</span>}
              </span>
            </Fragment>
          ))}
        </div>
        <div className="combo-facts">
          <span className="combo-damage">{Math.round(c.damage)}%</span>
          <span className="combo-percents">
            {Math.round(c.start_percent)}% → {Math.round(c.end_percent)}%
          </span>
          <span className="combo-length">{c.moves} moves · {durationS}s</span>
          {c.true_combo === true && (
            <span className="combo-kind combo-kind--true"
                  title="The opponent never regained control between hits">
              TRUE
            </span>
          )}
          {c.true_combo === false && (
            <span className="combo-kind combo-kind--string"
                  title="The opponent had actionable frames between hits">
              STRING
            </span>
          )}
          {c.did_kill && <span className="combo-kill">KILL</span>}
        </div>
      </div>
      <div className="combo-vs" title={charName(c.opp_character)}>
        <span className="combo-vs-label">vs</span>
        <img className="combo-stock" alt=""
             src={`${API}/stock/${c.opp_character}/${opp?.costume ?? 0}`}
             onError={(e) => { e.target.style.display = 'none' }} />
        <PlayerName className="combo-opp" name={c.opp_name}
                    code={c.opp_code} fallback={`P${c.opp_port}`} />
      </div>
      <span className="combo-stage">
        <img className="combo-stage-icon" src={`${API}/stage-icon/${c.stage}`} alt={stageName(c.stage)}
             loading="lazy" onError={(e) => { e.target.style.display = 'none' }} />
      </span>
      <span className="combo-when">{formatDate(c.start_at)}</span>
      <div className="combo-actions">
        {/* Not `synced`: sharing uploads the game on demand now. `shareable`
            is the one thing that can't be fixed by uploading — a combo below
            the length rule never gets a /combo/N page at all. */}
        <ShareLinkButton gameId={c.game.id} comboId={c.id} players={c.game.players}
                         disabledReason={c.shareable ? '' : 'Public combo links require at least 4 moves. Multiple hits from one move count as one move.'} />
        <LiteButton className="wl-trigger" onOpen={() => onLite(c)}
                    title="Preview this combo instantly in-app (no Dolphin)">
          Lite
        </LiteButton>
        <button className="combo-watch" onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); onWatch(c) }}
                title="Play just this combo (with optional skins)">
          ▶ Watch
        </button>
      </div>
    </div>
  )
}

// nucleOME Combos: every conversion mined out of the indexed corpus,
// filterable by character, length, damage, kills, percent, stage. Extraction
// is its own user-triggered pass over the frame data (heavier than the
// metadata scan), incremental after the first run.
export default function CombosPage() {
  const [identity, setIdentity] = useState(null)
  const [facets, setFacets] = useState(null)
  const [status, setStatus] = useState(null) // {counts}
  // Defaults match the public-link floor of four distinct moves, plus a
  // browsing-only damage filter. Multi-hit attacks still count as one move.
  const [filters, setFilters] = useState({
    mine: 'me', my_char: '', vs_char: '', stage: '', opponent: '',
    min_moves: '4', min_damage: '50', start_pct: '', kind: '', kills: false,
  })
  const [sort, setSort] = useState('recent')
  const [sortDir, setSortDir] = useState('desc')
  const [data, setData] = useState(null) // {total, combos} for the current page
  const [page, setPage] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [firstPageSettled, setFirstPageSettled] = useState(false)
  const [detailsError, setDetailsError] = useState(false)
  const [detailsAttempt, setDetailsAttempt] = useState(0)
  const [pageRequest] = useState(() => createComboPageRequest({
    request: (url, options) => api.request(url, options),
    onData: (result, p) => { setData(result); setPage(p) },
    onLoading: setLoading,
    onError: setLoadError,
    onSettled: () => setFirstPageSettled(true),
  }))
  const [opponentDraft, setOpponentDraft] = useState('')
  const [playCount, setPlayCount] = useState(PLAYLIST_DEFAULT) // "Play [N]"
  const [watching, setWatching] = useState(null) // {game, clip}
  const [lite, setLite] = useState(null) // {gameId, start, end, title, subtitle}
  const [playlist, setPlaylist] = useState(null) // {clips, title}
  const requestedPage = useRef(0)

  const fetchJson = useCallback((url, opts) => api.request(url, opts), [])

  useEffect(() => {
    // Give the first page priority over library-wide header/dropdown queries.
    if (!firstPageSettled) return undefined
    const controller = new AbortController()
    const options = { signal: controller.signal }
    setDetailsError(false)
    const accept = setter => value => { if (!controller.signal.aborted) setter(value) }
    const failed = () => { if (!controller.signal.aborted) setDetailsError(true) }
    fetchJson(`${API}/identity`, options).then(accept(setIdentity)).catch(failed)
    fetchJson(`${API}/replays/facets`, options).then(accept(setFacets)).catch(failed)
    fetchJson(`${API}/combos/status`, options).then(accept(setStatus)).catch(failed)
    return () => controller.abort()
  }, [fetchJson, firstPageSettled, detailsAttempt])

  useEffect(() => () => pageRequest.cancel(), [pageRequest])

  // direction-aware mapping: the API's char/opp_char are attacker/victim
  const queryParams = useCallback((f, offset) => {
    const params = new URLSearchParams()
    params.set('mine', f.mine)
    const attacker = f.mine === 'vs' ? f.vs_char : f.my_char
    const victim = f.mine === 'vs' ? f.my_char : f.vs_char
    if (attacker !== '') params.set('char', attacker)
    if (victim !== '') params.set('opp_char', victim)
    if (f.stage !== '') params.set('stage', f.stage)
    if (f.opponent) params.set('opponent', f.opponent)
    if (f.min_moves !== '') params.set('min_moves', f.min_moves)
    if (f.min_damage !== '') params.set('min_damage', f.min_damage)
    if (f.kind !== '') params.set('kind', f.kind)
    if (f.kills) params.set('kills', '1')
    if (f.start_pct.startsWith('<')) params.set('max_start', f.start_pct.slice(1))
    else if (f.start_pct.endsWith('+')) params.set('min_start', f.start_pct.slice(0, -1))
    params.set('sort', sort)
    params.set('direction', sortDir)
    params.set('limit', PAGE_SIZE)
    params.set('offset', offset)
    return params
  }, [sort, sortDir])

  // Fetch one page (server-side offset/limit), replacing the visible list.
  const loadPage = useCallback((p) => {
    requestedPage.current = p
    return pageRequest.load(`${API}/combos?${queryParams(filters, p * PAGE_SIZE)}`, p)
  }, [pageRequest, queryParams, filters])

  // Any filter/sort change resets to page 1. loadPage closes over the fresh
  // filters/sort, so re-running it here reloads with the new query.
  useEffect(() => {
    loadPage(0)
  }, [loadPage])

  // Pick a sort metric, or flip direction if it's already active.
  const chooseSort = (value, defDir) => {
    playSound('boop')
    if (value === sort) setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))
    else { setSort(value); setSortDir(defDir) }
  }

  // The pass is a `combo_scan` job; the cloud loop runs one every ten minutes
  // too. When one ends, refresh the counts, and the first page when it
  // analyzed any games or this screen started it.
  const scan = passView(useLatestJob('combo_scan'))
  const startedScan = useRef(null)
  useJobEnd('combo_scan', (job) => {
    fetchJson(`${API}/combos/status`).then(setStatus).catch(() => {})
    if (comboScanNeedsRefresh(job, startedScan.current)) loadPage(0)
  })

  const startScan = async () => {
    playSound('boop')
    try {
      const { job_id: jobId } = await fetchJson(`${API}/combos/scan`, { method: 'POST' })
      startedScan.current = jobId
      refreshJob(jobId).catch(() => {})
    } catch { /* 409 = already running */ }
  }

  const setFilter = (key, value) => setFilters((f) => ({ ...f, [key]: value }))

  // Queue the top N currently-filtered combos (in the current sort order) as
  // one back-to-back playlist. The modal then offers per-character/stage skins
  // that dress the whole reel from a single stateless ISO.
  const playTop = useCallback(async (n) => {
    playSound('boop')
    const count = Math.max(1, n || PLAYLIST_DEFAULT)
    const params = queryParams(filters, 0)
    params.set('limit', count)
    try {
      const d = await fetchJson(`${API}/combos?${params}`)
      const clips = (d.combos || []).map((c) => ({
        game_id: c.game.id,
        start_frame: c.start_frame,
        end_frame: c.end_frame,
      }))
      if (clips.length) {
        setPlaylist({
          clips,
          title: `Watch ${clips.length} combo${clips.length === 1 ? '' : 's'}`,
        })
      }
    } catch { /* backend not up */ }
  }, [fetchJson, queryParams, filters])

  const hasCodes = (identity?.user_codes || []).length > 0

  return (
    <div className="combos-page">
      <ComboLibraryStatus identity={identity} status={{ ...status, scan }} error={detailsError}
                          onScan={startScan} onRetry={() => setDetailsAttempt(n => n + 1)} />

      <div className="combos-filters">
          <div className="combos-direction" title={!identity ? "Loading identity..." : !hasCodes ? "Add your connect code in Replays to filter by player." : undefined}>
            <button
              disabled={!hasCodes}
              className={`combos-dir-btn ${filters.mine === 'me' ? 'active' : ''}`}
              onMouseEnter={playHoverSound}
              onClick={() => setFilter('mine', 'me')}
              title="Combos you performed"
            >
              My combos
            </button>
            <button
              disabled={!hasCodes}
              className={`combos-dir-btn ${filters.mine === 'vs' ? 'active' : ''}`}
              onMouseEnter={playHoverSound}
              onClick={() => setFilter('mine', 'vs')}
              title="Combos your opponents landed on you"
            >
              On me
            </button>
          </div>
        <IconSelect
          disabled={!facets}
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
          disabled={!facets}
          value={filters.vs_char}
          onChange={(v) => setFilter('vs_char', v)}
          placeholder="Vs: any character"
          options={(facets?.opp_characters || []).map(({ character, games: n }) => ({
            value: character,
            label: charName(character),
            count: n,
            icon: `${API}/stock/${character}/0`,
          }))}
        />
        <IconSelect
          disabled={!facets}
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
        <FilterSelect
          value={filters.min_moves}
          onChange={(v) => setFilter('min_moves', v)}
          anyLabel="Any length"
          options={MIN_MOVES}
          inputs={MIN_MOVES_INPUTS}
        />
        <FilterSelect
          value={filters.min_damage}
          onChange={(v) => setFilter('min_damage', v)}
          anyLabel="Any damage"
          options={MIN_DAMAGE}
          inputs={MIN_DAMAGE_INPUTS}
        />
        <FilterSelect
          value={filters.start_pct}
          onChange={(v) => setFilter('start_pct', v)}
          anyLabel="Any start %"
          options={START_PERCENT}
          inputs={START_PERCENT_INPUTS}
        />
        <FilterSelect
          value={filters.kind}
          onChange={(v) => setFilter('kind', v)}
          anyLabel="Combos & strings"
          options={KINDS}
        />
        <button
          className={`combos-kills ${filters.kills ? 'active' : ''}`}
          onMouseEnter={playHoverSound}
          onClick={() => { playSound('boop'); setFilter('kills', !filters.kills) }}
          title="Only combos that took a stock"
        >
          Kills only
        </button>
        <form
          className="combos-opponent-search"
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
        <div className="combos-sort" role="group" aria-label="Sort combos by">
          <span className="combos-sort-label">Sort:</span>
          {SORTS.map((s) => (
            <button
              key={s.value}
              className={`combos-sort-btn ${sort === s.value ? 'active' : ''}`}
              onMouseEnter={playHoverSound}
              onClick={() => chooseSort(s.value, s.defDir)}
              title={sort === s.value ? 'Click to flip direction' : `Sort by ${s.label.toLowerCase()}`}
            >
              {s.label}
              {sort === s.value && (
                <span className="combos-sort-arrow">{sortDir === 'asc' ? '↑' : '↓'}</span>
              )}
            </button>
          ))}
        </div>
        <span className="combos-count">
          {data ? `${data.total.toLocaleString()} combos` : loadError ? 'Combos unavailable' : 'Loading combos…'}
        </span>
        <div className="combos-playall-group">
          <button
            className="combos-playall"
            onMouseEnter={playHoverSound}
            onClick={() => playTop(playCount)}
            disabled={!data || data.total === 0}
            title="Play these combos back-to-back, with optional skins"
          >
            ▶ Play
          </button>
          <input
            className="combos-playcount"
            type="number"
            min={1}
            value={playCount}
            onChange={(e) => {
              const v = parseInt(e.target.value, 10)
              setPlayCount(Number.isFinite(v) ? Math.max(1, v) : '')
            }}
            onBlur={(e) => { if (!e.target.value) setPlayCount(PLAYLIST_DEFAULT) }}
            title="How many combos to queue (go wild — it's your marathon)"
          />
          <span className="combos-playall-suffix">combos</span>
        </div>
      </div>

      <div className="combos-list" aria-busy={loading}>
        {loading && !data && <p className="combos-none" role="status">Loading combos…</p>}
        {loadError && <div className="combos-pending" role="alert">
          {loadError}
          <button className="combos-pending-btn" onClick={() => loadPage(requestedPage.current)}>Retry</button>
        </div>}
        {data && data.combos.length === 0 && !loading && (
          <p className="combos-none">No combos match these filters.</p>
        )}
        {(data?.combos || []).map((c, i) => (
          <ComboRow key={c.id} c={c} i={i}
                    onWatch={(combo) => setWatching({
                      game: combo.game,
                      clip: { start: combo.start_frame, end: combo.end_frame },
                    })}
                    onLite={(combo) => setLite({
                      gameId: combo.game.id,
                      start: combo.start_frame, end: combo.end_frame,
                      title: `${charName(combo.character)} combo · ${Math.round(combo.damage)}%`,
                      subtitle: `vs ${charName(combo.opp_character)} · ${stageName(combo.stage)}`,
                    })} />
        ))}
        {data && data.combos.length > 0 && (
          <NumberedPager
            page={page}
            pages={Math.ceil(data.total / PAGE_SIZE)}
            loading={loading}
            onPage={loadPage}
          />
        )}
      </div>

      <Suspense fallback={<p className="combos-none" role="status">Loading player…</p>}>
      {watching && (
        <WatchModsModal game={watching.game} clip={watching.clip}
                        onClose={() => setWatching(null)} />
      )}

      {lite && (
        <WatchLiteModal clips={lite.clips} gameId={lite.gameId} start={lite.start} end={lite.end}
                        title={lite.title} subtitle={lite.subtitle}
                        onClose={() => setLite(null)} />
      )}

      {playlist && (
        <PlaylistModsModal clips={playlist.clips} title={playlist.title}
                           onClose={() => setPlaylist(null)}
                           onWatchLite={(cs) => {
                             setPlaylist(null)
                             setLite({
                               title: playlist.title || 'Combo playlist',
                               clips: cs.map((c) => ({
                                 gameId: c.game_id, start: c.start_frame, end: c.end_frame,
                               })),
                             })
                           }} />
      )}
      </Suspense>
    </div>
  )
}
