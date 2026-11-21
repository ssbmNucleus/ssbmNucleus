/**
 * exportPipeline.js — the export builder's three one-shot pipelines, as data.
 *
 *   iso    : export
 *   patch  : export -> patch      (xdelta patch into the Patches library)
 *   bundle : export -> textures -> package   (texture-pack ISO, HD portraits, .ssbm)
 *
 * Every step is one backend job (core/jobs.py). A run follows only the job its
 * current step started (`run.jobId`), so a job from an earlier run, or one this
 * step did not start, can never advance it or hand it a result.
 */
import { jobOutcome } from '../../shared/jobs/jobOutcome.js'

export const PIPELINES = {
  iso: ['export'],
  patch: ['export', 'patch'],
  bundle: ['export', 'textures', 'package'],
}

// Where each step's result is kept on the run.
const RESULT_KEY = { export: 'exported', patch: 'patch', textures: 'textures', package: 'bundle' }

export function nextStep(action, step) {
  const steps = PIPELINES[action] || []
  const index = steps.indexOf(step)
  return index >= 0 && index + 1 < steps.length ? steps[index + 1] : null
}

/** "Step 2 of 3" for a multi-step action, else null. */
export function stepMeta(action, step) {
  const steps = PIPELINES[action] || []
  return steps.length > 1 ? `Step ${steps.indexOf(step) + 1} of ${steps.length}` : null
}

/**
 * What a job record means for `run` ({ action, step, jobId, ... }):
 *   null                    not this step's job, or it is still running
 *   { fail: message }       the step's job did not finish
 *   { next: run }           start run.step (its jobId is not known yet)
 *   { done: run }           the last step finished
 * The step's result is kept on the run (`exported` also gets the job id, which
 * is the export's artifact id).
 */
export function advance(run, job) {
  if (!run?.jobId || !job || job.id !== run.jobId) return null
  const outcome = jobOutcome(job)
  if (!outcome) return null
  if (!outcome.ok) return { fail: outcome.error }
  const result = run.step === 'export' ? { ...outcome.result, artifactId: job.id } : outcome.result
  const finished = { ...run, jobId: null, [RESULT_KEY[run.step]]: result }
  const step = nextStep(run.action, run.step)
  return step ? { next: { ...finished, step } } : { done: finished }
}


/** A start response belongs only to the exact run that sent it. */
export function acceptStepStart(current, expected, data, idOf = value => value.job_id) {
  if (current !== expected) return null
  const jobId = idOf(data)
  if (!jobId) throw new Error('This step started without a job to follow. Run the export again.')
  return { ...expected, jobId }
}
