import assert from 'node:assert/strict'
import test from 'node:test'
import {
  classifyIsoVerification, classifyIsoVerificationFailure, createIsoVerificationGate,
} from './isoVerification.js'

test('only an explicit MD5 mismatch is classified as an invalid ISO', () => {
  assert.deepEqual(classifyIsoVerification({ valid: false, md5: '0123456789abcdef' }), {
    status: 'invalid',
    message: 'Invalid ISO (MD5: 01234567...). Need vanilla Melee 1.02',
  })
  assert.equal(classifyIsoVerification({ valid: true }).status, 'valid')
  assert.throws(() => classifyIsoVerification({}), /incomplete response/)
  assert.throws(() => classifyIsoVerification({ valid: null }), /incomplete response/)
})

test('the backend reason replaces the generic invalid wording', () => {
  const message = 'This is an NKit image: a shrunk dump that Dolphin and Slippi play but Nucleus cannot use.'
  assert.deepEqual(classifyIsoVerification({ valid: false, md5: 'abc', reason: 'nkit', message }), {
    status: 'invalid', message,
  })
})

test('an unreadable ISO shows the backend reason, not a backend outage', () => {
  const error = {
    message: 'Nucleus cannot read this file: Operation not permitted. macOS is blocking Nucleus from this folder.',
    status: 403,
    data: { success: false, reason: 'unreadable' },
  }
  const result = classifyIsoVerificationFailure(error)
  assert.equal(result.status, 'unavailable')
  assert.equal(result.message, error.message)
  assert.doesNotMatch(result.message, /Nucleus is running/)
})

test('HTTP and connection failures are verification unavailable', () => {
  const result = classifyIsoVerificationFailure({ message: 'Backend unreachable', status: 0 })
  assert.equal(result.status, 'unavailable')
  assert.match(result.message, /retry/i)
  assert.doesNotMatch(result.message, /not a vanilla/i)
  const missing = classifyIsoVerificationFailure({ message: 'ISO file not found', status: 404 })
  assert.equal(missing.status, 'unavailable')
  assert.match(missing.message, /choose the file again/i)
})

test('a response for an older path cannot replace the current result', () => {
  const gate = createIsoVerificationGate()
  const oldRequest = gate.begin('old.iso')
  const currentRequest = gate.begin('new.iso')
  assert.equal(gate.isCurrent(oldRequest, 'new.iso'), false)
  assert.equal(gate.isCurrent(currentRequest, 'new.iso'), true)
  gate.invalidate()
  assert.equal(gate.isCurrent(currentRequest, 'new.iso'), false)
})
