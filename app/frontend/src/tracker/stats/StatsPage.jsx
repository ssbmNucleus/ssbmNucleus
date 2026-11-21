import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../shared/transport/api'
import { playHoverSound } from '../../shared/audio/sounds'
import { charName, stageName } from '../../shared/data/meleeNames'
import IconSelect from '../../shared/ui/IconSelect'
import StatsLoading from './StatsLoading'
import { createLatestRequest } from '../lib/latestRequest'
import { API, num } from './statsHelpers'
import { TooltipHost } from './StatsTooltip'
import { StatLine, StatLineCaption, Section } from './StatsBlocks'
import { BreakdownRows, RivalRows, SaltReport } from './StatsTables'
import { CharPie, PositionChart, SessionHist, HourChart, MonthChart } from './StatsCharts'
import RankChart from './RankChart'
const DeepStatsPanel = lazy(() => import('./DeepStatsPanel'))
import './StatsPage.css'

// the 6 tournament-legal stages: FoD, Stadium, Yoshi's, Dream Land, BF, FD.
// Everything else exists in the data but hides behind "Show all".
const LEGAL_STAGES = new Set([2, 3, 8, 28, 31, 32])

// "Top tiers" = everyone above Ganon tier on the standard SSBM tier list:
// Fox, Falco, Marth, Sheik, Puff, Falcon (top), Peach, ICs, Pikachu, Yoshi
// (high), Luigi, DK, Doc, Samus (mid). Character ids from meleeNames.CHARACTERS.
const TOP_TIERS = new Set([0, 1, 2, 7, 9, 12, 13, 14, 15, 16, 17, 19, 20, 22])

// nucleOME Stats: pure local math over the replay index — no AI anywhere in
// this tab (the coach is a separate chatbot that reads the same numbers).
// Everything renders from one GET /stats payload, refetched per char filter.

