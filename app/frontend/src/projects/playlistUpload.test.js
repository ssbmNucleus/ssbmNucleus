import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import { uploadPlaylistTracks, summarizeUpload, trackNameOf } from './playlistUpload.js'

const wav = (name) => new File([new Uint8Array([1, 2, 3])], name)

/** Stub fetch; `respond(index)` returns the JSON body for the nth call. */
function stubFetch(respond) {
  const original = globalThis.fetch
  const calls = []
  let inFlight = 0
  let overlapped = false
  globalThis.fetch = async (url, options) => {
    inFlight += 1
    if (inFlight > 1) overlapped = true
    calls.push({ url, name: options.body.get('name') })
    await new Promise(resolve => setTimeout(resolve, 1))
    inFlight -= 1
    const body = respond(calls.length - 1)
    return { json: async () => body }
  }
  return {
    calls,
    get overlapped() { return overlapped },
    restore() { globalThis.fetch = original }
  }
}

test('the track name is the file name without its extension', () => {
  assert.equal(trackNameOf(wav('Fountain of Dreams.mp3')), 'Fountain of Dreams')
  assert.equal(trackNameOf(wav('my.song.v2.flac')), 'my.song.v2')
})

test('files upload one at a time, never overlapping', async () => {
  const fetchStub = stubFetch(() => ({ success: true, tracks: [] }))
  try {
    const files = ['a.mp3', 'b.wav', 'c.flac', 'd.hps'].map(wav)
    const result = await uploadPlaylistTracks({ files, url: '/api/mex/menu-music/tracks/add' })
    assert.equal(fetchStub.overlapped, false)
    assert.deepEqual(fetchStub.calls.map(c => c.name), ['a', 'b', 'c', 'd'])
    assert.deepEqual(result.added, ['a', 'b', 'c', 'd'])
    assert.deepEqual(result.failed, [])
  } finally {
    fetchStub.restore()
  }
})

test('one unconvertible file does not stop the rest of the batch', async () => {
  const fetchStub = stubFetch(i => (
    i === 1 ? { success: false, error: 'Audio conversion failed' } : { success: true, tracks: [] }
  ))
  try {
    const result = await uploadPlaylistTracks({
      files: ['good.mp3', 'corrupt.hps', 'also-good.wav'].map(wav),
      url: '/add'
    })
    assert.deepEqual(result.added, ['good', 'also-good'])
    assert.deepEqual(result.failed, [{ name: 'corrupt', error: 'Audio conversion failed' }])
  } finally {
    fetchStub.restore()
  }
})

test('an unsupported file is rejected without ever hitting the server', async () => {
  const fetchStub = stubFetch(() => ({ success: true, tracks: [] }))
  try {
    const result = await uploadPlaylistTracks({ files: [wav('clip.aiff'), wav('ok.mp3')], url: '/add' })
    assert.deepEqual(fetchStub.calls.map(c => c.name), ['ok'])
    assert.deepEqual(result.added, ['ok'])
    assert.equal(result.failed.length, 1)
    assert.match(result.failed[0].error, /Unsupported audio format '\.aiff'/)
  } finally {
    fetchStub.restore()
  }
})

test('progress reports each file before it uploads, and the list grows per song', async () => {
  const fetchStub = stubFetch(i => ({ success: true, tracks: new Array(i + 1).fill({}) }))
  try {
    const progress = []
    const lengths = []
    await uploadPlaylistTracks({
      files: ['a.mp3', 'b.mp3'].map(wav),
      url: '/add',
      onProgress: (p) => progress.push(p),
      onAdded: (data) => lengths.push(data.tracks.length)
    })
    assert.deepEqual(progress, [
      { index: 0, total: 2, name: 'a' },
      { index: 1, total: 2, name: 'b' }
    ])
    assert.deepEqual(lengths, [1, 2])
  } finally {
    fetchStub.restore()
  }
})

test('summaries read naturally for one file, many files, and mixed results', () => {
  assert.equal(summarizeUpload({ added: [], failed: [] }), '')
  assert.equal(summarizeUpload({ added: ['Song'], failed: [] }), 'Added “Song”')
  assert.equal(summarizeUpload({ added: ['a', 'b', 'c'], failed: [] }), 'Added 3 songs')
  assert.equal(
    summarizeUpload({ added: [], failed: [{ name: 'a', error: 'boom' }] }),
    'Add failed: boom'
  )
  assert.equal(
    summarizeUpload({ added: ['a'], failed: [{ name: 'b', error: 'boom' }] }),
    'Added 1 of 2 songs — “b” (boom)'
  )
})

test('a whole-batch failure reports its one reason instead of repeating it', () => {
  const failed = ['a', 'b', 'c'].map(name => ({ name, error: 'No project open' }))
  assert.equal(summarizeUpload({ added: [], failed }), 'All 3 songs failed: No project open')
})

test('long failure lists are capped so the message stays readable', () => {
  const failed = ['a', 'b', 'c', 'd', 'e'].map((name, i) => ({ name, error: `err${i}` }))
  assert.equal(
    summarizeUpload({ added: ['ok'], failed }),
    'Added 1 of 6 songs — “a” (err0), “b” (err1), “c” (err2), and 2 more'
  )
})

test('the playlist editor picker accepts a multi-file selection', async () => {
  const source = await readFile(new URL('../shared/audio/PlaylistEditor.jsx', import.meta.url), 'utf8')
  assert.match(source, /type="file"[\s\S]*?multiple/)
  assert.match(source, /Array\.from\(event\.target\.files/)
})
