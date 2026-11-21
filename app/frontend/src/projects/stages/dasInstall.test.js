import test from 'node:test'
import assert from 'node:assert/strict'

import { dasInstallFailureNotice, dasInstallNotice } from './dasInstall.js'

test('a complete install has nothing to say', () => {
  assert.equal(dasInstallNotice({ success: true, message: 'DAS framework installed successfully' }), null)
  assert.equal(dasInstallNotice({ success: true, warning: '  ' }), null)
  assert.equal(dasInstallNotice(undefined), null)
})

test('an install warning reaches the user word for word', () => {
  const warning = 'No alternate-stage loader for Pokemon Stadium: it is made from the stage file in your own '
    + 'Melee 1.02 ISO. Set your vanilla ISO in Settings and install again.'
  const notice = dasInstallNotice({ success: true, warning })
  assert.match(notice, /not for every stage/)
  assert.ok(notice.endsWith(warning))
})

test('a failed install says what failed and where to retry', () => {
  const notice = dasInstallFailureNotice(new Error('DAS framework source not found'))
  assert.match(notice, /could not be set up: DAS framework source not found/)
  assert.match(notice, /Stages tab/)
  assert.match(dasInstallFailureNotice(null), /unknown error/)
})
