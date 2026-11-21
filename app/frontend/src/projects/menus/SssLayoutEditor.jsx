import { useState, useEffect, useCallback, useRef } from 'react'
import SssCanvas from './SssCanvas'
import SssIconProperties from './SssIconProperties'
import IconReorderList from './IconReorderList'
import PropsPopup from './PropsPopup'
import { SSS_STATUS_LOCKED } from './sssSlots.js'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { appConfirm } from '../../shared/ui/appDialogs'
import { API_URL, backendMediaUrl } from '../../shared/config/config'
import { api } from '../../shared/transport/api'
import './LayoutEditor.css'

const STATUS_LABELS = ['Hidden', 'Locked', 'Unlocked', 'Random', 'Decoration']

// Per-slot layout fields: these stay with the slot position when icon
// identities are reordered/swapped within the list
const SSS_SLOT_FIELDS = ['x', 'y', 'z', 'scaleX', 'scaleY', 'width', 'height', 'group']

// Grid spacing (game units) used by the "Columns" auto-layout
const SSS_GRID_GAP_X = 6.6
const SSS_GRID_GAP_Y = 5.6
const SSS_TEMPLATE_ASPECT = 28.59 / 23.50
// Center the auto grid on the template's bright select frame (game origin),
// not high up near the top edge.
const SSS_GRID_CENTER_X = 0
const SSS_GRID_CENTER_Y = 0

// Pick the column count whose grid aspect best matches the stage-select
// template, so "Auto" lands on a balanced layout for any icon count.
function pickSssAutoColumns(count) {
  if (count <= 0) return 6
  let bestCols = Math.min(count, 6)
  let bestErr = Infinity
  for (let cols = 1; cols <= count; cols++) {
    const rows = Math.ceil(count / cols)
    const aspect = (cols * SSS_GRID_GAP_X) / (rows * SSS_GRID_GAP_Y)
    const err = Math.abs(Math.log(aspect / SSS_TEMPLATE_ASPECT))
    if (err < bestErr) { bestErr = err; bestCols = cols }
  }
  return bestCols
}

