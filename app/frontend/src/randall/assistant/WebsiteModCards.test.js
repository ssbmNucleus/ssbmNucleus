// A broadened search must never look like an exact one.
//
// The fixtures are what `_fallback_search` produces in
// backend/randall/website/website.py (see tests/backend/test_assistant_website_search.py):
// `relaxed` carries the search that actually matched and the filters that were
// dropped, `original_filters` carries what the user asked for, and every card
// from the weaker search carries `alternative_match`.
import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'

const realRequire = createRequire(import.meta.url)
const source = readFileSync(new URL('./WebsiteModCards.jsx', import.meta.url), 'utf8')
const compiled = transformSync(source, { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
const module = { exports: {} }
new Function('require', 'module', 'exports', compiled)(name => {
  if (name === '../../shared/transport/api') return { api: { post: async () => ({}) } }
  if (name === '../../shared/account/account') return { getAccessToken: async () => null }
  if (name === '@formkit/auto-animate/react') return { useAutoAnimate: () => [null] }
  if (name === './DownloadProgress') return { DownloadActivity: () => null }
  return realRequire(name)
}, module, module.exports)

const { default: WebsiteModCards, relaxedLine, searchPhrase } = module.exports
const card = extra => ({ mod: { post_id: 1, title: 'Stage Select Screen', author: 'Artist',
  image: 'https://media.ssbmnucleus.net/a.png', like_count: 2, download_count: 3, ...extra } })
const render = props => renderToStaticMarkup(React.createElement(WebsiteModCards, props))

// The tag search `css background` found nothing, so the same words were tried
// as free text and three mods came back.
const broadened = {
  website_total: 3,
  filters: { query: 'css background', tags: [], character: '', author: '' },
  original_filters: { query: '', tags: ['css', 'background'], character: '', author: '' },
  relaxed: { matched: "the words 'css background' as text", dropped_filters: [],
    requested: { query: '', tags: ['css', 'background'], character: '', author: '' } },
}

test('a broadened search is qualified in one line above the cards', () => {
  const line = relaxedLine(broadened)
  assert.equal(line, "Showing 'css background' instead of the tags css and background; "
    + 'nothing matched the exact words.')
  const html = render({ cards: [card({ alternative_match: "the words 'css background' as text" })], search: broadened })
  assert.match(html, /assistant-search-relaxed/)
  assert.ok(html.indexOf(line) < html.indexOf('assistant-website-mods'), 'the qualification comes before the cards')
})

test('the words that were dropped to find these mods are named', () => {
  const line = relaxedLine({
    filters: { query: 'hat', tags: [], character: '', author: '' },
    original_filters: { query: 'hat', tags: [], character: 'Fox', author: 'Artist' },
    relaxed: { matched: "the words 'hat' as text", dropped_filters: ['character', 'author'] },
  })
  assert.equal(line, "Showing 'hat' instead of 'hat', the character Fox and the author Artist; "
    + 'nothing matched the exact words. The character and author filters were dropped to find these.')
})

test('cards from a broadened search are tagged as alternatives', () => {
  const html = render({
    cards: [card({ alternative_match: "the words 'css background' as text" }),
      card({ post_id: 2, title: 'Another one', alternative_match: "the words 'css background' as text" })],
    search: broadened,
  })
  assert.equal((html.match(/assistant-mod-alternative/g) || []).length, 2)
  assert.equal((html.match(/Alternative match/g) || []).length, 2)
  assert.match(html, /Found by searching the words &#x27;css background&#x27; as text, not the words you used\./)
})

test('an exact search says nothing extra, and its cards carry no tag', () => {
  assert.equal(relaxedLine({ website_total: 4, filters: { query: 'marth' } }), null)
  // An empty fallback result reports itself through the no-match copy instead.
  assert.equal(relaxedLine({ website_total: 0, relaxed: { matched: null, dropped_filters: [] } }), null)
  const html = render({ cards: [card()], search: { website_total: 1, filters: { query: 'marth' } } })
  assert.doesNotMatch(html, /assistant-search-relaxed/)
  assert.doesNotMatch(html, /Alternative match/)
})

test('a search is said in the words the user typed, not in filter names', () => {
  assert.equal(searchPhrase({ query: 'sss background' }), "'sss background'")
  assert.equal(searchPhrase({ tags: ['Stage Skin'] }), 'the tag Stage Skin')
  assert.equal(searchPhrase({ query: 'hat', character: 'Fox' }), "'hat' and the character Fox")
  assert.equal(searchPhrase({}), 'what you asked for')
})

test('a card credits the creator, and the uploader when it differs', () => {
  const reupload = render({ cards: [card({ author: 'SSBM Textures', creator: 'mcromich',
    credit: 'mcromich (via SSBM Textures)' })], search: { website_total: 1 } })
  assert.match(reupload, /by mcromich \(via SSBM Textures\)/)
  // A card saved before credits existed still shows its author.
  assert.match(render({ cards: [card()], search: { website_total: 1 } }), /by Artist/)
})
