import { jobStore, startJobStore, cancelJob, refreshJob } from './jobs'
import { ACTIVE } from './jobStore'
import { api } from '../transport/api'

/** Dismissing a preview must wait until its worker has stopped writing files. */
export function discardPreviews(id, path) {
  startJobStore()
  let finished = false
  let unsubscribe = () => {}
  const removeWhenEnded = () => {
    const record = jobStore.get(id)
    if (finished || !record || ACTIVE.has(record.status)) return
    finished = true
    unsubscribe()
    void api.delete(path).catch(() => {})
  }
  unsubscribe = jobStore.subscribe(removeWhenEnded)
  removeWhenEnded()
  if (!finished) {
    void cancelJob(id).catch(() => {})
    void refreshJob(id).then(removeWhenEnded).catch(() => {})
  }
}