const VANILLA_PLACEMENTS = [
  { group: 0, width: 3.1, height: 2.7, x: -16.498047, y: 15.699995, z: 1, scaleX: 1, scaleY: 1 },
  { group: 0, width: 3.1, height: 2.7, x: -16.498047, y: 10.099995, z: 0.5, scaleX: 1, scaleY: 1 },
  { group: 0, width: 3.1, height: 2.7, x: -9.8984375, y: 15.699995, z: 1, scaleX: 1, scaleY: 1 },
  { group: 0, width: 3.1, height: 2.7, x: -9.8984375, y: 10.099995, z: 0.5, scaleX: 1, scaleY: 1 },
  { group: 0, width: 3.1, height: 2.7, x: -3.2988281, y: 15.699995, z: 1, scaleX: 1, scaleY: 1 },
  { group: 0, width: 3.1, height: 2.7, x: -3.2988281, y: 10.099995, z: 0.5, scaleX: 1, scaleY: 1 },
  { group: 0, width: 3.1, height: 2.7, x: 3.2998047, y: 15.699995, z: 1, scaleX: 1, scaleY: 1 },
  { group: 0, width: 3.1, height: 2.7, x: 3.2998047, y: 10.099995, z: 0.5, scaleX: 1, scaleY: 1 },
  { group: 0, width: 3.1, height: 2.7, x: 9.899414, y: 15.699995, z: 1, scaleX: 1, scaleY: 1 },
  { group: 0, width: 3.1, height: 2.7, x: 9.899414, y: 10.099995, z: 0.5, scaleX: 1, scaleY: 1 },
  { group: 0, width: 3.1, height: 2.7, x: 16.499023, y: 15.700005, z: 1, scaleX: 1, scaleY: 1 },
  { group: 0, width: 3.1, height: 2.7, x: 16.499023, y: 10.100004, z: 0.5, scaleX: 1, scaleY: 1 },
  { group: 1, width: 3.1, height: 2.7, x: -4.5996094, y: 3.700001, z: 0.8, scaleX: 1, scaleY: 1 },
  { group: 1, width: 3.1, height: 2.7, x: -4.5996094, y: -1.8999989, z: 0.3, scaleX: 1, scaleY: 1 },
  { group: 1, width: 3.1, height: 2.7, x: 2, y: 3.700001, z: 0.8, scaleX: 1, scaleY: 1 },
  { group: 1, width: 3.1, height: 2.7, x: 2, y: -1.8999989, z: 0.3, scaleX: 1, scaleY: 1 },
  { group: 1, width: 3.1, height: 2.7, x: 8.599609, y: 3.700001, z: 0.8, scaleX: 1, scaleY: 1 },
  { group: 1, width: 3.1, height: 2.7, x: 8.599609, y: -1.8999989, z: 0.3, scaleX: 1, scaleY: 1 },
  { group: 1, width: 3.1, height: 2.7, x: 15.199219, y: 3.700001, z: 0.8, scaleX: 1, scaleY: 1 },
  { group: 1, width: 3.1, height: 2.7, x: 15.199219, y: -1.8999989, z: 0.3, scaleX: 1, scaleY: 1 },
  { group: 1, width: 3.1, height: 2.7, x: 21.799805, y: 3.699994, z: 0.8, scaleX: 1, scaleY: 1 },
  { group: 1, width: 3.1, height: 2.7, x: 21.799805, y: -1.9000058, z: 0.3, scaleX: 1, scaleY: 1 },
  { group: 0, width: 3.1, height: 2.9, x: -23.09961, y: 13.699999, z: 0.4, scaleX: 1, scaleY: 1.1 },
  { group: 0, width: 3.1, height: 2.9, x: 23.09961, y: 14, z: 0.4, scaleX: 1, scaleY: 1.1 },
  { group: 2, width: 2.9, height: 2.1, x: 1.2998047, y: -9.100002, z: 0, scaleX: 0.8, scaleY: 0.8 },
  { group: 2, width: 2.9, height: 2.1, x: 6.5996094, y: -9.100002, z: 0, scaleX: 0.8, scaleY: 0.8 },
  { group: 2, width: 2.9, height: 2.1, x: 12.299805, y: -9.100002, z: 0, scaleX: 0.8, scaleY: 0.8 },
  { group: 2, width: 2.9, height: 2.1, x: 17.59961, y: -9.100002, z: 0, scaleX: 0.8, scaleY: 0.8 },
  { group: 2, width: 2.9, height: 2.1, x: 22.899414, y: -9.100002, z: 0, scaleX: 0.8, scaleY: 0.8 },
  { group: 1, width: 3.6, height: 2.7, x: -14.099609, y: 3.599984, z: 0.4, scaleX: 1, scaleY: 1 },
]

function applyTemplate(icons, template) {
  const placements = template.iconPlacements
  return icons.map((icon, i) => {
    if (i >= placements.length) return icon
    const p = placements[i]
    return {
      ...icon,
      group: p.group,
      width: p.width,
      height: p.height,
      x: p.x,
      y: p.y,
      z: p.z,
      scaleX: p.scaleX,
      scaleY: p.scaleY
    }
  })
}

function makeTemplate(icons) {
  return {
    appearTime: 10,
    appearSpacing: 5,
    startX: 36,
    iconPlacements: icons.map(icon => ({
      group: icon.group,
      width: icon.width,
      height: icon.height,
      x: icon.x,
      y: icon.y,
      z: icon.z,
      scaleX: icon.scaleX,
      scaleY: icon.scaleY
    }))
  }
}

