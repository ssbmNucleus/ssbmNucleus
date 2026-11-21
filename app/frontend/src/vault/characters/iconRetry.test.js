import test from 'node:test'
import assert from 'node:assert/strict'
import { EMPTY, iconFailed, iconSrc, retryIcons } from './iconRetry.js'

const URL = 'http://127.0.0.1:5000/vanilla/Fox/css_icon.png'

test('a failed icon shows the letter until the vault is read again, then is tried once more', () => {
  // Before setup: no vanilla icons yet, so the card shows its letter (it used to stay so until a remount).
  assert.equal(iconSrc(EMPTY, 'Fox', URL), URL)
  let state = iconFailed(EMPTY, 'Fox')
  assert.equal(iconSrc(state, 'Fox', URL), null)
  assert.equal(iconSrc(state, 'Marth', URL.replace('Fox', 'Marth')), URL.replace('Fox', 'Marth'))
  assert.equal(iconFailed(state, 'Fox'), state, 'failing again changes nothing')
  // Setup finished (or an import saved): the metadata is read again and the grid retries, past a cached failure.
  state = retryIcons(state)
  assert.equal(iconSrc(state, 'Fox', URL), `${URL}?retry=1`)
  assert.equal(iconSrc(state, 'Marth', 'm.png?x=1'), 'm.png?x=1', 'an icon that loaded is never asked again')
  // Still missing: the letter again, and the next read tries a second time.
  state = retryIcons(iconFailed(state, 'Fox'))
  assert.equal(iconSrc(state, 'Fox', URL), `${URL}?retry=2`)
  assert.equal(iconSrc(retryIcons(iconFailed(EMPTY, 'A')), 'A', 'a.png?v=3'), 'a.png?v=3&retry=1')
})

test('a vault read with nothing failed is the same state, so the grid does not render again', () => {
  assert.equal(retryIcons(EMPTY), EMPTY)
  const state = retryIcons(iconFailed(EMPTY, 'Fox'))
  assert.equal(retryIcons(state), state)
})
