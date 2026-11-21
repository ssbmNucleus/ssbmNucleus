import test from 'node:test'
import assert from 'node:assert/strict'

const withStubs = async (fn) => {
  const previous = {
    window: globalThis.window, document: globalThis.document,
    fetch: globalThis.fetch, URL: globalThis.URL,
  }
  const links = []
  const revoked = []
  globalThis.window = { electron: { backendPort: 51234, backendToken: 'image-test-token' }, location: { search: '' } }
  globalThis.document = {
    createElement: () => ({ click() { this.clicked = true }, remove() { this.removed = true } }),
    body: { appendChild(link) { links.push(link) } },
  }
  const RealURL = previous.URL
  globalThis.URL = class extends RealURL {
    static createObjectURL() { return 'blob:stub' }
    static revokeObjectURL(url) { revoked.push(url) }
  }
  try {
    await fn({ links, revoked })
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete globalThis[key]
      else globalThis[key] = value
    }
  }
}

test('filenames are sanitised and keep the source extension', async () => {
  await withStubs(async () => {
    const { imageFilename, safeFilePart, imageExtension } = await import('./imageDownload.js')
    assert.equal(imageFilename(['Falcon', 'Neutral (Red)'], '/storage/x_csp.png'), 'Falcon_Neutral_Red.png')
    assert.equal(imageFilename(['Pokemon Stadium', 'DAS'], '/storage/p.JPG?t=9'), 'Pokemon_Stadium_DAS.jpg')
    assert.equal(imageFilename([null, ''], 'data:image/png;base64,xx'), 'image.png')
    assert.equal(safeFilePart('  ../..  ', 'fallback'), 'fallback')
    assert.equal(imageExtension('/storage/a.webp'), '.webp')
    assert.equal(imageExtension('/api/mex/render'), '.png') // no extension -> png
  })
})

test('the image is fetched and handed over as a named blob download', async () => {
  await withStubs(async ({ links, revoked }) => {
    const requested = []
    globalThis.fetch = async (url) => { requested.push(url); return new Response('bytes', { status: 200 }) }
    const { downloadImage } = await import('./imageDownload.js')

    await downloadImage('http://127.0.0.1:51234/storage/a_csp.png?t=7', 'Falcon_csp.png')
    assert.equal(requested[0], 'http://127.0.0.1:51234/storage/a_csp.png?t=7')
    assert.equal(links[0].download, 'Falcon_csp.png')
    assert.equal(links[0].clicked, true)
    assert.equal(links[0].removed, true)
    assert.deepEqual(revoked, ['blob:stub'])

    // data: URIs (a freshly rendered preview) go to fetch untouched
    await downloadImage('data:image/png;base64,AAAA', 'preview.png')
    assert.equal(requested[1], 'data:image/png;base64,AAAA')
  })
})

test('a missing source or a failed fetch raises instead of saving an empty file', async () => {
  await withStubs(async ({ links }) => {
    globalThis.fetch = async () => new Response(null, { status: 404 })
    const { downloadImage } = await import('./imageDownload.js')
    await assert.rejects(downloadImage('', 'x.png'), /no image/)
    await assert.rejects(downloadImage('/storage/gone.png', 'x.png'), /HTTP 404/)
    assert.equal(links.length, 0)
  })
})
