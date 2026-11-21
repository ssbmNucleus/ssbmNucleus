import assert from 'node:assert/strict'
import * as scanRefresh from '../replays/scanRefresh.js'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'

// Compile only this component in memory, without starting/building the app.
const source = readFileSync(new URL('./ComboLibraryStatus.jsx', import.meta.url), 'utf8')
const compiled = transformSync(source, { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
const module = { exports: {} }
new Function('require', 'module', 'exports', compiled)(createRequire(import.meta.url), module, module.exports)
const Status = module.exports.default
const render = props => renderToStaticMarkup(React.createElement(Status, props))

test('library header preserves its row and hides the scan action only when complete', () => {
  const identity = { index: { parsed: 20 } }
  const inputs = [
    {},
    { identity, status: { counts: { combos: 100, games_pending: 0, games_scanned: 20 } } },
    { identity, status: { counts: { combos: 100, games_pending: 3, games_scanned: 17 } } },
    { identity, status: { scan: { running: true, done: 5, total: 20, found: 18 } } },
  ]
  for (const input of inputs) {
    const html = render(input)
    assert.equal((html.match(/class="combos-library-status"/g) || []).length, 1)
    assert.equal((html.match(/<button/g) || []).length, input === inputs[1] ? 0 : 1)
    assert.match(html, /class="combos-library-progress"/)
  }
  assert.match(render(inputs[1]), /Analysis complete/)
  assert.doesNotMatch(render(inputs[1]), /Analyze now/)
  assert.match(render(inputs[2]), /Analyze now/)
  assert.match(render(inputs[0]), /Loading library details/)
  assert.match(render(inputs[0]), /disabled=""/)
  assert.match(render(inputs[3]), /18 combos with 4\+ moves found/)
  assert.match(render(inputs[3]), /width:25%/)
})

test('empty and failed details remain actionable without replacing the controls header', () => {
  const empty = { combos: 0, games_pending: 20, games_scanned: 0 }
  assert.match(render({ identity: { index: { parsed: 20 } }, status: { counts: empty } }), /Scan combos/)
  const noReplays = render({ identity: { index: { parsed: 0 } }, status: { counts: empty } })
  assert.match(noReplays, /Replays tab first/)
  assert.match(noReplays, /disabled=""/)
  assert.match(render({ error: true }), /Retry details/)
  const failed = render({ identity: { index: { parsed: 20 } },
    status: { counts: { combos: 0, games_pending: 3, games_scanned: 17 }, scan: { error: 'database is locked' } } })
  assert.match(failed, /Analysis failed: database is locked/)
  assert.match(failed, /Analyze now/)
})

function isolatedComponent(name, dependencies) {
  const text = readFileSync(new URL(name, import.meta.url), 'utf8')
  const code = transformSync(text, { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
  const output = { exports: {} }
  const require = createRequire(import.meta.url)
  const load = id => id.startsWith('react') ? require(id)
    : id.endsWith('.css') ? {} : dependencies[id] || (() => null)
  new Function('require', 'module', 'exports', code)(load, output, output.exports)
  return output.exports.default
}

test('real Combos page first render includes direction, metadata filters and stable status row', () => {
  const Page = isolatedComponent('./CombosPage.jsx', {
    './ComboLibraryStatus': Status,
    '../../shared/config/config': { BACKEND_URL: 'http://synthetic.invalid' },
    '../../shared/transport/api': { api: { request: () => { throw Error('No requests in server render') } } },
    './comboPageRequest': { createComboPageRequest: () => ({ cancel() {} }) },
    '../replays/scanRefresh': scanRefresh,
    '../../shared/jobs/useJobs': { useLatestJob: () => null, useJobEnd: () => {}, refreshJob: async () => null },
    '../../shared/jobs/passView': { passView: () => ({ running: false, done: 0, total: 0, error: null }) },
    '../../shared/ui/IconSelect': props => React.createElement('button', { disabled: props.disabled }, props.placeholder),
    '../../shared/ui/FilterSelect': props => React.createElement('button', null, props.anyLabel),
  })
  const html = renderToStaticMarkup(React.createElement(Page))
  assert.match(html, /My combos/)
  assert.match(html, /On me/)
  assert.match(html, /Me: any character/)
  assert.match(html, /Vs: any character/)
  assert.match(html, /Any stage/)
  assert.match(html, /Loading library details/)
  assert.equal((html.match(/disabled=""/g) || []).length, 7) // Status, two directions, three facets, Play.
})

test('unshareable combos retain an explicit disabled action, eligible ones keep sharing', () => {
  const Share = isolatedComponent('../share/ShareLinkButton.jsx', {
    '../../shared/config/features': {}, '../replays/litePaint': { P: [] },
  })
  const reason = 'Public combo links require at least 4 moves.'
  const disabled = renderToStaticMarkup(React.createElement(Share, { gameId: 1, comboId: 2, disabledReason: reason }))
  assert.match(disabled, /disabled=""/)
  assert.match(disabled, /aria-label="Public combo links require at least 4 moves/)
  const enabled = renderToStaticMarkup(React.createElement(Share, { gameId: 1, comboId: 2 }))
  assert.doesNotMatch(enabled, /disabled=""/)
  assert.match(enabled, /Share this combo/)
})

test('lazy module fallback reserves every header control before the page loads', () => {
  const Loading = isolatedComponent('./ComboLoading.jsx', { './ComboLibraryStatus': Status })
  const html = renderToStaticMarkup(React.createElement(Loading))
  for (const text of ['My combos', 'On me', 'Me: any character', 'Vs: any character',
    'Any stage', '4+ moves', '50%+', 'Any start %', 'Combos &amp; strings', 'Kills only',
    'Recent', 'Damage', 'Moves', 'Start %', 'Length', 'Play']) assert.ok(html.includes(text), text)
  assert.match(html, /class="combos-library-status"/)
  assert.match(html, /class="combos-filters"/)
  assert.match(html, /aria-busy="true"/)
})
