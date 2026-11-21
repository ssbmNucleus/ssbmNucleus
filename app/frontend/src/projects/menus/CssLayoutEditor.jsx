import { useState, useEffect, useCallback, useMemo } from 'react'
import SssCanvas from './SssCanvas'
import CssIconProperties from './CssIconProperties'
import CssLloadBadges, { L_BADGE_STYLE } from './CssLloadBadges'
import { LloadAddPicker, LloadAltRows } from './CssLloadAlternates'
import IconReorderList from './IconReorderList'
import PropsPopup from './PropsPopup'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { API_URL, backendMediaUrl } from '../../shared/config/config'
import { api } from '../../shared/transport/api'
import { applyCssTemplate, buildCssGridTemplate, computeAutoCssLayout, gridIcons, pickAutoColumns } from './cssGridLayout'
import './LayoutEditor.css'

// Per-slot layout fields: these stay with the slot position when icon
// identities are reordered/swapped within the list
const CSS_SLOT_FIELDS = ['x', 'y', 'z', 'scaleX', 'scaleY',
  'collisionSizeX', 'collisionSizeY', 'collisionOffsetX', 'collisionOffsetY']

const CSS_BASE_WIDTH = 3.5
const CSS_BASE_HEIGHT = 3.4
const CSS_TEMPLATE_WIDTH = 35.05
const CSS_TEMPLATE_HEIGHT = 28.8

function getCssCollisionRect(icon) {
  return {
    ox: icon.collisionOffsetX || 0,
    oy: icon.collisionOffsetY || 0,
    w: (icon.collisionSizeX || 7.05) / 2 * icon.scaleX,
    h: (icon.collisionSizeY || 7.2) / 2 * icon.scaleY
  }
}

// L-load alternates' icons are tucked behind their base (docs/dev/L_LOAD.md).
// The editor works on the visible icons only; the tucked ones ride along in
// layout.icons and are posted back untouched (the backend re-tucks them).
function altIdsOf(layout) {
  return layout?.lload?.altExternalIds || []
}

function tuckedIcons(layout) {
  const alts = new Set(altIdsOf(layout))
  return alts.size ? layout.icons.filter(ic => alts.has(ic.fighter)) : []
}

