/**
 * usePagination - shared pagination state for the install-page card lists
 * (costumes, stage variants, custom stages, menu mods).
 *
 * Keeps the DOM small when a list has hundreds/thousands of entries: callers
 * render only items[start..end) and show a <PaginationBar pager={...}/> when
 * pageCount > 1.
 *
 * `resetKey` should identify the list (selected fighter/stage/submod) so the
 * page jumps back to 0 when the user switches lists. The current page is also
 * clamped automatically when the list shrinks (e.g. after removing items).
 */
import { useState, useEffect } from 'react'

export const DEFAULT_PAGE_SIZE = 60

export default function usePagination(totalItems, resetKey, pageSize = DEFAULT_PAGE_SIZE) {
  const [page, setPage] = useState(0)

  useEffect(() => {
    setPage(0)
  }, [resetKey])

  const pageCount = Math.max(1, Math.ceil(totalItems / pageSize))
  const current = Math.min(page, pageCount - 1)
  const start = current * pageSize
  const end = Math.min(start + pageSize, totalItems)

  return { page: current, pageCount, start, end, setPage, pageSize, totalItems }
}
