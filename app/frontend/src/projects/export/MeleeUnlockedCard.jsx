/**
 * MeleeUnlockedCard - the export screen's fourth action: build a fighter plugin
 * (.mufighter) for each of the project's custom fighters whose C source is in the
 * Vault, into a `fighters` folder the user picks a place for. Melee Unlocked's
 * Source Port loads that folder from beside its game library.
 *
 * It is not one of the ISO pipelines (exportPipeline.js): nothing is built into
 * the ISO, and it does not need one. The build is a backend job
 * (`melee_unlocked_export`), followed here for its progress and its result. The
 * wording is meleeUnlocked.js.
 *
 * A plugin is native code the game runs. Source that came inside a downloaded
 * package is listed here as not built, with where it came from, until the user
 * confirms that fighter (POST .../source/<slug>/confirm, which only this window
 * can call). A fighter with no source can have a folder of C attached here.
 */
import { useCallback, useEffect, useState } from 'react'
import { api } from '../../shared/transport/api'
import { useActiveJob, useJob } from '../../shared/jobs/useJobs'
import { jobOutcome, jobPercent } from '../../shared/jobs/jobOutcome'
import {
  KIT_PATH_KEY, GCC_BIN_KEY, blockedReason, describe, fighterLists, resultLines, unconfirmedLine,
} from './meleeUnlocked.js'

const EXPORT_KIND = 'melee_unlocked_export'
const sourceUrl = slug => `/melee-unlocked/source/${encodeURIComponent(slug)}`

export default function MeleeUnlockedCard() {
  const [kitPath] = useState(() => localStorage.getItem(KIT_PATH_KEY) || '')
  const [gccBin] = useState(() => localStorage.getItem(GCC_BIN_KEY) || '')
  const [fighters, setFighters] = useState(null)
  const [jobId, setJobId] = useState(null)
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState(null)
  const [asking, setAsking] = useState(null)        // the slug whose confirmation is open
  const [sourceBusy, setSourceBusy] = useState(null)
  const [sourceError, setSourceError] = useState(null)

  // An export already running when the screen opens (started, then the dialog closed) is picked up.
  const active = useActiveJob(EXPORT_KIND)
  useEffect(() => { if (active?.id && !jobId) setJobId(active.id) }, [active?.id, jobId])   // kept, so its result shows when it ends
  const job = useJob(jobId || active?.id || null)
  const outcome = jobOutcome(job)
  const busy = starting || (!!job && !outcome)
  const percent = jobPercent(job)

  const loadFighters = useCallback(() => api.get('/melee-unlocked/fighters')
    .then(data => setFighters(fighterLists(data)))
    .catch(() => { /* no project open, or an older backend: the card stays generic */ }), [])
  useEffect(() => { loadFighters() }, [loadFighters])

  const reason = blockedReason({ kitPath, gccBin, fighters })
  const lines = startError ? [{ kind: 'error', text: startError }]
    : !outcome ? null
    : outcome.ok ? resultLines(outcome.result) : [{ kind: 'error', text: outcome.error }]

  const run = async () => {
    if (!window.electron) {
      setStartError('Electron API not available')
      return
    }
    const destination = await window.electron.selectDirectory()
    if (!destination) return
    setStarting(true)
    setStartError(null)
    try {
      const data = await api.post('/melee-unlocked/export', { destination, kitPath, gccBin })
      setJobId(data.job_id)
    } catch (err) {
      if (err.data?.job_id) setJobId(err.data.job_id)   // one is already running: follow it
      else setStartError(err.message)
    } finally {
      setStarting(false)
    }
  }

  // The user read the question, which names the fighter and where its source came from,
  // and allows this source (the sha256 it was shown) to be built.
  const confirmSource = async (fighter) => {
    setSourceBusy(fighter.slug)
    setSourceError(null)
    try {
      await api.post(`${sourceUrl(fighter.slug)}/confirm`, { sha256: fighter.sha256 })
      setAsking(null)
    } catch (err) {
      setSourceError(`${fighter.name}: ${err.message}`)
    } finally {
      setSourceBusy(null)
      loadFighters()
    }
  }

  const attachSource = async (fighter) => {
    if (!window.electron) return
    const folder = await window.electron.selectDirectory()
    if (!folder) return
    setSourceBusy(fighter.slug)
    setSourceError(null)
    try {
      await api.post(sourceUrl(fighter.slug), { folder })
    } catch (err) {
      setSourceError(`${fighter.name}: ${err.message}`)
    } finally {
      setSourceBusy(null)
      loadFighters()
    }
  }

  const unconfirmed = fighters?.unconfirmed || []
  const withoutSource = fighters?.withoutSource || []

  return (
    <div className={`export-option accent-violet melee-unlocked-card ${reason ? 'disabled' : ''}`}>
      <div className="option-text">
        <h3>Melee Unlocked</h3>
        <p>{describe(fighters)}</p>
        {reason && <p className="option-reason">{reason}</p>}
        {(unconfirmed.length > 0 || withoutSource.length > 0) && !busy && (
          <ul className="mu-sources">
            {unconfirmed.map(f => (
              <li key={f.slug} className="mu-source mu-unconfirmed">
                <span>{unconfirmedLine(f)}</span>
                {asking === f.slug ? (
                  <div className="mu-confirm" role="group" aria-label={`Confirm ${f.name}'s source`}>
                    <p>{f.confirmText}</p>
                    <button className="btn-mu-source" onClick={() => confirmSource(f)} disabled={sourceBusy === f.slug}>
                      {`Build ${f.name}`}
                    </button>
                    <button className="btn-mu-source" onClick={() => setAsking(null)}>Cancel</button>
                  </div>
                ) : (
                  <button className="btn-mu-source" onClick={() => setAsking(f.slug)}>Review</button>
                )}
              </li>
            ))}
            {withoutSource.map(f => (
              <li key={f.slug} className="mu-source mu-without">
                <span>{`${f.name}: no C source in the Vault.`}</span>
                <button className="btn-mu-source" onClick={() => attachSource(f)} disabled={sourceBusy === f.slug}>
                  Attach source folder
                </button>
              </li>
            ))}
          </ul>
        )}
        {sourceError && <p className="option-reason">{sourceError}</p>}
        {busy && (
          <div className="melee-unlocked-progress" role="progressbar" aria-label="Melee Unlocked export progress"
               aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent ?? 0}>
            <div className="mu-bar"><div className="mu-bar-fill" style={{ width: `${percent ?? 0}%` }} /></div>
            <span className="mu-detail">{job?.detail || 'Starting...'}</span>
          </div>
        )}
        {!busy && lines && (
          <ul className="melee-unlocked-result">
            {lines.map((line, i) => <li key={i} className={`mu-line mu-${line.kind}`}>{line.text}</li>)}
          </ul>
        )}
      </div>
      <button className="btn-option" onClick={run} disabled={!!reason || busy}>
        {busy ? (percent != null ? `${percent}%` : 'Building...') : 'Export'}
      </button>
    </div>
  )
}
