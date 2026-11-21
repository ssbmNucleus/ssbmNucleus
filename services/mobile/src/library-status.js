// library-status — what the Games list says when it has nothing to list.
//
// Bug #64: a 44k-game desktop sync pushes in batches, and every committed
// batch is readable by the phone straight away. But the phone lists only
// games under your connect codes (the desktop's rule), and the first ~18k
// games that went up were years older than the player's current code — so the
// list said nothing at all while the vault already held thousands of rows.
// A bare "0 synced" read as "the phone is broken / waiting for the sync to
// finish". This says what is actually true.
//
// Pure (no DOM, no imports) so node:test can load it directly.

/**
 * @param {object} p
 * @param {number} p.synced   rows the vault returned (before the listing rules)
 * @param {number} p.listed   rows that survived the listing rules
 * @param {string[]} p.codes  the player's claimed connect codes
 * @param {boolean} [p.loading] the library crawl is still paging in
 * @returns {string|null} plain text, or null when the list isn't empty
 */
export function emptyLibraryText({ synced, listed, codes, loading = false }) {
  if (listed > 0) return null
  if (loading) return 'Loading your games…'
  if (!synced) {
    return 'No games in your vault yet. Sync from the desktop app — games '
      + 'show up here as each batch uploads, no need to wait for it to finish.'
  }
  const n = synced.toLocaleString('en-US')
  const who = codes && codes.length ? codes.join(', ') : 'your connect codes'
  return `${n} game${synced === 1 ? '' : 's'} uploaded so far, but none played `
    + `as ${who} yet — older replays from before that code aren't listed. `
    + 'If the desktop is still syncing, your recent games are on the way; '
    + 'refresh in a bit, or check your codes in Settings.'
}
