/**
 * VaultMenusView - the vault's Menus mode: a sidebar of the seven menu-mod
 * kinds (grouped by screen, with live counts) beside the selected kind's
 * card grid. Replaces the old three-level card drill-down (Menus → CSS/SSS/
 * HUD → kind → cards) with one page.
 *
 * The kind registry lives in menuKinds.js; the pane (cards + editors) in
 * MenuKindPane. While a kind's editor is open the sidebar hides and the
 * editor takes the full width.
 *
 * Counts are cached for the life of the page so returning to Menus paints
 * the last known numbers at once and refreshes quietly.
 */
import { useCallback, useEffect, useState } from 'react'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { api } from '../../shared/transport/api'
import { MENU_GROUPS, MENU_KINDS, kindByKey } from './menuKinds'
import MenuKindPane from './MenuKindPane'

let cachedCounts = null

function useMenuKindCounts(refreshKey) {
  const [counts, setCounts] = useState(cachedCounts)
  const refetch = useCallback(async () => {
    try {
      const data = await api.get('/menus/summary')
      cachedCounts = data.counts || {}
      setCounts(cachedCounts)
    } catch (err) {
      console.error('[menus] summary failed:', err)
    }
  }, [])
  useEffect(() => { refetch() }, [refetch, refreshKey])
  return [counts, refetch]
}

export default function VaultMenusView({
  selectedKind,
  onSelectKind,
  refreshKey = 0,
  detailOpen = false,
  onDetailChange,
}) {
  const [counts, refetchCounts] = useMenuKindCounts(refreshKey)
  const kind = kindByKey(selectedKind)

  return (
    <div className={`vault-menus${detailOpen ? ' vault-menus--detail' : ''}`}>
      {!detailOpen && (
        <nav className="vault-menus-side" aria-label="Menu mod kinds">
          {MENU_GROUPS.map((group) => (
            <div key={group.key} className="vault-menus-group">
              <div className="vault-menus-group-label">{group.label}</div>
              {MENU_KINDS.filter((k) => k.group === group.key).map((k) => {
                const n = counts?.[k.key]
                const active = k.key === kind.key
                const pending = n === undefined
                return (
                  <button
                    key={k.key}
                    className={`vault-menus-item${active ? ' active' : ''}`}
                    onMouseEnter={playHoverSound}
                    onClick={() => { if (!active) { playSound('boop'); onSelectKind(k.key) } }}
                  >
                    <span className="vault-menus-item-label">{k.label}</span>
                    {/* Always render a digit so the badge never changes width
                        when the numbers arrive; hide it until they do. */}
                    <span className={`vault-menus-item-count${pending ? ' pending' : n ? '' : ' empty'}`}>
                      {pending ? 0 : n}
                    </span>
                  </button>
                )
              })}
            </div>
          ))}
        </nav>
      )}

      <section className="vault-menus-pane">
        <MenuKindPane
          key={kind.key}
          kind={kind}
          refreshKey={refreshKey}
          expectedCount={counts?.[kind.key]}
          onDetailChange={onDetailChange}
          onCountsChanged={refetchCounts}
        />
      </section>
    </div>
  )
}
