import test from 'node:test'
import assert from 'node:assert/strict'
import { appControlBlockedFile, explainAppControl } from './appControl.js'

// The exact text bug report ee46f7d3 (0.8.15, Windows 11, Smart App Control on)
// showed on every new project.
const GCILIB = "Failed to create project: Could not load file or assembly '~\\AppData\\Local\\Programs\\SSBM Nucleus\\resources\\utility\\mex\\GCILib.dll'. An Application Control policy has blocked this file. (0x800711C7)"

test('the m-ex create failure names the blocked file', () => {
  assert.deepEqual(appControlBlockedFile(GCILIB), { file: 'GCILib.dll' })
  const message = explainAppControl(GCILIB)
  assert.match(message, /^Windows Smart App Control blocked GCILib\.dll, a file that comes with Nucleus,/)
  assert.match(message, /0x800711C7/)
  assert.match(message, /only runs with Smart App Control turned off/)
  assert.doesNotMatch(message, /update/i, 'no signed update is coming, so none is promised')
  assert.doesNotMatch(message, /AppData/)
})

test('a blocked Python extension and a blocked launch are explained too', () => {
  const python = 'ImportError: DLL load failed while importing _brotli: An Application Control policy has blocked this file.'
  assert.equal(appControlBlockedFile(python).file, '_brotli')
  const launch = '[WinError 4551] An Application Control policy has blocked this file'
  assert.deepEqual(appControlBlockedFile(launch), { file: null })
  assert.match(explainAppControl(launch), /^Windows Smart App Control blocked a file that comes with Nucleus because/)
})

test('every other error passes through unchanged', () => {
  for (const text of ['HTTP 500', 'MEX project not found: x.mexproj', '', undefined, null]) {
    assert.equal(explainAppControl(text), text)
    assert.equal(appControlBlockedFile(text), null)
  }
})