export default function SssLayoutEditor() {
  const [layout, setLayout] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [dirty, setDirty] = useState(false)
  const [activePage, setActivePage] = useState(0)
  const [selectedIndices, setSelectedIndices] = useState([])
  const [zoom, setZoom] = useState(8)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const [showCollision, setShowCollision] = useState(true)
  const [showOverscan, setShowOverscan] = useState(false)
  // Canvas drag behavior: 'move' (free positioning), 'swap' (exchange two
  // icons), or 'reorder' (insert an icon at another slot, shifting the rest).
  // Swap and reorder both snap to the grid template.
  const [gridMode, setGridMode] = useState('move')
  const useTemplate = gridMode !== 'move'
  const [editingPageName, setEditingPageName] = useState(null)
  const [pageNameDraft, setPageNameDraft] = useState('')
  const [propsPopup, setPropsPopup] = useState(null) // { x, y }
  const fileInputRef = useRef(null)

  // Load layout
  useEffect(() => {
    fetchLayout()
  }, [])

  const fetchLayout = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.get('/menus/sss/layout')
      setLayout(data)
      setActivePage(0)
      setSelectedIndices([])
      setDirty(false)
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
      await api.post('/menus/sss/layout', { pages: layout.pages })
      setDirty(false)
      // Re-fetch to get updated icon paths
      await fetchLayout()
    } catch (e) {
      alert(`Save failed: ${e.message}`)
    } finally {
      setSaving(false)
    }
  }

  const currentPage = layout?.pages?.[activePage]
  const currentIcons = currentPage?.icons || []

  const updateIcons = useCallback((newIcons) => {
    setLayout(prev => {
      if (!prev) return prev
      const newPages = [...prev.pages]
      newPages[activePage] = { ...newPages[activePage], icons: newIcons }
      return { ...prev, pages: newPages }
    })
    setDirty(true)
  }, [activePage])

  const updatePageTemplate = useCallback((newTemplate) => {
    setLayout(prev => {
      if (!prev) return prev
      const newPages = [...prev.pages]
      newPages[activePage] = { ...newPages[activePage], template: newTemplate }
      return { ...prev, pages: newPages }
    })
    setDirty(true)
  }, [activePage])

  const maybeApplyTemplate = useCallback((icons) => {
    if (!useTemplate || !currentPage?.template) return icons
    return applyTemplate(icons, currentPage.template)
  }, [useTemplate, currentPage?.template])

  const handleSetGridMode = useCallback((mode) => {
    setGridMode(mode)
    if (mode !== 'move' && currentPage?.template) {
      updateIcons(applyTemplate(currentIcons, currentPage.template))
    }
  }, [currentPage, currentIcons, updateIcons])

  const primaryIdx = selectedIndices.length > 0 ? selectedIndices[0] : -1

  // Icon operations
  const handleSelectionChange = useCallback((indices) => {
    setSelectedIndices(indices)
  }, [])

  const handleMoveIcon = useCallback((idx, dx, dy) => {
    const newIcons = [...currentIcons]
    newIcons[idx] = { ...newIcons[idx], x: newIcons[idx].x + dx, y: newIcons[idx].y + dy }
    updateIcons(newIcons)
  }, [currentIcons, updateIcons])

  const handleMoveIcons = useCallback((indices, dx, dy) => {
    const newIcons = [...currentIcons]
    indices.forEach(idx => {
      newIcons[idx] = { ...newIcons[idx], x: newIcons[idx].x + dx, y: newIcons[idx].y + dy }
    })
    updateIcons(newIcons)
  }, [currentIcons, updateIcons])

  const swapIcons = useCallback((icons, i, j) => {
    const a = icons[i], b = icons[j]
    icons[i] = { ...b, x: a.x, y: a.y, z: a.z, scaleX: a.scaleX, scaleY: a.scaleY,
                  width: a.width, height: a.height, group: a.group }
    icons[j] = { ...a, x: b.x, y: b.y, z: b.z, scaleX: b.scaleX, scaleY: b.scaleY,
                  width: b.width, height: b.height, group: b.group }
    return icons
  }, [])

  const handleSwapIcons = useCallback((i, j) => {
    const newIcons = [...currentIcons]
    swapIcons(newIcons, i, j)
    updateIcons(maybeApplyTemplate(newIcons))
  }, [currentIcons, updateIcons, maybeApplyTemplate, swapIcons])

  const handleUpdateIcon = useCallback((indices, updates) => {
    const newIcons = [...currentIcons]
    const idxList = Array.isArray(indices) ? indices : [indices]
    idxList.forEach(idx => { newIcons[idx] = { ...newIcons[idx], ...updates } })
    updateIcons(newIcons)
  }, [currentIcons, updateIcons])

  const handleAddIcon = useCallback(() => {
    const newIcon = {
      index: currentIcons.length,
      x: 0, y: 0, z: 0,
      scaleX: 1, scaleY: 1,
      status: 1, stageID: 0,
      stageName: 'Locked',
      group: 0,
      width: 3.1, height: 2.7,
      previewID: 0, randomSelectID: 0,
      iconPath: null, icon: null
    }
    const newIcons = maybeApplyTemplate([...currentIcons, newIcon])
    updateIcons(newIcons)
    setSelectedIndices([newIcons.length - 1])
  }, [currentIcons, updateIcons, maybeApplyTemplate])

  const handleRemoveIcon = useCallback(() => {
    if (selectedIndices.length === 0) return
    const removeSet = new Set(selectedIndices)
    const newIcons = currentIcons.filter((_, i) => !removeSet.has(i))
    const applied = maybeApplyTemplate(newIcons)
    updateIcons(applied)
    setSelectedIndices([])
  }, [currentIcons, selectedIndices, updateIcons, maybeApplyTemplate])

  const handleMoveIconUp = useCallback(() => {
    if (primaryIdx <= 0) return
    const newIcons = [...currentIcons]
    swapIcons(newIcons, primaryIdx, primaryIdx - 1)
    updateIcons(maybeApplyTemplate(newIcons))
    setSelectedIndices([primaryIdx - 1])
  }, [currentIcons, primaryIdx, updateIcons, maybeApplyTemplate, swapIcons])

  const handleMoveIconDown = useCallback(() => {
    if (primaryIdx < 0 || primaryIdx >= currentIcons.length - 1) return
    const newIcons = [...currentIcons]
    swapIcons(newIcons, primaryIdx, primaryIdx + 1)
    updateIcons(maybeApplyTemplate(newIcons))
    setSelectedIndices([primaryIdx + 1])
  }, [currentIcons, primaryIdx, updateIcons, maybeApplyTemplate, swapIcons])

  // Reorder core: pull the icon identities at `indices` out of the list and
  // re-insert them as a contiguous block before position `insertPos` in the
  // remaining list. Slot layout fields stay with their positions (re-zipped),
  // so reordering shuffles identities through fixed grid slots.
  const reorderByInsertPos = useCallback((indices, insertPos) => {
    const movingSet = new Set(indices)
    const movingSorted = [...indices].sort((a, b) => a - b)
    const moving = movingSorted.map(i => currentIcons[i])
    const remaining = currentIcons.filter((_, i) => !movingSet.has(i))
    const pos = Math.max(0, Math.min(insertPos, remaining.length))
    remaining.splice(pos, 0, ...moving)
    const slots = currentIcons.map(ic =>
      Object.fromEntries(SSS_SLOT_FIELDS.map(f => [f, ic[f]]))
    )
    const rezipped = remaining.map((ic, i) => ({ ...ic, ...slots[i] }))
    updateIcons(maybeApplyTemplate(rezipped))
    setSelectedIndices(moving.map((_, k) => pos + k))
  }, [currentIcons, updateIcons, maybeApplyTemplate])

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
    reorderByInsertPos(selectedIndices, currentIcons.length - selectedIndices.length)
  }, [selectedIndices, currentIcons.length, reorderByInsertPos])

  // Page operations
  const handleAddPage = useCallback(() => {
    if (!layout) return
    const newIcons = VANILLA_PLACEMENTS.map((p, i) => ({
      index: i, x: p.x, y: p.y, z: p.z,
      scaleX: p.scaleX, scaleY: p.scaleY,
      status: 1, stageID: 0, stageName: 'Locked',
      group: p.group, width: p.width, height: p.height,
      previewID: 0, randomSelectID: 0,
      iconPath: null, icon: null
    }))
    const newPage = {
      name: 'New Page',
      template: {
        appearTime: 10, appearSpacing: 5, startX: 36,
        iconPlacements: VANILLA_PLACEMENTS.map(p => ({ ...p }))
      },
      icons: newIcons
    }
    const newPages = [...layout.pages, newPage]
    setLayout({ ...layout, pages: newPages })
    setActivePage(newPages.length - 1)
    setSelectedIndices([])
    setDirty(true)
  }, [layout])

  const handleDeletePage = useCallback(async () => {
    if (!layout || layout.pages.length <= 1) return
    if (!await appConfirm(`Delete page "${currentPage?.name}"?`, {
      title: 'Delete Page',
      confirmText: 'Delete',
    })) return
    const newPages = layout.pages.filter((_, i) => i !== activePage)
    setLayout({ ...layout, pages: newPages })
    setActivePage(Math.min(activePage, newPages.length - 1))
    setSelectedIndices([])
    setDirty(true)
  }, [layout, activePage, currentPage])

  const handleMovePageLeft = useCallback(() => {
    if (!layout || activePage <= 0) return
    const newPages = [...layout.pages]
    const temp = newPages[activePage]
    newPages[activePage] = newPages[activePage - 1]
    newPages[activePage - 1] = temp
    setLayout({ ...layout, pages: newPages })
    setActivePage(activePage - 1)
    setDirty(true)
  }, [layout, activePage])

  const handleMovePageRight = useCallback(() => {
    if (!layout || activePage >= layout.pages.length - 1) return
    const newPages = [...layout.pages]
    const temp = newPages[activePage]
    newPages[activePage] = newPages[activePage + 1]
    newPages[activePage + 1] = temp
    setLayout({ ...layout, pages: newPages })
    setActivePage(activePage + 1)
    setDirty(true)
  }, [layout, activePage])

  const startRenamePage = (idx) => {
    setEditingPageName(idx)
    setPageNameDraft(layout.pages[idx].name)
  }

  const commitRenamePage = () => {
    if (editingPageName === null || !layout) return
    const newPages = [...layout.pages]
    newPages[editingPageName] = { ...newPages[editingPageName], name: pageNameDraft }
    setLayout({ ...layout, pages: newPages })
    setEditingPageName(null)
    setDirty(true)
  }

  // Template operations
  const handleCreateTemplate = useCallback(() => {
    if (!currentPage) return
    updatePageTemplate(makeTemplate(currentIcons))
  }, [currentPage, currentIcons, updatePageTemplate])

  const handleApplyTemplate = useCallback(() => {
    if (!currentPage?.template) return
    updateIcons(applyTemplate(currentIcons, currentPage.template))
  }, [currentPage, currentIcons, updateIcons])

  const [gridCols, setGridCols] = useState(6)

  const handleApplyGrid = useCallback((cols) => {
    if (cols <= 0) return
    setGridCols(cols)
    const count = currentIcons.length
    if (count === 0) return
    const rows = Math.ceil(count / cols)

    // Put the Random-select icon (if any) in the bottom-left slot, keeping the
    // other icons in their existing relative order around it.
    let ordered = currentIcons
    const randomIdx = currentIcons.findIndex(ic => ic.status === 3)
    if (randomIdx >= 0) {
      const arr = [...currentIcons]
      const [rnd] = arr.splice(randomIdx, 1)
      const bottomLeft = Math.min((rows - 1) * cols, arr.length)
      arr.splice(bottomLeft, 0, rnd)
      ordered = arr
    }

    const iconW = 3.1, iconH = 2.7
    const gapX = SSS_GRID_GAP_X, gapY = SSS_GRID_GAP_Y
    const totalW = (cols - 1) * gapX
    const totalH = (rows - 1) * gapY
    const startX = SSS_GRID_CENTER_X - totalW / 2
    const startY = SSS_GRID_CENTER_Y + totalH / 2

    const placements = ordered.map((icon, i) => {
      const col = i % cols
      const row = Math.floor(i / cols)
      return {
        ...icon,
        x: startX + col * gapX,
        y: startY - row * gapY,
        z: 1 - row * 0.2,
        scaleX: 1, scaleY: 1,
        width: iconW, height: iconH,
        group: Math.min(row, 2)
      }
    })

    const newTemplate = {
      appearTime: 10, appearSpacing: 5, startX: 36,
      iconPlacements: placements.map(p => ({
        group: p.group, width: p.width, height: p.height,
        x: p.x, y: p.y, z: p.z, scaleX: p.scaleX, scaleY: p.scaleY
      }))
    }
    updatePageTemplate(newTemplate)
    updateIcons(placements)
  }, [currentIcons, updatePageTemplate, updateIcons])

  const handleResetVanilla = useCallback(() => {
    const newTemplate = {
      appearTime: 10, appearSpacing: 5, startX: 36,
      iconPlacements: VANILLA_PLACEMENTS.map(p => ({ ...p }))
    }
    updatePageTemplate(newTemplate)
    const applied = applyTemplate(currentIcons, newTemplate)
    updateIcons(applied)
  }, [currentIcons, updatePageTemplate, updateIcons])

  const handleImportTemplate = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  const handleTemplateFileChange = useCallback((e) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => {
      try {
        const template = JSON.parse(ev.target.result)
        if (template.iconPlacements) {
          updatePageTemplate(template)
          if (useTemplate) {
            updateIcons(applyTemplate(currentIcons, template))
          }
        } else {
          alert('Invalid template file: missing iconPlacements')
        }
      } catch (err) {
        alert(`Failed to parse template: ${err.message}`)
      }
    }
    reader.readAsText(file)
    e.target.value = ''
  }, [updatePageTemplate, useTemplate, currentIcons, updateIcons])

  const handleExportTemplate = useCallback(() => {
    if (!currentPage?.template) return
    const json = JSON.stringify(currentPage.template, null, 2)
    const blob = new Blob([json], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'template.json'
    a.click()
    URL.revokeObjectURL(url)
  }, [currentPage])

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--color-text-muted)' }}>
        Loading SSS layout...
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ textAlign: 'center', padding: '2rem' }}>
        <p style={{ color: 'var(--color-danger)' }}>{error}</p>
        <button className="mode-btn" onClick={fetchLayout}>Retry</button>
      </div>
    )
  }

  if (!layout) return null

  const selectedIcons = selectedIndices.map(i => currentIcons[i]).filter(Boolean)

  return (
    <div className="sss-layout-editor">
      {/* Top bar: page tabs + actions */}
      <div className="sss-top-bar">
        <div className="sss-page-tabs">
          {layout.pages.map((page, idx) => (
            <div
              key={idx}
              className={`sss-page-tab ${idx === activePage ? 'active' : ''}`}
              onClick={() => { playSound('boop'); setActivePage(idx); setSelectedIndices([]) }}
              onDoubleClick={() => startRenamePage(idx)}
              onMouseEnter={playHoverSound}
            >
              {editingPageName === idx ? (
                <input
                  autoFocus
                  value={pageNameDraft}
                  onChange={(e) => setPageNameDraft(e.target.value)}
                  onBlur={commitRenamePage}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') commitRenamePage()
                    if (e.key === 'Escape') { setEditingPageName(null); setPageNameDraft('') }
                  }}
                  onClick={(e) => e.stopPropagation()}
                  style={{ width: '80px', fontSize: '0.75rem' }}
                />
              ) : (
                <span>{page.name}</span>
              )}
            </div>
          ))}
          <button
            className="sss-tab-btn"
            onClick={() => { playSound('boop'); handleAddPage() }}
            onMouseEnter={playHoverSound}
            title="Add page"
          >+</button>
        </div>

        <div className="sss-top-actions">
          {layout.pages.length > 1 && (
            <>
              <button className="sss-tab-btn" onClick={handleMovePageLeft} title="Move page left"
                disabled={activePage <= 0}>&#9664;</button>
              <button className="sss-tab-btn" onClick={handleMovePageRight} title="Move page right"
                disabled={activePage >= layout.pages.length - 1}>&#9654;</button>
              <button className="sss-tab-btn" onClick={handleDeletePage} title="Delete page"
                style={{ color: 'var(--color-danger)' }}>&#10005;</button>
            </>
          )}
          <button
            className="sss-tab-btn"
            onClick={fetchLayout}
            onMouseEnter={playHoverSound}
            title="Reload"
          >&#8635;</button>
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
        {/* Canvas */}
        <SssCanvas
          icons={currentIcons}
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
          fitToView
        />

        {/* Right panel: icon list only */}
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

          {currentIcons.some(ic => ic.status === SSS_STATUS_LOCKED) && (
            <div className="sss-slot-hint">Right-click a Locked slot to pick its stage.</div>
          )}

          <div className="sss-icon-list-header">
            <span>Icons ({currentIcons.length})</span>
            <div className="sss-reorder-btns">
              <button onClick={handleMoveIconsToTop} title="Move to top" disabled={primaryIdx <= 0}>&#8607;</button>
              <button onClick={handleMoveIconUp} title="Move up" disabled={primaryIdx <= 0}>&#9650;</button>
              <button onClick={handleMoveIconDown} title="Move down"
                disabled={primaryIdx < 0 || primaryIdx >= currentIcons.length - 1}>&#9660;</button>
              <button onClick={handleMoveIconsToBottom} title="Move to bottom"
                disabled={primaryIdx < 0 || primaryIdx >= currentIcons.length - 1}>&#8609;</button>
            </div>
          </div>
          <IconReorderList
            icons={currentIcons}
            selectedIndices={selectedIndices}
            onSelect={setSelectedIndices}
            onContextMenu={(x, y) => setPropsPopup({ x, y })}
            onReorder={handleReorderIcon}
            onReorderBulk={handleReorderIcons}
            getLabel={(icon) => icon.stageName || STATUS_LABELS[icon.status] || '?'}
            getIconUrl={(icon) => icon.iconPath
              ? backendMediaUrl(`${API_URL}/menus/sss/stage-icon?path=${encodeURIComponent(icon.iconPath)}`)
              : null}
          />
        </div>

        {/* Properties popup */}
        {propsPopup && selectedIcons.length > 0 && (
          <PropsPopup x={propsPopup.x} y={propsPopup.y} onClose={() => setPropsPopup(null)}>
            <SssIconProperties
              icons={selectedIcons}
              indices={selectedIndices}
              stages={layout.stages || []}
              pages={layout.pages}
              onUpdate={handleUpdateIcon}
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
              onClick={() => { playSound('tick'); handleApplyGrid(Math.max(1, gridCols - 1)) }}
              disabled={gridCols <= 1}
              title="Fewer columns"
            >−</button>
            <input type="number" min={1} max={20}
              value={gridCols}
              onChange={(e) => handleApplyGrid(Math.max(1, Math.min(20, parseInt(e.target.value) || 1)))} />
            <button
              onClick={() => { playSound('tick'); handleApplyGrid(Math.min(20, gridCols + 1)) }}
              disabled={gridCols >= 20}
              title="More columns"
            >+</button>
          </div>
          <span className="sss-grid-dim">
            ({Math.ceil(currentIcons.length / gridCols)} rows)
          </span>
          <button
            className="sss-tab-btn"
            onClick={() => { playSound('boop'); handleApplyGrid(pickSssAutoColumns(currentIcons.length)) }}
            title="Auto-fit columns and rows to the icon count"
          >Auto</button>
          <button className="sss-tab-btn" onClick={handleResetVanilla}>Reset</button>
        </div>
        <div className="sss-bottom-group">
          <label>Zoom: {zoom}x</label>
          <input
            type="range" min={4} max={20} value={zoom}
            onChange={(e) => setZoom(parseInt(e.target.value))}
            style={{ width: '80px' }}
          />
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
        <div className="sss-bottom-group" style={{ marginLeft: 'auto' }}>
          <button className="sss-tab-btn" onClick={handleImportTemplate} title="Import template JSON">Import</button>
          <button className="sss-tab-btn" onClick={handleExportTemplate} title="Export template JSON">Export</button>
        </div>
      </div>

      {/* Hidden file input for template import */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".json"
        style={{ display: 'none' }}
        onChange={handleTemplateFileChange}
      />
    </div>
  )
}
