import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  IGNORED_LINK_MESSAGE, LINK_WINDOW_MS, PENDING_LINK_KEY, checkPatreonLink, decidePatreonLink, startPatreonLink,
} from './patreonLinkGuard.js'

function memoryStorage() {
  const data = new Map()
  return {
    getItem: key => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => data.set(key, String(value)),
    removeItem: key => data.delete(key),
    data,
  }
}

const clock = (start = 1_000_000) => {
  let t = start
  return { now: () => t, advance: ms => { t += ms } }
}

test('a link nobody started from this app is refused', async () => {
  const storage = memoryStorage()
  const refused = []
  const taken = await decidePatreonLink({ token: 'attacker' }, { storage, refuse: r => refused.push(r) })
  assert.equal(taken, false)
  assert.deepEqual(refused, ['not_started'])
})

test('the ignored-link alert names the Settings tab that holds the Account card', () => {
  // Account is a card on a tab, not a tab of its own (the alert used to say "Settings > Account").
  const settings = readFileSync(new URL('../../settings/Settings.jsx', import.meta.url), 'utf8')
  const tab = settings.match(/label: '([^']+)', cards: <>(?:(?!label: )[^])*?<AccountSection\b/)?.[1]
  assert.ok(tab, 'no Settings tab lists <AccountSection>')
  assert.ok(IGNORED_LINK_MESSAGE.endsWith(`use Settings > ${tab} > Account.`), IGNORED_LINK_MESSAGE)
})

test('a started link is taken within the window, once, and not after it', async () => {
  const storage = memoryStorage()
  const time = clock()
  startPatreonLink({ storage, now: time.now, newState: () => 's1' })
  time.advance(LINK_WINDOW_MS - 1)
  assert.equal(await decidePatreonLink({ token: 't1' }, { storage, now: time.now }), true)
  assert.equal(storage.data.has(PENDING_LINK_KEY), false)                       // spent
  assert.equal(await decidePatreonLink({ token: 't2' }, { storage, now: time.now }), false)  // no replay
  startPatreonLink({ storage, now: time.now, newState: () => 's2' })
  time.advance(LINK_WINDOW_MS + 1)
  assert.deepEqual(checkPatreonLink({ token: 't3' }, { storage, now: time.now }), { ok: false, reason: 'not_started' })
})

test('a link that carries state must carry one this app made', async () => {
  const storage = memoryStorage()
  const time = clock()
  const state = startPatreonLink({ storage, now: time.now, newState: () => 'nonce-a' })
  assert.equal(state, 'nonce-a')
  assert.deepEqual(checkPatreonLink({ token: 't', state: 'nonce-b' }, { storage, now: time.now }),
    { ok: false, reason: 'state_mismatch' })
  assert.deepEqual(checkPatreonLink({ token: 't', state: 'nonce-a' }, { storage, now: time.now }),
    { ok: true, stateChecked: true })
})

test('replacing a linked account with a different one asks first; the same account does not', async () => {
  const names = { old: 'Alice', relink: 'Alice', other: 'Mallory' }
  const lookupName = async token => names[token] || ''
  const asked = []
  const confirm = async question => { asked.push(question); return false }
  for (const [token, expected] of [['relink', true], ['other', false]]) {
    const storage = memoryStorage()
    startPatreonLink({ storage })
    const taken = await decidePatreonLink({ token, name: 'shown' }, { storage, currentToken: 'old', lookupName, confirm })
    assert.equal(taken, expected, token)
  }
  assert.deepEqual(asked, [{ oldName: 'Alice', newName: 'Mallory' }])
  // names the website cannot tell (offline): ask, with the name the link shows
  const storage = memoryStorage()
  startPatreonLink({ storage })
  const yes = await decidePatreonLink({ token: 'x', name: 'Shown Name' }, {
    storage, currentToken: 'old', lookupName: async () => { throw new Error('offline') },
    confirm: async question => { asked.push(question); return true },
  })
  assert.equal(yes, true)
  assert.deepEqual(asked.at(-1), { oldName: '', newName: 'Shown Name' })
  // no account linked yet: nothing to replace, no question
  const fresh = memoryStorage()
  startPatreonLink({ storage: fresh })
  assert.equal(await decidePatreonLink({ token: 'first' }, { storage: fresh, confirm: () => assert.fail('asked') }), true)
})
