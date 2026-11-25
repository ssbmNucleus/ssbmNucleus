/**
 * meleeUnlocked.js - what the Melee Unlocked export card says, as plain functions
 * (MeleeUnlockedCard.jsx draws it; settings/MeleeUnlockedSection.jsx keeps the two folders).
 *
 * A fighter's plugin is native code the game runs, so C source that came inside a
 * downloaded package is not built until the user confirms that fighter here
 * (backend projects/install/fighter_source.py). The /fighters answer lists those
 * as `unconfirmed`, each with where its package came from and the question to ask.
 */
export const KIT_PATH_KEY = 'melee_unlocked_kit_path'
export const GCC_BIN_KEY = 'melee_unlocked_gcc_bin'

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`
const names = list => list.map(f => f.name).join(', ')

/** The /fighters answer with every list present. */
export function fighterLists(data) {
  return {
    buildable: data?.buildable || [],
    unconfirmed: data?.unconfirmed || [],
    withoutSource: data?.withoutSource || [],
  }
}

/** Why the export cannot run, or null when it can. `fighters` is the /fighters answer or null. */
export function blockedReason({ kitPath, gccBin, fighters }) {
  if (!kitPath && !gccBin) return 'Set the fighter kit and compiler folders in Settings'
  if (!kitPath) return 'Set the fighter kit folder in Settings'
  if (!gccBin) return 'Set the compiler folder in Settings'
  if (!fighters) return null
  const { buildable, unconfirmed, withoutSource } = fighterLists(fighters)
  if (buildable.length === 0) {
    if (unconfirmed.length) return `Nothing to build until you confirm the downloaded source of ${names(unconfirmed)}`
    return withoutSource.length === 0
      ? 'This project has no custom fighters'
      : 'None of this project\'s custom fighters has its C source in the Vault'
  }
  return null
}

/** The card's description line. */
export function describe(fighters) {
  if (!fighters) return 'Fighter plugins for Melee Unlocked\'s Source Port.'
  const { buildable, unconfirmed, withoutSource } = fighterLists(fighters)
  if (buildable.length === 0 && unconfirmed.length === 0) return 'Fighter plugins for Melee Unlocked\'s Source Port.'
  const waiting = unconfirmed.length
    ? ` ${plural(unconfirmed.length, 'fighter')} with downloaded source ${unconfirmed.length === 1 ? 'waits' : 'wait'} for your confirmation.`
    : ''
  const rest = withoutSource.length ? ` ${plural(withoutSource.length, 'fighter')} without source will stay locked there.` : ''
  return `Plugins for ${plural(buildable.length, 'custom fighter')}, for Melee Unlocked's Source Port.${waiting}${rest}`
}

/** One unconfirmed fighter's line on the card: who, and where the source came from. */
export function unconfirmedLine(fighter) {
  return `${fighter.name}: not built. Its C source came from ${fighter.origin} and has not been confirmed.`
}

/** The lines shown after an export: [{ kind: 'ok' | 'warn' | 'error', text }]. */
export function resultLines(result) {
  const lines = []
  if (result.built?.length) {
    lines.push({ kind: 'ok', text: `Built ${plural(result.built.length, 'plugin')} in ${result.folder}` })
  }
  for (const f of result.failed || []) {
    const last = String(f.error || '').trim().split('\n').filter(Boolean).pop() || 'build failed'
    lines.push({ kind: 'error', text: `${f.name}: ${last}` })
  }
  for (const f of result.unconfirmed || []) {
    lines.push({ kind: 'warn', text: `${f.name}: not built, ${f.reason || 'its source has not been confirmed'}` })
  }
  if (result.withoutSource?.length) {
    lines.push({ kind: 'warn', text: `No source in the Vault: ${names(result.withoutSource)}` })
  }
  if (!lines.length) lines.push({ kind: 'warn', text: 'Nothing was built.' })
  return lines
}
