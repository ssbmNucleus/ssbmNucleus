import test from 'node:test'
import assert from 'node:assert/strict'
import { collectWebsiteCards } from './websiteCards.js'

test('live vault ownership overrides chat history and works in fresh searches', () => {
  const messages = [{ tools: [{ id: 'search', result: { website_mods: [{ post_id: 1 }, { post_id: 2 }] } }] }]
  assert.equal(collectWebsiteCards(messages, { 1: true }).get(1).inVault, true)
  messages[0].tools.push({ id: 'old', name: 'download_website_mod', result: { website_mods: [{ post_id: 2 }], imported_count: 1 } })
  assert.equal(collectWebsiteCards(messages, { 2: false }).get(2).inVault, false)
  messages[0].tools[0].result.website_mods[0].in_vault = true
  assert.equal(collectWebsiteCards(messages).get(1).inVault, true)
})

test('bulk progress updates each original card independently', () => {
  const mods = [{ post_id: 1 }, { post_id: 2 }, { post_id: 3 }]
  const messages = [{ tools: [{ id: 'search', result: { website_mods: mods } }] },
    { tools: [{ id: 'batch', name: 'download_website_mods', status: 'running', result: {
      website_mods: mods, imported_count: 1, downloads: [
        { post_id: 1, status: 'done', result: { imported_count: 1 } },
        { post_id: 2, status: 'error', result: { error: 'Changed' } },
        { post_id: 3, status: 'queued' },
      ],
    } }] }]
  const cards = collectWebsiteCards(messages)
  assert.equal(cards.size, 3)
  assert.equal(cards.get(1).inVault, true)
  assert.equal(Boolean(cards.get(2).inVault), false)
  assert.equal(Boolean(cards.get(3).inVault), false)
  assert.equal(cards.get(2).download.result.error, 'Changed')
  assert.equal(cards.get(3).download.status, 'queued')
  for (const card of cards.values()) assert.equal(card.owner, 'search')
})

test('search, inspection and download update the first card through approval and completion', () => {
  const mod = { post_id: 123, title: 'Kermit', like_count: 2 }
  const messages = [{ tools: [{ id: 'search', result: { website_mods: [mod] } }] },
    { tools: [{ id: 'inspect', result: { website_mods: [{ ...mod, images: ['gallery.png'] }] } }] },
    { tools: [{ id: 'download', name: 'download_website_mod', approval: { status: 'pending', website_mods: [mod] } }] }]
  let cards = collectWebsiteCards(messages)
  assert.equal(cards.size, 1)
  assert.equal(cards.get(123).owner, 'search')
  assert.deepEqual(cards.get(123).mod.images, ['gallery.png'])
  assert.equal(cards.get(123).download.approval.status, 'pending')
  messages.at(-1).tools[0].result = { imported_count: 1, website_mods: [mod] }
  cards = collectWebsiteCards(messages)
  assert.equal(cards.size, 1)
  assert.equal(cards.get(123).inVault, true)
})

test('failed or declined downloads do not claim ownership; later likes preserve ownership', () => {
  const mod = { post_id: 1 }
  const messages = [{ tools: [{ id: 'download', name: 'download_website_mod',
    result: { website_mods: [mod], error: 'Failed', imported_count: 0 } }] }]
  assert.equal(Boolean(collectWebsiteCards(messages).get(1).inVault), false)
  messages[0].tools[0].result = { website_mods: [mod], skipped_count: 1 }
  messages.push({ tools: [{ id: 'like', name: 'set_website_mod_like', result: { website_mods: [{ ...mod, like_count: 8 }] } }] })
  const card = collectWebsiteCards(messages).get(1)
  assert.equal(card.inVault, true)
  assert.equal(card.mod.like_count, 8)
  assert.equal(card.owner, 'download')
})