export default function StatsPage() {
  const [stats, setStats] = useState(null)
  const [facets, setFacets] = useState(null)
  const [rankHistory, setRankHistory] = useState(null)
  const [myChar, setMyChar] = useState('')
  // inclusive YYYY-MM-DD day bounds; empty = unbounded on that side
  const [range, setRange] = useState({ start: '', end: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [retry, setRetry] = useState(0)
  const [metadataReady, setMetadataReady] = useState(false)
  // full corpus span, captured from the first UNFILTERED response so the date
  // inputs have stable defaults that don't creep inward as filters narrow it
  const fullSpanRef = useRef(null)

  const [loader] = useState(() => createLatestRequest({
    request: (url, options) => api.request(url, options),
    onLoading: setLoading,
    onError: setError,
    errorMessage: 'Could not load stats.',
    onData: (s, qs) => {
      if (!fullSpanRef.current && !qs && s.overview?.first_at) {
        fullSpanRef.current = {
          start: s.overview.first_at.slice(0, 10),
          end: s.overview.last_at.slice(0, 10),
        }
      }
      setStats(s)
      setMetadataReady(true)
    },
  }))

  useEffect(() => {
    if (!metadataReady) return undefined
    const controller = new AbortController()
    const options = { signal: controller.signal }
    api.request(`${API}/replays/facets`, options).then(value => {
      if (!controller.signal.aborted) setFacets(value)
    }).catch(() => {})
    // Remote rating history never competes with the first local summary.
    api.request(`${API}/rank-history`, options).then(value => {
      if (!controller.signal.aborted) setRankHistory(value)
    }).catch(() => {})
    return () => controller.abort()
  }, [metadataReady])

  useEffect(() => {
    const params = new URLSearchParams()
    if (myChar !== '') params.set('my_char', myChar)
    if (range.start) params.set('start', range.start)
    if (range.end) params.set('end', range.end)
    const qs = params.toString()
    setLoading(true)
    setError('')
    const run = () => loader.load(`${API}/stats${qs ? `?${qs}` : ''}`, qs)
    // Date input segments can issue several changes while typing a year.
    const timer = qs ? setTimeout(run, 300) : null
    if (!qs) run()
    return () => { clearTimeout(timer); loader.cancel() }
  }, [myChar, range, retry, loader])

  const o = stats?.overview
  const hasRange = !!(range.start || range.end)

  // hide the my-characters section when it's collapsed to the filtered char
  const showMyChars = (stats?.my_characters || []).length > 1

  const charOptions = useMemo(() => (facets?.my_characters || []).map(
    ({ character, games: n }) => ({
      value: character,
      label: charName(character),
      count: n,
      icon: `${API}/stock/${character}/0`,
    })), [facets])

  // Only the truly-empty corpus gets the full empty page — an empty *period*
  // must keep the topbar so the dates can be adjusted back out of it.
  if (!loading && !error && stats && !stats.overview.games && !hasRange && myChar === '') {
    return (
      <div className="stats-page">
        <div className="stats-empty">
          <h2>No stats yet</h2>
          <p>
            Stats are computed from your indexed replays. Head to the Replays
            tab to scan your Slippi folder and claim your connect codes —
            everything here fills in from that same index.
          </p>
        </div>
      </div>
    )
  }

  if (!stats) {
    return <StatsLoading error={error} onRetry={() => setRetry(n => n + 1)} />
  }

  return (
    <TooltipHost>
    <div className="stats-page">
      <div className="stats-topbar">
        <IconSelect
          value={myChar}
          onChange={(v) => setMyChar(v)}
          placeholder="Any character"
          options={charOptions}
        />
        <span className="stats-span stats-daterange">
          <input
            type="date"
            className="stats-date-input"
            value={range.start || fullSpanRef.current?.start || ''}
            min={fullSpanRef.current?.start}
            max={range.end || fullSpanRef.current?.end}
            onChange={(e) => setRange((r) => ({ ...r, start: e.target.value }))}
            aria-label="Stats start date"
          />
          <span className="stats-daterange-arrow">→</span>
          <input
            type="date"
            className="stats-date-input"
            value={range.end || fullSpanRef.current?.end || ''}
            min={range.start || fullSpanRef.current?.start}
            max={fullSpanRef.current?.end}
            onChange={(e) => setRange((r) => ({ ...r, end: e.target.value }))}
            aria-label="Stats end date"
          />
          {hasRange && (
            <button
              className="stats-daterange-reset"
              onMouseEnter={playHoverSound}
              onClick={() => setRange({ start: '', end: '' })}
              title="Reset to all time"
            >
              ✕
            </button>
          )}
        </span>
      </div>

      <div className="stats-request-status" role={error ? 'alert' : 'status'}>
        {error ? <>{error} Showing previous results. <button className="stats-retry" onClick={() => setRetry(n => n + 1)}>Retry</button></>
          : loading ? 'Updating stats…' : null}
      </div>
      {!o.games ? (
        <div className="stats-empty">
          <h2>No games match these filters</h2>
          <p>Change the character or widen the date range.</p>
        </div>
      ) : (
      <>
      <StatLine o={o} sessions={stats.sessions} />
      <StatLineCaption o={o} sessions={stats.sessions} />

      <div className="stats-grid">
        <Section title="Matchups" sub="winrate vs each character">
          <BreakdownRows
            entries={stats.matchups}
            icon={(e) => `${API}/stock/${e.character}/0`}
            label={(e) => charName(e.character)}
            filterId={(e) => e.character}
            tierPreset={{ label: 'Top tiers only', ids: TOP_TIERS }}
          />
        </Section>

        {showMyChars ? (
          <Section title="Characters" sub="share of games" fill>
            <CharPie entries={stats.my_characters} />
          </Section>
        ) : myChar !== '' && (
          <Section title={`Deep stats — ${charName(myChar)}`}
                   sub="frame-level, from your replays" fill>
            <Suspense fallback={<p role="status">Loading detailed stats…</p>}>
              <DeepStatsPanel key={myChar} character={myChar} />
            </Suspense>
          </Section>
        )}

        <Section title="Stages" sub="winrate per stage">
          <BreakdownRows
            entries={stats.stages}
            icon={(e) => `${API}/stage-icon/${e.stage}`}
            label={(e) => stageName(e.stage)}
            defaultFilter={(e) => LEGAL_STAGES.has(e.stage)}
          />
        </Section>

        <Section title="Session stamina" sub="do you tilt deep in a session? each game vs your own average winrate">
          <PositionChart positions={stats.sessions.by_position} />
          <p className="stats-footnote stats-sesshist-label">
            How long your sessions run — sessions of exactly N games:
          </p>
          <SessionHist dist={stats.sessions.length_distribution} />
          <p className="stats-footnote">
            Median session: {num(stats.sessions.median_games)} games ·
            longest: {num(stats.sessions.longest)}. A session ends after
            45 minutes without a game.
          </p>
        </Section>

        <Section title="Activity" sub="games per month" wide>
          <MonthChart months={stats.months} />
        </Section>

        {stats.time_heatmap?.length > 0 && (
          <Section title="Time of day" sub="games per hour" wide>
            <HourChart cells={stats.time_heatmap} />
          </Section>
        )}

        {rankHistory && Object.values(rankHistory).some(
          (h) => (h.seasons || []).length || (h.samples || []).length) && (
          <Section title="Ranked rating" sub="over time, per connect code" wide>
            <RankChart history={rankHistory} />
            <p className="stats-footnote">
              Slippi only publishes each past season&apos;s final rating —
              Nucleus records your live rating whenever you use the app, so
              this chart fills in on its own from here on out.
            </p>
          </Section>
        )}

        <Section title="Rivals" sub="most-played opponents" wide>
          <RivalRows rivals={stats.rivals || []} />
        </Section>

        <Section title="Salt report" sub="early quits (No Contest endings)" wide>
          <SaltReport salt={stats.salt} />
        </Section>
      </div>
      </>
      )}
    </div>
    </TooltipHost>
  )
}