export default function CssLayoutEditor() {
  const [layout, setLayout] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [dirty, setDirty] = useState(false)
  const [selectedIndices, setSelectedIndices] = useState([])
  const [propsPopup, setPropsPopup] = useState(null)
  const [zoom, setZoom] = useState(8)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const [showCollision, setShowCollision] = useState(true)
  const [showOverscan, setShowOverscan] = useState(false)
  // Canvas drag behavior: 'move' (free positioning), 'swap' (exchange two
  // icons), or 'reorder' (insert an icon at another slot, shifting the rest).
  // Swap and reorder both snap to the grid template.
  const [gridMode, setGridMode] = useState('move')
  const useTemplate = gridMode !== 'move'
  const fighterIconUrl = (icon) => icon.iconPath
    ? backendMediaUrl(`${API_URL}/menus/css/fighter-icon?path=${encodeURIComponent(icon.iconPath)}`)
    : null
  // An alternate's art comes from its tucked icon (not in the visible list)
  const altIconUrl = (name) => {
    const tucked = (layout?.icons || []).find(ic => (ic.fighterName || '').trim().toLowerCase()
      === String(name).trim().toLowerCase())
    return tucked ? fighterIconUrl(tucked) : null
  }

  // L alternates edits save straight away (no Save button)
  const [lloadBusy, setLloadBusy] = useState(false)
  const [lloadProblems, setLloadProblems] = useState([])

  useEffect(() => { fetchLayout() }, [])

  // Take a fresh layout payload. `keepFighter` re-selects that fighter's icon
  // (by visible index) so the properties popup survives an L alternates save.
  const applyLoadedLayout = (data, keepFighter) => {
    setLayout(data)
    const keep = keepFighter == null ? -1
      : gridIcons(data.icons || [], altIdsOf(data)).findIndex(ic => ic.fighter === keepFighter)
    setSelectedIndices(keep >= 0 ? [keep] : [])
    setDirty(false)
  }

  const fetchLayout = async () => {
    setLoading(true)
    setError(null)
    try {
      applyLoadedLayout(await api.get('/menus/css/layout'))
    } catch (e) {
      setError(e.message || 'Failed to load layout')
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async () => {
    if (!layout) return
    setSaving(true)
    try {
      await api.post('/menus/css/layout', { icons: layout.icons, template: layout.template })
      setDirty(false)
      await fetchLayout()
    } catch (e) {
      alert(`Save failed: ${e.message}`)
    } finally {
      setSaving(false)
    }
  }

  // Visible icons: everything below draws, selects, swaps, reorders and
  // counts these only (indices are positions in this list)
  const icons = useMemo(
    () => gridIcons(layout?.icons || [], altIdsOf(layout)),
    [layout?.icons, layout?.lload])
  const baseIds = useMemo(() => new Set(layout?.lload?.baseExternalIds || []), [layout?.lload])

  const updateIcons = useCallback((newIcons) => {
    setLayout(prev => prev ? { ...prev, icons: [...newIcons, ...tuckedIcons(prev)] } : prev)
    setDirty(true)
  }, [])

  // Save the L-load groups, then re-fit the grid over the visible icons the
  // way adding/removing a fighter does, so a new alternate leaves no hole and
  // a dropped one gets a slot back. Unsaved edits are saved first, since the
  // reload would lose them.
  const handleSaveLload = async (groups) => {
    const keepFighter = icons[selectedIndices[0]]?.fighter
    setLloadBusy(true)
    setLloadProblems([])
    try {
      if (dirty) await api.post('/menus/css/layout', { icons: layout.icons, template: layout.template })
      const res = await api.post('/menus/css/lload', { groups })
      setLloadProblems(res.problems || [])
      let data = await api.get('/menus/css/layout')
      if (data.icons?.length && data.template) {
        await api.post('/menus/css/layout',
          computeAutoCssLayout(data.icons, data.template, altIdsOf(data)))
        data = await api.get('/menus/css/layout')
      }
      applyLoadedLayout(data, keepFighter)
    } catch (e) {
      setLloadProblems([e.message || 'Failed to save L alternates'])
    } finally {
      setLloadBusy(false)
    }
  }

  const updateTemplate = useCallback((newTemplate) => {
    setLayout(prev => prev ? { ...prev, template: newTemplate } : prev)
    setDirty(true)
  }, [])

  const maybeApplyTemplate = useCallback((icns) => {
    if (!useTemplate || !layout?.template) return icns
    return applyCssTemplate(icns, layout.template)
  }, [useTemplate, layout?.template])

  const handleSetGridMode = useCallback((mode) => {
    setGridMode(mode)
    if (mode !== 'move' && layout?.template) {
      updateIcons(applyCssTemplate(icons, layout.template))
    }
  }, [layout, icons, updateIcons])

  const primaryIdx = selectedIndices.length > 0 ? selectedIndices[0] : -1

  const handleSelectionChange = useCallback((indices) => setSelectedIndices(indices), [])

  const handleMoveIcon = useCallback((idx, dx, dy) => {
    const newIcons = [...icons]
    newIcons[idx] = { ...newIcons[idx], x: newIcons[idx].x + dx, y: newIcons[idx].y + dy }
    updateIcons(newIcons)
  }, [icons, updateIcons])

  const handleMoveIcons = useCallback((indices, dx, dy) => {
    const newIcons = [...icons]
    indices.forEach(idx => {
      newIcons[idx] = { ...newIcons[idx], x: newIcons[idx].x + dx, y: newIcons[idx].y + dy }
    })
    updateIcons(newIcons)
  }, [icons, updateIcons])

  const swapIcons = useCallback((arr, i, j) => {
    const a = arr[i], b = arr[j]
    arr[i] = { ...b, x: a.x, y: a.y, z: a.z, scaleX: a.scaleX, scaleY: a.scaleY,
               collisionSizeX: a.collisionSizeX, collisionSizeY: a.collisionSizeY,
               collisionOffsetX: a.collisionOffsetX, collisionOffsetY: a.collisionOffsetY }
    arr[j] = { ...a, x: b.x, y: b.y, z: b.z, scaleX: b.scaleX, scaleY: b.scaleY,
               collisionSizeX: b.collisionSizeX, collisionSizeY: b.collisionSizeY,
               collisionOffsetX: b.collisionOffsetX, collisionOffsetY: b.collisionOffsetY }
    return arr
  }, [])

  const handleSwapIcons = useCallback((i, j) => {
    const newIcons = [...icons]
    swapIcons(newIcons, i, j)
    updateIcons(maybeApplyTemplate(newIcons))
  }, [icons, updateIcons, maybeApplyTemplate, swapIcons])

  const handleUpdateIcon = useCallback((indices, updates) => {
    const newIcons = [...icons]
    const idxList = Array.isArray(indices) ? indices : [indices]
    idxList.forEach(idx => { newIcons[idx] = { ...newIcons[idx], ...updates } })
    updateIcons(newIcons)
  }, [icons, updateIcons])

  const handleAddIcon = useCallback(() => {
    const newIcon = {
      index: icons.length,
      x: 0, y: 0, z: 0,
      scaleX: 1, scaleY: 1,
      fighter: 0, fighterName: null,
      sfxID: 205,
      collisionOffsetX: 0, collisionOffsetY: 0,
      collisionSizeX: 7.05, collisionSizeY: 7.2,
      iconPath: null, status: 2
    }
    const newIcons = maybeApplyTemplate([...icons, newIcon])
    updateIcons(newIcons)
    setSelectedIndices([newIcons.length - 1])
  }, [icons, updateIcons, maybeApplyTemplate])

  const handleRemoveIcon = useCallback(() => {
    if (selectedIndices.length === 0) return
    const removeSet = new Set(selectedIndices)
    const newIcons = icons.filter((_, i) => !removeSet.has(i))
    updateIcons(maybeApplyTemplate(newIcons))
    setSelectedIndices([])
  }, [icons, selectedIndices, updateIcons, maybeApplyTemplate])

  const handleMoveIconUp = useCallback(() => {
    if (primaryIdx <= 0) return
    const newIcons = [...icons]
    swapIcons(newIcons, primaryIdx, primaryIdx - 1)
    updateIcons(maybeApplyTemplate(newIcons))
    setSelectedIndices([primaryIdx - 1])
  }, [icons, primaryIdx, updateIcons, maybeApplyTemplate, swapIcons])

  const handleMoveIconDown = useCallback(() => {
    if (primaryIdx < 0 || primaryIdx >= icons.length - 1) return
    const newIcons = [...icons]
    swapIcons(newIcons, primaryIdx, primaryIdx + 1)
    updateIcons(maybeApplyTemplate(newIcons))
    setSelectedIndices([primaryIdx + 1])
  }, [icons, primaryIdx, updateIcons, maybeApplyTemplate])

  // Reorder core: pull the icon identities at `indices` out of the list and
  // re-insert them as a contiguous block before position `insertPos` in the
  // remaining list. Slot layout fields stay with their positions (re-zipped),
  // so reordering shuffles identities through fixed grid slots.
  const reorderByInsertPos = useCallback((indices, insertPos) => {
    const movingSet = new Set(indices)
    const movingSorted = [...indices].sort((a, b) => a - b)
    const moving = movingSorted.map(i => icons[i])
    const remaining = icons.filter((_, i) => !movingSet.has(i))
    const pos = Math.max(0, Math.min(insertPos, remaining.length))
    remaining.splice(pos, 0, ...moving)
    const slots = icons.map(ic =>
      Object.fromEntries(CSS_SLOT_FIELDS.map(f => [f, ic[f]]))
    )
    const rezipped = remaining.map((ic, i) => ({ ...ic, ...slots[i] }))
    updateIcons(maybeApplyTemplate(rezipped))
    setSelectedIndices(moving.map((_, k) => pos + k))
  }, [icons, updateIcons, maybeApplyTemplate])

  // Convert a drop target row into an insert position, then reorder the block.
  // Dragging downward drops after the target; upward drops before it.
  const reorderToTarget = useCallback((indices, to) => {
    const movingSet = new Set(indices)
    if (movingSet.has(to)) return
    const movingSorted = [...indices].sort((a, b) => a - b)
    let insertPos = 0
    for (let i = 0; i < to; i++) if (!movingSet.has(i)) insertPos++
    if (movingSorted[0] < to) insertPos++
    reorderByInsertPos(indices, insertPos)
  }, [reorderByInsertPos])

  // Drag-and-drop reorder: move one icon identity from one slot to another.
  const handleReorderIcon = useCallback((from, to) => {
    if (from === to) return
    reorderToTarget([from], to)
  }, [reorderToTarget])

  // Bulk drag-and-drop reorder: move every selected identity as a block.
  const handleReorderIcons = useCallback((indices, to) => {
    reorderToTarget(indices, to)
  }, [reorderToTarget])

  const handleMoveIconsToTop = useCallback(() => {
    if (selectedIndices.length === 0) return
    reorderByInsertPos(selectedIndices, 0)
  }, [selectedIndices, reorderByInsertPos])

  const handleMoveIconsToBottom = useCallback(() => {
    if (selectedIndices.length === 0) return
    reorderByInsertPos(selectedIndices, icons.length - selectedIndices.length)
  }, [selectedIndices, icons.length, reorderByInsertPos])

  const handleApplyTemplate = useCallback(() => {
    if (!layout?.template) return
    updateIcons(applyCssTemplate(icons, layout.template))
  }, [icons, layout?.template, updateIcons])

  const handleApplyGrid = useCallback((cols) => {
    if (!layout) return
    const count = icons.length
    if (count === 0 || cols <= 0) return

    // Scale each axis independently to fill the vanilla bounding box exactly
    const newTemplate = buildCssGridTemplate(layout.template, count, cols)
    updateTemplate(newTemplate)
    updateIcons(applyCssTemplate(icons, newTemplate))
  }, [layout, icons, updateIcons, updateTemplate])

  const handleResetVanilla = useCallback(() => {
    fetchLayout()
  }, [])

  if (loading) return <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--color-text-muted)' }}>Loading CSS layout...</div>
  if (error) return <div style={{ textAlign: 'center', padding: '2rem' }}><p style={{ color: 'var(--color-danger)' }}>{error}</p><button className="mode-btn" onClick={fetchLayout}>Retry</button></div>
  if (!layout) return null

  const selectedIcons = selectedIndices.map(i => icons[i]).filter(Boolean)

  return (
    <div className="sss-layout-editor">
      {/* Top bar */}
      <div className="sss-top-bar">
        <div className="sss-page-tabs">
          <span style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-display)', fontWeight: 600, padding: '0.35rem 0.5rem', fontSize: '0.85rem' }}>
            Character Select Screen
          </span>
        </div>
        <div className="sss-top-actions">
          <button className="sss-tab-btn" onClick={fetchLayout} onMouseEnter={playHoverSound} title="Reload">&#8635;</button>
          <button
            className={`mode-btn ${dirty ? 'active' : ''}`}
            onClick={handleSave}
            disabled={saving || !dirty}
            onMouseEnter={playHoverSound}
            style={{ marginLeft: '0.5rem' }}
          >
            {saving ? 'Saving...' : dirty ? 'Save *' : 'Saved'}
          </button>
        </div>
      </div>

      {/* Main content */}
      <div className="sss-main-content">
        {/* Relative wrapper so the L badges can sit over the canvas */}
        <div style={{ position: 'relative', display: 'flex', flex: 1, minWidth: 0, minHeight: 0 }}>
          <SssCanvas
            icons={icons}
            selectedIndices={selectedIndices}
            onSelectionChange={handleSelectionChange}
            onMoveIcon={handleMoveIcon}
            onMoveIcons={handleMoveIcons}
            onSwapIcons={handleSwapIcons}
            onReorderIcons={handleReorderIcon}
            onContextMenu={(x, y) => setPropsPopup({ x, y })}
            zoom={zoom}
            offset={offset}
            onZoomChange={setZoom}
            onOffsetChange={setOffset}
            showCollision={showCollision}
            showOverscan={showOverscan}
            swapMode={gridMode === 'swap'}
            reorderMode={gridMode === 'reorder'}
            iconBaseWidth={CSS_BASE_WIDTH}
            iconBaseHeight={CSS_BASE_HEIGHT}
            templateWidth={CSS_TEMPLATE_WIDTH}
            templateHeight={CSS_TEMPLATE_HEIGHT}
            templateSrc={backendMediaUrl(`${API_URL}/menus/css/backdrop`)}
            getCollisionRect={getCssCollisionRect}
            iconEndpoint="/menus/css/fighter-icon"
            fitToView
          />
          <CssLloadBadges
            icons={icons}
            baseIds={baseIds}
            zoom={zoom}
            offset={offset}
            iconBaseWidth={CSS_BASE_WIDTH}
            iconBaseHeight={CSS_BASE_HEIGHT}
          />
        </div>

        <div className="sss-right-panel">
          <div className="sss-icon-actions">
            <button className="sss-action-btn add" onClick={handleAddIcon} onMouseEnter={playHoverSound}>
              + Add Icon
            </button>
            <button className="sss-action-btn remove" onClick={handleRemoveIcon} onMouseEnter={playHoverSound}
              disabled={selectedIndices.length === 0}>
              - Remove{selectedIndices.length > 1 ? ` (${selectedIndices.length})` : ''}
            </button>
          </div>

          {lloadBusy && (
            <div style={{ padding: '0.3rem var(--space-2)', fontSize: '0.65rem', color: 'var(--color-cyan)' }}>
              Saving L alternates and re-fitting the grid...
            </div>
          )}
          {(lloadProblems.length > 0 || layout.lload?.problems?.length > 0) && (
            <div style={{ padding: '0.3rem var(--space-2)', fontSize: '0.65rem', color: 'var(--color-warning)' }}>
              {[...lloadProblems, ...(layout.lload?.problems || [])].map((p, i) =>
                <div key={i}>L alternates: {p}</div>)}
            </div>
          )}

          <div className="sss-icon-list-header">
            <span>Icons ({icons.length})</span>
            <div className="sss-reorder-btns">
              <button onClick={handleMoveIconsToTop} title="Move to top" disabled={primaryIdx <= 0}>&#8607;</button>
              <button onClick={handleMoveIconUp} title="Move up" disabled={primaryIdx <= 0}>&#9650;</button>
              <button onClick={handleMoveIconDown} title="Move down"
                disabled={primaryIdx < 0 || primaryIdx >= icons.length - 1}>&#9660;</button>
              <button onClick={handleMoveIconsToBottom} title="Move to bottom"
                disabled={primaryIdx < 0 || primaryIdx >= icons.length - 1}>&#8609;</button>
            </div>
          </div>
          <IconReorderList
            icons={icons}
            selectedIndices={selectedIndices}
            onSelect={setSelectedIndices}
            onContextMenu={(x, y) => setPropsPopup({ x, y })}
            onReorder={handleReorderIcon}
            onReorderBulk={handleReorderIcons}
            getLabel={(icon) => (
              <>
                {icon.fighterName || `Fighter ${icon.fighter}`}
                {baseIds.has(icon.fighter) && <span style={{ ...L_BADGE_STYLE, marginLeft: '0.35rem' }}>L</span>}
              </>
            )}
            getIconUrl={fighterIconUrl}
            renderRowAction={(icon) => (
              <LloadAddPicker fighterId={icon.fighter} lload={layout.lload}
                busy={lloadBusy} onSave={handleSaveLload} />
            )}
            renderAfterRow={(icon) => (
              <LloadAltRows fighterId={icon.fighter} lload={layout.lload}
                busy={lloadBusy} onSave={handleSaveLload} iconUrlFor={altIconUrl} />
            )}
          />
        </div>

        {propsPopup && selectedIcons.length > 0 && (
          <PropsPopup x={propsPopup.x} y={propsPopup.y} onClose={() => setPropsPopup(null)}>
            <CssIconProperties
              icons={selectedIcons}
              indices={selectedIndices}
              fighters={layout.fighters || []}
              onUpdate={handleUpdateIcon}
              lload={layout.lload}
            />
          </PropsPopup>
        )}
      </div>

      {/* Bottom toolbar */}
      <div className="sss-bottom-bar">
        {/* Columns is the primary control - big stepper, first in the bar */}
        <div className="sss-grid-controls sss-grid-controls--primary">
          <label>Columns</label>
          <div className="sss-cols-stepper">
            <button
              onClick={() => { playSound('tick'); handleApplyGrid(Math.max(1, (layout?.template?.iconsPerRow ?? 9) - 1)) }}
              disabled={(layout?.template?.iconsPerRow ?? 9) <= 1}
              title="Fewer columns"
            >−</button>
            <input type="number" min={1} max={20}
              value={layout?.template?.iconsPerRow ?? 9}
              onChange={(e) => handleApplyGrid(Math.max(1, Math.min(20, parseInt(e.target.value) || 1)))} />
            <button
              onClick={() => { playSound('tick'); handleApplyGrid(Math.min(20, (layout?.template?.iconsPerRow ?? 9) + 1)) }}
              disabled={(layout?.template?.iconsPerRow ?? 9) >= 20}
              title="More columns"
            >+</button>
          </div>
          <span className="sss-grid-dim">
            ({Math.ceil(icons.length / (layout?.template?.iconsPerRow ?? 9))} rows)
          </span>
          <button
            className="sss-tab-btn"
            onClick={() => { playSound('boop'); handleApplyGrid(pickAutoColumns(icons.length)) }}
            title="Auto-fit columns and rows to the icon count"
          >Auto</button>
          <button className="sss-tab-btn" onClick={handleResetVanilla}>Reset</button>
        </div>
        <div className="sss-bottom-group">
          <label>Zoom: {zoom}x</label>
          <input type="range" min={4} max={20} value={zoom}
            onChange={(e) => setZoom(parseInt(e.target.value))} style={{ width: '80px' }} />
        </div>
        <label className="sss-checkbox">
          <input type="checkbox" checked={showCollision} onChange={(e) => setShowCollision(e.target.checked)} />
          Collisions
        </label>
        <label className="sss-checkbox">
          <input type="checkbox" checked={showOverscan} onChange={(e) => setShowOverscan(e.target.checked)} />
          Overscan
        </label>
        <div className="sss-drag-mode">
          <label>Drag</label>
          <div className="sss-mode-seg">
            <button
              className={gridMode === 'move' ? 'active' : ''}
              onClick={() => { playSound('boop'); handleSetGridMode('move') }}
              onMouseEnter={playHoverSound}
              title="Drag icons to reposition them freely"
            >Move</button>
            <button
              className={gridMode === 'swap' ? 'active' : ''}
              onClick={() => { playSound('boop'); handleSetGridMode('swap') }}
              onMouseEnter={playHoverSound}
              title="Drag an icon onto another to swap the two"
            >Swap</button>
            <button
              className={gridMode === 'reorder' ? 'active' : ''}
              onClick={() => { playSound('boop'); handleSetGridMode('reorder') }}
              onMouseEnter={playHoverSound}
              title="Drag an icon onto a slot to insert it there, shifting the rest"
            >Reorder</button>
          </div>
        </div>
      </div>
    </div>
  )
}
