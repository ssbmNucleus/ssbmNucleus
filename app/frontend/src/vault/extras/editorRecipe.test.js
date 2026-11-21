import test from 'node:test'
import assert from 'node:assert/strict'
import { readEditorColors, serializeEditorColors, displayColor, loadCurrentTextureColor, rgbWithAlpha } from './editorRecipe.js'

test('Side B RGB edits and presets preserve each channel alpha including transparent', () => {
  assert.deepEqual(['12345600', '12345640', '123456FF'].map(value => rgbWithAlpha('#aa33cc', value)),
    ['AA33CC00', 'AA33CC40', 'AA33CCFF'])
  assert.equal(rgbWithAlpha('#112233'), '112233FF')
})

test('legacy or absent modifications reset every channel instead of reusing a prior recipe', () => {
  const defaults = { color1: 'FF004C', color2: 'B20000' }
  assert.deepEqual(readEditorColors({ modifications: { color1: { color: '000000' } } }, defaults),
    { color1: '000000', color2: 'B20000' })
  assert.deepEqual(readEditorColors({ name: 'Legacy DAT' }, defaults), defaults)
  assert.deepEqual(readEditorColors(null, defaults), defaults)
})

test('UpB edits retain unexposed imported layers and update every loaded channel', () => {
  const saved = { tip: { color: 'FE60' }, dots: { color: '112233' },
    flare: { color: '445566' }, customLayer: { color: '778899' }, fire: { hue: 0 } }
  const colors = readEditorColors({ modifications: saved },
    { tip: 'FE60', body: 'FFFFFF', dots: 'FF290C', flare: 'FFE54C' })
  colors.body = '00FF00'
  const result = serializeEditorColors(colors, saved)
  assert.deepEqual(result.dots, saved.dots)
  assert.deepEqual(result.flare, saved.flare)
  assert.deepEqual(result.customLayer, saved.customLayer)
  assert.deepEqual(result.body, { color: '00FF00' })
  assert.deepEqual(saved.fire, { hue: 0 })
})

test('Shine save includes explicit vanilla flash and sparkle restoration', () => {
  assert.deepEqual(serializeEditorColors({ primary: '621F', secondary: 'AB9F',
    flash1: '63FF', flash2: 'FFFF', sparkles: 'FFFFFF' }), {
    primary: { color: '621F' }, secondary: { color: 'AB9F' },
    flash1: { color: '63FF' }, flash2: { color: 'FFFF' }, sparkles: { color: 'FFFFFF' },
  })
})

test('representative swatches reflect the latest supplied recipe color', () => {
  assert.equal(displayColor('00ff00'), '#00FF00')
  assert.equal(displayColor('#0000ff'), '#0000FF')
  assert.equal(displayColor(undefined), '#FF6600')
})

const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const flush = () => new Promise(resolve => setImmediate(resolve))

test('texture requests from closed or previous editors cannot change color or loading state', async () => {
  const request = deferred()
  const events = []
  const cancel = loadCurrentTextureColor(request.promise, {
    onValue: value => events.push(value), onSettled: () => events.push('settled'),
  })
  cancel()
  request.resolve({ color: 'FF0000' })
  await flush()
  assert.deepEqual(events, [])
})

test('late texture responses cannot overwrite a color the user just picked', async () => {
  const request = deferred()
  let revision = 0
  const pendingRevision = revision
  let color = 'FF3300'
  loadCurrentTextureColor(request.promise, {
    isCurrent: () => pendingRevision === revision,
    onValue: value => { color = value.color },
  })
  revision += 1
  color = '0000FF'
  request.resolve({ color: 'FF0000' })
  await flush()
  assert.equal(color, '0000FF')
})

test('current texture requests settle successfully or report failure once', async () => {
  const events = []
  loadCurrentTextureColor(Promise.resolve({ color: '112233' }), {
    onValue: value => events.push(value.color), onSettled: () => events.push('settled'),
  })
  await flush()
  assert.deepEqual(events, ['112233', 'settled'])
  loadCurrentTextureColor(Promise.reject(new Error('unavailable')), {
    onValue: () => assert.fail('unexpected texture'),
    onError: error => events.push(error.message), onSettled: () => events.push('settled'),
  })
  await flush()
  assert.deepEqual(events.slice(2), ['unavailable', 'settled'])
})
