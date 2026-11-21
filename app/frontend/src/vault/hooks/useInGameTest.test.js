import test from 'node:test'
import assert from 'node:assert/strict'
import { loadModule, hookHarness } from '../../../../../tests/frontend/hookHarness.mjs'
import { initialTestState } from './inGameSession.js'

test('the in-game hook starts the shared store before mounting and passes its exact job operations', () => {
  const h = hookHarness(), calls = [], starts = []; let sessionOptions
  const store = { get() {}, subscribe() {} }, refresh = () => {}
  const { useInGameTest } = loadModule(new URL('./useInGameTest.js', import.meta.url), {
    react: h.react, '../../shared/transport/socket': { channel() {} }, '../../shared/transport/api': { api: {} },
    '../../shared/audio/sounds': { playSound() {} },
    '../../shared/jobs/jobs': { jobStore: store, refreshJob: refresh, startJobStore: () => calls.push('store') },
    './inGameSession': { initialTestState, createInGameSession: options => {
      sessionOptions = options
      return { mount: () => calls.push('mount'), unmount: () => calls.push('unmount'),
        start: (...args) => starts.push(args), stop() {}, reset() {} }
    } },
  }, { localStorage: { getItem: key => key }, sessionStorage: {} })
  const hook = h.render(() => useInGameTest())
  assert.deepEqual(calls, ['store', 'mount'])
  assert.deepEqual(sessionOptions.jobs, { get: store.get, subscribe: store.subscribe, refresh })
  hook.captureStageScreenshot({ stageCode: 'GrOp', variantId: 'blue' })
  hook.capturePauseScreenshot({ modId: 'm', name: 'Blue Fox' })
  assert.equal(starts[0][2].interactive, false); assert.equal(starts[1][2].interactive, false)
  assert.equal(starts[0][2].result({ screenshot: 'stage.png' }).screenshot, 'stage.png')
  assert.match(starts[1][2].result({ modId: 'm' }).reason, /Blue Fox/)
  h.unmount(); assert.deepEqual(calls, ['store', 'mount', 'unmount'])
})
