import { useState, useRef } from 'react'
import { api } from '../../shared/transport/api'
import { useJob } from '../../shared/jobs/useJobs'
import { jobOutcome, jobPercent } from '../../shared/jobs/jobOutcome'
import { shelfDoneText, startShelfAdd } from '../../shared/jobs/shelfAdd'
import { appConfirm } from '../../shared/ui/appDialogs'

/**
 * useVaultShelfAdd - "Add to Play" for a Vault patch or bundle.
 *
 * POST /api/play/shelf/add {patchId | bundleId} starts a `shelf_add` job (play/adding.py):
 * the backend builds the patch onto the user's own Melee disc into a new shelf entry, with
 * the item's name, description and picture (and a bundle's HD textures for Dolphin). The
 * entry is the shelf's own afterwards. The overlay follows that job's record.
 *
 * When an added game already has that name, the person is asked whether to replace it
 * (shared/jobs/shelfAdd.js); keeping it ends the attempt quietly.
 */
export function addRequest(kind, id) {
  return kind === 'bundle' ? { bundleId: id } : { patchId: id }
}

export function useVaultShelfAdd() {
  // { id: the bundle or patch, name, jobId, error: the request's own failure }
  const [adding, setAdding] = useState(null)
  const addingRef = useRef(null)
  const job = useJob(adding?.jobId || null)
  const outcome = jobOutcome(job)

  const setCurrent = (next) => {
    addingRef.current = next
    setAdding(next)
  }

  const startAdd = async (kind, item) => {
    const attempt = { id: item.id, name: item.name, jobId: null, error: null }
    setCurrent(attempt)
    try {
      const data = await startShelfAdd(addRequest(kind, item.id), { post: api.post, confirm: appConfirm })
      if (addingRef.current === attempt) setCurrent({ ...attempt, jobId: data.job_id })
    } catch (err) {
      if (addingRef.current !== attempt) return
      if (err.kept) {
        setCurrent(null)
        return
      }
      setCurrent({ ...attempt, error: err.data ? (err.message || 'Could not add it to Unlocked') : `Add to Unlocked: ${err.message}` })
    }
  }

  return {
    addingId: adding?.id ?? null,
    addPercent: jobPercent(job) ?? 0,
    addMessage: job?.detail || 'Starting...',
    addError: adding?.error || (outcome && !outcome.ok ? outcome.error : null),
    addDone: Boolean(outcome?.ok),
    addDoneText: outcome?.ok ? shelfDoneText(outcome.result, adding?.name || 'It') : null,
    handleAddPatchToPlay: (patch) => startAdd('patch', patch),
    handleAddBundleToPlay: (bundle) => startAdd('bundle', bundle),
    dismissAdd: () => setCurrent(null),
  }
}
