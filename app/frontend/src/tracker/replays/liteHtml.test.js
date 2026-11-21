// Watch Lite paints replay text into innerHTML; a crafted .slp tag must come out as text.
import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import { esc, urlId } from './liteHtml.js'

describe('Watch Lite HTML escaping', () => {
  it('turns a crafted player tag into text', () => {
    const html = `<b>${esc('<svg/onload=eval(c.innerText)>')}</b>`
    assert.equal(html, '<b>&lt;svg/onload=eval(c.innerText)&gt;</b>')
  })

  it('escapes quotes and ampersands, and empty values become empty text', () => {
    assert.equal(esc(`a&b "c" 'd'`), 'a&amp;b &quot;c&quot; &#39;d&#39;')
    assert.equal(esc(undefined), '')
    assert.equal(esc(12), '12')
  })

  it('keeps URL ids inside the attribute', () => {
    assert.equal(urlId('9" onerror="x'), '9%22%20onerror%3D%22x')
    assert.equal(urlId(undefined), '0')
  })
})
