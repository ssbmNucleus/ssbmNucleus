import test from 'node:test'
import assert from 'node:assert/strict'
import { confirmImportLink, importLinkQuestion } from './importLinkPrompt.js'

test('the question names the host the file comes from, and warns when it is not the Nucleus site', () => {
  const own = importLinkQuestion({ url: 'https://ssbmnucleus.net/files/fox.zip', title: 'Blue Fox' })
  assert.equal(own.host, 'ssbmnucleus.net')
  assert.match(own.message, /"Blue Fox" from the SSBM Nucleus website \(ssbmnucleus\.net\)/)
  assert.doesNotMatch(own.message, /is not the SSBM Nucleus website/)
  const other = importLinkQuestion({ url: 'https://evil.example:8443/x.zip', name: 'x.zip' })
  assert.equal(other.host, 'evil.example:8443')
  assert.match(other.message, /from evil\.example:8443 into your vault\. evil\.example:8443 is not the SSBM Nucleus website/)
  assert.equal(importLinkQuestion({ url: 'not a url' }), null)
  assert.match(importLinkQuestion({ url: 'https://ssbmnucleus.net.evil.example/a' }).message, /is not the SSBM/)
})

test('nothing is imported unless the person says yes', async () => {
  const shown = []
  const yes = async (message, options) => { shown.push([message, options]); return true }
  assert.equal(await confirmImportLink({ url: 'https://ssbmnucleus.net/a.zip' }, yes), true)
  assert.equal(shown[0][1].confirmText, 'Import')
  assert.equal(await confirmImportLink({ url: 'https://ssbmnucleus.net/a.zip' }, async () => false), false)
  assert.equal(await confirmImportLink({ url: 'https://ssbmnucleus.net/a.zip' }, async () => { throw new Error('no host') }), false)
  assert.equal(await confirmImportLink({ url: '' }, yes), false)
  assert.equal(shown.length, 1)
})
