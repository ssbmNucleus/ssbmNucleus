/**
 * NumberedPager — footer pager for a server-paginated list. First/last pages
 * are always visible, with a window around the current page and gaps elided
 * with an ellipsis. Clicking an ellipsis turns it into a type-a-page-number
 * input (Enter jumps, Escape/blur cancels). Renders nothing for a single page.
 *
 * Props: page (0-based), pages (total), loading, onPage(nextPage).
 */
import { useState } from 'react'
import { playSound, playHoverSound } from '../audio/sounds'
import './NumberedPager.css'

export default function NumberedPager({ page, pages, loading, onPage }) {
  const [jumpAt, setJumpAt] = useState(null) // which gap is an input right now
  const [draft, setDraft] = useState('')
  if (pages <= 1) return null

  const items = []
  if (pages <= 7) {
    for (let i = 0; i < pages; i++) items.push(i)
  } else {
    const want = [...new Set([0, 1, page - 1, page, page + 1, pages - 2, pages - 1]
      .filter((n) => n >= 0 && n < pages))].sort((a, b) => a - b)
    let prev = null
    for (const n of want) {
      if (prev != null && n - prev > 1) items.push(`gap-${n}`)
      items.push(n)
      prev = n
    }
  }

  const closeJump = () => { setJumpAt(null); setDraft('') }
  const submitJump = () => {
    const n = parseInt(draft, 10)
    closeJump()
    if (Number.isFinite(n)) {
      const target = Math.min(Math.max(1, n), pages) - 1
      if (target !== page) onPage(target)
    }
  }

  return (
    <div className="numbered-pager">
      <button type="button" disabled={loading || page === 0}
              onMouseEnter={playHoverSound} onClick={() => onPage(page - 1)}
              aria-label="Previous page">‹</button>
      {items.map((it) => (typeof it === 'number' ? (
        <button key={it} type="button"
                className={it === page ? 'is-current' : ''}
                disabled={loading || it === page}
                onMouseEnter={playHoverSound} onClick={() => onPage(it)}>
          {it + 1}
        </button>
      ) : it === jumpAt ? (
        <input key={it} className="numbered-pager-jump" autoFocus
               type="number" min={1} max={pages} value={draft}
               placeholder={`1–${pages}`}
               onChange={(e) => setDraft(e.target.value)}
               onBlur={closeJump}
               onKeyDown={(e) => {
                 if (e.key === 'Enter') submitJump()
                 else if (e.key === 'Escape') closeJump()
               }} />
      ) : (
        <button key={it} type="button" className="numbered-pager-gap"
                title="Jump to a page…" onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); setJumpAt(it) }}>…</button>
      )))}
      <button type="button" disabled={loading || page >= pages - 1}
              onMouseEnter={playHoverSound} onClick={() => onPage(page + 1)}
              aria-label="Next page">›</button>
    </div>
  )
}
