import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import { AUDIO_ACCEPT, toUploadableAudio } from './audioConvert.js'

const SUPPORTED_EXTENSIONS = ['wav', 'mp3', 'ogg', 'm4a', 'flac', 'hps', 'brstm', 'dsp']

test('the picker contract advertises exactly the server-supported formats', () => {
  assert.equal(AUDIO_ACCEPT, '.wav,.mp3,.ogg,.m4a,.flac,.hps,.brstm,.dsp')
  assert.equal(AUDIO_ACCEPT.includes('audio/*'), false)
  assert.equal(AUDIO_ACCEPT.includes('.ssm'), false)
})

test('every advertised format uploads as the original File', async () => {
  for (const extension of SUPPORTED_EXTENSIONS) {
    const file = new File([new Uint8Array([1, 2, 3])], `track.${extension}`)
    assert.strictEqual(await toUploadableAudio(file), file)
  }
})

test('unsupported extensions fail before upload', async () => {
  for (const extension of ['aiff', 'aac', 'wma', 'ssm', 'exe']) {
    const file = new File([new Uint8Array([1])], `track.${extension}`)
    await assert.rejects(toUploadableAudio(file), new RegExp(`Unsupported audio format '.${extension}'`))
  }
})

test('files over 512 MB fail without reading their contents', async () => {
  let read = false
  const file = {
    name: 'huge.flac',
    size: 512 * 1024 * 1024 + 1,
    async arrayBuffer() {
      read = true
      throw new Error('must not read')
    }
  }
  await assert.rejects(toUploadableAudio(file), /maximum is 512 MB/)
  assert.equal(read, false)
})

test('all four upload paths use the shared validator', async () => {
  const callers = [
    '../../projects/playlistUpload.js',   // menu + stage music playlists upload through this
    '../../vault/stages/CustomStageDetailView.jsx',
    '../../vault/sounds/SoundBankModal.jsx'
  ]
  for (const caller of callers) {
    const source = await readFile(new URL(caller, import.meta.url), 'utf8')
    assert.match(source, /import \{[^}]*toUploadableAudio[^}]*\} from ['"][^'"]*audioConvert(\.js)?['"]/)
    assert.match(source, /await toUploadableAudio\(file\)/)
  }
  for (const modal of ['../../projects/MenuMusicModal.jsx', '../../projects/StageMusicModal.jsx']) {
    const source = await readFile(new URL(modal, import.meta.url), 'utf8')
    assert.match(source, /import \{[^}]*uploadPlaylistTracks[^}]*\} from ['"]\.\/playlistUpload['"]/)
  }
})
