import { test } from 'node:test'
import assert from 'node:assert/strict'
import { cloudErrorKind, friendlyCloudError } from './cloudErrors.js'

test('wire codes become the kind that picks the fix', () => {
  assert.equal(cloudErrorKind('not_configured', 400), 'not_linked')
  assert.equal(cloudErrorKind('vault-public: HTTP 403 {"error":"membership_required","message":"Join sc00p on Patreon for free"}', 502), 'not_member')
  assert.equal(cloudErrorKind('pledge_required'), 'pledge_required')
  assert.equal(cloudErrorKind('', 402), 'pledge_required')
  assert.equal(cloudErrorKind('invalid_token', 502), 'relink')
  assert.equal(cloudErrorKind('inactive', 502), 'blocked')
})

test('quota, offline and server failures read as plain sentences', () => {
  assert.match(friendlyCloudError('vault-sync: HTTP 429 {"error":"vault upload quota exceeded"}'), /Upload limit reached/)
  assert.match(friendlyCloudError('vault-sync: unreachable (<urlopen error [Errno 11001] getaddrinfo failed>)'), /Can't reach the cloud/)
  assert.match(friendlyCloudError('vault-read: HTTP 503 upstream'), /problem on its end/)
  assert.match(friendlyCloudError('a sync is already running', 409), /already running/)
})

test('no raw plumbing ever reaches the screen', () => {
  for (const raw of ['vault-sync: HTTP 418 {"x":1}', 'PUT returned 500: b\'oops\'', 'snapshot PUT returned 400']) {
    const text = friendlyCloudError(raw)
    assert.doesNotMatch(text, /HTTP|[{}]|PUT returned/, raw)
  }
})

test('the local backend not answering is not blamed on the internet', () => {
  assert.equal(cloudErrorKind('Backend unreachable', 0), 'local')
  assert.doesNotMatch(friendlyCloudError('Backend unreachable', 0), /internet/)
})

test('messages already written for people pass through', () => {
  assert.equal(friendlyCloudError('this replay could not be prepared for sharing', 409), 'this replay could not be prepared for sharing')
  assert.equal(friendlyCloudError('Account changed while sharing. Please try again.', 409), 'Account changed while sharing. Please try again.')
  assert.equal(friendlyCloudError(''), '')
})
