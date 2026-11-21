import test from 'node:test'
import assert from 'node:assert/strict'
import { downloadReceiptItems } from './downloadReceipts.js'

test('old mixed batch receipts show every successful download, excluding failures and skips', () => {
  const result = { downloads: [
    { result: { imported_count: 2, imported_items: [{ id: 'a', character: 'Pichu' }, { id: 'b', character: 'Pichu' }] } },
    { result: { imported_count: 4, website_mods: [{ post_id: 1, title: 'Retro Stadium', image: 'stage.png', tags: ['Stage Skin'] }] } },
    { result: { imported_count: 1, website_mods: [{ post_id: 2, title: 'Patch', image: 'patch.png' }] } },
    { result: { imported_count: 0, error: 'Bad archive', website_mods: [{ post_id: 3 }] } },
    { result: { imported_count: 0, skipped_count: 1, website_mods: [{ post_id: 4 }] } },
  ] }
  const cards = downloadReceiptItems(result)
  assert.equal(cards.length, 4)
  assert.equal(cards[2].image, 'stage.png')
  assert.equal(cards[2].count, 4)
  assert.equal(cards[3].image, 'patch.png')
})

test('exact stage cards replace the fallback and current costume assets win over old batch assets', () => {
  const result = { imported_items: [{ id: 'a', character: 'Pichu', image: 'new.png' }], downloads: [
    { result: { imported_count: 2, website_mods: [{ post_id: 1, image: 'post.png' }],
      imported_items: [{ id: 'a', character: 'Pichu', image: 'old.png' }],
      imported_stages: [{ id: 'lake', image: 'lake.png', stage: 'Dreamland', folder: 'dreamland' }] } },
  ] }
  const cards = downloadReceiptItems(result)
  assert.equal(cards.length, 2)
  assert.equal(cards[0].image, 'new.png')
  assert.equal(cards[1].kind, 'stage')
  assert.equal(cards[1].image, 'lake.png')
})
