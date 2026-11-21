import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../shared/transport/api'
import { useJobEndedAt } from '../../shared/jobs/useJobs'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import {
  getStartggSlug, onStartggChange, fetchStartggProfile, getCachedStartggData,
  fetchStartggStandings, syncStartggSets, syncMoreStartggSets, fetchStartggEventSets,
} from './startgg'
import { createTournamentLoader } from './tournamentLoading'
import { groupEvents, headToHead, demons, bestWins, trajectory, ordinal } from './tournamentMath'
import { API, matchForSets, openExternal, Section } from './tournamentShared'
import RunSection from './RunSection'
import SetDetailModal from './SetDetailModal'
import { EventList, TrajectoryChart, DemonRows, BestWinRows } from './TournamentLists'
import '../stats/StatsPage.css'
import './TournamentsPage.css'

const BracketView = lazy(() => import('./BracketView'))
const WatchLiteModal = lazy(() => import('../replays/WatchLiteModal'))

// "Your start.gg" — the tournament half of your Slippi life, free for every
// player (start.gg's ToS is explicit that their data is not ours to sell).
// The page answers the Monday-morning question — "how
// did my weekend actually go?" — by leading with THE RUN: your latest bracket,
// set by set, with seeds, upset factors, and (the desktop trick) your actual
// local replays attached to the sets they belong to.

const StartggIcon = (props) => (
  <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
    <path d="M8 4H5v16h3M16 4h3v16h-3" />
  </svg>
)

