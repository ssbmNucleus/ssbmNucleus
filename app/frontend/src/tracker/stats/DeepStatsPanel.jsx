import { useCallback, useEffect, useState } from 'react'
import { BACKEND_URL } from '../../shared/config/config'
import { api } from '../../shared/transport/api'
import { refreshJob, useJobEnd, useLatestJob } from '../../shared/jobs/useJobs'
import { passView } from '../../shared/jobs/passView'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { charName } from '../../shared/data/meleeNames'
import './DeepStatsPanel.css'

const API = `${BACKEND_URL}/api/nucleome`

// Frame-level stats for ONE of the player's characters, mined from their own
// replays (analyzer rows in nucleome.db via /api/nucleome/deep/*). Shows in
// the Stats grid when a character filter is active — before mining it's an
// "Analyze N games" call to action, during mining a progress bar, after
// mining the panel proper. Mining is a `deep_stats` job; Randall can also
// start one from chat, and this panel follows its record either way.

const METRIC_TILES = [
  ['lc_rate', 'L-cancel', '%'],
  ['tech_rate', 'Tech', '%'],
  ['openings_per_min', 'Openings', '/min'],
  ['dmg_per_conv', 'Dmg/conv', ''],
  ['kill_conv_pct', 'Kill conv', '%'],
  ['avg_death_pct', 'Avg death', '%'],
]

const CAUSE_META = [
  ['raw', 'Raw kill', '#7aa2f7'],
  ['edgeguard', 'Edgeguarded', '#e0af68'],
  ['failed_recovery', 'Failed recovery', '#f7768e'],
  ['tech_chase', 'Tech chased', '#bb9af7'],
  ['sd', 'SD', '#565f89'],
]

export default function DeepStatsPanel({ character }) {
  const [pack, setPack] = useState(null)
  const [coverage, setCoverage] = useState(null)
  const record = useLatestJob('deep_stats')
  const job = passView(record)
  const [starting, setStarting] = useState(false)
  // per-game mining rate MEASURED on this machine (backend persists it
  // after every completed job); 0.2s is only the first-ever-run seed
  const [secsPerGame, setSecsPerGame] = useState(0.2)

  const load = useCallback(async () => {
    try {
      const d = await api.get('/api/nucleome/deep/pack', { query: { character } })
      setPack(d)
      setCoverage(d.coverage || null)
    } catch (err) {
      // 404 until something is mined — that body still carries the coverage
      if (err.data) {
        setPack(null)
        setCoverage(err.data.coverage || null)
      }
      /* backend gone; leave as-is */
    }
  }, [character])

  const status = useCallback(async () => {
    try {
      const d = await api.get('/api/nucleome/deep/status', { query: { character } })
      if (d.coverage) setCoverage(d.coverage)
      if (d.secs_per_game) setSecsPerGame(d.secs_per_game)
    } catch { /* backend gone; leave as-is */ }
  }, [character])

  // on mount / character change: fetch pack + coverage
  useEffect(() => {
    setPack(null)
    setCoverage(null)
    load()
    status()
  }, [character, load, status])

  // refresh the pack when a job lands
  useJobEnd('deep_stats', () => { load(); status() })

  const start = async () => {
    playSound('boop')
    setStarting(true)
    try {
      const { job_id: jobId } = await api.post('/api/nucleome/deep/start', { character })
      await refreshJob(jobId)
    } catch (err) {
      // 409 = a job is already running; its record shows here anyway
      if (err.status !== 409) throw err
    } finally {
      setStarting(false)
    }
  }

  const name = charName(character)
  const pending = coverage?.pending ?? 0
  const running = job.running
  // params.character is an int from the backend; the select's value may be
  // a string — compare numerically
  const jobCharacter = record?.params?.character
  const forMe = jobCharacter == null || Number(jobCharacter) === Number(character)
  const jobForMe = running && forMe

  // ---- mining in progress: progress bar
  if (jobForMe) {
    const pct = job.total ? Math.round((100 * job.done) / job.total) : 0
    return (
      <div className="deep-panel">
        <div className="deep-progress-wrap">
          <p className="deep-progress-label">
            Building deep stats for your {name}… {job.done}/{job.total}
          </p>
          <div className="deep-progress"><div style={{ width: `${pct}%` }} /></div>
        </div>
      </div>
    )
  }

  // ---- nothing mined yet: call to action
  if (!pack) {
    return (
      <div className="deep-panel deep-panel-empty">
        <p className="deep-empty-blurb">
          Deep stats for your {name} — L-cancels, tech rates, death causes,
          recovery — mined from your own replays.
        </p>
        <button
          type="button" className="deep-analyze-btn"
          disabled={starting || running || !pending}
          onMouseEnter={playHoverSound} onClick={start}
        >
          {running ? 'Another analysis is running…'
            : pending ? `Analyze ${pending.toLocaleString()} games`
              : 'No games to analyze'}
        </button>
        {pending > 0 && (
          <p className="deep-empty-eta">
            ~{Math.max(1, Math.round(pending * secsPerGame / 60))} min, runs in the background
          </p>
        )}
        {job.error && forMe && <p className="deep-failed">Analysis failed: {job.error}</p>}
      </div>
    )
  }

  // ---- the panel proper
  const causes = pack.deaths?.causes_pct || {}
  return (
    <div className="deep-panel">
      <div className="deep-head">
        <span className="deep-head-left">
          <img
            className="deep-head-icon" src={`${API}/stock/${character}/0`}
            alt="" title={name}
            onError={(e) => { e.target.style.display = 'none' }}
          />
          <span className="deep-head-n">
            {pack.n_games.toLocaleString()} games analyzed
          </span>
        </span>
        {pending > 0 && (
          <button
            type="button" className="deep-refresh-btn" disabled={starting || running}
            onMouseEnter={playHoverSound} onClick={start}
            title="New replays have been indexed since the last analysis"
          >
            +{pending.toLocaleString()} new
          </button>
        )}
      </div>

      {/* Same editorial boxscore language as the career line up top: big
          value + quiet label on a shared baseline, hairline column rules —
          not a wall of KPI chips. */}
      <div className="deep-statline">
        {METRIC_TILES.map(([key, label, unit]) => {
          const m = pack.metrics?.[key]
          return (
            <span className="deep-stat" key={key}>
              <span className="deep-stat-num">
                {m ? m.median : '—'}<small>{m ? unit : ''}</small>
              </span>
              <span className="deep-stat-label">{label}</span>
            </span>
          )
        })}
      </div>

      <div className="deep-bottom">
        {pack.deaths && (
          <>
            <p className="deep-causes-title">
              How your stocks end
              <span className="deep-causes-n">
                {pack.deaths.n_deaths.toLocaleString()} deaths
              </span>
            </p>
            <div className="deep-causes-bar">
              {CAUSE_META.map(([key, , color]) => (
                (causes[key] || 0) > 0 && (
                  <div key={key} style={{ width: `${causes[key]}%`, background: color }} />
                )
              ))}
            </div>
            <div className="deep-causes-legend">
              {CAUSE_META.map(([key, label, color]) => (
                (causes[key] || 0) > 0 && (
                  <span key={key}>
                    <i style={{ background: color }} />{label} {causes[key]}%
                  </span>
                )
              ))}
            </div>
          </>
        )}

        {pack.recovery && (
          <p className="deep-footline">
            Recovery: makes it back <strong>{pack.recovery.success_pct}%</strong> of
            the time ({pack.recovery.attempts_per_game}/game) · median death at{' '}
            <strong>{pack.deaths?.percentiles?.median ?? '—'}%</strong>
          </p>
        )}
      </div>
    </div>
  )
}
