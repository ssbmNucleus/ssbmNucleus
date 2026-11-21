export const TOKEN_KEY = 'nucleus.vault.token'
export const GENERATION_KEY = 'nucleus.vault.generation'
export const CODES_KEY = 'nucleus.vault.codes'

const storageOrGlobal = (storage) => storage || globalThis.localStorage
const newGeneration = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`

export function tokenFor(storage) {
  try { return storageOrGlobal(storage).getItem(TOKEN_KEY) || '' } catch { return '' }
}

export function generationFor(storage) {
  try { return storageOrGlobal(storage).getItem(GENERATION_KEY) || '' } catch { return '' }
}

export function replaceToken(nextToken, storage) {
  try {
    const target = storageOrGlobal(storage)
    const next = nextToken || ''
    const changed = (target.getItem(TOKEN_KEY) || '') !== next
    if (changed) {
      target.setItem(GENERATION_KEY, newGeneration())
      target.removeItem(CODES_KEY)
    }
    next ? target.setItem(TOKEN_KEY, next) : target.removeItem(TOKEN_KEY)
    return changed
  } catch { return false }
}

export function claimTokenFromHash(hash, storage) {
  const match = /[#&]t=([A-Za-z0-9_-]{16,})/.exec(hash || '')
  if (!match) return false
  replaceToken(match[1], storage)
  return true
}

export const cacheForGeneration = (value, generation) => ({ account_generation: generation, value })

export function cacheValueForGeneration(envelope, generation) {
  return envelope?.account_generation === generation ? envelope.value : undefined
}

export async function fetchAccountPages({ readPage, token, generation, isCurrent, onPage }) {
  const games = []
  let before = null
  for (;;) {
    const page = await readPage({ action: 'list', limit: 1000, before, token })
    if (!isCurrent(token, generation)) throw new Error('vault account changed during library refresh')
    games.push(...(page.games || []))
    // the rows so far ride along so the caller can list them before the
    // crawl ends (bug #64: a big vault is dozens of pages)
    if (onPage) onPage(games.length, games)
    if (!page.next_before) return games
    before = page.next_before
  }
}