const agoLabel = (ms) => {
  if (!ms) return ''
  const mins = Math.round((Date.now() - ms) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hours = Math.round(mins / 60)
  if (hours < 48) return `${hours} h ago`
  return `${Math.round(hours / 24)} d ago`
}

function Stat({ value, label, cls = '' }) {
  return (
    <span className="stats-stat">
      <span className={`stats-stat-num ${cls}`}>{value}</span>
      <span className="stats-stat-label">{label}</span>
    </span>
  )
}

export default function TournamentsPage({ onGoToSettings }) {
  const [slug, setSlug] = useState(getStartggSlug)
  useEffect(() => onStartggChange((s) => setSlug(s || '')), [])
  return <TournamentHistory key={slug} slug={slug} onGoToSettings={onGoToSettings} />
}

function TournamentHistory({ slug, onGoToSettings }) {
  const [cached] = useState(() => getCachedStartggData(slug))
  const [profile, setProfile] = useState(cached.profile)
  const [standings, setStandings] = useState(cached.standings)
  const [standingsPending, setStandingsPending] = useState(!cached.standings)
  const [setsData, setSetsData] = useState(cached.sets)
  const [phase, setPhase] = useState(slug ? 'loading' : 'idle')
  const [loader] = useState(() => createTournamentLoader({
    cached: getCachedStartggData, profile: fetchStartggProfile,
    standings: fetchStartggStandings, sets: syncStartggSets,
    onProfile: setProfile,
    onStandings: value => { setStandings(value); setStandingsPending(false) },
    onSets: setSetsData, onPhase: setPhase,
  }))
  const mounted = useRef(true)
  const [selectedKey, setSelectedKey] = useState(null)
  const [replayMap, setReplayMap] = useState(() => new Map())
  const [watch, setWatch] = useState(null)   // {clips, startIndex}
  const [detail, setDetail] = useState(null) // {title, subtitle, sets} -> SetDetailModal
  const [syncingMore, setSyncingMore] = useState(false)
  const [avatarFailed, setAvatarFailed] = useState(false)
  const [bracket, setBracket] = useState(null) // null | {status, sets, partial, reason}
  const [replayRevision, setReplayRevision] = useState('')
  // When the last replay scan job ended; the poll below reads it each round.
  const lastScanEnded = useRef(null)
  lastScanEnded.current = useJobEndedAt('replay_scan')

  useEffect(() => {
    if (!slug || !setsData) return undefined
    const controller = new AbortController()
    let timer
    const refresh = async () => {
      try {
        const [status, identity] = await Promise.all([
          api.get(`${API}/replays/status`, { signal: controller.signal }),
          api.get(`${API}/identity`, { signal: controller.signal }),
        ])
        const revision = JSON.stringify([
          lastScanEnded.current, status?.index || null,
          identity?.user_codes || [],
        ])
        if (!controller.signal.aborted) setReplayRevision(revision)
      } catch { /* local backend unavailable; replay chips stay as-is */ }
      if (!controller.signal.aborted) timer = setTimeout(refresh, 3000)
    }
    refresh()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [slug, !!setsData])

  const load = useCallback((force) => loader.load(slug, { force }), [loader, slug])

  useEffect(() => {
    mounted.current = true
    if (slug) load(false)
    return () => { mounted.current = false; loader.cancel() }
  }, [slug, load, loader])

  const events = useMemo(
    () => (setsData ? groupEvents(setsData.sets, setsData.playerId) : []),
    [setsData])
  const h2h = useMemo(() => headToHead(events), [events])
  const demonList = useMemo(() => demons(h2h), [h2h])
  const scalps = useMemo(() => bestWins(events, 60), [events])
  const series = useMemo(() => trajectory(events), [events])
  const selected = useMemo(
    () => events.find((ev) => ev.key === selectedKey) || events[0] || null,
    [events, selectedKey])

  // Recent events = runs from synced sets, plus standings-only rows for events
  // whose sets fell outside the backfill window (visible but not clickable).
  const eventRows = useMemo(() => {
    const rows = events.map((ev) => ({
      key: ev.key, at: ev.lastAt, name: ev.event.tournament || ev.event.name,
      eventName: ev.event.name, placement: ev.placement,
      entrants: ev.event.entrants, delta: ev.delta, run: true,
    }))
    const known = new Set(events.map((ev) => ev.key))
    for (const st of standings?.standings || []) {
      if (!st.event?.id || known.has(st.event.id)) continue
      rows.push({
        key: st.event.id, at: st.event.start_at, name: st.event.tournament || st.event.name,
        eventName: st.event.name, placement: st.placement,
        entrants: st.event.entrants, delta: null, run: false,
      })
    }
    rows.sort((a, b) => (b.at || 0) - (a.at || 0))
    return rows
  }, [events, standings])

  const career = useMemo(() => {
    let wins = 0; let losses = 0; let upsets = 0; let best = null
    for (const ev of events) {
      wins += ev.wins
      losses += ev.losses
      upsets += ev.sets.filter((s) => s.upset).length
      if (ev.placement != null
          && (!best || ev.placement < best.placement
              || (ev.placement === best.placement
                  && (ev.event.entrants || 0) > (best.event.entrants || 0)))) best = ev
    }
    const graded = events.filter((ev) => ev.delta != null)
    return {
      wins, losses, upsets, best,
      winrate: wins + losses ? wins / (wins + losses) : null,
      outperf: graded.filter((ev) => ev.delta > 0).length,
      graded: graded.length,
    }
  }, [events])

  // Local Slippi replays for the selected run: time+code-match its sets
  // against the local index (months are fetched once and shared with the
  // set-detail sheet). Every failure path just means "no ▶ chips".
  useEffect(() => {
    // Wait for the revision once, avoiding an immediate duplicate month fetch
    // under the empty revision followed by the real index/identity revision.
    if (!selected || !replayRevision) { setReplayMap(new Map()); return undefined }
    let live = true
    matchForSets(selected.sets, replayRevision)
      .then((m) => { if (live) setReplayMap(m) })
      .catch(() => { if (live) setReplayMap(new Map()) })
    return () => { live = false }
  }, [selected, replayRevision])

  // bracket view: on-demand per event, closed again when the run changes.
  // `bracketVisible` drives the expand/collapse animation: the section mounts
  // collapsed, opens a frame later, and on close waits for the collapse
  // transition before unmounting.
  const [bracketVisible, setBracketVisible] = useState(false)
  const bracketCloseTimer = useRef(null)
  const bracketRequest = useRef(0)

  useEffect(() => {
    bracketRequest.current += 1
    clearTimeout(bracketCloseTimer.current)
    setBracket(null)
  }, [selected?.key])

  useEffect(() => {
    if (!bracket) { setBracketVisible(false); return undefined }
    // a short timeout (not rAF — which never fires in hidden windows) lets the
    // browser commit the collapsed 0fr state first, so the open transitions
    const id = setTimeout(() => setBracketVisible(true), 30)
    return () => clearTimeout(id)
  }, [bracket])

  useEffect(() => () => clearTimeout(bracketCloseTimer.current), [])

  // Above this, we can't show a whole bracket (a 700-entrant major is ~1400
  // sets); we scope to the phase groups the player actually appeared in.
  const BRACKET_FULL_MAX_ENTRANTS = 128

  const toggleBracket = useCallback(async () => {
    if (bracket) {
      bracketRequest.current += 1
      // collapse first, unmount when the transition is done
      setBracketVisible(false)
      clearTimeout(bracketCloseTimer.current)
      bracketCloseTimer.current = setTimeout(() => setBracket(null), 400)
      return
    }
    if (!selected) return
    const request = ++bracketRequest.current
    const ev = selected.event
    let phaseGroupIds = null
    if ((ev.entrants || 0) > BRACKET_FULL_MAX_ENTRANTS) {
      phaseGroupIds = [...new Set(selected.sets.map((s) => s.pg_id).filter(Boolean))]
      if (!phaseGroupIds.length) { setBracket({ status: 'error', reason: 'big' }); return }
    }
    setBracket({ status: 'loading' })
    try {
      const data = await fetchStartggEventSets(ev.id, { phaseGroupIds })
      if (mounted.current && bracketRequest.current === request) {
        setBracket({ status: 'ready', sets: data.sets, partial: data.partial })
      }
    } catch {
      if (mounted.current && bracketRequest.current === request) setBracket({ status: 'error', reason: 'network' })
    }
  }, [bracket, selected])

  const onWatch = useCallback((clips, startIndex = 0) => {
    setWatch({ clips, startIndex })
  }, [])

  const openSet = useCallback((set) => {
    setDetail({
      title: `${set.round_text || 'Set'} vs ${set.opp.name || '?'}`,
      subtitle: set.event?.tournament || set.event?.name || '',
      sets: [set],
    })
  }, [])

  // bracket boxes -> the corresponding run set (same start.gg set ids)
  const runSetById = useMemo(
    () => new Map((selected?.sets || []).map((s) => [s.id, s])),
    [selected])
  const openBracketSet = useCallback((setId) => {
    const s = runSetById.get(setId)
    if (s) openSet(s)
  }, [runSetById, openSet])

  const syncMore = useCallback(async () => {
    if (syncingMore || !slug) return
    setSyncingMore(true)
    try {
      const data = await syncMoreStartggSets(slug)
      if (mounted.current && data) setSetsData((prev) => ({ ...prev, ...data }))
    } catch { /* offline — the button stays for a retry */ }
    if (mounted.current) setSyncingMore(false)
  }, [slug, syncingMore])

  // ── states without data ──
  // Not connected: no sales pitch, just the one action that fixes it,
  // dead-center in the panel.
  if (!slug) {
    return (
      <div className="tg-page tg-page--center">
        <button
          type="button" className="tg-cta tg-cta--danger"
          onMouseEnter={playHoverSound}
          onClick={() => { playSound('boop'); if (onGoToSettings) onGoToSettings() }}
        >
          <StartggIcon /> Link start.gg
        </button>
      </div>
    )
  }

  if (phase === 'loading' && !setsData && !standings) {
    return <div className="tg-page"><div className="stats-loading">Pulling your bracket history…</div></div>
  }

  if (phase === 'error' && !setsData && !standings) {
    return (
      <div className="tg-page">
        <div className="tg-card">
          <span className="tg-card-kicker"><StartggIcon /> start.gg</span>
          <h2>start.gg is unreachable</h2>
          <p>Couldn&rsquo;t fetch your results (offline, or their API is down). Your data is still there — try again in a bit.</p>
          <button type="button" className="tg-cta" onMouseEnter={playHoverSound}
                  onClick={() => { playSound('boop'); load(true) }}>
            Retry
          </button>
        </div>
      </div>
    )
  }

  if (phase !== 'loading' && !standingsPending && setsData && !events.length && !(standings?.standings || []).length) {
    return (
      <div className="tg-page">
        <div className="tg-card">
          <span className="tg-card-kicker"><StartggIcon /> start.gg</span>
          <h2>No brackets yet</h2>
          <p>
            {profile?.gamer_tag || slug} hasn&rsquo;t played any Melee events on
            start.gg yet. Enter something local — the moment your first set is
            reported, your run shows up here.
          </p>
        </div>
        <TgFooter />
      </div>
    )
  }

  const stale = setsData?.stale || standings?.stale

  return (
    <div className="tg-page">
      <div className="tg-head">
        <div className="tg-identity">
          <div className="tg-avatar">
            {profile?.image && !avatarFailed ? (
              <img src={profile.image} alt="" onError={() => setAvatarFailed(true)} />
            ) : (
              (profile?.gamer_tag || slug)[0].toUpperCase()
            )}
          </div>
          <div className="tg-identity-name">
            <strong>
              {profile?.prefix && <span className="tg-prefix">{profile.prefix} | </span>}
              {profile?.gamer_tag || setsData?.gamerTag || slug}
            </strong>
            <button
              type="button" className="tg-link"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('boop'); openExternal(`https://www.start.gg/user/${slug}`) }}
            >
              <StartggIcon /> results from start.gg ↗
            </button>
          </div>
        </div>
        <div className="tg-sync">
          {stale && <span className="tg-stale" title="start.gg was unreachable — showing your cached results">cached</span>}
          <span className="tg-sync-at" role="status">{phase === 'loading' ? 'Syncing history…' : `synced ${agoLabel(setsData?.syncedAt)}`}</span>
          <button
            type="button" className="tg-refresh" title="Re-sync from start.gg"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); load(true) }}
            disabled={phase === 'loading' || syncingMore}
          >
            {phase === 'loading' ? '…' : '⟳'}
          </button>
        </div>
      </div>

      <div className="stats-statline">
        <Stat value={events.length} label="events" />
        <span className="stats-stat-div" />
        <Stat value={`${career.wins}–${career.losses}`} label="sets" />
        <span className="stats-stat-div" />
        <Stat
          value={career.winrate == null ? '—' : `${(career.winrate * 100).toFixed(1)}%`}
          label="won"
          cls={career.winrate == null ? '' : career.winrate >= 0.5 ? 'is-up' : 'is-down'}
        />
        <span className="stats-stat-div" />
        <Stat value={career.upsets} label="upsets landed" />
        <span className="stats-stat-div" />
        <Stat
          value={career.best ? ordinal(career.best.placement) : '—'}
          label={career.best ? `best · ${career.best.event.entrants ?? '?'} entrants` : 'best placement'}
        />
      </div>
      <p className="stats-statline-caption">
        {setsData?.partial
          ? `covering your most recent ${setsData.sets.length} of ${setsData.total} sets`
          : `all ${setsData?.sets.length ?? 0} reported sets`}
        {career.graded > 0 && (
          <span> · out-placed your seed at{' '}
            <span className={career.outperf * 2 >= career.graded ? 'is-up' : 'is-down'}>
              {career.outperf} of {career.graded}
            </span> events
          </span>
        )}
        {setsData?.partial && (
          <button
            type="button" className="tg-syncmore"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); syncMore() }}
            disabled={syncingMore || phase === 'loading'}
          >
            {syncingMore ? 'syncing…' : 'sync older sets'}
          </button>
        )}
      </p>

      <div className="stats-grid">
        {selected && (
          <RunSection run={selected} replayMap={replayMap} onOpenSet={openSet}
                      onBracket={toggleBracket} bracketOpen={!!bracket} />
        )}

        <Section title="Recent events" sub="click one to load that run">
          <EventList rows={eventRows} selectedKey={selected?.key} onSelect={setSelectedKey} />
        </Section>

        {bracket && selected && (
          <div className={`stats-section--wide tg-bracket-wrap${bracketVisible ? ' is-open' : ''}`}>
          <div className="tg-bracket-inner">
          <Section
            title="Bracket"
            sub={`${selected.event.tournament || ''} · ${selected.event.name || ''}`}
            wide
          >
            {bracket.status === 'loading' && (
              <p className="stats-footnote">Pulling the bracket from start.gg…</p>
            )}
            {bracket.status === 'error' && (
              <p className="stats-footnote">
                {bracket.reason === 'big'
                  ? 'This event is too big to render in-app from the data synced so far — '
                  : 'start.gg is unreachable right now — '}
                <button
                  type="button" className="tg-link"
                  onMouseEnter={playHoverSound}
                  onClick={() => { playSound('boop'); openExternal(`https://www.start.gg/${selected.event.slug || ''}`) }}
                >
                  open it on start.gg ↗
                </button>
              </p>
            )}
            {bracket.status === 'ready' && (
              <>
                <Suspense fallback={<p className="stats-footnote" role="status">Loading bracket view…</p>}>
                <BracketView sets={bracket.sets}
                             myEntrantId={selected.sets[0]?.me.entrant_id}
                             replayMap={replayMap}
                             onOpenSet={openBracketSet} />
                </Suspense>
                <p className="stats-footnote">
                  {bracket.partial ? 'Large bracket — showing the first pages. ' : ''}
                  Your sets are highlighted — the ones with a ▶ have local
                  replays, click to watch. Hover a name to trace their path.
                  Bracket data from start.gg.
                </p>
              </>
            )}
          </Section>
          </div>
          </div>
        )}

        {series.length >= 3 && (
          <Section title="Paper vs bracket" sub="did you beat your seed? every event, in order" wide>
            <TrajectoryChart series={series} />
          </Section>
        )}

        <Section title="Bracket demons" sub="they keep sending you to losers">
          <DemonRows list={demonList} onOpenSets={setDetail} />
        </Section>

        <Section title="Best wins" sub="ranked by upset factor">
          <BestWinRows list={scalps} onOpenSets={setDetail} />
        </Section>
      </div>

      <TgFooter />

      {detail && (
        <SetDetailModal detail={detail} replayRevision={replayRevision} onClose={() => setDetail(null)} onWatch={onWatch} />
      )}
      {watch && (
        <Suspense fallback={<p className="stats-footnote" role="status">Loading player…</p>}>
        <WatchLiteModal clips={watch.clips} startIndex={watch.startIndex}
                        onClose={() => setWatch(null)} />
        </Suspense>
      )}
    </div>
  )
}

// Required attribution (start.gg ToS §2.3): visible credit, unaltered name.
function TgFooter() {
  return (
    <p className="tg-attribution">
      Tournament data provided by{' '}
      <button
        type="button" className="tg-link"
        onMouseEnter={playHoverSound}
        onClick={() => { playSound('boop'); openExternal('https://www.start.gg') }}
      >
        start.gg
      </button>
      {' '}— your results, always free.
    </p>
  )
}
