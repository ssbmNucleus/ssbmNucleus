/**
 * Shared validation for audio uploads.
 *
 * Decoding and conversion belong to the backend so Electron never allocates a
 * full decoded track in the renderer. Every supported file is uploaded intact.
 */

export const AUDIO_ACCEPT = '.wav,.mp3,.ogg,.m4a,.flac,.hps,.brstm,.dsp'

const SUPPORTED_EXTS = new Set(['wav', 'mp3', 'ogg', 'm4a', 'flac', 'hps', 'brstm', 'dsp'])
const MAX_INPUT_BYTES = 512 * 1024 * 1024

function extensionOf(file) {
  return (file?.name?.split('.').pop() || '').toLowerCase()
}

function validateAudioFile(file) {
  const ext = extensionOf(file)
  if (!SUPPORTED_EXTS.has(ext)) {
    throw new Error(`Unsupported audio format${ext ? ` '.${ext}'` : ''}. Choose WAV, MP3, OGG, M4A, FLAC, HPS, BRSTM, or DSP.`)
  }
  if (file.size > MAX_INPUT_BYTES) {
    throw new Error(`Audio file is too large (${Math.ceil(file.size / 1024 / 1024)} MB). The maximum is ${MAX_INPUT_BYTES / 1024 / 1024} MB.`)
  }
}

/**
 * Validate and return the original File. The server converts supported source
 * formats to the Melee format required by the destination.
 */
export async function toUploadableAudio(file) {
  validateAudioFile(file)
  return file
}
