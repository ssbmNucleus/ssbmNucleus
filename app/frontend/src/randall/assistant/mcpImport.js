/**
 * mcpImport.js - a model import the user's own AI runs over the app's MCP (backend randall/mcp/model_jobs.py: job
 * kind `mcp_model_import`, started by import_model or fix_import), as the window shows it: the chip in the header
 * that says what is being imported, with its Cancel (McpImportChip.jsx), and the vault read again when one saves a
 * costume (App.jsx). The records come from the window's job store (shared/jobs: the backend's `job` socket event),
 * never from a poll. Cancel is the job route every job's Cancel uses (POST /api/jobs/<id>/cancel); the AI's own stop
 * is the MCP tool cancel_import. Either ends rigswap and saves nothing.
 */
import { useCallback, useEffect, useState } from 'react'
import { ACTIVE } from '../../shared/jobs/jobStore'
import { cancelJob, useJobEnd, useLatestJob } from '../../shared/jobs/useJobs'
import { subscribe as subscribeSocket } from '../../shared/transport/socket'

export const KIND = 'mcp_model_import'
// The backend's word that another tool the user's AI ran saved to the vault (randall/mcp/window.vault_changed).
export const VAULT_EVENT = 'mcp_vault_changed'
// How long the chip says an import stopped before it goes.
export const LINGER_MS = 4000
// jobs.cancel's own progress line (core/jobs.py), the record's detail until the job ends.
export const STOPPING = 'Stopping…'
// The step while an ask waits on the user's AI (the record's `asking`: model_jobs._watch_asks).
export const ASKING = 'waiting on your AI’s answer'
// The files the importer reads (backend import_job.SOURCES): a name that still ends in one shows without it.
const MODEL_FILE = /\.(zip|glb|gltf|fbx|dae|obj|smd)$/i

const words = value => (typeof value === 'string' && value.trim() ? value.trim() : null)
const fileName = value => (words(value) ? words(value).split(/[\\/]/).pop() : null)

/** A model as the chip names it: 'Clank.zip' -> 'Clank'. The backend sends the name the costume is saved under; a
 * record from before it did, or the file name the chip falls back on, still carries the file's extension. */
export function modelName(value) {
  const name = words(value)
  return name ? (words(name.replace(MODEL_FILE, '')) || name) : null
}

/** Whether an ended import job saved a costume to the vault (import_job's reply: `vault_changed`, `saved`), as
 * Randall's own import does when AssistantPanel reads the vault again. */
export function savedToVault(job) {
  const result = job?.result && typeof job.result === 'object' ? job.result : {}
  return job?.status === 'done'
    && Boolean(result.vault_changed || (result.saved && typeof result.saved === 'object'))
}

/**
 * What the chip shows for the newest import job (`job`, null when there is none), or null for no chip.
 *   seen   the chip saw this job running: one that ended before (an earlier session's) shows nothing
 *   asked  its Cancel was pressed here
 *   gone   the "stopped" note has been up for LINGER_MS
 *   error  the Cancel request failed, in words
 * A running job: { state: 'running' | 'stopping', model, fighter, change, step, canCancel, error, title }; a
 * stopped one: { state: 'stopped', text, title }. `step` is where the import is in a few plain words: the backend's
 * (the record's `step`, from rigswap's stage lines: import_job.STEPS), ASKING while an ask waits on the user's AI,
 * STOPPING once it is told to stop; never the record's `detail`, rigswap's raw line with its clock and file paths
 * (job_status still gives the AI that). `title` is the whole chip in one sentence, for its tooltip. Done and failed
 * jobs show nothing: the vault (and the AI) say how those went.
 */
export function chipView(job, { seen = false, asked = false, gone = false, error = null } = {}) {
  if (!job) return null
  const extra = job.extra && typeof job.extra === 'object' ? job.extra : {}
  const params = job.params && typeof job.params === 'object' ? job.params : {}
  const model = modelName(extra.model) || modelName(fileName(params.source)) || words(params.project) || 'a model'
  const fighter = words(extra.fighter) || words(params.fighter)
  const change = Boolean(words(extra.change) || words(params.change))
  if (ACTIVE.has(job.status)) {
    const stopping = Boolean(asked || extra.stopping || job.detail === STOPPING)
    const step = stopping ? STOPPING : extra.asking ? ASKING : words(extra.step)
    // a failed Cancel, until it is pressed again or the import stops another way (the AI's cancel_import)
    const failed = error && !stopping ? `Could not stop it: ${error}` : null
    const said = `Your AI is ${change ? 'changing' : 'importing'} ${model}${fighter ? ` ${change ? 'on' : 'as'} ${fighter}` : ''}`
    return {
      id: job.id,
      state: stopping ? 'stopping' : 'running',
      model, fighter, change, step,
      canCancel: !stopping,
      error: failed,
      title: [`${said}${step ? `: ${step}` : ''}`, failed].filter(Boolean).join('. '),
    }
  }
  if (job.status === 'cancelled' && seen && !gone) {
    const text = change ? 'Change stopped: nothing saved' : 'Import stopped: nothing saved'
    return { id: job.id, state: 'stopped', text, title: `${text} (${model})`, canCancel: false }
  }
  return null
}

/** The chip's state: the newest import job read through `chipView`, and `cancel`, which stops it. */
export function useMcpImportChip() {
  const job = useLatestJob(KIND)
  const id = job?.id ?? null
  const active = Boolean(job && ACTIVE.has(job.status))
  const [watched, setWatched] = useState(null)
  const [asked, setAsked] = useState(null)
  const [gone, setGone] = useState(null)
  const [failure, setFailure] = useState(null)
  useEffect(() => { if (active) setWatched(id) }, [id, active])
  const view = chipView(job, {
    seen: watched === id, asked: asked === id, gone: gone === id,
    error: failure && failure.id === id ? failure.message : null,
  })
  const stopped = view?.state === 'stopped'
  useEffect(() => {
    if (!stopped) return undefined
    const timer = setTimeout(() => setGone(id), LINGER_MS)
    return () => clearTimeout(timer)
  }, [stopped, id])
  const cancel = useCallback(() => {
    if (!id) return Promise.resolve()
    setAsked(id)
    setFailure(null)
    return Promise.resolve().then(() => cancelJob(id)).catch((err) => {
      setAsked(null)
      setFailure({ id, message: err?.message || 'the request failed' })
    })
  }, [id])
  return { view, cancel }
}

/** Call `onSaved(job)` when an import the user's AI ran ends with a costume saved: the window reads the vault again,
 * as after Randall's own import (AssistantPanel's onRefresh on `vault_changed`). */
export function useMcpImportSaved(onSaved) {
  useJobEnd(KIND, (job) => { if (savedToVault(job)) onSaved(job) })
}

/** Call `onChanged()` when any other tool the user's AI ran over MCP saved to the vault (a Stage Lab or Skin Lab save,
 * a website download, an imported file): the window reads the vault again, as after the same tool in Randall's chat.
 * Before this only model imports did, so a stage the AI saved showed only after a window reload. */
export function useMcpVaultChanged(onChanged, subscribe = subscribeSocket) {
  useEffect(() => subscribe({ [VAULT_EVENT]: () => onChanged() }), [onChanged, subscribe])
}
