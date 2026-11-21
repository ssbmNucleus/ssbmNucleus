import test from 'node:test'
import assert from 'node:assert/strict'
import { advance, nextStep, stepMeta } from './exportPipeline.js'

const done = (id, result) => ({ id, status: 'done', result })

test('each action runs its own steps in order', () => {
  assert.equal(nextStep('iso', 'export'), null)
  assert.equal(nextStep('patch', 'export'), 'patch')
  assert.equal(nextStep('bundle', 'export'), 'textures')
  assert.equal(nextStep('bundle', 'textures'), 'package')
  assert.equal(nextStep('bundle', 'package'), null)
  assert.equal(stepMeta('iso', 'export'), null)
  assert.equal(stepMeta('bundle', 'textures'), 'Step 2 of 3')
})

test('a finished export moves the run on with its artifact', () => {
  const run = { action: 'bundle', step: 'export', jobId: 'build_b' }
  const { next } = advance(run, done('build_b', { path: 'b.iso', buildId: 'build_b' }))
  assert.equal(next.step, 'textures')
  assert.equal(next.jobId, null)
  assert.deepEqual(next.exported, { path: 'b.iso', buildId: 'build_b', artifactId: 'build_b' })
})

test('a job the current step did not start never advances the run', () => {
  // F-G-3: an earlier run's texture job finishing late is not this run's.
  const run = { action: 'bundle', step: 'textures', jobId: 'tex-b', exported: { path: 'b.iso' } }
  assert.equal(advance(run, done('tex-a', { texturePackPath: 'A' })), null)
  // nor does anything arrive while the step's own job id is not known yet
  assert.equal(advance({ ...run, jobId: null }, done('tex-a', {})), null)
  const { next } = advance(run, done('tex-b', { texturePackPath: 'B' }))
  assert.equal(next.step, 'package')
  assert.equal(next.textures.texturePackPath, 'B')
  assert.equal(next.exported.path, 'b.iso')
})

test('a running job waits and a failed one fails the run with its error', () => {
  const run = { action: 'iso', step: 'export', jobId: 'build_a' }
  assert.equal(advance(run, { id: 'build_a', status: 'running', progress: 0.4 }), null)
  // F-G-1: a failed export ends the run instead of leaving it working
  assert.deepEqual(advance(run, { id: 'build_a', status: 'failed', error: 'MexCLI failed' }),
    { fail: 'MexCLI failed' })
})

test('the last step finishes the run with every result kept', () => {
  const run = { action: 'patch', step: 'patch', jobId: 'create-1', exported: { path: 'a.iso' } }
  const { done: finished } = advance(run, done('create-1', { patch_id: 'p1', size_mb: 3 }))
  assert.equal(finished.patch.patch_id, 'p1')
  assert.equal(finished.exported.path, 'a.iso')
  assert.equal(finished.jobId, null)
})


test('all three pipelines retain their own results and cannot advance twice from one terminal record', () => {
  for (const [action, steps] of [['iso', ['export']], ['patch', ['export', 'patch']], ['bundle', ['export', 'textures', 'package']]]) {
    let run = { action, step: 'export', jobId: 'export-id', filename: 'chosen.iso' }
    for (const [index, step] of steps.entries()) {
      const event = done(`${step}-id`, { path: `${step}.out`, artifactId: 'wrong' })
      const before = structuredClone(run)
      const decision = advance(run, event)
      assert.deepEqual(run, before)
      assert.equal(Boolean(decision.done), index === steps.length - 1)
      run = decision.next || decision.done
      assert.equal(run.filename, 'chosen.iso')
      assert.equal(run.exported.artifactId, 'export-id')
      assert.equal(advance(run, event), null)
      if (decision.next) run = { ...run, jobId: `${run.step}-id` }
    }
    if (action === 'bundle') assert.equal(run.bundle.path, 'package.out')
  }
})

test('a cancelled or interrupted step never launches the next job or accepts an earlier result', () => {
  const run = { action: 'bundle', step: 'textures', jobId: 'textures', exported: { path: 'saved.iso' } }
  for (const status of ['queued', 'running']) assert.equal(advance(run, { id: 'textures', status }), null)
  for (const status of ['failed', 'cancelled', 'interrupted']) {
    assert.ok(advance(run, { id: 'textures', status }).fail)
    assert.equal(advance(run, { id: 'old', status }), null)
  }
  assert.equal(advance(null, done('textures', {})), null)
  assert.equal(advance(run, null), null)
  assert.equal(nextStep('invalid', 'export'), null)
  assert.equal(nextStep('bundle', 'invalid'), null)
})


test('a late export start cannot revive a closed or replaced run; missing ids fail explicitly', async () => {
  const { acceptStepStart } = await import('./exportPipeline.js')
  const run = { action: 'iso', step: 'export', jobId: null, filename: 'named.iso' }
  assert.equal(acceptStepStart(null, run, null), null)
  assert.equal(acceptStepStart({ ...run }, run, null), null)
  assert.throws(() => acceptStepStart(run, run, {}), /without a job to follow/)
  assert.deepEqual(acceptStepStart(run, run, { artifactId: 'export' }, data => data.artifactId), { ...run, jobId: 'export' })
  assert.deepEqual(acceptStepStart(run, run, { job_id: 'step' }), { ...run, jobId: 'step' })
  assert.equal(run.jobId, null)
})
